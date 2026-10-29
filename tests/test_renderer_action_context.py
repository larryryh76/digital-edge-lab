"""Regression guard for action handlers calling primitives on Ctx instead of Studio."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "blender_scene.py").read_text(encoding="utf-8")


class ActionContextRegressionTests(unittest.TestCase):
    def test_actions_do_not_call_unimplemented_ctx_primitive_methods(self):
        # Ctx owns animation state, not geometry constructors. Studio owns primitives.
        for method in ("torus", "sphere", "box", "cyl", "cone", "plane", "label"):
            self.assertNotIn(f"ctx.{method}(", SOURCE, f"{method} must be called through ctx.studio")

    def test_studio_exposes_torus_used_by_action_handlers(self):
        self.assertIn("def torus(self, name, loc, major, minor, mat", SOURCE)
        self.assertIn("ctx.studio.torus(", SOURCE)

    def test_nonconstant_animation_curves_remain_continuously_moving(self):
        self.assertIn('kp.interpolation = "LINEAR"', SOURCE)
        self.assertNotIn('kp.interpolation = "BEZIER"\n\nframes, samples = measure', SOURCE)


if __name__ == "__main__":
    unittest.main()
