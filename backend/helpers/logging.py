"""Centralized activity logging helper."""
import logging
from sqlalchemy.orm import Session
import models

logger = logging.getLogger(__name__)


def log_activity(
    db: Session,
    profile_id: int,
    message: str,
    event_type: str = "info",
    video_id: int = None,
) -> None:
    """Persist an activity log entry to the database."""
    try:
        log = models.ActivityLog(
            profile_id=profile_id,
            video_id=video_id,
            event_type=event_type,
            message=message,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning("Error logging activity: %s", e)
