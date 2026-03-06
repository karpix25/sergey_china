"""Thumbnail extraction and upload helper (de-duplicated from campaign + upload flows)."""
import logging
import os

from services.video import video_processor
from services.storage import storage_service

logger = logging.getLogger(__name__)


def extract_and_upload_thumbnail(
    video_path: str, tiktok_id: str
) -> str | None:
    """
    Extract a thumbnail from *video_path*, upload to GCS, and return the
    GCS URI.  Returns ``None`` on failure.  Cleans up the local thumbnail file.
    """
    thumb_local = f"tmp/thumb_{tiktok_id}.jpg"
    try:
        if not video_processor.extract_thumbnail(video_path, thumb_local):
            return None

        gcs_thumb = storage_service.upload_from_filename(
            thumb_local, f"thumbs/{tiktok_id}.jpg"
        )
        return gcs_thumb if gcs_thumb else None
    except Exception as e:
        logger.warning("Thumbnail extraction failed for %s: %s", tiktok_id, e)
        return None
    finally:
        if os.path.exists(thumb_local):
            os.remove(thumb_local)
