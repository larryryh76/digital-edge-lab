import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DeliveryRegressionTests(unittest.TestCase):
    def test_delivery_report_has_explicit_review_and_publish_state(self):
        source = (ROOT / "src/pipeline.py").read_text(encoding="utf-8")
        self.assertIn('"human_review_required": True', source)
        self.assertIn('"youtube": "not_implemented"', source)
        self.assertIn('"tiktok": "not_implemented"', source)

    def test_final_media_qa_and_contact_sheet_are_required(self):
        source = (ROOT / "src/pipeline.py").read_text(encoding="utf-8")
        self.assertIn("ffprobe", source)
        self.assertIn('"contact_sheet_created": "PASS"', source)
        self.assertIn("contact-sheet.jpg", source)
        self.assertIn("narration.wav", source)

    def test_source_reachability_is_not_claim_support(self):
        source = (ROOT / "src/pipeline.py").read_text(encoding="utf-8")
        self.assertIn('"reachability_only": True', source)
        self.assertIn("editorial review is still required", source)
        self.assertIn('"source_claim_support": "HUMAN_REVIEW_REQUIRED"', source)

    def test_failure_artifact_does_not_depend_on_success_report(self):
        workflow = (ROOT / ".github/workflows/generate-pilot.yml").read_text(encoding="utf-8")
        # Either status-check form is valid: failure/cancelled already overrides the implicit success() check.
        self.assertRegex(workflow, r"if:\s*\$\{\{[^\n]*failure\(\)[^\n]*cancelled\(\)[^\n]*\}\}")
        self.assertIn("output/**", workflow)
        self.assertIn("digital-edge-lab-failure-", workflow)

    def test_blender_ffmpeg_output_path_lets_blender_add_extension(self):
        source = (ROOT / "src/blender_scene.py").read_text(encoding="utf-8")
        self.assertIn('with_suffix("")', source)
        smoke = (ROOT / "tests/blender_smoke.py").read_text(encoding="utf-8")
        self.assertIn("with_suffix('')", smoke)

    def test_blender_video_format_uses_image_settings_property(self):
        scene = (ROOT / "src/blender_scene.py").read_text(encoding="utf-8")
        smoke = (ROOT / "tests/blender_smoke.py").read_text(encoding="utf-8")
        self.assertIn('scene.render.image_settings.file_format = "FFMPEG"', scene)
        self.assertIn("s.render.image_settings.file_format = 'FFMPEG'", smoke)
        self.assertNotIn("scene.render.file_format = ", scene)
        self.assertNotIn("s.render.file_format = ", smoke)


    def test_gemini_fallback_prioritizes_current_models_and_skips_image_models(self):
        from src.pipeline import ordered_model_candidates
        available = {
            "gemini-3.8-flash": ["generateContent"],
            "gemini-3.7-flash": ["generateContent"],
            "gemini-2.5-flash": ["generateContent"],
            "gemini-3.8-flash-image": ["generateContent"],
            "gemini-3.8-flash-tts": ["generateContent"],
            "gemini-3.1-flash-tts-preview": ["generateContent"],
        }
        text_models = ordered_model_candidates("gemini-3.8-flash", available, audio=False)
        self.assertEqual(text_models[:2], ["gemini-3.8-flash", "gemini-3.7-flash"])
        self.assertNotIn("gemini-2.5-flash", text_models)
        self.assertNotIn("gemini-3.8-flash-image", text_models)
        tts_models = ordered_model_candidates("gemini-3.8-flash-tts", available, audio=True)
        self.assertEqual(tts_models[:2], ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview"])
        self.assertNotIn("gemini-3.8-flash-image", tts_models)

    def test_blender_scene_deadline_is_bounded(self):
        source = (ROOT / "src/pipeline.py").read_text(encoding="utf-8")
        self.assertRegex(source, r"timeout=150")
        self.assertIn("scene_", source)
        self.assertIn("_blender.log", source)

    def test_memory_is_written_after_render_qa(self):
        source = (ROOT / "src/pipeline.py").read_text(encoding="utf-8")
        self.assertLess(source.index("video, duration, audio_qa = render(data, wav)"),
                        source.index('(OUT / "channel-memory.json").write_text'))

if __name__ == "__main__":
    unittest.main()
