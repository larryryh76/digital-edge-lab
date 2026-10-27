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
