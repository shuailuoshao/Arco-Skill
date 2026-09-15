# STAGING VALIDATION REPORT

- Calibration ID: `cal-20260910T145805Z-61c3e9`
- Staging path: `D:\learn\Arco\calibration\staging\cal-20260910T145805Z-61c3e9`
- Validator: **PASS**
- Publication state: `STAGED_VALIDATED_AWAITING_AUTHORIZATION`
- Publication authorized/performed: **NO / NO**

## Validation summary

| Check | Result |
|---|---|
| Asset copies | 43 expected / 43 actual / PASS |
| SHA-256 | 43 complete; all source-copy pairs match |
| Asset → Semantic | 43 → 42 / PASS |
| Approved semantics | 42 |
| Face Slots | 2 / PASS |
| Expression Sets | 2 / PASS |
| CONFIRMED Clusters | 8 / PASS |
| Similarity Groups | 21 / PASS |
| Composite compatibility | 0 materialized; 4 pending evidence |
| Frontal pose compatibility | PROVISIONAL |
| Identity revision | 0, unchanged |
| Variant/State revisions | unchanged |
| Candidate revisions | expression_library 0→1; asset_index 0→1 |
| New tests | 9/9 PASS |
| Existing regression | 22/22 PASS |
| Skill validation | PASS |
| Formal read-only validation with staging present | PASS |

## Duplicate official assets

- Assets: `arco-expr-frontal-011`, `arco-expr-frontal-016`
- Shared Semantic: `expr-frontal-neutral-serious-01`
- Identical SHA-256: `9fc37446350ddc2b9fa118bdb80c715134f6ebc1e343f5a33632e1f141bbf0bc`
- Both managed files and provenance records are retained.

## Warnings

- a_l_5797 faceless_composite: UNREGISTERED target locator is outside the current publication unit; no formal Asset reference was created
- a_l_5797 full_composite: UNREGISTERED target locator is outside the current publication unit; no formal Asset reference was created
- a_l_5799 faceless_composite: UNREGISTERED target locator is outside the current publication unit; no formal Asset reference was created
- a_l_5799 full_composite: UNREGISTERED target locator is outside the current publication unit; no formal Asset reference was created
- a_l_5811 faceless_composite: UNREGISTERED target locator is outside the current publication unit; no formal Asset reference was created
- a_l_5811 full_composite: UNREGISTERED target locator is outside the current publication unit; no formal Asset reference was created
- a_l_5802 faceless_composite: UNREGISTERED target locator is outside the current publication unit; no formal Asset reference was created
- a_l_5802 full_composite: UNREGISTERED target locator is outside the current publication unit; no formal Asset reference was created

These eight locator warnings are deliberate: the composite images are outside this publication unit. Their proposed IDs are not validated or stored as formal Asset references.

## Managed assets and SHA-256

| Asset ID | Semantic ID | Source file | SHA-256 |
|---|---|---|---|
| `arco-expr-oblique-001` | `expr-oblique-proud-confident-01` | `アルコ_a_l_5793.png` | `d03ebd27ea08ba3dd22e4f1b6885a7437d50f9b802ac97523eb8e5720002532b` |
| `arco-expr-oblique-002` | `expr-oblique-neutral-serious-01` | `アルコ_a_l_5794.png` | `d0c4a0bef6f260aca4ae9312a6ad9929d2e2c5447d0bdc4f6b75a8d4cac5a398` |
| `arco-expr-oblique-003` | `expr-oblique-closed-neutral-01` | `アルコ_a_l_5795.png` | `0425d957385cf790598b992ef085837a73c18ee438f0117d8ba87f51f5166fc1` |
| `arco-expr-oblique-004` | `expr-oblique-cheerful-smile-01` | `アルコ_a_l_5796.png` | `6cde93f0af3fb9aa82c3cec8273e18e69e6d735563ca6bf6029fe6fed48770db` |
| `arco-expr-oblique-005` | `expr-oblique-cheerful-laugh-01` | `アルコ_a_l_5797.png` | `282ba8b4b97d2af28eef0fc8b68c114af8fa7fea73f392911019966fc28e5b58` |
| `arco-expr-oblique-006` | `expr-oblique-closed-eye-smile-01` | `アルコ_a_l_5798.png` | `72357eb15a2f9736932eb5a4329fabafb5b14f52a48356977ecf8cf37c45cacf` |
| `arco-expr-oblique-007` | `expr-oblique-closed-eye-laugh-01` | `アルコ_a_l_5799.png` | `cd5bc627f3a11b6e076c501b1a46690a80c4267b0f9955bcb31eb194990598cf` |
| `arco-expr-oblique-008` | `expr-oblique-concerned-01` | `アルコ_a_l_5800.png` | `dd7ad32900de00b18dc420752a654507285b1dd9592468f2613673470184f01a` |
| `arco-expr-oblique-009` | `expr-oblique-angry-complaint-01` | `アルコ_a_l_5801.png` | `3dd10fc5e8e21ac4b01c3915efb448b5bee5cae27a9e13c5bba83e32ffca754a` |
| `arco-expr-oblique-010` | `expr-oblique-closed-eye-displeased-01` | `アルコ_a_l_5802.png` | `e917a36cc6d0ec0370479877baa355eab3cd182bb55d2b84d625e7a7ca04d55c` |
| `arco-expr-oblique-011` | `expr-oblique-angry-eyes-closed-01` | `アルコ_a_l_5803.png` | `f9fd789dd0695ef10f9d49d87c5f782f9bfea93123a0c29c470374db2edd5c94` |
| `arco-expr-oblique-012` | `expr-oblique-displeased-01` | `アルコ_a_l_5804.png` | `3b5bb564842fe81b38f7aa93f04b2df22e3e5fc017a9474f641773edde90bf30` |
| `arco-expr-oblique-013` | `expr-oblique-concerned-questioning-01` | `アルコ_a_l_5805.png` | `a67145fc6a207df371e37e34e0de031ff897ec665f21fe4875a88b7a69bd3efe` |
| `arco-expr-oblique-014` | `expr-oblique-closed-eye-weary-01` | `アルコ_a_l_5806.png` | `e172ec7ad9ac2d3cd0363fd6565533944c83a8d9553e3e2c46dae90cf3a2fa06` |
| `arco-expr-oblique-015` | `expr-oblique-resigned-drained-01` | `アルコ_a_l_5807.png` | `fd70abae2e6a3d4ca8e600287913afefd7b52e013bd7ceaab3d57756212eced3` |
| `arco-expr-oblique-016` | `expr-oblique-obvious-surprise-01` | `アルコ_a_l_5808.png` | `dbad2a2a95ce9c8098c6e041612a6765a645ff59496a5c39bf489677a2f2b637` |
| `arco-expr-oblique-017` | `expr-oblique-gentle-smile-01` | `アルコ_a_l_5809.png` | `62f8c93d9a4a53940ab0d5c92b3bb130af78b95aeae6848ab0445cb28553e9cd` |
| `arco-expr-oblique-018` | `expr-oblique-cold-displeased-01` | `アルコ_a_l_5810.png` | `da7fe1c1dd23514a839f1f21bfa76adc5082954d1625d52185123eeb2c2ffcbe` |
| `arco-expr-oblique-019` | `expr-oblique-reproachful-resigned-01` | `アルコ_a_l_5811.png` | `9cc2aa31d4498eaf8437c2f81594f190517b984f702d636719bfbb5d8fade16b` |
| `arco-expr-oblique-020` | `expr-oblique-low-gaze-contemplation-01` | `アルコ_a_l_5812.png` | `3923ec69c898ec60da4859cb1a34c16f473f3dcfde0132776db9cd1bee722fcf` |
| `arco-expr-oblique-021` | `expr-oblique-dejected-complaint-01` | `アルコ_a_l_5813.png` | `c955932bf4c47a09a8cf22e3b0b4b4d5e1eee305e2862ad292c2ca4167c24bcf` |
| `arco-expr-frontal-001` | `expr-frontal-attentive-neutral-01` | `アルコ_b_l_7830.png` | `386cea17af789627dd06070002fd02261025ad5447e0c451f194bb401080d240` |
| `arco-expr-frontal-002` | `expr-frontal-closed-neutral-01` | `アルコ_b_l_7865.png` | `c9ec738943c2a535e277d86569397f4207658dec1dd1a4b3476c87de1e345c1c` |
| `arco-expr-frontal-003` | `expr-frontal-cheerful-smile-01` | `アルコ_b_l_7914.png` | `827a18fd067fe4844c0f7cf45dd51b3ccb18a8ebcbd3a6132b038858bb1f2e1c` |
| `arco-expr-frontal-004` | `expr-frontal-excited-shout-01` | `アルコ_b_l_7963.png` | `82b7eb2e3da5b6053676633c766057e56a587778170a503dd217bc3f4212c649` |
| `arco-expr-frontal-005` | `expr-frontal-closed-eye-smile-01` | `アルコ_b_l_7998.png` | `b1dd2a686220170fa0b30971797f3a0f36dd5c108d2ab2c2c530b360937da3f3` |
| `arco-expr-frontal-006` | `expr-frontal-closed-eye-laugh-01` | `アルコ_b_l_8033.png` | `4abad161afc32fd2cf021f5425172165ac80f8e620064b3c6cd9aaaf7c59b40b` |
| `arco-expr-frontal-007` | `expr-frontal-concerned-01` | `アルコ_b_l_8082.png` | `5d371637d020129bb1b606d6ae691a546874501b2c5047e74be4743a9b96963a` |
| `arco-expr-frontal-008` | `expr-frontal-frightened-exclamation-01` | `アルコ_b_l_8131.png` | `6921335c51c30d5dabf20f6e36612395af690e690841862bb17ea42e28186774` |
| `arco-expr-frontal-009` | `expr-frontal-difficult-deliberation-01` | `アルコ_b_l_8166.png` | `b9a8d36116dd85207a275840eb3bc3c7a56c2987a2e7020dd401ab0004c514ce` |
| `arco-expr-frontal-010` | `expr-frontal-resigned-deliberative-speech-01` | `アルコ_b_l_8201.png` | `2664839ae5ddd668cc34b8a85ddd9557510c97aea169f3f5603fa5e4d70842f4` |
| `arco-expr-frontal-011` | `expr-frontal-neutral-serious-01` | `アルコ_b_l_8250.png` | `9fc37446350ddc2b9fa118bdb80c715134f6ebc1e343f5a33632e1f141bbf0bc` |
| `arco-expr-frontal-012` | `expr-frontal-surprised-saddened-01` | `アルコ_b_l_8299.png` | `40851a46b362f8b3ef01ec1c18e4d428119409d36e7fdd484a5cd902babcc0b6` |
| `arco-expr-frontal-013` | `expr-frontal-eyes-closed-composed-01` | `アルコ_b_l_8334.png` | `2c7f054e717dba98511742b20047ccda6d3460b3c82c5bf37111d5d103aab1a1` |
| `arco-expr-frontal-014` | `expr-frontal-eyes-closed-sigh-01` | `アルコ_b_l_8369.png` | `61b7504125b13a7fad6bbf1d43fcdab9472a9b08175798a20f0802bb21baa81c` |
| `arco-expr-frontal-015` | `expr-frontal-obvious-surprise-01` | `アルコ_b_l_8418.png` | `98d2f4e2979157e4f3fda372e8f7d21a59dd3c1ebaa60f25dd78275f352022d0` |
| `arco-expr-frontal-016` | `expr-frontal-neutral-serious-01` | `アルコ_b_l_8467.png` | `9fc37446350ddc2b9fa118bdb80c715134f6ebc1e343f5a33632e1f141bbf0bc` |
| `arco-expr-frontal-017` | `expr-frontal-excited-toothy-grin-01` | `アルコ_b_l_8516.png` | `765d3944e47fddd8653d26be4f2078e90c0bf93be0d8139c4032fd46caa116e1` |
| `arco-expr-frontal-018` | `expr-frontal-extreme-excited-toothy-grin-01` | `アルコ_b_l_8551.png` | `a827d4bf789b1c22d08c8b853db909675f562ea6195744789cb85a12452dbbbc` |
| `arco-expr-frontal-019` | `expr-frontal-displeased-01` | `アルコ_b_l_8600.png` | `f908928f438185fa99a202d9629164e78eea7ae6ac35f0d1ab8bb7ed8d584d38` |
| `arco-expr-frontal-020` | `expr-frontal-impatient-speaking-01` | `アルコ_b_l_8649.png` | `860e6405b0c628c9796202d4d1f2d0a922f21cf49657749801ccb6aef2286c47` |
| `arco-expr-frontal-021` | `expr-frontal-attentive-speaking-01` | `アルコ_b_l_8709.png` | `8a68a121e14eda387d0165772a9ef51404588e95d1ce7d5f647c4f328b2c8f83` |
| `arco-expr-frontal-022` | `expr-frontal-casual-speaking-01` | `アルコ_b_l_8769.png` | `06abd18bcddd7ca2e0f88e094af949e80ce50d32d3f5c5c8818004f199ce8549` |

## Pending publication files

- `SKILL.md`
- `assets/templates/asset.yaml`
- `character/assets.yaml`
- `character/expressions.yaml`
- `references/calibration/schema.md`
- `references/calibration/workflow.md`
- `references/calibration/expression-schema.md`
- `references/core/prompt-compiler.md`
- `references/core/reference-routing.md`
- `references/core/expression-compiler.md`
- `scripts/validate_library.py`
- `scripts/test_validate_library.py`
- `scripts/validate_expression_staging.py`
- `scripts/test_validate_expression_staging.py`
- `scripts/check_calibration_lock.py`
- `assets/arco/expressions/oblique/arco-expr-oblique-001.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-002.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-003.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-004.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-005.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-006.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-007.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-008.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-009.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-010.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-011.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-012.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-013.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-014.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-015.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-016.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-017.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-018.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-019.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-020.png`
- `assets/arco/expressions/oblique/arco-expr-oblique-021.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-001.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-002.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-003.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-004.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-005.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-006.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-007.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-008.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-009.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-010.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-011.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-012.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-013.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-014.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-015.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-016.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-017.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-018.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-019.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-020.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-021.png`
- `assets/arco/expressions/frontal/arco-expr-frontal-022.png`

## Publish manifest draft

- Transaction ID: `tx-expression-library-20260910T145805Z-61c3e9`
- Base revisions: `{'expression_library_revision': 0, 'asset_index_revision': 0, 'identity_revision': 0}`
- Base/protected hashes: 13
- Candidate files: 58
- Every `after_hash` is null and every publication status is pending.
- Preflight must recheck every base hash; drift produces `STALE_STAGING`.
- Mid-transaction failure produces `RECOVERY_REQUIRED`.

## Stop confirmation

- No formal file, revision, History record, completion marker, or published Asset was changed.
- Execution stopped after staging and validation.
- Awaiting: `确认发布 Expression Library`.
