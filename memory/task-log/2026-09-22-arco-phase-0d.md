# Arco Phase 0D real baseline capture

- Goal: execute and seal the seven frozen Phase 0 regression steps through the unchanged production Runtime and real Codex ImageGen host.
- Decision: reuse the repository's immutable Codex-managed task-exchange pattern because the host tool is not importable as a Python callable. The bridge freezes only the actual adapter payload and does not implement production mapping or routing.
- Result: seven canonical real outputs and seven canonical success receipts were sealed. One additional case-01 first-generation attempt is retained as a failed host-network attempt; its exact-payload retry succeeded.
- Replay-check: PASS. Focused Phase 0 suites: 26/26 PASS. Full discovery: 257/258 PASS with the known pre-existing Batch 4B.2 start-revision assertion conflict.
- Production Runtime diff: NONE. Phase 0D: PASS. Phase 0 Gate: PASS. Phase 1 was not started.
