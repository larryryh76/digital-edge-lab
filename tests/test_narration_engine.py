"""Offline regression tests for neural voice selection."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import narration  # noqa: E402


class LocalVoiceSelectionTests(unittest.TestCase):
    def test_prefers_piper_when_cached_model_and_config_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "voice.onnx"
            model.write_bytes(b"model")
            Path(str(model) + ".json").write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"PIPER_MODEL": str(model)}):
                with patch("narration.shutil.which", side_effect=lambda name: "/usr/bin/piper" if name == "piper" else None):
                    self.assertEqual(narration.find_local_voice(), "piper")

    def test_uses_espeak_only_when_neural_voice_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "missing.onnx"
            with patch.dict(os.environ, {"PIPER_MODEL": str(model)}):
                with patch("narration.shutil.which", side_effect=lambda name: "/usr/bin/espeak-ng" if name == "espeak-ng" else None):
                    self.assertEqual(narration.find_local_voice(), "/usr/bin/espeak-ng")


if __name__ == "__main__":
    unittest.main()
