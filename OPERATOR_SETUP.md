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
- `POST /api/chat` with `{"message":"create a new series about the fall of ancient Rome"}` — persist series metadata; the response explicitly marks episode generation blocked until a research/story-plan adapter is connected

The operator does not claim unsupported actions have succeeded. Publishing, autonomous research, episode-plan generation, pause/resume of active rendering, and TikTok upload are not presented as implemented. SQLite job history persists under `output/operator.sqlite3` by default.

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

No TikTok upload is claimed. Official Content Posting API access, creator authorization, and applicable app review/permissions must be obtained before publishing can be enabled.
