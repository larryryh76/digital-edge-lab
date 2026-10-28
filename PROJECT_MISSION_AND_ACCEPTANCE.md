# Digital Edge Lab — Mission and Acceptance Criteria

## Mission

Build a useful, faceless AI channel operator that researches, plans, creates, quality-checks, packages, publishes through authorized official integrations, and learns from original short-form videos for YouTube Shorts and TikTok. This must be a production system, not merely a prompt generator, slideshow maker, or set of workflows.

## Hard requirements

- ₦0 starting budget: prioritize free tiers and local/open-source tools. Never incur paid usage or spending without explicit owner approval.
- Android-first owner experience. The owner should only need occasional monitoring, account authorization, editorial review where required, and community oversight.
- Target cadence: 6–7 quality uploads per week on each platform. Quality and compliance take priority over quotas.
- Faceless, original, engaging storytelling with persistent channel/narrator memory, series continuity, and awareness of previous episodes.
- Visual quality: cinematic, genuinely animated 3D-style scenes with camera motion, depth, interactions, changing compositions, and meaningful visual progression. Use generated clips when available; otherwise use a tested free hybrid of assets, Blender/animation, narration, captions, and FFmpeg.
- Never present repeated stills as 3D animation. Reject recycled scenes, generic filler narration, silent or unsynchronized videos, fabricated facts, copied scripts, copyright infringement, undisclosed promotions, fake analytics, and false claims of publishing or completion.
- Report capability honestly as implemented, CI-tested, live-provider-tested, account-tested, blocked, or not implemented. A successful workflow exit alone is not proof of a usable video.

## Required production loop

1. Research topics; select based on relevance, novelty, evidence quality, visual potential, and past-episode memory.
2. Collect credible sources and supporting notes. Check material claims against independent sources and flag uncertainty for human review.
3. Write an original short script with a strong immediate hook, coherent development, natural narration, and satisfying payoff.
4. Plan scenes shot-by-shot with actions, camera directions, timing, transitions, and on-screen text—not just static-image prompts.
5. Produce animated scenes using available free tools, generated assets/clips, or a tested Blender/FFmpeg route. Document fallbacks when a provider is unavailable.
6. Generate narration and captions, synchronize them to the edit, and ensure intelligible audio without unintended silent sections.
7. Render platform-appropriate vertical video and run media and editorial QA.
8. Reject failed outputs. Package the actual MP4, transcript/captions, source list, thumbnail/contact sheet, QA report, and diagnostics.
9. Schedule/publish only through supported, authorized official APIs. If platform approval or account credentials are missing, prepare a manual upload package and say so.
10. Read actual analytics only when authorized and data exists; use findings to improve hooks, pacing, topics, and retention.
11. Save episode memory only after QA passes. Persist job state, logs, artifacts, errors, and safe retry/cancellation outcomes.

## Video acceptance gate

A pilot is accepted only when the actual downloadable video—not merely a log or prompt—passes these checks:

- Valid MP4, H.264 video, AAC audio, portrait 720×1280 or better, target 24 fps, plausible non-zero duration, and no corruption/truncation.
- Audible, intelligible narration and synchronized captions; no unintended silent sections or cut-off ending.
- Multiple distinct, intentionally composed animated scenes with visible motion and progression. No slideshow of repeated stills masquerading as animation.
- Clear hook, development, and payoff; visual review and source/claim review documented.
- Deliver the MP4, media-probe output, QA report, scene/contact sheet, transcript/captions, source URLs, commit SHA, workflow URL, run duration, and known defects.
- A failed gate fails the job and preserves diagnostics. Automated checks do not replace claim-level fact verification or required human review.

## Workflow reliability

- PR and push checks must be fast: syntax, unit tests, and lightweight checks only.
- Expensive Blender bootstrap, renderer smoke tests, and complete pilot rendering belong to manual certification and the single designated scheduled production workflow.
- Superseded runs for the same workflow/ref must be cancelled. Do not use per-SHA concurrency groups that allow every stale run to continue.
- Apply hard job/step timeouts, show progress, and report actionable failure causes.
- Do not run duplicate daily production from multiple scheduled workflows. Prompt-only runs must not compete with the production schedule.
- Use least-privilege CI permissions; never expose keys in URLs, logs, artifacts, committed files, or chat.
- Make retries safe against duplicate episodes, uploads, memory writes, and analytics.
- Separate offline tests from live Gemini/provider checks and real-account publishing tests.
- Job states must be truthful: queued, running, succeeded, failed, or cancelled, with stage, timestamps, errors, and artifact links.

## Publishing and monetization

- YouTube upload, scheduling, and analytics require OAuth consent, quota, and real account tests. A private upload is not proof of public publishing.
- TikTok Direct Post requires official API access, app approval/scopes, and creator authorization. Until verified, the supported fallback is a manual upload package.
- Do not claim unattended publishing until an actual post is confirmed on the intended account and its real platform ID is recorded.
- Never invent revenue, monetization eligibility, audience metrics, or earnings. Follow platform rules and disclose promotions when required.

## Delivery milestones

1. **Stop workflow waste:** cancel superseded runs; keep PR checks fast; use one scheduled production entry point and explicit full certification.
2. **Certify the renderer:** pass unit tests and smoke tests; render the current pilot; inspect the MP4/contact sheet; verify codec, dimensions, duration, narration, captions, motion, and scene variety; fix root causes and rerun reproducibly.
3. **Verify the AI operator:** test live Gemini only with configured secrets/quota; verify grounded research, original scripts, persistent memory, real job state, cancellation/retry, artifact inspection, and useful error recovery.
4. **Verify integrations:** test authorized YouTube private upload/analytics and TikTok only if approved. Record real response IDs. Do not claim scheduling/publication before live verification.
5. **Production readiness:** demonstrate quality across multiple distinct episodes, then add one controlled schedule, retention, failure notification, quota/rate-limit handling, and a simple owner-facing status view.
6. **Final capability matrix:** classify every feature as verified working, partial, needs owner authorization, blocked, or not implemented.

## Definition of done

A limited pilot is ready only when a current commit reproducibly produces a visually reviewed, narrated, captioned, genuinely animated video and all defects/blockers are documented. Autonomous channel operation requires repeated quality runs, real platform integration tests, safe scheduling/retry behavior, and verified analytics. Until then, describe the project as a working foundation or limited pilot—not a fully autonomous production channel.
