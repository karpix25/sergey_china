"""Overlay upload, list, delete routes."""
import logging
import os
import shutil

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

import models
from database import get_db
from helpers.overlay_url import resolve_overlay_preview_url
from services.storage import storage_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/overlays/upload")
async def upload_overlay(file: UploadFile = File(...), db: Session = Depends(get_db)):
    cta_dir = "storage/cta_plates"
    os.makedirs(cta_dir, exist_ok=True)

    file_path = os.path.join(cta_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Upload to GCS for persistence
    gcs_blob_name = f"overlays/{file.filename}"
    gcs_uri = storage_service.upload_from_filename(file_path, gcs_blob_name)

    overlay = models.Overlay(
        name=file.filename,
        file_path=file_path,
        gcs_path=gcs_uri if gcs_uri and not gcs_uri.startswith("local://") else None,
    )
    db.add(overlay)
    db.commit()
    db.refresh(overlay)

    preview_url = resolve_overlay_preview_url(
        gcs_path=overlay.gcs_path,
        file_path=overlay.file_path,
        filename=file.filename,
    )
    return {"id": overlay.id, "name": overlay.name, "preview_url": preview_url}


@router.get("/overlays")
async def list_overlays(db: Session = Depends(get_db)):
    overlays = db.query(models.Overlay).all()
    result = []
    for o in overlays:
        preview_url = resolve_overlay_preview_url(
            gcs_path=o.gcs_path,
            file_path=o.file_path,
        )
        result.append({
            "id": o.id,
            "name": o.name,
            "file_path": o.file_path,
            "gcs_path": o.gcs_path,
            "is_active": o.is_active,
            "preview_url": preview_url,
        })
    return result


@router.delete("/overlays/{overlay_id}")
async def delete_overlay(overlay_id: int, db: Session = Depends(get_db)):
    overlay = db.query(models.Overlay).get(overlay_id)
    if not overlay:
        raise HTTPException(status_code=404, detail="Overlay not found")

    # Delete local file
    if overlay.file_path and os.path.exists(overlay.file_path):
        os.remove(overlay.file_path)

    # Delete from GCS
    if overlay.gcs_path and storage_service.bucket:
        try:
            blob_name = overlay.gcs_path.replace(f"gs://{storage_service.bucket_name}/", "")
            blob = storage_service.bucket.blob(blob_name)
            blob.delete()
            logger.info("GCS delete: %s", blob_name)
        except Exception as e:
            logger.warning("GCS delete error (non-fatal): %s", e)

    db.delete(overlay)
    db.commit()
    return {"message": "Overlay deleted"}
