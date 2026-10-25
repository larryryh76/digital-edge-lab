import base64
import json
import os
import re
import subprocess
import shutil
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


def list_available_models():
    """Discover models exposed by this API key instead of relying on retired names."""
    try:
        response = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": API_KEY, "pageSize": 1000},
            timeout=30,
        )
        if not response.ok:
            print(f"Gemini model discovery unavailable (HTTP {response.status_code}); using configured model only.", flush=True)
            return []
        data = response.json()
        models = []
        for item in data.get("models", []):
            name = str(item.get("name", "")).removeprefix("models/")
            methods = item.get("supportedGenerationMethods", [])
            if name and "generateContent" in methods:
                models.append(name)
        return models
    except (requests.RequestException, ValueError) as exc:
        print(f"Gemini model discovery failed ({exc}); using configured model only.", flush=True)
        return []


def request_gemini(model, parts, config=None):
    if not API_KEY:
        stop("Missing GEMINI_API_KEY repository secret.")
    body = {"contents": [{"parts": parts}]}
    if config:
        body["generationConfig"] = config

    is_audio = bool(config and "AUDIO" in config.get("responseModalities", []))
    candidates = [model]
    available = list_available_models()
    if is_audio:
        # TTS models are specialized; use only models actually exposed to this API key.
        candidates += [
            name for name in available
            if "tts" in name.lower() and ("flash" in name.lower() or "pro" in name.lower())
        ]
    else:
        # Prefer the configured model, then available non-retired flash models.
        candidates += [
            name for name in available
            if "flash" in name.lower() and "tts" not in name.lower()
        ]
    models = list(dict.fromkeys(candidates))
    import time
    last_error = "No model attempted"
    for model_name in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        for attempt in range(3):
            try:
                response = requests.post(url, params={"key": API_KEY}, json=body, timeout=180)
            except requests.RequestException as exc:
                last_error = f"network error on {model_name}: {exc}"
                if attempt < 2:
                    wait = 5 * (attempt + 1)
                    print(f"Gemini network issue on {model_name}; retrying in {wait}s...", flush=True)
                    time.sleep(wait)
                    continue
                print(f"Gemini model {model_name} exhausted network retries.", flush=True)
                break
            if response.ok:
                try:
                    data = response.json()
                    return data["candidates"][0]["content"]["parts"]
                except (ValueError, KeyError, IndexError, TypeError):
                    last_error = "Unexpected Gemini response on " + model_name + ": " + response.text[:700]
                    print(last_error, flush=True)
                    break
            last_error = f"Gemini API {response.status_code} on {model_name}: {response.text[:700]}"
            print(last_error, flush=True)
            if response.status_code not in (429, 500, 502, 503, 504, 404):
                stop(last_error)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                wait = 5 * (attempt + 1)
                print(f"Retrying {model_name} in {wait}s...", flush=True)
                time.sleep(wait)
                continue
            break
        if model_name != models[-1]:
            print(f"Trying next API-listed model after {model_name} failed.", flush=True)
    stop("All available Gemini models failed. " + last_error)


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
You are the senior story editor and visual director for Digital Edge Lab, an original faceless
short-form channel about AI, technology, digital tools, and evidence-based digital workflows.
Make one 50-65 second vertical mini-documentary with the pacing of a premium science/technology
short: immediate visual hook, a question viewers genuinely want answered, escalating discoveries,
one concrete example, a clear payoff, and a final line worth remembering. Use cinematic visual
storytelling, not a lecture or a slideshow. Do not imitate any named creator, channel, trademark,
signature catchphrase, or exact visual style. Build a distinct Digital Edge Lab identity: midnight
blue environments, electric-cyan highlights, warm metallic accents, tactile 3D objects, dramatic
lighting, close-up-to-wide visual progression, purposeful camera movement, and restrained editorial
graphics. Never invent statistics, promise income, or claim the brand personally tested anything. Do not choose
an abstract AI-workflow topic merely because it sounds technical. Prefer a vivid, physical, surprising
question with an answer that can be demonstrated on screen in 30-50 seconds. The narration must be
factually coherent to a general audience: define any necessary technical term in plain English,
avoid invented mechanisms and grandiose claims, and never confuse a metaphor with a literal process.
If the topic needs nuance, narrow the claim rather than bluffing.
Include 2-3 reputable source URLs you believe are real; prefer primary research, official docs, and
original product documentation. Do not invent URLs or overstate what a source proves. If uncertain,
choose a narrower topic that can be explained accurately.
The recurring narrator is Edge: a recognizable, curious, precise, conversational voice with dry
wit used sparingly. Edge is a consistent fictional editorial narrator, not a human claiming a
private life. Use supplied memory for continuity and avoid repeating recent topics.
CHANNEL MEMORY: {memory_prompt}
Return ONLY JSON with: title, description, topic, narration, scenes, sources, hashtags.
Narration: 95-120 words, natural spoken English with varied rhythm, intentional pauses using
punctuation, no generic greeting, no filler, no fake first-person experiments. Every sentence must
advance the story or explain what the viewer is seeing. Avoid jargon unless immediately explained.
Read it aloud mentally: if it sounds like an AI blog post, rewrite it as spoken language. Start with a vivid
claim, surprising contrast, or specific question—not "Did you know?". End with a satisfying payoff.
Create 6-8 scene objects with "visual" and "on_screen_text". Each scene must describe a different
shot and physical composition that can be rendered as a distinct 3D setup: specify hero object,
camera distance/angle, movement or action, environment, and lighting. The action must be filmable:
an object falls, cracks, opens, expands, collides, transforms, flows, is revealed by a cutaway, or
moves through a space. Do not describe static diagrams, floating text cards, or a list of facts. Avoid reusing the
same hero object in adjacent scenes. Include at least one visual transformation, a concrete
worked example, and a clear reveal. Do not ask the renderer to show legible paragraphs or tiny UI
text. On-screen text should be 2-5 words, punchy, readable on a phone, and not repeat narration.
Sources must be objects with "name", "url", and "supports". Use original objects and typography;
never imply stock footage or real screenshots were created.
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
    if len(data["narration"].split()) < 80 or len(data["scenes"]) < 5:
        stop("Generated narration or scene plan is too short.")
    # Reject generic filler and unsupported pseudo-technical explanations before paying for TTS.
    narration = str(data["narration"]).strip()
    if len(narration.split()) > 145:
        stop("Narration is too long for the target short; refusing to render rushed speech.")
    weak_openers = ("in today's video", "welcome back", "did you know", "in the world of")
    if narration.lower().startswith(weak_openers):
        stop("Narration opens with generic filler; regenerate with a specific curiosity hook.")
    if not any(mark in narration for mark in ("?", "!", ".")):
        stop("Narration lacks natural sentence structure.")
    for field in ("title", "topic", "description"):
        if not str(data.get(field, "")).strip():
            stop(f"Generated script has an empty {field}.")
    if not isinstance(data["scenes"], list) or not isinstance(data["sources"], list):
        stop("Generated scenes and sources must be structured lists.")
    return data


def make_narration(text):
    # A warm, grounded documentary delivery with human pacing; avoid synthetic announcer energy.
    prompt = (
        "Voice direction for Edge, the Digital Edge Lab narrator: sound like a real, confident "
        "documentary storyteller speaking to one curious person. Use a warm, mid-low register, "
        "natural conversational rhythm, subtle curiosity, restrained emotion, clean consonants, "
        "and short intentional pauses at commas and reveals. Emphasize only the key words. "
        "Do not sound robotic, overexcited, salesy, or like a news bulletin. Do not add words, "
        "ad-libs, or sound effects. Read the supplied narration verbatim.\n\n"
        + text
    )
    parts = request_gemini(
        TTS_MODEL,
        [{"text": prompt}],
        {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Charon"}}
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

    # Interpret the scene brief so the illustration matches the story, not just its position.
    brief = (str(scene.get("visual", "")) + " " + str(scene.get("on_screen_text", ""))).lower()
    cx, cy = W // 2, 430
    if any(k in brief for k in ("document", "page", "text block", "hundred-page", "long text")):
        # A tall document with highlighted lines and a lost-detail marker.
        d.rounded_rectangle((205, cy-185, 515, cy+205), radius=18,
                            fill=(13, 25, 46), outline=accent, width=4)
        d.rectangle((235, cy-150, 485, cy-115), fill=(27, 49, 78))
        for j in range(9):
            yy = cy-85+j*27
            color = accent if j in (1, 7) else (66, 89, 119)
            d.rounded_rectangle((238, yy, 440+(j%3)*15, yy+9), radius=4, fill=color)
        d.ellipse((420, cy+78, 466, cy+124), fill=(255, 92, 113))
        d.line((443, cy+101, 548, cy+145), fill=(255, 92, 113), width=5)
        d.text((500, cy+140), "?", font=get_font(46, True), fill=(255, 122, 136))
    elif any(k in brief for k in ("curve", "valley", "attention", "recall", "middle effect", "performance")):
        # A deliberately legible U-shaped recall curve with a highlighted weak middle.
        points = [(80,cy+105),(145,cy+50),(205,cy+8),(270,cy+70),(360,cy+130),
                  (450,cy+70),(525,cy+12),(630,cy+95)]
        for a,b in zip(points, points[1:]):
            d.line((*a,*b), fill=accent, width=8)
        d.line((75,cy+150,645,cy+150), fill=(76,98,130), width=3)
        d.rounded_rectangle((270,cy+75,390,cy+155), radius=14,
                            fill=(76,32,58), outline=(255,100,135), width=3)
        d.text((281,cy+101), "MIDDLE", font=get_font(18,True), fill=(255,218,228))
    elif any(k in brief for k in ("chunk", "retrieval", "filter", "query", "split", "slice")):
        # Show one source being divided into searchable chunks before retrieval.
        d.rounded_rectangle((50,cy-92,205,cy+100), radius=18,
                            fill=(13,29,53), outline=(112,131,164), width=3)
        for j in range(5):
            d.rounded_rectangle((73,cy-65+j*31,180,cy-49+j*31), radius=5,
                                fill=(100,121,153) if j!=2 else accent)
        d.line((210,cy,270,cy), fill=accent, width=6)
        d.polygon([(260,cy-12),(280,cy),(260,cy+12)], fill=accent)
        for j,(x,y) in enumerate([(310,cy-100),(310,cy-20),(310,cy+60)]):
            d.rounded_rectangle((x,y,x+115,y+58),radius=12,
                                fill=(13,29,53),outline=accent if j==1 else (58,83,120),width=3)
            d.text((x+34,y+18),f"CHUNK {j+1}",font=get_font(14,True),fill=(238,246,255))
        d.line((430,cy,485,cy),fill=accent,width=6)
        d.polygon([(475,cy-12),(495,cy),(475,cy+12)],fill=accent)
        d.rounded_rectangle((505,cy-52,650,cy+52),radius=16,
                            fill=(20,45,57),outline=(48,220,170),width=3)
        d.text((525,cy-12),"MATCH",font=get_font(19,True),fill=(190,255,231))
    elif any(k in brief for k in ("before", "after", "versus", "compare", "bigger context", "mega-prompt")):
        for x,title,color in [(48,"BEFORE",(255,106,121)),(372,"AFTER",accent)]:
            d.rounded_rectangle((x,cy-125,x+298,cy+140),radius=22,
                                fill=(13,25,46),outline=color,width=3)
            d.text((x+20,cy-95),title,font=get_font(21,True),fill=color)
        for j,wid in enumerate((220,100,185,80)):
            d.rounded_rectangle((70,cy-42+j*43,70+wid,cy-22+j*43),radius=8,fill=(255,106,121))
        for j,wid in enumerate((90,150,205,240)):
            d.rounded_rectangle((395,cy-42+j*43,395+wid,cy-22+j*43),radius=8,fill=accent)
        d.ellipse((323,cy-28,365,cy+14),fill=(240,247,255))
        d.polygon([(338,cy-17),(353,cy-7),(338,cy+3)],fill=(7,12,25))
    elif any(k in brief for k in ("prompt", "anchor", "instruction", "top", "bottom", "context")):
        d.rounded_rectangle((120,cy-165,600,cy+170),radius=22,
                            fill=(13,25,46),outline=accent,width=3)
        d.rounded_rectangle((148,cy-135,572,cy-82),radius=12,
                            fill=(17,74,80),outline=(48,220,170),width=2)
        d.text((172,cy-119),"KEY INSTRUCTIONS",font=get_font(20,True),fill=(194,255,239))
        for j,wid in enumerate((365,300,330,240,345)):
            yy=cy-48+j*35
            d.rounded_rectangle((155,yy,155+wid,yy+12),radius=5,fill=(63,85,116))
        d.rounded_rectangle((148,cy+112,572,cy+157),radius=12,
                            fill=(17,74,80),outline=(48,220,170),width=2)
        d.text((172,cy+122),"THE QUESTION",font=get_font(18,True),fill=(194,255,239))
    elif any(k in brief for k in ("checklist", "steps", "workflow", "process", "output")):
        xs = [95, 270, 445, 620]
        labels = ["INPUT", "STEP 1", "STEP 2", "OUTPUT"]
        for j,x in enumerate(xs):
            d.rounded_rectangle((x-58,cy-58,x+58,cy+58),radius=18,
                                fill=(13,29,53),outline=accent,width=4)
            d.text((x-43,cy-12),labels[j],font=get_font(13,True),fill=(240,247,255))
            if j<len(xs)-1:
                d.line((x+60,cy,xs[j+1]-62,cy),fill=accent,width=5)
                d.polygon([(xs[j+1]-70,cy-10),(xs[j+1]-55,cy),(xs[j+1]-70,cy+10)],fill=accent)
    elif any(k in brief for k in ("network", "connected", "node", "system", "architecture")):
        nodes=[(140,cy-70),(300,cy-145),(300,cy+10),(470,cy-70),(590,cy+30)]
        for a,b in [(0,1),(0,2),(1,3),(2,3),(3,4)]:
            d.line((*nodes[a],*nodes[b]),fill=(48,91,145),width=5)
        for x,y in nodes:
            d.ellipse((x-30,y-30,x+30,y+30),fill=(13,29,53),outline=accent,width=5)
    else:
        baseline=cy+115
        heights=[80,145,105,205,165,240]
        for j,height in enumerate(heights):
            x=95+j*88
            d.rounded_rectangle((x,baseline-height,x+48,baseline),radius=10,fill=accent)
            d.ellipse((x+12,baseline-height-18,x+36,baseline-height+6),fill=(239,248,255))
        d.line((70,baseline+4,W-70,baseline+4),fill=(93,123,163),width=3)

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
        if not re.match(r"^https://\S+$", url, re.I):
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
    # Network reachability is advisory: hosted runners may block domains or have transient
    # network failures. Do not abort the entire render for that alone; mark the episode for review.
    data["source_validation"]["review_required"] = (not checks or reachable == 0)
    data["source_validation"]["status"] = (
        "reachable_links_found" if reachable else "manual_review_required"
    )
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
        scene_json = cards / f"scene_{i:02d}.json"
        scene_json.write_text(json.dumps(scene, ensure_ascii=False))
        # Render a real procedural 3D environment in Blender. No slide-card fallback:
        # if the 3D renderer fails, the pilot fails rather than disguising slides as 3D.
        blender = shutil.which("blender")
        if not blender:
            stop("Blender is required for the 3D-first renderer but was not found.")
        blender_log = cards / f"scene_{i:02d}_blender.log"
        blender_env = os.environ.copy()
        # Blender's bundled libraries can otherwise oversubscribe threads on hosted runners.
        blender_env.update({
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENCV_OPENCL_RUNTIME": "disabled",
        })
        with blender_log.open("w", encoding="utf-8") as log:
            result = subprocess.run(
                [blender, "-b", "-t", "1", "--python", str(ROOT / "src" / "blender_scene.py"),
                 "--", str(scene_json), str(image), str(i), str(len(scenes))],
                stdout=log, stderr=subprocess.STDOUT, text=True, env=blender_env,
                timeout=240,
            )
        if result.returncode:
            details = blender_log.read_text(encoding="utf-8", errors="replace")[-5000:]
            stop(f"Blender render failed for scene {i + 1} (exit {result.returncode}). Log tail:\\n{details}")
        if not image.exists() or image.stat().st_size < 10000:
            stop(f"Blender did not produce a valid 3D render for scene {i + 1}.")
        # Add readable, timed narration captions over the 3D image (not a slide template).
        frame = Image.open(image).convert("RGB")
        painter = ImageDraw.Draw(frame)
        fw, fh = frame.size
        sx, sy = fw / W, fh / H
        panel = (int(28*sx), int(1000*sy), fw-int(28*sx), fh-int(70*sy))
        painter.rounded_rectangle(panel, radius=max(12, int(24*sx)),
                                  fill=(8, 14, 28), outline=(54, 92, 135), width=max(1, int(2*sx)))
        # Fit captions to the actual render width and reserve a safe bottom margin.
        caption_font = get_font(max(16, int(20*sx)), True)
        max_caption_width = fw - int(104*sx)
        caption_words = captions[i].strip().split()
        caption_lines, current = [], ""
        for word in caption_words:
            candidate = f"{current} {word}".strip()
            if painter.textbbox((0, 0), candidate, font=caption_font)[2] <= max_caption_width:
                current = candidate
            else:
                if current:
                    caption_lines.append(current)
                current = word
        if current:
            caption_lines.append(current)
        # Cap at three lines; append an ellipsis instead of letting text escape the panel.
        if len(caption_lines) > 3:
            caption_lines = caption_lines[:3]
            last = caption_lines[2]
            while last and painter.textbbox((0, 0), last + "…", font=caption_font)[2] > max_caption_width:
                last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
            caption_lines[2] = last.rstrip(" .") + "…"
        line_height = max(30, int(36*sy))
        total_height = len(caption_lines) * line_height
        start_y = max(int(1010*sy), fh - int(58*sy) - total_height)
        for line_no, line in enumerate(caption_lines):
            painter.text((int(52*sx), start_y + line_no*line_height), line,
                         font=caption_font, fill=(245, 248, 255), stroke_width=0)
        frame.save(image)
        clip = OUT / f"segment_{i:02d}.mp4"
        # Blender renders the 3D scene; FFmpeg adds a restrained moving camera crop and transitions.
        # This is the first 3D milestone, not yet full character animation.
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
