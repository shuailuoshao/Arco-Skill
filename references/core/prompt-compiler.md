# Prompt Compiler

普通 Prompt 只读取正式发布区，不扫描 staging。Expression Semantic 的默认稳定检索只允许 `semantic_review_status: APPROVED`；APPROVED 不要求 high confidence。其他审核状态仅可贡献明确标注的 `visual_features`，不得作为确定情绪。

## 输入

只使用以下已解析输入：

- request readiness 已满足的 Arco Identity facts；
- 指定 Variant、合法 State 组合和 Must Keep；
- 用户本轮明确要求；
- 本轮临时 Arco reference 中足以补齐的字段；
- 外部参考提供的 HOW 信息；
- 当前模型 profile。

不得把 `TODO_CALIBRATION` 写入 Prompt。`UNCERTAIN` 只有用户明确允许时才能作为弱参考，并在解析摘要中标明。

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

1. 阿尔可身份要求；
2. Outfit Variant；
3. State；
4. 动作与身体姿态；
5. 表情与视线；
6. 场景与时间；
7. 构图和空间关系；
8. 镜头、景别、视角和透视；
9. 主光、环境光和轮廓光；
10. 主色、辅色、点缀色与冷暖关系；
11. 画风与上色/阴影方式；
12. 环境细节与动态；
13. 角色一致性约束；
14. 禁止项。

写成自然、连贯的语言，重点回答“谁在什么地方，以什么姿态，被怎样的镜头和光线表现”。把最重要的 Identity、Variant Must Keep 和构图锚点放在前部，避免埋在低价值细节里。

不要依赖 `masterpiece`、`best quality`、`8K`、`ultra detailed` 等空泛词控制结果。

## Reference Instructions

Reference-conditioned 模式为每张图片明确职责：Identity/Variant 图片提供 WHO，External 图片只提供 HOW，并逐项声明不得继承的外部身份、发色、瞳色、脸、体型与服装。参考图存在时仍保留关键 Identity Lock 和 Variant Must Keep，但不重复几十项已经清晰可见的低价值细节。Expression PNG 不进入 image input；只把 APPROVED Semantic 的 visual features 编译为自然语言。

For an offline candidate dry-run, the resolver may receive an explicit
candidate Identity document.  This does not make candidate data production
data: normal Runtime planning continues to read only the formal published
root and never discovers staging paths.

每个 Reference Contract 的 `inherit` 与 `do_not_inherit` 必须逐项进入 Reference Instructions。Quality Gate 对照 Contract 检查引用 ID 和全部排除字段；缺失任一排除项即失败。Identity full-body Secondary 可以继承身份、整体身体比例和整体发长，但不得默认继承 outfit、pose 或 expression。

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
