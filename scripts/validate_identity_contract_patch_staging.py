"""Validate the metadata-only Identity Primary contract patch staging."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGET = "identity-p01-crop"
EXPECTED_INHERIT = {"identity", "face", "hair", "eyes"}
EXPECTED_EXCLUDE = {"outfit", "pose", "expression"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validate(root: Path, staging: Path) -> dict:
    errors = []
    formal_assets = load(root / "character/assets.yaml")
    candidate_assets = load(staging / "candidate-root/character/assets.yaml")
    manifest = load(staging / "publish-manifest.yaml")
    history = load(staging / "history-draft.yaml")
    hashes = load(staging / "source-hashes.yaml")
    def req(condition, message):
        if not condition: errors.append(message)
    published = manifest.get("publication_state") == "COMPLETE"
    req(manifest.get("publication_authorized") is (True if published else False), "publication authorization state invalid")
    req(manifest.get("publication_executed") is False, "unexpected publication execution flag")
    req(manifest.get("calibration_targets") == ["character.assets"] and manifest.get("revalidation_status") == "PASS", "publication v3 fields missing")
    req(candidate_assets.get("revision") == 4, "candidate Asset Index revision must be 4")
    req(formal_assets.get("revision") == (4 if published else 3), "formal Asset Index revision mismatch")
    for relative, expected in hashes.get("formal_file_hashes", {}).items():
        if published and relative == "character/assets.yaml":
            continue
        req((root / relative).is_file() and sha256(root / relative) == expected, f"protected formal file changed: {relative}")
    formal_by = {item["asset_id"]: item for item in formal_assets["assets"]}
    candidate_by = {item["asset_id"]: item for item in candidate_assets["assets"]}
    req(set(formal_by) == set(candidate_by), "asset set changed")
    before_target = formal_by[TARGET]
    after_target = candidate_by[TARGET]
    before_meta = before_target["generation_reference"]
    after_meta = after_target["generation_reference"]
    req(set(k for k,v in after_meta["inheritance"].items() if v == "inherit") == EXPECTED_INHERIT, "inheritance is not exact")
    req(set(k for k,v in after_meta["inheritance"].items() if v == "do_not_inherit") == EXPECTED_EXCLUDE, "exclusions are not exact")
    immutable = ["asset_id", "path", "sha256", "parent_asset_id", "derived_from_asset_id", "operation", "dimensions_px", "generation_risk_note"]
    for key in immutable:
        req(after_target.get(key) == before_target.get(key), f"target metadata changed: {key}")
    for aid in set(formal_by) - {TARGET}:
        req(candidate_by[aid] == formal_by[aid], f"unrelated asset changed: {aid}")
    if published:
        req(formal_by[TARGET] == candidate_by[TARGET], "published target differs from candidate")
    req(after_target["path"] == "assets/arco/identity/p01-face-hair-primary-a.png", "target path changed")
    req(sha256(root / after_target["path"]) == after_target["sha256"], "target image hash invalid")
    for aid, expected in hashes.get("managed_image_hashes", {}).items():
        asset = formal_by.get(aid)
        req(asset is not None and asset.get("sha256") == expected and sha256(root / asset["path"]) == expected, f"protected managed image hash changed: {aid}")
    req(history.get("target_entity") == "character.assets" and history.get("knowledge_change") is False, "history is not metadata-only")
    item = manifest.get("files", [{}])[0]
    req(len(manifest.get("files", [])) == 1 and item.get("target_path") == "character/assets.yaml" and item.get("staged_path") == "candidate-root/character/assets.yaml" and item.get("before_hash") == manifest["base_hashes"]["character/assets.yaml"], "manifest scope is not metadata-only")
    if published:
        req(item.get("after_hash") == item.get("candidate_hash") and item.get("publication_status") == "replaced", "published file hash/status mismatch")
        req((root / manifest["history_path"]).is_file(), "published History missing")
        req((root / manifest["completion_marker"]).is_file(), "completion marker missing")
        req(not (root / manifest["in_progress_marker"]).exists(), "publication_in_progress not cleared")
    return {"status": "PASS" if not errors else "FAIL", "calibration_id": manifest.get("calibration_id"), "errors": errors, "publication_executed": False, "image_generation_called": False, "remote_upload": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate(args.root.resolve(), args.staging.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"{result['status']}: {len(result['errors'])} errors")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
