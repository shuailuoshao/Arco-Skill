"""Create the read-only Identity Calibration staging candidate."""
from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import yaml

from verify_historical_manifest import annotate_manifest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(r"D:\阿尔可")
P01 = SOURCE_ROOT / "阿尔可立绘1.png"
P03 = SOURCE_ROOT / "阿尔可立绘3.png"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def build_identity(calibration_id: str) -> dict:
    fields = {
        "hair.base_color": ("冰银/浅蓝白基色，发梢过渡到粉红", "UNCERTAIN", ["identity-p01", "identity-p03"]),
        "hair.base_identity": ("极长发、厚刘海、两侧长发束和粉色发梢", "UNCERTAIN", ["identity-p01", "identity-p03"]),
        "eyes.color": ("高饱和红/绯红虹膜", "UNCERTAIN", ["identity-p01", "identity-p03"]),
        "face.shape": ("柔和偏窄的椭圆脸，下颌向小巧尖圆下巴收束", "UNCERTAIN", ["identity-p01", "identity-p03"]),
        "face.feature_relationships": ("大型动漫眼、短鼻、较小下半脸", "UNCERTAIN", ["identity-p01", "identity-p03"]),
        "body.height": (None, "TODO_CALIBRATION", []),
        "body.head_to_body_ratio": ("修长动漫比例，不固化精确数值", "TODO_CALIBRATION", ["identity-p01"]),
        "body.overall_build": ("纤细、轻盈、窄躯干、长肢体", "UNCERTAIN", ["identity-p01", "identity-p03"]),
        "body.chest_proportion": (None, "TODO_CALIBRATION", []),
        "body.shoulder_width": ("视觉上偏窄", "UNCERTAIN", ["identity-p01", "identity-p03"]),
        "body.waist_hip_ratio": ("细腰、髋部柔和展开，受姿势和服装影响", "UNCERTAIN", ["identity-p01"]),
        "body.leg_proportion": ("腿部相对躯干较长", "UNCERTAIN", ["identity-p01"]),
        "body.other_stable_features": (None, "TODO_CALIBRATION", []),
        "rendering.baseline_style": ("日系视觉小说 standing-art、清晰线稿和柔和赛璐璐渲染", "UNCERTAIN", ["identity-p01"]),
    }
    labels = {
        "hair.base_color": "基础发色", "hair.base_identity": "基础发型身份特征", "eyes.color": "眼睛颜色",
        "face.shape": "脸型", "face.feature_relationships": "五官视觉关系", "body.height": "身高",
        "body.head_to_body_ratio": "头身比", "body.overall_build": "整体体型", "body.chest_proportion": "胸部相对体型比例",
        "body.shoulder_width": "肩宽", "body.waist_hip_ratio": "腰臀比例", "body.leg_proportion": "腿部比例",
        "body.other_stable_features": "其他稳定身体视觉特征", "rendering.baseline_style": "基线渲染风格",
    }
    required = {
        "hair.base_color": ["portrait", "upper_body", "full_body", "back_view"], "hair.base_identity": ["portrait", "upper_body", "full_body", "back_view"],
        "eyes.color": ["portrait", "upper_body", "full_body"], "face.shape": ["portrait", "upper_body", "full_body"],
        "face.feature_relationships": ["portrait", "upper_body", "full_body"], "body.height": ["full_body"],
        "body.head_to_body_ratio": ["full_body"], "body.overall_build": ["upper_body", "full_body"],
        "body.chest_proportion": ["upper_body", "full_body"], "body.shoulder_width": ["upper_body", "full_body", "back_view"],
        "body.waist_hip_ratio": ["full_body", "back_view"], "body.leg_proportion": ["full_body"],
        "body.other_stable_features": [], "rendering.baseline_style": [],
    }
    facts = []
    for field, (value, status, evidence) in fields.items():
        facts.append({"field_id": field, "display_name_zh": labels[field], "value": value, "status": status,
                      "evidence_ids": evidence, "conflicts": [], "note_zh": "用户批准的工作级描述；不等于 CANON 或 VISUAL_CONSENSUS。",
                      "required_global": field != "body.other_stable_features" and field != "rendering.baseline_style",
                      "required_for": required[field]})
    return {"schema_version": 1, "entity_type": "identity", "entity_ref": "character.identity", "entity_id": "arco",
            "display_name_zh": "阿尔可", "revision": 1, "last_calibration_id": calibration_id, "facts": facts,
            "working_identity_description": "阿尔可：冰银浅蓝长发并带粉色发梢、红色眼睛、纤细修长体型；服装、角和姿势不属于本描述。",
            "identity_primary": "identity-p01-crop", "identity_secondary": ["identity-p01", "identity-p03"],
            "identity_detail": [], "coverage": {"portrait": "READY", "upper_body": "READY", "full_body": "READY", "back_view": "INCOMPLETE"},
            "global_reference_readiness": "PARTIAL", "evidence_source_family_count": 1, "canon_count": 0, "visual_consensus_count": 0}


def asset_record(asset_id: str, source: Path, managed: str, role: str, calibration_id: str, *, derived_from=None, crop_box=None, priority=None, preferred=None) -> dict:
    record = {"asset_id": asset_id, "path": managed, "asset_status": "VERIFIED", "expression_id": None, "variant_id": None,
              "state_ids": [], "reference_level": "primary" if priority == "primary" else "secondary", "roles": [role],
              "purpose_note_zh": "Identity Calibration candidate", "source_kind": "official", "source_authority": "user_attested_official",
              "source_group_id": "arco-standing-open-arms-oblique-01", "source_family_id": "arco-official-standing-art-system-01",
              "face_slot_id": None, "face_slot_membership": None, "expression_set_id": None, "view_class": "three_quarter_right",
              "derived_from_asset_id": derived_from, "provenance": {"original_filename": source.name, "source_path": str(source),
              "source_note": "用户确认的官方 standing-art；未虚构 URL、资源包路径或发布日期。", "ingest_calibration_id": calibration_id},
              "sha256": None, "can_be_generation_reference": True if priority else False,
              "generation_reference": None}
    if crop_box:
        record["operation"] = {"kind": "deterministic_lossless_crop", "crop_box_px": crop_box, "source_sha256": sha256(source), "evidence_independence": "none"}
    if priority:
        record["generation_reference"] = {"priority": priority, "supported_roles": ["identity_reference"],
          "preferred_for": preferred or [], "excluded_for": ["back_view"], "coverage": {"visible_fields": ["identity", "hair", "eyes", "face"], "view_angles": ["three_quarter_right"]},
          "inheritance": {"identity": "inherit", "outfit": "do_not_inherit", "pose": "do_not_inherit", "expression": "do_not_inherit"}}
    return record


def create() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    calibration_id = f"cal-{stamp}-{secrets.token_hex(3)}"
    staging = ROOT / "calibration" / "staging" / calibration_id
    candidate = staging / "candidate-root"
    (candidate / "character").mkdir(parents=True)
    (staging / "assets").mkdir(parents=True)
    shutil.copy2(ROOT / "character" / "identity.yaml", candidate / "character" / "identity.base.yaml")
    shutil.copy2(ROOT / "character" / "assets.yaml", candidate / "character" / "assets.base.yaml")
    shutil.copy2(ROOT / "character" / "expressions.yaml", candidate / "character" / "expressions.yaml")
    shutil.copy2(ROOT / "variants" / "index.yaml", candidate / "variants.index.yaml")
    identity = build_identity(calibration_id)
    dump(candidate / "character" / "identity.yaml", identity)
    assets_data = yaml.safe_load((ROOT / "character" / "assets.yaml").read_text(encoding="utf-8"))
    assets = assets_data["assets"]
    new = []
    for aid, src, rel, role, prio, pref in [("identity-p01", P01, "assets/arco/identity/p01-full.png", "identity_evidence", "secondary", ["full_body"]), ("identity-p03", P03, "assets/arco/identity/p03-alternate.png", "identity_evidence", "supplemental", ["portrait", "upper_body", "full_body"])]:
        out = candidate / rel; out.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, out)
        rec = asset_record(aid, src, rel, role, calibration_id, priority=prio, preferred=pref); rec["sha256"] = sha256(out); new.append(rec)
    crop_rel = "assets/arco/identity/p01-face-hair-crop.png"; crop = candidate / crop_rel; crop.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(P01), "-vf", "crop=1700:1500:250:0", "-frames:v", "1", str(crop)], check=True)
    crop_rec = asset_record("identity-p01-crop", P01, crop_rel, "identity_reference", calibration_id, derived_from="identity-p01", crop_box=[250, 0, 1700, 1500], priority="primary", preferred=["portrait", "upper_body"]); crop_rec["sha256"] = sha256(crop); new.append(crop_rec)
    assets_data["revision"] = 2; assets_data["last_calibration_id"] = calibration_id; assets_data["assets"] = assets + new
    dump(candidate / "character" / "assets.yaml", assets_data)
    base_hashes = {}
    for rel in ["character/identity.yaml", "character/assets.yaml", "character/expressions.yaml", "variants/index.yaml", "calibration/history/cal-20260910T145805Z-61c3e9.yaml"]:
        p = ROOT / rel; base_hashes[rel] = sha256(p) if p.is_file() else None
    history = {"schema_version": 1, "calibration_id": calibration_id, "draft": True, "publication_status": "NOT_PUBLISHED", "source_family_independence": {"count": 1}, "candidate_assets": [{"asset_id": x["asset_id"], "source": x["provenance"]} for x in new], "rejected_candidates": [{"id": "P02", "reason": "closed eyes and swimsuit/horn/cape contamination"}, {"id": "P04", "reason": "closed eyes and cape/armor/horn/headwear contamination"}], "user_adjudication": {"P01_to_primary_parent": True, "P03_to_alternate_secondary": True, "provenance": "user_attested_official"}, "observations": ["silver-blue hair with pink tips", "red irises in open-eye composites", "slender long-limbed proportions", "back-view evidence unavailable"], "identity_claim_status_counts": {"UNCERTAIN": 10, "TODO_CALIBRATION": 4, "VISUAL_CONSENSUS": 0, "CANON": 0}, "coverage": identity["coverage"], "global_reference_readiness": "PARTIAL", "generation_permissions": {x["asset_id"]: x.get("generation_reference") for x in new}, "publication_not_executed": True}
    dump(staging / "history-draft.yaml", history)
    manifest = annotate_manifest({"schema_version": 3, "calibration_id": calibration_id, "transaction_id": f"tx-identity-{calibration_id}", "publication_state": "STAGED_VALIDATED_AWAITING_AUTHORIZATION", "publication_authorized": False, "base_state": {"expression_library_revision": 1, "asset_index_revision": 1, "identity_revision": 0}, "base_hashes": base_hashes, "files": [{"target_path": "character/identity.yaml", "staged_path": "candidate-root/character/identity.yaml", "before_hash": base_hashes["character/identity.yaml"], "candidate_hash": sha256(candidate / "character/identity.yaml"), "after_hash": None, "backup_path": "backups/character/identity.yaml", "rollback_action": "restore_backup", "publication_status": "pending"}, {"target_path": "character/assets.yaml", "staged_path": "candidate-root/character/assets.yaml", "before_hash": base_hashes["character/assets.yaml"], "candidate_hash": sha256(candidate / "character/assets.yaml"), "after_hash": None, "backup_path": "backups/character/assets.yaml", "rollback_action": "restore_backup", "publication_status": "pending"}], "publication_status": "pending"})
    dump(staging / "publish-manifest.yaml", manifest)
    dump(staging / "calibration-lock.yaml", {"calibration_id": calibration_id, "state": "staged_validated_awaiting_authorization", "targets": ["character.identity", "character.assets"]})
    (staging / "source-provenance.json").write_text(json.dumps({"P01": str(P01), "P03": str(P03), "P02": "history-only", "P04": "history-only"}, ensure_ascii=False, indent=2), encoding="utf-8")
    return staging


if __name__ == "__main__":
    print(create())
