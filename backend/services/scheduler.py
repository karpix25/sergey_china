"""
Autopublish Scheduler — Smart Spacing
======================================
Запускается при старте FastAPI-приложения.
Каждую МИНУТУ проверяет все профили с is_enabled=True
и публикует следующее готовое видео, если:
  1. Текущее время внутри publish_window.
  2. Лимит posts_per_day НЕ исчерпан.
  3. С последней публикации прошло >= min_time_between_posts_minutes.
  4. Наступило рассчитанное «идеальное» время для следующей публикации.

Идеальный интервал = доступное_окно_минут / posts_per_day.
К каждому слоту добавляется jitter ±5 мин (анти-бот рандомизация).
"""
import logging
import datetime
import random
import os
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

load_dotenv("../.env") # Look in parent dir first (Docker structure)
load_dotenv()           # Then local

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

scheduler = AsyncIOScheduler()


def _parse_time(s: str) -> tuple[int, int]:
    """Parse 'HH:MM' string into (hours, minutes)."""
    parts = s.split(":")
    return int(parts[0]), int(parts[1])


def calculate_publish_slots(settings, published_today: int, queue_count: int) -> list[datetime.datetime]:
    """
    Рассчитать точное время публикации для каждого видео в очереди.
    Возвращает список datetime (UTC) с точностью до секунд.
    """
    if queue_count <= 0:
        return []

    now_utc = datetime.datetime.utcnow()
    posts_per_day = settings.posts_per_day or 1
    min_gap = settings.min_time_between_posts_minutes or 60

    remaining = posts_per_day - published_today
    if remaining <= 0:
        return []  # лимит на сегодня исчерпан

    # Парсим окно публикации
    window_start_str = settings.publish_window_start or "00:00"
    window_end_str = settings.publish_window_end or "23:59"
    try:
        ws_h, ws_m = _parse_time(window_start_str)
        we_h, we_m = _parse_time(window_end_str)
        start_minutes = ws_h * 60 + ws_m
        end_minutes = we_h * 60 + we_m
    except Exception:
        start_minutes = 0
        end_minutes = 23 * 60 + 59

    window_total_min = end_minutes - start_minutes
    if window_total_min <= 0:
        window_total_min = 1

    # Идеальный интервал между постами
    ideal_interval = max(min_gap, window_total_min / posts_per_day)

    # Определяем стартовую точку
    last_pub = settings.last_published_at
    now_minutes = now_utc.hour * 60 + now_utc.minute

    if last_pub and last_pub.date() == now_utc.date():
        # Последняя публикация сегодня — считаем от неё
        base_time = last_pub
    elif now_minutes < start_minutes:
        # Ещё не наступило окно — считаем от начала окна
        base_time = now_utc.replace(hour=ws_h, minute=ws_m, second=0, microsecond=0)
    else:
        # Внутри окна, публикаций сегодня нет — считаем от текущего момента
        base_time = now_utc

    slots = []
    slots_to_calculate = min(queue_count, remaining)
    for i in range(slots_to_calculate):
        # jitter ±5 мин для каждого слота (детерминированный seed на основе позиции)
        jitter = random.randint(-5, 5)
        offset_minutes = ideal_interval * (i + 1) + jitter
        slot_time = base_time + datetime.timedelta(minutes=offset_minutes)

        # Не выходим за пределы окна
        slot_end_of_day = now_utc.replace(hour=we_h, minute=we_m, second=59, microsecond=0)
        if slot_time > slot_end_of_day:
            break  # за пределами окна — остальные не влезают

        # Если слот в прошлом (< now), сдвигаем на ближайший допустимый момент
        if slot_time < now_utc:
            slot_time = now_utc + datetime.timedelta(minutes=min_gap * (i + 1))

        slots.append(slot_time)

    return slots


async def _run_autopublish():
    """Основная задача планировщика (вызывается раз в минуту)."""
    from database import SessionLocal
    import models
    from services.uploadpost import uploadpost_service
    from services.storage import storage_service
    from services.telegram_sender import send_video_to_telegram
    from helpers.logging import log_activity

    db = SessionLocal()
    logger.info("[Scheduler] _run_autopublish loop started")
    try:
        now_utc = datetime.datetime.utcnow()
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

        # 0. Диагностика очереди
        assigned_video_ids = db.query(models.VideoPublishLog.video_id).subquery()
        ready_videos_count = (
            db.query(models.Video)
            .filter(
                models.Video.status == "merged",
                ~models.Video.id.in_(assigned_video_ids)
            )
            .count()
        )
        logger.info("[Scheduler] Diagnostic: Ready unassigned videos count = %d", ready_videos_count)

        # Все активные направления публикации
        destinations = (
            db.query(models.UploadPostDestination)
            .filter(models.UploadPostDestination.is_active == True)
            .all()
        )

        if not destinations:
            logger.info("[Scheduler] No active destinations found.")
            return
        
        logger.info("[Scheduler] Found %d active destinations", len(destinations))

        for dest in destinations:
            platforms = dest.platforms or []
            posts_per_day = dest.posts_per_day or 1
            min_gap = dest.min_time_between_posts_minutes or 60

            # Telegram mode doesn't strictly need Upload-Post platforms
            if not platforms and dest.publish_mode != "telegram":
                logger.debug("[Scheduler] Destination %s has no platforms, skipping.", dest.name)
                continue

            # ── 1. Проверяем временное окно ──
            window_start_str = dest.publish_window_start or "00:00"
            window_end_str = dest.publish_window_end or "23:59"
            try:
                ws_h, ws_m = _parse_time(window_start_str)
                we_h, we_m = _parse_time(window_end_str)
                now_minutes = now_utc.hour * 60 + now_utc.minute
                start_minutes = ws_h * 60 + ws_m
                end_minutes = we_h * 60 + we_m
                in_window = start_minutes <= now_minutes <= end_minutes
            except Exception:
                in_window = True

            if not in_window:
                logger.debug("[Scheduler] Destination %s: outside window (%s - %s)", dest.name, window_start_str, window_end_str)
                continue

            # ── 2. Считаем публикации за сегодня для ЭТОГО профиля ──
            published_today = (
                db.query(models.VideoPublishLog)
                .filter(
                    models.VideoPublishLog.destination_id == dest.id,
                    models.VideoPublishLog.status == "published",
                    models.VideoPublishLog.published_at >= today_start,
                )
                .count()
            )

            remaining = posts_per_day - published_today
            if remaining <= 0:
                continue

            # ── 3. Проверяем min_gap с момента последней публикации ──
            last_pub_log = (
                db.query(models.VideoPublishLog)
                .filter(
                    models.VideoPublishLog.destination_id == dest.id,
                    models.VideoPublishLog.status == "published"
                )
                .order_by(models.VideoPublishLog.published_at.desc())
                .first()
            )
            last_pub = last_pub_log.published_at if last_pub_log else None

            if last_pub:
                elapsed = (now_utc - last_pub).total_seconds() / 60.0
                if elapsed < min_gap:
                    logger.debug(
                        "[Scheduler] Destination %s: %d min since last pub, need %d. Waiting.",
                        dest.name, int(elapsed), min_gap,
                    )
                    continue

            # ── 4. Рассчитываем идеальный интервал ──
            window_total_min = end_minutes - start_minutes
            if window_total_min <= 0:
                window_total_min = 1

            ideal_interval = max(min_gap, window_total_min / posts_per_day)

            if last_pub and last_pub >= today_start:
                minutes_since_last = (now_utc - last_pub).total_seconds() / 60.0
                jitter = random.randint(-5, 5)
                target_wait = ideal_interval + jitter
                if minutes_since_last < target_wait:
                    logger.debug(
                        "[Scheduler] Destination %s: ideal wait %d min (jitter %+d), elapsed %d. Waiting.",
                        dest.name, int(ideal_interval), jitter, int(minutes_since_last),
                    )
                    continue

            # ── 5. Берём следующее ГОТОВОЕ УНИКАЛЬНОЕ видео ──
            # Видео, которое имеет status == "merged", 
            # и которого НЕТ в video_publish_logs ВООБЩЕ (ни для какого профиля).
            assigned_video_ids = db.query(models.VideoPublishLog.video_id).subquery()
            
            video = (
                db.query(models.Video)
                .filter(
                    models.Video.status == "merged",
                    ~models.Video.id.in_(assigned_video_ids)
                )
                .order_by(models.Video.created_at.asc())
                .first()
            )

            if not video:
                # Count why it's empty
                total_merged = db.query(models.Video).filter(models.Video.status == "merged").count()
                logger.info("[Scheduler] Destination %s: Queue empty. Total ready videos: %d, already assigned: %d", 
                            dest.name, total_merged, db.query(assigned_video_ids).count())
                continue

            logger.info(
                "[Scheduler] Destination %s: publishing video %s to %s (slot %d/%d today)...",
                dest.name, video.tiktok_id, platforms, published_today + 1, posts_per_day,
            )

            # Создаем черновой лог для блокировки видео (чтобы другой поток не взял его же)
            pub_log = models.VideoPublishLog(
                video_id=video.id,
                destination_id=dest.id,
                status="processing"
            )
            db.add(pub_log)
            db.commit() # видео забронировано

            video_url = _resolve_video_url(video, storage_service)
            if not video_url:
                logger.warning(
                    "[Scheduler] Video %s: no URL available, skipping.", video.tiktok_id
                )
                pub_log.status = "failed"
                pub_log.error_message = "No video URL available"
                db.commit()
                continue

            # 5. Выбор режима публикации
            if dest.publish_mode == "telegram":
                bot_token = (dest.telegram_bot_token or "").strip() or os.environ.get("TELEGRAM_BOT_TOKEN")
                chat_id = (dest.telegram_chat_id or "").strip() or os.environ.get("TELEGRAM_CHAT_ID")
                
                source = "DB" if (dest.telegram_chat_id or "").strip() else "ENV"
                logger.info("[Scheduler] Telegram Mode for %s: sending to chat %s (source: %s)", dest.name, chat_id, source)
                log_activity(db, None, f"[Auto] Отправка видео {video.tiktok_id} в Telegram", "info", video_id=video.id)
                result = await send_video_to_telegram(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    video_url=video_url,
                    caption=video.description or f"Video {video.tiktok_id}"
                )
            else:
                # Публикация в Upload-Post для каждого профиля
                profiles = dest.uploadpost_profiles or []
                if not profiles:
                    profiles = [""]  # fallback: use ENV profile

                result = None
                for profile in profiles:
                    result = await uploadpost_service.publish_video(
                        api_key=None,
                        uploadpost_profile=profile,
                        video_url=video_url,
                        title=video.script[:80] if video.script else f"Video {video.tiktok_id}",
                        description=video.description,
                        platforms=platforms,
                        tiktok_privacy=dest.tiktok_privacy or "PUBLIC_TO_EVERYONE",
                        youtube_privacy=dest.youtube_privacy or "public",
                        youtube_category_id=dest.youtube_category_id or "22",
                        instagram_media_type=dest.instagram_media_type or "REELS",
                    )
                log_activity(db, None, f"[Auto] Отправка видео {video.tiktok_id} через Upload-Post", "info", video_id=video.id)

            if result.get("success"):
                pub_log.status = "published"
                pub_log.published_at = datetime.datetime.utcnow()
                db.commit()
                logger.info(
                    "[Scheduler] ✅ Video %s published to %s at %s.",
                    video.tiktok_id, dest.name,
                    datetime.datetime.utcnow().strftime("%H:%M:%S")
                )
                log_activity(db, None, f"✅ Видео {video.tiktok_id} успешно опубликовано ({dest.publish_mode})", "success", video_id=video.id)
            else:
                pub_log.status = "failed"
                pub_log.error_message = result.get("error", "Unknown error")
                db.commit()
                logger.error(
                    "[Scheduler] ❌ Video %s publish to %s failed: %s",
                    video.tiktok_id, dest.name, result.get("error"),
                )
                log_activity(db, None, f"❌ Ошибка публикации {video.tiktok_id}: {result.get('error')}", "error", video_id=video.id)

    except Exception as e:
        logger.exception("[Scheduler] Unexpected error: %s", e)
    finally:
        db.close()


def _resolve_video_url(video, storage_service) -> str | None:
    """
    Возвращает публичный URL видео.
    Приоритет: processed_video_path (GCS) → local_video_path → original url
    """
    # GCS → signed URL
    gcs_uri = video.processed_video_path or video.gcs_path
    if gcs_uri and gcs_uri.startswith("gs://") and storage_service:
        try:
            blob_name = gcs_uri.replace(
                f"gs://{storage_service.bucket_name}/", ""
            )
            signed = storage_service.generate_signed_url(blob_name, expiration_minutes=120)
            if signed:
                return signed
        except Exception as e:
            logger.warning("[Scheduler] GCS signed URL failed: %s", e)

    # Local path (only works if server is accessible from Upload-Post)
    if video.local_video_path:
        backend_url = "http://localhost:8000"  # Overridable via env
        backend_url = os.environ.get("BACKEND_PUBLIC_URL", backend_url)
        return f"{backend_url}/{video.local_video_path.lstrip('/')}"

    # Original TikTok URL (may have expired)
    return video.url or None


def start_scheduler():
    """Запускает планировщик. Вызывается из main.py при старте приложения."""
    # Запуск СРАЗУ при старте + каждые 1 мин
    scheduler.add_job(
        _run_autopublish,
        trigger=IntervalTrigger(minutes=1),
        id="autopublish",
        name="Autopublish Videos (Smart Spacing)",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.datetime.now() # Run immediately
    )
    scheduler.start()
    logger.info("[Scheduler] Smart autopublish scheduler started (immediate first run).")


def stop_scheduler():
    """Останавливает планировщик при завершении приложения."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Autopublish scheduler stopped.")
