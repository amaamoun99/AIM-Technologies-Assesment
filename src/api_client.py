import time
import logging
import requests
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class YouTubeAPIError(Exception):
    """Base exception for YouTube API errors."""
    pass

class YouTubeAPIClient:
    BASE_URL = "https://www.googleapis.com/youtube/v3"

    def __init__(self, api_key: str, timeout: int = 10, max_retries: int = 3, backoff_factor: float = 2.0):
        if not api_key:
            raise ValueError("API key must be provided")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def _request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/{endpoint}"
        req_params = params.copy() if params else {}
        req_params["key"] = self.api_key

        retries = 0
        backoff = 1.0

        while True:
            try:
                response = requests.get(url, params=req_params, timeout=self.timeout)
                
                # Check for rate limiting or server errors to retry
                if response.status_code in (429, 500, 503, 504):
                    if retries < self.max_retries:
                        retries += 1
                        sleep_time = backoff * self.backoff_factor
                        logger.warning(
                            f"HTTP {response.status_code} on {endpoint}. Retrying in {sleep_time:.2f}s... (Attempt {retries}/{self.max_retries})"
                        )
                        time.sleep(sleep_time)
                        backoff *= 2.0
                        continue
                    else:
                        response.raise_for_status()

                # Raise HTTPError for other non-2xx status codes
                response.raise_for_status()
                return response.json()

            except requests.exceptions.HTTPError as e:
                # Do not retry on general HTTP errors (like 403, 404, etc.)
                raise e
            except requests.exceptions.RequestException as e:
                # Retry on connection errors/timeouts
                if retries < self.max_retries:
                    retries += 1
                    sleep_time = backoff * self.backoff_factor
                    logger.warning(
                        f"Request failed with {str(e)}. Retrying in {sleep_time:.2f}s... (Attempt {retries}/{self.max_retries})"
                    )
                    time.sleep(sleep_time)
                    backoff *= 2.0
                    continue
                raise YouTubeAPIError(f"Request failed after {self.max_retries} retries: {str(e)}") from e

    def resolve_channel_id(self, handle: str) -> str:
        """Resolve a channel handle (e.g. @Saba7oKorah or Saba7oKorah) to its unique channel ID UC..."""
        cleaned = handle.strip()
        # Strip leading '@' if present
        handle_name = cleaned[1:] if cleaned.startswith("@") else cleaned
        
        try:
            data = self._request("channels", {"part": "id", "forHandle": handle_name})
            if data.get("items"):
                return data["items"][0]["id"]
        except Exception as e:
            raise YouTubeAPIError(f"Failed to resolve channel handle '{handle}': {e}") from e

        raise YouTubeAPIError(f"No channel found for handle '{handle}'")

    def search_channel_videos(self, channel_id: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """List videos of a channel using its uploads playlist (highly quota efficient)."""
        # 1. Fetch channel's uploads playlist ID
        channel_data = self._request("channels", {"part": "contentDetails", "id": channel_id})
        if not channel_data.get("items"):
            raise YouTubeAPIError(f"Channel {channel_id} not found")
        
        uploads_playlist_id = (
            channel_data["items"][0]
            .get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )
        if not uploads_playlist_id:
            raise YouTubeAPIError(f"Could not find uploads playlist for channel {channel_id}")

        # 2. Fetch items from uploads playlist
        items: List[Dict[str, Any]] = []
        next_page_token = None
        
        while len(items) < max_results:
            limit = min(max_results - len(items), 50)
            params = {
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": limit
            }
            if next_page_token:
                params["pageToken"] = next_page_token
                
            playlist_data = self._request("playlistItems", params)
            new_items = playlist_data.get("items", [])
            items.extend(new_items)
            
            next_page_token = playlist_data.get("nextPageToken")
            if not next_page_token or not new_items:
                break
                
        return items

    def get_video_details(self, video_ids: List[str]) -> List[Dict[str, Any]]:
        """Fetch statistics and details for a list of video IDs (max 50 per request)."""
        if not video_ids:
            return []

        all_items: List[Dict[str, Any]] = []
        # Chunk video_ids in sizes of 50
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i+50]
            ids_str = ",".join(chunk)
            data = self._request("videos", {
                "part": "snippet,statistics,contentDetails",
                "id": ids_str
            })
            all_items.extend(data.get("items", []))
            
        return all_items

    def get_comments(self, video_id: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """Fetch comments for a video, handling disabled comments gracefully."""
        items: List[Dict[str, Any]] = []
        next_page_token = None
        
        try:
            while len(items) < max_results:
                limit = min(max_results - len(items), 100)
                params = {
                    "part": "snippet",
                    "videoId": video_id,
                    "maxResults": limit
                }
                if next_page_token:
                    params["pageToken"] = next_page_token

                data = self._request("commentThreads", params)
                new_items = data.get("items", [])
                items.extend(new_items)
                
                next_page_token = data.get("nextPageToken")
                if not next_page_token or not new_items:
                    break
        except requests.HTTPError as e:
            # Check if comments are disabled (usually returns 403 Forbidden with commentsDisabled)
            if e.response is not None and e.response.status_code == 403:
                try:
                    err_data = e.response.json()
                    errors = err_data.get("error", {}).get("errors", [])
                    reasons = [err.get("reason") for err in errors]
                    if "commentsDisabled" in reasons:
                        logger.warning(f"Comments are disabled for video {video_id}.")
                        return []
                except Exception:
                    pass
            # Raise other HTTP errors
            raise YouTubeAPIError(f"Failed to fetch comments for video {video_id}: {e}") from e
        except Exception as e:
            raise YouTubeAPIError(f"Failed to fetch comments for video {video_id}: {e}") from e

        return items
