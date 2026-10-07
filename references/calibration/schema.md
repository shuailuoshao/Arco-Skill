# Character Bible Schema

Expression Library v1 的候选结构详见 [expression-schema.md](expression-schema.md)。Expression Asset 与 Semantic 分离；Asset role 只能是 `expression_evidence`，不得累计到 Identity、Variant、hair、body、face.shape 或 jaw/chin。Face Slot membership 与具体 compatibility 分离。Semantic 审核使用 `UNREVIEWED / REVIEW_REQUIRED / APPROVED / DISPUTED`，不复用 Character Evidence Status。

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

新服装可附加独立 `design_definition`、`approval_context` 和 `source_materials`，合同见 [服装准备流程](outfit-preparation.md)。认可的补全和改款是固定设计，原图观察证据状态继续保留。Identity 的 `approved_view_designs.back` 保存独立确认的背面设计及正式背面身份参考。

## State

State 必须带真实证据状态和 `evidence_ids`，并声明 `state_group`、可空 `exclusive_group`、`compatible_with`、`conflicts_with`、`requires` 与 `overrides`。

组级兼容关系由 Variant 统一声明；State-specific compatibility 只用于例外。

## Asset

资产只记录来源与用途，不允许 `evidence_status` 或 `status`。固定字段及枚举见 `assets/templates/asset.yaml`。

### Future Asset schema v3: generation reference permission

Phase 1 仅提供向前兼容读取和验证，不迁移当前 Asset Index。schema v2 中字段缺失严格等价于 `can_be_generation_reference: false`。

未来只有 Identity 或 Variant Calibration 批准具体业务语义后，才能把相应 Asset Index 作为同一 Calibration 的独立 target 发布：

```yaml
can_be_generation_reference: true
generation_reference:
  priority: primary # primary | secondary | supplemental
  supported_roles: [identity_reference]
  preferred_for: [portrait, upper_body, full_body]
  excluded_for: [back_view]
  coverage:
    profiles: [portrait, upper_body]
    visible_fields: [identity, hair, eyes, face]
    view_angles: [front]
    occluded_fields: []
  inheritance:
    identity: inherit
    outfit: do_not_inherit
    pose: do_not_inherit
    expression: do_not_inherit
```

`generation_reference` 是 closed mapping，只允许 `priority`、`supported_roles`、
`preferred_for`、`excluded_for`、`coverage`、`inheritance`。未知关键字段验证失败。
`inheritance` 的值只能是 `inherit` 或 `do_not_inherit`。派生参考还必须在 Asset
顶层保存 `derived_from_asset_id` 与 `evidence_independence: none`；具体裁剪参数保存在
`operation`，裁剪不会增加证据独立性。

Runtime Policy 不能建立绕过 Asset Index 的 per-asset allowlist。Body Base 当前只用于本地证据；着装 Faceless Composite 和表情 PNG 按正式 schema v3 中获批的具体职责选择。新增许可与 Asset Index revision 推进必须另走 Calibration。

多来源合成参考使用 `derived_from_asset_ids` 与 `derivation_sources`，和单亲 `derived_from_asset_id` 互斥。每个输入绑定 asset_id、sha256、usage，服装输入还保存 parts/区域、原套装版本及处理记录；生成记录绑定 preparation_id、candidate_id、plan_sha256、output_sha256 和调用尝试。合成图统一 `source_kind: derivative`、`evidence_independence: none`，不增加 VISUAL_CONSENSUS 的独立来源数。

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
