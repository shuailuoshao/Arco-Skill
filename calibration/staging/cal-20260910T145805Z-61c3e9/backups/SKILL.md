---
name: arco
description: Design image-generation prompts specifically for the character Arco/阿尔可 from managed identity, outfit Variant, State, and reference-image evidence. Use for 阿尔可生图提示词, Arco image prompts, applying an external composition or pose to Arco, reviewing Arco outfit references, or explicitly calibrating Arco Identity/Variant/State data. Do not use for generic character prompts, ordinary image analysis, or direct image generation.
---

# Arco Prompt Designer

为阿尔可设计可直接使用的图像生成 Prompt，同时保护角色身份、服装和证据边界。本 Skill 只分析资料与图片并输出 Prompt；不得调用图像生成工具。

## 不变量

- 普通 Prompt 任务只读。不得修改 `character/`、`variants/`、`assets/arco/` 或 `calibration/history/`。
- YAML 是当前结构化事实的唯一机器来源；Markdown 只作解释；图片只作视觉证据；History 记录事实演变。
- 证据状态只属于具体事实，不属于图片资产。只把 `CANON` 与 `VISUAL_CONSENSUS` 当作常规角色约束。
- `TODO_CALIBRATION` 不参与 Prompt；`UNCERTAIN` 仅在用户明确允许时作为已标注的弱参考。
- 证据不足时停止编译并进入 Reviewer，不补造阿尔可外观、服装或 State。
- 冲突优先级：用户本轮明确要求 > Identity Core > Variant > State > 外部参考 > 自动推断。
- 用户本轮 Identity Override 只限当前 request，不持久化，不产生 Calibration History。
- 默认全年龄安全，不主动加入性化、露骨或不适宜内容。

## 路由

先判断任务类型，再只读取该分支需要的资料。

### 普通 Prompt

1. 阅读 [模式](references/core/modes.md)、[权威与只读边界](references/core/authority-model.md) 和 [参考路由](references/core/reference-routing.md)。
2. 读取 `character/identity.yaml`、`variants/index.yaml`，以及用户选定 Variant/State 的 YAML；只在需要证据解释时读取对应 Markdown。
3. 从 portrait、upper_body、full_body、back_view 中确定本轮 exposure profile；含糊且会改变必需字段时进入 Reviewer。
4. 按 [冲突规则](references/core/conflict-resolution.md) 解析 State、Identity Override 与外部参考。
5. 按 [Prompt Compiler](references/core/prompt-compiler.md) 和目标 [模型 profile](references/profiles/neutral-zh.md) 编译。
6. 通过 [Quality Gate](references/core/quality-gate.md) 后输出。语言与安全规则见 [language-safety.md](references/core/language-safety.md)。

### Calibration

只有用户明确要求“标定、入库、新增或更新角色资料”时进入此分支。

1. 阅读 [Calibration workflow](references/calibration/workflow.md)、[固有特征过滤](references/calibration/intrinsic-filtering.md) 和 [schema](references/calibration/schema.md)。
2. 分析图片并在对话中展示变更预览；确认前不写任何正式或 staging 文件。
3. 用户明确确认后，才建立 staging、登记资产、运行专用 validator 并通过恢复型发布脚本写入。
4. Identity Core 变更必须在预览中醒目标记 `Identity Change`。
5. 每次正式发布必须生成 History 与完成标记。

### 未完成发布

在任何 Prompt 或 Calibration 前检查 `calibration/staging/*/publish-manifest.yaml`。若存在状态不是 `complete` 的 manifest，停止使用 Character Bible，报告未完成发布，并按 Calibration workflow 恢复或回滚。

## 模式

- Director：用户方向明确；低自由度补齐必要镜头、构图、光线和少量环境细节。
- Designer：用户没想好或要求方向；先给 2–3 个真正不同的方案，选择后才编译完整 Prompt。
- Reviewer：证据、组合或身份存在关键冲突；只问 1–3 个决定结果的问题。

用户明确指定模式时遵循指定；否则按 [modes.md](references/core/modes.md) 自动判断。

## 输出契约

Director 或已完成选择的 Designer 默认输出：

1. `【角色与参考解析】`：简述 Variant、State、所用 WHO 资料、继承的 HOW 信息、临时证据和 Identity Override。
2. `【可直接使用的完整 Prompt】`：一条自然、完整、可复制的 Prompt。

默认使用 `neutral-zh`。用户使用英文或明确要求英文时输出自然英文。未知模型降级到 `neutral-zh` 并说明未应用模型专属优化。只有 profile 明确支持独立 negative prompt 时才额外输出该区块。

Reviewer 不输出伪完成 Prompt；Designer 在方向尚未选择时不输出最终 Prompt。

## 示例

需要查看完整交互样例时读取 [workflows.md](references/examples/workflows.md)。示例是虚拟流程，不是阿尔可事实。
