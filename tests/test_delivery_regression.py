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
        self.assertRegex(workflow, r"if:\s*\$\{\{\s*always\(\).*failure\(\).*cancelled\(\)")
        self.assertIn("output/**", workflow)
        self.assertIn("digital-edge-lab-failure-", workflow)

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
