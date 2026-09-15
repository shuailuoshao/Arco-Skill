---
source_entity: character.identity
source_revision: 1
---

# 阿尔可 Identity 工作级证据说明

结构化事实以 identity.yaml 为唯一来源。本次发布14项字段，其中10项 UNCERTAIN、4项 TODO_CALIBRATION；没有 CANON 或 VISUAL_CONSENSUS。用户批准工作描述不提高证据等级。

Identity Primary 为 identity-p01-crop（Candidate A），仅作为 portrait / WHO anchor。P01 提供上半身、全身、整体发长及身体比例辅助；P03 保持 supplemental，按实际覆盖价值选择。三者均继承同一 standing-art source family，派生裁剪不增加独立性。

Candidate A outfit leakage 为 LOW，expression leakage 为 HIGH，用户接受剩余风险。参考图的 outfit、pose、expression 默认不得继承，运行时通过 Reference Contract 和 Prompt Instructions 表达。

field_ref: body.head_to_body_ratio

头身比原工作描述保留在待标定备注与 History；字段仍待标定，不作为已确认数值或默认 Prompt 事实。

证据覆盖为 portrait、upper_body、full_body READY，back_view INCOMPLETE，Global Reference Readiness 为 PARTIAL。证据状态与参考覆盖是不同概念；本说明不声明角色事实已经 CANON。
