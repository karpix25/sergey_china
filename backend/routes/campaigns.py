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

    background_tasks.add_task(
        process_campaign,
        profile.id, req.video_count, req.base_description,
        req.enable_subtitles, req.subtitle_style, req.overlay_settings,
    )
    return {"message": "Campaign started", "profile_id": profile.id}


# ─────────────────────────────────────────────
#  Background campaign processing
# ─────────────────────────────────────────────

async def process_campaign(
    profile_id: int,
    count: int,
    base_description: str = None,
    enable_subtitles: bool = True,
    subtitle_style: dict = None,
    overlay_settings: dict = None,
):
    """Acquire campaign semaphore (max 1 concurrent) then process."""
    async with campaign_semaphore:
        await _process_campaign_inner(
            profile_id, count, base_description,
            enable_subtitles, subtitle_style, overlay_settings,
        )


async def _process_campaign_inner(
    profile_id: int,
    count: int,
    base_description: str = None,
    enable_subtitles: bool = True,
    subtitle_style: dict = None,
    overlay_settings: dict = None,
):
    db = SessionLocal()
    profile_username = None
    try:
        profile = db.query(models.Profile).get(profile_id)
        if not profile:
            logger.error("Background Task Error: Profile %d not found", profile_id)
            return

        profile_username = profile.username.lower()
        logger.info("━" * 60)
        logger.info("  🚀 Кампания: @%s (лимит: %d видео)", profile.username, count)
        logger.info("━" * 60)
        log_activity(db, profile_id, f"Запуск кампании для @{profile.username} (лимит: {count} видео)", "info")

        # Fetch videos from scraper
        videos_data = await scraper_service.fetch_profile_videos(profile.username, count)
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
                    logger.info("Video %s exists with status '%s', re-processing.", v_data["id"], existing.status)
                    log_activity(db, profile_id, f"Повторная обработка {v_data['id']}", "info", video_id=existing.id)
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
                await download_video(video.url, local_raw_path)

                # Upload raw to GCS
                gcs_uri = storage_service.upload_from_filename(local_raw_path, f"raw/{video.tiktok_id}.mp4")
                video.gcs_path = gcs_uri
                video.status = "downloaded"
                log_activity(db, profile_id, f"Видео {video.tiktok_id} успешно скачано", "info", video_id=video.id)
                db.commit()

                # Thumbnail
                thumb_url = extract_and_upload_thumbnail(local_raw_path, video.tiktok_id)
                if thumb_url:
                    video.thumbnail_url = thumb_url
                    db.commit()

                # Analyze with Gemini
                sync_achieved = False
                retry_count = 0
                max_retries = 2

                logger.info("    🧠 Анализ Gemini...")
                analysis = await analysis_service.analyze_video(gcs_uri)
                logger.info(
                    "    🧠 Результат: is_product=%s, dur=%ss",
                    analysis["is_product"], analysis["detected_duration"],
                )
                video.is_product = analysis["is_product"]
                video.duration = analysis["detected_duration"]
                video.script = analysis["script"]
                video.product_info = analysis.get("product_summary", "")
                log_activity(db, profile_id, f"Gemini: Анализ видео {video.tiktok_id} завершен", "info", video_id=video.id)
                db.commit()

                if not video.is_product:
                    logger.info("    ⏭️  Нет товара — пропуск")
                    video.status = "skipped (no product)"
                    log_activity(db, profile_id, f"Пропуск: Товар не обнаружен в {video.tiktok_id}", "skip", video_id=video.id)
                    db.commit()
                    continue

                # Adapted description
                if base_description:
                    logger.info("  - Adapting description for video %s...", video.tiktok_id)
                    video.description = await analysis_service.generate_adapted_description(
                        video.script, base_description, video.product_info
                    )
                    db.commit()

                # Voiceover + sync loop
                current_script = video.script
                video_dur = video.duration

                while not sync_achieved and retry_count <= max_retries:
                    logger.info("    🎙️  Озвучка (попытка %d)...", retry_count + 1)

                    if enable_subtitles:
                        audio_path, alignment = audio_service.generate_speech_with_timestamps(current_script)
                        wpc = video_processor.get_words_per_chunk(subtitle_style)
                        srt_content = subtitle_service.alignments_to_srt(alignment, words_per_chunk=wpc)
                        srt_path = audio_path.replace(".mp3", ".srt")
                        subtitle_service.save_srt(srt_content, srt_path)
                    else:
                        audio_path = audio_service.generate_speech(current_script)
                        srt_path = None

                    audio_dur = audio_service.get_duration(audio_path)
                    log_activity(db, profile_id, f"Озвучка сгенерирована ({audio_dur:.1f}с)", "info", video_id=video.id)

                    diff = audio_dur - video_dur
                    logger.info("    ⏱️  Audio=%.1fs, Video=%.1fs, Diff=%+.1fs", audio_dur, video_dur, diff)

                    if abs(diff) > 1.0:
                        if retry_count >= max_retries:
                            logger.info("  - Max retries reached. Proceeding with current audio.")
                        else:
                            retry_count += 1
                            action = "shorten" if diff > 0 else "lengthen"
                            logger.info("  - Audio sync failed (diff=%+.1fs). Attempting to %s script...", diff, action)
                            current_script = await analysis_service.rewrite_script(current_script, video_dur, audio_dur)
                            video.script = current_script
                            db.commit()
                            continue

                    # Final Merge
                    logger.info("    🎬 Склейка + CTA...")
                    log_activity(db, profile_id, f"Склейка видео {video.tiktok_id}...", "info", video_id=video.id)
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
                    )
                    if needs_speedup:
                        logger.info("  - Audio still too long (%.1fs > %.1fs), sped up.", audio_dur, video_dur)

                    # Upload final to GCS
                    gcs_or_local_uri = storage_service.upload_from_filename(
                        final_path, f"final/{video.tiktok_id}_final.mp4"
                    )
                    video.processed_video_path = gcs_or_local_uri
                    video.local_video_path = final_path
                    video.status = "merged"
                    log_activity(db, profile_id, f"Видео {video.tiktok_id} успешно обработано!", "success", video_id=video.id)
                    db.commit()
                    sync_achieved = True

                    if gcs_or_local_uri and not gcs_or_local_uri.startswith("local://"):
                        if os.path.exists(final_path):
                            os.remove(final_path)
                            video.local_video_path = None
                            db.commit()
                            logger.info("  - Deleted local final file: %s", final_path)
                        if os.path.exists(local_raw_path):
                            os.remove(local_raw_path)
                            logger.info("  - Deleted local raw file: %s", local_raw_path)

            except Exception as e:
                err_msg = str(e)[:200]
                logger.error("  ❌ ОШИБКА: %s: %s", video.tiktok_id, err_msg)
                video.status = f"failed: {err_msg}"
                db.commit()

    except Exception as e:
        logger.error("  ❌ Критическая ошибка кампании @%s: %s", profile_username or profile_id, e)
    finally:
        if profile_username:
            processing_profiles.discard(profile_username)
        logger.info("━" * 60)
        logger.info("  ✅ Кампания @%s завершена", profile_username or profile_id)
        logger.info("━" * 60)
        db.close()
