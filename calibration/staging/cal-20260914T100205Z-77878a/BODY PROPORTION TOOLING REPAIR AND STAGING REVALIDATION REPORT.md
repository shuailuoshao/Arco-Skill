# BODY PROPORTION TOOLING REPAIR AND STAGING REVALIDATION REPORT

## 1. Calibration

- Calibration ID: `cal-20260914T100205Z-77878a`
- Scope: Prompt Compiler tooling repair and revalidation of the existing body-proportion staging only.
- Candidate data changed: **NO**.
- Publication, History finalize, completion marker, Live Smoke Test, image generation and remote upload: **NOT EXECUTED**.

## 2. Candidate freeze

- Candidate Identity revision: `2`; candidate Asset Index revision: `5`.
- `body.chest_proportion`: `small-to-modest`, `UNCERTAIN`.
- Evidence: `identity-body-c07`, `identity-body-c13`, `identity-body-c14`, `identity-p01`, `identity-p03`.
- Identity Primary: `identity-p01-crop` (unchanged).
- Casual Variant revision 1 and Expression Library revision 1: unchanged.
- Candidate file hashes still equal the staging manifest: Identity `fe4aa2cf6e471703ea8b70a0310a29f283110d1adb12913652b5a1ba9558a90e`; Assets `b65aec7c614b36e6b68217a37fa4a138a15d108c317cd24a9d5afd6e9483e535`.
- The candidate contains 14 facts with its pre-existing status distribution (11 `UNCERTAIN`, 3 `TODO_CALIBRATION`); no status was changed during this repair.

## 3. Prompt propagation repair

- Root cause: `compile_reference_instructions()` compiled only Reference Contracts and had no Identity Fact → Prompt representation path.
- Added pure `resolve_identity_fact_prompt_fragments()` and `compile_prompt()` in `scripts/reference_runtime.py`.
- `UNCERTAIN` facts require explicit `allow_uncertain_working=True`; `TODO_CALIBRATION` is always omitted.
- `body.chest_proportion: small-to-modest` maps to:

  `a slim, lightly built figure with a narrow upper torso and a small-to-modest, understated bust`

- Profiles: `portrait`, `upper_body`, and `full_body`; `back_view` follows existing routing.
- One deduplicated soft guard is allowed: `no exaggerated chest volume`.
- `flat chest`, `tiny breasts`, and `very small breasts` are rejected.
- Selector behavior, Asset permissions, Invocation Plan schema and production formal-only reads were not changed.

## 4. Candidate dry-run

Request: Arco, portrait/chest-up, Casual Outfit, gentle smile, simple indoor daylight.

Selected references, in order: `identity-p01-crop` → `casual-outfit-primary`.

Final prompt:

> a slim, lightly built figure with a narrow upper torso and a small-to-modest, understated bust Reference identity-p01-crop: use to define Arco's identity, including her face, hair and eyes. Do not inherit: expression, outfit, pose. Reference casual-outfit-primary: use to define outfit. Do not inherit: body_proportions, expression, eyes, face, hair, identity, pose. Arco portrait chest-up, Casual Outfit, gentle smile, simple indoor daylight. no exaggerated chest volume

- Body Base C07/C13/C14 selected: `0`.
- Expression PNG selected: `0`.
- Evidence-only selected: `0`.
- Staging paths selected: `0`.
- Mild constraint count: `1`.
- Banned phrase count: `0`.
- Image generation / adapter call: `0`.

## 5. Historical fixture repair

- Root cause: old Identity tests compared a completed Identity transaction with today's later Variant/Asset state; Casual tests required an active lock after Casual publication had completed.
- Added `scripts/historical_test_fixtures.py`.
- Identity tests now use a temporary historical published root based on the recorded transaction candidate and frozen Variant Index/Hash.
- Casual tests now use a temporary active staging copy with pending authorization and the recorded pre-publication rollback root.
- Real staging, formal data, old History and completion markers were not rewritten.
- Validator rules were changed: **NO**.

## 6. Modified tooling files

- `scripts/reference_runtime.py`
- `scripts/test_reference_runtime.py`
- `scripts/historical_test_fixtures.py` (new)
- `scripts/test_identity_staging.py`
- `scripts/test_prepublication_tooling.py`
- `scripts/test_casual_variant_staging.py`
- `references/core/prompt-compiler.md`
- `references/core/generation-runtime.md`

All changes are evolvable tooling or isolated tests; no Identity Calibration target was edited.

## 7. Validation

| Check | Result |
|---|---|
| New Prompt Compiler tests | PASS, 8/8 new cases |
| Runtime test module | PASS, 29/29 |
| Original three fixture blockers | PASS, 3/3; combined fixture suite 21/21 |
| Full regression | PASS, 88/88, 84.04 s, timeout 600 s |
| Body staging validator | PASS |
| Selector tests | PASS, included in Runtime/Prepublication coverage |
| Contract tests | PASS, 3/3 |
| Formal Library Validator | PASS, 0 errors |
| History Draft validation | PASS |
| Skill Validation | PASS with `PYTHONUTF8=1` |
| Protected formal hashes | PASS, unchanged |
| Managed asset hashes | PASS, 51/51 |

Formal protected hashes remain:

- Identity 1: `beffb1b0c1479891fa292e69dbd6682cba434996a7ab1030c8ef8d4dee6d3507`
- Asset Index 4: `4cda53ea9a0eca7929b5372b26e1c49d857a515fafebacd74dda3fae039193fd`
- Expression 1: `0bc3c7ae8e18797c472dc79022d0cd74fe71b04c90d5ec02e571c180b41e7030`
- Variant Index 1: `e9534a08e2daf609780c0c847771ef04052a58c309e6a104480f412905bb10b0`

## 8. Warnings

1. Skill quick validation first failed because the host defaulted to GBK for the UTF-8 `SKILL.md`; the isolated UTF-8 rerun passed.
2. Formal published readiness remains intentionally `PARTIAL`/`INCOMPLETE` for unresolved identity, outfit and back-view facts; the formal validator reported no errors.
3. The Expression baseline retains its eight pre-existing source-locator warnings; they are unchanged and non-blocking.

## 9. Final recommendation

**READY_FOR_BODY_PROPORTION_PUBLICATION**

This is only a recommendation. Publication remains unauthorized and was not attempted.
