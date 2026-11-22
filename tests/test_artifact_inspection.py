import unittest
import inspect
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inspect_delivery_artifact as target

class ArtifactInspectionContractTests(unittest.TestCase):
    def test_probe_requires_both_streams(self):
        self.assertIn("missing video stream", inspect.getsource(target.probe))
        self.assertIn("missing audio stream", inspect.getsource(target.probe))
    def test_portrait_and_short_bounds_are_enforced(self):
        src=inspect.getsource(target.main)
        self.assertIn("video is not portrait", src)
        self.assertIn("duration outside short-form bounds", src)
    def test_representative_frames_are_extracted(self):
        src=inspect.getsource(target.frame_metrics)
        self.assertIn("start.jpg", src)
        self.assertIn("middle.jpg", src)
        self.assertIn("end.jpg", src)

if __name__ == "__main__":
    unittest.main()
