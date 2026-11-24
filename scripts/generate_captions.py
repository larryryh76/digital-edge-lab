#!/usr/bin/env python3
import json, html
from pathlib import Path

def ts(seconds):
    ms = int(round(seconds*1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

report = json.loads(Path("output/delivery/run-report.json").read_text())
lines = []
for i, beat in enumerate(report.get("timeline", []), 1):
    text = beat["narration"].strip()
    lines += [str(i), f"{ts(beat['start'])} --> {ts(beat['end'])}", text, ""]
Path("output/delivery/captions.srt").write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {len(lines)//4} caption cues")
