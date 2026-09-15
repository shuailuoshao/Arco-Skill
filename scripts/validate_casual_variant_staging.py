"""Validate a Casual Outfit Variant candidate without reading it in production Runtime."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from reference_runtime import (
    ReferenceRuntimeError,
    build_builtin_imagegen_args,
    build_invocation_plan,
    compile_reference_instructions,
    compute_global_reference_readiness,
    compute_request_reference_readiness,
    select_references,
    validate_reference_instructions,
)
from validate_library import validate


PRIMARY = "casual-outfit-primary"
EVIDENCE_ONLY = {
    "casual-outfit-open-arms-no-horns-evidence",
    "casual-outfit-open-arms-horns-evidence",
    "casual-outfit-crossed-arms-evidence",
    "casual-outfit-raised-fists-evidence",
}
FORBIDDEN_FACT_PARTS = {"hair", "eyes", "face", "body", "expression", "pose", "horn", "weapon", "cape", "temporary_prop"}
EXPECTED_COVERAGE = {
    "upper_body": "READY",
    "lower_body": "READY",
    "full_body": "READY",
    "footwear": "READY",
    "back_view": "INCOMPLETE",
    "overall": "PARTIAL",
}


def load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assembled_root(formal: Path, staging: Path, pending_history: dict[str, Any] | None = None) -> tempfile.TemporaryDirectory[str]:
    holder = tempfile.TemporaryDirectory()
    target = Path(holder.name)
    for rel in ("character", "variants", "assets/arco", "runtime", "calibration/history"):
        source = formal / rel
        if source.is_dir():
            shutil.copytree(source, target / rel, dirs_exist_ok=True)
    candidate = staging / "candidate-root"
    shutil.copytree(candidate / "character", target / "character", dirs_exist_ok=True)
    shutil.copytree(candidate / "variants", target / "variants", dirs_exist_ok=True)
    shutil.copytree(candidate / "assets", target / "assets", dirs_exist_ok=True)
    shutil.copy2(formal / "SKILL.md", target / "SKILL.md")
    history = pending_history or load(staging / "history-draft.yaml")
    manifest = load(staging / "publish-manifest.yaml")
    transaction_dir = target / "calibration/transactions"
    transaction_dir.mkdir(parents=True, exist_ok=True)
    pending_digest = hashlib.sha256(
        json.dumps(history, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    transaction = {
        "calibration_id": staging.name,
        "pending_history_sha256": pending_digest,
        "candidate_hashes": {
            item["target_path"]: item["candidate_hash"] for item in manifest.get("files", [])
        },
    }
    (transaction_dir / f"{staging.name}.publication_in_progress.json").write_text(
        json.dumps(transaction, ensure_ascii=False), encoding="utf-8"
    )
    return holder


def validate_candidate(formal: Path, staging: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    candidate = staging / "candidate-root"
    manifest = load(staging / "publish-manifest.yaml")
    history = load(staging / "history-draft.yaml")
    assets_before = load(formal / "character/assets.yaml")
    assets = load(candidate / "character/assets.yaml")
    index = load(candidate / "variants/index.yaml")
    variant = load(candidate / "variants/casual-outfit/variant.yaml")

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(manifest.get("calibration_id") == staging.name, "manifest calibration_id mismatch")
    require(manifest.get("calibration_targets") == ["variants.index", "variants.casual-outfit", "character.assets"], "manifest calibration targets mismatch")
    require(manifest.get("publication_authorized") is False, "publication must remain unauthorized")
    require(manifest.get("publication_state") in {"STAGING_VALIDATION_PENDING", "STAGED_VALIDATED_AWAITING_AUTHORIZATION"}, "invalid staging publication state")
    require(assets.get("revision") == 3 and assets_before.get("revision") == 2, "Asset Index must be 2 -> 3")
    require(index.get("revision") == 1 and len(index.get("variants", [])) == 1, "Variant Index must be 0 -> 1 with one entry")
    require(variant.get("revision") == 1 and variant.get("variant_id") == "casual-outfit", "Casual Variant revision/id mismatch")
    require(variant.get("display_name_zh") == "常服" and variant.get("display_name_en") == "Casual Outfit", "Variant display names mismatch")
    facts = variant.get("facts", [])
    require(len(facts) == 10, "Variant must contain exactly 10 facts")
    require(all(fact.get("status") == "UNCERTAIN" for fact in facts), "All Variant facts must remain UNCERTAIN")
    require(not any(any(part in str(fact.get("field_id", "")).lower() for part in FORBIDDEN_FACT_PARTS) for fact in facts), "Forbidden non-outfit field found in Variant facts")
    fact_ids = {fact.get("field_id") for fact in facts}
    require(set(variant.get("must_keep_fields", [])) <= fact_ids and len(variant.get("must_keep_fields", [])) == 7, "Must Keep must reference exactly seven real Variant facts")
    require(not any("horn" in value for value in variant.get("must_keep_fields", [])), "Horns cannot be Must Keep")
    require(variant.get("coverage") == EXPECTED_COVERAGE, "Variant coverage mismatch")

    old_count = len(assets_before.get("assets", []))
    require(assets.get("assets", [])[:old_count] == assets_before.get("assets", []), "Published Identity/Expression asset records changed in candidate")
    new_assets = assets.get("assets", [])[old_count:]
    require(len(new_assets) == 5, "Candidate must add exactly five assets")
    by_id = {item.get("asset_id"): item for item in new_assets}
    require(len(by_id) == 5 and set(by_id) == {PRIMARY} | EVIDENCE_ONLY, "Candidate asset IDs are not the approved set")
    primary_refs = variant.get("reference_asset_ids", {}).get("primary")
    require(primary_refs == [PRIMARY], "Variant must have exactly the approved Primary")
    require(variant.get("reference_asset_ids", {}).get("secondary") == [], "Revision 1 must not add Secondary")
    require(variant.get("reference_asset_ids", {}).get("detail") == [], "Revision 1 must not add Detail")
    primary = by_id.get(PRIMARY, {})
    generation = primary.get("generation_reference") or {}
    require(primary.get("variant_id") == "casual-outfit", "Primary variant_id mismatch")
    require(primary.get("roles") == ["variant_evidence"], "Primary evidence role mismatch")
    require(primary.get("can_be_generation_reference") is True, "Primary generation permission missing")
    require(generation.get("priority") == "primary" and generation.get("supported_roles") == ["outfit_reference"], "Primary generation role/priority mismatch")
    inheritance = generation.get("inheritance") or {}
    require(inheritance.get("outfit") == "inherit", "Variant Primary must inherit outfit")
    for key in ("identity", "face", "hair", "eyes", "body_proportions", "pose", "expression"):
        require(inheritance.get(key) == "do_not_inherit", f"Variant Primary must not inherit {key}")
    require(primary.get("evidence_independence") == "none", "Byte-identical Variant copy must have no evidence independence")
    formal_identity = next((item for item in assets_before["assets"] if item.get("asset_id") == "identity-p01"), {})
    require(primary.get("sha256") == formal_identity.get("sha256"), "Primary must be content-equivalent to identity-p01")
    for asset_id in EVIDENCE_ONLY:
        asset = by_id.get(asset_id, {})
        require(asset.get("can_be_generation_reference") is False and asset.get("generation_reference") is None, f"{asset_id} must remain evidence-only")
        require(asset.get("asset_type") == "faceless_composite", f"{asset_id} must be typed faceless_composite")
    for asset in new_assets:
        path = candidate / str(asset.get("path"))
        require(path.is_file() and sha(path) == asset.get("sha256"), f"Candidate asset file/hash mismatch: {asset.get('asset_id')}")
    all_ids = {item.get("asset_id") for item in assets.get("assets", [])}
    for fact in facts:
        require(bool(fact.get("evidence_ids")) and set(fact.get("evidence_ids", [])) <= all_ids, f"Dangling evidence on {fact.get('field_id')}")

    expected_files = {"character/assets.yaml", "variants/index.yaml", "variants/casual-outfit/variant.yaml", "variants/casual-outfit/notes.md"} | {item.get("path") for item in new_assets}
    manifest_targets = {item.get("target_path") for item in manifest.get("files", [])}
    require(manifest_targets == expected_files, "Manifest publication file set mismatch")
    for item in manifest.get("files", []):
        staged = staging / str(item.get("staged_path"))
        require(staged.is_file() and sha(staged) == item.get("candidate_hash"), f"Manifest candidate hash mismatch: {item.get('target_path')}")
        require(item.get("after_hash") is None and item.get("publication_status") == "pending", f"Manifest target is not pending: {item.get('target_path')}")
    for rel, expected in manifest.get("base_hashes", {}).items():
        path = formal / rel
        require(path.is_file() and sha(path) == expected, f"STALE_STAGING: {rel}")
    require(load(formal / "character/identity.yaml").get("revision") == 1, "Formal Identity revision changed")
    require(load(formal / "character/expressions.yaml").get("revision") == 1, "Formal Expression revision changed")
    require(load(formal / "variants/index.yaml").get("revision") == 0, "Formal Variant Index revision changed")

    history_for_validation = copy.deepcopy(history)
    history_for_validation["validation_result"] = {
        "validator_version": "casual-variant-staging-v1",
        "structure": "PASS",
        "identity_readiness": "INCOMPLETE",
        "variant_readiness": {"casual-outfit": "INCOMPLETE"},
        "errors": 0,
        "warnings": 0,
    }
    holder = assembled_root(formal, staging, history_for_validation)
    assembled = Path(holder.name)
    try:
        formal_result = validate(assembled, pending_history=history_for_validation)
        require(formal_result.get("structure") == "PASS", "Assembled candidate Formal Library Validator failed")
        runtime_assets = load(assembled / "character/assets.yaml")["assets"]
        config = load(formal / "runtime/generation.yaml")["generation"]
        try:
            selected = select_references(
                root=assembled,
                managed_assets=runtime_assets,
                requested_roles=["identity_reference", "outfit_reference"],
                selected_variant_id="casual-outfit",
                exposure_profile="portrait",
                variant_required=True,
                config=config,
            )
            selected_ids = [item.get("asset_id") for item in selected]
            require(selected_ids == ["identity-p01-crop", PRIMARY], f"Unexpected portrait reference order: {selected_ids}")
            require(not EVIDENCE_ONLY & set(selected_ids), "Evidence-only asset reached Runtime selection")
            instructions = compile_reference_instructions(selected)
            validate_reference_instructions(selected, instructions)
            plan = build_invocation_plan(mode="reference_conditioned", prompt=instructions + "\nArco in casual outfit.", selected_references=selected)
            args = build_builtin_imagegen_args(plan)
            require(args.get("referenced_image_paths") == [item.get("path") for item in selected], "Adapter Boundary paths/order mismatch")
            request_ready = compute_request_reference_readiness(exposure_profile="portrait", references=selected, variant_required=True, selected_variant_id="casual-outfit")
            require(request_ready.get("status") == "READY", "Portrait Request Variant readiness must be READY")
            wrong_contract = compute_request_reference_readiness(
                exposure_profile="portrait",
                references=[dict(selected[-1], variant_id="wrong-variant")],
                variant_required=True,
                selected_variant_id="casual-outfit",
            )
            require(wrong_contract.get("status") == "CONFLICT", "Wrong Variant Contract did not return CONFLICT")
        except ReferenceRuntimeError as exc:
            errors.append(f"Runtime candidate integration failed closed: {exc.code}: {exc}")
        global_ready = compute_global_reference_readiness(load(assembled / "character/identity.yaml"), index, runtime_assets)
        require(global_ready.get("variants", {}).get("casual-outfit") == "PARTIAL", "Global Casual Variant readiness must be PARTIAL")
        require(global_ready.get("variant_profiles", {}).get("casual-outfit", {}).get("back_view") == "INCOMPLETE", "Runtime back-view must remain INCOMPLETE")
    finally:
        holder.cleanup()

    return {
        "validator": "casual-variant-staging-v1",
        "calibration_id": staging.name,
        "status": "PASS" if not errors else "FAIL",
        "counts": {
            "variant_facts": len(facts),
            "uncertain": sum(fact.get("status") == "UNCERTAIN" for fact in facts),
            "canon": sum(fact.get("status") == "CANON" for fact in facts),
            "visual_consensus": sum(fact.get("status") == "VISUAL_CONSENSUS" for fact in facts),
            "new_assets": len(new_assets),
            "generation_assets": sum(item.get("can_be_generation_reference") is True for item in new_assets),
            "evidence_only_assets": sum(item.get("can_be_generation_reference") is False for item in new_assets),
        },
        "coverage": variant.get("coverage"),
        "errors": errors,
        "warnings": warnings,
        "publication_executed": False,
        "remote_image_generation": False,
        "remote_image_upload": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate_candidate(args.root.resolve(), args.staging.resolve())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"CASUAL VARIANT STAGING: {result['status']}")
        for error in result["errors"]:
            print("ERROR:", error)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
