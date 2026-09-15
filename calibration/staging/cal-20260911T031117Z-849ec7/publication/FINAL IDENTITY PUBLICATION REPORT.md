# FINAL IDENTITY PUBLICATION REPORT

| # | Item | Result |
|---:|---|---|
| 1 | Calibration ID | cal-20260911T031117Z-849ec7 |
| 2 | Publication state | COMPLETE |
| 3 | Preflight | PASS |
| 4 | STALE_STAGING | No |
| 5 | Identity final revision | 1 |
| 6 | Assets final revision | 2 |
| 7 | Expression final revision | 1 |
| 8 | Variant final revision | 0 |
| 9 | Identity Facts | 14 |
| 10 | UNCERTAIN | 10 |
| 11 | TODO_CALIBRATION | 4 |
| 12 | CANON | 0 |
| 13 | VISUAL_CONSENSUS | 0 |
| 14 | Primary | identity-p01-crop |
| 15 | Primary SHA-256 | 386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414 |
| 16 | Parent / crop | identity-p01 / [680,0,760,640] / 760×640 / evidence_independence none |
| 17 | Secondary | P01 secondary; P03 supplemental |
| 18 | Generation permission | Three approved Identity references only |
| 19 | Evidence-only prohibition | Expression / Body Base / Faceless denied |
| 20 | portrait | READY |
| 21 | upper_body | READY |
| 22 | full_body | READY |
| 23 | back_view | INCOMPLETE |
| 24 | Global | PARTIAL |
| 25 | Expression baseline | PASS |
| 26 | Runtime tests | PASS 15/15 |
| 27 | Coverage/inheritance | PASS 9/9 |
| 28 | Regression | PASS 26/26 |
| 29 | Formal library | PASS |
| 30 | Skill validation | PASS |
| 31 | Protected Hash verification | PASS; only approved changes |
| 32 | History | D:\learn\Arco\calibration\history\cal-20260911T031117Z-849ec7.yaml |
| 33 | Completion marker | Exists |
| 34 | In-progress marker | Cleared |
| 35 | Actual recovery/rollback | None; 5 isolated injected failures recovered |
| 36 | Remote image generation | None |
| 37 | Remote upload | None |
| 38 | Recommendation | IDENTITY_PUBLICATION_COMPLETE; stopped |

实际 payload：6 files（3 PNG + 2 YAML + 1 Markdown）；加 History 与 completion 为8项正式产物。

## After hashes

- character/identity.yaml: `beffb1b0c1479891fa292e69dbd6682cba434996a7ab1030c8ef8d4dee6d3507`
- character/assets.yaml: `5fc9b027de91a92fb12a5c340955066f5ff457090b05d437b9a75038c048e32b`
- assets/arco/identity/p01-full.png: `bddba1d7b1bed2c21572892003ac50dc6c2340d53e8262a56b6db69b16cf1f86`
- assets/arco/identity/p01-face-hair-primary-a.png: `386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414`
- assets/arco/identity/p03-alternate.png: `0056f16ff4468a0e26505b521a2fcd8f13a032ddb10e468c22c06c433a38206d`
- character/identity.md: `9fd5238102dbfab7ae608604f91b00210c52f0a9892522d883ab7f7e07136b25`

完整测试命令、stdout/stderr、开始/结束时间及耗时见 publication/final-tests。旧 History 未改变；8项已接受 Expression pending-locator warnings 继续保留。
