"""Media QA must be measured from encoded media, not from intent."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import media_qa  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def make_clip(path, filtergraph):
    """`filtergraph` is a complete lavfi source, e.g. 'testsrc=size=180x320:rate=24'."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", filtergraph,
         "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return path


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe required")
class MotionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_static_frame_is_measured_as_static(self):
        clip = make_clip(self.tmp / "still.mp4",
                        "color=c=black:size=180x320:rate=24:duration=2")
        stats = media_qa.motion_stats(clip)
        self.assertLess(stats["mean"], 0.05)
        self.assertGreater(stats["static_fraction"], 0.9)

    def test_moving_test_pattern_is_measured_as_moving(self):
        clip = make_clip(self.tmp / "moving.mp4",
                        "testsrc=size=180x320:rate=24:duration=2")
        stats = media_qa.motion_stats(clip)
        self.assertGreater(stats["mean"], 0.25)
        self.assertLess(stats["static_fraction"], 0.2)

    def test_frozen_clip_is_detected(self):
        clip = make_clip(self.tmp / "frozen.mp4",
                        "color=c=gray:size=180x320:rate=24:duration=3")
        frozen = media_qa.frozen_segments(clip, min_duration=1.0)
        self.assertTrue(frozen)
        self.assertGreaterEqual(frozen[0][1], 1.0)

    def test_black_frames_are_detected(self):
        clip = make_clip(self.tmp / "dark.mp4",
                        "color=c=black:size=180x320:rate=24:duration=2")
        # blackdetect needs a minimum duration and a full dark picture.
        self.assertTrue(media_qa.black_segments(clip, min_duration=0.5))

    def test_identical_stills_compare_as_duplicates(self):
        a = make_clip(self.tmp / "a.mp4",
                        "color=c=navy:size=180x320:rate=24:duration=2")
        b = make_clip(self.tmp / "b.mp4",
                        "color=c=navy:size=180x320:rate=24:duration=2")
        frame_a = media_qa.extract_frame(a, 0.5, self.tmp / "a.png", 180, 320)
        frame_b = media_qa.extract_frame(b, 0.5, self.tmp / "b.png", 180, 320)
        self.assertGreater(media_qa.image_similarity(frame_a, frame_b), 0.98)

    def test_different_stills_are_not_duplicates(self):
        a = make_clip(self.tmp / "c.mp4",
                        "color=c=navy:size=180x320:rate=24:duration=2")
        b = make_clip(self.tmp / "d.mp4",
                        "testsrc=size=180x320:rate=24:duration=2")
        frame_a = media_qa.extract_frame(a, 0.5, self.tmp / "c.png", 180, 320)
        frame_b = media_qa.extract_frame(b, 0.5, self.tmp / "d.png", 180, 320)
        self.assertLess(media_qa.image_similarity(frame_a, frame_b), 0.9)


class RendererMotionContractTests(unittest.TestCase):
    def test_expansion_animation_has_intermediate_motion_not_only_endpoints(self):
        source = (ROOT / "src" / "blender_scene.py").read_text(encoding="utf-8")
        body = source[source.index("def act_expand(ctx):"):source.index("def act_squeeze(ctx):")]
        self.assertIn("checkpoints =", body)
        self.assertIn("0.78", body)
        self.assertIn('key(hero, "location", frame', body)
        self.assertIn('key(rim, "rotation_euler", frame', body)

    def test_reveal_animation_has_multiple_motion_checkpoints_and_no_ease_out(self):
        source = (ROOT / "src" / "blender_scene.py").read_text(encoding="utf-8")
        body = source[source.index("def act_reveal(ctx):"):source.index("def act_transform(ctx):")]
        self.assertIn("checkpoints =", body)
        self.assertIn("0.84, 1.0", body)
        self.assertIn('point.interpolation = "LINEAR"', body)
        self.assertIn('startswith("slab_etch")', body)

    def test_balance_scale_animation_is_coupled_and_continuous(self):
        source = (ROOT / "src" / "blender_scene.py").read_text(encoding="utf-8")
        body = source[source.index("def act_compare_pan(ctx):"):source.index("ACTION_PROGRAMS =")]
        self.assertIn("scale_pan_left", body)
        self.assertIn("scale_pan_right", body)
        self.assertIn("scale_chain-1", body)
        self.assertIn("0.70, 16.0", body)
        self.assertIn("ctx.mover = beam or left", body)


class RequirementTests(unittest.TestCase):
    def test_spin_requirement_rejects_a_static_object(self):
        passed, failures = media_qa.compare_motion(
            {"rotation_degrees_min": 120, "subject_displacement_min": 0.18,
             "subject_screen_pixels_min": 10.0},
            {"rotation_degrees": 4.0, "displacement": 0.4, "screen_pixels": 40.0})
        self.assertFalse(passed)
        self.assertTrue(any("rotation" in f for f in failures))

    def test_compression_requirement_rejects_no_change(self):
        passed, failures = media_qa.compare_motion(
            {"scale_ratio_max": 0.62, "subject_displacement_min": 0.05},
            {"scale_ratio_min": 0.99, "displacement": 0.3, "screen_pixels": 40.0})
        self.assertFalse(passed)
        self.assertTrue(any("shrink" in f for f in failures))

    def test_camera_only_motion_fails_the_screen_travel_floor(self):
        passed, failures = media_qa.compare_motion(
            {"subject_displacement_min": 0.18, "subject_screen_pixels_min": 10.0},
            {"displacement": 0.0, "screen_pixels": 0.0})
        self.assertFalse(passed)
        self.assertTrue(any("screen travel" in f for f in failures))

    def test_deformation_requirement_uses_any_part(self):
        passed, failures = media_qa.compare_motion(
            {"translate_min": 0.1, "any_part_shrink_below": 0.8},
            {"displacement": 0.6, "screen_pixels": 30.0},
            {"_squeezed": {"scale_ratio_min": 0.4}})
        self.assertTrue(passed, failures)

    def test_diversity_rejects_near_identical_scenes(self):
        reports = [{"subject": "dial", "action": "spin", "template": "dial__spin"},
                   {"subject": "dial", "action": "spin", "template": "dial__spin"},
                   {"subject": "dial", "action": "spin", "template": "dial__spin"}]
        matrix = {"0": {"0": 1.0, "1": 0.99, "2": 0.4},
                  "1": {"0": 0.99, "1": 1.0, "2": 0.3},
                  "2": {"0": 0.4, "1": 0.3, "2": 1.0}}
        result = media_qa.check_scene_diversity(reports, matrix)
        self.assertFalse(result["passed"])
        self.assertTrue(any("near-identical" in f for f in result["failures"]))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe required")
class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _clip(self, size, seconds=3.0):
        path = self.tmp / "final.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error",
             "-f", "lavfi", "-i", f"testsrc=size={size}:rate=24:duration={seconds}",
             "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
            capture_output=True, text=True, check=True)
        return path

    def test_wrong_resolution_is_rejected(self):
        clip = self._clip("180x320")
        result = media_qa.verify_delivery(clip, width=720, height=1280, fps=24,
                                          min_seconds=0.5, max_seconds=30)
        self.assertFalse(result["passed"])
        self.assertTrue(any("resolution" in f for f in result["failures"]))

    def test_missing_audio_is_rejected(self):
        path = self.tmp / "silent.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "testsrc=size=180x320:rate=24:duration=2", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", str(path)], capture_output=True, text=True, check=True)
        result = media_qa.verify_delivery(path, width=180, height=320, fps=24,
                                          min_seconds=0.5, max_seconds=30)
        self.assertFalse(result["passed"])
        self.assertTrue(any("audio" in f for f in result["failures"]))


if __name__ == "__main__":
    unittest.main()
