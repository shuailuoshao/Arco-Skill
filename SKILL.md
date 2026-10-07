---
name: arco
description: Plan and generate Arco/阿尔可 images from managed Identity, Variant, State, Expression and selected references. Use for 阿尔可生图、提示词、添加新服装、残缺或商品服装参考、跨套装混搭、reference-conditioned planning and explicit Identity/Variant/State calibration. Do not use for generic characters or ordinary image analysis.
---

# Arco Image Director

为阿尔可编译 Prompt，并在正式 generation references 足够或用户提供合格的本轮临时参考时规划 reference-conditioned generation。真实图像调用必须经过独立授权的 `ArcoRealAdapter`；适配器接收并复核 Invocation Plan、Reference Contract 与参考图路径后，才可调用 `builtin_image_gen`。

## 生产 Style Transfer V1.0

正常生成通过 `scripts/arco_production.py` 的 `run_production_generation()` 进入统一流程。先调用 `plan_production_generation()` 冻结分离参考、实际视觉分析与提示词，展示具体预览并等待本轮用户确认；确认后才由 `run_production_generation()` 执行。用户提供的外部图默认尽量复现构图、姿势、表情、光影和画风，仅替换为阿尔可身份与指定服装。

生产默认值固定为：

- Style Transfer：`ON`
- Rendering Hygiene：`OFF`

没有外部 Style Reference 时，Style Transfer 使用 Official Arco calibrated style baseline。Rendering Hygiene V1.1 只接受显式 `rendering_hygiene: hygiene_v11` 作为实验性 request-scoped opt-in，不会自动启用。

Style Brief 必须由上游按当前 Style Reference 绑定并通过 Runtime 校验；缺失、来源不匹配或包含 WHO 身份污染时 fail closed。生产入口不读取实验 manifest、盲评记录或 formal regression 状态，也不写入 Character、Variant、Asset Registry 或 Calibration History。

## 不变量

- 普通 Prompt 任务只读。不得修改 `character/`、`variants/`、`assets/arco/` 或 `calibration/history/`。
- YAML 是当前结构化事实的唯一机器来源；Markdown 只作解释；图片只作视觉证据；History 记录事实演变。
- 证据状态只属于具体事实，不属于图片资产。事实常规约束使用 `CANON` 与 `VISUAL_CONSENSUS`；已发布 Variant 的独立获批设计也作为固定服装约束，保留原证据状态。
- `TODO_CALIBRATION` 不参与 Prompt；`UNCERTAIN` 仅在用户明确允许时作为已标注的弱参考。
- 证据不足时停止编译并进入 Reviewer，不补造阿尔可外观、服装或 State。
- 冲突优先级：用户本轮明确要求 > Identity Core > Variant > State > 外部参考 > 自动推断。
- 用户本轮 Identity Override 只限当前 request，不持久化，不产生 Calibration History。
- 默认全年龄安全，不主动加入性化、露骨或不适宜内容。
- Runtime 只读取正式发布区；request-scoped reference 不持久化，也不提升全局成熟度。
- 生成默认使用获准的着装无五官身份图、指定服装图与表情 PNG；脸不可见的背面使用独立背面身份和服装覆盖，省略表情 PNG。Body Base 仅保留为本地证据，参考预览和生图输入均排除它及同图副本。每次生成必须先确认具体分析。

## 路由

先判断任务类型，再只读取该分支需要的资料。

### 新服装准备与混搭

用户要求添加、补全或组合服装时，读取 [服装准备流程](references/calibration/outfit-preparation.md)，通过 `scripts/outfit_preparation.py` 规划。局部图、商品图、其他人物穿着图和已发布套装均可提供指定部件；认可的组合发布为一套新的固定 Variant。

先完成只读素材分析和完整方案。确认设计与主图计划后才建立准备工作区；主图认可后集中确认其余视图；完整包对照检查通过并获用户认可后，才建立正式 Calibration staging 并发布。缺背面身份时先单独确认 `Identity Change`，通过 `scripts/identity_preparation.py` 标定，再冻结服装计划。候选图和检查记录保留于准备工作区，每张图最多自动修正两次，失败调用计数。

### Prompt 与 Generation Planning

修改已有成图（包括连续修改、修复摩尔纹/重影/糊边）时，先读取 [修订流程](references/core/revision-reference.md)，必须通过 `run_production_revision()`；不得把上一轮结果包装成普通参考后调用首次生成入口。传递完整修订上下文及视觉检查状态。正常回源优先保持构图；发现退化则排除问题成图并使用原始参考和累计要求重建。

1. 生成前必读 [分离参考与分析确认](references/core/reference-analysis.md)，按其中步骤看图、选图、编译、确认与验收。阅读 [模式](references/core/modes.md)、[权威与只读边界](references/core/authority-model.md)、[参考路由](references/core/reference-routing.md) 和 [Style Reference Contract](references/core/style-reference.md)。
2. 读取 `character/identity.yaml`、`variants/index.yaml`，以及用户选定 Variant/State 的 YAML；用户指定表情时额外读取正式 `character/expressions.yaml`，只接受 APPROVED Semantic 作为默认稳定语义。
3. 从 portrait、upper_body、full_body、back_view 中确定本轮 exposure profile；含糊且会改变必需字段时进入 Reviewer。
4. 按 [冲突规则](references/core/conflict-resolution.md) 解析 State、Identity Override 与外部参考；External Style Reference 额外遵循 [Style Brief Contract](references/core/style-brief.md) 的 request-scoped 边界。
5. 对已解析的 Style Reference 校验并绑定 Style Brief，按 Primary / Secondary / Official Style Baseline 和 User Axis Override 解析纯 Runtime `ResolvedStyleContext`。该 Context 只用于本次规划，不写回持久化资料。
6. 按 [Generation Runtime](references/core/generation-runtime.md) 解析模式与 Global/Request Reference Readiness；reference-conditioned 模式再读取 [Reference Selector](references/core/reference-selector.md)、[Image Input Builder](references/core/image-input-builder.md) 与 [Real Adapter](references/core/real-adapter.md)。
7. 按 [Prompt Compiler](references/core/prompt-compiler.md) 和目标 [模型 profile](references/profiles/neutral-zh.md) 编译；将 Resolver 最终产生的 `ResolvedStyleContext` 作为唯一 Style 输入，原始 Style Brief、Baseline 与 Override 不直接进入编译器。
8. 通过 [Quality Gate](references/core/quality-gate.md) 后输出 Prompt 或 Invocation Plan。语言与安全规则见 [language-safety.md](references/core/language-safety.md)。

真实生图返回后，查看原尺寸成图并记录身份、构图动作、表情、光影画风四项视觉检查。未达标可在已确认目标内自动修正一次；之后报告结果和偏差。新目标须重新确认，代理自评不等于用户验收。

### Calibration

只有用户明确要求“标定、入库、新增或更新角色资料”时进入此分支。

新增服装先走上面的准备分支；以下通用流程用于其他资料变更及其发布规则。

1. 阅读 [Calibration workflow](references/calibration/workflow.md)、[固有特征过滤](references/calibration/intrinsic-filtering.md) 和 [schema](references/calibration/schema.md)。
2. 分析图片并在对话中展示变更预览；确认前不写任何正式或 staging 文件。
3. 用户明确确认后，才建立 staging、登记资产、运行专用 validator 并通过恢复型发布脚本写入。
4. Identity Core 变更必须在预览中醒目标记 `Identity Change`。
5. 每次正式发布必须生成 History 与完成标记。

### Staging 隔离与未完成事务

普通 Prompt 只读取正式发布区，不扫描或加载 staging。开始新 Calibration、正式写操作、publication 或 recovery 时才检查 `calibration/staging/*/calibration-lock.yaml`；相同目标的活动锁阻止冲突 Calibration，任何未授权 publication 必须停止。事务中断时按 Calibration workflow 进入恢复流程。

## 模式

- Director：用户方向明确；低自由度补齐必要镜头、构图、光线和少量环境细节。
- Designer：用户没想好或要求方向；先给 2–3 个真正不同的方案，选择后才编译完整 Prompt。
- Reviewer：证据、组合或身份存在关键冲突；只问 1–3 个决定结果的问题。

用户明确指定模式时遵循指定；否则按 [modes.md](references/core/modes.md) 自动判断。

## 输出契约

### 作品保存

生成预览使用 `artwork_title` 展示简短中文主题；从用户已确认需求提取，用户指定名称时优先采用，不单独追问命名。把该字段交给生产入口；它只用于作品归档，不参与角色事实或参考权威。

首次生成、人工修订与自动修正会统一归档到 `作品/<主题>/<香港日期>_<批次>/`。结果的 `archive_image_path` 是面向用户的可读图片路径；`output_path`、`output_id` 与原始修订身份保持不变。向用户展示归档图片，同时链接作品索引；归档失败时明确报告 `archive_error` 并展示仍保留的原始工具图片。

外部原图副本放在“原始参考”，角色参考来源和哈希、请求、提示词、检查及版本关系放在“生成记录”。保留全部版本，失败稿单独收纳；自动检查通过不等于用户认可，不能自动标记定稿。检查结果通过 `with_reference_review()` 或 `with_visual_review()` 保存。

普通生图只读取正式资料，不扫描 `archive` 或 `scripts/fixtures` 作为生成参考。历史归档与测试夹具不能自动登记为角色证据。

Director 或已完成选择的 Designer 默认输出：

1. `【角色与参考解析】`：简述 Variant、State、所用 WHO 资料、继承的 HOW 信息、临时证据和 Identity Override。
2. `【可直接使用的完整 Prompt】`：一条自然、完整、可复制的 Prompt。

默认使用 `neutral-zh`。用户使用英文或明确要求英文时输出自然英文。未知模型降级到 `neutral-zh` 并说明未应用模型专属优化。只有 profile 明确支持独立 negative prompt 时才额外输出该区块。

Reviewer 不输出伪完成 Prompt；Designer 在方向尚未选择时不输出最终 Prompt。

生成预览必须展示实际所选阿尔可图片、外部图片、必须保留的身份和参考关系、允许调整之处，以及最终提示词。Reference-conditioned planning 还输出所选 Reference Contract、Global/Request Reference Readiness、Invocation Plan 与纯参数字典；真实生成只能把这些冻结结果交给 `ArcoRealAdapter`。Prompt-only 的参数字典只能包含 `prompt`。不得在运行时自动登记或批准 generation reference。

## 示例

需要查看完整交互样例时读取 [workflows.md](references/examples/workflows.md)。示例是虚拟流程，不是阿尔可事实。
