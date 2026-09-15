"""Build the user-approved Casual Outfit Variant staging candidate.

This script writes only beneath calibration/staging/<calibration-id> and never
modifies the published library.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import secrets
import shutil
from pathlib import Path
from typing import Any

import yaml


SOURCES = [
    {
        "asset_id": "casual-outfit-primary",
        "source": r"D:\阿尔可\阿尔可立绘1.png",
        "managed": "assets/arco/variants/casual-outfit/primary/casual-outfit-primary.png",
        "sha256": "bddba1d7b1bed2c21572892003ac50dc6c2340d53e8262a56b6db69b16cf1f86",
        "filename": "阿尔可立绘1.png",
        "group": "arco-standing-open-arms-oblique-01",
        "view_class": "three_quarter_right",
        "view_angle": "front_three_quarter",
        "reference_level": "primary",
        "asset_type": "full_composite",
        "purpose": "常服全身结构与生成用 OUTFIT Primary；与 identity-p01 内容相同但合同独立。",
    },
    {
        "asset_id": "casual-outfit-open-arms-no-horns-evidence",
        "source": r"D:\阿尔可\阿尔可立绘\アルコ\アルコ_a_l_5685.png",
        "managed": "assets/arco/variants/casual-outfit/evidence/open-arms-no-horns.png",
        "sha256": "06c61729cdd23ede65e7376beabe50c7f32da8276709730a750452819c367f3d",
        "filename": "アルコ_a_l_5685.png",
        "group": "arco-standing-open-arms-oblique-01",
        "view_class": "three_quarter_right",
        "view_angle": "front_three_quarter",
        "reference_level": "detail",
        "asset_type": "faceless_composite",
        "purpose": "无角 open-arms 常服结构证据；禁止生成输入。",
    },
    {
        "asset_id": "casual-outfit-open-arms-horns-evidence",
        "source": r"D:\阿尔可\阿尔可立绘\アルコ\アルコ_a_l_6592.png",
        "managed": "assets/arco/variants/casual-outfit/evidence/open-arms-horns.png",
        "sha256": "37ec7c9841d98e9676ca262eebadea0da5e3e82928b2c93d75f919faeedd5a3a",
        "filename": "アルコ_a_l_6592.png",
        "group": "arco-standing-open-arms-oblique-01",
        "view_class": "three_quarter_right",
        "view_angle": "front_three_quarter",
        "reference_level": "detail",
        "asset_type": "faceless_composite",
        "purpose": "有角同姿势对照，仅证明 horns 可与常服分离；禁止生成输入。",
    },
    {
        "asset_id": "casual-outfit-crossed-arms-evidence",
        "source": r"D:\阿尔可\阿尔可立绘\アルコ\アルコ_b_l_8781.png",
        "managed": "assets/arco/variants/casual-outfit/evidence/crossed-arms.png",
        "sha256": "4eff91bea4e535e646ad406a5e8aae5e402c337cee635feb1e6339f0eaa8d974",
        "filename": "アルコ_b_l_8781.png",
        "group": "arco-standing-crossed-arms-frontal-01",
        "view_class": "front",
        "view_angle": "front",
        "reference_level": "detail",
        "asset_type": "faceless_composite",
        "purpose": "crossed-arms 跨姿势常服证据；禁止生成输入。",
    },
    {
        "asset_id": "casual-outfit-raised-fists-evidence",
        "source": r"D:\阿尔可\阿尔可立绘\アルコ\アルコ_b_l_8783.png",
        "managed": "assets/arco/variants/casual-outfit/evidence/raised-fists.png",
        "sha256": "f8d8b38fe4ddaa3eee2d0f3d6a8e659ba25b5926a35a9fcf57f5247ed3172270",
        "filename": "アルコ_b_l_8783.png",
        "group": "arco-standing-raised-fists-frontal-01",
        "view_class": "front",
        "view_angle": "front",
        "reference_level": "detail",
        "asset_type": "faceless_composite",
        "purpose": "raised-fists frontal 常服结构证据；禁止生成输入。",
    },
]

FACTS = [
    ("outfit.silhouette", "服装整体轮廓", "白色长袖上身、黑色高腰宽腿短裤与深色长袜构成修长的高对比常服轮廓", "high", [0, 1, 2, 3, 4], ["upper_body", "full_body", "back_view"]),
    ("outfit.upper_garment.base_color", "上衣基础颜色", "白色；阴影区域可呈灰蓝", "high", [0, 1, 2, 3, 4], ["upper_body", "full_body", "back_view"]),
    ("outfit.upper_garment.structure", "上衣结构", "合身长袖衬衫，不是无袖内搭", "high", [0, 1, 2, 3, 4], ["upper_body", "full_body", "back_view"]),
    ("outfit.upper_garment.collar", "衣领结构", "白色尖角翻领", "high", [0, 1, 2, 4], ["upper_body", "full_body", "back_view"]),
    ("outfit.upper_garment.sleeves", "袖部结构", "长袖，袖口收窄至手腕", "high", [0, 1, 2, 3, 4], ["upper_body", "full_body", "back_view"]),
    ("outfit.chest_detail", "胸前细节", "红色多层褶饰领巾（jabot-like cravat），不解释为蝴蝶结", "medium", [0, 1, 2, 4], ["upper_body", "full_body", "back_view"]),
    ("outfit.torso_structure", "躯干与肩带结构", "两条黑色宽肩带连接黑色高腰短裤，中央保留白色褶饰前襟", "high", [0, 1, 2, 4], ["upper_body", "full_body", "back_view"]),
    ("outfit.lower_garment", "下装", "黑色高腰宽腿短裤，具有裙裤式蓬展轮廓", "high", [0, 1, 2, 3, 4], ["full_body", "back_view"]),
    ("outfit.legwear", "腿部服装", "深色大腿袜／过膝长袜，带独立窄吊带和金色连接扣", "high", [0, 1, 2, 3, 4], ["full_body", "back_view"]),
    ("outfit.footwear", "鞋履", "深色圆头、闭口、低跟鞋；不强判 loafer、pump 或 Mary Jane", "medium", [0, 1, 2, 3, 4], ["full_body", "back_view"]),
]

MUST_KEEP = [
    "outfit.upper_garment.base_color",
    "outfit.upper_garment.structure",
    "outfit.chest_detail",
    "outfit.torso_structure",
    "outfit.lower_garment",
    "outfit.legwear",
    "outfit.footwear",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def protected_hashes(root: Path) -> dict[str, str]:
    paths = [
        root / "character/identity.yaml",
        root / "character/assets.yaml",
        root / "character/expressions.yaml",
        root / "variants/index.yaml",
        root / "character/identity.md",
    ]
    assets = load_yaml(root / "character/assets.yaml").get("assets", [])
    paths.extend(root / item["path"] for item in assets)
    paths.extend(sorted((root / "calibration/history").glob("*.yaml")))
    paths.extend(sorted((root / "calibration/history").glob("*.complete")))
    return {path.relative_to(root).as_posix(): sha256(path) for path in paths if path.is_file()}


def asset_record(spec: dict[str, Any], calibration_id: str) -> dict[str, Any]:
    primary = spec["reference_level"] == "primary"
    record: dict[str, Any] = {
        "asset_id": spec["asset_id"],
        "path": spec["managed"],
        "asset_status": "VERIFIED",
        "expression_id": None,
        "variant_id": "casual-outfit",
        "state_ids": [],
        "reference_level": spec["reference_level"],
        "roles": ["variant_evidence"],
        "purpose_note_zh": spec["purpose"],
        "asset_type": spec["asset_type"],
        "source_kind": "official",
        "source_authority": "user_approved",
        "source_group_id": spec["group"],
        "source_family_id": "arco-official-standing-art-system-01",
        "face_slot_id": None,
        "face_slot_membership": None,
        "expression_set_id": None,
        "view_class": spec["view_class"],
        "view_angle": spec["view_angle"],
        "derived_from_asset_id": None,
        "provenance": {
            "original_filename": spec["filename"],
            "source_path": spec["source"],
            "source_note": "用户确认的官方 standing-art；来源关系沿用已批准 Design Preview，未虚构 URL 或发布日期。",
            "ingest_calibration_id": calibration_id,
        },
        "sha256": spec["sha256"],
        "can_be_generation_reference": primary,
    }
    if primary:
        record.update({
            "evidence_independence": "none",
            "content_equivalent_to_asset_id": "identity-p01",
            "generation_reference": {
                "priority": "primary",
                "supported_roles": ["outfit_reference"],
                "preferred_for": ["portrait", "upper_body", "full_body"],
                "excluded_for": ["back_view"],
                "coverage": {
                    "profiles": ["portrait", "upper_body", "full_body"],
                    "visible_fields": [
                        "variant.visible_headwear_accessories",
                        "variant.upper_body_outfit",
                        "variant.full_outfit",
                        "variant.footwear",
                    ],
                    "view_angles": ["three_quarter_right"],
                    "occluded_fields": ["variant.back_outfit"],
                },
                "inheritance": {
                    "outfit": "inherit",
                    "identity": "do_not_inherit",
                    "face": "do_not_inherit",
                    "hair": "do_not_inherit",
                    "eyes": "do_not_inherit",
                    "body_proportions": "do_not_inherit",
                    "pose": "do_not_inherit",
                    "expression": "do_not_inherit",
                },
            },
        })
    return record


def build(root: Path, adjudication_path: Path | None = None) -> Path:
    now = dt.datetime.now(dt.timezone.utc)
    calibration_id = f"cal-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    staging = root / "calibration/staging" / calibration_id
    if staging.exists():
        raise RuntimeError(f"Calibration already exists: {staging}")

    for spec in SOURCES:
        source = Path(spec["source"])
        if not source.is_file() or sha256(source) != spec["sha256"]:
            raise RuntimeError(f"CASUAL_VARIANT_PROVENANCE_INCOMPLETE: {source}")

    base_hashes = protected_hashes(root)
    identity = load_yaml(root / "character/identity.yaml")
    assets_before = load_yaml(root / "character/assets.yaml")
    expressions = load_yaml(root / "character/expressions.yaml")
    variants_before = load_yaml(root / "variants/index.yaml")
    if (identity.get("revision"), assets_before.get("revision"), expressions.get("revision"), variants_before.get("revision")) != (1, 2, 1, 0):
        raise RuntimeError("STALE_STAGING: formal revisions no longer match the approved baseline")

    candidate_root = staging / "candidate-root"
    candidate_assets = dict(assets_before)
    candidate_assets["revision"] = 3
    candidate_assets["last_calibration_id"] = calibration_id
    candidate_assets["assets"] = list(assets_before["assets"]) + [asset_record(item, calibration_id) for item in SOURCES]

    variant_index = dict(variants_before)
    variant_index["revision"] = 1
    variant_index["last_calibration_id"] = calibration_id
    variant_index["variants"] = [{
        "variant_id": "casual-outfit",
        "path": "variants/casual-outfit/variant.yaml",
        "display_name_zh": "常服",
        "display_name_en": "Casual Outfit",
        "lifecycle_status": "published",
    }]

    evidence_ids = [item["asset_id"] for item in SOURCES]
    facts = []
    for field_id, display, value, confidence, indices, required_for in FACTS:
        facts.append({
            "field_id": field_id,
            "display_name_zh": display,
            "value": value,
            "status": "UNCERTAIN",
            "evidence_ids": [evidence_ids[index] for index in indices],
            "conflicts": [],
            "note_zh": f"同一 official standing-art source family 的跨姿势工作事实；visual confidence: {confidence}。用户批准不等于 CANON 或 VISUAL_CONSENSUS。",
            "required_global": True,
            "required_for": required_for,
        })

    variant = {
        "schema_version": 1,
        "entity_type": "variant",
        "entity_ref": "variants.casual-outfit",
        "variant_id": "casual-outfit",
        "display_name_zh": "常服",
        "display_name_en": "Casual Outfit",
        "lifecycle_status": "published",
        "revision": 1,
        "last_calibration_id": calibration_id,
        "facts": facts,
        "reference_asset_ids": {
            "primary": ["casual-outfit-primary"],
            "secondary": [],
            "detail": [],
        },
        "state_mutable_fields": [
            "overlay.horns", "overlay.cape", "overlay.weapon", "overlay.temporary_prop",
        ],
        "must_keep_fields": MUST_KEEP,
        "state_groups": {},
        "state_files": [],
        "known_generation_risks": [
            "Primary includes Arco identity, pose and expression; Reference Contract must inherit outfit only.",
            "No rear outfit evidence; hidden back garment geometry must not be inferred.",
            "Horns are a separable overlay observation, not a Casual Variant fact or Must Keep field.",
        ],
        "coverage": {
            "upper_body": "READY",
            "lower_body": "READY",
            "full_body": "READY",
            "footwear": "READY",
            "back_view": "INCOMPLETE",
            "overall": "PARTIAL",
        },
    }

    dump_yaml(candidate_root / "character/assets.yaml", candidate_assets)
    dump_yaml(candidate_root / "variants/index.yaml", variant_index)
    dump_yaml(candidate_root / "variants/casual-outfit/variant.yaml", variant)
    notes = f"""---
source_entity: variants.casual-outfit
source_revision: 1
---

# 常服 / Casual Outfit

本说明对应 Calibration `{calibration_id}` 的候选 revision 1。结构化事实以 `variant.yaml` 为准。

- Primary 仅定义 OUTFIT，不定义 WHO、pose 或 expression。
- horns 不属于本 Variant 的 Must Keep；当前只记录为可分离 overlay 观察。
- back-view 缺少正式证据，因此保持 `INCOMPLETE`。
- 全部10项工作事实为 `UNCERTAIN`；用户批准不等于 `CANON` 或 `VISUAL_CONSENSUS`。
"""
    notes_path = candidate_root / "variants/casual-outfit/notes.md"
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.write_text(notes, encoding="utf-8")

    for spec in SOURCES:
        destination = candidate_root / spec["managed"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(spec["source"]), destination)
        if sha256(destination) != spec["sha256"]:
            raise RuntimeError(f"Copy hash mismatch: {destination}")

    ledger = {
        "calibration_id": calibration_id,
        "source_family_id": "arco-official-standing-art-system-01",
        "accepted_assets": SOURCES,
        "provenance_queue": [{
            "candidate_id": "CQ01",
            "original_filename": "日常.png",
            "source_path": r"D:\阿尔可\日常.png",
            "sha256": "b0d7d5828c91d96e3a8223eecaa0ffc878c1f932c297f5e6ccec5fb1cf1a1dd2",
            "registration_status": "UNREGISTERED",
            "reason": "official provenance not established; History only",
        }],
        "independence_note": "CA01–CA05 are one source family; pose/group differences do not create independent source families.",
    }
    dump_yaml(staging / "source-provenance.yaml", ledger)

    adjudication_text = "User approved the Casual Outfit Design Preview and explicitly authorized staging + validation only."
    if adjudication_path and adjudication_path.is_file():
        adjudication_text = adjudication_path.read_text(encoding="utf-8")
    (staging / "user-adjudication.txt").write_text(adjudication_text, encoding="utf-8")

    history = {
        "schema_version": 1,
        "calibration_id": calibration_id,
        "timestamp": now.isoformat(),
        "operation": "create_variant",
        "publication_state": "DRAFT_UNPUBLISHED_UNFINISHED",
        "user_confirmed": True,
        "confirmed_at": now.isoformat(),
        "reason": "Create the approved Arco Casual Outfit Variant candidate with evidence and an outfit-only generation Primary.",
        "user_adjudication": {
            "original_text_path": "user-adjudication.txt",
            "sha256": sha256(staging / "user-adjudication.txt"),
        },
        "evidence_ids": evidence_ids,
        "candidate_inventory": ledger,
        "observations": [{
            "observation_id": "casual-outfit-cross-pose-structure",
            "field_ref": "outfit.silhouette",
            "evidence_ids": evidence_ids,
            "observation": "三个姿势组重复显示白色长袖上衣、红色胸饰、黑色宽肩带、高腰宽腿短裤、深色长袜及闭口鞋。",
            "intrinsic_interpretation": "过滤姿势褶皱、遮挡和角层后，这些结构构成同一套常服的工作描述。",
            "rendering_factors": {"lighting_sensitive": True, "pose_sensitive": True, "perspective_sensitive": True, "occlusion": "crossed-arms and hair", "other": ["single source family"]},
            "confidence": "high",
            "comparison": {"corroborating_evidence_ids": evidence_ids, "conflicting_evidence_ids": []},
            "proposed_status": "UNCERTAIN",
            "note": "Multiple source groups do not increase source-family independence.",
        }],
        "intrinsic_outfit_interpretation": {fact[0]: fact[2] for fact in FACTS},
        "horn_no_horn_analysis": {
            "pair": ["casual-outfit-open-arms-no-horns-evidence", "casual-outfit-open-arms-horns-evidence"],
            "conclusion": "horns are separable from outfit",
            "not_concluded": "horns are a State or a Casual Variant fact",
        },
        "primary_decision": {"asset_id": "casual-outfit-primary", "role": "outfit_reference", "secondary": [], "detail": []},
        "must_keep_fields": MUST_KEEP,
        "state_mutable_fields": variant["state_mutable_fields"],
        "coverage": variant["coverage"],
        "reference_contract": candidate_assets["assets"][-5]["generation_reference"]["inheritance"],
        "targets": [
            {"entity_ref": "variants.index", "target_type": "variant_index", "target_id": "casual-outfit", "revision_before": 0, "revision_after": 1, "changed_fields": ["revision", "last_calibration_id", "variants"], "before": variants_before, "after": variant_index, "status_before": None, "status_after": None},
            {"entity_ref": "variants.casual-outfit", "target_type": "variant", "target_id": "casual-outfit", "revision_before": 0, "revision_after": 1, "changed_fields": ["create", "facts", "reference_asset_ids", "must_keep_fields", "state_mutable_fields", "coverage"], "before": {}, "after": variant, "status_before": None, "status_after": None},
            {"entity_ref": "character.assets", "target_type": "asset_registry", "target_id": "casual-outfit-assets", "revision_before": 2, "revision_after": 3, "changed_fields": ["revision", "last_calibration_id", "assets"], "before": assets_before, "after": candidate_assets, "status_before": None, "status_after": None},
        ],
        "validation_result": {"structure": "PENDING", "errors": None, "warnings": None},
    }
    dump_yaml(staging / "history-draft.yaml", history)

    files = [
        ("character/assets.yaml", "candidate-root/character/assets.yaml", "protected_entity", None),
        ("variants/index.yaml", "candidate-root/variants/index.yaml", "protected_entity", None),
        ("variants/casual-outfit/variant.yaml", "candidate-root/variants/casual-outfit/variant.yaml", "protected_entity", None),
        ("variants/casual-outfit/notes.md", "candidate-root/variants/casual-outfit/notes.md", "protected_entity", None),
    ] + [(spec["managed"], f"candidate-root/{spec['managed']}", "immutable_data", spec["asset_id"]) for spec in SOURCES]
    manifest_files = []
    for target, staged, verification_class, asset_id in files:
        target_path = root / target
        item = {
            "target_path": target,
            "staged_path": staged,
            "before_hash": sha256(target_path) if target_path.is_file() else None,
            "candidate_hash": sha256(staging / staged),
            "after_hash": None,
            "backup_path": f"publication/rollback/{target}" if target_path.is_file() else None,
            "rollback_action": "restore_backup" if target_path.is_file() else "remove_created_file_only_if_hash_matches_candidate",
            "verification_class": verification_class,
            "publication_status": "pending",
        }
        if asset_id:
            item["asset_id"] = asset_id
        manifest_files.append(item)

    manifest = {
        "schema_version": 3,
        "calibration_id": calibration_id,
        "transaction_id": f"tx-casual-variant-{calibration_id}",
        "calibration_targets": ["variants.index", "variants.casual-outfit", "character.assets"],
        "publication_state": "STAGING_VALIDATION_PENDING",
        "publication_status": "pending",
        "publication_authorized": False,
        "revalidation_status": "PENDING",
        "base_state": {
            "identity_revision": 1,
            "asset_index_revision": 2,
            "expression_library_revision": 1,
            "variant_index_revision": 0,
        },
        "base_hashes": base_hashes,
        "tooling_hashes": {
            "scripts/reference_runtime.py": sha256(root / "scripts/reference_runtime.py"),
            "scripts/validate_library.py": sha256(root / "scripts/validate_library.py"),
            "scripts/publication_v3.py": sha256(root / "scripts/publication_v3.py"),
        },
        "verification_policy": {
            "immutable_data": "after_hash_exact",
            "protected_entity": "revision_lineage_and_history",
            "evolvable_tooling": "transaction_completion_only",
        },
        "files": manifest_files,
        "staged_history_path": "history-draft.yaml",
        "history_candidate_hash": sha256(staging / "history-draft.yaml"),
        "history_path": f"calibration/history/{calibration_id}.yaml",
        "completion_marker": f"calibration/history/{calibration_id}.complete",
        "in_progress_marker": f"calibration/history/{calibration_id}.publication_in_progress",
        "write_journal": [],
    }
    dump_yaml(staging / "publish-manifest.yaml", manifest)
    dump_yaml(staging / "calibration-lock.yaml", {
        "schema_version": 1,
        "calibration_id": calibration_id,
        "state": "STAGING_VALIDATION_IN_PROGRESS",
        "targets": manifest["calibration_targets"],
        "blocks": ["conflicting_calibration", "formal_write", "unauthorized_publication"],
        "read_only_prompt_behavior": "IGNORE_STAGING",
    })
    dump_yaml(staging / "protected-before.yaml", base_hashes)
    return staging


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path)
    args = parser.parse_args()
    staging = build(args.root.resolve(), args.adjudication)
    print(staging)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
