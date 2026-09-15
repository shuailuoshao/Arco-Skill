# ARCO POST-SMOKE CLOSURE AND OUTPUT ARTIFACT DIAGNOSIS REPORT

Date: 2026-09-15
Scope: post-smoke closure and read-only output-artifact diagnosis
Final classification: `ALPHA_DISPLAY_ARTIFACT`

## 1. A/B final user verdict

Test: `ARCO BODY PROPORTION A/B LIVE SMOKE TEST`

```text
BODY_PROPORTION_A_B_RESULT: PASS
Identity revision: 2
body.chest_proportion: small-to-modest
Evidence Status: UNCERTAIN
Runtime effectiveness: CONFIRMED
```

User visual adjudication:

- B 图胸部前向体积明显低于 A 图。
- 当前比例符合“偏小至克制”的工作定义。
- 未发现明显过度矫正。
- 躯干轮廓保持自然。
- WHO 保持。
- Casual Outfit 保持。
- Expression 保持。
- 未发现明显 reference contamination。

The A/B result is recorded as a runtime test result only. The A/B images are not Character Evidence and are not managed assets.

## 2. Frozen character data

No character data was changed by this closure.

| Data | Frozen value |
|---|---|
| Identity | 2 |
| Asset Index | 5 |
| Expression | 1 |
| Variant Index | 1 |
| Casual Variant | 1 |
| `body.chest_proportion` | `small-to-modest / UNCERTAIN` |
| Body Proportion calibration effectiveness | `CONFIRMED` |
| A/B images registered as Character Evidence | `NO` |
| A/B image role | `runtime_test_artifact` only |
| New Calibration required | `NO` |

## 3. B image identity

Source:

`C:\Users\shuai\.codex\generated_images\01a0894a-a612-7323-ae81-1f403daf4121\exec-48598bb7-ce13-494a-9d7c-39214f6f6d74.png`

| Property | Result |
|---|---|
| Format | PNG |
| Mode | `RGBA` |
| Dimensions | `1367 × 1151` |
| File bytes | `2,217,874` |
| SHA-256 before/after | `fcb231ed01aa06dc0356d6c414bb445c36af2ebd5adf58d14aadd10f1c3fe3ea` |

## 4. Alpha channel diagnosis

| Metric | Result |
|---|---:|
| Alpha minimum | 0 |
| Alpha maximum | 255 |
| Unique alpha values | 256; every value from 0 through 255 is present |
| Total pixels | 1,573,417 |
| `alpha < 255` | 1,573,395 |
| `alpha == 0` | 57,886 |
| Semi-transparent (`0 < alpha < 255`) | 1,515,509 |
| Fully opaque (`alpha == 255`) | 22 |

Alpha distribution summary:

| Alpha range | Pixel count |
|---|---:|
| 0 | 57,886 |
| 1 | 82,938 |
| 2 | 28,649 |
| 3 | 15,523 |
| 4–63 | 124,493 |
| 64–127 | 36,561 |
| 128–191 | 37,004 |
| 192–239 | 80,707 |
| 240–250 | 122,131 |
| 251 | 133,790 |
| 252 | 648,617 |
| 253 | 205,014 |
| 254 | 82 |
| 255 | 22 |

Bounding regions are inclusive `[x_min, y_min, x_max, y_max]`:

- `alpha < 255`: `[0, 0, 1366, 1150]` — the full image.
- Fully transparent: `[0, 0, 1190, 389]`.
- Semi-transparent: `[0, 0, 1366, 1150]`.

## 5. Transparent-region RGB diagnosis

- All 57,886 fully transparent pixels have underlying RGB exactly `(0, 0, 0)`.
- There are 129,706 exact-black RGB pixels with `alpha < 255`.
- The overwhelming majority of those exact-black pixels have alpha 0–3 and occupy the top/outer-hair region.
- The small high-alpha exact-black subset is confined to `[507, 782, 1044, 1123]`, consistent with real dark outfit/line details rather than the top black display region.
- This is not evidence of a premultiplied-alpha PNG. PNG stores non-premultiplied color samples; RGB values may remain black beneath fully transparent pixels.

## 6. Compositing diagnostic

Each preview is an independent opaque RGB test artifact. The original RGBA file was not overwritten.

| Background | Result | Preview |
|---|---|---|
| White | Top/outer-hair black region disappears; subject and background render normally. | [white composite](<C:\Users\shuai\.codex\visualizations\2026\09\15\01a0a336-104f-7150-b522-5033638d86a2\arco-post-smoke-closure\exec-48598bb7-ce13-494a-9d7c-39214f6f6d74-white-composite.png>) |
| Neutral gray `(128,128,128)` | Top/outer-hair black region disappears; transparent boundary becomes visible as expected. | [gray composite](<C:\Users\shuai\.codex\visualizations\2026\09\15\01a0a336-104f-7150-b522-5033638d86a2\arco-post-smoke-closure\exec-48598bb7-ce13-494a-9d7c-39214f6f6d74-neutral-gray-composite.png>) |
| Checkerboard `(238,238,238)/(64,64,64)`, 32 px cells | Transparency is visible; no large black block remains around the head/hair. | [checkerboard composite](<C:\Users\shuai\.codex\visualizations\2026\09\15\01a0a336-104f-7150-b522-5033638d86a2\arco-post-smoke-closure\exec-48598bb7-ce13-494a-9d7c-39214f6f6d74-checkerboard-composite.png>) |

Preview hashes:

- White: `808fc50ea59673604efa034536c325c85dda2ca45131f12731a6643e8cf141dd`
- Neutral gray: `4f3a3ce37b623735ac5fa5b4d663c2f228ce5509856567f659c8793dff744b67`
- Checkerboard: `089cd98bd1b6b01b799381e9e186df65f4ef591d3b604b01b4ac3fe8ac422934`

## 7. Artifact classification

`ALPHA_DISPLAY_ARTIFACT`

Reason: the apparent black region is carried by transparent or near-transparent pixels whose underlying RGB is black. Explicit white, gray, and checkerboard compositing removes the large black region. The remaining dark pixels are localized image content, not a generated black block.

Viewer behavior is a secondary presentation factor: a viewer or preview surface using black behind transparency exposes the transparent pixels as black. The source PNG itself contains a valid alpha channel.

## 8. Output pipeline diagnosis

| Question | Result |
|---|---|
| RGBA preserved? | Yes. Source PNG is RGBA color type 6. |
| Wrong alpha handling proven? | No. No premultiplied-alpha or local alpha-flattening evidence. |
| Local output pipeline implicated? | No. Repository contains runtime capability/configuration, but no local PNG post-processing path that touched this file. |
| Extra PNG processing observed? | C2PA provenance metadata is present in a `caBX` chunk, including created/converted/watermarked actions; this does not prove pixel compositing or alpha damage. |
| Generation model implicated as a visible RGB artifact? | No. The black region disappears under correct compositing and is tied to transparency. |
| Viewer implicated? | Yes, as a display/compositing factor only; not the primary artifact classification. |

## 9. Integrity and scope verification

The original B PNG remained byte-for-byte unchanged:

- SHA-256 before: `fcb231ed01aa06dc0356d6c414bb445c36af2ebd5adf58d14aadd10f1c3fe3ea`
- SHA-256 after: `fcb231ed01aa06dc0356d6c414bb445c36af2ebd5adf58d14aadd10f1c3fe3ea`
- Bytes before/after: `2,217,874`

The following protected files were not modified:

- `character/identity.yaml`: `FE4AA2CF6E471703EA8B70A0310A29F283110D1ADB12913652B5A1BA9558A90E`
- `character/assets.yaml`: `B65AEC7C614B36E6B68217A37FA4A138A15D108C317CD24A9D5AFD6E9483E535`
- `character/expressions.yaml`: `0BC3C7AE8E18797C472DC79022D0CD74FE71B04C90D5EC02E571C180B41E7030`
- `variants/index.yaml`: `E9534A08E2DAF609780C0C847771EF04052A58C309E6A104480F412905BB10B0`
- `variants/casual-outfit/variant.yaml`: `84746C6DACDF870A2E8EF9DCDD7C496F4764E35AC2924A22B27886CAECBE2EEA`
- `runtime/generation.yaml`: `8175783A9EDCA6F1120B9977501113046CDE7E7F6614110BE3DBE73A3FB704CA`

No Calibration, Character Evidence registration, managed asset registration, upload, prompt change, Runtime change, or new generation was performed.

## 10. Recommended next validation

For future viewing, retain the original RGBA output and create an opaque preview derivative only for display. Do not change the generation prompt or start a new Calibration.

If a future opaque-background validation is desired, run it as a separate generation-quality validation using the same formal character data and explicitly request a complete opaque background. That is not required for this closure.
