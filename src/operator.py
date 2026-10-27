"""Minimal real local operator API backed by SQLite; no mocked progress.

Run: python src/operator.py serve
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
            if code == 0:
                update_job(job_id, status="completed", stage="verified pipeline exit", pid=None,
                           result_json=json.dumps({"exit_code": code, "log_tail": tail}))
                conversation("assistant", "Offline pilot completed successfully. Inspect the run-report and video artifact before publishing.", job_id)
            else:
                update_job(job_id, status="failed", stage="failed", pid=None,
                           error=tail[-6000:], result_json=json.dumps({"exit_code": code, "log_tail": tail}))
                conversation("assistant", "Pilot failed. The stored error and log tail contain the actual failure; no delivery was claimed.", job_id)
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
                       result_json=json.dumps({"exit_code": code, "report": report, "log_tail": tail}))
            conversation("assistant", "Episode passed the pipeline's delivery QA gates. Review the generated MP4 and report before publishing.", job_id)
        else:
            update_job(job_id, status="failed", stage="failed or QA rejected", pid=None,
                       error=tail[-6000:] or "Pipeline exited without a QA-passed run-report.",
                       result_json=json.dumps({"exit_code": code, "report": report, "log_tail": tail}))
            conversation("assistant", "Episode generation failed or did not pass delivery QA. No completed episode was claimed.", job_id)
    except Exception as exc:
        update_job(job_id, status="failed", stage="failed to launch", pid=None, error=str(exc)[:6000])
    finally:
        PROCESSES.pop(job_id, None)


def interpret(message):
    """Small deterministic command router; unknown commands are never claimed as done."""
    text = str(message).strip()
    if not text:
        return {"ok": False, "message": "Enter a command."}
    conversation("user", text)
    low = text.lower()
    if any(k in low for k in ("what are you working on", "status", "show jobs", "production status")):
        result = {"ok": True, "message": "Current persisted production jobs.", "jobs": jobs_list()}
    elif "why did" in low and ("fail" in low or "error" in low or "render" in low):
        failed = [j for j in jobs_list(100) if j["status"] == "failed"]
        result = {"ok": True, "message": "Stored failure evidence from actual job logs.", "jobs": failed[:10]}
    elif any(k in low for k in ("run pilot", "generate pilot", "render pilot", "test production pipeline")):
        job = job_create("offline_pilot", text)
        thread = threading.Thread(target=execute_pilot, args=(job["id"], text), daemon=True)
        thread.start()
        result = {"ok": True, "message": "Started the repository's real offline pilot. Progress will reflect subprocess output.", "job": job_get(job["id"])}
    elif low.startswith("continue"):
        from channel_memory import ChannelMemory
        memory = ChannelMemory(MEMORY_PATH)
        data = memory.load()
        match = re.search(r"continue\s+series\s+([a-z0-9-]+)", low)
        series_id = match.group(1) if match else None
        if series_id:
            series = data.get("series", {}).get(series_id)
        else:
            active = [s for s in data.get("series", {}).values() if s.get("status") == "active"]
            series = sorted(active, key=lambda s: s.get("created_at", ""))[-1] if active else None
            series_id = series.get("series_id") if series else None
        if not series:
            result = {"ok": False, "message": "No active series found. Use 'create a new series about TOPIC' first, or specify 'continue series SERIES_ID'."}
        elif not os.getenv("GEMINI_API_KEY"):
            job = job_create("generated_episode", text, status="blocked", stage="missing GEMINI_API_KEY")
            update_job(job["id"], result_json=json.dumps({"series_id": series_id, "blocked_reason": "Set GEMINI_API_KEY locally to enable topic-directed generation."}))
            result = {"ok": False, "message": "Series found, but episode generation is blocked until GEMINI_API_KEY is configured.", "series": series, "job": job_get(job["id"])}
        else:
            episode_number = len(series.get("episode_ids", [])) + 1
            episode_id = f"{series_id}-e{episode_number:02d}"
            memory.create_episode(episode_id, title=f"{series.get('title', series_id)} — Episode {episode_number}",
                                  topic=series.get("title", series_id), series_id=series_id,
                                  episode_number=episode_number)
            job = job_create("generated_episode", text)
            threading.Thread(target=execute_generated_episode,
                args=(job["id"], series.get("title", series_id), series_id, episode_id),
                daemon=True).start()
            result = {"ok": True, "message": "Continuation queued with this series' completed-episode memory. The real production subprocess will report progress and QA.", "series": memory.load()["series"][series_id], "job": job_get(job["id"])}
    elif "create a new series about " in low or "create new series about " in low:
        from channel_memory import ChannelMemory
        match = re.search(r"series about\s+(.+)$", text, re.I)
        topic = match.group(1).strip(" .!?") if match else "Untitled series"
        memory = ChannelMemory(MEMORY_PATH)
        data = memory.load()
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:64] or "new-series"
        if slug in data["series"]:
            series = data["series"][slug]
            result = {"ok": True, "message": "That series already exists; no duplicate was created.", "series": series}
        else:
            series = {"series_id": slug, "title": topic, "status": "active", "episode_ids": [],
                      "created_at": now(), "editorial_note": "Episode memory is committed only after delivery QA passes."}
            data["series"][slug] = series
            memory.save(data)
            if not os.getenv("GEMINI_API_KEY"):
                job = job_create("generated_episode", text, status="blocked", stage="missing GEMINI_API_KEY")
                update_job(job["id"], result_json=json.dumps({"series_id": slug, "blocked_reason": "Set GEMINI_API_KEY locally to enable topic-directed generation."}))
                result = {"ok": True, "message": "Series saved. Episode generation is blocked until GEMINI_API_KEY is configured; no video was claimed.", "series": series, "job": job_get(job["id"])}
            else:
                episode_number = len(series.get("episode_ids", [])) + 1
                episode_id = f"{slug}-e{episode_number:02d}"
                memory.create_episode(episode_id, title=f"{topic} — Episode {episode_number}",
                                      topic=topic, series_id=slug, episode_number=episode_number)
                job = job_create("generated_episode", text)
                thread = threading.Thread(target=execute_generated_episode,
                    args=(job["id"], topic, slug, episode_id), daemon=True)
                thread.start()
                result = {"ok": True, "message": "Series and episode request saved. The real Gemini-to-Blender pipeline has started; progress and final QA are read from the subprocess.", "series": memory.load()["series"][slug], "job": job_get(job["id"])}
    elif low.startswith(("pause ", "resume ", "cancel ", "retry ")):
        action, _, target = low.partition(" ")
        job = job_get(target.strip())
        if not job:
            result = {"ok": False, "message": "Supply an exact job ID. No job was changed."}
        elif action == "cancel":
            process = PROCESSES.get(job["id"])
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                result = {"ok": True, "message": "Cancellation signal sent to the actual subprocess.", "job": update_job(job["id"], status="cancelled", stage="cancelled")}
            elif job["status"] == "queued":
                result = {"ok": True, "message": "Queued job cancelled.", "job": update_job(job["id"], status="cancelled", stage="cancelled")}
            else:
                result = {"ok": False, "message": "This job is not cancellable in its current state.", "job": job}
        elif action == "pause" and job["status"] == "queued":
            result = {"ok": True, "message": "Queued job paused before execution.", "job": update_job(job["id"], status="paused", stage="paused before execution")}
        elif action == "resume" and job["status"] == "paused":
            resumed = update_job(job["id"], status="queued", stage="resuming queued job")
            if job["kind"] == "offline_pilot":
                threading.Thread(target=execute_pilot, args=(job["id"], job["instruction"]), daemon=True).start()
            else:
                result = {"ok": False, "message": "This paused job type has no resume executor.", "job": resumed}
                conversation("assistant", result["message"], job["id"])
                return result
            result = {"ok": True, "message": "Queued job resumed.", "job": resumed}
        elif action == "retry" and job["status"] in ("failed", "cancelled", "blocked"):
            new = job_create(job["kind"], job["instruction"], status="retrying", stage="retry queued")
            if new["kind"] == "offline_pilot":
                threading.Thread(target=execute_pilot, args=(new["id"], new["instruction"]), daemon=True).start()
            elif new["kind"] == "generated_episode":
                from channel_memory import ChannelMemory
                memory = ChannelMemory(MEMORY_PATH)
                data = memory.load()
                requested = re.search(r"series about\s+(.+)$", new["instruction"], re.I)
                if requested:
                    series_id = re.sub(r"[^a-z0-9]+", "-", requested.group(1).strip(" .!?").lower()).strip("-")[:64]
                else:
                    match = re.search(r"continue\s+series\s+([a-z0-9-]+)", new["instruction"], re.I)
                    series_id = match.group(1) if match else None
                series = data.get("series", {}).get(series_id) if series_id else None
                if series:
                    pending = [ep for ep in data.get("episodes", {}).values()
                               if ep.get("series_id") == series_id and ep.get("status") == "queued"]
                    if pending:
                        episode = sorted(pending, key=lambda ep: ep.get("episode_number") or 0)[-1]
                    else:
                        number = len(series.get("episode_ids", [])) + 1
                        episode_id = f"{series_id}-e{number:02d}"
                        episode = memory.create_episode(episode_id, title=f"{series['title']} — Episode {number}",
                            topic=series["title"], series_id=series_id, episode_number=number)
                    threading.Thread(target=execute_generated_episode,
                        args=(new["id"], episode.get("topic", series["title"]), series_id, episode["episode_id"]),
                        daemon=True).start()
                else:
                    update_job(new["id"], status="blocked", stage="series context unavailable",
                               error="Could not identify the series from the original instruction.")
            result = {"ok": True, "message": "Created a separate retry job; previous logs remain intact. Retry only starts if its required configuration and series context exist.", "job": job_get(new["id"])}
        else:
            result = {"ok": False, "message": f"{action.title()} is not supported for this job type yet; no state was changed.", "job": job}
    else:
        result = {"ok": False, "message": "Command understood as a request, but no safe executor is registered. Supported now: status, why did render fail, run pilot, create a new series about TOPIC (requires GEMINI_API_KEY for generation), cancel JOB_ID, retry JOB_ID."}
    conversation("assistant", result["message"], (result.get("job") or {}).get("id"))
    return result


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
<p>Connected to the local backend. Commands are executed only where a real handler exists; unsupported work is reported honestly.</p>
<div class="panel"><div id="messages" aria-live="polite"></div><form id="chat"><input id="prompt" autocomplete="off" placeholder="Run pilot, check status, create a series..." required><button>Send</button></form></div>
<div class="panel"><strong>Persistent jobs</strong><button id="refresh" style="float:right">Refresh</button><pre id="jobs">Loading…</pre></div>
<p>Local-only service · Do not expose this page/API publicly without authentication.</p>
<script>
const messages=document.querySelector('#messages'), jobs=document.querySelector('#jobs');
function line(role,text){const d=document.createElement('div');d.className='msg '+role;d.textContent=role+': '+text;messages.appendChild(d);messages.scrollTop=messages.scrollHeight}
async function refresh(){try{const r=await fetch('/api/jobs');const d=await r.json();jobs.textContent=JSON.stringify(d.jobs.map(j=>({id:j.id,kind:j.kind,status:j.status,stage:j.stage,error:j.error})),null,2)}catch(e){jobs.textContent='Backend unavailable: '+e}}
document.querySelector('#refresh').onclick=refresh;
document.querySelector('#chat').onsubmit=async e=>{e.preventDefault();const input=document.querySelector('#prompt'),message=input.value.trim();if(!message)return;line('user',message);input.value='';try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message})});const d=await r.json();line('assistant',d.message+'\\n'+(d.job?'Job '+d.job.id+' · '+d.job.status:'')+(d.jobs?'\\n'+d.jobs.map(j=>j.id+' · '+j.status+' · '+j.stage).join('\\n'):''));await refresh()}catch(err){line('assistant','Request failed: '+err)}};
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
