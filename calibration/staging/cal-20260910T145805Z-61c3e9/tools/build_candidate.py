#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import yaml

CAL_ID = "cal-20260910T145805Z-61c3e9"
TX_ID = "tx-expression-library-20260910T145805Z-61c3e9"
ROOT = Path(r"D:\learn\Arco")
STAGE = ROOT / "calibration" / "staging" / CAL_ID
CANDIDATE = STAGE / "candidate-root"
SOURCE = Path(r"D:\阿尔可\阿尔可立绘\アルコ")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dump(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def copy_baseline() -> None:
    for name in ("SKILL.md",):
        shutil.copy2(ROOT / name, CANDIDATE / name)
    for folder in ("character", "variants", "references", "scripts", "assets/templates"):
        src = ROOT / folder
        dst = CANDIDATE / folder
        shutil.copytree(src, dst, dirs_exist_ok=True)


A = list(range(5793, 5814))
B = [7830, 7865, 7914, 7963, 7998, 8033, 8082, 8131, 8166, 8201, 8250, 8299, 8334, 8369, 8418, 8467, 8516, 8551, 8600, 8649, 8709, 8769]

# Semantic records are the locked adjudication result. The two duplicate official files share the same semantic id.
SEM = {
    "a_l_5793": ("expr-oblique-proud-confident-01", "高傲且自信", "Proud and confident", ["proud", "confident", "composed"], "moderate", "medium", "open-eyes-small-open-mouth-01"),
    "a_l_5794": ("expr-oblique-neutral-serious-01", "中性严肃", "Neutral and serious", ["neutral", "serious", "composed"], "subtle", "high", "neutral-open-eyes-closed-mouth-01"),
    "a_l_5795": ("expr-oblique-closed-neutral-01", "闭眼平静", "Eyes-closed neutral", ["eyes_closed", "neutral", "calm"], "subtle", "high", "closed-eyes-closed-mouth-01"),
    "a_l_5796": ("expr-oblique-cheerful-smile-01", "开心微笑", "Cheerful smile", ["happy", "smiling", "eyes_open"], "moderate", "high", "open-eyes-smile-01"),
    "a_l_5797": ("expr-oblique-cheerful-laugh-01", "睁眼大笑", "Open-eye cheerful laugh", ["happy", "laughing", "mouth_wide_open"], "strong", "high", "open-eyes-wide-open-mouth-01"),
    "a_l_5798": ("expr-oblique-closed-eye-smile-01", "闭眼微笑", "Eyes-closed smile", ["happy", "smiling", "eyes_closed"], "moderate", "high", "closed-eyes-smile-01"),
    "a_l_5799": ("expr-oblique-closed-eye-laugh-01", "闭眼大笑", "Eyes-closed laugh", ["happy", "laughing", "eyes_closed"], "strong", "high", "closed-eyes-wide-open-mouth-01"),
    "a_l_5800": ("expr-oblique-concerned-01", "担忧", "Concerned", ["concerned", "uneasy"], "moderate", "high", "raised-inner-brows-closed-mouth-01"),
    "a_l_5801": ("expr-oblique-angry-complaint-01", "生气抱怨", "Angry complaint", ["angry", "complaining", "speaking"], "strong", "medium", "lowered-eyelids-open-mouth-01"),
    "a_l_5802": ("expr-oblique-closed-eye-displeased-01", "闭眼不满", "Eyes-closed displeasure", ["eyes_closed", "displeased", "restrained"], "moderate", "high", "closed-eyes-downturned-mouth-01"),
    "a_l_5803": ("expr-oblique-angry-eyes-closed-01", "生气地闭眼", "Angry with eyes closed", ["angry", "eyes_closed", "mouth_open"], "strong", "medium", "closed-eyes-wide-open-mouth-high-tension-01"),
    "a_l_5804": ("expr-oblique-displeased-01", "不满", "Displeased", ["displeased", "stern", "eyes_open"], "moderate", "high", "half-lidded-closed-mouth-01"),
    "a_l_5805": ("expr-oblique-concerned-questioning-01", "担忧询问", "Concerned questioning", ["concerned", "questioning", "speaking"], "moderate", "medium", "raised-inner-brows-open-mouth-01"),
    "a_l_5806": ("expr-oblique-closed-eye-weary-01", "闭眼无奈", "Eyes-closed weariness", ["eyes_closed", "weary", "resigned"], "moderate", "high", "closed-eyes-flat-mouth-01"),
    "a_l_5807": ("expr-oblique-resigned-drained-01", "无奈和心累", "Resigned and emotionally drained", ["resigned", "weary", "emotionally_drained"], "moderate", "medium", "closed-eyes-open-mouth-low-tension-01"),
    "a_l_5808": ("expr-oblique-obvious-surprise-01", "明显惊讶", "Obvious surprise", ["surprised", "wide_eyes", "mouth_open"], "strong", "high", "wide-eyes-open-mouth-01"),
    "a_l_5809": ("expr-oblique-gentle-smile-01", "温和微笑", "Gentle smile", ["gentle", "smiling", "eyes_open"], "subtle", "high", "gentle-open-eyes-smile-01"),
    "a_l_5810": ("expr-oblique-cold-displeased-01", "冷淡不满", "Cold displeasure", ["cold", "displeased", "half_lidded"], "moderate", "high", "half-lidded-closed-mouth-01"),
    "a_l_5811": ("expr-oblique-reproachful-resigned-01", "责怪和无奈", "Reproachful and resigned", ["reproachful", "resigned", "weary"], "moderate", "medium", "half-lidded-small-open-mouth-01"),
    "a_l_5812": ("expr-oblique-low-gaze-contemplation-01", "低视线沉思", "Low-gaze contemplation", ["contemplative", "low_gaze", "composed"], "subtle", "high", "low-gaze-closed-mouth-01"),
    "a_l_5813": ("expr-oblique-dejected-complaint-01", "低落抱怨", "Dejected complaint", ["dejected", "complaining", "speaking"], "strong", "medium", "low-gaze-open-mouth-01"),
    "b_l_7830": ("expr-frontal-attentive-neutral-01", "专注中性", "Attentive neutral", ["attentive", "neutral", "eyes_open"], "subtle", "high", "neutral-open-eyes-closed-mouth-01"),
    "b_l_7865": ("expr-frontal-closed-neutral-01", "闭眼平静", "Eyes-closed neutral", ["eyes_closed", "neutral", "calm"], "subtle", "high", "closed-eyes-closed-mouth-01"),
    "b_l_7914": ("expr-frontal-cheerful-smile-01", "开心微笑", "Cheerful smile", ["happy", "smiling", "eyes_open"], "moderate", "high", "open-eyes-smile-01"),
    "b_l_7963": ("expr-frontal-excited-shout-01", "兴奋呼喊", "Excited shout", ["excited", "shouting", "wide_eyes"], "strong", "high", "wide-eyes-open-mouth-01"),
    "b_l_7998": ("expr-frontal-closed-eye-smile-01", "闭眼微笑", "Eyes-closed smile", ["happy", "smiling", "eyes_closed"], "moderate", "high", "closed-eyes-smile-01"),
    "b_l_8033": ("expr-frontal-closed-eye-laugh-01", "闭眼大笑", "Eyes-closed laugh", ["happy", "laughing", "eyes_closed"], "strong", "high", "closed-eyes-wide-open-mouth-01"),
    "b_l_8082": ("expr-frontal-concerned-01", "担忧", "Concerned", ["concerned", "uneasy"], "moderate", "high", "raised-inner-brows-closed-mouth-01"),
    "b_l_8131": ("expr-frontal-frightened-exclamation-01", "害怕惊呼", "Frightened exclamation", ["frightened", "startled", "exclaiming"], "strong", "medium", "raised-inner-brows-open-mouth-01"),
    "b_l_8166": ("expr-frontal-difficult-deliberation-01", "艰难思索", "Difficult deliberation", ["deliberating", "strained", "eyes_closed"], "moderate", "medium", "closed-eyes-downturned-mouth-01"),
    "b_l_8201": ("expr-frontal-resigned-deliberative-speech-01", "艰难思索后的无奈发言", "Resigned speech after difficult deliberation", ["deliberating", "resigned", "speaking", "eyes_closed"], "strong", "medium", "closed-eyes-wide-open-mouth-high-tension-01"),
    "b_l_8250": ("expr-frontal-neutral-serious-01", "中性严肃", "Neutral and serious", ["neutral", "serious", "composed"], "subtle", "high", "neutral-open-eyes-closed-mouth-01"),
    "b_l_8299": ("expr-frontal-surprised-saddened-01", "惊讶和难过", "Surprised and saddened", ["surprised", "sad", "vulnerable"], "moderate", "medium", "open-eyes-small-open-mouth-01"),
    "b_l_8334": ("expr-frontal-eyes-closed-composed-01", "闭眼克制", "Eyes-closed composure", ["eyes_closed", "composed", "restrained"], "subtle", "high", "closed-eyes-flat-mouth-01"),
    "b_l_8369": ("expr-frontal-eyes-closed-sigh-01", "闭眼叹气", "Eyes-closed sigh", ["eyes_closed", "sighing", "weary"], "subtle", "medium", "closed-eyes-open-mouth-low-tension-01"),
    "b_l_8418": ("expr-frontal-obvious-surprise-01", "明显惊讶", "Obvious surprise", ["surprised", "wide_eyes", "mouth_open"], "strong", "high", "wide-eyes-open-mouth-01"),
    "b_l_8467": ("expr-frontal-neutral-serious-01", "中性严肃", "Neutral and serious", ["neutral", "serious", "composed"], "subtle", "high", "neutral-open-eyes-closed-mouth-01"),
    "b_l_8516": ("expr-frontal-excited-toothy-grin-01", "兴奋地呲牙", "Excited toothy grin", ["excited", "toothy_grin", "eyes_open", "high_tension"], "strong", "medium", "excited-toothy-grin-01"),
    "b_l_8551": ("expr-frontal-extreme-excited-toothy-grin-01", "特别兴奋地呲牙", "Extremely excited toothy grin", ["highly_excited", "toothy_grin", "eyes_closed", "high_tension"], "strong", "medium", "excited-toothy-grin-01"),
    "b_l_8600": ("expr-frontal-displeased-01", "不满", "Displeased", ["displeased", "stern", "half_lidded"], "moderate", "high", "half-lidded-closed-mouth-01"),
    "b_l_8649": ("expr-frontal-impatient-speaking-01", "不耐烦说话", "Impatient speaking", ["impatient", "displeased", "speaking"], "moderate", "medium", "half-lidded-small-open-mouth-01"),
    "b_l_8709": ("expr-frontal-attentive-speaking-01", "专注轻声说话", "Attentive soft speech", ["attentive", "speaking", "calm"], "subtle", "high", "open-eyes-small-open-mouth-01"),
    "b_l_8769": ("expr-frontal-casual-speaking-01", "不经意地说话", "Casual speaking", ["casual", "speaking", "offhand"], "subtle", "medium", "open-eyes-small-open-mouth-01"),
}


def visual_features(tags: list[str]) -> dict:
    joined = set(tags)
    eyes = "closed" if "eyes_closed" in joined else "wide_open" if "wide_eyes" in joined else "open"
    mouth = "wide_open" if {"laughing", "shouting", "exclaiming", "mouth_open"} & joined else "clenched_teeth" if "toothy_grin" in joined else "slightly_open" if {"speaking", "questioning", "complaining", "sighing"} & joined else "closed"
    return {"eyes": eyes, "eyebrows": "expression-dependent", "mouth": mouth, "gaze": "forward_or_slot_aligned", "face_tension": "high" if "high_tension" in joined or "strained" in joined else "moderate"}


def build() -> None:
    copy_baseline()
    assets = []
    source_hashes = {}
    by_set = {"expression-set-oblique-right-01": [], "expression-set-frontal-01": []}
    for prefix, numbers, slot, view, set_id, group in (
        ("a_l", A, "face-slot-oblique-right-01", "three_quarter_right", "expression-set-oblique-right-01", "arco-expression-oblique-01"),
        ("b_l", B, "face-slot-frontal-01", "frontal", "expression-set-frontal-01", "arco-expression-frontal-01"),
    ):
        for ordinal, number in enumerate(numbers, 1):
            key = f"{prefix}_{number}"
            asset_id = f"arco-expr-{'oblique' if prefix == 'a_l' else 'frontal'}-{ordinal:03d}"
            src = SOURCE / f"アルコ_{key}.png"
            rel = Path("assets/arco/expressions") / ("oblique" if prefix == "a_l" else "frontal") / f"{asset_id}.png"
            dst = CANDIDATE / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            source_hashes[str(src)] = sha(src)
            if sha(src) != sha(dst):
                raise RuntimeError(f"copy hash mismatch: {src}")
            assets.append({
                "asset_id": asset_id, "expression_id": SEM[key][0], "path": rel.as_posix(),
                "asset_status": "VERIFIED", "roles": ["expression_evidence"], "reference_level": "detail",
                "view_angle": "front_three_quarter" if prefix == "a_l" else "front", "view_class": view,
                "face_slot_id": slot, "face_slot_membership": "CONFIRMED", "expression_set_id": set_id,
                "source_family_id": "arco-official-standing-art-system-01", "source_group_id": group,
                "source_kind": "official", "source_authority": "primary_official", "derived_from_asset_id": None,
                "provenance": {"original_filename": src.name, "source_path": str(src), "ingest_calibration_id": CAL_ID},
                "sha256": sha(dst),
            })
            by_set[set_id].append(asset_id)

    asset_doc = {"schema_version": 2, "entity_type": "asset_registry", "entity_ref": "character.assets", "revision": 1, "last_calibration_id": CAL_ID, "assets": assets}
    dump(CANDIDATE / "character/assets.yaml", asset_doc)

    seen = set()
    semantics = []
    for key, item in SEM.items():
        sid, zh, en, tags, intensity, confidence, sim = item
        if sid in seen:
            continue
        seen.add(sid)
        semantics.append({"expression_id": sid, "display_name_zh": zh, "display_name_en": en, "official_label": None, "official_label_source": None, "visual_features": visual_features(tags), "semantic_tags": tags, "intensity": intensity, "semantic_confidence": confidence, "semantic_review_status": "APPROVED", "similarity_group_ids": [sim], "expression_cluster_id": None})

    clusters = [
        ("neutral-serious-01", ["expr-oblique-neutral-serious-01", "expr-frontal-neutral-serious-01"]),
        ("closed-neutral-01", ["expr-oblique-closed-neutral-01", "expr-frontal-closed-neutral-01"]),
        ("cheerful-smile-01", ["expr-oblique-cheerful-smile-01", "expr-frontal-cheerful-smile-01"]),
        ("closed-eye-smile-01", ["expr-oblique-closed-eye-smile-01", "expr-frontal-closed-eye-smile-01"]),
        ("closed-eye-laugh-01", ["expr-oblique-closed-eye-laugh-01", "expr-frontal-closed-eye-laugh-01"]),
        ("concerned-01", ["expr-oblique-concerned-01", "expr-frontal-concerned-01"]),
        ("displeased-01", ["expr-oblique-cold-displeased-01", "expr-frontal-displeased-01"]),
        ("obvious-surprise-01", ["expr-oblique-obvious-surprise-01", "expr-frontal-obvious-surprise-01"]),
    ]
    semantic_by_id = {x["expression_id"]: x for x in semantics}
    for cid, members in clusters:
        for member in members:
            semantic_by_id[member]["expression_cluster_id"] = cid
    sim_ids = sorted({x["similarity_group_ids"][0] for x in semantics})
    expression_doc = {
        "schema_version": 2, "entity_type": "expression_library", "entity_ref": "character.expressions", "revision": 1, "last_calibration_id": CAL_ID, "scope": "arco",
        "direction_convention": "left/right means the direction the character face points on the image plane, never the side perceived by the observer",
        "semantic_review_status_values": ["UNREVIEWED", "REVIEW_REQUIRED", "APPROVED", "DISPUTED"],
        "prompt_compiler_gate": {"default_semantic_review_status": "APPROVED", "nonapproved_visual_features_allowed": True},
        "source_families": [{"source_family_id": "arco-official-standing-art-system-01", "source_kind": "official"}],
        "source_groups": [
            {"source_group_id": "arco-expression-oblique-01", "source_family_id": "arco-official-standing-art-system-01", "face_slot_id": "face-slot-oblique-right-01", "member_asset_ids": by_set["expression-set-oblique-right-01"]},
            {"source_group_id": "arco-expression-frontal-01", "source_family_id": "arco-official-standing-art-system-01", "face_slot_id": "face-slot-frontal-01", "member_asset_ids": by_set["expression-set-frontal-01"]},
        ],
        "face_slots": [
            {"face_slot_id": "face-slot-oblique-right-01", "view_class": "three_quarter_right", "membership_status": "CONFIRMED"},
            {"face_slot_id": "face-slot-frontal-01", "view_class": "frontal", "membership_status": "CONFIRMED"},
        ],
        "pose_families": [
            {"pose_family_id": "open-arms-oblique", "view_class": "three_quarter_right"},
            {"pose_family_id": "raised-fists-frontal", "view_class": "frontal"},
            {"pose_family_id": "crossed-arms-frontal", "view_class": "frontal"},
        ],
        "expression_sets": [
            {"expression_set_id": "expression-set-oblique-right-01", "face_slot_id": "face-slot-oblique-right-01", "member_asset_ids": by_set["expression-set-oblique-right-01"], "pose_compatibility": [{"target_type": "pose_family", "target_id": "open-arms-oblique", "status": "PROVISIONAL"}]},
            {"expression_set_id": "expression-set-frontal-01", "face_slot_id": "face-slot-frontal-01", "member_asset_ids": by_set["expression-set-frontal-01"], "pose_compatibility": [{"target_type": "pose_family", "target_id": "raised-fists-frontal", "status": "PROVISIONAL"}, {"target_type": "pose_family", "target_id": "crossed-arms-frontal", "status": "PROVISIONAL"}]},
        ],
        "similarity_groups": [{"similarity_group_id": x, "basis": "visual_structure_similarity_only"} for x in sim_ids],
        "expression_clusters": [{"expression_cluster_id": cid, "cluster_status": "CONFIRMED", "member_expression_ids": members} for cid, members in clusters],
        "composite_compatibility": [],
        "semantics": semantics,
    }
    dump(CANDIDATE / "character/expressions.yaml", expression_doc)

    review_keys = ["a_l_5793", "a_l_5801", "a_l_5803", "a_l_5805", "a_l_5807", "a_l_5808", "a_l_5811", "a_l_5812", "a_l_5813", "b_l_7963", "b_l_8131", "b_l_8166", "b_l_8201", "b_l_8299", "b_l_8369", "b_l_8516", "b_l_8551", "b_l_8649", "b_l_8769"]
    raw = {"a_l_5793": "高傲且自信的表情", "b_l_8551": "特别兴奋的呲牙😁"}
    cancelled = ["strong-exclamation-01", "concerned-speech-01", "strained-upset-01", "strained-speech-01", "cold-speech-01", "soft-speech-01", "closed-speech-01", "happy-laugh-01"]
    decisions = []
    for key in review_keys:
        sid, zh, en, tags, intensity, confidence, sim = SEM[key]
        decisions.append({"asset_source_key": key, "original_candidate_name": sid.replace("expr-oblique-", "").replace("expr-frontal-", ""), "user_raw_decision": raw.get(key, zh), "final_expression_id": sid, "display_name_zh": zh, "display_name_en": en, "semantic_tags": tags, "semantic_confidence": confidence, "intensity": intensity, "semantic_review_status": "APPROVED", "expression_cluster_id": semantic_by_id[sid]["expression_cluster_id"], "similarity_group_ids": [sim]})
    pending = []
    for key, label in (("a_l_5797", "casual"), ("a_l_5799", "swimsuit"), ("a_l_5811", "school-uniform"), ("a_l_5802", "robe")):
        pending.append({
            "expression_asset_source_key": key, "relationship_status": "PENDING_TARGET_REGISTRATION", "basis": "official_full_composite_pixel_match", "calibration_id": CAL_ID,
            "faceless_composite": {"registration_status": "UNREGISTERED", "proposed_asset_id": f"arco-faceless-{label}-candidate", "original_filename": None, "source_path": None},
            "full_composite": {"registration_status": "UNREGISTERED", "proposed_asset_id": f"arco-full-{label}-candidate", "original_filename": None, "source_path": None},
            "pixel_match": {"method": "alpha-aware exact pixel back-fit", "difference_region": "expression face-layer bounds", "result": "MATCH", "confidence": "high"},
            "source_locator_status": "NOT_IN_CURRENT_PUBLICATION_UNIT",
        })
    history = {"schema_version": 2, "calibration_id": CAL_ID, "draft": True, "publication_status": "NOT_PUBLISHED", "completion_status": "NOT_COMPLETED", "publication_unit": "expression_library_v1", "semantic_adjudication": {"reviewed_count": 19, "decisions": decisions, "cancelled_provisional_clusters": cancelled}, "pending_compatibility_evidence": pending}
    dump(STAGE / "history-draft.yaml", history)

    lock = {"schema_version": 1, "calibration_id": CAL_ID, "state": "STAGED_VALIDATED_AWAITING_AUTHORIZATION", "targets": ["character.assets", "character.expressions"], "blocks": ["conflicting_calibration", "formal_write", "unauthorized_publication"], "read_only_prompt_behavior": "IGNORE_STAGING"}
    dump(STAGE / "calibration-lock.yaml", lock)

    # Candidate documentation and templates are deliberately staged, never written to the formal tree here.
    (CANDIDATE / "references/calibration/expression-schema.md").write_text("""# Expression Library schema (candidate)\n\nExpression assets and semantic records are separate. Asset roles are exactly `expression_evidence`. Face Slot membership confirms geometry only. Concrete compatibility is independent and may only reference registered targets. `APPROVED` is a human working-name approval, not CANON, and does not imply high semantic confidence. `three_quarter_right` means the character face points toward image right. Unregistered composite evidence uses `registration_status: UNREGISTERED`; proposed IDs are not Asset references.\n""", encoding="utf-8")
    (CANDIDATE / "references/core/expression-compiler.md").write_text("""# Expression compiler gate (candidate)\n\nDefault stable semantic lookup MUST select only records with `semantic_review_status: APPROVED`. Medium confidence is allowed. REVIEW_REQUIRED, UNREVIEWED and DISPUTED records may contribute explicit visual features but cannot be asserted as a definite emotion. Normal prompt work reads only the published tree and never scans staging.\n""", encoding="utf-8")

    protected = [
        "character/assets.yaml", "character/expressions.yaml", "character/identity.yaml", "character/identity.md", "variants/index.yaml",
        "SKILL.md", "assets/templates/asset.yaml", "references/calibration/schema.md", "references/calibration/workflow.md", "references/core/prompt-compiler.md", "references/core/reference-routing.md", "scripts/validate_library.py", "scripts/test_validate_library.py",
    ]
    base_hashes = {p: sha(ROOT / p) for p in protected}
    files = []
    targets = ["character/assets.yaml", "character/expressions.yaml", "references/calibration/expression-schema.md", "references/core/expression-compiler.md"] + [a["path"] for a in assets]
    for target in targets:
        candidate = CANDIDATE / target
        formal = ROOT / target
        files.append({"target_path": target, "staged_path": f"candidate-root/{target}", "before_hash": sha(formal) if formal.is_file() else None, "candidate_hash": sha(candidate), "after_hash": None, "backup_path": f"backups/{target}", "rollback_action": "restore_backup" if formal.is_file() else "delete_created_file", "publication_status": "pending"})
    manifest = {
        "schema_version": 2, "calibration_id": CAL_ID, "transaction_id": TX_ID, "publication_state": "STAGED_VALIDATED_AWAITING_AUTHORIZATION", "publication_authorized": False,
        "base_state": {"expression_library_revision": 0, "asset_index_revision": 0, "identity_revision": 0}, "base_hashes": base_hashes,
        "staged_history_path": "history-draft.yaml", "history_path": f"calibration/history/{CAL_ID}.yaml", "completion_marker": f"calibration/history/{CAL_ID}.complete",
        "files": files, "transaction_sequence": ["preflight", "rollback_snapshot", "PUBLICATION_IN_PROGRESS", "file_writes", "after_hash_validation", "history_finalize", "completion_marker", "TRANSACTION_COMPLETE"],
        "failure_state": "RECOVERY_REQUIRED", "stale_state": "STALE_STAGING",
    }
    dump(STAGE / "publication/publish-manifest.yaml", manifest)
    dump(STAGE / "source-hashes.yaml", source_hashes)


if __name__ == "__main__":
    build()
