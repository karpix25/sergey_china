from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

class Profile(Base):
    __tablename__ = "profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    videos = relationship("Video", back_populates="profile")

class Video(Base):
    __tablename__ = "videos"
    
    id = Column(Integer, primary_key=True, index=True)
    tiktok_id = Column(String, unique=True, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"))
    
    url = Column(String)              # Original TikTok download URL
    thumbnail_url = Column(String, nullable=True)  # TikTok cover image URL
    gcs_path = Column(String, nullable=True)       # Raw video GCS URI
    
    status = Column(String, default="pending")  # pending, downloaded, analyzed, voiced, merged, failed
    source = Column(String, default="tiktok")        # tiktok | upload
    processing_mode = Column(String, nullable=True)  # raw | overlay | full
    
    is_product = Column(Boolean, nullable=True)
    duration = Column(Float, nullable=True)
    script = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    
    processed_video_path = Column(String, nullable=True)  # GCS URI (gs://...)
    local_video_path = Column(String, nullable=True)      # Local path served via /outputs
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    published_at = Column(DateTime, nullable=True)         # Когда опубликовано в соцсети
    publish_status = Column(String, nullable=True)         # published | failed | None
    queue_position = Column(Integer, nullable=True)        # Позиция в очереди публикации (меньше = раньше)
    
    profile = relationship("Profile", back_populates="videos")

class Overlay(Base):
    __tablename__ = "overlays"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    file_path = Column(String)          # Local path (storage/cta_plates/...)
    gcs_path = Column(String, nullable=True)  # GCS URI (gs://bucket/overlays/...)
    is_active = Column(Boolean, default=True)


class UploadPostDestination(Base):
    """Глобальный профиль (направление) для публикации в Upload-Post."""
    __tablename__ = "uploadpost_destinations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False) # Название для внутреннего использования (e.g. "Гаджеты TikTok + YT")
    uploadpost_profiles = Column(JSON, default=list)   # ["profile1", "profile2"]
    
    is_active = Column(Boolean, default=True)           # Вкл/выкл
    platforms = Column(JSON, default=list)              # ["tiktok", "youtube", "instagram"]
    
    # Настройки расписания
    posts_per_day = Column(Integer, default=3)          # публикаций/день
    min_time_between_posts_minutes = Column(Integer, default=60)  # Мин. пауза между постами (минуты)
    publish_window_start = Column(String, default="09:00")  # С какого часа публиковать
    publish_window_end = Column(String, default="22:00")    # До какого часа публиковать

    # Режим публикации
    publish_mode = Column(String, default="auto")       # auto | telegram
    telegram_bot_token = Column(String, nullable=True)
    telegram_chat_id = Column(String, nullable=True)

    # TikTok / YouTube / Instagram specific fields
    youtube_category_id = Column(String, default="22")      # 22 = People & Blogs
    youtube_privacy = Column(String, default="public")      # public | unlisted | private
    tiktok_privacy = Column(String, default="PUBLIC_TO_EVERYONE")
    instagram_media_type = Column(String, default="REELS")

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Связки публикаций
    publish_logs = relationship("VideoPublishLog", back_populates="destination", cascade="all, delete-orphan")


class VideoPublishLog(Base):
    """Лог отправки конкретного видео на конкретный UploadPostDestination. 
    Гарантирует уникальность (1 видео = 1 дестинейшн)."""
    __tablename__ = "video_publish_logs"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="CASCADE"), index=True, nullable=False)
    destination_id = Column(Integer, ForeignKey("uploadpost_destinations.id", ondelete="CASCADE"), index=True, nullable=False)
    
    published_at = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(String, default="published") # published | failed
    error_message = Column(Text, nullable=True)

    video = relationship("Video")
    destination = relationship("UploadPostDestination", back_populates="publish_logs")

class ActivityLog(Base):
    __tablename__ = "activity_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=True) # Optional link to video
    
    event_type = Column(String)  # info, success, warning, error, skip
    message = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    profile = relationship("Profile", backref="activity_logs")
    video = relationship("Video")
