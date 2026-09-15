# Casual Variant Runtime filter

## Goal and acceptance

Prevent managed outfit selection from crossing Variant boundaries before Casual Outfit staging. Preserve all published character data and stop before staging.

## Decisions

- L2, reversible Runtime and test change; rollback snapshot stored outside the workspace.
- Reuse the existing pure selector and readiness functions; no dependency or remote adapter.
- Require `selected_variant_id`, enforce one eligible Primary, separate Identity/Outfit coverage, and expose profile-aware Global Variant readiness.
- External reuse check supported explicit resource context plus fail-closed policy; local implementation remained dependency-free.

## Result

- Added multi-Variant failure tests and exact adapter-boundary coverage.
- Updated Runtime reference documentation.
- Runtime suite: 21/21 PASS; complete discovery suite: 68/68 PASS.
- Formal library validation: PASS with 0 errors and 0 warnings; Skill validation: PASS under explicit UTF-8 mode.
- All 46 published assets match their registered SHA-256 values.
- Formal data and images remained read-only; Casual Variant staging was not created.
