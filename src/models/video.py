from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Video:
    video_id: str
    channel_id: str
    channel_name: str
    title: str
    description: Optional[str]
    published_at: datetime
    view_count: int
    like_count: int
    comment_count: int
    duration: Optional[str]
    fetched_at: Optional[datetime] = None
