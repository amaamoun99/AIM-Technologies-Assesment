from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Comment:
    comment_id: str
    video_id: str
    author: str
    text: Optional[str]
    like_count: int
    published_at: datetime
