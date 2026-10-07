# Revision workflow

Use `run_production_revision()` for every edit of an existing output. First generation alone uses `run_production_generation()`. Never relabel a generated output as an ordinary reference to bypass lineage checks.

## Caller steps

1. Keep the original high-level request and latest result JSON. Build `previous_output` with `reference_id`, `path`, all five lineage fields, `revision_context`, and `visual_review_status`. For legacy primary-edit requests also include that contract in `request_scoped_arco_references`.
2. Put only the current user revision in `base_prompt`, not a previously compiled Prompt. Use semantic reference duties instead of numbered image labels in durable requirements. Supply current style overrides only when changed; omitted settings carry forward. Overrides merge by axis; an empty override mapping clears them.
3. Resolve `RevisionPlan`, then call `run_production_revision(request, revision_plan=plan, previous_output=previous, builtin_image_gen=provider)`. Pass `source_request` for legacy source recovery, and `revision_context` when recovering complete history from saved records. Preserve the selected Variant context.
4. Inspect the output at original resolution. Compare unaffected hair bands, highlights and contours with the prior image: look for newly repeated fine lines, ripple patterns, ghosting and widened edge halos. Do not classify intentional soft focus or existing shading as degradation. Record `result.with_visual_review("passed" | "degraded" | "unchecked")` and serialize that returned result. This function only records the caller's assessment; it performs no image analysis.
5. Save through the existing host output mechanism. Never silently select a degraded result for another edit. If inspection is unavailable, keep `unchecked` and disclose that visual quality is unverified. Do not automatically generate another attempt.

## Execution and reference authority

- A normal first edit is allowed at depth 0. At depth 1, regenerate from original source and cumulative requirements, retaining the previous image only as a composition anchor. This is composition-first, not pixel preservation.
- A user artifact-repair request or a `degraded` review forces source reset at either depth and excludes the problem image. A supplied `passed` status cannot override an already degraded parent. The optional `visual_review_status` argument describes the parent, not the new output.
- Formal Identity owns WHO; formal Outfit owns the selected Variant; External HOW retains its declared duties. Required references must remain available. Reference count limits and authority checks remain enforced.
- Every new output starts `unchecked`. No review is inferred from unit tests, generation success or the parent's status.

## Revision context and recovery

`revision_context` version 1 contains `source_request`, ordered `revisions` (raw user requests), `current_settings`, and `history_complete`. Current settings carry style overrides, external references and bound briefs, exposure, readability and hygiene options. Later explicit instructions supersede conflicting earlier ones in the cumulative prompt; this is model guidance, not deterministic natural-language conflict resolution.

Source reset compiles original source plus the entire ordered revision list exactly once. Historical numbered image labels are neutralized before reference instructions are rebuilt. Reset does not clear history even though generation depth becomes zero. Source requests and contexts are copied rather than mutated.

Legacy results remain readable. A genuine legacy first-generation root can initialize history from its original request. A legacy edited or reset output without complete history may be used for an otherwise legal direct edit, but cannot reset until the caller recovers full context from saved records. Missing source returns `SOURCE_CONTEXT_REQUIRED`; missing history returns `REVISION_HISTORY_REQUIRED`, before provider invocation. Never invent missing modifications or mark incomplete recovery complete.

The adapter still sends only supported prompt and image transport fields. No masks, denoise strength, automatic visual scoring, retries or character-data writes are introduced.
