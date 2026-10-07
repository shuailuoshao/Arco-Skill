# Style Transfer V1.0 — Batch 4B.2-U Experiment Unblock

## Goal and boundary

- Unblock the four-case style-transfer experiment and prepare the one-run Case 01 A/B/C Pilot.
- Preserve the pre-existing dirty main worktree and record its Batch 4B.2 start revision/status in the existing environment capture.
- Keep formal generation at 0/36. Do not create a visual verdict or start Phase 2.
- Do not change production Style Runtime, selector, Prompt Compiler, Rendering Hygiene semantics, `ArcoRealAdapter`, or provider payload schema.

## Decisions and implementation

- Corrected Legacy worktree `D:/learn/Arco-legacy-selector-fixed` now expects the corrected full-body selector to exclude `identity-p01-crop`. No selector or runtime code changed in that worktree.
- The control-only test correction is commit `e2df644aac2df0317204f892e17d9946688a2d52`. Corrected Legacy patch SHA-256: `af6293c81e1b4e7b64e8f6ba224028d324ed20504a26cf1a19afacbff11a1e9b`. Control metadata records the updated revision, hash, and three-file patch allowlist.
- The existing regression suite now validates case-bound Brief metadata (`style_reference_sha256`, `created_for_case`), external image/hash and provenance failures, host smoke flags/timestamps/fresh output, B/C context parity, selector/scene parity, Hygiene-only prompt differences, Pilot gating and manifest isolation, Pilot artifact hashes, and final formal count exclusion.
- Pilot rows record `pilot: true`, `formal: false`, parity results, and the unchanged provider payload keys `prompt` and `referenced_image_paths`. The Pilot CLI now runs the final hard preflight, required tests/compiles, and writes the immutable Batch 4B.2-U environment capture after the Pilot attempt.
- The new final record path is `evaluation/style-regression/environment/batch-4b2u-final-preflight.json`; historical preflight/completion records are preserved. The original `environment.json` start capture remains unchanged.
- Main workspace start revision was `6ab0373631fb93ac043498e5e6b4f09750db33a4`; it was already dirty. Its tracked and untracked start paths/status are retained in `environment.json`.

## Validation

- Full production unittest discovery: 183 tests, 0 failures, 0 errors.
- Corrected Legacy Runtime and adapter suites: 42 tests, 0 failures, 0 errors.
- `py_compile` passed for production Runtime, adapter, runner, and regression tests; corrected-control Runtime, adapter, and focused test modules also compile.
- Production Runtime, adapter, `runtime/generation.yaml`, and `runtime/style-policy.yaml` SHA-256 values match the recorded start hashes.
- Formal manifest remains empty (A=0, B=0, C=0; 0/36). No Pilot manifest or host smoke result exists.

## Current gate and next inputs

- Experiment status: **BLOCKED**. The four private Style Reference images and their provenance, four case-level Style Brief files, and existing host `module:callable` binding were not present in the workspace.
- No reference or Brief was synthesized. Input freeze, host smoke, four-case hard Preflight, Pilot, and final immutable preflight capture remain unrun until those inputs are provided.
- After intake, freeze the four references and Briefs, run the reference-free smoke, require all four cases READY, then attempt Case 01 A1/B1/C1 exactly once. A failed/partial Pilot remains blocked and must not be retried.
