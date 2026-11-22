#!/usr/bin/env python3
"""Reject frozen CogVideo experiment clips using consecutive sampled frame deltas."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

def compare(a: Path, b: Path):
    with Image.open(a).convert("RGB") as left, Image.open(b).convert("RGB") as right:
        if left.size != right.size:
            raise ValueError(f"Frame size mismatch: {left.size} vs {right.size}")
        diff = ImageChops.difference(left, right)
        mean_delta = sum(ImageStat.Stat(diff).mean) / 3
        changed_fraction = sum(1 for v in diff.convert("L").getdata() if v > 8) / (left.width * left.height)
        return {"mean_abs_rgb_delta": round(mean_delta, 3), "changed_pixel_fraction": round(changed_fraction, 4)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--frames-dir", type=Path, default=Path("/kaggle/working"))
    p.add_argument("--output", type=Path, default=Path("/kaggle/working/motion_qa.json"))
    args=p.parse_args()
    records=[]
    for second in range(1,6):
        prev=args.frames_dir/f"frame_{second-1:02d}.jpg"
        cur=args.frames_dir/f"frame_{second:02d}.jpg"
        if not prev.is_file() or not cur.is_file():
            raise SystemExit(f"Missing interval frame(s): {prev}, {cur}")
        metrics=compare(prev,cur)
        metrics["interval_seconds"]=f"{second-1}-{second}"
        records.append(metrics)
    # Explicitly sample multiple intervals. This catches frozen/near-identical output,
    # but motion is a necessary—not sufficient—condition for coherent storytelling.
    frozen=[x for x in records if x["mean_abs_rgb_delta"] < 1.0 or x["changed_pixel_fraction"] < 0.01]
    result={"sampled_intervals":records,"frozen_intervals":frozen,"pass":not frozen,
            "limitation":"Pixel-difference motion QA cannot prove intended subject motion; manual clip inspection remains required."}
    args.output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
    if frozen:
        raise SystemExit("Motion QA rejected clip: one or more sampled intervals are effectively frozen.")
if __name__=="__main__":
    main()
