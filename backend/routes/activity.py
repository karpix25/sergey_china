"""Activity log routes."""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db

router = APIRouter()


@router.get("/activity/{profile_id}", response_model=List[schemas.ActivityLogResponse])
async def get_activity_logs(profile_id: int, db: Session = Depends(get_db)):
    return (
        db.query(models.ActivityLog)
        .filter(models.ActivityLog.profile_id == profile_id)
        .order_by(models.ActivityLog.created_at.desc())
        .limit(50)
        .all()
    )


@router.get("/activity", response_model=List[schemas.ActivityLogResponse])
async def get_all_activity_logs(db: Session = Depends(get_db)):
    return (
        db.query(models.ActivityLog)
        .order_by(models.ActivityLog.created_at.desc())
        .limit(100)
        .all()
    )
