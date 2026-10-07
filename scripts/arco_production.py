#!/usr/bin/env python3
"""Production Style Transfer generation entrypoint.

This module is the normal Arco Skill orchestration boundary.  It composes the
already validated reference runtime and real adapter; it does not contain an
experiment runner, manifest, retry loop, visual evaluation, or evidence writer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from copy import deepcopy
from revision_context import first_context, is_previous_output, VISUAL_STATUSES
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import yaml
from artwork_archive import archive_result, artwork_title, sync_review

from arco_real_adapter import ArcoRealAdapter
from composition_readability import CompositionReadabilityPlan, ReadabilityPolicy, plan_composition_readability
from reference_runtime import (
    REFERENCE_ROLES,
    ReferenceRuntimeError,
    build_invocation_plan,
    compile_prompt,
    compute_request_reference_readiness,
    resolve_style_context,
    resolve_style_references,
    select_references,
    validate_generation_reference_input,
)
from reference_analysis import (select_split_references, validate_analysis,
    compile_analysis, freeze_analysis, validate_confirmation, validate_visual_review)


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_CONFIG_PATH = Path("runtime/production.yaml")
GENERATION_CONFIG_PATH = Path("runtime/generation.yaml")
IDENTITY_PATH = Path("character/identity.yaml")
ASSETS_PATH = Path("character/assets.yaml")
VARIANTS_PATH = Path("variants/index.yaml")
STYLE_BASELINE_PATH = Path("character/style-baseline.yaml")
HYGIENE_POLICY_PATH = Path("runtime/style-policy.yaml")
READABILITY_POLICY_PATH = Path("runtime/composition-readability.yaml")

DEFAULT_REQUESTED_ROLES = ("identity_reference",)
VALID_HYGIENE_MODES = frozenset({"off", "hygiene_v11"})
ALLOWED_REQUEST_KEYS = frozenset(
    {
        "base_prompt",
        "exposure_profile",
        "variant_id",
        "arco_references",
        "request_scoped_arco_references",
        "external_references",
        "style_briefs",
        "user_style_overrides",
        "allow_uncertain_working",
        "rendering_hygiene",
        "composition_readability",
        "reference_analysis",
        "analysis_confirmation",
        "artwork_title",
    }
)


class ProductionGenerationError(ReferenceRuntimeError):
    """A stable production request/configuration error."""


def _error(code: str, message: str) -> None:
    raise ProductionGenerationError(code, message)


def _load_yaml(root: Path, relative: Path, *, label: str) -> dict[str, Any]:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        _error("PRODUCTION_CONFIG_INVALID", f"{label} escapes the production root.")
    if not path.is_file():
        _error("PRODUCTION_CONFIG_INVALID", f"Missing {label}: {relative.as_posix()}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        _error("PRODUCTION_CONFIG_INVALID", f"Could not read {label}: {exc}")
    if not isinstance(value, dict):
        _error("PRODUCTION_CONFIG_INVALID", f"{label} must be a mapping.")
    return value


def _sequence(value: Any, *, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        _error("MALFORMED_GENERATION_PLAN", f"{field} must be a list.")
    return list(value)


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _error("MALFORMED_GENERATION_PLAN", f"{field} must be a mapping.")
    return value


def _validate_production_config(config: Mapping[str, Any]) -> None:
    production = config.get("production")
    if not isinstance(production, Mapping):
        _error("PRODUCTION_CONFIG_INVALID", "Production config is missing its production mapping.")
    style_transfer = production.get("style_transfer")
    hygiene = production.get("rendering_hygiene")
    if not isinstance(style_transfer, Mapping) or style_transfer.get("default") != "enabled":
        _error("PRODUCTION_CONFIG_INVALID", "Production Style Transfer default must be enabled.")
    if not isinstance(hygiene, Mapping) or hygiene.get("default") != "disabled":
        _error("PRODUCTION_CONFIG_INVALID", "Production Rendering Hygiene default must be disabled.")
    if hygiene.get("experimental_opt_in") != "hygiene_v11":
        _error("PRODUCTION_CONFIG_INVALID", "Production Hygiene opt-in must be hygiene_v11.")


def _normalize_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        _error("MALFORMED_GENERATION_PLAN", "Production request must be a mapping.")
    unknown = sorted(set(request) - ALLOWED_REQUEST_KEYS)
    if unknown:
        _error(
            "MALFORMED_GENERATION_PLAN",
            f"Experiment or unsupported request fields are not accepted: {unknown}",
        )
    base_prompt = request.get("base_prompt")
    if not isinstance(base_prompt, str) or not base_prompt.strip():
        _error("INVALID_PROMPT", "base_prompt must be non-empty text.")
    profile = request.get("exposure_profile", "upper_body")
    if not isinstance(profile, str) or not profile:
        _error("INVALID_EXPOSURE_PROFILE", str(profile))
    hygiene = request.get("rendering_hygiene", "off")
    if hygiene not in VALID_HYGIENE_MODES:
        _error("INVALID_RENDERING_HYGIENE_MODE", str(hygiene))
    variant_id = request.get("variant_id")
    if variant_id is not None and (not isinstance(variant_id, str) or not variant_id.strip()):
        _error("MALFORMED_GENERATION_PLAN", "variant_id must be a non-empty string when supplied.")
    allow_uncertain_working = request.get("allow_uncertain_working", False)
    if "artwork_title" in request and (not isinstance(request["artwork_title"], str) or not request["artwork_title"].strip()):
        _error("MALFORMED_GENERATION_PLAN", "artwork_title must be non-empty text.")
    if type(allow_uncertain_working) is not bool:
        _error("MALFORMED_GENERATION_PLAN", "allow_uncertain_working must be boolean.")
    analysis = deepcopy(request.get("reference_analysis"))
    if isinstance(analysis, dict):
        identity_analysis = analysis.setdefault("identity", {})
        if isinstance(identity_analysis, dict) and "body_reference_mode" not in identity_analysis:
            identity_analysis.update(
                body_reference_mode="clothed_only",
                body_reference_reason="Default approved clothed identity reference; Body Base is local-only.")
    return {
        "base_prompt": base_prompt,
        "exposure_profile": profile,
        "variant_id": variant_id,
        "arco_references": _sequence(request.get("arco_references"), field="arco_references"),
        "request_scoped_arco_references": _sequence(
            request.get("request_scoped_arco_references"),
            field="request_scoped_arco_references",
        ),
        "external_references": _sequence(
            request.get("external_references"),
            field="external_references",
        ),
        "style_briefs": request.get("style_briefs", []),
        "user_style_overrides": request.get("user_style_overrides"),
        "allow_uncertain_working": allow_uncertain_working,
        "rendering_hygiene": hygiene,
        "composition_readability": request.get("composition_readability"),
        "reference_analysis": analysis,
        "analysis_confirmation": request.get("analysis_confirmation"),
    }


def _managed_selection(
    *,
    request: Mapping[str, Any],
    all_assets: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[str]]:
    descriptors = list(request["arco_references"])
    if descriptors and not all(isinstance(item, Mapping) for item in descriptors):
        _error("MALFORMED_GENERATION_PLAN", "arco_references must contain mappings.")

    if descriptors:
        by_id = {
            str(asset.get("asset_id")): asset
            for asset in all_assets
            if asset.get("asset_id") is not None
        }
        selected_assets: list[Mapping[str, Any]] = []
        roles: list[str] = []
        for descriptor in descriptors:
            asset_id = descriptor.get("asset_id")
            role = descriptor.get("role")
            if not isinstance(asset_id, str) or not asset_id:
                _error("MALFORMED_GENERATION_PLAN", "Managed Arco references require asset_id.")
            if not isinstance(role, str) or role not in REFERENCE_ROLES:
                _error("INVALID_REFERENCE_ROLE", str(role))
            if asset_id not in by_id:
                _error("REFERENCE_ASSET_NOT_FOUND", asset_id)
            validate_generation_reference_input(by_id[asset_id])
            selected_assets.append(by_id[asset_id])
            if role not in roles:
                roles.append(role)
        return selected_assets, roles

    return list(all_assets), []


def _reference_roles(
    *,
    managed_roles: Sequence[str],
    request_scoped: Sequence[Mapping[str, Any]],
    variant_id: str | None,
) -> list[str]:
    roles = list(managed_roles)
    scoped_roles: set[str] = set()
    for reference in request_scoped:
        if not isinstance(reference, Mapping):
            _error("MALFORMED_GENERATION_PLAN", "request_scoped_arco_references must contain mappings.")
        role = reference.get("role")
        if not isinstance(role, str) or role not in REFERENCE_ROLES:
            _error("INVALID_REFERENCE_ROLE", str(role))
        scoped_roles.add(role)
    roles = [role for role in roles if role not in scoped_roles]
    if not roles and not scoped_roles:
        roles.extend(DEFAULT_REQUESTED_ROLES)
    if variant_id is not None and "outfit_reference" not in roles and "outfit_reference" not in scoped_roles:
        roles.append("outfit_reference")
    return roles


def _copy_contracts(value: Sequence[Any], *, field: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            _error("MALFORMED_GENERATION_PLAN", f"{field} must contain mappings.")
        result.append(dict(item))
    return result


@dataclass(frozen=True)
class ProductionGenerationResult:
    """The frozen runtime result returned by the production entrypoint."""

    prompt: str
    style_context: Mapping[str, Any]
    selected_references: tuple[Mapping[str, Any], ...]
    invocation_plan: Mapping[str, Any]
    output_path: Path
    output_id: str
    generation_depth: int
    parent_output: str | None
    source_generation_id: str
    reset_triggered_from_output: str | None
    revision_context: Mapping[str, Any] | None = None
    visual_review_status: str = "unchecked"
    composition_readability_plan: CompositionReadabilityPlan | None = None
    analysis_preview: Mapping[str, Any] | None = None
    visual_review: Mapping[str, Any] | None = None
    automatic_repair_count: int = 0
    archive_image_path: Path | None = None
    archive_record_path: Path | None = None
    archive_error: str | None = None

    def with_reference_review(self, review: Mapping[str, Any]) -> ProductionGenerationResult:
        if not self.analysis_preview:
            _error("VISUAL_REVIEW_INVALID", "Result has no frozen analysis.")
        checked = validate_visual_review(review, output_path=self.output_path, frozen=self.analysis_preview)
        status = {"PASS": "passed", "FAIL": "degraded", "UNVERIFIED": "unchecked"}[checked["status"]]
        return sync_review(replace(self, visual_review=checked, visual_review_status=status))

    def with_visual_review(self, status: str) -> ProductionGenerationResult:
        """Record a caller review; no automatic image scoring or retries."""
        if not isinstance(status, str) or status not in VISUAL_STATUSES:
            raise ProductionGenerationError("VISUAL_REVIEW_INVALID", "Unknown visual review status.")
        if self.analysis_preview and status != "unchecked":
            _error("VISUAL_REVIEW_INVALID", "Use with_reference_review() for a bound, per-dimension review.")
        return sync_review(replace(self, visual_review_status=status))

    def as_dict(self) -> dict[str, Any]:
        return {
            "revision_context": deepcopy(self.revision_context),
            "visual_review_status": self.visual_review_status,
            "prompt": self.prompt,
            "style_context": dict(self.style_context),
            "selected_references": [dict(item) for item in self.selected_references],
            "invocation_plan": dict(self.invocation_plan),
            "output_path": str(self.output_path),
            "output_id": self.output_id,
            "generation_depth": self.generation_depth,
            "parent_output": self.parent_output,
            "source_generation_id": self.source_generation_id,
            "reset_triggered_from_output": self.reset_triggered_from_output,
            "composition_readability_plan": self.composition_readability_plan.as_dict() if self.composition_readability_plan else None,
            "analysis_preview": deepcopy(self.analysis_preview),
            "visual_review": deepcopy(self.visual_review),
            "automatic_repair_count": self.automatic_repair_count,
            "archive_image_path": str(self.archive_image_path) if self.archive_image_path else None,
            "archive_record_path": str(self.archive_record_path) if self.archive_record_path else None,
            "archive_error": self.archive_error,
        }


@dataclass(frozen=True)
class ProductionGenerationPlan:
    prompt: str
    style_context: Mapping[str, Any]
    selected_references: tuple[Mapping[str, Any], ...]
    invocation_plan: Mapping[str, Any]
    composition_readability_plan: CompositionReadabilityPlan
    analysis_preview: Mapping[str, Any] | None
    artwork_title: str = "阿尔可创作"

    def as_dict(self) -> dict[str, Any]:
        return {"prompt": self.prompt, "style_context": deepcopy(self.style_context),
                "selected_references": deepcopy(list(self.selected_references)),
                "invocation_plan": deepcopy(self.invocation_plan),
                "composition_readability_plan": self.composition_readability_plan.as_dict(),
                "analysis_preview": deepcopy(self.analysis_preview), "artwork_title": self.artwork_title}


def plan_production_generation(
    request: Mapping[str, Any],
    *,
    root: Path = ROOT,
    _revision_plan: Mapping[str, Any] | None = None,
    _previous_output: Mapping[str, Any] | None = None,
    _source_reset: bool = False,
    _revision_authorized: bool = False,
    _revision_stability_guard: Any = None,
    _readability_plan: CompositionReadabilityPlan | None = None,
) -> ProductionGenerationPlan:
    """Resolve, compile and freeze one request without calling a provider."""

    root = Path(root).resolve()
    if _revision_stability_guard is not None:
        from revision_stability import RevisionStabilityGuard
        if type(_revision_stability_guard) is not RevisionStabilityGuard or _source_reset:
            _error("REVISION_STABILITY_SCOPE", "Stability requires a direct-edit revision.")
    normalized = _normalize_request(request)
    try:
        readability_policy = ReadabilityPolicy.from_document(
            _load_yaml(root, READABILITY_POLICY_PATH, label="composition readability policy")
        )
        readability_plan = _readability_plan or plan_composition_readability(
            normalized["base_prompt"], readability_policy,
            options=normalized["composition_readability"],
        )
        if _readability_plan is not None and type(_readability_plan) is not CompositionReadabilityPlan:
            raise ValueError("_readability_plan must be CompositionReadabilityPlan.")
    except (TypeError, ValueError) as exc:
        _error("READABILITY_PLAN_INVALID", str(exc))
    production_config = _load_yaml(root, PRODUCTION_CONFIG_PATH, label="production config")
    _validate_production_config(production_config)
    generation_document = _load_yaml(root, GENERATION_CONFIG_PATH, label="generation config")
    generation_config = generation_document.get("generation")
    if not isinstance(generation_config, Mapping):
        _error("PRODUCTION_CONFIG_INVALID", "Generation config is missing its generation mapping.")
    if generation_config.get("split_reference_selection") and generation_config.get("reference_analysis_required") is not True:
        _error("PRODUCTION_CONFIG_INVALID", "Split generation requires reference analysis and confirmation.")
    identity = _load_yaml(root, IDENTITY_PATH, label="Identity")
    assets_document = _load_yaml(root, ASSETS_PATH, label="asset registry")
    all_assets = assets_document.get("assets")
    if not isinstance(all_assets, list):
        _error("PRODUCTION_CONFIG_INVALID", "Asset registry must contain an assets list.")
    # Loading the published Variant Index is an explicit production gate even
    # when the current request does not select a Variant.
    variants_document = _load_yaml(root, VARIANTS_PATH, label="Variant index")
    if not isinstance(variants_document.get("variants"), list):
        _error("PRODUCTION_CONFIG_INVALID", "Variant index must contain a variants list.")
    variant_definition = None
    variant_path = None
    if normalized["variant_id"]:
        entry = next((item for item in variants_document["variants"] if item.get("variant_id") == normalized["variant_id"]), None)
        if entry is None or entry.get("lifecycle_status") != "published":
            _error("UNPUBLISHED_VARIANT", "Select one published whole-outfit Variant.")
        variant_path = Path(entry["path"])
        variant_definition = _load_yaml(root, variant_path, label="selected Variant definition")
        if variant_definition.get("variant_id") != normalized["variant_id"] or variant_definition.get("lifecycle_status") != "published":
            _error("UNPUBLISHED_VARIANT", "Variant definition does not match the published selection.")
        if variant_definition.get("design_definition") is not None:
            from outfit_design import validate_approved_design, require_completed_calibration
            from reference_analysis import file_hash
            validate_approved_design(variant_definition)
            require_completed_calibration(root, variant_definition, code="UNPUBLISHED_VARIANT")
            normalized["variant_definition_sha256"] = file_hash(root / variant_path)
    baseline = _load_yaml(root, STYLE_BASELINE_PATH, label="Official Style Baseline")

    managed_assets, managed_roles = _managed_selection(request=normalized, all_assets=all_assets)
    scoped = _copy_contracts(
        normalized["request_scoped_arco_references"],
        field="request_scoped_arco_references",
    )
    external = _copy_contracts(normalized["external_references"], field="external_references")
    if not _revision_authorized and any(is_previous_output(ref) for ref in [*scoped, *external]):
        _error("REVISION_ENTRY_REQUIRED", "Previous outputs must use run_production_revision().")
    if any(ref.get("visual_review_status") == "degraded" for ref in [*scoped, *external]):
        _error("DEGRADED_REFERENCE", "A degraded output cannot be a generation reference.")
    if _revision_plan is not None:
        if _previous_output is None:
            _error("PREVIOUS_OUTPUT_REQUIRED", "Revision requires an explicit previous output contract.")
        previous_id = _previous_output.get("reference_id")
        if not isinstance(previous_id, str) or not previous_id:
            _error("PREVIOUS_OUTPUT_INVALID", "Previous output requires reference_id.")
        scoped = [
            ref for ref in scoped
            if ref.get("reference_id") != previous_id
            and (ref.get("provenance") or {}).get("transport") != "previous_output"
        ]
        if any(ref.get("role") in {"identity_reference", "outfit_reference"} for ref in scoped):
            _error("REVISION_AUTHORITY_CONFLICT", "Request-scoped references cannot own formal revision authority.")
        if _revision_plan["generated_output_role"] != "excluded":
            previous = dict(_previous_output)
            previous.update({
                "source_scope": "request_scoped_arco",
                "role": "composition_reference",
                "authority": "previous_output_continuity",
                "generated_output_role": _revision_plan["generated_output_role"],
                "persistent": False,
                "calibrating": False,
                "inherit": ["pose", "composition", "scene", "lighting"],
                "do_not_inherit": ["identity", "hair", "eyes", "face", "body_proportions", "outfit", "variant"],
                "coverage": {},
            })
            scoped.append(previous)
        if _revision_plan["requires_external_refs"] and not external:
            _error("EXTERNAL_REFERENCE_REQUIRED", "Required External HOW reference is unavailable.")
    requested_roles = _reference_roles(
        managed_roles=managed_roles,
        request_scoped=scoped,
        variant_id=normalized["variant_id"],
    )
    if _revision_plan is not None:
        if (_revision_plan["requires_original_identity"] or _revision_plan["requires_original_outfit"] or _revision_plan["generated_output_role"] == "composition_anchor") and "identity_reference" not in requested_roles:
            requested_roles.append("identity_reference")
        if _revision_plan["requires_original_outfit"] and "outfit_reference" not in requested_roles:
            requested_roles.append("outfit_reference")
    variant_required = "outfit_reference" in requested_roles or any(
        ref.get("role") == "outfit_reference" for ref in scoped
    )
    split_mode = generation_config.get("split_reference_selection", False)
    if split_mode:
        if scoped and any(ref.get("role") in {"identity_reference", "outfit_reference", "face_reference"} for ref in scoped):
            _error("SPLIT_REFERENCE_INVALID", "Published split layers must establish Arco WHO.")
        selected = select_split_references(root=root, assets=all_assets,
            analysis=normalized["reference_analysis"], profile=normalized["exposure_profile"],
            variant_id=normalized["variant_id"], descriptors=normalized["arco_references"])
        # Reuse canonical contract validation, ordering and image limits.
        selected = select_references(root=root, managed_assets=[], requested_roles=[],
            request_scoped_references=[*selected, *scoped], external_references=external,
            config=generation_config)
    else:
        selected = select_references(
            root=root,
            managed_assets=managed_assets,
            requested_roles=requested_roles,
            request_scoped_references=scoped,
            external_references=external,
            exposure_profile=normalized["exposure_profile"],
            variant_required=variant_required,
            selected_variant_id=normalized["variant_id"],
            config=generation_config,
        )
    if _revision_plan is not None:
        if _revision_plan["requires_original_identity"] and not any(
            ref.get("source_scope") == "managed_arco" and "identity_reference" in ref.get("duties", [ref.get("role")])
            for ref in selected
        ):
            _error("ORIGINAL_IDENTITY_REQUIRED", "Formal Identity reference is unavailable.")
        if _revision_plan["requires_original_outfit"] and not any(
            ref.get("source_scope") == "managed_arco" and ref.get("role") == "outfit_reference"
            and ref.get("variant_id") == normalized["variant_id"] for ref in selected
        ):
            _error("ORIGINAL_OUTFIT_REQUIRED", "Formal Outfit reference is unavailable.")
        if _revision_plan["requires_external_refs"] and not any(
            ref.get("source_scope") == "external_how" for ref in selected
        ):
            _error("EXTERNAL_REFERENCE_REQUIRED", "Required External HOW reference is unavailable.")
        # Preserve Image 1 as the previous edit target for existing revision prompts.
        if not _source_reset:
            selected.sort(key=lambda ref: 0 if ref.get("generated_output_role") else 1)
    readiness = compute_request_reference_readiness(
        exposure_profile=normalized["exposure_profile"],
        references=selected,
        variant_required=variant_required,
        selected_variant_id=normalized["variant_id"],
    )
    if readiness.get("status") != "READY":
        code = "REFERENCE_CONFLICT" if readiness.get("status") == "CONFLICT" else "REFERENCE_ASSETS_INCOMPLETE"
        _error(code, f"Request reference readiness is {readiness.get('status')}: {readiness.get('missing_fields', [])}")

    resolved_style_references = resolve_style_references(selected)
    # resolve_style_context performs the existing source/axis/priority-bound
    # validate_style_brief checks for every request-scoped Style Brief.
    style_context = resolve_style_context(
        resolved_style_references=resolved_style_references,
        style_briefs=normalized["style_briefs"],
        official_style_baseline=baseline,
        user_style_overrides=normalized["user_style_overrides"],
    )
    hygiene_policy = None
    if normalized["rendering_hygiene"] == "hygiene_v11":
        hygiene_policy = _load_yaml(root, HYGIENE_POLICY_PATH, label="Rendering Hygiene policy")
    prompt = compile_prompt(
        base_prompt=normalized["base_prompt"],
        references=selected,
        identity=identity,
        exposure_profile=normalized["exposure_profile"],
        allow_uncertain_working=bool(normalized["allow_uncertain_working"]),
        style_context=style_context,
        rendering_hygiene_policy=hygiene_policy,
        revision_stability_guard=_revision_stability_guard,
        composition_readability_plan=readability_plan,
    )
    from outfit_design import compile_design, compile_back_identity
    if variant_definition:
        design_prompt = compile_design(variant_definition)
        if design_prompt:
            prompt += "\n\n" + design_prompt
    if normalized["exposure_profile"] == "back_view":
        prompt += "\n\n" + compile_back_identity(identity)
        if identity.get("approved_view_designs"):
            from reference_analysis import file_hash
            normalized["back_identity_definition_sha256"] = file_hash(root / IDENTITY_PATH)
    analysis = None
    if generation_config.get("reference_analysis_required", False):
        analysis = validate_analysis(normalized["reference_analysis"], selected, style_context)
        prompt += "\n\n" + compile_analysis(analysis)
    invocation_plan = build_invocation_plan(
        mode="reference_conditioned",
        prompt=prompt,
        selected_references=selected,
    )
    preview = freeze_analysis(analysis=analysis, prompt=prompt, references=selected, request=normalized) if analysis else None
    if preview:
        from reference_analysis import file_hash
        preview["library_hashes"] = {}
        if variant_definition and variant_definition.get("design_definition") is not None:
            preview["library_hashes"][str((root / variant_path).resolve())] = file_hash(root / variant_path)
        if normalized["exposure_profile"] == "back_view":
            preview["library_hashes"][str((root / IDENTITY_PATH).resolve())] = file_hash(root / IDENTITY_PATH)
        invocation_plan["analysis_preview"] = deepcopy(preview)
    return ProductionGenerationPlan(prompt, style_context, tuple(selected), invocation_plan, readability_plan, preview, artwork_title(request))


def run_production_generation(request: Mapping[str, Any], *, builtin_image_gen: Callable[..., Any],
                              root: Path = ROOT, **revision_options: Any) -> ProductionGenerationResult:
    plan = plan_production_generation(request, root=root, **revision_options)
    if plan.analysis_preview:
        validate_confirmation(request.get("analysis_confirmation"), plan.analysis_preview)
    invocation = deepcopy(dict(plan.invocation_plan))
    if plan.analysis_preview:
        invocation["analysis_confirmation"] = deepcopy(request["analysis_confirmation"])
    output_path = ArcoRealAdapter(builtin_image_gen).generate(
        invocation_plan=invocation, reference_contracts=plan.selected_references,
        reference_image_paths=[str(ref["path"]) for ref in plan.selected_references])
    result = ProductionGenerationResult(
        prompt=plan.prompt,
        style_context=plan.style_context,
        selected_references=plan.selected_references,
        invocation_plan=invocation,
        output_path=output_path,
        output_id=str(output_path.resolve()),
        revision_context=first_context(request),
        generation_depth=0,
        parent_output=None,
        source_generation_id=str(output_path.resolve()),
        reset_triggered_from_output=None,
        composition_readability_plan=plan.composition_readability_plan,
        analysis_preview=plan.analysis_preview,
    )
    if revision_options.get("_revision_authorized"):
        return result  # Revision attaches its final lineage before publishing the archive.
    return archive_result(result, request, root)


def run_automatic_reference_repair(result: ProductionGenerationResult, *,
                                   source_request: Mapping[str, Any],
                                   builtin_image_gen: Callable[..., Any], root: Path = ROOT) -> ProductionGenerationResult:
    """One repair toward the original human-approved targets, never a new goal."""
    from reference_analysis import DETAILS, file_hash, digest
    import json
    from revision_reference import run_production_revision, plan_production_revision
    from revision_intent import resolve_revision_intent
    if result.automatic_repair_count != 0 or result.reset_triggered_from_output or result.generation_depth:
        _error("AUTOMATIC_REPAIR_LIMIT", "Only one automatic repair per initial generation is allowed.")
    if not result.visual_review or result.visual_review["status"] != "FAIL":
        _error("AUTOMATIC_REPAIR_REVIEW_REQUIRED", "A bound failed visual review is required before repair.")
    validate_visual_review(result.visual_review, output_path=result.output_path, frozen=result.analysis_preview)
    original = plan_production_generation(source_request, root=root)
    validate_confirmation(source_request.get("analysis_confirmation"), original.analysis_preview)
    if original.analysis_preview["plan_sha256"] != result.analysis_preview["plan_sha256"]:
        _error("ANALYSIS_CONFIRMATION_STALE", "The original approved request changed; request a new confirmation.")
    analysis = source_request["reference_analysis"]
    mapping = {"identity": ("identity",), "composition_pose": ("composition", "pose"),
               "expression": ("expression",), "lighting_style": ("lighting",)}
    failed = [key for key, check in result.visual_review["checks"].items() if check["status"] == "FAIL"]
    targets = [dimension for key in failed for dimension in mapping[key]]
    correction = "Restore the following originally approved targets; preserve all other approved content.\n"
    for dimension in targets:
        entry = analysis[dimension]
        correction += dimension + ": " + entry["transfer_target"] + "; " + "; ".join(entry[key] for key in DETAILS[dimension]) + "\n"
    if "lighting_style" in failed:
        correction += "Restore the rendering requirements from the original resolved Style Brief.\n"
    revision = deepcopy(dict(source_request))
    revision["base_prompt"] = correction
    revision.pop("analysis_confirmation", None)
    previous = {"reference_id": "automatic-repair-source", "path": str(result.output_path),
                "output_id": result.output_id, "generation_depth": result.generation_depth,
                "parent_output": result.parent_output, "source_generation_id": result.source_generation_id,
                "reset_triggered_from_output": result.reset_triggered_from_output,
                "revision_context": deepcopy(result.revision_context),
                # Identity failure excludes the result. Other fidelity failures
                # keep continuity only; they do not assert user acceptance.
                "visual_review_status": "degraded" if "identity" in failed else "passed"}
    options = {"revision_plan": resolve_revision_intent(correction), "previous_output": previous,
               "source_request": source_request, "selected_variant_id": source_request.get("variant_id"), "root": root}
    try:
        preview = plan_production_revision(revision, **options)
    except ReferenceRuntimeError as error:
        if error.code != "REFERENCE_LIMIT_EXCEEDED":
            raise
        # Rebuild from all clean references when a continuity image would
        # exceed the five-input transport budget.
        previous["visual_review_status"] = "degraded"
        preview = plan_production_revision(revision, **options)
    revision["analysis_confirmation"] = {
        "user_confirmed": True, "plan_sha256": preview.analysis_preview["plan_sha256"],
        "authorization_type": "automatic_repair",
        "original_plan_sha256": result.analysis_preview["plan_sha256"],
        "failed_output_sha256": file_hash(result.output_path),
        "user_message": "One automatic repair within the human-confirmed original analysis; "
                        + source_request["analysis_confirmation"]["user_message"],
    }
    ledger_path = Path(root).resolve() / "runtime/records/reference-repairs" / (digest(result.source_generation_id) + ".json")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ledger_path.open("x", encoding="utf-8") as ledger:
            json.dump({"source_generation_id": result.source_generation_id,
                       "original_plan_sha256": result.analysis_preview["plan_sha256"],
                       "failed_output_sha256": file_hash(result.output_path),
                       "automatic_repair_count": 1, "state": "reserved"}, ledger)
    except FileExistsError:
        _error("AUTOMATIC_REPAIR_LIMIT", "This initial generation already reserved its one automatic repair.")
    repaired = run_production_revision(revision, builtin_image_gen=builtin_image_gen, **options)
    ledger_path.write_text(json.dumps({"source_generation_id": result.source_generation_id,
        "original_plan_sha256": result.analysis_preview["plan_sha256"],
        "automatic_repair_count": 1, "state": "completed", "repair_output_id": repaired.output_id}), encoding="utf-8")
    return sync_review(replace(repaired, automatic_repair_count=1))


__all__ = [
    "ProductionGenerationError",
    "ProductionGenerationResult",
    "run_production_generation",
    "plan_production_generation",
    "ProductionGenerationPlan",
    "run_automatic_reference_repair",
]
