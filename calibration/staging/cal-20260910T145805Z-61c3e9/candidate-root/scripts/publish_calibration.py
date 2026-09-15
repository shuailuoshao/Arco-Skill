#!/usr/bin/env python3
"""Publish or recover an Arco calibration using a hash-checked manifest."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    print(
        "PyYAML is required. Install it with: "
        "python -m pip install -r scripts/requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(2)


VALID_STATES = {"prepared", "publishing", "history_pending", "complete", "rollback_required"}


class PublishError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_inside(base: Path, raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise PublishError(f"{label} must be a non-empty relative path")
    path = (base / raw).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as exc:
        raise PublishError(f"{label} escapes its allowed root: {raw}") from exc
    return path


def manifest_path(staging: Path) -> Path:
    return staging / "publish-manifest.yaml"


def load_manifest(staging: Path) -> dict[str, Any]:
    path = manifest_path(staging)
    if not path.is_file():
        raise PublishError(f"Missing manifest: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PublishError(f"Invalid manifest YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PublishError("Manifest must be a mapping")
    if data.get("state") not in VALID_STATES:
        raise PublishError(f"Invalid manifest state: {data.get('state')!r}")
    if not isinstance(data.get("files"), list):
        raise PublishError("Manifest files must be a list")
    return data


def save_manifest(staging: Path, data: dict[str, Any]) -> None:
    path = manifest_path(staging)
    temp = path.with_suffix(".yaml.tmp")
    temp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(temp, path)


def replace_from_source(source: Path, target: Path, calibration_id: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".{target.name}.{calibration_id}.tmp"
    shutil.copy2(source, temp)
    os.replace(temp, target)


def verify_manifest(root: Path, staging: Path, data: dict[str, Any]) -> None:
    if data.get("pre_validation") != "PASS":
        raise PublishError("Manifest requires pre_validation: PASS")
    calibration_id = data.get("calibration_id")
    if not isinstance(calibration_id, str) or staging.name != calibration_id:
        raise PublishError("Staging directory name must match calibration_id")
    for index, item in enumerate(data["files"]):
        if not isinstance(item, dict):
            raise PublishError(f"files[{index}] must be a mapping")
        target = resolve_inside(root, item.get("target_path"), f"files[{index}].target_path")
        staged = resolve_inside(staging, item.get("staged_path"), f"files[{index}].staged_path")
        resolve_inside(staging, item.get("backup_path"), f"files[{index}].backup_path")
        if not staged.is_file():
            raise PublishError(f"Missing staged file: {staged}")
        expected_after = item.get("sha256_after")
        if not isinstance(expected_after, str) or sha256(staged) != expected_after:
            raise PublishError(f"Staged hash mismatch for {target}")
        expected_before = item.get("sha256_before")
        if expected_before is not None and not isinstance(expected_before, str):
            raise PublishError(f"sha256_before must be a string or null for {target}")
        if item.get("publish_status") not in {"pending", "replaced"}:
            raise PublishError(f"Invalid publish_status for {target}")
    staged_history = resolve_inside(staging, data.get("staged_history_path"), "staged_history_path")
    resolve_inside(root, data.get("history_path"), "history_path")
    resolve_inside(root, data.get("completion_marker"), "completion_marker")
    if not staged_history.is_file():
        raise PublishError(f"Missing staged History: {staged_history}")


def publish(root: Path, staging: Path) -> dict[str, Any]:
    data = load_manifest(staging)
    verify_manifest(root, staging, data)
    if data["state"] == "complete":
        return data
    if data["state"] not in {"prepared", "publishing", "history_pending", "rollback_required"}:
        raise PublishError(f"Cannot resume state {data['state']}")
    calibration_id = data["calibration_id"]
    try:
        data["state"] = "publishing"
        save_manifest(staging, data)
        for item in data["files"]:
            target = resolve_inside(root, item["target_path"], "target_path")
            staged = resolve_inside(staging, item["staged_path"], "staged_path")
            backup = resolve_inside(staging, item["backup_path"], "backup_path")
            before_hash = item.get("sha256_before")
            after_hash = item["sha256_after"]
            current_hash = sha256(target) if target.is_file() else None
            if current_hash == after_hash:
                item["publish_status"] = "replaced"
                save_manifest(staging, data)
                continue
            if current_hash != before_hash:
                raise PublishError(f"Unexpected target hash for {target}: {current_hash!r}")
            if target.is_file() and not backup.is_file():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                if sha256(backup) != before_hash:
                    raise PublishError(f"Backup hash mismatch for {target}")
            replace_from_source(staged, target, calibration_id)
            if sha256(target) != after_hash:
                raise PublishError(f"Published hash mismatch for {target}")
            item["publish_status"] = "replaced"
            save_manifest(staging, data)
        data["state"] = "history_pending"
        save_manifest(staging, data)
        staged_history = resolve_inside(staging, data["staged_history_path"], "staged_history_path")
        history = resolve_inside(root, data["history_path"], "history_path")
        replace_from_source(staged_history, history, calibration_id)
        marker = resolve_inside(root, data["completion_marker"], "completion_marker")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker_temp = marker.parent / f".{marker.name}.{calibration_id}.tmp"
        marker_temp.write_text(calibration_id + "\n", encoding="utf-8")
        os.replace(marker_temp, marker)
        data["state"] = "complete"
        data["outcome"] = "published"
        save_manifest(staging, data)
        from validate_library import validate

        result = validate(root)
        if result["structure"] != "PASS":
            marker.unlink(missing_ok=True)
            data["state"] = "rollback_required"
            data["final_validation"] = result["summary"]
            save_manifest(staging, data)
            raise PublishError("Final Character Bible validation failed; rollback or repair is required")
        data["final_validation"] = result["summary"]
        save_manifest(staging, data)
        return data
    except Exception as exc:
        if data.get("state") != "complete":
            data["state"] = "rollback_required"
            data["failure"] = str(exc)
            save_manifest(staging, data)
        if isinstance(exc, PublishError):
            raise
        raise PublishError(str(exc)) from exc


def rollback(root: Path, staging: Path) -> dict[str, Any]:
    data = load_manifest(staging)
    verify_manifest(root, staging, data)
    calibration_id = data["calibration_id"]
    for item in reversed(data["files"]):
        target = resolve_inside(root, item["target_path"], "target_path")
        backup = resolve_inside(staging, item["backup_path"], "backup_path")
        before_hash = item.get("sha256_before")
        after_hash = item["sha256_after"]
        current_hash = sha256(target) if target.is_file() else None
        if current_hash == before_hash:
            item["publish_status"] = "pending"
            continue
        if current_hash != after_hash:
            raise PublishError(f"Cannot safely roll back unexpected target hash for {target}")
        if before_hash is None:
            target.unlink()
        else:
            if not backup.is_file() or sha256(backup) != before_hash:
                raise PublishError(f"Cannot restore missing or invalid backup for {target}")
            replace_from_source(backup, target, calibration_id)
        item["publish_status"] = "pending"
        save_manifest(staging, data)
    history = resolve_inside(root, data["history_path"], "history_path")
    marker = resolve_inside(root, data["completion_marker"], "completion_marker")
    marker.unlink(missing_ok=True)
    if history.is_file():
        staged_history = resolve_inside(staging, data["staged_history_path"], "staged_history_path")
        if sha256(history) != sha256(staged_history):
            raise PublishError("Cannot remove History because its contents drifted")
        history.unlink()
    data["state"] = "complete"
    data["outcome"] = "rolled_back"
    data.pop("failure", None)
    (staging / "ROLLBACK_COMPLETE").write_text(calibration_id + "\n", encoding="utf-8")
    save_manifest(staging, data)
    return data


def print_status(data: dict[str, Any]) -> None:
    print(f"CALIBRATION: {data.get('calibration_id')}")
    print(f"STATE: {data.get('state')}")
    print(f"OUTCOME: {data.get('outcome', '(pending)')}")
    for item in data.get("files", []):
        print(f"  {item.get('publish_status')}: {item.get('target_path')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["publish", "recover", "status"])
    parser.add_argument("staging_dir", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--strategy", choices=["resume", "rollback"])
    args = parser.parse_args(argv)
    root = args.root.resolve()
    staging = args.staging_dir.resolve()
    try:
        if args.command == "status":
            data = load_manifest(staging)
        elif args.command == "publish":
            data = publish(root, staging)
        elif args.strategy == "resume":
            data = publish(root, staging)
        elif args.strategy == "rollback":
            data = rollback(root, staging)
        else:
            parser.error("recover requires --strategy resume or rollback")
        print_status(data)
        return 0
    except PublishError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
