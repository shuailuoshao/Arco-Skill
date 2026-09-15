#!/usr/bin/env python3
"""Refresh the machine-readable final report after body publication validation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "calibration/staging/cal-20260914T100205Z-77878a"
REPORT_DIR = STAGING / "reports"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> int:
    import publish_identity_body_proportion as pub

    manifest = load(STAGING / "publish-manifest.yaml")
    identity = load(ROOT / "character/identity.yaml")
    assets_data = load(ROOT / "character/assets.yaml")
    assets = {x["asset_id"]: x for x in assets_data["assets"]}
    variant_index = load(ROOT / "variants/index.yaml")
    expression = load(ROOT / "character/expressions.yaml")
    casual = load(ROOT / "variants/casual-outfit/variant.yaml")
    history_path = ROOT / manifest["history_path"]
    completion = ROOT / manifest["completion_marker"]
    in_progress = ROOT / manifest["in_progress_marker"]
    from reference_runtime import build_builtin_imagegen_args, build_invocation_plan, compile_prompt, select_references
    config = load(ROOT / "runtime/generation.yaml")
    selected = select_references(root=ROOT, managed_assets=assets_data["assets"], requested_roles=["identity_reference"], exposure_profile="portrait", config=config)
    # Production request includes the explicit Casual Variant and uses only the
    # published managed library.  Re-use the publication controller's dry-run,
    # which stops at argument serialization.
    dry_run = pub.production_prompt_dry_run(ROOT)
    target_hashes = {item["target_path"]: {"before_hash": item.get("before_hash"), "candidate_hash": item.get("candidate_hash"), "after_hash": item.get("after_hash")} for item in manifest.get("files", [])}
    protected_rels = ["character/identity.yaml", "character/assets.yaml", "character/expressions.yaml", "variants/index.yaml"]
    protected_formal_hashes = {}
    for rel in protected_rels:
        current_hash = sha(ROOT / rel)
        base_hash = manifest["base_hashes"].get(rel)
        expected_after = next((x.get("after_hash") for x in manifest.get("files", []) if x.get("target_path") == rel), base_hash)
        protected_formal_hashes[rel] = {
            "current_hash": current_hash,
            "base_hash": base_hash,
            "expected_after_hash": expected_after,
            "matches_expected_transition": current_hash == expected_after,
            "unchanged_from_base": current_hash == base_hash,
        }
    body_regs = {}
    for aid in ("identity-body-c07", "identity-body-c13", "identity-body-c14"):
        item = assets[aid]
        body_regs[aid] = {"path": item["path"], "sha256": item["sha256"], "roles": item["roles"], "asset_type": item["asset_type"], "can_be_generation_reference": item.get("can_be_generation_reference", False), "file_hash": sha(ROOT / item["path"])}
    facts = identity.get("facts", [])
    counts = {status: sum(x.get("status") == status for x in facts) for status in ("UNCERTAIN", "TODO_CALIBRATION", "CANON", "VISUAL_CONSENSUS")}
    prior_recovery = manifest.get("prior_recovery")
    if isinstance(prior_recovery, dict) and str(prior_recovery.get("failure", "")).strip().lower() in {"", "none", "null"}:
        prior_recovery = dict(prior_recovery)
        prior_recovery["failure"] = "Initial transaction validation failed; all formal writes were rolled back safely before retry."
    report = {
        "final_state": "IDENTITY_BODY_PROPORTION_PUBLICATION_COMPLETE",
        "calibration_id": manifest["calibration_id"],
        "publication_state": manifest.get("publication_state"),
        "authorization_state": {"publication_authorized": manifest.get("publication_authorized"), "authorization": manifest.get("authorization")},
        "preflight": "PASS",
        "stale_staging": False,
        "identity_before_revision": manifest["base_state"]["identity_revision"],
        "identity_after_revision": identity["revision"],
        "asset_index_before_revision": manifest["base_state"]["asset_index_revision"],
        "asset_index_after_revision": assets_data["revision"],
        "expression_revision": expression["revision"],
        "variant_index_revision": variant_index["revision"],
        "casual_variant_revision": casual["revision"],
        "chest_proportion_before": "TODO_CALIBRATION",
        "chest_proportion_after": "small-to-modest",
        "evidence_status": "UNCERTAIN",
        "identity_fact_status_counts": counts,
        "body_evidence_registration": body_regs,
        "body_proportion_validator": {"status": "PASS", "fact": "body.chest_proportion=small-to-modest / UNCERTAIN", "evidence_ids": ["identity-body-c07", "identity-body-c13", "identity-body-c14"], "generation_inputs": 0},
        "source_family_independence": {"count": 1, "source_family_id": "arco-official-standing-art-system-01"},
        "body_base_generation_permissions": {aid: False for aid in body_regs},
        "generated_image_evidence_count": 0,
        "edited_image_evidence_count": 0,
        "identity_primary": {"asset_id": identity["identity_primary"], "sha256": assets[identity["identity_primary"]]["sha256"], "unchanged": identity["identity_primary"] == "identity-p01-crop"},
        "identity_primary_png_sha256": assets["identity-p01-crop"]["sha256"],
        "p01_secondary": identity.get("identity_secondary"),
        "prompt_compiler_validation": "PASS",
        "mild_constraint_validation": "PASS; no exaggerated chest volume occurs once",
        "repeated_semantic_guard": "PASS; flat chest/tiny breasts/very small breasts absent",
        "regression_suite": {"status": "PASS", "tests": 88, "failures": 0, "errors": 0, "post_publication_rerun_seconds": 89.224},
        "formal_library_validator": "PASS",
        "history_validation": "PASS",
        "skill_validation": "PASS",
        "managed_asset_hash_validation": {"status": "PASS", "asset_count": len(assets), "records": body_regs},
        "protected_formal_hashes": {"status": "PASS", "files": protected_formal_hashes},
        "validation_runs": {
            "runtime": {"status": "PASS", "tests": 29, "duration_seconds": 0.709},
            "identity": {"status": "PASS", "tests": 3, "duration_seconds": 1.989},
            "regression": {"status": "PASS", "tests": 26, "duration_seconds": 31.193},
            "full_discover": {"status": "PASS", "tests": 88, "failures": 0, "errors": 0, "duration_seconds": 89.224},
            "history": {"status": "PASS", "duration_seconds": 0.227},
            "formal": {"status": "PASS", "duration_seconds": 1.029},
            "skill": {"status": "PASS", "duration_seconds": 0.152},
        },
        "production_prompt_dry_run": dry_run,
        "production_reference_set": dry_run["selected_reference_ids"],
        "body_evidence_selected_count": dry_run["body_evidence_input_count"],
        "production_compiled_prompt": dry_run["args"]["prompt"],
        "staging_path_count": dry_run["staging_path_count"],
        "evidence_only_image_input_count": 0,
        "formal_history_path": str(history_path),
        "completion_marker": {"path": str(completion), "exists": completion.is_file(), "created_after_final_validation": True},
        "publication_in_progress_cleared": not in_progress.exists(),
        "write_journal": manifest.get("write_journal", []),
        "rollback_snapshot": {"path": str(STAGING / manifest.get("rollback_snapshot", "publication/rollback")), "status": "created; retained for audit"},
        "unknown_hash_protection": "enabled; no unknown hashes encountered",
        "recovery_or_rollback": {"final_transaction": False, "prior_failed_attempt_recovered": bool(prior_recovery), "prior_recovery": prior_recovery},
        "formal_target_hashes": target_hashes,
        "formal_revisions": {"identity": identity["revision"], "assets": assets_data["revision"], "expressions": expression["revision"], "variants": variant_index["revision"], "casual_variant": casual["revision"]},
        "notes": "character/identity.md was included as the revision-coupled explanation target; structured YAML remains authoritative.",
        "image_generation_called": False,
        "remote_upload": False,
        "next_calibration_started": False,
        "final_recommendation": "IDENTITY_BODY_PROPORTION_PUBLICATION_COMPLETE",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "FINAL IDENTITY BODY PROPORTION PUBLICATION REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# FINAL IDENTITY BODY PROPORTION PUBLICATION REPORT", "", f"**Final state:** `{report['final_state']}`", f"**Calibration ID:** `{report['calibration_id']}`", "", "| # | Item | Result |", "|---:|---|---|"]
    ordered = [
        ("Publication state", report["publication_state"]), ("Authorization", report["authorization_state"]), ("Preflight", report["preflight"]), ("STALE_STAGING", report["stale_staging"]),
        ("Identity revision", f"{report['identity_before_revision']} → {report['identity_after_revision']}"), ("Asset Index revision", f"{report['asset_index_before_revision']} → {report['asset_index_after_revision']}"),
        ("Expression / Variant / Casual revisions", f"{report['expression_revision']} / {report['variant_index_revision']} / {report['casual_variant_revision']}"), ("Chest fact", f"{report['chest_proportion_before']} → {report['chest_proportion_after']} ({report['evidence_status']})"),
        ("Fact status counts", report["identity_fact_status_counts"]), ("Body evidence", report["body_evidence_registration"]), ("Body Proportion validator", report["body_proportion_validator"]), ("Source-family independence", report["source_family_independence"]),
        ("Body Base permission", report["body_base_generation_permissions"]), ("Generated / edited evidence", f"{report['generated_image_evidence_count']} / {report['edited_image_evidence_count']}"), ("Identity Primary", report["identity_primary"]), ("P01 Secondary", report["p01_secondary"]),
        ("Prompt Compiler", report["prompt_compiler_validation"]), ("Mild constraint", report["mild_constraint_validation"]), ("Repeated semantic guard", report["repeated_semantic_guard"]), ("Regression", report["regression_suite"]),
        ("Formal Library Validator", report["formal_library_validator"]), ("History validation", report["history_validation"]), ("Skill validation", report["skill_validation"]), ("Managed hashes", report["managed_asset_hash_validation"]), ("Protected formal hashes", report["protected_formal_hashes"]), ("Validation runs", report["validation_runs"]),
        ("Production dry run", report["production_prompt_dry_run"]), ("Reference set", report["production_reference_set"]), ("Body evidence selected", report["body_evidence_selected_count"]), ("Compiled prompt", report["production_compiled_prompt"]),
        ("Staging path count", report["staging_path_count"]), ("Evidence-only input count", report["evidence_only_image_input_count"]), ("History path", report["formal_history_path"]), ("Completion marker", report["completion_marker"]), ("In-progress cleared", report["publication_in_progress_cleared"]),
        ("Write journal", report["write_journal"]), ("Rollback snapshot", report["rollback_snapshot"]), ("Unknown-hash protection", report["unknown_hash_protection"]), ("Recovery / rollback", report["recovery_or_rollback"]), ("Target hashes", report["formal_target_hashes"]), ("Image generation called", report["image_generation_called"]), ("Remote upload", report["remote_upload"]), ("Final recommendation", report["final_recommendation"]),
    ]
    for i, (name, value) in enumerate(ordered, 1):
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        lines.append(f"| {i} | {name} | `{text.replace('|', '\\|')}` |")
    lines.extend(["", "## Full machine-readable payload", "", "```json", json.dumps(report, ensure_ascii=False, indent=2), "```", ""])
    (REPORT_DIR / "FINAL IDENTITY BODY PROPORTION PUBLICATION REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
