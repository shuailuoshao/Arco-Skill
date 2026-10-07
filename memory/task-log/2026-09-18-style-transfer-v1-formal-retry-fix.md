# Batch 4B.3-T formal retry fix

- Recorded: 2026-09-18
- Result: PASS; formal batch remains fail-closed at 31/36.
- Formal counts: A=11, B=10, C=10, total=31.
- Terminal sample: `case-04:B:r2`; `imagegen_safety_block`; `provider_policy_refusal`; retry disallowed.
- Implementation: explicit failure policy, bounded retry state, sanitized structured failure records, generated PNG path validation, structured formal status, and append-only r5 checkpoint capture.
- Historical preservation: 69 task attempts, 31 receipts, 32 PNG outputs, and the manifest remain unchanged; legacy policy exceptions are exact attempt hashes only.
- Capture: `evaluation/style-regression/environment/batch-4b3t-formal-continuation-r5.json`.
- Validation: full unittest discovery 213/213 PASS; `py_compile` PASS; r5 validation PASS; read-only formal status PASS.
- Next: require a separately authorized prompt or protocol revision before any further generation.
