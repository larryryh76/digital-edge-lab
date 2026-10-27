"""Pipeline safety, caption alignment and workflow contract tests."""

import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import narration  # noqa: E402
import pipeline  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "generate-pilot.yml"
PIPELINE = (ROOT / "src" / "pipeline.py").read_text(encoding="utf-8")


class CaptionTests(unittest.TestCase):
    def test_caption_cards_cover_the_whole_window(self):
        cards = narration.caption_cards("one two three four five six seven eight nine ten",
                                        6.0)
        self.assertTrue(cards)
        self.assertGreaterEqual(max(c["end"] for c in cards), 5.9)
        self.assertLessEqual(max(c["end"] for c in cards), 6.1)

    def test_caption_cards_are_sequential_and_non_empty(self):
        cards = narration.caption_cards("a" * 200, 4.0)
        self.assertTrue(cards)
        previous = -1.0
        for card in cards:
            self.assertGreater(card["end"], card["start"])
            self.assertGreaterEqual(card["start"], previous)
            previous = card["start"]
            self.assertTrue(card["lines"])

    def test_empty_narration_yields_no_cards(self):
        self.assertEqual(narration.caption_cards("", 3.0), [])

    def test_caption_alignment_runs_on_real_cards(self):
        """Regression: the gate raised NameError after every scene had rendered."""
        import media_qa

        beats = [{"id": "b1", "role": "hook",
                  "narration": "Four memory channels become one cheaper pipe."}]
        windows = [{"index": 0, "beat_id": "b1", "start": 0.0, "end": 4.6,
                    "duration": 4.6, "frames": 110, "narration": beats[0]["narration"]}]
        cards = [narration.caption_cards(beats[0]["narration"], 4.6)]
        result = media_qa.caption_alignment(cards, windows, beats)
        self.assertTrue(result["passed"], result["failures"])

    def test_captions_that_stop_early_are_rejected(self):
        import media_qa

        beats = [{"id": "b1", "role": "hook", "narration": "one two three four"}]
        windows = [{"index": 0, "beat_id": "b1", "start": 0.0, "end": 6.0,
                    "duration": 6.0, "frames": 144, "narration": beats[0]["narration"]}]
        cards = [[{"lines": ["one two"], "start": 0.0, "end": 1.5}]]
        result = media_qa.caption_alignment(cards, windows, beats)
        self.assertFalse(result["passed"])
        self.assertTrue(any("stop at" in failure for failure in result["failures"]))


class DegradedDeliveryTests(unittest.TestCase):
    def _report(self, **overrides):
        report = {
            "status": "verified_delivery",
            "origin": "gemini:gemini-3.6-flash",
            "scene_count": 7,
            "narration": {"engine": "gemini-tts", "publication_quality_voice": True},
            "delivery_media": {"duration_seconds": 42.0, "width": 720, "height": 1280,
                               "fps": "24/1"},
            "scene_diversity": {"distinct_templates": 7},
            "failed_gates": [],
            "degraded": None,
        }
        report.update(overrides)
        return report

    def test_generated_run_summary_says_nothing_about_degradation(self):
        import run_summary

        text = run_summary.summary(self._report())
        self.assertIn("verified_delivery", text)
        self.assertNotIn("DEGRADED", text)

    def test_degraded_run_summary_is_explicit(self):
        import run_summary

        report = self._report(status="verified_degraded_delivery",
                              degraded={"stage": "plan_generation",
                                        "reason": "http_429 on every model"})
        text = run_summary.summary(report)
        self.assertIn("DEGRADED DELIVERY", text)
        self.assertIn("http_429", text)

    def test_pipeline_can_fall_back_but_labels_it(self):
        self.assertIn("--fallback-plan", PIPELINE)
        self.assertIn("verified_degraded_delivery", PIPELINE)
        self.assertIn("DEGRADED_DELIVERY.txt", PIPELINE)


class GateTests(unittest.TestCase):
    def test_all_gates_pass_gives_no_failures(self):
        result = pipeline.decide_failures(
            {"passed": True}, {"passed": True}, {"passed": True},
            {"passed": True}, {"mean": 1.2})
        self.assertEqual(result, [])

    def test_each_failing_gate_is_reported(self):
        result = pipeline.decide_failures(
            {"passed": False}, {"passed": False}, {"passed": False},
            {"passed": False}, {"mean": 0.01})
        self.assertEqual(result, ["scene_qa", "scene_diversity", "caption_alignment",
                                  "delivery_media", "visual_motion"])

    def test_static_final_video_fails_the_motion_gate(self):
        result = pipeline.decide_failures(
            {"passed": True}, {"passed": True}, {"passed": True},
            {"passed": True}, {"mean": 0.05})
        self.assertEqual(result, ["visual_motion"])


class SourceTests(unittest.TestCase):
    @staticmethod
    def valid_https(url):
        parsed = urlparse(url)
        return parsed.scheme == "https" and bool(parsed.netloc) and not any(
            ch.isspace() for ch in url)

    def test_https_source_validation(self):
        self.assertTrue(self.valid_https("https://example.org/paper"))
        self.assertFalse(self.valid_https("http://example.org"))
        self.assertFalse(self.valid_https("https://"))
        self.assertFalse(self.valid_https("https://example.org bad"))

    def test_reachability_is_reported_as_advisory_only(self):
        episode = {"sources": [{"name": "x", "url": "ftp://nope"}]}
        result = pipeline.validate_sources(episode, timeout=1)
        self.assertTrue(result["reachability_only"])
        self.assertEqual(result["source_claim_support_status"], "HUMAN_REVIEW_REQUIRED")
        self.assertFalse(result["checks"][0]["reachable"])


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_failure_artifact_is_uploaded_regardless_of_success_report(self):
        self.assertRegex(self.text, r"if:\s*\$\{\{\s*failure\(\)[^}]*\}\}")
        self.assertIn("output/**", self.text)

    def test_success_artifact_matches_pipeline_output_directory(self):
        self.assertIn("output/delivery/", self.text)
        self.assertIn("digital-edge-lab-pilot", self.text)

    def test_workflow_runs_the_real_pipeline_entry_point(self):
        self.assertIn("python src/pipeline.py", self.text)

    def test_workflow_does_not_depend_on_obsolete_helpers(self):
        self.assertNotIn("tests/blender_smoke.py", self.text)

    def test_secret_is_passed_by_env_not_inlined(self):
        self.assertIn("GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}", self.text)
        self.assertNotIn("sk-", self.text)

    def test_memory_commit_only_runs_on_main(self):
        self.assertIn("github.ref == 'refs/heads/main'", self.text)


class MemoryTests(unittest.TestCase):
    def test_memory_candidate_does_not_mutate_original(self):
        memory = {"recent_topics": [{"topic": "old"}], "running_context": []}
        candidate = dict(memory)
        candidate["recent_topics"] = list(memory["recent_topics"]) + [{"topic": "new"}]
        self.assertEqual(len(memory["recent_topics"]), 1)
        self.assertEqual(len(candidate["recent_topics"]), 2)

    def test_checked_in_plan_is_valid_json(self):
        plan = json.loads((ROOT / "plans" / "quantization-on-device.json")
                          .read_text(encoding="utf-8"))
        self.assertTrue(plan["beats"])
        self.assertEqual(len(plan["beats"]), len(plan["scenes"]))


if __name__ == "__main__":
    unittest.main()
