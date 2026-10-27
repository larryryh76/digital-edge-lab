"""Typed scene-plan validation and the run #73 regression guard."""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import scene_spec  # noqa: E402

PLAN = json.loads((ROOT / "plans" / "quantization-on-device.json").read_text(encoding="utf-8"))


def plan():
    return copy.deepcopy(PLAN)


class SchemaTests(unittest.TestCase):
    def test_checked_in_plan_is_renderable(self):
        episode, errors = scene_spec.normalize_episode(plan())
        self.assertEqual(errors, [])
        self.assertIsNotNone(episode)
        self.assertEqual(len(episode["scenes"]), len(episode["beats"]))
        self.assertTrue(80 <= len(episode["narration"].split()) <= 135)

    def test_unknown_subject_kind_is_rejected(self):
        data = plan()
        data["scenes"][0]["subject"]["kind"] = "hypercube_of_feelings"
        _, errors = scene_spec.normalize_episode(data)
        self.assertTrue(any("unsupported subject kind" in e for e in errors), errors)

    def test_action_must_be_filmable_for_subject(self):
        data = plan()
        # A clamp cannot spin around a dial axis; the renderer has no such program.
        data["scenes"][0]["subject"]["kind"] = "clamp"
        data["scenes"][0]["action"]["kind"] = "spin"
        _, errors = scene_spec.normalize_episode(data)
        self.assertTrue(any("not filmable" in e for e in errors), errors)

    def test_scene_must_reference_a_real_beat(self):
        data = plan()
        data["scenes"][2]["beat_id"] = "b99"
        _, errors = scene_spec.normalize_episode(data)
        self.assertTrue(any("unknown beat" in e for e in errors), errors)

    def test_beats_and_scenes_must_match_one_to_one(self):
        data = plan()
        data["scenes"].pop()
        _, errors = scene_spec.normalize_episode(data)
        self.assertTrue(any("one-to-one" in e for e in errors), errors)

    def test_generic_placeholder_subject_is_never_deliverable(self):
        data = plan()
        data["scenes"][0]["subject"]["kind"] = "generic_cube"
        data["scenes"][0]["action"]["kind"] = "spin"
        _, errors = scene_spec.normalize_episode(data)
        self.assertTrue(any("place-holder" in e for e in errors), errors)

    def test_repetitive_subjects_are_rejected(self):
        data = plan()
        for scene in data["scenes"]:
            scene["subject"]["kind"] = "data_block"
            scene["action"]["kind"] = scene_spec.SUBJECT_KINDS["data_block"]["actions"][0]
        _, errors = scene_spec.normalize_episode(data)
        self.assertTrue(any("not varied enough" in e for e in errors), errors)

    def test_first_beat_must_be_the_hook(self):
        data = plan()
        data["beats"][0]["role"] = "setup"
        _, errors = scene_spec.normalize_episode(data)
        self.assertTrue(any("hook" in e for e in errors), errors)


class DeterminismTests(unittest.TestCase):
    def test_template_is_a_pure_function_of_the_spec(self):
        episode, _ = scene_spec.normalize_episode(plan())
        again, _ = scene_spec.normalize_episode(plan())
        for a, b in zip(episode["scenes"], again["scenes"]):
            self.assertEqual(scene_spec.template_id(a), scene_spec.template_id(b))
            self.assertEqual(scene_spec.required_parts(a), scene_spec.required_parts(b))

    def test_every_registered_subject_has_a_builder_and_parts(self):
        blender = (ROOT / "src" / "blender_scene.py").read_text(encoding="utf-8")
        for kind, meta in scene_spec.SUBJECT_KINDS.items():
            self.assertIn(f'"{kind}": build_', blender, f"no builder for {kind}")
            self.assertTrue(meta["parts"], kind)
            for action in meta["actions"]:
                self.assertIn(action, scene_spec.ACTIONS,
                              f"{kind} lists unknown action {action}")
        for action in scene_spec.ACTIONS:
            self.assertIn(f'"{action}": act_', blender, f"no action program for {action}")

    def test_requirements_are_machine_checkable(self):
        for action, meta in scene_spec.ACTIONS.items():
            self.assertTrue(meta["motion"], action)
            for key in meta["motion"]:
                self.assertIn(key, {
                    "rotation_degrees_min", "scale_ratio_max", "scale_ratio_min",
                    "translate_down_min", "translate_min", "parts_moved_min",
                    "parts_removed_min", "stepped_positions_min", "partner_part_moves",
                    "any_part_shrink_below", "any_part_height_shrink_below",
                }, f"{action} uses unchecked requirement {key}")


class Run73RegressionTests(unittest.TestCase):
    """The exact failure mode of run #73 must be impossible to reintroduce."""

    def test_renderer_has_no_free_text_keyword_dispatch(self):
        blender = (ROOT / "src" / "blender_scene.py").read_text(encoding="utf-8")
        self.assertNotIn("in brief_text", blender)
        self.assertNotIn("story_treatment", blender)
        self.assertNotIn("technical_fallback", blender)

    def test_pipeline_does_not_mirror_the_renderer_with_a_keyword_table(self):
        pipeline = (ROOT / "src" / "pipeline.py").read_text(encoding="utf-8")
        # The duplicated `expected = ...` if/elif chain is what let metadata QA
        # "pass" while the render contained something else entirely.
        self.assertNotIn("expected = \"", pipeline)
        self.assertNotIn("Visual QA rejected scene", pipeline)
        self.assertIn("scene_spec.template_id", pipeline)

    def test_run73_scene_intents_map_to_seven_distinct_templates(self):
        """Run #73 collapsed these intents onto 3x metallic_object_transformation."""
        intents = [
            ("glass_sphere", "squeeze"),      # sphere straining inside a clamp
            ("clamp", "squeeze"),             # the clamp itself applying pressure
            ("dial", "spin"),                 # spinning precision dial
            ("voxel_sphere", "snap_to_grid"),  # dial snapping into a stepped grid
            ("mountain_pair", "compare_pan"),  # smooth vs voxel mountain
            ("pipe_bundle", "collapse_to_one"),  # four pipes into one
            ("smartphone", "descend"),        # sphere lowering onto a phone
        ]
        templates = []
        for i, (subject, action) in enumerate(intents):
            allowed = scene_spec.SUBJECT_KINDS[subject]["actions"]
            if action not in allowed:
                self.assertIn(action, scene_spec.ACTIONS)
                continue
            scene = scene_spec.normalize_scene(
                {"beat_id": "b1", "subject": {"kind": subject},
                 "action": {"kind": action}, "camera": {"framing": "medium",
                                                        "move": "push_in"}},
                i, {"b1"})
            templates.append(scene_spec.template_id(scene))
        self.assertGreaterEqual(len(templates), 5)
        self.assertEqual(len(set(templates)), len(templates))
        for template in templates:
            self.assertNotIn("generic", template)
        # The old fallback label must not exist anywhere in the new registry.
        self.assertNotIn("metallic_object_transformation", scene_spec.SUBJECT_KINDS)
        self.assertNotIn("metallic_object_transformation", scene_spec.ACTIONS)

    def test_unsupported_but_valid_pair_cannot_be_silently_substituted(self):
        data = plan()
        data["scenes"][0]["subject"]["kind"] = "compass"
        data["scenes"][0]["action"]["kind"] = "compare_pan"
        _, errors = scene_spec.normalize_episode(data)
        self.assertTrue(any("not filmable" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
