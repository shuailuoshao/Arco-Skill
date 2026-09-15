# ARCO CASUAL PIPELINE UPPER-BODY FINAL VALIDATION

Date: 2026-09-15
Execution mode: final validation
Final status: CASUAL_UPPER_BODY_VISUAL_REVIEW_REQUIRED

## 1. Scope and outcome

The frozen formal Arco data was used for one upper_body + casual-outfit reference-conditioned built-in image generation. The generation succeeded. The result is retained only at the built-in generated-images path and is not registered as a managed asset, Character Evidence, Calibration, or library revision.

The image requires user visual review before any PRODUCTION_READY decision. This report is a preliminary technical and visual assessment, not an automatic approval.

## 2. Formal data and frozen state

| Field | Value | Changed |
|---|---:|---|
| Identity revision | 2 | No |
| Asset Index | 5 | No |
| Expression Library revision | 1 | No |
| Variant Index revision | 1 | No |
| Casual Variant revision | 1 | No |
| Selected variant | casual-outfit | No |
| Calibration created | No | No |
| Character Library modified | No | No |
| School Variant started | No | No |

The formal body fact was preserved as body.chest_proportion=small-to-modest. Its evidence status remains the formal existing status; no Evidence Status, Identity, Asset Index, Expression, Variant, or body fact was promoted or rewritten.

## 3. Frozen reference selection

The formal Selector was run once. Its result was frozen and not rerun or rewritten during invocation.

### Reference order

1. identity-p01-crop — identity reference, primary
   - Path: D:\learn\Arco\assets\arco\identity\p01-face-hair-primary-a.png
   - SHA-256: 386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414
   - Inherit: identity, face, hair, eyes
   - Do not inherit: outfit, pose, expression

2. identity-p01 — identity reference, secondary
   - Path: D:\learn\Arco\assets\arco\identity\p01-full.png
   - SHA-256: bddba1d7b1bed2c21572892003ac50dc6c2340d53e8262a56b6db69b16cf1f86
   - Inherit: body_proportions, hair_length, identity
   - Do not inherit: outfit, pose, expression
   - P01 Secondary selection: YES; identity-p01-crop alone does not satisfy upper-body coverage, so the full P01 reference supplies body/silhouette support.

3. casual-outfit-primary — outfit reference, primary
   - Path: D:\learn\Arco\assets\arco\variants\casual-outfit\primary\casual-outfit-primary.png
   - SHA-256: bddba1d7b1bed2c21572892003ac50dc6c2340d53e8262a56b6db69b16cf1f86
   - Inherit: outfit
   - Do not inherit: identity, face, hair, eyes, body_proportions, pose, expression

The Expression PNG was not passed as an input. The requested expr-oblique-gentle-smile-01 is not present in the formal library; the closest approved semantic was used: expr-oblique-cheerful-smile-01 — open eyes, closed mouth, natural smile, moderate intensity.

## 4. Preflight gates

All required gates passed before generation:

- C07/C13/C14 input count: 0
- Evidence-only input count: 0
- Staging path count: 0
- Expression PNG input count: 0
- Body Base input count: 0
- Faceless Composite input count: 0
- Other Variant input count: 0
- scripts/test_reference_runtime.py: 29/29 PASS
- Reference Contract: PASS
- Quality Gate: PASS
- Invocation Plan: PASS
- Formal revisions and protected-file SHA-256 baselines: matched

## 5. Body fact propagation

The formal Compiler propagated body.chest_proportion=small-to-modest into the compiled prompt exactly once. The generated body wording was:

    a slim, lightly built figure with a narrow upper torso and a small-to-modest, understated bust

The soft constraint no exaggerated chest volume appeared exactly once. Forbidden phrase count: 0.

## 6. Compiled prompt

The following complete prompt was passed unchanged to the single generation call:

    a slim, lightly built figure with a narrow upper torso and a small-to-modest, understated bust Reference identity-p01-crop: use to define Arco's identity, including her face, hair and eyes. Do not inherit: expression, outfit, pose. Reference identity-p01: use to define body_proportions, hair_length, identity. Do not inherit: expression, outfit, pose. Reference casual-outfit-primary: use to define outfit. Do not inherit: body_proportions, expression, eyes, face, hair, identity, pose. Arco with her established identity, long pale silver-blue hair fading softly to pink at the ends, characteristic bangs, and red eyes. She wears her established Casual Outfit: a white long-sleeved blouse, a red layered chest decoration, and the black suspender-style high-waist structure. Upper-body half-length composition showing the head, shoulders, chest, and waist, with a small amount below the waist visible; body mostly facing the camera with a slight three-quarter turn. Natural, relaxed posture with no dramatic pose or exaggerated contrapposto, and a gentle natural smile with open eyes and a closed mouth. Simple bright indoor environment used as a neutral validation setting, soft natural daylight. Clean Japanese visual-novel anime character illustration, clean linework, soft cel rendering, clean facial rendering, restrained highlights, coherent hair strands, and simple anime background integration. no exaggerated chest volume

## 7. Frozen invocation and generation

    mode: reference_conditioned
    provider: builtin_image_gen
    capability: reference_conditioned_image_generation
    request_profile: upper_body
    selected_variant_id: casual-outfit
    referenced_image_paths:
      - D:\learn\Arco\assets\arco\identity\p01-face-hair-primary-a.png
      - D:\learn\Arco\assets\arco\identity\p01-full.png
      - D:\learn\Arco\assets\arco\variants\casual-outfit\primary\casual-outfit-primary.png
    generation_calls: 1
    technical_retry: no

Generation result: SUCCESS.

Generated image path:

C:\Users\shuai\.codex\generated_images\01a0a336-104f-7150-b522-5033638d86a2\exec-ae1b74ae-aa7e-433e-9164-baaa7d3e0b77.png

The result was not copied into managed assets, uploaded, or registered as evidence.

## 8. Generated PNG technical record

The generated file was inspected read-only after generation.

| Property | Result |
|---|---|
| Dimensions | 1024 × 1536 |
| Mode | RGBA |
| File size | 2,137,997 bytes |
| SHA-256 | 664fb5fb25bfe0fd8380f42cd2e718e9c0d408d0d304ebc20ef2de4615e4326c |
| Alpha channel | Present |
| Alpha min / max | 0 / 253 |
| Alpha unique values | 254 (0..253) |
| alpha < 255 pixels | 1,572,864 — entire image |
| alpha == 0 pixels | 81,790 |
| Semi-transparent pixels (0 < alpha < 255) | 1,491,074 |
| alpha < 255 bounding region | Whole frame: (0,0)–(1024,1536) in half-open pixel coordinates |
| alpha == 0 bounding region | Whole frame: (0,0)–(1024,1536) in half-open pixel coordinates |
| PNG chunks | IHDR, caBX, IDAT, IEND |

Underlying RGB inspection found 3,402 distinct RGB values among fully transparent pixels. The most frequent fully transparent value was black (0,0,0) with 1,676 pixels. There were 94 semi-transparent pixels with RGB (0,0,0). No fully opaque black pixels were present because the file contains no alpha value of 255.

This alpha state is recorded for user review. No alpha derivative, opaque preview, compositing rewrite, or source PNG modification was performed in this validation.

## 9. Preliminary visual assessment

The generated image was inspected once with the local image viewer. Assessment remains preliminary because the image is still awaiting the required user visual review.

| Check | Preliminary result |
|---|---|
| Torso silhouette | Upper-body framing is present; head, shoulders, chest, waist, and a small amount below the waist are visible. Silhouette reads as slim and coherent. |
| Chest proportion | Appears small-to-modest and restrained, consistent with the propagated working fact. |
| Shoulder / chest / waist relation | Natural-looking relationship in the visible upper-body composition; no obvious geometric distortion. |
| Overcorrection | No obvious overcorrection observed in the preliminary viewer inspection. |
| Blouse | White long-sleeved blouse is present. |
| Red chest detail | Red layered chest decoration is present. |
| Black suspender / high-waist structure | Present and visually readable. |
| WHO consistency | Face, pale silver-blue hair with pink ends, characteristic bangs, and red eyes are retained preliminarily. |
| Expression consistency | Open eyes and a gentle closed-mouth natural smile are present preliminarily. |
| Cross-reference contamination | No obvious identity/outfit cross-contamination observed in the preliminary check. |
| Composition suitability | Suitable as an upper-body validation composition; slight three-quarter turn and relaxed posture are present without dramatic contrapposto. |
| Background | Bright indoor neutral validation setting with soft daylight is present. |

The viewer inspection also makes the transparent/partially transparent edge and corner behavior visible. This is logged as a technical review item, not treated as a reason to regenerate or retouch this result.

## 10. Post-generation integrity checks

The following protected files remained byte-for-byte unchanged after generation:

| File | SHA-256 after generation |
|---|---|
| character/identity.yaml | fe4aa2cf6e471703ea8b70a0310a29f283110d1adb12913652b5a1ba9558a90e |
| character/assets.yaml | b65aec7c614b36e6b68217a37fa4a138a15d108c317cd24a9d5afd6e9483e535 |
| character/expressions.yaml | 0bc3c7ae8e18797c472dc79022d0cd74fe71b04c90d5ec02e571c180b41e7030 |
| variants/index.yaml | e9534a08e2daf609780c0c847771ef04052a58c309e6a104480f412905bb10b0 |
| variants/casual-outfit/variant.yaml | 84746c6dacdf870a2e8ef9dcdd7c496f4764e35ac2924a22b27886caecbe2eea |
| runtime/generation.yaml | 8175783a9edca6f1120b9977501113046cde7e7f6614110be3dbe73a3fb704ca |

No Runtime modification, prompt compiler modification, Character Library modification, Calibration creation, evidence registration, upload, or additional image generation occurred.

## 11. Required next step

The next step is user visual review of the generated image, focusing on:

1. whether the chest proportion is accepted as small-to-modest;
2. whether the transparent/partially transparent edge behavior is acceptable for the intended viewer/output use;
3. whether WHO, Casual Outfit, and expression consistency are accepted;
4. whether the upper-body framing is suitable for the intended validation use.

No new Calibration is required by this execution. No automatic PRODUCTION_READY status is allowed.

## 12. Final status

CASUAL_UPPER_BODY_VISUAL_REVIEW_REQUIRED

