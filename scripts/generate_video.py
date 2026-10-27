#!/usr/bin/env python3
"""Generate an actual vertical MP4 through Gemini Omni Flash; fail closed if no video bytes."""
from __future__ import annotations
import base64, json, os, shutil, subprocess, sys, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORIES = ROOT / "output" / "story-prompt"
OUT = ROOT / "output" / "video"

def main() -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("ERROR: GEMINI_API_KEY is missing.", file=sys.stderr)
        return 2
    candidates = sorted(STORIES.glob("story-prompt-*.md"))
    if not candidates:
        print("ERROR: no generated story prompt found.", file=sys.stderr)
        return 2
    story = candidates[-1].read_text(encoding="utf-8").strip()
    # Ask the video model to produce one coherent short clip with native audio.
    prompt = """Create one polished, cinematic 3D animated YouTube Short based on the production brief below.
Prioritize the section titled VIDEO GENERATOR MASTER PROMPT and use the shot timeline as guidance. Output a coherent moving video, not a slideshow or a still image. Include synchronized narration/dialogue, environmental sound effects and suitable music where supported. Keep visual continuity, an immediate hook, clear cause-and-effect motion, and a satisfying final frame. No watermarks or unnecessary text. Vertical 9:16.
PRODUCTION BRIEF:
""" + story[:18000]
    body = {
        "model": os.environ.get("GEMINI_VIDEO_MODEL", "gemini-omni-1.1-flash"),
        "input": prompt,
        "response_format": {"type": "video", "aspect_ratio": "9:16", "resolution": "720p"}
    }
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/interactions?key=" + key,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=720) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:3000]
        print(f"Gemini video API HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Video generation request failed: {exc}", file=sys.stderr)
        return 1

    video_b64 = None
    # REST Interactions returns video bytes in steps[].content[] (SDK output_video is not REST).
    for step in data.get("steps", []):
        if step.get("type") == "model_output":
            for item in step.get("content", []):
                if item.get("type") == "video" and item.get("data"):
                    video_b64 = item["data"]
                    break
        if video_b64:
            break
    if not video_b64:
        print("ERROR: API returned no video payload. Response status=" + str(data.get("status")), file=sys.stderr)
        print(json.dumps(data, ensure_ascii=False)[:2500], file=sys.stderr)
        return 1
    try:
        raw = base64.b64decode(video_b64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        print(f"ERROR: invalid base64 video payload: {exc}", file=sys.stderr)
        return 1
    if len(raw) < 100_000 or not (raw[4:8] == b"ftyp" or b"ftyp" in raw[:32]):
        print(f"ERROR: output does not look like a valid MP4 ({len(raw)} bytes).", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mp4 = OUT / f"digital-edge-lab-{stamp}.mp4"
    mp4.write_bytes(raw)
    audio_status = "not_checked"
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        check = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(mp4)], capture_output=True, text=True, timeout=30)
        audio_status = "present" if "audio" in check.stdout.lower() else "missing"
        if audio_status == "missing":
            mp4.unlink(missing_ok=True)
            print("ERROR: generated MP4 contains no detectable audio stream; refusing delivery.", file=sys.stderr)
            return 1
    meta = {
        "status": "video_generated",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": body["model"],
        "aspect_ratio_requested": "9:16",
        "file": mp4.name,
        "bytes": len(raw),
        "audio_stream_check": audio_status,
        "api_interaction_status": data.get("status"),
        "note": "Video bytes verified as MP4. Audio check is only marked present when ffprobe confirms an audio stream."
    }
    (OUT / f"{mp4.stem}.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"SUCCESS: generated MP4 {mp4} ({len(raw)} bytes); audio stream check: {audio_status}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
