# 冲突与组合规则

## 总优先级

按以下顺序处理冲突：

```text
用户本轮明确要求
> Arco Identity Core
> 指定 Variant
> 指定 State
> 外部参考图
> 自动推断
```

State 只修改 Variant 明确允许变化的字段。合法 State override 不视为与 Variant 冲突；若触及 Must Keep，则 Variant 优先并进入 Reviewer。

## 参考等级

每个正式 Variant 恰好一个 Primary：

```text
Primary > Secondary > Detail
```

低级别资料与高级别资料冲突时，高级别优先。同级资料存在无法解释的重要冲突时，不挑一张偷偷覆盖，进入 Reviewer。

## External Style Reference

External Style Reference 的 `role` 保持 canonical role；`duties` 只声明 HOW duties。Identity / Variant / State 的权威始终属于 Arco Identity Contract，Style Reference 只能控制 HOW。

Style Reference 使用固定 10 个 Style Axis：

```text
linework, shading, color_logic, highlight_language, material_rendering,
texture_language, lighting_language, background_rendering, detail_density,
edge_treatment
```

Style Reference 可以声明 `style_priority: primary` 或 `style_priority: secondary`，最多各一个。只有一个 Style Reference 且未声明 priority 时自动成为 Primary；多图缺省 priority、两个 Primary 或超过一个 Secondary 都 fail closed。Primary 与 Secondary 不做数值权重混合；双方声明同一 Style Axis 时抛出 `STYLE_AXIS_CONFLICT`。Reference resolution、Brief、Baseline 与 Override 汇总为唯一 `ResolvedStyleContext`；Prompt Compiler 只消费这个最终 Context，不重新决定 axis ownership，也不向 Provider 增加 Style 字段。

Style Context 的最终 Axis precedence 为：

```text
User Style Axis Override
> Primary Style Brief
> Secondary Style Brief
> Official Style Baseline
```

Official Style Baseline 只在没有 External Primary 时参与 fallback；存在 Primary 时完全不读取、不校验。只有 Secondary 没有 Primary 时进入 `official_fallback`，不将 Secondary 与 Baseline 混合。Primary 已声明但没有对应 Brief 的 Axis 使用 `STYLE_BRIEF_MISSING` 拒绝。每个已解析 Axis 都保留 `source`、`source_type` 与 confidence；`hair_color`、`eye_color`、`variant_key_colors` 的 intrinsic identity protection 始终保留。

## State 闭世界组合

1. 同一 `exclusive_group` 的 State 冲突。
2. 缺少 `requires` 时阻止。
3. 命中 `conflicts_with` 时阻止。
4. 修改非 `state_mutable_fields` 或 Must Keep 时阻止。
5. 跨 `state_group` 组合必须由 Variant 的组级兼容规则或 State 的 `compatible_with` 明确允许。
6. 同组默认不兼容；只有显式允许且不在同一互斥组时才组合。
7. 未声明兼容不等于兼容。

## Identity Override

第一版只支持 request-scoped override：

```yaml
scope: request
persistent: false
persistent_to_bible: false
calibrating: false
```

明确 override 可以影响本次 Prompt，但解析摘要必须披露偏离字段和“Character Bible 未修改”。下一请求不继承。

“以后都改成”“更新标准身份”“写入角色库”等表达不是普通 override，必须切换到 Calibration / Identity Change。
