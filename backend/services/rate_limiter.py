"""
Rate Limiter & Retry Logic for Gemini / Vertex AI API
======================================================
- Token-bucket rate limiter: ensures we stay under RPM quota
- Exponential backoff retry: handles 429 / 500 / transient errors
- Campaign semaphore: limits concurrent campaign processing
"""
import asyncio
import time
import random
import logging
import functools

logger = logging.getLogger(__name__)

# ── Rate Limiter (token-bucket) ──────────────────────────────
class RateLimiter:
    """
    Simple async token-bucket rate limiter.
    Default: 100 requests per 60 seconds (safe margin under 200 RPM Vertex limit).
    """

    def __init__(self, max_calls: int = 100, period_seconds: float = 60.0):
        self.max_calls = max_calls
        self.period = period_seconds
        self._tokens = max_calls
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a token is available, then consume it."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                # Calculate wait time until next token
                wait = self.period / self.max_calls
            logger.debug("[RateLimiter] Throttled — waiting %.1fs", wait)
            await asyncio.sleep(wait)

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * (self.max_calls / self.period)
        self._tokens = min(self.max_calls, self._tokens + new_tokens)
        self._last_refill = now


# Global instances
gemini_rate_limiter = RateLimiter(max_calls=100, period_seconds=60)

# Campaign concurrency: max 1 campaign at a time (sequential processing)
campaign_semaphore = asyncio.Semaphore(1)


# ── Retry with exponential backoff ───────────────────────────
RETRYABLE_STATUS_CODES = {"429", "500", "503", "RESOURCE_EXHAUSTED"}


def is_retryable(error: Exception) -> bool:
    """Check if the error is transient and worth retrying."""
    msg = str(error).lower()
    for code in RETRYABLE_STATUS_CODES:
        if code.lower() in msg:
            return True
    # google-genai specific errors
    if "quota" in msg or "rate" in msg or "too many" in msg or "unavailable" in msg:
        return True
    return False


async def retry_with_backoff(
    func,
    *args,
    max_retries: int = 5,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    rate_limiter: RateLimiter | None = None,
    **kwargs,
):
    """
    Call an async or sync function with exponential backoff + jitter on retryable errors.
    Optionally rate-limits via the provided RateLimiter before each attempt.
    """
    last_exception = None

    for attempt in range(1, max_retries + 1):
        try:
            # Rate limit
            if rate_limiter:
                await rate_limiter.acquire()

            # Call function
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            return result

        except Exception as e:
            last_exception = e
            if not is_retryable(e) or attempt == max_retries:
                logger.error(
                    "[Retry] Non-retryable or max retries reached (attempt %d/%d): %s",
                    attempt, max_retries, str(e)[:200],
                )
                raise

            # Exponential backoff with jitter
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            jitter = random.uniform(0, delay * 0.3)
            total_delay = delay + jitter
            logger.warning(
                "[Retry] Attempt %d/%d failed (%s). Retrying in %.1fs...",
                attempt, max_retries, str(e)[:100], total_delay,
            )
            await asyncio.sleep(total_delay)

    raise last_exception  # Should never reach here, but just in case
