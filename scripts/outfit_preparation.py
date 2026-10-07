"""Whole-outfit onboarding: read-only design, main image, views and publication.

The host supplies image inspection and concrete complete design alternatives.
Only confirmed previews create preparation records or invoke the generator.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil

from outfit_design import SLOTS, compile_back_identity, compile_design, validate_design, require_completed_calibration
from preparation_support import (IDENTITY_EXCLUSIONS, ID, check_preview, confirm, freeze,
    get_candidate, inside, invalidate_dependents, invocation, load, locked, new_id,
    record_visual_review, resume_preparation, run_candidate, utc, validate_record, workspace, write)
from reference_analysis import digest, fail, file_hash, text
from reference_runtime import generation_allowed, validate_generation_reference_input, resolve_style_references, resolve_style_context, compile_style_instructions

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ("front", "right-three-quarter", "back")
VIEW_CLASSES = {"front": "front", "right-three-quarter": "three_quarter_right", "back": "back"}


def resolve_sources(request: dict, root: Path) -> list[dict]:
    inputs = request.get("sources")
    if not isinstance(inputs, list) or not inputs:
        fail("OUTFIT_MATERIAL_REQUIRED", "V1 requires at least one image with its inspected part regions.")
    registry = {x["asset_id"]: x for x in load(root / "character/assets.yaml")["assets"]}
    originals_by_hash = {a["sha256"]: a for a in registry.values()}
    result, ids = [], set()
    groups_by_hash = {sha: a["source_group_id"] for sha, a in originals_by_hash.items()}
    for item in inputs:
        if not isinstance(item, dict) or not ID.fullmatch(str(item.get("source_id", ""))) or item["source_id"] in ids:
            fail("OUTFIT_MATERIAL_INVALID", "Sources need unique stable source_id values.")
        ids.add(item["source_id"])
        asset = registry.get(item.get("asset_id")) if item.get("asset_id") else None
        if item.get("asset_id") and asset is None:
            fail("OUTFIT_MATERIAL_INVALID", "Unknown published source asset.")
        path = inside(root, asset["path"]) if asset else Path(item.get("path", "")).resolve()
        if not path.is_file() or any(x in path.as_posix().casefold() for x in ("calibration/staging", "calibration/preparations")):
            fail("OUTFIT_MATERIAL_INVALID", "Use original images or published assets, never unapproved candidates.")
        validate_generation_reference_input(dict(asset or {}, path=str(path)), root=root)
        sha = file_hash(path)
        if asset and sha != asset["sha256"]:
            fail("OUTFIT_MATERIAL_STALE", "Published source hash mismatch.")
        source = deepcopy(item)
        source.update(path=str(path), sha256=sha,
            source_group_id=(asset or {}).get("source_group_id") or item.get("source_group_id") or "image-" + sha,
            source_kind=(asset or {}).get("source_kind", "user_provided"),
            evidence_independence=(asset or {}).get("evidence_independence", "independent"))
        if not asset and sha in originals_by_hash:
            source.update(copied_from_asset_id=originals_by_hash[sha]["asset_id"], evidence_independence="none")
        # Two crops/copies of a source never become two independent observations.
        original = source.get("original_path")
        if original:
            original = Path(original).resolve()
            if not original.is_file() or any(area in original.as_posix().casefold() for area in ("calibration/staging", "calibration/preparations")) or not source.get("processing_records"):
                fail("OUTFIT_MATERIAL_INVALID", "Processed materials require their original and processing records.")
            validate_generation_reference_input({"path": str(original)}, root=root)
            source.update(original_path=str(original), original_sha256=file_hash(original), evidence_independence="none")
            source["source_group_id"] = groups_by_hash.get(source["original_sha256"], "image-" + source["original_sha256"])
            for operation in source["processing_records"]:
                if not isinstance(operation, dict) or not operation.get("operation") or not operation.get("input_sha256") or not operation.get("output_sha256"):
                    fail("OUTFIT_MATERIAL_INVALID", "Processing records require operation and input/output hashes.")
            operations = source["processing_records"]
            if operations[0]["input_sha256"] != source["original_sha256"] or operations[-1]["output_sha256"] != sha or any(a["output_sha256"] != b["input_sha256"] for a, b in zip(operations, operations[1:])):
                fail("OUTFIT_MATERIAL_STALE", "Processing lineage does not bind the original to the selected image.")
        if sha in groups_by_hash:
            source["source_group_id"] = groups_by_hash[sha]
        groups_by_hash[sha] = source["source_group_id"]
        if asset:
            source["asset_id"] = asset["asset_id"]
            if asset.get("variant_id"):
                variant_path = inside(root, "variants/" + asset["variant_id"] + "/variant.yaml")
                variant = load(variant_path)
                if variant.get("lifecycle_status") != "published":
                    fail("UNPUBLISHED_ASSET", "Composition sources must be published Variants.")
                if variant.get("design_definition") is not None:
                    require_completed_calibration(root, variant, code="UNPUBLISHED_VARIANT")
                source.update(source_variant_id=asset["variant_id"], source_variant_revision=variant["revision"],
                              source_variant_path=str(variant_path), source_variant_sha256=file_hash(variant_path))
        if source.get("kind") not in {"partial", "product", "other_wearer", "arco_worn", "published_variant"}:
            fail("OUTFIT_MATERIAL_INVALID", "Declare partial, product, other_wearer, arco_worn or published_variant material.")
        for key in ("view", "occlusions", "source_note"):
            text(source.get(key), "source." + key)
        parts = source.get("parts")
        if not isinstance(parts, list) or not parts:
            fail("OUTFIT_ANALYSIS_REQUIRED", "Inspect and record visible parts and regions; incomplete images are allowed.")
        part_ids = set()
        for part in parts:
            if not isinstance(part, dict) or not ID.fullmatch(str(part.get("part_id", ""))) or part["part_id"] in part_ids or part.get("slot") not in SLOTS:
                fail("OUTFIT_MATERIAL_INVALID", "Each visible part needs a unique ID and known slot.")
            part_ids.add(part["part_id"])
            text(part.get("observations"), "part.observations")
            if part.get("evidence_status") not in {"TODO_CALIBRATION", "UNCERTAIN", "VISUAL_CONSENSUS", "CANON"}:
                fail("OUTFIT_MATERIAL_INVALID", "Retain the original observation's evidence status.")
            if part["evidence_status"] in {"VISUAL_CONSENSUS", "CANON"} and not asset:
                fail("OUTFIT_EVIDENCE_ESCALATION", "An external image alone cannot establish CANON or consensus.")
            region = part.get("region")
            if not isinstance(region, dict) or region.get("kind") not in {"whole", "box"}:
                fail("OUTFIT_REGION_REQUIRED", "Record the whole image or a normalized part box; processed sources retain their original lineage.")
            if region["kind"] == "box":
                box = region.get("xyxy")
                if not isinstance(box, list) or len(box) != 4 or any(type(x) not in {int, float} or not 0 <= x <= 1 for x in box) or box[0] >= box[2] or box[1] >= box[3]:
                    fail("OUTFIT_REGION_REQUIRED", "Box coordinates must be normalized, positive and ordered.")
        result.append(source)
    return result


def identity_references(root: Path, view_ids: list[str], explicit: dict | None = None) -> tuple[dict, list[dict]]:
    assets = load(root / "character/assets.yaml")["assets"]
    identity = load(root / "character/identity.yaml")
    if identity.get("approved_view_designs"):
        require_completed_calibration(root, identity, code="IDENTITY_CALIBRATION_REQUIRED")
    references, missing = {}, []
    explicit = explicit or {}
    for view_id in view_ids:
        view = VIEW_CLASSES.get(view_id, "front")
        profile = "back_view" if view == "back" else "full_body"
        required = {"identity", "hair.back", "body.back"} if view == "back" else {"identity", "hair", "body.full"}
        choices = []
        for asset in assets:
            metadata = asset.get("generation_reference") or {}
            coverage = metadata.get("coverage") or {}
            visible = set(coverage.get("visible_fields") or []) - set(coverage.get("occluded_fields") or [])
            angle_ok = bool(set(coverage.get("view_angles") or []) & {"back", "back_three_quarter"}) if view == "back" else asset.get("view_class") in {view, "frontal" if view == "front" else view}
            if generation_allowed(asset) and asset.get("asset_type") == "faceless_composite" and "identity_reference" in metadata.get("supported_roles", []) and profile not in metadata.get("excluded_for", []) and required <= visible and angle_ok:
                if not explicit.get(view_id) or explicit[view_id] == asset["asset_id"]:
                    choices.append(asset)
        if not choices:
            missing.append({"view_id": view_id, "missing_fields": sorted(required), "route": "identity_calibration", "identity_change": True})
            continue
        preferred = {"front": "casual-outfit-crossed-arms-evidence", "three_quarter_right": "casual-outfit-open-arms-no-horns-evidence"}.get(view)
        preferred_ids = [preferred] if preferred else ((identity.get("approved_view_designs") or {}).get("back") or {}).get("reference_asset_ids", [])
        asset = sorted(choices, key=lambda x: (x["asset_id"] not in preferred_ids, x["asset_id"]))[0]
        path = inside(root, asset["path"])
        if any(area in path.as_posix().casefold() for area in ("calibration/staging", "calibration/preparations")):
            fail("UNPUBLISHED_ASSET", "Identity references must come from the formal asset area.")
        validate_generation_reference_input(dict(asset, path=str(path)), root=root)
        if file_hash(path) != asset["sha256"]:
            fail("ASSET_HASH_MISMATCH", asset["asset_id"])
        references[view_id] = {"reference_id": "identity-" + view_id, "asset_id": asset["asset_id"],
            "path": str(path), "sha256": asset["sha256"], "usage": "identity", "view_class": asset["view_class"],
            "inherit": ["identity", "hair", "body_proportions", "official_arco_style"],
            "exclude": ["outfit", "pose", "expression", "scene"]}
    return references, missing


def material_references(sources: list[dict], design: dict, selected: list[str] | None = None) -> list[dict]:
    bindings = {(b["source_id"], b["part_id"]) for part in design["parts"].values() for b in part["source_bindings"]}
    if selected is not None and (not isinstance(selected, list) or set(selected) - {s["source_id"] for s in sources}):
        fail("OUTFIT_MATERIAL_INVALID", "View source selection contains unknown materials.")
    result = []
    for source in sources:
        parts = [p for p in source["parts"] if (source["source_id"], p["part_id"]) in bindings]
        if not parts or (selected is not None and source["source_id"] not in selected):
            continue
        result.append({"reference_id": "material-" + source["source_id"], "source_id": source["source_id"],
            "asset_id": source.get("asset_id"), "path": source["path"], "sha256": source["sha256"],
            "usage": "garment", "parts": deepcopy(parts), "inherit": ["selected_garment_parts"], "exclude": list(IDENTITY_EXCLUSIONS)})
    return result


def _curate(refs: list[dict]) -> list[dict]:
    """One physical input can carry approved identity and selected clothes."""
    result = []
    for reference in refs:
        ref = deepcopy(reference)
        same = next((r for r in result if r["path"] == ref["path"]), None)
        if same is None:
            result.append(ref)
        elif same["usage"] == "identity" and ref["usage"] == "garment" and same.get("asset_id") == ref.get("asset_id"):
            same.update(usage="identity_and_garment", source_id=ref["source_id"], parts=ref["parts"], garment_exclude=ref["exclude"])
        elif same["usage"] in {"garment", "identity_and_garment"} and ref["usage"] == "garment" and same.get("source_id") == ref.get("source_id"):
            same["parts"].extend(ref["parts"])
        else:
            fail("PREPARATION_CONTRACT_INVALID", "Conflicting duties on the same physical reference; curate the sources explicitly.")
    return result


def _style_prompt(baseline: dict) -> str:
    return compile_style_instructions(resolve_style_context(resolved_style_references=resolve_style_references([]), style_briefs=[], official_style_baseline=baseline))


def _prompt(design: dict, refs: list[dict], view_id: str, baseline: dict, identity: dict) -> str:
    entity = {"design_definition": design, "approval_context": {"user_confirmed": True,
        "design_sha256": digest(design), "user_message": "Design awaiting explicit stage confirmation",
        "preparation_id": "preview", "reference_pack_sha256": "preview"}}
    description = next((x["description"] for x in design["detail_requirements"] if x["view_id"] == view_id), None)
    goal = description or {"front": "front full-body neutral standing view", "right-three-quarter": "right three-quarter full-body neutral standing view", "back": "back full-body neutral standing view, face invisible"}[view_id]
    detail = view_id.startswith("detail-")
    framing = (
        "Garment-only detail reference: use a close-up or flat-lay composition as specified by the detail requirement. Render only the garment items named in that requirement; use the whole-outfit design and wearing relations only to keep those items consistent. Do not depict a person, human body, head, hair or facial features. Use a clear plain background and the official Arco baseline drawing style."
        if detail else
        "Faceless wearing reference: retain Arco head/hair/body silhouette, omit facial features. Use a clear plain background, unobstructed full-body framing and the official Arco baseline drawing style."
    )
    lines = ["Prepare a fixed Arco outfit reference: " + goal + ".",
        framing,
        "Preserve selected source garments' original cut, length and colors. Solve joins through the approved wearing relations; apply only explicitly approved redesigns.",
        compile_design(entity), _style_prompt(baseline)]
    if view_id == "back":
        lines.append(compile_back_identity(identity))
    for index, ref in enumerate(refs, 1):
        if ref["usage"] in {"garment", "identity_and_garment"}:
            if ref["usage"] == "identity_and_garment":
                duty = "official Arco rendering style only" if detail else "published Arco identity anchor"
                lines.append(f"Image {index}: {duty}, also supplying the explicitly selected clothing regions below. Garment-only exclusions apply to the garment-transfer duty.")
            lines.append(f"Image {index} garment-only: take only these parts/regions: " + json.dumps(ref["parts"], ensure_ascii=False, sort_keys=True) + ". Exclude the source person's identity, hair, facial expression, pose, drawing style, background and all unselected accessories.")
        elif ref["usage"] == "accepted_primary":
            if detail:
                lines.append(f"Image {index}: human-accepted garment design anchor; preserve the locked clothing construction and details only. Exclude its wearer, hair, pose and camera framing.")
            else:
                lines.append(f"Image {index}: human-accepted front design anchor; preserve the locked outfit structure across views. Do not copy its front camera into the requested view.")
        elif detail:
            lines.append(f"Image {index}: official Arco rendering style only; exclude its person, head, hair, body, clothing, pose and expression.")
        else:
            lines.append(f"Image {index}: approved Arco identity silhouette/proportions and baseline style only; exclude its clothing, pose and expression.")
    return "\n".join(lines)


def _bindings(root: Path, sources: list[dict], identity_refs: dict) -> dict:
    paths = [root / p for p in ("character/identity.yaml", "character/assets.yaml", "character/style-baseline.yaml", "variants/index.yaml")]
    paths += [Path(s["path"]) for s in sources] + [Path(r["path"]) for r in identity_refs.values()]
    paths += [Path(s[k]) for s in sources for k in ("original_path", "source_variant_path") if s.get(k)]
    return {str(p.resolve()): file_hash(p) for p in paths}


def plan_outfit_preparation(request: dict, *, root: Path = ROOT) -> dict:
    """Read-only: accept partial evidence, require concrete complete proposals."""
    root = root.resolve()
    request = deepcopy(request)
    variant_id = request.get("variant_id")
    if not ID.fullmatch(str(variant_id or "")):
        fail("OUTFIT_REQUEST_INVALID", "A stable new whole-outfit variant_id is required.")
    if any(x["variant_id"] == variant_id for x in load(root / "variants/index.yaml")["variants"]):
        fail("OUTFIT_VARIANT_EXISTS", "V1 publishes a new fixed outfit; choose a new Variant ID.")
    text(request.get("name"), "outfit.name")
    sources = resolve_sources(request, root)
    designs = request.get("designs")
    if not isinstance(designs, list) or not designs:
        fail("DESIGN_PROPOSALS_REQUIRED", "Inspect materials and propose complete designs, normally two alternatives.")
    seen = set()
    for design in designs:
        validate_design(design, sources)
        if not ID.fullmatch(str(design.get("design_id", ""))) or design["design_id"] in seen:
            fail("DESIGN_INVALID", "Design alternatives require unique IDs.")
        seen.add(design["design_id"])
    selected = next((d for d in designs if d["design_id"] == request.get("selected_design_id")), None)
    if selected is None:
        return freeze({"schema_version": 1, "purpose": "outfit_preparation", "phase": "design",
            "status": "NEEDS_DESIGN_SELECTION", "request": request, "sources": sources, "designs": designs,
            "bindings": _bindings(root, sources, {})})
    gaps = request.get("gaps", [])
    if not isinstance(gaps, list) or any(not isinstance(g, dict) or g.get("slot") not in SLOTS or not g.get("gap_id") or not g.get("description") for g in gaps):
        fail("DESIGN_INVALID", "Gaps require IDs, slots and concrete descriptions.")
    resolutions = selected.get("gap_resolutions", {})
    if not isinstance(resolutions, dict):
        fail("DESIGN_INVALID", "gap_resolutions must map gap IDs to concrete decisions.")
    unresolved = [g for g in gaps if g.get("critical", True) and (not isinstance(resolutions.get(g["gap_id"]), str) or not resolutions[g["gap_id"]].strip())]
    conflicts = request.get("conflicts", [])
    if not isinstance(conflicts, list) or any(not isinstance(c, dict) or not c.get("conflict_id") or not c.get("description") for c in conflicts):
        fail("DESIGN_INVALID", "Conflicts require IDs and descriptions.")
    unresolved += [c for c in conflicts if not (selected.get("conflict_resolutions") or {}).get(c["conflict_id"])]
    combination = request.get("combination", {})
    if not isinstance(combination, dict) or set(combination) - set(SLOTS):
        fail("DESIGN_INVALID", "Combination maps garment slots to selected source/part bindings.")
    for slot, bindings in combination.items():
        if selected["parts"][slot]["source_bindings"] != bindings:
            fail("DESIGN_SOURCE_MISMATCH", "Selected design changed the requested composition sources.")
    if unresolved:
        return freeze({"schema_version": 1, "purpose": "outfit_preparation", "phase": "design", "status": "NEEDS_COMPLETION",
            "request": request, "sources": sources, "selected_design": selected, "unresolved": unresolved,
            "bindings": _bindings(root, sources, {})})
    view_ids = list(VIEWS) + [d["view_id"] for d in selected["detail_requirements"]]
    identity_refs, missing = identity_references(root, list(VIEWS), request.get("identity_assets"))
    bindings = _bindings(root, sources, identity_refs)
    payload = {"schema_version": 1, "purpose": "outfit_preparation", "phase": "design_and_main", "status": "IDENTITY_CALIBRATION_REQUIRED" if missing else "READY",
        "request": request, "sources": sources, "selected_design": selected, "identity_references": identity_refs,
        "identity_prerequisites": missing, "required_views": view_ids, "bindings": bindings,
        "confirmation_nodes": ["design_and_main", "main_and_views", "reference_pack_and_publication"],
        "max_automatic_repairs_per_image": 2}
    if not missing:
        refs = _curate([identity_refs["front"], *material_references(sources, selected, (request.get("view_sources") or {}).get("front"))])
        payload["main_plan"] = invocation(purpose="outfit_preparation", view_id="front",
            prompt=_prompt(selected, refs, "front", load(root / "character/style-baseline.yaml"), load(root / "character/identity.yaml")), references=refs, bindings=bindings, context={"request": request, "sources": sources})
        adopt = request.get("existing_primary_source_id")
        if adopt:
            source = next((s for s in sources if s["source_id"] == adopt), None)
            if source is None or source["kind"] not in {"arco_worn", "published_variant"}:
                fail("OUTFIT_ADOPTION_INVALID", "Direct review requires an actual Arco wearing reference.")
            payload["adopt_primary"] = {"source_id": adopt, "path": source["path"], "sha256": source["sha256"]}
    return freeze(payload)


def _retain_sources(sources: list[dict], path: Path) -> None:
    for source in sources:
        target = inside(path, "originals/" + source["source_id"] + "-" + source["sha256"][:12] + Path(source["path"]).suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source["path"], target)
        if file_hash(target) != source["sha256"]:
            fail("OUTFIT_MATERIAL_STALE", "Retained source contents changed.")
        source["retained_path"] = str(target)
        if source.get("original_path"):
            original = inside(path, "originals/" + source["source_id"] + "-original-" + source["original_sha256"][:12] + Path(source["original_path"]).suffix)
            if not original.exists():
                shutil.copy2(source["original_path"], original)
            if file_hash(original) != source["original_sha256"]:
                fail("OUTFIT_MATERIAL_STALE", "Retained original contents changed.")
            source["retained_original_path"] = str(original)


def create_preparation(preview: dict, confirmation: dict, *, root: Path = ROOT) -> dict:
    confirm(confirmation, preview)
    if preview.get("purpose") != "outfit_preparation" or preview.get("status") != "READY":
        fail("PREPARATION_PREREQUISITE_REQUIRED", "Complete the design and separately publish missing identity baselines before freezing try-on.")
    # Rebuild rather than trusting a self-hashed caller-supplied invocation.
    if plan_outfit_preparation(preview["request"], root=root) != preview:
        fail("PREPARATION_PLAN_STALE", "Planning inputs changed.")
    pid = new_id("prep")
    path = workspace(root, pid)
    path.mkdir(parents=True, exist_ok=False)
    record = {"schema_version": 1, "preparation_id": pid, "purpose": "outfit_preparation", "created_at": utc(), "state": "MAIN_READY",
        "request": deepcopy(preview["request"]), "sources": deepcopy(preview["sources"]), "design_definition": deepcopy(preview["selected_design"]),
        "required_views": preview["required_views"], "identity_references": deepcopy(preview["identity_references"]),
        "plans": {"front": deepcopy(preview["main_plan"])}, "previews": {"design": deepcopy(preview)},
        "approvals": {"design": deepcopy(confirmation)}, "attempts": [], "candidates": [], "events": []}
    _retain_sources(record["sources"], path)
    write(path / "preparation.yaml", record)
    return deepcopy(record)


def adopt_primary(*, root: Path, preparation_id: str) -> dict:
    path = workspace(root, preparation_id)
    with locked(path):
        record = load(path / "preparation.yaml")
        preview = record["previews"]["design"]
        confirm(record["approvals"]["design"], preview)
        source = preview.get("adopt_primary")
        if not source or record["candidates"] or record["attempts"]:
            fail("OUTFIT_ADOPTION_INVALID", "Adopt only the explicitly previewed primary before generation.")
        target = inside(path, "candidates/front-adopted" + Path(source["path"]).suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source["path"], target)
        candidate = {"candidate_id": "front-adopted", "view_id": "front", "path": str(target), "sha256": file_hash(target),
            "plan_sha256": record["plans"]["front"]["plan_sha256"], "attempt_id": None, "repair_number": 0,
            "main_sha256": None, "review": None, "user_accepted": False, "invalidated": False, "adopted_source_id": source["source_id"]}
        record["candidates"].append(candidate)
        record["state"] = "AWAITING_VISUAL_REVIEW"
        write(path / "preparation.yaml", record)
        return deepcopy(candidate)


def plan_remaining_views(*, root: Path, preparation_id: str, main_candidate_id: str) -> dict:
    record = load(workspace(root, preparation_id) / "preparation.yaml")
    validate_record(record)
    main = get_candidate(record, main_candidate_id)
    if main["view_id"] != "front" or not main.get("review") or main["review"]["status"] != "PASS":
        fail("MAIN_VISUAL_REVIEW_REQUIRED", "Inspect and review the main image before presenting remaining views.")
    bindings = deepcopy(record["plans"]["front"]["bindings"])
    bindings[main["path"]] = main["sha256"]
    primary = {"reference_id": "accepted-primary", "candidate_id": main["candidate_id"], "path": main["path"], "sha256": main["sha256"], "usage": "accepted_primary"}
    plans = {}
    for view_id in record["required_views"]:
        if view_id == "front":
            continue
        identity = record["identity_references"][view_id if view_id in VIEW_CLASSES else "front"]
        detail = next((d for d in record["design_definition"]["detail_requirements"] if d["view_id"] == view_id), None)
        selected = (record["request"].get("view_sources") or {}).get(view_id)
        if selected is None and detail:
            selected = detail["source_ids"]
        refs = _curate([identity, primary, *material_references(record["sources"], record["design_definition"], selected)])
        plans[view_id] = invocation(purpose="outfit_preparation", view_id=view_id,
            prompt=_prompt(record["design_definition"], refs, view_id, load(root / "character/style-baseline.yaml"), load(root / "character/identity.yaml")), references=refs, bindings=bindings,
            context={"design_preview_sha256": record["previews"]["design"]["preview_sha256"], "main_candidate_id": main["candidate_id"]})
    return freeze({"schema_version": 1, "purpose": "outfit_preparation", "phase": "main_and_views", "preparation_id": preparation_id,
        "main_candidate": deepcopy(main), "plans": plans, "bindings": bindings, "max_automatic_repairs_per_image": 2})


def approve_main_and_views(preview: dict, confirmation: dict, *, root: Path = ROOT) -> dict:
    confirm(confirmation, preview)
    pid = preview["preparation_id"]
    path = workspace(root, pid)
    with locked(path):
        record = load(path / "preparation.yaml")
        if record["state"] in {"PUBLICATION_STAGED", "PUBLISHED", "RECOVERY_REQUIRED"}:
            fail("PREPARATION_STATE_INVALID", "Main/view approval is closed by the publication transaction.")
        if plan_remaining_views(root=root, preparation_id=pid, main_candidate_id=preview["main_candidate"]["candidate_id"]) != preview:
            fail("PREPARATION_PLAN_STALE", "Main image, inspection or remaining-view plans changed.")
        previous = record.get("locked_main")
        if previous and previous["candidate_id"] != preview["main_candidate"]["candidate_id"]:
            invalidate_dependents(record)
            record["events"].append({"event": "main_replaced", "previous": previous, "at": utc()})
        main = get_candidate(record, preview["main_candidate"]["candidate_id"])
        main["user_accepted"] = True
        record["locked_main"] = {"candidate_id": main["candidate_id"], "sha256": main["sha256"]}
        record["plans"].update(deepcopy(preview["plans"]))
        record["previews"]["main_and_views"] = deepcopy(preview)
        record["approvals"]["main_and_views"] = deepcopy(confirmation)
        record["state"] = "VIEWS_READY"
        write(path / "preparation.yaml", record)
        return deepcopy(record)


def revise_preparation(*, root: Path, preparation_id: str, preview: dict, confirmation: dict) -> dict:
    """Design/material edits return to node one; retain every prior candidate."""
    confirm(confirmation, preview)
    if preview.get("status") != "READY" or plan_outfit_preparation(preview["request"], root=root) != preview:
        fail("PREPARATION_PLAN_STALE", "Confirm the newly rebuilt complete design/main preview.")
    path = workspace(root, preparation_id)
    with locked(path):
        record = load(path / "preparation.yaml")
        if record["state"] == "PUBLISHED" or preview["request"]["variant_id"] != record["request"]["variant_id"]:
            fail("PREPARATION_STATE_INVALID", "Cannot rewrite a publication transaction or change its Variant identity.")
        if record["state"] in {"PUBLICATION_STAGED", "RECOVERY_REQUIRED"}:
            from preparation_publication import release_staging_for_revision
            release_staging_for_revision(root=root, record=record)
        record.setdefault("plan_history", []).append({"at": utc(), "reason": "design_reconfirmed",
            "plans": deepcopy(record["plans"]), "previews": deepcopy(record["previews"]), "approvals": deepcopy(record["approvals"]),
            "locked_main": deepcopy(record.get("locked_main")), "pack_review": deepcopy(record.get("pack_review"))})
        record["events"].append({"event": "design_reconfirmed", "previous_preview": record["previews"]["design"], "at": utc()})
        for candidate in record["candidates"]:
            candidate.update(invalidated=True, user_accepted=False)
        record.pop("locked_main", None)
        record.update(request=deepcopy(preview["request"]), sources=deepcopy(preview["sources"]), design_definition=deepcopy(preview["selected_design"]),
            required_views=preview["required_views"], identity_references=deepcopy(preview["identity_references"]), plans={"front": deepcopy(preview["main_plan"])},
            previews={"design": deepcopy(preview)}, approvals={"design": deepcopy(confirmation)}, state="MAIN_READY")
        _retain_sources(record["sources"], path)
        record.pop("pack_review", None)
        write(path / "preparation.yaml", record)
        return deepcopy(record)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["plan", "create", "status", "plan-views", "approve-views", "review", "revise", "adopt-primary", "plan-pack", "review-pack", "plan-publication", "stage", "publish", "recover"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--input", type=Path, help="JSON request/preview/review, according to operation")
    parser.add_argument("--confirmation", type=Path)
    parser.add_argument("--preparation-id")
    parser.add_argument("--candidate-id")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8")) if args.input else {}
    approval = json.loads(args.confirmation.read_text(encoding="utf-8")) if args.confirmation else {}
    options = {"root": args.root.resolve(), "preparation_id": args.preparation_id}
    if args.operation == "plan":
        result = plan_outfit_preparation(data, root=args.root)
    elif args.operation == "create":
        result = create_preparation(data, approval, root=args.root)
    elif args.operation == "status":
        result = resume_preparation(**options)
    elif args.operation == "plan-views":
        result = plan_remaining_views(**options, main_candidate_id=args.candidate_id)
    elif args.operation == "approve-views":
        result = approve_main_and_views(data, approval, root=args.root)
    elif args.operation == "review":
        result = record_visual_review(**options, candidate_id=args.candidate_id, review=data)
    elif args.operation == "revise":
        result = revise_preparation(**options, preview=data, confirmation=approval)
    elif args.operation == "adopt-primary":
        result = adopt_primary(**options)
    else:
        from preparation_publication import plan_publication, stage_publication, publish_preparation, recover_publication, plan_reference_pack, record_pack_review
        if args.operation == "plan-pack":
            result = plan_reference_pack(**options, selection=data.get("selection"))
        elif args.operation == "review-pack":
            result = record_pack_review(**options, preview=data["preview"], review=data["review"])
        elif args.operation == "plan-publication":
            result = plan_publication(**options, selection=data.get("selection"))
        elif args.operation == "stage":
            result = stage_publication(data, approval, root=args.root)
        elif args.operation == "publish":
            result = publish_preparation(**options)
        else:
            result = recover_publication(**options)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
