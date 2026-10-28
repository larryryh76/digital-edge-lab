# Digital Edge Lab — Product Mission and Acceptance Criteria

## Mission

Build a genuinely useful, faceless AI channel operator that can research, plan, produce, quality-check, package, publish where officially authorized, and learn from original short-form videos for YouTube Shorts and TikTok. This is a production system—not merely a prompt generator, slideshow maker, or collection of workflows.

## Non-negotiable constraints

- Starting budget: ₦0. Prefer free tiers and local/open-source tools; never incur paid usage or spending without explicit owner approval.
- Owner workflow: Android-first and usable from a phone. The owner should only need occasional monitoring, editorial review when required, account authorization, and routine community oversight.
- Target cadence: 6–7 quality videos per week on YouTube and 6–7 on TikTok. Quality and platform compliance take priority over hitting a quota.
- Format: faceless, original, engaging short-form storytelling. The narrator/persona should have persistent memory of channel identity, prior episodes, facts already covered, and series continuity.
- Creative bar: cinematic, genuinely animated 3D-style scenes with camera movement, spatial depth, object/character interaction, varied compositions, clear visual progression, and a meaningful ending. Gemini-generated clips may be used when available; otherwise use a tested hybrid of generated assets, Blender/animation, narration, captions, and FFmpeg.
- Reject: repetitive still images, basic slideshows presented as animation, recycled scenes, generic filler narration, silent videos, unsynchronized narration, misleading hooks, fabricated facts, copied scripts, copyright infringement, undisclosed promotions, fake analytics, fake publishing success, and fake workflow completion.
- Truthfulness: distinguish implemented, locally tested, CI-tested, live-account tested, and blocked capabilities. A successful workflow exit is not sufficient proof that a usable video or published post exists.

## Required end-to-end operating loop

1. Research current or evergreen topics appropriate to the channel and audience.
2. Select topics using relevance, novelty, evidence quality, visual potential, and prior-episode memory.
3. Gather source URLs and supporting notes. Verify material claims against credible independent sources; flag uncertainty and sensitive claims for human review.
4. Write an original short script with an immediate hook, coherent development, natural narration, and a satisfying payoff.
5. Plan scenes shot-by-shot with visual actions, camera directions, timing, transitions, and on-screen text—not a list of static images.
6. Produce scenes using available free tools, generated clips/assets, or a tested Blender/FFmpeg route. Provide a documented fallback when a provider is unavailable.
7. Generate narration and captions; synchronize them to the edit and mix audio at a usable level.
8. Render platform-appropriate vertical video and run media and editorial QA.
9. Reject failed outputs. Produce a review package containing the MP4, thumbnail/frame contact sheet, captions/transcript, sources, QA report, and diagnostics.
10. Prepare platform metadata and schedule/publish only through supported, authorized official APIs. If TikTok or YouTube access is not approved/configured, clearly prepare a manual package rather than claiming publication.
11. Read actual analytics only after authorization and data availability; use them to improve future topic, hook, pacing, and retention decisions.
12. Save episode memory only after the output passes QA. Preserve job logs, artifacts, status, and failure causes so interrupted work can be resumed or safely retried.

## Minimum video acceptance gate

A pilot is accepted only when the actual downloadable artifact—not merely a log or prompt—passes all applicable checks:

- Valid MP4 container, H.264 video, AAC audio, portrait 720×1280 or better, and target 24 fps.
- Non-zero, plausible duration and no corrupt/truncated media.
- Audible narration, music/effects only when licensed/appropriate, synchronized captions, and no unintended silent sections.
- Multiple distinct, intentionally composed animated scenes with visible motion and progression. No repeated-still slideshow masquerading as 3D animation.
- Hook, development, and payoff are evident; narration is intelligible and not cut off.
- Visual/frame review and factual/source review are documented. Automated QA is not a substitute for claim-level verification.
- Deliver MP4, media-probe output, QA report, scene/contact sheet, transcript/captions, source list, commit SHA, workflow URL, run duration, and any known defects.
- A failed gate must fail the job and preserve diagnostic artifacts. Never label an artifact “verified” unless the gate actually passed.

## Automation and reliability requirements

- Keep routine pull-request checks fast: syntax, unit tests, lint/static checks, and lightweight contract tests.
- Reserve expensive Blender bootstrapping, renderer smoke tests, and full pilot rendering for explicit certification runs and the intended scheduled production run.
- Use concurrency groups that cancel superseded runs for the same workflow/ref. Avoid per-SHA groups that let every stale run continue indefinitely.
- Put hard timeouts on jobs and long-running commands; print progress and actionable failure reasons.
- Do not start duplicate daily production from multiple scheduled workflows. There should be one clearly designated scheduled production entry point.
- Keep CI permissions least-privilege. Never expose API keys in URLs, logs, artifacts, committed files, or chat.
- Make jobs idempotent where possible; avoid duplicate episode creation, uploads, memory writes, and analytics records after retries.
- Separate deterministic offline tests from live Gemini/provider tests and account-authorized publishing tests.
- Persist state and job outcomes. Show queued/running/succeeded/failed/cancelled honestly, with stage, timestamps, errors, and artifact links.

## Publishing and monetization reality

- YouTube uploads, scheduling, and analytics require real OAuth consent, quota, and an actual account-level test. Private upload verification is not public publishing verification.
- TikTok Direct Post requires the relevant official API access, app approval/scopes, and creator authorization. Until verified, manual-upload packaging is the supported fallback.
- No unattended-publication claim until a real end-to-end test confirms the post exists on the intended account and the returned post/video identifier is recorded.
- Do not invent revenue, monetization eligibility, audience metrics, or earnings. Follow platform policies and disclose promotions where required.

## Delivery milestones

### A. Stop workflow waste
- Ensure new commits supersede stale runs for the same workflow/ref.
- PR/push events run fast tests only.
- Full renderer certification runs on manual dispatch; scheduled production is controlled and non-duplicated.
- Inspect and cancel redundant active runs when an authorized cancellation action is available.

### B. Certify the actual renderer
- Pass unit tests and renderer smoke tests.
- Render a complete pilot from the current commit.
- Inspect the real MP4 and frame contact sheet; verify codecs, resolution, duration, narration, captions, scene diversity, and motion.
- Fix root causes and rerun from a clean, reproducible state.

### C. Verify the AI operator
- Test live Gemini access only with configured secrets and available quota.
- Verify grounded research, original scripts, structured memory/continuity, real job state, cancellation/retry, artifact inspection, and useful error recovery.
- Clearly mark human-review requirements and unavailable capabilities.

### D. Verify platform integrations
- Test authorized YouTube private upload and analytics with the owner’s consent; record actual response IDs.
- Test TikTok only if official access is approved; otherwise validate manual upload packages.
- Do not claim scheduling or public publishing works until tested against real platform responses.

### E. Production readiness
- Demonstrate repeatable quality across multiple distinct episodes, not a single lucky render.
- Establish one controlled schedule, artifact retention, failure notifications, quota/rate-limit handling, and a simple owner-facing status view.
- Deliver a final capability matrix: verified working, partially working, needs owner authorization, blocked, and not implemented.

## Definition of done

The system is ready for a limited pilot only when a current commit reproducibly produces a visually reviewed, narrated, captioned, genuinely animated video and all stated defects/blockers are documented. It is ready for autonomous channel operation only after repeated production runs, real platform integration tests, safe scheduling/retry behavior, and honest analytics are verified. Until then, describe it as a working foundation or limited pilot—not a fully autonomous production channel.
