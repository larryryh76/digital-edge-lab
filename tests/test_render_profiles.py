"""Render profile contracts: preview remains cheap; production is native quality."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from render_profiles import get_render_profile, profile_names


class RenderProfileTests(unittest.TestCase):
    def test_preview_profile_preserves_the_existing_cpu_ci_contract(self):
        profile = get_render_profile("preview")
        self.assertEqual(profile["render_width"], 288)
        self.assertEqual(profile["render_height"], 512)
        self.assertEqual(profile["render_fps"], 12)
        self.assertEqual(profile["output_width"], 720)
        self.assertEqual(profile["output_height"], 1280)
        self.assertEqual(profile["output_fps"], 24)
        self.assertEqual(profile["engine"], "BLENDER_EEVEE_NEXT")
        self.assertFalse(profile["require_gpu"])

    def test_production_profile_renders_native_1080p_at_24_fps(self):
        profile = get_render_profile("production")
        self.assertEqual(profile["render_width"], 1080)
        self.assertEqual(profile["render_height"], 1920)
        self.assertEqual(profile["render_fps"], 24)
        self.assertEqual(profile["output_width"], 1080)
        self.assertEqual(profile["output_height"], 1920)
        self.assertEqual(profile["output_fps"], 24)
        self.assertEqual(profile["engine"], "CYCLES")
        self.assertGreaterEqual(profile["samples"], 32)
        self.assertTrue(profile["denoise"])
        self.assertTrue(profile["require_gpu"])
        self.assertEqual(profile["render_workers"], 1)

    def test_unknown_profile_fails_instead_of_silently_downgrading(self):
        with self.assertRaises(ValueError):
            get_render_profile("cinematic-magic")

    def test_profile_is_returned_as_a_copy(self):
        profile = get_render_profile("preview")
        profile["render_width"] = 1
        self.assertEqual(get_render_profile("preview")["render_width"], 288)

    def test_only_explicit_supported_profiles_are_exposed(self):
        self.assertEqual(profile_names(), ("preview", "production"))


if __name__ == "__main__":
    unittest.main()
