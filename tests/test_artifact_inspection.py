import unittest
import inspect
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inspect_delivery_artifact as target

class ArtifactInspectionContractTests(unittest.TestCase):
    def test_probe_requires_both_streams(self):
        source=inspect.getsource(target.probe)
        self.assertIn("missing video stream", source)
        self.assertIn("missing audio stream", source)

    def test_portrait_short_fps_audio_bounds_are_enforced(self):
        source=inspect.getsource(target.main)
        for phrase in ("video is not portrait","duration outside short-form bounds","fps outside accepted range","audio sample rate too low"):
            self.assertIn(phrase, source)

    def test_dynamic_representative_frames_and_media_detectors_exist(self):
        source=inspect.getsource(target.frame_metrics)
        self.assertIn('"start"', source)
        self.assertIn('"middle"', source)
        self.assertIn('"end"', source)
        self.assertIn('"-frames:v"', source)
        self.assertIn('"fps=1"', source)
        detector=inspect.getsource(target.detect_media_issues)
        self.assertIn("blackdetect", detector)
        self.assertIn("freezedetect", detector)

if __name__=="__main__":
    unittest.main()
