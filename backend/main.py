from fastapi import FastAPI, HTTPException, Security, Depends, status, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from contextlib import asynccontextmanager
import os
import logging
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi.responses import RedirectResponse

# Configure logging early
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Load .env

# Load .env
load_dotenv("../.env")
load_dotenv() 

import models
from database import engine, get_db
from helpers.db_utils import upgrade_db_schema

# Auto-upgrade schema before start
upgrade_db_schema()

from routes.videos import router as videos_router
from routes.campaigns import router as campaigns_router
from routes.overlays import router as overlays_router
from routes.destinations import router as destinations_router
from routes.queue import router as queue_router
from routes.telegram import router as telegram_router
from routes.activity import router as activity_router

from helpers.auth import get_api_key

# ─── Suppress noisy polling endpoints from access logs ───
class PollFilterLog(logging.Filter):
    NOISY = ("/api/videos", "/api/activity", "/api/overlays", "/api/autopublish")
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if '"GET' not in msg:
            return True
        for path in self.NOISY:
            if path in msg and ('200 OK' in msg or '304 Not Modified' in msg):
                return False
        return True

logging.getLogger("uvicorn.access").addFilter(PollFilterLog())

def run_startup_migrations():
    alters = [
        "ALTER TABLE videos ADD COLUMN IF NOT EXISTS description TEXT",
        "ALTER TABLE videos ADD COLUMN IF NOT EXISTS published_at TIMESTAMP",
        "ALTER TABLE videos ADD COLUMN IF NOT EXISTS publish_status VARCHAR",
        "ALTER TABLE videos ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'tiktok'",
        "ALTER TABLE videos ADD COLUMN IF NOT EXISTS processing_mode VARCHAR",
        "ALTER TABLE autopublish_settings ADD COLUMN IF NOT EXISTS publish_window_start VARCHAR DEFAULT '09:00'",
        "ALTER TABLE autopublish_settings ADD COLUMN IF NOT EXISTS publish_window_end VARCHAR DEFAULT '22:00'",
        "ALTER TABLE autopublish_settings ADD COLUMN IF NOT EXISTS min_time_between_posts_minutes INTEGER DEFAULT 60",
        "ALTER TABLE overlays ADD COLUMN IF NOT EXISTS gcs_path VARCHAR",
        "ALTER TABLE videos ADD COLUMN IF NOT EXISTS queue_position INTEGER",
        "ALTER TABLE autopublish_settings ADD COLUMN IF NOT EXISTS publish_mode VARCHAR DEFAULT 'auto'",
        "ALTER TABLE autopublish_settings ADD COLUMN IF NOT EXISTS telegram_bot_token VARCHAR",
        "ALTER TABLE autopublish_settings ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR",
        "ALTER TABLE uploadpost_destinations ADD COLUMN IF NOT EXISTS publish_mode VARCHAR DEFAULT 'auto'",
        "ALTER TABLE uploadpost_destinations ADD COLUMN IF NOT EXISTS telegram_bot_token VARCHAR",
        "ALTER TABLE uploadpost_destinations ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR",
        "ALTER TABLE uploadpost_destinations ADD COLUMN IF NOT EXISTS uploadpost_profiles JSON DEFAULT '[]'",
        "ALTER TABLE uploadpost_destinations DROP COLUMN IF EXISTS uploadpost_profile",
    ]
    try:
        with engine.connect() as conn:
            for sql in alters:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                except Exception:
                    pass
    except Exception as e:
        print(f"[Migration] Warning: {e}")

run_startup_migrations()
models.Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    yield
    stop_scheduler()

app = FastAPI(title="TikTok Content Manager API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes with security
app.include_router(videos_router, prefix="/api", dependencies=[Depends(get_api_key)])
app.include_router(campaigns_router, prefix="/api", dependencies=[Depends(get_api_key)])
app.include_router(overlays_router, prefix="/api", dependencies=[Depends(get_api_key)])
app.include_router(destinations_router, prefix="/api", dependencies=[Depends(get_api_key)])
app.include_router(queue_router, prefix="/api", dependencies=[Depends(get_api_key)])
app.include_router(telegram_router, prefix="/api", dependencies=[Depends(get_api_key)])
app.include_router(activity_router, prefix="/api", dependencies=[Depends(get_api_key)])

os.makedirs("outputs", exist_ok=True)
os.makedirs("storage/cta_plates", exist_ok=True)
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
app.mount("/storage", StaticFiles(directory="storage"), name="storage")

# Apply security to static files (via middleware or wrap)
# Actually, standard way is to use a route that checks auth then returns FileResponse, 
# but for now we applied query param auth to get_api_key.
# To keep it simple and consistent with how frontend uses it (?api_key=...), 
# we can use a custom middleware or just keep them as-is if 401s elsewhere are the main pain.
# Given they were getting 401s on /stream and /url, let's fix those first.

@app.get("/api/storage/url")
async def get_storage_url(gs_uri: str, download: int = 0, authenticated: str = Depends(get_api_key)):
    from services.storage import storage_service
    if not gs_uri.startswith("gs://"):
        raise HTTPException(status_code=400, detail="Invalid GCS URI")
    blob_name = gs_uri.replace(f"gs://{storage_service.bucket_name}/", "")
    signed_url = storage_service.generate_signed_url(blob_name, expiration_minutes=60, download=bool(download))
    if not signed_url:
        raise HTTPException(status_code=503, detail="GCS not configured")
    return RedirectResponse(url=signed_url)

@app.get("/api/videos/{video_id}/stream")
async def stream_video(video_id: int, download: int = 0, db: Session = Depends(get_db), authenticated: str = Depends(get_api_key)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    gcs_uri = video.processed_video_path or video.gcs_path
    if not gcs_uri or not gcs_uri.startswith("gs://"):
        if video.local_video_path:
            return RedirectResponse(url=f"/{video.local_video_path.lstrip('/')}")
        raise HTTPException(status_code=404, detail="No video available")
    return await get_storage_url(gcs_uri, download=download, authenticated=authenticated)

@app.get("/")
async def root():
    return {"message": "TikTok Content Manager API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
