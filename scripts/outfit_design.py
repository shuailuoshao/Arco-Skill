"""Approved outfit designs and source lineage, separate from evidence Facts."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from reference_analysis import digest, fail, text

SLOTS = ("upper", "lower", "footwear", "hosiery", "accessories", "outerwear")
ORIGINS = {"source", "completion", "redesign", "omitted"}


def descriptions(value: Any, where: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, list) or (required and not value):
        fail("DESIGN_INVALID", f"{where} must be a list of descriptions.")
    return [text(item, where) for item in value]


def validate_design(design: Any, sources: list[dict] | None = None) -> dict:
    if not isinstance(design, dict) or design.get("schema_version") != 1:
        fail("DESIGN_INVALID", "Design requires schema_version 1.")
    parts = design.get("parts")
    if not isinstance(parts, dict) or set(parts) != set(SLOTS):
        fail("DESIGN_INCOMPLETE", "Specify upper, lower, footwear, hosiery, accessories and outerwear, including explicit omissions.")
    available = {(s["source_id"], p["part_id"]): p for s in sources or [] for p in s["parts"]}
    for slot, part in parts.items():
        if not isinstance(part, dict) or part.get("origin") not in ORIGINS:
            fail("DESIGN_INVALID", f"Invalid origin for {slot}.")
        text(part.get("description"), f"parts.{slot}.description")
        descriptions(part.get("fixed_features"), f"parts.{slot}.fixed_features")
        bindings = part.get("source_bindings")
        if not isinstance(bindings, list) or (part["origin"] in {"source", "redesign"} and not bindings):
            fail("DESIGN_SOURCE_REQUIRED", f"{slot} requires source bindings.")
        if part["origin"] in {"completion", "omitted"} and bindings:
            fail("DESIGN_INVALID", f"{slot} must preserve the distinction between observed and authored content.")
        for binding in bindings:
            if not isinstance(binding, dict) or not binding.get("source_id") or not binding.get("part_id"):
                fail("DESIGN_SOURCE_REQUIRED", f"Invalid part binding for {slot}.")
            if sources is not None:
                observed = available.get((binding["source_id"], binding["part_id"]))
                if observed is None or observed["slot"] != slot:
                    fail("DESIGN_SOURCE_MISMATCH", f"{slot} does not match the selected source part.")
        if part["origin"] in {"completion", "redesign"}:
            text(part.get("decision_reason"), f"parts.{slot}.decision_reason")
    descriptions(design.get("wearing_relations"), "wearing_relations", required=True)
    descriptions(design.get("fixed_constraints"), "fixed_constraints", required=True)
    details = design.get("detail_requirements")
    if not isinstance(details, list):
        fail("DESIGN_INVALID", "detail_requirements must be a list.")
    seen = set()
    for detail in details:
        if not isinstance(detail, dict) or not isinstance(detail.get("view_id"), str) or not detail["view_id"].startswith("detail-") or detail["view_id"] in seen:
            fail("DESIGN_INVALID", "Detail views require unique detail-* IDs.")
        seen.add(detail["view_id"])
        text(detail.get("description"), "detail.description")
        ids = detail.get("source_ids")
        if not isinstance(ids, list) or (sources is not None and set(ids) - {s["source_id"] for s in sources}):
            fail("DESIGN_SOURCE_MISMATCH", "Detail sources must belong to this preparation.")
    # Observation statuses stay in the source records. Approval creates design
    # authority only; it never manufactures CANON or independent consensus.
    return design


def validate_approved_design(entity: Mapping[str, Any]) -> None:
    design = entity.get("design_definition")
    if design is None:  # Legacy Variants remain valid without migration.
        return
    validate_design(design, entity.get("source_materials"))
    approval = entity.get("approval_context")
    if not isinstance(approval, Mapping) or approval.get("user_confirmed") is not True:
        fail("DESIGN_APPROVAL_REQUIRED", "Published designs require explicit approval context.")
    if approval.get("design_sha256") != digest(design):
        fail("DESIGN_APPROVAL_STALE", "Approved design definition changed.")
    for key in ("user_message", "preparation_id", "reference_pack_sha256"):
        text(approval.get(key), "approval_context." + key)
    for key in ("gap_resolutions", "conflict_resolutions"):
        decisions = design.get(key, {})
        if not isinstance(decisions, dict):
            fail("DESIGN_INVALID", key + " must be a mapping.")
        for identifier, decision in decisions.items():
            text(identifier, key + ".id")
            text(decision, key + ".decision")


def require_completed_calibration(root: Path, entity: Mapping[str, Any], *, code: str) -> None:
    """New authored definitions become production authority after completion."""
    import re
    import yaml
    cid = entity.get("last_calibration_id")
    if not isinstance(cid, str) or not re.fullmatch(r"cal-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}", cid):
        fail(code, "Approved design has no valid completed Calibration link.")
    history = root / "calibration/history" / (cid + ".yaml")
    marker = history.with_suffix(".complete")
    if not history.is_file() or not marker.is_file() or marker.read_text(encoding="utf-8").strip() != cid:
        fail(code, "Finish or recover this design's publication before production planning.")
    data = yaml.safe_load(history.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("user_confirmed") is not True or not any(
        t.get("entity_ref") == entity.get("entity_ref") and t.get("revision_after") == entity.get("revision") for t in data.get("targets", []) if isinstance(t, dict)):
        fail(code, "Calibration history does not match the published design revision.")


def compile_design(entity: Mapping[str, Any]) -> str:
    validate_approved_design(entity)
    design = entity.get("design_definition")
    if design is None:
        return ""
    lines = ["[Approved Variant Design]", "Use this fixed complete outfit, including its approved authored completions."]
    for slot, part in design["parts"].items():
        lines.append(f"{slot} ({part['origin']}): {part['description']}")
        lines.extend("Keep: " + value for value in part["fixed_features"])
        if part["origin"] in {"completion", "redesign"}:
            lines.append("Approved decision: " + part["decision_reason"])
    lines.extend("Wearing relation: " + value for value in design["wearing_relations"])
    lines.extend("Fixed constraint: " + value for value in design["fixed_constraints"])
    for key in ("gap_resolutions", "conflict_resolutions"):
        decisions = design.get(key, {})
        if not isinstance(decisions, dict):
            fail("DESIGN_INVALID", key + " must bind IDs to approved decisions.")
        lines.extend("Approved " + key + " " + str(identifier) + ": " + text(value, key) for identifier, value in decisions.items())
    lines.append("[/Approved Variant Design]")
    return "\n".join(lines)


def compile_back_identity(identity: Mapping[str, Any]) -> str:
    entry = (identity.get("approved_view_designs") or {}).get("back")
    if entry is None:
        return ""
    validate_back_identity(entry)
    return "[Approved Back Identity]\n" + "\n".join(entry["definition"]["fixed_constraints"] + ["Approved rear completion: " + value for value in entry["definition"]["completion_decisions"]]) + "\n[/Approved Back Identity]"


def validate_back_identity(entry: Any) -> None:
    if not isinstance(entry, Mapping) or not isinstance(entry.get("definition"), dict):
        fail("IDENTITY_DESIGN_INVALID", "Back identity requires a design definition.")
    definition = entry["definition"]
    if definition.get("schema_version") != 1:
        fail("IDENTITY_DESIGN_INVALID", "Back identity definition requires schema_version 1.")
    descriptions(definition.get("fixed_constraints"), "back identity.fixed_constraints", required=True)
    descriptions(definition.get("completion_decisions"), "back identity.completion_decisions")
    approval = entry.get("approval_context")
    if not isinstance(approval, Mapping) or approval.get("user_confirmed") is not True or approval.get("design_sha256") != digest(definition):
        fail("IDENTITY_DESIGN_APPROVAL_REQUIRED", "Back identity definition requires bound independent human approval.")
    text(approval.get("user_message"), "identity approval.user_message")


def lineage_errors(asset: Mapping[str, Any], assets: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Validate multi-input derivation without giving synthesized images votes."""
    parents = asset.get("derived_from_asset_ids")
    if parents is None:
        return []
    errors = []
    if asset.get("derived_from_asset_id") is not None:
        errors.append("Single-parent and multi-input derivation are mutually exclusive.")
    if not isinstance(parents, list) or not parents or any(not isinstance(x, str) for x in parents) or len(set(parents)) != len(parents):
        return errors + ["derived_from_asset_ids requires unique asset IDs."]
    if asset.get("source_kind") != "derivative" or asset.get("evidence_independence") != "none":
        errors.append("Synthesized references must be derivative with evidence_independence: none.")
    bindings = asset.get("derivation_sources")
    if not isinstance(bindings, list) or any(not isinstance(x, dict) for x in bindings):
        return errors + ["derivation_sources must describe every input."]
    if {x.get("asset_id") for x in bindings} != set(parents):
        errors.append("Derivation sources must match all parents.")
    for binding in bindings:
        parent = assets.get(binding.get("asset_id"))
        if parent is None or binding.get("sha256") != parent.get("sha256"):
            errors.append("Missing or changed derivation input: " + str(binding.get("asset_id")))
        if not binding.get("usage"):
            errors.append("Derivation input requires usage and selected part/region provenance.")
    visited = set()
    def walk(current: str, chain: set[str]) -> None:
        if current in chain:
            errors.append("Derivation cycle: " + current)
            return
        if current in visited:
            return
        visited.add(current)
        parent = assets.get(current, {})
        ids = parent.get("derived_from_asset_ids") or ([parent["derived_from_asset_id"]] if parent.get("derived_from_asset_id") else [])
        for item in ids:
            walk(item, chain | {current})
    walk(str(asset.get("asset_id")), set())
    return errors
