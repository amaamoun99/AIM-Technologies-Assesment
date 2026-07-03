import os
import pytest
import requests
from unittest.mock import patch, MagicMock
from src.api_client import YouTubeAPIClient, YouTubeAPIError

@pytest.fixture
def client():
    return YouTubeAPIClient(api_key="test_api_key", timeout=1, max_retries=2, backoff_factor=0.01)

def test_init_raises_value_error():
    with pytest.raises(ValueError):
        YouTubeAPIClient(api_key="")

def test_request_success(client):
    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_get.return_value = mock_response
        
        res = client._request("test_endpoint", {"param": "val"})
        
        assert res == {"status": "ok"}
        mock_get.assert_called_once_with(
            "https://www.googleapis.com/youtube/v3/test_endpoint",
            params={"param": "val", "key": "test_api_key"},
            timeout=1
        )

def test_request_429_retries_and_succeeds(client):
    with patch("requests.get") as mock_get, patch("time.sleep") as mock_sleep:
        mock_response_fail = MagicMock()
        mock_response_fail.status_code = 429
        mock_response_fail.raise_for_status.side_effect = requests.HTTPError("Too Many Requests")

        mock_response_ok = MagicMock()
        mock_response_ok.status_code = 200
        mock_response_ok.json.return_value = {"status": "ok"}

        mock_get.side_effect = [mock_response_fail, mock_response_ok]

        res = client._request("test_endpoint")

        assert res == {"status": "ok"}
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

def test_request_max_retries_reached(client):
    with patch("requests.get") as mock_get, patch("time.sleep") as mock_sleep:
        mock_response_fail = MagicMock()
        mock_response_fail.status_code = 500
        mock_response_fail.raise_for_status.side_effect = requests.HTTPError("Internal Server Error")

        mock_get.return_value = mock_response_fail

        with pytest.raises(requests.HTTPError):
            client._request("test_endpoint")
        
        assert mock_get.call_count == 3  # 1 initial + 2 retries

def test_resolve_channel_id_by_handle(client):
    with patch.object(client, "_request") as mock_req:
        mock_req.return_value = {"items": [{"id": "UC_TEST_CHANNEL"}]}
        
        chan_id = client.resolve_channel_id("@Saba7oKorah")
        
        assert chan_id == "UC_TEST_CHANNEL"
        mock_req.assert_called_once_with("channels", {"part": "id", "forHandle": "Saba7oKorah"})

def test_resolve_channel_id_by_search_fallback(client):
    with patch.object(client, "_request") as mock_req:
        # First call (handle) returns empty list or fails, second call (search) returns a match
        mock_req.side_effect = [
            {"items": []}, # channels query
            {"items": [{"id": {"channelId": "UC_SEARCHED_CHANNEL"}}]} # search query
        ]
        
        chan_id = client.resolve_channel_id("@SomeChannel")
        
        assert chan_id == "UC_SEARCHED_CHANNEL"
        assert mock_req.call_count == 2

def test_search_channel_videos(client):
    with patch.object(client, "_request") as mock_req:
        mock_req.side_effect = [
            # channels details call
            {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUP_UPLOADS"}}}]},
            # playlistItems call
            {"items": [{"id": "item1"}, {"id": "item2"}], "nextPageToken": None}
        ]
        
        videos = client.search_channel_videos("UC_TEST_CHANNEL", max_results=5)
        
        assert len(videos) == 2
        assert videos[0]["id"] == "item1"
        assert mock_req.call_count == 2

def test_get_video_details(client):
    with patch.object(client, "_request") as mock_req:
        mock_req.return_value = {"items": [{"id": "vid1", "snippet": {}}]}
        
        details = client.get_video_details(["vid1"])
        
        assert len(details) == 1
        assert details[0]["id"] == "vid1"
        mock_req.assert_called_once_with("videos", {"part": "snippet,statistics,contentDetails", "id": "vid1"})

def test_get_comments_disabled_handling(client):
    with patch("requests.get") as mock_get:
        response_403 = MagicMock()
        response_403.status_code = 403
        
        # Mocking error response body for disabled comments
        response_403.json.return_value = {
            "error": {
                "errors": [
                    {
                        "domain": "youtube.commentThread",
                        "reason": "commentsDisabled",
                        "message": "The video identified by the <code>videoId</code> parameter has enabled comments disabled."
                    }
                ],
                "code": 403,
                "message": "The video identified by the <code>videoId</code> parameter has enabled comments disabled."
            }
        }
        response_403.raise_for_status.side_effect = requests.HTTPError("Forbidden", response=response_403)
        mock_get.return_value = response_403

        comments = client.get_comments("disabled_video_id")
        
        assert comments == []
