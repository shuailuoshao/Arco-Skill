# neutral-zh Profile

默认目标是模型中立的中文自然语言 Prompt。

- 语言：简洁、准确、自然，不写关键词墙。
- 结构：遵循 Prompt Compiler 顺序，但最终合并为连贯文本。
- 权重：Identity、Variant Must Keep、动作和构图锚点优先。
- 细节：只补足能控制画面的关系，不堆叠低价值形容词。
- 禁止项：嵌入主 Prompt 的一致性限制，不额外输出独立 Negative Prompt。
- 模型适配：用户指定未配置的模型时继续使用本 profile，并披露“未应用模型专属优化”。
- 英文请求：保持同一信息顺序和约束，输出自然英文，不逐词直译中文句法。

此 profile 不声称适配任何特定厂商的 `image2.5` 实现。未来增加模型 profile 时，只新增独立 profile 文件，不修改 Character Bible。
