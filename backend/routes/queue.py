"""Global publishing queue routes — list, shuffle, interleave."""
import logging
import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_unpublished_videos(db: Session):
    """Return merged videos that have NOT been published to any destination."""
    assigned_ids = db.query(models.VideoPublishLog.video_id)
    return (
        db.query(models.Video)
        .filter(
            models.Video.status == "merged",
            ~models.Video.id.in_(assigned_ids),
        )
        .order_by(
            models.Video.queue_position.asc().nullslast(),
            models.Video.created_at.asc(),
        )
        .all()
    )


@router.get("/videos/global-queue")
async def get_global_queue(db: Session = Depends(get_db)):
    """Получить глобальную очередь видео, которые ГОТОВЫ, но ЕЩЕ НИКУДА не опубликованы."""
    queue = _get_unpublished_videos(db)

    queue_items = [
        {
            "id": v.id,
            "tiktok_id": v.tiktok_id,
            "description": v.description,
            "source": v.source or "tiktok",
            "queue_position": v.queue_position,
        }
        for v in queue
    ]
    return {"queue_count": len(queue_items), "queue": queue_items}


@router.post("/videos/global-queue/shuffle")
async def shuffle_global_queue(db: Session = Depends(get_db)):
    """Перемешать глобальную очередь."""
    assigned_ids = db.query(models.VideoPublishLog.video_id)
    videos = (
        db.query(models.Video)
        .filter(
            models.Video.status == "merged",
            ~models.Video.id.in_(assigned_ids),
        )
        .all()
    )

    if not videos:
        return {"message": "Нет видео для перемешивания", "count": 0}

    positions = list(range(1, len(videos) + 1))
    random.shuffle(positions)

    for v, pos in zip(videos, positions):
        v.queue_position = pos

    db.commit()
    return {"message": f"Перемешано {len(videos)} видео", "count": len(videos)}


@router.post("/videos/global-queue/interleave")
async def interleave_global_queue(db: Session = Depends(get_db)):
    """Равномерно вкрапить загруженные видео среди парсенных в глобальной очереди."""
    all_videos = _get_unpublished_videos(db)

    if not all_videos:
        return {"message": "Нет видео для вкрапления", "count": 0}

    tiktok_vids = [v for v in all_videos if (v.source or "tiktok") != "upload"]
    upload_vids = [v for v in all_videos if (v.source or "tiktok") == "upload"]

    if not upload_vids:
        return {"message": "Нет загруженных видео для вкрапления", "count": 0}

    # Interleave evenly
    result: list = []
    if not tiktok_vids:
        result = upload_vids
    else:
        interval = max(1, len(tiktok_vids) // (len(upload_vids) + 1))
        upload_idx = 0
        for i, tv in enumerate(tiktok_vids):
            result.append(tv)
            if upload_idx < len(upload_vids) and (i + 1) % interval == 0:
                result.append(upload_vids[upload_idx])
                upload_idx += 1
        # Distribute remaining uploads at random positions
        while upload_idx < len(upload_vids):
            pos = random.randint(0, len(result))
            result.insert(pos, upload_vids[upload_idx])
            upload_idx += 1

    for i, v in enumerate(result):
        v.queue_position = i + 1
    db.commit()

    return {
        "message": f"Вкраплено {len(upload_vids)} загруженных видео среди {len(tiktok_vids)} парсенных",
        "count": len(result),
    }

@router.post("/trigger-scheduler")
async def trigger_scheduler(db: Session = Depends(get_db)):
    """Вручную запустить цикл планировщика (для отладки)."""
    try:
        from services.scheduler import _run_autopublish
        await _run_autopublish()
        return {"status": "triggered"}
    except Exception as e:
        logger.exception("Manual trigger failed")
        raise HTTPException(status_code=500, detail=str(e))
