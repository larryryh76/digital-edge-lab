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
    def test_prefers_kokoro_when_cached_model_and_voice_pack_exist(self):
        import types

        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "kokoro.int8.onnx"
            voices = Path(tmp) / "voices.bin"
            model.write_bytes(b"model")
            voices.write_bytes(b"voices")
            fake_module = types.ModuleType("kokoro_onnx")
            with patch.dict(os.environ, {
                "KOKORO_MODEL": str(model),
                "KOKORO_VOICES": str(voices),
            }), patch.dict(sys.modules, {"kokoro_onnx": fake_module}):
                self.assertEqual(narration.find_local_voice(), "kokoro")

    def test_noncommercial_piper_is_not_selected_even_if_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "ryan-noncommercial.onnx"
            model.write_bytes(b"legacy")
            with patch.dict(os.environ, {
                "PIPER_MODEL": str(model),
                "KOKORO_MODEL": "",
                "KOKORO_VOICES": "",
            }):
                with patch("narration.shutil.which",
                           side_effect=lambda name: "/usr/bin/piper" if name == "piper"
                           else "/usr/bin/espeak-ng" if name == "espeak-ng" else None):
                    self.assertEqual(narration.find_local_voice(), "/usr/bin/espeak-ng")

    def test_uses_espeak_only_when_kokoro_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "missing.onnx"
            voices = Path(tmp) / "missing.bin"
            with patch.dict(os.environ, {
                "KOKORO_MODEL": str(model),
                "KOKORO_VOICES": str(voices),
            }):
                with patch("narration.shutil.which",
                           side_effect=lambda name: "/usr/bin/espeak-ng" if name == "espeak-ng" else None):
                    self.assertEqual(narration.find_local_voice(), "/usr/bin/espeak-ng")


if __name__ == "__main__":
    unittest.main()
