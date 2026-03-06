"""Overlay preview URL resolution (de-duplicated from upload_overlay & list_overlays)."""
from services.storage import storage_service


def resolve_overlay_preview_url(
    gcs_path: str | None,
    file_path: str | None,
    filename: str | None = None,
) -> str:
    """
    Return a viewable URL for an overlay image.

    Priority:
      1. GCS signed URL (if bucket is configured and gcs_path is set)
      2. Local static fallback
    """
    if gcs_path and storage_service.bucket:
        blob_name = gcs_path.replace(f"gs://{storage_service.bucket_name}/", "")
        signed = storage_service.generate_signed_url(blob_name, expiration_minutes=1440)
        if signed:
            return signed

    # Fallback to local static mount
    if file_path:
        clean = file_path.replace("\\", "/").lstrip("/")
        return f"/{clean}"

    if filename:
        return f"/storage/cta_plates/{filename}"

    return ""
