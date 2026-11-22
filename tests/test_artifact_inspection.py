import unittest
import inspect
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inspect_delivery_artifact as target


class ArtifactInspectionContractTests(unittest.TestCase):
    def test_probe_requires_both_streams(self):
        source = inspect.getsource(target.probe)
        self.assertIn("missing video stream", source)
        self.assertIn("missing audio stream", source)

    def test_portrait_and_short_bounds_are_enforced(self):
        source = inspect.getsource(target.main)
        self.assertIn("video is not portrait", source)
        self.assertIn("duration outside short-form bounds", source)

    def test_representative_frames_are_extracted(self):
        source = inspect.getsource(target.frame_metrics)
        self.assertIn('("start", 0.5)', source)
        self.assertIn('("middle", 5.0)', source)
        self.assertIn('("end", 10.0)', source)
        self.assertIn('f"{label}.jpg"', source)
        self.assertIn('"-frames:v"', source)
        self.assertIn('"fps=1"', source)


if __name__ == "__main__":
    unittest.main()
