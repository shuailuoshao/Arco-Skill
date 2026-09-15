# Identity body proportion pre-publication check

## Understanding

Read-only verification for `cal-20260914T100205Z-77878`; no candidate or formal data writes.

## Acceptance

- Verify C07/C13/C14 evidence closure and single source-family independence.
- Exclude generated/edit images from Character Evidence.
- Preserve identity-p01-crop as sole Identity Primary, Casual Variant 1 and Expression 1.
- Confirm Prompt Compiler uses `body.chest_proportion` with conservative wording and no repeated sexualized phrasing.
- Run full regression, Formal Library, History Draft, Skill, managed asset and protected hash checks.

## Result

- Targeted body staging validator: PASS; C07/C13/C14 evidence closed, same source family, generation permission false.
- Formal YAML and managed asset hashes: PASS; Identity Primary remains `identity-p01-crop`; Casual Variant and Expression remain unchanged.
- Runtime 21/21: PASS; portrait does not select Body Base and upper/full-body retain the existing Identity Secondary behavior.
- Prompt Compiler gate: BLOCKED — `compile_reference_instructions()` does not read or emit the approved `body.chest_proportion` wording/soft constraint.
- Full unittest regression: BLOCKED — 71 tests ran with 2 failures and 1 error from pre-publication staging/fixture assumptions.
- Publication, generation, upload and candidate edits: not performed.
