# PRE-PUBLICATION TOOLING REPAIR AND IDENTITY REVALIDATION REPORT

结论：**READY_FOR_IDENTITY_PUBLICATION**。本轮未 publication。

| # | Item | Result |
|---:|---|---|
| 1 | Expression baseline root cause | Published validator compared current evolvable tooling to historical after_hash; formal Expression data itself was valid. |
| 2 | Expression formal baseline | PASS |
| 3 | Supplemental fixture root cause | Old module derived candidate/staging from script parents, producing D:/learn paths and an implicit mixed state. Fixture now explicitly uses the completed Expression transaction and isolated mutation roots. |
| 4 | Runtime coverage root cause | Selector chose only one asset per role and Global readiness tested only Primary existence. |
| 5 | Runtime coverage repair | Profile-aware greedy minimum cover selects Primary first, useful Secondary next, and Supplemental only for a remaining field gap. Global derives all four profile states. |
| 6 | Inheritance root cause | Managed contract hard-coded empty inherit/do_not_inherit arrays. |
| 7 | Inheritance repair | Asset inheritance mapping is normalized into Contract lists, compiled into per-reference instructions, and checked by Quality Gate. |
| 8 | Candidate schema mismatch | Candidate used schema v2 with enabled generation metadata, identity_reference as an evidence role, user_attested_official outside the enum, and missing view_angle. |
| 9 | Schema repair | Candidate Asset Index uses schema v3; structural values normalize to identity_evidence, user_approved and front_three_quarter. Closed nested fields and derived independence are validated. Identity facts/source family/Primary decisions are unchanged. |
| 10 | Lock incompatibility | Lock guard used case-sensitive uppercase states and omitted STAGED_REVALIDATION_FAILED. |
| 11 | Lock repair | State normalization and failed-state blocking added; four read-only/offline operations bypass the lock by contract. |
| 12 | Manifest PNG entries | 3: identity-p01-crop, identity-p01, identity-p03 |
| 13 | portrait | READY — Candidate A |
| 14 | upper_body | READY — Candidate A + P01 |
| 15 | full_body | READY — Candidate A + P01 |
| 16 | back_view | INCOMPLETE |
| 17 | Global readiness | PARTIAL |
| 18 | Reference selection tests | PASS |
| 19 | Inheritance propagation | PASS |
| 20 | Prompt Compiler inheritance | PASS |
| 21 | Supplemental suite | PASS |
| 22 | Existing regressions | PASS |
| 23 | Formal Expression validation | PASS |
| 24 | Formal library validation | PASS |
| 25 | Skill validation | PASS |
| 26 | Protected hashes | UNCHANGED |
| 27 | Candidate revisions | Identity 1 / Assets 2 / Expression 1 / Variant 0 |
| 28 | publication_authorized | false |
| 29 | Remote image call/upload | none |
| 30 | Final recommendation | READY_FOR_IDENTITY_PUBLICATION |

## Test runs

| Suite | Status | Duration (s) |
|---|---|---:|
| formal-expression-baseline | PASS | 1.11 |
| supplemental-expression-suite | PASS | 9.035 |
| identity-staging-validator | PASS | 0.311 |
| identity-staging-tests | PASS | 0.343 |
| runtime-unit-tests | PASS | 0.184 |
| coverage-inheritance-lock-tests | PASS | 0.862 |
| existing-regression-suite | PASS | 81.64 |
| formal-library-validation | PASS | 0.289 |
| skill-validation | PASS | 0.086 |

各 suite 的完整 command、UTC start/end、exit code、stdout/stderr 和 600 秒 timeout 保存在同目录 JSON。

## Protection

- 正式受保护数据文件：50；前置漂移 0，后置漂移 0，新增正式数据文件 0。
- Tooling 变更单独记录为 evolvable_tooling，不是 Identity Calibration target。
- Identity Facts、Evidence Status、source family、Primary/Secondary 人工裁决均保持冻结。
- 未调用 publisher、远程 image generation 或图片上传；未 finalize History，未创建 completion marker。
