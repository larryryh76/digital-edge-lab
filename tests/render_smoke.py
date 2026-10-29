"""Renderer smoke test: render real scenes with Blender and gate them on motion.

Run: python tests/render_smoke.py
Needs Blender and ffmpeg on PATH; exits non-zero when a scene is static, when the
wrong subject is built, or when the encoded pixels show no motion.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import media_qa  # noqa: E402
import scene_spec  # noqa: E402

SECONDS = 2.75
SCENES = [  # (subject, action) — include the two previously failing production treatments
    ("glass_sphere", "compress"),
    ("glass_sphere", "expand"),
    ("dial", "spin"),
    ("pipe_bundle", "collapse_to_one"),
    ("mountain_pair", "compare_pan"),
    ("balance_scale", "compare_pan"),
    ("block_pair", "collide"),
]


def main():
    blender = shutil.which("blender")
    if not blender:
        print("SKIP: blender not available", file=sys.stderr)
        return 2
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("SKIP: ffmpeg not available", file=sys.stderr)
        return 2

    work = Path(tempfile.mkdtemp(prefix="del-smoke-"))
    failures = []
    frames = int(round(SECONDS * 24))
    for i, (subject, action) in enumerate(SCENES):
        if action not in scene_spec.SUBJECT_KINDS[subject]["actions"]:
            failures.append(f"{subject}/{action}: action not allowed by registry")
            continue
        scene = scene_spec.normalize_scene({
            "beat_id": "b1",
            "subject": {"kind": subject, "material": "metal", "color": "cyan"},
            "action": {"kind": action, "intensity": 0.8},
            "environment": {"kind": "studio_plinth"},
            "camera": {"framing": "medium", "move": "push_in"},
            "lighting": {"mood": "cool"},
            "on_screen_text": "SMOKE",
        }, i, {"b1"})
        # Longer shots for the previously failing treatments expose end-of-shot
        # freezes that a 2.75s smoke clip would never exercise.
        shot_seconds = 8.0 if action == "expand" else (6.0 if subject == "balance_scale" else SECONDS)
        shot_frames = int(round(shot_seconds * 24))
        spec_path = work / f"scene_{i:02d}.json"
        spec_path.write_text(json.dumps(scene), encoding="utf-8")
        out = work / f"segment_{i:02d}.mp4"
        log = work / f"scene_{i:02d}.log"
        print(f"[smoke] rendering {subject}/{action} -> {out.name}", flush=True)
        started = time.monotonic()
        with log.open("w", encoding="utf-8") as handle:
            result = subprocess.run(
                [blender, "-b", "-t", "2", "--python-exit-code", "1",
                 "--python", str(ROOT / "src" / "blender_scene.py"),
                 "--", str(spec_path), str(out), str(i), str(len(SCENES)),
                 f"{shot_seconds:.3f}"],
                stdout=handle, stderr=subprocess.STDOUT, text=True, timeout=900,
                env=dict(os.environ, LIBGL_ALWAYS_SOFTWARE="1",
                         GALLIUM_DRIVER="llvmpipe"))
        log_tail = log.read_text(encoding="utf-8", errors="replace")
        elapsed = time.monotonic() - started
        if result.returncode:
            failures.append(f"{subject}/{action}: blender exit {result.returncode}\n"
                            + log_tail[-2500:])
            continue
        print(f"[smoke] rendered {shot_frames} frames in {elapsed:.1f}s "
              f"({elapsed / max(shot_frames, 1):.2f}s/frame)", flush=True)
        produced = sorted(out.parent.glob(out.stem + "*.mp4"))
        if len(produced) != 1:
            failures.append(f"{subject}/{action}: expected one mp4, got "
                            f"{[p.name for p in produced]}\n" + log_tail[-2500:])
            continue
        clip = produced[0]
        if clip != out:
            clip.replace(out)
        trace_path = out.with_name(out.stem + ".visual.json")
        if not trace_path.is_file():
            failures.append(f"{subject}/{action}: no visual trace")
            continue
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        window = {"index": i, "start": 0.0, "end": shot_seconds, "duration": shot_seconds,
                  "frames": shot_frames, "narration": "smoke test line"}
        report = media_qa.evaluate_scene(scene, window, out, trace, scene_spec)
        status = "PASS" if report["passed"] else "FAIL"
        print(f"[smoke] {subject}/{action} {status} "
              f"motion={report['measured']['displacement']} "
              f"screen={report['measured']['screen_pixels']}px "
              f"encoded={report['encoded_motion']['mean']}", flush=True)
        if not report["passed"]:
            failures.append(f"{subject}/{action}: {report['failures']}")

    if failures:
        print(json.dumps({"passed": False, "failures": failures}, indent=2), file=sys.stderr)
        print(f"ARTIFACTS: {work}", file=sys.stderr)
        return 1
    print(f"render smoke: {len(SCENES)} scenes passed on real rendered media")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
