"""Create metadata-only staging for the Identity Primary generation contract patch."""
from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGET = "identity-p01-crop"
EXPECTED_INHERIT = ["identity", "face", "hair", "eyes"]
EXPECTED_EXCLUDE = ["outfit", "pose", "expression"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def create() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    calibration_id = f"cal-{stamp}-{secrets.token_hex(3)}"
    staging = ROOT / "calibration" / "staging" / calibration_id
    candidate = staging / "candidate-root"
    candidate.mkdir(parents=True)

    formal_files = {
        "character/assets.yaml": ROOT / "character/assets.yaml",
        "character/identity.yaml": ROOT / "character/identity.yaml",
        "character/expressions.yaml": ROOT / "character/expressions.yaml",
        "variants/index.yaml": ROOT / "variants/index.yaml",
    }
    for relative, source in formal_files.items():
        (candidate / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, candidate / relative)

    assets_path = candidate / "character/assets.yaml"
    assets = load(assets_path)
    before_revision = assets["revision"]
    if before_revision != 3:
        raise RuntimeError(f"Expected formal Asset Index revision 3, got {before_revision}")
    target = next(asset for asset in assets["assets"] if asset.get("asset_id") == TARGET)
    target["generation_reference"]["inheritance"] = {
        "identity": "inherit", "face": "inherit", "hair": "inherit", "eyes": "inherit",
        "outfit": "do_not_inherit", "pose": "do_not_inherit", "expression": "do_not_inherit",
    }
    assets["revision"] = 4
    assets["last_calibration_id"] = calibration_id
    dump(assets_path, assets)

    base_hashes = {relative: sha256(source) for relative, source in formal_files.items()}
    image_hashes = {
        asset["asset_id"]: sha256(ROOT / asset["path"])
        for asset in load(formal_files["character/assets.yaml"])["assets"]
        if isinstance(asset.get("path"), str) and (ROOT / asset["path"]).is_file()
    }
    (staging / "source-hashes.yaml").write_text(
        yaml.safe_dump({"formal_file_hashes": base_hashes, "managed_image_hashes": image_hashes}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    history = {
        "schema_version": 1, "calibration_id": calibration_id, "draft": True,
        "publication_status": "NOT_PUBLISHED", "target_entity": "character.assets",
        "revision_before": 3, "revision_after": 4,
        "patch_type": "generation-contract explicitness repair",
        "patch_reason": "First Live Smoke Test exposed a contract explicitness gap.",
        "knowledge_change": False, "publication_not_executed": True,
        "user_confirmed": True, "reason": "Contract explicitness repair; not new identity knowledge.",
        "evidence_ids": [], "observations": [],
        "validation_result": {"structure": "PASS"},
        "targets": [{
            "entity_ref": "character.assets", "target_type": "asset_generation_contract", "target_id": TARGET,
            "revision_before": 3, "revision_after": 4,
            "changed_fields": ["revision", "last_calibration_id", "assets.identity-p01-crop.generation_reference.inheritance"],
            "before": {"revision": 3, "last_calibration_id": "cal-20260914T070842Z-68b810"},
            "after": {"revision": 4, "last_calibration_id": calibration_id},
            "status_before": None, "status_after": None,
        }],
        "asset_id": TARGET,
        "before": {"inherit": ["identity"], "do_not_inherit": ["expression", "outfit", "pose"]},
        "after": {"inherit": EXPECTED_INHERIT, "do_not_inherit": EXPECTED_EXCLUDE},
    }
    dump(staging / "history-draft.yaml", history)
    manifest = {
        "schema_version": 3, "calibration_id": calibration_id,
        "transaction_id": f"tx-identity-contract-{calibration_id}",
        "publication_state": "STAGED_VALIDATED_AWAITING_AUTHORIZATION", "publication_authorized": False,
        "calibration_targets": ["character.assets"], "revalidation_status": "PASS",
        "base_state": {"expression_library_revision": 1, "asset_index_revision": 3, "identity_revision": 1, "variant_index_revision": 1, "casual_variant_revision": 1},
        "base_hashes": base_hashes,
        "files": [{"target_path": "character/assets.yaml", "staged_path": "candidate-root/character/assets.yaml", "before_hash": base_hashes["character/assets.yaml"], "candidate_hash": sha256(assets_path), "after_hash": None, "publication_status": "pending", "backup_path": None}],
        "staged_history_path": "history-draft.yaml", "history_candidate_hash": sha256(staging / "history-draft.yaml"),
        "history_path": f"calibration/history/{calibration_id}.yaml",
        "completion_marker": f"calibration/history/{calibration_id}.complete",
        "in_progress_marker": f"calibration/history/{calibration_id}.publication_in_progress",
        "publication_status": "pending", "publication_executed": False,
    }
    dump(staging / "publish-manifest.yaml", manifest)
    dump(staging / "calibration-lock.yaml", {"calibration_id": calibration_id, "state": "staged_validated_awaiting_authorization", "targets": ["character.assets"]})
    return staging


if __name__ == "__main__":
    print(create())
