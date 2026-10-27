#!/usr/bin/env python3
"""Fast, hosted story-prompt generation for Digital Edge Lab.

Uses only Python's standard library. It does not render video or pretend to.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY = ROOT / "memory" / "channel-memory.json"
OUT = ROOT / "output" / "story-prompt"


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: GEMINI_API_KEY is missing. Add it under GitHub repository Settings > Secrets and variables > Actions.")
        return 2

    model = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash").strip()
    requested_topic = os.environ.get("EPISODE_TOPIC", "").strip()
    memory = {}
    if MEMORY.exists():
        try:
            memory = json.loads(MEMORY.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print("Warning: channel memory could not be parsed; continuing without it.")

    recent = memory.get("recent_topics", [])
    recent_text = "\n".join(
        f"- {item.get('title', '')}: {item.get('topic', '')}"
        for item in recent[-15:] if isinstance(item, dict)
    ) or "- No prior episodes recorded."

    niche = "\n".join(f"- {item}" for item in memory.get("running_context", [])[:5])
    topic_instruction = (
        f"Use this user-requested topic as the starting point: {requested_topic}. Improve the angle if needed, "
        "but keep the core topic."
        if requested_topic else
        "Choose today's strongest specific, surprising, high-retention topic for this channel. It must be distinct "
        "from recent episodes and should offer a concrete reveal or visual demonstration, not a generic listicle."
    )

    prompt = f"""
You are the editorial director and story writer for Digital Edge Lab, a faceless YouTube Shorts channel.
CHANNEL CONTEXT:
{niche}
EDITORIAL RULES:
- The narrator is Edge: curious, sharp, calm, confident, conversational English.
- Make complex AI/technology concepts understandable through a vivid, concrete story.
- Never invent statistics, sources, product tests, personal experience, or guaranteed income claims.
- No generic intro. Hook viewers in the first 1–2 seconds. Every scene must advance the story.
- Create an original, coherent mini-story suitable for a polished cinematic 3D animated vertical video.
RECENT TOPICS TO AVOID REPEATING:
{recent_text}
TASK:
{topic_instruction}

Write a complete video-generator-ready story prompt for a 35–50 second vertical 9:16 Short.
The result must be detailed enough that a video model or production agent can follow it without guessing.
Include all of these sections:
1. TITLE (accurate, intriguing, not clickbait), one-sentence premise, target viewer, and the central question.
2. ORIGINALITY NOTE: how this differs from the recent topics.
3. STORY BEATS: setup, escalation, reveal, consequence, ending/payoff.
4. VISUAL BIBLE: cinematic 3D style, materials, palette, lighting, environment, character/object continuity, and explicit things to avoid.
5. SHOT-BY-SHOT TIMELINE: 5–7 scenes with exact start/end times that add up to the full duration. For every scene specify: narration verbatim; exact visible action; subject placement and scale; camera lens/framing/movement; lighting; transition; sound effects; music behavior; on-screen text if any. Avoid static slideshow shots. Show motion and causal changes in every scene.
6. AUDIO DIRECTION: voice character, pacing, emotional shifts, pronunciation notes, ambience, SFX, music, ducking, and mix priorities. Narration and effects must be synchronized to visible events.
7. VIDEO GENERATOR MASTER PROMPT: one cohesive prompt that can be pasted directly into a text-to-video generator, including native synchronized audio where supported. State 9:16, target duration, scene continuity, camera motion, narration/audio, and a clean final frame.
8. NEGATIVE PROMPT: common failure modes, malformed text, extra limbs/objects, continuity drift, flicker, static scenes, watermarks, subtitles unless specified, abrupt cuts, silent output.
9. FACT-CHECK LIST: factual claims needing verification, and search terms or authoritative source types to verify them. Do not fabricate source URLs.
10. QA CHECKLIST: hook clarity, story coherence, audio presence/synchronization, visual continuity, ending, aspect ratio, and duration.
11. METADATA: title, 2-sentence description, 3–5 relevant hashtags, and a concise thumbnail concept.

Return polished Markdown only. Be specific, cinematic, and production-ready. Do not claim a video has been generated.
""".strip()

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 8192}
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=150) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:3000]
        print(f"Gemini API error (HTTP {exc.code}): {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Gemini request failed: {exc}", file=sys.stderr)
        return 1

    candidates = data.get("candidates", [])
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    story = "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
    if not story or len(story) < 1200:
        print("ERROR: Gemini returned an empty or unexpectedly short story prompt; refusing to save it as complete.", file=sys.stderr)
        print(json.dumps(data, ensure_ascii=False)[:3000], file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    markdown_path = OUT / f"story-prompt-{stamp}.md"
    metadata_path = OUT / f"story-prompt-{stamp}.json"
    markdown_path.write_text(story + "\n", encoding="utf-8")
    metadata_path.write_text(json.dumps({
        "status": "story_prompt_generated",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "requested_topic": requested_topic or None,
        "characters": len(story),
        "markdown_file": markdown_path.name,
        "note": "Story prompt only. No video has been generated by this workflow."
    }, indent=2) + "\n", encoding="utf-8")
    print(f"SUCCESS: wrote {markdown_path} ({len(story)} characters)")
    print(f"Metadata: {metadata_path}")
    print("Next stage is a real video-provider integration; this quick workflow does not render with Blender.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
