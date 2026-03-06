"""Video download helper with retry logic for TikTok CDN."""
import asyncio
import logging
import httpx

logger = logging.getLogger(__name__)

TIKTOK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.0 Mobile/15E148 Safari/604.1"
    ),
    "Referer": "https://www.tiktok.com/",
}

MIN_FILE_SIZE = 10_000  # 10KB — anything smaller is broken


async def download_video(url: str, dest_path: str, retries: int = 3) -> int:
    """
    Download a video from *url* to *dest_path* with retry logic.

    Returns the size of the downloaded file in bytes.
    Raises ``Exception`` if all attempts fail.
    """
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=30.0, read=120.0, write=30.0),
                follow_redirects=True,
                headers=TIKTOK_HEADERS,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

                if len(resp.content) < MIN_FILE_SIZE:
                    raise ValueError(
                        f"Downloaded file too small: {len(resp.content)} bytes"
                    )

                with open(dest_path, "wb") as f:
                    f.write(resp.content)

            size = len(resp.content)
            logger.info(
                "Downloaded %dKB (attempt %d/%d)", size // 1024, attempt + 1, retries
            )
            return size

        except Exception as err:
            logger.warning("Attempt %d/%d failed: %s", attempt + 1, retries, err)
            if attempt == retries - 1:
                raise Exception(
                    f"Failed to download after {retries} attempts: {err}"
                ) from err
            await asyncio.sleep(2)

    # Unreachable but keeps type-checkers happy
    raise Exception("Download failed")
