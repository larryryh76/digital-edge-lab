# Digital Edge Lab

A zero-budget-first workflow for producing original faceless educational videos about AI, technology, digital tools, and online-business workflows.

## Current stage

This repository creates a **pilot video artifact**. It does not publish to YouTube or TikTok yet. Automatic publishing will only be added after the required platform accounts, permissions, and tests are complete.

## Android-friendly setup

1. Open **Settings → Secrets and variables → Actions** in this repository.
2. Choose **New repository secret**.
3. Set the name to `GEMINI_API_KEY` and paste a Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey).
4. Open the **Actions** tab.
5. Select **Digital Edge Lab — Generate pilot** → **Run workflow** → **Run workflow**.
6. Open the finished run and download the `digital-edge-lab-pilot` artifact.

Never paste an API key into source code, issues, screenshots, or chat. The repository is public, so everything committed here is visible to everyone.

## What the pilot does

- Asks Gemini to produce a short script, scene plan, and source URLs.
- Requests narration from Gemini TTS.
- Generates original blue/cyan motion-graphic cards.
- Renders a vertical MP4 using FFmpeg.
- Uploads the result as a downloadable workflow artifact.

The pilot is a technical test, not a finished publishing system. Review facts, source URLs, audio, and video before posting.

## Free-tier limitations

API availability, model names, and quotas can change. Do not enable billing or paid services unless you explicitly choose to. Consumer Gemini video-generation features are not the same as a free, unattended video-generation API. If Gemini TTS is unavailable for your account, the workflow will fail visibly rather than silently create a video with no narration.

## Roadmap

1. Generate and inspect the first pilot.
2. Fix any API/model or rendering errors using the workflow logs.
3. Improve visual variety and package long-form and vertical exports.
4. Set up YouTube OAuth and test uploads as private/unlisted first.
5. Apply for TikTok Content Posting API access and required scopes/audit.
6. Enable scheduling only after end-to-end tests pass.

## Quality and compliance

Make videos useful and original, with meaningful explanations and editorial judgment. Do not invent statistics, claim personal testing that did not happen, or reuse media without permission. Repetitive low-value mass-produced content may not qualify for monetization. Disclose realistic synthetic/altered media where platform rules require it.
