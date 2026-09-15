"""Create an evidence-backed, non-public Identity body proportion calibration staging."""
from __future__ import annotations

import hashlib
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = {
    "identity-body-c07": (Path(r"D:\阿尔可\阿尔可立绘\アルコ\アルコ_a_l_5791.png"), "c07-open-arms"),
    "identity-body-c13": (Path(r"D:\阿尔可\阿尔可立绘\アルコ\アルコ_b_l_7679.png"), "c13-raised-fists"),
    "identity-body-c14": (Path(r"D:\阿尔可\阿尔可立绘\アルコ\アルコ_b_l_7739.png"), "c14-crossed-arms"),
}

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))

def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")

def create() -> Path:
    for source, _ in SOURCE.values():
        if not source.is_file():
            raise FileNotFoundError(source)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    calibration_id = f"cal-{stamp}-{secrets.token_hex(3)}"
    staging = ROOT / "calibration" / "staging" / calibration_id
    candidate = staging / "candidate-root"
    for rel in ("character/identity.yaml", "character/assets.yaml", "character/expressions.yaml", "variants/index.yaml"):
        target = candidate / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)

    identity = load(candidate / "character/identity.yaml")
    assets = load(candidate / "character/assets.yaml")
    if identity["revision"] != 1 or assets["revision"] != 4:
        raise RuntimeError("stale formal baseline")
    existing = {a["asset_id"] for a in assets["assets"]}
    evidence_ids = list(SOURCE)
    for aid, (source, pose) in SOURCE.items():
        rel = Path("assets/arco/identity/body-evidence") / f"{aid}.png"
        destination = candidate / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        assets["assets"].append({
            "asset_id": aid, "path": rel.as_posix(), "asset_status": "VERIFIED",
            "expression_id": None, "variant_id": None, "state_ids": [],
            "reference_level": "detail", "roles": ["body_evidence"],
            "purpose_note_zh": "官方 Body Base 身体比例证据；禁止生成输入。",
            "asset_type": "body_base", "source_kind": "official", "source_authority": "primary_official",
            "source_group_id": f"arco-body-base-{pose}", "source_family_id": "arco-official-standing-art-system-01",
            "face_slot_id": None, "face_slot_membership": None, "expression_set_id": None,
            "view_class": "front" if pose != "c07-open-arms" else "three_quarter_right",
            "view_angle": "front" if pose != "c07-open-arms" else "front_three_quarter",
            "derived_from_asset_id": None,
            "provenance": {"original_filename": source.name, "source_path": str(source),
                           "source_note": "用户批准的官方 Body Base evidence-only registration。",
                           "ingest_calibration_id": calibration_id},
            "sha256": sha(source), "can_be_generation_reference": False,
        })
    if existing & set(SOURCE):
        raise RuntimeError("evidence asset already exists")
    assets["revision"] = 5
    assets["last_calibration_id"] = calibration_id
    dump(candidate / "character/assets.yaml", assets)

    fact = next(x for x in identity["facts"] if x["field_id"] == "body.chest_proportion")
    fact.update({"value": "small-to-modest", "status": "UNCERTAIN", "evidence_ids": evidence_ids + ["identity-p01", "identity-p03"],
                 "note_zh": "用户批准的工作级描述；不等于 VISUAL_CONSENSUS 或 CANON。整体体型纤细轻盈，肩背与躯干较窄，胸部比例偏小至克制。"})
    identity["revision"] = 2
    identity["last_calibration_id"] = calibration_id
    identity["working_identity_description"] = "阿尔可：冰银浅蓝长发并带粉色发梢、红色眼睛、纤细修长体型；胸部比例偏小至克制；服装、角和姿势不属于本描述。"
    dump(candidate / "character/identity.yaml", identity)

    formal = {rel: ROOT / rel for rel in ("character/identity.yaml", "character/assets.yaml", "character/expressions.yaml", "variants/index.yaml")}
    base_hashes = {rel: sha(path) for rel, path in formal.items()}
    managed_hashes = {a["asset_id"]: a["sha256"] for a in load(ROOT / "character/assets.yaml")["assets"]}
    dump(staging / "source-hashes.yaml", {"formal_file_hashes": base_hashes, "managed_image_hashes": managed_hashes})
    history = {"schema_version": 1, "calibration_id": calibration_id, "draft": True, "publication_status": "NOT_PUBLISHED",
               "target_entity": "character.identity", "revision_before": 1, "revision_after": 2,
               "patch_type": "identity body proportion calibration", "patch_reason": "First Live Smoke Test exposed an upper-torso visual mismatch.",
               "knowledge_change": True, "contract_explicitness_repair": False, "user_confirmed": True,
               "evidence_ids": fact["evidence_ids"], "source_family_independence": {"count": 1},
               "observations": ["C07/C13 show a narrow torso and restrained chest projection; C14 is chest-occluded.", "P01/P03 support a slender dressed silhouette; clothing adds visual volume."],
               "candidate_fact": {"field_id": "body.chest_proportion", "value": "small-to-modest", "status": "UNCERTAIN", "prompt_zh": "整体体型纤细轻盈，肩背与躯干较窄，胸部比例偏小至克制。", "prompt_en": "a slim, lightly built figure with a narrow upper torso and a small-to-modest, understated bust", "soft_constraint_en": "no exaggerated chest volume"},
               "publication_not_executed": True}
    dump(staging / "history-draft.yaml", history)
    manifest = {"schema_version": 3, "calibration_id": calibration_id, "transaction_id": f"tx-identity-body-{calibration_id}",
                "publication_state": "STAGED_VALIDATED_AWAITING_AUTHORIZATION", "publication_authorized": False,
                "calibration_targets": ["character.identity", "character.assets"], "revalidation_status": "PENDING",
                "base_state": {"expression_library_revision": 1, "asset_index_revision": 4, "identity_revision": 1, "variant_index_revision": 1, "casual_variant_revision": 1},
                "base_hashes": base_hashes, "files": [{"target_path": "character/identity.yaml", "staged_path": "candidate-root/character/identity.yaml", "before_hash": base_hashes["character/identity.yaml"], "candidate_hash": sha(candidate / "character/identity.yaml"), "after_hash": None, "publication_status": "pending"}, {"target_path": "character/assets.yaml", "staged_path": "candidate-root/character/assets.yaml", "before_hash": base_hashes["character/assets.yaml"], "candidate_hash": sha(candidate / "character/assets.yaml"), "after_hash": None, "publication_status": "pending"}],
                "staged_history_path": "history-draft.yaml", "history_path": f"calibration/history/{calibration_id}.yaml", "completion_marker": f"calibration/history/{calibration_id}.complete", "publication_status": "pending", "publication_executed": False, "image_generation_called": False, "remote_upload": False}
    dump(staging / "publish-manifest.yaml", manifest)
    dump(staging / "calibration-lock.yaml", {"schema_version": 1, "calibration_id": calibration_id, "state": "staged_validated_awaiting_authorization", "targets": ["character.identity", "character.assets"]})
    return staging

if __name__ == "__main__":
    print(create())
