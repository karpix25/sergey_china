import httpx
import os
from typing import List, Dict

class ScraperService:
    def __init__(self):
        self.api_key = os.getenv("SCRAPE_CREATORS_API_KEY")
        self.base_url = "https://api.scrapecreators.com/v3" # Based on docs link provided

    async def fetch_profile_videos(self, username: str, count: int = 10) -> List[Dict]:
        """
        Fetches videos in batches of 20 (API limit per request).
        """
        print(f"Scraper: Fetching {count} videos for @{username}...")
        all_videos = []
        cursor = None
        batch_size = 20
        
        async with httpx.AsyncClient() as client:
            while len(all_videos) < count:
                url = f"{self.base_url}/tiktok/profile/videos"
                params = {
                    "handle": username.replace("@", ""),
                    "count": min(batch_size, count - len(all_videos))
                }
                if cursor:
                    params["max_cursor"] = cursor
                
                headers = {
                    "x-api-key": self.api_key
                }
                
                try:
                    print(f"Scraper: Requesting {params['count']} videos (cursor: {cursor})...")
                    response = await client.get(url, params=params, headers=headers, timeout=60.0)
                    response.raise_for_status()
                    data = response.json()
                    
                    if not data.get("success") and "aweme_list" not in data and "videos" not in data:
                        print(f"Scraper: API returned unusual response: {str(data)[:200]}")
                    raw_videos = data.get("aweme_list") or data.get("videos") or []
                    
                    processed_videos = []
                    for v in raw_videos:
                        # Extract ID
                        v_id = v.get("aweme_id") or v.get("id")
                        
                        # Extract URLs — priority order (user specified play_addr.url_list for no watermark):
                        # The user pointed out that the non-watermarked video is in video.play_addr.url_list
                        video_obj = v.get("video", {})
                        play_addr = video_obj.get("play_addr", {})
                        play_urls = play_addr.get("url_list") or []
                        
                        v_url = None
                        url_source = "none"

                        # 1. User requested path: play_addr.url_list
                        if play_urls and len(play_urls) > 0:
                            # Usually the last one or the one with specific params is best, 
                            # but we'll try the first one as a starting point or the one that looks like a direct CDN link
                            v_url = play_urls[0]
                            url_source = "play_addr.url_list"

                        # 2. download_addr (fallback)
                        if not v_url:
                            download_addr = video_obj.get("download_addr", {})
                            dl_urls = download_addr.get("url_list") or []
                            if dl_urls and dl_urls[0]:
                                v_url = dl_urls[0]
                                url_source = "download_addr"

                        # 3. bit_rate info (fallback)
                        if not v_url:
                            bitrate_info = v.get("video", {}).get("bit_rate") or []
                            if bitrate_info:
                                br_urls = bitrate_info[0].get("PlayAddr", {}).get("url_list") or []
                                if br_urls and br_urls[0]:
                                    v_url = br_urls[0]
                                    url_source = "bitrateInfo"

                        # 4. top-level download_url (last resort)
                        if not v_url:
                            v_url = v.get("download_url")
                            url_source = "top-level download_url"
                        
                        # Extract thumbnail (cover image) — prioritize origin_cover (higher quality/stability)
                        video_obj = v.get("video", {})
                        cover_obj = video_obj.get("origin_cover") or video_obj.get("cover") or v.get("cover") or {}
                        
                        v_thumb = None
                        thumb_list = cover_obj.get("url_list") or []
                        if thumb_list and thumb_list[0]:
                            v_thumb = thumb_list[0]
                        
                        # Fallback for some API versions
                        if not v_thumb:
                            v_thumb = v.get("origin_cover", {}).get("url_list", [None])[0] or \
                                      v.get("cover", {}).get("url_list", [None])[0]

                        if v_id and v_url:
                            print(f"  video {v_id}: url from [{url_source}]")
                            processed_videos.append({
                                "id": v_id,
                                "download_url": v_url,
                                "thumbnail_url": v_thumb,
                            })
                    
                    if not processed_videos:
                        print(f"Scraper: No more videos found in response.")
                        break
                        
                    all_videos.extend(processed_videos)
                    cursor = data.get("cursor") or data.get("max_cursor") or data.get("next_cursor")
                    
                    if not cursor:
                        break
                        
                except Exception as e:
                    print(f"Error fetching videos: {e}")
                    break
                    
        return all_videos[:count]

scraper_service = ScraperService()
