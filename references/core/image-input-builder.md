# Image Input Builder

Image Input Builder 是选图与图像生成工具之间的纯序列化边界。它只构造 Invocation Plan 和参数字典，不 import、持有或调用真实图像工具；真实调用只能经过 `ArcoRealAdapter`。

当前 Codex built-in interface 的已确认输入字段为：

```text
prompt: string
referenced_image_paths?: string[]
num_last_images_to_include?: integer
```

接口未暴露稳定的底层 model 字段，因此内部只使用 `provider: builtin_image_gen` 与 capability `reference_conditioned_image_generation`，不依赖 “image2.5” 名称。

全部选中图都有路径时使用 `referenced_image_paths`。只有全部选中图都能由最小、精确的近期会话图片集合表示，且不会夹带未选中图片时，才使用 `num_last_images_to_include`。两者互斥。

Prompt-only 参数必须只有：

```json
{"prompt": "..."}
```

不得用空数组、零或 null 代替字段缺失。`ArcoRealAdapter` 会再次校验计划、合同和路径，并只把这里生成的参数传给 `builtin_image_gen`。
