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
MEMORY_DIR = ROOT / "memory"
MEMORY_FILE = MEMORY_DIR / "channel-memory.json"
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.8-flash")
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
    # Retry temporary Gemini overload/rate-limit/server failures with backoff.
    response = None
    for attempt in range(5):
        try:
            response = requests.post(
                url, params={"key": API_KEY}, json=body, timeout=240
            )
        except requests.RequestException as exc:
            if attempt == 4:
                stop(f"Gemini network request failed after 5 attempts: {exc}")
            wait = min(8 * (2 ** attempt), 60)
            print(f"Gemini network issue; retrying in {wait}s (attempt {attempt + 2}/5)...", flush=True)
            import time
            time.sleep(wait)
            continue
        if response.ok:
            break
        if response.status_code not in (429, 500, 502, 503, 504):
            stop(f"Gemini API {response.status_code}: {response.text[:1500]}")
        if attempt == 4:
            stop(f"Gemini API {response.status_code} after 5 attempts: {response.text[:1500]}")
        wait = min(8 * (2 ** attempt), 60)
        print(f"Gemini API {response.status_code} temporary failure; retrying in {wait}s (attempt {attempt + 2}/5)...", flush=True)
        import time
        time.sleep(wait)
    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        stop("Unexpected Gemini response: " + json.dumps(data)[:1200])


def load_channel_memory():
    """Load durable editorial memory committed to the repository."""
    if not MEMORY_FILE.exists():
        return {"persona": "Edge", "channel_name": "Digital Edge Lab",
                "voice": "clear, curious, confident, conversational English",
                "principles": [], "recent_topics": [], "running_context": []}
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        stop("Channel memory file is unreadable; refusing to discard continuity.")


def generate_script(memory):
    recent = memory.get("recent_topics", [])[-20:]
    running_context = memory.get("running_context", [])[-12:]
    memory_prompt = json.dumps({
        "narrator_persona": memory.get("persona", "Edge"),
        "channel_name": memory.get("channel_name", "Digital Edge Lab"),
        "voice": memory.get("voice", "clear, curious, confident, conversational"),
        "principles": memory.get("principles", []),
        "recent_topics_to_avoid_repeating": recent,
        "continuity_context": running_context,
    }, ensure_ascii=False)
    prompt = f"""
You are the editorial desk and story producer for Digital Edge Lab, a faceless educational brand
covering AI, technology, digital tools, and evidence-based online-business workflows. Create one
60-75 second vertical explainer with a strong curiosity-gap opening, a clear central question,
a concrete example, a useful takeaway, and a memorable final line. Do not write a generic list
of definitions. Never invent statistics, promise income, or claim the brand personally tested
anything. Include 2-3 reputable source URLs that you know are real; prefer primary research,
official documentation, and original product docs. Do not invent URLs or overstate what a source
proves. If uncertain, choose a narrower topic you can explain accurately.
You are the recurring narrator Edge. Keep a recognizable, conversational editorial voice and
consistent point of view without pretending to be a human with a private life. Use the supplied
memory, build continuity when helpful, and avoid repeating recent topics. Do not claim memory
outside the supplied context.
CHANNEL MEMORY: {memory_prompt}
Return ONLY JSON with: title, description, topic, narration, scenes, sources, hashtags.
Narration: 115-145 words, natural spoken English, varied sentence length, no generic greeting,
no filler such as "in today's fast-paced world", and no fake first-person experiments. Every
scene must advance the story and be visually distinct. Create 6-8 scene objects with "visual"
and "on_screen_text". The visual field must describe a concrete diagram, interface mockup, object,
or visual metaphor that can be drawn—not just a mood. On-screen text should be 3-7 words, punchy,
large, and not repeat narration verbatim. At least one scene should show a specific worked
example or before/after comparison. Sources must be objects with "name", "url", and "supports".
Use original shapes and typography; do not imply stock footage or screenshots were created.
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


def draw_card(scene, index, total, path, caption=""):
    """Create a designed scene card; render() adds motion and timed narration captions."""
    im = Image.new("RGB", (W, H), (7, 12, 25))
    d = ImageDraw.Draw(im)
    # Branded editorial layout with a different visual grammar per scene.
    accent = [(56, 194, 236), (123, 108, 255), (48, 220, 170), (255, 174, 66),
              (86, 164, 255), (255, 104, 150), (142, 226, 255)][index % 7]
    d.rectangle((0, 0, W, 12), fill=accent)
    d.text((48, 48), "DIGITAL EDGE LAB", font=get_font(23, True), fill=accent)
    d.text((W-180, 54), f"{index+1:02d} / {total:02d}", font=get_font(19, True), fill=(174, 193, 220))
    d.line((48, 94, W-48, 94), fill=(35, 54, 82), width=2)

    # Abstract technical illustration changes with each scene instead of repeating one template.
    cx, cy = W // 2, 430
    if index % 6 == 0:  # connected workflow
        xs = [105, 285, 465, 615]
        labels = ["INPUT", "STEP 1", "STEP 2", "OUTPUT"]
        for j, x in enumerate(xs):
            d.rounded_rectangle((x-58, cy-58, x+58, cy+58), radius=18,
                                fill=(13, 29, 53), outline=accent, width=4)
            d.text((x-43, cy-12), labels[j], font=get_font(13, True), fill=(240, 247, 255))
            if j < len(xs)-1:
                d.line((x+60, cy, xs[j+1]-62, cy), fill=accent, width=5)
                d.polygon([(xs[j+1]-70,cy-10),(xs[j+1]-55,cy),(xs[j+1]-70,cy+10)], fill=accent)
    elif index % 6 == 1:  # comparison
        for x, title, color, bars in [(70, "ONE BIG PROMPT", (255, 112, 112), [150, 80, 125, 55]),
                                      (370, "SMALL STEPS", accent, [55, 95, 130, 160])]:
            d.rounded_rectangle((x, cy-125, x+275, cy+145), radius=22,
                                fill=(13, 25, 46), outline=color, width=3)
            d.text((x+18, cy-98), title, font=get_font(17, True), fill=color)
            for j, bw in enumerate(bars):
                d.rounded_rectangle((x+22, cy-45+j*42, x+22+bw, cy-25+j*42),
                                    radius=8, fill=color)
    elif index % 6 == 2:  # modular steps
        for j in range(3):
            x, y = 78+j*195, cy-95+j*28
            d.rounded_rectangle((x,y,x+165,y+180), radius=20,
                                fill=(13, 29, 53), outline=accent, width=3)
            d.ellipse((x+55,y+24,x+110,y+79), outline=accent, width=4)
            d.text((x+70,y+39), str(j+1), font=get_font(20, True), fill=(245,249,255))
            d.text((x+20,y+112), ["CLEAN","ANALYZE","SUMMARIZE"][j], font=get_font(14, True), fill=(218,232,250))
    elif index % 6 == 3:  # data bars
        baseline = cy+115
        for j, height in enumerate([80, 145, 105, 205, 165, 240]):
            x = 95+j*88
            d.rounded_rectangle((x,baseline-height,x+48,baseline), radius=10, fill=accent)
            d.ellipse((x+12,baseline-height-18,x+36,baseline-height+6), fill=(239,248,255))
        d.line((70,baseline+4,W-70,baseline+4), fill=(93,123,163), width=3)
    elif index % 6 == 4:  # checklist
        for j, label in enumerate(["Clear inputs", "One task at a time", "Check each result", "Build final output"]):
            y = cy-120+j*66
            d.rounded_rectangle((85,y,135,y+42), radius=10, outline=accent, width=3)
            d.line((97,y+21,110,y+32,126,y+10), fill=accent, width=4)
            d.text((155,y+6), label, font=get_font(21, True), fill=(235,243,255))
    else:  # network of linked nodes
        nodes = [(140,cy-70),(300,cy-145),(300,cy+10),(470,cy-70),(590,cy+30)]
        edges = [(0,1),(0,2),(1,3),(2,3),(3,4)]
        for a,b in edges:
            d.line((*nodes[a],*nodes[b]), fill=(48,91,145), width=5)
        for x,y in nodes:
            d.ellipse((x-30,y-30,x+30,y+30), fill=(13,29,53), outline=accent, width=5)

    # Main scene statement
    label = str(scene.get("on_screen_text", "A useful idea")).strip().upper()
    lines = textwrap.wrap(label, width=24) or [label]
    y = 700
    for line in lines[:3]:
        box = d.textbbox((0, 0), line, font=get_font(36, True))
        d.text(((W-(box[2]-box[0]))//2,y), line, font=get_font(36,True), fill=(245,249,255))
        y += 48

    # The visual description is editorial context, not a claim that an external clip was generated.
    visual = textwrap.wrap(str(scene.get("visual", ""))[:110], width=48)[:2]
    for j, line in enumerate(visual):
        box = d.textbbox((0,0),line,font=get_font(16))
        d.text(((W-(box[2]-box[0]))//2, 865+j*23), line, font=get_font(16), fill=(150,177,210))

    # Burn in a readable narration caption so the story remains understandable without audio.
    caption_lines = textwrap.wrap(caption.strip(), width=38)[:3]
    d.rounded_rectangle((36, 1010, W-36, 1198), radius=22, fill=(13,23,40), outline=(38,61,91), width=2)
    for j, line in enumerate(caption_lines):
        d.text((58, 1040+j*42), line, font=get_font(21), fill=(232,240,251))
    im.save(path)


def split_caption(text, count):
    """Split narration into sequential chunks so captions follow the spoken story."""
    words = text.strip().split()
    if not words:
        return ["" for _ in range(count)]
    count = max(1, count)
    chunks, start = [], 0
    for i in range(count):
        remaining = len(words) - start
        slots = count - i
        end = len(words) if slots == 1 else min(len(words), start + max(1, round(remaining / slots)))
        chunks.append(" ".join(words[start:end]))
        start = end
    return chunks


def validate_sources(data):
    """Check whether cited source URLs are reachable; reachability is not proof of a claim."""
    checks = []
    for source in data.get("sources", []):
        url = str(source.get("url", "")).strip()
        item = {"name": source.get("name", ""), "url": url, "reachable": False, "status_code": None}
        if not re.match(r"^https://[^\\s]+$", url, re.I):
            item["error"] = "URL must be a valid HTTPS URL"
            checks.append(item)
            continue
        try:
            response = requests.get(
                url, timeout=12, allow_redirects=True,
                headers={"User-Agent": "DigitalEdgeLab-SourceCheck/1.0"}
            )
            item["status_code"] = response.status_code
            item["final_url"] = response.url
            # Some reputable sites block automated clients; reachable is not content verification.
            item["reachable"] = response.status_code < 400 or response.status_code in (401, 403, 429)
            if not item["reachable"]:
                item["error"] = "URL returned an HTTP error"
        except requests.RequestException as exc:
            item["error"] = str(exc)[:240]
        checks.append(item)
    data["source_checks"] = checks
    reachable = sum(1 for item in checks if item["reachable"])
    data["source_validation"] = {
        "checked_count": len(checks),
        "reachable_count": reachable,
        "reachability_only": True,
        "note": "A reachable URL does not prove that the source supports the claim; editorial review is still required."
    }
    if not checks or reachable == 0:
        stop("No source URL could be reached. Refusing to produce a pilot with unverified source links.")
    return data

def render(data, wav_path):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(wav_path)],
        check=True, capture_output=True, text=True,
    )
    duration = max(float(probe.stdout.strip()), 1.0)
    cards = OUT / "cards"
    cards.mkdir(exist_ok=True)
    scenes = data["scenes"]
    captions = split_caption(data["narration"], len(scenes))
    segment_duration = duration / len(scenes)
    segments = []
    for i, scene in enumerate(scenes):
        image = cards / f"scene_{i:02d}.png"
        draw_card(scene, i, len(scenes), image, captions[i])
        clip = OUT / f"segment_{i:02d}.mp4"
        # Every scene has slow camera movement plus short fades, so the result is animated video,
        # not a slideshow of motionless stills. Scene-specific artwork varies across the sequence.
        frames = max(int(segment_duration * FPS), 1)
        zoom_expr = "min(zoom+0.0012,1.10)" if i % 2 == 0 else "max(zoom-0.0007,1.0)"
        x_expr = "(iw-iw/zoom)/2" if i % 2 == 0 else "(iw-iw/zoom)/2+8*sin(on/18)"
        y_expr = "(ih-ih/zoom)/2" if i % 2 == 0 else "(ih-ih/zoom)/2+12*cos(on/21)"
        vf = (
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d=1:s={W}x{H}:fps={FPS},"
            f"fade=t=in:st=0:d=0.25,fade=t=out:st={max(segment_duration-0.25,0):.3f}:d=0.25,"
            "format=yuv420p"
        )
        subprocess.run(
            ["ffmpeg","-y","-loop","1","-i",str(image),"-t",f"{segment_duration:.3f}",
             "-vf",vf,"-an","-c:v","libx264","-preset","veryfast","-crf","22",
             "-pix_fmt","yuv420p","-r",str(FPS),str(clip)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        segments.append(clip)

    concat = OUT / "segments.txt"
    concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in segments) + "\n")
    silent = OUT / "visuals.mp4"
    subprocess.run(
        ["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy",str(silent)],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    final = OUT / "digital-edge-lab-pilot.mp4"
    # Standardize the audio for common Android/social players and normalize perceived loudness.
    subprocess.run(
        ["ffmpeg","-y","-i",str(silent),"-i",str(wav_path),"-map","0:v:0","-map","1:a:0",
         "-vf",f"scale={W}:{H},fps={FPS},format=yuv420p","-af",
         "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000",
         "-shortest","-c:v","libx264","-preset","veryfast","-crf","22",
         "-c:a","aac","-b:a","160k","-ac","2","-ar","48000",
         "-movflags","+faststart",str(final)],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    # Fail the job if the finished MP4 has no audio stream or has a near-silent narration track.
    check = subprocess.run(
        ["ffmpeg","-hide_banner","-i",str(final),"-map","0:a:0","-af","volumedetect","-f","null","-"],
        check=True, capture_output=True, text=True,
    )
    audio_log = check.stderr
    match = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", audio_log)
    if not match or float(match.group(1)) < -45:
        stop("Rendered MP4 audio is missing or nearly silent; refusing to report success.")
    # Verify the finished MP4 has both streams and synchronized durations.
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,duration", "-of", "json", str(final)],
        check=True, capture_output=True, text=True,
    )
    streams = json.loads(probe.stdout).get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not video_streams or not audio_streams:
        stop("Final MP4 failed QA: expected both video and audio streams.")
    try:
        video_seconds = float(video_streams[0]["duration"])
        audio_seconds = float(audio_streams[0]["duration"])
    except (KeyError, TypeError, ValueError):
        stop("Final MP4 QA could not read stream durations.")
    if audio_seconds < duration * 0.95 or abs(video_seconds - audio_seconds) > 1.5:
        stop(
            f"Final MP4 audio/video duration mismatch "
            f"(video={video_seconds:.2f}s, audio={audio_seconds:.2f}s, "
            f"narration={duration:.2f}s)."
        )
    return final, duration, {
        "video_duration_seconds": round(video_seconds, 2),
        "audio_duration_seconds": round(audio_seconds, 2),
        "audio_mean_volume_db": float(match.group(1)),
        "audio_codec": "AAC",
        "audio_sample_rate_hz": 48000,
        "qa_passed": True,
    }


def main():
    print("Generating a Digital Edge Lab pilot (not publishing it)...")
    memory = load_channel_memory()
    data = generate_script(memory)
    data = validate_sources(data)
    (OUT / "metadata.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    (OUT / "narration.txt").write_text(data["narration"], encoding="utf-8")
    # Update durable editorial memory; the workflow commits this file back to the repo.
    history = list(memory.get("recent_topics", []))
    history.append({"title": data["title"], "topic": data["topic"],
                    "created_at_utc": datetime.now(timezone.utc).isoformat()})
    memory["recent_topics"] = history[-30:]
    context = list(memory.get("running_context", []))
    context.append(f"Episode: {data['title']} — {data['topic']}")
    memory["running_context"] = context[-20:]
    (OUT / "channel-memory.json").write_text(
        json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    wav = make_narration(data["narration"])
    video, duration, audio_qa = render(data, wav)
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "title": data["title"], "topic": data["topic"],
        "video_file": video.name, "duration_seconds": round(duration, 2),
        "status": "rendered_not_published",
        "audio_qa": audio_qa,
    }
    report_path = OUT / "run-report.json"
    report_path.write_text(json.dumps(report, indent=2))
    # Keep silent intermediate renders and raw PCM out of the downloadable artifact.
    delivery = OUT / "delivery"
    delivery.mkdir(exist_ok=True)
    for stale in delivery.iterdir():
        if stale.is_file():
            stale.unlink()
    import shutil
    shutil.copy2(video, delivery / video.name)
    shutil.copy2(OUT / "metadata.json", delivery / "metadata.json")
    shutil.copy2(OUT / "narration.txt", delivery / "narration.txt")
    shutil.copy2(report_path, delivery / "run-report.json")
    shutil.copy2(OUT / "channel-memory.json", delivery / "channel-memory.json")
    print(json.dumps(report, indent=2))
    print("Pilot rendered. Inspect sources and media before posting.")


if __name__ == "__main__":
    main()
