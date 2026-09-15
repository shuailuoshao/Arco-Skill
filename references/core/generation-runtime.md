# Reference-Conditioned Generation Runtime

运行链路：Mode Resolver → Identity/Variant/State/Pose/Expression Resolver → Reference Selector → Reference Contract → Image Input Builder → Prompt Compiler → Quality Gate → Invocation Plan → Arco Real Adapter → builtin_image_gen。

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
