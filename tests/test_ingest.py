import os
import json
import pytest
import shutil
from unittest.mock import MagicMock, patch
from src.ingest import IngestionPipeline

@pytest.fixture
def temp_raw_dir(tmp_path):
    d = tmp_path / "raw_test"
    d.mkdir()
    yield str(d)
    shutil.rmtree(d, ignore_errors=True)

def test_ingest_decoupled_flow(temp_raw_dir):
    # Mock dependencies
    mock_api_client = MagicMock()
    mock_db = MagicMock()

    # Configure mocks
    mock_api_client.resolve_channel_id.return_value = "UC_MOCK_CHANNEL"
    mock_api_client.search_channel_videos.return_value = [
        {"contentDetails": {"videoId": "vid_1"}},
        {"contentDetails": {"videoId": "vid_2"}}
    ]
    mock_api_client.get_video_details.return_value = [
        {
            "id": "vid_1",
            "snippet": {
                "channelId": "UC_MOCK_CHANNEL",
                "channelTitle": "Mock Channel",
                "title": "Video 1 Title",
                "description": "Video 1 Description",
                "publishedAt": "2023-10-27T15:30:00Z"
            },
            "statistics": {"viewCount": "100", "likeCount": "10", "commentCount": "1"},
            "contentDetails": {"duration": "PT1M"}
        },
        {
            "id": "vid_2",
            "snippet": {
                "channelId": "UC_MOCK_CHANNEL",
                "channelTitle": "Mock Channel",
                "title": "Video 2 Title",
                "description": "Video 2 Description",
                "publishedAt": "2023-10-27T15:35:00Z"
            },
            "statistics": {"viewCount": "200", "likeCount": "20", "commentCount": "0"},
            "contentDetails": {"duration": "PT2M"}
        }
    ]
    mock_api_client.get_comments.side_effect = [
        [
            {
                "id": "c_1",
                "snippet": {
                    "videoId": "vid_1",
                    "topLevelComment": {
                        "id": "c_1",
                        "snippet": {
                            "authorDisplayName": "User A",
                            "textDisplay": "First!",
                            "likeCount": 1,
                            "publishedAt": "2023-10-27T15:31:00Z"
                        }
                    }
                }
            }
        ],
        [] # no comments for video 2
    ]

    pipeline = IngestionPipeline(
        api_client=mock_api_client,
        db=mock_db,
        raw_dir=temp_raw_dir,
        cache_path=os.path.join(temp_raw_dir, "cache.json")
    )
    
    # Run Task 1: youtube_to_landing (Extract)
    staged_summary = pipeline.youtube_to_landing("@MockChannel", max_videos=2, max_comments_per_video=5)

    # Assertions for Task 1
    assert staged_summary["videos_staged"] == 2
    assert staged_summary["comments_staged"] == 1

    # Verify API calls
    mock_api_client.resolve_channel_id.assert_called_once_with("@MockChannel")
    mock_api_client.search_channel_videos.assert_called_once_with("UC_MOCK_CHANNEL", max_results=2)
    mock_api_client.get_video_details.assert_called_once_with(["vid_1", "vid_2"])
    
    # Should fetch comments for both videos
    assert mock_api_client.get_comments.call_count == 2
    mock_api_client.get_comments.assert_any_call("vid_1", max_results=5)
    mock_api_client.get_comments.assert_any_call("vid_2", max_results=5)

    # Verify raw files are written on disk in staging layer
    channel_dir = os.path.join(temp_raw_dir, "UC_MOCK_CHANNEL")
    assert os.path.exists(channel_dir)
    
    file1 = os.path.join(channel_dir, "vid_1.json")
    file2 = os.path.join(channel_dir, "vid_2.json")
    
    assert os.path.exists(file1)
    assert os.path.exists(file2)

    with open(file1, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["video"]["id"] == "vid_1"
        assert len(data["comments"]) == 1
        assert data["comments"][0]["id"] == "c_1"

    # Verify DB has NOT been called during extraction task
    assert mock_db.insert_videos.call_count == 0
    assert mock_db.insert_comments.call_count == 0

    # Run Task 2: landing_to_postgres (Load & Transform)
    loaded_summary = pipeline.landing_to_postgres()

    # Assertions for Task 2
    assert loaded_summary["videos_loaded"] == 2
    assert loaded_summary["comments_loaded"] == 1

    # Verify DB insertions occurred
    assert mock_db.insert_videos.call_count == 1
    assert mock_db.insert_comments.call_count == 1
