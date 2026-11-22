# Digital Edge Lab — Real 3D Animation Engine Replacement Roadmap

**Status:** execution roadmap; engine replacement is not yet complete  
**Hard constraint:** no still-image-to-video or slideshow motion. The engine must animate real scene objects, rigged characters, props, and cameras in 3D.

## Decision

Keep Blender as the 3D scene compositor/renderer, but replace the current subject treatment gradually with a reusable asset-and-animation system. The existing typed procedural renderer is useful for deterministic QA and technical metaphor scenes; it is not sufficient as the final storytelling engine. The Continuous Story and free-video procedural graphics generators are preview/diagnostic outputs, not production-quality replacements.

## Target pipeline

1. **Story/script:** original hook, grounded facts, character intent, progression, and payoff.
2. **Shot plan:** each shot has subject IDs, action/animation clip, props, environment, framing, camera move, lighting, and duration. Validate before rendering.
3. **Asset selection:** prefer locally cached, pinned assets with explicit license records. CC0 assets are the default for reusable commercial channel assets. Keep source URL, creator, license, download version/hash, and attribution requirements in the manifest.
4. **Characters:** use real mesh characters with armatures and reusable animation clips. Begin with a small curated cast, not random assets per episode. Keep the same character IDs/appearance through an episode and series.
5. **Animation:** retarget approved motion clips to supported rigs; blend transitions; add hand/head/prop actions and procedural secondary motion. If no matching action is supported, fail the shot or use an intentional non-character shot—not a fake animation.
6. **Scene:** import genuine 3D environments, set dressing, props, physically based materials, lighting, and depth. Technical metaphor shots may use authored Blender objects, but should have cinematic composition and real interactions.
7. **Cinematography:** virtual camera blocking, lens/framing changes, tracking/dolly/orbit/pan, cuts and match cuts. Camera motion cannot be the only source of movement in a shot that claims character/object action.
8. **Render:** real frames from evaluated 3D scene state at target frame rate. Maintain preview and final profiles; preview output must never be promoted as final by merely upscaling.
9. **Audio/edit:** licensed sound effects and ambience, commercial-safe narration, captions timed from measured narration, dialogue pauses, transitions, and an intelligible final mix.
10. **QA:** inspect subject motion—not just camera/background—using sampled rendered pixels and object-motion traces. Detect frozen subjects, motion discontinuities, off-screen actions, missing/incorrect assets, repetitive shot compositions, black frames, audio gaps/clipping, captions outside safe areas, and unsupported claims. Fail closed; preserve diagnostics.
11. **Delivery:** MP4, transcript, timed captions, asset/license manifest, source/claim notes, thumbnail/contact sheet, probe output, visual-motion report, QA report, and workflow metadata.

## Zero-budget asset policy

- **First candidates to test:** Quaternius CC0 Universal Animation Library (including both clip packs) and CC0 character/prop/environment packs; Poly Haven CC0 environments/HDRIs/materials.
- **Optional humanoid source:** Mixamo may be used after its current terms are rechecked and the exact use (commercial video, downloadable assets, no redistribution of raw clips) is documented.
- **Do not use:** assets with unclear license, non-commercial restrictions, unverified AI training/output rights, paid-only features, API credits, watermarked demo outputs, or raw re-uploaded animation packs with questionable provenance.
- **Fallback:** deterministic authored Blender animation and pinned CC0 assets. The fallback must remain genuine 3D object/character animation; it must not switch to still-image animation.
- **Cost safety:** no paid API/service, GPU rental, or metered provider without explicit owner approval. GitHub Actions CPU jobs stay lightweight. GPU/render experiments remain manual, quota-aware, and optional.

## Implementation milestones and gates

### A. Stabilize current pipeline (in progress)
- Correct brittle unit-test contracts.
- Keep all existing safety, state, audio, media, and renderer regression tests passing.
- Reduce duplicate workflow runs; keep PR checks fast.
- Verify a production run and preserve diagnostics.

**Gate:** full offline test suite passes; current workflow regression is repaired; no false QA passes.

### B. Curated asset foundation
- Add a small version-pinned CC0 asset manifest.
- Build asset download/cache, hash verification, safe extraction, and license metadata validation.
- Add Blender import tests for the supported formats and missing/corrupt asset behavior.
- Start with 1–2 characters, a few environments, and a manageable prop set.

**Gate:** every imported asset is traceable to a source and license; deterministic CI can load assets without paid APIs.

### C. Rig and motion system
- Validate armature naming/structure, animation clip inventory, retargeting, clip blending, loop quality, and transition rules.
- Create typed action capability matrix per character/rig.
- Add scene tests for walk/run/idle/turn/look/react/reach/pick-up/put-down and object interactions where supported.
- Reject unsupported action combinations before rendering.

**Gate:** the character visibly performs the intended action in actual rendered frames; the camera cannot satisfy the subject-motion check by itself.

### D. Cinematic shot assembly
- Add reusable shot templates (establishing, close-up, tracking, over-shoulder, reveal, reaction, interaction).
- Add depth layers, lighting continuity, shot-specific composition and safe framing.
- Generate multiple distinct shots for each story rather than one generic scene with a changing label.

**Gate:** contact sheets show different readable compositions; a human visual review confirms the scene/story matches the script.

### E. Render and artifact QA
- Separate fast preview from final render settings.
- Add sampled-frame pixel-difference/motion analysis with subject masks/regions when available.
- Add checks for repeated frames, frozen intervals, camera-only movement, subject visibility, caption/audio sync and end truncation.
- Run representative subject/action tests against real Blender renders and inspect actual artifacts.

**Gate:** repeated frozen or misleading scenes are blocked; reports clearly separate automated checks from visual human review.

### F. Production pilot
- Render at least three different story topics using the new asset/rig system.
- Compare quality, motion, runtime, render cost and QA results.
- Only route production to the new engine after all pilot gates pass. Do not label the 2D Continuous Story or procedural graphics output as cinematic 3D.

## Non-negotiable acceptance

- Actual 3D geometry, scene depth, animation and camera changes; no image-to-video and no slideshow/Ken Burns.
- The intended character/object is visibly moving or interacting—not just background particles, camera drift, labels or captions.
- Story continuity and consistent character identity across shots.
- All assets are commercially usable under documented licenses.
- Output quality is reviewed from the encoded video/contact sheet, not inferred from source code or successful workflow status.
- No paid APIs or services without explicit approval.
