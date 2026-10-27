"""Digital Edge Lab production pipeline.

    python src/pipeline.py                     # script + narration from Gemini
    python src/pipeline.py --plan plans/x.json # deterministic checked-in plan
    python src/pipeline.py --offline --plan …  # no API at all (local voice)

Stages: plan -> validate -> per-beat narration -> Blender render -> per-scene
visual QA -> encode -> delivery QA -> report. Any failed gate exits non-zero and
writes an actionable report; a green exit means the encoded episode passed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import media_qa  # noqa: E402
import narration as narration_mod  # noqa: E402
import scene_spec  # noqa: E402
from gemini_client import GeminiClient, GeminiError  # noqa: E402

OUT = ROOT / "output"
W, H, FPS = 720, 1280, 24
TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.8-flash")
TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")


# --- diagnostics -----------------------------------------------------------
class Diagnostics:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.data = {}

    def set(self, key, value):
        self.data[key] = value
        self.flush()

    def append(self, key, value):
        self.data.setdefault(key, []).append(value)
        self.data[key] = self.data[key][-40:]
        self.flush()

    def flush(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


def fail(message, diagnostics=None, code=1):
    print(f"ERROR: {message}", file=sys.stderr, flush=True)
    if diagnostics is not None:
        diagnostics.set("failure", {"message": str(message)[:4000],
                                    "at": datetime.now(timezone.utc).isoformat()})
    raise SystemExit(code)


# --- font + captions -------------------------------------------------------
def get_font(size, bold=False):
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/liberation2/LiberationSans-{'Bold' if bold else 'Regular'}.ttf",
        f"/usr/share/fonts/truetype/liberation/LiberationSans-{'Bold' if bold else 'Regular'}.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def build_caption_pngs(cards, index, out_dir):
    paths = []
    for j, card in enumerate(cards):
        image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        painter = ImageDraw.Draw(image)
        font = get_font(30, True)
        lines = card["lines"]
        line_height = 44
        panel_h = 38 + line_height * len(lines)
        top = H - 150 - panel_h
        painter.rounded_rectangle((40, top, W - 40, top + panel_h), radius=26,
                                  fill=(8, 14, 28, 216), outline=(60, 104, 150, 230), width=2)
        for line_no, line in enumerate(lines):
            width = painter.textbbox((0, 0), line, font=font)[2]
            painter.text(((W - width) / 2, top + 22 + line_no * line_height), line,
                         font=font, fill=(246, 250, 255, 255))
        path = out_dir / f"caption_{index:02d}_{j:02d}.png"
        image.save(path)
        paths.append((path, card["start"], card["end"]))
    return paths


def encode_segment(raw_clip, cards, duration, out_path, work):
    overlays = build_caption_pngs(cards, int(out_path.stem.split("_")[-1]), work) \
        if cards else []
    argv = ["ffmpeg", "-y", "-v", "error", "-i", str(raw_clip)]
    for path, _, _ in overlays:
        argv += ["-loop", "1", "-framerate", str(FPS), "-t", f"{duration:.4f}", "-i", str(path)]
    chain = [f"[0:v]scale={W}:{H}:flags=lanczos,setsar=1[base]"]
    last = "base"
    for k, (_, start, end) in enumerate(overlays, start=1):
        chain.append(
            f"[{last}][{k}:v]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[v{k}]")
        last = f"v{k}"
    chain.append(f"[{last}]fps={FPS},format=yuv420p[vout]")
    argv += ["-filter_complex", ";".join(chain), "-map", "[vout]", "-an",
             "-t", f"{duration:.4f}", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS), str(out_path)]
    result = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=240)
    if result.returncode:
        raise RuntimeError(f"segment encode failed: {result.stderr[-500:]}")
    return out_path


# --- plan acquisition ------------------------------------------------------
ENUM_DOC = None


def enum_documentation():
    global ENUM_DOC
    if ENUM_DOC:
        return ENUM_DOC
    lines = ["SUBJECT KINDS (choose subject.kind from this list; `actions` are the only "
             "actions that may be used with it):"]
    for kind, meta in scene_spec.SUBJECT_KINDS.items():
        if kind == scene_spec.FALLBACK_SUBJECT:
            continue
        lines.append(f"- {kind}: {meta['summary']}; actions: {', '.join(meta['actions'])}")
    lines.append("")
    lines.append("ACTION KINDS (action.kind):")
    for kind, meta in scene_spec.ACTIONS.items():
        lines.append(f"- {kind}: {meta['summary']}")
    lines.append("")
    lines.append(f"ENUMS: beat.role in {list(scene_spec.BEAT_ROLES)}; "
                 f"camera.framing in {list(scene_spec.CAMERA_FRAMINGS)}; "
                 f"camera.move in {list(scene_spec.CAMERA_MOVES)}; "
                 f"lighting.mood in {list(scene_spec.LIGHTING_MOODS)}; "
                 f"environment.kind in {list(scene_spec.ENVIRONMENTS)}; "
                 f"subject.material in {list(scene_spec.MATERIALS)}; "
                 f"subject.color in {list(scene_spec.COLORS)}.")
    ENUM_DOC = "\n".join(lines)
    return ENUM_DOC


def script_prompt(memory):
    recent = [t.get("topic") for t in memory.get("recent_topics", [])[-12:]]
    return f"""You are the story editor and visual director for Digital Edge Lab, an original
faceless short-form channel about technology. Produce ONE 35-55 second vertical mini-documentary
with the pacing of a premium science short: an immediate visual hook, a genuine question, an
escalating explanation, one concrete example, a clear reveal and a payoff line.

You write a *typed* scene plan that a 3D renderer can actually build. The renderer has a fixed
catalogue. You must choose from it exactly; scenes are rejected if they do not match.

{enum_documentation()}

Return ONLY JSON with exactly these keys:
title, description, topic, hashtags, sources, beats, scenes.

beats: 6-8 objects, each {{"id": "b1", "role": "<role>", "narration": "<one or two spoken sentences>"}}.
- The first beat's role must be "hook"; the last must be "payoff"; use at least 5 distinct roles.
- Each narration is 8-30 words of natural spoken English that describes what the viewer is
  seeing at that moment. No greetings, no filler, no "did you know".
- The full narration across all beats must be 80-135 words.

scenes: exactly one object per beat, same order, each:
{{"beat_id": "b1",
  "subject": {{"kind": "<subject kind>", "label": "<what it represents>", "material": "<material>", "color": "<color>"}},
  "action": {{"kind": "<action kind>", "intensity": 0.6}},
  "environment": {{"kind": "<environment>"}},
  "camera": {{"framing": "<framing>", "move": "<move>"}},
  "lighting": {{"mood": "<mood>"}},
  "from_state": "<what the scene looks like at the start>",
  "to_state": "<what has visibly changed by the end>",
  "on_screen_text": "<3-5 words>",
  "qa": {{"must_show": ["<objects the frame must contain>"], "must_change": ["<the visible change>"]}}}}

Hard rules:
- The action you choose must literally be filmable with the subject: use the actions listed for
  that subject kind and nothing else.
- Use at least 6 different subject kinds and at least 6 different action kinds across the episode.
- Do not repeat the same subject in two consecutive scenes.
- The narration must describe the action. If the line says something breaks, shrinks, snaps,
  merges or lands, the scene's action must be that action.
- No static diagrams, no text cards, no screenshots, no fake first-person tests, no invented
  statistics or URLs.
- Sources: 2-3 real, reputable URLs as {{"name","url","supports"}}; prefer primary docs or papers.
- Avoid recent topics: {recent}

Return raw JSON only, no Markdown fences, no commentary."""


def generate_episode(client, memory, diagnostics):
    prompt = script_prompt(memory)
    attempts = 0
    last_errors = []
    while attempts < 3:
        attempts += 1
        text = prompt if attempts == 1 else (
            prompt + "\n\nYOUR PREVIOUS PLAN WAS REJECTED BY THE VALIDATOR:\n- "
            + "\n- ".join(last_errors[:12])
            + "\nReturn a corrected, complete JSON object. Every scene must use a subject kind "
              "and an action that kind lists as allowed. Do not explain; return JSON only."
        )
        parts = client.generate(TEXT_MODEL, [{"text": text}],
                                {"temperature": 0.75 if attempts == 1 else 0.4,
                                 "responseMimeType": "application/json"},
                                deadline_seconds=200, attempts_per_model=3, label="text")
        raw = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_errors = [f"response was not valid JSON ({exc})"]
            diagnostics.append("plan_rejections", {"attempt": attempts, "errors": last_errors})
            continue
        episode, errors = scene_spec.normalize_episode(data)
        diagnostics.append("plan_validation", {"attempt": attempts, "errors": errors})
        if episode is not None:
            episode["origin"] = f"gemini:{client.actual_models.get('text') or TEXT_MODEL}"
            return episode
        last_errors = errors
    raise RuntimeError("could not obtain a renderable typed scene plan: "
                       + "; ".join(last_errors[:6]))


def load_plan(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    episode, errors = scene_spec.normalize_episode(data)
    if errors:
        raise RuntimeError("checked-in plan failed validation: " + "; ".join(errors))
    episode["origin"] = f"plan:{Path(path).name}"
    return episode


# --- sources ---------------------------------------------------------------
def validate_sources(episode, timeout=12):
    import requests
    checks = []
    for source in episode.get("sources", []):
        url = source.get("url", "")
        item = {"name": source.get("name", ""), "url": url, "reachable": False}
        if not re.match(r"^https://\S+$", url, re.I):
            item["error"] = "not an https URL"
            checks.append(item)
            continue
        try:
            response = requests.get(url, timeout=timeout, allow_redirects=True,
                                    headers={"User-Agent": "DigitalEdgeLab-SourceCheck/2.0"})
            item["status_code"] = response.status_code
            item["reachable"] = response.status_code < 400 or response.status_code in (401, 403, 429)
        except Exception as exc:  # advisory only
            item["error"] = str(exc)[:200]
        checks.append(item)
    reachable = sum(1 for c in checks if c["reachable"])
    return {
        "checked_count": len(checks),
        "reachable_count": reachable,
        "reachability_only": True,
        "note": "A reachable URL does not prove that the source supports the claim; "
                "editorial review is still required.",
        "source_claim_support_status": "HUMAN_REVIEW_REQUIRED",
        "checks": checks,
    }


# --- rendering -------------------------------------------------------------
def normalize_blender_output(requested, index):
    requested = Path(requested)
    pattern = re.compile(r"^" + re.escape(requested.stem) + r"\d{4,6}-\d{4,6}\.mp4$")
    candidates = []
    if requested.is_file():
        candidates.append(requested)
    candidates.extend(p for p in requested.parent.glob(requested.stem + "*.mp4")
                      if p != requested and pattern.fullmatch(p.name))
    candidates = sorted(set(candidates))
    if len(candidates) != 1:
        raise RuntimeError(f"scene {index + 1}: expected one Blender mp4, found "
                           f"{[p.name for p in candidates]}")
    clip = candidates[0]
    if clip.stat().st_size < 5000:
        raise RuntimeError(f"scene {index + 1}: Blender mp4 is {clip.stat().st_size} bytes")
    info = media_qa.probe(clip)
    video = media_qa.video_stream(info)
    if not video or video.get("codec_name") != "h264":
        raise RuntimeError(f"scene {index + 1}: {clip.name} is not H.264 video")
    if clip != requested:
        if requested.exists():
            raise RuntimeError(f"scene {index + 1}: refusing to overwrite {requested}")
        clip.replace(requested)
    return requested


def render_scene(episode, scene, window, work, diagnostics):
    index = scene["index"]
    spec = dict(scene)
    spec["on_screen_text"] = scene.get("on_screen_text", "")
    spec_path = work / f"scene_{index:02d}.json"
    spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    raw = work / f"segment_{index:02d}.mp4"
    for stale in raw.parent.glob(raw.stem + "*"):
        stale.unlink()
    blender = shutil.which("blender")
    if not blender:
        raise RuntimeError("Blender is required but was not found on PATH")
    log_path = work / f"scene_{index:02d}_blender.log"
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               MKL_NUM_THREADS="1", OPENCV_OPENCL_RUNTIME="disabled")
    seconds = window["frames"] / FPS
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            [blender, "-b", "-t", "2", "--python-exit-code", "1",
             "--python", str(ROOT / "src" / "blender_scene.py"),
             "--", str(spec_path), str(raw), str(index), str(len(episode["scenes"])),
             f"{seconds:.4f}"],
            stdout=log, stderr=subprocess.STDOUT, text=True, env=env, timeout=600,
        )
    if result.returncode:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"Blender failed for scene {index + 1} "
                           f"(exit {result.returncode}):\n{tail}")
    try:
        clip = normalize_blender_output(raw, index)
    except RuntimeError as exc:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        diagnostics.append("scene_render_failure",
                           {"scene_index": index, "error": str(exc), "log_tail": tail})
        raise
    trace_path = clip.with_name(clip.stem + ".visual.json")
    if not trace_path.is_file():
        raise RuntimeError(f"scene {index + 1}: renderer produced no visual trace")
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    return clip, trace


def render_episode(episode, windows, work, diagnostics):
    segments, traces = [], []
    for scene, window in zip(episode["scenes"], windows):
        print(f"[render] scene {scene['index'] + 1}/{len(episode['scenes'])} "
              f"{scene_spec.template_id(scene)} ({window['duration']:.2f}s)", flush=True)
        clip, trace = render_scene(episode, scene, window, work, diagnostics)
        cards = narration_mod.caption_cards(window["narration"], window["duration"])
        final = work / f"final_segment_{scene['index']:02d}.mp4"
        encode_segment(clip, cards, window["duration"], final, work)
        segments.append(final)
        traces.append(trace)
        diagnostics.append("scene_rendered", {
            "scene_index": scene["index"], "template": trace.get("template"),
            "duration": window["duration"], "frames": window["frames"],
            "displacement": trace.get("measured", {}).get("mover", {}).get("displacement"),
            "screen_pixels": trace.get("measured", {}).get("mover", {}).get("screen_pixels"),
        })
    return segments, traces


def concat_video(segments, out_path):
    listing = out_path.parent / "segments.txt"
    listing.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in segments) + "\n",
                       encoding="utf-8")
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", str(out_path)],
        check=False, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"segment concatenation failed: {result.stderr[-400:]}")
    return out_path


def mux_delivery(video, wav, out_path):
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(wav),
         "-map", "0:v:0", "-map", "1:a:0",
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000",
         "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
         "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "48000",
         "-movflags", "+faststart", str(out_path)],
        check=False, capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f"final mux failed: {result.stderr[-500:]}")
    return out_path


def decide_failures(scene_summary, diversity, captions, delivery_qa, final_motion):
    """Single place that decides whether a delivery is acceptable."""
    failed = []
    if not scene_summary.get("passed"):
        failed.append("scene_qa")
    if not diversity.get("passed"):
        failed.append("scene_diversity")
    if not captions.get("passed"):
        failed.append("caption_alignment")
    if not delivery_qa.get("passed"):
        failed.append("delivery_media")
    if (final_motion or {}).get("mean", 0.0) < 0.35:
        failed.append("visual_motion")
    return failed


# --- main ------------------------------------------------------------------
def prepare_dirs():
    OUT.mkdir(exist_ok=True)
    # Never delete output/diagnostics: the workflow writes run context there.
    for name in ("cards", "render", "segments", "delivery"):
        target = OUT / name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
    for stale in OUT.iterdir():
        if stale.is_file() and stale.name != ".gitkeep":
            stale.unlink()
    return OUT / "render", OUT / "cards", OUT / "delivery"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Digital Edge Lab pilot pipeline")
    parser.add_argument("--plan", help="checked-in JSON episode plan (deterministic)")
    parser.add_argument("--offline", action="store_true",
                        help="no API calls; requires --plan and a local voice")
    parser.add_argument("--keep-output", action="store_true")
    args = parser.parse_args(argv)

    if args.offline and not args.plan:
        fail("--offline requires --plan")

    work, cards_dir, delivery = prepare_dirs()
    diagnostics = Diagnostics(OUT / "diagnostics.json")
    diagnostics.set("run", {
        "status": "started",
        "at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline" if args.offline else "generated",
        "plan": args.plan,
        "configured_text_model": TEXT_MODEL,
        "configured_tts_model": TTS_MODEL,
        "commit": os.getenv("GITHUB_SHA"),
        "run_id": os.getenv("GITHUB_RUN_ID"),
    })
    print("Digital Edge Lab: building one pilot episode (not publishing).", flush=True)

    memory_file = ROOT / "memory" / "channel-memory.json"
    try:
        memory = json.loads(memory_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        memory = {"persona": "Edge", "channel_name": "Digital Edge Lab",
                  "recent_topics": [], "running_context": [], "principles": []}

    client = None
    if not args.offline:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            fail("GEMINI_API_KEY is not set. Add it as a repository secret, or run "
                 "--offline --plan <file> for a no-API verification build.",
                 diagnostics)
        client = GeminiClient(api_key, log=lambda event: diagnostics.append("gemini", event))

    try:
        episode = load_plan(args.plan) if args.plan else generate_episode(client, memory, diagnostics)
    except (RuntimeError, GeminiError) as exc:
        fail(f"plan generation failed: {exc}", diagnostics)
    (OUT / "episode-plan.json").write_text(json.dumps(episode, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
    print(f"[plan] {episode['title']} ({len(episode['scenes'])} scenes, "
          f"{len(episode['narration'].split())} words, origin={episode['origin']})", flush=True)

    try:
        wav, windows, narration_report = narration_mod.synthesize(
            episode, work / "narration", client=client, tts_model=TTS_MODEL,
            offline=args.offline)
    except narration_mod.NarrationError as exc:
        fail(f"narration failed: {exc}", diagnostics)
    diagnostics.set("narration", narration_report)
    (OUT / "narration.txt").write_text(episode["narration"], encoding="utf-8")
    total_audio = windows[-1]["end"]
    print(f"[narration] {narration_report['engine']} · {total_audio:.2f}s "
          f"({len(windows)} beats)", flush=True)

    try:
        segments, traces = render_episode(episode, windows, work, diagnostics)
    except RuntimeError as exc:
        fail(str(exc), diagnostics)

    # --- per-scene QA -----------------------------------------------------
    scene_reports, mid_frames = [], {}
    for scene, window, trace, segment in zip(episode["scenes"], windows, traces, segments):
        report = media_qa.evaluate_scene(scene, window, segment, trace, scene_spec)
        scene_reports.append(report)
        midpoint = window["duration"] / 2
        mid_frames[scene["index"]] = media_qa.extract_frame(
            segment, midpoint, cards_dir / f"mid_{scene['index']:02d}.png", 360, 640)
        status = "PASS" if report["passed"] else "FAIL"
        print(f"[qa] scene {scene['index'] + 1} {status} "
              f"template={report['template']} "
              f"motion={report['measured']['displacement']} "
              f"screen={report['measured']['screen_pixels']}px", flush=True)
        diagnostics.append("scene_qa", report)

    similarity = {}
    for a, path_a in mid_frames.items():
        similarity[str(a)] = {}
        for b, path_b in mid_frames.items():
            similarity[str(a)][str(b)] = 1.0 if a == b else round(
                media_qa.image_similarity(path_a, path_b), 4)
    diversity = media_qa.check_scene_diversity(scene_reports, similarity)
    captions = media_qa.caption_alignment(
        [narration_mod.caption_cards(w["narration"], w["duration"]) for w in windows],
        windows, episode["beats"])
    scene_summary = media_qa.summarise(scene_reports)

    silent_video = work / "visuals.mp4"
    try:
        concat_video(segments, silent_video)
        final = mux_delivery(silent_video, wav, OUT / "digital-edge-lab-pilot.mp4")
    except RuntimeError as exc:
        fail(str(exc), diagnostics)

    delivery_qa = media_qa.verify_delivery(final, width=W, height=H, fps=FPS, min_seconds=25.0,
                                           max_seconds=70.0)
    contact = media_qa.contact_sheet(final, OUT / "contact-sheet.jpg")
    final_motion = media_qa.motion_stats(final)

    sources = validate_sources(episode)
    diagnostics.set("sources", sources)

    gates = {
        "plan_validated": True,
        "narrated_audio_present": narration_report["total_seconds"] > 20,
        "scene_qa": scene_summary,
        "scene_diversity": diversity,
        "caption_alignment": captions,
        "delivery_media": delivery_qa,
        "visual_motion": final_motion,
    }
    failed_gates = decide_failures(scene_summary, diversity, captions, delivery_qa,
                                   final_motion)

    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "failed_qa" if failed_gates else "verified_delivery",
        "title": episode["title"],
        "topic": episode["topic"],
        "origin": episode["origin"],
        "scene_count": len(episode["scenes"]),
        "narration": {
            "engine": narration_report["engine"],
            "publication_quality_voice": narration_report["publication_quality_voice"],
            "seconds": narration_report["total_seconds"],
            "words": len(episode["narration"].split()),
            "beats": narration_report["beats"],
        },
        "timeline": [{k: w[k] for k in ("index", "beat_id", "role", "start", "end",
                                        "duration", "frames", "narration")} for w in windows],
        "scenes": scene_reports,
        "scene_diversity": diversity,
        "caption_alignment": captions,
        "delivery_media": delivery_qa,
        "visual_motion": final_motion,
        "sources": sources,
        "gates": gates,
        "failed_gates": failed_gates,
        "video_file": final.name,
        "publishing": {"youtube": "not_implemented", "tiktok": "not_implemented"},
        "editorial_review": {
            "source_claim_support": "HUMAN_REVIEW_REQUIRED",
            "publication_ready": False,
            "note": "Automated QA verifies construction, animation, timing and media "
                    "integrity. Editorial accuracy and taste still require human review.",
        },
    }
    (OUT / "run-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                         encoding="utf-8")

    # --- delivery bundle --------------------------------------------------
    for name in (final.name, "run-report.json", "episode-plan.json", "narration.txt",
                 "contact-sheet.jpg"):
        source = OUT / name
        if source.exists():
            shutil.copy2(source, delivery / name)
    shutil.copy2(wav, delivery / "narration.wav")
    review = delivery / "scene-review"
    review.mkdir(exist_ok=True)
    for trace_file in work.glob("segment_*.visual.json"):
        shutil.copy2(trace_file, review / trace_file.name)
    for scene_file in work.glob("scene_*.json"):
        shutil.copy2(scene_file, review / scene_file.name)
    for log_file in work.glob("scene_*_blender.log"):
        shutil.copy2(log_file, review / log_file.name)
    for frame in cards_dir.glob("mid_*.png"):
        shutil.copy2(frame, review / frame.name)
    for public, path in (("diagnostics.json", OUT / "diagnostics.json"),
                         ("contact-sheet.jpg", contact)):
        if path.exists():
            shutil.copy2(path, delivery / public)

    report["delivery_path"] = str(delivery)
    (OUT / "run-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    shutil.copy2(OUT / "run-report.json", delivery / "run-report.json")

    print(json.dumps({"status": report["status"], "failed_gates": failed_gates,
                      "duration": delivery_qa["duration_seconds"],
                      "resolution": f"{delivery_qa['width']}x{delivery_qa['height']}",
                      "scenes": len(scene_reports),
                      "distinct_templates": diversity["distinct_templates"]}, indent=2),
          flush=True)
    if failed_gates:
        fail("delivery rejected by QA: " + ", ".join(failed_gates), diagnostics)
    diagnostics.set("run", dict(diagnostics.data["run"], status="verified_delivery"))

    # Candidate narrator memory is written only after every gate passed.
    candidate = dict(memory)
    history = list(memory.get("recent_topics", []))
    history.append({"title": episode["title"], "topic": episode["topic"],
                    "created_at_utc": datetime.now(timezone.utc).isoformat()})
    candidate["recent_topics"] = history[-30:]
    context = list(memory.get("running_context", []))
    context.append(f"Episode: {episode['title']} — {episode['topic']}")
    candidate["running_context"] = context[-20:]
    (OUT / "channel-memory.json").write_text(json.dumps(candidate, indent=2, ensure_ascii=False),
                                             encoding="utf-8")
    print("Pilot rendered and verified. Editorial review is still required before publishing.")


if __name__ == "__main__":
    main()
