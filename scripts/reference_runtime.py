#!/usr/bin/env python3
"""Pure, read-only planning for Arco reference-conditioned generation.

This module deliberately stops at a serializable argument dictionary.  It has
no image-generation client and performs no network calls.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
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
    "scene_reference",
    "pose_reference",
    "lighting_reference",
    "style_reference",
}
HOW_DUTIES = frozenset({
    "pose_reference",
    "composition_reference",
    "scene_reference",
    "lighting_reference",
    "style_reference",
})
STYLE_AXES = (
    "linework",
    "shading",
    "color_logic",
    "highlight_language",
    "material_rendering",
    "texture_language",
    "lighting_language",
    "background_rendering",
    "detail_density",
    "edge_treatment",
)
STYLE_AXIS_LABELS = {
    "linework": "Linework",
    "shading": "Shading",
    "color_logic": "Color logic",
    "highlight_language": "Highlight language",
    "material_rendering": "Material rendering",
    "texture_language": "Texture language",
    "lighting_language": "Lighting language",
    "background_rendering": "Background rendering",
    "detail_density": "Detail density",
    "edge_treatment": "Edge treatment",
}
STYLE_PROMPT_HEADER = "Rendering style requirements:"
RENDERING_HYGIENE_HEADER = "Rendering hygiene guardrails:"
RENDERING_HYGIENE_RULE_FAMILIES = (
    "unsupported_detail_inflation",
    "highlight_organization_drift",
    "texture_noise_drift",
    "material_rendering_drift",
    "lighting_effect_inflation",
    "detail_hierarchy_flattening",
)
RENDERING_HYGIENE_ESCAPE_CLAUSE = (
    "Priority: Honor explicit user requests first, then the Resolved Style. Do not suppress any rendering characteristic supported by either; constrain only unsupported additions."
)
STYLE_PRIORITIES = frozenset({"primary", "secondary"})
STYLE_CORE_AXES = (
    "linework",
    "shading",
    "color_logic",
    "highlight_language",
    "texture_language",
    "detail_density",
)
STYLE_CONFIDENCE_LEVELS = frozenset({"HIGH", "MEDIUM", "LOW"})
PROTECTED_IDENTITY_PROPERTIES = (
    "hair_color",
    "eye_color",
    "variant_key_colors",
)
STYLE_WHO_TOKENS = frozenset({
    "identity",
    "hair",
    "eye",
    "eyes",
    "face",
    "body",
    "proportion",
    "proportions",
    "outfit",
    "clothing",
    "dress",
    "skirt",
    "variant",
    "state",
    "arco",
    "girl",
    "woman",
    "person",
    "character",
})
WHO_FIELDS = {"identity", "hair", "eyes", "face", "body_proportions", "outfit", "variant"}
ROLE_ORDER = {
    "identity_reference": 0,
    "outfit_reference": 1,
    "state_reference": 2,
    "face_reference": 3,
    "detail_reference": 4,
    "composition_reference": 5,
    "scene_reference": 6,
    "pose_reference": 7,
    "lighting_reference": 8,
    "style_reference": 9,
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


@lru_cache(maxsize=32)
def _body_base_fingerprints(registry_path: str, modified_ns: int, size: int):
    """Cache the published evidence inventory, invalidated by registry changes."""
    import yaml

    registry = Path(registry_path)
    document = yaml.safe_load(registry.read_text(encoding="utf-8"))
    assets = document.get("assets") if isinstance(document, Mapping) else None
    if not isinstance(assets, list):
        _error("REFERENCE_POLICY_INVALID", "Published asset inventory is unavailable.")
    bodies = [asset for asset in assets if asset.get("asset_type") == "body_base"]
    root = registry.parent.parent
    return (frozenset(asset["asset_id"] for asset in bodies),
            frozenset(asset["sha256"].lower() for asset in bodies),
            frozenset(str((root / asset["path"]).resolve()).casefold() for asset in bodies))


def validate_generation_reference_input(reference: Mapping[str, Any], *, root: Path | None = None) -> None:
    """Exclude Body Base evidence, including renamed copies and old contracts."""
    if reference.get("asset_type") == "body_base":
        _error("BODY_BASE_NOT_ALLOWED", "Use approved clothed identity references.")
    roots = {Path(__file__).resolve().parents[1]}
    if root is not None and (root / "character/assets.yaml").is_file():
        roots.add(root.resolve())
    ids, hashes, paths = set(), set(), set()
    for published_root in roots:
        registry = published_root / "character/assets.yaml"
        stat = registry.stat()
        blocked_ids, blocked_hashes, blocked_paths = _body_base_fingerprints(
            str(registry), stat.st_mtime_ns, stat.st_size)
        ids.update(blocked_ids)
        hashes.update(blocked_hashes)
        paths.update(blocked_paths)
    if (reference.get("asset_id") in ids or reference.get("reference_id") in ids
            or str(reference.get("sha256", "")).lower() in hashes):
        _error("BODY_BASE_NOT_ALLOWED", "Body Base evidence is local-only.")
    raw_path = reference.get("path")
    if isinstance(raw_path, (str, Path)) and raw_path:
        path = Path(raw_path).resolve()
        if str(path).casefold() in paths or (path.is_file() and _sha256(path) in hashes):
            _error("BODY_BASE_NOT_ALLOWED", "Body Base images and identical copies cannot be sent.")


def generation_permission_valid(asset: Mapping[str, Any]) -> bool:
    """Validate recorded permission structure independently of upload policy."""
    if asset.get("can_be_generation_reference") is not True:
        return False
    metadata = asset.get("generation_reference")
    if not isinstance(metadata, Mapping) or not metadata.get("supported_roles"):
        return False
    supported = set(metadata["supported_roles"])
    if "expression_evidence" in (asset.get("roles") or []) and supported != {"face_reference"}:
        return False
    if asset.get("asset_type") == "body_base" and supported != {"identity_reference"}:
        return False
    if asset.get("asset_type") == "faceless_composite" and not supported <= {"identity_reference", "outfit_reference", "state_reference"}:
        return False
    return True


def generation_allowed(asset: Mapping[str, Any]) -> bool:
    """Published permission plus the current clothed-only upload policy."""
    return asset.get("asset_type") != "body_base" and generation_permission_valid(asset)


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
        if exposure_profile == "back_view":
            # A rear outfit cannot supply rear identity, and a front image
            # cannot acquire rear coverage by merely listing those fields.
            if not set(coverage.get("view_angles") or []) & {"back", "back_three_quarter"}:
                continue
            duties = set(ref.get("duties") or [ref.get("role")])
            allowed = set()
            if "identity_reference" in duties:
                allowed.update({"identity", "hair.back", "body.back"})
            if "outfit_reference" in duties:
                allowed.add("variant.back_outfit")
            visible &= allowed
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


def _reference_duties(reference: Mapping[str, Any]) -> list[str]:
    """Return validated duties without mutating the supplied contract."""
    role = reference.get("role")
    raw_duties = reference.get("duties")
    if raw_duties is None:
        duties = [role]
    elif not isinstance(raw_duties, Sequence) or isinstance(raw_duties, (str, bytes)):
        _error("INVALID_REFERENCE_DUTIES", "Reference duties must be a non-empty list.")
    else:
        duties = list(raw_duties)
    if not duties or any(not isinstance(duty, str) or not duty for duty in duties):
        _error("INVALID_REFERENCE_DUTIES", "Reference duties must contain non-empty strings.")
    if len(set(duties)) != len(duties):
        _error("INVALID_REFERENCE_DUTIES", "Reference duties must not contain duplicates.")
    unknown = set(duties) - REFERENCE_ROLES
    if unknown:
        _error("INVALID_REFERENCE_DUTIES", f"Unknown reference duties: {sorted(unknown)}")
    if role not in duties:
        _error("INVALID_REFERENCE_DUTIES", "Canonical role must be included in duties.")
    if reference.get("source_scope") == "external_how":
        non_how = set(duties) - HOW_DUTIES
        if non_how:
            _error("INVALID_REFERENCE_DUTIES", f"External HOW cannot carry WHO duties: {sorted(non_how)}")
    return sorted(duties, key=lambda duty: (ROLE_ORDER.get(duty, len(ROLE_ORDER)), duty))


def _style_axes(reference: Mapping[str, Any], duties: Sequence[str]) -> list[str]:
    """Return canonicalized declared Style Axis ownership."""
    raw_axes = reference.get("style_axes")
    if raw_axes is None:
        return []
    if "style_reference" not in duties:
        _error("STYLE_AXIS_INVALID", "style_axes requires style_reference duty.")
    if not isinstance(raw_axes, Sequence) or isinstance(raw_axes, (str, bytes)):
        _error("STYLE_AXIS_INVALID", "style_axes must be a list.")
    axes = list(raw_axes)
    if any(not isinstance(axis, str) or axis not in STYLE_AXES for axis in axes):
        invalid = [axis for axis in axes if not isinstance(axis, str) or axis not in STYLE_AXES]
        _error("STYLE_AXIS_INVALID", f"Unknown Style Axis: {invalid}")
    if len(set(axes)) != len(axes):
        _error("STYLE_AXIS_INVALID", "style_axes must not contain duplicates.")
    return [axis for axis in STYLE_AXES if axis in axes]


def validate_reference_contract(reference: Mapping[str, Any]) -> None:
    if reference.get("asset_type") == "body_base":
        _error("BODY_BASE_NOT_ALLOWED", "Use approved clothed identity references.")
    scope = reference.get("source_scope")
    if scope not in SCOPES:
        _error("INVALID_REFERENCE_SCOPE", str(scope))
    role = reference.get("role")
    if role not in REFERENCE_ROLES:
        _error("INVALID_REFERENCE_ROLE", str(role))
    duties = _reference_duties(reference)
    inherit = set(reference.get("inherit") or [])
    excluded = set(reference.get("do_not_inherit") or [])
    output_role = reference.get("generated_output_role")
    if output_role is not None:
        if output_role not in {"primary_edit_source", "composition_anchor"}:
            _error("INVALID_GENERATED_OUTPUT_ROLE", str(output_role))
        if scope != "request_scoped_arco" or role != "composition_reference" or reference.get("authority") != "previous_output_continuity":
            _error("GENERATED_OUTPUT_AUTHORITY", "Previous output must be continuity-only.")
        if inherit & WHO_FIELDS or not WHO_FIELDS <= excluded:
            _error("GENERATED_OUTPUT_AUTHORITY", "Previous output cannot own WHO or Variant.")
    if inherit & excluded:
        _error("REFERENCE_INHERIT_CONFLICT", f"Conflicting fields: {sorted(inherit & excluded)}")
    raw_path = reference.get("path")
    if raw_path and any(area in str(raw_path).replace("\\", "/").lower() for area in ("calibration/staging", "calibration/preparations")):
        _error("UNPUBLISHED_ASSET", "Staging and preparation paths cannot be ordinary generation inputs.")
    if scope == "managed_arco" and not reference.get("asset_id"):
        _error("MISSING_ASSET_ID", "Managed references require asset_id.")
    if scope == "request_scoped_arco":
        if "asset_id" in reference:
            _error("REQUEST_REFERENCE_HAS_ASSET_ID", "Request-scoped references cannot have asset_id.")
        if reference.get("persistent") is not False or reference.get("calibrating") is not False:
            _error("REQUEST_REFERENCE_PERSISTENCE", "Request-scoped references must be non-persistent and non-calibrating.")
    if scope == "external_how" and inherit & WHO_FIELDS:
        _error("EXTERNAL_IDENTITY_POLLUTION", f"External HOW inherits WHO fields: {sorted(inherit & WHO_FIELDS)}")
    if scope == "external_how":
        style_duty = "style_reference" in duties
        if "style_priority" in reference and (
            not style_duty or reference.get("style_priority") not in STYLE_PRIORITIES
        ):
            _error("STYLE_PRIORITY_INVALID", str(reference.get("style_priority")))
        _style_axes(reference, duties)


def resolve_style_references(references: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Resolve External Style References into deterministic priority ownership.

    This function is deliberately limited to contract normalization and
    conflict detection. It does not inspect images, compile prompts, or
    communicate with a provider.
    """
    style_references: list[dict[str, Any]] = []
    for reference in references:
        validate_reference_contract(reference)
        duties = _reference_duties(reference)
        normalized = dict(reference)
        normalized["duties"] = list(duties)
        if reference.get("source_scope") != "external_how" or "style_reference" not in duties:
            continue
        normalized["style_axes"] = _style_axes(reference, duties)
        style_references.append(normalized)

    if not style_references:
        return {
            "references": [],
            "primary_reference_id": None,
            "secondary_reference_ids": [],
            "axis_owners": {},
        }

    def reference_id(reference: Mapping[str, Any]) -> str:
        value = reference.get("reference_id") or reference.get("asset_id") or reference.get("request_reference_id")
        if not isinstance(value, str) or not value:
            _error("INVALID_REFERENCE_CONTRACTS", "Style references require reference_id.")
        return value

    for reference in style_references:
        reference_id(reference)
        if "style_priority" in reference and reference["style_priority"] not in STYLE_PRIORITIES:
            _error("STYLE_PRIORITY_INVALID", str(reference.get("style_priority")))

    if len(style_references) == 1 and "style_priority" not in style_references[0]:
        style_references[0]["style_priority"] = "primary"
    elif len(style_references) > 1 and any("style_priority" not in ref for ref in style_references):
        _error("STYLE_PRIMARY_CONFLICT", "Multiple Style References require explicit style_priority.")

    primaries = [ref for ref in style_references if ref.get("style_priority") == "primary"]
    secondaries = [ref for ref in style_references if ref.get("style_priority") == "secondary"]
    if len(primaries) > 1:
        _error("STYLE_PRIMARY_CONFLICT", "At most one Style Reference may be primary.")
    if len(secondaries) > 1:
        _error("STYLE_SECONDARY_CONFLICT", "At most one Style Reference may be secondary.")

    primary = primaries[0] if primaries else None
    secondary = secondaries[0] if secondaries else None
    axis_owners: dict[str, str] = {}
    if primary is not None:
        primary_id = reference_id(primary)
        for axis in primary["style_axes"]:
            axis_owners[axis] = primary_id
    if secondary is not None:
        secondary_id = reference_id(secondary)
        primary_axes = set(primary.get("style_axes") or []) if primary is not None else set()
        overlap = primary_axes & set(secondary.get("style_axes") or [])
        if overlap:
            _error("STYLE_AXIS_CONFLICT", f"Primary and Secondary claim the same Style Axis: {sorted(overlap)}")
        for axis in secondary["style_axes"]:
            axis_owners[axis] = secondary_id

    style_references.sort(
        key=lambda ref: (
            {"primary": 0, "secondary": 1}.get(ref.get("style_priority"), 2),
            reference_id(ref),
        )
    )
    return {
        "references": style_references,
        "primary_reference_id": reference_id(primary) if primary is not None else None,
        "secondary_reference_ids": [reference_id(secondary)] if secondary is not None else [],
        "axis_owners": axis_owners,
    }


def _normalize_confidence(value: Any, *, error_code: str = "STYLE_BRIEF_CONFIDENCE_INVALID") -> str:
    if not isinstance(value, str) or value.strip().upper() not in STYLE_CONFIDENCE_LEVELS:
        _error(error_code, f"Unknown confidence: {value}")
    return value.strip().upper()


def _style_reference_id(reference: Mapping[str, Any]) -> str:
    value = reference.get("reference_id") or reference.get("asset_id") or reference.get("request_reference_id")
    if not isinstance(value, str) or not value:
        _error("STYLE_BRIEF_SOURCE_MISMATCH", "Style references require a non-empty reference_id.")
    return value


def _style_reference_index(resolved_style_references: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], str | None, list[str], dict[str, str]]:
    """Read the already-resolved Batch 1 result without re-resolving priority."""
    if not isinstance(resolved_style_references, Mapping):
        _error("STYLE_BRIEF_SOURCE_MISMATCH", "Resolved Style References must be a mapping.")
    raw_references = resolved_style_references.get("references", [])
    if not isinstance(raw_references, Sequence) or isinstance(raw_references, (str, bytes)):
        _error("STYLE_BRIEF_SOURCE_MISMATCH", "Resolved Style References must contain a list.")
    references: dict[str, dict[str, Any]] = {}
    for reference in raw_references:
        if not isinstance(reference, Mapping):
            _error("STYLE_BRIEF_SOURCE_MISMATCH", "Resolved Style References contain an invalid reference.")
        normalized = dict(reference)
        reference_id = _style_reference_id(normalized)
        if reference_id in references:
            _error("STYLE_BRIEF_SOURCE_MISMATCH", f"Duplicate Style Reference: {reference_id}")
        raw_axes = normalized.get("style_axes") or []
        if not isinstance(raw_axes, Sequence) or isinstance(raw_axes, (str, bytes)):
            _error("STYLE_BRIEF_SOURCE_MISMATCH", f"Invalid Style Axis declaration: {reference_id}")
        normalized["style_axes"] = [axis for axis in STYLE_AXES if axis in raw_axes]
        references[reference_id] = normalized

    primary_id = resolved_style_references.get("primary_reference_id")
    if primary_id is not None and primary_id not in references:
        _error("STYLE_BRIEF_SOURCE_MISMATCH", f"Unknown primary Style Reference: {primary_id}")
    raw_secondary_ids = resolved_style_references.get("secondary_reference_ids", [])
    if not isinstance(raw_secondary_ids, Sequence) or isinstance(raw_secondary_ids, (str, bytes)):
        _error("STYLE_BRIEF_SOURCE_MISMATCH", "Secondary Style Reference IDs must be a list.")
    secondary_ids = list(raw_secondary_ids)
    if any(reference_id not in references for reference_id in secondary_ids):
        _error("STYLE_BRIEF_SOURCE_MISMATCH", "Unknown secondary Style Reference.")
    raw_axis_owners = resolved_style_references.get("axis_owners", {})
    if not isinstance(raw_axis_owners, Mapping):
        _error("STYLE_BRIEF_SOURCE_MISMATCH", "Style Axis ownership must be a mapping.")
    axis_owners = {str(axis): str(owner) for axis, owner in raw_axis_owners.items()}
    return references, primary_id, secondary_ids, axis_owners


def _style_description_has_who_pollution(description: str) -> bool:
    lowered = description.casefold()
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", lowered)
        for token in STYLE_WHO_TOKENS
    )


def _normalize_style_description(
    description: Any,
    *,
    error_code: str,
    who_error_code: str = "STYLE_BRIEF_WHO_POLLUTION",
) -> str:
    if not isinstance(description, str) or not description.strip():
        _error(error_code, "Style Axis description must be a non-empty string.")
    normalized = description.strip()
    if _style_description_has_who_pollution(normalized):
        _error(who_error_code, "Style descriptions must not contain WHO identity tokens.")
    return normalized


def validate_style_brief(
    brief: Mapping[str, Any],
    *,
    resolved_style_references: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and normalize a request-scoped Style Brief."""
    if not isinstance(brief, Mapping):
        _error("STYLE_BRIEF_INVALID", "Style Brief must be a mapping.")
    if brief.get("schema_version") != 1:
        _error("STYLE_BRIEF_INVALID", "Style Brief schema_version must be 1.")
    source_reference_id = brief.get("source_reference_id")
    if not isinstance(source_reference_id, str) or not source_reference_id:
        _error("STYLE_BRIEF_SOURCE_MISMATCH", "Style Brief requires source_reference_id.")

    references, _primary_id, _secondary_ids, _axis_owners = _style_reference_index(resolved_style_references)
    source_reference = references.get(source_reference_id)
    if source_reference is None:
        _error("STYLE_BRIEF_SOURCE_MISMATCH", f"Unknown Style Reference: {source_reference_id}")
    expected_priority = source_reference.get("style_priority")
    if brief.get("style_priority") != expected_priority:
        _error("STYLE_BRIEF_PRIORITY_MISMATCH", f"Style Brief priority does not match {source_reference_id}.")

    raw_active_axes = brief.get("active_axes")
    if not isinstance(raw_active_axes, Sequence) or isinstance(raw_active_axes, (str, bytes)):
        _error("STYLE_BRIEF_AXIS_INVALID", "active_axes must be a list.")
    active_axes = list(raw_active_axes)
    if any(not isinstance(axis, str) or axis not in STYLE_AXES for axis in active_axes):
        _error("STYLE_BRIEF_AXIS_INVALID", "Style Brief contains an unknown Axis.")
    if len(set(active_axes)) != len(active_axes):
        _error("STYLE_BRIEF_AXIS_INVALID", "active_axes must not contain duplicates.")
    owned_axes = set(source_reference.get("style_axes") or [])
    unowned_axes = set(active_axes) - owned_axes
    if unowned_axes:
        _error("STYLE_BRIEF_AXIS_UNOWNED", f"Style Brief claims unowned Axes: {sorted(unowned_axes)}")

    raw_axes = brief.get("axes")
    if not isinstance(raw_axes, Mapping):
        _error("STYLE_BRIEF_AXIS_INVALID", "axes must be a mapping.")
    axis_keys = set(raw_axes)
    if any(not isinstance(axis, str) or axis not in STYLE_AXES for axis in axis_keys):
        _error("STYLE_BRIEF_AXIS_INVALID", "axes contains an unknown Axis.")
    unowned_payload_axes = axis_keys - owned_axes
    if unowned_payload_axes:
        _error("STYLE_BRIEF_AXIS_UNOWNED", f"Style Brief contains unowned Axes: {sorted(unowned_payload_axes)}")
    if axis_keys != set(active_axes):
        _error("STYLE_BRIEF_AXIS_INVALID", "axes keys must exactly match active_axes.")

    normalized_axes: dict[str, dict[str, str]] = {}
    for axis in STYLE_AXES:
        if axis not in raw_axes:
            continue
        value = raw_axes[axis]
        if not isinstance(value, Mapping):
            _error("STYLE_BRIEF_INVALID", f"Style Brief Axis payload is invalid: {axis}")
        normalized_axes[axis] = {
            "description": _normalize_style_description(value.get("description"), error_code="STYLE_BRIEF_INVALID"),
            "confidence": _normalize_confidence(value.get("confidence")),
        }

    normalized = dict(brief)
    normalized["schema_version"] = 1
    normalized["source_reference_id"] = source_reference_id
    normalized["style_priority"] = expected_priority
    normalized["active_axes"] = [axis for axis in STYLE_AXES if axis in active_axes]
    normalized["axes"] = normalized_axes
    return normalized


def validate_style_baseline(baseline: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate declared Official Style Baseline evidence without touching assets."""
    if baseline is None:
        _error("STYLE_BASELINE_MISSING", "Official Style Baseline is required for fallback resolution.")
    if not isinstance(baseline, Mapping):
        _error("STYLE_BASELINE_INVALID", "Official Style Baseline must be a mapping.")
    if baseline.get("schema_version") != 1 or baseline.get("mode") != "fallback_only":
        _error("STYLE_BASELINE_INVALID", "Official Style Baseline schema or mode is invalid.")
    baseline_id = baseline.get("baseline_id")
    if not isinstance(baseline_id, str) or not baseline_id.strip():
        _error("STYLE_BASELINE_INVALID", "baseline_id must be non-empty.")
    source_family_id = baseline.get("source_family_id")
    if not isinstance(source_family_id, str) or not source_family_id.strip():
        _error("STYLE_BASELINE_SOURCE_MISMATCH", "source_family_id must be non-empty.")

    evidence = baseline.get("evidence")
    if not isinstance(evidence, Mapping):
        _error("STYLE_BASELINE_INVALID", "Baseline evidence must be a mapping.")
    asset_ids = evidence.get("asset_ids")
    hashes = evidence.get("sha256")
    if not isinstance(asset_ids, Sequence) or isinstance(asset_ids, (str, bytes)):
        _error("STYLE_BASELINE_INVALID", "Baseline evidence asset_ids must be a list.")
    if not isinstance(hashes, Sequence) or isinstance(hashes, (str, bytes)):
        _error("STYLE_BASELINE_INVALID", "Baseline evidence sha256 must be a list.")
    asset_ids = list(asset_ids)
    hashes = list(hashes)
    if len(asset_ids) != len(hashes):
        _error("STYLE_BASELINE_INVALID", "Baseline evidence asset/hash counts must match.")
    if any(not isinstance(asset_id, str) or not asset_id for asset_id in asset_ids):
        _error("STYLE_BASELINE_INVALID", "Baseline evidence asset IDs must be non-empty strings.")
    if any(not isinstance(value, str) or not value for value in hashes):
        _error("STYLE_BASELINE_INVALID", "Baseline evidence hashes must be non-empty strings.")
    if len(set(asset_ids)) != len(asset_ids) or len(set(hashes)) != len(hashes):
        _error("STYLE_BASELINE_DUPLICATE_EVIDENCE", "Baseline evidence must contain distinct assets and hashes.")
    if len(asset_ids) < 2 or len(set(asset_ids)) < 2 or len(set(hashes)) < 2:
        _error("STYLE_BASELINE_EVIDENCE_INSUFFICIENT", "Baseline evidence requires two distinct assets and hashes.")

    consensus_rule = baseline.get("consensus_rule")
    if not isinstance(consensus_rule, Mapping):
        _error("STYLE_BASELINE_INVALID", "consensus_rule must be a mapping.")
    minimum_support = consensus_rule.get("minimum_support")
    if not isinstance(minimum_support, int) or isinstance(minimum_support, bool) or minimum_support < 2:
        _error("STYLE_BASELINE_INVALID", "consensus_rule.minimum_support must be at least 2.")
    if consensus_rule.get("outlier_features_excluded") is not True:
        _error("STYLE_BASELINE_INVALID", "Baseline outlier features must be excluded.")

    axes = baseline.get("axes")
    if not isinstance(axes, Mapping):
        _error("STYLE_BASELINE_INVALID", "Baseline axes must be a mapping.")
    unknown_axes = set(axes) - set(STYLE_AXES)
    if unknown_axes:
        _error("STYLE_BASELINE_INVALID", f"Unknown baseline Axes: {sorted(unknown_axes)}")
    missing_core = set(STYLE_CORE_AXES) - set(axes)
    if missing_core:
        _error("STYLE_BASELINE_INVALID", f"Missing core baseline Axes: {sorted(missing_core)}")
    normalized_axes: dict[str, dict[str, str]] = {}
    for axis in STYLE_AXES:
        if axis not in axes:
            continue
        value = axes[axis]
        if not isinstance(value, Mapping):
            _error("STYLE_BASELINE_INVALID", f"Baseline Axis payload is invalid: {axis}")
        normalized_axes[axis] = {
            "description": _normalize_style_description(
                value.get("description"),
                error_code="STYLE_BASELINE_INVALID",
                who_error_code="STYLE_BASELINE_INVALID",
            ),
            "confidence": _normalize_confidence(value.get("confidence"), error_code="STYLE_BASELINE_INVALID"),
        }

    normalized = dict(baseline)
    normalized["schema_version"] = 1
    normalized["baseline_id"] = baseline_id.strip()
    normalized["mode"] = "fallback_only"
    normalized["source_family_id"] = source_family_id.strip()
    normalized["evidence"] = dict(evidence)
    normalized["evidence"]["asset_ids"] = list(asset_ids)
    normalized["evidence"]["sha256"] = list(hashes)
    normalized["consensus_rule"] = dict(consensus_rule)
    normalized["axes"] = normalized_axes
    return normalized


def _style_brief_sequence(
    style_briefs: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    if style_briefs is None:
        return []
    if isinstance(style_briefs, Mapping):
        if "source_reference_id" in style_briefs:
            return [style_briefs]
        return list(style_briefs.values())
    if isinstance(style_briefs, Sequence) and not isinstance(style_briefs, (str, bytes)):
        return list(style_briefs)
    _error("STYLE_BRIEF_INVALID", "style_briefs must be a sequence or mapping.")


def resolve_style_context(
    *,
    resolved_style_references: Mapping[str, Any],
    style_briefs: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    official_style_baseline: Mapping[str, Any] | None,
    user_style_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve request-scoped Style provenance without entering prompt compilation."""
    references, primary_id, secondary_ids, axis_owners = _style_reference_index(resolved_style_references)
    normalized_briefs: dict[str, dict[str, Any]] = {}
    for brief in _style_brief_sequence(style_briefs):
        normalized_brief = validate_style_brief(
            brief,
            resolved_style_references=resolved_style_references,
        )
        source_id = normalized_brief["source_reference_id"]
        if source_id in normalized_briefs:
            _error("STYLE_BRIEF_SOURCE_MISMATCH", f"Duplicate Style Brief: {source_id}")
        normalized_briefs[source_id] = normalized_brief

    resolved_axes: dict[str, dict[str, str]] = {}
    mode = "official_fallback"
    if primary_id is not None:
        mode = "external"
        primary_reference = references[primary_id]
        primary_owned_axes = set(primary_reference.get("style_axes") or [])
        primary_brief = normalized_briefs.get(primary_id)
        if primary_owned_axes and primary_brief is None:
            _error("STYLE_BRIEF_MISSING", f"Primary Style Brief is missing: {primary_id}")
        if primary_brief is not None and primary_owned_axes - set(primary_brief["active_axes"]):
            _error("STYLE_BRIEF_MISSING", f"Primary Style Brief does not cover all owned Axes: {primary_id}")
        if primary_brief is not None:
            for axis in primary_brief["active_axes"]:
                resolved_axes[axis] = {
                    "description": primary_brief["axes"][axis]["description"],
                    "source": primary_id,
                    "source_type": "primary",
                    "confidence": primary_brief["axes"][axis]["confidence"],
                }

        secondary_id = secondary_ids[0] if secondary_ids else None
        secondary_brief = normalized_briefs.get(secondary_id) if secondary_id is not None else None
        if secondary_brief is not None:
            for axis in secondary_brief["active_axes"]:
                if axis not in resolved_axes and axis_owners.get(axis) == secondary_id:
                    resolved_axes[axis] = {
                        "description": secondary_brief["axes"][axis]["description"],
                        "source": secondary_id,
                        "source_type": "secondary",
                        "confidence": secondary_brief["axes"][axis]["confidence"],
                    }
    else:
        normalized_baseline = validate_style_baseline(official_style_baseline)
        for axis in STYLE_AXES:
            if axis not in normalized_baseline["axes"]:
                continue
            baseline_axis = normalized_baseline["axes"][axis]
            resolved_axes[axis] = {
                "description": baseline_axis["description"],
                "source": normalized_baseline["baseline_id"],
                "source_type": "official_baseline",
                "confidence": baseline_axis["confidence"],
            }

    if user_style_overrides is not None:
        if not isinstance(user_style_overrides, Mapping):
            _error("STYLE_OVERRIDE_DESCRIPTION_INVALID", "user_style_overrides must be a mapping.")
        for axis, raw_override in user_style_overrides.items():
            if not isinstance(axis, str) or axis not in STYLE_AXES:
                _error("STYLE_OVERRIDE_AXIS_INVALID", f"Unknown override Axis: {axis}")
            if not isinstance(raw_override, Mapping):
                _error("STYLE_OVERRIDE_DESCRIPTION_INVALID", f"Invalid override payload: {axis}")
            description = raw_override.get("description")
            if not isinstance(description, str) or not description.strip():
                _error("STYLE_OVERRIDE_DESCRIPTION_INVALID", f"Override description is empty: {axis}")
            if _style_description_has_who_pollution(description.strip()):
                _error("STYLE_OVERRIDE_DESCRIPTION_INVALID", f"Override contains WHO content: {axis}")
            confidence = _normalize_confidence(
                raw_override.get("confidence", "HIGH"),
                error_code="STYLE_OVERRIDE_DESCRIPTION_INVALID",
            )
            resolved_axes[axis] = {
                "description": description.strip(),
                "source": "user_override",
                "source_type": "user_override",
                "confidence": confidence,
            }

    return {
        "mode": mode,
        "primary_reference_id": primary_id,
        "secondary_reference_id": secondary_ids[0] if secondary_ids else None,
        "resolved_axes": {
            axis: resolved_axes[axis]
            for axis in STYLE_AXES
            if axis in resolved_axes
        },
        "protected_identity_properties": list(PROTECTED_IDENTITY_PROPERTIES),
    }


def _managed_contract(asset: Mapping[str, Any], role: str, root: Path) -> dict[str, Any]:
    validate_generation_reference_input(dict(asset, path=str(root / asset.get("path", ""))), root=root)
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
    if any(area in absolute.as_posix().lower() for area in ("calibration/staging", "calibration/preparations")) or not absolute.is_file():
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
        "asset_type": asset.get("asset_type"),
        "sha256": asset.get("sha256"),
        "can_be_generation_reference": True,
        "supported_roles": list(asset["generation_reference"].get("supported_roles", [])),
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
        candidates = [
            asset
            for asset in managed_assets
            if generation_allowed(asset)
            and role in asset.get("generation_reference", {}).get("supported_roles", [])
            and (
                exposure_profile is None
                or exposure_profile
                not in asset.get("generation_reference", {}).get("excluded_for", [])
            )
        ]
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
        validate_generation_reference_input(ref, root=root)
        validate_reference_contract(ref)
    selected.sort(key=lambda ref: (
        ROLE_ORDER[str(ref["role"])],
        {"primary": 0, "secondary": 1, "supplemental": 2}.get(ref.get("generation_priority"), 3),
        str(ref.get("reference_id", "")),
    ))
    generation = config.get("generation", config)
    # Multiple contracts for one physical image share one transport input.
    unique: dict[str, dict[str, Any]] = {}
    for ref in selected:
        key = str(Path(ref["path"]).resolve()).casefold() if ref.get("path") else str(ref["reference_id"])
        if key not in unique:
            unique[key] = dict(ref)
            continue
        kept = unique[key]
        if kept["source_scope"] != ref["source_scope"] or kept.get("asset_id") != ref.get("asset_id"):
            _error("REFERENCE_DUPLICATE_CONFLICT", "One image cannot have conflicting source authorities.")
        inherit = set(kept.get("inherit", [])) | set(ref.get("inherit", []))
        excluded = set(kept.get("do_not_inherit", [])) | set(ref.get("do_not_inherit", []))
        if inherit & excluded:
            _error("REFERENCE_INHERIT_CONFLICT", "Duplicated image contracts disagree on inheritance.")
        kept["duties"] = sorted(set(_reference_duties(kept)) | set(_reference_duties(ref)), key=ROLE_ORDER.get)
        kept["inherit"] = sorted(inherit)
        kept["do_not_inherit"] = sorted(excluded)
        coverage = dict(kept.get("coverage") or {})
        for field in ("profiles", "visible_fields", "view_angles", "occluded_fields"):
            coverage[field] = sorted(set(coverage.get(field, [])) | set((ref.get("coverage") or {}).get(field, [])))
        kept["coverage"] = coverage
    selected = list(unique.values())
    local_count = sum(ref["source_scope"] in {"managed_arco", "request_scoped_arco"} and not ref.get("generated_output_role") for ref in selected)
    external_count = sum(ref["source_scope"] == "external_how" for ref in selected)
    if local_count > int(generation["max_local_arco_references"]) or external_count > int(generation["max_external_references"]) or len(selected) > int(generation["max_total_image_inputs"]):
        _error("REFERENCE_LIMIT_EXCEEDED", "Selected references exceed runtime limits.")
    return selected


def compile_reference_instructions(references: Sequence[Mapping[str, Any]]) -> str:
    """Compile enforceable reference duties without changing the scene prompt."""
    blocks: list[str] = []
    for ref in references:
        validate_reference_contract(ref)
        duties = _reference_duties(ref)
        identity = str(ref.get("reference_id"))
        inherit_fields = set(ref.get("inherit") or [])
        if ref.get("role") == "identity_reference" and {"identity", "face", "hair", "eyes"} <= inherit_fields:
            inherit = "Arco's identity, including her face, hair and eyes"
        else:
            inherit = ", ".join(ref.get("inherit") or []) or "only its assigned reference role"
        excluded = ", ".join(ref.get("do_not_inherit") or []) or "none"
        style_responsibility = ""
        if "style_reference" in duties:
            priority = ref.get("style_priority")
            if priority in STYLE_PRIORITIES:
                style_responsibility = f" Use as the {priority} Style Reference."
            else:
                style_responsibility = " Use as a Style Reference."
        blocks.append(
            f"Reference {identity}: use to define {inherit}.{style_responsibility} Do not inherit: {excluded}."
        )
    return " ".join(blocks)


def _resolved_style_axes(style_context: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(style_context, Mapping):
        _error("STYLE_CONTEXT_INVALID", "Resolved Style Context must be a mapping.")
    axes = style_context.get("resolved_axes")
    if not isinstance(axes, Mapping):
        _error("STYLE_CONTEXT_INVALID", "Resolved Style Context must contain resolved_axes.")
    unknown_axes = [axis for axis in axes if not isinstance(axis, str) or axis not in STYLE_AXES]
    if unknown_axes:
        _error("STYLE_AXIS_UNDECLARED", f"Resolved Style Context contains unknown axes: {unknown_axes}")
    return axes


def _protected_identity_property_labels(style_context: Mapping[str, Any]) -> list[str]:
    raw_properties = style_context.get("protected_identity_properties", [])
    if raw_properties is None:
        raw_properties = []
    if not isinstance(raw_properties, Sequence) or isinstance(raw_properties, (str, bytes)):
        _error("STYLE_CONTEXT_INVALID", "protected_identity_properties must be a sequence.")
    if any(not isinstance(value, str) or not value.strip() for value in raw_properties):
        _error("STYLE_CONTEXT_INVALID", "Protected identity properties must be non-empty strings.")
    properties = set(raw_properties)
    ordered = [field for field in PROTECTED_IDENTITY_PROPERTIES if field in properties]
    ordered.extend(sorted(properties - set(PROTECTED_IDENTITY_PROPERTIES)))
    return [value.replace("_", " ") for value in ordered]


def _style_color_scope_instruction(style_context: Mapping[str, Any]) -> str | None:
    labels = _protected_identity_property_labels(style_context)
    if not labels:
        return None
    if len(labels) == 1:
        protected = labels[0]
    elif len(labels) == 2:
        protected = f"{labels[0]} and {labels[1]}"
    else:
        protected = f"{', '.join(labels[:-1])}, and {labels[-1]}"
    return (
        "  Color scope: Color logic affects overall rendering and palette relationships only; "
        f"preserve intrinsic identity colors for {protected}."
    )


def compile_style_instructions(style_context: Mapping[str, Any]) -> str:
    """Compile only resolved Style Axes into a stable, structured prompt block."""
    axes = _resolved_style_axes(style_context)
    lines: list[str] = []
    for axis in STYLE_AXES:
        if axis not in axes:
            continue
        value = axes[axis]
        if not isinstance(value, Mapping):
            _error("STYLE_CONTEXT_INVALID", f"Resolved Style Axis payload is invalid: {axis}")
        description = value.get("description")
        if not isinstance(description, str) or not description.strip():
            _error("STYLE_CONTEXT_INVALID", f"Resolved Style Axis description is empty: {axis}")
        normalized_description = " ".join(description.split())
        if _style_description_has_who_pollution(normalized_description):
            _error("STYLE_PROMPT_WHO_POLLUTION", f"Resolved Style Axis contains WHO content: {axis}")
        if not lines:
            lines.append(STYLE_PROMPT_HEADER)
        lines.append(f"- {STYLE_AXIS_LABELS[axis]}: {normalized_description}")
        if axis == "color_logic":
            scope = _style_color_scope_instruction(style_context)
            if scope is not None:
                lines.append(scope)
    return "\n".join(lines)


def validate_style_prompt(style_context: Mapping[str, Any], compiled_prompt: str) -> None:
    """Validate that the structured Style block contains exactly resolved Style behavior."""
    axes = _resolved_style_axes(style_context)
    expected_block = compile_style_instructions(style_context)
    style_reference_present = bool(
        style_context.get("primary_reference_id") or style_context.get("secondary_reference_id")
    )
    if not isinstance(compiled_prompt, str):
        _error("STYLE_AXIS_NOT_COMPILED", "Compiled Prompt must be text.")

    lines = compiled_prompt.splitlines()
    header_positions = [index for index, line in enumerate(lines) if line == STYLE_PROMPT_HEADER]
    if not header_positions:
        if style_reference_present:
            _error("STYLE_REFERENCE_UNUSED", "Resolved Style Reference has no Style block in the Prompt.")
        if axes:
            _error("STYLE_AXIS_NOT_COMPILED", "Resolved Style Axes have no Style block in the Prompt.")
        return
    if len(header_positions) != 1:
        _error("STYLE_AXIS_UNDECLARED", "Prompt must contain exactly one structured Style block.")
    if not expected_block:
        _error("STYLE_AXIS_UNDECLARED", "Prompt contains a Style block without resolved Style Axes.")

    start = header_positions[0]
    end = start + 1
    while end < len(lines) and lines[end].strip():
        end += 1
    actual_lines = lines[start:end]
    expected_axis_lines = {
        axis: f"- {STYLE_AXIS_LABELS[axis]}: {' '.join(str(axes[axis]['description']).split())}"
        for axis in STYLE_AXES
        if axis in axes and isinstance(axes[axis], Mapping)
    }
    expected_axis_order = [axis for axis in STYLE_AXES if axis in axes]
    expected_color_scope = _style_color_scope_instruction(style_context) if "color_logic" in axes else None
    actual_axis_order: list[str] = []
    seen_axes: set[str] = set()
    color_scope_seen = False

    for line in actual_lines[1:]:
        if line.startswith("- "):
            label, separator, description = line[2:].partition(": ")
            reverse_labels = {value: key for key, value in STYLE_AXIS_LABELS.items()}
            axis = reverse_labels.get(label)
            if not separator or axis is None or axis not in axes or axis in seen_axes:
                _error("STYLE_AXIS_UNDECLARED", f"Prompt contains an undeclared Style line: {line}")
            if _style_description_has_who_pollution(description):
                _error("STYLE_PROMPT_WHO_POLLUTION", f"Style block contains WHO content: {axis}")
            if line != expected_axis_lines.get(axis):
                _error("STYLE_AXIS_NOT_COMPILED", f"Resolved Style description was not compiled: {axis}")
            seen_axes.add(axis)
            actual_axis_order.append(axis)
        elif line.startswith("  Color scope:"):
            if expected_color_scope is None or line != expected_color_scope or color_scope_seen:
                _error("STYLE_AXIS_UNDECLARED", "Prompt contains an undeclared Style scope instruction.")
            color_scope_seen = True
        else:
            if _style_description_has_who_pollution(line):
                _error("STYLE_PROMPT_WHO_POLLUTION", "Style block contains WHO content.")
            _error("STYLE_AXIS_UNDECLARED", f"Prompt contains undeclared Style text: {line}")

    missing_axes = [axis for axis in expected_axis_order if axis not in seen_axes]
    if missing_axes:
        _error("STYLE_AXIS_NOT_COMPILED", f"Resolved Style Axes are missing from the Prompt: {missing_axes}")
    if actual_axis_order != expected_axis_order:
        _error("STYLE_AXIS_ORDER_INVALID", "Prompt Style Axes are not in canonical order.")
    if expected_color_scope is not None and not color_scope_seen:
        _error("STYLE_IDENTITY_PROTECTION_MISSING", "Color logic is missing its intrinsic identity scope guard.")


def _validated_rendering_hygiene_policy(policy: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(policy, Mapping):
        _error("RENDERING_HYGIENE_POLICY_INVALID", "Rendering Hygiene policy must be a mapping.")
    if type(policy.get("schema_version")) is not int or policy.get("schema_version") != 2:
        _error("RENDERING_HYGIENE_POLICY_INVALID", "Rendering Hygiene policy schema_version must be 2.")
    policy_id = policy.get("policy_id")
    if policy_id is not None and (not isinstance(policy_id, str) or not policy_id.strip()):
        _error("RENDERING_HYGIENE_POLICY_INVALID", "Rendering Hygiene policy_id must be non-empty text.")

    allowed_keys = {"schema_version", "policy_id", *RENDERING_HYGIENE_RULE_FAMILIES}
    unknown_keys = [key for key in policy if not isinstance(key, str) or key not in allowed_keys]
    if unknown_keys:
        _error(
            "RENDERING_HYGIENE_UNSUPPORTED_RULE",
            f"Rendering Hygiene policy contains unsupported rule families or fields: {unknown_keys}",
        )

    missing = [family for family in RENDERING_HYGIENE_RULE_FAMILIES if family not in policy]
    if missing:
        _error("RENDERING_HYGIENE_POLICY_INVALID", f"Rendering Hygiene policy is missing rule families: {missing}")

    rules: dict[str, dict[str, Any]] = {}
    for family in RENDERING_HYGIENE_RULE_FAMILIES:
        rule = policy[family]
        if not isinstance(rule, Mapping):
            _error("RENDERING_HYGIENE_POLICY_INVALID", f"Rendering Hygiene rule must be a mapping: {family}")
        unknown_rule_fields = [key for key in rule if key not in {"enabled", "requires"}]
        if unknown_rule_fields:
            _error(
                "RENDERING_HYGIENE_UNSUPPORTED_RULE",
                f"Rendering Hygiene rule contains unsupported fields: {family}.{unknown_rule_fields}",
            )
        if type(rule.get("enabled")) is not bool:
            _error("RENDERING_HYGIENE_POLICY_INVALID", f"Rendering Hygiene rule enabled must be boolean: {family}")
        requires = rule.get("requires")
        if not isinstance(requires, Mapping) or set(requires) != {"any_of"}:
            _error(
                "RENDERING_HYGIENE_POLICY_INVALID",
                f"Rendering Hygiene rule requires must contain only any_of: {family}",
            )
        any_of = requires.get("any_of")
        if not isinstance(any_of, Sequence) or isinstance(any_of, (str, bytes)) or not any_of:
            _error(
                "RENDERING_HYGIENE_POLICY_INVALID",
                f"Rendering Hygiene rule requires.any_of must be a non-empty list: {family}",
            )
        required_axes = list(any_of)
        if (
            any(not isinstance(axis, str) or axis not in STYLE_AXES for axis in required_axes)
            or len(set(required_axes)) != len(required_axes)
        ):
            _error(
                "RENDERING_HYGIENE_POLICY_INVALID",
                f"Rendering Hygiene rule requires unknown or duplicate Style Axes: {family}",
            )
        rules[family] = {
            "enabled": rule["enabled"],
            "required_axes": tuple(axis for axis in STYLE_AXES if axis in required_axes),
        }
    return rules


def _rendering_hygiene_axis_description(axes: Mapping[str, Any], axis: str) -> str:
    value = axes[axis]
    if not isinstance(value, Mapping):
        _error("STYLE_CONTEXT_INVALID", f"Resolved Style Axis payload is invalid: {axis}")
    description = value.get("description")
    if not isinstance(description, str) or not description.strip():
        _error("STYLE_CONTEXT_INVALID", f"Resolved Style Axis description is empty: {axis}")
    normalized = " ".join(description.split())
    if _style_description_has_who_pollution(normalized):
        _error("RENDERING_HYGIENE_IDENTITY_POLLUTION", f"Resolved Style Axis contains WHO content: {axis}")
    return normalized


def _rendering_hygiene_instruction(
    family: str,
    axes: Mapping[str, Any],
    supporting_axes: Sequence[str],
) -> str:
    descriptions = {
        axis: _rendering_hygiene_axis_description(axes, axis)
        for axis in supporting_axes
    }
    if family == "unsupported_detail_inflation":
        return (
            f"Detail density: Preserve the resolved target: \"{descriptions['detail_density']}\". "
            "Keep local micro-detail within that target; do not inflate unsupported detail."
        )
    if family == "highlight_organization_drift":
        return (
            f"Highlight organization: Preserve the resolved target: \"{descriptions['highlight_language']}\". "
            "Do not fragment, intensify, or spatially expand highlights beyond that target."
        )
    if family == "texture_noise_drift":
        return (
            f"Texture: Preserve the resolved target: \"{descriptions['texture_language']}\". "
            "Retain its intentional texture and constrain only unsupported texture noise."
        )
    if family == "material_rendering_drift":
        return (
            f"Material rendering: Preserve the resolved target: \"{descriptions['material_rendering']}\". "
            "Do not shift surfaces toward a different material treatment."
        )
    if family == "lighting_effect_inflation":
        return (
            f"Lighting: Preserve the resolved target: \"{descriptions['lighting_language']}\". "
            "Preserve its exposure balance and do not intensify or spatially expand secondary lighting effects beyond that target."
        )
    if family == "detail_hierarchy_flattening":
        target = "; ".join(
            f"{STYLE_AXIS_LABELS[axis]}: \"{descriptions[axis]}\""
            for axis in supporting_axes
        )
        return (
            f"Detail hierarchy: Preserve the relative subject, secondary-element, and background hierarchy supported by: {target}. "
            "Do not globally raise or lower detail density."
        )
    _error("RENDERING_HYGIENE_UNSUPPORTED_RULE", f"Unknown Rendering Hygiene family: {family}")


def compile_rendering_hygiene(
    style_context: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
) -> str:
    """Compile fixed, style-relative Rendering Hygiene guardrails."""
    rules = _validated_rendering_hygiene_policy(policy)
    if not any(rule["enabled"] for rule in rules.values()):
        return ""
    axes = _resolved_style_axes(style_context)
    if not axes:
        _error(
            "RENDERING_HYGIENE_STYLE_CONTEXT_MISSING",
            "Rendering Hygiene requires at least one resolved Style Axis.",
        )

    active_rules: list[tuple[str, tuple[str, ...]]] = []
    for family in RENDERING_HYGIENE_RULE_FAMILIES:
        rule = rules[family]
        supporting_axes = tuple(axis for axis in rule["required_axes"] if axis in axes)
        if rule["enabled"] and supporting_axes:
            active_rules.append((family, supporting_axes))
    if not active_rules:
        return ""

    lines = [RENDERING_HYGIENE_HEADER]
    lines.extend(
        f"- {_rendering_hygiene_instruction(family, axes, supporting_axes)}"
        for family, supporting_axes in active_rules
    )
    lines.append(f"- {RENDERING_HYGIENE_ESCAPE_CLAUSE}")
    return "\n".join(lines)


def validate_rendering_hygiene(
    style_context: Mapping[str, Any],
    compiled_prompt: str,
    *,
    policy: Mapping[str, Any],
) -> None:
    """Validate the controlled Hygiene block without classifying free-text Style."""
    expected_block = compile_rendering_hygiene(style_context, policy=policy)
    if not isinstance(compiled_prompt, str):
        _error("RENDERING_HYGIENE_MISSING", "Compiled Prompt must be text.")

    lines = compiled_prompt.splitlines()
    header_positions = [index for index, line in enumerate(lines) if line == RENDERING_HYGIENE_HEADER]
    if not expected_block:
        if header_positions:
            _error("RENDERING_HYGIENE_STYLE_CONFLICT", "Prompt contains a Hygiene block while all policy rules are disabled.")
        return
    if not header_positions:
        _error("RENDERING_HYGIENE_MISSING", "Enabled Rendering Hygiene policy has no block in the Prompt.")
    if len(header_positions) != 1:
        _error("RENDERING_HYGIENE_STYLE_CONFLICT", "Prompt must contain exactly one Rendering Hygiene block.")

    start = header_positions[0]
    end = start + 1
    while end < len(lines) and lines[end].strip():
        end += 1
    actual_block = "\n".join(lines[start:end])
    if _style_description_has_who_pollution(actual_block):
        _error(
            "RENDERING_HYGIENE_IDENTITY_POLLUTION",
            "Rendering Hygiene must describe rendering behavior, not identity.",
        )
    if actual_block != expected_block:
        _error(
            "RENDERING_HYGIENE_STYLE_CONFLICT",
            "Rendering Hygiene block differs from the controlled style-relative template.",
        )


def _style_reference_contract_index(
    references: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for reference in references:
        validate_reference_contract(reference)
        if "style_reference" not in _reference_duties(reference):
            continue
        reference_id = reference.get("reference_id") or reference.get("asset_id") or reference.get("request_reference_id")
        if not isinstance(reference_id, str) or not reference_id:
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Style References require a stable reference ID.")
        if reference_id in result:
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", f"Duplicate Style Reference: {reference_id}")
        result[reference_id] = reference
    return result


def _validate_style_context_reference_match(
    style_context: Mapping[str, Any],
    references: Sequence[Mapping[str, Any]],
) -> None:
    axes = _resolved_style_axes(style_context)
    style_references = _style_reference_contract_index(references)
    mode = style_context.get("mode")
    primary_id = style_context.get("primary_reference_id")
    secondary_id = style_context.get("secondary_reference_id")
    if primary_id is not None and not isinstance(primary_id, str):
        _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Style Context primary_reference_id is invalid.")
    if secondary_id is not None and not isinstance(secondary_id, str):
        _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Style Context secondary_reference_id is invalid.")

    declared_primaries = [key for key, value in style_references.items() if value.get("style_priority") == "primary"]
    declared_secondaries = [key for key, value in style_references.items() if value.get("style_priority") == "secondary"]

    if mode == "external":
        if primary_id not in style_references:
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "External Style Context primary does not match current References.")
        if declared_primaries and declared_primaries != [primary_id]:
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Style Context primary conflicts with Reference priority.")
        if not declared_primaries:
            only_reference = style_references.get(primary_id)
            if len(style_references) != 1 or only_reference is None or "style_priority" in only_reference:
                _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Current Style References do not declare the Context primary.")
        if secondary_id is None:
            if declared_secondaries:
                _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Style Context is missing the current secondary Reference.")
        elif secondary_id not in style_references or declared_secondaries != [secondary_id]:
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Style Context secondary does not match current References.")
        if set(style_references) != {value for value in (primary_id, secondary_id) if value is not None}:
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Style Context does not account for every current Style Reference.")
    elif mode == "official_fallback":
        if primary_id is not None or declared_primaries:
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Official fallback conflicts with an External Primary Style Reference.")
        if len(style_references) == 1 and "style_priority" not in next(iter(style_references.values())):
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Unresolved Style Reference priority cannot accompany official fallback.")
        if secondary_id is None:
            if declared_secondaries:
                _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Official fallback Context is missing the current secondary Reference.")
        elif secondary_id not in style_references or declared_secondaries != [secondary_id]:
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Official fallback secondary does not match current References.")
        if set(style_references) != ({secondary_id} if secondary_id is not None else set()):
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Official fallback does not account for every current Style Reference.")
    else:
        _error("STYLE_CONTEXT_REFERENCE_MISMATCH", "Style Context mode is not recognized.")

    for axis, value in axes.items():
        if not isinstance(value, Mapping):
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", f"Style Axis provenance is invalid: {axis}")
        source_type = value.get("source_type")
        source = value.get("source")
        if source_type == "primary" and (mode != "external" or source != primary_id):
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", f"Primary provenance does not match the Context: {axis}")
        if source_type == "secondary" and (mode != "external" or source != secondary_id):
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", f"Secondary provenance does not match the Context: {axis}")
        if source_type == "official_baseline" and (mode != "official_fallback" or primary_id is not None):
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", f"Official Baseline provenance conflicts with the Context: {axis}")
        if source_type == "user_override" and source != "user_override":
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", f"User Override provenance is invalid: {axis}")
        if source_type not in {"primary", "secondary", "official_baseline", "user_override"}:
            _error("STYLE_CONTEXT_REFERENCE_MISMATCH", f"Unknown Style Axis provenance: {axis}")


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
    style_context: Mapping[str, Any] | None = None,
    rendering_hygiene_policy: Mapping[str, Any] | None = None,
    revision_stability_guard: Any = None,
    composition_readability_plan: Any = None,
) -> str:
    """Compile Identity facts, resolved Style, reference duties, and the scene.

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

    style_references = _style_reference_contract_index(references)
    if style_references and style_context is None:
        _error("STYLE_CONTEXT_MISSING", "Style References require a resolved Style Context.")
    if style_context is not None:
        _validate_style_context_reference_match(style_context, references)
        style_text = compile_style_instructions(style_context)
    else:
        style_text = ""

    rendering_hygiene_text = ""
    if rendering_hygiene_policy is not None:
        hygiene_rules = _validated_rendering_hygiene_policy(rendering_hygiene_policy)
        if any(rule["enabled"] for rule in hygiene_rules.values()) and style_context is None:
            _error("STYLE_CONTEXT_MISSING", "Enabled Rendering Hygiene requires a Resolved Style Context.")
        if style_context is not None:
            rendering_hygiene_text = compile_rendering_hygiene(
                style_context,
                policy=rendering_hygiene_policy,
            )

    reference_text = compile_reference_instructions(references)
    stability_text = ""
    if revision_stability_guard is not None:
        from revision_stability import compile_revision_stability
        stability_text = compile_revision_stability(revision_stability_guard)
    readability_text = ""
    if composition_readability_plan is not None:
        from composition_readability import compile_readability
        readability_text = compile_readability(composition_readability_plan)

    if style_context is None:
        # Keep the legacy no-Style call byte-for-byte stable.
        pieces = identity_parts + ([reference_text] if reference_text else []) + [base_prompt.strip()]
        if readability_text:
            pieces.append(readability_text)
        if stability_text:
            pieces.append(stability_text)
        if constraints:
            pieces.append(" ".join(constraints))
        prompt = " ".join(piece for piece in pieces if piece).strip()
    else:
        pieces = identity_parts + ([style_text] if style_text else [])
        pieces += ([reference_text] if reference_text else []) + [base_prompt.strip()]
        if readability_text:
            pieces.append(readability_text)
        if stability_text:
            pieces.append(stability_text)
        if rendering_hygiene_text:
            pieces.append(rendering_hygiene_text)
        if constraints:
            pieces.append(" ".join(constraints))
        prompt = "\n\n".join(piece for piece in pieces if piece).strip()
        validate_style_prompt(style_context, prompt)
        if rendering_hygiene_text:
            validate_rendering_hygiene(
                style_context,
                prompt,
                policy=rendering_hygiene_policy,
            )

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
    if all(isinstance(path, str) and path for path in paths) and len({str(Path(path).resolve()).casefold() for path in paths}) != len(paths):
        _error("REFERENCE_DUPLICATE_CONFLICT", "Deduplicate physical images before building an invocation.")
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
    """Serialize the built-in tool schema after excluding local-only evidence."""
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
        for path in paths:
            validate_generation_reference_input({"path": path})
        result["referenced_image_paths"] = list(paths)
    elif isinstance(recent, int) and recent > 0:
        result["num_last_images_to_include"] = recent
    else:
        _error("IMAGE_INPUT_BUILD_FAILED", "Reference-conditioned invocation has no valid image input.")
    return result
