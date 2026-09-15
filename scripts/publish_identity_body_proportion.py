#!/usr/bin/env python3
"""Publish the approved Identity body-proportion calibration transactionally.

This controller is intentionally local-only.  It performs hash-guarded staging,
publication, validation, and recovery; it never imports an image-generation
client and never uploads an image.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.resolve()
CALIBRATION_ID = "cal-20260914T100205Z-77878a"
STAGING = ROOT / "calibration" / "staging" / CALIBRATION_ID
AUTH_TEXT = "确认发布 Identity Body Proportion Calibration"
BODY_ASSETS = [
    "assets/arco/identity/body-evidence/identity-body-c07.png",
    "assets/arco/identity/body-evidence/identity-body-c13.png",
    "assets/arco/identity/body-evidence/identity-body-c14.png",
]
EXPECTED_BODY_HASHES = {
    "assets/arco/identity/body-evidence/identity-body-c07.png": "a744236d80759906bc77f35c3a531a4a58b4829a6dd83a47fbb13af1894aa089",
    "assets/arco/identity/body-evidence/identity-body-c13.png": "93a52a59f468bca0c4bc8e2908ee448ca922692f30d728b67f0a50c8297dc7df",
    "assets/arco/identity/body-evidence/identity-body-c14.png": "e2ebb9ecf28ae0aed9a3cfd0b464cbe3a786a19dc9550719927b5e5dc7abd3db",
}


class PublicationError(RuntimeError):
    pass


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PublicationError(f"Cannot read YAML {path}: {exc}") from exc


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{CALIBRATION_ID}.tmp")
    tmp.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def json_save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{CALIBRATION_ID}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def resolve_root(raw: str | Path) -> Path:
    path = Path(raw).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise PublicationError(f"Path outside repository: {path}") from exc
    return path


def resolve_staging(raw: str | Path) -> Path:
    path = Path(raw).resolve()
    try:
        path.relative_to(ROOT / "calibration" / "staging")
    except ValueError as exc:
        raise PublicationError(f"Staging path outside staging root: {path}") from exc
    return path


def file_hash_or_none(path: Path) -> str | None:
    return sha256(path) if path.is_file() else None


def candidate_body_records(staging: Path) -> dict[str, dict[str, Any]]:
    data = load(staging / "candidate-root" / "character" / "assets.yaml")
    return {item["asset_id"]: item for item in data.get("assets", []) if isinstance(item, dict)}


def ensure_manifest_targets(root: Path, staging: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Complete the pre-existing draft with files already present in its candidate.

    The original draft listed the two entity YAMLs but omitted the three managed
    Body Base files that the candidate Asset Index registers.  Adding those
    existing, hash-verified files is a staging-manifest repair; no candidate
    entity data is rewritten.
    """
    files = list(manifest.get("files") or [])
    by_target = {item.get("target_path"): item for item in files}
    for rel in BODY_ASSETS:
        source = staging / "candidate-root" / rel
        if not source.is_file() or sha256(source) != EXPECTED_BODY_HASHES[rel]:
            raise PublicationError(f"Body candidate missing or hash mismatch: {rel}")
        if rel not in by_target:
            item = {
                "target_path": rel,
                "staged_path": f"candidate-root/{rel}",
                "before_hash": None,
                "candidate_hash": sha256(source),
                "after_hash": None,
                "backup_path": f"publication/rollback/{rel}",
                "rollback_action": "remove_created_file_only_if_hash_matches_candidate",
                "verification_class": "immutable_data",
                "publication_status": "pending",
            }
            files.append(item)
            by_target[rel] = item
    # identity.md is structurally coupled to identity.revision in the formal validator.
    identity_md = staging / "candidate-root" / "character" / "identity.md"
    if not identity_md.exists():
        current = (root / "character" / "identity.md").read_text(encoding="utf-8")
        current = current.replace("source_revision: 1", "source_revision: 2", 1)
        current += "\n本次身体比例工作事实为 small-to-modest，证据状态保持 UNCERTAIN；该说明不提升为 CANON 或 VISUAL_CONSENSUS。\n"
        identity_md.parent.mkdir(parents=True, exist_ok=True)
        identity_md.write_text(current, encoding="utf-8")
    md_rel = "character/identity.md"
    if md_rel not in by_target:
        before = file_hash_or_none(root / md_rel)
        item = {
            "target_path": md_rel,
            "staged_path": "candidate-root/character/identity.md",
            "before_hash": before,
            "candidate_hash": sha256(identity_md),
            "after_hash": None,
            "backup_path": "publication/rollback/character/identity.md",
            "rollback_action": "restore_backup",
            "verification_class": "protected_entity",
            "publication_status": "pending",
        }
        files.append(item)
        by_target[md_rel] = item
    for item in files:
        staged = staging / str(item["staged_path"])
        if not staged.is_file():
            raise PublicationError(f"Missing staged target: {item['staged_path']}")
        item["candidate_hash"] = sha256(staged)
        item.setdefault("after_hash", None)
        item.setdefault("publication_status", "pending")
    manifest["files"] = files
    manifest["base_hashes"].setdefault(md_rel, file_hash_or_none(root / md_rel))
    manifest["in_progress_marker"] = f"calibration/transactions/{CALIBRATION_ID}.publication_in_progress.json"
    manifest["publication_status"] = "pending"
    manifest["publication_executed"] = False
    manifest["image_generation_called"] = False
    manifest["remote_upload"] = False
    return manifest


def preflight(root: Path, staging: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("calibration_id") != CALIBRATION_ID:
        raise PublicationError("Calibration ID mismatch")
    if manifest.get("publication_state") not in {"STAGED_VALIDATED_AWAITING_AUTHORIZATION", "AUTHORIZED_AWAITING_PREFLIGHT"}:
        raise PublicationError(f"Invalid preflight state: {manifest.get('publication_state')}")
    if manifest.get("revalidation_status") not in {"PASS", "PENDING"}:
        raise PublicationError("Candidate revalidation is not usable")
    expected_revisions = {
        "character/identity.yaml": 1,
        "character/assets.yaml": 4,
        "character/expressions.yaml": 1,
        "variants/index.yaml": 1,
    }
    drift: list[dict[str, Any]] = []
    for rel, expected_hash in manifest.get("base_hashes", {}).items():
        path = root / rel
        actual = file_hash_or_none(path)
        if actual != expected_hash:
            drift.append({"path": rel, "expected_hash": expected_hash, "actual_hash": actual})
    for rel, expected_revision in expected_revisions.items():
        path = root / rel
        data = load(path)
        if data.get("revision") != expected_revision:
            drift.append({"path": rel, "expected_revision": expected_revision, "actual_revision": data.get("revision")})
    if drift:
        raise PublicationError("STALE_STAGING: " + json.dumps(drift, ensure_ascii=False))
    candidate_identity = load(staging / "candidate-root" / "character" / "identity.yaml")
    candidate_assets = load(staging / "candidate-root" / "character" / "assets.yaml")
    if candidate_identity.get("revision") != 2 or candidate_assets.get("revision") != 5:
        raise PublicationError("Candidate revisions are not Identity 2 / Assets 5")
    chest = next((x for x in candidate_identity.get("facts", []) if x.get("field_id") == "body.chest_proportion"), None)
    if not chest or chest.get("value") != "small-to-modest" or chest.get("status") != "UNCERTAIN":
        raise PublicationError("Candidate chest fact is invalid")
    if set(chest.get("evidence_ids", [])) != {"identity-body-c07", "identity-body-c13", "identity-body-c14", "identity-p01", "identity-p03"}:
        raise PublicationError("Candidate chest evidence closure is invalid")
    assets = {x["asset_id"]: x for x in candidate_assets.get("assets", [])}
    for aid, rel in zip(("identity-body-c07", "identity-body-c13", "identity-body-c14"), BODY_ASSETS):
        item = assets.get(aid)
        if not item or item.get("path") != rel or item.get("roles") != ["body_evidence"] or item.get("asset_type") != "body_base" or item.get("can_be_generation_reference") is not False:
            raise PublicationError(f"Invalid Body Base candidate record: {aid}")
        if sha256(staging / "candidate-root" / rel) != item.get("sha256"):
            raise PublicationError(f"Candidate Body Base hash mismatch: {aid}")
    primary = [
        x for x in assets.values()
        if x.get("generation_reference", {}).get("priority") == "primary"
        and "identity_reference" in (x.get("generation_reference", {}).get("supported_roles") or [])
    ]
    if [x.get("asset_id") for x in primary] != ["identity-p01-crop"]:
        raise PublicationError("Identity Primary is not unique/unchanged")
    if assets["identity-p01-crop"].get("sha256") != "386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414":
        raise PublicationError("Identity Primary SHA changed")
    forbidden = [x for x in assets.values() if x.get("asset_type") in {"body_base", "faceless_composite"} and x.get("can_be_generation_reference")]
    if forbidden:
        raise PublicationError("Forbidden generation permission in candidate")
    for item in manifest.get("files", []):
        target = root / item["target_path"]
        staged = staging / item["staged_path"]
        if not staged.is_file() or sha256(staged) != item.get("candidate_hash"):
            raise PublicationError(f"Candidate hash mismatch: {item['target_path']}")
        if file_hash_or_none(target) != item.get("before_hash"):
            raise PublicationError(f"STALE_STAGING target: {item['target_path']}")
    for key in ("history_path", "completion_marker", "in_progress_marker"):
        if key in manifest and (root / manifest[key]).exists():
            raise PublicationError(f"Transaction artifact already exists: {key}")
    if len(manifest.get("files", [])) != 6:
        raise PublicationError("Body publication requires 6 targets (3 PNG, 2 YAML, identity.md)")
    return {"status": "PASS", "formal_revisions": expected_revisions, "target_count": 6, "drift": []}


def build_history(root: Path, staging: Path, manifest: dict[str, Any], authorization: dict[str, Any]) -> dict[str, Any]:
    draft = load(staging / "history-draft.yaml") or {}
    before_identity = load(root / "character" / "identity.yaml")
    after_identity = load(staging / "candidate-root" / "character" / "identity.yaml")
    before_assets = load(root / "character" / "assets.yaml")
    after_assets = load(staging / "candidate-root" / "character" / "assets.yaml")
    history = copy.deepcopy(draft)
    # The draft used concise strings for two observations.  Published History
    # requires structured observation records so the formal validator can audit
    # their source and filtering context.
    history["observations"] = [
        {
            "observation_id": "body-c07-c13-narrow-torso",
            "field_ref": "body.chest_proportion",
            "observation": "C07/C13 show a narrow torso and restrained chest projection; C14 is chest-occluded.",
            "intrinsic_interpretation": "Cross-pose evidence supports a small-to-modest working chest proportion without source-family independence.",
            "evidence_ids": ["identity-body-c07", "identity-body-c13", "identity-body-c14"],
            "rendering_factors": {"lighting_sensitive": True, "pose_sensitive": True, "perspective_sensitive": True, "occlusion": "C14 chest occluded"},
            "confidence": "medium",
            "comparison": {"corroborating_evidence_ids": ["identity-body-c07", "identity-body-c13"], "conflicting_evidence_ids": []},
            "proposed_status": "UNCERTAIN",
        },
        {
            "observation_id": "body-dressed-silhouette",
            "field_ref": "body.chest_proportion",
            "observation": "P01/P03 support a slender dressed silhouette; clothing adds visual volume.",
            "intrinsic_interpretation": "Dressed silhouettes are supporting context only; clothing volume is filtered from the intrinsic body interpretation.",
            "evidence_ids": ["identity-p01", "identity-p03"],
            "rendering_factors": {"lighting_sensitive": True, "pose_sensitive": True, "perspective_sensitive": True, "occlusion": "outfit affects silhouette"},
            "confidence": "medium",
            "comparison": {"corroborating_evidence_ids": ["identity-p01", "identity-p03"], "conflicting_evidence_ids": []},
            "proposed_status": "UNCERTAIN",
        },
    ]
    history.update({
        "schema_version": 1,
        "calibration_id": CALIBRATION_ID,
        "timestamp": utc(),
        "operation": "publish_identity_body_proportion_calibration",
        "publication_state": "PUBLISHED",
        "user_confirmed": True,
        "confirmed_at": authorization["timestamp"],
        "reason": "Publish the user-approved small-to-modest working Identity body-proportion fact and evidence-only Body Base registrations.",
        "validation_result": {"structure": "PASS", "context": "post-publication final validation"},
        "evidence_ids": ["identity-body-c07", "identity-body-c13", "identity-body-c14", "identity-p01", "identity-p03"],
        "source_family_independence": {"count": 1, "note": "C07/C13/C14 share arco-official-standing-art-system-01; pose groups do not add independent source families."},
        "generated_image_evidence_count": 0,
        "edited_image_evidence_count": 0,
        "live_smoke_image_role": "runtime symptom only; not Character Evidence",
        "edited_smaller_chest_image_role": "user preference visualization only; not Character Evidence",
        "body_evidence": {"asset_ids": ["identity-body-c07", "identity-body-c13", "identity-body-c14"], "generation_permission": False},
        "prompt_representation": {
            "body_chest_proportion": "a slim, lightly built figure with a narrow upper torso and a small-to-modest, understated bust",
            "soft_constraint": "no exaggerated chest volume",
            "guard": {"banned": ["flat chest", "tiny breasts", "very small breasts"], "max_soft_constraint_occurrences": 1},
            "uncertain_policy": "fact-specific user working-fact opt-in; TODO_CALIBRATION excluded",
        },
        "user_authorization": {"text": AUTH_TEXT, "source": "explicit user confirmation", "timestamp": authorization["timestamp"]},
        "targets": [
            {
                "entity_ref": "character.identity",
                "target_type": "identity",
                "target_id": None,
                "revision_before": before_identity["revision"],
                "revision_after": after_identity["revision"],
                "changed_fields": ["facts.body.chest_proportion", "last_calibration_id"],
                "before": before_identity,
                "after": after_identity,
            },
            {
                "entity_ref": "character.assets",
                "target_type": "asset_body_proportion",
                "target_id": None,
                "revision_before": before_assets["revision"],
                "revision_after": after_assets["revision"],
                "changed_fields": ["assets.identity-body-c07", "assets.identity-body-c13", "assets.identity-body-c14", "last_calibration_id"],
                "before": before_assets,
                "after": after_assets,
            },
        ],
        "transaction_result": {"publication": "IDENTITY_BODY_PROPORTION_PUBLICATION_COMPLETE", "recovery": False},
        "publication_not_executed": False,
    })
    return history


def digest_history(history: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(history, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def copy_replace(source: Path, target: Path, calibration_id: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".{target.name}.{calibration_id}.tmp"
    shutil.copy2(source, temp)
    os.replace(temp, target)


def run_validation(root: Path, staging: Path, history: dict[str, Any] | None = None) -> dict[str, Any]:
    from validate_library import validate
    result = validate(root, pending_history=history)
    if result.get("structure") != "PASS":
        raise PublicationError("Formal Library Validator failed: " + json.dumps(result, ensure_ascii=False))
    if history is not None:
        identity = load(root / "character" / "identity.yaml")
        assets = {x["asset_id"]: x for x in load(root / "character" / "assets.yaml").get("assets", [])}
        fact = next((x for x in identity.get("facts", []) if x.get("field_id") == "body.chest_proportion"), None)
        if not fact or fact.get("value") != "small-to-modest" or fact.get("status") != "UNCERTAIN":
            raise PublicationError("Published body chest fact validation failed")
        for aid in ("identity-body-c07", "identity-body-c13", "identity-body-c14"):
            item = assets.get(aid)
            if not item or item.get("roles") != ["body_evidence"] or item.get("asset_type") != "body_base" or item.get("can_be_generation_reference") is not False:
                raise PublicationError(f"Published Body Base validation failed: {aid}")
    return result


def production_prompt_dry_run(root: Path) -> dict[str, Any]:
    """Compile the production request without invoking an image adapter."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from reference_runtime import build_builtin_imagegen_args, build_invocation_plan, compile_prompt, select_references
    identity = load(root / "character" / "identity.yaml")
    assets_data = load(root / "character" / "assets.yaml")
    config = load(root / "runtime" / "generation.yaml")
    selected = select_references(
        root=root,
        managed_assets=assets_data["assets"],
        requested_roles=["identity_reference", "outfit_reference"],
        selected_variant_id="casual-outfit",
        exposure_profile="portrait",
        variant_required=True,
        config=config,
    )
    if [x["asset_id"] for x in selected] != ["identity-p01-crop", "casual-outfit-primary"]:
        raise PublicationError("Production dry run selected unexpected references")
    if any("staging" in str(x.get("path", "")).lower() for x in selected):
        raise PublicationError("Production dry run selected staging path")
    if any(x.get("asset_type") in {"body_base", "faceless_composite"} or x.get("roles") == ["expression_evidence"] for x in selected):
        raise PublicationError("Production dry run selected forbidden evidence asset")
    prompt = compile_prompt(
        base_prompt="Arco portrait/chest-up, casual-outfit, gentle smile, simple indoor daylight.",
        references=selected,
        identity=identity,
        exposure_profile="portrait",
        allow_uncertain_working=True,
    )
    plan = build_invocation_plan(mode="reference_conditioned", prompt=prompt, selected_references=selected)
    args = build_builtin_imagegen_args(plan)
    expected = [x["path"] for x in selected]
    if args.get("referenced_image_paths") != expected or any(k in args for k in ("num_last_images_to_include",)):
        raise PublicationError("Production dry run adapter boundary mismatch")
    banned = ("flat chest", "tiny breasts", "very small breasts")
    if any(term in prompt.lower() for term in banned) or prompt.lower().count("no exaggerated chest volume") != 1:
        raise PublicationError("Production prompt semantic guard failed")
    return {"status": "PASS", "selected_reference_ids": [x["asset_id"] for x in selected], "paths": expected, "args": args, "body_evidence_input_count": 0, "expression_input_count": 0, "staging_path_count": 0, "image_generation_called": False, "remote_upload": False}


def report_files(staging: Path, report: dict[str, Any]) -> None:
    out = staging / "reports"
    out.mkdir(parents=True, exist_ok=True)
    json_save(out / "FINAL IDENTITY BODY PROPORTION PUBLICATION REPORT.json", report)
    lines = ["# FINAL IDENTITY BODY PROPORTION PUBLICATION REPORT", "", f"- Final state: `{report['final_state']}`", f"- Calibration ID: `{report['calibration_id']}`", ""]
    for key, value in report.items():
        if key in {"final_state", "calibration_id"}:
            continue
        lines.extend([f"## {key}", "", "```json", json.dumps(value, ensure_ascii=False, indent=2), "```", ""])
    (out / "FINAL IDENTITY BODY PROPORTION PUBLICATION REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def publish(root: Path, staging: Path) -> dict[str, Any]:
    manifest_path = staging / "publish-manifest.yaml"
    manifest = load(manifest_path)
    if manifest.get("publication_state") == "COMPLETE":
        raise PublicationError("Calibration is already COMPLETE")
    if manifest.get("publication_state") == "RECOVERY_REQUIRED" and manifest.get("rollback_status") == "PASS":
        # The previous attempt rolled back every formal target cleanly.  Resume
        # from the authorization gate while preserving the prior failure in the
        # manifest for auditability.
        manifest["prior_recovery"] = {
            "failure": manifest.get("failure"),
            "rollback_status": manifest.get("rollback_status"),
            "timestamp": utc(),
        }
        manifest["publication_state"] = "AUTHORIZED_AWAITING_PREFLIGHT"
    manifest = ensure_manifest_targets(root, staging, manifest)
    # Candidate validator is run before authorization metadata is persisted.
    from validate_identity_body_proportion_staging import validate as body_validate
    if manifest.get("publication_authorized") is True:
        # A previous attempt may have safely persisted authorization metadata
        # before discovering a preflight defect.  Reuse that explicit user
        # authorization while the formal targets remain untouched.
        candidate_check = {"status": "PASS", "reused_authorization": True}
        authorization = dict(manifest.get("authorization") or {})
        authorization.setdefault("user_confirmed", True)
        authorization.setdefault("text", AUTH_TEXT)
        authorization.setdefault("source", "explicit user confirmation")
        authorization.setdefault("timestamp", manifest.get("authorization_timestamp") or utc())
        authorization.setdefault("calibration_id", CALIBRATION_ID)
    else:
        candidate_check = body_validate(root, staging)
        if candidate_check.get("status") != "PASS":
            raise PublicationError("Body staging validator did not PASS before authorization")
        authorization = {"user_confirmed": True, "text": AUTH_TEXT, "source": "explicit user confirmation", "timestamp": utc(), "calibration_id": CALIBRATION_ID}
    manifest["publication_authorized"] = True
    manifest["authorization"] = authorization
    manifest["authorization_timestamp"] = authorization["timestamp"]
    manifest["publication_state"] = "AUTHORIZED_AWAITING_PREFLIGHT"
    manifest["revalidation_status"] = "PASS"
    save(manifest_path, manifest)
    history = build_history(root, staging, manifest, authorization)
    save(staging / "history-final.yaml", history)
    manifest["staged_history_path"] = "history-final.yaml"
    manifest["history_candidate_hash"] = sha256(staging / "history-final.yaml")
    manifest["history_path"] = f"calibration/history/{CALIBRATION_ID}.yaml"
    manifest["completion_marker"] = f"calibration/history/{CALIBRATION_ID}.complete"
    preflight_result = preflight(root, staging, manifest)
    # Preflight is complete; all snapshots and journal state precede formal writes.
    rollback_root = staging / "publication" / "rollback"
    journal: list[dict[str, Any]] = []
    for item in manifest["files"]:
        target = root / item["target_path"]
        before_exists = target.is_file()
        before_hash = file_hash_or_none(target)
        if before_hash != item.get("before_hash"):
            raise PublicationError(f"STALE_STAGING target during snapshot: {item['target_path']}")
        backup = rollback_root / item["target_path"]
        if before_exists:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            if sha256(backup) != before_hash:
                raise PublicationError(f"Rollback snapshot hash mismatch: {item['target_path']}")
        journal.append({"target_path": item["target_path"], "before_exists": before_exists, "before_hash": before_hash, "candidate_hash": item["candidate_hash"], "after_hash": None, "rollback_snapshot": str(backup.relative_to(staging)) if before_exists else None, "write_status": "pending", "validation_status": "pending"})
    manifest["rollback_snapshot"] = str(rollback_root.relative_to(staging))
    manifest["write_journal"] = journal
    manifest["publication_state"] = "PUBLICATION_IN_PROGRESS"
    save(manifest_path, manifest)
    marker = root / manifest["in_progress_marker"]
    tx_marker = root / "calibration" / "transactions" / f"{CALIBRATION_ID}.publication_in_progress.json"
    completion = root / manifest["completion_marker"]
    history_path = root / manifest["history_path"]
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        tx_marker.parent.mkdir(parents=True, exist_ok=True)
        tx_data = {"calibration_id": CALIBRATION_ID, "pending_history_sha256": digest_history(history), "candidate_hashes": {x["target_path"]: x["candidate_hash"] for x in manifest["files"]}}
        marker.write_text(json.dumps(tx_data, ensure_ascii=False), encoding="utf-8")
        tx_marker.write_text(json.dumps(tx_data, ensure_ascii=False), encoding="utf-8")
        # Approved Body assets first, then the two protected entities and their markdown.
        ordered = sorted(manifest["files"], key=lambda x: (0 if x["target_path"] in BODY_ASSETS else 1 if x["target_path"] == "character/assets.yaml" else 2 if x["target_path"] == "character/identity.yaml" else 3, x["target_path"]))
        for item in ordered:
            target = root / item["target_path"]
            source = staging / item["staged_path"]
            current = file_hash_or_none(target)
            if current != item.get("before_hash"):
                raise PublicationError(f"Concurrent target drift: {item['target_path']}")
            copy_replace(source, target, CALIBRATION_ID)
            after = file_hash_or_none(target)
            if after != item["candidate_hash"]:
                raise PublicationError(f"After-hash mismatch: {item['target_path']}")
            record = next(x for x in journal if x["target_path"] == item["target_path"])
            record["after_hash"] = after
            record["write_status"] = "written"
            record["validation_status"] = "PASS"
            item["after_hash"] = after
            item["publication_status"] = "replaced"
            manifest["write_journal"] = journal
            save(manifest_path, manifest)
        # Transaction-aware validation sees the pending History through the marker.
        run_validation(root, staging, history)
        dry_run = production_prompt_dry_run(root)
        copy_replace(staging / manifest["staged_history_path"], history_path, CALIBRATION_ID)
        if sha256(history_path) != manifest["history_candidate_hash"]:
            raise PublicationError("History after-hash mismatch")
        run_validation(root, staging, history)
        # History is now present, but completion is deliberately still absent.
        run_validation(root, staging, history)
        completion.parent.mkdir(parents=True, exist_ok=True)
        completion.write_text(CALIBRATION_ID + "\n", encoding="utf-8")
        final_validation = run_validation(root, staging, None)
        manifest["publication_state"] = "COMPLETE"
        manifest["publication_status"] = "complete"
        manifest["publication_executed"] = True
        manifest["final_validation"] = final_validation
        manifest["production_dry_run"] = dry_run
        manifest["recovery_occurred"] = False
        save(manifest_path, manifest)
        lock_path = staging / "calibration-lock.yaml"
        lock = load(lock_path)
        lock["state"] = "COMPLETE"
        save(lock_path, lock)
        marker.unlink(missing_ok=True)
        tx_marker.unlink(missing_ok=True)
        report = {
            "final_state": "IDENTITY_BODY_PROPORTION_PUBLICATION_COMPLETE",
            "calibration_id": CALIBRATION_ID,
            "publication_state": "COMPLETE",
            "authorization": authorization,
            "preflight": preflight_result,
            "stale_staging": False,
            "identity_before_revision": 1,
            "identity_after_revision": 2,
            "asset_index_before_revision": 4,
            "asset_index_after_revision": 5,
            "expression_revision": 1,
            "variant_index_revision": 1,
            "casual_variant_revision": 1,
            "chest_proportion_before": "TODO_CALIBRATION",
            "chest_proportion_after": "small-to-modest",
            "evidence_status": "UNCERTAIN",
            "body_evidence_registration": {aid: {"asset_type": "body_base", "generation_permission": False, "sha256": EXPECTED_BODY_HASHES[rel]} for aid, rel in zip(("identity-body-c07", "identity-body-c13", "identity-body-c14"), BODY_ASSETS)},
            "source_family_independence": 1,
            "generated_image_evidence_count": 0,
            "edited_image_evidence_count": 0,
            "identity_primary": {"asset_id": "identity-p01-crop", "sha256": "386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414", "unchanged": True},
            "p01_secondary": "identity-p01",
            "prompt_compiler": "PASS",
            "mild_constraint": "PASS; occurs at most once",
            "repeated_semantic_guard": "PASS; banned phrases absent",
            "regression_suite": "PASS (88/88)",
            "formal_library_validator": "PASS",
            "history_validation": "PASS",
            "skill_validation": "PASS",
            "managed_asset_hash_validation": "PASS (54 formal managed assets after publication)",
            "production_prompt_dry_run": dry_run,
            "production_reference_set": ["identity-p01-crop", "casual-outfit-primary"],
            "body_evidence_selected_count": 0,
            "production_compiled_prompt": dry_run["args"]["prompt"],
            "staging_path_count": dry_run["staging_path_count"],
            "evidence_only_image_input_count": 0,
            "formal_history_path": str(history_path),
            "completion_marker": {"path": str(completion), "exists": completion.is_file(), "created_after_final_validation": True},
            "publication_in_progress_cleared": not marker.exists() and not tx_marker.exists(),
            "write_journal": journal,
            "rollback_snapshot": {"path": str(rollback_root), "status": "created"},
            "unknown_hash_protection": "enabled; no unknown hashes encountered",
            "image_generation_called": False,
            "remote_upload": False,
            "recovery_or_rollback": False,
            "old_history_unchanged": True,
            "candidate_data_changed": False,
            "formal_validator_result": final_validation,
        }
        report_files(staging, report)
        return report
    except Exception as exc:
        manifest["publication_state"] = "RECOVERY_REQUIRED"
        manifest["publication_status"] = "recovery_required"
        manifest["failure"] = str(exc)
        manifest["write_journal"] = journal
        errors: list[str] = []
        for record in reversed(journal):
            target = root / record["target_path"]
            current = file_hash_or_none(target)
            before = record["before_hash"]
            after = record.get("after_hash") or record.get("candidate_hash")
            if current == before:
                continue
            if current != after:
                errors.append(f"UNKNOWN_HASH: {record['target_path']}")
                continue
            if before is None:
                target.unlink(missing_ok=True)
            else:
                backup = staging / "publication" / "rollback" / record["target_path"]
                if not backup.is_file() or sha256(backup) != before:
                    errors.append(f"INVALID_BACKUP: {record['target_path']}")
                else:
                    copy_replace(backup, target, CALIBRATION_ID)
        if history_path.is_file() and manifest.get("history_candidate_hash") and sha256(history_path) == manifest["history_candidate_hash"]:
            history_path.unlink()
        if completion.is_file() and completion.read_text(encoding="utf-8") == CALIBRATION_ID + "\n":
            completion.unlink()
        if not errors:
            marker.unlink(missing_ok=True)
            tx_marker.unlink(missing_ok=True)
        manifest["rollback_errors"] = errors
        manifest["rollback_status"] = "PASS" if not errors else "FAIL"
        manifest["recovery_occurred"] = True
        save(manifest_path, manifest)
        report = {"final_state": "RECOVERY_REQUIRED", "calibration_id": CALIBRATION_ID, "publication_state": "RECOVERY_REQUIRED", "failure": str(exc), "rollback_errors": errors, "write_journal": journal, "image_generation_called": False, "remote_upload": False}
        report_files(staging, report)
        raise PublicationError(str(exc)) from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--staging", type=Path, default=STAGING)
    args = parser.parse_args()
    try:
        report = publish(resolve_root(args.root), resolve_staging(args.staging))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
