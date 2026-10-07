# Style Transfer V1.0 Batch 3

## Goal and boundary

- Compile the existing `ResolvedStyleContext` into a deterministic Style block and validate that block in the final Prompt.
- Preserve Batch 1/2 resolution, Reference limits, Adapter implementation, Provider schema, image transport, and all Batch 4 exclusions.

## Decisions and result

- `compile_style_instructions()` consumes resolved axes and protected identity metadata only, emits canonical axis order, and omits confidence/provenance from model-facing text.
- `compile_prompt(style_context=None)` preserves the legacy path when no Style Reference exists; Style References fail closed without Context. With Context, order is Identity → Style → Reference duties → Scene → Identity soft constraints.
- Style References are named by source responsibility; axis descriptions stay in the Style block. Color logic receives an intrinsic identity color scope guard.
- `validate_style_prompt()` checks compiled/missing/undeclared axes, axis order, color protection, WHO pollution, and unused Style Context. Reference/Context provenance mismatch fails closed.
- Added External Primary, Primary + Secondary + User Override, and Official Fallback prompt snapshots plus Runtime and Adapter-boundary regressions.

## Validation

- `python -m unittest discover -s scripts -p "test_*.py"`: 140 tests, 0 failures, 0 errors.
- `python -m py_compile scripts/reference_runtime.py scripts/arco_real_adapter.py`: PASS.
- Manual snapshot review: Clean Cel preserved only declared axes; painterly shading/texture/edge behavior survived while the Primary warm-lighting axis was replaced only by the cold blue User Override, with intrinsic color guard intact; Official Fallback contained resolved baseline axes without external-source wording.
- `scripts/arco_real_adapter.py`, Provider schema, and Rendering Hygiene were not changed/implemented.
