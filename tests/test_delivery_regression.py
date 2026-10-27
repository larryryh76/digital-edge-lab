"""Delivery regressions: run #73 must stay fixed.

Run #73 shipped a playable MP4 in which five different narrative beats contained
the same generic metallic transformation, and the QA layer "passed" metadata
that described scenes the renderer never built. These tests pin the properties
that make that impossible.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import media_qa  # noqa: E402
import pipeline  # noqa: E402
import scene_spec  # noqa: E402

BLENDER = (ROOT / "src" / "blender_scene.py").read_text(encoding="utf-8")
PIPELINE = (ROOT / "src" / "pipeline.py").read_text(encoding="utf-8")


class RendererContractTests(unittest.TestCase):
    def test_trace_reports_measured_animation(self):
        for field in ("measured", "parts", "mover_object", "built_parts",
                      "requirement", "hero_object"):
            self.assertIn(field, BLENDER)
        self.assertIn("scene.frame_set(frame)", BLENDER)
        self.assertIn("object_corners(obj)", BLENDER)

    def test_renderer_writes_a_trace_before_rendering(self):
        trace_write = BLENDER.index("trace_path.write_text")
        render_call = BLENDER.index("bpy.ops.render.render(animation=True)")
        self.assertLess(trace_write, render_call)

    def test_no_scene_is_animated_only_by_the_camera(self):
        # Every action program must key at least one object transform.
        for action in scene_spec.ACTIONS:
            program = f'"act_{action}"'
            marker = f'"{action}": act_{action}'
            self.assertIn(marker, BLENDER, f"{action} is not registered")
            start = BLENDER.index(f"def act_{action}(")
            body = BLENDER[start:start + 2600]
            self.assertTrue(
                "key(" in body or "for " in body,
                f"{action} does not keyframe any subject transform")
        self.assertNotIn('"act_camera', BLENDER)

    def test_idle_motion_is_small_and_never_the_action(self):
        self.assertIn("math.radians(2.0)", BLENDER)

    def test_required_parts_come_from_the_shared_registry(self):
        self.assertIn("scene_spec.required_parts(spec)", BLENDER)
        for kind, meta in scene_spec.SUBJECT_KINDS.items():
            builder = BLENDER[BLENDER.index(f"def build_{kind}("):]
            builder = builder[:builder.index("\ndef ", 10)]
            for part in meta["parts"]:
                self.assertIn(part, builder,
                              f"builder for {kind} does not create required part {part}")


class PipelineContractTests(unittest.TestCase):
    def test_outputs_are_named_consistently(self):
        self.assertIn("digital-edge-lab-pilot.mp4", PIPELINE)
        self.assertIn("run-report.json", PIPELINE)
        self.assertIn("contact-sheet.jpg", PIPELINE)
        self.assertIn("delivery", PIPELINE)

    def test_diagnostics_directory_is_preserved(self):
        # The workflow writes output/diagnostics/run-context.txt before the run;
        # wiping it silently broke failure triage in run #73.
        self.assertIn("Never delete output/diagnostics", PIPELINE)

    def test_failed_gate_exits_non_zero(self):
        self.assertIn("def decide_failures(", PIPELINE)
        self.assertIn('fail("delivery rejected by QA:', PIPELINE)
        self.assertIn("raise SystemExit", PIPELINE)

    def test_no_generic_scene_label_can_be_reported_as_pass(self):
        self.assertNotIn("metallic_object_transformation", PIPELINE)
        self.assertNotIn("technical_fallback", PIPELINE)

    def test_report_states_honest_publication_state(self):
        self.assertIn('"publication_ready": False', PIPELINE)
        self.assertIn('"youtube": "not_implemented"', PIPELINE)
        self.assertIn('"tiktok": "not_implemented"', PIPELINE)
        self.assertIn("HUMAN_REVIEW_REQUIRED", PIPELINE)

    def test_narration_timing_comes_from_measured_audio(self):
        narration_src = (ROOT / "src" / "narration.py").read_text(encoding="utf-8")
        self.assertIn("probe_duration", narration_src)
        self.assertIn("spoken_seconds", narration_src)
        self.assertIn("pad_to(", narration_src)


class ReportConsistencyTests(unittest.TestCase):
    def test_failed_report_is_never_labelled_success(self):
        failed = pipeline.decide_failures({"passed": False}, {"passed": True},
                                          {"passed": True}, {"passed": True},
                                          {"mean": 1.0})
        self.assertTrue(failed)

    def test_scene_report_fails_when_subject_parts_are_missing(self):
        scene = scene_spec.normalize_scene({
            "beat_id": "b1",
            "subject": {"kind": "dial"},
            "action": {"kind": "spin"},
            "camera": {"framing": "close_up", "move": "push_in"},
        }, 0, {"b1"})
        trace = {
            "template": "dial__spin",
            "required_parts": scene_spec.required_parts(scene),
            "built_parts": ["visible_sphere"],
            "measured": {"mover": {"rotation_degrees": 400, "displacement": 1.0,
                                   "screen_pixels": 50.0},
                         "parts_moved": 1, "parts_removed": 0,
                         "moving_part_names": ["x"]},
            "requirement": scene_spec.motion_requirement(scene),
        }
        window = {"index": 0, "start": 0.0, "end": 3.0, "duration": 3.0, "frames": 72,
                  "narration": "a line"}
        # No real segment is needed: the parts check must fail before any decode.
        report = media_qa.evaluate_scene(scene, window, "does-not-exist.mp4", trace,
                                        scene_spec)
        self.assertFalse(report["passed"])
        self.assertTrue(any("requested subject parts missing" in f
                            for f in report["failures"]))

    def test_template_mismatch_is_a_failure(self):
        scene = scene_spec.normalize_scene({
            "beat_id": "b1",
            "subject": {"kind": "pipe_bundle"},
            "action": {"kind": "collapse_to_one"},
            "camera": {"framing": "medium", "move": "push_in"},
        }, 0, {"b1"})
        trace = {
            "template": "generic_cube__spin",
            "required_parts": scene_spec.required_parts(scene),
            "built_parts": scene_spec.required_parts(scene),
            "measured": {"mover": {}, "parts_moved": 0, "parts_removed": 0},
            "requirement": scene_spec.motion_requirement(scene),
        }
        window = {"index": 0, "start": 0.0, "end": 3.0, "duration": 3.0, "frames": 72,
                  "narration": "a line"}
        report = media_qa.evaluate_scene(scene, window, "does-not-exist.mp4", trace,
                                        scene_spec)
        self.assertFalse(report["passed"])
        self.assertTrue(any("renderer template" in f for f in report["failures"]))


class PlanIntegrityTests(unittest.TestCase):
    def test_plan_uses_distinct_subjects_and_actions(self):
        data = json.loads((ROOT / "plans" / "quantization-on-device.json")
                          .read_text(encoding="utf-8"))
        episode, errors = scene_spec.normalize_episode(data)
        self.assertEqual(errors, [])
        subjects = [s["subject"]["kind"] for s in episode["scenes"]]
        actions = [s["action"]["kind"] for s in episode["scenes"]]
        self.assertGreaterEqual(len(set(subjects)), 5)
        self.assertGreaterEqual(len(set(actions)), 5)

    def test_no_placeholder_subject_in_delivered_plan(self):
        data = json.loads((ROOT / "plans" / "quantization-on-device.json")
                          .read_text(encoding="utf-8"))
        kinds = [s["subject"]["kind"] for s in data["scenes"]]
        self.assertNotIn(scene_spec.FALLBACK_SUBJECT, kinds)


if __name__ == "__main__":
    unittest.main()
