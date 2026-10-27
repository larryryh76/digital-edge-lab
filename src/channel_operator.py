"""Minimal real local operator API backed by SQLite; no mocked progress.

Run: python src/channel_operator.py serve
The server binds to loopback only. It can start the repository's actual offline pilot,
persist user instructions/jobs, and honestly reports story-generation/publishing blockers.
"""
from __future__ import annotations
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
DB_PATH = Path(os.getenv("DEL_OPERATOR_DB", ROOT / "output" / "operator.sqlite3"))
MEMORY_PATH = Path(os.getenv("DEL_CHANNEL_MEMORY", ROOT / "memory" / "channel-memory.json"))
PLAN_PATH = Path(os.getenv("DEL_PILOT_PLAN", ROOT / "plans" / "quantization-on-device.json"))
LOCK = threading.RLock()
PROCESSES = {}


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=15000")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY, kind TEXT NOT NULL, instruction TEXT NOT NULL,
      status TEXT NOT NULL, stage TEXT NOT NULL, created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL, result_json TEXT, error TEXT, pid INTEGER
    );
    CREATE TABLE IF NOT EXISTS conversation (
      id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
      role TEXT NOT NULL, message TEXT NOT NULL, job_id TEXT
    );
    CREATE TABLE IF NOT EXISTS operator_state (
      key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    """)
    return db


def job_create(kind, instruction, status="queued", stage="queued"):
    job_id = str(uuid.uuid4())
    with connect() as db:
        db.execute("INSERT INTO jobs(id,kind,instruction,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                   (job_id, kind, instruction, status, stage, now(), now()))
    return job_get(job_id)


def job_get(job_id):
    with connect() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _job_dict(row) if row else None


def _job_dict(row):
    result = dict(row)
    result["result"] = json.loads(result.pop("result_json") or "null")
    return result


def jobs_list(limit=25):
    with connect() as db:
        rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(100, limit)),)).fetchall()
    return [_job_dict(row) for row in rows]


def update_job(job_id, **fields):
    allowed = {"status", "stage", "result_json", "error", "pid"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    updates["updated_at"] = now()
    if not updates:
        return job_get(job_id)
    sql = ", ".join(k + "=?" for k in updates)
    with connect() as db:
        db.execute("UPDATE jobs SET " + sql + " WHERE id=?", (*updates.values(), job_id))
    return job_get(job_id)


def conversation(role, message, job_id=None):
    with connect() as db:
        db.execute("INSERT INTO conversation(created_at,role,message,job_id) VALUES(?,?,?,?)",
                   (now(), role, str(message)[:8000], job_id))


def recent_conversation(limit=30):
    with connect() as db:
        rows = db.execute("SELECT * FROM conversation ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in reversed(rows)]


def execute_pilot(job_id, instruction):
    """Run actual pipeline once; state and terminal outcome are persisted."""
    with LOCK:
        current = job_get(job_id)
        if not current or current["status"] not in ("queued", "retrying"):
            return
        update_job(job_id, status="running", stage="starting real offline pilot", error=None)
        conversation("system", "Started actual offline pilot subprocess.", job_id)
        command = [sys.executable, str(ROOT / "src" / "pipeline.py"), "--offline", "--plan", str(PLAN_PATH)]
        try:
            process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, bufsize=1)
            PROCESSES[job_id] = process
            update_job(job_id, pid=process.pid, stage="rendering and quality assurance")
            output = []
            for line in process.stdout:
                line = line.rstrip()
                output.append(line)
                # Stage labels are extracted from actual pipeline output, not fabricated.
                if line.startswith("["):
                    stage = line.split("]", 1)[0].lstrip("[")[:100]
                    update_job(job_id, stage=stage)
            code = process.wait()
            if job_get(job_id) and job_get(job_id)["status"] == "cancelled":
                return
            tail = "\n".join(output[-80:])[-16000:]
            delivery = None
            delivery_error = None
            if code == 0:
                try:
                    video_path, report = _latest_verified_video()
                    delivery = {"report": report, "video_path": str(video_path), "bytes": video_path.stat().st_size}
                except Exception as exc:
                    delivery_error = str(exc)
            if code == 0 and delivery:
                update_job(job_id, status="completed", stage="QA-passed artifact verified", pid=None,
                           result_json=json.dumps({"exit_code": code, "delivery": delivery, "log_tail": tail}))
                conversation("assistant", "Offline pilot passed report and MP4 existence checks. Visual review is still required before publishing.", job_id)
            else:
                failure = delivery_error or tail[-6000:] or "Pipeline exited unsuccessfully."
                update_job(job_id, status="failed", stage="failed or delivery QA missing", pid=None,
                           error=failure[-6000:], result_json=json.dumps({"exit_code": code, "delivery_error": delivery_error, "log_tail": tail}))
                conversation("assistant", "Pilot did not produce a confirmed QA-passed artifact. No completion was claimed.", job_id)
        except Exception as exc:
            update_job(job_id, status="failed", stage="failed to launch", pid=None, error=str(exc)[:6000])
        finally:
            PROCESSES.pop(job_id, None)


def execute_generated_episode(job_id, topic, series_id, episode_id):
    """Generate a topic-directed episode through the real Gemini + narration + Blender pipeline."""
    current = job_get(job_id)
    if not current or current["status"] not in ("queued", "retrying"):
        return
    if not os.getenv("GEMINI_API_KEY"):
        update_job(job_id, status="blocked", stage="missing GEMINI_API_KEY",
                   error="Set GEMINI_API_KEY in the local environment, then retry this job.")
        return
    update_job(job_id, status="running", stage="research/story planning", error=None)
    conversation("system", "Started topic-directed Gemini episode generation and the real production pipeline.", job_id)
    command = [sys.executable, str(ROOT / "src" / "pipeline.py"),
               "--topic", topic, "--series-id", series_id, "--episode-id", episode_id]
    try:
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, bufsize=1)
        PROCESSES[job_id] = process
        update_job(job_id, pid=process.pid, stage="research/story planning")
        output = []
        for line in process.stdout:
            line = line.rstrip()
            output.append(line)
            if line.startswith("["):
                update_job(job_id, stage=line.split("]", 1)[0].lstrip("[")[:100])
        code = process.wait()
        if job_get(job_id) and job_get(job_id)["status"] == "cancelled":
            return
        tail = "\n".join(output[-100:])[-18000:]
        report_path = ROOT / "output" / "run-report.json"
        report = None
        if code == 0 and report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                report = None
        if code == 0 and report and report.get("status") in ("verified_delivery", "verified_degraded_delivery"):
            update_job(job_id, status="completed", stage="QA-passed episode delivered", pid=None,
                       result_json=json.dumps({"exit_code": code, "report": report, "log_tail": tail,
                                                "series_id": series_id, "episode_id": episode_id}))
            conversation("assistant", "Episode passed the pipeline's delivery QA gates. Review the generated MP4 and report before publishing.", job_id)
        else:
            update_job(job_id, status="failed", stage="failed or QA rejected", pid=None,
                       error=tail[-6000:] or "Pipeline exited without a QA-passed run-report.",
                       result_json=json.dumps({"exit_code": code, "report": report, "log_tail": tail,
                                                "series_id": series_id, "episode_id": episode_id}))
            conversation("assistant", "Episode generation failed or did not pass delivery QA. No completed episode was claimed.", job_id)
    except Exception as exc:
        update_job(job_id, status="failed", stage="failed to launch", pid=None, error=str(exc)[:6000])
    finally:
        PROCESSES.pop(job_id, None)


def _latest_verified_video():
    report_path = ROOT / "output" / "run-report.json"
    if not report_path.is_file():
        raise RuntimeError("No pipeline run-report exists. Generate and QA an episode first.")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Latest run-report is unreadable: " + str(exc)[:200]) from exc
    if report.get("status") not in ("verified_delivery", "verified_degraded_delivery"):
        raise RuntimeError("Latest pipeline report is not QA-passed; publishing is blocked.")
    candidates = []
    raw = report.get("video_file") or report.get("video_path")
    if raw:
        p = Path(raw)
        candidates.extend([p if p.is_absolute() else ROOT / p, ROOT / "output" / "delivery" / p.name, ROOT / "output" / p.name])
    candidates.extend([ROOT / "output" / "delivery" / "digital-edge-lab-pilot.mp4",
                       ROOT / "output" / "delivery" / "pilot.mp4"])
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0 and path.suffix.lower() == ".mp4":
            return path.resolve(), report
    raise RuntimeError("Run-report says delivery passed, but its referenced MP4 is missing or empty.")


def _research_topic(topic):
    """Run a bounded Gemini Google Search-grounded research request and persist source notes."""
    topic = str(topic).strip()
    if not topic or len(topic) > 240:
        raise ValueError("topic must contain 1-240 characters")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Grounded research requires GEMINI_API_KEY; no research request was made.")
    import requests
    model = os.getenv("DEL_RESEARCH_MODEL", os.getenv("DEL_AGENT_MODEL", "gemini-2.5-flash"))
    prompt = (
        "Research this topic for a short educational video: " + topic + "\n"
        "Use Google Search grounding. Return concise findings, dates/context, uncertainties, "
        "and avoid unsupported statistics. Distinguish established facts from interpretation. "
        "Do not invent citations; source URLs will be taken from grounding metadata."
    )
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                  "tools": [{"google_search": {}}],
                  "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1400}},
            timeout=(8, 50))
    except requests.RequestException as exc:
        raise RuntimeError("Grounded research request failed: " + str(exc)[:250]) from exc
    if response.status_code >= 400:
        raise RuntimeError(f"Grounded research API returned HTTP {response.status_code}: {response.text[:350]}")
    try:
        payload = response.json()
        candidate = payload["candidates"][0]
        findings = "\n".join(p.get("text", "") for p in candidate["content"]["parts"] if p.get("text")).strip()
        metadata = candidate.get("groundingMetadata", {})
        chunks = metadata.get("groundingChunks", [])
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Grounded research returned a malformed response.") from exc
    sources, seen = [], set()
    for chunk in chunks:
        web = chunk.get("web", {}) if isinstance(chunk, dict) else {}
        url = str(web.get("uri", "")).strip()
        if url.startswith("https://") and url not in seen:
            seen.add(url)
            sources.append({"title": str(web.get("title", ""))[:250], "url": url})
    if not findings or not sources:
        raise RuntimeError("Research did not return findings plus Google grounding source URLs; refusing to save ungrounded notes.")
    record = {"research_id": str(uuid.uuid4()), "topic": topic, "created_at": now(),
              "provider": "Google Gemini Google Search grounding", "model": model,
              "findings": findings[:9000], "sources": sources[:12],
              "verification_status": "grounded_sources_returned_claim_review_still_required"}
    from channel_memory import ChannelMemory
    store = ChannelMemory(MEMORY_PATH)
    data = store.load()
    same = next((item for item in reversed(data.get("research", []))
                 if item.get("topic", "").strip().casefold() == topic.casefold()
                 and {s.get("url") for s in item.get("sources", [])} == {s.get("url") for s in record["sources"]}), None)
    if same:
        return {"research": same, "duplicate_prevented": True}
    data.setdefault("research", []).append(record)
    data["research"] = data["research"][-100:]
    store.save(data)
    return {"research": record, "duplicate_prevented": False}


def _agent_tool(name, args):
    from channel_memory import ChannelMemory
    memory = ChannelMemory(MEMORY_PATH)
    if name == "list_jobs":
        return {"jobs": jobs_list(args.get("limit", 20))}
    if name == "get_channel_memory":
        data = memory.load()
        series_id = args.get("series_id")
        if series_id and series_id not in data.get("series", {}):
            return {"found": False, "series_id": series_id, "available_series": list(data.get("series", {}))[:30]}
        context = memory.context_for(series_id=series_id) if series_id else data
        # Keep tool context bounded so large archives do not overwhelm the model.
        if not series_id:
            context = {k: context.get(k) for k in ("schema_version", "channel", "series", "episodes", "characters", "timelines", "research", "production_history", "publishing", "analytics", "recent_topics")}
            context["episodes"] = dict(list(context.get("episodes", {}).items())[-12:])
            context["research"] = context.get("research", [])[-20:]
            context["production_history"] = context.get("production_history", [])[-20:]
        return {"found": True, "memory": context}
    if name == "cancel_job":
        job_id = str(args["job_id"]).strip()
        job = job_get(job_id)
        if not job:
            raise ValueError("No job exists with that exact ID.")
        process = PROCESSES.get(job_id)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            cancelled = update_job(job_id, status="cancelled", stage="cancelled by operator", pid=None)
            conversation("system", "Cancellation sent to actual subprocess for job " + job_id, job_id)
            return {"cancelled": True, "job": cancelled, "evidence": "subprocess termination requested"}
        if job["status"] in ("queued", "retrying", "paused", "blocked"):
            cancelled = update_job(job_id, status="cancelled", stage="cancelled before execution")
            return {"cancelled": True, "job": cancelled, "evidence": "job was not actively running"}
        return {"cancelled": False, "job": job, "reason": "job is already terminal or has no active subprocess"}
    if name == "retry_job":
        job_id = str(args["job_id"]).strip()
        old_job = job_get(job_id)
        if not old_job:
            raise ValueError("No job exists with that exact ID.")
        if old_job["status"] not in ("failed", "cancelled", "blocked", "interrupted"):
            raise ValueError("Only failed, cancelled, blocked or interrupted jobs can be retried.")
        new_job = job_create(old_job["kind"], old_job["instruction"], status="retrying", stage="retry queued")
        old_result = old_job.get("result") if isinstance(old_job.get("result"), dict) else {}
        if old_job["kind"] == "offline_pilot":
            threading.Thread(target=execute_pilot, args=(new_job["id"], new_job["instruction"]), daemon=True).start()
            return {"retry_started": True, "previous_job_id": job_id, "job": job_get(new_job["id"])}
        if old_job["kind"] == "generated_episode":
            from channel_memory import ChannelMemory
            data = memory.load()
            series_id = old_result.get("series_id")
            episode_id = old_result.get("episode_id")
            if not series_id or not episode_id:
                topic_key = old_job["instruction"].strip().casefold()
                matches = [ep for ep in data.get("episodes", {}).values()
                           if str(ep.get("topic", "")).strip().casefold() == topic_key
                           and ep.get("status") in ("queued", "failed", "interrupted")]
                if matches:
                    ep = sorted(matches, key=lambda item: item.get("episode_number") or 0)[-1]
                    series_id, episode_id = ep.get("series_id"), ep.get("episode_id")
            episode = data.get("episodes", {}).get(episode_id) if episode_id else None
            if not series_id or not episode:
                update_job(new_job["id"], status="blocked", stage="episode context unavailable",
                           error="Could not safely recover the original series/episode ID; no duplicate episode was created.")
                return {"retry_started": False, "previous_job_id": job_id, "job": job_get(new_job["id"])}
            update_job(new_job["id"], result_json=json.dumps({"series_id": series_id, "episode_id": episode_id}))
            threading.Thread(target=execute_generated_episode,
                args=(new_job["id"], episode.get("topic", old_job["instruction"]), series_id, episode_id),
                daemon=True).start()
            return {"retry_started": True, "previous_job_id": job_id, "series_id": series_id,
                    "episode_id": episode_id, "job": job_get(new_job["id"])}
        update_job(new_job["id"], status="blocked", stage="no retry executor",
                   error="No retry executor is registered for job type " + old_job["kind"])
        return {"retry_started": False, "previous_job_id": job_id, "job": job_get(new_job["id"])}
    if name == "research_topic":
        return _research_topic(args["topic"])
    if name == "start_episode":
        topic = str(args["topic"]).strip()
        if not topic or len(topic) > 240:
            raise ValueError("topic must contain 1-240 characters")
        continue_existing = args["continue_existing"]
        data = memory.load()
        series_id = str(args.get("series_id", "")).strip() or None
        if continue_existing:
            if series_id:
                series = data.get("series", {}).get(series_id)
            else:
                active = [s for s in data.get("series", {}).values() if s.get("status") == "active"]
                series = sorted(active, key=lambda s: s.get("created_at", ""))[-1] if active else None
                series_id = series.get("series_id") if series else None
            if not series:
                raise RuntimeError("No active series was found. Start a new series first or supply a valid series_id.")
            episode_topic = topic if topic.lower() not in ("next episode", "continue", "continue the story", "next") else series.get("title", series_id)
            existing = [e for e in data.get("episodes", {}).values()
                        if e.get("series_id") == series_id and e.get("status") in ("queued", "failed", "interrupted")]
            if existing:
                episode = sorted(existing, key=lambda e: e.get("episode_number") or 0)[-1]
                episode_id = episode["episode_id"]
            else:
                number = max([int(e.get("episode_number") or 0) for e in data.get("episodes", {}).values()
                              if e.get("series_id") == series_id] + [0]) + 1
                episode_id = f"{series_id}-e{number:02d}"
                episode = memory.create_episode(episode_id, title=f"{series.get('title', series_id)} — Episode {number}",
                    topic=episode_topic, series_id=series_id, episode_number=number)
        else:
            series_id = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:64] or "new-series"
            if series_id not in data.get("series", {}):
                data.setdefault("series", {})[series_id] = {"series_id": series_id, "title": topic,
                    "status": "active", "episode_ids": [], "created_at": now(),
                    "editorial_note": "Canonical episode memory is committed only after delivery QA passes."}
                memory.save(data)
            series = memory.load()["series"][series_id]
            number = max([int(e.get("episode_number") or 0) for e in memory.load().get("episodes", {}).values()
                          if e.get("series_id") == series_id] + [0]) + 1
            episode_id = f"{series_id}-e{number:02d}"
            episode = memory.create_episode(episode_id, title=f"{topic} — Episode {number}",
                topic=topic, series_id=series_id, episode_number=number)
        if not os.getenv("GEMINI_API_KEY"):
            blocked = job_create("generated_episode", topic, status="blocked", stage="missing GEMINI_API_KEY")
            update_job(blocked["id"], error="Set GEMINI_API_KEY in the local environment before AI generation.",
                       result_json=json.dumps({"series_id": series_id, "episode_id": episode_id}))
            return {"started": False, "blocked": True, "reason": "GEMINI_API_KEY is missing; the episode was not generated.",
                    "series_id": series_id, "episode_id": episode_id, "job": job_get(blocked["id"])}
        job = job_create("generated_episode", topic)
        update_job(job["id"], result_json=json.dumps({"series_id": series_id, "episode_id": episode_id}))
        thread = threading.Thread(target=execute_generated_episode,
            args=(job["id"], episode_topic if continue_existing else topic, series_id, episode_id), daemon=True)
        thread.start()
        return {"started": True, "series_id": series_id, "episode_id": episode_id, "job": job_get(job["id"]),
                "note": "Background job started; this is not a completion claim."}
    if name == "run_offline_pilot":
        job = job_create("offline_pilot", "Run deterministic offline production pilot")
        threading.Thread(target=execute_pilot, args=(job["id"], job["instruction"]), daemon=True).start()
        return {"started": True, "job": job_get(job["id"]), "note": "Background job started; poll status before claiming success."}
    if name == "diagnose_recent_failures":
        limit = args.get("limit", 10)
        failures = [j for j in jobs_list(100) if j.get("status") in ("failed", "blocked", "cancelled", "interrupted")]
        return {"failures": failures[:limit], "count": len(failures),
                "note": "These are persisted operator job records; they do not prove the root cause beyond their stored error evidence."}
    if name == "inspect_latest_artifact":
        video, report = _latest_verified_video()
        result = {"report_status": report.get("status"), "report": report,
                  "video_path": str(video), "bytes": video.stat().st_size}
        try:
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
                "-of", "json", str(video)], capture_output=True, text=True, timeout=15, check=False)
            result["ffprobe_exit_code"] = probe.returncode
            if probe.returncode == 0:
                result["media_streams"] = json.loads(probe.stdout)
            else:
                result["ffprobe_error"] = probe.stderr[-500:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["ffprobe_error"] = str(exc)[:300]
        return result
    if name == "prepare_tiktok_manual_upload":
        video, report = _latest_verified_video()
        from tiktok_publisher import prepare_for_manual_upload
        result = prepare_for_manual_upload(video, args["title"])
        return {"package": result, "report_status": report.get("status"), "published": False}
    if name == "get_youtube_analytics":
        from youtube_publisher import build_youtube_analytics_service, fetch_video_analytics
        service = build_youtube_analytics_service()
        result = fetch_video_analytics(args["video_id"], args["start_date"], args["end_date"],
                                       analytics_service=service)
        data = memory.load()
        data.setdefault("analytics", []).append({"platform": "youtube", "video_id": args["video_id"],
            "start_date": args["start_date"], "end_date": args["end_date"], "fetched_at": now(),
            "result": result})
        data["analytics"] = data["analytics"][-100:]
        memory.save(data)
        return {"analytics": result, "stored": True, "video_id": args["video_id"],
                "date_range": [args["start_date"], args["end_date"]]}
    if name == "upload_youtube_private":
        video, report = _latest_verified_video()
        from youtube_publisher import upload_video
        metadata = {"title": args["title"], "description": args.get("description", ""),
                    "privacy_status": "private", "tags": ["Digital Edge Lab", "education"]}
        result = upload_video(video, metadata, approval=False)
        # The publisher returns a platform ID/URL only after the API actually confirms an upload.
        data = memory.load()
        data.setdefault("publishing", {}).setdefault("youtube", []).append({
            "video_id": result.get("video_id"), "url": result.get("url"), "status": result.get("status"),
            "fingerprint": result.get("fingerprint"), "at": now(), "source_video": str(video)})
        memory.save(data)
        return {"upload": result, "report_status": report.get("status"), "video_path": str(video)}
    raise ValueError("No registered tool executor for " + name)


def _agent_chat(message):
    from agent_runtime import AgentError, GeminiToolAgent
    # Persist the user turn first; the model receives previous turns, not a duplicate current turn.
    conversation("user", message)
    history = recent_conversation(20)
    if history and history[-1].get("role") == "user" and history[-1].get("message") == message:
        history = history[:-1]
    try:
        response = GeminiToolAgent().run(message, history, _agent_tool)
        assistant_text = response.get("message", "")
        for tool_call in response.get("tool_calls", []):
            # Preserve evidence of model-selected actions and actual tool outcomes across restarts.
            conversation("system", "Agent tool result: " + json.dumps(tool_call, ensure_ascii=False)[:6500])
        conversation("assistant", assistant_text)
        return {**response, "message": assistant_text}
    except AgentError as exc:
        response = {"ok": False, "message": str(exc), "provider": "Google Gemini",
                    "model": os.getenv("DEL_AGENT_MODEL", "gemini-2.5-flash"), "tool_calls": []}
        conversation("assistant", response["message"])
        return response
    except Exception as exc:
        response = {"ok": False, "message": "Agent request failed safely: " + str(exc)[:700],
                    "provider": "Google Gemini", "tool_calls": []}
        conversation("assistant", response["message"])
        return response


def interpret(message):
    """Use the model as the intelligence layer; never silently fall back to keyword routing."""
    text = str(message).strip()
    if not text:
        return {"ok": False, "message": "Enter an instruction."}
    if not os.getenv("GEMINI_API_KEY"):
        conversation("user", text)
        answer = "AI operator unavailable: GEMINI_API_KEY is missing. No model reasoning or tool execution occurred. Set the key in your local environment and restart the operator."
        conversation("assistant", answer)
        return {"ok": False, "message": answer, "provider": "Google Gemini", "tool_calls": []}
    return _agent_chat(text)


INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Digital Edge Lab Operator</title><style>
:root{color-scheme:dark;font:16px system-ui;background:#080b13;color:#e8edf7}body{margin:0 auto;max-width:900px;padding:20px}
h1{font-size:1.35rem}p{color:#9aa8bf}.panel{border:1px solid #26324a;background:#0e1422;border-radius:14px;padding:14px;margin:14px 0}
#messages{height:48vh;min-height:260px;overflow:auto;white-space:pre-wrap;display:flex;flex-direction:column;gap:10px}
.msg{padding:10px 12px;border-radius:10px;background:#172136;overflow-wrap:anywhere}.user{border-left:3px solid #6c8cff}.assistant{border-left:3px solid #29c5d7}
form{display:flex;gap:8px}input{flex:1;min-width:0;background:#080b13;border:1px solid #35415b;color:inherit;border-radius:8px;padding:12px}
button{background:#4f6fe8;color:white;border:0;border-radius:8px;padding:10px 14px;font-weight:650}pre{white-space:pre-wrap;overflow-wrap:anywhere;color:#b9c9e5}
</style></head><body><h1>Digital Edge Lab · Channel Operator</h1>
<p>Gemini model-backed agent · Research, production, memory and publishing tools report their actual results. Missing API access is shown as a blocker.</p>
<div class="panel"><div id="messages" aria-live="polite"></div><form id="chat"><input id="prompt" autocomplete="off" placeholder="Ask naturally: research ancient Rome and produce a Short..." required><button>Send</button></form></div>
<div class="panel"><strong>Persistent jobs</strong><button id="refresh" style="float:right">Refresh</button><pre id="jobs">Loading…</pre></div>
<p>Local-only service · Do not expose this page/API publicly without authentication.</p>
<script>
const messages=document.querySelector('#messages'), jobs=document.querySelector('#jobs');
function line(role,text){const d=document.createElement('div');d.className='msg '+role;d.textContent=role+': '+text;messages.appendChild(d);messages.scrollTop=messages.scrollHeight}
async function refresh(){try{const r=await fetch('/api/jobs');const d=await r.json();jobs.textContent=JSON.stringify(d.jobs.map(j=>({id:j.id,kind:j.kind,status:j.status,stage:j.stage,error:j.error})),null,2)}catch(e){jobs.textContent='Backend unavailable: '+e}}
document.querySelector('#refresh').onclick=refresh;
document.querySelector('#chat').onsubmit=async e=>{e.preventDefault();const input=document.querySelector('#prompt'),message=input.value.trim();if(!message)return;line('user',message);input.value='';try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message})});const d=await r.json();line('assistant',d.message+(d.provider?'\\nModel: '+d.provider+' / '+(d.model||'configured'):'')+(d.tool_calls&&d.tool_calls.length?'\\nTools: '+d.tool_calls.map(t=>t.name+' ['+(t.ok?'ok':t.error||'failed')+']').join(', '):'')+(d.job?'\\nJob '+d.job.id+' · '+d.job.status:'')+(d.jobs?'\\n'+d.jobs.map(j=>j.id+' · '+j.status+' · '+j.stage).join('\\n'):''));await refresh()}catch(err){line('assistant','Request failed: '+err)}};
refresh();fetch('/api/conversation').then(r=>r.json()).then(d=>d.messages.forEach(m=>line(m.role,m.message))).catch(()=>{});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "DigitalEdgeOperator/0.1"
    def _send(self, code, obj):
        payload = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            payload = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        if path == "/health":
            return self._send(200, {"ok": True, "service": "digital-edge-operator", "database": str(DB_PATH)})
        if path == "/api/jobs":
            return self._send(200, {"jobs": jobs_list()})
        if path == "/api/conversation":
            return self._send(200, {"messages": recent_conversation()})
        if path.startswith("/api/jobs/"):
            job = job_get(path.rsplit("/", 1)[-1])
            return self._send(200 if job else 404, {"job": job})
        return self._send(404, {"ok": False, "message": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 64_000:
                return self._send(400, {"ok": False, "message": "Body must be 1..64000 bytes"})
            body = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"ok": False, "message": "Expected JSON"})
        if path == "/api/chat":
            if not isinstance(body.get("message"), str):
                return self._send(400, {"ok": False, "message": "message must be a string"})
            return self._send(200, interpret(body["message"]))
        if path.endswith("/action") and path.startswith("/api/jobs/"):
            action = str(body.get("action", "")).lower()
            return self._send(200, interpret(action + " " + path.split("/")[-2]))
        return self._send(404, {"ok": False, "message": "Not found"})

    def log_message(self, fmt, *args):
        print("operator", self.address_string(), fmt % args, flush=True)


def serve(host="127.0.0.1", port=8765):
    connect().close()
    server = ThreadingHTTPServer((host, int(port)), Handler)
    print(f"Digital Edge Lab operator listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve(os.getenv("DEL_OPERATOR_HOST", "127.0.0.1"), int(os.getenv("DEL_OPERATOR_PORT", "8765")))
    else:
        print(json.dumps(interpret(" ".join(sys.argv[1:])), indent=2))
