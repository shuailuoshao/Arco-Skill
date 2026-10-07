# Prompt Compiler

普通 Prompt 只读取正式发布区，不扫描 staging。Expression Semantic 的默认稳定检索只允许 `semantic_review_status: APPROVED`；APPROVED 不要求 high confidence。其他审核状态仅可贡献明确标注的 `visual_features`，不得作为确定情绪。

## 输入

只使用以下已解析输入：

- request readiness 已满足的 Arco Identity facts；
- 指定 Variant、合法 State 组合和 Must Keep；
- 已发布 Variant 的 `design_definition` 与哈希绑定的 `approval_context`，包括固定补全、改款和穿法；
- 用户本轮明确要求；
- 本轮临时 Arco reference 中足以补齐的字段；
- 外部参考提供的 HOW 信息；
- 当前模型 profile。

不得把 `TODO_CALIBRATION` 写入 Prompt。`UNCERTAIN` 只有用户明确允许时才能作为弱参考，并在解析摘要中标明。

普通生产显式读取所选 Variant YAML，通过 `outfit_design.compile_design()` 将独立获批设计加入最终提示词；此设计权威不改变 Fact 的证据状态。背面另外读取 `approved_view_designs.back`。旧三套服装无设计字段时继续沿用原有参考规则。

### Identity Fact Resolution

Identity facts enter the compiler through an explicit, profile-aware
resolution step; the compiler never serializes the whole Identity YAML.  A
caller must opt in to user-approved working facts before an `UNCERTAIN` value
can be rendered. `TODO_CALIBRATION` is always omitted from generation text.

The current body mapping is intentionally narrow:

```text
body.chest_proportion: small-to-modest
→ a slim, lightly built figure with a narrow upper torso and a
  small-to-modest, understated bust
```

The compiler may add the single mild guard `no exaggerated chest volume`.
Duplicate body semantics are removed and the phrases `flat chest`, `tiny
breasts`, and `very small breasts` are rejected.  This mapping is available
for `portrait`, `upper_body`, and `full_body`; `back_view` follows its normal
profile routing and does not gain a special body rule.

## 编译顺序

`compile_prompt()` 按以下段落顺序组装最终文本：

1. Identity fact fragments 与已解析的 WHO 要求；
2. `ResolvedStyleContext` 编译出的 Style instructions；
3. 每张 Reference 的职责与继承边界；
4. 用户的 base scene prompt；
5. 请求明确需要时的 Composition Readability block；
6. 仅 DIRECT_EDIT 修订可选的 Revision Stability block；
7. 可选的 Style-aware Rendering Hygiene；
8. Identity soft constraints。

Revision Stability 的结构与激活边界见 [Phase 4 Revision Stability Guard](revision-stability.md)。

Composition Readability 的请求字段、尺度阈值、冲突与修订边界见 [Phase 5 Composition Readability](composition-readability.md)。

Rendering Hygiene 由调用方通过 `rendering_hygiene_policy` 显式启用，必须位于 base scene 之后、Identity soft constraints 之前。未传 policy 时，Batch 3 Style-only Prompt 保持逐字不变。Hygiene 的定义、policy contract 和质量边界见 [Rendering Hygiene](rendering-hygiene.md)。

写成自然、连贯的语言，重点回答“谁在什么地方，以什么姿态，被怎样的镜头和光线表现”。把最重要的 Identity、Variant Must Keep 和构图锚点放在前部，避免埋在低价值细节里。

## Resolved Style Context

`compile_style_instructions(style_context)` 只接收 `resolve_style_context()` 的最终结果。它按 canonical `STYLE_AXES` 顺序输出 `resolved_axes` 中实际声明的轴及其 description；缺失轴保持 unspecified。Compiler 不重新解析优先级、不读取 Baseline 文件、不输出 confidence，也不从默认美学补充 rendering 特征。

有 `color_logic` 且 `protected_identity_properties` 非空时，Style block 明确限定色彩描述只影响整体 rendering 与 palette relationships，并保留列出的固有角色颜色。Style description 继续通过 WHO token guard；Style Reference duty 缺少 Context 或 Context provenance 与当前 Reference 不一致时 fail closed。

`validate_style_prompt()` 检查每个 resolved axis 是否进入结构化 Style block、block 是否含未声明内容、color identity guard 是否存在、Style 文本是否污染 WHO，以及带 Style provenance 的 Context 是否实际编译。它只检查 Style block，不对 scene 文本做自然语言分类。

`compile_rendering_hygiene(style_context, *, policy)` 只使用受控、相对型模板，不从 Style Axis 自由文本推断属性。显式用户要求优先于 Resolved Style，二者均优先于 Hygiene；active Hygiene block 必须包含 escape clause。`validate_rendering_hygiene()` 检查最终 Prompt 中的 block 是否与模板完全一致、唯一且不含 WHO 内容，不尝试进行通用自然语言冲突分类。

稳定错误码包括 `STYLE_CONTEXT_MISSING`、`STYLE_CONTEXT_INVALID`、`STYLE_CONTEXT_REFERENCE_MISMATCH`、`STYLE_AXIS_NOT_COMPILED`、`STYLE_AXIS_UNDECLARED`、`STYLE_AXIS_ORDER_INVALID`、`STYLE_IDENTITY_PROTECTION_MISSING`、`STYLE_PROMPT_WHO_POLLUTION` 和 `STYLE_REFERENCE_UNUSED`。

不要依赖 `masterpiece`、`best quality`、`8K`、`ultra detailed` 等空泛词控制结果。

## Reference Instructions

Reference-conditioned 模式为每张图片明确职责：Identity/Variant 图片提供 WHO，External 图片只提供 HOW，并逐项声明不得继承的外部身份、发色、瞳色、脸、体型与服装。参考图存在时仍保留关键 Identity Lock 和 Variant Must Keep，但不重复几十项已经清晰可见的低价值细节。获准 Expression PNG 作为 face_reference 提供阿尔可五官结构；目标表情由本轮分析决定。APPROVED Semantic 可提供稳定语义，其他状态仅依据明确可见特征描述。

For an offline candidate dry-run, the resolver may receive an explicit
candidate Identity document.  This does not make candidate data production
data: normal Runtime planning continues to read only the formal published
root and never discovers staging paths.

每个 Reference Contract 的 `inherit` 与 `do_not_inherit` 必须逐项进入 Reference Instructions。Reference Instructions 说明哪张图片负责什么，并标出已解析的 Style Reference priority；Style instructions 说明 Resolver 已确定的视觉行为，不重复来源或 priority。Quality Gate 对照 Contract 检查引用 ID 和全部排除字段；缺失任一排除项即失败。Identity full-body Secondary 可以继承身份、整体身体比例和整体发长，但不得默认继承 outfit、pose 或 expression。

## Request Readiness

先确定 exposure profiles：

- `portrait`：脸、眼、基础头发和可见头饰；
- `upper_body`：portrait + 上半身体型、Variant 上装和可见配饰；
- `full_body`：upper_body + 整体比例、腿部、下装和鞋袜；
- `back_view`：当前景别所需字段 + 发型和服装背面证据。

多个 profile 取字段并集。只有画面实际可见或影响轮廓的字段才是本轮必需项。景别或遮挡关系不足以判定时进入 Reviewer。

全局 readiness 可以 INCOMPLETE，而本轮 request readiness 可以 READY。临时参考只补足本轮，不改变库状态。

## 输出

### 角色与参考解析

简短列出：Variant、State、使用的角色资料、继承的 HOW、临时证据、弱参考和 Identity Override。

### 可直接使用的完整 Prompt

输出一条连续自然语言 Prompt。默认中文；用户使用英文或明确要求英文时输出英文。Negative Prompt 只在模型 profile 明确支持独立字段时另行输出。

若本轮还要求 generation planning，追加 Reference Contract、Global/Request Reference Readiness 与 Invocation Plan。Prompt-only 的 built-in 参数中不得出现任何图片字段。

生产入口在现有 Compiler 后追加已校验的 Reference Analysis block，逐项保留身份、构图、动作、眉眼嘴与明暗关系；Style Axes 继续仅由 ResolvedStyleContext 编译。详见 [分析确认](reference-analysis.md)。
