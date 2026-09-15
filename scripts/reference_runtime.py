#!/usr/bin/env python3
"""Pure, read-only planning for Arco reference-conditioned generation.

This module deliberately stops at a serializable argument dictionary.  It has
no image-generation client and performs no network calls.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence


MODES = {"reference_conditioned", "prompt_only"}
READINESS = {"READY", "PARTIAL", "INCOMPLETE", "CONFLICT"}
SCOPES = {"managed_arco", "request_scoped_arco", "external_how"}
REFERENCE_ROLES = {
    "identity_reference",
    "outfit_reference",
    "state_reference",
    "face_reference",
    "detail_reference",
    "composition_reference",
    "pose_reference",
    "lighting_reference",
    "style_reference",
}
WHO_FIELDS = {"identity", "hair", "eyes", "face", "body_proportions", "outfit", "variant"}
ROLE_ORDER = {
    "identity_reference": 0,
    "outfit_reference": 1,
    "state_reference": 2,
    "face_reference": 3,
    "detail_reference": 4,
    "composition_reference": 5,
    "pose_reference": 6,
    "lighting_reference": 7,
    "style_reference": 8,
}

# Identity facts are deliberately mapped through a small, explicit allowlist.
# This keeps the compiler from dumping the YAML wholesale into a generation
# prompt and makes the policy boundary testable.  The body proportion mapping
# is a user-approved working description in the body-proportion candidate; it
# is therefore opt-in when its evidence status is UNCERTAIN.
IDENTITY_FACT_PROMPT_PROFILES = {
    "body.chest_proportion": {"portrait", "upper_body", "full_body"},
}
IDENTITY_FACT_PROMPT_MAP = {
    ("body.chest_proportion", "small-to-modest"): {
        "text": (
            "a slim, lightly built figure with a narrow upper torso and a "
            "small-to-modest, understated bust"
        ),
        "soft_constraints": ["no exaggerated chest volume"],
    },
}
PROMPT_BANNED_BODY_PHRASES = {
    "flat chest",
    "tiny breasts",
    "very small breasts",
}
PROFILE_REQUIREMENTS = {
    "portrait": {"identity", "hair", "eyes", "face"},
    "upper_body": {"identity", "hair", "eyes", "face", "body.upper"},
    "full_body": {
        "identity", "hair", "eyes", "face", "body.upper", "body.full",
    },
    "back_view": {"identity", "hair.back", "body.back"},
}
VARIANT_REQUIREMENTS = {
    "portrait": {"variant.visible_headwear_accessories"},
    "upper_body": {"variant.upper_body_outfit"},
    "full_body": {"variant.full_outfit", "variant.footwear"},
    "back_view": {"variant.back_outfit"},
}


class ReferenceRuntimeError(ValueError):
    """A stable runtime-planning error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _error(code: str, message: str) -> None:
    raise ReferenceRuntimeError(code, message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generation_allowed(asset: Mapping[str, Any]) -> bool:
    """Missing permission is a deny; excluded calibration layers remain denied."""
    roles = set(asset.get("roles") or [])
    kind = asset.get("asset_type")
    if "expression_evidence" in roles or kind in {"body_base", "faceless_composite"}:
        return False
    if asset.get("can_be_generation_reference") is not True:
        return False
    metadata = asset.get("generation_reference")
    return isinstance(metadata, Mapping) and bool(metadata.get("supported_roles"))


def _coverage_fields(value: Mapping[str, Any]) -> set[str]:
    coverage = value.get("coverage") or {}
    return set(coverage.get("visible_fields") or []) - set(coverage.get("occluded_fields") or [])


def _required_fields(exposure_profile: str, variant_required: bool = False) -> set[str]:
    if exposure_profile not in PROFILE_REQUIREMENTS:
        _error("INVALID_EXPOSURE_PROFILE", exposure_profile)
    required = set(PROFILE_REQUIREMENTS[exposure_profile])
    if variant_required:
        required.update(VARIANT_REQUIREMENTS[exposure_profile])
    if exposure_profile == "back_view":
        required.add("view.back")
    return required


def _role_required_fields(exposure_profile: str, role: str) -> set[str]:
    """Return only the coverage owned by one managed-reference role."""
    if exposure_profile not in PROFILE_REQUIREMENTS:
        _error("INVALID_EXPOSURE_PROFILE", exposure_profile)
    if role == "identity_reference":
        required = set(PROFILE_REQUIREMENTS[exposure_profile])
        if exposure_profile == "back_view":
            required.add("view.back")
        return required
    if role == "outfit_reference":
        required = set(VARIANT_REQUIREMENTS[exposure_profile])
        if exposure_profile == "back_view":
            required.add("view.back")
        return required
    return set()


def resolve_mode(
    *,
    explicit_mode: str | None,
    wants_generation: bool,
    request_reference_readiness: str,
    capability_available: bool = True,
    fallback_to_prompt_only: bool = True,
) -> dict[str, Any]:
    if explicit_mode is not None and explicit_mode not in MODES:
        _error("INVALID_GENERATION_MODE", f"Unknown generation mode: {explicit_mode}")
    if request_reference_readiness not in READINESS:
        _error("INVALID_REFERENCE_READINESS", request_reference_readiness)
    if not wants_generation or explicit_mode == "prompt_only":
        return {"mode": "prompt_only", "decision": "READY", "fallback_reason": None}
    forced = explicit_mode == "reference_conditioned"
    reason = None
    if request_reference_readiness not in {"READY", "PARTIAL"}:
        reason = "REFERENCE_CONFLICT" if request_reference_readiness == "CONFLICT" else "REFERENCE_ASSETS_INCOMPLETE"
    elif not capability_available:
        reason = "BUILTIN_IMAGE_GENERATION_UNAVAILABLE"
    if reason is None:
        return {"mode": "reference_conditioned", "decision": "READY", "fallback_reason": None}
    if forced or not fallback_to_prompt_only:
        return {"mode": "reference_conditioned", "decision": "REVIEWER", "fallback_reason": reason}
    return {"mode": "prompt_only", "decision": "FALLBACK", "fallback_reason": reason}


def compute_global_reference_readiness(
    identity: Mapping[str, Any],
    variant_index: Mapping[str, Any],
    assets: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    eligible = [asset for asset in assets if generation_allowed(asset)]
    identity_assets = [asset for asset in eligible if "identity_reference" in asset.get("generation_reference", {}).get("supported_roles", [])]
    profiles: dict[str, str] = {}
    for profile in PROFILE_REQUIREMENTS:
        covered: set[str] = set()
        has_back = False
        for asset in identity_assets:
            covered.update(_coverage_fields(asset.get("generation_reference", {})))
            has_back = has_back or bool(set(asset.get("generation_reference", {}).get("coverage", {}).get("view_angles") or []) & {"back", "back_three_quarter"})
        if profile == "back_view" and has_back:
            covered.add("view.back")
        profiles[profile] = "READY" if int(identity.get("revision", 0)) > 0 and not (_required_fields(profile) - covered) else "INCOMPLETE"
    variants: dict[str, str] = {}
    variant_profiles: dict[str, dict[str, str]] = {}
    for item in variant_index.get("variants", []) or []:
        variant_id = item.get("variant_id") or item.get("id")
        if not variant_id:
            continue
        variant_id = str(variant_id)
        candidates = [
            asset for asset in eligible
            if asset.get("variant_id") == variant_id
            and "outfit_reference" in asset.get("generation_reference", {}).get("supported_roles", [])
        ]
        primaries = [
            asset for asset in candidates
            if asset.get("generation_reference", {}).get("priority") == "primary"
        ]
        if len(primaries) > 1:
            profile_statuses = {profile: "CONFLICT" for profile in PROFILE_REQUIREMENTS}
            variants[variant_id] = "CONFLICT"
            variant_profiles[variant_id] = profile_statuses
            continue
        has_primary = len(primaries) == 1
        profile_statuses: dict[str, str] = {}
        for profile in PROFILE_REQUIREMENTS:
            covered: set[str] = set()
            has_back = False
            for asset in candidates:
                metadata = asset.get("generation_reference", {})
                covered.update(_coverage_fields(metadata))
                has_back = has_back or bool(
                    set(metadata.get("coverage", {}).get("view_angles") or [])
                    & {"back", "back_three_quarter"}
                )
            if profile == "back_view" and has_back:
                covered.add("view.back")
            required = _role_required_fields(profile, "outfit_reference")
            profile_statuses[profile] = "READY" if has_primary and not (required - covered) else "INCOMPLETE"
        ready_count = sum(value == "READY" for value in profile_statuses.values())
        variants[variant_id] = (
            "READY" if ready_count == len(profile_statuses)
            else "PARTIAL" if ready_count
            else "INCOMPLETE"
        )
        variant_profiles[variant_id] = profile_statuses
    ready_count = sum(value == "READY" for value in profiles.values())
    identity_status = "READY" if ready_count == len(profiles) else "PARTIAL" if ready_count else "INCOMPLETE"
    overall = identity_status
    if any(value == "CONFLICT" for value in variants.values()):
        overall = "CONFLICT"
    elif variants and not all(value == "READY" for value in variants.values()):
        overall = "PARTIAL" if identity_status != "INCOMPLETE" else "INCOMPLETE"
    return {
        "identity": identity_status,
        "identity_profiles": profiles,
        "variants": variants,
        "variant_profiles": variant_profiles,
        "overall": overall,
    }


def compute_request_reference_readiness(
    *,
    exposure_profile: str,
    references: Sequence[Mapping[str, Any]],
    variant_required: bool = False,
    selected_variant_id: str | None = None,
    conflict: bool = False,
) -> dict[str, Any]:
    if exposure_profile not in PROFILE_REQUIREMENTS:
        _error("INVALID_EXPOSURE_PROFILE", exposure_profile)
    if conflict:
        return {"status": "CONFLICT", "covered_fields": [], "missing_fields": [], "basis": []}
    if variant_required and selected_variant_id:
        conflicting = [
            str(ref.get("reference_id") or ref.get("asset_id") or "unknown")
            for ref in references
            if ref.get("role") == "outfit_reference"
            and ref.get("variant_id") != selected_variant_id
        ]
        if conflicting:
            return {
                "status": "CONFLICT",
                "covered_fields": [],
                "missing_fields": [],
                "basis": [],
                "conflicting_reference_ids": conflicting,
            }
    arco = [ref for ref in references if ref.get("source_scope") in {"managed_arco", "request_scoped_arco"}]
    covered: set[str] = set()
    basis: list[str] = []
    has_back_view = False
    for ref in arco:
        coverage = ref.get("coverage") or {}
        visible = set(coverage.get("visible_fields") or []) - set(coverage.get("occluded_fields") or [])
        covered.update(visible)
        has_back_view = has_back_view or bool(set(coverage.get("view_angles") or []) & {"back", "back_three_quarter"})
        basis.append(str(ref.get("reference_id") or ref.get("asset_id") or ref.get("request_reference_id") or "unknown"))
    required = _required_fields(exposure_profile, variant_required)
    if exposure_profile == "back_view" and has_back_view:
        covered.add("view.back")
    missing = sorted(required - covered)
    if exposure_profile == "back_view" and not has_back_view:
        status = "INCOMPLETE"
    elif not arco or not (covered & {"identity", "hair", "eyes", "face", "hair.back"}):
        status = "INCOMPLETE"
    else:
        status = "READY" if not missing else "PARTIAL"
    return {"status": status, "covered_fields": sorted(covered), "missing_fields": missing, "basis": basis}


def validate_reference_contract(reference: Mapping[str, Any]) -> None:
    scope = reference.get("source_scope")
    if scope not in SCOPES:
        _error("INVALID_REFERENCE_SCOPE", str(scope))
    role = reference.get("role")
    if role not in REFERENCE_ROLES:
        _error("INVALID_REFERENCE_ROLE", str(role))
    inherit = set(reference.get("inherit") or [])
    excluded = set(reference.get("do_not_inherit") or [])
    if inherit & excluded:
        _error("REFERENCE_INHERIT_CONFLICT", f"Conflicting fields: {sorted(inherit & excluded)}")
    raw_path = reference.get("path")
    if raw_path and "calibration/staging" in str(raw_path).replace("\\", "/").lower():
        _error("UNPUBLISHED_ASSET", "Staging paths cannot be generation inputs.")
    if scope == "managed_arco" and not reference.get("asset_id"):
        _error("MISSING_ASSET_ID", "Managed references require asset_id.")
    if scope == "request_scoped_arco":
        if "asset_id" in reference:
            _error("REQUEST_REFERENCE_HAS_ASSET_ID", "Request-scoped references cannot have asset_id.")
        if reference.get("persistent") is not False or reference.get("calibrating") is not False:
            _error("REQUEST_REFERENCE_PERSISTENCE", "Request-scoped references must be non-persistent and non-calibrating.")
    if scope == "external_how" and inherit & WHO_FIELDS:
        _error("EXTERNAL_IDENTITY_POLLUTION", f"External HOW inherits WHO fields: {sorted(inherit & WHO_FIELDS)}")


def _managed_contract(asset: Mapping[str, Any], role: str, root: Path) -> dict[str, Any]:
    if not generation_allowed(asset):
        _error("ASSET_NOT_ALLOWED_FOR_GENERATION", str(asset.get("asset_id")))
    if asset.get("asset_status") != "VERIFIED":
        _error("INVALID_ASSET_STATUS", str(asset.get("asset_id")))
    supported = set(asset["generation_reference"].get("supported_roles") or [])
    if role not in supported:
        _error("REFERENCE_ROLE_NOT_SUPPORTED", f"{asset.get('asset_id')} cannot serve {role}")
    relative = Path(str(asset.get("path", "")))
    absolute = (root / relative).resolve()
    try:
        absolute.relative_to(root.resolve())
    except ValueError:
        _error("UNPUBLISHED_ASSET", "Managed asset path escapes the published root.")
    if "calibration/staging" in absolute.as_posix().lower() or not absolute.is_file():
        _error("UNPUBLISHED_ASSET", str(relative))
    if _sha256(absolute) != str(asset.get("sha256", "")).lower():
        _error("ASSET_HASH_MISMATCH", str(asset.get("asset_id")))
    inheritance = asset["generation_reference"].get("inheritance") or {}
    inherit = sorted(key for key, value in inheritance.items() if value == "inherit")
    do_not_inherit = sorted(key for key, value in inheritance.items() if value == "do_not_inherit")
    contract = {
        "reference_id": str(asset["asset_id"]), "source_scope": "managed_arco",
        "asset_id": str(asset["asset_id"]), "path": str(absolute), "role": role,
        "authority": "published_asset", "selection_reason": "published_generation_reference",
        "confidence": "high", "persistent": True,
        "generation_priority": asset["generation_reference"].get("priority"),
        "inherit": inherit,
        "do_not_inherit": do_not_inherit,
        "coverage": asset.get("generation_reference", {}).get("coverage", {}),
    }
    if asset.get("variant_id") is not None:
        contract["variant_id"] = str(asset["variant_id"])
    return contract


def select_references(
    *,
    root: Path,
    managed_assets: Sequence[Mapping[str, Any]],
    requested_roles: Sequence[str],
    request_scoped_references: Sequence[Mapping[str, Any]] = (),
    external_references: Sequence[Mapping[str, Any]] = (),
    exposure_profile: str | None = None,
    variant_required: bool = False,
    selected_variant_id: str | None = None,
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for role in requested_roles:
        candidates = [asset for asset in managed_assets if generation_allowed(asset) and role in asset.get("generation_reference", {}).get("supported_roles", [])]
        if role == "outfit_reference":
            if not selected_variant_id:
                _error("VARIANT_SELECTION_REQUIRED", "Managed outfit references require selected_variant_id.")
            candidates = [asset for asset in candidates if asset.get("variant_id") == selected_variant_id]
            if not candidates:
                _error("VARIANT_REFERENCE_NOT_FOUND", selected_variant_id)
            primaries = [asset for asset in candidates if asset.get("generation_reference", {}).get("priority") == "primary"]
            if not primaries:
                _error("VARIANT_PRIMARY_MISSING", selected_variant_id)
            if len(primaries) > 1:
                _error("VARIANT_PRIMARY_CONFLICT", selected_variant_id)
            primary = primaries[0]
            candidates = [primary] + [asset for asset in candidates if asset is not primary]
        candidates.sort(key=lambda a: ({"primary": 0, "secondary": 1, "supplemental": 2}.get(a.get("generation_reference", {}).get("priority"), 9), str(a.get("asset_id"))))
        if candidates:
            primary = candidates[0]
            selected.append(_managed_contract(primary, role, root))
            if exposure_profile is not None and role in {"identity_reference", "outfit_reference"}:
                required = _role_required_fields(exposure_profile, role)
                covered = _coverage_fields(primary.get("generation_reference", {}))
                if exposure_profile == "back_view" and set(primary.get("generation_reference", {}).get("coverage", {}).get("view_angles") or []) & {"back", "back_three_quarter"}:
                    covered.add("view.back")
                missing = required - covered
                # Greedy minimal cover. Supplementals are considered only if they
                # contribute fields still absent after all useful secondaries.
                for priority in ("secondary", "supplemental"):
                    useful = [a for a in candidates[1:] if a.get("generation_reference", {}).get("priority") == priority and (_coverage_fields(a.get("generation_reference", {})) & missing)]
                    useful.sort(key=lambda a: (-len(_coverage_fields(a.get("generation_reference", {})) & missing), str(a.get("asset_id"))))
                    while useful and missing:
                        chosen = useful.pop(0)
                        contribution = _coverage_fields(chosen.get("generation_reference", {})) & missing
                        if not contribution:
                            continue
                        selected.append(_managed_contract(chosen, role, root))
                        covered.update(_coverage_fields(chosen.get("generation_reference", {})))
                        if exposure_profile == "back_view" and set(chosen.get("generation_reference", {}).get("coverage", {}).get("view_angles") or []) & {"back", "back_three_quarter"}:
                            covered.add("view.back")
                        missing = required - covered
                        useful.sort(key=lambda a: (-len(_coverage_fields(a.get("generation_reference", {})) & missing), str(a.get("asset_id"))))
    selected.extend(dict(ref) for ref in request_scoped_references)
    selected.extend(dict(ref) for ref in external_references)
    for ref in selected:
        validate_reference_contract(ref)
    selected.sort(key=lambda ref: (
        ROLE_ORDER[str(ref["role"])],
        {"primary": 0, "secondary": 1, "supplemental": 2}.get(ref.get("generation_priority"), 3),
        str(ref.get("reference_id", "")),
    ))
    generation = config.get("generation", config)
    local_count = sum(ref["source_scope"] in {"managed_arco", "request_scoped_arco"} for ref in selected)
    external_count = sum(ref["source_scope"] == "external_how" for ref in selected)
    if local_count > int(generation["max_local_arco_references"]) or external_count > int(generation["max_external_references"]) or len(selected) > int(generation["max_total_image_inputs"]):
        _error("REFERENCE_LIMIT_EXCEEDED", "Selected references exceed runtime limits.")
    return selected


def compile_reference_instructions(references: Sequence[Mapping[str, Any]]) -> str:
    """Compile enforceable reference duties without changing the scene prompt."""
    blocks: list[str] = []
    for ref in references:
        validate_reference_contract(ref)
        identity = str(ref.get("reference_id"))
        inherit_fields = set(ref.get("inherit") or [])
        if ref.get("role") == "identity_reference" and {"identity", "face", "hair", "eyes"} <= inherit_fields:
            inherit = "Arco's identity, including her face, hair and eyes"
        else:
            inherit = ", ".join(ref.get("inherit") or []) or "only its assigned reference role"
        excluded = ", ".join(ref.get("do_not_inherit") or []) or "none"
        blocks.append(f"Reference {identity}: use to define {inherit}. Do not inherit: {excluded}.")
    return " ".join(blocks)


def resolve_identity_fact_prompt_fragments(
    identity: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    exposure_profile: str,
    allow_uncertain_working: bool = False,
) -> dict[str, Any]:
    """Resolve the small, policy-approved subset of Identity facts for text.

    ``UNCERTAIN`` facts are only eligible when the caller explicitly supplies
    the user-approved working-fact opt-in.  ``TODO_CALIBRATION`` is always
    excluded.  The returned representation is data-only so it can be tested
    independently from reference selection and image invocation.
    """
    if exposure_profile not in PROFILE_REQUIREMENTS:
        _error("INVALID_EXPOSURE_PROFILE", exposure_profile)
    raw_facts = identity.get("facts", []) if isinstance(identity, Mapping) else identity
    if not isinstance(raw_facts, Sequence) or isinstance(raw_facts, (str, bytes)):
        _error("INVALID_IDENTITY_FACTS", "Identity facts must be a sequence.")

    fragments: list[dict[str, Any]] = []
    soft_constraints: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    seen_semantics: set[str] = set()
    seen_constraints: set[str] = set()
    for fact in raw_facts:
        if not isinstance(fact, Mapping):
            continue
        field_id = str(fact.get("field_id", ""))
        value = str(fact.get("value", "")).strip()
        status = str(fact.get("status", ""))
        if status == "TODO_CALIBRATION":
            omitted.append({"field_id": field_id, "reason": "TODO_CALIBRATION"})
            continue
        if status == "UNCERTAIN" and not allow_uncertain_working:
            omitted.append({"field_id": field_id, "reason": "UNCERTAIN_NOT_OPTED_IN"})
            continue
        if status not in {"CANON", "VISUAL_CONSENSUS", "UNCERTAIN"}:
            omitted.append({"field_id": field_id, "reason": "STATUS_NOT_ELIGIBLE"})
            continue
        if exposure_profile not in IDENTITY_FACT_PROMPT_PROFILES.get(field_id, set()):
            omitted.append({"field_id": field_id, "reason": "PROFILE_NOT_ROUTED"})
            continue
        mapping = IDENTITY_FACT_PROMPT_MAP.get((field_id, value.lower()))
        if mapping is None:
            omitted.append({"field_id": field_id, "reason": "NO_PROMPT_MAPPING"})
            continue
        text = str(mapping["text"]).strip()
        lowered = text.lower()
        if any(banned in lowered for banned in PROMPT_BANNED_BODY_PHRASES):
            _error("PROMPT_SEMANTIC_GUARD", f"Banned body phrase in mapping: {field_id}")
        semantic_key = f"{field_id}:{value.lower()}"
        if semantic_key not in seen_semantics:
            fragments.append({"field_id": field_id, "status": status, "text": text})
            seen_semantics.add(semantic_key)
        for constraint in mapping.get("soft_constraints", []):
            constraint_text = str(constraint).strip()
            constraint_lower = constraint_text.lower()
            if any(banned in constraint_lower for banned in PROMPT_BANNED_BODY_PHRASES):
                _error("PROMPT_SEMANTIC_GUARD", f"Banned body phrase in constraint: {field_id}")
            if constraint_lower not in seen_constraints:
                soft_constraints.append({"field_id": field_id, "text": constraint_text})
                seen_constraints.add(constraint_lower)

    # This is intentionally a single mild guard, even if duplicate candidate
    # facts are supplied by a fixture or future schema extension.
    if len(soft_constraints) > 1:
        soft_constraints = soft_constraints[:1]
    return {
        "fragments": fragments,
        "soft_constraints": soft_constraints,
        "omitted": omitted,
    }


def compile_prompt(
    *,
    base_prompt: str,
    references: Sequence[Mapping[str, Any]],
    identity: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    exposure_profile: str | None = None,
    allow_uncertain_working: bool = False,
) -> str:
    """Compile Identity fact text, reference duties, and the scene prompt.

    This remains a pure text compiler.  It never discovers staging assets or
    invokes an image-generation adapter; callers still pass the result to the
    existing Invocation Plan boundary.
    """
    if not isinstance(base_prompt, str) or not base_prompt.strip():
        _error("INVALID_PROMPT", "Prompt must be non-empty.")
    identity_parts: list[str] = []
    constraints: list[str] = []
    if identity is not None:
        if exposure_profile is None:
            _error("INVALID_EXPOSURE_PROFILE", "Identity fact compilation requires a profile.")
        resolved = resolve_identity_fact_prompt_fragments(
            identity,
            exposure_profile=exposure_profile,
            allow_uncertain_working=allow_uncertain_working,
        )
        identity_parts = [str(item["text"]) for item in resolved["fragments"]]
        constraints = [str(item["text"]) for item in resolved["soft_constraints"]]
    reference_text = compile_reference_instructions(references)
    pieces = identity_parts + ([reference_text] if reference_text else []) + [base_prompt.strip()]
    # Keep the mild constraint separate from the identity description so it
    # cannot become a repeated or over-weighted body paragraph.
    if constraints:
        pieces.append(" ".join(constraints))
    prompt = " ".join(piece for piece in pieces if piece).strip()
    validate_reference_instructions(references, prompt)
    lowered = prompt.lower()
    if any(banned in lowered for banned in PROMPT_BANNED_BODY_PHRASES):
        _error("PROMPT_SEMANTIC_GUARD", "Prompt contains a banned body phrase.")
    if lowered.count("no exaggerated chest volume") > 1:
        _error("PROMPT_SEMANTIC_GUARD", "Mild chest constraint was repeated.")
    return prompt


def validate_reference_instructions(references: Sequence[Mapping[str, Any]], instructions: str) -> None:
    """Quality gate: every declared exclusion must survive prompt compilation."""
    lowered = instructions.lower()
    for ref in references:
        validate_reference_contract(ref)
        if str(ref.get("reference_id", "")).lower() not in lowered:
            _error("QUALITY_GATE_FAILED", f"Missing reference instruction for {ref.get('reference_id')}")
        for field in ref.get("do_not_inherit") or []:
            if str(field).lower() not in lowered:
                _error("QUALITY_GATE_FAILED", f"Missing do_not_inherit instruction: {field}")


def build_invocation_plan(
    *, mode: str, prompt: str, selected_references: Sequence[Mapping[str, Any]],
    num_last_images_to_include: int | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        _error("INVALID_GENERATION_MODE", mode)
    if not isinstance(prompt, str) or not prompt.strip():
        _error("INVALID_PROMPT", "Prompt must be non-empty.")
    if mode == "prompt_only":
        if selected_references:
            _error("PROMPT_ONLY_HAS_REFERENCES", "Prompt-only mode cannot carry references.")
        return {"provider": "builtin_image_gen", "capability": "reference_conditioned_image_generation", "mode": mode, "prompt": prompt, "selected_reference_ids": []}
    if not selected_references:
        _error("REFERENCE_ASSETS_INCOMPLETE", "Reference-conditioned mode requires at least one reference.")
    for ref in selected_references:
        validate_reference_contract(ref)
    paths = [ref.get("path") for ref in selected_references]
    plan = {"provider": "builtin_image_gen", "capability": "reference_conditioned_image_generation", "mode": mode, "prompt": prompt, "selected_reference_ids": [str(ref.get("reference_id")) for ref in selected_references]}
    if all(isinstance(path, str) and path for path in paths):
        if num_last_images_to_include is not None:
            _error("IMAGE_INPUT_BUILD_FAILED", "Path and conversation transports are mutually exclusive.")
        plan["referenced_image_paths"] = list(paths)
    elif all(ref.get("conversation_image") is True and not ref.get("path") for ref in selected_references) and num_last_images_to_include == len(selected_references) and num_last_images_to_include > 0:
        plan["num_last_images_to_include"] = num_last_images_to_include
    else:
        _error("IMAGE_INPUT_BUILD_FAILED", "Selected images cannot be represented exactly by one built-in transport.")
    return plan


def build_builtin_imagegen_args(invocation_plan: Mapping[str, Any]) -> dict[str, Any]:
    """Pure serialization boundary for the documented built-in tool schema."""
    if invocation_plan.get("provider") != "builtin_image_gen":
        _error("INVALID_PROVIDER", str(invocation_plan.get("provider")))
    prompt = invocation_plan.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        _error("INVALID_PROMPT", "Prompt must be non-empty.")
    result: dict[str, Any] = {"prompt": prompt}
    if invocation_plan.get("mode") == "prompt_only":
        return result
    paths = invocation_plan.get("referenced_image_paths")
    recent = invocation_plan.get("num_last_images_to_include")
    if paths is not None and recent is not None:
        _error("IMAGE_INPUT_BUILD_FAILED", "Built-in image transports are mutually exclusive.")
    if isinstance(paths, list) and paths and all(isinstance(path, str) and path for path in paths):
        result["referenced_image_paths"] = list(paths)
    elif isinstance(recent, int) and recent > 0:
        result["num_last_images_to_include"] = recent
    else:
        _error("IMAGE_INPUT_BUILD_FAILED", "Reference-conditioned invocation has no valid image input.")
    return result
