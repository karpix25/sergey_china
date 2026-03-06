"""Telegram test routes — send test message and test video."""
import logging
import os

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import models
from database import get_db
from services.storage import storage_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_telegram_credentials() -> tuple[str, str]:
    """Return (bot_token, chat_id) from environment."""
    return (
        os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        os.environ.get("TELEGRAM_CHAT_ID", ""),
    )


@router.post("/telegram/test")
async def test_telegram():
    """Отправить тестовое сообщение в Telegram для проверки настроек."""
    bot_token, chat_id = _get_telegram_credentials()
    if not bot_token or not chat_id:
        return {"success": False, "error": "TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы в .env"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": "🎬 Тестовое сообщение от планировщика.\nTelegram интеграция работает! ✅",
                "parse_mode": "HTML",
            })
            result = resp.json()

            if result.get("ok"):
                return {"success": True, "message_id": result["result"]["message_id"]}
            return {"success": False, "error": result.get("description", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/telegram/test-video/{video_id}")
async def test_telegram_video(video_id: int, db: Session = Depends(get_db)):
    """Отправить конкретное видео из БД в Telegram для тестирования."""
    from services.telegram_sender import send_video_to_telegram

    bot_token, chat_id = _get_telegram_credentials()
    if not bot_token or not chat_id:
        return {"success": False, "error": "TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы в .env"}

    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        return {"success": False, "error": f"Видео {video_id} не найдено"}

    # Resolve video URL
    video_url = None
    for path in [video.processed_video_path, video.gcs_path]:
        if path and path.startswith("gs://"):
            parts = path.replace("gs://", "").split("/", 1)
            if len(parts) == 2:
                blob_name = parts[1]
                video_url = storage_service.generate_signed_url(blob_name)
                if video_url:
                    break

    if not video_url:
        return {"success": False, "error": f"Не удалось получить URL для видео {video_id}"}

    caption = f"📹 <b>{video.tiktok_id}</b>\n\n{video.description or 'Без описания'}"

    return await send_video_to_telegram(
        bot_token=bot_token,
        chat_id=chat_id,
        video_url=video_url,
        caption=caption,
    )
