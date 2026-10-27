# Digital Edge Lab

Digital Edge Lab is a zero-budget-first production workflow for original faceless educational content about AI, technology, digital tools, and evidence-based online-business workflows.

## Launch status

**Development / private-pilot stage.** The workflow generates a reviewable video artifact; it does not publish publicly. We will only enable platform publishing after account ownership, permissions, upload tests, and quality checks are verified.

## Verified capability status

| Capability | Status | Evidence / limitation |
|---|---|---|
| Gemini script generation and TTS | Implemented; live availability varies | Uses API-key model discovery and bounded requests. The workflow run report records the selected model when generation succeeds. |
| Procedural 3D rendering | Implemented; visual quality still needs human review | Blender MP4 smoke test and final media checks run in Actions; procedural scenes may still look repetitive. |
| MP4 encoding and stream/audio QA | Automated checks implemented | H.264 portrait video, frame rate, audio stream, duration alignment and loudness are checked. |
| Contact sheet and review bundle | Implemented in current pipeline | Successful delivery includes representative frames, narration WAV/text, metadata and run report. |
| Source URL reachability | Automated partial check | HTTP reachability is not evidence that a source supports a claim; human fact-checking remains required. |
| Transactional narrator memory | Implemented in pipeline ordering | Candidate memory is written only after render/media QA; workflow commits it only after successful job completion. |
| Failure diagnostics | Implemented; verify on each failed run | Failure artifact upload is guarded with `always()` and includes available output/log files. |
| YouTube OAuth/private upload | Integrated tool/module; real-account test pending | Agent can request a private upload through the official API module. OAuth client, owner consent, optional dependencies and quota are required. Public posting is not exposed as an agent tool. |
| TikTok Direct Post | API module + agent manual-package tool; real-account test pending | Direct Post still requires approved app access and creator authorization. The manual package is not a published post. |
| Automatic weekly production at publish quality | Not yet production-ready | A successful render does not replace manual visual, factual, narration and caption review. |

## AI operator

A local conversational operator is implemented in `src/channel_operator.py` and uses Gemini's native function-calling API through `src/agent_runtime.py`. It validates tool arguments, executes registered production/memory/job/publishing tools, feeds real tool results back to the model, and bounds tool rounds. If `GEMINI_API_KEY` is missing, it explicitly reports that AI reasoning is unavailable rather than pretending to be a model-backed chatbot. Setup: see [`OPERATOR_SETUP.md`](OPERATOR_SETUP.md).

The agent implementation has mocked/offline protocol tests; live model access depends on a valid key, quota and provider availability. This is not yet a hosted autonomous service, and it does not enable public posting.

## Required account setup

### 1. Google AI Studio (script and narration)
1. Open https://aistudio.google.com/app/apikey and create or review an API key.
2. In this repository, open **Settings → Secrets and variables → Actions → New repository secret**.
3. Name the secret exactly `GEMINI_API_KEY`. Never commit or share the key.
4. The workflow tries compatible fallback models if a configured Gemini model is overloaded or unavailable. API quotas and model availability are not guaranteed.

### 2. YouTube (publishing, after pilot approval)
1. Create/confirm the channel under the intended Google account and enable 2-step verification.
2. In Google Cloud Console, create a project, enable **YouTube Data API v3**, configure the OAuth consent screen, and create an OAuth client.
3. Store OAuth credentials only in GitHub Actions secrets. Do not paste credentials into this repository.
4. Test uploads as **private** first. Review title, description, audience setting, synthetic-media disclosure where applicable, and copyright before any public release.
5. YouTube API projects subject to an audit/restriction may have upload limitations until reviewed.

### 3. TikTok (publishing, after pilot approval)
1. Confirm the TikTok account and account type.
2. Register an app in TikTok for Developers and apply for Content Posting API access and the required scopes.
3. Complete the platform's authorization flow and any required audit. Direct posting availability is controlled by TikTok; credentials alone do not guarantee unrestricted posting.
4. Test in the platform's allowed test/private mode before scheduling public posts.

**Important:** YouTube and TikTok publishing are not enabled in this repository yet. Account login, OAuth consent, app approval, and any account verification must be completed by the account owner. Do not send passwords or API keys in chat.

## Run the pilot

1. Open the **Actions** tab.
2. Select **Digital Edge Lab — Generate pilot**.
3. Choose **Run workflow**.
4. When it finishes, download the `digital-edge-lab-pilot` artifact.
5. Review the actual MP4, narration, sources, and run report before approving it.

## Production pipeline

- Generate a script and scene plan with Gemini.
- Generate synthetic narration with Gemini TTS.
- Render original procedural 3D scenes using Blender.
- Add timed captions, camera movement, transitions, and narration with FFmpeg.
- Check that the final MP4 contains synchronized audio and video and passes audio-level checks.
- Package the deliverables as a downloadable artifact for human review.

The 3D renderer is an early-stage procedural renderer, not a replacement for a full professional animation studio. Visual quality is evaluated from generated outputs, not assumed from successful code execution.

## 24-hour launch priorities

1. Get a complete pilot build through script, narration, 3D render, and MP4 QA.
2. Inspect the actual video and correct any visual/audio defects.
3. Confirm source links and editorial accuracy.
4. Confirm channel ownership and required account security.
5. Complete YouTube OAuth setup and private-upload testing if credentials and account-owner authorization are available.
6. Confirm TikTok developer access; do not promise automatic posting until access is granted.
7. Only then enable scheduled publishing. Keep public release behind an explicit approval step until quality is consistent.

## Editorial and platform safety

- Never invent facts, statistics, source links, or claims of personally testing tools.
- Use original visuals and licensed/authorized media only.
- Add synthetic/altered-media disclosures when required.
- Avoid repetitive mass-produced videos; each episode must have a distinct idea, real explanatory value, and meaningful editorial review.
- Do not enable paid services or billing without explicit approval.
