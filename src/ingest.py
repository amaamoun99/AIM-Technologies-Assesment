import os
import json
import logging
from typing import Any, Dict, List, Optional
from src.api_client import YouTubeAPIClient
from src.transform import VideoTransformer
from src.storage import Database

logger = logging.getLogger(__name__)

class IngestionPipeline:
    def __init__(self, api_client: YouTubeAPIClient, db: Database, raw_dir: str = "data/raw", cache_path: str = "data/channel_cache.json"):
        self.api_client = api_client
        self.db = db
        self.raw_dir = raw_dir
        self.cache_path = cache_path

    def youtube_to_staging(
        self,
        channel_id_or_handle: str,
        max_videos: int = 10,
        max_comments_per_video: int = 10
    ) -> Dict[str, int]:
        """Task 1: Extract from YouTube API and save raw JSON to staging layer."""
        logger.info(f"[Task: youtube_to_staging] Extracting for channel target: {channel_id_or_handle}")
        
        # 1. Resolve channel ID
        if isinstance(channel_id_or_handle, str) and channel_id_or_handle.startswith("UC") and len(channel_id_or_handle) == 24:
            channel_id = channel_id_or_handle
            logger.info(f"Using provided channel ID: {channel_id}")
        else:
            # Check local file-based cache
            cache = {}
            if os.path.exists(self.cache_path):
                try:
                    with open(self.cache_path, "r", encoding="utf-8") as f:
                        cache = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to read channel cache file: {e}")

            if channel_id_or_handle in cache:
                channel_id = cache[channel_id_or_handle]
                logger.info(f"Resolved channel target '{channel_id_or_handle}' from cache to: {channel_id}")
            else:
                try:
                    channel_id = self.api_client.resolve_channel_id(channel_id_or_handle)
                    logger.info(f"Resolved channel target '{channel_id_or_handle}' via API to ID: {channel_id}")
                    
                    # Update cache
                    cache[channel_id_or_handle] = channel_id
                    os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                    with open(self.cache_path, "w", encoding="utf-8") as f:
                        json.dump(cache, f, ensure_ascii=False, indent=2)
                    logger.info(f"Cached resolved ID mapping: '{channel_id_or_handle}' -> '{channel_id}'")
                except Exception as e:
                    logger.error(f"Failed to resolve channel target '{channel_id_or_handle}': {e}")
                    raise

        # 2. Fetch recent videos
        try:
            playlist_items = self.api_client.search_channel_videos(channel_id, max_results=max_videos)
            video_ids = [item["contentDetails"]["videoId"] for item in playlist_items]
            logger.info(f"Found {len(video_ids)} videos for channel {channel_id}")
        except Exception as e:
            logger.error(f"Failed to list videos for channel {channel_id}: {e}")
            raise

        if not video_ids:
            return {"videos_staged": 0, "comments_staged": 0}

        # 3. Fetch full details for the videos
        try:
            raw_videos = self.api_client.get_video_details(video_ids)
            logger.info(f"Retrieved details for {len(raw_videos)} videos")
        except Exception as e:
            logger.error(f"Failed to get video details for channel {channel_id}: {e}")
            raise

        # Ensure staging directory for the channel exists
        channel_raw_dir = os.path.join(self.raw_dir, channel_id)
        os.makedirs(channel_raw_dir, exist_ok=True)

        videos_staged_count = 0
        comments_staged_count = 0

        # Process each video
        for video_item in raw_videos:
            video_id = video_item.get("id")
            if not video_id:
                continue

            videos_staged_count += 1
            logger.info(f"Staging video {video_id}")

            # 4. Fetch comments for this video
            try:
                raw_comments = self.api_client.get_comments(video_id, max_results=max_comments_per_video)
                comments_staged_count += len(raw_comments)
                logger.info(f"Fetched {len(raw_comments)} comments for video {video_id}")
            except Exception as e:
                logger.warning(f"Failed to fetch comments for video {video_id}, continuing: {e}")
                raw_comments = []

            # 5. Write raw JSON to staging folder
            raw_data = {
                "video": video_item,
                "comments": raw_comments
            }
            raw_file_path = os.path.join(channel_raw_dir, f"{video_id}.json")
            try:
                with open(raw_file_path, "w", encoding="utf-8") as f:
                    json.dump(raw_data, f, ensure_ascii=False, indent=2)
                logger.info(f"Saved raw JSON to {raw_file_path}")
            except Exception as e:
                logger.error(f"Failed to save raw JSON for video {video_id}: {e}")

        return {
            "videos_staged": videos_staged_count,
            "comments_staged": comments_staged_count
        }

    def staging_to_postgres(self) -> Dict[str, int]:
        """Task 2: Read raw JSON files from staging layer, transform, and load to PostgreSQL DB."""
        logger.info("[Task: staging_to_postgres] Starting transformation and load to database...")
        
        all_videos = []
        all_comments = []
        files_processed = 0

        if not os.path.exists(self.raw_dir):
            logger.warning(f"Staging directory {self.raw_dir} does not exist.")
            return {"videos_loaded": 0, "comments_loaded": 0}

        # Scan for all JSON files in the raw staging folder
        for root, _, files in os.walk(self.raw_dir):
            for file in files:
                if not file.endswith(".json"):
                    continue
                
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                    
                    raw_video = raw_data.get("video")
                    raw_comments = raw_data.get("comments", [])
                    
                    if not raw_video:
                        logger.warning(f"Staging file {file_path} is missing video details.")
                        continue
                    
                    # 1. Transform raw elements
                    video_id = raw_video.get("id")
                    transformed_videos = VideoTransformer.transform_videos([raw_video])
                    transformed_comments = VideoTransformer.transform_comments(video_id, raw_comments)
                    
                    all_videos.extend(transformed_videos)
                    all_comments.extend(transformed_comments)
                    files_processed += 1
                except Exception as e:
                    logger.error(f"Failed to process staging file {file_path}: {e}")

        logger.info(f"Processed {files_processed} staging files. Found {len(all_videos)} videos and {len(all_comments)} comments.")

        videos_loaded_count = 0
        comments_loaded_count = 0

        # 2. Bulk load videos into Postgres database
        if all_videos:
            try:
                self.db.insert_videos(all_videos)
                videos_loaded_count = len(all_videos)
            except Exception as e:
                logger.error(f"Database insertion failed for videos batch: {e}")
                raise

        # 3. Bulk load comments into Postgres database
        if all_comments:
            try:
                self.db.insert_comments(all_comments)
                comments_loaded_count = len(all_comments)
            except Exception as e:
                logger.error(f"Database insertion failed for comments batch: {e}")
                raise

        return {
            "videos_loaded": videos_loaded_count,
            "comments_loaded": comments_loaded_count
        }
