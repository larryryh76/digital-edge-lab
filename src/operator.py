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
            series = {"series_id": slug, "title": topic, "status": "planned", "episode_ids": [],
                      "created_at": now(), "operator_note": "Series metadata recorded; episode research/story generation adapter is not yet connected."}
            data["series"][slug] = series
            memory.save(data)
            job = job_create("series_request", text, status="blocked", stage="awaiting research/story adapter")
            update_job(job["id"], result_json=json.dumps({"series_id": slug, "blocked_reason": "The current pipeline accepts a checked-in episode plan; autonomous research/story-plan generation is not yet wired into the operator."}))
            result = {"ok": True, "message": "Series metadata saved to persistent memory. Episode production is honestly marked blocked because the research/story-plan adapter is not yet connected.", "series": series, "job": job_get(job["id"])}
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
        elif action == "retry" and job["status"] in ("failed", "cancelled"):
            new = job_create(job["kind"], job["instruction"], status="retrying", stage="retry queued")
            if new["kind"] == "offline_pilot":
                threading.Thread(target=execute_pilot, args=(new["id"], new["instruction"]), daemon=True).start()
            result = {"ok": True, "message": "Created a separate retry job; previous logs remain intact.", "job": new}
        else:
            result = {"ok": False, "message": f"{action.title()} is not supported for this job type yet; no state was changed.", "job": job}
    else:
        result = {"ok": False, "message": "Command understood as a request, but no safe executor is registered. Supported now: status, why did render fail, run pilot, create a new series about TOPIC, cancel JOB_ID, retry JOB_ID."}
    conversation("assistant", result["message"], (result.get("job") or {}).get("id"))
    return result


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
