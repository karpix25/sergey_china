"""
Upload-Post API Service
========================
Сервис для публикации видео в TikTok, YouTube, Instagram через Upload-Post API.

Режим работы:
- STUB (api_key == None или "test"): логирует намерение, не отправляет запросов.
  Активируется автоматически, пока не задан реальный ключ.
- LIVE: отправляет реальные запросы к https://api.upload-post.com

Для активации LIVE-режима достаточно заполнить поля в настройках автопубликации
(API Key и Username) через дашборд или прямо в таблице autopublish_settings.
"""
import os
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

UPLOADPOST_BASE_URL = "https://api.upload-post.com"

# Читаем из env (приоритет перед настройками профиля)
_ENV_API_KEY = os.environ.get("UPLOADPOST_API_KEY", "").strip()
_ENV_PROFILE = os.environ.get("UPLOADPOST_PROFILE", "").strip()


def get_env_status() -> dict:
    """Возвращает статус ENV-ключа (без реального API-запроса)."""
    has_key = bool(_ENV_API_KEY and _ENV_API_KEY not in ("your_uploadpost_key_here", "test"))
    return {
        "env_key_configured": has_key,
        "env_profile_configured": bool(_ENV_PROFILE),
        "env_key_preview": (_ENV_API_KEY[:6] + "..." + _ENV_API_KEY[-4:]) if has_key and len(_ENV_API_KEY) > 10 else None,
    }



class UploadPostService:
    """Обёртка над Upload-Post API с поддержкой stub-режима.Тakem ключ из ENV если в профиле не задан."""

    def _resolve_key(self, api_key: Optional[str]) -> str:
        """Возвращает активный ключ: сначала из профиля, затем из ENV."""
        if api_key and api_key.strip() not in ("", "test", "YOUR_API_KEY"):
            return api_key.strip()
        return _ENV_API_KEY

    def _resolve_profile(self, profile: Optional[str]) -> str:
        if profile and profile.strip():
            return profile.strip()
        return _ENV_PROFILE

    def _is_stub(self, api_key: Optional[str]) -> bool:
        resolved = self._resolve_key(api_key)
        return not resolved or resolved in ("", "test", "YOUR_API_KEY")

    def _headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Apikey {api_key}",
        }

    async def publish_video(
        self,
        *,
        api_key: Optional[str],
        uploadpost_profile: str,
        video_url: str,               # GCS signed URL или локальный URL
        title: str,
        description: Optional[str],
        platforms: list[str],
        # Platform-specific params
        tiktok_privacy: str = "PUBLIC_TO_EVERYONE",
        youtube_privacy: str = "public",
        youtube_category_id: str = "22",
        instagram_media_type: str = "REELS",
    ) -> dict:
        """
        Публикует видео на выбранных платформах.
        Возвращает dict с результатом по каждой платформе.
        """
        if self._is_stub(api_key):
            return self._stub_response(platforms, video_url, title)

        return await self._live_publish(
            api_key=self._resolve_key(api_key),
            uploadpost_profile=self._resolve_profile(uploadpost_profile),
            video_url=video_url,
            title=title,
            description=description,
            platforms=platforms,
            tiktok_privacy=tiktok_privacy,
            youtube_privacy=youtube_privacy,
            youtube_category_id=youtube_category_id,
            instagram_media_type=instagram_media_type,
        )

    def _stub_response(self, platforms: list[str], video_url: str, title: str) -> dict:
        """Возвращает заглушку — успешный результат без реального запроса."""
        logger.info(
            "[STUB] Autopublish: would publish '%s' to platforms %s via URL: %s",
            title,
            platforms,
            video_url,
        )
        return {
            "stub": True,
            "platforms": platforms,
            "success": True,
            "message": "Stub mode: no API key configured. Video would be published to: "
                       + ", ".join(platforms),
        }

    async def _live_publish(
        self,
        *,
        api_key: str,
        uploadpost_profile: str,
        video_url: str,
        title: str,
        description: Optional[str],
        platforms: list[str],
        tiktok_privacy: str,
        youtube_privacy: str,
        youtube_category_id: str,
        instagram_media_type: str,
    ) -> dict:
        """Реальный запрос к Upload-Post API (POST /api/upload_videos)."""
        endpoint = f"{UPLOADPOST_BASE_URL}/api/upload_videos"

        # Формируем список платформ для Upload-Post
        # Upload-Post принимает platform[] (array)
        payload = {
            "user": uploadpost_profile,
            "video": video_url,
            "title": title[:80] if title else "Video",  # TikTok max 90 chars
            "async_upload": "true",
        }

        if description:
            payload["description"] = description

        # Platform-specific params
        if "tiktok" in platforms:
            payload["tiktok_privacy"] = tiktok_privacy

        if "youtube" in platforms:
            payload["youtube_privacy"] = youtube_privacy
            payload["youtube_category_id"] = youtube_category_id
            if description:
                payload["youtube_description"] = description

        if "instagram" in platforms:
            payload["instagram_media_type"] = instagram_media_type

        # Build form-data with platform[] array
        form_data = []
        for field, value in payload.items():
            form_data.append((field, str(value)))

        for platform in platforms:
            # Map our names to Upload-Post names
            platform_map = {
                "tiktok": "tiktok",
                "youtube": "youtube",
                "instagram": "instagram",
            }
            up_platform = platform_map.get(platform)
            if up_platform:
                form_data.append(("platform[]", up_platform))

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    endpoint,
                    headers=self._headers(api_key),
                    data=form_data,
                )

            if response.status_code in (200, 202):
                result = response.json()
                logger.info("[LIVE] Upload-Post publish success: %s", result)
                return {"success": True, "data": result, "stub": False}
            else:
                logger.error(
                    "[LIVE] Upload-Post publish failed: %s %s",
                    response.status_code,
                    response.text,
                )
                return {
                    "success": False,
                    "stub": False,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}",
                }

        except Exception as e:
            logger.exception("[LIVE] Upload-Post publish exception: %s", e)
            return {"success": False, "stub": False, "error": str(e)}

    async def get_account_info(self, api_key: str) -> dict:
        """
        Проверяет валидность API ключа через GET /api/uploadposts/me.
        Возвращает {'valid': True/False, 'email': ..., 'plan': ...}
        """
        if self._is_stub(api_key):
            return {"valid": False, "stub": True, "message": "No API key configured"}

        resolved_key = self._resolve_key(api_key)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"{UPLOADPOST_BASE_URL}/api/uploadposts/me",
                    headers=self._headers(resolved_key),
                )
            if response.status_code == 200:
                data = response.json()
                return {"valid": True, "email": data.get("email"), "plan": data.get("plan")}
            return {"valid": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    async def get_user_profiles(self, api_key: Optional[str] = None) -> dict:
        """
        Получает список user profiles из Upload-Post API.
        GET /api/uploadposts/users
        Возвращает {'success': True, 'profiles': [...], 'limit': N, 'plan': '...'}
        """
        resolved_key = self._resolve_key(api_key)
        if not resolved_key or resolved_key in ("", "test", "YOUR_API_KEY"):
            return {"success": False, "profiles": [], "error": "No API key configured"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"{UPLOADPOST_BASE_URL}/api/uploadposts/users",
                    headers=self._headers(resolved_key),
                )
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "profiles": data.get("profiles", []),
                    "limit": data.get("limit"),
                    "plan": data.get("plan"),
                }
            return {"success": False, "profiles": [], "error": f"HTTP {response.status_code}"}
        except Exception as e:
            logger.exception("[UploadPost] get_user_profiles error: %s", e)
            return {"success": False, "profiles": [], "error": str(e)}


uploadpost_service = UploadPostService()
