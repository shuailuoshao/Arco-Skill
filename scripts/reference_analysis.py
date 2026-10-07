"""Caller-owned visual analysis, frozen confirmation and bounded visual repair.

This module validates evidence records; it never infers image content or claims
that a caller's confirmation string independently proves human authorization.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from reference_runtime import (ReferenceRuntimeError, _managed_contract, generation_allowed,
                               validate_generation_reference_input)

DIMENSIONS = ("identity", "composition", "pose", "expression", "lighting")
DETAILS = {
    "identity": ("face_structure", "hair_structure", "body_proportions", "outfit"),
    "composition": ("framing", "camera", "subject_position", "negative_space"),
    "pose": ("body_direction", "limb_relationships", "occlusion"),
    "expression": ("brows", "eyelids", "gaze", "mouth"),
    "lighting": ("light_regions", "shadow_regions", "shadow_edges", "cast_shadows", "highlights"),
}
REVIEW_DIMENSIONS = ("identity", "composition_pose", "expression", "lighting_style")


def fail(code: str, message: str) -> None:
    raise ReferenceRuntimeError(code, message)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def file_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail("REFERENCE_ANALYSIS_INVALID", f"Nonempty description required: {where}")
    return value.strip()


def select_split_references(*, root: Path, assets: Sequence[Mapping[str, Any]],
                            analysis: Mapping[str, Any] | None, profile: str,
                            variant_id: str | None,
                            descriptors: Sequence[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """Select compatible published layers, never fall back to a full composite."""
    if not isinstance(analysis, Mapping):
        fail("REFERENCE_ANALYSIS_REQUIRED", "Inspect references and supply reference_analysis before planning.")
    if not variant_id:
        fail("VARIANT_SELECTION_REQUIRED", "Split references require a selected Variant.")
    expression = analysis.get("expression")
    if not isinstance(expression, Mapping):
        fail("REFERENCE_ANALYSIS_INVALID", "Expression analysis is required.")
    expression_id = expression.get("library_asset_id")
    by_id = {asset["asset_id"]: asset for asset in assets}
    face = by_id.get(expression_id)
    hidden_face = profile == "back_view" and expression.get("face_visible") is False
    back_identity_ids = []
    if hidden_face:
        import yaml
        from outfit_design import require_completed_calibration
        identity_document = yaml.safe_load((root / "character/identity.yaml").read_text(encoding="utf-8"))
        if identity_document.get("approved_view_designs"):
            require_completed_calibration(root, identity_document, code="IDENTITY_CALIBRATION_REQUIRED")
            back_identity_ids = ((identity_document.get("approved_view_designs") or {}).get("back") or {}).get("reference_asset_ids", [])
    if profile == "back_view" and not hidden_face:
        fail("SPLIT_REFERENCE_INCOMPLETE" if "face_visible" not in expression else "BACK_FACE_VISIBILITY_REQUIRED", "Back production requires explicit face_visible: false analysis.")
    if hidden_face and expression_id:
        fail("BACK_EXPRESSION_NOT_APPLICABLE", "A face-invisible back view has no expression PNG.")
    if not hidden_face and (face is None or "expression_evidence" not in (face.get("roles") or [])):
        fail("EXPRESSION_REFERENCE_REQUIRED", "Select an actual published expression PNG after visual comparison.")
    if not hidden_face and not generation_allowed(face):
        fail("ASSET_NOT_ALLOWED_FOR_GENERATION", str(expression_id))
    view = "back" if hidden_face else face.get("view_class")
    def normalized_view(value):
        return "front" if value in {"front", "frontal"} else value
    selected_ids: dict[str, str] = {}
    for descriptor in descriptors:
        role = descriptor.get("role")
        if role not in {"identity_reference", "outfit_reference", "face_reference"} or role in selected_ids:
            fail("SPLIT_REFERENCE_INVALID", "Split selection accepts one explicit asset per WHO role.")
        selected_ids[role] = descriptor.get("asset_id")
        asset = by_id.get(descriptor.get("asset_id"))
        if asset is not None:
            validate_generation_reference_input(
                dict(asset, path=str(root / asset.get("path", ""))), root=root)
    if "face_reference" in selected_ids and selected_ids["face_reference"] != expression_id:
        fail("REFERENCE_ANALYSIS_SOURCE_MISMATCH", "Expression selection differs from analysis.")

    def choose(kind: str, role: str) -> Mapping[str, Any]:
        candidates = [asset for asset in assets if generation_allowed(asset)
                      and asset.get("asset_type") == kind
                      and role in asset["generation_reference"]["supported_roles"]
                      and profile not in asset["generation_reference"].get("excluded_for", [])
                      and normalized_view(asset.get("view_class")) == normalized_view(view)
                      and (role != "outfit_reference" or asset.get("variant_id") == variant_id)]
        if hidden_face:
            required = {"identity", "hair.back", "body.back"} if role == "identity_reference" else {"variant.back_outfit"}
            candidates = [asset for asset in candidates if required <= (
                set(asset["generation_reference"]["coverage"].get("visible_fields") or [])
                - set(asset["generation_reference"]["coverage"].get("occluded_fields") or []))
                and set(asset["generation_reference"]["coverage"].get("view_angles") or []) & {"back", "back_three_quarter"}]
        if role in selected_ids:
            candidates = [asset for asset in candidates if asset["asset_id"] == selected_ids[role]]
        elif role == "identity_reference":
            preferred_identity = {
                "front": "casual-outfit-crossed-arms-evidence",
                "three_quarter_right": "casual-outfit-open-arms-no-horns-evidence",
            }.get(normalized_view(view))
            if not hidden_face:
                candidates = [asset for asset in candidates if asset["asset_id"] == preferred_identity]
        if not candidates:
            if hidden_face and role == "identity_reference":
                fail("IDENTITY_CALIBRATION_REQUIRED", "Publish a separately approved back identity baseline before back production.")
            fail("SPLIT_REFERENCE_INCOMPLETE", f"No permitted compatible {kind} for {view}/{profile}; enter Reviewer.")
        return sorted(candidates, key=lambda asset: (
            hidden_face and role == "identity_reference" and asset["asset_id"] not in back_identity_ids,
            {"primary": 0, "secondary": 1, "supplemental": 2}.get(asset["generation_reference"].get("priority"), 3),
            asset["asset_id"]))[0]

    dressed = choose("faceless_composite", "identity_reference") if hidden_face else None
    outfit = choose("faceless_composite", "outfit_reference")
    identity = analysis.get("identity") or {}
    body_mode = identity.get("body_reference_mode", "clothed_only")
    if body_mode == "body_base":
        fail("BODY_BASE_NOT_ALLOWED", "Use approved clothed identity references.")
    if body_mode != "clothed_only":
        fail("SPLIT_REFERENCE_INVALID", "Unknown body_reference_mode.")
    if "body_reference_mode" in identity:
        text(identity.get("body_reference_reason"), "identity.body_reference_reason")
    result = []
    separate_dressed_identity = False
    dressed = dressed or choose("faceless_composite", "identity_reference")
    if dressed["asset_id"] != outfit["asset_id"]:
        contract = _managed_contract(dressed, "identity_reference", root)
        # The requested Variant owns clothing, even when the identity
        # silhouette is supplied by another approved dressed Variant.
        contract["inherit"] = sorted((set(contract["inherit"]) - {"outfit", "variant"}) | {"body_proportions"})
        contract["do_not_inherit"] = sorted(set(contract["do_not_inherit"]) | {"outfit", "variant"})
        result.append(contract)
        separate_dressed_identity = True
    costume = _managed_contract(outfit, "outfit_reference", root)
    # One image supplies costume plus hair/blank face silhouette. The face PNG
    # supplies eyes/features; neither layer alone claims a complete face.
    costume["duties"] = ["outfit_reference"] if separate_dressed_identity else ["outfit_reference", "identity_reference"]
    if not separate_dressed_identity:
        costume["inherit"] = sorted(set(costume["inherit"]) | {"body_proportions"})
    result.append(costume)
    if not hidden_face:
        result.append(_managed_contract(face, "face_reference", root))
    return result


def validate_analysis(analysis: Any, references: Sequence[Mapping[str, Any]],
                      style_context: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(analysis, Mapping) or analysis.get("schema_version") != 1:
        fail("REFERENCE_ANALYSIS_INVALID", "reference_analysis requires schema_version 1.")
    result = deepcopy(dict(analysis))
    hidden_face = isinstance(result.get("expression"), Mapping) and result["expression"].get("face_visible") is False
    ids = {ref["reference_id"] for ref in references if not ref.get("generated_output_role")}
    sources = result.get("sources")
    if not isinstance(sources, list) or any(not isinstance(item, str) for item in sources) or len(set(sources)) != len(sources) or set(sources) != ids:
        fail("REFERENCE_ANALYSIS_SOURCE_MISMATCH", "Analysis sources must exactly match selected original references.")
    for dimension in DIMENSIONS:
        entry = result.get(dimension)
        if not isinstance(entry, Mapping):
            fail("REFERENCE_ANALYSIS_INVALID", f"Missing {dimension} analysis.")
        source_ids = entry.get("source_reference_ids")
        if not isinstance(source_ids, list) or not source_ids or any(not isinstance(item, str) for item in source_ids) or set(source_ids) - ids:
            fail("REFERENCE_ANALYSIS_SOURCE_MISMATCH", f"Invalid sources for {dimension}.")
        details = () if hidden_face and dimension == "expression" else DETAILS[dimension]
        for key in (*details, "observations", "transfer_target"):
            text(entry.get(key), f"{dimension}.{key}")
    for key in ("allowed_adjustments", "uncertainties"):
        if not isinstance(result.get(key), list) or any(not isinstance(item, str) or not item.strip() for item in result[key]):
            fail("REFERENCE_ANALYSIS_INVALID", f"{key} must be a list of descriptions.")
    if result["uncertainties"]:
        fail("REFERENCE_ANALYSIS_UNRESOLVED", "Resolve critical uncertainties with the user before freezing a generation plan.")
    expression = result["expression"]
    face = next((ref for ref in references if ref.get("role") == "face_reference"), None)
    if hidden_face:
        back_anchors = [ref for ref in references if set((ref.get("coverage") or {}).get("view_angles") or []) & {"back", "back_three_quarter"}]
        if face is not None or expression.get("library_asset_id") or not any("identity_reference" in ref.get("duties", [ref.get("role")]) for ref in back_anchors):
            fail("REFERENCE_ANALYSIS_SOURCE_MISMATCH", "Face-invisible analysis requires a real back identity anchor and no expression PNG.")
    else:
        if face is None or expression.get("library_asset_id") != face.get("asset_id"):
            fail("REFERENCE_ANALYSIS_SOURCE_MISMATCH", "Expression must bind to the selected managed face layer.")
        text(expression.get("library_adjustments"), "expression.library_adjustments")
    style = result.get("style")
    if not isinstance(style, Mapping) or style.get("context_sha256") != digest(style_context):
        fail("REFERENCE_ANALYSIS_STYLE_MISMATCH", "Style analysis must reference the resolved Style Brief context hash.")
    identity_sources = set(result["identity"]["source_reference_ids"])
    if any(ref["source_scope"] == "external_how" and ref["reference_id"] in identity_sources for ref in references):
        fail("REFERENCE_ANALYSIS_WHO_POLLUTION", "External references cannot establish Arco identity.")
    anchors = {ref["reference_id"] for ref in references
               if ref.get("role") in {"identity_reference", "outfit_reference", "face_reference"}}
    if not anchors <= identity_sources:
        fail("REFERENCE_ANALYSIS_SOURCE_MISMATCH", "Identity analysis must inspect the clothed identity, outfit and feature layers.")
    return result


def compile_analysis(analysis: Mapping[str, Any]) -> str:
    hidden_face = analysis["expression"].get("face_visible") is False
    blocks = ["[Reference Analysis]", "Keep Arco's back hair construction, intrinsic colors and body proportions. The face is invisible; do not add facial features or an expression layer." if hidden_face else "Keep Arco's facial structure, hair construction, intrinsic colors and body proportions; transfer rendering, pose and expression without replacing identity."]
    for dimension in DIMENSIONS:
        entry = analysis[dimension]
        blocks.append(f"{dimension}: {entry['transfer_target']}")
        if not (hidden_face and dimension == "expression"):
            blocks.extend(f"  {key}: {entry[key]}" for key in DETAILS[dimension])
    if not hidden_face:
        blocks.append("Expression library adjustment: " + analysis["expression"]["library_adjustments"])
    blocks.extend("Allowed adjustment: " + item for item in analysis["allowed_adjustments"])
    blocks.append("[/Reference Analysis]")
    return "\n".join(blocks)


def freeze_analysis(*, analysis: Mapping[str, Any], prompt: str,
                    references: Sequence[Mapping[str, Any]], request: Mapping[str, Any]) -> dict[str, Any]:
    paths = [str(Path(ref["path"]).resolve()) for ref in references]
    payload = {"reference_analysis": deepcopy(dict(analysis)), "prompt": prompt,
               "references": [dict(ref, sha256=file_hash(ref["path"])) for ref in references],
               "request": {key: deepcopy(value) for key, value in request.items()
                           if key != "analysis_confirmation"}}
    return {"schema_version": 1, "plan_sha256": digest(payload),
            "image_hashes": {path: file_hash(path) for path in paths},
            "prompt_sha256": digest(prompt), "contracts_sha256": digest(list(references)),
            "max_automatic_repairs": 1}


def validate_confirmation(confirmation: Any, frozen: Mapping[str, Any]) -> None:
    if not isinstance(confirmation, Mapping) or confirmation.get("user_confirmed") is not True:
        fail("ANALYSIS_CONFIRMATION_REQUIRED", "Show the actual preview and wait for explicit human confirmation.")
    if confirmation.get("plan_sha256") != frozen["plan_sha256"]:
        fail("ANALYSIS_CONFIRMATION_STALE", "Analysis, prompt, request or reference contents changed after confirmation.")
    text(confirmation.get("user_message"), "analysis_confirmation.user_message")


def validate_plan_binding(invocation: Mapping[str, Any], references: Sequence[Mapping[str, Any]]) -> None:
    frozen = invocation.get("analysis_preview")
    if frozen is None:
        return
    validate_confirmation(invocation.get("analysis_confirmation"), frozen)
    if digest(invocation["prompt"]) != frozen["prompt_sha256"] or digest(list(references)) != frozen["contracts_sha256"]:
        fail("ANALYSIS_CONFIRMATION_STALE", "Frozen prompt or contracts changed.")
    actual = {str(Path(ref["path"]).resolve()): file_hash(ref["path"]) for ref in references}
    if actual != frozen["image_hashes"]:
        fail("ANALYSIS_CONFIRMATION_STALE", "Reference image contents changed.")
    for path, expected in frozen.get("library_hashes", {}).items():
        if not Path(path).is_file() or file_hash(path) != expected:
            fail("ANALYSIS_CONFIRMATION_STALE", "Approved design or identity definition changed.")


def validate_visual_review(review: Any, *, output_path: Path, frozen: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(review, Mapping) or review.get("plan_sha256") != frozen["plan_sha256"]:
        fail("VISUAL_REVIEW_INVALID", "Review must bind to the approved plan.")
    if review.get("output_sha256") != file_hash(output_path):
        fail("VISUAL_REVIEW_INVALID", "Review must bind to the actual output contents.")
    if review.get("inspected_original_size") is not True:
        fail("VISUAL_REVIEW_INVALID", "Inspect the original-size image before reporting a review.")
    checks = review.get("checks")
    if not isinstance(checks, Mapping) or set(checks) != set(REVIEW_DIMENSIONS):
        fail("VISUAL_REVIEW_INVALID", "Review all identity, composition/pose, expression and lighting/style dimensions.")
    for dimension, check in checks.items():
        if not isinstance(check, Mapping) or check.get("status") not in {"PASS", "FAIL", "UNVERIFIED"}:
            fail("VISUAL_REVIEW_INVALID", f"Invalid check: {dimension}")
        text(check.get("evidence"), f"visual_review.{dimension}.evidence")
    result = deepcopy(dict(review))
    statuses = {check["status"] for check in checks.values()}
    result["status"] = "FAIL" if "FAIL" in statuses else "UNVERIFIED" if "UNVERIFIED" in statuses else "PASS"
    result["user_accepted"] = False
    return result
