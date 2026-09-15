# IDENTITY BODY PROPORTION CALIBRATION STAGING VALIDATION REPORT

- Calibration ID: `cal-20260914T100205Z-77878a`
- Decision: `READY_FOR_IDENTITY_BODY_PROPORTION_CALIBRATION_PUBLICATION`
- Scope: `body.chest_proportion` plus C07/C13/C14 evidence-only registration
- Identity candidate revision: `2` (formal remains `1`)
- Asset Index candidate revision: `5` (formal remains `4`)
- Candidate value/status: `small-to-modest` / `UNCERTAIN`
- Evidence: `identity-body-c07`, `identity-body-c13`, `identity-body-c14`, `identity-p01`, `identity-p03`
- Prompt representation: `a slim, lightly built figure with a narrow upper torso and a small-to-modest, understated bust`
- Soft constraint: `no exaggerated chest volume`

## Validation

- Targeted staging validator: PASS
- Protected formal-file hashes: PASS
- Identity Primary uniqueness and P01 crop SHA-256: PASS (`386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414`)
- Identity contract and runtime regression tests: PASS (24 tests)
- Publication executed: `false`
- Image generation called: `false`
- Remote upload: `false`

The staging lock remains `staged_validated_awaiting_authorization`; no publication, generation, or Live Smoke Test was performed.
