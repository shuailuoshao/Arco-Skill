# Style Transfer V1.0 第一批改造

## 理解

- 目标：只建立 Style Contract、External Reference multi-duty、Primary/Secondary Style Reference 解析与测试。
- 边界：不修改 Prompt Compiler、Style Brief 生成、Style Baseline、Rendering Hygiene、Real Adapter/provider schema 或现有 reference limits。

## 已确认决策

- External duties 复用 `*_reference` canonical naming，并新增 `scene_reference`。
- `style_axes` 为可选列表；缺省不声明 ownership。
- 单个未标注 priority 的 Style Reference 自动为 Primary；多图缺省 priority fail closed。
- Runtime 返回 normalized references、primary/secondary IDs 和 axis owners；不读取图片、不联网、不写磁盘。

## 结果

- 新增 Style Contract 与 Style Brief boundary 文档。
- Runtime 新增 duties/Style Axis 校验与 `resolve_style_references()`。
- 新增稳定错误码：`INVALID_REFERENCE_DUTIES`、`STYLE_PRIORITY_INVALID`、`STYLE_PRIMARY_CONFLICT`、`STYLE_AXIS_CONFLICT`，以及 Secondary/Axis schema 的专用校验码。
- unittest discovery：104/104 PASS。
- `py_compile scripts/reference_runtime.py scripts/arco_real_adapter.py`：PASS。
