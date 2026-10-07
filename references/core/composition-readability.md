# Phase 5 Composition Readability

The gate runs before generation. It reads request text, optional `composition_readability` fields, the frozen `RevisionPlan` where applicable, and `runtime/composition-readability.yaml`. It never reads a generated image or changes generation strategy, reference authority, or Stability activation.

## Request and result contract

`composition_readability` is optional and accepts only `composition_priority`, `subject_frame_height_ratio`, `subject_scale`, and `character_detail_requirement`. Priority is one of `atmosphere`, `balanced`, `character_readability`; scale is one of `unknown`, `very_small`, `small`, `medium`, `close`; detail is `low`, `normal`, or `high`. The ratio is numeric in `(0, 1]`. Unknown fields, invalid values, and a ratio that conflicts with an explicit scale fail before provider invocation.
An explicit `low` or `normal` detail setting also fails if the same revision text explicitly requires high character readability.

`CompositionReadabilityPlan.as_dict()` emits `composition_priority`, `subject_scale`, `requested_frame_ratio`, `character_detail_requirement`, `scale_readability_conflict`, `recommended_subject_scale`, `recommended_frame_ratio`, `readability_guidance_enabled`, and `guidance`. A `null` conflict means scale is unknown; it does not assert that the request is readable. The production result exposes this plan through `composition_readability_plan`.

Structured inputs take precedence over recognized request phrases. Numeric frame-height percentages or Chinese tenths take precedence over discrete scale words. No exact ratio is inferred from vague prose. The source request supplies scale context only when the revision gives no numeric or discrete scale. A new revision's explicit scale supersedes source scale. For an ambiguous priority, `balanced` is the default. A clearly atmosphere-first request remains `atmosphere`; a clearly character-first request is `character_readability`. When a source prioritizes atmosphere but a revision requests a closer, clearer character, the revision is `balanced` unless it explicitly selects another priority.

The central policy defines `very_small < 0.15`, `small < 0.25`, `medium < 0.50`, and `close >= 0.50` by frame height. The preferred full-body minimum is `0.25` and the character-first planning target is `0.30`. These are planning thresholds, not perception measurements or mandatory crops. A high-detail request at a known scale below the preferred minimum creates a conflict. Merely mentioning a character does not create a high-detail request.

| Known scale and requirement | Priority | Conflict | Recommendation |
| --- | --- | --- | --- |
| Below 0.25, high detail | atmosphere | true | Preserve requested scale and negative space; disclose the detail trade-off. |
| Below 0.25, high detail | balanced | true | Move toward 0.25 while retaining environment. |
| Below 0.25, high detail | character_readability | true | Move toward 0.30. |
| At least 0.25, normal detail | any | false | Keep requested scale. |
| Unknown scale | any | null | Never invent a requested ratio; compile only an explicit readability goal. |

## Compiler and revision boundaries

`run_production_generation()` plans first-generation requests. `run_production_revision()` plans from the revision and optional canonical source request after Phase 3 chooses `DIRECT_EDIT` or `SOURCE_RESET`. The bridge passes the immutable plan to production and the Prompt Compiler. The Compiler places the optional `[Composition Readability]` block after the scene request and before Phase 4 Stability. It uses controlled composition guidance, never generic quality escalation.

For `DIRECT_EDIT`, scale adjustment is allowed only when the supplied Phase 1 revision type is `composition` or `mixed`. Phase 4 still preserves unrelated content. For `SOURCE_RESET`, the source and revision texts are planned separately, the formal Source Truth remains authoritative, and direct-edit Stability remains absent. The gate never selects an execution strategy, changes generation depth, or changes WHO, Variant, External HOW, or Previous Output authority.

The frozen case-03 request specifies a character at roughly 40% of frame height and asks for a relatively clear silhouette. Its Phase 5 plan records `atmosphere`, `medium`, `normal`, no conflict, no enlargement, and a short silhouette instruction. This is a structural comparison; no image is generated or judged.

Phase 5R closes the upstream vocabulary gap: the Phase 1 resolver classifies `人物往近一点，让脸清楚` as `mixed` and preserves the identity requirement. Phase 5 consumes that plan through the existing revision bridge; its scale policy and Prompt Compiler contract remain unchanged.
