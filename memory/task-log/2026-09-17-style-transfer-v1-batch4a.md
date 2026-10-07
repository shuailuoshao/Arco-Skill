# Style Transfer V1.0 — Batch 4A

## Goal and boundary

- Add an opt-in, style-relative Rendering Hygiene layer after the base scene prompt.
- Preserve Batch 3 Style-only prompts and snapshots byte-for-byte.
- Do not generate images or implement visual regression, image scoring, structural checks, automatic repair, or provider retry behavior.

## Decisions and result

- Added a V1 YAML policy with six registered rule families; all are enabled in the default policy. Unknown families and malformed policies fail closed.
- Added pure `compile_rendering_hygiene(style_context, *, policy)` and `validate_rendering_hygiene(style_context, compiled_prompt, *, policy)` APIs.
- `compile_prompt(..., rendering_hygiene_policy=None)` keeps Hygiene opt-in. When enabled, Hygiene appears after the scene and before Identity soft constraints.
- Hygiene uses fixed relative clauses and an explicit escape clause. The gate validates the generated template exactly and reuses WHO token protection; it does not attempt broad NLP semantic-conflict detection.
- Added side-by-side Style + Hygiene snapshots for External Primary, Primary + Secondary + User Override, and Official Fallback. Existing Style-only snapshots remain unchanged.
- `ResolvedStyleContext`, Style Brief schema, `character/style-baseline.yaml`, Adapter, Provider schema, transport, and reference limits were not changed by Batch 4A.

## Validation

- Focused Runtime tests: 86/86 PASS.
- Full unittest discovery: 158 tests, 0 failures, 0 errors.
- `python -m py_compile scripts/reference_runtime.py scripts/arco_real_adapter.py`: PASS.
- Prompt review: Clean Cel retained clean linework, restrained cel shading, grouped highlights, and low texture; Painterly retained brush texture and soft edges; Watercolor / Grain retained paper texture and grain. No global texture, grain, gloss, highlight, bloom, or rim-light ban was added.
- Real image generation: NOT PERFORMED.
- Known gate boundary: arbitrary custom prose is not semantically classified; the generated Hygiene block is protected by the fixed template and exact comparison.

## Batch 4B entry

- Use the three Style-only / Style + Hygiene snapshot pairs as the controlled prompt ablation inputs for the future visual regression batch. Keep any image generation and visual review within that separately authorized batch.
