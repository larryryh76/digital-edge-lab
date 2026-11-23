#!/usr/bin/env python3
"""Encoded-video motion gate for the rigged character proof.

Samples the video at low cost, measures motion in a central subject region and
compares it with an outer background band. This cannot identify semantics, but it
rejects static renders and camera/background-only movement in the proof framing.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
import numpy as np

def extract_sampled_frames(path: Path, fps: float = 3.0, width: int = 160):
    probe = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf",
         f"fps={fps},scale={width}:-2:flags=area", "-f", "rawvideo",
         "-pix_fmt", "gray", "pipe:1"],
        capture_output=True, check=True, timeout=180)
    payload = probe.stdout
    # scale to even height; ffmpeg's scaled output is known to preserve aspect ratio.
    height = int(round(width * 16 / 9 / 2) * 2)  # vertical short, 9:16
    frame_bytes = width * height
    if not payload or len(payload) % frame_bytes:
        raise RuntimeError(f"ffmpeg returned incomplete sample frames ({len(payload)} bytes)")
    return np.frombuffer(payload, dtype=np.uint8).reshape(-1, height, width)

def motion_metrics(frames):
    if frames.ndim != 3 or frames.shape[0] < 4:
        raise ValueError("at least four sampled frames are required")
    h, w = frames.shape[1:]
    # Broad subject region; outer 15% bands provide a background/camera-motion reference.
    y0, y1 = int(h * .12), int(h * .88)
    x0, x1 = int(w * .15), int(w * .85)
    subject = frames[:, y0:y1, x0:x1].astype(np.int16)
    background = np.concatenate([frames[:, :int(h*.12), :].reshape(len(frames), -1),
                                frames[:, int(h*.88):, :].reshape(len(frames), -1),
                                frames[:, :, :int(w*.15)].reshape(len(frames), -1),
                                frames[:, :, int(w*.85):].reshape(len(frames), -1)], axis=1).astype(np.int16)
    diffs = np.abs(np.diff(subject, axis=0))
    bgdiff = np.abs(np.diff(background, axis=0))
    per_frame = diffs.mean(axis=(1,2))
    bg_per_frame = bgdiff.mean(axis=1)
    return {
        "sampled_frames": int(frames.shape[0]),
        "subject_roi_mean_delta": float(per_frame.mean()),
        "background_mean_delta": float(bg_per_frame.mean()),
        "subject_active_fraction": float((per_frame >= 0.65).mean()),
        "subject_frozen_interval_fraction": float((per_frame < 0.20).mean()),
        "subject_motion_dominates": bool(per_frame.mean() >= max(0.45, bg_per_frame.mean() * 0.50)),
        "interval_subject_delta": [round(float(v), 3) for v in per_frame],
    }

def evaluate(metrics, *, minimum_delta=0.45, maximum_frozen=0.70):
    problems=[]
    if metrics["sampled_frames"] < 4: problems.append("too few sampled frames")
    if metrics["subject_roi_mean_delta"] < minimum_delta:
        problems.append(f"subject-region motion too low ({metrics['subject_roi_mean_delta']:.3f})")
    if metrics["subject_frozen_interval_fraction"] > maximum_frozen:
        problems.append(f"too many frozen subject intervals ({metrics['subject_frozen_interval_fraction']:.0%})")
    if not metrics["subject_motion_dominates"]:
        problems.append("subject motion does not dominate the outer background reference")
    return {"passed": not problems, "failures": problems, **metrics}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--report", type=Path, default=None)
    args=ap.parse_args()
    frames=extract_sampled_frames(args.video)
    report=evaluate(motion_metrics(frames))
    out=args.report or args.video.with_suffix(".motion-qa.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2
if __name__=="__main__": sys.exit(main())
