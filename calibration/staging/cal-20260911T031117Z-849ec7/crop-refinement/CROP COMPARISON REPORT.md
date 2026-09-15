# IDENTITY PRIMARY CROP COMPARISON REPORT

Calibration: cal-20260911T031117Z-849ec7. Status: AWAITING_USER_SELECTION. Recommendation: Candidate A. No asset selection or publication authorization has been changed.

## Crop inventory

Coordinates are [x, y, width, height], in unscaled parent pixels, with the origin at top left. Parent is identity-p01, candidate-root/assets/arco/identity/p01-full.png, dimensions 2207 × 3813. Parent SHA-256: `bddba1d7b1bed2c21572892003ac50dc6c2340d53e8262a56b6db69b16cf1f86`.

| Candidate | Crop box | Dimensions | SHA-256 |
|---|---|---|---|
| Current Crop | [250, 0, 1700, 1500] | 1700 × 1500 | f2787e9549dd05e65e1a816733f3fb3683a755b83cb449c7edbaa0741e9cbed4 |
| A / identity-p01-crop-candidate-a | [680, 0, 760, 640] | 760 × 640 | 386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414 |
| B / identity-p01-crop-candidate-b | [560, 0, 1000, 760] | 1000 × 760 | 3f3667aac68fa277783b2bde63b4b4eb507488c691d1240eb81140160e00efba |
| C / identity-p01-crop-candidate-c | [400, 0, 1280, 840] | 1280 × 840 | 8a25cb9f8a82206ff0ccb1483d6c24d619252a8cc799c79c53c1aebb3e036807 |

All new crops are in this report's directory. The Current Crop remains in its original candidate-root path, byte-for-byte unchanged.

## Visual scores

Scores are reviewer judgments, not model output measurements. For completeness/readability/suitability, 5 is best and 1 is worst. Leakage uses LOW/MEDIUM/HIGH, where LOW is preferable. No live generation was performed.

| Criterion | Current Crop | A | B | C |
|---|---|---|---|---|
| Face completeness | 5 | 5 | 5 | 5 |
| Eyes visibility | 5 | 5 | 5 | 5 |
| Bangs visibility | 5 | 5 | 5 | 5 |
| Hair-origin visibility | 5 | 5 | 5 | 5 |
| Side-lock visibility | 5 | 3 | 4 | 5 |
| Hair identity readability | 5 | 4 | 4 | 4 |
| Hair-color readability | 5 | 3 | 3 | 3 |
| Face identity readability | 5 | 5 | 5 | 5 |
| Outfit leakage | HIGH | LOW | MEDIUM | MEDIUM |
| Pose leakage | HIGH | MEDIUM | MEDIUM | MEDIUM |
| Expression leakage | HIGH | HIGH | HIGH | HIGH |
| Portrait generation suitability | 2 | 5 | 4 | 3 |
| General WHO-anchor suitability | 2 | 5 | 4 | 3 |
| Recommendation | Comparison only; reject as default | Recommended | Alternative if more lateral hair is preferred | No advantage sufficient to offset added outfit |

All retain the chin, entire face, both eyes, and naturally visible brow/eye region. Bangs obscure parts of the eyebrows in the parent; cropping cannot reveal those parts. Hair origin is retained with the parent's original tight top margin.

Candidate A retains the face-framing portions of both major side locks; their lower curves/tips are cut. Rightmost trailing hair strands are also cut at the boundary. A small amount of white collar, dark suspender edge and shoulder remains along the bottom; no bow, waist or meaningful torso silhouette is retained. This is LOW leakage, not zero. The face and silver-blue hair provide a useful WHO anchor, while pink-tip gradient and full hair length are insufficiently represented.

Candidate B retains more lateral hair but cuts the lower tips. The white collar, dark suspenders, shoulder and top of the red bow remain clearly recognizable: MEDIUM outfit leakage. Candidate C retains a front side-lock curl and more lateral silhouette, but includes more red bow and shoulder clothing: MEDIUM leakage, at its upper end. Neither B nor C fully establishes pink hair-tip gradient.

Current Crop retains much more hair length and pink gradient, but also collar, bow, suspenders, sleeves and waist, resulting in HIGH outfit and pose leakage. It remains a comparison, not a recommended default.

All candidates inherit the same tilted head and wide-open mouth from P01. Expression leakage remains HIGH; deterministic cropping does not neutralize that expression. The scores judge the visual anchor, not demonstrated generation behavior. `expression: do_not_inherit` and `pose: do_not_inherit` remain required, but do not guarantee zero leakage.

## Pixel verification and alpha

For A/B/C, bounds checks passed. Each generated PNG was decoded as RGBA and compared byte-for-byte against the corresponding decoded parent crop region: all pixels and alpha match exactly. No resizing, recoloring, repainting, background replacement or enhancement was used. SHA-256 and decoded-pixel hashes are in verification.json. File encoding may differ from the parent PNG; image samples do not.

Fully transparent pixel fractions: A 25.98%, B 37.47%, C 46.87%. Transparency is inherited background around the head; no replacement or masking was introduced. C spends substantially more canvas on transparent background and clothing without improving the face.

## Proposed coverage after selection

Use the existing legal enum: `preferred_for: [portrait]`. General identity and face identity describe intended use in notes; do not introduce them as unrecognized coverage enums. Do not claim upper_body, full_body or back_view completeness for any new Primary. P01 full-body Secondary continues to provide full hair length, pink gradient, body proportions and overall silhouette. A future upper-body request must assess actual combined reference coverage rather than inheriting READY from this Primary.

P01 remains Secondary with outfit/pose/expression do_not_inherit. P03 remains supplemental and its existing source authority is unchanged. None of A/B/C is added to Asset Index or granted generation permission during comparison. Family/group inheritance is recorded in verification.json, and independent source-family increment is zero.

## Protected state

All existing candidate-root files, the current crop, publish manifest, lock and History Draft were hashed before and after generation and are unchanged. All formal character files, variants files, managed assets and published History files were likewise checked unchanged. Complete before/after hashes are in verification.json. No official revision, Fact evidence status, authorization, completion marker or published History was changed. No image-generation tool or remote upload was called.

This report only confirms crop comparison and pixel verification; it does not certify publication readiness or revalidate unrelated staging implementation. Wait for the user's choice of A/B/C before replacing the Primary reference.
