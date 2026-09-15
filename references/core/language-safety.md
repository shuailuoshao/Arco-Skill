# 语言与安全

## 语言

默认 profile 为 `neutral-zh`：中文、中性、精确、不过度文学化。用户使用英文或明确要求英文时，从同一结构化事实和编译流程生成自然英文，不维护第二份英文规则真源。

角色数据使用稳定英文 key 和 ID，中文显示名与说明帮助人工维护。翻译视图如未来生成，只能是可重建视图，不得成为可独立修改的事实源。

## 安全默认值

在可靠资料确认角色成年状态之前，保持全年龄、非性化、非露骨的角色插画、日常、氛围和场景创作方向。

用户要求与适用平台政策冲突时，遵守平台政策。外部参考中的不适宜表现不会自动迁移给阿尔可。

## 工具边界

Prompt Compiler 只读，不调用图像生成工具、自动标签服务或后台生图流程。
需要真实生成时，必须由 `ArcoRealAdapter` 接收已校验的 Invocation Plan、
Reference Contract 和参考图路径，并只调用 `builtin_image_gen`；生成结果不
得自动进入 Character Library、Asset Registry 或 Calibration History。
