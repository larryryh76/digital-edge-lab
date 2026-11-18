"""Tests for selecting and verifying Poly Haven asset file metadata."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyhaven_assets import select_hdri_file


class PolyHavenAssetTests(unittest.TestCase):
    def test_prefers_requested_resolution_and_exr(self):
        payload = {
            "message": "OK",
            "data": {
                "hdri": {
                    "1k": {
                        "exr": {"url": "https://cdn.example/1k.exr", "md5": "abc"},
                        "hdr": {"url": "https://cdn.example/1k.hdr", "md5": "def"},
                    },
                    "2k": {"exr": {"url": "https://cdn.example/2k.exr", "md5": "ghi"}},
                }
            },
        }
        result = select_hdri_file(payload)
        self.assertEqual(result["resolution"], "1k")
        self.assertEqual(result["format"], "exr")
        self.assertEqual(result["url"], "https://cdn.example/1k.exr")

    def test_falls_back_to_hdr_when_exr_is_unavailable(self):
        payload = {"data": {"hdri": {"1k": {
            "hdr": {"url": "https://cdn.example/1k.hdr", "md5": "def"}
        }}}}
        result = select_hdri_file(payload)
        self.assertEqual(result["format"], "hdr")

    def test_fails_clearly_when_asset_has_no_downloadable_hdri(self):
        with self.assertRaises(ValueError):
            select_hdri_file({"data": {"hdri": {}}})


if __name__ == "__main__":
    unittest.main()
