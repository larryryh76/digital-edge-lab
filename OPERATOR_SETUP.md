# Digital Edge Lab — real AI operator setup

## Start the operator

Requires Python 3.10+ and the repository's normal dependencies. From the repository root:

```bash
python -m pip install -r requirements.txt
export GEMINI_API_KEY="YOUR_KEY_FROM_GOOGLE_AI_STUDIO"
# Optional: choose another Gemini model available to this key.
export DEL_AGENT_MODEL="gemini-3.8-flash"
python src/channel_operator.py serve
```

On Android/Termux, use the same commands in the repository directory; keep the API key in your private shell environment and never commit it. Open **http://127.0.0.1:8765** in the same device's browser. The service binds to loopback only and must not be exposed publicly without authentication/TLS.

If `GEMINI_API_KEY` is absent or rejected, the chat explicitly reports that model reasoning is unavailable. It does not silently substitute keyword routing. The agent uses Gemini's native function-calling API, validates tool names/arguments, executes local tools, sends actual tool results back to the model, and stops after a bounded number of tool rounds.

## Useful instructions to try

- “Show my current jobs and explain which ones are still running.”
- “Create an episode about how Roman roads changed the empire.”
- “Continue the last unfinished episode and preserve its continuity.”
- “Research ancient Rome using grounded sources, then produce a Short about the strongest finding.”
- “Diagnose the recent production failures from the stored logs.”
- “Cancel the current render” or “retry job JOB_ID” (the model selects the real persisted job ID from job results).
- “Run the offline pilot, then inspect the actual report and video.”
- “Prepare the latest verified video for manual TikTok upload.”
- “Upload the latest verified video to YouTube as private.”

The agent can only execute registered tools. A request to generate an episode starts a background job; it is not a completion claim. Job records and conversation history persist in `output/operator.sqlite3`. Structured channel/story memory is stored at `memory/channel-memory.json` (configurable with `DEL_CHANNEL_MEMORY`). Output artifacts are under `output/`.

## Current limitations

- The Gemini agent code and tool-calling protocol have offline tests, but a live API call still depends on a valid `GEMINI_API_KEY`, model availability and quota.
- The production renderer is the repository's Blender/FFmpeg pipeline. A complete current pilot must pass report/media QA and be visually inspected; do not treat a successful process exit alone as sufficient.
- Cancellation terminates the active subprocess. Full pause/resume of an active Blender render is not implemented.
- Source URL reachability is not claim-level fact verification; independent research/fact-checking remains partial.
- YouTube private upload is callable through the agent, but requires local OAuth client JSON, authorized account consent and optional dependencies. Public publication is deliberately not exposed as an agent tool.
- TikTok's official Direct Post API requires approved app access and creator authorization. The operator offers a manual-upload package when direct publishing is not available.
- Authorized YouTube Analytics integration and hosted durable scheduling are not complete.

## YouTube OAuth and private uploads

```bash
python -m pip install -r requirements-publishing.txt
```

Create a Google Cloud project, enable YouTube Data API v3, configure the OAuth consent screen, create an OAuth Desktop client, and store the downloaded JSON as `secrets/youtube-client.json` (or set `YOUTUBE_OAUTH_CLIENT_FILE`). Never commit OAuth credentials or token files. When the operator is asked to upload a verified artifact, the tool only uses **private** visibility. Confirm the returned video ID/URL from the actual API response. Public posting/scheduling must not be assumed enabled.

## TikTok manual package

The agent can call the official publisher's manual-package function against the latest QA-passed MP4. It returns `ready_for_manual_upload`; that is not a published post. Direct Post requires an approved TikTok app, `video.publish` scope and creator authorization. Do not paste access tokens into chat.

## API endpoints

- `GET /health` — service health
- `GET /api/jobs` — persistent jobs
- `GET /api/conversation` — persisted chat history
- `POST /api/chat` JSON `{"message":"..." }` — model-driven conversation/tool loop
- `GET /api/jobs/JOB_ID` — one persisted job
