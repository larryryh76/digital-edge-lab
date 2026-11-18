# Digital Edge Lab — Ready-Made Video Quality Stack

Research checked: 18 November 2026.

## Decision

There is no trustworthy, fully automatic, zero-cost service that turns a topic into a finished, fact-checked, cinematic YouTube Short and reliably publishes it to both YouTube and TikTok. The best fit is a hybrid pipeline: keep the project's custom story planning, Blender scene direction, QA, and platform packaging, while adopting proven external services for compute, production assets, and voice.

Do not add a paid provider or start a metered API without explicit owner approval. Any external provider must be optional, have a deterministic fallback, and report whether it was actually used.

## High-value ready-made components

| Need | Ready-made option | Fit | Decision |
|---|---|---|---|
| Better final rendering | Kaggle Notebooks GPU + Kaggle CLI/API | Free GPU notebook execution; API supports automated notebook workflows. Kaggle documents GPU quotas and a 12-hour session limit; GPU availability and quota are not guaranteed. | Best first experiment for an optional GPU render worker. Keep GitHub Actions CPU path for fast tests and fallback. |
| Real 3D models, HDRIs, PBR materials | Poly Haven + public API | Assets are CC0, including commercial use. API is free but requires a small “Powered by Poly Haven” credit when using the API. | Adopt as the first curated asset source. Cache and pin selected asset versions; retain source/license metadata. |
| More ready-made Blender assets | Blendkit (formerly BlenderKit) | Free tier includes a subset of models, materials, scenes and HDRIs; full library is paid. Licenses vary by asset between Royalty Free and CC0. | Optional manual/curated asset source; never assume every item is CC0. |
| Character rigs and human motion | Adobe Mixamo | Free with Adobe ID; Adobe says characters and animations can be used in personal, commercial and non-profit projects. | Use only when a story genuinely needs a human/character. Not a replacement for technical-object animation. |
| Distributed Blender render farm | SheepIt | Free, supports Blender engines, but project priority uses points earned by sharing compute. The owner can be soft-paused when their point balance is too negative. | Keep as a manual fallback/experiment, not the primary unattended pipeline. |
| AI-generated video clips | Wan 2.2 / HunyuanVideo / LTX-2 family via self-hosting or hosted services | Open weights exist, but high-quality generation needs substantial GPU memory. Hosted services use credits or paid plans; licenses differ. | Do not run these on GitHub's CPU runner. Revisit only through a verified free allowance or owner-approved budget. |
| Narration | Existing Gemini TTS + local Piper fallback | Gemini 3.8 Flash TTS currently lists a free tier, but free-tier data may be used to improve Google's products; limits are not a production SLA. Piper is local and predictable but less expressive. | Keep Gemini as preferred voice when available; keep Piper as labelled fallback. Compare actual WAVs before declaring voice quality solved. |

## Important findings

### 1. Current renderer is intentionally preview-grade

The checked-in Blender renderer currently sets:

- 288 × 512 render resolution
- 12 fps
- 1 EEVEE sample
- final delivery is then scaled to 720 × 1280 and encoded at 24 fps

That is a real ceiling on detail and motion smoothness. The final encode cannot restore detail or temporal information that was never rendered. This should remain the cheap CI/preview profile, not the final-quality production profile.

**Production target:** render at native 720 × 1280 or higher and 24 fps minimum; use a GPU-capable worker for higher EEVEE sample counts or Cycles where the shot benefits. Do not increase quality settings on the existing 2-core CPU runner without a measured render-time budget.

### 2. Kaggle is the most promising no-cost automation experiment

Kaggle's official documentation describes GPU notebook execution, programmatic notebook workflows through the Kaggle CLI/API, and session limits. The GPU quota is limited and availability can vary. This is more automatable than an interactive Colab session, but it is not guaranteed capacity.

A safe integration should:
1. Be an explicit manual/opt-in production mode, never silently switch to a paid service.
2. Upload a pinned Blender project, scripts, assets and exact dependency manifest.
3. Render a small GPU capability probe before the full episode.
4. Fail closed if GPU is unavailable or quota is exhausted; preserve the CPU preview and diagnostics.
5. Download the rendered frames/video and run the same local encoded-media QA gates.
6. Record accelerator type, Blender version, render settings, timings, and artifact checksums.
7. Require Kaggle API credentials as repository secrets; never commit token files.

No Kaggle account or API token has been configured or tested for this repository yet.

### 3. Poly Haven is the strongest free asset source

Use its CC0 HDRIs for believable reflections and ambient lighting, PBR textures for surfaces, and selected models for scene dressing. Cache only assets actually used in a scene. Keep an asset manifest containing slug, download URL, license, source URL, checksum and selected resolution. The public API's attribution requirement is separate from the CC0 asset license.

### 4. SheepIt is free, but not a guaranteed free compute shortcut

SheepIt is a real distributed render farm. Its points system rewards users who contribute their own compute and spends points when other machines render a user's frames. The service can pause projects when the balance is too negative. This makes it useful as an optional community render route, but not a dependable zero-effort automation dependency.

### 5. Do not confuse a model download with usable production capacity

Wan/Hunyuan/LTX weights are not equivalent to a hosted free API. Their memory, setup, runtime, license and hosting constraints must be checked for the exact checkpoint. A free web demo or credit grant is not an unlimited production allowance. No video-generation provider should be wired into the daily workflow until a real end-to-end test establishes output quality, availability, licensing, and per-episode cost.

## Integration order

1. Finish exhaustive real-Blender subject/action certification and preserve the fast PR feedback path.
2. Separate the preview render profile from a native-resolution production profile.
3. Add a curated Poly Haven asset manifest and optional cached asset import; keep the procedural fallback.
4. Build the optional Kaggle GPU worker behind an explicit mode and secrets check.
5. Compare identical scenes on CPU preview and GPU production using actual frames, render time, and QA results.
6. Add character animation only for episodes that need it; add sound/music libraries only with a verified per-asset license and attribution record.
7. Review the actual MP4/contact sheet and narration audio before accepting a production-quality episode.

## Sources

- Kaggle GPU usage and API: https://www.kaggle.com/docs/efficient-gpu-usage and https://www.kaggle.com/docs/api
- Google Colab resource limits: https://research.google.com/colaboratory/faq.html
- Poly Haven CC0 license: https://polyhaven.com/license
- Poly Haven public API and attribution terms: https://github.com/Poly-Haven/Public-API
- Blendkit free/paid plans: https://www.blendkit.com/plans/pricing/
- Blendkit asset licenses: https://www.blendkit.com/docs/licenses/
- Adobe Mixamo FAQ: https://helpx.adobe.com/creative-cloud/faq/mixamo-faq.html
- SheepIt project points and render-farm rules: https://api.sheepit-renderfarm.com/faq
- SheepIt service and supported Blender engines: https://www.sheepit-renderfarm.com/
- Blender rendering engines: https://www.blender.org/features/rendering/
- Gemini API pricing/free-tier notes: https://ai.google.dev/gemini-api/docs/pricing

This document is a researched integration plan, not a claim that these external services have already been connected or live-tested.
