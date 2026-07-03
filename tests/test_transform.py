from datetime import datetime, timezone
from src.transform import VideoTransformer

def test_transform_videos_happy_path():
    raw_json = [
        {
            "id": "vid_abc",
            "snippet": {
                "channelId": "chan_123",
                "channelTitle": "Tech Channel",
                "title": "A Great Video",
                "description": "This is a description",
                "publishedAt": "2023-10-27T15:30:00Z"
            },
            "statistics": {
                "viewCount": "15000",
                "likeCount": "450",
                "commentCount": "32"
            },
            "contentDetails": {
                "duration": "PT10M15S"
            }
        }
    ]

    videos = VideoTransformer.transform_videos(raw_json)
    assert len(videos) == 1
    v = videos[0]
    assert v.video_id == "vid_abc"
    assert v.channel_id == "chan_123"
    assert v.channel_name == "Tech Channel"
    assert v.title == "A Great Video"
    assert v.description == "This is a description"
    assert v.published_at == datetime(2023, 10, 27, 15, 30, 0, tzinfo=timezone.utc)
    assert v.view_count == 15000
    assert v.like_count == 450
    assert v.comment_count == 32
    assert v.duration == "PT10M15S"
    assert v.fetched_at is not None

def test_transform_videos_missing_optional_fields():
    raw_json = [
        {
            "id": "vid_def",
            "snippet": {
                "channelId": "chan_456",
                "channelTitle": "Other Channel",
                "title": "Minimal Video",
                "publishedAt": "2023-10-27T15:30:00Z"
                # description missing
            }
            # statistics missing, contentDetails missing
        }
    ]

    videos = VideoTransformer.transform_videos(raw_json)
    assert len(videos) == 1
    v = videos[0]
    assert v.video_id == "vid_def"
    assert v.description is None
    assert v.view_count == 0
    assert v.like_count == 0
    assert v.comment_count == 0
    assert v.duration is None

def test_transform_comments_happy_path():
    raw_json = [
        {
            "id": "thread_1",
            "snippet": {
                "videoId": "vid_abc",
                "topLevelComment": {
                    "id": "comment_1",
                    "snippet": {
                        "authorDisplayName": "Alice",
                        "textDisplay": "Nice video!",
                        "likeCount": 12,
                        "publishedAt": "2023-10-28T09:00:00Z"
                    }
                }
            }
        }
    ]

    comments = VideoTransformer.transform_comments("vid_abc", raw_json)
    assert len(comments) == 1
    c = comments[0]
    assert c.comment_id == "comment_1"
    assert c.video_id == "vid_abc"
    assert c.author == "Alice"
    assert c.text == "Nice video!"
    assert c.like_count == 12
    assert c.published_at == datetime(2023, 10, 28, 9, 0, 0, tzinfo=timezone.utc)

def test_transform_comments_edge_cases():
    raw_json = [
        {
            "id": "thread_2",
            "snippet": {
                "videoId": "vid_abc",
                "topLevelComment": {
                    "id": "comment_2",
                    "snippet": {
                        # authorDisplayName and textDisplay missing
                        "publishedAt": "2023-10-28T09:00:00Z"
                    }
                }
            }
        }
    ]

    comments = VideoTransformer.transform_comments("vid_abc", raw_json)
    assert len(comments) == 1
    c = comments[0]
    assert c.comment_id == "comment_2"
    assert c.author == "Unknown"
    assert c.text is None
    assert c.like_count == 0
