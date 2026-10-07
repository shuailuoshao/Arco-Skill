"""Metadata-only, hash-guarded publication for the approved split references."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import shutil

import yaml
from check_calibration_lock import conflicts
from publication_v3 import publish, write
from publish_calibration import sha256, PublishError
from validate_library import validate

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = ("character/identity.yaml", "character/expressions.yaml", "variants/index.yaml")
FACELESS = {"casual-outfit-open-arms-no-horns-evidence", "casual-outfit-crossed-arms-evidence", "casual-outfit-raised-fists-evidence"}


def metadata(asset):
    kind = asset.get("asset_type")
    profiles = ["portrait", "upper_body", "full_body"]
    variant_fields = ["variant.visible_headwear_accessories", "variant.upper_body_outfit", "variant.full_outfit", "variant.footwear"]
    if "expression_evidence" in asset.get("roles", []):
        roles, fields = ["face_reference"], ["eyes", "face"]
        inherit = ["face", "eyes"]
        exclude = ["hair", "body_proportions", "outfit", "pose", "lighting", "scene", "style", "expression"]
    elif kind == "body_base":
        roles, fields = ["identity_reference"], ["identity", "hair", "face", "body.upper", "body.full"]
        profiles = ["upper_body", "full_body"]
        inherit = ["identity", "hair", "body_proportions"]
        exclude = ["eyes", "outfit", "expression", "pose", "scene", "lighting", "style"]
    else:
        roles = ["identity_reference", "outfit_reference"]
        fields = ["identity", "hair", "face", "body.upper", "body.full", *variant_fields]
        inherit = ["identity", "hair", "face", "outfit"]
        exclude = ["eyes", "expression", "pose", "scene", "lighting", "style"]
    return {"priority": "primary" if asset["asset_id"] == "casual-outfit-open-arms-no-horns-evidence" or "expression_evidence" in asset.get("roles", []) else "secondary",
            "supported_roles": roles, "preferred_for": profiles,
            "excluded_for": [profile for profile in ["portrait", "upper_body", "full_body", "back_view"] if profile not in profiles],
            "coverage": {"profiles": profiles, "visible_fields": fields,
                         "view_angles": [asset["view_angle"]], "occluded_fields": []},
            "inheritance": {**{key: "inherit" for key in inherit}, **{key: "do_not_inherit" for key in exclude}}}


def candidate_assets(original, cid):
    result = deepcopy(original)
    changes = {}
    for asset in result["assets"]:
        enabled = "expression_evidence" in asset.get("roles", []) or asset.get("asset_type") == "body_base" or asset["asset_id"] in FACELESS
        disabled = asset.get("asset_type") == "full_composite" or asset["asset_id"] == "identity-p01-crop"
        if not enabled and not disabled:
            continue
        before = {key: deepcopy(asset.get(key)) for key in ("can_be_generation_reference", "generation_reference", "purpose_note_zh")}
        asset["can_be_generation_reference"] = enabled
        if enabled:
            asset["generation_reference"] = metadata(asset)
            asset["purpose_note_zh"] = "获准作为分离生成参考；仅继承合同指定职责，不继承原图姿势、表情或渲染。"
        else:
            asset.pop("generation_reference", None)
            asset["purpose_note_zh"] = "保留官方完整立绘证据；默认生成改用已批准的分离图层。"
        after = {key: deepcopy(asset.get(key)) for key in before}
        changes[asset["asset_id"]] = {"before": before, "after": after}
    result["revision"] += 1
    result["last_calibration_id"] = cid
    return result, changes


def assert_metadata_only(before, after):
    allowed = {"can_be_generation_reference", "generation_reference", "purpose_note_zh"}
    if after["revision"] != before["revision"] + 1 or len(after["assets"]) != len(before["assets"]):
        raise PublishError("Asset revision/set changed unexpectedly")
    for old, new in zip(before["assets"], after["assets"], strict=True):
        if {key: value for key, value in old.items() if key not in allowed} != {key: value for key, value in new.items() if key not in allowed}:
            raise PublishError("Non-permission asset metadata changed: " + old["asset_id"])
    excluded = {"revision", "last_calibration_id", "assets"}
    if {key: value for key, value in before.items() if key not in excluded} != {key: value for key, value in after.items() if key not in excluded}:
        raise PublishError("Unexpected registry change")


def ensure_pass(result):
    if result["structure"] != "PASS":
        raise PublishError(json.dumps(result["issues"], ensure_ascii=False))
    return {"structure": result["structure"], "summary": result["summary"]}


def create(root=ROOT):
    root = root.resolve()
    if conflicts(root, {"character.assets"}, "publication"):
        raise PublishError("An active calibration transaction blocks publication")
    original = yaml.safe_load((root / "character/assets.yaml").read_text(encoding="utf-8"))
    cid = "cal-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    staging = root / "calibration/staging" / cid
    candidate = staging / "candidate-root"
    candidate.mkdir(parents=True)
    # Only validator inputs are copied; generation outputs and experiments are
    # excluded, and formal/staging image paths retain the registry structure.
    for directory in ("character", "variants", "runtime", "calibration/history"):
        shutil.copytree(root / directory, candidate / directory)
    shutil.copy2(root / "SKILL.md", candidate / "SKILL.md")
    base_hashes = {rel: sha256(root / rel) for rel in (*PROTECTED, "character/assets.yaml")}
    for asset in original["assets"]:
        rel = asset["path"]
        source = root / rel
        target = candidate / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        base_hashes[rel] = sha256(source)
    updated, changes = candidate_assets(original, cid)
    assert_metadata_only(original, updated)
    write(candidate / "character/assets.yaml", updated)
    history = {"schema_version": 1, "calibration_id": cid, "user_confirmed": True,
               "knowledge_change": False, "reason": "User-approved split generation reference permissions; no Identity, Expression or Variant fact changes.",
               "evidence_ids": list(changes), "observations": [], "validation_result": {"structure": "PASS"},
               "contract_changes": changes,
               "targets": [{"entity_ref": "character.assets", "target_type": "asset_generation_contract", "target_id": "split-reference-policy",
                            "revision_before": original["revision"], "revision_after": updated["revision"],
                            "changed_fields": ["revision", "last_calibration_id", "assets.generation_permissions"],
                            "before": {"revision": original["revision"], "last_calibration_id": original["last_calibration_id"]},
                            "after": {"revision": updated["revision"], "last_calibration_id": cid}}]}
    write(staging / "history-draft.yaml", history)
    marker_rel = f"calibration/transactions/{cid}.publication_in_progress.json"
    marker = candidate / marker_rel
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"calibration_id": cid,
        "pending_history_sha256": __import__("hashlib").sha256(json.dumps(history, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "candidate_hashes": {"character/assets.yaml": sha256(candidate / "character/assets.yaml")}}), encoding="utf-8")
    ensure_pass(validate(candidate, pending_history=history))
    write(staging / "calibration-lock.yaml", {"calibration_id": cid, "targets": ["character.assets"], "state": "STAGED_VALIDATED_AWAITING_AUTHORIZATION"})
    manifest = {"schema_version": 3, "calibration_id": cid, "calibration_targets": ["character.assets"],
                "publication_authorized": False, "publication_state": "STAGED_VALIDATED_AWAITING_AUTHORIZATION",
                "revalidation_status": "PASS", "base_hashes": base_hashes,
                "base_state": {"asset_index_revision": original["revision"]},
                "files": [{"target_path": "character/assets.yaml", "staged_path": "candidate-root/character/assets.yaml",
                           "before_hash": base_hashes["character/assets.yaml"], "candidate_hash": sha256(candidate / "character/assets.yaml")}],
                "staged_history_path": "history-draft.yaml", "history_candidate_hash": sha256(staging / "history-draft.yaml"),
                "history_path": f"calibration/history/{cid}.yaml", "completion_marker": f"calibration/history/{cid}.complete",
                "in_progress_marker": marker_rel}
    write(staging / "publish-manifest.yaml", manifest)
    return staging


def publish_permissions(staging, authorization_text, root=ROOT):
    def written(current_root, current_staging, history):
        before = yaml.safe_load((current_staging / "publication/rollback/character/assets.yaml").read_text(encoding="utf-8"))
        after = yaml.safe_load((current_root / "character/assets.yaml").read_text(encoding="utf-8"))
        assert_metadata_only(before, after)
        manifest = yaml.safe_load((current_staging / "publish-manifest.yaml").read_text(encoding="utf-8"))
        for relative in PROTECTED:
            if sha256(current_root / relative) != manifest["base_hashes"][relative]:
                raise PublishError("Protected facts changed: " + relative)
        ensure_pass(validate(current_root, pending_history=history))
    result = publish(root, staging, authorization={"user_confirmed": True, "user_request": authorization_text},
                     validate_written=written, validate_complete=lambda current_root, _: ensure_pass(validate(current_root)))
    result["state"] = "complete"
    write(staging / "publish-manifest.yaml", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--authorization-text")
    options = parser.parse_args()
    if options.publish and not options.authorization_text:
        parser.error("--publish requires the explicit user's authorization text")
    staged = create()
    if options.publish:
        publish_permissions(staged, options.authorization_text)
    print(staged)
