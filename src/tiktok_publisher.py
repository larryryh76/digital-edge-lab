"""Official TikTok Content Posting API integration with private-first approval.

Requires a creator-authorized access token with video.publish and an approved app.
All HTTP requests are bounded. An uncertain initiation/upload is persisted and is never
blindly restarted, because the API does not provide a caller-supplied idempotency key.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import requests

API = "https://open.tiktokapis.com/v2"
CHUNK_SIZE = 10 * 1024 * 1024


class TikTokError(RuntimeError):
    pass


def fingerprint(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def prepare_for_manual_upload(video_path, title, output_dir="output/tiktok-prepared"):
    """Prepare a truthful manual-upload package when API access is unavailable."""
    source = Path(video_path)
    if not source.is_file() or source.stat().st_size == 0:
        raise TikTokError("validated video file is missing or empty")
    if source.suffix.lower() != ".mp4":
        raise TikTokError("TikTok package requires MP4 output")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    video = destination / source.name
    shutil.copy2(source, video)
    metadata = {"status": "ready_for_manual_upload", "title": str(title)[:2200],
                "video_file": video.name, "bytes": video.stat().st_size,
                "sha256": fingerprint(video), "platform_publish_verified": False}
    _atomic(destination / "tiktok-package.json", metadata)
    return metadata


def _request_json(session, method, url, *, headers, payload=None, timeout=(8, 45)):
    try:
        response = session.request(method, url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise TikTokError("TikTok request outcome may be uncertain; inspect saved state before retrying.") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise TikTokError("TikTok returned a non-JSON response (HTTP %s)." % response.status_code) from exc
    if response.status_code >= 400 or data.get("error", {}).get("code", "ok") != "ok":
        error = data.get("error", {})
        raise TikTokError("TikTok API rejected the request: %s %s (log_id=%s)" %
                          (error.get("code", response.status_code),
                           str(error.get("message", ""))[:300], error.get("log_id", "unavailable")))
    return data


def publish_video(video_path, title, *, approval=False, privacy_level="SELF_ONLY",
                  access_token=None, state_file="output/publishing/tiktok-state.json",
                  session=None):
    """Direct-post a validated MP4; returns platform status, never infers publication."""
    path = Path(video_path)
    if not path.is_file() or path.stat().st_size == 0:
        raise TikTokError("video file missing or empty")
    if path.suffix.lower() != ".mp4":
        raise TikTokError("only validated MP4 files can be posted")
    title = str(title).strip()
    if not title or len(title) > 2200:
        raise ValueError("TikTok caption/title must contain 1-2200 characters")
    if not approval:
        raise TikTokError("explicit approval is required before sending video to TikTok")
    token = access_token or os.getenv("TIKTOK_ACCESS_TOKEN", "")
    if not token:
        raise TikTokError("TIKTOK_ACCESS_TOKEN is missing; authorize the creator through the official TikTok OAuth flow with video.publish scope")
    session = session or requests.Session()
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json; charset=UTF-8"}
    state_path = Path(state_file)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    key = fingerprint(path)
    previous = state.get(key)
    if previous:
        if previous.get("publish_id"):
            return {**previous, "duplicate_prevented": True}
        raise TikTokError("A prior TikTok initiation may have succeeded. Reconcile creator inbox/status before retrying; duplicate post blocked.")
    # Save intent before any API call; failed/ambiguous calls require reconciliation.
    state[key] = {"status": "initializing", "fingerprint": key, "title": title}
    _atomic(state_path, state)
    try:
        creator = _request_json(session, "POST", API + "/post/publish/creator_info/query/",
                                headers=headers).get("data", {})
        options = creator.get("privacy_level_options", [])
        if privacy_level not in options:
            raise TikTokError("Requested privacy level is not allowed for this creator; available options: " + ", ".join(options))
        size = path.stat().st_size
        chunks = math.ceil(size / CHUNK_SIZE)
        init = _request_json(session, "POST", API + "/post/publish/video/init/",
            headers=headers, payload={"post_info": {
                "title": title, "privacy_level": privacy_level,
                "disable_duet": False, "disable_comment": False, "disable_stitch": False,
                "is_aigc": True
            }, "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                               "chunk_size": CHUNK_SIZE, "total_chunk_count": chunks}})
        data = init.get("data", {})
        publish_id, upload_url = data.get("publish_id"), data.get("upload_url")
        if not publish_id or not upload_url:
            raise TikTokError("TikTok init response omitted publish_id or upload_url")
        state[key].update({"status": "uploading", "publish_id": publish_id})
        _atomic(state_path, state)
        with path.open("rb") as stream:
            start = 0
            while start < size:
                block = stream.read(CHUNK_SIZE)
                end = start + len(block) - 1
                try:
                    response = session.put(upload_url, data=block, headers={
                        "Content-Type": "video/mp4", "Content-Length": str(len(block)),
                        "Content-Range": f"bytes {start}-{end}/{size}"
                    }, timeout=(10, 120))
                except requests.RequestException as exc:
                    state[key]["status"] = "uncertain"
                    _atomic(state_path, state)
                    raise TikTokError("TikTok upload interrupted; use saved publish_id to reconcile status, do not restart upload.") from exc
                if response.status_code not in (200, 201, 206):
                    state[key]["status"] = "uncertain"
                    _atomic(state_path, state)
                    raise TikTokError("TikTok chunk upload failed with HTTP %s; saved publish_id for reconciliation." % response.status_code)
                start = end + 1
        state[key]["status"] = "processing"
        _atomic(state_path, state)
        status = _request_json(session, "POST", API + "/post/publish/status/fetch/",
                               headers=headers, payload={"publish_id": publish_id}).get("data", {})
        platform_status = status.get("status", "PROCESSING")
        result = {"status": platform_status, "publish_id": publish_id,
                  "fingerprint": key, "title": title,
                  "privacy_level": privacy_level, "platform_response": status}
        state[key] = result
        _atomic(state_path, state)
        return result
    except TikTokError as exc:
        state[key]["status"] = state[key].get("status", "uncertain")
        state[key]["error"] = str(exc)[:500]
        _atomic(state_path, state)
        raise
