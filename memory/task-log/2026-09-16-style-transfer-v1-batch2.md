# Style Transfer V1.0 Batch 2

## 理解

- 目标：在 Batch 1 Reference Runtime Contract 上实现 Style Brief binding、Official Style Baseline、Resolved Style Context、User Axis Override 和 provenance。
- 边界：不修改 Prompt Compiler、Real Adapter、Provider schema、image transport、reference limits 或 Character/Variant/Calibration/Memory 持久化结构。

## 已确认决策

- Style Brief 只绑定本次 `resolve_style_references()` 结果；confidence 接受大小写并归一化为大写。
- Primary 负责自己的 declared Axes；Secondary 只填补 Primary 未声明且自身拥有的 Axes。
- Secondary-only 进入 `official_fallback`，不与 Official Baseline 混合。
- Official Baseline 只验证声明型证据 metadata，不读取资产、不重算 SHA、不查询视觉共识。
- User Axis Override 只覆盖单个 canonical Axis，intrinsic identity protection 始终保留。

## 结果

- 新增 `validate_style_brief()`、`validate_style_baseline()` 和 `resolve_style_context()`。
- 新增 `character/style-baseline.yaml`，证据为 `identity-p01` 与 `identity-p03`。
- 更新 Style Reference、Style Brief、routing、conflict resolution 和 SKILL 文档。
- unittest discovery：114/114 PASS。
- `py_compile scripts/reference_runtime.py scripts/arco_real_adapter.py`：PASS。
- 三个纯 Runtime 手工 Case：Primary external、Primary+Secondary external、Official fallback，均通过。
