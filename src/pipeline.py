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
TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
W, H, FPS = 720, 1280, 24
ACTUAL_MODELS = {"text": None, "tts": None}


def treatment_diversity_report(treatment_names, scene_count=None):
    """Require at least five genuinely distinct renderer treatments for a full episode."""
    count = len(treatment_names) if scene_count is None else int(scene_count)
    required = min(5, count)
    unique = sorted(set(treatment_names))
    repeated = {name: treatment_names.count(name) for name in unique
                if treatment_names.count(name) > 1}
    return {"passed": len(unique) >= required, "unique_count": len(unique),
            "required_count": required, "repeated_treatments": repeated}


def stop(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def list_available_models():
    """Discover model IDs and methods actually advertised for this API key."""
    if not API_KEY:
        stop("Missing GEMINI_API_KEY repository secret.")
    try:
        response = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                                params={"key": API_KEY, "pageSize": 1000}, timeout=(5, 15))
        if not response.ok:
            diagnostic("model_discovery", {"status": "failed", "http_status": response.status_code})
            return {}
        result = {}
        for item in response.json().get("models", []):
            name = str(item.get("name", "")).removeprefix("models/")
            methods = item.get("supportedGenerationMethods", [])
            if name and "generateContent" in methods:
                result[name] = methods
        diagnostic("model_discovery", {"status": "success", "models": sorted(result)})
        return result
    except (requests.RequestException, ValueError) as exc:
        diagnostic("model_discovery", {"status": "failed", "error": str(exc)[:300]})
        return {}


def diagnostic(stage, details):
    path = OUT / "diagnostics.json"
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        current = {}
    current[stage] = details
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")


def record_model_event(operation, event):
    """Keep model-level history instead of letting TTS overwrite the text request evidence."""
    path = OUT / "diagnostics.json"
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        current = {}
    history = current.setdefault("model_request_history", {}).setdefault(operation, [])
    history.append(event)
    current["model_request_history"][operation] = history[-40:]
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")


def ordered_model_candidates(configured, available, audio=False):
    """Prefer current models for the requested task; skip deprecated and image-only models."""
    if audio:
        eligible = [name for name, methods in available.items()
                    if "generateContent" in methods and "tts" in name.lower()
                    and "image" not in name.lower()]
        priority = ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts",
                    "gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts")
    else:
        eligible = [name for name, methods in available.items()
                    if "generateContent" in methods and "flash" in name.lower()
                    and "tts" not in name.lower() and "image" not in name.lower()]
        priority = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
                    "gemini-3.5-flash", "gemini-3-flash-preview",
                    "gemini-3.1-flash-lite-preview", "gemini-3.1-flash-lite",
                    "gemini-3.5-flash-lite", "gemini-flash-latest",
                    "gemini-flash-lite-latest")
    ordered = []
    if configured in eligible:
        ordered.append(configured)
    ordered.extend(name for name in priority if name in eligible and name not in ordered)
    ordered.extend(name for name in sorted(eligible) if name not in ordered)
    return ordered


def request_gemini(model, parts, config=None):
    if not API_KEY:
        stop("Missing GEMINI_API_KEY repository secret.")
    import random, time
    audio = bool(config and "AUDIO" in config.get("responseModalities", []))
    available = list_available_models()
    models = ordered_model_candidates(model, available, audio=audio)
    if not models and not available:
        # Keep a single configured-model attempt if model discovery itself was temporarily unavailable.
        models = [model]
    if not models:
        stop("No API-listed generateContent model suitable for this operation; inspect diagnostics.")
    # A failed model must not consume the entire run. Rotate quickly through alternatives.
    deadline = time.monotonic() + 150
    failures = []
    for name in models[:6]:
        for attempt in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 2:
                break
            url = "https://generativelanguage.googleapis.com/v1beta/models/" + name + ":generateContent"
            try:
                response = requests.post(url, params={"key": API_KEY},
                    json={"contents": [{"parts": parts}], **({"generationConfig": config} if config else {})},
                    timeout=(min(5, remaining), min(22, remaining)))
            except requests.Timeout as exc:
                status, retryable, detail = "timeout", True, str(exc)[:250]
            except requests.RequestException as exc:
                status, retryable, detail = "network_error", True, str(exc)[:250]
            else:
                if response.ok:
                    try:
                        payload = response.json()
                        output = payload["candidates"][0]["content"]["parts"]
                        if not isinstance(output, list) or not output:
                            raise ValueError("empty response parts")
                        operation = "tts" if audio else "text"
                        ACTUAL_MODELS[operation] = name
                        record_model_event(operation, {"status": "success", "model": name})
                        diagnostic("last_model_request", {"status": "success", "model": name, "operation": operation})
                        return output
                    except (ValueError, KeyError, IndexError, TypeError) as exc:
                        status, retryable, detail = "malformed_response", False, str(exc)[:250]
                else:
                    status = "http_" + str(response.status_code)
                    detail = response.text[:400]
                    retryable = response.status_code in (429, 500, 502, 503, 504)
            failures.append({"model": name, "status": status, "attempt": attempt + 1, "detail": detail})
            operation = "tts" if audio else "text"
            record_model_event(operation, {"status": status, "model": name,
                "attempt": attempt + 1, "detail": detail[:250]})
            diagnostic("last_model_request", {"status": status, "model": name,
                "operation": operation, "failures": failures[-12:]})
            if not retryable or status in ("timeout", "network_error"):
                # A timed-out model must not consume a second full request window; rotate to the
                # next API-advertised candidate instead.
                break
            # Retry one fast transient server/rate-limit failure, then rotate candidates.
            delay = min(0.6 + random.random() * 0.5, max(0, deadline - time.monotonic()))
            if delay:
                print("Gemini " + status + " on " + name + "; retrying once in "
                      + str(round(delay, 1)) + "s", flush=True)
                time.sleep(delay)
    diagnostic("generation_failure", {"configured_model": model, "operation": "tts" if audio else "text",
        "attempted_models": models[:6], "failures": failures})
    record_model_event("tts" if audio else "text", {"status": "exhausted",
        "configured_model": model, "attempted_models": models[:6], "failure_count": len(failures)})
    stop("Gemini generation exhausted model fallbacks; diagnostics saved to output/diagnostics.json")



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
avoid invented mechanisms and grandiose claims, and never confuse a metaphor with a literal process. For tokenization, never imply all models split a word identically, never invent token IDs, and never claim tokenization alone makes a task impossible; verify any exact split against a named tokenizer or explain that splits vary by model. Distinguish a useful metaphor from the actual mechanism.
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
Create exactly 7 scene objects with "visual" and "on_screen_text". Each scene must describe a different
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
    missing = [k for k in required if not isinstance(data, dict) or k not in data]
    if missing:
        diagnostic("script_schema_retry", {"missing_fields": missing, "reason": "initial response omitted required JSON fields"})
        correction = prompt + "\n\nREPAIR REQUIREMENT: Your previous response omitted required fields: " + ", ".join(missing) + ". Return a complete JSON object containing every required field. Do not explain the repair or use Markdown fences."
        parts = request_gemini(
            TEXT_MODEL,
            [{"text": correction}],
            {"temperature": 0.35, "responseMimeType": "application/json"},
        )
        raw = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()
        raw = re.sub(r"^\`\`\`(?:json)?\s*|\s*\`\`\`$", "", raw, flags=re.I)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            stop("Gemini returned invalid JSON during schema repair: " + raw[:1200])
        missing = [k for k in required if not isinstance(data, dict) or k not in data]
        if missing:
            stop("Generated script still lacks required fields after one repair attempt: " + ", ".join(missing))
    if len(data["narration"].split()) < 80 or len(data["scenes"]) < 5:
        stop("Generated narration or scene plan is too short.")
    if len(data["scenes"]) != 7:
        diagnostic("script_schema_failure", {"expected_scene_count": 7, "actual_scene_count": len(data["scenes"])})
        stop(f"Pilot requires exactly seven distinct scenes; Gemini returned {len(data['scenes'])}. Refusing to silently ship a shorter episode.")
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
    data["source_validation"]["reachability_status"] = (
        "reachable_links_found" if reachable else "no_reachable_links"
    )
    data["source_validation"]["source_claim_support_status"] = "HUMAN_REVIEW_REQUIRED"
    data["source_validation"]["human_editorial_approval"] = "PENDING"
    data["source_validation"]["review_required"] = True
    data["source_validation"]["status"] = "HUMAN_REVIEW_REQUIRED"
    return data

def normalize_blender_output(requested_path, scene_index, probe_runner=subprocess.run):
    """Find only this scene's expected Blender MP4 names, ffprobe them, and normalize one match."""
    requested = Path(requested_path)
    # Blender appends a frame-range suffix to animation outputs on some versions:
    # segment_00.mp4 -> segment_000001-0081.mp4. Do not accept arbitrary MP4s.
    suffix_pattern = re.compile(
        r"^" + re.escape(requested.stem) + r"\d{4,6}-\d{4,6}\.mp4$"
    )
    candidates = []
    if requested.is_file():
        candidates.append(requested)
    candidates.extend(p for p in requested.parent.glob(requested.stem + "*.mp4")
                      if p.is_file() and p != requested and suffix_pattern.fullmatch(p.name))
    candidates = sorted(set(candidates))
    if len(candidates) != 1:
        raise RuntimeError(
            f"Scene {scene_index + 1}: expected exactly one current Blender MP4 for "
            f"{requested.name}; found {[p.name for p in candidates]}"
        )
    candidate = candidates[0]
    if candidate.stat().st_size < 1000:
        raise RuntimeError(f"Scene {scene_index + 1}: Blender MP4 is too small ({candidate.stat().st_size} bytes): {candidate.name}")
    probe = probe_runner(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,width,height",
         "-of", "json", str(candidate)],
        check=False, capture_output=True, text=True, timeout=20,
    )
    if probe.returncode:
        raise RuntimeError(f"Scene {scene_index + 1}: ffprobe rejected {candidate.name}: {probe.stderr[-1000:]}")
    try:
        payload = json.loads(probe.stdout)
        videos = [x for x in payload.get("streams", []) if x.get("codec_type") == "video"]
        duration = float(payload.get("format", {}).get("duration", 0))
    except (ValueError, TypeError, AttributeError) as exc:
        raise RuntimeError(f"Scene {scene_index + 1}: malformed ffprobe data for {candidate.name}: {exc}") from exc
    if (len(videos) != 1 or videos[0].get("codec_name") != "h264"
            or int(videos[0].get("width", 0)) < 100
            or int(videos[0].get("height", 0)) < 100 or duration <= 0):
        raise RuntimeError(f"Scene {scene_index + 1}: {candidate.name} is not a valid H.264 video (probe={payload})")
    if candidate != requested:
        if requested.exists():
            raise RuntimeError(f"Scene {scene_index + 1}: refusing to overwrite existing requested output {requested}")
        candidate.replace(requested)
    diagnostic("scene_render_output", {
        "scene_index": scene_index, "requested_path": str(requested),
        "discovered_path": candidate.name, "normalized_path": str(requested),
        "size_bytes": requested.stat().st_size, "duration_seconds": duration,
        "codec": videos[0].get("codec_name"), "width": videos[0].get("width"),
        "height": videos[0].get("height"), "status": "validated"
    })
    return requested


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
        clip = OUT / f"segment_{i:02d}.mp4"
        scene_json = cards / f"scene_{i:02d}.json"
        scene_json.write_text(json.dumps(scene, ensure_ascii=False))
        blender = shutil.which("blender")
        if not blender:
            stop("Blender is required for the animated 3D renderer but was not found.")
        blender_log = cards / f"scene_{i:02d}_blender.log"
        # Delete any exact/suffixed scene outputs before rendering so stale clips cannot pass QA.
        for stale_clip in clip.parent.glob(clip.stem + "*.mp4"):
            if stale_clip.is_file():
                stale_clip.unlink()
        blender_env = os.environ.copy()
        blender_env.update({
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENCV_OPENCL_RUNTIME": "disabled",
        })
        with blender_log.open("w", encoding="utf-8") as log:
            result = subprocess.run(
                [blender, "-b", "-t", "2", "--python", str(ROOT / "src" / "blender_scene.py"),
                 "--", str(scene_json), str(clip), str(i), str(len(scenes)),
                 f"{segment_duration:.3f}"],
                stdout=log, stderr=subprocess.STDOUT, text=True, env=blender_env,
                timeout=150,
            )
        if result.returncode:
            details = blender_log.read_text(encoding="utf-8", errors="replace")[-5000:]
            stop(f"Animated Blender render failed for scene {i + 1} (exit {result.returncode}). Log tail:\n{details}")
        try:
            clip = normalize_blender_output(clip, i)
        except RuntimeError as exc:
            details = blender_log.read_text(encoding="utf-8", errors="replace")[-5000:]
            diagnostic("scene_render_failure", {"scene_index": i, "error": str(exc),
                "log_tail": details, "candidate_files": [
                    {"name": p.name, "size_bytes": p.stat().st_size}
                    for p in cards.parent.glob(clip.stem + "*.mp4") if p.is_file()
                ]})
            stop(str(exc) + "\nBlender log tail:\n" + details)

        # Render captions as a transparent overlay so the underlying 3D action remains visible.
        overlay = cards / f"caption_{i:02d}.png"
        caption_image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        painter = ImageDraw.Draw(caption_image)
        panel = (28, 1000, W-28, 1210)
        painter.rounded_rectangle(panel, radius=24, fill=(8, 14, 28, 218),
                                  outline=(54, 92, 135, 235), width=2)
        caption_font = get_font(20, True)
        max_caption_width = W - 104
        caption_lines, current = [], ""
        for word in captions[i].strip().split():
            candidate = f"{current} {word}".strip()
            if painter.textbbox((0, 0), candidate, font=caption_font)[2] <= max_caption_width:
                current = candidate
            else:
                if current:
                    caption_lines.append(current)
                current = word
        if current:
            caption_lines.append(current)
        if len(caption_lines) > 3:
            caption_lines = caption_lines[:3]
            last = caption_lines[2]
            while last and painter.textbbox((0, 0), last + "…", font=caption_font)[2] > max_caption_width:
                last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
            caption_lines[2] = last.rstrip(" .") + "…"
        line_height = 38
        start_y = max(1015, 1100 - (len(caption_lines)*line_height)//2)
        for line_no, line in enumerate(caption_lines):
            painter.text((52, start_y + line_no*line_height), line,
                         font=caption_font, fill=(245, 248, 255, 255))
        caption_image.save(overlay)

        # Preserve the Blender-rendered motion, add readable captions, then edit to delivery FPS.
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(clip), "-loop", "1", "-i", str(overlay),
             "-filter_complex",
             f"[0:v]scale={W}:{H}[base];[base][1:v]overlay=0:0:shortest=1,"
             f"fps={FPS},fade=t=in:st=0:d=0.18,"
             f"fade=t=out:st={max(segment_duration-0.18,0):.3f}:d=0.18,format=yuv420p[v]",
             "-map", "[v]", "-an", "-t", f"{segment_duration:.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-pix_fmt", "yuv420p", "-r", str(FPS), str(OUT / f"final_segment_{i:02d}.mp4")],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        segments.append(OUT / f"final_segment_{i:02d}.mp4")

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
    # Remove stale files first so a failed generation cannot masquerade as a fresh delivery.
    for stale in OUT.iterdir():
        if stale.is_file():
            stale.unlink()
        elif stale.is_dir():
            shutil.rmtree(stale)
    OUT.mkdir(exist_ok=True)
    diagnostic("run", {"status": "started", "configured_text_model": TEXT_MODEL, "configured_tts_model": TTS_MODEL})
    memory = load_channel_memory()
    data = generate_script(memory)
    data = validate_sources(data)
    (OUT / "metadata.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    (OUT / "narration.txt").write_text(data["narration"], encoding="utf-8")
    wav = make_narration(data["narration"])
    video, duration, audio_qa = render(data, wav)
    # Confirm every rendered scene reports the specific treatment used by Blender.
    visual_traces = []
    for i, scene in enumerate(data["scenes"]):
        trace_path = OUT / f"segment_{i:02d}.visual.json"
        if not trace_path.is_file():
            stop(f"Scene {i + 1} has no renderer visual trace; refusing to accept unverified scene output.")
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            stop(f"Scene {i + 1} visual trace is unreadable: {exc}")
        if trace.get("scene_index") != i or not trace.get("treatment") or trace.get("brief") != scene.get("visual", ""):
            stop(f"Scene {i + 1} visual trace does not match the current scene brief.")
        visual_traces.append(trace)
    treatment_names = [x["treatment"] for x in visual_traces]
    # Distinct labels alone are not visual QA: ensure known concrete briefs select their matching set.
    for scene_index, (brief_scene, trace) in enumerate(zip(data["scenes"], visual_traces)):
        brief_text = (str(brief_scene.get("visual", "")) + " " +
                      str(brief_scene.get("on_screen_text", ""))).lower()
        expected = None
        # Specific physical actions take precedence over incidental nouns such as "etched".
        if ("phone" in brief_text or "smartphone" in brief_text) and any(k in brief_text for k in ("massive", "crushing", "heavy", "too big")):
            expected = "phone_overloaded_by_model_cube"
        elif "16-bit" in brief_text or ("floating-point" in brief_text and "weights" in brief_text):
            expected = "high_precision_weight_sphere"
        elif ("4-bit" in brief_text or "coarse" in brief_text or "stepped" in brief_text) and "sphere" in brief_text:
            expected = "quantized_grid_sphere"
        elif ("laser" in brief_text or "beam" in brief_text) and any(k in brief_text for k in ("decimal", "gear", "integer", "rounding", "15-step")):
            expected = "decimal_rounding_gear_track"
        elif ("memory block" in brief_text or "memory" in brief_text) and any(k in brief_text for k in ("collapses", "reducing", "volume", "three-quarters", "75%")):
            expected = "memory_volume_compression"
        elif ("motherboard" in brief_text or "smartphone" in brief_text or "phone frame" in brief_text) and any(k in brief_text for k in ("socket", "local speed", "energy pulse", "device")):
            expected = "phone_socket_hero_reveal"
        elif "strawberry" in brief_text and ("10 letters" in brief_text or "laser" in brief_text or "sweeps" in brief_text):
            expected = "copper_strawberry_word_laser"
        elif "straw" in brief_text and "berry" in brief_text and "laser" in brief_text:
            expected = "three_token_blocks"
        elif "38221" in brief_text or "token id" in brief_text:
            expected = "token_id_cube_reveal"
        elif "token library" in brief_text or "massive grid" in brief_text:
            expected = "token_library_grid"
        elif "magnifying glass" in brief_text or "no letters inside" in brief_text:
            expected = "magnifying_lens_cutaway"
        elif "balance scale" in brief_text or "alphabet beads" in brief_text:
            expected = "token_vs_letters_balance"
        elif "re-assembles" in brief_text or "flickers between 2 and 3" in brief_text or "blind spot" in brief_text:
            expected = "strawberry_count_reveal"
        if expected and trace.get("treatment") != expected:
            stop(f"Visual QA rejected scene {scene_index + 1}: expected {expected}, got {trace.get('treatment')}.")
    diversity = treatment_diversity_report(treatment_names, len(data["scenes"]))
    if not diversity["passed"]:
        stop("Visual QA rejected the episode: too many scenes share the same generic treatment. "
             + json.dumps(diversity, sort_keys=True))
    # Persist candidate editorial history only after render, audio/video QA, and scene-treatment QA.
    history = list(memory.get("recent_topics", []))
    history.append({"title": data["title"], "topic": data["topic"],
                    "created_at_utc": datetime.now(timezone.utc).isoformat()})
    candidate = dict(memory)
    candidate["recent_topics"] = history[-30:]
    context = list(memory.get("running_context", []))
    context.append("Episode: " + str(data["title"]) + " — " + str(data["topic"]))
    candidate["running_context"] = context[-20:]
    (OUT / "channel-memory.json").write_text(json.dumps(candidate, indent=2, ensure_ascii=False), encoding="utf-8")
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "title": data["title"], "topic": data["topic"],
        "video_file": video.name, "duration_seconds": round(duration, 2),
        "status": "rendered_not_published",
        "audio_qa": audio_qa,
        "models": {"text": ACTUAL_MODELS["text"] or TEXT_MODEL, "tts": ACTUAL_MODELS["tts"] or TTS_MODEL},
        "source_validation": data.get("source_validation", {}),
        "human_review_required": True,
        "editorial_review": {
            "source_reachability": data.get("source_validation", {}).get("reachability_status", "unknown"),
            "source_claim_support": "HUMAN_REVIEW_REQUIRED",
            "human_fact_check": "PENDING",
            "publication_ready": False
        },
        "output_path": str(video),
        "visual_scene_qa": {
            "automated_treatment_trace": "PASS",
            "distinct_treatments": len(set(treatment_names)),
            "scene_count": len(visual_traces),
            "scenes": [{"scene_index": x["scene_index"], "treatment": x["treatment"],
                        "hero_object": x.get("hero_object"), "laser_action": x.get("laser_action"),
                        "brief": x.get("brief")} for x in visual_traces],
            "semantic_visual_review": "HUMAN_REVIEW_REQUIRED"
        },
        "publishing": {"youtube": "not_implemented", "tiktok": "not_implemented",
                       "scheduling": "not_implemented", "analytics": "not_implemented"},
    }
    # Final independent media inspection: stream metadata, dimensions, frame rate and contact sheet.
    probe_full = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,duration,sample_rate,channels,nb_frames",
         "-of", "json", str(video)], check=True, capture_output=True, text=True, timeout=25)
    media = json.loads(probe_full.stdout)
    vstreams = [x for x in media.get("streams", []) if x.get("codec_type") == "video"]
    # Report the actual muxed delivery duration, not the source WAV's pre-render duration.
    report["duration_seconds"] = round(float(media.get("format", {}).get("duration", duration)), 2)
    astreams = [x for x in media.get("streams", []) if x.get("codec_type") == "audio"]
    if not vstreams or not astreams or vstreams[0].get("codec_name") != "h264":
        stop("Final delivery failed codec/stream QA.")
    if (int(vstreams[0].get("width", 0)) != W or int(vstreams[0].get("height", 0)) != H
            or vstreams[0].get("r_frame_rate") != f"{FPS}/1"):
        stop("Final delivery failed portrait resolution or FPS QA.")
    contact = OUT / "contact-sheet.jpg"
    sample = subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vf",
         "fps=1/5,scale=180:320,tile=3x3", "-frames:v", "1", str(contact)],
        capture_output=True, text=True, timeout=45)
    if sample.returncode or not contact.exists() or contact.stat().st_size < 1000:
        stop("Could not create visual contact sheet; see renderer/ffmpeg diagnostics.")
    report["media_qa"] = {
        "status": "PASS", "video_codec": vstreams[0].get("codec_name"),
        "width": vstreams[0].get("width"), "height": vstreams[0].get("height"),
        "fps": vstreams[0].get("r_frame_rate"), "video_frames": vstreams[0].get("nb_frames"),
        "audio_codec": astreams[0].get("codec_name"),
        "audio_sample_rate_hz": astreams[0].get("sample_rate"),
        "audio_channels": astreams[0].get("channels"),
        "contact_sheet": contact.name
    }
    report["checks"] = {
        "video_audio_streams": "PASS", "audio_not_near_silent": "PASS",
        "duration_alignment": "PASS", "portrait_720x1280": "PASS",
        "fps_24": "PASS", "contact_sheet_created": "PASS",
        "source_claim_support": "HUMAN_REVIEW_REQUIRED"
    }
    report["human_review_required"] = True
    report["source_validation"]["review_required"] = True
    report["source_validation"]["source_claim_support_status"] = "HUMAN_REVIEW_REQUIRED"
    report["source_validation"]["human_editorial_approval"] = "PENDING"
    report["editorial_review"]["human_fact_check"] = "PENDING"
    report["editorial_review"]["publication_ready"] = False
    report_path = OUT / "run-report.json"
    report_path.write_text(json.dumps(report, indent=2))
    # Package the actual narration audio and visual inspection aid with the delivery.
    delivery = OUT / "delivery"
    delivery.mkdir(exist_ok=True)
    for stale in delivery.iterdir():
        if stale.is_file():
            stale.unlink()
    shutil.copy2(video, delivery / video.name)
    shutil.copy2(OUT / "metadata.json", delivery / "metadata.json")
    shutil.copy2(OUT / "narration.txt", delivery / "narration.txt")
    shutil.copy2(wav, delivery / "narration.wav")
    shutil.copy2(contact, delivery / "contact-sheet.jpg")
    shutil.copy2(report_path, delivery / "run-report.json")
    shutil.copy2(OUT / "channel-memory.json", delivery / "channel-memory.json")
    # Bundle the exact per-scene briefs, Blender logs, and treatment traces for human visual review.
    review_bundle = delivery / "scene-review"
    review_bundle.mkdir(exist_ok=True)
    for review_file in (OUT / "cards").glob("scene_*"):
        if review_file.is_file():
            shutil.copy2(review_file, review_bundle / review_file.name)
    for trace_file in OUT.glob("segment_*.visual.json"):
        if trace_file.is_file():
            shutil.copy2(trace_file, review_bundle / trace_file.name)
    print(json.dumps(report, indent=2))
    print("Pilot rendered. Inspect sources and media before posting.")


if __name__ == "__main__":
    main()
