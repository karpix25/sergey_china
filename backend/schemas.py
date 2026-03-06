from pydantic import BaseModel
from typing import Optional, List
import datetime

class CampaignCreate(BaseModel):
    username: str
    video_count: int = 10
    base_description: Optional[str] = None
    enable_subtitles: bool = True
    subtitle_style: Optional[dict] = None
    overlay_settings: Optional[dict] = None  # {bottom_offset: int, scale: int}

class CampaignResponse(BaseModel):
    message: str
    profile_id: int

class VideoResponse(BaseModel):
    id: int
    tiktok_id: str
    status: str
    thumbnail_url: Optional[str]
    is_product: Optional[bool]
    duration: Optional[float]
    script: Optional[str]
    description: Optional[str]
    product_info: Optional[str]
    processed_video_path: Optional[str]
    gcs_path: Optional[str]
    local_video_path: Optional[str]
    published_at: Optional[datetime.datetime] = None
    publish_status: Optional[str] = None
    source: Optional[str] = "tiktok"
    processing_mode: Optional[str] = None

    class Config:
        from_attributes = True


class UploadPostDestinationCreate(BaseModel):
    name: str
    uploadpost_profiles: List[str] = []
    is_active: bool = True
    platforms: List[str] = []
    posts_per_day: int = 3
    min_time_between_posts_minutes: int = 60
    publish_window_start: Optional[str] = "09:00"
    publish_window_end: Optional[str] = "22:00"
    publish_mode: Optional[str] = "auto"
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    youtube_category_id: Optional[str] = "22"
    youtube_privacy: Optional[str] = "public"
    tiktok_privacy: Optional[str] = "PUBLIC_TO_EVERYONE"
    instagram_media_type: Optional[str] = "REELS"


class UploadPostDestinationResponse(BaseModel):
    id: int
    name: str
    uploadpost_profiles: List[str] = []
    is_active: bool
    platforms: List[str]
    posts_per_day: int
    min_time_between_posts_minutes: int
    publish_window_start: Optional[str]
    publish_window_end: Optional[str]
    publish_mode: Optional[str] = "auto"
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    youtube_category_id: Optional[str]
    youtube_privacy: Optional[str]
    tiktok_privacy: Optional[str]
    instagram_media_type: Optional[str]
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class ActivityLogResponse(BaseModel):
    id: int
    profile_id: int
    video_id: Optional[int] = None
    event_type: str
    message: str
    created_at: datetime.datetime

    class Config:
        from_attributes = True

class VideoBulkDescriptionUpdate(BaseModel):
    description: str
