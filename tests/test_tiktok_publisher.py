import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tiktok_publisher import TikTokError, prepare_for_manual_upload, publish_video


class TikTokPublisherTests(unittest.TestCase):
    def test_manual_package_is_not_mislabeled_as_published(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "episode.mp4"
            source.write_bytes(b"test media")
            result = prepare_for_manual_upload(source, "Episode", Path(temp) / "prepared")
            self.assertEqual(result["status"], "ready_for_manual_upload")
            self.assertFalse(result["platform_publish_verified"])
            self.assertTrue((Path(temp) / "prepared" / "tiktok-package.json").exists())

    def test_publish_requires_explicit_approval_and_token(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "episode.mp4"
            source.write_bytes(b"test media")
            with self.assertRaisesRegex(TikTokError, "explicit approval"):
                publish_video(source, "Episode", approval=False, access_token="token",
                              state_file=Path(temp) / "state.json")
            with self.assertRaisesRegex(TikTokError, "TIKTOK_ACCESS_TOKEN"):
                publish_video(source, "Episode", approval=True, access_token="",
                              state_file=Path(temp) / "state.json")


if __name__ == "__main__":
    unittest.main()
