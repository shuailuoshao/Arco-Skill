# IDENTITY PRE-PUBLICATION CHECK REPORT

## Regression

- Focused test: `test_full_body_variant_lists_lower_body_and_footwear_gaps`
- Start: `2026-09-11T03:35:57.766138+00:00`
- End: `2026-09-11T03:36:00.146421+00:00`
- Duration: `2.380s`
- Result: **PASS**
- Suite: `test_validate_library`, 26 tests
- Suite start: `2026-09-11T03:36:14.634204+00:00`
- Suite end: `2026-09-11T03:37:12.498009+00:00`
- Suite duration: `57.864s`
- Result: **PASS** (`26/26`)
- Cause classification: normal-but-slow fixture/validator setup; no dead loop or semantic regression observed. The prior 60-second cutoff was too short.
- Focused stdout: empty; stderr: unittest progress and `Ran 1 test ... OK`.
- Suite stdout: empty; stderr: unittest progress and `Ran 26 tests in 57.658s OK`.

## Primary crop

- Parent dimensions: `2207 × 3813`
- Crop dimensions: `1700 × 1500`
- Crop box: `[250, 0, 1700, 1500]`
- Bounds: **PASS**
- Deterministic re-run hash: **PASS**
- Pixel derivation from parent region: **PASS**
- Resize/recolor/enhancement/repaint: **none detected**
- Image mode: `RGBA`, full-range color; no abnormal alpha mode
- SHA-256: `f2787e9549dd05e65e1a816733f3fb3683a755b83cb449c7edbaa0741e9cbed4`

Visual inspection:

- Entire face: retained
- Both eyes: retained
- Bangs: retained
- Top-of-head/hair origin: retained
- Major side locks: retained, with some lower ends naturally clipped by the crop
- Chin: retained
- Hair silhouette: suitable for portrait/upper-body WHO anchoring
- Outfit leakage: **high**; collar, red bow, suspenders, sleeves and waist remain visible
- Invalid transparent region: none material; transparent corners are normal background

Recommendation: **NOT_READY_FOR_PUBLICATION** until the outfit-leakage decision is explicitly accepted or a tighter approved crop is requested. The crop is technically valid and remains unchanged in staging.

## Readiness and protection

- Identity candidate: `0 → 1`
- Asset Index candidate: `1 → 2`
- Expression: `1` unchanged
- Variant: `0` unchanged
- State: unchanged
- Global readiness: `PARTIAL`
- Coverage: portrait READY, upper_body READY, full_body READY, back_view INCOMPLETE
- Formal Identity/Asset/Expression/Variant hashes: unchanged
- Publication authorization: false
- Publication: not executed
- Remote image generation/upload: not called
