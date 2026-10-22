import base64
import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
W, H, FPS = 720, 1280, 24


def stop(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def request_gemini(model, parts, config=None):
    if not API_KEY:
        stop("Missing GEMINI_API_KEY repository secret.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"contents": [{"parts": parts}]}
    if config:
        body["generationConfig"] = config
    response = requests.post(
        url, params={"key": API_KEY}, json=body, timeout=240
    )
    if not response.ok:
        stop(f"Gemini API {response.status_code}: {response.text[:1500]}")
    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        stop("Unexpected Gemini response: " + json.dumps(data)[:1200])


def generate_script():
    prompt = """
You are the editorial desk for Digital Edge Lab, a faceless educational brand covering AI,
technology, digital tools, and online-business workflows. Create one useful 60-75 second
vertical video. Choose an evergreen topic. Never invent statistics, promise income, or claim
the brand personally tested anything. Include 2-4 reputable source URLs; do not invent URLs.
Return ONLY JSON with: title, description, topic, narration, scenes, sources, hashtags.
narration should be 120-160 words. scenes should contain 6-8 objects, each with
"visual" and "on_screen_text". Sources should be objects with "name", "url", and "supports".
Use visuals that can be illustrated with typography and simple original shapes.
"""
    parts = request_gemini(
        TEXT_MODEL,
        [{"text": prompt}],
        {"temperature": 0.6, "responseMimeType": "application/json"},
    )
    raw = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()
    raw = re.sub(r"^\`\`\`(?:json)?\s*|\s*\`\`\`$", "", raw, flags=re.I)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        stop("Gemini did not return valid JSON: " + raw[:1200])
    required = ("title", "description", "topic", "narration", "scenes", "sources", "hashtags")
    if any(k not in data for k in required):
        stop("Generated script is missing required fields.")
    if len(data["narration"].split()) < 80 or len(data["scenes"]) < 4:
        stop("Generated narration or scene plan is too short.")
    return data


def make_narration(text):
    prompt = "Read this narration exactly in a natural, clear, confident English voice at a moderate pace:\n\n" + text
    parts = request_gemini(
        TTS_MODEL,
        [{"text": prompt}],
        {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}
            },
        },
    )
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            raw = base64.b64decode(inline["data"])
            mime = inline.get("mimeType") or inline.get("mime_type") or "audio/pcm;rate=24000"
            match = re.search(r"rate=(\d+)", mime)
            rate = int(match.group(1)) if match else 24000
            raw_path, wav_path = OUT / "voice.pcm", OUT / "narration.wav"
            raw_path.write_bytes(raw)
            subprocess.run(
                ["ffmpeg", "-y", "-f", "s16le", "-ar", str(rate), "-ac", "1",
                 "-i", str(raw_path), str(wav_path)],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            return wav_path
    stop("TTS response contained no audio. Check model access and workflow logs.")


def get_font(size, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_card(scene, index, total, path):
    im = Image.new("RGB", (W, H), (7, 12, 25))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((32, 32, W - 32, H - 32), radius=32, outline=(30, 116, 220), width=3)
    d.text((58, 64), "DIGITAL EDGE LAB", font=get_font(24, True), fill=(86, 205, 255))
    d.text((58, 108), f"SCENE {index + 1:02d} / {total:02d}", font=get_font(17), fill=(156, 178, 207))
    cx, cy = W // 2, H // 2 - 70
    for radius, color, width in [(205, (25, 66, 130), 5), (150, (26, 112, 185), 4), (95, (56, 194, 236), 3)]:
        d.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), outline=color, width=width)
    d.line((cx-230, cy, cx+230, cy), fill=(35, 102, 177), width=3)
    d.line((cx, cy-230, cx, cy+230), fill=(35, 102, 177), width=3)
    label = str(scene.get("on_screen_text", "A useful idea")).upper()
    lines = textwrap.wrap(label, width=18) or [label]
    y = H - 390 - len(lines) * 25
    for line in lines[:4]:
        box = d.textbbox((0, 0), line, font=get_font(38, True))
        d.text(((W - (box[2] - box[0])) // 2, y), line, font=get_font(38, True), fill=(245, 249, 255))
        y += 56
    visual_lines = textwrap.wrap(str(scene.get("visual", ""))[:130], width=43)[:3]
    for j, line in enumerate(visual_lines):
        box = d.textbbox((0, 0), line, font=get_font(17))
        d.text(((W - (box[2] - box[0])) // 2, H - 180 + j * 26), line, font=get_font(17), fill=(157, 184, 216))
    im.save(path)


def render(data, wav_path):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(wav_path)],
        check=True, capture_output=True, text=True,
    )
    duration = max(float(probe.stdout.strip()), 1.0)
    cards = OUT / "cards"
    cards.mkdir(exist_ok=True)
    concat = OUT / "concat.txt"
    lines = []
    scenes = data["scenes"]
    for i, scene in enumerate(scenes):
        image = cards / f"scene_{i:02d}.png"
        draw_card(scene, i, len(scenes), image)
        lines.extend([f"file '{image.as_posix()}'", f"duration {duration / len(scenes):.3f}"])
    lines.append(f"file '{(cards / f'scene_{len(scenes)-1:02d}.png').as_posix()}'")
    concat.write_text("\n".join(lines))
    silent = OUT / "visuals.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
         "-vf", f"scale={W}:{H},format=yuv420p,fps={FPS}", "-c:v", "libx264",
         "-preset", "veryfast", "-pix_fmt", "yuv420p", str(silent)],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    final = OUT / "digital-edge-lab-pilot.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(silent), "-i", str(wav_path), "-shortest",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(final)],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return final, duration


def main():
    print("Generating a Digital Edge Lab pilot (not publishing it)...")
    data = generate_script()
    (OUT / "metadata.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    (OUT / "narration.txt").write_text(data["narration"], encoding="utf-8")
    wav = make_narration(data["narration"])
    video, duration = render(data, wav)
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "title": data["title"], "topic": data["topic"],
        "video_file": video.name, "duration_seconds": round(duration, 2),
        "status": "rendered_not_published",
    }
    (OUT / "run-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print("Pilot rendered. Inspect sources and media before posting.")


if __name__ == "__main__":
    main()
