"""Video CRUD routes — status, list, delete, upload."""
import asyncio
import logging
import os
import shutil
import uuid as _uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

import models
import schemas
from database import SessionLocal, get_db
from helpers.thumbnails import extract_and_upload_thumbnail
from helpers.cleanup import cleanup_local_files
from services.analysis import analysis_service
from services.audio import audio_service
from services.storage import storage_service
from services.subtitles import subtitle_service
from services.video import video_processor
from helpers.auth import get_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos")

# ── Processing queue: max 2 concurrent video processing tasks ──
_processing_semaphore = asyncio.Semaphore(2)


# ─────────────────────────────────────────────
#  READ / UPDATE / DELETE
# ─────────────────────────────────────────────

@router.get("/video_status/{video_id}")
async def get_video_status(video_id: int, db: Session = Depends(get_db)):
    video = db.query(models.Video).get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"status": video.status, "processed_video_path": video.processed_video_path}


@router.get("", response_model=List[schemas.VideoResponse])
async def list_videos(db: Session = Depends(get_db)):
    return db.query(models.Video).order_by(models.Video.created_at.desc()).all()


@router.delete("/all")
async def delete_all_videos(db: Session = Depends(get_db)):
    try:
        db.query(models.ActivityLog).filter(
            models.ActivityLog.video_id != None  # noqa: E711
        ).delete(synchronize_session=False)
        count = db.query(models.Video).delete(synchronize_session=False)
        db.commit()
        return {"message": f"Deleted {count} videos"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{video_id}/status")
async def update_video_status(video_id: int, body: dict, db: Session = Depends(get_db)):
    """
    Вручную изменить статус видео.
    Body:
      - status: str (optional) — pipeline status: merged, failed, pending, etc.
      - publish_status: str|null (optional) — published, failed, или null (вернуть в очередь)
    """
    import datetime

    video = db.query(models.Video).get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if "status" in body:
        video.status = body["status"]
    if "publish_status" in body:
        new_ps = body["publish_status"]
        video.publish_status = new_ps
        if new_ps == "published" and not video.published_at:
            video.published_at = datetime.datetime.utcnow()
        if new_ps is None:
            video.published_at = None

    db.commit()
    db.refresh(video)
    return {
        "id": video.id,
        "status": video.status,
        "publish_status": video.publish_status,
        "published_at": video.published_at.isoformat() if video.published_at else None,
    }

@router.patch("/bulk-update-description")
async def bulk_update_description(
    body: schemas.VideoBulkDescriptionUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Массово обновить описание для всех НЕОПУБЛИКОВАННЫХ видео.
    Теперь каждое описание перегенерируется через AI с учетом скрипта видео и нового шаблона.
    """
    assigned_ids = db.query(models.VideoPublishLog.video_id)
    videos = (
        db.query(models.Video)
        .filter(
            models.Video.status == "merged",
            ~models.Video.id.in_(assigned_ids),
            (models.Video.publish_status != "published") | (models.Video.publish_status == None)
        )
        .all()
    )

    if not videos:
        return {"message": "Нет готовых видео для обновления"}

    video_ids = [v.id for v in videos]
    background_tasks.add_task(_run_bulk_description_update, video_ids, body.description)

    return {"message": f"Запущено фоновое обновление описаний для {len(videos)} видео. Это займет некоторое время."}


async def _run_bulk_description_update(video_ids: List[int], new_base_description: str):
    """Фоновая задача для AI-адаптации описаний."""
    db = SessionLocal()
    try:
        from helpers.logging import log_activity
        from services.analysis import analysis_service

        for vid in video_ids:
            video = db.query(models.Video).get(vid)
            if not video or not video.script:
                continue

            try:
                new_desc = await analysis_service.generate_adapted_description(
                    video.script, new_base_description, video.product_info or ""
                )
                video.description = new_desc
                db.commit()
                log_activity(db, video.profile_id, f"Описание видео {video.tiktok_id} обновлено через AI", "info", video_id=video.id)
            except Exception as e:
                logger.error("Failed to update description for video %d: %s", vid, e)

    finally:
        db.close()


# ─────────────────────────────────────────────
#  UPLOAD OWN VIDEO
# ─────────────────────────────────────────────

@router.post("/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    files: List[UploadFile] = File(...),
    profile: str = "default",
    mode: str = "raw",  # raw | overlay | full
):
    """
    Загрузить одно или несколько видео (массовая загрузка).
    mode:
      raw     — сохранить as-is, готово к публикации
      overlay — наложить плашку CTA, оригинальный звук
      full    — анализ Gemini + озвучка + плашка
    """
    if mode not in ("raw", "overlay", "full"):
        raise HTTPException(status_code=400, detail="mode must be raw | overlay | full")

    profile_obj = db.query(models.Profile).filter(
        models.Profile.username == profile.lower()
    ).first()
    if not profile_obj:
        profile_obj = models.Profile(username=profile.lower())
        db.add(profile_obj)
        db.commit()
        db.refresh(profile_obj)

    os.makedirs("tmp/uploads", exist_ok=True)

    results = []
    for file in files:
        unique_id = f"upload_{_uuid.uuid4().hex[:8]}"
        ext = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
        local_path = f"tmp/uploads/{unique_id}{ext}"
        with open(local_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        video = models.Video(
            tiktok_id=unique_id,
            profile_id=profile_obj.id,
            url=local_path,
            status="queued",
            source="upload",
            processing_mode=mode,
        )
        db.add(video)
        db.commit()
        db.refresh(video)

        background_tasks.add_task(_queued_process, video.id, local_path, mode)
        results.append({"id": video.id, "filename": file.filename, "status": "queued", "mode": mode})

    return {"count": len(results), "videos": results}


# ─────────────────────────────────────────────
#  Background processing
# ─────────────────────────────────────────────

async def _queued_process(video_id: int, local_path: str, mode: str):
    """Wrapper that acquires the semaphore before processing (max 2 concurrent)."""
    async with _processing_semaphore:
        await process_uploaded_video(video_id, local_path, mode)


async def process_uploaded_video(
    video_id: int,
    local_path: str,
    mode: str,
    enable_subtitles: bool = True,
    subtitle_style: dict = None,
    overlay_settings: dict = None,
):
    """Фоновая задача обработки загруженного видео в зависимости от режима."""
    db = SessionLocal()
    try:
        video = db.query(models.Video).get(video_id)
        if not video:
            return

        # Upload original to GCS
        gcs_raw = storage_service.upload_from_filename(local_path, f"uploads/{video.tiktok_id}_raw.mp4")
        video.gcs_path = gcs_raw

        # Thumbnail
        thumb_url = extract_and_upload_thumbnail(local_path, video.tiktok_id)
        if thumb_url:
            video.thumbnail_url = thumb_url

        if mode == "raw":
            video.local_video_path = local_path
            video.status = "merged"
            video.description = os.path.basename(local_path)
            db.commit()
            logger.info("[Upload] Video %d ready (raw)", video_id)
            return

        if mode == "overlay":
            cta = video_processor.get_random_cta()
            processed = (
                video_processor.overlay_only(local_path, cta, overlay_settings=overlay_settings)
                if cta
                else local_path
            )
            gcs_proc = storage_service.upload_from_filename(processed, f"processed/{video.tiktok_id}.mp4")
            video.processed_video_path = gcs_proc
            video.local_video_path = processed
            video.status = "merged"
            video.description = os.path.basename(local_path)
            db.commit()
            logger.info("[Upload] Video %d ready (overlay)", video_id)
            return

        if mode == "full":
            video.status = "downloaded"
            db.commit()

            script, is_product, duration = None, None, None
            try:
                result = await analysis_service.analyze_video(video.gcs_path or local_path)
                script = result.get("script")
                is_product = result.get("is_product")
                duration = result.get("detected_duration")
                product_summary = result.get("product_summary", "")
                
                video.script = script
                video.is_product = is_product
                video.duration = duration
                video.product_info = product_summary
                video.status = "analyzed"
                db.commit()
            except Exception as e:
                logger.error("[Upload] Analysis failed: %s", e)

            audio_path = None
            srt_path = None
            if script:
                try:
                    if enable_subtitles:
                        audio_path, alignment = audio_service.generate_speech_with_timestamps(script)
                        wpc = video_processor.get_words_per_chunk(subtitle_style)
                        srt_content = subtitle_service.alignments_to_srt(alignment, words_per_chunk=wpc)
                        srt_path = audio_path.replace(".mp3", ".srt")
                        subtitle_service.save_srt(srt_content, srt_path)
                        
                        # Upload for future UI updates
                        video.voice_gcs_path = storage_service.upload_from_filename(audio_path, f"audio/{video.tiktok_id}.mp3")
                        video.srt_gcs_path = storage_service.upload_from_filename(srt_path, f"srt/{video.tiktok_id}.srt")
                    else:
                        audio_path = audio_service.generate_speech(script)
                        video.voice_gcs_path = storage_service.upload_from_filename(audio_path, f"audio/{video.tiktok_id}.mp3")
                        video.srt_gcs_path = None

                    video.status = "voiced"
                    db.commit()
                except Exception as e:
                    logger.error("[Upload] Audio generation failed: %s", e)

            try:
                cta = video_processor.get_random_cta()
                if audio_path:
                    processed = video_processor.merge_audio_and_overlay(
                        local_path, audio_path, overlay_path=cta,
                        target_duration=duration, subtitles_path=srt_path,
                        subtitle_style=subtitle_style, overlay_settings=overlay_settings,
                    )
                elif cta:
                    processed = video_processor.overlay_only(local_path, cta, overlay_settings=overlay_settings)
                else:
                    processed = local_path

                gcs_proc = storage_service.upload_from_filename(processed, f"processed/{video.tiktok_id}.mp4")
                video.processed_video_path = gcs_proc
                video.local_video_path = None
                video.status = "merged"
                db.commit()
                
                # Cleanup local files
                cleanup_local_files(processed, local_path, audio_path, srt_path)
                
                logger.info("[Upload] Video %d ready (full)", video_id)
            except Exception as e:
                logger.error("[Upload] Merge failed: %s", e)
                video.status = "failed"
                db.commit()

    except Exception as e:
        logger.error("[Upload] process_uploaded_video error: %s", e)
        try:
            video = db.query(models.Video).get(video_id)
            if video:
                video.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()

@router.post("/bulk-update-style")
async def bulk_update_style(
    update: schemas.VideoBulkDesignUpdate,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key)
):
    """Массовое обновление дизайна (субтитры, плашки) для существующих видео."""
    background_tasks.add_task(
        update.video_ids, 
        update.subtitle_style,
        update.overlay_id,
        update.overlay_settings
    )
    return {"message": f"Запущено обновление дизайна для {len(update.video_ids)} видео"}

async def _run_bulk_design_update(video_ids: List[int], subtitle_style: dict, overlay_id: int, overlay_settings: Optional[dict] = None):
    """Фоновая задача для пересборки видео с новым дизайном."""
    db = SessionLocal()
    try:
        from services.storage import storage_service
        from services.video import video_processor
        from helpers.logging import log_activity

        overlay = None
        if overlay_id:
            overlay = db.query(models.Overlay).get(overlay_id)

        for vid in video_ids:
            video = db.query(models.Video).get(vid)
            # We need both raw video and voiceover to re-render
            if not video or not video.gcs_path or not video.voice_gcs_path:
                logger.warning("Skipping bulk design update for video %s: Missing GCS assets", vid)
                continue

            try:
                logger.info("Re-rendering video %s with new design", video.tiktok_id)
                # 1. Download necessary assets
                local_raw = storage_service.download_to_local(video.gcs_path)
                local_audio = storage_service.download_to_local(video.voice_gcs_path)
                local_srt = None
                if video.srt_gcs_path:
                    local_srt = storage_service.download_to_local(video.srt_gcs_path)

                # 2. Re-merge with new style
                final_local = video_processor.merge_audio_and_overlay(
                    video_path=local_raw,
                    audio_path=local_audio,
                    subtitles_path=local_srt,
                    subtitle_style=subtitle_style,
                    overlay_path=overlay.file_path if overlay else None,
                    target_duration=video.duration,
                    overlay_settings=overlay_settings
                )

                # 3. Upload new version
                video.processed_video_path = storage_service.upload_from_filename(
                    final_local, f"processed/{video.tiktok_id}.mp4"
                )
                video.status = "merged"
                db.commit()
                
                log_activity(db, video.profile_id, f"Дизайн видео {video.tiktok_id} обновлен", "success", video_id=video.id)
                
                # Cleanup
                cleanup_local_files(local_raw, local_audio, final_local, local_srt)

            except Exception as e:
                logger.error("Failed to update design for video %d: %s", vid, e)
                log_activity(db, video.profile_id, f"Ошибка обновления дизайна {video.tiktok_id}: {str(e)}", "error", video_id=video.id)

    finally:
        db.close()
