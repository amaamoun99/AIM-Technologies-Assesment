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

    def run_for_channel(
        self,
        channel_id_or_handle: str,
        max_videos: int = 10,
        max_comments_per_video: int = 10,
        dry_run: bool = False
    ) -> Dict[str, int]:
        """Orchestrate the ingestion for a single channel handle or ID."""
        logger.info(f"Starting ingestion for channel target: {channel_id_or_handle}")
        
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
            return {"videos_fetched": 0, "comments_fetched": 0, "videos_loaded": 0, "comments_loaded": 0}

        # 3. Fetch full details for the videos
        try:
            raw_videos = self.api_client.get_video_details(video_ids)
            logger.info(f"Retrieved details for {len(raw_videos)} videos")
        except Exception as e:
            logger.error(f"Failed to get video details for channel {channel_id}: {e}")
            raise

        # Ensure landing directory for the channel exists
        channel_raw_dir = os.path.join(self.raw_dir, channel_id)
        os.makedirs(channel_raw_dir, exist_ok=True)

        videos_fetched_count = 0
        comments_fetched_count = 0
        videos_loaded_count = 0
        comments_loaded_count = 0

        # Process each video
        for video_item in raw_videos:
            video_id = video_item.get("id")
            if not video_id:
                continue

            videos_fetched_count += 1
            logger.info(f"Processing video {video_id}")

            # 4. Fetch comments for this video
            try:
                raw_comments = self.api_client.get_comments(video_id, max_results=max_comments_per_video)
                comments_fetched_count += len(raw_comments)
                logger.info(f"Fetched {len(raw_comments)} comments for video {video_id}")
            except Exception as e:
                logger.warning(f"Failed to fetch comments for video {video_id}, continuing: {e}")
                raw_comments = []

            # 5. Write raw JSON to landing zone
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

            # 6. Transform raw items
            videos = VideoTransformer.transform_videos([video_item])
            comments = VideoTransformer.transform_comments(video_id, raw_comments)

            # 7. Load into Database
            if videos and not dry_run:
                try:
                    self.db.insert_videos(videos)
                    videos_loaded_count += len(videos)
                    
                    if comments:
                        self.db.insert_comments(comments)
                        comments_loaded_count += len(comments)
                except Exception as e:
                    logger.error(f"Failed to load data for video {video_id} into database: {e}")
            elif dry_run:
                logger.info(f"Dry run mode: skipped loading {len(videos)} videos and {len(comments)} comments to DB")

        return {
            "videos_fetched": videos_fetched_count,
            "comments_fetched": comments_fetched_count,
            "videos_loaded": videos_loaded_count,
            "comments_loaded": comments_loaded_count
        }
