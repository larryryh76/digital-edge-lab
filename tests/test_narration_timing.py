"""Narration timing regressions: the voice must speak the beat, not the prompt.

Run #84 evidence: a 15-word beat came back as 40.4s of hosted-TTS audio because
the long voice-direction paragraph was performed as content. The pipeline then
built a 974-frame scene and blew the render timeout. These tests pin the two
repairs: plausibility gating with a bare retry, and a render budget that scales
with the scene.
"""

import base64
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import narration  # noqa: E402
import pipeline  # noqa: E402

RATE = 24000
LINE = "Heavy AI models require massive memory and cheap storage to run."


def pcm_for(seconds, rate=RATE):
    """Silence-free s16le mono PCM of an exact duration."""
    frames = int(round(seconds * rate))
    return struct.pack("<h", 1200) * frames


class FakeClient:
    """Returns a pre-canned duration per prompt so the gate can be exercised."""

    def __init__(self, script):
        self.script = script
        self.prompts = []
        self.actual_models = {"tts": "fake-tts"}

    def generate(self, model, parts, config=None, **kwargs):
        prompt = parts[0]["text"]
        self.prompts.append(prompt)
        seconds = self.script(prompt)
        payload = base64.b64encode(pcm_for(seconds)).decode("ascii")
        return [{"inlineData": {"mimeType": f"audio/pcm;rate={RATE}", "data": payload}}]


class TtsPlausibilityTest(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="del-tts-"))

    def test_bare_line_is_tried_first_to_prevent_directions_being_spoken(self):
        client = FakeClient(lambda prompt: 5.9 if prompt == LINE else 40.4)
        out = narration.gemini_tts(client, LINE, self.work / "beat.wav", "fake-tts")
        self.assertEqual(client.prompts, [LINE], "valid bare narration should not pay for another TTS call")
        measured = narration.probe_duration(out)
        self.assertAlmostEqual(measured, 5.9, delta=0.1)

    def test_direction_paragraph_cannot_leak_back_into_the_prompt(self):
        self.assertNotIn("Voice direction for Edge", narration.STYLE_BRIEF)
        self.assertLess(len(narration.STYLE_BRIEF.split()), 16)
        self.assertFalse(narration.plausibility(LINE, 40.4)[0])
        self.assertTrue(narration.plausibility(LINE, 5.9)[0])

    def test_audio_that_is_wrong_twice_fails_the_episode(self):
        client = FakeClient(lambda prompt: 40.4)
        with self.assertRaises(narration.NarrationError) as caught:
            narration.gemini_tts(client, LINE, self.work / "beat.wav", "fake-tts")
        message = str(caught.exception)
        self.assertIn("cannot be this line", message)
        self.assertIn("bare", message)
        self.assertIn("styled", message)

    def test_synthesize_rejects_implausible_beat_before_rendering(self):
        episode = {"beats": [{"id": "b1", "role": "hook", "narration": LINE}],
                   "narration": LINE}
        client = FakeClient(lambda prompt: 40.4)
        with self.assertRaises(narration.NarrationError):
            narration.synthesize(episode, self.work / "narration", client=client,
                                 tts_model="fake-tts")


class RenderBudgetTest(unittest.TestCase):
    def test_budget_grows_with_scene_length(self):
        short = pipeline.render_timeout(int(3.0 * pipeline.FPS))
        long = pipeline.render_timeout(int(12.0 * pipeline.FPS))
        self.assertGreater(long, short)
        self.assertGreater(short, 120)
        # A 40s scene must not inherit the budget of a 3s one.
        self.assertGreater(pipeline.render_timeout(int(40.0 * pipeline.FPS)), 600)

    def test_measured_render_cost_fits_inside_the_budget(self):
        frames = int(5.0 * pipeline.FPS)
        self.assertGreaterEqual(pipeline.render_timeout(frames) / frames, 2.1)

    def test_override_is_kept_for_tests(self):
        self.assertEqual(pipeline.render_timeout(100, override=7), 7)


if __name__ == "__main__":
    unittest.main()
