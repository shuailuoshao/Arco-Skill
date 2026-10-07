"""Batch 4B.3-V formal sample validity audit and verdict-set freezer.

This module is intentionally separate from the frozen Batch 4B.3-F runner.
It audits the accepted formal rows read-only, prepares six isolated replacement
tasks, accepts generated PNGs through the existing receipt primitives, and
freezes a new verdict set without changing historical manifests or records.

No image pixels are inspected beyond the PNG signature and cryptographic hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_style_regression as runner  # noqa: E402


EVALUATION_DIR = ROOT / "archive/实验/evaluation" / "style-regression"
V_ROOT = EVALUATION_DIR / "verdict-replacements" / "batch-4b.3v"
AUDIT_PATH = V_ROOT / "audit.json"
PLAN_PATH = V_ROOT / "replacement-plan.json"
VERDICT_SET_PATH = EVALUATION_DIR / "verdict-set.json"
COMPLETION_REPORT_PATH = EVALUATION_DIR / "batch-4b.3v-completion.md"
SOURCE_MANIFEST_PATH = EVALUATION_DIR / "manifest.jsonl"
V_BATCH = "4B.3-V"
FORMAL_BATCH = "4B.3-F"
REPLACEMENT_CASE = "case-04"
REPLACEMENT_REPLICATES = (2, 3)
GROUPS = ("A", "B", "C")
PNG_SIGNATURE = bytes.fromhex("89504E470D0A1A0A")
LEGACY_ALLOWLIST_CAPTURE = EVALUATION_DIR / "environment" / "batch-4b3t-formal-continuation-r14.json"
SAFETY_CLARIFICATION = (
    "Safety clarification: The character is an adult woman, fully clothed in the complete ordinary published "
    "casual outfit shown by the outfit reference, presented neutrally and non-sexually. Do not depict nudity, "
    "transparent clothing, suggestive posing, or sexualized content."
)
SAFETY_BLOCK_SHA256 = hashlib.sha256(SAFETY_CLARIFICATION.encode("utf-8")).hexdigest()

SAFETY_TERMS = (
    "safety clarification",
    "adult woman",
    "fully clothed",
    "non-sexual",
    "nonsexual",
    "nudity",
    "transparent clothing",
    "suggestive",
    "sexualized",
    "成年女性",
    "成年人",
    "非色情",
    "非性化",
    "裸露",
    "透明服装",
    "挑逗",
    "性化",
)
SCENE_CONTRACT = {
    "courtyard": ("庭院",),
    "low_density_background": ("墙面", "叶片"),
    "facing_and_turn": ("面向镜头", "右侧"),
    "relaxed_arms_and_visible_hands": ("双臂", "双手"),
    "upper_body_framing": ("上半身", "头部", "腰部"),
    "complete_head_shoulders_hands": ("头顶", "双肩", "双手"),
    "centered_subject": ("居中",),
    "camera": ("平视", "三分之四"),
    "neutral_exposure": ("中性", "曝光"),
    "no_extra_subjects": ("道具", "角色"),
}


class ValidityAuditError(RuntimeError):
    """A fail-closed V audit or freeze error."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative(path: Path) -> str:
    return path.resolve(strict=False).relative_to(ROOT.resolve()).as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidityAuditError(f"Cannot read JSON object: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidityAuditError(f"Expected a JSON object: {path}")
    return value


def _write_once_bytes(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ValidityAuditError(f"Write-once artifact already exists: {path}") from exc


def _write_once_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_once_bytes(path, _json_bytes(value))


def _write_once_text(path: Path, text: str) -> None:
    _write_once_bytes(path, text.encode("utf-8"))


def _ensure_existing_or_equal(path: Path, expected: bytes) -> None:
    if not path.is_file():
        raise ValidityAuditError(f"Required V artifact is missing: {path}")
    actual = path.read_bytes()
    if actual != expected:
        raise ValidityAuditError(f"Existing V artifact differs; refusing overwrite: {path}")


def _historical_relative_files() -> list[Path]:
    """Return the pre-V audit scope, excluding only planned V outputs."""
    allowed_new = {
        Path("verdict-set.json"),
        Path(COMPLETION_REPORT_PATH.name),
    }
    paths: list[Path] = []
    if EVALUATION_DIR.is_dir():
        for path in EVALUATION_DIR.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(EVALUATION_DIR)
            if relative.parts and relative.parts[0] == "verdict-replacements":
                continue
            if relative in allowed_new:
                continue
            paths.append(relative)
    return sorted(paths, key=lambda item: item.as_posix())


def _snapshot_historical_artifacts() -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for relative in _historical_relative_files():
        path = EVALUATION_DIR / relative
        files.append(
            {
                "path": (Path("archive/实验/evaluation/style-regression") / relative).as_posix(),
                "sha256": runner.sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return {
        "scope": "archive/实验/evaluation/style-regression excluding verdict-replacements, verdict-set.json, and the V report",
        "files": files,
        "tree_sha256": _sha256_bytes(_json_bytes(files)),
    }


def _assert_historical_snapshot(snapshot: Mapping[str, Any]) -> None:
    expected_files = snapshot.get("files")
    if not isinstance(expected_files, list):
        raise ValidityAuditError("Historical snapshot has no file list.")
    current = _snapshot_historical_artifacts()
    if current != dict(snapshot):
        expected_by_path = {item.get("path"): item.get("sha256") for item in expected_files if isinstance(item, Mapping)}
        current_by_path = {item.get("path"): item.get("sha256") for item in current["files"]}
        added = sorted(set(current_by_path) - set(expected_by_path))
        removed = sorted(set(expected_by_path) - set(current_by_path))
        changed = sorted(
            path for path in set(expected_by_path) & set(current_by_path)
            if expected_by_path[path] != current_by_path[path]
        )
        raise ValidityAuditError(
            "Historical artifacts changed: "
            f"added={added}, removed={removed}, changed={changed}"
        )


def _accepted_rows() -> list[dict[str, Any]]:
    rows = runner._load_jsonl(SOURCE_MANIFEST_PATH)
    accepted = [
        row
        for row in rows
        if row.get("batch") == FORMAL_BATCH
        and row.get("formal") is True
        and row.get("status") == "succeeded"
        and row.get("include_in_formal_analysis") is True
        and row.get("excluded_from_verdict") is False
    ]
    if len(accepted) != 36:
        raise ValidityAuditError(f"Expected 36 accepted formal rows, found {len(accepted)}.")
    sample_keys = [str(row.get("sample_key")) for row in accepted]
    if len(set(sample_keys)) != 36:
        raise ValidityAuditError("Accepted formal rows do not have unique sample keys.")
    expected_keys = {
        runner._sample_key(case_id, group, replicate)
        for case_id in runner.CASE_IDS
        for replicate in range(1, runner.EXPECTED_REPLICATES + 1)
        for group in GROUPS
    }
    if set(sample_keys) != expected_keys:
        raise ValidityAuditError("Accepted formal rows do not cover the expected 36-sample design.")
    return sorted(accepted, key=lambda row: sample_keys.index(str(row["sample_key"])))


def _historical_runner_allowlist() -> dict[str, dict[str, str]]:
    """Load the existing hash-pinned compatibility table for old formal tasks."""
    capture = _load_json(LEGACY_ALLOWLIST_CAPTURE)
    entries = capture.get("legacy_task_compatibility")
    if not isinstance(entries, list) or not entries:
        raise ValidityAuditError("The immutable formal continuation has no legacy task compatibility table.")
    result: dict[str, dict[str, str]] = {}
    for raw in entries:
        if not isinstance(raw, Mapping):
            raise ValidityAuditError("Legacy task compatibility entry is not an object.")
        entry = {str(key): str(value) for key, value in raw.items()}
        task_sha = entry.get("task_sha256")
        if not task_sha or task_sha in result:
            raise ValidityAuditError("Legacy task compatibility table has a duplicate or empty task hash.")
        result[task_sha] = entry
    return result


def _load_cases() -> dict[str, dict[str, Any]]:
    document = yaml.safe_load((EVALUATION_DIR / "cases.yaml").read_text(encoding="utf-8"))
    cases = document.get("cases") if isinstance(document, Mapping) else None
    if not isinstance(cases, list):
        raise ValidityAuditError("cases.yaml has no case list.")
    result = {str(case["case_id"]): dict(case) for case in cases if isinstance(case, Mapping)}
    if set(result) != set(runner.CASE_IDS):
        raise ValidityAuditError("cases.yaml case IDs differ from the formal design.")
    return result


def _is_prompt_revised(row: Mapping[str, Any]) -> bool:
    path = str(row.get("compiled_prompt_path", ""))
    return bool(row.get("protocol_revision")) or "/protocol-revisions/" in path.replace("\\", "/")


def _safety_signature(prompt: str) -> dict[str, Any]:
    lowered = prompt.casefold()
    safety_lines: list[dict[str, Any]] = []
    for index, line in enumerate(prompt.splitlines()):
        line_lower = line.casefold()
        if any(term.casefold() in line_lower for term in SAFETY_TERMS):
            safety_lines.append({"line": index, "text": line})
    first = safety_lines[0]["line"] if safety_lines else None
    prefix = prompt.splitlines()[: first + 1] if first is not None else []
    return {
        "present": bool(safety_lines),
        "lines": safety_lines,
        "first_safety_line": first,
        "prefix_through_first_safety_line": prefix,
        "prompt_contains_safety_language": any(term.casefold() in lowered for term in SAFETY_TERMS),
    }


def _semantic_scene_contract(prompt: str) -> dict[str, bool]:
    return {
        name: all(token in prompt for token in tokens)
        for name, tokens in SCENE_CONTRACT.items()
    }


def _bc_hygiene_only(prompt_b: str, prompt_c: str) -> dict[str, Any]:
    if not prompt_c.startswith(prompt_b):
        return {"valid": False, "reason": "C prompt does not preserve B prompt as an exact prefix."}
    suffix = prompt_c[len(prompt_b) :]
    valid = suffix.startswith("\n\nRendering hygiene guardrails:") and bool(suffix.strip())
    return {
        "valid": valid,
        "suffix_sha256": _sha256_bytes(suffix.encode("utf-8")),
        "suffix": suffix,
        "reason": None if valid else "C/B prompt suffix is not the frozen Hygiene-only delta.",
    }


def _load_task_and_receipt(row: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    from archive_paths import relocate
    task_path = relocate(ROOT / str(row["task_path"]), root=ROOT)
    output_path = relocate(ROOT / str(row["output_path"]), root=ROOT)
    allowlist = _historical_runner_allowlist()
    task = runner.load_codex_task(
        task_path,
        root=ROOT,
        require_utf8_schema=True,
        legacy_runner_hash_allowlist=allowlist,
    )
    if task.get("batch") != FORMAL_BATCH:
        raise ValidityAuditError(f"Accepted row task has unexpected batch: {row['sample_key']}")
    if task.get("prompt_sha256_utf8") != row.get("prompt_sha256_utf8"):
        raise ValidityAuditError(f"Manifest/task prompt hash mismatch: {row['sample_key']}")
    receipt = runner.verify_codex_execution_receipt(
        task_path,
        output_path,
        root=ROOT,
        expected_receipt_path=str(row["receipt_path"]),
        expected_receipt_sha256=str(row["receipt_sha256"]),
        legacy_runner_hash_allowlist=allowlist,
    )
    if receipt.get("sent_prompt_sha256_utf8") != task.get("prompt_sha256_utf8"):
        raise ValidityAuditError(f"Receipt/task prompt hash mismatch: {row['sample_key']}")
    if receipt.get("output_sha256") != row.get("output_sha256"):
        raise ValidityAuditError(f"Manifest/receipt output hash mismatch: {row['sample_key']}")
    return task, receipt


def _triplet_audit(
    case_id: str,
    replicate: int,
    rows: Mapping[str, Mapping[str, Any]],
    tasks: Mapping[str, Mapping[str, Any]],
    receipts: Mapping[str, Mapping[str, Any]],
    cases: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    ordered = {group: rows[f"{case_id}:{group}:r{replicate}"] for group in GROUPS}
    ordered_tasks = {group: tasks[f"{case_id}:{group}:r{replicate}"] for group in GROUPS}
    ordered_receipts = {group: receipts[f"{case_id}:{group}:r{replicate}"] for group in GROUPS}
    prompts = {group: str(ordered_tasks[group]["prompt"]) for group in GROUPS}
    scene_contracts = {group: _semantic_scene_contract(prompts[group]) for group in GROUPS}
    scene_parity = all(all(scene_contracts[group].values()) for group in GROUPS)

    reference_lists = {
        group: ordered_receipts[group].get("references_ordered") for group in GROUPS
    }
    reference_parity = len({json.dumps(value, ensure_ascii=True, sort_keys=True) for value in reference_lists.values()}) == 1
    ordered_reference_parity = reference_parity and all(
        list(ordered_tasks[group].get("reference_ids", [])) == list(ordered_tasks["A"].get("reference_ids", []))
        for group in GROUPS
    )

    bc_context_fields = {
        "resolved_style_context_sha256": {
            group: ordered[group].get("resolved_style_context_sha256") for group in ("B", "C")
        },
        "style_context_hash": {
            group: ordered[group].get("style_context_hash") for group in ("B", "C")
        },
    }
    bc_style_context_parity = all(len(set(values.values())) == 1 for values in bc_context_fields.values())
    hygiene_delta = _bc_hygiene_only(prompts["B"], prompts["C"])

    safety = {group: _safety_signature(prompts[group]) for group in GROUPS}
    safety_equivalent = len({json.dumps(value, ensure_ascii=False, sort_keys=True) for value in safety.values()}) == 1
    # For a clean triplet, all groups have no safety clarification. For a
    # harmonized replacement, all groups will share the exact same block.
    prompt_parity_outside_delta = bool(
        scene_parity
        and reference_parity
        and ordered_reference_parity
        and bc_style_context_parity
        and hygiene_delta["valid"]
        and safety_equivalent
    )
    confounded = not prompt_parity_outside_delta
    if not scene_parity:
        confound_reason = "scene contract is not present for every group"
    elif not reference_parity or not ordered_reference_parity:
        confound_reason = "reference identity/hash/order parity failed"
    elif not bc_style_context_parity:
        confound_reason = "B/C StyleContext parity failed"
    elif not hygiene_delta["valid"]:
        confound_reason = "B/C difference is not Hygiene-only"
    elif not safety_equivalent:
        confound_reason = "safety clarification differs across A/B/C"
    else:
        confound_reason = None

    return {
        "triplet_id": f"{case_id}:r{replicate}",
        "sample_ids": [f"{case_id}:{group}:r{replicate}" for group in GROUPS],
        "scene_parity": scene_parity,
        "scene_contracts": scene_contracts,
        "reference_parity": reference_parity,
        "ordered_reference_parity": ordered_reference_parity,
        "reference_ids_by_group": {
            group: list(ordered_tasks[group].get("reference_ids", [])) for group in GROUPS
        },
        "reference_hashes_by_group": {
            group: [item.get("sha256") for item in ordered_receipts[group].get("references_ordered", [])]
            for group in GROUPS
        },
        "bc_style_context_parity": bc_style_context_parity,
        "bc_style_context_fields": bc_context_fields,
        "bc_difference_hygiene_only": hygiene_delta["valid"],
        "bc_hygiene_suffix_sha256": hygiene_delta.get("suffix_sha256"),
        "safety_equivalent_semantically_and_structurally": safety_equivalent,
        "safety_signatures": safety,
        "prompt_parity_outside_intended_delta": prompt_parity_outside_delta,
        "confounded": confounded,
        "confound_reason": confound_reason,
        "group_prompt_sha256": {
            group: ordered_tasks[group]["prompt_sha256_utf8"] for group in GROUPS
        },
        "group_protocol_revision": {
            group: ordered[group].get("protocol_revision") for group in GROUPS
        },
    }


def audit_original_samples() -> dict[str, Any]:
    rows_list = _accepted_rows()
    rows = {str(row["sample_key"]): row for row in rows_list}
    cases = _load_cases()
    task_by_sample: dict[str, dict[str, Any]] = {}
    receipt_by_sample: dict[str, dict[str, Any]] = {}
    sample_records: list[dict[str, Any]] = []
    for row in rows_list:
        sample_id = str(row["sample_key"])
        task, receipt = _load_task_and_receipt(row)
        task_by_sample[sample_id] = task
        receipt_by_sample[sample_id] = receipt
        revised = _is_prompt_revised(row)
        sample_records.append(
            {
                "sample_id": sample_id,
                "case_id": row["case_id"],
                "group": row["group"],
                "replicate": row["replicate"],
                "output_sha256": receipt["output_sha256"],
                "actual_sent_prompt_sha256": receipt["sent_prompt_sha256_utf8"],
                "validity_classification": "PROMPT_REVISED" if revised else "CLEAN",
                "protocol_revision": row.get("protocol_revision"),
                "task_path": row["task_path"],
                "receipt_path": row["receipt_path"],
                "output_path": row["output_path"],
                "verdict_included": True,
                "replacement_provenance": None,
            }
        )

    triplets: list[dict[str, Any]] = []
    for case_id in runner.CASE_IDS:
        for replicate in range(1, runner.EXPECTED_REPLICATES + 1):
            triplets.append(_triplet_audit(case_id, replicate, rows, task_by_sample, receipt_by_sample, cases))

    affected_triplets = [item["triplet_id"] for item in triplets if item["confounded"]]
    if affected_triplets != ["case-04:r2", "case-04:r3"]:
        raise ValidityAuditError(f"Unexpected affected triplets: {affected_triplets}")
    affected_samples = {
        sample_id
        for triplet in triplets
        if triplet["confounded"]
        for sample_id in triplet["sample_ids"]
    }
    for record in sample_records:
        if record["sample_id"] in affected_samples:
            record["verdict_included"] = False
            record["exclusion_reason"] = next(
                triplet["confound_reason"]
                for triplet in triplets
                if record["sample_id"] in triplet["sample_ids"]
            )

    classification_counts = {
        "CLEAN": sum(item["validity_classification"] == "CLEAN" for item in sample_records),
        "PROMPT_REVISED": sum(item["validity_classification"] == "PROMPT_REVISED" for item in sample_records),
    }
    if classification_counts != {"CLEAN": 31, "PROMPT_REVISED": 5}:
        raise ValidityAuditError(f"Unexpected original validity counts: {classification_counts}")

    return {
        "schema_version": 1,
        "batch": V_BATCH,
        "audit_status": "COMPLETE",
        "visual_evaluation_performed": False,
        "source_manifest_path": _relative(SOURCE_MANIFEST_PATH),
        "source_manifest_sha256": runner.sha256_file(SOURCE_MANIFEST_PATH),
        "historical_snapshot": _snapshot_historical_artifacts(),
        "original_sample_count": len(sample_records),
        "original_classification_counts": classification_counts,
        "samples": sample_records,
        "triplets": triplets,
        "affected_triplets": affected_triplets,
        "excluded_original_sample_ids": sorted(affected_samples),
        "replacement_policy": {
            "safety_clarification": SAFETY_CLARIFICATION,
            "safety_clarification_sha256": SAFETY_BLOCK_SHA256,
            "canonical_prompt_dir": "archive/实验/evaluation/style-regression/style-context/case-04",
            "groups": {"A": "Corrected Legacy", "B": "Style Transfer", "C": "Style Transfer + Hygiene"},
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _canonical_prompt(case_id: str, group: str) -> tuple[Path, str]:
    path = EVALUATION_DIR / "style-context" / case_id / f"prompt-{group}.txt"
    if not path.is_file():
        raise ValidityAuditError(f"Canonical prompt is missing: {path}")
    prompt = path.read_text(encoding="utf-8").rstrip("\r\n")
    if not prompt:
        raise ValidityAuditError(f"Canonical prompt is empty: {path}")
    return path, prompt


def build_replacement_prompt(body: str) -> str:
    """Prepend the exact common safety clarification to one frozen body."""
    return f"{SAFETY_CLARIFICATION}\n\n{body.rstrip(chr(13) + chr(10))}"


def _replacement_task_frozen_hashes(source_task: Mapping[str, Any]) -> dict[str, Any]:
    frozen = source_task.get("frozen_input_hashes")
    if not isinstance(frozen, Mapping):
        raise ValidityAuditError("Source task has no frozen input hashes.")
    copied = json.loads(json.dumps(frozen, ensure_ascii=False))
    files = copied.get("files")
    if not isinstance(files, dict):
        raise ValidityAuditError("Source task frozen input files are invalid.")
    # V tasks are new tasks and therefore bind the current frozen runner. The
    # original tasks remain validated through the historical allowlist above.
    files["scripts/run_style_regression.py"] = runner.sha256_file(ROOT / "scripts" / "run_style_regression.py")
    return copied


def _replacement_plan_from_audit(audit: Mapping[str, Any]) -> dict[str, Any]:
    sample_records = {str(item["sample_id"]): item for item in audit["samples"]}
    original_rows = {str(row["sample_key"]): row for row in _accepted_rows()}
    entries: list[dict[str, Any]] = []
    for replicate in REPLACEMENT_REPLICATES:
        for group in GROUPS:
            sample_id = f"{REPLACEMENT_CASE}:{group}:r{replicate}"
            source_row = original_rows[sample_id]
            source_task = runner.load_codex_task(
                ROOT / str(source_row["task_path"]),
                root=ROOT,
                require_utf8_schema=True,
                legacy_runner_hash_allowlist=_historical_runner_allowlist(),
            )
            canonical_path, body = _canonical_prompt(REPLACEMENT_CASE, group)
            prompt = build_replacement_prompt(body)
            prompt_path = V_ROOT / "prompts" / f"{REPLACEMENT_CASE}-{group}-r{replicate}.txt"
            task_path = V_ROOT / "tasks" / f"{REPLACEMENT_CASE}-{group}-r{replicate}-attempt-1.json"
            expected_output = V_ROOT / "outputs" / REPLACEMENT_CASE / f"{group}-r{replicate}.png"
            entry = {
                "sample_id": sample_id,
                "case_id": REPLACEMENT_CASE,
                "group": group,
                "replicate": replicate,
                "validity_classification": "PROMPT_REVISED",
                "canonical_prompt_path": _relative(canonical_path),
                "canonical_prompt_sha256": _sha256_bytes(body.encode("utf-8")),
                "prompt_path": _relative(prompt_path),
                "prompt_sha256_utf8": _sha256_bytes(prompt.encode("utf-8")),
                "safety_clarification_sha256": SAFETY_BLOCK_SHA256,
                "task_path": _relative(task_path),
                "expected_output_path": _relative(expected_output),
                "source_sample_id": sample_id,
                "superseded_output_sha256": sample_records[sample_id]["output_sha256"],
                "superseded_prompt_sha256": sample_records[sample_id]["actual_sent_prompt_sha256"],
                "superseded_task_path": sample_records[sample_id]["task_path"],
                "superseded_receipt_path": sample_records[sample_id]["receipt_path"],
                "superseded_output_path": sample_records[sample_id]["output_path"],
                "reference_ids_ordered": list(source_task["reference_ids"]),
                "reference_paths_ordered": list(source_task["referenced_image_paths"]),
                "reference_hashes_ordered": [
                    item["sha256"] for item in source_task["frozen_input_hashes"]["references"]
                ],
                "task_id": f"validity:{sample_id}:attempt-1",
                "task_sha256": None,
                "receipt_path": _relative(V_ROOT / "receipts" / task_path.name),
                "receipt_sha256": None,
                "output_sha256": None,
                "status": "prepared",
                "_prompt": prompt,
                "_source_frozen_input_hashes": _replacement_task_frozen_hashes(source_task),
            }
            entries.append(entry)
    entries.sort(key=lambda item: (item["replicate"], GROUPS.index(item["group"])))
    return {
        "schema_version": 1,
        "batch": V_BATCH,
        "status": "PREPARED",
        "visual_evaluation_performed": False,
        "safety_clarification": SAFETY_CLARIFICATION,
        "safety_clarification_sha256": SAFETY_BLOCK_SHA256,
        "entries": entries,
    }


def _public_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(plan, ensure_ascii=False))
    for entry in value.get("entries", []):
        entry.pop("_prompt", None)
        entry.pop("_source_frozen_input_hashes", None)
    return value


def prepare() -> dict[str, Any]:
    if VERDICT_SET_PATH.exists():
        raise ValidityAuditError(f"Verdict set is already frozen; refusing to prepare again: {VERDICT_SET_PATH}")
    audit = audit_original_samples()
    if AUDIT_PATH.exists():
        existing = _load_json(AUDIT_PATH)
        if existing.get("source_manifest_sha256") != audit.get("source_manifest_sha256"):
            raise ValidityAuditError("Existing V audit is bound to a different historical manifest.")
        audit = existing
    else:
        _write_once_json(AUDIT_PATH, audit)

    plan = _replacement_plan_from_audit(audit)
    public_plan = _public_plan(plan)
    if PLAN_PATH.exists():
        existing_plan = _load_json(PLAN_PATH)
        if existing_plan != public_plan:
            raise ValidityAuditError("Existing replacement plan differs; refusing overwrite.")
    else:
        for entry in plan["entries"]:
            prompt = entry["_prompt"]
            prompt_path = ROOT / entry["prompt_path"]
            if prompt_path.exists():
                _ensure_existing_or_equal(prompt_path, prompt.encode("utf-8"))
            else:
                _write_once_text(prompt_path, prompt)
            task = runner.build_codex_task(
                task_id=entry["task_id"],
                task_kind="formal",
                batch=V_BATCH,
                case_id=entry["case_id"],
                group=entry["group"],
                replicate=entry["replicate"],
                prompt=prompt,
                referenced_image_paths=entry["reference_paths_ordered"],
                reference_ids=entry["reference_ids_ordered"],
                expected_output_path=entry["expected_output_path"],
                frozen_input_hashes=entry["_source_frozen_input_hashes"],
            )
            if task["prompt_sha256_utf8"] != entry["prompt_sha256_utf8"]:
                raise ValidityAuditError(f"Replacement prompt hash changed during task construction: {entry['sample_id']}")
            entry["task_sha256"] = task["task_sha256"]
            task_path = ROOT / entry["task_path"]
            if task_path.exists():
                _ensure_existing_or_equal(task_path, _json_bytes(task))
            else:
                runner.write_codex_task(task, path=task_path)
        public_plan = _public_plan(plan)
        _write_once_json(PLAN_PATH, public_plan)

    return {
        "status": "PREPARED",
        "audit_path": _relative(AUDIT_PATH),
        "plan_path": _relative(PLAN_PATH),
        "replacement_entries": len(public_plan["entries"]),
        "original_classification_counts": audit["original_classification_counts"],
        "affected_triplets": audit["affected_triplets"],
    }


def _load_plan() -> dict[str, Any]:
    plan = _load_json(PLAN_PATH)
    if plan.get("batch") != V_BATCH or len(plan.get("entries", [])) != 6:
        raise ValidityAuditError("Replacement plan is incomplete or has the wrong batch.")
    return plan


def _plan_entry(plan: Mapping[str, Any], sample_id: str) -> dict[str, Any]:
    matches = [entry for entry in plan["entries"] if entry.get("sample_id") == sample_id]
    if len(matches) != 1:
        raise ValidityAuditError(f"Replacement plan has no unique entry for {sample_id}.")
    return dict(matches[0])


def accept(sample_id: str, source_path: Path) -> dict[str, Any]:
    plan = _load_plan()
    entry = _plan_entry(plan, sample_id)
    task_path = ROOT / str(entry["task_path"])
    output_path = ROOT / str(entry["expected_output_path"])
    if not source_path.is_file():
        raise ValidityAuditError(f"Generated PNG is missing: {source_path}")
    with source_path.open("rb") as handle:
        if handle.read(8) != PNG_SIGNATURE:
            raise ValidityAuditError(f"Generated source is not a PNG: {source_path}")
    task = runner.load_codex_task(task_path, root=ROOT, require_utf8_schema=True)
    if task.get("batch") != V_BATCH or task.get("prompt_sha256_utf8") != entry["prompt_sha256_utf8"]:
        raise ValidityAuditError(f"Replacement task does not match the prepared plan: {sample_id}")
    receipt = runner.write_codex_execution_receipt(
        task_path,
        source_path,
        sent_prompt=str(task["prompt"]),
        root=ROOT,
    )
    accepted = runner.accept_codex_task_output(task_path, source_path, root=ROOT)
    verified = runner.verify_codex_execution_receipt(task_path, output_path, root=ROOT)
    if verified["output_sha256"] != accepted["output_sha256"]:
        raise ValidityAuditError(f"Replacement output hash changed after acceptance: {sample_id}")
    if verified["sent_prompt_sha256_utf8"] != entry["prompt_sha256_utf8"]:
        raise ValidityAuditError(f"Replacement receipt prompt hash mismatch: {sample_id}")
    if receipt["receipt_sha256"] != verified["receipt_sha256"]:
        raise ValidityAuditError(f"Replacement receipt changed after acceptance: {sample_id}")
    return {
        "sample_id": sample_id,
        "status": "ACCEPTED",
        "task_path": entry["task_path"],
        "receipt_path": verified["receipt_path"],
        "receipt_sha256": verified["receipt_sha256"],
        "output_path": entry["expected_output_path"],
        "output_sha256": verified["output_sha256"],
        "actual_sent_prompt_sha256": verified["sent_prompt_sha256_utf8"],
    }


def _replacement_acceptance(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    accepted: dict[str, dict[str, Any]] = {}
    for raw_entry in plan["entries"]:
        entry = dict(raw_entry)
        task_path = ROOT / str(entry["task_path"])
        output_path = ROOT / str(entry["expected_output_path"])
        receipt_path = ROOT / str(entry["receipt_path"])
        if not task_path.is_file() or not output_path.is_file() or not receipt_path.is_file():
            raise ValidityAuditError(f"Replacement is not fully accepted: {entry['sample_id']}")
        task = runner.load_codex_task(task_path, root=ROOT, require_utf8_schema=True)
        receipt = runner.verify_codex_execution_receipt(task_path, output_path, root=ROOT)
        if task.get("batch") != V_BATCH:
            raise ValidityAuditError(f"Replacement task batch mismatch: {entry['sample_id']}")
        if task.get("prompt_sha256_utf8") != entry["prompt_sha256_utf8"]:
            raise ValidityAuditError(f"Replacement task prompt mismatch: {entry['sample_id']}")
        if receipt.get("sent_prompt_sha256_utf8") != entry["prompt_sha256_utf8"]:
            raise ValidityAuditError(f"Replacement receipt prompt mismatch: {entry['sample_id']}")
        if receipt.get("output_sha256") != runner.sha256_file(output_path):
            raise ValidityAuditError(f"Replacement output hash mismatch: {entry['sample_id']}")
        accepted[entry["sample_id"]] = {
            **entry,
            "task_sha256": task["task_sha256"],
            "receipt_sha256": receipt["receipt_sha256"],
            "receipt_path": receipt["receipt_path"],
            "output_path": receipt["output_path"],
            "output_sha256": receipt["output_sha256"],
            "actual_sent_prompt_sha256": receipt["sent_prompt_sha256_utf8"],
            "status": "accepted",
        }
    if len(accepted) != 6:
        raise ValidityAuditError("Expected six accepted replacements.")
    return accepted


def _write_completion_report(report: str) -> None:
    if COMPLETION_REPORT_PATH.exists():
        _ensure_existing_or_equal(COMPLETION_REPORT_PATH, report.encode("utf-8"))
    else:
        _write_once_text(COMPLETION_REPORT_PATH, report)


def freeze() -> dict[str, Any]:
    if VERDICT_SET_PATH.exists():
        raise ValidityAuditError(f"Verdict set already exists; refusing to rewrite: {VERDICT_SET_PATH}")
    audit = _load_json(AUDIT_PATH)
    plan = _load_plan()
    _assert_historical_snapshot(audit["historical_snapshot"])
    if runner.sha256_file(SOURCE_MANIFEST_PATH) != audit["source_manifest_sha256"]:
        raise ValidityAuditError("Historical formal manifest changed after the audit.")
    replacements = _replacement_acceptance(plan)
    original_rows = {str(item["sample_id"]): item for item in audit["samples"]}
    final_samples: list[dict[str, Any]] = []
    excluded_originals: list[dict[str, Any]] = []
    for sample_id, record in original_rows.items():
        if record["verdict_included"]:
            final_samples.append(
                {
                    "sample_id": sample_id,
                    "output_sha256": record["output_sha256"],
                    "actual_sent_prompt_sha256": record["actual_sent_prompt_sha256"],
                    "validity_classification": record["validity_classification"],
                    "replacement_provenance": None,
                }
            )
        else:
            excluded_originals.append(
                {
                    "sample_id": sample_id,
                    "output_sha256": record["output_sha256"],
                    "actual_sent_prompt_sha256": record["actual_sent_prompt_sha256"],
                    "validity_classification": record["validity_classification"],
                    "exclusion_reason": record["exclusion_reason"],
                    "superseded_by": sample_id,
                    "task_path": record["task_path"],
                    "receipt_path": record["receipt_path"],
                    "output_path": record["output_path"],
                }
            )
    for sample_id in sorted(replacements):
        replacement = replacements[sample_id]
        original = original_rows[sample_id]
        final_samples.append(
            {
                "sample_id": sample_id,
                "output_sha256": replacement["output_sha256"],
                "actual_sent_prompt_sha256": replacement["actual_sent_prompt_sha256"],
                "validity_classification": "PROMPT_REVISED",
                "replacement_provenance": {
                    "kind": "replacement",
                    "reason": "supersedes a confounded Case 04 triplet with one byte-identical safety clarification across A/B/C",
                    "supersedes_sample_id": sample_id,
                    "superseded_output_sha256": original["output_sha256"],
                    "superseded_prompt_sha256": original["actual_sent_prompt_sha256"],
                    "superseded_task_path": original["task_path"],
                    "superseded_receipt_path": original["receipt_path"],
                    "superseded_output_path": original["output_path"],
                    "replacement_task_path": replacement["task_path"],
                    "replacement_task_sha256": replacement["task_sha256"],
                    "replacement_receipt_path": replacement["receipt_path"],
                    "replacement_receipt_sha256": replacement["receipt_sha256"],
                    "replacement_output_path": replacement["output_path"],
                    "replacement_prompt_sha256": replacement["actual_sent_prompt_sha256"],
                    "safety_clarification_sha256": SAFETY_BLOCK_SHA256,
                },
            }
        )

    final_samples.sort(key=lambda item: item["sample_id"])
    if len(final_samples) != 36:
        raise ValidityAuditError(f"Final verdict set has {len(final_samples)} samples, expected 36.")
    if len({item["sample_id"] for item in final_samples}) != 36:
        raise ValidityAuditError("Final verdict set has duplicate sample IDs.")
    if len({item["output_sha256"] for item in final_samples}) != 36:
        raise ValidityAuditError("Final verdict set has duplicate output hashes.")
    counts = {group: 0 for group in GROUPS}
    for item in final_samples:
        group = item["sample_id"].split(":")[1]
        if group not in counts:
            raise ValidityAuditError(f"Unexpected final verdict group: {group}")
        counts[group] += 1
    counts["total"] = len(final_samples)
    if counts != {"A": 12, "B": 12, "C": 12, "total": 36}:
        raise ValidityAuditError(f"Final verdict counts are not balanced: {counts}")
    if len(excluded_originals) != 6:
        raise ValidityAuditError(f"Expected six excluded originals, found {len(excluded_originals)}.")

    verdict = {
        "schema_version": 1,
        "batch": V_BATCH,
        "status": "FROZEN",
        "visual_evaluation_performed": False,
        "source_manifest_path": audit["source_manifest_path"],
        "source_manifest_sha256": audit["source_manifest_sha256"],
        "historical_snapshot": audit["historical_snapshot"],
        "original_sample_audit": audit["samples"],
        "original_classification_counts": audit["original_classification_counts"],
        "affected_triplets": audit["affected_triplets"],
        "excluded_originals": excluded_originals,
        "samples": final_samples,
        "final_counts": counts,
        "replacement_policy": audit["replacement_policy"],
        "frozen_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_once_json(VERDICT_SET_PATH, verdict)
    verdict_hash = runner.sha256_file(VERDICT_SET_PATH)
    report = "\n".join(
        [
            "# Batch 4B.3-V Completion Report",
            "",
            "Status: FROZEN.",
            "",
            "## Audit result",
            "",
            f"- Accepted formal samples audited: {len(audit['samples'])}.",
            f"- Original CLEAN samples: {audit['original_classification_counts']['CLEAN']}.",
            f"- Original PROMPT_REVISED samples: {audit['original_classification_counts']['PROMPT_REVISED']}.",
            "- Affected/confounded triplets: case-04:r2 and case-04:r3.",
            "- Original outputs excluded from the verdict set: 6.",
            "",
            "## Replacements",
            "",
            "- Harmonized replacements performed: 6.",
            "- Replacement IDs: " + ", ".join(sorted(replacements)) + ".",
            "- Common safety clarification SHA-256: " + SAFETY_BLOCK_SHA256 + ".",
            "- Existing formal images, manifests, attempts, receipts, continuation records, and reports were preserved.",
            "",
            "## Frozen verdict set",
            "",
            f"- A: {counts['A']}",
            f"- B: {counts['B']}",
            f"- C: {counts['C']}",
            f"- Total: {counts['total']}",
            f"- Verdict-set SHA-256: {verdict_hash}.",
            "- Historical artifact snapshot: unchanged.",
            "- Visual evaluation/scoring performed: no.",
            "- Batch 4B.4 started: no.",
            "",
        ]
    )
    _write_completion_report(report)
    return {
        "status": "FROZEN",
        "verdict_set_path": _relative(VERDICT_SET_PATH),
        "completion_report_path": _relative(COMPLETION_REPORT_PATH),
        "final_counts": counts,
        "original_classification_counts": audit["original_classification_counts"],
        "affected_triplets": audit["affected_triplets"],
        "replacements": len(replacements),
        "verdict_set_sha256": verdict_hash,
        "visual_evaluation_performed": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true", help="Audit originals and prepare isolated replacement tasks.")
    modes.add_argument("--accept", metavar="SAMPLE_ID", help="Accept one generated replacement PNG.")
    modes.add_argument("--freeze", action="store_true", help="Validate replacements and freeze the verdict set.")
    parser.add_argument("--source", type=Path, help="Generated PNG source for --accept.")
    args = parser.parse_args(argv)
    try:
        if args.prepare:
            result = prepare()
        elif args.accept:
            if args.source is None:
                raise ValidityAuditError("--accept requires --source PATH.")
            result = accept(args.accept, args.source.expanduser().resolve(strict=False))
        else:
            result = freeze()
    except (ValidityAuditError, runner.ExperimentError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
