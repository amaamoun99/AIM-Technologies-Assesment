from datetime import datetime, timezone
from src.models import Video, Comment

def test_video_model():
    now = datetime.now(timezone.utc)
    video = Video(
        video_id="vid_123",
        channel_id="chan_abc",
        channel_name="Test Channel",
        title="Test Title",
        description="Test Description",
        published_at=now,
        view_count=1000,
        like_count=50,
        comment_count=10,
        duration="PT5M",
        fetched_at=now
    )
    assert video.video_id == "vid_123"
    assert video.channel_id == "chan_abc"
    assert video.channel_name == "Test Channel"
    assert video.title == "Test Title"
    assert video.description == "Test Description"
    assert video.published_at == now
    assert video.view_count == 1000
    assert video.like_count == 50
    assert video.comment_count == 10
    assert video.duration == "PT5M"
    assert video.fetched_at == now

def test_comment_model():
    now = datetime.now(timezone.utc)
    comment = Comment(
        comment_id="comment_999",
        video_id="vid_123",
        author="John Doe",
        text="Cool video!",
        like_count=5,
        published_at=now
    )
    assert comment.comment_id == "comment_999"
    assert comment.video_id == "vid_123"
    assert comment.author == "John Doe"
    assert comment.text == "Cool video!"
    assert comment.like_count == 5
    assert comment.published_at == now
