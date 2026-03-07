"""Destination CRUD + manual publish + autopublish status routes."""
import datetime
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from services.storage import storage_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────
#  CRUD
# ─────────────────────────────────────────────

@router.get("/destinations", response_model=List[schemas.UploadPostDestinationResponse])
async def get_all_destinations(db: Session = Depends(get_db)):
    """Получить все направления (профили) публикации."""
    return db.query(models.UploadPostDestination).order_by(models.UploadPostDestination.id).all()


@router.post("/destinations", response_model=schemas.UploadPostDestinationResponse)
async def create_destination(req: schemas.UploadPostDestinationCreate, db: Session = Depends(get_db)):
    """Создать новое направление публикации."""
    dest = models.UploadPostDestination(**req.dict())
    db.add(dest)
    db.commit()
    db.refresh(dest)
    return dest


@router.put("/destinations/{dest_id}", response_model=schemas.UploadPostDestinationResponse)
async def update_destination(dest_id: int, req: schemas.UploadPostDestinationCreate, db: Session = Depends(get_db)):
    """Обновить существующее направление."""
    dest = db.query(models.UploadPostDestination).get(dest_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    for key, value in req.dict().items():
        setattr(dest, key, value)

    db.commit()
    db.refresh(dest)
    return dest


@router.delete("/destinations/{dest_id}")
async def delete_destination(dest_id: int, db: Session = Depends(get_db)):
    """Удалить направление."""
    dest = db.query(models.UploadPostDestination).get(dest_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    db.delete(dest)
    db.commit()
    return {"success": True}


# ─────────────────────────────────────────────
#  Manual publish
# ─────────────────────────────────────────────

@router.post("/destinations/{dest_id}/publish-now/{video_id}")
async def publish_video_now(dest_id: int, video_id: int, db: Session = Depends(get_db)):
    """Ручная публикация КОНКРЕТНОГО видео в КОНКРЕТНОЕ направление."""
    from services.uploadpost import uploadpost_service
    from services.scheduler import _resolve_video_url
    from services.telegram_sender import send_video_to_telegram
    import os

    video = db.query(models.Video).get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if video.status != "merged":
        raise HTTPException(status_code=400, detail="Video is not ready (status must be 'merged')")

    dest = db.query(models.UploadPostDestination).get(dest_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    platforms = dest.platforms or []
    if not platforms:
        raise HTTPException(status_code=400, detail="No platforms configured for this destination.")

    video_url = _resolve_video_url(video, storage_service)
    if not video_url:
        raise HTTPException(status_code=400, detail="No video URL available")

    if dest.publish_mode == "telegram":
        bot_token = dest.telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = dest.telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        result = await send_video_to_telegram(
            bot_token=bot_token,
            chat_id=chat_id,
            video_url=video_url,
            caption=video.description or f"Video {video.tiktok_id}"
        )
    else:
        result = await uploadpost_service.publish_video(
            api_key=None,
            uploadpost_profile=(dest.uploadpost_profiles or [""])[0],
            video_url=video_url,
            title=video.script[:80] if video.script else f"Video {video.tiktok_id}",
            description=video.description,
            platforms=platforms,
            tiktok_privacy=dest.tiktok_privacy,
            youtube_privacy=dest.youtube_privacy,
            youtube_category_id=dest.youtube_category_id,
            instagram_media_type=dest.instagram_media_type,
        )

    if result.get("success"):
        pub_log = models.VideoPublishLog(
            video_id=video.id,
            destination_id=dest.id,
            status="published",
            published_at=datetime.datetime.utcnow(),
        )
        db.add(pub_log)
        db.commit()

    return result


# ─────────────────────────────────────────────
#  Autopublish helpers
# ─────────────────────────────────────────────

@router.get("/autopublish/validate-key")
async def validate_uploadpost_key(api_key: str):
    """Проверить валидность Upload-Post API ключа."""
    from services.uploadpost import uploadpost_service
    return await uploadpost_service.get_account_info(api_key)


@router.get("/autopublish/status")
async def get_autopublish_env_status():
    """Статус системы автопубликации: активна через ENV или нет."""
    from services.uploadpost import get_env_status
    return get_env_status()


@router.get("/autopublish/profiles")
async def get_uploadpost_profiles():
    """Получить список user profiles из Upload-Post API (используя ключ из ENV)."""
    from services.uploadpost import uploadpost_service
    return await uploadpost_service.get_user_profiles()
