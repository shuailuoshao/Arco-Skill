# Arco Real Adapter

`ArcoRealAdapter` is the only project boundary allowed to invoke the built-in
image generator. It consumes an already-frozen Invocation Plan, its ordered
Reference Contracts, and the same ordered reference image paths.

## Provider binding

The host injects a callable with this shape:

```python
def builtin_image_gen(*, prompt: str, referenced_image_paths: list[str]) -> object:
    ...
```

The callable returns a local output path, or a mapping containing one of
`path`, `file_path`, `output_path`, `image_path`, or
`generated_image_path`. The adapter does not know or import the host's MCP/UI
implementation.

## Preflight contract

Before the provider is called, the adapter verifies:

- provider, capability, and `reference_conditioned` mode;
- unique Invocation Plan reference IDs match Contract IDs in the same order;
- each Contract path matches both the plan and supplied path list;
- every Contract passes the existing Runtime contract validator;
- managed contracts are persistent published contracts;
- Body Base types, published evidence IDs/paths/hashes, and identical image
  copies are rejected even in old plans or request-scoped/external contracts;
- staging paths, missing files, disallowed layers, and runtime reference limits
  are rejected;
- every declared `do_not_inherit` field survives in the compiled prompt;
- only the documented built-in arguments are sent.

Any failure is fail-closed and happens before provider invocation where the
failure is detectable locally.

Recorded Body Base permissions remain part of the unchanged evidence registry.
The runtime upload policy excludes these assets independently of that metadata;
library validation continues to check the recorded permission structure.

## Output and mutation boundary

The provider creates the generated output. The adapter verifies that the result
is an existing regular file and is not one of the reference inputs, then
returns its resolved `Path`. It never copies, uploads, registers evidence,
modifies Character/Variant/Asset YAML, starts Calibration, or writes History.

正常生成与修订必须遵循 [分离参考、确认与视觉验收](reference-analysis.md)。先规划、展示具体预览、等待本轮用户确认，再调用；图片、提示词或目标变化使旧确认失效。

服装准备通过 `generate_preparation(invocation_plan, root, preparation_id)`，独立身份标定通过 `generate_identity_calibration(...)`。两条路径读取各自准备记录中的冻结计划、阶段确认和调用预约，复核实际文件、用途和最多五张输入；只允许已认可的主图作其余视图依据。它们不调用普通生产的 WHO 选择器，也不改变普通 `generate()` 的已发布参考规则。详细合同见 [服装准备流程](../calibration/outfit-preparation.md)。
