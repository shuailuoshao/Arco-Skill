# Reference-Conditioned Generation Runtime

运行链路：Mode Resolver → Identity/Variant/State/Pose/Expression Resolver → Reference Selector → Reference Contract → Style Reference/Brief Resolver → `ResolvedStyleContext` → Image Input Builder → Prompt Compiler → Quality Gate → Invocation Plan → Arco Real Adapter → builtin_image_gen。

Prompt Compiler 将最终 `ResolvedStyleContext` 渲染为 Style instructions；Adapter 与 Provider 仍只接收既有 Prompt 和 image transport 字段。

## Production Style Transfer V1.0

正常 Arco Skill 生成由 `scripts/arco_production.py` 的
`run_production_generation(request, builtin_image_gen=...)` 统一编排。入口只接受
高层用户请求、阿尔可参考图/已发布资产、可选 External HOW References 和上游绑定的
Style Brief；它不会读取或依赖任何实验 runner、Pilot manifest、盲评或 formal
regression 状态。

修改已有输出必须使用 [修订入口](revision-reference.md) 的 `run_production_revision()`。
首次生成入口拒绝带有 output lineage、generated-output role 或 previous-output provenance 的参考，返回 `REVISION_ENTRY_REQUIRED`；修订入口的内部调用除外。显式标记 `degraded` 的参考不能用于生成。
结果新增 `revision_context` 和 `visual_review_status`；初始状态是 `unchecked`，不代表质量通过。

Style Transfer 在生产入口中始终启用。没有 External Primary Style Reference 时，
Runtime 使用 `character/style-baseline.yaml` 的 Official Style Baseline fallback；
存在有效 External Style Reference 时，入口继续使用既有 Reference Role Resolver、
Style Reference Resolver、Style Brief validation、`ResolvedStyleContext`、Style
Conflict Resolver、Prompt Compiler 和 Identity protection。

Rendering Hygiene 默认关闭。只有 request 明确指定
`rendering_hygiene: hygiene_v11` 时，入口才加载 `runtime/style-policy.yaml` 并将
Hygiene block 编译进本次 Prompt；未知或隐式 Hygiene 值 fail closed。

Prompt Compiler receives resolved Identity fact fragments separately from the
Reference Contract.  The body-proportion fragment is an optional textual
identity aid, not a new image reference and not permission for Body Base
assets.  Candidate Identity facts may be supplied only by an explicit,
isolated offline validation fixture; production Runtime never reads
`calibration/staging`.

## Readiness

`GLOBAL_REFERENCE_READINESS` 只表示正式数据库的 generation references 成熟度。`REQUEST_REFERENCE_READINESS` 表示当前请求是否因 managed 或 request-scoped references 而可执行。临时图片永远不提升 Global。

Global Variant readiness 按每个已发布 Variant 的 `portrait / upper_body / full_body / back_view` coverage 计算，而不是仅凭存在一个 Primary 判断。至少一个 profile READY 但并非全部 READY 时，Variant overall 为 `PARTIAL`；重复 Primary 为 `CONFLICT`。`variant_profiles` 保存逐 profile 结果。

Request readiness 使用 `READY / PARTIAL / INCOMPLETE / CONFLICT`，并按 portrait、upper_body、full_body、back_view 的实际覆盖计算。正面 portrait 图不能让 full-body 或 back-view 请求成为 READY；指定 Variant 时还必须覆盖当前景别可见的 Variant 信息。

指定服装 Variant 的请求必须把稳定 `selected_variant_id` 传给 Selector 和 Request Readiness。Outfit Contract 的 `variant_id` 与请求不一致时，Request Readiness 必须返回 `CONFLICT`；不得按名称排序或“当前只有一个 Variant”猜测目标。

## Mode 与降级

- 用户显式 prompt-only 时不产生 image inputs。
- 自动模式优先 reference-conditioned；引用不足或 capability 不可用时可披露原因并降级 prompt-only。
- 用户明确要求必须使用参考图时不得静默降级，进入 Reviewer。
- Prompt-only 不绕过原有 Identity/Variant Request Readiness。

## 失败码

稳定错误包括 `REFERENCE_ASSETS_INCOMPLETE`、`REFERENCE_CONFLICT`、`REFERENCE_LIMIT_EXCEEDED`、`UNPUBLISHED_ASSET`、`ASSET_NOT_ALLOWED_FOR_GENERATION`、`VARIANT_SELECTION_REQUIRED`、`VARIANT_REFERENCE_NOT_FOUND`、`VARIANT_PRIMARY_MISSING`、`VARIANT_PRIMARY_CONFLICT`、`IMAGE_INPUT_BUILD_FAILED` 与 `QUALITY_GATE_FAILED`。Runtime 全程只读，不登记新资产或修改 Character Bible。

正常生成与修订必须遵循 [分离参考、确认与视觉验收](reference-analysis.md)。先规划、展示具体预览、等待本轮用户确认，再调用；图片、提示词或目标变化使旧确认失效。

添加或混搭服装使用独立 [服装准备入口](../calibration/outfit-preparation.md)。普通生产拒绝 `calibration/preparations` 候选路径；服装素材在受控准备通道中只提供指定部件。背面生产要求真实背面身份和所选 Variant 背面覆盖，脸不可见时不要求表情 PNG。
