import json
import re
import tempfile
import unittest
from types import SimpleNamespace
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
        self.assertIn('["source_claim_support_status"] = "HUMAN_REVIEW_REQUIRED"', source)
        self.assertIn('["human_editorial_approval"] = "PENDING"', source)
        self.assertIn('"review_required"] = True', source)

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
        self.assertIn("gemini-2.5-flash", text_models)
        self.assertGreater(text_models.index("gemini-2.5-flash"), 1)
        self.assertNotIn("gemini-3.8-flash-image", text_models)
        tts_models = ordered_model_candidates("gemini-3.8-flash-tts", available, audio=True)
        self.assertEqual(tts_models[:2], ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview"])
        self.assertNotIn("gemini-3.8-flash-image", tts_models)

    def test_suffixed_blender_mp4_is_probed_normalized_and_accepted(self):
        from src.pipeline import normalize_blender_output
        with tempfile.TemporaryDirectory() as td:
            requested = Path(td) / "segment_00.mp4"
            actual = Path(td) / "segment_000001-0081.mp4"
            actual.write_bytes(b"x" * 4096)
            calls = []
            def fake_probe(command, **kwargs):
                calls.append(command[-1])
                return SimpleNamespace(returncode=0, stdout=json.dumps({
                    "streams": [{"codec_type": "video", "codec_name": "h264",
                                 "width": 360, "height": 640}],
                    "format": {"duration": "6.75"}
                }), stderr="")
            normalized = normalize_blender_output(requested, 0, probe_runner=fake_probe)
            self.assertEqual(normalized, requested)
            self.assertTrue(requested.is_file())
            self.assertFalse(actual.exists())
            self.assertEqual(calls, [str(actual)])
            self.assertEqual(requested.stat().st_size, 4096)

    def test_suffixed_blender_outputs_fail_if_ambiguous(self):
        from src.pipeline import normalize_blender_output
        with tempfile.TemporaryDirectory() as td:
            requested = Path(td) / "segment_01.mp4"
            (Path(td) / "segment_0100001-0081.mp4").write_bytes(b"x" * 2000)
            (Path(td) / "segment_0100082-0162.mp4").write_bytes(b"x" * 2000)
            with self.assertRaisesRegex(RuntimeError, "exactly one"):
                normalize_blender_output(requested, 1, probe_runner=lambda *a, **k: None)

    def test_visual_briefs_have_distinct_named_render_treatments(self):
        renderer = (ROOT / "src/blender_scene.py").read_text(encoding="utf-8")
        for treatment in ("copper_strawberry_word_laser", "three_token_blocks",
                          "macro_serial_number_reveal", "tokenization_lens_reveal",
                          "pi_sphere_compression", "misaligned_token_reassembly",
                          "brand_cube_reveal"):
            self.assertIn(treatment, renderer)
        self.assertIn('label("STRAWBERRY"', renderer)
        self.assertIn('cube("Cyan laser sweep"', renderer)
        self.assertIn('not any(k in brief_text for k in ("misaligned", "snap back", "gaps", "token gap", "sparks"))', renderer)
        self.assertIn('keyframe_insert(data_path="location", frame=end_frame)', renderer)

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
