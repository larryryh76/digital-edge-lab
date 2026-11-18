"""Static safety contracts for the optional Kaggle GPU worker."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "kaggle" / "production-render" / "production_render.py"
METADATA = ROOT / "kaggle" / "production-render" / "kernel-metadata.template.json"
WORKFLOW = ROOT / ".github" / "workflows" / "kaggle-production-render.yml"


class KaggleWorkerContractTests(unittest.TestCase):
    def test_worker_python_source_compiles(self):
        compile(WORKER.read_text(encoding="utf-8"), str(WORKER), "exec")

    def test_worker_pins_the_exact_source_commit(self):
        source = WORKER.read_text(encoding="utf-8")
        self.assertIn('SOURCE_SHA = "__SOURCE_SHA__"', source)
        self.assertIn('git", "fetch", "--depth", "1", "origin", SOURCE_SHA', source)
        self.assertIn('git", "checkout", "--detach", SOURCE_SHA', source)

    def test_worker_uses_native_quality_gpu_profile_and_fails_closed(self):
        source = WORKER.read_text(encoding="utf-8")
        self.assertIn('"DEL_RENDER_PROFILE": "production"', source)
        self.assertIn('"DEL_RENDER_WORKERS": "1"', source)
        self.assertIn('"DEL_RENDER_PHASE_BUDGET_SECONDS": "7200"', source)
        self.assertIn("nvidia-smi", source)
        self.assertIn("failed_gates", source)
        self.assertIn("(1080, 1920)", source)

    def test_worker_uses_commercially_licensed_kokoro_voice(self):
        source = WORKER.read_text(encoding="utf-8")
        self.assertIn('"KOKORO_MODEL": str(kokoro_model)', source)
        self.assertIn('"KOKORO_VOICES": str(kokoro_voices)', source)
        self.assertIn('"KOKORO_VOICE": "am_michael"', source)
        self.assertIn('narration.get("engine") != "kokoro-neural"', source)
        self.assertIn('"voice_model_license": "Apache-2.0"', source)
        self.assertIn('"inference_package_license": "MIT"', source)
        self.assertIn('ASSET_ATTRIBUTION.txt', source)
        self.assertNotIn("PIPER_MODEL", source)
        self.assertNotIn("piper-tts", source)

    def test_worker_uses_cc0_poly_haven_hdris_with_attribution(self):
        source = WORKER.read_text(encoding="utf-8")
        self.assertIn('slug="studio_small_03"', source)
        self.assertIn('"DEL_POLYHAVEN_HDRI"', source)
        self.assertIn("Powered by Poly Haven", source)
        self.assertIn("video-description.txt", source)

    def test_kaggle_kernel_is_private_and_gpu_enabled(self):
        metadata = json.loads(METADATA.read_text(encoding="utf-8"))
        self.assertEqual(metadata["is_private"], "true")
        self.assertEqual(metadata["enable_gpu"], "true")
        self.assertEqual(metadata["enable_internet"], "true")
        self.assertEqual(metadata["machine_shape"], "NvidiaTeslaT4")

    def test_gpu_workflow_requires_explicit_confirmation_and_secrets(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("confirm_gpu_usage:", workflow)
        self.assertIn("if: inputs.confirm_gpu_usage", workflow)
        self.assertIn("secrets.KAGGLE_USERNAME", workflow)
        self.assertIn("secrets.KAGGLE_KEY", workflow)
        self.assertIn("kaggle kernels push", workflow)
        self.assertIn("kaggle kernels output", workflow)


if __name__ == "__main__":
    unittest.main()
