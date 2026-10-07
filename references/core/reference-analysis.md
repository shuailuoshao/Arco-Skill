# 分离参考、确认与视觉验收

## 每次生成的步骤

1. 查看用户参考、正式着装无五官身份图、指定服装图和候选表情 PNG。表情图是透明眉眼嘴图层，必须结合无五官图判断阿尔可的脸型、发型与五官关系。依据目标表情和视角选择最接近的库图；库图用于辨识度，目标表情来自外部参考。Body Base 仅保留为本地证据，不调用看图工具展示，不加入参考预览或生图输入。
2. 在 `reference_analysis` 中记录实际观察、来源、目标和调整。保持五官关系、刘海结构、固有颜色、身体比例和指定服装；镜头、姿势、表情、线条、阴影、高光及材质跟随外部目标。光照可以改变表观颜色，不能换掉固有发色或瞳色。
3. 调用 `plan_production_generation(request)` 得到只读计划。展示实际所选图片、来源、构图、眉眼嘴关系、明暗组织、与表情库的差异及最终提示词。关键疑点先进入 Reviewer。
4. 等用户明确确认这个具体预览后，由可信会话调用方填写 `analysis_confirmation`，再调用 `run_production_generation()`。实现计划的授权、旧轮次确认或代理自己的描述均不能代替本次确认。代码验证绑定关系，不能独立证明确认来自真人。
5. 查看原尺寸成图，与角色图和外部参考逐项比较，用 `with_reference_review()` 记录检查。文件存在、适配器通过或提示词包含关键词，都不代表画面通过。
6. 有明确未达标项目时可调用一次 `run_automatic_reference_repair()`，只恢复已确认目标。身份失败从原始参考重建；其他表现偏差沿用修订桥接。改变目标或参考组合时重新确认。
7. 修正后再检查，报告成图及具体偏差；代理自评不等于用户验收。结果字段和 `output/.reference-repairs/` 独占预约记录共同限制修正次数；失败调用也不能无限重试。

## Reference Analysis v1

顶层 `schema_version: 1`；`sources` 精确列出所选原始参考 ID，不含修订成图。每个维度包含非空的 `source_reference_ids`、`observations` 和 `transfer_target`：

| 维度 | 必须记录的可见关系 |
|---|---|
| identity | face_structure、hair_structure、body_proportions、outfit |
| composition | framing、camera、subject_position、negative_space |
| pose | body_direction、limb_relationships、occlusion |
| expression | brows、eyelids、gaze、mouth |
| lighting | light_regions、shadow_regions、shadow_edges、cast_shadows、highlights |

不可见内容写明“不可见”；推断写明依据，不虚构精确尺寸、角度或光源。表情描述眉毛内外端、眼睑开合、视线及嘴形的关系；光影记录亮暗区域、阴影边界、投影与高光组织。

`expression.library_asset_id` 指定正式表情 PNG；`expression.library_adjustments` 说明与目标表情的差异，完全匹配时写无需调整。`style.context_sha256` 使用 `reference_analysis.digest()` 对同组参考的最终 `ResolvedStyleContext` 求哈希；画风描述复用 Style Brief。

`allowed_adjustments` 是调整列表；`uncertainties` 是关键疑点列表，未解决时拒绝冻结。Identity 来源必须包含所选着装身份图、无五官服装图和五官图层，且不含外部人物。

## 选图规则

按表情 PNG 的库内视角选择相容着装身份图和服装图。`front` 与 `frontal` 等价；不擅自镜像或把正面图作为背面证据。`arco_references` 可显式指定同职责正式着装资产。

- portrait / upper_body / full_body：着装身份图 + 指定服装图 + 表情图。身份与服装使用同一资产时只输入一次，共两张角色参考。
- 默认 `body_reference_mode: clothed_only`。生产入口为省略该字段的请求填入模式与原因，不逐次询问用户；显式指定此模式时仍需非空 `body_reference_reason`。`body_base` 模式、Body Base 资产及其同图副本在调用工具前拒绝。
- 自动身份图：斜侧 `three_quarter_right` 使用 `casual-outfit-open-arms-no-horns-evidence`；正面 `front` / `frontal` 使用 `casual-outfit-crossed-arms-evidence`。继承可见发型、空白脸部轮廓和着装后的身体比例，不从衣物遮挡处推断精确体型。其他视角或缺少许可、相容参考及景别覆盖时进入 Reviewer。
- 可用 `arco_references` 显式选择独立 `identity_reference`：必须为已获该职责许可、与表情视角相容的正式 `faceless_composite`，可来自其他 Variant。独立身份合同排除 `outfit` 与 `variant`，本轮服装只由选定 Variant 的 `outfit_reference` 决定。缺少许可或覆盖时停止；同一资产同时承担身份与服装时只输入一次。
- back_view：明确 `expression.face_visible: false`，省略 `library_asset_id`、library_adjustments 及眉眼嘴细节，仍记录不可见原因、sources、observations 和 transfer_target。选择实际背面身份及所选 Variant 背面服装参考，分别满足身份/头发/身体与服装覆盖。缺背面身份返回 `IDENTITY_CALIBRATION_REQUIRED`；按 [独立身份前置流程](../calibration/outfit-preparation.md) 确认并标定后继续。

同一物理文件只输入一次，职责冲突则拒绝。最多三张 Arco WHO、两张 External HOW，总计最多五张。预览只展示实际选中的着装身份图、服装图、表情图与外部参考。输入变化要求更新分析来源、合同和冻结确认摘要，旧确认失效。修订成图只有连续性职责；超过总数则从全部原始来源重建，不丢掉已确认参考。

## 确认与复核接口

`ProductionGenerationPlan.as_dict()` 返回参考合同、提示词、Invocation Plan 和 `analysis_preview`。冻结摘要绑定标准化请求、分析、最终提示词、合同和所有输入文件哈希。

确认结构：`analysis_confirmation: {user_confirmed: true, plan_sha256: <预览哈希>, user_message: <实际确认消息>}`。真实适配器再次核对提示词、合同和文件；内部字段不会传给图像工具。普通修订先用 `plan_production_revision()` 展示精确预览，再填写新确认。

已批准的 Variant 设计和背面 Identity 定义也绑定文件哈希；修改正式定义会使旧确认失效。服装准备采用独立的三节点确认及每图两次修正，见 [服装准备流程](../calibration/outfit-preparation.md)。

`visual_review` 绑定计划哈希与输出文件哈希，要求 `inspected_original_size: true`。`checks` 必须包含 identity、composition_pose、expression、lighting_style，每项有 `status: PASS | FAIL | UNVERIFIED` 和非空 `evidence`。任何 FAIL 则总体 FAIL，无法判断则 UNVERIFIED；`user_accepted` 为 false，等待用户判断。

缺确认、确认过期、来源不符、表情图缺失、覆盖不足或疑点未解决，均在真实调用前停止。校验器不读取图像内容，不保证生成模型遵从；视觉观察由看过实际图片的代理提供。
