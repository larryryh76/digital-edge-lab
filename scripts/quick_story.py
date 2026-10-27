#!/usr/bin/env python3
"""Fast story-prompt generation for Digital Edge Lab; stdlib only, no renderer."""
from __future__ import annotations
import json, os, sys, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY = ROOT / "memory" / "channel-memory.json"
OUT = ROOT / "output" / "story-prompt"

def main() -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("ERROR: GEMINI_API_KEY is missing. Add it in GitHub repository Settings > Secrets and variables > Actions.")
        return 2
    model = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash").strip()
    requested = os.environ.get("EPISODE_TOPIC", "").strip()
    try:
        memory = json.loads(MEMORY.read_text(encoding="utf-8")) if MEMORY.exists() else {}
    except (OSError, json.JSONDecodeError):
        memory = {}
    recent = memory.get("recent_topics", [])
    recent_text = "\n".join(f"- {x.get('title', '')}: {x.get('topic', '')}" for x in recent[-15:] if isinstance(x, dict))
    context = "\n".join(f"- {x}" for x in memory.get("running_context", [])[:5])
    choice = (f"Start with this requested topic: {requested}. Improve the angle but retain the core topic."
              if requested else "Choose today's most compelling, specific and surprising topic for this channel. Avoid repeating recent episodes.")
    prompt = f"""You are the editorial director and story writer for Digital Edge Lab, a faceless YouTube Shorts channel.
CHANNEL CONTEXT:
{context}
RECENT TOPICS TO AVOID:
{recent_text}
TASK: {choice}
Write a complete, production-ready story prompt for a 35–50 second vertical 9:16 Short about AI, technology, digital tools or evidence-based case studies.
Editorial rules: narrator Edge is curious, sharp, calm, confident and conversational; open with a curiosity gap in the first 1–2 seconds; every scene adds new information; explain complex concepts simply through concrete visuals; never invent statistics, sources, product tests, personal experiences or income claims.
Return detailed Markdown with:
1) accurate intriguing title, premise, target viewer and central question;
2) originality note;
3) story arc (setup, escalation, reveal, consequence and payoff);
4) visual bible (cinematic 3D look, palette, materials, lighting, locations, continuity and avoid-list);
5) 5–7 shot-by-shot scenes whose exact timecodes add up to 35–50 seconds; for each include verbatim narration, visible action, subject placement, framing/lens, camera movement, lighting, transition, sound effects, music behavior and any on-screen text;
6) audio direction with voice pacing, pronunciation, ambience, sound design, ducking and synchronization;
7) one cohesive VIDEO GENERATOR MASTER PROMPT ready to paste into a real text-to-video model, including native synchronized audio where supported;
8) negative prompt to prevent static slideshow scenes, flicker, continuity drift, malformed objects/text, watermarks and silent output;
9) factual claims to verify plus suggested search terms/authoritative source types (never fabricate URLs);
10) practical visual/audio/story QA checklist;
11) YouTube metadata: title, short description, 3–5 hashtags and thumbnail concept.
Make motion and cause-and-effect explicit in every shot. Do not claim a video was generated. Return polished Markdown only."""
    body = {"contents":[{"role":"user","parts":[{"text":prompt}]}],
            "generationConfig":{"temperature":0.85,"maxOutputTokens":8192}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","x-goog-api-key":key}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=150) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        print(f"Gemini API HTTP {exc.code}: {exc.read().decode(errors='replace')[:2500]}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Gemini request failed: {exc}", file=sys.stderr)
        return 1
    candidates = data.get("candidates", [])
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    story = "\n".join(p.get("text","") for p in parts if p.get("text")).strip()
    if len(story) < 1200:
        print("ERROR: model response is empty or too short; refusing to mark it complete.", file=sys.stderr)
        print(json.dumps(data, ensure_ascii=False)[:2000], file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    md = OUT / f"story-prompt-{stamp}.md"
    meta = OUT / f"story-prompt-{stamp}.json"
    md.write_text(story + "\n", encoding="utf-8")
    meta.write_text(json.dumps({"status":"story_prompt_generated","created_at_utc":datetime.now(timezone.utc).isoformat(),
        "model":model,"requested_topic":requested or None,"characters":len(story),"markdown_file":md.name,
        "note":"Story prompt only; no video has been generated by this workflow."},indent=2)+"\n",encoding="utf-8")
    print(f"SUCCESS: story prompt created ({len(story)} characters): {md}")
    print(f"Metadata: {meta}")
    print("This quick workflow does not install Blender or render video.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
