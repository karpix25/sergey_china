"""
Telegram Sender — отправляет видео и описание в Telegram через Bot API.
Использует httpx для HTTP-запросов (без внешних зависимостей).
"""
import httpx
import logging
import tempfile
import os

logger = logging.getLogger(__name__)


async def send_video_to_telegram(
    bot_token: str,
    chat_id: str,
    video_url: str,
    caption: str = "",
) -> dict:
    """
    Скачивает видео по URL и отправляет в Telegram чат.
    
    Returns: {"success": True} или {"success": False, "error": "..."}
    """
    if not bot_token or not chat_id:
        return {"success": False, "error": "Telegram bot_token или chat_id не настроены"}

    tmp_path = None
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            # 1. Скачать видео
            logger.info("[Telegram] Downloading video from %s...", video_url[:80])
            resp = await client.get(video_url, follow_redirects=True)
            resp.raise_for_status()

            # Сохранить во временный файл
            suffix = ".mp4"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(resp.content)
            tmp_path = tmp.name
            tmp.close()

            file_size = os.path.getsize(tmp_path)
            logger.info("[Telegram] Downloaded %.1f MB, sending to chat %s...", file_size / 1024 / 1024, chat_id)

            # Ограничение Telegram Bot API: 50MB для видео
            if file_size > 50 * 1024 * 1024:
                return {"success": False, "error": f"Видео слишком большое ({file_size // 1024 // 1024}MB > 50MB)"}

            # 2. Отправить через Telegram Bot API
            url = f"https://api.telegram.org/bot{bot_token}/sendVideo"
            
            # Обрезать caption до 1024 символов (лимит Telegram)
            safe_caption = (caption or "")[:1024]

            with open(tmp_path, "rb") as vf:
                files = {"video": ("video.mp4", vf, "video/mp4")}
                data = {
                    "chat_id": chat_id,
                    "caption": safe_caption,
                    "parse_mode": "HTML",
                }
                tg_resp = await client.post(url, data=data, files=files, timeout=120)

            result = tg_resp.json()

            if result.get("ok"):
                logger.info("[Telegram] ✅ Video sent to chat %s", chat_id)
                return {"success": True, "message_id": result.get("result", {}).get("message_id")}
            else:
                error_msg = result.get("description", "Unknown Telegram error")
                logger.error("[Telegram] ❌ Failed: %s", error_msg)
                return {"success": False, "error": error_msg}

    except httpx.HTTPStatusError as e:
        logger.error("[Telegram] HTTP error downloading video: %s", e)
        return {"success": False, "error": f"Ошибка скачивания видео: {e.response.status_code}"}
    except Exception as e:
        logger.exception("[Telegram] Unexpected error: %s", e)
        return {"success": False, "error": str(e)}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
