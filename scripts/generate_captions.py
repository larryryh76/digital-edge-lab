#!/usr/bin/env python3
"""Generate an SRT sidecar whose cues are bounded by the rendered MP4 duration."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

def ts(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def media_duration(path: Path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(p.stdout.strip())

report = json.loads(Path("output/delivery/run-report.json").read_text())
mp4_candidates = sorted(Path("output/delivery").glob("*.mp4"))
if len(mp4_candidates) != 1:
    raise SystemExit(f"expected exactly one delivery mp4, found {len(mp4_candidates)}")
duration = media_duration(mp4_candidates[0])
timeline = report.get("timeline", [])
lines = []
for i, beat in enumerate(timeline, 1):
    start = min(max(float(beat["start"]), 0.0), duration)
    end = min(max(float(beat["end"]), start), duration)
    if end <= start:
        continue
    text = beat["narration"].strip()
    if not text:
        continue
    lines += [str(len(lines) // 4 + 1), f"{ts(start)} --> {ts(end)}", text, ""]
Path("output/delivery/captions.srt").write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {len(lines)//4} caption cues bounded to {duration:.3f}s")
