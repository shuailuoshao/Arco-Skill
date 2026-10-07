"""Shared preview/staging/publication bridge for outfits and back identity.

Only the accepted final pack creates Calibration staging. The established v3
publisher owns formal writes, hash guards, rollback, History and completion.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil

import yaml

from check_calibration_lock import conflicts
from outfit_design import validate_approved_design, validate_back_identity
from preparation_support import (CHECKS, check_preview, confirm, freeze, get_candidate, inside,
    load, locked, new_id, utc, validate_record, workspace, write)
from reference_analysis import digest, fail, file_hash
from publish_calibration import PublishError, replace_from_source
from publication_v3 import publish
from validate_library import validate


def yaml_bytes(data: dict) -> bytes:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False).encode("utf-8")


def _data_file(relative: str, data: dict) -> dict:
    # Preview JSON preserves values but discards shared-object YAML aliases.
    # Hash the same value tree that survives saving and reopening the preview.
    data = json.loads(json.dumps(data, ensure_ascii=False))
    return {"target_path": relative, "data": data, "candidate_hash": hashlib.sha256(yaml_bytes(data)).hexdigest()}


def _image_file(relative: str, path: str, asset_id: str) -> dict:
    return {"target_path": relative, "source_path": path, "asset_id": asset_id, "candidate_hash": file_hash(path)}


def _text_file(relative: str, content: str) -> dict:
    return {"target_path": relative, "text": content, "candidate_hash": hashlib.sha256(content.encode("utf-8")).hexdigest()}


def _asset(asset_id: str, relative: str, sha: str, *, variant_id: str | None, level: str,
           kind: str, group: str, view: str, roles: list[str]) -> dict:
    return {"asset_id": asset_id, "path": relative, "sha256": sha, "asset_status": "VERIFIED",
        "asset_type": "faceless_composite" if view != "detail" else "outfit_detail",
        "variant_id": variant_id, "state_ids": [], "reference_level": level,
        "roles": roles, "view_angle": "front_three_quarter" if view == "three_quarter_right" else view,
        "view_class": view, "source_kind": kind, "source_authority": "user_approved" if kind == "derivative" else "unverified",
        "source_group_id": group, "can_be_generation_reference": False,
        "provenance": {"source_note": "Approved preparation; observation evidence and authored design remain separate."}}


def _sources(record: dict, variant_id: str, assets: list[dict], files: list[dict]) -> list[dict]:
    sources = deepcopy(record["sources"])
    for source in sources:
        if source.get("asset_id"):
            continue
        aid = variant_id + "-source-" + source["source_id"]
        relative = f"assets/arco/variants/{variant_id}/sources/{source['source_id']}" + Path(source["path"]).suffix
        original_id = None
        if source.get("original_path"):
            original_id = aid + "-original"
            original_relative = f"assets/arco/variants/{variant_id}/sources/{source['source_id']}-original" + Path(source["original_path"]).suffix
            files.append(_image_file(original_relative, source["original_path"], original_id))
            original = _asset(original_id, original_relative, source["original_sha256"], variant_id=variant_id,
                level="detail", kind="user_provided", group=source["source_group_id"], view="unknown", roles=["variant_evidence"])
            original["asset_type"] = "source_material"
            original["provenance"].update(source_path=source["original_path"], preparation_id=record["preparation_id"])
            assets.append(original)
        files.append(_image_file(relative, source["path"], aid))
        parent_id = original_id or source.get("copied_from_asset_id")
        asset = _asset(aid, relative, source["sha256"], variant_id=variant_id, level="detail",
            kind="derivative" if parent_id else "user_provided", group=source["source_group_id"], view="unknown", roles=["variant_evidence"])
        asset["asset_type"] = "source_material"
        asset["provenance"].update(source_path=source["path"], preparation_id=record["preparation_id"], source_note=source["source_note"])
        if parent_id:
            asset.update(derived_from_asset_id=parent_id, evidence_independence="none", operation=source.get("processing_records") or [{"operation": "copy", "input_sha256": source["sha256"], "output_sha256": source["sha256"]}])
        assets.append(asset)
        source.update(asset_id=aid, published_path=relative)
    return sources


def _permission(view: str, *, identity: bool = False, detail: bool = False) -> dict:
    if detail:
        return {"priority": "supplemental", "supported_roles": ["detail_reference"], "preferred_for": [], "excluded_for": [],
            "coverage": {"profiles": [], "visible_fields": [], "view_angles": ["detail"], "occluded_fields": []},
            "inheritance": {"outfit_detail": "inherit", "identity": "do_not_inherit", "pose": "do_not_inherit"}}
    back = view == "back"
    profiles = ["back_view"] if back else ["portrait", "upper_body", "full_body"]
    visible = (["identity", "hair.back", "body.back"] if identity else ["variant.back_outfit"]) if back else ["variant.visible_headwear_accessories", "variant.upper_body_outfit", "variant.full_outfit", "variant.footwear"]
    inheritance = {"identity": "inherit" if identity else "do_not_inherit", "hair": "inherit" if identity else "do_not_inherit",
        "body_proportions": "inherit" if identity else "do_not_inherit", "outfit": "do_not_inherit" if identity else "inherit",
        "expression": "do_not_inherit", "pose": "do_not_inherit", "style": "do_not_inherit", "scene": "do_not_inherit"}
    return {"priority": "primary" if view == "front" or identity else "secondary",
        "supported_roles": ["identity_reference" if identity else "outfit_reference"], "preferred_for": profiles,
        "excluded_for": ["portrait", "upper_body", "full_body"] if back else ["back_view"],
        "coverage": {"profiles": profiles, "visible_fields": visible,
            "view_angles": ["front_three_quarter" if view == "three_quarter_right" else view], "occluded_fields": []}, "inheritance": inheritance}


def _output_asset(record: dict, candidate: dict, aid: str, relative: str, *, variant_id: str | None,
                  level: str, view: str, source_materials: list[dict], identity: bool = False) -> dict:
    asset = _asset(aid, relative, candidate["sha256"], variant_id=variant_id, level=level, kind="derivative",
        group="preparation-" + record["preparation_id"], view=view,
        roles=["identity_evidence", "hair_evidence", "body_evidence"] if identity else ["outfit_detail_evidence" if view == "detail" else "variant_evidence"])
    sources = {s["source_id"]: s for s in source_materials}
    parents = []
    if candidate.get("adopted_source_id"):
        source = sources[candidate["adopted_source_id"]]
        parents.append({"asset_id": source["asset_id"], "sha256": source["sha256"], "usage": "adopted_worn_reference", "parts": source["parts"]})
    else:
        for ref in record["plans"][candidate["view_id"]]["references"]:
            if ref["usage"] == "accepted_primary":
                parent_id = variant_id + "-front"
            elif ref["usage"] in {"garment", "identity_and_garment"}:
                parent_id = sources[ref["source_id"]]["asset_id"]
            else:
                parent_id = ref["asset_id"]
            binding = {"asset_id": parent_id, "sha256": ref["sha256"], "usage": ref["usage"]}
            if ref.get("parts"):
                binding["parts"] = deepcopy(ref["parts"])
            if ref.get("source_id"):
                source = sources[ref["source_id"]]
                for key in ("source_variant_id", "source_variant_revision", "source_variant_sha256", "processing_records"):
                    if key in source:
                        binding[key] = deepcopy(source[key])
            parents.append(binding)
    asset.update(derived_from_asset_ids=list(dict.fromkeys(x["asset_id"] for x in parents)), derivation_sources=parents,
        evidence_independence="none", can_be_generation_reference=True,
        generation_reference=_permission(view, identity=identity, detail=view == "detail"),
        generation_record={"preparation_id": record["preparation_id"], "candidate_id": candidate["candidate_id"],
            "plan_sha256": candidate["plan_sha256"], "output_sha256": candidate["sha256"], "attempt_id": candidate["attempt_id"], "repair_number": candidate["repair_number"]})
    if candidate.get("actual_prompt_sha256"):
        asset["generation_record"]["actual_prompt_sha256"] = candidate["actual_prompt_sha256"]
    if candidate.get("repair_source_candidate_id"):
        asset["generation_record"].update(repair_source_candidate_id=candidate["repair_source_candidate_id"],
            correction_code=candidate["correction_code"], repair_input_bindings=deepcopy(candidate["repair_input_bindings"]))
    return asset


def _target(before: dict, after: dict, target_type: str, target_id: str, fields: list[str]) -> dict:
    return {"entity_ref": after["entity_ref"], "target_type": target_type, "target_id": target_id,
        "revision_before": before.get("revision", 0), "revision_after": after["revision"], "changed_fields": fields,
        "before": {k: deepcopy(before.get(k)) for k in fields if k in before},
        "after": {k: deepcopy(after.get(k)) for k in fields}, "status_before": None, "status_after": None}


def _formal_bindings(root: Path) -> dict:
    paths = [root / "SKILL.md"]
    for directory in ("character", "variants", "runtime", "calibration/history"):
        paths += list((root / directory).rglob("*.yaml"))
    paths += list((root / "calibration/history").glob("*.complete"))
    paths += [inside(root, a["path"]) for a in load(root / "character/assets.yaml")["assets"]]
    return {str(p.resolve()): file_hash(p) for p in paths if p.is_file()}


def plan_reference_pack(*, root: Path, preparation_id: str, selection: dict | None = None) -> dict:
    """Read-only full-image pack for an explicit cross-view inspection."""
    record = load(workspace(root, preparation_id) / "preparation.yaml")
    validate_record(record)
    required = record["required_views"]
    if selection is not None and (not isinstance(selection, dict) or set(selection) != set(required)):
        fail("REFERENCE_PACK_INCOMPLETE", "Choose every required view exactly once.")
    selected = {}
    for view in required:
        options = [c for c in record["candidates"] if c["view_id"] == view and not c.get("invalidated") and (c.get("review") or {}).get("status") == "PASS"]
        chosen = selection.get(view) if selection else (record.get("locked_main", {}).get("candidate_id") if view == "front" else options[-1]["candidate_id"] if options else None)
        if not chosen:
            fail("REFERENCE_PACK_INCOMPLETE", "Reviewed image missing for " + view)
        candidate = get_candidate(record, chosen)
        if candidate["view_id"] != view or not (candidate.get("review") or {}).get("status") == "PASS":
            fail("REFERENCE_PACK_UNVERIFIED", "Each selected view requires a passing inspection.")
        selected[view] = deepcopy(candidate)
    return freeze({"schema_version": 1, "purpose": record["purpose"], "phase": "pack_visual_inspection",
        "preparation_id": preparation_id, "selection": {v: c["candidate_id"] for v, c in selected.items()},
        "images": selected, "bindings": {c["path"]: c["sha256"] for c in selected.values()}})


def record_pack_review(*, root: Path, preparation_id: str, preview: dict, review: dict) -> dict:
    """Retain the actual all-views comparison; it does not authorize publication."""
    if not isinstance(review, dict) or review.get("preview_sha256") != preview["preview_sha256"] or review.get("inspected_original_size") is not True:
        fail("VISUAL_REVIEW_INVALID", "Pack inspection must bind all original-size selected images.")
    checks = review.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(CHECKS):
        fail("VISUAL_REVIEW_INVALID", "Inspect all five dimensions across the entire reference pack.")
    from reference_analysis import text
    for key, item in checks.items():
        if not isinstance(item, dict) or item.get("status") not in {"PASS", "FAIL", "UNVERIFIED"}:
            fail("VISUAL_REVIEW_INVALID", "Invalid pack check: " + key)
        text(item.get("evidence"), "pack_review." + key)
    result = {"preview": deepcopy(preview), "review": deepcopy(review), "user_accepted": False}
    statuses = {x["status"] for x in checks.values()}
    result["status"] = "FAIL" if "FAIL" in statuses else "UNVERIFIED" if "UNVERIFIED" in statuses else "PASS"
    path = workspace(root, preparation_id)
    with locked(path):
        record = load(path / "preparation.yaml")
        if record["state"] in {"PUBLICATION_STAGED", "PUBLISHED", "RECOVERY_REQUIRED"}:
            fail("PREPARATION_STATE_INVALID", "The publication transaction already froze its inspection records.")
        if plan_reference_pack(root=root, preparation_id=preparation_id, selection=preview["selection"]) != preview:
            fail("REFERENCE_PACK_STALE", "Re-inspect the selected pack after any view changes.")
        if record.get("pack_review"):
            record.setdefault("pack_review_history", []).append(deepcopy(record["pack_review"]))
        record["pack_review"] = result
        write(path / "preparation.yaml", record)
    return deepcopy(result)


def plan_publication(*, root: Path, preparation_id: str, selection: dict | None = None) -> dict:
    path = workspace(root, preparation_id)
    record = load(path / "preparation.yaml")
    if record["state"] in {"PUBLISHED", "PUBLICATION_STAGED", "RECOVERY_REQUIRED"}:
        fail("PREPARATION_STATE_INVALID", "This preparation already has a publication transaction.")
    identity = record["purpose"] == "identity_calibration"
    validate_record(record)
    if not identity:
        confirm(record["approvals"].get("main_and_views"), record["previews"].get("main_and_views", {}))
    required = ["identity-back"] if identity else record["required_views"]
    selected = {}
    if selection is not None and (not isinstance(selection, dict) or set(selection) != set(required)):
        fail("REFERENCE_PACK_INCOMPLETE", "Select exactly one candidate for each required view.")
    for view in required:
        if selection:
            candidate = get_candidate(record, selection[view])
        else:
            options = [c for c in record["candidates"] if c["view_id"] == view and not c.get("invalidated") and (c.get("review") or {}).get("status") == "PASS"]
            if not options:
                fail("REFERENCE_PACK_INCOMPLETE", "A reviewed candidate is required for " + view)
            candidate = get_candidate(record, options[-1]["candidate_id"])
        if candidate["view_id"] != view or not candidate.get("review") or candidate["review"]["status"] != "PASS":
            fail("REFERENCE_PACK_UNVERIFIED", "Every selected image requires all five visual checks to pass.")
        if not identity:
            main = record.get("locked_main") or {}
            if (view == "front" and candidate["candidate_id"] != main.get("candidate_id")) or (view != "front" and candidate["main_sha256"] != main.get("sha256")):
                fail("PREPARATION_MAIN_STALE", "Reference views must depend on the accepted main image.")
        selected[view] = deepcopy(candidate)
    if not identity:
        pack_review = record.get("pack_review")
        pack_preview = plan_reference_pack(root=root, preparation_id=preparation_id, selection={v: c["candidate_id"] for v, c in selected.items()})
        if not pack_review or pack_review.get("status") != "PASS" or pack_review["preview"] != pack_preview:
            fail("REFERENCE_PACK_REVIEW_REQUIRED", "Inspect all selected views together before the publication preview.")
    pack_sha = digest({v: {"sha256": c["sha256"], "review": c["review"], "candidate_id": c["candidate_id"]} for v, c in selected.items()})
    cid = record.get("next_calibration_id") or "cal-" + preparation_id.split("-", 1)[1]
    assets_before = load(root / "character/assets.yaml")
    registry = deepcopy(assets_before)
    registry.update(schema_version=3, revision=registry["revision"] + 1, last_calibration_id=cid)
    files, targets, new_assets = [], [], []
    design_approval = {"user_confirmed": True, "user_message": record["approvals"]["design"]["user_message"],
        "design_sha256": digest(record["design_definition"]), "preparation_id": preparation_id,
        "reference_pack_sha256": pack_sha, "design_preview_sha256": record["previews"]["design"]["preview_sha256"]}
    if not identity:
        design_approval["main_approval"] = deepcopy(record["approvals"]["main_and_views"])
    if identity:
        before = load(root / "character/identity.yaml")
        entity = deepcopy(before)
        aid = "arco-identity-back-" + preparation_id.rsplit("-", 1)[1]
        candidate = selected["identity-back"]
        relative = "assets/arco/identity/back/" + aid + Path(candidate["path"]).suffix
        files.append(_image_file(relative, candidate["path"], aid))
        new_assets.append(_output_asset(record, candidate, aid, relative, variant_id=None, level="identity", view="back", source_materials=[], identity=True))
        entry = {"definition": deepcopy(record["design_definition"]), "approval_context": design_approval, "reference_asset_ids": [aid]}
        validate_back_identity(entry)
        entity.setdefault("approved_view_designs", {})["back"] = entry
        entity.update(revision=entity["revision"] + 1, last_calibration_id=cid)
        files.append(_data_file("character/identity.yaml", entity))
        markdown = root / "character/identity.md"
        if markdown.is_file():
            content = markdown.read_text(encoding="utf-8")
            import re
            content = re.sub(r"(?m)^source_revision: [0-9]+$", "source_revision: " + str(entity["revision"]), content, count=1)
            files.append(_text_file("character/identity.md", content))
        targets.append(_target(before, entity, "identity_design", "back", ["revision", "last_calibration_id", "approved_view_designs"]))
        calibration_targets = ["character.assets", "character.identity"]
    else:
        variant_id = record["request"]["variant_id"]
        materials = _sources(record, variant_id, new_assets, files)
        refs = {"primary": [], "secondary": [], "detail": []}
        for view_id, candidate in selected.items():
            level = "primary" if view_id == "front" else "detail" if view_id.startswith("detail-") else "secondary"
            view = {"front": "front", "right-three-quarter": "three_quarter_right", "back": "back"}.get(view_id, "detail")
            aid = variant_id + "-" + view_id
            relative = f"assets/arco/variants/{variant_id}/references/{view_id}" + Path(candidate["path"]).suffix
            files.append(_image_file(relative, candidate["path"], aid))
            new_assets.append(_output_asset(record, candidate, aid, relative, variant_id=variant_id, level=level, view=view, source_materials=materials))
            refs[level].append(aid)
        entity = {"schema_version": 1, "entity_type": "variant", "entity_ref": "variants." + variant_id,
            "variant_id": variant_id, "display_name_zh": record["request"]["name"], "display_name_en": record["request"].get("name_en", variant_id),
            "lifecycle_status": "published", "revision": 1, "last_calibration_id": cid, "facts": [],
            "reference_asset_ids": refs, "must_keep_fields": [], "state_mutable_fields": [], "state_files": [], "state_groups": {},
            "design_definition": deepcopy(record["design_definition"]), "approval_context": design_approval,
            "source_materials": materials, "known_risks": ["Authored completion constraints are design decisions, not elevated evidence Facts."],
            "coverage": {k: "READY" for k in ("upper_body", "lower_body", "full_body", "footwear", "back_view", "overall")}}
        validate_approved_design(entity)
        files.append(_data_file(f"variants/{variant_id}/variant.yaml", entity))
        targets.append(_target({"revision": 0, "last_calibration_id": None}, entity, "variant", variant_id, list(entity)))
        before_index = load(root / "variants/index.yaml")
        index = deepcopy(before_index)
        index["variants"].append({"variant_id": variant_id, "path": f"variants/{variant_id}/variant.yaml", "display_name_zh": entity["display_name_zh"], "display_name_en": entity["display_name_en"], "lifecycle_status": "published"})
        index.update(revision=index["revision"] + 1, last_calibration_id=cid)
        files.append(_data_file("variants/index.yaml", index))
        targets.append(_target(before_index, index, "variant_index", "variants.index", ["revision", "last_calibration_id"]))
        calibration_targets = ["character.assets", "variants.index", "variants." + variant_id]
        files.append(_data_file(f"variants/{variant_id}/preparation-record.yaml", {
            "schema_version": 1, "purpose": record["purpose"], "preparation_id": preparation_id,
            "source_materials": materials, "design_definition": record["design_definition"],
            "plans": record["plans"], "attempts": record["attempts"], "candidates": record["candidates"],
            "approvals": record["approvals"], "pack_review": record.get("pack_review"), "plan_history": record.get("plan_history", []),
            "pack_review_history": record.get("pack_review_history", []), "events": record["events"], "selected_pack": {v: c["candidate_id"] for v, c in selected.items()}}))
    existing_ids = {a["asset_id"] for a in registry["assets"]}
    if existing_ids & {a["asset_id"] for a in new_assets}:
        fail("PUBLICATION_TARGET_EXISTS", "An asset ID in this publication is already registered.")
    registry["assets"].extend(new_assets)
    files.append(_data_file("character/assets.yaml", registry))
    targets.append(_target(assets_before, registry, "asset_registry", "character.assets", ["revision", "last_calibration_id"]))
    history = {"schema_version": 1, "calibration_id": cid, "timestamp": record["created_at"], "operation": "add" if not identity else "update",
        "user_confirmed": True, "reason": "Approved back Identity Change" if identity else "Approved complete outfit reference pack",
        "evidence_ids": [a["asset_id"] for a in new_assets], "observations": [], "targets": targets,
        "preparation_id": preparation_id, "reference_pack_sha256": pack_sha,
        "validation_result": {"structure": "PASS", "visual_acceptance": "human-approved publication required", "evidence_statuses_changed": False}}
    bindings = _formal_bindings(root)
    bindings.update({c["path"]: c["sha256"] for c in selected.values()})
    bindings.update(record["plans"][required[0]]["bindings"])
    for source in record.get("sources", []):
        bindings[source["path"]] = source["sha256"]
        if source.get("original_path"):
            bindings[source["original_path"]] = source["original_sha256"]
    for item in files:
        target = inside(root, item["target_path"])
        item["before_hash"] = file_hash(target) if target.is_file() else None
        if item.get("asset_id") and target.exists():
            fail("PUBLICATION_TARGET_EXISTS", "New image paths must not overwrite existing assets.")
        bindings[str(target)] = item["before_hash"]
    return freeze({"schema_version": 1, "purpose": record["purpose"], "phase": "reference_pack_and_publication",
        "preparation_id": preparation_id, "calibration_id": cid, "identity_change": identity,
        "selection": {v: c["candidate_id"] for v, c in selected.items()}, "selected_pack": selected,
        "reference_pack_sha256": pack_sha, "files": files, "history": history, "calibration_targets": calibration_targets,
        "pack_review": record.get("pack_review"),
        "bindings": bindings, "record_sha256": file_hash(path / "preparation.yaml")})


def _validate(root: Path, pending_history: dict | None = None) -> dict:
    result = validate(root, pending_history=pending_history)
    if result["structure"] != "PASS":
        raise PublishError("Publication validation failed: " + json.dumps([x for x in result["issues"] if x["severity"] == "ERROR"], ensure_ascii=False))
    return {"structure": "PASS", "errors": 0, "warnings": result["summary"]["warnings"]}


def _publication_binding(manifest: dict, record: dict, root: Path, staging: Path, *, materialized: bool = True) -> None:
    """Bind the v3 transport to the exact human-approved publication preview."""
    preview = manifest["approved_preview"]
    if preview.get("preview_sha256") != digest({k: v for k, v in preview.items() if k != "preview_sha256"}):
        fail("PREPARATION_PLAN_STALE", "Publication preview changed.")
    approval = manifest["publication_confirmation"]
    if approval != record["approvals"]["publication"] or approval.get("preview_sha256") != preview["preview_sha256"] or record["publication_preview_sha256"] != preview["preview_sha256"]:
        fail("PREPARATION_CONFIRMATION_STALE", "Publication authorization does not bind this preparation.")
    expected = [{k: item[k] for k in ("target_path", "candidate_hash", "before_hash", "asset_id") if k in item} | {"staged_path": "candidate-files/" + item["target_path"]} for item in preview["files"]]
    actual = [{k: item[k] for k in ("target_path", "candidate_hash", "before_hash", "asset_id", "staged_path") if k in item} for item in manifest["files"]]
    if actual != expected or manifest["calibration_id"] != preview["calibration_id"] or manifest["calibration_targets"] != preview["calibration_targets"] or manifest["preparation_id"] != record["preparation_id"]:
        fail("PREPARATION_PLAN_STALE", "Publication targets or candidate hashes changed after acceptance.")
    cid = preview["calibration_id"]
    paths = {"history_path": f"calibration/history/{cid}.yaml", "completion_marker": f"calibration/history/{cid}.complete",
        "in_progress_marker": f"calibration/transactions/{cid}.publication_in_progress.json", "staged_history_path": "publication/history-candidate.yaml"}
    expected_history_hash = hashlib.sha256(yaml_bytes(preview["history"])).hexdigest()
    if any(manifest.get(k) != value for k, value in paths.items()) or manifest["history_candidate_hash"] != expected_history_hash:
        fail("PREPARATION_PLAN_STALE", "Publication history or completion paths changed.")
    history_file = inside(staging, paths["staged_history_path"])
    if materialized and (not history_file.is_file() or file_hash(history_file) != expected_history_hash):
        fail("PREPARATION_PLAN_STALE", "Staged History changed after preview.")
    expected_base = {str(Path(p).relative_to(root.resolve())).replace("\\", "/"): h for p, h in preview["bindings"].items() if Path(p).is_relative_to(root.resolve()) and "calibration/preparations/" not in Path(p).as_posix()}
    if manifest["base_hashes"] != expected_base:
        fail("PREPARATION_PLAN_STALE", "Publication drift guards changed.")
    allowed_journal = {item["target_path"]: (item["before_hash"], item["candidate_hash"]) for item in expected}
    allowed_journal[paths["history_path"]] = (None, expected_history_hash)
    allowed_journal[paths["completion_marker"]] = (None, hashlib.sha256((cid + os.linesep).encode("utf-8")).hexdigest())
    for item in manifest.get("write_journal", []):
        if allowed_journal.get(item["path"]) != (item["before_hash"], item["candidate_hash"]):
            fail("PUBLICATION_RECOVERY_INVALID", "Journal does not belong to the approved transaction.")


def _new_manifest(preview: dict, confirmation: dict, root: Path) -> dict:
    cid = preview["calibration_id"]
    return {"schema_version": 3, "calibration_id": cid, "calibration_targets": preview["calibration_targets"],
        "publication_authorized": False, "publication_state": "STAGING_IN_PROGRESS", "revalidation_status": "PENDING",
        "base_hashes": {str(Path(p).relative_to(root.resolve())).replace("\\", "/"): h for p, h in preview["bindings"].items() if Path(p).is_relative_to(root.resolve()) and "calibration/preparations/" not in Path(p).as_posix()},
        "files": [{k: item[k] for k in ("target_path", "candidate_hash", "before_hash", "asset_id") if k in item} | {"staged_path": "candidate-files/" + item["target_path"]} for item in preview["files"]],
        "staged_history_path": "publication/history-candidate.yaml", "history_candidate_hash": hashlib.sha256(yaml_bytes(preview["history"])).hexdigest(),
        "history_path": f"calibration/history/{cid}.yaml", "completion_marker": f"calibration/history/{cid}.complete",
        "in_progress_marker": f"calibration/transactions/{cid}.publication_in_progress.json", "preparation_id": preview["preparation_id"],
        "approved_preview": deepcopy(preview), "publication_confirmation": deepcopy(confirmation)}


def _finish_staging(root: Path, staging: Path, manifest: dict) -> dict:
    preview = manifest["approved_preview"]
    confirm(manifest["publication_confirmation"], preview)
    try:
        for item in preview["files"]:
            target = inside(staging, "candidate-files/" + item["target_path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if file_hash(target) != item["candidate_hash"]:
                    fail("PREPARATION_PLAN_STALE", "Staged candidate changed; preserve it for review.")
            elif "data" in item:
                target.write_bytes(yaml_bytes(item["data"]))
            elif "text" in item:
                target.write_bytes(item["text"].encode("utf-8"))
            else:
                shutil.copy2(item["source_path"], target)
            if file_hash(target) != item["candidate_hash"]:
                fail("PREPARATION_PLAN_STALE", "Candidate changed while staging.")
        history = staging / manifest["staged_history_path"]
        if history.exists() and file_hash(history) != manifest["history_candidate_hash"]:
            fail("PREPARATION_PLAN_STALE", "Preserve the changed staged History for review.")
        write(history, preview["history"])
        candidate_root = staging / "candidate-root"
        for directory in ("character", "variants", "runtime", "calibration/history"):
            shutil.copytree(root / directory, candidate_root / directory, dirs_exist_ok=True)
        shutil.copy2(root / "SKILL.md", candidate_root / "SKILL.md")
        for asset in load(root / "character/assets.yaml")["assets"]:
            source, target = inside(root, asset["path"]), inside(candidate_root, asset["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for item in manifest["files"]:
            target = inside(candidate_root, item["target_path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staging / item["staged_path"], target)
        write(candidate_root / manifest["history_path"], preview["history"])
        (candidate_root / manifest["completion_marker"]).write_text(preview["calibration_id"] + "\n", encoding="utf-8")
        manifest["candidate_validation"] = _validate(candidate_root)
        manifest.update(revalidation_status="PASS", publication_state="STAGED_VALIDATED_AWAITING_AUTHORIZATION")
    except Exception as exc:
        manifest.update(revalidation_status="FAIL", publication_state="STAGED_REVALIDATION_FAILED", failure=str(exc))
        raise
    finally:
        write(staging / "publish-manifest.yaml", manifest)
        write(staging / "calibration-lock.yaml", {"calibration_id": preview["calibration_id"], "targets": preview["calibration_targets"], "state": manifest["publication_state"]})
    return manifest


def stage_publication(preview: dict, confirmation: dict, *, root: Path) -> dict:
    confirm(confirmation, preview)
    pid = preview["preparation_id"]
    path = workspace(root, pid)
    if preview.get("phase") != "reference_pack_and_publication" or plan_publication(root=root, preparation_id=pid, selection=preview["selection"]) != preview:
        fail("PREPARATION_PLAN_STALE", "Pack, reviews or publication targets changed after preview.")
    blocked = conflicts(root, set(preview["calibration_targets"]), "begin-calibration")
    if blocked:
        fail("CALIBRATION_LOCKED", str(blocked))
    with locked(path):
        if file_hash(path / "preparation.yaml") != preview["record_sha256"]:
            fail("PREPARATION_PLAN_STALE", "Preparation changed before staging.")
        staging = inside(root, "calibration/staging/" + preview["calibration_id"])
        if staging.exists():
            fail("PUBLICATION_TARGET_EXISTS", "This preparation already owns a staging; use recovery.")
        record = load(path / "preparation.yaml")
        for candidate in record["candidates"]:
            if candidate["candidate_id"] in preview["selection"].values():
                candidate["user_accepted"] = True
        record.update(state="RECOVERY_REQUIRED", publication_staging=str(staging), publication_preview_sha256=preview["preview_sha256"], publication_preview=deepcopy(preview))
        record["approvals"]["publication"] = deepcopy(confirmation)
        write(path / "preparation.yaml", record)
        staging.mkdir(parents=True, exist_ok=False)
        manifest = _new_manifest(preview, confirmation, root)
        write(staging / "publish-manifest.yaml", manifest)
        write(staging / "calibration-lock.yaml", {"calibration_id": preview["calibration_id"], "targets": preview["calibration_targets"], "state": "STAGED_REVALIDATION_FAILED"})
        result = _finish_staging(root, staging, manifest)
        record["state"] = "PUBLICATION_STAGED"
        write(path / "preparation.yaml", record)
        return result


def publish_preparation(*, root: Path, preparation_id: str, fail_after: str | None = None) -> dict:
    path = workspace(root, preparation_id)
    with locked(path):
        record = load(path / "preparation.yaml")
        if record["state"] != "PUBLICATION_STAGED":
            fail("PREPARATION_STATE_INVALID", "A validated, human-accepted publication staging is required.")
        staging = Path(record["publication_staging"]).resolve()
        if not staging.is_relative_to((root / "calibration/staging").resolve()):
            fail("PREPARATION_PATH_INVALID", "Publication staging escapes this library.")
        manifest = load(staging / "publish-manifest.yaml")
        _publication_binding(manifest, record, root, staging)
        confirm(manifest["publication_confirmation"], manifest["approved_preview"])
        try:
            result = publish(root, staging, authorization=record["approvals"]["publication"],
                validate_written=lambda current, stage, history: _validate(current, history),
                validate_complete=lambda current, stage: _validate(current), fail_after=fail_after)
            record.update(state="PUBLISHED", calibration_id=result["calibration_id"], completed_at=utc())
            return result
        except Exception:
            record["state"] = "RECOVERY_REQUIRED"
            raise
        finally:
            write(path / "preparation.yaml", record)


def recover_publication(*, root: Path, preparation_id: str) -> dict:
    """Restore only known hashes, preserve snapshots and re-arm the same approval."""
    path = workspace(root, preparation_id)
    with locked(path):
        record = load(path / "preparation.yaml")
        staging = Path(record["publication_staging"]).resolve()
        if not staging.is_relative_to((root / "calibration/staging").resolve()):
            fail("PREPARATION_PATH_INVALID", "Recovery staging escapes this library.")
        if not (staging / "publish-manifest.yaml").is_file() and record.get("publication_preview"):
            staging.mkdir(parents=True, exist_ok=True)
            manifest = _new_manifest(record["publication_preview"], record["approvals"]["publication"], root)
            write(staging / "publish-manifest.yaml", manifest)
        else:
            manifest = load(staging / "publish-manifest.yaml")
        pending_staging = manifest["publication_state"] in {"STAGING_IN_PROGRESS", "STAGED_REVALIDATION_FAILED"}
        _publication_binding(manifest, record, root, staging, materialized=not pending_staging)
        blocked = [c for c in conflicts(root, set(manifest["calibration_targets"]), "recovery") if c["calibration_id"] != manifest["calibration_id"]]
        if blocked:
            fail("CALIBRATION_LOCKED", str(blocked))
        if pending_staging:
            result = _finish_staging(root, staging, manifest)
            record["state"] = "PUBLICATION_STAGED"
            write(path / "preparation.yaml", record)
            return result
        if manifest["publication_state"] == "COMPLETE":
            _validate(root)
            record.update(state="PUBLISHED", calibration_id=manifest["calibration_id"])
            write(path / "preparation.yaml", record)
            return manifest
        if manifest["publication_state"] not in {"RECOVERY_REQUIRED", "PUBLICATION_IN_PROGRESS", "AFTER_HASH_VALIDATED"}:
            fail("PUBLICATION_RECOVERY_INVALID", "No interrupted publication to recover.")
        for item in reversed(manifest.get("write_journal", [])):
            target = inside(root, item["path"])
            current = file_hash(target) if target.is_file() else None
            if current == item["before_hash"]:
                continue
            if current != item["candidate_hash"]:
                fail("PUBLICATION_RECOVERY_UNKNOWN_HASH", "Preserve the unexpected concurrent contents: " + item["path"])
            if item["before_hash"] is None:
                target.unlink()
            else:
                backup = inside(staging, "publication/rollback/" + item["path"])
                if not backup.is_file() or file_hash(backup) != item["before_hash"]:
                    fail("PUBLICATION_RECOVERY_INVALID_BACKUP", item["path"])
                replace_from_source(backup, target, manifest["calibration_id"])
        check_preview(manifest["approved_preview"])
        previous = deepcopy(manifest.get("write_journal", []))
        rollback = inside(staging, "publication/rollback")
        if rollback.exists():
            saved = inside(staging, "publication/rollback-saved-" + str(len(manifest.get("recovery_events", []))))
            rollback.rename(saved)
        inside(root, manifest["in_progress_marker"]).unlink(missing_ok=True)
        manifest.setdefault("recovery_events", []).append({"at": utc(), "restored_journal": previous})
        manifest.update(publication_authorized=False, publication_state="STAGED_VALIDATED_AWAITING_AUTHORIZATION", write_journal=[], rollback_status="PASS", revalidation_status="PASS")
        for item in manifest["files"]:
            item.pop("after_hash", None)
            item.pop("publication_status", None)
            item.pop("backup_path", None)
        write(staging / "publish-manifest.yaml", manifest)
        write(staging / "calibration-lock.yaml", {"calibration_id": manifest["calibration_id"], "targets": manifest["calibration_targets"], "state": manifest["publication_state"]})
        record["state"] = "PUBLICATION_STAGED"
        write(path / "preparation.yaml", record)
        return manifest


def release_staging_for_revision(*, root: Path, record: dict) -> None:
    """A newly confirmed design may retire a staging with no formal changes."""
    staging = Path(record["publication_staging"]).resolve()
    if not staging.is_relative_to((root / "calibration/staging").resolve()):
        fail("PREPARATION_PATH_INVALID", "Revision staging escapes this library.")
    manifest = load(staging / "publish-manifest.yaml")
    _publication_binding(manifest, record, root, staging, materialized=False)
    if manifest["publication_state"] == "COMPLETE" or inside(root, manifest["history_path"]).exists() or inside(root, manifest["completion_marker"]).exists():
        fail("PREPARATION_STATE_INVALID", "Published outfits require a new Variant preparation.")
    for item in manifest.get("write_journal", []):
        target = inside(root, item["path"])
        if (file_hash(target) if target.is_file() else None) != item["before_hash"]:
            fail("PUBLICATION_RECOVERY_REQUIRED", "Restore the interrupted formal writes before changing the design.")
    if inside(root, manifest["in_progress_marker"]).exists():
        fail("PUBLICATION_RECOVERY_REQUIRED", "Recover the active formal transaction before changing the design.")
    manifest.update(publication_state="CANCELLED", publication_authorized=False, cancelled_at=utc(), cancellation_reason="New complete design/main preview explicitly confirmed")
    write(staging / "publish-manifest.yaml", manifest)
    write(staging / "calibration-lock.yaml", {"calibration_id": manifest["calibration_id"], "targets": manifest["calibration_targets"], "state": "CANCELLED"})
    record.setdefault("events", []).append({"event": "publication_retired", "calibration_id": manifest["calibration_id"], "at": utc()})
    for key in ("publication_staging", "publication_preview", "publication_preview_sha256"):
        record.pop(key, None)
    record["approvals"].pop("publication", None)
    record["next_calibration_id"] = new_id("cal")
