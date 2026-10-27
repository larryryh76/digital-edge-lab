"""Crash-safe, versioned channel/story memory with legacy migration."""
from __future__ import annotations
import json
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.RLock()
SCHEMA_VERSION = 2


def _now():
    return datetime.now(timezone.utc).isoformat()


def _empty():
    return {
        "schema_version": SCHEMA_VERSION,
        "channel": {"name": "Digital Edge Lab", "persona": "Edge",
                    "audience": "curious technology learners",
                    "niche": ["AI", "technology", "digital tools", "evidence-based case studies"],
                    "tone": "curious, sharp, calm, confident, conversational English",
                    "editorial_rules": []},
        "series": {}, "episodes": {}, "characters": {}, "timelines": {},
        "research": [], "production_history": [], "publishing": {},
        "analytics": [], "recent_topics": [], "running_context": [],
        "migrated_at": None, "updated_at": _now()
    }


def _atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


class ChannelMemory:
    """JSON memory with atomic replacement, backup, stable IDs and legacy import."""
    def __init__(self, path):
        self.path = Path(path)
        self.backup = self.path.with_suffix(self.path.suffix + ".bak")
        self._lock = _LOCK

    def load(self):
        with self._lock:
            if not self.path.exists():
                return _empty()
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                if self.backup.exists():
                    raw = json.loads(self.backup.read_text(encoding="utf-8"))
                else:
                    raise
            if raw.get("schema_version") == SCHEMA_VERSION and "episodes" in raw:
                return raw
            # Preserve the complete legacy document; migrate topics/context without loss.
            data = _empty()
            data["channel"].update({
                k: raw[k] for k in ("channel_name", "persona", "role", "voice", "point_of_view")
                if k in raw
            })
            data["channel"]["editorial_rules"] = list(raw.get("principles", []))
            data["recent_topics"] = list(raw.get("recent_topics", []))
            data["running_context"] = list(raw.get("running_context", []))
            for i, topic in enumerate(data["recent_topics"]):
                stable = str(topic.get("episode_id") or
                             "legacy-" + str(topic.get("created_at_utc", i)).replace(":", "-"))
                data["episodes"].setdefault(stable, {
                    "episode_id": stable, "title": topic.get("title", "Legacy episode"),
                    "topic": topic.get("topic", ""), "status": "legacy_completed",
                    "summary": topic.get("summary", ""), "created_at": topic.get("created_at_utc"),
                    "series_id": topic.get("series_id"), "sources": topic.get("sources", []),
                    "ending": topic.get("ending", ""), "unresolved": topic.get("unresolved", [])
                })
            data["migrated_at"] = _now()
            data["legacy_fields_preserved"] = raw
            return data

    def save(self, data):
        with self._lock:
            data = dict(data)
            data["schema_version"] = SCHEMA_VERSION
            data["updated_at"] = _now()
            if self.path.exists():
                try:
                    shutil.copy2(self.path, self.backup)
                except OSError:
                    pass
            _atomic_json(self.path, data)

    def create_episode(self, episode_id, *, title, topic, series_id=None, episode_number=None):
        with self._lock:
            data = self.load()
            if episode_id in data["episodes"]:
                raise ValueError("episode already exists: " + episode_id)
            if series_id and series_id not in data["series"]:
                data["series"][series_id] = {"series_id": series_id, "title": series_id,
                                             "status": "active", "episode_ids": []}
            record = {"episode_id": episode_id, "title": title, "topic": topic,
                      "series_id": series_id, "episode_number": episode_number,
                      "status": "queued", "summary": "", "characters": [],
                      "timeline": [], "hook": "", "ending": "", "unresolved": [],
                      "sources": [], "created_at": _now(), "updated_at": _now()}
            data["episodes"][episode_id] = record
            if series_id:
                series = data["series"][series_id]
                if episode_id not in series["episode_ids"]:
                    series["episode_ids"].append(episode_id)
            self.save(data)
            return record

    def complete_episode(self, episode_id, report):
        """Only call after all delivery QA gates passed."""
        with self._lock:
            data = self.load()
            episode = data["episodes"].get(episode_id)
            if not episode:
                raise KeyError("unknown episode: " + episode_id)
            if report.get("status") not in ("verified_delivery", "verified_degraded_delivery"):
                raise ValueError("cannot commit story memory before delivery QA passes")
            episode.update({
                "status": "completed" if report["status"] == "verified_delivery" else "completed_degraded",
                "summary": report.get("summary", episode.get("summary", "")),
                "hook": report.get("hook", episode.get("hook", "")),
                "ending": report.get("ending", episode.get("ending", "")),
                "unresolved": report.get("unresolved", episode.get("unresolved", [])),
                "characters": report.get("characters", episode.get("characters", [])),
                "timeline": report.get("timeline", episode.get("timeline", [])),
                "sources": report.get("sources", episode.get("sources", [])),
                "delivery_report": report, "updated_at": _now()
            })
            data["production_history"].append({"episode_id": episode_id, "status": episode["status"],
                                               "at": _now(), "video_file": report.get("video_file")})
            data["recent_topics"] = (data.get("recent_topics", []) + [{
                "episode_id": episode_id, "title": episode["title"], "topic": episode["topic"],
                "created_at_utc": _now()
            }])[-100:]
            self.save(data)
            return episode

    def context_for(self, series_id=None, episode_id=None):
        data = self.load()
        episodes = sorted(data["episodes"].values(), key=lambda e: e.get("updated_at", ""))
        if series_id:
            episodes = [e for e in episodes if e.get("series_id") == series_id]
        if episode_id:
            current = data["episodes"].get(episode_id)
            if current and current not in episodes:
                episodes.append(current)
        return {"channel": data["channel"], "series": data["series"].get(series_id),
                "episodes": episodes[-12:], "characters": data["characters"],
                "timelines": data["timelines"], "recent_topics": data["recent_topics"][-30:]}
