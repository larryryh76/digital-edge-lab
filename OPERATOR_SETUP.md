# Digital Edge Lab operator and publishing setup

## Local operator

Install the normal project requirements, then run:

```bash
python src/operator.py serve
```

The service binds to `127.0.0.1:8765` by default. It is intended for local use only; do not expose it to the public internet without authentication and TLS.

- `GET /health` — service health
- `GET /api/jobs` — persisted job queue
- `GET /api/conversation` — persisted conversation history
- `POST /api/chat` with `{"message":"run pilot"}` — run the real checked-in offline pilot
- `POST /api/chat` with `{"message":"what are you working on?"}` — read real job state
- `POST /api/chat` with `{"message":"create a new series about the fall of ancient Rome"}` — save series memory and start the actual topic-directed Gemini-to-Blender pipeline when `GEMINI_API_KEY` is configured
- `POST /api/chat` with `{"message":"continue series fall-of-ancient-rome"}` — create a stable next episode ID and generate with that series' completed-episode context

The operator does not claim unsupported actions have succeeded. Gemini-driven topic/scene-plan generation and the existing source-validation stage are wired into the real pipeline; independent web-research fact-checking and full pause/resume of an active Blender process remain incomplete. Publishing is implemented as an explicit integration module but still requires account authorization and has not been verified against real platform credentials. SQLite job history persists under `output/operator.sqlite3` by default.

## Channel memory

`src/channel_memory.py` provides schema-versioned migration from `memory/channel-memory.json`, atomic JSON replacement, a backup, stable episode IDs, duplicate prevention, and a QA-gated episode completion method. Call `complete_episode` only after the pipeline's delivery QA has passed.

## YouTube API setup

Publishing dependencies are optional and isolated from the offline renderer:

```bash
python -m pip install -r requirements-publishing.txt
```

1. In Google Cloud Console, enable YouTube Data API v3 and configure an OAuth consent screen.
2. Create an OAuth **Desktop app** client and download its JSON file.
3. Store it locally as `secrets/youtube-client.json` (or set `YOUTUBE_OAUTH_CLIENT_FILE`). Never commit it.
4. Run the publisher from a local terminal once to complete OAuth. The token is stored as `secrets/youtube-token.json` (or `YOUTUBE_TOKEN_FILE`) and is chmod 600 where supported.
5. Validate the MP4 with the existing pipeline before calling `upload_video`. It defaults to private. Non-private publication requires explicit `approval=True`.

YouTube API quota applies; uploads commonly consume substantial quota. No API keys, OAuth client files, account permissions, or successful real uploads are bundled with this repository. Interrupted uploads must be reconciled against the channel before retrying. Approved scheduling is supported through the YouTube `publishAt` field (scheduled videos must remain private until publication). Optional playlist insertion and JPEG thumbnail upload are supported when `playlist_id` and `thumbnail_path` are provided in the metadata. The uploaded platform video ID is persisted before optional post-upload operations so a playlist/thumbnail error does not cause a duplicate video upload.

Analytics requires a separate OAuth scope and a correctly authorized YouTube Analytics API service; the included analytics boundary will not pretend this access exists.

## TikTok

`src/tiktok_publisher.py` implements the official Content Posting API Direct Post flow: creator privacy options are queried first, the approved post is initialized, MP4 bytes are uploaded in bounded chunks, and the returned publish ID is checked through the official status endpoint. It defaults to `SELF_ONLY`, requires explicit `approval=True`, marks AI-generated content, and persists uncertain outcomes to block blind duplicate retries.

One-time requirements: register a TikTok developer app, add Content Posting API, obtain approval for the `video.publish` scope, authorize the creator account, and set `TIKTOK_ACCESS_TOKEN` in the local environment. Unaudited apps are restricted to private viewing by TikTok. The implementation has not been verified against a real authorized creator account in this repository, so real publishing remains unverified until credentials and approval are available. When access is missing, `prepare_for_manual_upload` creates a package explicitly marked `ready_for_manual_upload`, not published.
