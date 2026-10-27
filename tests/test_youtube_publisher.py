import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from youtube_publisher import validate_metadata, PublishingError, upload_video


class YouTubePublisherTests(unittest.TestCase):
    def test_metadata_validation_and_private_default(self):
        meta = validate_metadata({"title": "Episode", "description": "Test"})
        self.assertEqual(meta["privacyStatus"], "private")
        with self.assertRaises(ValueError):
            validate_metadata({"title": ""})
        with self.assertRaises(ValueError):
            validate_metadata({"title": "x" * 101})

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
