# Style Transfer V1.0 — Batch 4B.3

## Goal and boundary

- Record the Batch 4B.3 formal-generation gate without generating images or changing the frozen experiment inputs.
- Keep formal count at A=0, B=0, C=0, total 0/36.
- Do not evaluate images or issue a V1 verdict.

## Findings and decision

- The saved Batch 4B.2-R capture reports hard Preflight READY for all four cases, and its completion record reports a passing Codex-managed smoke and successful Case 01 A/B/C Pilot runs.
- Current `python scripts/run_style_regression.py --dry-run` returned READY: four cases, 36 planned samples, parity checked for four cases, and no blockers.
- The runner rejects `--generate --codex-managed` at `scripts/run_style_regression.py:3738-3739`. The existing Codex task acceptance route records Pilot samples only, so it cannot emit or accept the immutable formal tasks required for this batch.
- Per the batch stop condition, `case-01-A-r1` was not dispatched. No alternate provider route, direct generation, or manual task was used.

## Result and validation

- Completion record: `evaluation/style-regression/batch-4b.3-completion.md`.
- Formal manifest: `evaluation/style-regression/manifest.jsonl`, still empty.
- Formal output directory: `evaluation/style-regression/outputs/`, absent.
- Technical retries: 0. Formal output hashes recorded: 0/36.
- No frozen-input drift was flagged by the current dry run. SHA-256 values for the Runtime, Adapter, runner, generation config, style policy, and cases match the immutable preflight capture. No production or frozen experiment files were changed for this blocked run.
- No formal generation, visual scoring, ranking, V1 verdict, or tuning occurred.
- Any runner change requires a new experimental freeze; do not continue this batch under a modified runner.
