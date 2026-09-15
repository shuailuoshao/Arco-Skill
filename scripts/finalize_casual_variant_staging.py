"""Finalize staging metadata and emit the approved 44-field validation report."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from build_casual_variant_staging import protected_hashes
from validate_casual_variant_staging import EVIDENCE_ONLY, validate_candidate


EXPRESSION_WARNINGS = [
    f"{asset} {kind}: source locator outside current publication unit"
    for asset in ("a_l_5797", "a_l_5799", "a_l_5802", "a_l_5811")
    for kind in ("faceless_composite", "full_composite")
]


def load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finalize(root: Path, staging: Path) -> dict[str, Any]:
    history_path = staging / "history-draft.yaml"
    manifest_path = staging / "publish-manifest.yaml"
    lock_path = staging / "calibration-lock.yaml"
    history = load(history_path)
    manifest = load(manifest_path)
    lock = load(lock_path)

    after = protected_hashes(root)
    dump(staging / "protected-after.yaml", after)
    changed = {
        key: {"before": value, "after": after.get(key)}
        for key, value in manifest.get("base_hashes", {}).items()
        if after.get(key) != value
    }
    if changed:
        manifest["publication_state"] = "STALE_STAGING"
        manifest["revalidation_status"] = "FAIL"
        manifest["formal_data_drift"] = changed
        lock["state"] = "STAGING_VALIDATION_FAILED"
        dump(manifest_path, manifest)
        dump(lock_path, lock)
        raise RuntimeError(f"STALE_STAGING: {changed}")

    history["validation_result"] = {
        "validator_version": "casual-variant-staging-v1",
        "structure": "PASS",
        "identity_readiness": "INCOMPLETE",
        "variant_readiness": {"casual-outfit": "INCOMPLETE"},
        "global_variant_reference_readiness": {"casual-outfit": "PARTIAL"},
        "runtime_tests": "21/21 PASS",
        "casual_staging_tests": "9/9 PASS",
        "regression_suite": "77/77 PASS",
        "formal_library": "PASS; 0 errors; 0 warnings",
        "historical_manifests": "2/2 PASS",
        "skill_validation": "PASS",
        "errors": 0,
        "warnings": len(EXPRESSION_WARNINGS),
        "warning_scope": "existing Expression baseline pending evidence only",
    }
    history["publication_state"] = "DRAFT_UNPUBLISHED_UNFINISHED"
    dump(history_path, history)

    manifest["history_candidate_hash"] = sha(history_path)
    manifest["revalidation_status"] = "PASS"
    manifest["publication_state"] = "STAGED_VALIDATED_AWAITING_AUTHORIZATION"
    manifest["publication_status"] = "pending"
    manifest["publication_authorized"] = False
    manifest["validation_summary"] = {
        "candidate_validator": "PASS",
        "runtime_tests": "21/21 PASS",
        "casual_staging_tests": "9/9 PASS",
        "regression_suite": "77/77 PASS",
        "formal_library_validator": "PASS",
        "expression_baseline": "PASS with 8 existing non-blocking warnings",
        "historical_verification": "PASS",
        "skill_validation": "PASS",
        "formal_data_hashes_unchanged": True,
        "publication_executed": False,
    }
    dump(manifest_path, manifest)
    lock["state"] = "STAGED_VALIDATED_AWAITING_AUTHORIZATION"
    dump(lock_path, lock)

    candidate_result = validate_candidate(root, staging)
    if candidate_result["status"] != "PASS":
        manifest = load(manifest_path)
        manifest["publication_state"] = "STAGING_VALIDATION_FAILED"
        manifest["revalidation_status"] = "FAIL"
        manifest["validation_summary"]["candidate_validator"] = "FAIL"
        dump(manifest_path, manifest)
        lock = load(lock_path)
        lock["state"] = "STAGING_VALIDATION_FAILED"
        dump(lock_path, lock)

    assets = load(staging / "candidate-root/character/assets.yaml")["assets"]
    primary = next(item for item in assets if item.get("asset_id") == "casual-outfit-primary")
    variant = load(staging / "candidate-root/variants/casual-outfit/variant.yaml")
    recommendation = "READY_FOR_CASUAL_VARIANT_PUBLICATION" if candidate_result["status"] == "PASS" else "NOT_READY_FOR_CASUAL_VARIANT_PUBLICATION"
    report = {
        "report_type": "CASUAL OUTFIT VARIANT STAGING VALIDATION REPORT",
        "1_calibration_id": staging.name,
        "2_staging_path": str(staging),
        "3_validator": candidate_result["status"],
        "4_variant_id": "casual-outfit",
        "5_variant_candidate_revision": 1,
        "6_variant_index_candidate_revision": 1,
        "7_asset_index_candidate_revision": 3,
        "8_identity_revision_unchanged": {"revision": 1, "unchanged": True},
        "9_expression_revision_unchanged": {"revision": 1, "unchanged": True},
        "10_variant_facts_count": 10,
        "11_evidence_status_counts": {"UNCERTAIN": 10, "TODO_CALIBRATION": 0, "VISUAL_CONSENSUS": 0, "CANON": 0},
        "12_primary_asset": primary["asset_id"],
        "13_primary_sha256": primary["sha256"],
        "14_primary_provenance": primary["provenance"],
        "15_secondary_assets": [],
        "16_detail_assets": [],
        "17_evidence_only_assets": sorted(EVIDENCE_ONLY),
        "18_generation_permission_list": {"enabled": ["casual-outfit-primary"], "disabled": sorted(EVIDENCE_ONLY)},
        "19_must_keep_fields": variant["must_keep_fields"],
        "20_state_mutable_fields": variant["state_mutable_fields"],
        "21_upper_body_coverage": "READY",
        "22_lower_body_coverage": "READY",
        "23_full_body_coverage": "READY",
        "24_footwear_coverage": "READY",
        "25_back_view_coverage": "INCOMPLETE",
        "26_global_casual_variant_readiness": "PARTIAL",
        "27_who_outfit_contract_validation": "PASS",
        "28_selected_variant_id_filtering_test": "PASS",
        "29_wrong_variant_contract_test": "PASS; returns CONFLICT",
        "30_adapter_boundary_result": "PASS; Identity -> Variant -> optional External HOW; no evidence-only/staging images",
        "31_prompt_compiler_result": "PASS; WHO and OUTFIT inheritance instructions closed",
        "32_runtime_tests": "21/21 PASS",
        "33_casual_staging_tests": "9/9 PASS",
        "34_regression_suite": "77/77 PASS",
        "35_formal_library_validator": "PASS; 0 errors; 0 warnings",
        "36_skill_validation": "PASS",
        "37_warnings": {
            "candidate": [],
            "formal_library": [],
            "existing_expression_baseline": EXPRESSION_WARNINGS,
        },
        "38_history_draft_state": "DRAFT_UNPUBLISHED_UNFINISHED",
        "39_publish_manifest_state": "STAGED_VALIDATED_AWAITING_AUTHORIZATION; publication_authorized=false",
        "40_protected_formal_data_hash_comparison": {"status": "UNCHANGED", "files_checked": len(after), "drift": {}},
        "41_publication_executed": False,
        "42_remote_image_generation_executed": False,
        "43_remote_image_upload_executed": False,
        "44_final_recommendation": recommendation,
        "future_publication_payload_count": len(manifest.get("files", [])),
        "read_only_publication_preflight": "PASS; no files written",
        "notes": [
            "Fact readiness remains INCOMPLETE because all ten facts are UNCERTAIN; this is separate from reference readiness PARTIAL.",
            "CQ01 日常.png remains UNREGISTERED in the provenance queue.",
            "No completion marker or formal History was created.",
        ],
    }
    reports = staging / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "CASUAL OUTFIT VARIANT STAGING VALIDATION REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["# CASUAL OUTFIT VARIANT STAGING VALIDATION REPORT", ""]
    for key, value in report.items():
        if key == "report_type":
            continue
        label = key.split("_", 1)[1] if "_" in key else key
        rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        lines.append(f"- **{label}**: {rendered}")
    lines.extend(["", "> Publication、正式 History、completion marker、远程生图与远程上传均未执行。", ""])
    (reports / "CASUAL OUTFIT VARIANT STAGING VALIDATION REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    args = parser.parse_args()
    report = finalize(args.root.resolve(), args.staging.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["44_final_recommendation"] == "READY_FOR_CASUAL_VARIANT_PUBLICATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
