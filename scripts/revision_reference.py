"""Revision-only bridge from the frozen intent plan to production references."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from arco_production import ROOT, ProductionGenerationError, ProductionGenerationResult, run_production_generation
from arco_production import READABILITY_POLICY_PATH, _load_yaml
from arco_production import plan_production_generation, ProductionGenerationPlan
from composition_readability import ReadabilityPolicy, plan_composition_readability
from revision_intent import GeneratedOutputRole, RevisionPlan, RevisionType, SourceStrategy
from revision_lineage import ExecutionStrategy, GenerationLineage, choose_execution_strategy, direct_edit_lineage
from revision_stability import build_revision_stability_guard
from revision_context import advance_context, cumulative_prompt, without_image_numbers, VISUAL_STATUSES
from revision_intent import resolve_revision_intent


def _source_reset_request(
    source_request: Mapping[str, Any] | None,
    revision_request: Mapping[str, Any],
    revision_plan: RevisionPlan,
    selected_variant_id: str | None,
) -> dict[str, Any]:
    if not isinstance(source_request, Mapping):
        raise ProductionGenerationError("SOURCE_CONTEXT_REQUIRED", "Source Reset requires the canonical first-generation request.")
    source_prompt = source_request.get("base_prompt")
    revision_prompt = revision_request.get("base_prompt")
    if not isinstance(source_prompt, str) or not source_prompt.strip() or not isinstance(revision_prompt, str) or not revision_prompt.strip():
        raise ProductionGenerationError("SOURCE_CONTEXT_REQUIRED", "Canonical and revision prompts must be non-empty.")
    source_variant = source_request.get("variant_id")
    requested_variant = revision_request.get("variant_id")
    variants = {value for value in (source_variant, requested_variant, selected_variant_id) if value is not None}
    if len(variants) > 1:
        raise ProductionGenerationError("VARIANT_CONTEXT_CONFLICT", "Source and revision Variant contexts disagree.")
    reset_request = dict(source_request)
    reset_request["analysis_confirmation"] = revision_request.get("analysis_confirmation")
    reset_request["request_scoped_arco_references"] = []
    reset_request["variant_id"] = next(iter(variants), None)
    if revision_plan.requires_original_outfit and reset_request["variant_id"] is None:
        raise ProductionGenerationError("VARIANT_SELECTION_REQUIRED", "Formal Outfit authority requires the current Variant ID.")
    if revision_plan.requires_external_refs and not reset_request.get("external_references"):
        raise ProductionGenerationError("EXTERNAL_REFERENCE_REQUIRED", "Canonical External HOW reference is unavailable.")
    reset_request["base_prompt"] = (
        "Create a fresh image from the following original source request and formal references. "
        "Apply the requested revision to the new image. The previous output, if provided, "
        "is only a continuity and composition guide; do not edit its pixels or derive "
        "character identity or outfit from it.\n\nOriginal source request:\n"
        + without_image_numbers(source_prompt) + "\n\nRequested revision:\n" + revision_prompt
    )
    return reset_request


def run_production_revision(
    request: Mapping[str, Any],
    *,
    revision_plan: RevisionPlan,
    previous_output: Mapping[str, Any],
    source_request: Mapping[str, Any] | None = None,
    selected_variant_id: str | None = None,
    revision_context: Mapping[str, Any] | None = None,
    visual_review_status: str | None = None,
    builtin_image_gen: Callable[..., Any],
    root: Path = ROOT,
    _prepare_only: bool = False,
) -> ProductionGenerationResult | ProductionGenerationPlan:
    """Apply frozen Phase 1 reference requirements to an explicit revision."""
    if type(revision_plan) is not RevisionPlan:
        raise ProductionGenerationError("REVISION_PLAN_REQUIRED", "A frozen RevisionPlan is required.")
    if not isinstance(previous_output, Mapping):
        raise ProductionGenerationError("PREVIOUS_OUTPUT_INVALID", "Previous output must be a contract.")
    from artwork_archive import previous_title
    if "artwork_title" not in request:
        title = previous_title(root, previous_output.get("output_id"))
        if title:
            request = {**request, "artwork_title": title}
    parent = GenerationLineage.from_output(previous_output)
    status = visual_review_status if visual_review_status is not None else previous_output.get("visual_review_status", "unchecked")
    if not isinstance(status, str) or status not in VISUAL_STATUSES:
        raise ProductionGenerationError("VISUAL_REVIEW_INVALID", "Unknown visual review status.")
    detected = resolve_revision_intent(request.get("base_prompt", ""))
    degraded = status == "degraded" or previous_output.get("visual_review_status") == "degraded" or detected.generated_output_role is GeneratedOutputRole.EXCLUDED
    if degraded:
        revision_plan = replace(revision_plan, source_strategy=SourceStrategy.SOURCE_RESET,
                                generated_output_role=GeneratedOutputRole.EXCLUDED)
    strategy = choose_execution_strategy(parent, revision_plan)
    try:
        context = advance_context(previous_output, source_request, request, revision_context)
    except (TypeError, ValueError) as exc:
        raise ProductionGenerationError("REVISION_CONTEXT_INVALID", str(exc)) from exc
    canonical_source = context["source_request"]
    if strategy is ExecutionStrategy.SOURCE_RESET:
        if not canonical_source.get("base_prompt"):
            raise ProductionGenerationError("SOURCE_CONTEXT_REQUIRED", "Source Reset requires the canonical first-generation request.")
        if not context["history_complete"]:
            raise ProductionGenerationError("REVISION_HISTORY_REQUIRED", "Recover the complete ordered revision history before Source Reset.")
    stability_guard = build_revision_stability_guard(revision_plan, strategy, request.get("base_prompt"))
    try:
        policy = ReadabilityPolicy.from_document(
            _load_yaml(Path(root).resolve(), READABILITY_POLICY_PATH, label="composition readability policy")
        )
        readability_plan = plan_composition_readability(
            cumulative_prompt(context) if strategy is ExecutionStrategy.SOURCE_RESET else request.get("base_prompt"), policy,
            options=context["current_settings"].get("composition_readability"),
            source_text=canonical_source.get("base_prompt"),
            source_options=canonical_source.get("composition_readability"),
            allow_scale_change=strategy is ExecutionStrategy.SOURCE_RESET or revision_plan.revision_type in {RevisionType.COMPOSITION, RevisionType.MIXED},
        )
    except (TypeError, ValueError) as exc:
        raise ProductionGenerationError("READABILITY_PLAN_INVALID", str(exc)) from exc
    request_variant = request.get("variant_id")
    if selected_variant_id is not None:
        if not isinstance(selected_variant_id, str) or not selected_variant_id:
            raise ProductionGenerationError("VARIANT_SELECTION_REQUIRED", "Selected Variant must be a non-empty ID.")
        if request_variant is not None and request_variant != selected_variant_id:
            raise ProductionGenerationError("VARIANT_CONTEXT_CONFLICT", "Revision Variant conflicts with supplied context.")
    if strategy is ExecutionStrategy.DIRECT_EDIT and revision_plan.requires_original_outfit and not (request_variant or selected_variant_id):
        raise ProductionGenerationError("VARIANT_SELECTION_REQUIRED", "Formal Outfit authority requires the current Variant ID.")
    revision_request = dict(request)
    for key, value in context["current_settings"].items():
        revision_request[key] = value
    if revision_plan.requires_original_outfit and selected_variant_id is not None and request_variant is None:
        revision_request["variant_id"] = selected_variant_id
    if strategy is ExecutionStrategy.SOURCE_RESET:
        reset_revision = dict(revision_request, base_prompt=cumulative_prompt(context))
        effective_source = dict(canonical_source, **context["current_settings"])
        reset_request = _source_reset_request(effective_source, reset_revision, revision_plan, selected_variant_id)
        if degraded:
            bad_path = Path(previous_output["path"]).resolve()
            for key in ("external_references", "request_scoped_arco_references"):
                reset_request[key] = [ref for ref in reset_request.get(key, [])
                    if not (ref.get("path") and Path(ref["path"]).resolve() == bad_path)
                    and ref.get("visual_review_status") != "degraded"]
            if revision_plan.requires_external_refs and not reset_request.get("external_references"):
                raise ProductionGenerationError("EXTERNAL_REFERENCE_REQUIRED", "Required clean External HOW reference is unavailable.")
        # This is an execution projection, not a change to the frozen Phase 1 plan.
        reset_plan = revision_plan.as_dict()
        reset_plan["requires_original_identity"] = True
        reset_plan["requires_original_outfit"] = reset_request["variant_id"] is not None
        reset_plan["requires_external_refs"] = bool(reset_request.get("external_references"))
        if revision_plan.generated_output_role is not GeneratedOutputRole.EXCLUDED:
            reset_plan["generated_output_role"] = GeneratedOutputRole.COMPOSITION_ANCHOR.value
        result = (plan_production_generation if _prepare_only else run_production_generation)(
            reset_request, **({} if _prepare_only else {"builtin_image_gen": builtin_image_gen}), root=root,
            _revision_plan=reset_plan, _previous_output=previous_output,
            _source_reset=True, _revision_authorized=True,
            _readability_plan=readability_plan,
        )
        if _prepare_only:
            return result
        if result.output_id == parent.output_id:
            raise ProductionGenerationError("OUTPUT_INPUT_ALIAS", "Source Reset output must have a new output ID.")
        from artwork_archive import archive_result
        return archive_result(replace(result, reset_triggered_from_output=parent.output_id, revision_context=context), request, root, previous_output)
    if parent.generation_depth != 0:
        raise ProductionGenerationError("EDIT_DEPTH_EXCEEDED", "A second direct generated edit is prohibited.")
    if not (revision_plan.requires_original_identity or revision_plan.requires_original_outfit) and revision_plan.generated_output_role is GeneratedOutputRole.PRIMARY_EDIT_SOURCE:
        scoped = revision_request.get("request_scoped_arco_references") or []
        if not any(isinstance(ref, Mapping) and ref.get("reference_id") == previous_output.get("reference_id")
                   and ref.get("path") == previous_output.get("path") for ref in scoped):
            raise ProductionGenerationError("PREVIOUS_OUTPUT_REQUIRED", "Direct edit request must include its previous output.")
        if revision_plan.requires_external_refs and not revision_request.get("external_references"):
            raise ProductionGenerationError("EXTERNAL_REFERENCE_REQUIRED", "Required External HOW reference is unavailable.")
        result = (plan_production_generation if _prepare_only else run_production_generation)(revision_request,
                                           **({} if _prepare_only else {"builtin_image_gen": builtin_image_gen}), root=root,
                                           _revision_authorized=True,
                                           _revision_stability_guard=stability_guard,
                                           _readability_plan=readability_plan)
    else:
        result = (plan_production_generation if _prepare_only else run_production_generation)(
            revision_request,
            **({} if _prepare_only else {"builtin_image_gen": builtin_image_gen}),
            root=root,
            _revision_authorized=True,
            _revision_plan=revision_plan.as_dict(),
            _previous_output=previous_output,
            _revision_stability_guard=stability_guard,
            _readability_plan=readability_plan,
        )
    if _prepare_only:
        return result
    if result.output_id == parent.output_id:
        raise ProductionGenerationError("OUTPUT_INPUT_ALIAS", "Direct edit output must have a new output ID.")
    from artwork_archive import archive_result
    return archive_result(replace(result, revision_context=context, **direct_edit_lineage(parent)), request, root, previous_output)


def plan_production_revision(request, **options) -> ProductionGenerationPlan:
    """Freeze an exact revision preview without invoking the image provider."""
    options.pop("builtin_image_gen", None)
    return run_production_revision(request, builtin_image_gen=None, _prepare_only=True, **options)
