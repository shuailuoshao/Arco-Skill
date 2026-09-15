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
- staging paths, missing files, disallowed layers, and runtime reference limits
  are rejected;
- every declared `do_not_inherit` field survives in the compiled prompt;
- only the documented built-in arguments are sent.

Any failure is fail-closed and happens before provider invocation where the
failure is detectable locally.

## Output and mutation boundary

The provider creates the generated output. The adapter verifies that the result
is an existing regular file and is not one of the reference inputs, then
returns its resolved `Path`. It never copies, uploads, registers evidence,
modifies Character/Variant/Asset YAML, starts Calibration, or writes History.
