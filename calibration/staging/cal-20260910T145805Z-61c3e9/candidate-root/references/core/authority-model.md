# 权威模型与只读边界

## 四种材料的职责

- YAML：当前机器可读事实的唯一权威来源。
- Markdown：证据解释、推导过程、冲突说明与人类可读总结。
- Images：视觉证据，不是数据库字段值。
- Calibration History：事实如何演变、由什么证据促成、谁确认以及验证结果。

Prompt Compiler 不得从 Markdown 重新猜测已有 YAML 字段。Markdown 与 YAML 不一致时，使用 YAML、停止静默融合并报告冲突。

## 普通任务只读

普通 Prompt、Designer 方案、Reviewer 审核和外部参考分析不得修改：

- `character/*.yaml` 与说明 Markdown；
- `variants/`；
- `assets/arco/`；
- `calibration/history/`；
- entity revision 或 `last_calibration_id`。

一次性 Identity Override 也属于只读 Prompt 行为。

## Calibration 写入资格

只有用户明确要求标定、入库、新增 Variant/State 或永久修改 Identity 时，才允许读取 Calibration 写入流程。确认前只展示预览；用户确认后才能建立 staging。

## 证据状态

- `TODO_CALIBRATION`：尚无经过审核的有效结论；不参与 Prompt。
- `UNCERTAIN`：已有证据和分析但结论不足或冲突；只有用户明确允许时作为弱参考，并在解析中披露。
- `VISUAL_CONSENSUS`：用户批准的多来源稳定视觉规律；可作常规约束。
- `CANON`：用户批准且由官方明确设定直接支持的事实；可作常规约束。

状态属于具体 claim/field。资产只记录来源与用途，不携带上述状态。

## Markdown 约束

说明 Markdown 的 frontmatter 使用 `source_entity` 和 `source_revision`。正文用 `field_ref` 和 `evidence_ids` 指向事实与资产，不使用 `value:`、`status:` 等保留结构重新声明当前事实。
