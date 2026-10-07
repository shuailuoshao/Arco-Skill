# Phase 4 Revision Stability Guard

`run_production_revision()` consumes the frozen Phase 1 `RevisionPlan` and the Phase 3 execution decision. Only `DIRECT_EDIT` constructs a `RevisionStabilityGuard`; first generation and `SOURCE_RESET` compile without one. The guard does not choose an execution strategy or inspect images.

The frozen guard has `enabled`, `execution_scope`, `requested_scope`, `preserve_unaffected_regions`, `protect_low_frequency_regions`, and `avoid_revision_artifacts`. `as_dict()` exposes these in fixed order. Scope incorporates the normalized current request and the existing revision type; it does not classify the request again.

One scope-aware contract allows requested scene, character-detail, composition, style, or mixed changes while preserving unrelated content. Composition may change geometry and style may change rendering. Smooth backgrounds, gradients, blur, flat-color fields, soft lighting, haze, shadows, and glow remain stable where unaffected; unrequested detail, ripple, moire, and repeated texture are discouraged. This is visual guidance, not pixel identity.

The Prompt Compiler places a delimited Revision Stability block after the revision request and before optional Rendering Hygiene and Identity soft constraints. Reference duties and resolved Style precede the request. Formal WHO, Variant, and External HOW authority remain upstream and take precedence. `SOURCE_RESET` retains its Phase 3 fresh-source prompt and never receives this direct-edit block.
