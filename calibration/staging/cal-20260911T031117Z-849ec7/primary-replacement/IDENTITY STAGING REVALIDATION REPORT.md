# IDENTITY STAGING REVALIDATION REPORT

结论：**NOT_READY_FOR_IDENTITY_PUBLICATION**。Primary replacement 已完成；发布门禁未通过。

| 项目 | 结果 |
|---|---|
| 1. Calibration ID | cal-20260911T031117Z-849ec7 |
| 2. New Primary | identity-p01-crop；D:\learn\Arco\calibration\staging\cal-20260911T031117Z-849ec7\candidate-root\assets\arco\identity\p01-face-hair-primary-a.png |
| 3. Crop box / dimensions | [680,0,760,640] / 760×640 |
| 4. SHA-256 | 386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414 |
| 5. Parent | identity-p01；直接 RGBA 对应区域一致 |
| 6. preferred_for | portrait only |
| 7. Secondary | identity-p01 secondary；identity-p03 supplemental；原记录未改 |
| 8. B/C 与旧 crop | 原文件和 comparison records 保留；不进入 manifest |
| 9. Expression leakage | HIGH，用户接受；metadata 默认不继承，现有 Runtime 未落实 |
| 10. portrait coverage | Identity visual: READY；Runtime: READY |
| 11. upper_body coverage | Identity visual: READY；Runtime: PARTIAL |
| 12. full_body coverage | Identity visual: READY；Runtime: PARTIAL |
| 13. back_view coverage | Identity visual: INCOMPLETE；Runtime: PARTIAL |
| 14. Candidate global | PARTIAL；现有 Runtime 错报 READY，作为阻断项 |
| 15. 综合 candidate validator | FAIL；legacy validator 结果见下表 |
| 16–18. Runtime / regression / Skill | 见逐项执行结果 |
| 19. Formal hashes | UNCHANGED；87 protected files |
| 20. Manifest | STAGED_REVALIDATION_FAILED；publication_authorized=false |
| 21. Recommendation | NOT_READY_FOR_IDENTITY_PUBLICATION |

## Test execution

| Test | Status | Duration (s) | Exit |
|---|---|---:|---:|
| identity-staging-validator | PASS | 0.352 | 0 |
| runtime-tests | PASS | 0.247 | 0 |
| regression-tests | PASS | 57.031 | 0 |
| identity-regression-tests | PASS | 0.298 | 0 |
| expression-regression-tests | INCOMPLETE (stopped) | 31.96 | 4294967295 |
| formal-library-validation | PASS | 0.334 | 0 |
| skill-validation | PASS | 0.096 | 0 |

每个测试的 JSON 保存完整 command、cwd、UTC start/end、duration、stdout/stderr 和 600 秒 timeout。未完成不计 PASS。

## Blocking checks

- schema_compatibility_identity-p01: {"schema_version": 2, "roles": ["identity_evidence"], "source_authority": "user_attested_official", "view_angle": null}
- schema_compatibility_identity-p01-crop: {"schema_version": 2, "roles": ["identity_reference"], "source_authority": "user_attested_official", "view_angle": null}
- schema_compatibility_identity-p03: {"schema_version": 2, "roles": ["identity_evidence"], "source_authority": "user_attested_official", "view_angle": null}
- runtime_secondary_support_upper_full: {"portrait": {"status": "READY", "covered_fields": ["eyes", "face", "hair", "identity"], "missing_fields": [], "basis": ["identity-p01-crop"]}, "upper_body": {"status": "PARTIAL", "covered_fields": ["eyes", "face", "hair", "identity"], "missing_fields": ["body.upper", "outfit.upper"], "basis": ["identity-p01-crop"]}, "full_body": {"status": "PARTIAL", "covered_fields": ["eyes", "face", "hair", "identity"], "missing_fields": ["body.full", "body.upper", "footwear", "outfit.lower", "outfit.upper"], "basis": ["identity-p01-crop"]}, "back_view": {"status": "PARTIAL", "covered_fields": ["eyes", "face", "hair", "identity"], "missing_fields": ["body.back", "hair.back", "outfit.back", "view.back"], "basis": ["identity-p01-crop"]}}
- runtime_global_not_above_partial: {"identity": "READY", "variants": {}, "overall": "READY"}
- runtime_expression_outfit_pose_do_not_inherit: {"reference_id": "identity-p01-crop", "source_scope": "managed_arco", "asset_id": "identity-p01-crop", "path": "D:\\arco-offline-published-fixture\\assets\\arco\\identity\\p01-face-hair-primary-a.png", "role": "identity_reference", "authority": "published_asset", "selection_reason": "published_generation_reference", "confidence": "high", "persistent": true, "inherit": [], "do_not_inherit": [], "coverage": {"visible_fields": ["identity", "hair", "eyes", "face"], "view_angles": ["three_quarter_right"], "profiles": ["portrait"]}}
- Test failure/incomplete: expression-regression-tests; see expression-regression-tests.json.

## Coverage interpretation

视觉 inventory 的 upper/full READY 仅指 P01 原图具备相应 Identity 信息，不代表服装继承、Variant 就绪或当前 Selector 能正确选取。Secondary metadata 和 Runtime 均未修改；实际缺失字段如下：

- portrait: selected=['identity-p01-crop']; missing=[]
- upper_body: selected=['identity-p01-crop']; missing=['body.upper', 'outfit.upper']
- full_body: selected=['identity-p01-crop']; missing=['body.full', 'body.upper', 'footwear', 'outfit.lower', 'outfit.upper']
- back_view: selected=['identity-p01-crop']; missing=['body.back', 'hair.back', 'outfit.back', 'view.back']

## Protection and audit

- Candidate Identity 1 / Assets 2；正式 Identity 0 / Assets 1 / Expression 1 / Variant 0；State 与全部正式受保护内容未改（详见 Hash JSON）。
- 14 facts: 10 UNCERTAIN / 4 TODO_CALIBRATION / 0 CANON / 0 VISUAL_CONSENSUS；事实值与状态未改。
- manifest 为 5 个 publication targets（两份 YAML + 三张 Identity PNG），不含旧 crop/B/C。before_hash 未重置；after_hash 均为 null。
- before/ 保存本次 staging 修改前快照；History 仅 Draft，未 finalize；未创建 completion marker。
- 既有 schema/Runtime 问题如实阻断，不以旧浅层 validator PASS 替代发布资格。
- 无远程图片生成、上传、publication 或正式工具修改。
- 工作流采用本地复用、快照、逐项验证与留档；网络调研与全局规则注入不在批准范围。

可复用结论：元数据声明不等于 Runtime 已执行；已有测试 PASS 不等于缺失场景通过；视觉 inventory 与实际选择 coverage 必须分开。

## Final audit / interrupted-suite clarification

- 核心 regression **PASS 26/26**，57.031 秒；Identity tests **PASS 3/3**；既有 Runtime tests **PASS 15/15**。新增 Runtime 验收检查失败，不能由旧测试 PASS 抵消。
- 补充 Expression suite **INCOMPLETE**：fixture 把 `D:/learn` 当作 staging 并复制父目录，因此主动停止其具体测试进程；不是 timeout。停止前 baseline 已 ERROR。没有修复或删除原始 fixture。该中断可能留下本地临时 fixture 文件，不属于正式发布数据。
- 安全单跑 Expression baseline：**FAIL**，0.673 秒；完整 traceback 见 expression-baseline-only.json。相关回归不能整体宣称 PASS。
- Legacy staging validator 的 PASS 是关闭最终失败状态前的浅层检查结果，不证明 schema/Runtime 兼容；最终综合 candidate validator **FAIL**。
- Schema 阻断具体为：现有 candidate schema_version=2 却启用 generation permission（validator 要求 v3）；source_authority=user_attested_official 不在枚举中；三张资产缺 view_angle；crop 的 Asset roles=identity_reference 不在 evidence-role 枚举中。均未擅自修复。
- Primary 视觉复查：脸、下巴、双眼、刘海、头顶/发根完整；保留面旁上段发束，下段/粉色发梢不足交由 Secondary；少量领口与吊带边缘，outfit LOW；张嘴表情 HIGH 已接受。RGBA / alpha 与母图区完全一致。
- 最终再次确认 5 个 manifest candidate hashes 正确、after_hash 均 null、publication_authorized=false；正式 Identity History/completion 未创建；87 个保护文件 Hash 未变。
- 未授权发布的检查只验证本次草案 gate，不宣称现有 publisher 已实现全部安全机制；没有调用 publisher。

## Existing lock guard limitation

原 calibration-lock.yaml 已按快照逐字节恢复，避免本轮额外改变锁协议。现有 lock 的小写 state 不在正式 guard 的大写 ACTIVE 集合中；新失败 manifest 状态同样未被该 guard 支持。这是另一个既有工具兼容阻断，不宣称冲突锁已正确生效；未修改 guard。Manifest 仍 STAGED_REVALIDATION_FAILED / publication_authorized=false。
