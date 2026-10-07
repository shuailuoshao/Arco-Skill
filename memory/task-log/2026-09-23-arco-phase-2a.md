# Arco Phase 2A — Character Reference Re-anchor

## Objective and boundary

Consume the frozen Phase 1 `RevisionPlan` to restore formal Identity and Outfit authority during revisions. Preserve first generation, scene-only editing, and frozen Phase 0 artifacts. Do not implement Source Reset, physical deduplication, or real A/B generation.

## Decisions

- Add a revision-only bridge in `scripts/revision_reference.py`; production uses the existing selector, style context, and Invocation Plan.
- Formal `managed_arco` Identity owns WHO; formal Outfit for the selected Variant owns Variant. External contracts own HOW.
- Previous output is retained with explicit continuity authority and no WHO/Variant coverage or inheritance. Its image path remains first for legacy Image 1 edit prompts.
- The current Variant ID can be supplied from formal generation context. Missing or conflicting Variant context fails closed.
- `source_reset` is deferred before any provider call.

## Verification

- Phase 2A focused tests: 20 passed (including separate face, eye, hair, and anatomy subcases).
- Phase 1 focused tests: 8 passed. Reference and production tests: 102 passed.
- Phase 0 isolated baseline: fixture validation READY, replay-check 7/7 PASS, 26 tests passed, 64 frozen files hash-identical.
- Full main-worktree suite: 286 tests, 279 passed, 7 failed. Six Phase 0 tests are gated by intentionally dirty protected runtime files; the isolated baseline passes. One Style Regression test has the known Batch 4B.2 start-revision mismatch.
- Physical deduplication and real image generation were not performed.
