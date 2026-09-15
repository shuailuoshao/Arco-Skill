#!/usr/bin/env python3
"""Validate the Arco Character Bible and report database/request readiness."""

from __future__ import annotations

import argparse
import hashlib
import json
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reference_runtime import compute_global_reference_readiness

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised by CLI environments
    print(
        "PyYAML is required. Install it with: "
        "python -m pip install -r scripts/requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(2)


VALID_STATUSES = {
    "TODO_CALIBRATION",
    "UNCERTAIN",
    "VISUAL_CONSENSUS",
    "CANON",
}
HARD_STATUSES = {"VISUAL_CONSENSUS", "CANON"}
VALID_PROFILES = {"portrait", "upper_body", "full_body", "back_view"}
VALID_ROLES = {
    "identity_evidence",
    "body_evidence",
    "variant_evidence",
    "state_evidence",
    "expression_evidence",
    "hair_evidence",
    "face_evidence",
    "outfit_detail_evidence",
    "rendering_style_evidence",
}
VALID_REFERENCE_LEVELS = {"identity", "primary", "secondary", "detail"}
VALID_VIEW_ANGLES = {
    "front",
    "front_three_quarter",
    "side",
    "back_three_quarter",
    "back",
    "detail",
    "unknown",
}
VALID_SOURCE_KINDS = {"official", "user_provided", "derivative", "unknown"}
VALID_SOURCE_AUTHORITIES = {
    "primary_official",
    "secondary_official",
    "user_approved",
    "unverified",
}
VALID_ASSET_STATUSES = {"VERIFIED"}
VALID_GENERATION_PRIORITIES = {"primary", "secondary", "supplemental"}
VALID_INHERITANCE_DECISIONS = {"inherit", "do_not_inherit"}
GENERATION_REFERENCE_KEYS = {
    "priority", "supported_roles", "preferred_for", "excluded_for",
    "coverage", "inheritance",
}
COVERAGE_KEYS = {"profiles", "visible_fields", "view_angles", "occluded_fields"}
VALID_GENERATION_ROLES = {
    "identity_reference", "outfit_reference", "state_reference", "face_reference",
    "detail_reference", "composition_reference", "pose_reference",
    "lighting_reference", "style_reference",
}
VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_CANON_BASIS = {"explicit_official_definition"}
VALID_VARIANT_COVERAGE_KEYS = {
    "upper_body", "lower_body", "full_body", "footwear", "back_view", "overall",
}
VALID_REFERENCE_READINESS = {"READY", "PARTIAL", "INCOMPLETE", "CONFLICT"}
STABLE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVED_MARKDOWN_FACT = re.compile(r"^\s*(value|status|evidence_status)\s*:", re.I)


@dataclass
class Issue:
    severity: str
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass
class Context:
    root: Path
    issues: list[Issue] = field(default_factory=list)
    assets: dict[str, dict[str, Any]] = field(default_factory=dict)
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    variants: dict[str, dict[str, Any]] = field(default_factory=dict)
    states: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)

    def add(self, severity: str, code: str, path: Path | str, message: str) -> None:
        try:
            display = str(Path(path).resolve().relative_to(self.root.resolve()))
        except (ValueError, OSError):
            display = str(path)
        self.issues.append(Issue(severity, code, display.replace("\\", "/"), message))

    def error(self, code: str, path: Path | str, message: str) -> None:
        self.add("ERROR", code, path, message)

    def warning(self, code: str, path: Path | str, message: str) -> None:
        self.add("WARNING", code, path, message)


def load_yaml(ctx: Context, path: Path) -> Any:
    if not path.is_file():
        ctx.error("missing-file", path, "Required YAML file is missing.")
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        ctx.error("invalid-yaml", path, f"Cannot read YAML: {exc}")
        return None


def relative_path(ctx: Context, raw: Any, owner: Path) -> Path | None:
    if not isinstance(raw, str) or not raw:
        ctx.error("invalid-path", owner, "Path must be a non-empty relative string.")
        return None
    candidate = (ctx.root / raw).resolve()
    try:
        candidate.relative_to(ctx.root.resolve())
    except ValueError:
        ctx.error("path-escape", owner, f"Path escapes the skill root: {raw}")
        return None
    return candidate


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def register_entity(ctx: Context, data: Any, path: Path) -> None:
    if not isinstance(data, dict):
        return
    entity_ref = data.get("entity_ref")
    if not isinstance(entity_ref, str) or not entity_ref:
        ctx.error("missing-entity-ref", path, "Managed YAML entity needs entity_ref.")
        return
    if entity_ref in ctx.entities:
        ctx.error("duplicate-entity-ref", path, f"Duplicate entity_ref: {entity_ref}")
        return
    revision = data.get("revision")
    if not isinstance(revision, int) or revision < 0:
        ctx.error("invalid-revision", path, "revision must be a non-negative integer.")
    last_id = data.get("last_calibration_id")
    if revision == 0 and last_id is not None:
        ctx.error("unexpected-history-link", path, "revision 0 must not have last_calibration_id.")
    if isinstance(revision, int) and revision > 0 and not isinstance(last_id, str):
        ctx.error("missing-history-link", path, "revision > 0 requires last_calibration_id.")
    ctx.entities[entity_ref] = {"data": data, "path": path}


def validate_assets(ctx: Context) -> None:
    path = ctx.root / "character" / "assets.yaml"
    data = load_yaml(ctx, path)
    if not isinstance(data, dict):
        return
    register_entity(ctx, data, path)
    asset_schema = data.get("schema_version")
    if asset_schema not in {2, 3}:
        ctx.error("invalid-asset-schema-version", path, "Asset registry schema_version must be 2 or 3.")
    assets = data.get("assets")
    if not isinstance(assets, list):
        ctx.error("invalid-assets", path, "assets must be a list.")
        return
    for index, asset in enumerate(assets):
        where = f"{path}#assets[{index}]"
        if not isinstance(asset, dict):
            ctx.error("invalid-asset", where, "Asset entry must be a mapping.")
            continue
        if "evidence_status" in asset or "status" in asset:
            ctx.error(
                "asset-evidence-status",
                where,
                "Assets describe sources, not claim authority; remove evidence/status fields.",
            )
        asset_id = asset.get("asset_id")
        if not isinstance(asset_id, str) or not STABLE_ID.fullmatch(asset_id):
            ctx.error("invalid-asset-id", where, "asset_id must be stable kebab-case.")
            continue
        if asset_id in ctx.assets:
            ctx.error("duplicate-asset-id", where, f"Duplicate asset_id: {asset_id}")
            continue
        if asset.get("asset_status") not in VALID_ASSET_STATUSES:
            ctx.error("invalid-asset-status", where, f"Invalid asset_status: {asset.get('asset_status')!r}")
        roles = asset.get("roles")
        if not isinstance(roles, list) or not roles:
            ctx.error("missing-asset-roles", where, "roles must be a non-empty list.")
        elif unknown := set(roles) - VALID_ROLES:
            ctx.error("invalid-asset-role", where, f"Unknown roles: {sorted(unknown)}")
        for key, allowed in (
            ("reference_level", VALID_REFERENCE_LEVELS),
            ("view_angle", VALID_VIEW_ANGLES),
            ("source_kind", VALID_SOURCE_KINDS),
            ("source_authority", VALID_SOURCE_AUTHORITIES),
        ):
            if asset.get(key) not in allowed:
                ctx.error("invalid-asset-enum", where, f"Invalid {key}: {asset.get(key)!r}")
        if not isinstance(asset.get("source_group_id"), str) or not asset.get("source_group_id"):
            ctx.error("missing-source-group", where, "source_group_id is required.")
        permission = asset.get("can_be_generation_reference", False)
        metadata = asset.get("generation_reference")
        if not isinstance(permission, bool):
            ctx.error("invalid-generation-permission", where, "can_be_generation_reference must be boolean.")
        if permission is True:
            if asset_schema != 3:
                ctx.error("generation-permission-requires-v3", where, "Published generation permission requires Asset schema v3.")
            if not isinstance(metadata, dict):
                ctx.error("missing-generation-reference", where, "Enabled generation permission requires generation_reference metadata.")
            else:
                if metadata.get("priority") not in VALID_GENERATION_PRIORITIES:
                    ctx.error("invalid-generation-priority", where, f"Invalid generation priority: {metadata.get('priority')!r}")
                supported = metadata.get("supported_roles")
                if not isinstance(supported, list) or not supported or set(supported) - VALID_GENERATION_ROLES:
                    ctx.error("invalid-generation-roles", where, "supported_roles must be a non-empty list of known generation roles.")
                unknown = set(metadata) - GENERATION_REFERENCE_KEYS
                if unknown:
                    ctx.error("unknown-generation-reference-field", where, f"Unknown generation_reference fields: {sorted(unknown)}")
                preferred = metadata.get("preferred_for")
                excluded = metadata.get("excluded_for")
                if not isinstance(preferred, list) or set(preferred) - VALID_PROFILES:
                    ctx.error("invalid-generation-profiles", where, "preferred_for must be a list of known profiles.")
                if not isinstance(excluded, list) or set(excluded) - VALID_PROFILES or set(preferred or []) & set(excluded or []):
                    ctx.error("invalid-generation-exclusions", where, "excluded_for must use known profiles and not overlap preferred_for.")
                coverage = metadata.get("coverage")
                if not isinstance(coverage, dict):
                    ctx.error("invalid-generation-coverage", where, "coverage must be a mapping.")
                else:
                    unknown_coverage = set(coverage) - COVERAGE_KEYS
                    if unknown_coverage:
                        ctx.error("unknown-generation-coverage-field", where, f"Unknown coverage fields: {sorted(unknown_coverage)}")
                    for key in COVERAGE_KEYS:
                        if key in coverage and not isinstance(coverage[key], list):
                            ctx.error("invalid-generation-coverage", where, f"coverage.{key} must be a list.")
                inheritance = metadata.get("inheritance")
                if not isinstance(inheritance, dict) or not inheritance:
                    ctx.error("invalid-generation-inheritance", where, "inheritance must be a non-empty mapping.")
                elif any(value not in VALID_INHERITANCE_DECISIONS for value in inheritance.values()):
                    ctx.error("invalid-generation-inheritance", where, "inheritance values must be inherit or do_not_inherit.")
                if asset.get("derived_from_asset_id") is not None and asset.get("evidence_independence") != "none":
                    ctx.error("derived-evidence-independence", where, "Derived generation references require evidence_independence: none.")
            if "expression_evidence" in (roles or []) or asset.get("asset_type") in {"body_base", "faceless_composite"}:
                ctx.error("generation-layer-forbidden", where, "Expression, Body Base, and Faceless assets cannot be generation inputs in this runtime policy.")
        elif metadata is not None:
            ctx.error("unexpected-generation-reference", where, "Disabled generation permission must omit generation_reference or set it to null.")
        asset_path = relative_path(ctx, asset.get("path"), path)
        if asset_path is not None:
            if not asset_path.is_file():
                ctx.error("missing-asset-file", asset_path, f"Asset file for {asset_id} is missing.")
            else:
                expected_hash = asset.get("sha256")
                actual_hash = file_sha256(asset_path)
                if not isinstance(expected_hash, str) or expected_hash.lower() != actual_hash:
                    ctx.error("asset-hash-mismatch", asset_path, f"SHA-256 mismatch for {asset_id}.")
        ctx.assets[asset_id] = asset
    for asset_id, asset in ctx.assets.items():
        parent = asset.get("derived_from_asset_id")
        if parent is not None and parent not in ctx.assets:
            ctx.error("missing-derived-parent", path, f"{asset_id} derives from unknown asset {parent}.")


def validate_runtime_config(ctx: Context) -> None:
    path = ctx.root / "runtime" / "generation.yaml"
    data = load_yaml(ctx, path)
    if not isinstance(data, dict):
        return
    generation = data.get("generation")
    if data.get("schema_version") != 1 or not isinstance(generation, dict):
        ctx.error("invalid-runtime-config", path, "Runtime config requires schema_version 1 and generation mapping.")
        return
    if generation.get("provider") != "builtin_image_gen" or generation.get("required_capability") != "reference_conditioned_image_generation":
        ctx.error("invalid-runtime-provider", path, "Runtime must use the built-in provider capability contract.")
    if generation.get("default_mode") not in {"reference_conditioned", "prompt_only"}:
        ctx.error("invalid-runtime-mode", path, "Invalid default generation mode.")
    if set(generation.get("supported_modes") or []) != {"reference_conditioned", "prompt_only"}:
        ctx.error("invalid-runtime-modes", path, "supported_modes must contain both supported modes.")
    limits = [generation.get("max_local_arco_references"), generation.get("max_external_references"), generation.get("max_total_image_inputs")]
    if not all(isinstance(value, int) and value > 0 for value in limits):
        ctx.error("invalid-reference-limits", path, "Reference limits must be positive integers.")
    elif limits[2] < max(limits[0], limits[1]):
        ctx.error("invalid-reference-limits", path, "Total image limit cannot be below an individual limit.")
    for key in ("require_published_assets", "require_generation_reference_permission", "expression_asset_auto_upload", "body_base_auto_upload", "faceless_composite_auto_upload"):
        if not isinstance(generation.get(key), bool):
            ctx.error("invalid-runtime-boolean", path, f"{key} must be boolean.")


def validate_fact(ctx: Context, fact: Any, owner: Path, seen: set[str]) -> None:
    if not isinstance(fact, dict):
        ctx.error("invalid-fact", owner, "Fact entries must be mappings.")
        return
    field_id = fact.get("field_id")
    if not isinstance(field_id, str) or not field_id:
        ctx.error("missing-field-id", owner, "Fact requires field_id.")
        return
    if field_id in seen:
        ctx.error("duplicate-field-id", owner, f"Duplicate field_id: {field_id}")
    seen.add(field_id)
    status = fact.get("status")
    if status not in VALID_STATUSES:
        ctx.error("invalid-evidence-status", owner, f"Invalid status for {field_id}: {status!r}")
        return
    evidence = fact.get("evidence_ids")
    if not isinstance(evidence, list):
        ctx.error("invalid-evidence-list", owner, f"evidence_ids for {field_id} must be a list.")
        evidence = []
    missing = [item for item in evidence if item not in ctx.assets]
    if missing:
        ctx.error("missing-evidence", owner, f"{field_id} references unknown assets: {missing}")
    value = fact.get("value")
    if status == "TODO_CALIBRATION" and value is not None:
        ctx.error("todo-has-value", owner, f"{field_id} cannot have a value while TODO_CALIBRATION.")
    if status == "UNCERTAIN" and not evidence:
        ctx.error("uncertain-without-evidence", owner, f"{field_id} needs evidence when UNCERTAIN.")
    if status in HARD_STATUSES and value in (None, "", [], {}):
        ctx.error("hard-fact-empty", owner, f"{field_id} needs a value when {status}.")
    if status == "VISUAL_CONSENSUS":
        groups = {
            ctx.assets[item].get("source_group_id")
            for item in evidence
            if item in ctx.assets
        }
        groups.discard(None)
        if len(groups) < 2:
            ctx.error(
                "consensus-not-independent",
                owner,
                f"{field_id} needs at least two independent source_group_id values.",
            )
    if status == "CANON":
        authoritative = any(
            ctx.assets[item].get("source_kind") == "official"
            and ctx.assets[item].get("source_authority") == "primary_official"
            for item in evidence
            if item in ctx.assets
        )
        if not authoritative:
            ctx.error(
                "canon-without-primary-official-source",
                owner,
                f"{field_id} needs primary official evidence explicitly supporting the claim.",
            )
        basis = fact.get("canon_basis")
        if (
            not isinstance(basis, dict)
            or basis.get("kind") not in VALID_CANON_BASIS
            or not isinstance(basis.get("source_note"), str)
            or not basis.get("source_note").strip()
        ):
            ctx.error(
                "canon-without-explicit-definition",
                owner,
                f"{field_id} needs canon_basis.kind=explicit_official_definition and a source_note; an official image alone is insufficient.",
            )
    required_for = fact.get("required_for", [])
    if not isinstance(required_for, list) or set(required_for) - VALID_PROFILES:
        ctx.error("invalid-required-for", owner, f"Invalid required_for on {field_id}.")


def validate_markdown(ctx: Context, path: Path, entity_ref: str, revision: int) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    metadata: dict[str, Any] = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            try:
                metadata = yaml.safe_load(text[4:end]) or {}
            except yaml.YAMLError as exc:
                ctx.error("invalid-markdown-frontmatter", path, str(exc))
            body = text[end + 5 :]
    if metadata.get("source_entity") != entity_ref:
        ctx.error("markdown-entity-mismatch", path, f"Expected source_entity {entity_ref}.")
    if metadata.get("source_revision") != revision:
        ctx.error("markdown-revision-mismatch", path, f"Expected source_revision {revision}.")
    in_fence = False
    for line_number, line in enumerate(body.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and RESERVED_MARKDOWN_FACT.match(line):
            ctx.error(
                "markdown-redefines-fact",
                f"{path}:{line_number}",
                "Markdown must not redefine structured value/status fields.",
            )


def validate_identity(ctx: Context) -> dict[str, Any] | None:
    path = ctx.root / "character" / "identity.yaml"
    data = load_yaml(ctx, path)
    if not isinstance(data, dict):
        return None
    register_entity(ctx, data, path)
    facts = data.get("facts")
    if not isinstance(facts, list):
        ctx.error("invalid-facts", path, "facts must be a list.")
        return data
    seen: set[str] = set()
    for fact in facts:
        validate_fact(ctx, fact, path, seen)
    validate_markdown(ctx, ctx.root / "character" / "identity.md", data.get("entity_ref", ""), data.get("revision", -1))
    return data


def validate_simple_entities(ctx: Context) -> dict[str, Any] | None:
    expressions_path = ctx.root / "character" / "expressions.yaml"
    expressions = load_yaml(ctx, expressions_path)
    if isinstance(expressions, dict):
        register_entity(ctx, expressions, expressions_path)
        ids: set[str] = set()
        for item in expressions.get("expressions", []):
            expression_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(expression_id, str) or not STABLE_ID.fullmatch(expression_id):
                ctx.error("invalid-expression-id", expressions_path, f"Invalid expression id: {expression_id!r}")
            elif expression_id in ids:
                ctx.error("duplicate-expression-id", expressions_path, f"Duplicate expression id: {expression_id}")
            else:
                ids.add(expression_id)
    index_path = ctx.root / "variants" / "index.yaml"
    index = load_yaml(ctx, index_path)
    if isinstance(index, dict):
        register_entity(ctx, index, index_path)
    return index if isinstance(index, dict) else None


def validate_variants(ctx: Context, index: dict[str, Any] | None) -> None:
    if index is None:
        return
    entries = index.get("variants")
    if not isinstance(entries, list):
        ctx.error("invalid-variant-index", ctx.root / "variants" / "index.yaml", "variants must be a list.")
        return
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            ctx.error("invalid-variant-entry", ctx.root / "variants" / "index.yaml", "Variant index entries must be mappings.")
            continue
        variant_id = entry.get("variant_id")
        if not isinstance(variant_id, str) or not STABLE_ID.fullmatch(variant_id):
            ctx.error("invalid-variant-id", ctx.root / "variants" / "index.yaml", f"Invalid variant_id: {variant_id!r}")
            continue
        if variant_id in seen:
            ctx.error("duplicate-variant-id", ctx.root / "variants" / "index.yaml", f"Duplicate variant_id: {variant_id}")
            continue
        seen.add(variant_id)
        variant_path = relative_path(ctx, entry.get("path"), ctx.root / "variants" / "index.yaml")
        if variant_path is None:
            continue
        data = load_yaml(ctx, variant_path)
        if not isinstance(data, dict):
            continue
        register_entity(ctx, data, variant_path)
        if data.get("variant_id") != variant_id:
            ctx.error("variant-id-mismatch", variant_path, f"Expected variant_id {variant_id}.")
        facts = data.get("facts", [])
        fact_seen: set[str] = set()
        if not isinstance(facts, list):
            ctx.error("invalid-facts", variant_path, "facts must be a list.")
            facts = []
        for fact in facts:
            validate_fact(ctx, fact, variant_path, fact_seen)
        refs = data.get("reference_asset_ids", {})
        if not isinstance(refs, dict):
            ctx.error("invalid-reference-map", variant_path, "reference_asset_ids must be a mapping.")
            refs = {}
        primary = refs.get("primary", [])
        if data.get("lifecycle_status") == "published" and (not isinstance(primary, list) or len(primary) != 1):
            ctx.error("primary-cardinality", variant_path, "Published Variant must have exactly one Primary asset.")
        for level in ("primary", "secondary", "detail"):
            ids = refs.get(level, [])
            if not isinstance(ids, list):
                ctx.error("invalid-reference-list", variant_path, f"{level} references must be a list.")
                continue
            for asset_id in ids:
                asset = ctx.assets.get(asset_id)
                if asset is None:
                    ctx.error("missing-variant-asset", variant_path, f"Unknown {level} asset: {asset_id}")
                else:
                    if asset.get("variant_id") != variant_id:
                        ctx.error("asset-variant-mismatch", variant_path, f"Asset {asset_id} belongs to another Variant.")
                    if asset.get("reference_level") != level:
                        ctx.error("asset-level-mismatch", variant_path, f"Asset {asset_id} is not {level}.")
        mutable = data.get("state_mutable_fields", [])
        must_keep = data.get("must_keep_fields", [])
        if not isinstance(mutable, list) or not isinstance(must_keep, list):
            ctx.error("invalid-state-field-policy", variant_path, "state_mutable_fields and must_keep_fields must be lists.")
            mutable, must_keep = [], []
        if set(mutable) & set(must_keep):
            ctx.error("mutable-must-keep-overlap", variant_path, "A field cannot be both mutable and Must Keep.")
        unknown_must_keep = set(must_keep) - fact_seen
        if unknown_must_keep:
            ctx.error("unknown-must-keep-field", variant_path, f"Must Keep references unknown Variant facts: {sorted(unknown_must_keep)}")
        coverage = data.get("coverage")
        if coverage is not None:
            if not isinstance(coverage, dict):
                ctx.error("invalid-variant-coverage", variant_path, "coverage must be a mapping when present.")
            else:
                unknown_coverage = set(coverage) - VALID_VARIANT_COVERAGE_KEYS
                missing_coverage = VALID_VARIANT_COVERAGE_KEYS - set(coverage)
                if unknown_coverage or missing_coverage:
                    ctx.error(
                        "invalid-variant-coverage-keys",
                        variant_path,
                        f"coverage must use the closed key set; missing={sorted(missing_coverage)}, unknown={sorted(unknown_coverage)}",
                    )
                invalid_values = {
                    key: value for key, value in coverage.items()
                    if key in VALID_VARIANT_COVERAGE_KEYS and value not in VALID_REFERENCE_READINESS
                }
                if invalid_values:
                    ctx.error("invalid-variant-coverage-value", variant_path, f"Invalid coverage values: {invalid_values}")
                profile_values = [coverage.get(key) for key in VALID_VARIANT_COVERAGE_KEYS - {"overall"}]
                expected_overall = (
                    "CONFLICT" if "CONFLICT" in profile_values else
                    "READY" if profile_values and all(value == "READY" for value in profile_values) else
                    "PARTIAL" if "READY" in profile_values else
                    "INCOMPLETE"
                )
                if coverage.get("overall") in VALID_REFERENCE_READINESS and coverage.get("overall") != expected_overall:
                    ctx.error(
                        "variant-coverage-overall-mismatch",
                        variant_path,
                        f"coverage.overall must be {expected_overall} for the declared profile coverage.",
                    )
        groups = data.get("state_groups", {})
        if not isinstance(groups, dict):
            ctx.error("invalid-state-groups", variant_path, "state_groups must be a mapping.")
            groups = {}
        for group_id, config in groups.items():
            compatible = config.get("compatible_groups", []) if isinstance(config, dict) else []
            if not isinstance(compatible, list):
                ctx.error("invalid-group-compatibility", variant_path, f"compatible_groups for {group_id} must be a list.")
                continue
            for other in compatible:
                if other not in groups:
                    ctx.error("unknown-compatible-group", variant_path, f"{group_id} references unknown group {other}.")
                elif group_id not in groups.get(other, {}).get("compatible_groups", []):
                    ctx.error("asymmetric-group-compatibility", variant_path, f"{group_id} and {other} must declare compatibility symmetrically.")
        state_map: dict[str, dict[str, Any]] = {}
        for raw_state_path in data.get("state_files", []):
            state_path = relative_path(ctx, raw_state_path, variant_path)
            if state_path is None:
                continue
            state = load_yaml(ctx, state_path)
            if not isinstance(state, dict):
                continue
            register_entity(ctx, state, state_path)
            state_id = state.get("state_id")
            if not isinstance(state_id, str) or not STABLE_ID.fullmatch(state_id):
                ctx.error("invalid-state-id", state_path, f"Invalid state_id: {state_id!r}")
                continue
            if state_id in state_map:
                ctx.error("duplicate-state-id", state_path, f"Duplicate state_id: {state_id}")
                continue
            if state.get("variant_id") != variant_id:
                ctx.error("state-variant-mismatch", state_path, f"State must belong to {variant_id}.")
            if state.get("status") not in VALID_STATUSES:
                ctx.error("invalid-state-status", state_path, "State needs a valid evidence status.")
            evidence = state.get("evidence_ids", [])
            if state.get("status") in HARD_STATUSES and not evidence:
                ctx.error("state-without-evidence", state_path, "Calibrated State needs evidence_ids.")
            for asset_id in evidence:
                if asset_id not in ctx.assets:
                    ctx.error("missing-state-evidence", state_path, f"Unknown evidence asset: {asset_id}")
            if state.get("status") == "VISUAL_CONSENSUS":
                groups_for_state = {
                    ctx.assets[asset_id].get("source_group_id")
                    for asset_id in evidence
                    if asset_id in ctx.assets
                }
                groups_for_state.discard(None)
                if len(groups_for_state) < 2:
                    ctx.error("state-consensus-not-independent", state_path, "VISUAL_CONSENSUS State needs two independent source groups.")
            if state.get("status") == "CANON":
                authoritative = any(
                    ctx.assets[asset_id].get("source_kind") == "official"
                    and ctx.assets[asset_id].get("source_authority") == "primary_official"
                    for asset_id in evidence
                    if asset_id in ctx.assets
                )
                basis = state.get("canon_basis")
                if not authoritative:
                    ctx.error("state-canon-without-primary-official-source", state_path, "CANON State needs primary official evidence.")
                if (
                    not isinstance(basis, dict)
                    or basis.get("kind") not in VALID_CANON_BASIS
                    or not isinstance(basis.get("source_note"), str)
                    or not basis.get("source_note").strip()
                ):
                    ctx.error("state-canon-without-explicit-definition", state_path, "CANON State needs an explicit official definition basis.")
            group = state.get("state_group")
            if group not in groups:
                ctx.error("unknown-state-group", state_path, f"Unknown state_group: {group!r}")
            overrides = state.get("overrides", {})
            if not isinstance(overrides, dict):
                ctx.error("invalid-state-overrides", state_path, "overrides must be a mapping.")
                overrides = {}
            illegal = set(overrides) - set(mutable)
            if illegal:
                ctx.error("state-illegal-override", state_path, f"Overrides are not state-mutable: {sorted(illegal)}")
            broken = set(overrides) & set(must_keep)
            if broken:
                ctx.error("state-breaks-must-keep", state_path, f"Overrides break Must Keep: {sorted(broken)}")
            state_map[state_id] = {"data": state, "path": state_path}
        for state_id, wrapped in state_map.items():
            state = wrapped["data"]
            for key in ("compatible_with", "conflicts_with", "requires"):
                values = state.get(key, [])
                if not isinstance(values, list):
                    ctx.error("invalid-state-relation", wrapped["path"], f"{key} must be a list.")
                    continue
                missing = set(values) - set(state_map)
                if missing:
                    ctx.error("unknown-state-reference", wrapped["path"], f"{key} references unknown states: {sorted(missing)}")
            for other in state.get("compatible_with", []):
                if other in state_map and state_id not in state_map[other]["data"].get("compatible_with", []):
                    ctx.error("asymmetric-state-compatibility", wrapped["path"], f"Compatibility with {other} must be symmetric.")
            for other in state.get("conflicts_with", []):
                if other in state_map and state_id not in state_map[other]["data"].get("conflicts_with", []):
                    ctx.error("asymmetric-state-conflict", wrapped["path"], f"Conflict with {other} must be symmetric.")
        notes = variant_path.with_name("notes.md")
        validate_markdown(ctx, notes, data.get("entity_ref", ""), data.get("revision", -1))
        ctx.variants[variant_id] = {"data": data, "path": variant_path}
        ctx.states[variant_id] = state_map


def validate_asset_references(ctx: Context) -> None:
    for asset_id, asset in ctx.assets.items():
        variant_id = asset.get("variant_id")
        state_ids = asset.get("state_ids")
        if variant_id is not None and variant_id not in ctx.variants:
            ctx.error("unknown-asset-variant", ctx.root / "character" / "assets.yaml", f"{asset_id} references unknown Variant {variant_id}.")
        if not isinstance(state_ids, list):
            ctx.error("invalid-asset-states", ctx.root / "character" / "assets.yaml", f"{asset_id} state_ids must be a list.")
            state_ids = []
        if state_ids and variant_id is None:
            ctx.error("asset-state-without-variant", ctx.root / "character" / "assets.yaml", f"{asset_id} cannot reference States without variant_id.")
        known_states = ctx.states.get(variant_id, {}) if isinstance(variant_id, str) else {}
        missing_states = [state_id for state_id in state_ids if state_id not in known_states]
        if missing_states:
            ctx.error("unknown-asset-state", ctx.root / "character" / "assets.yaml", f"{asset_id} references unknown States: {missing_states}")
        parent_id = asset.get("derived_from_asset_id")
        if parent_id is not None:
            parent = ctx.assets.get(parent_id)
            if asset.get("source_kind") != "derivative":
                ctx.error("derived-kind-mismatch", ctx.root / "character" / "assets.yaml", f"{asset_id} has a derived parent but source_kind is not derivative.")
            if parent and parent.get("source_group_id") != asset.get("source_group_id"):
                ctx.error("derived-source-group-mismatch", ctx.root / "character" / "assets.yaml", f"{asset_id} and its parent must share source_group_id.")
        elif asset.get("source_kind") == "derivative":
            ctx.error("derivative-without-parent", ctx.root / "character" / "assets.yaml", f"{asset_id} is derivative but has no derived_from_asset_id.")
        if asset.get("source_authority") in {"primary_official", "secondary_official"} and asset.get("source_kind") != "official":
            ctx.error("official-authority-kind-mismatch", ctx.root / "character" / "assets.yaml", f"{asset_id} has official authority but source_kind is not official.")


def validate_observation(ctx: Context, observation: Any, path: Path | str) -> None:
    if not isinstance(observation, dict):
        ctx.error("invalid-observation", path, "Observation must be a mapping.")
        return
    observation_id = observation.get("observation_id")
    if not isinstance(observation_id, str) or not STABLE_ID.fullmatch(observation_id):
        ctx.error("invalid-observation-id", path, "observation_id must be stable kebab-case.")
    if not isinstance(observation.get("field_ref"), str) or not observation.get("field_ref"):
        ctx.error("observation-missing-field", path, "Observation requires field_ref.")
    for key in ("observation", "intrinsic_interpretation"):
        if not isinstance(observation.get(key), str) or not observation.get(key).strip():
            ctx.error("observation-missing-layer", path, f"Observation requires non-empty {key}.")
    evidence = observation.get("evidence_ids")
    if not isinstance(evidence, list) or not evidence:
        ctx.error("observation-missing-evidence", path, "Observation requires evidence_ids.")
        evidence = []
    missing = [item for item in evidence if item not in ctx.assets]
    if missing:
        ctx.error("observation-unknown-evidence", path, f"Observation references unknown assets: {missing}")
    factors = observation.get("rendering_factors")
    if not isinstance(factors, dict):
        ctx.error("observation-missing-rendering-check", path, "Observation requires rendering_factors.")
    else:
        for key in ("lighting_sensitive", "pose_sensitive", "perspective_sensitive"):
            if not isinstance(factors.get(key), bool):
                ctx.error("invalid-rendering-factor", path, f"rendering_factors.{key} must be boolean.")
        if "occlusion" not in factors:
            ctx.error("invalid-rendering-factor", path, "rendering_factors.occlusion is required.")
    if observation.get("confidence") not in VALID_CONFIDENCE:
        ctx.error("invalid-observation-confidence", path, "confidence must be low, medium, or high.")
    comparison = observation.get("comparison")
    if not isinstance(comparison, dict):
        ctx.error("observation-missing-comparison", path, "Observation requires cross-image comparison.")
    else:
        for key in ("corroborating_evidence_ids", "conflicting_evidence_ids"):
            values = comparison.get(key)
            if not isinstance(values, list):
                ctx.error("invalid-observation-comparison", path, f"comparison.{key} must be a list.")
                continue
            unknown = [item for item in values if item not in ctx.assets]
            if unknown:
                ctx.error("observation-unknown-evidence", path, f"comparison.{key} references unknown assets: {unknown}")
    if observation.get("proposed_status") not in VALID_STATUSES:
        ctx.error("invalid-observation-status", path, "Observation proposed_status is invalid.")


def validate_state_selection(ctx: Context, variant_id: str | None, selected: list[str]) -> list[str]:
    failures: list[str] = []
    if not selected:
        return failures
    if not variant_id or variant_id not in ctx.variants:
        return ["State selection requires an existing --variant."]
    variant = ctx.variants[variant_id]["data"]
    states = ctx.states.get(variant_id, {})
    missing = [item for item in selected if item not in states]
    if missing:
        return [f"Unknown selected states: {missing}"]
    chosen = {item: states[item]["data"] for item in selected}
    for state_id, state in chosen.items():
        absent = set(state.get("requires", [])) - set(selected)
        if absent:
            failures.append(f"{state_id} requires {sorted(absent)}")
        explicit_conflict = set(state.get("conflicts_with", [])) & set(selected)
        if explicit_conflict:
            failures.append(f"{state_id} conflicts with {sorted(explicit_conflict)}")
    ids = list(chosen)
    groups = variant.get("state_groups", {})
    for index, left_id in enumerate(ids):
        left = chosen[left_id]
        for right_id in ids[index + 1 :]:
            right = chosen[right_id]
            left_exclusive = left.get("exclusive_group")
            if left_exclusive and left_exclusive == right.get("exclusive_group"):
                failures.append(f"{left_id} and {right_id} share exclusive_group {left_exclusive}")
                continue
            left_group = left.get("state_group")
            right_group = right.get("state_group")
            explicit = (
                right_id in left.get("compatible_with", [])
                and left_id in right.get("compatible_with", [])
            )
            group_compatible = (
                left_group != right_group
                and right_group in groups.get(left_group, {}).get("compatible_groups", [])
                and left_group in groups.get(right_group, {}).get("compatible_groups", [])
            )
            if not explicit and not group_compatible:
                failures.append(f"Compatibility is not declared for {left_id} + {right_id}")
    return sorted(set(failures))


def validate_history(ctx: Context, pending_history: dict[str, Any] | None = None) -> None:
    history_dir = ctx.root / "calibration" / "history"
    targets_by_entity: dict[str, list[dict[str, Any]]] = {}
    history_by_id: dict[str, dict[str, Any]] = {}
    if history_dir.is_dir():
        paths = sorted(history_dir.glob("*.yaml"))
        pending_path = history_dir / (str(pending_history.get('calibration_id')) + '.yaml') if pending_history else None
        if pending_path is not None and pending_path not in paths:
            paths.append(pending_path)
        for path in paths:
            data = pending_history if path == pending_path else load_yaml(ctx, path)
            if not isinstance(data, dict):
                continue
            calibration_id = data.get("calibration_id")
            if not isinstance(calibration_id, str) or path.stem != calibration_id:
                ctx.error("history-id-mismatch", path, "History filename must match calibration_id.")
                continue
            if calibration_id in history_by_id:
                ctx.error("duplicate-history-id", path, f"Duplicate history id: {calibration_id}")
            history_by_id[calibration_id] = data
            if not data.get("user_confirmed"):
                ctx.error("history-not-confirmed", path, "Published History requires user_confirmed: true.")
            if not data.get("reason"):
                ctx.error("history-missing-reason", path, "History requires reason.")
            if not isinstance(data.get("evidence_ids"), list):
                ctx.error("history-invalid-evidence", path, "History evidence_ids must be a list.")
            else:
                unknown_evidence = [item for item in data["evidence_ids"] if item not in ctx.assets]
                if unknown_evidence:
                    ctx.error("history-unknown-evidence", path, f"History references unknown assets: {unknown_evidence}")
            if not isinstance(data.get("validation_result"), dict):
                ctx.error("history-missing-validation", path, "History requires validation_result.")
            elif data["validation_result"].get("structure") != "PASS":
                ctx.error("history-failed-validation", path, "Published History must record structure: PASS.")
            observations = data.get("observations", [])
            if not isinstance(observations, list):
                ctx.error("invalid-observations", path, "History observations must be a list.")
            else:
                for index, observation in enumerate(observations):
                    validate_observation(ctx, observation, f"{path}#observations[{index}]")
            marker = history_dir / f"{calibration_id}.complete"
            if not marker.is_file() and path != pending_path:
                ctx.error("history-incomplete", path, "History is missing its completion marker.")
            targets = data.get("targets")
            if not isinstance(targets, list) or not targets:
                ctx.error("history-missing-targets", path, "History requires non-empty targets.")
                continue
            seen_targets: set[tuple[str, Any, Any]] = set()
            for target in targets:
                if not isinstance(target, dict):
                    ctx.error("invalid-history-target", path, "History target must be a mapping.")
                    continue
                entity_ref = target.get("entity_ref")
                if not isinstance(entity_ref, str):
                    ctx.error("history-missing-entity-ref", path, "History target requires entity_ref.")
                    continue
                target_key = (entity_ref, target.get("target_type"), target.get("target_id"))
                if target_key in seen_targets:
                    ctx.error("duplicate-history-target", path, f"Duplicate History target: {target_key}")
                seen_targets.add(target_key)
                before = target.get("revision_before")
                after = target.get("revision_after")
                if not isinstance(before, int) or not isinstance(after, int) or after != before + 1:
                    ctx.error("history-revision-gap", path, f"{entity_ref} revision must advance exactly once.")
                for key in ("changed_fields", "before", "after"):
                    if key not in target:
                        ctx.error("history-target-incomplete", path, f"{entity_ref} target is missing {key}.")
                if not isinstance(target.get("changed_fields"), list) or not target.get("changed_fields"):
                    ctx.error("history-empty-change-set", path, f"{entity_ref} changed_fields must be non-empty.")
                if not isinstance(target.get("before"), dict) or not isinstance(target.get("after"), dict):
                    ctx.error("history-invalid-snapshot", path, f"{entity_ref} before/after must be mappings.")
                if target.get("status_before") != target.get("before", {}).get("status") and "status" in target.get("before", {}):
                    ctx.error("history-status-mismatch", path, f"{entity_ref} status_before disagrees with before.status.")
                if target.get("status_after") != target.get("after", {}).get("status") and "status" in target.get("after", {}):
                    ctx.error("history-status-mismatch", path, f"{entity_ref} status_after disagrees with after.status.")
                targets_by_entity.setdefault(entity_ref, []).append(
                    {"calibration_id": calibration_id, "target": target, "path": path}
                )
    for entity_ref, wrapped in ctx.entities.items():
        data = wrapped["data"]
        path = wrapped["path"]
        revision = data.get("revision")
        if not isinstance(revision, int) or revision <= 0:
            continue
        links = targets_by_entity.get(entity_ref, [])
        events_by_calibration: dict[str, list[dict[str, Any]]] = {}
        for link in links:
            events_by_calibration.setdefault(link["calibration_id"], []).append(link)
        events = sorted(
            events_by_calibration.values(),
            key=lambda event: event[0]["target"].get("revision_after", -1),
        )
        expected = 0
        for event in events:
            revision_pairs = {
                (link["target"].get("revision_before"), link["target"].get("revision_after"))
                for link in event
            }
            if len(revision_pairs) != 1:
                ctx.error("history-event-revision-mismatch", event[0]["path"], f"{entity_ref} targets in one Calibration must share one revision pair.")
                continue
            target = event[0]["target"]
            if target.get("revision_before") != expected:
                ctx.error("history-chain-gap", event[0]["path"], f"{entity_ref} expected revision_before {expected}.")
                break
            expected = target.get("revision_after", expected)
        links_by_target: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
        for link in links:
            target = link["target"]
            links_by_target.setdefault((target.get("target_type"), target.get("target_id")), []).append(link)
        for target_links in links_by_target.values():
            target_links.sort(key=lambda item: item["target"].get("revision_after", -1))
            for previous, current in zip(target_links, target_links[1:]):
                previous_after = previous["target"].get("after", {})
                current_before = current["target"].get("before", {})
                if isinstance(previous_after, dict) and isinstance(current_before, dict):
                    shared = set(previous_after) & set(current_before)
                    if any(previous_after[key] != current_before[key] for key in shared):
                        ctx.error("history-snapshot-gap", current["path"], f"{entity_ref} before snapshot disagrees with the previous after snapshot.")
        if expected != revision:
            ctx.error("history-chain-incomplete", path, f"History reaches revision {expected}, current entity is {revision}.")
        last_id = data.get("last_calibration_id")
        latest_event = events[-1] if events else []
        if not latest_event or latest_event[0]["calibration_id"] != last_id:
            ctx.error("history-last-link-mismatch", path, f"last_calibration_id does not match latest History for {entity_ref}.")
        for latest_link in latest_event:
            latest_target = latest_link["target"]
            target_id = latest_target.get("target_id")
            current_snapshot: Any = data
            facts = data.get("facts") if isinstance(data, dict) else None
            if isinstance(facts, list) and isinstance(target_id, str):
                current_snapshot = next(
                    (fact for fact in facts if isinstance(fact, dict) and fact.get("field_id") == target_id),
                    data,
                )
            latest_after = latest_target.get("after", {})
            if isinstance(current_snapshot, dict) and isinstance(latest_after, dict):
                mismatched = [key for key, value in latest_after.items() if current_snapshot.get(key) != value]
                if mismatched:
                    ctx.error("history-current-mismatch", path, f"Latest History after snapshot disagrees on: {sorted(mismatched)}")


def validate_staging(ctx: Context) -> None:
    staging = ctx.root / "calibration" / "staging"
    if not staging.is_dir():
        return
    for manifest in staging.glob("*/publish-manifest.yaml"):
        data = load_yaml(ctx, manifest)
        if isinstance(data, dict) and data.get("state") != "complete":
            ctx.error("unfinished-publish", manifest, f"Publish state is {data.get('state')!r}; recover or roll back before use.")
    for path in staging.glob("**/*observation*.yaml"):
        data = load_yaml(ctx, path)
        if isinstance(data, dict) and "observations" in data:
            observations = data.get("observations")
        else:
            observations = [data]
        if not isinstance(observations, list):
            ctx.error("invalid-observations", path, "observations must be a list.")
            continue
        for index, observation in enumerate(observations):
            validate_observation(ctx, observation, f"{path}#observations[{index}]")


def fact_readiness(facts: list[dict[str, Any]], profiles: set[str] | None, temporary: set[str]) -> list[str]:
    missing: list[str] = []
    for fact in facts:
        field_id = fact.get("field_id")
        if not isinstance(field_id, str):
            continue
        required = bool(fact.get("required_global")) if profiles is None else bool(set(fact.get("required_for", [])) & profiles)
        if required and fact.get("status") not in HARD_STATUSES and field_id not in temporary:
            missing.append(field_id)
    return sorted(missing)


def build_readiness(
    ctx: Context,
    identity: dict[str, Any] | None,
    profiles: set[str],
    variant_id: str | None,
    selected_states: list[str],
    temporary: set[str],
) -> dict[str, Any]:
    identity_facts = identity.get("facts", []) if isinstance(identity, dict) else []
    identity_missing = fact_readiness(identity_facts, None, set())
    variants: dict[str, Any] = {}
    for item_id, wrapped in ctx.variants.items():
        data = wrapped["data"]
        missing = fact_readiness(data.get("facts", []), None, set())
        primary = data.get("reference_asset_ids", {}).get("primary", [])
        ready = data.get("lifecycle_status") == "published" and not missing and isinstance(primary, list) and len(primary) == 1
        variants[item_id] = {"status": "READY" if ready else "INCOMPLETE", "missing_fields": missing}
    if not profiles:
        request = {
            "status": "INCOMPLETE",
            "exposure_profiles": [],
            "missing_fields": ["request_profile"],
            "temporary_evidence_used": [],
        }
    else:
        missing = fact_readiness(identity_facts, profiles, temporary)
        temporary_used = sorted(set(identity_facts_item.get("field_id") for identity_facts_item in identity_facts) & temporary)
        if variant_id:
            wrapped = ctx.variants.get(variant_id)
            if wrapped is None:
                missing.append(f"variant:{variant_id}")
            else:
                variant_missing = fact_readiness(wrapped["data"].get("facts", []), profiles, temporary)
                missing.extend(f"variant:{variant_id}:{item}" for item in variant_missing)
                if "back_view" in profiles:
                    refs = wrapped["data"].get("reference_asset_ids", {})
                    supporting = [
                        ctx.assets.get(asset_id)
                        for level in ("secondary", "detail")
                        for asset_id in refs.get(level, [])
                    ]
                    if not any(asset and asset.get("view_angle") in {"back", "back_three_quarter"} for asset in supporting):
                        missing.append(f"variant:{variant_id}:back-reference")
        state_failures = validate_state_selection(ctx, variant_id, selected_states)
        missing.extend(f"state:{item}" for item in state_failures)
        request = {
            "status": "READY" if not missing else "INCOMPLETE",
            "exposure_profiles": sorted(profiles),
            "missing_fields": sorted(set(missing)),
            "temporary_evidence_used": temporary_used,
        }
    return {
        "structure": "FAIL" if any(issue.severity == "ERROR" for issue in ctx.issues) else "PASS",
        "identity_readiness": {
            "status": "READY" if not identity_missing else "INCOMPLETE",
            "missing_fields": identity_missing,
        },
        "variant_readiness": variants,
        "request_readiness": request,
    }


def validate(root: Path, profiles: set[str] | None = None, variant_id: str | None = None, selected_states: list[str] | None = None, temporary: set[str] | None = None, check_staging: bool = False, pending_history: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = Context(root=root.resolve())
    if pending_history is not None:
        cid = str(pending_history.get('calibration_id', ''))
        marker = ctx.root / 'calibration' / 'transactions' / (cid + '.publication_in_progress.json')
        try:
            transaction = json.loads(marker.read_text(encoding='utf-8'))
            digest = hashlib.sha256(json.dumps(pending_history, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
            if transaction.get('calibration_id') != cid or transaction.get('pending_history_sha256') != digest:
                raise ValueError('Pending History does not match active transaction')
            for rel, expected in transaction['candidate_hashes'].items():
                target = (ctx.root / rel).resolve()
                target.relative_to(ctx.root)
                if file_sha256(target) != expected:
                    raise ValueError('Transaction target hash mismatch')
        except (OSError, ValueError, KeyError) as exc:
            ctx.error('invalid-transaction-context', marker, str(exc))
            pending_history = None
    if not (ctx.root / "SKILL.md").is_file():
        ctx.error("missing-skill", ctx.root / "SKILL.md", "SKILL.md is missing.")
    validate_assets(ctx)
    validate_runtime_config(ctx)
    identity = validate_identity(ctx)
    index = validate_simple_entities(ctx)
    validate_variants(ctx, index)
    validate_asset_references(ctx)
    validate_history(ctx, pending_history)
    # Read-only validation ignores staging. Mutation/calibration entrypoints opt in.
    if check_staging:
        validate_staging(ctx)
    readiness = build_readiness(
        ctx,
        identity,
        profiles or set(),
        variant_id,
        selected_states or [],
        temporary or set(),
    )
    readiness["global_reference_readiness"] = compute_global_reference_readiness(
        identity or {}, index or {}, list(ctx.assets.values())
    )
    readiness["issues"] = [issue.as_dict() for issue in ctx.issues]
    readiness["summary"] = {
        "errors": sum(issue.severity == "ERROR" for issue in ctx.issues),
        "warnings": sum(issue.severity == "WARNING" for issue in ctx.issues),
    }
    return readiness


def print_human(result: dict[str, Any]) -> None:
    print(f"STRUCTURE: {result['structure']}")
    identity = result["identity_readiness"]
    print(f"IDENTITY_READINESS: {identity['status']}")
    if identity["missing_fields"]:
        print("  missing: " + ", ".join(identity["missing_fields"]))
    print("VARIANT_READINESS:")
    if not result["variant_readiness"]:
        print("  (none)")
    for variant_id, value in result["variant_readiness"].items():
        print(f"  {variant_id}: {value['status']}")
        if value["missing_fields"]:
            print("    missing: " + ", ".join(value["missing_fields"]))
    request = result["request_readiness"]
    print(f"REQUEST_READINESS: {request['status']}")
    print("  exposure_profiles: " + (", ".join(request["exposure_profiles"]) or "(none)"))
    if request["missing_fields"]:
        print("  missing: " + ", ".join(request["missing_fields"]))
    if request["temporary_evidence_used"]:
        print("  temporary: " + ", ".join(request["temporary_evidence_used"]))
    global_refs = result["global_reference_readiness"]
    print(f"GLOBAL_REFERENCE_READINESS: {global_refs['overall']}")
    for issue in result["issues"]:
        print(f"{issue['severity']} [{issue['code']}] {issue['path']}: {issue['message']}")
    print(f"SUMMARY: {result['summary']['errors']} error(s), {result['summary']['warnings']} warning(s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--request-profile", action="append", choices=sorted(VALID_PROFILES), default=[])
    parser.add_argument("--variant")
    parser.add_argument("--state", action="append", default=[])
    parser.add_argument("--temporary-field", action="append", default=[])
    parser.add_argument("--require-identity-ready", action="store_true")
    parser.add_argument("--require-variant")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check-staging", action="store_true", help="Check unfinished staging for mutation workflows; read-only validation ignores it by default.")
    args = parser.parse_args(argv)
    if args.variant and args.require_variant and args.variant != args.require_variant:
        parser.error("--variant and --require-variant must name the same Variant when both are used")
    variant_id = args.variant or args.require_variant
    result = validate(
        args.root,
        profiles=set(args.request_profile),
        variant_id=variant_id,
        selected_states=args.state,
        temporary=set(args.temporary_field),
        check_staging=args.check_staging,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human(result)
    if result["structure"] == "FAIL":
        return 1
    if args.require_identity_ready and result["identity_readiness"]["status"] != "READY":
        return 3
    if args.require_variant:
        value = result["variant_readiness"].get(args.require_variant)
        if not value or value["status"] != "READY":
            return 3
    if args.request_profile and result["request_readiness"]["status"] != "READY":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
