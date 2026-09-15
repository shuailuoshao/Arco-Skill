# IDENTITY CALIBRATION STAGING VALIDATION REPORT

- Calibration ID: `cal-20260911T031117Z-849ec7`
- Validator: **PASS** (`identity-staging-v1`)
- Historical verification fix: **PASS**; immutable/protected/evolvable classes supported
- Identity candidate revision: `0 → 1`
- Asset Index candidate revision: `1 → 2`
- Expression Library: revision `1`, unchanged
- Variant / State: unchanged (`0`)
- Identity Facts: `14`
- Status counts: `UNCERTAIN=10`, `TODO_CALIBRATION=4`, `CANON=0`, `VISUAL_CONSENSUS=0`

## Candidate assets

- Identity Primary: `identity-p01-crop`
- Identity Secondary: `identity-p01`
- Alternate Secondary: `identity-p03`
- Identity Detail: none
- Derived crop: `candidate-root/assets/arco/identity/p01-face-hair-crop.png`
- Derived crop SHA-256: `f2787e9549dd05e65e1a816733f3fb3683a755b83cb449c7edbaa0741e9cbed4`
- Crop box: `[250, 0, 1700, 1500]`
- Parent: `identity-p01`; evidence independence: `none`
- Generation permission: Primary crop `primary`; P01 `secondary`; P03 `supplemental`
- Asset hashes: P01 `bddba1d7b1bed2c21572892003ac50dc6c2340d53e8262a56b6db69b16cf1f86`; P03 `0056f16ff4468a0e26505b521a2fcd8f13a032ddb10e468c22c06c433a38206d`
- Evidence-only Body Base/Faceless/Expression upload: prohibited
- P02/P04: History-only candidates, no generation permission

## Coverage

| Profile | Candidate status |
|---|---|
| portrait | READY |
| upper_body | READY |
| full_body | READY |
| back_view | INCOMPLETE |

`GLOBAL_REFERENCE_READINESS` candidate: **PARTIAL**. No rear evidence was inferred or synthesized.

## Integrity and publication gate

- Formal Identity SHA-256: `ebdd02a3c7c2629ff61e63dca6b917d2f5e8c8809794e1405bbad86901cf4f69` (unchanged)
- Formal Asset Index SHA-256: `405cd66e64acbfe0b0ac2b57a398e0b241090f59719e7878610370a7b98c099a` (unchanged)
- Formal Expression SHA-256: `0bc3c7ae8e18797c472dc79022d0cd74fe71b04c90d5ec02e571c180b41e7030` (unchanged)
- Formal Variant Index SHA-256: `d1f54d8ed48c41316f8817f94750b4c13f1c313877861970af8ef892a233bb1c` (unchanged)
- Manifest state: `STAGED_VALIDATED_AWAITING_AUTHORIZATION`
- `publication_authorized: false`
- Publication: **not executed**
- Remote image generation/upload: **not called**
- Completion marker: **not created**

All specified positive and negative staging checks passed. This staging remains awaiting the explicit command `确认发布 Identity Calibration`.
