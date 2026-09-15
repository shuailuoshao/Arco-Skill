# Current state

- Goal: keep the published Arco Runtime safe while exposing a contract-checked Real Adapter for explicit generation.
- Current milestone: `ArcoRealAdapter` implementation is complete; it validates frozen plans/contracts/paths, invokes an injected `builtin_image_gen`, and returns only a verified output path.
- Locked decisions: `casual-outfit`; explicit `selected_variant_id`; fail closed; profile-aware Variant readiness.
- Data boundary: Identity 1, Assets 3, Expressions 1, Variant Index 1, Casual Variant 1; Identity/Expression/old Calibration History unchanged.
- Validation: pre-publication candidate PASS; Runtime 21/21; Casual staging 9/9; regression baseline 77/77; final Formal/History/Skill/managed-hash/production dry-run validation PASS.
- Next: bind the host's `builtin_image_gen` callable when a live generation is explicitly requested; do not auto-register the output or start Calibration.

## Arco Real Adapter implementation closure

- Recorded: 2026-09-15
- Adapter: `scripts/arco_real_adapter.py`
- Focused tests: 12/12 PASS
- Full unittest discovery: 100/100 PASS
- Formal library structural validation: PASS (0 errors, 0 warnings)
- Character/Variant/Asset/Calibration data: unchanged
- Live provider invocation: not performed; tests use an injected fake Provider

## Casual reference-conditioned pipeline acceptance closure

- Recorded: 2026-09-15
- CASUAL_REFERENCE_CONDITIONED_PIPELINE: PRODUCTION_READY
- RESULT: PASS
- Scope: Casual reference-conditioned pipeline validation only; this does not change formal character data or Evidence Status.
- Formal revisions confirmed unchanged: Identity 2; Asset Index 5; Expression Library 1; Variant Index 1; Casual Variant 1.
- Human visual acceptance: torso silhouette PASS; body.chest_proportion PASS; small-to-modest proportion PASS; overcorrection not found; shoulder/chest/waist relationship natural; Casual Outfit structure PASS; WHO consistency PASS; Expression consistency PASS; reference contamination not observed.
- Body constraint: no outfit deformation observed.
- RGBA display finding: black regions are classified as ALPHA_DISPLAY_ARTIFACT, not generation/content failure.
- Artifact role: runtime validation artifact only.
- Character Evidence registration: NO.
- Evidence Status progression: NO.
- Calibration: NOT CREATED.
- Validation artifact: `C:\Users\shuai\.codex\generated_images\01a0a336-104f-7150-b522-5033638d86a2\exec-ae1b74ae-aa7e-433e-9164-baaa7d3e0b77.png`.
- Validation report: `memory/task-log/2026-09-15-arco-casual-upper-body-final-validation.md`.
- Next: wait for explicit user authorization; do not automatically start another generation, Calibration, School Variant, Evidence registration, or other next-stage workflow.
