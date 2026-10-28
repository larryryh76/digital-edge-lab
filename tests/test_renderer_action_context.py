"""Regression guard for action handlers calling primitives on Ctx instead of Studio."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "blender_scene.py").read_text(encoding="utf-8")


class ActionContextRegressionTests(unittest.TestCase):
    def test_actions_do_not_call_unimplemented_ctx_primitive_methods(self):
        # Ctx owns animation state, not geometry constructors. Studio owns primitives.
        bad = re.findall(r"\\bctx\\.(torus|sphere|box|cyl|cone|plane|label)\\s*\\(", SOURCE)
        self.assertEqual(bad, [], f"primitive calls must go through ctx.studio: {bad}")

    def test_studio_exposes_torus_used_by_action_handlers(self):
        self.assertRegex(SOURCE, r"def torus\\(self, name, loc, major, minor, mat")
        self.assertIn("ctx.studio.torus(", SOURCE)


if __name__ == "__main__":
    unittest.main()
