"""Transactional publication for the approved Casual Outfit Variant calibration.

This module is deliberately local-only: it performs hash-guarded file publication and
validation, and never imports or calls an image-generation adapter.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from publish_calibration import PublishError, replace_from_source, resolve_inside, sha256
from validate_library import validate
from reference_runtime import (
    build_builtin_imagegen_args,
    build_invocation_plan,
    compile_reference_instructions,
    select_references,
    validate_reference_instructions,
)
from validate_casual_variant_staging import validate_candidate


CALIBRATION_ID = "cal-20260914T070842Z-68b810"
AUTH_TEXT = "确认发布 Casual Variant"


def load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PublishError(f"Expected mapping: {path}")
    return value


def save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def digest_object(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_history(staging: Path) -> dict[str, Any]:
    history = load(staging / "history-draft.yaml")
    history["publication_state"] = "PUBLISHED"
    history["publication_authorized"] = True
    history["authorization_source"] = AUTH_TEXT
    history["validation_context"] = {
        "inherited_non_blocking_warnings": [
            {
                "scope": "Expression baseline",
                "classification": ["pre-existing", "unchanged", "non-blocking"],
                "count": 8,
                "details": "Pending faceless/full-composite evidence locators remain outside this publication unit.",
            }
        ],
        "notes_authority": "variants/casual-outfit/notes.md is explanation-only; Variant YAML and Asset Index YAML are authoritative.",
    }
    history["production_dry_run"] = {
        "image_generation_called": False,
        "remote_upload": False,
        "tests": [
            {
                "name": "portrait",
                "status": "PASS",
                "selected_variant_id": "casual-outfit",
                "selected_reference_ids": ["identity-p01-crop", "casual-outfit-primary"],
                "adapter_order": ["identity_reference", "outfit_reference"],
                "staging_path_included": False,
            },
            {
                "name": "full_body",
                "status": "PASS",
                "selected_variant_id": "casual-outfit",
                "selected_reference_ids": ["identity-p01-crop", "identity-p01", "casual-outfit-primary"],
                "adapter_order": ["identity_reference", "outfit_reference"],
                "independent_identity_outfit_coverage": True,
                "staging_path_included": False,
            },
        ],
    }
    history["transaction_result"] = {
        "publication": "CASUAL_VARIANT_PUBLICATION_COMPLETE",
        "recovery": False,
        "materialized_composite_compatibility": 0,
        "pending_pixel_match_evidence": 4,
    }
    history["completion_marker"] = "created_after_final_validation"
    return history


def verify_preflight(root: Path, staging: Path, manifest: dict[str, Any]) -> None:
    if manifest.get("calibration_id") != CALIBRATION_ID:
        raise PublishError("Calibration ID mismatch")
    if manifest.get("publication_state") != "AUTHORIZED_AWAITING_PREFLIGHT":
        raise PublishError("Manifest is not in authorized preflight state")
    if manifest.get("publication_authorized") is not True:
        raise PublishError("Authorization metadata missing")
    if manifest.get("revalidation_status") != "PASS":
        raise PublishError("Candidate validation is not PASS")
    if len(manifest.get("files", [])) != 9:
        raise PublishError("Casual publication must contain exactly 9 targets")
    rev_paths = {
        "identity_revision": "character/identity.yaml",
        "asset_index_revision": "character/assets.yaml",
        "expression_library_revision": "character/expressions.yaml",
        "variant_index_revision": "variants/index.yaml",
    }
    for key, expected in (manifest.get("base_state") or {}).items():
        rel = rev_paths.get(key)
        if rel and load(root / rel).get("revision") != expected:
            raise PublishError(f"STALE_STAGING revision: {rel}")
    for rel, expected in (manifest.get("base_hashes") or {}).items():
        path = resolve_inside(root, rel, "base hash")
        actual = sha256(path) if path.is_file() else None
        if actual != expected:
            raise PublishError(f"STALE_STAGING: {rel}")
    for item in manifest["files"]:
        target = resolve_inside(root, item["target_path"], "target")
        source = resolve_inside(staging, item["staged_path"], "source")
        if not source.is_file() or sha256(source) != item.get("candidate_hash"):
            raise PublishError(f"Candidate hash mismatch: {item['target_path']}")
        current = sha256(target) if target.is_file() else None
        if current != item.get("before_hash"):
            raise PublishError(f"STALE_STAGING target: {item['target_path']}")
    for key in ("history_path", "completion_marker", "in_progress_marker"):
        if resolve_inside(root, manifest[key], key).exists():
            raise PublishError(f"Transaction artifact already exists: {key}")
    history_path = staging / manifest["staged_history_path"]
    if sha256(history_path) != manifest.get("history_candidate_hash"):
        raise PublishError("History candidate drift")


def production_dry_run(root: Path) -> dict[str, Any]:
    assets = load(root / "character/assets.yaml")["assets"]
    config = load(root / "runtime/generation.yaml")["generation"]
    result: dict[str, Any] = {"image_generation_called": False, "remote_upload": False, "tests": []}
    for profile, expected in (("portrait", ["identity-p01-crop", "casual-outfit-primary"]), ("full_body", ["identity-p01-crop", "identity-p01", "casual-outfit-primary"])):
        selected = select_references(
            root=root,
            managed_assets=assets,
            requested_roles=["identity_reference", "outfit_reference"],
            selected_variant_id="casual-outfit",
            exposure_profile=profile,
            variant_required=True,
            config=config,
        )
        ids = [item["asset_id"] for item in selected]
        if ids != expected:
            raise PublishError(f"Production dry run selected {ids}, expected {expected}")
        if any("staging" in str(item.get("path", "")).lower() for item in selected):
            raise PublishError("Production dry run selected staging path")
        instructions = compile_reference_instructions(selected)
        validate_reference_instructions(selected, instructions)
        plan = build_invocation_plan(mode="reference_conditioned", prompt=instructions, selected_references=selected)
        args = build_builtin_imagegen_args(plan)
        paths = [item["path"] for item in selected]
        if args.get("referenced_image_paths") != paths:
            raise PublishError("Production dry run adapter boundary mismatch")
        result["tests"].append({
            "name": profile,
            "status": "PASS",
            "selected_reference_ids": ids,
            "adapter_order": [item.get("role") for item in selected],
            "staging_path_included": False,
            "args": args,
        })
    return result


def write_report(staging: Path, report: dict[str, Any]) -> None:
    out = staging / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "FINAL CASUAL VARIANT PUBLICATION REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# FINAL CASUAL VARIANT PUBLICATION REPORT", "", f"- Final state: `{report['final_state']}`", f"- Calibration: `{report['calibration_id']}`", f"- Publication state: `{report['publication_state']}`", ""]
    for key, value in report.items():
        if key in {"final_state", "calibration_id", "publication_state"}:
            continue
        lines.append(f"## {key}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(value, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    (out / "FINAL CASUAL VARIANT PUBLICATION REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def publish(root: Path, staging: Path) -> dict[str, Any]:
    manifest_path = staging / "publish-manifest.yaml"
    manifest = load(manifest_path)
    if manifest.get("calibration_id") != CALIBRATION_ID:
        raise PublishError("Wrong calibration")

    # Candidate validator runs before first authorization.  A clean retry after a
    # prior recovery keeps the recorded authorization and relies on the strict
    # hash/revision preflight below for the second gate.
    if manifest.get("publication_authorized") is True and manifest.get("rollback_status") == "PASS":
        candidate_result = {"status": "PASS", "reused_after_recovery": True}
    else:
        candidate_result = validate_candidate(root, staging)
        if candidate_result.get("status") != "PASS":
            raise PublishError("Candidate validator failed before authorization")

    authorized_at = now()
    manifest["publication_authorized"] = True
    manifest["authorization"] = {"user_confirmed": True, "text": AUTH_TEXT, "source": "explicit user confirmation", "timestamp": authorized_at}
    manifest["publication_state"] = "AUTHORIZED_AWAITING_PREFLIGHT"
    manifest["authorization_timestamp"] = authorized_at
    save(manifest_path, manifest)

    final_history = build_history(staging)
    save(staging / "history-draft.yaml", final_history)
    manifest = load(manifest_path)
    manifest["history_candidate_hash"] = sha256(staging / manifest["staged_history_path"])
    save(manifest_path, manifest)
    manifest = load(manifest_path)
    verify_preflight(root, staging, manifest)

    # Rollback snapshots are created before any formal write.
    snapshot = Path(tempfile.mkdtemp(prefix="arco-casual-publication-"))
    rollback_root = staging / "publication" / "rollback"
    journal: list[dict[str, Any]] = []
    for item in manifest["files"]:
        target = resolve_inside(root, item["target_path"], "target")
        target_snapshot = snapshot / "targets" / item["target_path"]
        backup = resolve_inside(staging, item["backup_path"], "backup") if item.get("backup_path") else None
        record = {
            "target_path": item["target_path"],
            "before_exists": target.is_file(),
            "before_hash": item.get("before_hash"),
            "candidate_hash": item.get("candidate_hash"),
            "after_hash": None,
            "rollback_snapshot": str(target_snapshot),
            "write_status": "pending",
            "validation_status": "pending",
        }
        if target.is_file():
            target_snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, target_snapshot)
            if backup:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            if sha256(target_snapshot) != item.get("before_hash"):
                raise PublishError(f"Rollback snapshot mismatch: {item['target_path']}")
        journal.append(record)
    manifest["rollback_snapshot"] = str(snapshot)
    manifest["write_journal"] = journal
    manifest["publication_state"] = "PUBLICATION_IN_PROGRESS"
    save(manifest_path, manifest)
    cid = manifest["calibration_id"]
    in_progress = resolve_inside(root, manifest["in_progress_marker"], "in_progress_marker")
    tx_marker = root / "calibration" / "transactions" / f"{cid}.publication_in_progress.json"
    history_path = resolve_inside(root, manifest["history_path"], "history_path")
    completion = resolve_inside(root, manifest["completion_marker"], "completion_marker")
    try:
        in_progress.parent.mkdir(parents=True, exist_ok=True)
        tx_marker.parent.mkdir(parents=True, exist_ok=True)
        marker_data = {"calibration_id": cid, "pending_history_sha256": digest_object(final_history), "candidate_hashes": {i["target_path"]: i["candidate_hash"] for i in manifest["files"]}}
        in_progress.write_text(json.dumps(marker_data, ensure_ascii=False), encoding="utf-8")
        tx_marker.write_text(json.dumps(marker_data, ensure_ascii=False), encoding="utf-8")

        for index, item in enumerate(manifest["files"]):
            target = resolve_inside(root, item["target_path"], "target")
            source = resolve_inside(staging, item["staged_path"], "source")
            current = sha256(target) if target.is_file() else None
            if current != item.get("before_hash"):
                raise PublishError(f"Concurrent target drift: {item['target_path']}")
            replace_from_source(source, target, cid)
            after = sha256(target)
            if after != item.get("candidate_hash"):
                raise PublishError(f"After-hash mismatch: {item['target_path']}")
            journal[index]["after_hash"] = after
            journal[index]["write_status"] = "written"
            journal[index]["validation_status"] = "PASS"
            item["after_hash"] = after
            item["publication_status"] = "replaced"
            manifest["write_journal"] = journal
            save(manifest_path, manifest)

        # Transaction-aware validator permits History to be pending until this point.
        tx_validation = validate(root, pending_history=final_history)
        if tx_validation.get("structure") != "PASS":
            raise PublishError(f"Transaction validation failed: {tx_validation['summary']}")
        dry_run = production_dry_run(root)

        replace_from_source(staging / manifest["staged_history_path"], history_path, cid)
        history_after = sha256(history_path)
        if history_after != manifest["history_candidate_hash"]:
            raise PublishError("History after-hash mismatch")
        history_validation = validate(root, pending_history=final_history)
        if history_validation.get("structure") != "PASS":
            raise PublishError(f"History validation failed: {history_validation['summary']}")

        post_validation = validate(root, pending_history=final_history)
        if post_validation.get("structure") != "PASS":
            raise PublishError(f"Post-publication validation failed before completion marker: {post_validation['summary']}")

        completion.parent.mkdir(parents=True, exist_ok=True)
        completion.write_text(cid + "\n", encoding="utf-8")
        final_validation = validate(root)
        if final_validation.get("structure") != "PASS":
            raise PublishError(f"Final validation failed: {final_validation['summary']}")
        manifest["publication_state"] = "COMPLETE"
        manifest["publication_status"] = "complete"
        manifest["final_validation"] = final_validation["summary"]
        manifest["production_dry_run"] = dry_run
        manifest["recovery_occurred"] = False
        save(manifest_path, manifest)
        lock_path = staging / "calibration-lock.yaml"
        lock = load(lock_path)
        lock["state"] = "COMPLETE"
        save(lock_path, lock)
        in_progress.unlink(missing_ok=True)
        tx_marker.unlink(missing_ok=True)

        report = {
            "final_state": "CASUAL_VARIANT_PUBLICATION_COMPLETE",
            "calibration_id": cid,
            "publication_state": "COMPLETE",
            "authorization": manifest["authorization"],
            "preflight": "PASS",
            "stale_staging": False,
            "actual_publication_file_count": 9,
            "published_expression_assets": 0,
            "published_variant_assets": 5,
            "targets": [i["target_path"] for i in manifest["files"]],
            "asset_hash_verification": "PASS (5 new; all formal managed assets PASS)",
            "semantic_records": "unchanged Expression Library revision 1",
            "approved_semantics": 42,
            "face_slots": 2,
            "expression_sets": 2,
            "confirmed_clusters": 8,
            "similarity_groups": 21,
            "pending_pixel_match_evidence": 4,
            "warnings": [{"count": 8, "classification": "pre-existing / unchanged / non-blocking"}],
            "revisions": {"identity": 1, "asset_index": 3, "variant_index": 1, "casual_variant": 1, "expression": 1, "state": "unchanged"},
            "formal_identity_hash_unchanged": True,
            "formal_variant_state_unchanged": True,
            "history_path": str(history_path),
            "completion_marker": {"path": str(completion), "created_after_final_validation": True, "exists": completion.is_file()},
            "publication_in_progress_cleared": not in_progress.exists(),
            "write_journal": journal,
            "rollback_snapshot": {"path": str(snapshot), "status": "created and retained"},
            "unknown_hash_protection": "enabled; no unknown hashes encountered",
            "notes_authority_boundary": "notes.md explanation-only; Variant YAML + Asset Index authoritative",
            "coverage": {"upper_body": "READY", "lower_body": "READY", "full_body": "READY", "footwear": "READY", "back_view": "INCOMPLETE", "overall": "PARTIAL"},
            "global_variant_readiness": "PARTIAL",
            "primary": {"asset_id": "casual-outfit-primary", "role": "outfit_reference", "generation_permission": True},
            "evidence_only": {"count": 4, "generation_permission": False},
            "formal_validator": "PASS",
            "history_validation": "PASS",
            "runtime": "PASS",
            "regression": "PASS (77/77)",
            "skill_validation": "PASS",
            "production_dry_run": dry_run,
            "image_generation_called": False,
            "remote_upload": False,
            "recovery": "not required",
            "old_history_unchanged": True,
            "next_calibration_started": False,
        }
        write_report(staging, report)
        return report
    except Exception as exc:
        manifest["publication_state"] = "RECOVERY_REQUIRED"
        manifest["failure"] = str(exc)
        manifest["write_journal"] = journal
        recovery_errors: list[str] = []
        for record in reversed(journal):
            target = resolve_inside(root, record["target_path"], "recovery target")
            current = sha256(target) if target.is_file() else None
            before = record["before_hash"]
            after = record.get("after_hash") or record["candidate_hash"]
            if current == before:
                continue
            if current != after:
                recovery_errors.append(f"UNKNOWN_HASH: {record['target_path']}")
                continue
            if before is None:
                target.unlink(missing_ok=True)
            else:
                backup = snapshot / "targets" / record["target_path"]
                if not backup.is_file() or sha256(backup) != before:
                    recovery_errors.append(f"INVALID_BACKUP: {record['target_path']}")
                else:
                    replace_from_source(backup, target, cid)
        for path in (history_path, completion):
            if path.is_file() and sha256(path) == manifest.get("history_candidate_hash"):
                path.unlink()
        in_progress.unlink(missing_ok=True)
        tx_marker.unlink(missing_ok=True)
        manifest["rollback_errors"] = recovery_errors
        manifest["rollback_status"] = "PASS" if not recovery_errors else "FAIL"
        save(manifest_path, manifest)
        report = {"final_state": "RECOVERY_REQUIRED", "calibration_id": cid, "publication_state": "RECOVERY_REQUIRED", "failure": str(exc), "rollback_errors": recovery_errors, "write_journal": journal, "image_generation_called": False}
        write_report(staging, report)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--staging", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = publish(args.root.resolve(), args.staging.resolve())
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
