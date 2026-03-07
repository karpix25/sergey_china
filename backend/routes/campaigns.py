"""Campaign creation and background processing routes."""
import asyncio
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

import models
import schemas
from database import SessionLocal, get_db
from helpers.download import download_video
from helpers.cleanup import cleanup_local_files
from helpers.logging import log_activity
from helpers.thumbnails import extract_and_upload_thumbnail
from services.analysis import analysis_service
from services.audio import audio_service
from services.rate_limiter import campaign_semaphore
from services.scraper import scraper_service
from services.storage import storage_service
from services.subtitles import subtitle_service
from services.video import video_processor

logger = logging.getLogger(__name__)

router = APIRouter()

# Global set to track currently processing profiles to prevent duplicates
processing_profiles: set[str] = set()


@router.post("/campaigns", response_model=schemas.CampaignResponse)
async def create_campaign(
    req: schemas.CampaignCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    username = req.username.replace("@", "").lower()
    logger.info("Creating campaign for %s", username)

    if username in processing_profiles:
        return {"message": "Campaign already in progress for this profile", "profile_id": 0}

    profile = db.query(models.Profile).filter(models.Profile.username == username).first()
    if not profile:
        profile = models.Profile(username=username)
        db.add(profile)
        db.commit()
        db.refresh(profile)

    processing_profiles.add(username)

    from tasks import process_campaign_task
    process_campaign_task.delay(
        profile.id, req.video_count, req.base_description,
        req.enable_subtitles, req.subtitle_style, req.overlay_settings,
        req.audio_settings,
    )
    return {"message": "Campaign started", "profile_id": profile.id}
