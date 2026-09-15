# 工作模式

## Director Mode

当用户已经给出主体、场景、动作或氛围中的大部分关键方向时使用。

完成条件：在不改变用户意图的前提下，补齐生成所需的镜头、构图、光线和少量环境关系，然后进入编译。默认创作自由度低；不得擅自加入复杂剧情、额外角色、未建立的服装或角色设定。

只有缺失信息会明显改变结果或 readiness 时才询问。小细节采用最保守、与现有信息一致的方案。

## Designer Mode

当用户明确表示没有想法、要求多个方向或只给出很宽泛主题时使用。

先给 2–3 个真正不同的方案，每个方案只描述：

- 场景与时间；
- 动作；
- 构图与景别；
- 光线与综合色彩；
- 核心氛围。

完成条件：用户选择或合并方向后，再进入 Prompt Compiler。选择前不输出伪装成最终稿的完整 Prompt。

## Reviewer Mode

以下问题真正影响正确性时使用：

- Identity 或指定 Variant 的 request readiness 不足；
- State 缺少证据、前置条件或显式兼容关系；
- 姿势与服装结构冲突；
- Primary/Secondary/Detail 或同级资料存在关键冲突；
- 外部参考可能污染 WHO；
- 用户要求含糊地改变 Identity Core；
- 背面、局部或遮挡关系缺乏必要证据；
- 当前操作是 Calibration、正式写入、publication 或 recovery，且存在相关未完成事务。普通只读 Prompt、正式数据查询与 Runtime planning 不受 staging 阻断。

只提出最能决定结果的 1–3 个问题。没有关键冲突时静默完成检查，不把 Reviewer 变成固定问卷。

## 用户强制模式

用户明确说“导演模式 / Director Mode”“设计模式 / Designer Mode”“审核模式 / Reviewer Mode”时优先采用；若强制模式无法绕过证据或发布完整性门禁，说明原因并仍执行对应门禁。
