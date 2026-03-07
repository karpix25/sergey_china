import os
import uuid
import logging
from typing import List, Optional
from celery_app import celery_app
from database import SessionLocal
import models
from services.scraper import scraper_service
from services.storage import storage_service
from services.analysis import analysis_service
from services.audio import audio_service
from services.video import video_processor
from services.subtitles import subtitle_service
from helpers.download import download_video
from helpers.thumbnails import extract_and_upload_thumbnail
from helpers.logging import log_activity
from helpers.cleanup import cleanup_local_files
import asyncio

logger = logging.getLogger(__name__)

def run_async(coro):
    """Helper to run async functions in sync Celery tasks."""
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # This shouldn't happen in a standard Celery worker thread
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    else:
        return loop.run_until_complete(coro)

@celery_app.task(name="tasks.process_campaign")
def process_campaign_task(
    profile_id: int,
    count: int,
    base_description: str = None,
    enable_subtitles: bool = True,
    subtitle_style: dict = None,
    overlay_settings: dict = None,
    audio_settings: dict = None
):
    """Celery task for campaign processing."""
    db = SessionLocal()
    profile_username = None
    try:
        profile = db.query(models.Profile).get(profile_id)
        if not profile:
            logger.error("Celery Task Error: Profile %d not found", profile_id)
            return

        profile_username = profile.username.lower()
        logger.info("━" * 60)
        logger.info("  🚀 Celery Кампания: @%s (лимит: %d видео)", profile.username, count)
        logger.info("━" * 60)
        log_activity(db, profile_id, f"Celery: Запуск кампании для @{profile.username} (лимит: {count} видео)", "info")

        # Fetch videos from scraper (Async)
        videos_data = run_async(scraper_service.fetch_profile_videos(profile.username, count))
        logger.info("Scraper returned %d videos for @%s", len(videos_data), profile.username)

        for v_data in videos_data:
            # Check if already processed
            existing = db.query(models.Video).filter(models.Video.tiktok_id == v_data["id"]).first()
            if existing:
                if existing.status == "merged":
                    logger.info("Video %s already merged, skipping.", v_data["id"])
                    log_activity(db, profile_id, f"Пропуск {v_data['id']}: уже обработано", "skip", video_id=existing.id)
                    continue
                else:
                    video = existing
            else:
                video = models.Video(
                    tiktok_id=v_data["id"],
                    profile_id=profile_id,
                    url=v_data["download_url"],
                    thumbnail_url=v_data.get("thumbnail_url"),
                    status="pending",
                )
                db.add(video)
                db.commit()
                db.refresh(video)
                log_activity(db, profile_id, f"Найдено новое видео: {v_data['id']}", "success", video_id=video.id)

            logger.info("  ▶ Видео: %s", video.tiktok_id)
            log_activity(db, profile_id, f"Начало обработки видео {video.tiktok_id}", "info", video_id=video.id)

            try:
                # Download
                local_raw_path = f"tmp/{video.tiktok_id}.mp4"
                os.makedirs("tmp", exist_ok=True)
                run_async(download_video(video.url, local_raw_path))

                # Upload raw to GCS
                gcs_uri = storage_service.upload_from_filename(local_raw_path, f"raw/{video.tiktok_id}.mp4")
                video.gcs_path = gcs_uri
                video.status = "downloaded"
                db.commit()

                # Thumbnail
                thumb_url = extract_and_upload_thumbnail(local_raw_path, video.tiktok_id)
                if thumb_url:
                    video.thumbnail_url = thumb_url
                    db.commit()

                # Analyze with Gemini (Async)
                analysis = run_async(analysis_service.analyze_video(gcs_uri))
                video.is_product = analysis["is_product"]
                video.duration = analysis["detected_duration"]
                video.script = analysis["script"]
                video.product_info = analysis.get("product_summary", "")
                db.commit()

                if not video.is_product:
                    video.status = "skipped (no product)"
                    db.commit()
                    continue

                # Adapted description (Async)
                if base_description:
                    video.description = run_async(analysis_service.generate_adapted_description(
                        video.script, base_description, video.product_info
                    ))
                    db.commit()

                # Voiceover + sync loop
                sync_achieved = False
                retry_count = 0
                max_retries = 2
                current_script = video.script
                video_dur = video.duration

                while not sync_achieved and retry_count <= max_retries:
                    if enable_subtitles:
                        audio_path, alignment = audio_service.generate_speech_with_timestamps(current_script)
                        wpc = video_processor.get_words_per_chunk(subtitle_style)
                        srt_content = subtitle_service.alignments_to_srt(alignment, words_per_chunk=wpc)
                        srt_path = audio_path.replace(".mp3", ".srt")
                        subtitle_service.save_srt(srt_content, srt_path)
                        
                        video.voice_gcs_path = storage_service.upload_from_filename(audio_path, f"audio/{video.tiktok_id}.mp3")
                        video.srt_gcs_path = storage_service.upload_from_filename(srt_path, f"srt/{video.tiktok_id}.srt")
                        db.commit()
                    else:
                        audio_path = audio_service.generate_speech(current_script)
                        video.voice_gcs_path = storage_service.upload_from_filename(audio_path, f"audio/{video.tiktok_id}.mp3")
                        video.srt_gcs_path = None
                        db.commit()
                        srt_path = None

                    audio_dur = audio_service.get_duration(audio_path)
                    diff = audio_dur - video_dur

                    if abs(diff) > 1.0 and retry_count < max_retries:
                        retry_count += 1
                        current_script = run_async(analysis_service.rewrite_script(current_script, video_dur, audio_dur))
                        video.script = current_script
                        db.commit()
                        continue

                    # Final Merge
                    video.status = "voiced"
                    db.commit()

                    cta_path = video_processor.get_random_cta()
                    needs_speedup = audio_dur > video_dur + 1.0
                    final_path = video_processor.merge_audio_and_overlay(
                        local_raw_path, audio_path, cta_path,
                        target_duration=video_dur if needs_speedup else None,
                        subtitles_path=srt_path,
                        subtitle_style=subtitle_style,
                        overlay_settings=overlay_settings,
                        audio_settings=audio_settings
                    )

                    # Upload final to GCS
                    gcs_uri_final = storage_service.upload_from_filename(
                        final_path, f"final/{video.tiktok_id}_final.mp4"
                    )
                    video.processed_video_path = gcs_uri_final
                    video.status = "merged"
                    db.commit()
                    sync_achieved = True

                    cleanup_local_files(final_path, local_raw_path, audio_path, srt_path)

            except Exception as e:
                logger.error("  ❌ ОШИБКА: %s: %s", video.tiktok_id, e)
                video.status = f"failed: {str(e)[:200]}"
                db.commit()

    finally:
        db.close()

@celery_app.task(name="tasks.bulk_design_update")
def bulk_design_update_task(video_ids: List[int], subtitle_style: dict, overlay_id: int, overlay_settings: dict = None, audio_settings: dict = None):
    """Celery task for bulk design updates."""
    db = SessionLocal()
    try:
        overlay = None
        if overlay_id:
            overlay = db.query(models.Overlay).get(overlay_id)

        for vid in video_ids:
            video = db.query(models.Video).get(vid)
            if not video or not video.gcs_path or not video.voice_gcs_path:
                continue

            try:
                local_raw = storage_service.download_to_local(video.gcs_path)
                local_audio = storage_service.download_to_local(video.voice_gcs_path)
                local_srt = None
                if video.srt_gcs_path:
                    local_srt = storage_service.download_to_local(video.srt_gcs_path)

                final_local = video_processor.merge_audio_and_overlay(
                    video_path=local_raw,
                    audio_path=local_audio,
                    subtitles_path=local_srt,
                    subtitle_style=subtitle_style,
                    overlay_path=overlay.file_path if overlay else None,
                    target_duration=video.duration,
                    overlay_settings=overlay_settings,
                    audio_settings=audio_settings
                )

                gcs_uri = storage_service.upload_from_filename(
                    final_local, f"final/{video.tiktok_id}_revised_{uuid.uuid4().hex[:6]}.mp4"
                )
                video.processed_video_path = gcs_uri
                video.status = "merged"
                db.commit()

                cleanup_local_files(final_local, local_raw, local_audio, local_srt)

            except Exception as e:
                logger.error("Bulk Update Failed for %d: %s", vid, e)
    finally:
        db.close()
