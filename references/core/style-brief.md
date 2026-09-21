# Style Brief Contract

Style Brief 是绑定到本次请求、并绑定到 Batch 1 `resolve_style_references()` 结果的内部数据。它把已声明的 Style Axis 转成可追踪的 HOW 描述，不改变 Reference Contract。Resolver 将 Brief、Baseline 与 User Override 合成为 `ResolvedStyleContext`；只有这个最终 Context 会传给 Prompt Compiler，Style metadata 不进入 Provider 参数。

## Schema

```yaml
schema_version: 1
source_reference_id: external-style-01
style_priority: primary
active_axes:
  - linework
  - shading
axes:
  linework:
    description: clean, crisp anime linework with controlled contours
    confidence: HIGH
  shading:
    description: soft cel-shaded form modeling with limited blending
    confidence: MEDIUM
```

`source_reference_id` 必须来自 `resolve_style_references(references)` 的 `references`。`style_priority` 必须与该解析结果一致，`active_axes` 只能是该 Reference 已声明 `style_axes` 的子集，且 `axes` 的 key 必须精确匹配 `active_axes`。description 必须是非空字符串；confidence 接受 `high`、`medium`、`low` 的大小写形式，Runtime 统一归一化为 `HIGH`、`MEDIUM`、`LOW`。

Style Brief 使用固定的小型 WHO token guard 拒绝明显的人物身份、发色、眼睛、脸部、服装、Variant 或 State 描述。它不是自然语言分类器，也不读取图片、不联网、不调用模型。

公开 Runtime API 为：

```python
validate_style_brief(brief, *, resolved_style_references)
```

该函数返回 normalized copy，不修改输入。失败时使用稳定错误码：`STYLE_BRIEF_MISSING`、`STYLE_BRIEF_SOURCE_MISMATCH`、`STYLE_BRIEF_PRIORITY_MISMATCH`、`STYLE_BRIEF_AXIS_UNOWNED`、`STYLE_BRIEF_AXIS_INVALID`、`STYLE_BRIEF_CONFIDENCE_INVALID` 和 `STYLE_BRIEF_WHO_POLLUTION`。

## Context hand-off

`resolve_style_context()` 只在 request scope 内消费 Style Brief：

- 有 Primary 时，Primary Brief 覆盖自己的 Axis；Secondary 只填补 Primary 未声明且自己拥有的 Axis。
- Primary 已声明的 Axis 如果没有对应 Brief，fail closed 为 `STYLE_BRIEF_MISSING`。
- 只有 Secondary 没有 Primary 时，使用 Official Style Baseline fallback，不把 Secondary 与 Baseline 混合。
- 没有 External Primary 时，使用 Baseline 的声明型 rendering axes。
- User Style Axis Override 只覆盖或新增单个 Axis，优先级最高。

最终边界是纯数据 `ResolvedStyleContext`，每个 Axis 都保留 `description`、`source`、`source_type` 和大写 `confidence`。`protected_identity_properties` 始终保留 `hair_color`、`eye_color`、`variant_key_colors`；任何 Style Override 都不能删除它们。

Batch 3 的 `compile_prompt(..., style_context=...)` 将最终 Context 编译到 Style block，并校验其与当前 References 的一致性。本批仍不实现 Style Baseline 的视觉共识计算、Rendering Hygiene、Visual Reviewer、Output Gate 或 Targeted Repair。
