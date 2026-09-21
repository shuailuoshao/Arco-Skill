# Style Reference Contract

Style Reference 是 External HOW Reference 的一种职责。它只能回答“应该怎样呈现”，不能回答“角色是谁”。

## External HOW duties

External Reference 继续使用 canonical `role`，并可以用 `duties` 声明同一张图片承担的多个 HOW 职责：

```yaml
role: style_reference
duties:
  - style_reference
  - composition_reference
  - lighting_reference
  - pose_reference
```

允许的 External HOW duties 只有：

```text
pose_reference
composition_reference
scene_reference
lighting_reference
style_reference
```

`role` 始终是 canonical role。旧 Contract 未声明 `duties` 时，运行时按 `duties: [role]` 解释。`role` 不在 `duties` 中、duties 含未知值、重复值或 WHO duty 时，必须 fail closed，并使用 `INVALID_REFERENCE_DUTIES`。

一张图片可以同时承担多个 HOW duties，但仍然只有一个 Reference Contract、一个 `reference_id` 和一个 image input。duties 不会展开为多张图片。

## Style-only authority

Style Reference 只能决定 HOW：

- linework 与边缘处理方式；
- 明暗、色彩、高光、材质与纹理语言；
- 光线、背景呈现和细节密度。

Style Reference 绝不能决定或修改：

```text
identity
hair
eyes
face
body_proportions
outfit
variant
state
```

继承参考图的 painterly shading 是合法的 HOW 继承；继承参考图人物的 blonde hair 是非法的 WHO 污染。External HOW 的 `inherit` 仍然不得包含任何 WHO 字段，并继续触发现有 `EXTERNAL_IDENTITY_POLLUTION` 防护。

Identity / Variant / State 的权威始终属于 Arco Identity Contract。Style Reference 不具有 WHO 权限。

## Style Axes

Style Contract 固定使用以下 10 个 Style Axis：

```text
linework
shading
color_logic
highlight_language
material_rendering
texture_language
lighting_language
background_rendering
detail_density
edge_treatment
```

`style_axes` 是 External Style Reference 的可选字段。缺省表示该 Contract 没有声明具体 Axis ownership，不等价于占用全部 Axis。

## Primary / Secondary

承担 `style_reference` duty 的 External Reference 可以声明：

```yaml
style_priority: primary
```

或：

```yaml
style_priority: secondary
```

最多一个 Primary、最多一个 Secondary。只有一个 Style Reference 且未声明 priority 时，运行时自动将其解析为 Primary。多张 Style Reference 时必须显式声明 priority；缺省 priority 会 fail closed。

Primary 优先决定其声明的 Style Axis。Secondary 不与 Primary 做数值权重混合，只能填补 Primary 未声明的 Axis。两者声明同一个 Axis 时，运行时抛出 `STYLE_AXIS_CONFLICT`。

## Style Brief binding

Batch 2 的 Style Brief 是 request-scoped 的下游描述，必须绑定到 `resolve_style_references()` 已返回的 `source_reference_id` 和 `style_priority`。Brief 只能描述该 Reference 已声明的 Axis；Primary 已声明的每个 Axis 都必须有对应 Brief，缺失时使用 `STYLE_BRIEF_MISSING` fail closed。Secondary Brief 只在 Primary 未声明的 Axis 上补充，且不改变 Reference Contract。

Brief 的 `description` 使用固定 token guard 拒绝明显 WHO 内容，confidence 归一化为大写 `HIGH`、`MEDIUM` 或 `LOW`。这一步不读取图片、不联网、不调用模型。

## Official Style Baseline fallback

当没有 External Primary 时，Runtime 使用 `character/style-baseline.yaml` 中声明的 Official Style Baseline；它的 `mode` 必须是 `fallback_only`。Baseline 只提供保守的 rendering 共识，不提供发色、瞳色、脸、服装、Variant 或 State 事实。Baseline 的 evidence 是声明型元数据，Runtime 只验证 schema、证据数量、hash/asset 对应关系和 consensus metadata，不重新计算 SHA、不读取资产文件、不查询视觉共识。

只有 Secondary、没有 Primary 时仍进入 `official_fallback`，不把 Secondary 与 Baseline 混合。存在 Primary 时 Baseline 完全不读取、不校验、不参与补全；External mode 的 Style Context 只由 Primary、Secondary 和可选 User Axis Override 构成。

最终 `ResolvedStyleContext` 始终携带 intrinsic color protection：`hair_color`、`eye_color`、`variant_key_colors`。Style Override 只能覆盖单个 canonical Axis，不能删除这些保护 metadata。

Batch 2 的 Baseline 校验错误码包括 `STYLE_BASELINE_INVALID`、`STYLE_BASELINE_EVIDENCE_INSUFFICIENT`、`STYLE_BASELINE_SOURCE_MISMATCH`、`STYLE_BASELINE_DUPLICATE_EVIDENCE` 和 `STYLE_BASELINE_MISSING`；User Axis Override 的稳定错误码包括 `STYLE_OVERRIDE_AXIS_INVALID` 与 `STYLE_OVERRIDE_DESCRIPTION_INVALID`。

本批稳定错误码包括 `INVALID_REFERENCE_DUTIES`、`STYLE_PRIORITY_INVALID`、`STYLE_PRIMARY_CONFLICT` 和 `STYLE_AXIS_CONFLICT`；Secondary 数量与 Axis 声明本身的非法情况分别使用 `STYLE_SECONDARY_CONFLICT` 和 `STYLE_AXIS_INVALID`。

本文件定义 Reference Contract 与 Resolver 输入边界。最终 `ResolvedStyleContext` 由 Prompt Compiler 编译进 Prompt；Style metadata 不增加 Provider 参数。
