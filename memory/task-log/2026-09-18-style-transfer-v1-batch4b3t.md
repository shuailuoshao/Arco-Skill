# Batch 4B.3-T task log — Unicode-safe Codex transport

Date: 2026-09-18 (Asia/Hong_Kong)

## Incident and migration

The Batch 4B.3-F `case-01:A:r1` attempt 1 was generated after Windows shell text encoding altered Chinese characters in the immutable task prompt. The prompt actually sent to image generation did not match the frozen prompt, so the image is invalid experimental evidence. The PNG remains at `evaluation/style-regression/outputs/case-01/A-r1.png`; its SHA-256 remains `45ab0a13b622d9e9ea0e42f51c58380426cea6264e4e589d3ff858bfd4320560`.

The formal manifest now marks A-r1 attempt 1 `invalidated` and `excluded_from_verdict`, with `failure_kind=task_transport` and `failure_reason=prompt_encoding_corruption`. No sent-prompt hash was invented. The unexecuted legacy B-r1 task is retained and marked `superseded`; it is not counted as a generated failure. The original A-r1 image, task records, earlier captures, and earlier Pilot run remain preserved.

## Transport change

- New Codex tasks use schema version 2, `prompt_encoding: utf-8`, and `prompt_sha256_utf8`.
- Python explicitly decodes immutable task JSON as UTF-8. The Codex exchange envelope is ASCII JSON with strict Base64 transport of prompt bytes.
- The runner validates the exact sent prompt’s UTF-8 digest immediately before generation.
- Write-once receipts bind sample and attempt IDs, immutable task digest, sent prompt digest, ordered reference IDs/paths/hashes, output destination, and output hash. Acceptance checks the receipt against the immutable task and output.
- Chinese/non-ASCII round-trip, strict decode, pre-generation rejection, receipt tampering, ordered-reference, output-hash, and migration behavior are covered in `scripts/test_style_regression.py`.
- Windows execution documents `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`; shell stdout is not used as the raw prompt transport.

## Validation and frozen state

- Full unittest discovery: 206 passed.
- `py_compile`: passed for Runtime, adapter, runner, and regression tests.
- Hard Preflight: READY, all four cases READY; reference-free Smoke PASS.
- Isolated Case 01 A/B/C Codex-managed Pilot: 3/3 receipt-validated and accepted under `evaluation/style-regression/pilot/runs/batch-4b3t-r2/`.
- Batch 4B.3-T completion report: `evaluation/style-regression/batch-4b.3t-r2-completion.md`.
- Authoritative immutable capture: `evaluation/style-regression/environment/batch-4b3t-final-preflight-r2.json`; captured runner SHA-256 `1b68379a1683562552844ce3416d9cac084377b713ef6ef451008de03a1917b3`.
- The earlier r1 capture remains unchanged. The preserved A-r1 PNG hash remains unchanged.
- Read-only `--formal-status --codex-managed` returns `case-01:A:r1`, attempt 2, with formal total 0.
- No formal attempt 2 task was created; no formal sample was generated in this implementation task.

After the initial r1 capture, the read-only resume check exposed a separate safe-resume bug: latest historical invalidated/superseded tasks were rechecked against the new runner hash. The audit-only branch now validates their immutable task digests and evidence while skipping the obsolete live runner-hash check. A regression assertion covers the pending index after migration. Since the runner changed, the r1 capture and Pilot were preserved and all gates were rerun into r2.

## Final boundary

Compliant formal generation: **0/36**. Invalid technical attempts: **1**. Next pending compliant sample: **case-01:A:r1 attempt 2**. No visual evaluation, scoring, ranking, or Style Transfer V1.0 verdict was made. Batch 4B.4 was not started.
