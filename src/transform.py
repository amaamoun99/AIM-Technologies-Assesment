import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from src.models import Video, Comment

logger = logging.getLogger(__name__)

def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO 8601 datetime string from YouTube API, converting 'Z' to UTC timezone."""
    if not dt_str:
        return None
    try:
        # Replace Z with +00:00 for ISO compliance in standard library if needed
        # but Python 3.11's fromisoformat handles 'Z' out of the box.
        # Just in case, let's normalize 'Z' to '+00:00' for backward compatibility.
        normalized = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except Exception as e:
        logger.warning(f"Failed to parse datetime string '{dt_str}': {e}")
        return None

class VideoTransformer:
    @staticmethod
    def transform_videos(raw_items: List[Dict[str, Any]]) -> List[Video]:
        """Transform raw video items from YouTube API JSON to Video dataclasses."""
        videos = []
        for item in raw_items:
            try:
                video_id = item.get("id")
                snippet = item.get("snippet", {})
                statistics = item.get("statistics", {})
                content_details = item.get("contentDetails", {})

                if not video_id:
                    logger.warning("Skipping raw video item with missing ID")
                    continue

                published_at_str = snippet.get("publishedAt")
                published_at = parse_iso_datetime(published_at_str)
                if not published_at:
                    logger.warning(f"Skipping video {video_id} due to invalid publishedAt date")
                    continue

                # Safely parse numeric fields, defaulting to 0 if missing/None
                view_count = int(statistics.get("viewCount") or 0)
                like_count = int(statistics.get("likeCount") or 0)
                comment_count = int(statistics.get("commentCount") or 0)

                video = Video(
                    video_id=video_id,
                    channel_id=snippet.get("channelId", ""),
                    channel_name=snippet.get("channelTitle", ""),
                    title=snippet.get("title", ""),
                    description=snippet.get("description"),
                    published_at=published_at,
                    view_count=view_count,
                    like_count=like_count,
                    comment_count=comment_count,
                    duration=content_details.get("duration"),
                    fetched_at=datetime.now(timezone.utc)
                )
                videos.append(video)
            except Exception as e:
                logger.error(f"Error transforming video item {item.get('id', 'unknown')}: {e}")
                
        return videos

    @staticmethod
    def transform_comments(video_id: str, raw_items: List[Dict[str, Any]]) -> List[Comment]:
        """Transform raw comment thread items from YouTube API JSON to Comment dataclasses."""
        comments = []
        for item in raw_items:
            try:
                snippet = item.get("snippet", {})
                top_comment = snippet.get("topLevelComment", {})
                comment_id = top_comment.get("id") or item.get("id")
                comment_snippet = top_comment.get("snippet", {})

                if not comment_id:
                    logger.warning(f"Skipping raw comment item with missing ID under video {video_id}")
                    continue

                published_at_str = comment_snippet.get("publishedAt")
                published_at = parse_iso_datetime(published_at_str)
                if not published_at:
                    logger.warning(f"Skipping comment {comment_id} due to invalid publishedAt date")
                    continue

                like_count = int(comment_snippet.get("likeCount") or 0)

                comment = Comment(
                    comment_id=comment_id,
                    video_id=video_id,
                    author=comment_snippet.get("authorDisplayName", "Unknown"),
                    text=comment_snippet.get("textDisplay"),
                    like_count=like_count,
                    published_at=published_at
                )
                comments.append(comment)
            except Exception as e:
                logger.error(f"Error transforming comment thread item under video {video_id}: {e}")

        return comments
