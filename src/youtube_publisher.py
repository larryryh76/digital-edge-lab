"""Official YouTube Data API publishing boundary. Private-first; never auto-publish by default.

Optional dependencies: google-api-python-client, google-auth-oauthlib, google-auth-httplib2.
OAuth client JSON and token cache are local files and must never be committed.
"""
from __future__ import annotations
import json
import os
import hashlib
from pathlib import Path
from datetime import datetime, timezone


class PublishingError(RuntimeError):
    pass


def validate_metadata(metadata):
    title = str(metadata.get("title", "")).strip()
    description = str(metadata.get("description", "")).strip()
    tags = metadata.get("tags", [])
    if not title:
        raise ValueError("YouTube title is required")
    if len(title) > 100:
        raise ValueError("YouTube title exceeds 100 characters")
    if len(description) > 5000:
        raise ValueError("YouTube description exceeds 5000 characters")
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise ValueError("tags must be a list of strings")
    return {"title": title, "description": description, "tags": tags[:500],
            "categoryId": str(metadata.get("category_id", "28")),
            "privacyStatus": str(metadata.get("privacy_status", "private")),
            "madeForKids": bool(metadata.get("made_for_kids", False))}


def content_fingerprint(video_path, metadata):
    digest = hashlib.sha256()
    with open(video_path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_youtube_service(client_secret_file=None, token_file=None):
    """Run installed-app OAuth once; refresh credentials on subsequent invocations."""
    client_secret_file = Path(client_secret_file or os.getenv("YOUTUBE_OAUTH_CLIENT_FILE", "secrets/youtube-client.json"))
    token_file = Path(token_file or os.getenv("YOUTUBE_TOKEN_FILE", "secrets/youtube-token.json"))
    if not client_secret_file.is_file():
        raise PublishingError("YouTube OAuth client file missing; set YOUTUBE_OAUTH_CLIENT_FILE to your downloaded OAuth desktop-client JSON.")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise PublishingError("Install optional publishing dependencies: google-api-python-client google-auth-oauthlib google-auth-httplib2") from exc
    scopes = ["https://www.googleapis.com/auth/youtube.upload",
              "https://www.googleapis.com/auth/youtube.readonly"]
    credentials = None
    if token_file.is_file():
        credentials = Credentials.from_authorized_user_file(str(token_file), scopes)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), scopes)
            credentials = flow.run_local_server(port=0, open_browser=False)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(credentials.to_json(), encoding="utf-8")
        try:
            token_file.chmod(0o600)
        except OSError:
            pass
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def upload_video(video_path, metadata, *, approval=False, service=None, state_file="output/publishing/youtube-state.json"):
    """Upload a validated MP4 resumably. Public/scheduled publication requires explicit approval."""
    path = Path(video_path)
    if not path.is_file() or path.stat().st_size == 0:
        raise PublishingError("video file missing or empty")
    if path.suffix.lower() != ".mp4":
        raise PublishingError("only validated MP4 files can be uploaded")
    meta = validate_metadata(metadata)
    if (meta["privacyStatus"] != "private" or meta["publishAt"]) and not approval:
        raise PublishingError("explicit approval is required for public, unlisted, or scheduled publication")
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise PublishingError("Install optional publishing dependencies: google-api-python-client google-auth-oauthlib google-auth-httplib2") from exc
    if service is None:
        service = build_youtube_service()
    state_path = Path(state_file)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fingerprint = content_fingerprint(path, meta)
    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    previous = state.get(fingerprint)
    if previous and previous.get("video_id"):
        return {**previous, "duplicate_prevented": True}
    if previous and previous.get("status") in ("uploading", "uncertain"):
        raise PublishingError("An earlier upload may have reached YouTube. Reconcile the channel before retrying; duplicate upload blocked.")
    state[fingerprint] = {"status": "uploading", "fingerprint": fingerprint, "metadata": meta}
    temp = state_path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(temp, state_path)
    try:
        snippet = {"title": meta["title"], "description": meta["description"],
                   "tags": meta["tags"], "categoryId": meta["categoryId"]}
        body_status = {"privacyStatus": meta["privacyStatus"],
                       "selfDeclaredMadeForKids": meta["madeForKids"]}
        if meta["publishAt"]:
            body_status["publishAt"] = meta["publishAt"]
        body = {"snippet": snippet, "status": body_status}
        request = service.videos().insert(part="snippet,status", body=body,
            media_body=MediaFileUpload(str(path), mimetype="video/mp4", resumable=True))
        response = None
        while response is None:
            status, response = request.next_chunk()
            # The client library retains resumable state inside the request for retry.
        video_id = response.get("id")
        if not video_id:
            raise PublishingError("YouTube returned no video ID")
        result = {"video_id": video_id, "url": "https://www.youtube.com/watch?v=" + video_id,
                  "status": "scheduled" if meta["publishAt"] else meta["privacyStatus"],
                  "fingerprint": fingerprint, "metadata": meta}
        # Save the platform ID immediately. Optional post-upload failures must not
        # cause the video itself to be uploaded again on retry.
        state[fingerprint] = result
        temp = state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(temp, state_path)
        if meta["playlistId"]:
            service.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": meta["playlistId"], "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
        if meta["thumbnailPath"]:
            thumbnail = Path(meta["thumbnailPath"])
            if not thumbnail.is_file():
                raise PublishingError("video uploaded as " + video_id + " but thumbnail file is missing")
            service.thumbnails().set(videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail), mimetype="image/jpeg")).execute()
        return result
    except PublishingError:
        state[fingerprint]["status"] = "uncertain"
        temp = state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(temp, state_path)
        raise
    except Exception as exc:
        state[fingerprint]["status"] = "uncertain"
        state[fingerprint]["error"] = str(exc)[:500]
        temp = state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(temp, state_path)
        raise PublishingError("YouTube upload outcome is uncertain; inspect the channel before retrying. Duplicate upload blocked.") from exc


def fetch_video_analytics(video_id, start_date, end_date, *, analytics_service=None):
    """Query available metrics for an explicit date range and authorized service."""
    if analytics_service is None:
        raise PublishingError("YouTube Analytics service must be authorized with the yt-analytics.readonly scope")
    try:
        start = datetime.fromisoformat(str(start_date)).date()
        end = datetime.fromisoformat(str(end_date)).date()
    except ValueError as exc:
        raise ValueError("start_date and end_date must be ISO dates (YYYY-MM-DD)") from exc
    if end < start or end > datetime.now(timezone.utc).date():
        raise ValueError("analytics date range must be ordered and cannot end in the future")
    return analytics_service.reports().query(
        ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
        metrics="views,likes,comments,estimatedMinutesWatched",
        filters="video==" + video_id).execute()
