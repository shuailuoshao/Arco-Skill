# Style-aware Rendering Hygiene

Rendering Hygiene is a style-relative guardrail. It protects the resolved target from unsupported rendering inflation or drift; it does not define a target style or add a second Style compiler.

## Authority and boundary

Rendering authority is ordered as follows:

1. Explicit user requests;
2. `ResolvedStyleContext`;
3. Rendering Hygiene.

Hygiene may constrain only rendering behavior that has no support in the explicit request or resolved Style. It must never suppress a rendering characteristic supported by either. Its escape clause is emitted in every active Hygiene block.

Hygiene is not a `ResolvedStyleContext` field or a Style Axis. It does not own WHO, alter Identity / Variant / State, change resolved axes or provenance, or reinterpret the Style Brief. The compiler uses controlled relative language and does not classify free-text Style descriptions.

Hygiene addresses only unsupported rendering inflation or drift. It does not inspect references, re-resolve Style, call a model, access the network, or write to disk. It does not handle anatomy, hands, geometry, perspective, object structure, or other structural artifacts.

## V1.1 axis-bound rule families

Rules activate only from exact keys present in `ResolvedStyleContext.resolved_axes`. The compiler never searches descriptions, scene text, reference metadata, or other free text for keywords. Every active rule includes the normalized description of each resolved axis that activated it.

| Rule family | Required resolved axis |
|---|---|
| `unsupported_detail_inflation` | `detail_density` |
| `highlight_organization_drift` | `highlight_language` |
| `texture_noise_drift` | `texture_language` |
| `material_rendering_drift` | `material_rendering` |
| `lighting_effect_inflation` | `lighting_language` |
| `detail_hierarchy_flattening` | `detail_density` or `background_rendering` |

If none of a rule's required axes are present, that rule emits nothing. If no enabled rule is axis-eligible, the complete Hygiene block is omitted.

Highlight, texture, and material rules bind directly to their respective resolved descriptions. Texture instructions explicitly preserve intentional watercolor, pigment, paper, grain, brush, and related texture when those characteristics occur in the resolved target.

Lighting uses relational language: preserve the resolved target and its exposure balance, and do not intensify or spatially expand secondary lighting effects beyond that target. It does not introduce named effects such as bloom, rim light, or volumetric glow; those terms appear only if the resolved `lighting_language` description already contains them.

Detail hierarchy is not a generic detail-reduction command. It preserves the relative subject, secondary-element, and background hierarchy supported by the available `detail_density` and/or `background_rendering` descriptions and does not globally raise or lower detail density.

These rules are not global bans and do not emit a negative-prompt list. Supported grain, texture, gloss, highlights, lighting, and painterly rendering remain valid when present in the resolved Style or explicit user request.

## Policy and compiler

`runtime/style-policy.yaml` is the V1.1 policy. It uses integer `schema_version: 2`, an optional `policy_id`, and one closed rule entry for each registered family:

```yaml
enabled: true
requires:
  any_of:
    - canonical_style_axis
```

`requires.any_of` must be a non-empty, duplicate-free list of canonical Style Axis keys. Missing or malformed entries, unknown axes, and duplicate axes fail closed. Unknown family or rule fields raise `RENDERING_HYGIENE_UNSUPPORTED_RULE`.

`compile_rendering_hygiene(style_context, *, policy) -> str` is pure and deterministic. It receives an already resolved context and a caller-supplied policy mapping. It does not load this YAML itself, modify context data, or infer axis presence or allow/deny attributes from description text. It reads an active axis description only after the structured axis key satisfies a rule requirement. An all-disabled or all-ineligible policy compiles to an empty string.

## Prompt integration and quality gate

`compile_prompt(..., rendering_hygiene_policy=None)` keeps Hygiene opt-in. With at least one enabled rule and a resolved Style Context, the prompt order is:

```text
Identity facts → Resolved Style → Reference duties → Base scene → Rendering Hygiene → Identity soft constraints
```

`validate_rendering_hygiene(style_context, compiled_prompt, *, policy)` requires exactly one controlled Hygiene block when any rule is enabled, rejects WHO pollution, and compares the block with the compiler's registered template. Stable errors include `RENDERING_HYGIENE_MISSING`, `RENDERING_HYGIENE_STYLE_CONFLICT`, `RENDERING_HYGIENE_IDENTITY_POLLUTION`, and `RENDERING_HYGIENE_UNSUPPORTED_RULE`.

The V1.1 gate does not use NLP to detect semantic contradictions in arbitrary prose. It prevents conflicts in generated Hygiene through controlled axis-bound templates and exact block validation; this is not a general-purpose natural-language conflict detector.

## Provider boundary

Hygiene is compiled into the prompt before the existing Adapter boundary. It adds no provider fields, references, image inputs, or transport behavior. Reference limits remain unchanged.

Batch 4A validates prompts and snapshots only. Real image generation and visual regression belong to a later batch.
