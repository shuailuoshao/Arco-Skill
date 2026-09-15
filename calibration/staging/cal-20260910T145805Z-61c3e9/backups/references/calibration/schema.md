# Character Bible Schema

## 通用实体

所有受标定管理的 YAML 实体包含：

```yaml
schema_version: 1
entity_type: identity
entity_ref: character.identity
revision: 0
last_calibration_id: null
```

`entity_ref` 在整个库中唯一。revision 0 是初始骨架；revision 大于 0 时必须有可完成追踪的 History。

## Fact

```yaml
field_id: hair.base_color
display_name_zh: 基础发色
value: null
status: TODO_CALIBRATION
evidence_ids: []
conflicts: []
note_zh: ""
required_global: true
required_for: [portrait, upper_body, full_body, back_view]
```

`required_for` 可用值为 `portrait`、`upper_body`、`full_body`、`back_view`。多个 profile 取并集。

`CANON` 事实还必须提供明确的官方定义依据，不能只凭官方图片本身：

```yaml
canon_basis:
  kind: explicit_official_definition
  source_note: "官方角色设定页明确写明该字段。"
```

`source_note` 说明“官方在哪里明确了这一事实”。仅观察官方插画中的颜色、姿势或光照表现不满足此条件。

## Variant

正式 Variant 路径为 `variants/<variant-id>/variant.yaml`，英文 ID 与路径稳定，中文显示名可修改。

Variant 包含 facts、恰好一个 Primary、Secondary/Detail 列表、Must Keep、可变字段、State group 规则、State 路径和已知风险。

## State

State 必须带真实证据状态和 `evidence_ids`，并声明 `state_group`、可空 `exclusive_group`、`compatible_with`、`conflicts_with`、`requires` 与 `overrides`。

组级兼容关系由 Variant 统一声明；State-specific compatibility 只用于例外。

## Asset

资产只记录来源与用途，不允许 `evidence_status` 或 `status`。固定字段及枚举见 `assets/templates/asset.yaml`。

## Observation

Observation 仅在字段确实受光照、姿势、透视或遮挡影响时使用。结构见 `assets/templates/calibration-history.yaml` 中的 `observations` 示例。

## History

History 的 `targets` 支持一次 Calibration 修改多个实体。每个 target 必须有 `entity_ref`、target type/id、revision before/after、changed fields、before/after 和状态变化。

## Markdown

说明文档 frontmatter：

```yaml
---
source_entity: variants.default-outfit
source_revision: 2
---
```

Markdown 不声明结构化 `value` 或 `status`，只用 `field_ref` 和 `evidence_ids` 解释对应事实。
