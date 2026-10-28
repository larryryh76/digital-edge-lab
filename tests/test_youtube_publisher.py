import sys
import tempfile
import unittest
import types
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from youtube_publisher import (validate_metadata, PublishingError, upload_video, content_fingerprint,
                              fetch_video_analytics, build_youtube_analytics_service)


class YouTubePublisherTests(unittest.TestCase):
    def test_metadata_validation_and_private_default(self):
        meta = validate_metadata({"title": "Episode", "description": "Test"})
        self.assertEqual(meta["privacyStatus"], "private")
        self.assertEqual(meta["publishAt"], "")
        self.assertEqual(meta["playlistId"], "")
        self.assertEqual(meta["thumbnailPath"], "")
        with self.assertRaises(ValueError):
            validate_metadata({"title": ""})
        with self.assertRaises(ValueError):
            validate_metadata({"title": "x" * 101})

    def test_content_fingerprint_does_not_change_with_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "video.mp4"
            path.write_bytes(b"same bytes")
            first = content_fingerprint(path, {"title": "A"})
            second = content_fingerprint(path, {"title": "B"})
            self.assertEqual(first, second)

    def test_uncertain_upload_is_not_blindly_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "video.mp4"
            path.write_bytes(b"fake-not-a-real-video")
            state = Path(temp) / "state.json"
            parent_module = types.ModuleType("googleapiclient")
            parent_module.__path__ = []
            media_module = types.ModuleType("googleapiclient.http")
            media_module.MediaFileUpload = lambda *args, **kwargs: object()
            class Request:
                def next_chunk(self):
                    raise RuntimeError("simulated interrupted upload")
            class Videos:
                def insert(self, **kwargs):
                    return Request()
            class Service:
                def videos(self):
                    return Videos()
            with patch.dict("sys.modules", {"googleapiclient": parent_module,
                                            "googleapiclient.http": media_module}):
                with self.assertRaisesRegex(PublishingError, "outcome is uncertain"):
                    upload_video(path, {"title": "Episode"}, service=Service(), state_file=state)
                with self.assertRaisesRegex(PublishingError, "duplicate upload blocked"):
                    upload_video(path, {"title": "Episode"}, service=Service(), state_file=state)

    def test_analytics_uses_real_query_result_and_validates_date_range(self):
        class Query:
            def execute(self):
                return {"rows": [[12, 3, 1, 8.5]], "columnHeaders": [
                    {"name": "views"}, {"name": "likes"}, {"name": "comments"},
                    {"name": "estimatedMinutesWatched"}]}
        class Reports:
            def query(self, **kwargs):
                self.kwargs = kwargs
                return Query()
        class Service:
            def __init__(self):
                self.report_api = Reports()
            def reports(self):
                return self.report_api
        service = Service()
        result = fetch_video_analytics("video123", "2026-10-01", "2026-10-10",
                                       analytics_service=service)
        self.assertEqual(result["rows"][0][0], 12)
        self.assertEqual(service.report_api.kwargs["filters"], "video==video123")
        with self.assertRaisesRegex(ValueError, "cannot end in the future"):
            fetch_video_analytics("video123", "2026-10-01", "2099-01-01",
                                  analytics_service=service)

    def test_analytics_oauth_missing_client_is_a_clear_blocker(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(PublishingError, "OAuth client file missing"):
                build_youtube_analytics_service(client_secret_file=Path(temp) / "missing.json",
                                                token_file=Path(temp) / "token.json")

    def test_missing_video_and_non_private_requires_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "video.mp4"
            with self.assertRaises(PublishingError):
                upload_video(path, {"title": "Episode"})
            path.write_bytes(b"fake-not-a-real-video")
            with self.assertRaises(PublishingError):
                upload_video(path, {"title": "Episode", "privacy_status": "public"}, service=object())


if __name__ == "__main__":
    unittest.main()
