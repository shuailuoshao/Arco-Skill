# Batch 5 — Style Transfer V1.0 usable release integration

- Recorded: 2026-09-20
- Result: READY FOR NORMAL USE.
- Production entrypoint: `scripts/arco_production.py:run_production_generation`.
- Defaults: Style Transfer ON; Rendering Hygiene OFF. `hygiene_v11` is an explicit request-scoped experimental opt-in only.
- Implementation: composed the published Reference Selector, Style Reference/Brief Resolver, ResolvedStyleContext, Prompt Compiler, Identity protection, Invocation Plan, and ArcoRealAdapter without changing their rules.
- Tests: production smoke tests 9/9 PASS; full unittest discovery 232/232 PASS; production py_compile PASS.
- Real E2E: one built-in ImageGen call through the production entrypoint succeeded. Output is isolated at `evaluation/style-transfer-v1-release/release-smoke/arco-production-smoke.png`; SHA-256 is `e9d1ae19cfb8c55ee16bdfc0b0034e3cf440d3805bdf7e3c988a2aa01940868e`.
- Historical preservation: read-only Pilot preflight revalidation passed (19/19 inputs, 8/8 protected hashes). Batch 4B/4C.1/4C.2-P evidence was not edited, and no Batch 4C.3 or formal regression was started.
- Stop condition: release report written; no further image experiment queued.
