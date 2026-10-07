# 服装准备、试穿与整套发布

入口为 `scripts/outfit_preparation.py`，独立身份前置入口为 `scripts/identity_preparation.py`。普通生产仍选择一个已发布 `variant_id`，保持常服、校服、泳装的现有图片和用法。第一版接受图片加文字补充，使用现有内置生图适配器。

## 操作顺序与完成条件

1. **只读分析素材。** 查看每张原图，记录可见部件、取用区域、视角、遮挡、来源、已有 Variant 版本、冲突和缺口。只看到局部也可开始。商品图和其他人物图只提供指定衣服部件，排除原人物身份、发型、表情、姿势、画风、背景和未选配件。完成条件：所有取用部件都有来源和区域，所有关键缺口都有具体描述。
2. **提出完整设计。** 通常给两套完整方案，各自明确上衣、下装、鞋、袜、饰物、外套和穿法；不穿的部件写明省略。文字要求落实到对应设计约束。混搭先保留原款并用塞衣角、覆盖等穿法衔接；改长度、结构、配色属于显式 `redesign` 选项。完成条件：用户能选择整套方案，关键缺口和冲突均有具体解法。
3. **补齐身份前置。** 调用 `plan_outfit_preparation()`。返回 `IDENTITY_CALIBRATION_REQUIRED` 时，展示独立、全局复用的 `Identity Change`，用 `plan_identity_calibration()` 规划背面头发与身体构造。确认其具体提示词和图片后创建独立准备记录、生成、检查，再确认身份发布预览并发布。完成条件：正式资产能独立覆盖背面身份、`hair.back`、`body.back`；正面图不能代替这些覆盖。
4. **确认设计与主图计划（节点一）。** 重新规划至 READY，展示实际输入图片、每个取用范围、完整设计和最终提示词。可信会话调用方保存实际用户确认，再调用 `create_preparation()`。确认之前仅做只读规划。通过 `run_candidate(view_id="front")` 生成正面全身无五官主图；已有合格阿尔可穿着图可经明确 `existing_primary_source_id` 和 `adopt_primary()` 直接进入检查。完成条件：主图候选已保留，原尺寸视觉检查有记录。
5. **认可主图并确认其余视图（节点二）。** 主图五项检查 PASS 后，`plan_remaining_views()` 提供右斜侧、背面及必要细节图的实际输入和提示词，一次展示并确认整个批次。`approve_main_and_views()` 锁定主图。各视图分别取用锁定主图、相应正式身份基准和相关原始素材；未认可的斜侧图不会成为背面依据。完成条件：所需视图全部产生并逐张检查。
6. **检查整包并确认发布（节点三）。** `plan_reference_pack()` 展示实际所选版本，查看全部原尺寸图片并用 `record_pack_review()` 保存跨视图对照。随后 `plan_publication()` 展示完整参考包、设计、来源、文件、实体修订和 History 草案。用户认可这一具体预览后 `stage_publication()`，再 `publish_preparation()`。完成条件：候选及正式结构校验 PASS，正式 History 和 `.complete` 同时存在，事务为 COMPLETE。

视觉检查分别为 `identity`、`parts`、`wearing_occlusion`、`cross_view`、`image_quality`，每项保存 PASS / FAIL / UNVERIFIED 和具体证据。统一阿尔可基准画风、清晰背景、正面/右斜侧/背面全身无五官穿着图；头发等遮住关键结构时，用设计的 `detail_requirements` 增补服装细节图。程序只验证记录与哈希，文件存在、关键词出现、检查 PASS 均不能替代真人验收。

## 请求与设计合同

Python 示例和受控替身可参考 `scripts/test_outfit_preparation.py`；下面字段都由看过实际图片的调用方填写，不由程序猜图。

| 字段 | 内容 |
|---|---|
| `name`, `variant_id` | 新套装名称与新稳定 ID；第一版不覆盖旧套装 |
| `sources` | 每张素材的 `source_id`、`path` 或正式 `asset_id`、kind、view、occlusions、source_note、parts |
| `sources[].parts[]` | `part_id`、slot、observations、原 `evidence_status`、region |
| `region` | whole；或归一化 `box` + `xyxy`。已处理/裁剪图保留原图和处理链 |
| `combination` | slot 到所选 `{source_id, part_id}` 的列表；必须与选定设计相同 |
| `gaps`, `conflicts` | 关键缺口/冲突 ID 与说明；设计以 `gap_resolutions` / `conflict_resolutions` 逐项回答 |
| `designs`, `selected_design_id` | 完整方案与所选方案；未选择时返回 NEEDS_DESIGN_SELECTION |
| `text_supplements` | 文字补充原文；将实际要求落实到方案的固定特征或改款决定 |
| `identity_assets` | 可选，按 front / right-three-quarter / back 明确选择正式身份参考 |
| `view_sources` | 可选，逐视图明确素材 ID；总输入最多五张，超出时回到只读选图规划 |
| `existing_primary_source_id` | 可选，直接验收明确的 arco_worn / published_variant 主图 |

`design_definition` 为 schema 1，`parts` 完整包含 `upper / lower / footwear / hosiery / accessories / outerwear`。每项有 description、origin、source_bindings、fixed_features。origin 为 source、completion、redesign 或 omitted；补全和改款还需 decision_reason。`wearing_relations` 与 `fixed_constraints` 非空；`detail_requirements` 为 `{view_id: detail-*, description, source_ids}` 列表。

原图可见事实保存在 `source_materials[].parts`，用户认可的新设计保存在 `design_definition` 和 `approval_context`。补全成为固定设计约束，原证据状态继续保留。新 Variant 不把这些决定自动转换为硬 Fact，正式生成通过 `compile_design()` 显式使用设计。

处理过的素材提供 `original_path` 与 `processing_records`（operation、input_sha256、output_sha256 的连续链），保留原图、处理结果和同源关系。裁剪、补全、试穿及派生视图都不增加独立证据数量。改变处理结果、素材或设计后重新确认节点一。

## 冻结、修正与续办

确认结构为 `{user_confirmed: true, preview_sha256: <实际预览哈希>, user_message: <实际用户消息>}`。预览绑定实际图片、区域/分析、完整设计、提示词、资料版本和文件哈希。此结构只核验绑定；可信会话负责确认来自真人，不能由代理代填授权。

准备记录位于 `calibration/preparations/<preparation-id>/preparation.yaml`，包含原图副本、全部候选版本、计划、检查、调用预约和确认；旧计划、确认与检查保留在历史记录中。`resume_preparation()` 保留已完成工作，将中断的预约记为 INTERRUPTED；该调用仍占次数。`run_candidate(..., repair=True)` 每次只恢复原目标，最多两次，失败调用也计数；修正耗尽时向用户展示已保留版本和具体偏差。用户要求新目标时 `revise_preparation()` 重新确认；如用户明确要求同目标的新一轮尝试，可在新请求中记录 `manual_restart` 说明并重新确认节点一。

主图替换会使旧依赖视图和整包对照失效。相同图片的新版本保留独立记录；新主图认可后重新规划节点二。每个修正候选仍需原尺寸检查。普通生成不读取准备记录或候选路径。

用户指出背面候选的膝部朝向错误时，同视图局部修正可用 `run_candidate(..., repair=True, repair_target_candidate_id=<候选 ID>, correction_code="back-knee-orientation", user_repair_message=<实际用户消息>)`。只接受当前获确认目标下该视图最新且检查 FAIL 的候选；它仅作为编辑目标，正式身份参考仍提供身份权威，不能转作其他视图的设计或身份依据。修正指令使用固定的背面膝部模板，不把检查 prose 或用户消息编译成新设计。实际输入仍限五张，不静默丢弃素材；调用保留修正次数、目标哈希、原版本及全部输入追溯，仍受最多两次自动修正限制。新图需重新检查及用户验收。

真实生成仅走 `ArcoRealAdapter.generate_preparation()`；身份路径为 `generate_identity_calibration()`。`run_candidate()` 先落盘预约，再调用适配器。提供绑定继续采用 `builtin_image_gen(prompt=..., referenced_image_paths=...)`，无需额外模型或服务。服装准备总输入限五张，可将同一正式图片的身份与指定服装区域合并为一个输入。

## 发布与恢复

节点三之后才创建 `calibration/staging/<calibration-id>/`，复用 `publication_v3.py` 的防漂移、备份、逐文件哈希、回滚、History 和完成标记机制。正式主图和辅助视图属于新 Variant；`derived_from_asset_ids` / `derivation_sources` 追溯所有实际输入、部件区域、其他套装版本和生成记录，`evidence_independence: none` 排除派生图的独立投票。

发布中断时调用 `recover_publication()`，只恢复已知哈希，保留原快照，再以同一已确认包重试 `publish_preparation()`。未知并发内容保持原样并报告冲突；需要改发布内容时回到预览确认。发布完但准备记录尚未落盘的中断也可通过 recovery 补记完成。

staging 建立或校验中断也使用 `recover_publication()` 续办。已暂存但尚未写入正式库的方案，可以在节点一确认新设计后由 `revise_preparation()` 退役旧 staging；旧文件保留，新方案取得新 Calibration ID。发生过正式写入时先恢复旧快照，再修改设计。新获批设计只有在 History 和 `.complete` 均匹配实体修订后才可成为普通生成或组合素材的依据。

CLI 示例：

```powershell
python scripts/outfit_preparation.py plan --input request.json
python scripts/outfit_preparation.py create --input preview.json --confirmation confirmation.json
python scripts/outfit_preparation.py status --preparation-id <id>
python scripts/outfit_preparation.py plan-views --preparation-id <id> --candidate-id <main-id>
python scripts/outfit_preparation.py plan-pack --preparation-id <id>
python scripts/outfit_preparation.py plan-publication --preparation-id <id>
python scripts/outfit_preparation.py stage --input publication-preview.json --confirmation confirmation.json
python scripts/outfit_preparation.py publish --preparation-id <id>
python scripts/outfit_preparation.py recover --preparation-id <id>
```

CLI 提供规划、检查记录、确认和发布接口；生成由宿主注入当前内置生图 callable 后调用 Python API。不要把测试替身绑定成真实提供方。受控测试验证流程和合同，真实服装质量最终通过用户确认后的实际试穿验收。

流程参考：[DashTailor](https://github.com/dashtoon/dashtailor-workflow) 的服装迁移/画风修正，[MMTryon](https://arxiv.org/html/2405.00448) 的多部件来源与穿法绑定，以及 [商品图迁移视角和配件污染案例](https://myaiforce.com/krea2-outfit-transfer/)。这里采用其流程经验，生成能力仍使用当前内置适配器。
