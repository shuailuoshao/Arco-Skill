# Quality Gate

输出前静默检查；关键项失败时进入 Reviewer，不输出伪完成 Prompt。

## 角色与证据

- 仍然是阿尔可，或已明确披露 request-scoped Identity Override。
- 发色、瞳色、脸型和身体比例没有被外部人物污染。
- 使用的 Identity facts 不是 `TODO_CALIBRATION`。
- `UNCERTAIN` 只在用户明确允许时作为弱参考。
- 本轮 request readiness 已满足；临时证据已披露且未持久化。

## Variant 与 State

- 使用正确 Variant，且没有混入另一套服装。
- Primary 唯一；服装关键 Must Keep 没有丢失。
- State 有真实证据、前置条件成立、组合被显式允许。
- 动作与服装结构兼容；State 没有覆盖禁止字段。

## 外部参考

- 只继承 HOW，未继承外部角色身份、服装或专属配饰。
- 多图职责没有未解决的关键冲突。

## Reference-conditioned Runtime

- Managed Asset 来自正式发布区、状态与 Hash 有效，并显式允许对应 generation role。
- 缺少 generation permission 等价于 false；不得上传 Expression、Body Base、Faceless、debug 或 staging 资产。
- Global 与 Request Reference Readiness 分离；request-scoped 图片按当前 exposure coverage 判定，不提升 Global。
- Reference 数量不超过 local 3、external 2、total 4；Contract、Invocation Plan 与最终参数的顺序和集合一致。
- External HOW 未污染 Arco WHO；inherit 与 do_not_inherit 不冲突。
- Asset inheritance 已逐项传播到 Reference Contract 和最终 Reference Instructions；每个 do_not_inherit 字段均可在 Prompt 中核对。
- 用户强制 reference-conditioned 时不得静默降级；自动模式降级必须披露原因。
- Prompt-only 参数只包含 prompt，不包含空图片字段。

## 画面自洽

- 手部、身体与视线描述不矛盾。
- 构图、人物位置、景别、镜头和透视明确且一致。
- 主光、环境光、轮廓光方向自洽。
- 色彩、时间、天气和氛围一致。
- 没有无意义质量词堆砌。
- 没有擅自加入大量剧情、物件或额外角色。

## 数据完整性

- 普通只读 Prompt 与 Runtime planning 不读取 staging，也不因 unfinished staging 失败；只有 Calibration、正式写入、publication 与 recovery 检查相关事务。
- YAML 与相关 Markdown revision 没有已知冲突。
- 普通 Prompt 路径没有写入 Character Bible、assets 或 History。
