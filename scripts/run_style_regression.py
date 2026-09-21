#!/usr/bin/env python3
"""Frozen, human-evaluated Arco Style Transfer V1.0 Batch 4B runner.

This runner orchestrates the existing Runtime and ArcoRealAdapter. It does not
implement Style resolution, prompt compilation, Hygiene, image scoring, or
image repair. Real generation requires a host-provided builtin_image_gen
callable with the signature already accepted by ArcoRealAdapter.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import difflib
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
EVALUATION_DIR = ROOT / "evaluation" / "style-regression"
CASES_PATH = EVALUATION_DIR / "cases.yaml"
MANIFEST_PATH = EVALUATION_DIR / "manifest.jsonl"
ENVIRONMENT_PATH = EVALUATION_DIR / "environment.json"
ENVIRONMENT_HISTORY_DIR = EVALUATION_DIR / "environment"
INITIAL_ENVIRONMENT_PATH = ENVIRONMENT_HISTORY_DIR / "initial-post-selector-fix.json"
FINAL_PREFLIGHT_ENVIRONMENT_PATH = ENVIRONMENT_HISTORY_DIR / "batch-4b2u-final-preflight.json"
COMPLETION_REPORT_PATH = EVALUATION_DIR / "batch-4b2u-completion.md"
INPUT_FREEZE_PATH = EVALUATION_DIR / "inputs-freeze.json"
REFERENCE_SELECTION_DIR = EVALUATION_DIR / "reference-selection"
STYLE_CONTEXT_DIR = EVALUATION_DIR / "style-context"
PREFLIGHT_JSON_PATH = EVALUATION_DIR / "preflight-report-batch-4b3f-r2.json"
PREFLIGHT_MARKDOWN_PATH = EVALUATION_DIR / "preflight-report-batch-4b3f-r2.md"
PILOT_DIR = EVALUATION_DIR / "pilot" / "runs" / "batch-4b3f"
PILOT_MANIFEST_PATH = PILOT_DIR / "manifest.jsonl"
BLIND_MAP_PATH = EVALUATION_DIR / "blind-map.private.json"
CONTROL_RUNTIME_METADATA_PATH = EVALUATION_DIR / "control-runtime" / "corrected-legacy.json"
HOST_SMOKE_DIR = EVALUATION_DIR / "host-smoke"
HOST_SMOKE_REPORT_PATH = HOST_SMOKE_DIR / "result.json"
HOST_SMOKE_OUTPUT_PATH = HOST_SMOKE_DIR / "outputs" / "output.png"
HOST_SMOKE_PROMPT = "a simple red circle centered on a white background"
HOST_SMOKE_MTIME_SKEW_NS = 2_000_000_000
LEGACY_CODEX_TASK_SCHEMA_VERSION = 1
CODEX_TASK_SCHEMA_VERSION = 2
CODEX_ENVELOPE_SCHEMA_VERSION = 1
CODEX_SMOKE_TASK_PATH = "evaluation/style-regression/host-smoke/codex-task.json"
CODEX_SMOKE_REPORT_PATH = "evaluation/style-regression/host-smoke/result.json"
CODEX_PILOT_TASK_DIR = "evaluation/style-regression/pilot/runs/batch-4b3t-r2/tasks"
R_R2_PARENT_FINAL_PREFLIGHT_ENVIRONMENT_PATH = "batch-4b3t-final-preflight-r2.json"
R_PARENT_FINAL_PREFLIGHT_ENVIRONMENT_PATH = "batch-4b3t-formal-continuation-r3.json"
R_FINAL_PREFLIGHT_ENVIRONMENT_PATH = "batch-4b3t-formal-continuation-r4.json"
R_RETRY_FIX_FINAL_CAPTURE_PATH = "batch-4b3t-formal-continuation-r5.json"
R_PROTOCOL_REVISION_CAPTURE_PATH = "batch-4b3t-formal-continuation-r6.json"
R_PROTOCOL_REVISION_R7_CAPTURE_PATH = "batch-4b3t-formal-continuation-r7.json"
R_PROTOCOL_REVISION_R8_CAPTURE_PATH = "batch-4b3t-formal-continuation-r8.json"
R_PROTOCOL_REVISION_R9_CAPTURE_PATH = "batch-4b3t-formal-continuation-r9.json"
R_FORMAL_CONTINUATION_R10_CAPTURE_PATH = "batch-4b3t-formal-continuation-r10.json"
R_FORMAL_CONTINUATION_R14_CAPTURE_PATH = "batch-4b3t-formal-continuation-r14.json"
R_PROTOCOL_REVISION_PATHS = {
    "case-04:B:r2": "evaluation/style-regression/protocol-revisions/r6/protocol.json",
    "case-04:C:r2": "evaluation/style-regression/protocol-revisions/r7/protocol.json",
    "case-04:A:r3": "evaluation/style-regression/protocol-revisions/r11/protocol.json",
    "case-04:B:r3": "evaluation/style-regression/protocol-revisions/r12/protocol.json",
    "case-04:C:r3": "evaluation/style-regression/protocol-revisions/r13/protocol.json",
}
R_COMPLETION_REPORT_PATH = "batch-4b.3t-r2-completion.md"
R_PREFLIGHT_JSON_PATH = "preflight-report-batch-4b3t-r4.json"
R_PREFLIGHT_MARKDOWN_PATH = "preflight-report-batch-4b3t-r4.md"
R_PREFLIGHT_LIVE_JSON_PATH = "preflight-report-batch-4b3t-live-r4.json"
R_PREFLIGHT_LIVE_MARKDOWN_PATH = "preflight-report-batch-4b3t-live-r4.md"
FORMAL_TASK_DIR = "evaluation/style-regression/formal/tasks"
TECHNICAL_FAILURE_KINDS = {
    "provider_tool_failure",
    "no_output",
    "invalid_empty_output",
    "corrupt_image",
    "task_transport",
    "manifest_write_failure",
}
FAILURE_POLICY_VERSION = 1
CODEX_FAILURE_POLICIES: dict[str, dict[str, Any]] = {
    "imagegen_network_send": {
        "failure_kind": "provider_tool_failure",
        "retryable": True,
        "max_new_attempts": 2,
        "backoff_seconds": (30, 60),
    },
    "imagegen_timeout": {
        "failure_kind": "provider_tool_failure",
        "retryable": True,
        "max_new_attempts": 1,
        "backoff_seconds": (30,),
    },
    "imagegen_path_missing": {
        "failure_kind": "task_transport",
        "retryable": True,
        "max_new_attempts": 1,
        "backoff_seconds": (0,),
    },
    "imagegen_safety_block": {
        "failure_kind": "provider_policy_refusal",
        "retryable": False,
        "max_new_attempts": 0,
        "backoff_seconds": (),
    },
    "imagegen_tool_error": {
        "failure_kind": "provider_unknown_failure",
        "retryable": False,
        "max_new_attempts": 0,
        "backoff_seconds": (),
    },
    "operator_rejected": {
        "failure_kind": "operator_rejected",
        "retryable": False,
        "max_new_attempts": 0,
        "backoff_seconds": (),
    },
}
CODEX_FAILURE_CODE_ALIASES = {
    "moderation_blocked": "imagegen_safety_block",
    "codex_generation_failed": "imagegen_tool_error",
    "rejected": "operator_rejected",
}
PNG_SIGNATURE = bytes.fromhex("89504E470D0A1A0A")
CASE_IDS = ["case-01", "case-02", "case-03", "case-04"]
EXPECTED_STYLE_FAMILIES = {
    "case-01": "clean_cel",
    "case-02": "soft_painterly_anime",
    "case-03": "atmospheric_complex_lighting",
    "case-04": "watercolor_grain_visible_texture",
}
GROUPS = ("A", "B", "C")
SUPPORTED_GROUPS = ("H", "A", "B", "C")
HISTORICAL_GROUP = "H"
GENERATED_GROUPS = ("A", "B", "C")
EXPECTED_REPLICATES = 3
EXPECTED_SAMPLE_COUNT = 36
WHO_DO_NOT_INHERIT = [
    "identity",
    "hair",
    "eyes",
    "face",
    "body_proportions",
    "outfit",
    "variant",
]

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from arco_real_adapter import ArcoRealAdapter, ArcoRealAdapterError  # noqa: E402
from reference_runtime import (  # noqa: E402
    STYLE_AXES,
    ReferenceRuntimeError,
    build_invocation_plan,
    compile_prompt,
    compile_rendering_hygiene,
    resolve_style_context,
    resolve_style_references,
    select_references,
)


class ExperimentError(RuntimeError):
    """An invalid or incomplete Batch 4B experiment input."""


def sanitize_codex_failure_detail(value: str, *, limit: int = 700) -> str:
    """Keep actionable provider diagnostics without retaining credential-like text."""
    detail = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <REDACTED>", str(value))
    detail = re.sub(r"(?i)(api[_-]?key|authorization|token)\s*[:=]\s*[^\s,;]+", r"\1=<REDACTED>", detail)
    detail = re.sub(r"\s+", " ", detail).strip()
    return detail[:limit]


def classify_codex_failure(failure_code: str, failure_message: str) -> dict[str, Any]:
    """Normalize one Codex image failure into the fail-closed retry policy."""
    code = CODEX_FAILURE_CODE_ALIASES.get(str(failure_code).strip(), str(failure_code).strip())
    detail = sanitize_codex_failure_detail(failure_message)
    if re.search(r"moderation_blocked|rejected by the safety system|safety_violations", detail, re.I):
        code = "imagegen_safety_block"
    elif code == "imagegen_tool_error" and re.search(
        r"network error|error sending request|connection (?:reset|closed)|socket", detail, re.I
    ):
        code = "imagegen_network_send"
    elif code == "imagegen_tool_error" and re.search(r"timed?\s*out|timeout|deadline", detail, re.I):
        code = "imagegen_timeout"
    if code not in CODEX_FAILURE_POLICIES:
        raise ExperimentError(f"Unknown Codex image failure code: {failure_code}")
    policy = CODEX_FAILURE_POLICIES[code]
    return {
        "failure_policy_version": FAILURE_POLICY_VERSION,
        "failure_code": code,
        "failure_kind": policy["failure_kind"],
        "retryable": bool(policy["retryable"]),
        "max_new_attempts": int(policy["max_new_attempts"]),
        "backoff_seconds": list(policy["backoff_seconds"]),
        "failure_reason": detail,
    }


def codex_failure_retry_state(attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the current retry decision for the latest failed attempt."""
    if not attempts or attempts[-1].get("status") != "failed":
        raise ExperimentError("Codex retry state requires a latest failed attempt.")
    latest = attempts[-1]
    policy = classify_codex_failure(
        str(latest.get("failure_code", "imagegen_tool_error")),
        str(latest.get("failure_reason", "")),
    )
    same_code_failures = 0
    for attempt in attempts:
        if attempt.get("status") != "failed":
            continue
        attempt_policy = classify_codex_failure(
            str(attempt.get("failure_code", "imagegen_tool_error")),
            str(attempt.get("failure_reason", "")),
        )
        if attempt_policy["failure_code"] == policy["failure_code"]:
            same_code_failures += 1
    retry_allowed = bool(
        policy["retryable"]
        and latest.get("retryable") is True
        and same_code_failures <= policy["max_new_attempts"]
    )
    retry_after_seconds = None
    if retry_allowed:
        backoff = policy["backoff_seconds"]
        retry_after_seconds = int(backoff[min(same_code_failures - 1, len(backoff) - 1)])
    return {
        **policy,
        "failure_number_for_code": same_code_failures,
        "retry_allowed": retry_allowed,
        "retry_after_seconds": retry_after_seconds,
        "next_action": "retry_after_backoff" if retry_allowed else "blocked",
    }


def _mapping_path(result: Mapping[str, Any], *keys: str) -> str | None:
    current: Any = result
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return str(current) if isinstance(current, (str, Path)) and str(current).strip() else None


def resolve_codex_generated_png_path(
    result: Mapping[str, Any],
    *,
    generated_root: Path | None = None,
) -> Path:
    """Resolve and validate a Codex ImageGen PNG path from structured data or text."""
    if not isinstance(result, Mapping):
        raise ExperimentError("Codex image result has no usable PNG path.")
    candidates = [
        _mapping_path(result, "generated_path"),
        _mapping_path(result, "file_path"),
        _mapping_path(result, "path"),
        _mapping_path(result, "structuredContent", "generated_path"),
        _mapping_path(result, "structuredContent", "file_path"),
        _mapping_path(result, "structuredContent", "path"),
    ]
    text_parts: list[str] = []
    for block in result.get("content", []) if isinstance(result.get("content"), list) else []:
        if isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str):
            text_parts.append(str(block["text"]))
    for match in re.finditer(r"[A-Za-z]:\\[^\r\n\"']+?\.png", "\n".join(text_parts), re.I):
        candidates.append(match.group(0))
    selected = next((Path(value).expanduser().resolve(strict=False) for value in candidates if value), None)
    if selected is None:
        raise ExperimentError("Codex image result has no usable PNG path.")
    root = (generated_root or (Path.home() / ".codex" / "generated_images")).expanduser().resolve(strict=False)
    try:
        selected.relative_to(root)
    except ValueError as exc:
        raise ExperimentError("Codex generated PNG path is outside the managed generated-images directory.") from exc
    if selected.suffix.lower() != ".png" or not selected.is_file():
        raise ExperimentError("Codex generated PNG path is missing or is not a PNG file.")
    with selected.open("rb") as handle:
        if handle.read(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
            raise ExperimentError("Codex generated PNG signature is invalid.")
    return selected


def _formal_protocol_revision(sample_key: str, *, root: Path = ROOT) -> dict[str, Any] | None:
    """Load the single user-authorized r6 safety clarification, if applicable."""
    relative_path = R_PROTOCOL_REVISION_PATHS.get(sample_key)
    if relative_path is None:
        return None
    path = root / relative_path
    if not path.is_file():
        return None
    revision = _load_json(path)
    if (
        revision.get("record_kind") != "formal-prompt-safety-revision"
        or revision.get("authorized_by") != "user"
        or revision.get("sample_key") != sample_key
        or revision.get("superseded_failure_code") != "imagegen_safety_block"
    ):
        raise ExperimentError("The r6 formal prompt revision metadata is invalid.")
    prompt_path = _repo_path(str(revision.get("revised_prompt_path", "")), root=root)
    if not prompt_path.is_file() or sha256_file(prompt_path) != revision.get("revised_prompt_file_sha256"):
        raise ExperimentError("The r6 revised prompt file is missing or changed.")
    prompt = prompt_path.read_text(encoding="utf-8").rstrip("\r\n")
    if hashlib.sha256(prompt.encode("utf-8")).hexdigest() != revision.get("revised_prompt_sha256_utf8"):
        raise ExperimentError("The r6 revised prompt text hash is invalid.")
    candidate = _repo_path(str(revision.get("candidate_path", "")), root=root)
    if not candidate.is_file() or sha256_file(candidate) != revision.get("candidate_sha256"):
        raise ExperimentError("The r6 generated candidate is missing or changed.")
    return {**revision, "prompt": prompt, "prompt_path": prompt_path, "path": path}


def _codex_task_payload(task: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(task)
    payload.pop("task_sha256", None)
    return payload


def _require_utf8_execution_environment() -> None:
    if os.environ.get("PYTHONUTF8") != "1":
        raise ExperimentError("Codex-managed execution requires PYTHONUTF8=1 before Python starts.")
    if os.environ.get("PYTHONIOENCODING", "").lower() not in {"utf-8", "utf8", "utf-8:strict"}:
        raise ExperimentError("Codex-managed execution requires PYTHONIOENCODING=utf-8 before Python starts.")


def build_codex_task(
    *,
    task_id: str,
    task_kind: str,
    case_id: str | None,
    group: str | None,
    replicate: int | None,
    prompt: str,
    referenced_image_paths: Sequence[str | Path],
    reference_ids: Sequence[str],
    expected_output_path: str,
    frozen_input_hashes: Mapping[str, Any],
    created_at: str | None = None,
    batch: str = "4B.2-R",
) -> dict[str, Any]:
    """Build a hash-addressed, immutable Codex generation task payload."""
    if task_kind not in {"smoke", "pilot", "formal"}:
        raise ExperimentError(f"Unsupported Codex task kind: {task_kind}")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ExperimentError("Codex task prompt must be a non-empty string.")
    if len(referenced_image_paths) != len(reference_ids):
        raise ExperimentError("Codex task reference paths and IDs must have identical order and length.")
    if task_kind == "smoke" and (case_id is not None or group is not None or replicate is not None or referenced_image_paths):
        raise ExperimentError("Codex smoke tasks must be reference-free and have no sample identifiers.")
    if task_kind in {"pilot", "formal"} and (
        case_id not in CASE_IDS or group not in GENERATED_GROUPS or not isinstance(replicate, int) or replicate < 1
    ):
        raise ExperimentError("Codex sample task requires valid case, group, and replicate identifiers.")
    payload: dict[str, Any] = {
        "schema_version": CODEX_TASK_SCHEMA_VERSION,
        "task_id": task_id,
        "task_kind": task_kind,
        "batch": batch,
        "case_id": case_id,
        "group": group,
        "replicate": replicate,
        "prompt": prompt,
        "prompt_encoding": "utf-8",
        "prompt_sha256_utf8": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "referenced_image_paths": [str(path) for path in referenced_image_paths],
        "reference_ids": list(reference_ids),
        "expected_output_path": expected_output_path,
        "frozen_input_hashes": copy.deepcopy(dict(frozen_input_hashes)),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
    }
    payload["task_sha256"] = sha256_json(payload)
    return payload


def write_codex_task(task: Mapping[str, Any], *, path: Path) -> dict[str, Any]:
    """Create a task file once; existing files are never replaced."""
    if task.get("task_sha256") != sha256_json(_codex_task_payload(task)):
        raise ExperimentError("Codex task hash is invalid before write.")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(task), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ExperimentError(f"Codex task already exists; replacement is forbidden: {path}") from exc
    return dict(task)


def load_codex_task(
    path: Path,
    *,
    root: Path = ROOT,
    verify_frozen_inputs: bool = True,
    require_utf8_schema: bool = False,
    legacy_runner_hash_allowlist: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Load a UTF-8 task file and verify its digest and declared input hashes.

    Schema 1 is readable for audit and migration only. Dispatch, receipt, and
    acceptance paths request the version 2 UTF-8 transport fields explicitly.
    """
    try:
        task = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentError(f"Codex task cannot be read: {path}: {exc}") from exc
    if not isinstance(task, Mapping) or task.get("schema_version") not in {
        LEGACY_CODEX_TASK_SCHEMA_VERSION,
        CODEX_TASK_SCHEMA_VERSION,
    }:
        raise ExperimentError("Codex task schema is invalid.")
    schema_version = task.get("schema_version")
    if require_utf8_schema and schema_version != CODEX_TASK_SCHEMA_VERSION:
        raise ExperimentError("Codex execution requires immutable task schema version 2 with UTF-8 prompt fields.")
    if task.get("task_sha256") != sha256_json(_codex_task_payload(task)):
        raise ExperimentError("Codex task hash does not match its canonical payload.")
    prompt = task.get("prompt")
    if not isinstance(prompt, str):
        raise ExperimentError("Codex task prompt is not a string.")
    prompt_sha256_utf8 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if schema_version == LEGACY_CODEX_TASK_SCHEMA_VERSION:
        if task.get("prompt_sha256") != prompt_sha256_utf8:
            raise ExperimentError("Codex task prompt hash is invalid.")
    elif (
        task.get("prompt_encoding") != "utf-8"
        or task.get("prompt_sha256_utf8") != prompt_sha256_utf8
        or task.get("prompt_sha256") != prompt_sha256_utf8
    ):
        raise ExperimentError("Codex task prompt hash is invalid.")
    paths = task.get("referenced_image_paths")
    reference_ids = task.get("reference_ids")
    if not isinstance(paths, list) or not isinstance(reference_ids, list) or len(paths) != len(reference_ids):
        raise ExperimentError("Codex task ordered reference paths and IDs are invalid.")
    frozen = task.get("frozen_input_hashes") or {}
    files = frozen.get("files", {}) if isinstance(frozen, Mapping) else {}
    if not isinstance(files, Mapping):
        raise ExperimentError("Codex task frozen file hashes are invalid.")
    references = frozen.get("references", []) if isinstance(frozen, Mapping) else []
    if not isinstance(references, list):
        raise ExperimentError("Codex task ordered reference hashes are invalid.")
    if len(references) != len(paths):
        if paths or references:
            raise ExperimentError("Codex task ordered reference paths, IDs, and hashes differ in length.")
    for index, item in enumerate(references):
        if not isinstance(item, Mapping) or (
            item.get("reference_id") != reference_ids[index]
            or str(item.get("path")) != str(paths[index])
            or not isinstance(item.get("sha256"), str)
        ):
            raise ExperimentError("Codex task ordered reference identifiers or hashes differ from its paths.")
    if verify_frozen_inputs:
        for relative_path, expected_hash in files.items():
            try:
                frozen_path = _repo_path(str(relative_path), root=root)
            except ExperimentError as exc:
                raise ExperimentError(f"Codex task frozen input path is unsafe: {relative_path}") from exc
            if not frozen_path.is_file() or not isinstance(expected_hash, str):
                raise ExperimentError(f"Codex task frozen input hash mismatch: {relative_path}")
            current_hash = sha256_file(frozen_path)
            if current_hash == expected_hash:
                continue
            allowlisted = (legacy_runner_hash_allowlist or {}).get(str(task.get("task_sha256")))
            if (
                relative_path == "scripts/run_style_regression.py"
                and isinstance(allowlisted, Mapping)
                and allowlisted.get("task_path") == _relative_path(path, root=root)
                and allowlisted.get("runner_sha256") == expected_hash
                and allowlisted.get("task_kind") == task.get("task_kind")
                and allowlisted.get("task_file_sha256") == sha256_file(path)
            ):
                continue
            raise ExperimentError(f"Codex task frozen input hash mismatch: {relative_path}")
    return dict(task)


def _task_attempt_number(task: Mapping[str, Any]) -> int:
    match = re.search(r":attempt-(\d+)$", str(task.get("task_id", "")))
    return int(match.group(1)) if match else 1


def _task_sample_id(task: Mapping[str, Any]) -> str:
    if task.get("task_kind") == "smoke":
        return "smoke"
    return _sample_key(str(task.get("case_id")), str(task.get("group")), int(task.get("replicate", 0)))


def _task_references_ordered(task: Mapping[str, Any]) -> list[dict[str, str]]:
    frozen = task.get("frozen_input_hashes") or {}
    references = frozen.get("references", []) if isinstance(frozen, Mapping) else []
    return [
        {
            "reference_id": str(item["reference_id"]),
            "path": str(item["path"]),
            "sha256": str(item["sha256"]),
        }
        for item in references
    ]


def verify_codex_task_prompt(task: Mapping[str, Any], prompt: str) -> str:
    """Fail closed unless the exact string about to be sent matches task UTF-8 bytes."""
    if task.get("schema_version") != CODEX_TASK_SCHEMA_VERSION or task.get("prompt_encoding") != "utf-8":
        raise ExperimentError("Codex prompt dispatch requires task schema version 2 with prompt_encoding=utf-8.")
    if not isinstance(prompt, str):
        raise ExperimentError("The intended Codex image prompt is not a string.")
    sent_digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if sent_digest != task.get("prompt_sha256_utf8") or prompt != task.get("prompt"):
        raise ExperimentError("The exact prompt intended for image generation differs from the frozen UTF-8 prompt hash.")
    return sent_digest


def _build_codex_task_envelope(task: Mapping[str, Any]) -> dict[str, Any]:
    if task.get("schema_version") != CODEX_TASK_SCHEMA_VERSION:
        raise ExperimentError("Codex task envelope requires task schema version 2.")
    verify_codex_task_prompt(task, str(task.get("prompt", "")))
    prompt_bytes = str(task["prompt"]).encode("utf-8")
    return {
        "envelope_schema_version": CODEX_ENVELOPE_SCHEMA_VERSION,
        "task_path": None,
        "task_id": task["task_id"],
        "task_kind": task["task_kind"],
        "task_sha256": task["task_sha256"],
        "sample_id": _task_sample_id(task),
        "attempt": _task_attempt_number(task),
        "prompt_encoding": "utf-8",
        "prompt_utf8_base64": base64.b64encode(prompt_bytes).decode("ascii"),
        "prompt_sha256_utf8": task["prompt_sha256_utf8"],
        "reference_ids_ordered": list(task["reference_ids"]),
        "reference_paths_ordered": list(task["referenced_image_paths"]),
        "references_ordered": _task_references_ordered(task),
        "expected_output_path": task["expected_output_path"],
    }


def build_codex_task_envelope(task_path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    """Read an immutable task with explicit UTF-8 and emit a printable ASCII envelope."""
    task = load_codex_task(task_path, root=root, require_utf8_schema=True)
    envelope = _build_codex_task_envelope(task)
    envelope["task_path"] = _relative_path(task_path, root=root)
    return envelope


def decode_codex_task_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly decode and verify the ASCII Base64 transport before any generator call."""
    if not isinstance(envelope, Mapping) or envelope.get("envelope_schema_version") != CODEX_ENVELOPE_SCHEMA_VERSION:
        raise ExperimentError("Codex task envelope schema is invalid.")
    encoded = envelope.get("prompt_utf8_base64")
    if not isinstance(encoded, str) or not encoded.isascii():
        raise ExperimentError("Codex task envelope prompt payload must be ASCII Base64.")
    if envelope.get("prompt_encoding") != "utf-8":
        raise ExperimentError("Codex task envelope must declare prompt_encoding=utf-8.")
    try:
        prompt_bytes = base64.b64decode(encoded.encode("ascii"), validate=True)
        prompt = prompt_bytes.decode("utf-8", errors="strict")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ExperimentError(f"Codex task envelope prompt is not valid strict UTF-8 Base64: {exc}") from exc
    sent_digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if sent_digest != envelope.get("prompt_sha256_utf8"):
        raise ExperimentError("Codex task envelope prompt hash mismatch after UTF-8 decoding.")
    return {"prompt": prompt, "prompt_bytes": prompt_bytes, "sent_prompt_sha256_utf8": sent_digest}


def dispatch_codex_task(
    task_path: Path,
    envelope: Mapping[str, Any],
    generator: Callable[..., Any],
    *,
    root: Path = ROOT,
) -> Any:
    """Reference dispatch seam: verify the complete envelope immediately before call."""
    task = load_codex_task(task_path, root=root, require_utf8_schema=True)
    expected = _build_codex_task_envelope(task)
    expected["task_path"] = _relative_path(task_path, root=root)
    if dict(envelope) != expected:
        raise ExperimentError("Codex task envelope differs from the immutable task identifiers or references.")
    decoded = decode_codex_task_envelope(envelope)
    sent_digest = verify_codex_task_prompt(task, decoded["prompt"])
    if sent_digest != decoded["sent_prompt_sha256_utf8"]:
        raise ExperimentError("Codex intended prompt digest changed immediately before generation.")
    _verify_task_reference_files(task)
    return generator(
        prompt=decoded["prompt"],
        referenced_image_paths=list(task["referenced_image_paths"]),
    )


def _verify_task_reference_files(task: Mapping[str, Any]) -> list[dict[str, str]]:
    references = _task_references_ordered(task)
    for reference in references:
        path = Path(reference["path"]).expanduser().resolve(strict=False)
        if not path.is_file() or sha256_file(path) != reference["sha256"]:
            raise ExperimentError(f"Codex task ordered reference hash mismatch: {reference['reference_id']}")
    return references


def _codex_execution_receipt_path(task_path: Path, *, root: Path = ROOT) -> Path:
    if not task_path.is_absolute():
        task_path = root / task_path
    if task_path.parent.name == "tasks":
        receipt_root = task_path.parent.parent / "receipts"
    else:
        receipt_root = task_path.parent / "receipts"
    return receipt_root / f"{task_path.stem}.json"


def _write_codex_execution_receipt_file(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = json.dumps(dict(receipt), ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="ascii", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ExperimentError(f"Codex execution receipt already exists; replacement is forbidden: {path}") from exc


def write_codex_execution_receipt(
    task_path: Path,
    generated_path: Path | str,
    *,
    sent_prompt: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Record a write-once receipt after generation and before task acceptance."""
    task = load_codex_task(task_path, root=root, require_utf8_schema=True)
    sent_digest = verify_codex_task_prompt(task, sent_prompt)
    references = _verify_task_reference_files(task)
    source_path = Path(generated_path).expanduser().resolve(strict=False)
    if not source_path.is_file() or source_path.stat().st_size == 0:
        raise ExperimentError("Codex receipt requires a non-empty generated output file.")
    with source_path.open("rb") as handle:
        if handle.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ExperimentError("Codex receipt output is not a PNG.")
    expected_output = _repo_path(str(task.get("expected_output_path", "")), root=root)
    if expected_output.suffix.lower() != ".png":
        raise ExperimentError("Codex task expected output path must end in .png.")
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "task_path": _relative_path(task_path, root=root),
        "task_id": task["task_id"],
        "sample_id": _task_sample_id(task),
        "attempt": _task_attempt_number(task),
        "task_sha256": task["task_sha256"],
        "sent_prompt_sha256_utf8": sent_digest,
        "references_ordered": references,
        "output_path": _relative_path(expected_output, root=root),
        "output_sha256": sha256_file(source_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt["receipt_sha256"] = sha256_json(receipt)
    receipt_path = _codex_execution_receipt_path(task_path, root=root)
    _write_codex_execution_receipt_file(receipt_path, receipt)
    return {**receipt, "receipt_path": _relative_path(receipt_path, root=root)}


def verify_codex_execution_receipt(
    task_path: Path,
    generated_path: Path | str,
    *,
    root: Path = ROOT,
    expected_receipt_path: str | None = None,
    expected_receipt_sha256: str | None = None,
    legacy_runner_hash_allowlist: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    task = load_codex_task(
        task_path,
        root=root,
        require_utf8_schema=True,
        legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
    )
    receipt_path = _codex_execution_receipt_path(task_path, root=root)
    if expected_receipt_path is not None and _relative_path(receipt_path, root=root) != expected_receipt_path:
        raise ExperimentError("Codex execution receipt path differs from the accepted manifest record.")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentError(f"Codex execution receipt cannot be read: {receipt_path}: {exc}") from exc
    if not isinstance(receipt, Mapping):
        raise ExperimentError("Codex execution receipt schema is invalid.")
    payload = dict(receipt)
    receipt_digest = payload.pop("receipt_sha256", None)
    if receipt_digest != sha256_json(payload):
        raise ExperimentError("Codex execution receipt hash is invalid or tampered.")
    if receipt.get("schema_version") != 1:
        raise ExperimentError("Codex execution receipt schema version is unsupported.")
    if expected_receipt_sha256 is not None and receipt_digest != expected_receipt_sha256:
        raise ExperimentError("Codex execution receipt hash differs from the accepted manifest record.")
    sent_digest = hashlib.sha256(str(task.get("prompt", "")).encode("utf-8")).hexdigest()
    if (
        receipt.get("task_path") != _relative_path(task_path, root=root)
        or receipt.get("task_id") != task.get("task_id")
        or receipt.get("sample_id") != _task_sample_id(task)
        or receipt.get("attempt") != _task_attempt_number(task)
        or receipt.get("task_sha256") != task.get("task_sha256")
        or receipt.get("sent_prompt_sha256_utf8") != task.get("prompt_sha256_utf8")
        or receipt.get("sent_prompt_sha256_utf8") != sent_digest
        or receipt.get("references_ordered") != _task_references_ordered(task)
        or receipt.get("output_path") != task.get("expected_output_path")
    ):
        raise ExperimentError("Codex execution receipt identifiers, prompt, references, or output path differ from its task.")
    _verify_task_reference_files(task)
    source_path = Path(generated_path).expanduser().resolve(strict=False)
    if not source_path.is_file() or not source_path.stat().st_size:
        raise ExperimentError("Codex execution receipt output is missing or empty.")
    if receipt.get("output_sha256") != sha256_file(source_path):
        raise ExperimentError("Codex execution receipt output hash differs from the generated image.")
    return {**dict(receipt), "receipt_path": _relative_path(receipt_path, root=root)}


def accept_codex_task_output(
    task_path: Path, generated_path: Path | str, *, root: Path = ROOT,
    legacy_runner_hash_allowlist: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Validate and copy one fresh Codex PNG to the task's frozen destination."""
    task = load_codex_task(
        task_path, root=root, legacy_runner_hash_allowlist=legacy_runner_hash_allowlist
    )
    receipt: dict[str, Any] | None = None
    if task.get("task_kind") in {"pilot", "formal"}:
        task = load_codex_task(
            task_path, root=root, require_utf8_schema=True,
            legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
        )
        receipt = verify_codex_execution_receipt(
            task_path, generated_path, root=root,
            legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
        )
    source_path = Path(generated_path).expanduser().resolve(strict=False)
    if not source_path.is_file() or source_path.stat().st_size == 0:
        raise ExperimentError("Codex generated image is missing or empty.")
    with source_path.open("rb") as handle:
        signature = handle.read(8)
    if signature != b"\x89PNG\r\n\x1a\n":
        raise ExperimentError("Codex generated image is not a PNG.")
    try:
        created_at = datetime.fromisoformat(str(task["created_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ExperimentError("Codex task creation timestamp is invalid.") from exc
    created_at_ns = int(created_at.timestamp() * 1_000_000_000)
    if source_path.stat().st_mtime_ns < created_at_ns - HOST_SMOKE_MTIME_SKEW_NS:
        raise ExperimentError("Codex generated image is stale for this task.")
    for reference_path in task["referenced_image_paths"]:
        if source_path == Path(reference_path).expanduser().resolve(strict=False):
            raise ExperimentError("Codex generated image aliases one of the task reference inputs.")
    expected_path = _repo_path(str(task.get("expected_output_path", "")), root=root)
    if expected_path.suffix.lower() != ".png":
        raise ExperimentError("Codex task expected output path must end in .png.")
    if expected_path.exists():
        raise ExperimentError(f"Codex task output already exists; replacement is forbidden: {expected_path}")
    source_hash = sha256_file(source_path)
    frozen = task.get("frozen_input_hashes") or {}
    reference_hashes = frozen.get("references", []) if isinstance(frozen, Mapping) else []
    known_reference_hashes = {
        item.get("sha256") for item in reference_hashes if isinstance(item, Mapping)
    }
    if source_hash in known_reference_hashes:
        raise ExperimentError("Codex output hash matches one of the task reference inputs.")
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source_path, expected_path)
        if not expected_path.is_file() or expected_path.stat().st_size == 0:
            raise ExperimentError("Codex output copy is missing or empty.")
        with expected_path.open("rb") as handle:
            if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ExperimentError("Codex output copy is not a PNG.")
        output_hash = sha256_file(expected_path)
        if output_hash != source_hash:
            raise ExperimentError("Codex output copy hash differs from the generated source.")
    except Exception:
        if expected_path.is_file():
            expected_path.unlink()
        raise
    result = {
        "output_path": expected_path,
        "output_sha256": output_hash,
        "source_path": source_path,
        "source_sha256": source_hash,
        "size_bytes": expected_path.stat().st_size,
    }
    if receipt is not None:
        result["receipt_path"] = receipt["receipt_path"]
        result["receipt_sha256"] = receipt["receipt_sha256"]
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    contents = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(contents.encode("utf-8")).hexdigest()


def sha256_tree(paths: Sequence[Path], *, root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((item for item in paths if item.is_file()), key=lambda p: p.as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExperimentError(f"Required file is missing: {path}") from exc
    except yaml.YAMLError as exc:
        raise ExperimentError(f"Invalid YAML in {path}: {exc}") from exc


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ExperimentError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise ExperimentError(f"Manifest row must be an object at {path}:{line_number}.")
        records.append(record)
    return records


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExperimentError(f"Required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExperimentError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExperimentError(f"Expected a JSON object in {path}.")
    return value


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_manifest_atomic(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _repo_path(value: str | Path, *, root: Path = ROOT) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ExperimentError(f"Path must stay inside the repository: {value}") from exc
    return resolved


def _evaluation_path(value: str | Path, *, root: Path = ROOT) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
    else:
        resolved = (root / "evaluation" / "style-regression" / candidate).resolve(strict=False)
    try:
        resolved.relative_to((root / "evaluation" / "style-regression").resolve())
    except ValueError as exc:
        raise ExperimentError(f"Experiment path must stay inside evaluation/style-regression: {value}") from exc
    return resolved


def _expected_case_ids(cases_document: Mapping[str, Any]) -> list[str]:
    cases = cases_document.get("cases")
    if not isinstance(cases, list):
        raise ExperimentError("cases.yaml must contain a cases list.")
    found = [case.get("case_id") for case in cases if isinstance(case, Mapping)]
    if found != CASE_IDS:
        raise ExperimentError(f"Expected cases in fixed order {CASE_IDS}, got {found}.")
    return found


def validate_case_schema(cases_document: Mapping[str, Any]) -> list[str]:
    """Validate frozen, non-asset case structure and return human-readable errors."""
    errors: list[str] = []
    try:
        case_ids = _expected_case_ids(cases_document)
    except ExperimentError as exc:
        return [str(exc)]

    if cases_document.get("schema_version") != 1:
        errors.append("cases.yaml schema_version must be 1.")
    if cases_document.get("replicates_per_case_group") != EXPECTED_REPLICATES:
        errors.append("The frozen experiment requires three replicates per Case × Group.")
    if cases_document.get("expected_sample_count") != EXPECTED_SAMPLE_COUNT:
        errors.append("The frozen A/B/C design must declare 36 samples.")
    shared = cases_document.get("shared_inputs")
    if not isinstance(shared, Mapping):
        errors.append("shared_inputs must be a mapping.")
        return errors
    if shared.get("identity_variant") != "casual-outfit" or shared.get("state") is not None:
        errors.append("Frozen shared Variant/State must be casual-outfit with no active State.")
    if shared.get("exposure_profile") != "upper_body":
        errors.append("Frozen exposure_profile must be upper_body.")
    base_scene = shared.get("base_scene_prompt")
    identity_ids = shared.get("identity_reference_ids")
    variant_ids = shared.get("variant_reference_ids")
    if not isinstance(base_scene, str) or not base_scene.strip():
        errors.append("shared_inputs.base_scene_prompt must be non-empty.")
    if not isinstance(identity_ids, list) or not identity_ids:
        errors.append("shared_inputs.identity_reference_ids must be a non-empty list.")
    if not isinstance(variant_ids, list) or not variant_ids:
        errors.append("shared_inputs.variant_reference_ids must be a non-empty list.")
    for field in (
        "pose_requirement",
        "composition_requirement",
        "camera_requirement",
        "exposure_requirement",
    ):
        value = shared.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"shared_inputs.{field} must be non-empty.")

    history = cases_document.get("historical_baseline")
    if (
        not isinstance(history, Mapping)
        or history.get("source_kind") != "historical_outputs"
        or history.get("group") != HISTORICAL_GROUP
        or history.get("formal_verdict") is not False
    ):
        errors.append("Group H must be declared as optional historical context outside the formal verdict.")
    groups = cases_document.get("groups")
    if not isinstance(groups, Mapping) or set(groups) != set(SUPPORTED_GROUPS):
        errors.append("groups must define H, A, B, and C.")
    elif (
        groups["H"].get("type") != "historical"
        or groups["H"].get("formal_verdict") is not False
        or groups["H"].get("optional") is not True
        or groups["A"].get("type") != "corrected_legacy"
        or groups["A"].get("formal_verdict") is not True
        or groups["A"].get("hygiene_enabled") is not False
        or groups["B"].get("type") != "style_transfer"
        or groups["B"].get("formal_verdict") is not True
        or groups["B"].get("hygiene_enabled") is not False
        or groups["C"].get("type") != "style_transfer_hygiene"
        or groups["C"].get("formal_verdict") is not True
        or groups["C"].get("hygiene_enabled") is not True
        or groups["A"].get("source") != "corrected_legacy"
        or groups["B"].get("source") != "current_runtime"
        or groups["C"].get("source") != "current_runtime"
    ):
        errors.append("Group H/A/B/C sources, verdict membership, or Hygiene settings differ from the frozen design.")

    for case_id, case in zip(case_ids, cases_document["cases"], strict=True):
        if not isinstance(case, Mapping):
            errors.append(f"{case_id} must be a mapping.")
            continue
        for field in (
            "name",
            "style_family",
            "base_scene_prompt",
            "pose_requirement",
            "composition_requirement",
            "camera_requirement",
            "exposure_requirement",
        ):
            if not isinstance(case.get(field), str) or not case[field].strip():
                errors.append(f"{case_id}.{field} must be non-empty.")
        if case.get("identity_variant") != shared.get("identity_variant"):
            errors.append(f"{case_id} changes the frozen Variant.")
        if case.get("state") != shared.get("state"):
            errors.append(f"{case_id} changes the frozen State.")
        if case.get("exposure_profile") != shared.get("exposure_profile"):
            errors.append(f"{case_id} changes the frozen exposure profile.")
        for field in (
            "identity_reference_ids",
            "identity_reference_hashes",
            "variant_reference_ids",
            "variant_reference_hashes",
        ):
            if case.get(field) != shared.get(field):
                errors.append(f"{case_id} changes shared {field}.")
        if case.get("style_family") != EXPECTED_STYLE_FAMILIES[case_id]:
            errors.append(f"{case_id} does not match its frozen Style family.")
        for field in ("identity_reference_hashes", "variant_reference_hashes"):
            values = case.get(field)
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in values)
            ):
                errors.append(f"{case_id}.{field} must contain frozen SHA-256 values.")
        for field in (
            "base_scene_prompt",
            "pose_requirement",
            "composition_requirement",
            "camera_requirement",
            "exposure_requirement",
        ):
            if case.get(field) != shared.get(field):
                errors.append(f"{case_id} changes shared {field}.")
        external = case.get("external_reference")
        if not isinstance(external, Mapping):
            errors.append(f"{case_id}.external_reference must be a mapping.")
            continue
        if external.get("reference_id") != f"external-style-0{case_id[-1]}":
            errors.append(f"{case_id} has an unexpected external reference ID.")
        if not isinstance(external.get("path"), str) or not external["path"].strip():
            errors.append(f"{case_id} requires an external reference path.")
        if external.get("role") != "style_reference":
            errors.append(f"{case_id} Style Reference role must be style_reference.")
        if external.get("duties") != ["style_reference"]:
            errors.append(f"{case_id} Style Reference duties must contain only style_reference.")
        if external.get("filename") != Path(str(external.get("path", ""))).name:
            errors.append(f"{case_id} Style Reference filename must match its private path.")
        external_hash = external.get("sha256")
        if external_hash is None:
            errors.append(f"{case_id} external reference SHA-256 is not frozen.")
        elif (
            not isinstance(external_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", external_hash)
        ):
            errors.append(f"{case_id} external reference SHA-256 is invalid.")
        if case.get("external_reference_hashes") != [external.get("sha256")]:
            errors.append(f"{case_id} external_reference_hashes must match its Primary reference hash.")
        if external.get("style_priority", "primary") != "primary":
            errors.append(f"{case_id} external Style Reference must be Primary.")
        if not isinstance(external.get("provenance"), str) or not external.get("provenance", "").strip():
            errors.append(f"{case_id} Style Reference provenance is missing.")
        expected_axes = case.get("expected_relevant_style_axes")
        if (
            not isinstance(expected_axes, list)
            or not expected_axes
            or any(axis not in STYLE_AXES for axis in expected_axes)
            or len(set(expected_axes)) != len(expected_axes)
        ):
            errors.append(f"{case_id} has invalid expected_relevant_style_axes.")
        brief = external.get("style_brief")
        if isinstance(brief, Mapping):
            errors.append(f"{case_id} Style Brief must be stored as a separately hashed file, not inline.")
        brief_path = external.get("style_brief_path")
        if not isinstance(brief_path, str) or not brief_path.strip():
            errors.append(f"{case_id} Style Brief is missing; inspect and freeze it before preflight.")
        brief_hash = external.get("style_brief_sha256")
        if not isinstance(brief_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", brief_hash):
            errors.append(f"{case_id} Style Brief SHA-256 is not frozen.")
        expected_order = (
            list(case.get("identity_reference_ids") or [])
            + list(case.get("variant_reference_ids") or [])
            + [str(external.get("reference_id"))]
        )
        if case.get("reference_order") != expected_order:
            errors.append(f"{case_id} reference_order does not match the frozen selected references.")
    return errors


def compose_scene_prompt(case: Mapping[str, Any]) -> str:
    return "\n".join(
        str(case[field]).strip()
        for field in (
            "base_scene_prompt",
            "pose_requirement",
            "composition_requirement",
            "camera_requirement",
            "exposure_requirement",
        )
    )


def _case_by_id(cases_document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {case["case_id"]: case for case in cases_document["cases"]}


def _control_runtime_metadata(root: Path = ROOT) -> dict[str, Any]:
    metadata_path = root / "evaluation" / "style-regression" / "control-runtime" / "corrected-legacy.json"
    if not metadata_path.is_file():
        raise ExperimentError("Corrected Legacy control runtime metadata is missing.")
    metadata = _load_json(metadata_path)
    if metadata.get("type") != "corrected_legacy" or metadata.get("purpose") != "evaluation_only":
        raise ExperimentError("Control runtime metadata must identify an evaluation-only corrected_legacy runtime.")
    worktree_value = metadata.get("worktree_path")
    if not isinstance(worktree_value, str) or not worktree_value.strip():
        raise ExperimentError("Corrected Legacy worktree_path is missing.")
    worktree = Path(worktree_value).resolve()
    if _git_output(worktree, "branch", "--show-current") != metadata.get("branch"):
        raise ExperimentError("Corrected Legacy branch differs from its frozen metadata.")
    runtime_path = worktree / "scripts" / "reference_runtime.py"
    if not runtime_path.is_file():
        raise ExperimentError(f"Corrected Legacy Runtime is missing: {runtime_path}")
    revision = _git_output(worktree, "rev-parse", "HEAD")
    if revision != metadata.get("selector_patch_revision"):
        raise ExperimentError("Corrected Legacy revision differs from its frozen metadata.")
    if _git_output(worktree, "status", "--porcelain=v1"):
        raise ExperimentError("Corrected Legacy worktree must be clean.")
    base_revision = metadata.get("base_revision")
    if not isinstance(base_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", base_revision):
        raise ExperimentError("Corrected Legacy base_revision must be a full commit SHA.")
    changed_paths = _git_output(worktree, "diff", "--name-only", f"{base_revision}..{revision}").splitlines()
    corrected_legacy_paths = {
        "scripts/reference_runtime.py",
        "scripts/test_reference_runtime.py",
        "scripts/test_arco_real_adapter.py",
    }
    if set(changed_paths) != corrected_legacy_paths:
        raise ExperimentError("Corrected Legacy must contain only the selector fix and its regression tests.")
    patch = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            f"{base_revision}..{revision}",
            "--",
            "scripts/reference_runtime.py",
            "scripts/test_reference_runtime.py",
            "scripts/test_arco_real_adapter.py",
        ],
        cwd=worktree,
        check=True,
        capture_output=True,
    ).stdout
    if hashlib.sha256(patch).hexdigest() != metadata.get("selector_patch_sha256"):
        raise ExperimentError("Corrected Legacy selector patch hash differs from its frozen metadata.")
    runtime_hash = sha256_file(runtime_path)
    if runtime_hash != metadata.get("runtime_sha256"):
        raise ExperimentError("Corrected Legacy Runtime hash differs from its frozen metadata.")
    runtime_files = [
        worktree / "scripts" / "reference_runtime.py",
        worktree / "scripts" / "arco_real_adapter.py",
        worktree / "runtime" / "generation.yaml",
    ]
    runtime_bundle_hash = sha256_tree(runtime_files, root=worktree)
    if runtime_bundle_hash != metadata.get("runtime_bundle_sha256"):
        raise ExperimentError("Corrected Legacy runtime bundle hash differs from its frozen metadata.")
    adapter_hash = sha256_file(worktree / "scripts" / "arco_real_adapter.py")
    if adapter_hash != metadata.get("adapter_sha256"):
        raise ExperimentError("Corrected Legacy adapter hash differs from its frozen metadata.")
    legacy_adapter_blob = _git_output(worktree, "hash-object", "scripts/arco_real_adapter.py")
    production_adapter_blob = _git_output(root, "hash-object", "scripts/arco_real_adapter.py")
    if legacy_adapter_blob != production_adapter_blob:
        raise ExperimentError("Corrected Legacy and production Adapter files differ.")
    workspace_start = metadata.get("main_workspace_at_batch_start")
    if not isinstance(workspace_start, Mapping):
        raise ExperimentError("Main workspace start revision and runtime hashes are not recorded.")
    if workspace_start.get("head_commit") != _git_output(root, "rev-parse", "HEAD"):
        raise ExperimentError("Main HEAD differs from the recorded Batch 4B.2 start revision.")
    starting_hashes = workspace_start.get("runtime_file_sha256")
    if not isinstance(starting_hashes, Mapping):
        raise ExperimentError("Main workspace start runtime hashes are invalid.")
    for relative in (
        "scripts/reference_runtime.py",
        "scripts/arco_real_adapter.py",
        "runtime/generation.yaml",
    ):
        expected_hash = starting_hashes.get(relative)
        current_path = root / relative
        if (
            not isinstance(expected_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
            or not current_path.is_file()
            or sha256_file(current_path) != expected_hash
        ):
            raise ExperimentError(f"Production Runtime or transport schema changed from its recorded start hash: {relative}.")
    return {**metadata, "worktree_path": str(worktree), "runtime_path": str(runtime_path)}


def _load_corrected_legacy_runtime(root: Path = ROOT) -> tuple[Any, dict[str, Any]]:
    metadata = _control_runtime_metadata(root)
    module_name = f"arco_corrected_legacy_runtime_{metadata['selector_patch_revision'][:12]}"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing, metadata
    spec = importlib.util.spec_from_file_location(module_name, metadata["runtime_path"])
    if spec is None or spec.loader is None:
        raise ExperimentError("Cannot load the Corrected Legacy Runtime module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module, metadata


def _external_contract(case: Mapping[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    external = case["external_reference"]
    return {
        "reference_id": external["reference_id"],
        "source_scope": "external_how",
        "path": str(_evaluation_path(external["path"], root=root)),
        "role": external.get("role", "style_reference"),
        "duties": list(external.get("duties") or ["style_reference"]),
        "style_priority": "primary",
        "style_axes": list(case["expected_relevant_style_axes"]),
        "authority": "user_request_external",
        "persistent": False,
        "calibrating": False,
        "inherit": [],
        "do_not_inherit": list(WHO_DO_NOT_INHERIT),
        "coverage": {},
    }


def _load_case_style_brief(
    case: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    external = case["external_reference"]
    relative = external.get("style_brief_path")
    if not isinstance(relative, str) or not relative.strip():
        raise ExperimentError(f"{case['case_id']} frozen Style Brief path is missing.")
    brief_path = _evaluation_path(relative, root=root)
    if not brief_path.is_file():
        raise ExperimentError(f"{case['case_id']} frozen Style Brief is missing: {relative}")
    expected_hash = external.get("style_brief_sha256")
    actual_hash = sha256_file(brief_path)
    if not isinstance(expected_hash, str) or actual_hash != expected_hash:
        raise ExperimentError(f"{case['case_id']} frozen Style Brief hash does not match cases.yaml.")
    brief = _load_yaml(brief_path)
    if not isinstance(brief, Mapping):
        raise ExperimentError(f"{case['case_id']} Style Brief must be a YAML mapping.")
    if brief.get("source_reference_id") != external.get("reference_id"):
        raise ExperimentError(f"{case['case_id']} Style Brief source ID differs from its image.")
    if brief.get("source_reference_hash") != external.get("sha256"):
        raise ExperimentError(f"{case['case_id']} Style Brief source hash differs from its image.")
    if brief.get("style_reference_sha256") != external.get("sha256"):
        raise ExperimentError(f"{case['case_id']} Style Brief Style Reference hash differs from its image.")
    if brief.get("created_for_case") != case.get("case_id"):
        raise ExperimentError(f"{case['case_id']} Style Brief case binding is invalid.")
    if brief.get("style_priority") != "primary":
        raise ExperimentError(f"{case['case_id']} Style Brief priority must be primary.")
    if brief.get("active_axes") != case.get("expected_relevant_style_axes"):
        raise ExperimentError(f"{case['case_id']} Style Brief axes differ from the frozen case.")
    for field in ("created_at", "runtime_revision"):
        if not isinstance(brief.get(field), str) or not brief[field].strip():
            raise ExperimentError(f"{case['case_id']} Style Brief is missing {field}.")
    return dict(brief)


def _reference_hash(reference: Mapping[str, Any]) -> str:
    declared = reference.get("sha256")
    return str(declared) if isinstance(declared, str) and declared else sha256_file(Path(reference["path"]))


def _validate_reference_assets(
    root: Path,
    case: Mapping[str, Any],
    managed_assets: Sequence[Mapping[str, Any]],
    generation_config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    external_data = case["external_reference"]
    external_path = _evaluation_path(external_data["path"], root=root)
    if not external_path.is_file():
        errors.append(f"{case['case_id']} external style image is missing: {external_data['path']}")
        return [], errors
    actual_hash = sha256_file(external_path)
    declared_hash = external_data.get("sha256")
    if declared_hash is not None and actual_hash != declared_hash:
        errors.append(f"{case['case_id']} external style image hash does not match cases.yaml.")
        return [], errors
    try:
        external = _external_contract(case, root=root)
        references = select_references(
            root=root,
            managed_assets=managed_assets,
            requested_roles=["identity_reference", "outfit_reference"],
            exposure_profile=case["exposure_profile"],
            variant_required=True,
            selected_variant_id=case["identity_variant"],
            external_references=[external],
            config=generation_config,
        )
    except (ReferenceRuntimeError, ExperimentError) as exc:
        errors.append(f"{case['case_id']} reference selection failed: {exc}")
        return [], errors

    reference_ids = [str(reference.get("reference_id")) for reference in references]
    if reference_ids != case.get("reference_order"):
        errors.append(
            f"{case['case_id']} selected reference order differs: {reference_ids}"
        )
    identity_ids = [ref["reference_id"] for ref in references if ref.get("role") == "identity_reference"]
    variant_ids = [ref["reference_id"] for ref in references if ref.get("role") == "outfit_reference"]
    if identity_ids != case.get("identity_reference_ids"):
        errors.append(f"{case['case_id']} selected Identity references differ: {identity_ids}")
    if variant_ids != case.get("variant_reference_ids"):
        errors.append(f"{case['case_id']} selected Variant references differ: {variant_ids}")
    identity_hashes = [_reference_hash(ref) for ref in references if ref.get("role") == "identity_reference"]
    variant_hashes = [_reference_hash(ref) for ref in references if ref.get("role") == "outfit_reference"]
    if identity_hashes != case.get("identity_reference_hashes"):
        errors.append(f"{case['case_id']} selected Identity reference hashes differ.")
    if variant_hashes != case.get("variant_reference_hashes"):
        errors.append(f"{case['case_id']} selected Variant reference hashes differ.")
    return references, errors


def _build_pair(
    root: Path,
    case: Mapping[str, Any],
    references: Sequence[Mapping[str, Any]],
    official_style_baseline: Mapping[str, Any],
    hygiene_policy: Mapping[str, Any],
) -> dict[str, Any]:
    legacy_runtime, legacy_metadata = _load_corrected_legacy_runtime(root)
    legacy_references = legacy_runtime.select_references(
        root=root,
        managed_assets=_load_yaml(root / "character" / "assets.yaml")["assets"],
        requested_roles=["identity_reference", "outfit_reference"],
        exposure_profile=case["exposure_profile"],
        variant_required=True,
        selected_variant_id=case["identity_variant"],
        external_references=[_external_contract(case, root=root)],
        config=_load_yaml(root / "runtime" / "generation.yaml"),
    )
    legacy_root = Path(legacy_metadata["worktree_path"])
    selection_snapshots = {
        "A": _selection_snapshot(case, legacy_references, root=root, selector_root=legacy_root),
        "B": _selection_snapshot(case, references, root=root),
        "C": _selection_snapshot(case, references, root=root),
    }
    parity_errors = _selection_parity_errors(selection_snapshots)
    if parity_errors:
        raise ExperimentError("A/B/C selector parity failed: " + "; ".join(parity_errors))

    resolved_style_references = resolve_style_references(references)
    style_context = resolve_style_context(
        resolved_style_references=resolved_style_references,
        style_briefs=[_load_case_style_brief(case, root=root)],
        official_style_baseline=official_style_baseline,
    )
    scene = compose_scene_prompt(case)
    prompt_a = legacy_runtime.compile_prompt(
        base_prompt=scene,
        references=legacy_references,
        exposure_profile=case["exposure_profile"],
    )
    prompt_b = compile_prompt(
        base_prompt=scene,
        references=references,
        style_context=style_context,
        exposure_profile=case["exposure_profile"],
    )
    prompt_c = compile_prompt(
        base_prompt=scene,
        references=references,
        style_context=style_context,
        exposure_profile=case["exposure_profile"],
        rendering_hygiene_policy=hygiene_policy,
    )
    hygiene_block = compile_rendering_hygiene(style_context, policy=hygiene_policy)
    if prompt_c != f"{prompt_b}\n\n{hygiene_block}":
        raise ExperimentError(f"{case['case_id']} B/C compiled prompts differ beyond Hygiene.")
    plan_a = legacy_runtime.build_invocation_plan(
        mode="reference_conditioned", prompt=prompt_a, selected_references=legacy_references
    )
    plan_b = build_invocation_plan(
        mode="reference_conditioned", prompt=prompt_b, selected_references=references
    )
    plan_c = build_invocation_plan(
        mode="reference_conditioned", prompt=prompt_c, selected_references=references
    )
    parity_keys = (
        "provider",
        "capability",
        "mode",
        "selected_reference_ids",
        "referenced_image_paths",
    )
    if any(plan_b.get(key) != plan_c.get(key) for key in parity_keys):
        raise ExperimentError(f"{case['case_id']} B/C invocation inputs differ beyond Hygiene.")
    if plan_a.get("selected_reference_ids") != plan_b.get("selected_reference_ids"):
        raise ExperimentError(f"{case['case_id']} A/B selected reference IDs differ.")
    if plan_a.get("referenced_image_paths") != plan_b.get("referenced_image_paths"):
        raise ExperimentError(f"{case['case_id']} A/B referenced image paths differ.")
    for group, plan in (("A", plan_a), ("B", plan_b), ("C", plan_c)):
        if scene not in plan.get("prompt", ""):
            raise ExperimentError(f"{case['case_id']} Group {group} prompt changed the frozen base scene.")
    context_b = copy.deepcopy(style_context)
    context_c = copy.deepcopy(style_context)
    if context_b != context_c:
        raise ExperimentError(f"{case['case_id']} B/C ResolvedStyleContext differs.")
    style_context_hash = sha256_json(style_context)
    plan_a["style_context_hash"] = None
    plan_b["style_context_hash"] = style_context_hash
    plan_c["style_context_hash"] = style_context_hash
    return {
        "case_id": case["case_id"],
        "references": [dict(reference) for reference in references],
        "references_by_group": {
            "A": [dict(reference) for reference in legacy_references],
            "B": [dict(reference) for reference in references],
            "C": [dict(reference) for reference in references],
        },
        "selector_snapshots": selection_snapshots,
        "selector_parity": True,
        "corrected_legacy": legacy_metadata,
        "scene": scene,
        "style_context": style_context,
        "hygiene_block": hygiene_block,
        "plans": {"A": plan_a, "B": plan_b, "C": plan_c},
    }


def _write_frozen_json(path: Path, value: Mapping[str, Any]) -> None:
    contents = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != contents:
            raise ExperimentError(f"Frozen experiment artifact changed; refusing to overwrite {path}.")
        return
    _write_json_atomic(path, value)


def _write_yaml_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=1000)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(contents, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _selection_path(case_id: str, *, root: Path = ROOT) -> Path:
    return root / "evaluation" / "style-regression" / "reference-selection" / f"{case_id}.json"


def _context_dir(case_id: str, *, root: Path = ROOT) -> Path:
    return root / "evaluation" / "style-regression" / "style-context" / case_id


def _style_regression_dir(root: Path = ROOT) -> Path:
    return root / "evaluation" / "style-regression"


def _input_freeze_path(root: Path = ROOT) -> Path:
    return _style_regression_dir(root) / "inputs-freeze.json"


def _preflight_report_paths(root: Path = ROOT) -> tuple[Path, Path]:
    directory = _style_regression_dir(root)
    capture = directory / "environment" / R_FINAL_PREFLIGHT_ENVIRONMENT_PATH
    if capture.is_file():
        return directory / R_PREFLIGHT_LIVE_JSON_PATH, directory / R_PREFLIGHT_LIVE_MARKDOWN_PATH
    return directory / R_PREFLIGHT_JSON_PATH, directory / R_PREFLIGHT_MARKDOWN_PATH


def _pilot_dir(root: Path = ROOT) -> Path:
    return _style_regression_dir(root) / "pilot" / "runs" / "batch-4b3t-r2"


def _pilot_manifest_path(root: Path = ROOT) -> Path:
    return _pilot_dir(root) / "manifest.jsonl"


def _pilot_output_path(case_id: str, group: str, *, root: Path = ROOT) -> Path:
    return _style_regression_dir(root) / "pilot" / "outputs" / "batch-4b3t-r2" / case_id / f"{group}-r1.png"


def _pilot_artifacts_present(root: Path = ROOT) -> bool:
    pilot_dir = _pilot_dir(root)
    return _pilot_manifest_path(root).is_file() or (
        pilot_dir.is_dir() and any(path.is_file() for path in pilot_dir.rglob("*"))
    )


def _formal_manifest_path(root: Path = ROOT) -> Path:
    return _style_regression_dir(root) / "manifest.jsonl"


def _formal_task_dir(root: Path = ROOT) -> Path:
    return root / FORMAL_TASK_DIR


def _formal_task_path(case_id: str, group: str, replicate: int, attempt: int, *, root: Path = ROOT) -> Path:
    return _formal_task_dir(root) / f"{case_id}-{group}-r{replicate}-attempt-{attempt}.json"


def _formal_sample_plan() -> list[dict[str, Any]]:
    return [
        {"case_id": case_id, "group": group, "replicate": replicate, "sample_key": _sample_key(case_id, group, replicate)}
        for case_id in CASE_IDS
        for replicate in range(1, EXPECTED_REPLICATES + 1)
        for group in GENERATED_GROUPS
    ]


def _formal_task_output_path(
    case_id: str, group: str, replicate: int, attempt: int, *, root: Path = ROOT
) -> Path:
    if attempt < 1:
        raise ExperimentError("Formal task attempt number must be positive.")
    suffix = f"{group}-r{replicate}" if attempt == 1 else f"{group}-r{replicate}-attempt-{attempt}"
    return _style_regression_dir(root) / "outputs" / case_id / f"{suffix}.png"


def _validate_pre_capture_formal_history(root: Path = ROOT) -> list[str]:
    """Permit only the preserved 4B.3-T invalidation and queued-task supersession."""
    evaluation_dir = _style_regression_dir(root)
    manifest_path = _formal_manifest_path(root)
    rows = _load_jsonl(manifest_path) if manifest_path.is_file() else []
    task_dir = _formal_task_dir(root)
    output_dir = evaluation_dir / "outputs"
    task_files = sorted(path for path in task_dir.glob("*.json")) if task_dir.exists() else []
    output_files = sorted(path for path in output_dir.rglob("*") if path.is_file()) if output_dir.exists() else []
    if not rows and not task_files and not output_files:
        return []
    errors: list[str] = []
    expected_keys = ["case-01:A:r1", "case-01:B:r1"]
    if [row.get("sample_key") for row in rows] != expected_keys:
        errors.append("Pre-capture formal history must contain only the A-r1 invalidation and B-r1 superseded queue record.")
        return errors
    task_paths: set[Path] = set()
    preserved_outputs: set[Path] = set()
    for key, expected_status, failure_kind, failure_reason in (
        ("case-01:A:r1", "invalidated", "task_transport", "prompt_encoding_corruption"),
        ("case-01:B:r1", "superseded", None, None),
    ):
        row = next(item for item in rows if item.get("sample_key") == key)
        group = key.split(":")[1]
        task_path = _formal_task_path("case-01", group, 1, 1, root=root)
        attempt = (row.get("attempts") or [{}])[0]
        if len(row.get("attempts") or []) != 1:
            errors.append(f"Pre-capture {key} audit history must preserve exactly one legacy attempt.")
            continue
        if (
            row.get("status") != expected_status
            or attempt.get("status") != expected_status
            or attempt.get("task_path") != _relative_path(task_path, root=root)
            or not task_path.is_file()
        ):
            errors.append(f"Pre-capture {key} migration state or task path is invalid.")
            continue
        try:
            task = load_codex_task(task_path, root=root, verify_frozen_inputs=False)
        except ExperimentError as exc:
            errors.append(f"Pre-capture {key} legacy task is invalid: {exc}")
            continue
        if (
            task.get("schema_version") != LEGACY_CODEX_TASK_SCHEMA_VERSION
            or task.get("task_id") != attempt.get("task_id")
            or task.get("task_sha256") != attempt.get("task_sha256")
            or task.get("expected_output_path") != row.get("output_path")
        ):
            errors.append(f"Pre-capture {key} legacy task differs from its preserved manifest record.")
        if expected_status == "invalidated":
            if (
                row.get("include_in_formal_analysis") is not False
                or row.get("excluded_from_verdict") is not True
                or row.get("failure_kind") != failure_kind
                or row.get("failure_reason") != failure_reason
                or attempt.get("failure_kind") != failure_kind
                or attempt.get("failure_reason") != failure_reason
                or not row.get("output_sha256")
                or attempt.get("output_sha256") != row.get("output_sha256")
            ):
                errors.append("A-r1 must be invalidated/excluded with task_transport prompt_encoding_corruption and its original output hash retained.")
            output_path = _repo_path(str(row.get("output_path", "")), root=root)
            if not output_path.is_file() or sha256_file(output_path) != row.get("output_sha256"):
                errors.append("A-r1 preserved PNG is missing or its original output SHA-256 changed.")
            else:
                with output_path.open("rb") as handle:
                    if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                        errors.append("A-r1 preserved output is not a PNG.")
                preserved_outputs.add(output_path.resolve())
        else:
            if (
                row.get("include_in_formal_analysis") is not False
                or row.get("failure_kind") is not None
                or attempt.get("failure_kind") is not None
                or not str(row.get("superseded_reason", "")).strip()
            ):
                errors.append("B-r1 must be marked superseded without recording a generated failure.")
            if _repo_path(str(row.get("output_path", "")), root=root).exists():
                errors.append("Superseded B-r1 task has an unexpected output image.")
        task_paths.add(task_path.resolve())
    found_task_paths = {path.resolve() for path in task_files}
    if found_task_paths != task_paths:
        errors.append("Pre-capture immutable task exchange contains unrecorded or missing legacy task files.")
    found_outputs = {path.resolve() for path in output_files}
    if found_outputs != preserved_outputs:
        errors.append("Pre-capture formal outputs contain unrecorded files or omit the preserved invalidated PNG.")
    return sorted(set(errors))


def migrate_legacy_formal_transport_state(*, root: Path = ROOT) -> dict[str, Any]:
    """Quarantine the known A-r1 transport-corrupted result and supersede B-r1 queue."""
    errors = _validate_pre_capture_formal_history(root)
    if not errors:
        rows = _load_jsonl(_formal_manifest_path(root)) if _formal_manifest_path(root).is_file() else []
        if not rows:
            raise ExperimentError("Legacy formal transport migration found no existing audit rows to migrate.")
        return {
            "migrated": False,
            "formal_sample_counts": _compliant_formal_sample_counts(rows, root=root),
            "invalid_technical_attempts": 1,
            "next_pending_sample": "case-01:A:r1 attempt 2",
        }

    manifest_path = _formal_manifest_path(root)
    rows = _load_jsonl(manifest_path)
    expected = ["case-01:A:r1", "case-01:B:r1"]
    if [row.get("sample_key") for row in rows] != expected:
        raise ExperimentError("Refusing to migrate an unexpected formal manifest state: " + "; ".join(errors))
    indexed = _manifest_index(rows)
    a_row = indexed["case-01:A:r1"]
    b_row = indexed["case-01:B:r1"]
    a_attempt = dict(a_row["attempts"][0])
    b_attempt = dict(b_row["attempts"][0])
    if a_row.get("status") != "succeeded" or b_row.get("status") != "queued":
        raise ExperimentError("Legacy migration requires the recorded A-r1 success and B-r1 queued task exactly.")
    if not a_row.get("output_sha256") or a_attempt.get("output_sha256") != a_row.get("output_sha256"):
        raise ExperimentError("Legacy A-r1 output hash is missing or inconsistent; refusing to invalidate it.")
    a_output_path = _repo_path(str(a_row.get("output_path", "")), root=root)
    if not a_output_path.is_file() or sha256_file(a_output_path) != a_row["output_sha256"]:
        raise ExperimentError("Legacy A-r1 image/hash changed; refusing to migrate audit state.")
    with a_output_path.open("rb") as handle:
        if handle.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ExperimentError("Legacy A-r1 preserved output is not a PNG; refusing migration.")

    invalidated_at = datetime.now(timezone.utc).isoformat()
    a_attempt.update(
        {
            "status": "invalidated",
            "invalidated_at": invalidated_at,
            "invalidated_from_status": "succeeded",
            "excluded_from_verdict": True,
            "include_in_formal_analysis": False,
            "failure_kind": "task_transport",
            "failure_reason": "prompt_encoding_corruption",
            "retryable": True,
        }
    )
    a_row.update(
        {
            "status": "invalidated",
            "invalidated_at": invalidated_at,
            "invalidated_from_status": "succeeded",
            "excluded_from_verdict": True,
            "include_in_formal_analysis": False,
            "failure_kind": "task_transport",
            "failure_reason": "prompt_encoding_corruption",
            "attempts": [a_attempt],
        }
    )
    b_superseded_at = datetime.now(timezone.utc).isoformat()
    superseded_reason = "Legacy schema-1 task predates UTF-8-safe prompt envelopes; no image generation occurred."
    b_attempt.update(
        {
            "status": "superseded",
            "superseded_at": b_superseded_at,
            "superseded_reason": superseded_reason,
            "generated_failure": False,
        }
    )
    b_row.update(
        {
            "status": "superseded",
            "superseded_at": b_superseded_at,
            "superseded_reason": superseded_reason,
            "include_in_formal_analysis": False,
            "attempts": [b_attempt],
        }
    )
    for row in (a_row, b_row):
        indexed[str(row["sample_key"])] = row
    _write_manifest_atomic(manifest_path, [indexed[key] for key in expected])
    final_errors = _validate_pre_capture_formal_history(root)
    if final_errors:
        raise ExperimentError("Migrated formal audit state failed validation: " + "; ".join(final_errors))
    return {
        "migrated": True,
        "formal_sample_counts": {group: 0 for group in GENERATED_GROUPS},
        "invalid_technical_attempts": 1,
        "superseded_unexecuted_tasks": 1,
        "preserved_output_path": a_row["output_path"],
        "preserved_output_sha256": a_row["output_sha256"],
        "next_pending_sample": "case-01:A:r1 attempt 2",
    }


def _compliant_formal_sample_counts(
    formal_rows: Sequence[Mapping[str, Any]],
    *,
    root: Path = ROOT,
    legacy_runner_hash_allowlist: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, int]:
    counts = {group: 0 for group in GENERATED_GROUPS}
    seen: set[str] = set()
    for row in formal_rows:
        if row.get("pilot") or row.get("status") != "succeeded":
            continue
        group = row.get("group")
        sample_key = str(row.get("sample_key", ""))
        if group not in GENERATED_GROUPS or sample_key in seen:
            raise ExperimentError("Formal manifest contains a duplicate or invalid accepted sample.")
        attempts = row.get("attempts")
        if not isinstance(attempts, list) or not attempts or attempts[-1].get("status") != "succeeded":
            raise ExperimentError(f"Accepted formal sample {sample_key} has no succeeded latest attempt.")
        attempt = attempts[-1]
        task_path = _repo_path(str(attempt.get("task_path", "")), root=root)
        source_path = Path(str(row.get("codex_generated_source_path", ""))).expanduser()
        output_path = _repo_path(str(row.get("output_path", "")), root=root)
        if (
            attempt.get("compliant") is not True
            or attempt.get("receipt_path") != row.get("receipt_path")
            or attempt.get("receipt_sha256") != row.get("receipt_sha256")
            or not output_path.is_file()
            or row.get("output_sha256") != sha256_file(output_path)
        ):
            raise ExperimentError(f"Formal sample {sample_key} lacks a receipt-validated accepted output.")
        verify_codex_execution_receipt(
            task_path,
            source_path,
            root=root,
            expected_receipt_path=str(row.get("receipt_path")),
            expected_receipt_sha256=str(row.get("receipt_sha256")),
            legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
        )
        if attempt.get("output_sha256") != row.get("output_sha256"):
            raise ExperimentError(f"Formal sample {sample_key} receipt output hash differs from its manifest.")
        seen.add(sample_key)
        counts[str(group)] += 1
    return counts


def _pilot_artifact_errors(
    root: Path = ROOT,
    *,
    legacy_runner_hash_allowlist: Mapping[str, Mapping[str, str]] | None = None,
) -> list[str]:
    """Accept only a complete, hash-valid Pilot; partial attempts remain blocked."""
    if not _pilot_artifacts_present(root):
        return []
    errors: list[str] = []
    manifest_path = _pilot_manifest_path(root)
    if not manifest_path.is_file():
        return ["Pilot artifacts exist without a manifest; retry or replacement is forbidden."]
    try:
        rows = _load_jsonl(manifest_path)
    except ExperimentError as exc:
        return [f"Pilot manifest is invalid: {exc}"]
    by_group = {row.get("group"): row for row in rows if row.get("case_id") == "case-01"}
    if len(rows) != len(GENERATED_GROUPS) or set(by_group) != set(GENERATED_GROUPS):
        errors.append("Pilot manifest must contain exactly one Case 01 row for each A/B/C group.")

    pilot_dir = _pilot_dir(root)
    codex_managed_pilot = any(row.get("execution_mode") == "codex-managed" for row in rows)
    context_path = pilot_dir / "contexts" / "case-01.json"
    required_artifacts = [
        pilot_dir / "prompts" / "case-01-base-scene.txt",
        context_path,
        *[
            pilot_dir / "prompts" / f"case-01-{group}.txt"
            for group in GENERATED_GROUPS
        ],
        *(
            [pilot_dir / "tasks" / f"case-01-{group}-r1.json" for group in GENERATED_GROUPS]
            if codex_managed_pilot
            else []
        ),
        *(
            [pilot_dir / "receipts" / f"case-01-{group}-r1.json" for group in GENERATED_GROUPS]
            if codex_managed_pilot
            else []
        ),
        *[_pilot_output_path("case-01", group, root=root) for group in GENERATED_GROUPS],
    ]
    for path in required_artifacts:
        if not path.is_file():
            errors.append(f"Pilot artifact is missing: {_relative_path(path, root=root)}")
    context_file_hash = sha256_file(context_path) if context_path.is_file() else None
    reference_snapshot = _selection_path("case-01", root=root)
    reference_snapshot_hash = sha256_file(reference_snapshot) if reference_snapshot.is_file() else None

    for group in GENERATED_GROUPS:
        row = by_group.get(group)
        if row is None:
            continue
        if row.get("case_id") != "case-01" or row.get("replicate") != 1:
            errors.append(f"Pilot {group} row has an unexpected case or replicate.")
        if (
            row.get("status") != "succeeded"
            or row.get("pilot") is not True
            or row.get("formal") is not False
            or row.get("include_in_formal_analysis") is not False
        ):
            errors.append(f"Pilot {group} row is not a successful Pilot-only sample.")
        for field in (
            "selector_parity",
            "scene_parity",
            "bc_context_parity",
            "bc_prompt_hygiene_only",
        ):
            if row.get(field) is not True:
                errors.append(f"Pilot {group} row is missing passing {field}.")
        if row.get("provider_payload_keys") != ["prompt", "referenced_image_paths"]:
            errors.append(f"Pilot {group} provider payload shape is invalid.")

        if row.get("execution_mode") == "codex-managed":
            task_path = pilot_dir / "tasks" / f"case-01-{group}-r1.json"
            try:
                task = load_codex_task(
                    task_path,
                    root=root,
                    legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
                )
                if task.get("schema_version") != CODEX_TASK_SCHEMA_VERSION:
                    errors.append(f"Pilot {group} Codex task lacks the UTF-8-safe schema.")
                if task.get("task_id") != f"pilot:case-01:{group}:r1":
                    errors.append(f"Pilot {group} Codex task ID is invalid.")
                if row.get("task_path") != _relative_path(task_path, root=root):
                    errors.append(f"Pilot {group} task path differs from its manifest.")
                if row.get("task_sha256") != task.get("task_sha256"):
                    errors.append(f"Pilot {group} task hash differs from its manifest.")
                if task.get("case_id") != "case-01" or task.get("group") != group or task.get("replicate") != 1:
                    errors.append(f"Pilot {group} Codex task identifiers differ from the Pilot manifest.")
                if task.get("expected_output_path") != row.get("output_path"):
                    errors.append(f"Pilot {group} task output path differs from its manifest.")
                prompt_path_for_task = pilot_dir / "prompts" / f"case-01-{group}.txt"
                if task.get("prompt") != prompt_path_for_task.read_text(encoding="utf-8").rstrip("\n"):
                    errors.append(f"Pilot {group} task prompt differs from the frozen compiled prompt.")
                if task.get("reference_ids") != row.get("selected_reference_ids"):
                    errors.append(f"Pilot {group} task reference order differs from its manifest.")
                if task.get("referenced_image_paths") != row.get("reference_paths_ordered"):
                    errors.append(f"Pilot {group} task reference paths differ from their frozen order.")
                if task.get("task_sha256") != row.get("task_sha256"):
                    errors.append(f"Pilot {group} task hash is invalid.")
                receipt_source = Path(str(row.get("codex_generated_source_path", ""))).expanduser()
                if not receipt_source.is_file():
                    errors.append(f"Pilot {group} generated source for its execution receipt is missing.")
                else:
                    verify_codex_execution_receipt(
                        task_path,
                        receipt_source,
                        root=root,
                        expected_receipt_path=row.get("receipt_path"),
                        expected_receipt_sha256=row.get("receipt_sha256"),
                        legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
                    )
            except (ExperimentError, OSError) as exc:
                errors.append(f"Pilot {group} Codex task is invalid: {exc}")
            if row.get("engine") != "Codex-managed":
                errors.append(f"Pilot {group} execution engine attribution is invalid.")

        output_path = _pilot_output_path("case-01", group, root=root)
        if row.get("output_path") != _relative_path(output_path, root=root):
            errors.append(f"Pilot {group} output path differs from its isolated destination.")
        elif output_path.is_file() and row.get("output_sha256") != sha256_file(output_path):
            errors.append(f"Pilot {group} output hash does not match its manifest.")

        prompt_path = pilot_dir / "prompts" / f"case-01-{group}.txt"
        if row.get("compiled_prompt_path") != _relative_path(prompt_path, root=root):
            errors.append(f"Pilot {group} prompt path is invalid.")
        elif prompt_path.is_file() and row.get("compiled_prompt_sha256") != sha256_file(prompt_path):
            errors.append(f"Pilot {group} prompt hash does not match its manifest.")

        if row.get("reference_snapshot_path") != _relative_path(reference_snapshot, root=root):
            errors.append(f"Pilot {group} reference snapshot path is invalid.")
        elif reference_snapshot_hash is None or row.get("reference_snapshot_sha256") != reference_snapshot_hash:
            errors.append(f"Pilot {group} reference snapshot hash does not match its manifest.")

        if group == "A":
            if row.get("resolved_style_context_path") is not None or row.get("resolved_style_context_sha256") is not None:
                errors.append("Pilot A must not use a ResolvedStyleContext.")
        elif (
            row.get("resolved_style_context_path") != _relative_path(context_path, root=root)
            or context_file_hash is None
            or row.get("resolved_style_context_sha256") != context_file_hash
        ):
            errors.append(f"Pilot {group} context path or hash does not match the shared Pilot context.")

    if set(by_group) == set(GENERATED_GROUPS):
        if by_group["B"].get("resolved_style_context_sha256") != by_group["C"].get("resolved_style_context_sha256"):
            errors.append("Pilot B/C ResolvedStyleContext hashes differ.")
        if by_group["B"].get("style_context_hash") != by_group["C"].get("style_context_hash"):
            errors.append("Pilot B/C Style Context hashes differ.")
    return sorted(set(errors))


def _selection_snapshot(
    case: Mapping[str, Any],
    references: Sequence[Mapping[str, Any]],
    *,
    root: Path = ROOT,
    selector_root: Path | None = None,
) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    for order, reference in enumerate(references, start=1):
        reference_path = Path(str(reference["path"])).resolve()
        try:
            local_path = _relative_path(reference_path, root=root)
        except ValueError as exc:
            raise ExperimentError(
                f"Selected reference path is outside the repository: {reference_path}"
            ) from exc
        selected.append(
            {
                "selection_order": order,
                "reference_id": reference.get("reference_id"),
                "asset_id": reference.get("asset_id"),
                "roles": [reference.get("role")],
                "duties": list(reference.get("duties") or reference.get("inherit") or []),
                "role": reference.get("role"),
                "style_priority": reference.get("style_priority"),
                "style_axes": list(reference.get("style_axes") or []),
                "path": local_path,
                "sha256": _reference_hash(reference),
                "source_scope": reference.get("source_scope"),
                "canonical_role": reference.get("canonical_role"),
                "source_family": reference.get("source_family"),
                "asset_type": reference.get("asset_type"),
            }
        )
    selector_root = selector_root or root
    selector_path = selector_root / "scripts" / "reference_runtime.py"
    return {
        "schema_version": 1,
        "case_id": case["case_id"],
        "selector_revision": {
            "runtime_sha256": sha256_file(selector_path),
            "commit_sha": _git_output(selector_root, "rev-parse", "HEAD"),
            "worktree_dirty": bool(_git_output(selector_root, "status", "--porcelain=v1")),
        },
        "groups_share_selection": list(GROUPS),
        "exposure_profile": case["exposure_profile"],
        "variant": case["identity_variant"],
        "state": case.get("state"),
        "scene_snapshot": {
            field: case.get(field)
            for field in (
                "base_scene_prompt",
                "pose_requirement",
                "composition_requirement",
                "camera_requirement",
                "exposure_requirement",
            )
        },
        "selected_reference_ids": [item["reference_id"] for item in selected],
        "selected_reference_hashes": [item["sha256"] for item in selected],
        "reference_order": [item["reference_id"] for item in selected],
        "style_priority": next(
            (item["style_priority"] for item in selected if item["role"] == "style_reference"),
            "primary",
        ),
        "style_axes": list(case.get("expected_relevant_style_axes") or []),
        "references": selected,
    }


def _selection_parity_errors(snapshots: Mapping[str, Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    if set(snapshots) != set(GROUPS):
        return ["A/B/C selector snapshots are incomplete."]
    baseline = snapshots["A"]
    parity_fields = (
        "case_id",
        "exposure_profile",
        "variant",
        "state",
        "scene_snapshot",
        "selected_reference_ids",
        "selected_reference_hashes",
        "reference_order",
        "style_priority",
        "style_axes",
    )
    for group in ("B", "C"):
        for field in parity_fields:
            if baseline.get(field) != snapshots[group].get(field):
                errors.append(f"A/{group} selector parity differs for {field}.")
        baseline_references = baseline.get("references") or []
        group_references = snapshots[group].get("references") or []
        if len(baseline_references) != len(group_references):
            errors.append(f"A/{group} selector parity differs for reference count.")
            continue
        for index, (a_reference, other_reference) in enumerate(
            zip(baseline_references, group_references, strict=True), start=1
        ):
            keys = (
                "selection_order",
                "reference_id",
                "asset_id",
                "roles",
                "role",
                "duties",
                "style_priority",
                "style_axes",
                "path",
                "sha256",
                "source_scope",
                "canonical_role",
                "source_family",
                "asset_type",
            )
            if any(a_reference.get(key) != other_reference.get(key) for key in keys):
                errors.append(f"A/{group} selector parity differs for reference {index}.")
    return errors


def _load_pre_selector_evidence(*, root: Path = ROOT) -> dict[str, Any]:
    evidence_path = (
        root
        / "evaluation"
        / "style-regression"
        / "reference-selection"
        / "pre-selector-fix-evidence.json"
    )
    evidence = _load_json(evidence_path)
    selected = evidence.get("selected_references")
    if not isinstance(selected, list) or not selected:
        raise ExperimentError("Pre-selector-fix selection evidence is invalid.")
    return evidence


def _selector_diff(
    case: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    evidence = _load_pre_selector_evidence(root=root)
    external_id = case["external_reference"]["reference_id"]
    after_references = [dict(item) for item in after["references"]]
    external_after = next(
        (item for item in after_references if item["reference_id"] == external_id), None
    )
    if external_after is None:
        raise ExperimentError(f"{case['case_id']} selection omitted its external Style Reference.")
    before_references = [dict(item) for item in evidence["selected_references"]]
    # The historical selector record predates external Style duties. The same
    # case-specific Primary image is appended to both sides of the comparison.
    before_references.append(dict(external_after))
    old_ids = [item["reference_id"] for item in before_references]
    new_ids = list(after["selected_reference_ids"])
    changed = old_ids != new_ids
    return {
        "case_id": case["case_id"],
        "before_source": evidence["source_record"],
        "before_selector_revision": evidence.get("selector_revision", "unknown"),
        "after_selector_revision": after["selector_revision"],
        "before_selected_reference_ids": old_ids,
        "after_selected_reference_ids": new_ids,
        "before_selected_reference_hashes": [item["sha256"] for item in before_references],
        "after_selected_reference_hashes": list(after["selected_reference_hashes"]),
        "before_reference_order": old_ids,
        "after_reference_order": list(after["reference_order"]),
        "changed": changed,
        "selector_confound": changed,
        "status": "changed" if changed else "unchanged",
        "interpretation": (
            "A-to-B differences include the selector correctness change."
            if changed
            else "Selector bug was latent for this case and did not change selected references."
        ),
    }


def _populate_case_hashes(
    cases_document: dict[str, Any], *, root: Path = ROOT
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    for case in cases_document.get("cases", []):
        external = case.get("external_reference") or {}
        case_id = case.get("case_id", "unknown")
        try:
            image_path = _evaluation_path(external.get("path", ""), root=root)
            private_root = (root / "evaluation" / "style-regression" / "private-assets").resolve()
            image_path.relative_to(private_root)
        except (ExperimentError, ValueError) as exc:
            errors.append(f"{case_id} Style Reference path is invalid: {exc}")
            continue
        if not image_path.is_file():
            errors.append(f"{case_id} external style image is missing: {external.get('path')}")
            continue
        image_hash = sha256_file(image_path)
        declared_image_hash = external.get("sha256")
        if declared_image_hash not in (None, image_hash):
            errors.append(f"{case_id} external style image hash changed after selection.")
            continue
        brief_relative = external.get("style_brief_path")
        if not isinstance(brief_relative, str) or not brief_relative.strip():
            errors.append(f"{case_id} Style Brief path is missing.")
            continue
        try:
            brief_path = _evaluation_path(brief_relative, root=root)
            brief_path.relative_to((root / "evaluation" / "style-regression" / "style-context" / case_id).resolve())
        except (ExperimentError, ValueError) as exc:
            errors.append(f"{case_id} Style Brief must be stored under its style-context directory: {exc}")
            continue
        if not brief_path.is_file():
            errors.append(f"{case_id} frozen Style Brief is missing: {brief_relative}")
            continue
        brief = _load_yaml(brief_path)
        if not isinstance(brief, Mapping):
            errors.append(f"{case_id} Style Brief must be a YAML mapping.")
            continue
        if brief.get("source_reference_id") != external.get("reference_id"):
            errors.append(f"{case_id} Style Brief source ID differs from its image.")
            continue
        if brief.get("source_reference_hash") != image_hash:
            errors.append(f"{case_id} Style Brief source hash differs from its image.")
            continue
        if brief.get("style_reference_sha256") != image_hash:
            errors.append(f"{case_id} Style Brief Style Reference hash differs from its image.")
            continue
        if brief.get("created_for_case") != case_id:
            errors.append(f"{case_id} Style Brief case binding is invalid.")
            continue
        if brief.get("style_priority") != "primary":
            errors.append(f"{case_id} Style Brief priority must be primary.")
            continue
        if brief.get("active_axes") != case.get("expected_relevant_style_axes"):
            errors.append(f"{case_id} Style Brief axes differ from the frozen case.")
            continue
        for field in ("created_at", "runtime_revision"):
            if not isinstance(brief.get(field), str) or not brief[field].strip():
                errors.append(f"{case_id} Style Brief is missing {field}.")
        external["sha256"] = image_hash
        external["style_brief_sha256"] = sha256_file(brief_path)
        case["external_reference_hashes"] = [image_hash]
    return cases_document, errors


def _build_pipeline_pairs(
    root: Path, cases_document: Mapping[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    pairs: dict[str, dict[str, Any]] = {}
    try:
        assets_document = _load_yaml(root / "character" / "assets.yaml")
        generation_config = _load_yaml(root / "runtime" / "generation.yaml")
        style_baseline = _load_yaml(root / "character" / "style-baseline.yaml")
        style_policy = _load_yaml(root / "runtime" / "style-policy.yaml")
    except ExperimentError as exc:
        return {}, [str(exc)]
    for case in cases_document.get("cases", []):
        try:
            references, reference_errors = _validate_reference_assets(
                root, case, assets_document["assets"], generation_config
            )
            errors.extend(reference_errors)
            if reference_errors:
                continue
            pairs[case["case_id"]] = _build_pair(
                root, case, references, style_baseline, style_policy
            )
        except (KeyError, TypeError, ReferenceRuntimeError, ExperimentError) as exc:
            errors.append(f"{case.get('case_id', 'unknown')} pipeline resolution failed: {exc}")
    return pairs, errors


def freeze_experiment_inputs(root: Path = ROOT) -> dict[str, Any]:
    """Freeze A/B/C selections, one Style Context per case, and all Pilot prompts."""
    input_freeze_path = _input_freeze_path(root)
    if input_freeze_path.exists():
        raise ExperimentError("Experiment inputs are already frozen; create a new revision to replace them.")
    cases_path = root / "evaluation" / "style-regression" / "cases.yaml"
    cases_document = _load_yaml(cases_path)
    if not isinstance(cases_document, dict):
        raise ExperimentError("cases.yaml must contain a mapping.")
    cases_document, hash_errors = _populate_case_hashes(cases_document, root=root)
    errors = validate_case_schema(cases_document) + hash_errors
    try:
        corrected_legacy = _control_runtime_metadata(root)
    except ExperimentError as exc:
        corrected_legacy = {}
        errors.append(str(exc))
    if errors:
        raise ExperimentError("Input freeze blocked:\n- " + "\n- ".join(sorted(set(errors))))
    # These are the only automated edits to the case file: freezing actual
    # hashes for user-selected files and briefs. Case choices and axes stay fixed.
    _write_yaml_atomic(cases_path, cases_document)
    pairs, pair_errors = _build_pipeline_pairs(root, cases_document)
    if pair_errors:
        raise ExperimentError("Input freeze blocked:\n- " + "\n- ".join(sorted(set(pair_errors))))
    if set(pairs) != set(CASE_IDS):
        raise ExperimentError("Input freeze requires all four resolved cases.")

    selectors: dict[str, Any] = {}
    diff_cases: list[dict[str, Any]] = []
    frozen_files: dict[str, str] = {}
    pre_selector_path = root / "evaluation" / "style-regression" / "reference-selection" / "pre-selector-fix-evidence.json"
    frozen_files[_relative_path(pre_selector_path, root=root)] = sha256_file(pre_selector_path)
    reference_manifest: dict[str, Any] = {"schema_version": 1, "references": []}
    for case in cases_document["cases"]:
        case_id = case["case_id"]
        pair = pairs[case_id]
        snapshot = {
            "schema_version": 1,
            "case_id": case_id,
            **pair["selector_snapshots"],
            "parity": pair["selector_parity"],
            "parity_fields": [
                "selected_reference_ids",
                "selected_reference_hashes",
                "reference_order",
                "reference roles and paths",
                "variant",
                "state",
                "exposure_profile",
                "scene_snapshot",
            ],
        }
        selection_path = _selection_path(case_id, root=root)
        _write_frozen_json(selection_path, snapshot)
        selectors[case_id] = {
            "path": _relative_path(selection_path, root=root),
            "sha256": sha256_file(selection_path),
        }
        frozen_files[selectors[case_id]["path"]] = selectors[case_id]["sha256"]
        diff_cases.append(_selector_diff(case, snapshot["B"], root=root))

        context_dir = _context_dir(case_id, root=root)
        context_path = context_dir / "resolved-style-context.json"
        context_path.parent.mkdir(parents=True, exist_ok=True)
        _write_frozen_json(context_path, pair["style_context"])
        frozen_files[_relative_path(context_path, root=root)] = sha256_file(context_path)
        brief_path = _evaluation_path(case["external_reference"]["style_brief_path"], root=root)
        frozen_files[_relative_path(brief_path, root=root)] = sha256_file(brief_path)
        reference_path = _evaluation_path(case["external_reference"]["path"], root=root)
        frozen_files[_relative_path(reference_path, root=root)] = sha256_file(reference_path)
        external = case["external_reference"]
        reference_manifest["references"].append(
            {
                "case_id": case_id,
                "reference_id": external["reference_id"],
                "filename": external["filename"],
                "private_asset_path": external["path"],
                "sha256": external["sha256"],
                "role": external["role"],
                "duties": list(external["duties"]),
                "style_priority": external["style_priority"],
                "style_axes": list(case["expected_relevant_style_axes"]),
                "source": external["provenance"],
            }
        )
        _write_frozen_text(context_dir / "prompt-A.txt", pair["plans"]["A"]["prompt"])
        _write_frozen_text(context_dir / "prompt-B.txt", pair["plans"]["B"]["prompt"])
        _write_frozen_text(context_dir / "prompt-C.txt", pair["plans"]["C"]["prompt"])
        for group in GROUPS:
            prompt_path = context_dir / f"prompt-{group}.txt"
            frozen_files[_relative_path(prompt_path, root=root)] = sha256_file(prompt_path)
        diff_dir = root / "evaluation" / "style-regression" / "prompt-diffs"
        diff_dir.mkdir(parents=True, exist_ok=True)
        for left, right in (("A", "B"), ("B", "C")):
            diff_path = diff_dir / f"{case_id}-{left}-vs-{right}.diff"
            diff_lines = difflib.unified_diff(
                pair["plans"][left]["prompt"].splitlines(),
                pair["plans"][right]["prompt"].splitlines(),
                fromfile=left,
                tofile=right,
                lineterm="",
            )
            _write_frozen_text(diff_path, "\n".join(diff_lines))
            frozen_files[_relative_path(diff_path, root=root)] = sha256_file(diff_path)

    reference_manifest_path = root / "evaluation" / "style-regression" / "reference-selection" / "style-reference-manifest.json"
    _write_frozen_json(reference_manifest_path, reference_manifest)
    frozen_files[_relative_path(reference_manifest_path, root=root)] = sha256_file(reference_manifest_path)

    diff_document = {
        "schema_version": 1,
        "selector_fix": "excluded_for is applied before priority and coverage selection",
        "source_record": _load_pre_selector_evidence(root=root)["source_record"],
        "cases": diff_cases,
    }
    diff_path = root / "evaluation" / "style-regression" / "reference-selection" / "selector-diff.json"
    _write_frozen_json(diff_path, diff_document)
    frozen_files[_relative_path(diff_path, root=root)] = sha256_file(diff_path)
    base_scene = root / "evaluation" / "style-regression" / "prompts" / "base-scene.txt"
    _write_frozen_text(base_scene, compose_scene_prompt(cases_document["cases"][0]))
    frozen_files[_relative_path(base_scene, root=root)] = sha256_file(base_scene)
    freeze_document = {
        "schema_version": 1,
        "experiment_id": cases_document.get("experiment_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": _git_output(root, "rev-parse", "HEAD"),
        "runtime_sha256": sha256_file(root / "scripts" / "reference_runtime.py"),
        "adapter_sha256": sha256_file(root / "scripts" / "arco_real_adapter.py"),
        "runner_sha256": sha256_file(root / "scripts" / "run_style_regression.py"),
        "corrected_legacy": corrected_legacy,
        "corrected_legacy_metadata_sha256": sha256_file(
            root / "evaluation" / "style-regression" / "control-runtime" / "corrected-legacy.json"
        ),
        "style_policy_sha256": sha256_file(root / "runtime" / "style-policy.yaml"),
        "cases_sha256": sha256_file(cases_path),
        "historical_h": _historical_group_h_summary(root, cases_document),
        "selector_snapshots": selectors,
        "selector_diff_path": _relative_path(diff_path, root=root),
        "selector_diff_sha256": sha256_file(diff_path),
        "files": frozen_files,
    }
    _write_frozen_json(input_freeze_path, freeze_document)
    return freeze_document


def _historical_group_h_summary(
    root: Path,
    cases_document: Mapping[str, Any],
) -> dict[str, Any]:
    history = cases_document.get("historical_baseline") or {}
    manifest_value = history.get("manifest_path")
    if not isinstance(manifest_value, str) or not manifest_value:
        return {
            "available": False,
            "sample_count": 0,
            "provenance_status": "unavailable",
            "manifest_path": None,
            "manifest_sha256": None,
        }
    try:
        manifest_path = _evaluation_path(manifest_value, root=root)
    except ExperimentError as exc:
        return {
            "available": False,
            "sample_count": 0,
            "provenance_status": "invalid_path",
            "manifest_path": manifest_value,
            "manifest_sha256": None,
            "details": [str(exc)],
        }
    if not manifest_path.is_file():
        return {
            "available": False,
            "sample_count": 0,
            "provenance_status": "unavailable",
            "manifest_path": manifest_value,
            "manifest_sha256": None,
        }
    try:
        records = _load_jsonl(manifest_path)
    except ExperimentError as exc:
        return {
            "available": True,
            "sample_count": 0,
            "provenance_status": "invalid_manifest",
            "manifest_path": manifest_value,
            "manifest_sha256": sha256_file(manifest_path),
            "details": [str(exc)],
        }
    cases = _case_by_id(cases_document)
    complete = 0
    details: list[str] = []
    for row in records:
        if row.get("group") != HISTORICAL_GROUP or row.get("case_id") not in cases:
            details.append(f"Unexpected historical row: {row.get('case_id')}:{row.get('group')}.")
            continue
        if row.get("provenance_status") not in {"verified", "reconstructed"}:
            details.append(f"Historical row lacks complete provenance: {row.get('case_id')}:{row.get('replicate')}.")
            continue
        output_value = row.get("output_path")
        try:
            output_path = _repo_path(str(output_value), root=root)
            output_path.relative_to((root / "evaluation" / "style-regression" / "private-assets").resolve())
            if not output_path.is_file() or row.get("output_sha256") != sha256_file(output_path):
                raise ExperimentError("output is missing or its hash does not match")
        except (ExperimentError, OSError, ValueError) as exc:
            details.append(f"Historical output is unverifiable for {row.get('case_id')}:{row.get('replicate')}: {exc}.")
            continue
        complete += 1
    provenance_status = "complete" if complete == len(records) else "partial_or_missing"
    return {
        "available": True,
        "sample_count": len(records),
        "verified_sample_count": complete,
        "provenance_status": provenance_status,
        "manifest_path": manifest_value,
        "manifest_sha256": sha256_file(manifest_path),
        "details": details,
    }


def _writable_probe(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".preflight-write-", delete=True):
            pass
        return True
    except OSError:
        return False


def _validate_frozen_inputs(
    root: Path,
    cases_document: Mapping[str, Any],
    plans: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    errors: list[str] = []
    freeze_path = _input_freeze_path(root)
    if not freeze_path.is_file():
        return ["Frozen inputs record is missing: evaluation/style-regression/inputs-freeze.json"]
    try:
        freeze = _load_json(freeze_path)
    except ExperimentError as exc:
        return [str(exc)]
    if freeze.get("schema_version") != 1:
        errors.append("inputs-freeze.json schema_version must be 1.")
    cases_path = root / "evaluation" / "style-regression" / "cases.yaml"
    if not cases_path.is_file() or freeze.get("cases_sha256") != sha256_file(cases_path):
        errors.append("cases.yaml changed after inputs were frozen.")
    expected_runtime_hash = freeze.get("runtime_sha256")
    runtime_path = root / "scripts" / "reference_runtime.py"
    if not runtime_path.is_file() or expected_runtime_hash != sha256_file(runtime_path):
        errors.append("Production Runtime changed after inputs were frozen.")
    adapter_path = root / "scripts" / "arco_real_adapter.py"
    if not adapter_path.is_file() or freeze.get("adapter_sha256") != sha256_file(adapter_path):
        errors.append("ArcoRealAdapter changed after inputs were frozen.")
    control_metadata_path = root / "evaluation" / "style-regression" / "control-runtime" / "corrected-legacy.json"
    if (
        not control_metadata_path.is_file()
        or freeze.get("corrected_legacy_metadata_sha256") != sha256_file(control_metadata_path)
    ):
        errors.append("Corrected Legacy metadata changed after inputs were frozen.")
    try:
        corrected_legacy = _control_runtime_metadata(root)
        if freeze.get("corrected_legacy", {}).get("selector_patch_revision") != corrected_legacy.get("selector_patch_revision"):
            errors.append("Corrected Legacy revision changed after inputs were frozen.")
    except ExperimentError as exc:
        errors.append(str(exc))

    files = freeze.get("files")
    if not isinstance(files, Mapping) or not files:
        errors.append("inputs-freeze.json must record frozen file hashes.")
        files = {}
    for relative, expected_hash in files.items():
        try:
            artifact = _repo_path(str(relative), root=root)
            if not artifact.is_file():
                errors.append(f"Frozen artifact is missing: {relative}")
            elif not isinstance(expected_hash, str) or sha256_file(artifact) != expected_hash:
                errors.append(f"Frozen artifact hash mismatch: {relative}")
        except ExperimentError as exc:
            errors.append(str(exc))

    selectors = freeze.get("selector_snapshots")
    if not isinstance(selectors, Mapping):
        errors.append("inputs-freeze.json selector_snapshots must be a mapping.")
        selectors = {}
    required_frozen_paths = {
        "evaluation/style-regression/prompts/base-scene.txt",
        "evaluation/style-regression/reference-selection/pre-selector-fix-evidence.json",
        "evaluation/style-regression/reference-selection/style-reference-manifest.json",
    }
    for case in cases_document.get("cases", []):
        external = case.get("external_reference") or {}
        case_id = str(case.get("case_id"))
        selector_record = selectors.get(case_id, {})
        normalized_reference_paths: list[str] = []
        for field in ("path", "style_brief_path"):
            try:
                normalized_reference_paths.append(
                    _relative_path(_evaluation_path(str(external.get(field, "")), root=root), root=root)
                )
            except ExperimentError:
                normalized_reference_paths.append("")
        required_frozen_paths.update(
            {
                *normalized_reference_paths,
                f"evaluation/style-regression/style-context/{case_id}/resolved-style-context.json",
                f"evaluation/style-regression/style-context/{case_id}/prompt-A.txt",
                f"evaluation/style-regression/style-context/{case_id}/prompt-B.txt",
                f"evaluation/style-regression/style-context/{case_id}/prompt-C.txt",
                f"evaluation/style-regression/prompt-diffs/{case_id}-A-vs-B.diff",
                f"evaluation/style-regression/prompt-diffs/{case_id}-B-vs-C.diff",
                str(selector_record.get("path", "")),
            }
        )
    for relative in sorted(required_frozen_paths):
        if not relative or relative not in files:
            errors.append(f"inputs-freeze.json is missing required artifact hash: {relative or '<empty path>'}")

    selector_diff_path = freeze.get("selector_diff_path")
    selector_diff_hash = freeze.get("selector_diff_sha256")
    try:
        diff_path = _repo_path(str(selector_diff_path), root=root)
        if not diff_path.is_file() or sha256_file(diff_path) != selector_diff_hash:
            errors.append("Frozen selector diff is missing or its hash changed.")
        else:
            diff = _load_json(diff_path)
            diff_cases = {
                item.get("case_id"): item
                for item in diff.get("cases", [])
                if isinstance(item, Mapping)
            }
            if set(diff_cases) != set(CASE_IDS):
                errors.append("Frozen selector diff must contain all four cases.")
            for case_id in CASE_IDS:
                if case_id in diff_cases and diff_cases[case_id].get("selector_confound") is not True:
                    errors.append(f"{case_id} historical selector confound must remain recorded as true.")
    except (ExperimentError, TypeError) as exc:
        errors.append(f"Frozen selector diff validation failed: {exc}")

    for case in cases_document.get("cases", []):
        case_id = str(case.get("case_id"))
        pair = plans.get(case_id)
        selector_record = selectors.get(case_id)
        if not isinstance(selector_record, Mapping):
            errors.append(f"{case_id} A/B/C selector snapshot hash is missing from inputs-freeze.json.")
            continue
        try:
            snapshot_path = _repo_path(str(selector_record.get("path")), root=root)
            if not snapshot_path.is_file() or sha256_file(snapshot_path) != selector_record.get("sha256"):
                errors.append(f"{case_id} A/B/C selector snapshot is missing or its hash changed.")
                continue
            snapshot = _load_json(snapshot_path)
            if snapshot.get("parity") is not True or not all(group in snapshot for group in GROUPS):
                errors.append(f"{case_id} A/B/C selector parity is not frozen as PASS.")
            frozen_groups = {group: snapshot[group] for group in GROUPS if group in snapshot}
            parity_errors = _selection_parity_errors(frozen_groups)
            errors.extend(f"{case_id} {message}" for message in parity_errors)
            if pair is None:
                continue
            current_groups = pair.get("selector_snapshots") or {}
            for group in GROUPS:
                if snapshot.get(group) != current_groups.get(group):
                    errors.append(f"{case_id} Group {group} selection differs from its frozen snapshot.")
                    break
            if pair.get("selector_parity") is not True:
                errors.append(f"{case_id} A/B/C selector parity failed.")
        except (ExperimentError, OSError, TypeError) as exc:
            errors.append(f"{case_id} selector snapshot validation failed: {exc}")

        context_dir = _context_dir(case_id, root=root)
        context_path = context_dir / "resolved-style-context.json"
        if not context_path.is_file():
            errors.append(f"{case_id} frozen ResolvedStyleContext is missing.")
        else:
            try:
                frozen_context = _load_json(context_path)
                if pair is not None and frozen_context != pair.get("style_context"):
                    errors.append(f"{case_id} production ResolvedStyleContext differs from its frozen context.")
                if pair is not None and pair["plans"]["B"].get("style_context_hash") != pair["plans"]["C"].get("style_context_hash"):
                    errors.append(f"{case_id} B/C Style Context hashes differ.")
            except ExperimentError as exc:
                errors.append(str(exc))
        for group in GROUPS:
            prompt_path = context_dir / f"prompt-{group}.txt"
            if not prompt_path.is_file():
                errors.append(f"{case_id} frozen Group {group} prompt is missing.")
            elif pair is not None and prompt_path.read_text(encoding="utf-8").rstrip("\n") != pair["plans"][group]["prompt"]:
                errors.append(f"{case_id} frozen Group {group} prompt differs from its compiled prompt.")
        if pair is not None:
            scene = compose_scene_prompt(case)
            if any(scene not in pair["plans"][group]["prompt"] for group in GROUPS):
                errors.append(f"{case_id} A/B/C base scene parity failed.")
            if pair["plans"]["C"]["prompt"] != f"{pair['plans']['B']['prompt']}\n\n{pair['hygiene_block']}":
                errors.append(f"{case_id} B/C prompt diff contains changes beyond Rendering Hygiene.")
            if pair["plans"]["A"].get("style_context_hash") is not None:
                errors.append(f"{case_id} Group A must not use a ResolvedStyleContext.")
            if pair["plans"]["B"]["selected_reference_ids"] != pair["plans"]["C"]["selected_reference_ids"]:
                errors.append(f"{case_id} B/C selected references differ.")
            if pair["plans"]["B"]["referenced_image_paths"] != pair["plans"]["C"]["referenced_image_paths"]:
                errors.append(f"{case_id} B/C image inputs differ.")
    return sorted(set(errors))


def collect_preflight(
    root: Path = ROOT,
    *,
    selected_cases: set[str] | None = None,
    hard: bool = False,
    provider_binding: str | None = None,
    codex_managed: bool = False,
    allow_formal_progress: bool = False,
    legacy_runner_hash_allowlist: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    if codex_managed and provider_binding:
        raise ExperimentError("Choose either --codex-managed or --provider-binding, not both.")
    evaluation_dir = _style_regression_dir(root)
    cases_document = _load_yaml(evaluation_dir / "cases.yaml")
    if not isinstance(cases_document, Mapping):
        raise ExperimentError("cases.yaml must contain a mapping.")
    schema_errors = validate_case_schema(cases_document)
    cases_by_id = _case_by_id(cases_document)
    relevant_cases = [
        case for case_id, case in cases_by_id.items()
        if selected_cases is None or case_id in selected_cases
    ]
    case_blockers: dict[str, list[str]] = {case_id: [] for case_id in CASE_IDS}
    global_blockers: list[str] = []

    def add_blocker(message: str) -> None:
        matching_case = next((case_id for case_id in CASE_IDS if message.startswith(case_id)), None)
        if matching_case:
            case_blockers[matching_case].append(message)
        else:
            global_blockers.append(message)

    for error in schema_errors:
        add_blocker(error)
    if selected_cases and not selected_cases.issubset(set(cases_by_id)):
        global_blockers.append(f"Unknown case selection: {sorted(selected_cases - set(cases_by_id))}")
    if hard and set(cases_by_id) != set(CASE_IDS):
        global_blockers.append("Hard preflight requires the complete four-case frozen design.")
    if hard and set(case["case_id"] for case in relevant_cases) != set(CASE_IDS):
        global_blockers.append("Hard preflight cannot run on a selected subset of cases.")

    try:
        ignore_text = (root / ".gitignore").read_text(encoding="utf-8")
    except OSError:
        ignore_text = ""
    for required_ignore in (
        "evaluation/style-regression/private-assets/",
        "evaluation/style-regression/outputs/",
        "evaluation/style-regression/pilot/outputs/",
        "evaluation/style-regression/host-smoke/outputs/",
        "evaluation/style-regression/blind-map.private.json",
    ):
        if required_ignore not in ignore_text.splitlines():
            global_blockers.append(f".gitignore is missing {required_ignore}")
    group_config = cases_document.get("groups") or {}
    try:
        declared_policy = (evaluation_dir / group_config["C"]["style_policy_path"]).resolve()
        if declared_policy != (root / "runtime" / "style-policy.yaml").resolve():
            global_blockers.append("Group C style_policy_path must resolve to runtime/style-policy.yaml.")
    except (KeyError, TypeError):
        global_blockers.append("Group C must declare the frozen style_policy_path.")

    for case in relevant_cases:
        case_id = case["case_id"]
        external = case.get("external_reference") or {}
        try:
            external_path = _evaluation_path(external.get("path", ""), root=root)
        except ExperimentError as exc:
            case_blockers[case_id].append(str(exc))
            continue
        if not external_path.is_file():
            case_blockers[case_id].append(f"{case_id} external style image is missing: {external.get('path')}")
        elif not isinstance(external.get("sha256"), str):
            case_blockers[case_id].append(f"{case_id} external reference SHA-256 is not frozen.")
        elif external.get("sha256") != sha256_file(external_path):
            case_blockers[case_id].append(f"{case_id} external style image hash mismatch.")
        try:
            external_path.relative_to((evaluation_dir / "private-assets").resolve())
        except ValueError:
            case_blockers[case_id].append(f"{case_id} external style image must be under gitignored private-assets/.")
        try:
            _load_case_style_brief(case, root=root)
        except ExperimentError as exc:
            case_blockers[case_id].append(str(exc))

    historical_h = _historical_group_h_summary(root, cases_document)
    try:
        corrected_legacy = _control_runtime_metadata(root)
    except ExperimentError as exc:
        corrected_legacy = None
        global_blockers.append(str(exc))

    output_root = (evaluation_dir / "outputs").resolve()
    planned_outputs: set[Path] = set()
    for case_id in (selected_cases or set(CASE_IDS)):
        for group in GENERATED_GROUPS:
            for replicate in range(1, EXPECTED_REPLICATES + 1):
                candidate = (output_root / case_id / f"{group}-r{replicate}.png").resolve()
                try:
                    candidate.relative_to(output_root)
                except ValueError:
                    global_blockers.append(f"Unsafe output path for {case_id} {group} r{replicate}.")
                if candidate in planned_outputs:
                    global_blockers.append(f"Output path collision: {candidate}")
                planned_outputs.add(candidate)
    if not _writable_probe(evaluation_dir):
        global_blockers.append("Experiment directory is not writable for recorded prompts/manifests.")
    if not _writable_probe(evaluation_dir / "pilot" / "outputs"):
        global_blockers.append("Pilot output directory is not writable.")
    if not _writable_probe(evaluation_dir / "host-smoke" / "outputs"):
        global_blockers.append("Host smoke output directory is not writable.")
    global_blockers.extend(
        _pilot_artifact_errors(root, legacy_runner_hash_allowlist=legacy_runner_hash_allowlist)
    )

    # A new transport capture may retain explicitly quarantined legacy audit
    # artifacts, but no receipt-validated formal sample may count toward it.
    formal_rows: list[dict[str, Any]] = []
    formal_counts = {group: 0 for group in GENERATED_GROUPS}
    try:
        formal_rows = _load_jsonl(evaluation_dir / "manifest.jsonl")
        formal_counts = _compliant_formal_sample_counts(
            formal_rows,
            root=root,
            legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
        )
        if sum(formal_counts.values()) and not allow_formal_progress:
            global_blockers.append("Receipt-validated formal samples exist; a new Batch 4B.3-T capture requires 0/36 compliant samples.")
        if not allow_formal_progress:
            global_blockers.extend(_validate_pre_capture_formal_history(root))
    except ExperimentError as exc:
        global_blockers.append(str(exc))

    plans: dict[str, Any] = {}
    if any((root / relative).is_file() for relative in (
        "character/assets.yaml",
        "runtime/generation.yaml",
        "character/style-baseline.yaml",
        "runtime/style-policy.yaml",
    )):
        try:
            assets_document = _load_yaml(root / "character" / "assets.yaml")
            generation_config = _load_yaml(root / "runtime" / "generation.yaml")
            style_baseline = _load_yaml(root / "character" / "style-baseline.yaml")
            style_policy = _load_yaml(root / "runtime" / "style-policy.yaml")
            for case in relevant_cases:
                case_id = case["case_id"]
                if case_blockers[case_id]:
                    continue
                try:
                    references, reference_errors = _validate_reference_assets(
                        root, case, assets_document["assets"], generation_config
                    )
                    if reference_errors:
                        case_blockers[case_id].extend(reference_errors)
                        continue
                    plans[case_id] = _build_pair(root, case, references, style_baseline, style_policy)
                except (KeyError, TypeError, ReferenceRuntimeError, ExperimentError) as exc:
                    case_blockers[case_id].append(f"{case_id} pipeline resolution failed: {exc}")
        except (KeyError, TypeError, ReferenceRuntimeError, ExperimentError) as exc:
            global_blockers.append(f"Pipeline dry-run failed: {exc}")
    else:
        global_blockers.append("Production Runtime, Adapter, or Style policy inputs are missing.")

    frozen_errors = _validate_frozen_inputs(root, cases_document, plans)
    for error in frozen_errors:
        add_blocker(error)

    provider_status: dict[str, Any] = {
        "binding": provider_binding,
        "execution_mode": "codex-managed" if codex_managed else "provider-binding",
        "available": False,
        "signature_compatible": False,
    }
    if hard:
        if codex_managed:
            provider_status["engine"] = "Codex-managed"
            provider_status["available"] = True
            provider_status["signature_compatible"] = None
            smoke_errors = _validate_codex_smoke(root)
            smoke_report_path = root / CODEX_SMOKE_REPORT_PATH
            provider_status["smoke_status"] = (
                "PASS" if not smoke_errors else "FAIL" if smoke_report_path.is_file() else "NOT_RUN"
            )
            global_blockers.extend(smoke_errors)
        elif not provider_binding:
            global_blockers.append("Hard preflight requires --provider-binding module:callable or --codex-managed.")
            smoke_errors = _validate_host_smoke(root, provider_binding)
            smoke_report_path = evaluation_dir / "host-smoke" / "result.json"
            provider_status["smoke_status"] = (
                "PASS" if not smoke_errors else "FAIL" if smoke_report_path.is_file() else "NOT_RUN"
            )
            global_blockers.extend(smoke_errors)
        else:
            try:
                provider = _load_provider_callable(provider_binding)
                module = importlib.import_module(provider.__module__)
                module_path = getattr(module, "__file__", None)
                provider_status["available"] = True
                provider_status["signature_compatible"] = True
                provider_status["callable"] = getattr(provider, "__name__", type(provider).__name__)
                if isinstance(module_path, str):
                    provider_status["module_path"] = str(Path(module_path).resolve())
                    if Path(module_path).is_file():
                        provider_status["module_sha256"] = sha256_file(Path(module_path))
            except (ExperimentError, ImportError, AttributeError) as exc:
                global_blockers.append(str(exc))
            smoke_errors = _validate_host_smoke(root, provider_binding)
            smoke_report_path = evaluation_dir / "host-smoke" / "result.json"
            provider_status["smoke_status"] = (
                "PASS" if not smoke_errors else "FAIL" if smoke_report_path.is_file() else "NOT_RUN"
            )
            global_blockers.extend(smoke_errors)
    else:
        smoke_errors = (
            _validate_codex_smoke(root)
            if codex_managed
            else _validate_host_smoke(root, provider_binding)
        )
        provider_status["smoke_status"] = "PASS" if not smoke_errors else "NOT_RUN"

    for case_id in CASE_IDS:
        case_blockers[case_id] = sorted(set(case_blockers[case_id]))
    global_blockers = sorted(set(global_blockers))
    case_statuses = {
        case_id: {
            "status": "READY" if not case_blockers[case_id] else "BLOCKED",
            "blockers": case_blockers[case_id],
            "selector_confound": None,
        }
        for case_id in CASE_IDS
    }
    try:
        selector_diff_path = root / "evaluation" / "style-regression" / "reference-selection" / "selector-diff.json"
        selector_evidence_path = selector_diff_path
        if not selector_evidence_path.is_file():
            selector_evidence_path = (
                root
                / "evaluation"
                / "style-regression"
                / "reference-selection"
                / "managed-selector-comparison.json"
            )
        if selector_evidence_path.is_file():
            diff = _load_json(selector_evidence_path)
            for item in diff.get("cases", []):
                case_id = item.get("case_id")
                if case_id in case_statuses:
                    case_statuses[case_id]["selector_confound"] = bool(item.get("selector_confound"))
    except ExperimentError:
        pass
    for case_id in CASE_IDS:
        if case_statuses[case_id]["selector_confound"] is not True:
            case_blockers[case_id].append(f"{case_id} historical selector confound is missing or false.")
            case_statuses[case_id]["blockers"] = sorted(set(case_blockers[case_id]))
            case_statuses[case_id]["status"] = "BLOCKED"
    all_case_ready = all(item["status"] == "READY" for item in case_statuses.values())
    global_ready = all_case_ready and not global_blockers
    errors = global_blockers + [message for entries in case_blockers.values() for message in entries]
    return {
        "cases_document": cases_document,
        "cases": relevant_cases,
        "historical_h": historical_h,
        "corrected_legacy": corrected_legacy,
        "formal_sample_counts": {
            group: formal_counts[group]
            for group in GENERATED_GROUPS
        },
        "plans": plans,
        "errors": errors,
        "global_blockers": global_blockers,
        "case_statuses": case_statuses,
        "global_status": "READY" if global_ready else "BLOCKED",
        "provider_binding": provider_status,
        "execution_mode": "codex-managed" if codex_managed else "provider-binding",
        "hard_preflight": hard,
        "legacy_runner_hash_allowlist": dict(legacy_runner_hash_allowlist or {}),
    }


def write_preflight_report(preflight: Mapping[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    cases_report = preflight.get("case_statuses") or {}
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": preflight.get("global_status", "BLOCKED"),
        "commit_sha": _git_output(root, "rev-parse", "HEAD"),
        "worktree_dirty": bool(_git_output(root, "status", "--porcelain=v1")),
        "provider_binding": preflight.get("provider_binding", {}),
        "historical_h": preflight.get("historical_h", {"available": False, "sample_count": 0}),
        "corrected_legacy": preflight.get("corrected_legacy"),
        "formal_sample_counts": preflight.get("formal_sample_counts", {group: 0 for group in GENERATED_GROUPS}),
        "formal_sample_total": sum((preflight.get("formal_sample_counts") or {}).values()),
        "formal_sample_target": EXPECTED_SAMPLE_COUNT,
        "global_blockers": list(preflight.get("global_blockers") or []),
        "cases": cases_report,
    }
    json_path, markdown_path = _preflight_report_paths(root)
    _write_json_atomic(json_path, report)
    lines = [
        "# Batch 4B.3-F Hard Preflight",
        "",
        f"**Experiment: {report['status']}**",
        "",
        f"Commit: `{report['commit_sha']}`; dirty worktree: `{str(report['worktree_dirty']).lower()}`.",
        "",
        f"Formal A/B/C: **{report['formal_sample_total']}/{EXPECTED_SAMPLE_COUNT}**.",
        f"Historical H: {'available' if report['historical_h'].get('available') else 'unavailable'}, {report['historical_h'].get('sample_count', 0)} samples; excluded from verdict.",
        f"Execution mode: `{report['provider_binding'].get('execution_mode')}`; engine: `{report['provider_binding'].get('engine', 'host-provider')}`; binding: `{report['provider_binding'].get('binding')}`; available: `{report['provider_binding'].get('available')}`; smoke: `{report['provider_binding'].get('smoke_status')}`.",
        f"Corrected Legacy: `{(report['corrected_legacy'] or {}).get('selector_patch_revision')}` at `{(report['corrected_legacy'] or {}).get('worktree_path')}`.",
        "",
        "## Cases",
        "",
    ]
    for case_id in CASE_IDS:
        case_report = cases_report.get(case_id, {"status": "BLOCKED", "blockers": ["Case report missing."]})
        lines.append(f"### {case_id}: {case_report['status']}")
        lines.append("")
        lines.append(f"Selector confound: `{case_report.get('selector_confound')}`.")
        for blocker in case_report.get("blockers", []):
            lines.append(f"- {blocker}")
        if not case_report.get("blockers"):
            lines.append("- All case gates passed.")
        lines.append("")
    lines.extend(["## Global blockers", ""])
    lines.extend(f"- {blocker}" for blocker in report["global_blockers"])
    if not report["global_blockers"]:
        lines.append("- None.")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return report


def _relative_path(path: Path, *, root: Path = ROOT) -> str:
    return path.resolve(strict=False).relative_to(root.resolve()).as_posix()


def _sample_key(case_id: str, group: str, replicate: int) -> str:
    return f"{case_id}:{group}:r{replicate}"


def _prompt_path(case_id: str, group: str, replicate: int, *, root: Path = ROOT) -> Path:
    return _style_regression_dir(root) / "prompts" / f"{case_id}-{group}-r{replicate}.txt"


def _context_path(case_id: str, group: str, replicate: int, *, root: Path = ROOT) -> Path:
    return _style_regression_dir(root) / "contexts" / f"{case_id}-{group}-r{replicate}.yaml"


def _base_prompt_path(case_id: str, *, root: Path = ROOT) -> Path:
    del case_id
    return _style_regression_dir(root) / "prompts" / "base-scene.txt"


def _output_path(case_id: str, group: str, replicate: int, *, root: Path = ROOT) -> Path:
    return _style_regression_dir(root) / "outputs" / case_id / f"{group}-r{replicate}.png"


def _manifest_index(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        key = record.get("sample_key") or _sample_key(
            str(record.get("case_id")), str(record.get("group")), int(record.get("replicate", 0))
        )
        if key in indexed:
            raise ExperimentError(f"Duplicate experiment manifest sample: {key}")
        indexed[key] = dict(record)
    return indexed


def _upsert_manifest(record: Mapping[str, Any], *, path: Path = MANIFEST_PATH) -> None:
    records = _load_jsonl(path)
    indexed = _manifest_index(records)
    key = str(record["sample_key"])
    indexed[key] = dict(record)
    ordered = sorted(
        indexed.values(),
        key=lambda item: (
            CASE_IDS.index(item["case_id"]),
            int(item["replicate"]),
            GROUPS.index(item["group"]),
        ),
    )
    _write_manifest_atomic(path, ordered)


def _identity_and_external_metadata(references: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    identity = [ref for ref in references if ref.get("role") == "identity_reference"]
    variant = [ref for ref in references if ref.get("role") == "outfit_reference"]
    external = [ref for ref in references if ref.get("source_scope") == "external_how"]
    return {
        "identity_reference_ids": [ref["reference_id"] for ref in identity],
        "identity_reference_hashes": [_reference_hash(ref) for ref in identity],
        "variant_reference_ids": [ref["reference_id"] for ref in variant],
        "variant_reference_hashes": [_reference_hash(ref) for ref in variant],
        "external_reference_ids": [ref["reference_id"] for ref in external],
        "external_reference_hashes": [_reference_hash(ref) for ref in external],
        "reference_order": [ref["reference_id"] for ref in references],
    }


def _persist_inputs(
    case: Mapping[str, Any],
    group: str,
    replicate: int,
    plan: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    *,
    root: Path = ROOT,
) -> tuple[Path, Path | None, Path, str]:
    prompt_file = _prompt_path(case["case_id"], group, replicate, root=root)
    context_file = _context_path(case["case_id"], group, replicate, root=root)
    base_file = _base_prompt_path(case["case_id"], root=root)
    destinations = [prompt_file, base_file]
    if context is not None:
        destinations.append(context_file)
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
    _write_frozen_text(prompt_file, str(plan["prompt"]))
    if context is not None:
        _write_frozen_text(
            context_file,
            yaml.safe_dump(dict(context), allow_unicode=True, sort_keys=False).rstrip("\n"),
        )
    else:
        context_file = None
    scene = compose_scene_prompt(case)
    _write_frozen_text(base_file, scene)
    return prompt_file, context_file, base_file, sha256_file(prompt_file)


def _write_frozen_text(path: Path, value: str) -> None:
    contents = value.rstrip("\n") + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != contents:
            raise ExperimentError(f"Frozen experiment text changed; refusing to overwrite {path}.")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8", newline="\n")


def _validate_host_provider(provider: Any) -> Callable[..., Any]:
    if not callable(provider):
        raise ExperimentError("Provider binding is not callable.")
    try:
        signature = inspect.signature(provider)
        parameters = list(signature.parameters.values())
        expected_names = ["prompt", "referenced_image_paths"]
        if [parameter.name for parameter in parameters] != expected_names or any(
            parameter.kind is not inspect.Parameter.KEYWORD_ONLY
            or parameter.default is not inspect.Parameter.empty
            for parameter in parameters
        ):
            raise TypeError("signature must declare exactly two required keyword-only parameters")
        prompt_annotation = parameters[0].annotation
        paths_annotation = parameters[1].annotation
        if prompt_annotation not in (inspect.Parameter.empty, str, "str"):
            raise TypeError("prompt annotation must be str")
        if paths_annotation not in (
            inspect.Parameter.empty,
            list[str],
            "list[str]",
            "typing.List[str]",
        ):
            raise TypeError("referenced_image_paths annotation must be list[str]")
        signature.bind(prompt=HOST_SMOKE_PROMPT, referenced_image_paths=[])
    except (TypeError, ValueError) as exc:
        raise ExperimentError(
            "Provider callable must match builtin_image_gen(*, prompt: str, referenced_image_paths: list[str])."
        ) from exc
    return provider


def _load_provider_callable(binding: str) -> Callable[..., Any]:
    module_name, separator, attribute_name = binding.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ExperimentError("--provider-binding must use module.path:callable syntax.")
    try:
        module = importlib.import_module(module_name)
        provider = getattr(module, attribute_name)
    except (ImportError, AttributeError) as exc:
        raise ExperimentError(f"Cannot load existing host provider binding {binding}: {exc}") from exc
    try:
        return _validate_host_provider(provider)
    except ExperimentError as exc:
        raise ExperimentError(f"Invalid host provider binding {binding}: {exc}") from exc


def run_host_smoke(
    binding: str | None = None,
    *,
    provider: Callable[..., Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Run one standalone transport check with no Arco or Style inputs."""
    report_path = root / "evaluation" / "style-regression" / "host-smoke" / "result.json"
    output_path = root / "evaluation" / "style-regression" / "host-smoke" / "outputs" / "output.png"
    if report_path.exists() or output_path.exists():
        raise ExperimentError("Host smoke artifacts already exist; replacement and retry are forbidden.")
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    started_at_ns = int(started_at.timestamp() * 1_000_000_000)
    report: dict[str, Any] = {
        "schema_version": 1,
        "binding": binding,
        "prompt_sha256": hashlib.sha256(HOST_SMOKE_PROMPT.encode("utf-8")).hexdigest(),
        "started_at": started_at.isoformat(),
        "smoke": True,
        "pilot": False,
        "formal": False,
        "status": "FAIL",
    }
    try:
        if provider is None:
            if not binding:
                raise ExperimentError("Host smoke requires --provider-binding module:callable.")
            provider = _load_provider_callable(binding)
        else:
            provider = _validate_host_provider(provider)
        report["callable"] = getattr(provider, "__name__", type(provider).__name__)
        result = provider(prompt=HOST_SMOKE_PROMPT, referenced_image_paths=[])
        output_value: Any = result
        if isinstance(result, Mapping):
            output_value = next(
                (result[key] for key in ("path", "file_path", "output_path", "image_path", "generated_image_path") if key in result),
                None,
            )
        if not isinstance(output_value, (str, Path)):
            raise ExperimentError("Host smoke callable must return a local output path.")
        source_path = Path(output_value).expanduser().resolve()
        if not source_path.is_file() or source_path.stat().st_size == 0:
            raise ExperimentError("Host smoke output path is missing or empty.")
        if source_path.stat().st_mtime_ns < started_at_ns - HOST_SMOKE_MTIME_SKEW_NS:
            raise ExperimentError("Host smoke output was not newly generated during this attempt.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path != output_path.resolve():
            shutil.copy2(source_path, output_path)
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise ExperimentError("Host smoke output copy is missing or empty.")
        report.update(
            {
                "status": "PASS",
                "output_path": _relative_path(output_path, root=root),
                "output_sha256": sha256_file(output_path),
            }
        )
    except Exception as exc:
        report["failure_code"] = getattr(exc, "code", type(exc).__name__)
        report["failure_message"] = str(exc)
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["execution_seconds"] = round(time.perf_counter() - started, 6)
    _write_json_atomic(report_path, report)
    return report


def export_codex_smoke_task(*, root: Path = ROOT) -> dict[str, Any]:
    task_path = root / CODEX_SMOKE_TASK_PATH
    report_path = root / CODEX_SMOKE_REPORT_PATH
    output_path = root / "evaluation" / "style-regression" / "host-smoke" / "outputs" / "output.png"
    if task_path.exists() or report_path.exists() or output_path.exists():
        raise ExperimentError("Codex smoke artifacts already exist; replacement and retry are forbidden.")
    task = build_codex_task(
        task_id="smoke:4b2r",
        task_kind="smoke",
        case_id=None,
        group=None,
        replicate=None,
        prompt=HOST_SMOKE_PROMPT,
        referenced_image_paths=[],
        reference_ids=[],
        expected_output_path=_relative_path(output_path, root=root),
        frozen_input_hashes={
            "smoke_prompt_sha256": hashlib.sha256(HOST_SMOKE_PROMPT.encode("utf-8")).hexdigest(),
            "files": {},
        },
    )
    return write_codex_task(task, path=task_path)


def _codex_smoke_failure_report(
    task: Mapping[str, Any], exc: BaseException, *, root: Path
) -> dict[str, Any]:
    report_path = root / CODEX_SMOKE_REPORT_PATH
    report = {
        "schema_version": 1,
        "execution_mode": "codex-managed",
        "engine": "Codex-managed",
        "binding": None,
        "task_path": _relative_path(root / CODEX_SMOKE_TASK_PATH, root=root),
        "task_sha256": task.get("task_sha256"),
        "prompt_sha256": hashlib.sha256(HOST_SMOKE_PROMPT.encode("utf-8")).hexdigest(),
        "started_at": task.get("created_at"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "smoke": True,
        "pilot": False,
        "formal": False,
        "status": "FAIL",
        "failure_code": getattr(exc, "code", type(exc).__name__),
        "failure_message": str(exc),
    }
    if not report_path.exists():
        _write_json_atomic(report_path, report)
    return report


def accept_codex_smoke_output(
    task_path: Path, generated_path: Path | str, *, root: Path = ROOT
) -> dict[str, Any]:
    task = load_codex_task(task_path, root=root)
    report_path = root / CODEX_SMOKE_REPORT_PATH
    if task.get("task_kind") != "smoke" or task.get("task_id") != "smoke:4b2r":
        raise ExperimentError("Codex smoke acceptance received a non-smoke task.")
    if task.get("prompt") != HOST_SMOKE_PROMPT or task.get("referenced_image_paths") != []:
        raise ExperimentError("Codex smoke task does not match the frozen reference-free prompt.")
    if report_path.exists():
        raise ExperimentError("Codex smoke result already exists; retry is forbidden.")
    try:
        result = accept_codex_task_output(task_path, generated_path, root=root)
    except Exception as exc:
        _codex_smoke_failure_report(task, exc, root=root)
        raise
    report = {
        "schema_version": 1,
        "execution_mode": "codex-managed",
        "engine": "Codex-managed",
        "binding": None,
        "task_path": _relative_path(task_path, root=root),
        "task_sha256": task["task_sha256"],
        "prompt_sha256": task["prompt_sha256"],
        "started_at": task["created_at"],
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "smoke": True,
        "pilot": False,
        "formal": False,
        "status": "PASS",
        "output_path": _relative_path(result["output_path"], root=root),
        "output_sha256": result["output_sha256"],
        "output_size_bytes": result["size_bytes"],
        "generated_source_path": str(result["source_path"]),
    }
    _write_json_atomic(report_path, report)
    return report


def _validate_codex_smoke(root: Path) -> list[str]:
    task_path = root / CODEX_SMOKE_TASK_PATH
    report_path = root / CODEX_SMOKE_REPORT_PATH
    if not task_path.is_file():
        return ["Codex-managed smoke task is missing."]
    if not report_path.is_file():
        return ["Codex-managed smoke result is missing."]
    errors: list[str] = []
    try:
        task = load_codex_task(task_path, root=root)
        report = _load_json(report_path)
    except ExperimentError as exc:
        return [str(exc)]
    if task.get("task_kind") != "smoke" or task.get("task_id") != "smoke:4b2r":
        errors.append("Codex-managed smoke task identifiers are invalid.")
    if task.get("prompt") != HOST_SMOKE_PROMPT or task.get("referenced_image_paths") != []:
        errors.append("Codex-managed smoke prompt or reference set changed.")
    if report.get("execution_mode") != "codex-managed" or report.get("engine") != "Codex-managed":
        errors.append("Codex smoke execution metadata is invalid.")
    if report.get("binding") is not None:
        errors.append("Codex-managed smoke must not use a Python provider binding.")
    if report.get("status") != "PASS":
        errors.append("Codex-managed smoke test did not pass.")
    if report.get("smoke") is not True or report.get("pilot") is not False or report.get("formal") is not False:
        errors.append("Codex smoke record must be smoke-only, not Pilot or formal.")
    if report.get("task_path") != _relative_path(task_path, root=root) or report.get("task_sha256") != task.get("task_sha256"):
        errors.append("Codex smoke result does not match its immutable task.")
    if report.get("prompt_sha256") != task.get("prompt_sha256"):
        errors.append("Codex smoke prompt hash does not match its immutable task.")
    try:
        output_path = _repo_path(str(report.get("output_path", "")), root=root)
        expected_output = _repo_path(str(task["expected_output_path"]), root=root)
        if output_path != expected_output:
            errors.append("Codex smoke output path differs from its task.")
        if not output_path.is_file() or output_path.stat().st_size == 0:
            errors.append("Codex smoke output is missing or empty.")
        elif report.get("output_sha256") != sha256_file(output_path):
            errors.append("Codex smoke output hash does not match.")
        else:
            with output_path.open("rb") as handle:
                if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                    errors.append("Codex smoke output is not a PNG.")
    except (ExperimentError, OSError, ValueError):
        errors.append("Codex smoke output path is invalid.")
    return errors


def _validate_host_smoke(root: Path, binding: str | None) -> list[str]:
    report_path = root / "evaluation" / "style-regression" / "host-smoke" / "result.json"
    if not report_path.is_file():
        return ["Host smoke test is missing."]
    try:
        report = _load_json(report_path)
    except ExperimentError as exc:
        return [str(exc)]
    if report.get("execution_mode") == "codex-managed":
        if binding is not None:
            return ["Codex-managed smoke cannot satisfy a provider-binding preflight."]
        return _validate_codex_smoke(root)
    errors: list[str] = []
    expected_prompt_hash = hashlib.sha256(HOST_SMOKE_PROMPT.encode("utf-8")).hexdigest()
    if report.get("status") != "PASS":
        errors.append("Host smoke test did not pass.")
    if report.get("smoke") is not True or report.get("pilot") is not False or report.get("formal") is not False:
        errors.append("Host smoke record must be smoke-only, not Pilot or formal.")
    if report.get("binding") != binding:
        errors.append("Host smoke binding differs from the Preflight binding.")
    if report.get("prompt_sha256") != expected_prompt_hash:
        errors.append("Host smoke prompt hash is invalid.")
    try:
        started_at = datetime.fromisoformat(report["started_at"])
        completed_at = datetime.fromisoformat(report["completed_at"])
        if completed_at < started_at:
            errors.append("Host smoke completion time precedes its start time.")
    except (KeyError, TypeError, ValueError):
        started_at = None
        errors.append("Host smoke timestamps are invalid or missing.")
    output_value = report.get("output_path")
    try:
        output_path = _repo_path(str(output_value), root=root)
        expected_dir = (root / "evaluation" / "style-regression" / "host-smoke" / "outputs").resolve()
        output_path.relative_to(expected_dir)
        if not output_path.is_file() or output_path.stat().st_size == 0:
            errors.append("Host smoke output is missing or empty.")
        elif started_at is not None and output_path.stat().st_mtime_ns < (
            int(started_at.timestamp() * 1_000_000_000) - HOST_SMOKE_MTIME_SKEW_NS
        ):
            errors.append("Host smoke output was not newly generated during this attempt.")
        elif report.get("output_sha256") != sha256_file(output_path):
            errors.append("Host smoke output hash does not match.")
    except (ExperimentError, OSError, ValueError):
        errors.append("Host smoke output path is invalid.")
    return errors


def _check_existing_sample(
    existing: Mapping[str, Any] | None,
    output_path: Path,
    sample_key: str,
) -> bool:
    """Return true when a successful sample already exists; never retry failures."""
    if existing is not None:
        status = existing.get("status")
        if status == "succeeded":
            if not output_path.is_file():
                raise ExperimentError(f"Recorded output is missing for {sample_key}; refusing regeneration.")
            if existing.get("output_sha256") != sha256_file(output_path):
                raise ExperimentError(f"Recorded output hash changed for {sample_key}; refusing regeneration.")
            return True
        raise ExperimentError(f"Sample {sample_key} already has status {status}; retries are forbidden.")
    if output_path.exists():
        raise ExperimentError(f"Unmanifested output already exists for {sample_key}; refusing overwrite.")
    return False


def run_generation(
    preflight: Mapping[str, Any],
    *,
    provider: Callable[..., Any],
    selected_cases: set[str] | None = None,
    selected_groups: set[str] | None = None,
) -> dict[str, int]:
    if preflight["errors"]:
        raise ExperimentError("Preflight blocked:\n- " + "\n- ".join(preflight["errors"]))
    cases_document = preflight["cases_document"]
    pairs = preflight["plans"]
    case_by_id = _case_by_id(cases_document)
    chosen_cases = selected_cases or set(CASE_IDS)
    chosen_groups = selected_groups or set(GENERATED_GROUPS)
    if not chosen_groups.issubset(set(GENERATED_GROUPS)):
        raise ExperimentError("Formal generation groups must be selected from A, B, and C.")

    counts = {"succeeded": 0, "failed": 0, "skipped": 0}
    adapter = ArcoRealAdapter(provider)
    policy_hash = sha256_file(ROOT / "runtime" / "style-policy.yaml")
    production_revision = _git_output(ROOT, "rev-parse", "HEAD")
    corrected_legacy = preflight.get("corrected_legacy") or _control_runtime_metadata(ROOT)

    for case_id in CASE_IDS:
        if case_id not in chosen_cases:
            continue
        case = case_by_id[case_id]
        pair = pairs[case_id]
        for replicate in range(1, EXPECTED_REPLICATES + 1):
            for group in GENERATED_GROUPS:
                if group not in chosen_groups:
                    continue
                references = pair["references_by_group"][group]
                metadata = _identity_and_external_metadata(references)
                sample_key = _sample_key(case_id, group, replicate)
                output_path = _output_path(case_id, group, replicate)
                existing_index = _manifest_index(_load_jsonl(MANIFEST_PATH))
                if _check_existing_sample(existing_index.get(sample_key), output_path, sample_key):
                    counts["skipped"] += 1
                    continue
                plan = pair["plans"][group]
                context = pair["style_context"] if group in ("B", "C") else None
                prompt_file, context_file, base_file, prompt_hash = _persist_inputs(case, group, replicate, plan, context)
                selector_snapshot_path = _selection_path(case_id)
                selector_snapshot_hash = sha256_file(selector_snapshot_path)
                is_corrected_legacy = group == "A"
                record = {
                    "sample_key": sample_key,
                    "experiment_id": "arco-style-transfer-v1-batch-4b.2",
                    "batch": "4B.2",
                    "case_id": case_id,
                    "group": group,
                    "replicate": replicate,
                    "runtime_type": "corrected_legacy" if is_corrected_legacy else "production",
                    "runtime_commit": corrected_legacy["selector_patch_revision"] if is_corrected_legacy else production_revision,
                    "runtime_sha256": corrected_legacy["runtime_sha256"] if is_corrected_legacy else sha256_file(ROOT / "scripts" / "reference_runtime.py"),
                    "selector_revision": corrected_legacy["selector_patch_revision"] if is_corrected_legacy else production_revision,
                    "identity_variant": case["identity_variant"],
                    "state": case["state"],
                    "exposure_profile": case["exposure_profile"],
                    "image_transport_strategy": "referenced_image_paths",
                    **metadata,
                    "selected_reference_ids": list(plan["selected_reference_ids"]),
                    "selected_reference_hashes": [
                        _reference_hash(reference) for reference in references
                    ],
                    "reference_roles": [reference.get("role") for reference in references],
                    "reference_duties": [
                        list(reference.get("duties") or reference.get("inherit") or [])
                        for reference in references
                    ],
                    "style_reference": {
                        "reference_id": case["external_reference"]["reference_id"],
                        "role": case["external_reference"]["role"],
                        "duties": list(case["external_reference"]["duties"]),
                        "style_axes": list(case["expected_relevant_style_axes"]),
                        "style_priority": case["external_reference"]["style_priority"],
                        "provenance": case["external_reference"]["provenance"],
                        "sha256": case["external_reference"]["sha256"],
                    },
                    "reference_snapshot_path": _relative_path(selector_snapshot_path),
                    "reference_snapshot_sha256": selector_snapshot_hash,
                    "base_scene_prompt_path": _relative_path(base_file),
                    "base_scene_prompt_sha256": sha256_file(base_file),
                    "resolved_style_context_path": _relative_path(context_file) if context_file else None,
                    "resolved_style_context_sha256": sha256_file(context_file) if context_file else None,
                    "style_context_hash": plan.get("style_context_hash"),
                    "compiled_prompt_path": _relative_path(prompt_file),
                    "compiled_prompt_sha256": prompt_hash,
                    "hygiene_enabled": group == "C",
                    "style_policy_sha256": policy_hash if group == "C" else None,
                    "output_path": _relative_path(output_path),
                    "status": "started",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
                _upsert_manifest(record)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    provider_path = adapter.generate(
                        invocation_plan=plan,
                        reference_contracts=references,
                        reference_image_paths=plan["referenced_image_paths"],
                    )
                    if provider_path.resolve() != output_path.resolve():
                        shutil.copy2(provider_path, output_path)
                    record.update(
                        {
                            "status": "succeeded",
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "output_sha256": sha256_file(output_path),
                        }
                    )
                    counts["succeeded"] += 1
                except Exception as exc:  # Record failure, never retry or rescue.
                    record.update(
                        {
                            "status": "failed",
                            "generation_failed_at": datetime.now(timezone.utc).isoformat(),
                            "failure_code": getattr(exc, "code", type(exc).__name__),
                        }
                    )
                    counts["failed"] += 1
                _upsert_manifest(record)
    return counts


def run_pilot(
    preflight: Mapping[str, Any],
    *,
    provider: Callable[..., Any] | None = None,
    execution_mode: str = "provider-binding",
    root: Path = ROOT,
) -> dict[str, int]:
    """Run exactly one A/B/C transport Pilot for Case 01 into pilot/ artifacts."""
    case_statuses = preflight.get("case_statuses")
    if (
        preflight.get("global_status") != "READY"
        or preflight.get("errors")
        or not isinstance(case_statuses, Mapping)
        or any(case_statuses.get(case_id, {}).get("status") != "READY" for case_id in CASE_IDS)
    ):
        raise ExperimentError("Pilot is gated on all four cases reporting READY in hard preflight.")
    codex_managed = execution_mode == "codex-managed"
    if execution_mode not in {"provider-binding", "codex-managed"}:
        raise ExperimentError(f"Unsupported Pilot execution mode: {execution_mode}")
    if codex_managed:
        if preflight.get("execution_mode") != "codex-managed":
            raise ExperimentError("Codex-managed Pilot requires Codex-managed hard preflight.")
    elif provider is None or preflight.get("provider_binding", {}).get("available") is not True:
        raise ExperimentError("Pilot is gated on a successfully imported host provider binding.")
    if preflight.get("provider_binding", {}).get("smoke_status") != "PASS":
        raise ExperimentError("Pilot is gated on a passing reference-free host smoke test.")
    plans = preflight.get("plans")
    if not isinstance(plans, Mapping) or set(plans) != set(CASE_IDS):
        raise ExperimentError("Pilot requires production-resolved plans for all four READY cases.")
    freeze_errors = _validate_frozen_inputs(root, preflight["cases_document"], plans)
    if freeze_errors:
        raise ExperimentError("Pilot frozen-input validation failed:\n- " + "\n- ".join(freeze_errors))

    manifest_path = _pilot_manifest_path(root)
    pilot_dir = _pilot_dir(root)
    output_paths = [_pilot_output_path("case-01", group, root=root) for group in GENERATED_GROUPS]
    if manifest_path.exists() and _load_jsonl(manifest_path):
        raise ExperimentError("Pilot manifest already contains rows; retries and replacement are forbidden.")
    existing_outputs = [path for path in output_paths if path.exists()]
    if existing_outputs:
        raise ExperimentError(f"Pilot output already exists; refusing overwrite: {existing_outputs[0]}")
    pilot_prompt_dir = pilot_dir / "prompts"
    pilot_context_dir = pilot_dir / "contexts"
    if pilot_prompt_dir.exists() and any(pilot_prompt_dir.iterdir()):
        raise ExperimentError("Pilot prompt artifacts already exist; retries and replacement are forbidden.")
    if pilot_context_dir.exists() and any(pilot_context_dir.iterdir()):
        raise ExperimentError("Pilot context artifacts already exist; retries and replacement are forbidden.")
    pilot_prompt_dir.mkdir(parents=True, exist_ok=True)
    pilot_context_dir.mkdir(parents=True, exist_ok=True)

    case = _case_by_id(preflight["cases_document"])["case-01"]
    pair = plans["case-01"]
    if pair.get("selector_parity") is not True:
        raise ExperimentError("Pilot A/B/C selector parity failed.")
    parity_errors = _selection_parity_errors(pair.get("selector_snapshots") or {})
    if parity_errors:
        raise ExperimentError("Pilot selector parity failed: " + "; ".join(parity_errors))
    if pair["plans"]["C"]["prompt"] != f"{pair['plans']['B']['prompt']}\n\n{pair['hygiene_block']}":
        raise ExperimentError("Pilot B/C parity failed; Hygiene must be the sole prompt difference.")
    if (
        pair["plans"]["B"].get("style_context_hash")
        != pair["plans"]["C"].get("style_context_hash")
        or pair["plans"]["B"].get("style_context_hash") != sha256_json(pair["style_context"])
    ):
        raise ExperimentError("Pilot B/C Style Context hashes differ from the shared frozen Context.")
    scene = compose_scene_prompt(case)
    if any(scene not in pair["plans"][group]["prompt"] for group in GENERATED_GROUPS):
        raise ExperimentError("Pilot A/B/C scene parity failed.")
    for left, right in (("A", "B"), ("B", "C")):
        if pair["plans"][left]["selected_reference_ids"] != pair["plans"][right]["selected_reference_ids"]:
            raise ExperimentError(f"Pilot {left}/{right} selected reference IDs differ.")
        if pair["plans"][left]["referenced_image_paths"] != pair["plans"][right]["referenced_image_paths"]:
            raise ExperimentError(f"Pilot {left}/{right} referenced image paths differ.")
    if _load_json(_context_dir("case-01", root=root) / "resolved-style-context.json") != pair["style_context"]:
        raise ExperimentError("Pilot context differs from the frozen production context.")

    context_path = pilot_context_dir / "case-01.json"
    _write_frozen_json(context_path, pair["style_context"])
    context_hash = sha256_file(context_path)
    base_scene_path = pilot_prompt_dir / "case-01-base-scene.txt"
    _write_frozen_text(base_scene_path, scene)
    policy_hash = sha256_file(root / "runtime" / "style-policy.yaml")
    production_revision = _git_output(root, "rev-parse", "HEAD")
    corrected_legacy = preflight.get("corrected_legacy") or _control_runtime_metadata(root)
    counts = {"succeeded": 0, "failed": 0}
    if codex_managed:
        counts["queued"] = 0
    adapter = ArcoRealAdapter(provider) if provider is not None else None

    for group in GENERATED_GROUPS:
        plan = pair["plans"][group]
        references = pair["references_by_group"][group]
        metadata = _identity_and_external_metadata(references)
        prompt_path = pilot_prompt_dir / f"case-01-{group}.txt"
        _write_frozen_text(prompt_path, str(plan["prompt"]))
        prompt_hash = sha256_file(prompt_path)
        output_path = _pilot_output_path("case-01", group, root=root)
        sample_key = f"pilot:case-01:{group}:r1"
        is_corrected_legacy = group == "A"
        selector_snapshot_path = _selection_path("case-01", root=root)
        record: dict[str, Any] = {
            "sample_key": sample_key,
            "experiment_id": "arco-style-transfer-v1-batch-4b.3t",
            "batch": "4B.3-T",
            "pilot": True,
            "formal": False,
            "include_in_formal_analysis": False,
            "selector_parity": True,
            "scene_parity": True,
            "bc_context_parity": True,
            "bc_prompt_hygiene_only": True,
            "provider_payload_keys": ["prompt", "referenced_image_paths"],
            "case_id": "case-01",
            "group": group,
            "replicate": 1,
            "runtime_type": "corrected_legacy" if is_corrected_legacy else "production",
            "runtime_commit": corrected_legacy["selector_patch_revision"] if is_corrected_legacy else production_revision,
            "runtime_sha256": corrected_legacy["runtime_sha256"] if is_corrected_legacy else sha256_file(root / "scripts" / "reference_runtime.py"),
            "selector_revision": corrected_legacy["selector_patch_revision"] if is_corrected_legacy else production_revision,
            "identity_variant": case["identity_variant"],
            "state": case["state"],
            "exposure_profile": case["exposure_profile"],
            "image_transport_strategy": "referenced_image_paths",
            **metadata,
            "selected_reference_ids": list(plan["selected_reference_ids"]),
            "selected_reference_hashes": [_reference_hash(reference) for reference in references],
            "reference_snapshot_path": _relative_path(selector_snapshot_path, root=root),
            "reference_snapshot_sha256": sha256_file(selector_snapshot_path),
            "reference_roles": [reference.get("role") for reference in references],
            "reference_duties": [list(reference.get("duties") or reference.get("inherit") or []) for reference in references],
            "style_reference": {
                "reference_id": case["external_reference"]["reference_id"],
                "role": case["external_reference"]["role"],
                "duties": list(case["external_reference"]["duties"]),
                "style_axes": list(case["expected_relevant_style_axes"]),
                "style_priority": case["external_reference"]["style_priority"],
                "provenance": case["external_reference"]["provenance"],
                "sha256": case["external_reference"]["sha256"],
            },
            "resolved_style_context_path": _relative_path(context_path, root=root) if group in ("B", "C") else None,
            "resolved_style_context_sha256": context_hash if group in ("B", "C") else None,
            "style_context_hash": plan.get("style_context_hash"),
            "base_scene_prompt_path": _relative_path(base_scene_path, root=root),
            "base_scene_prompt_sha256": sha256_file(base_scene_path),
            "compiled_prompt_path": _relative_path(prompt_path, root=root),
            "compiled_prompt_sha256": prompt_hash,
            "hygiene_enabled": group == "C",
            "style_policy_sha256": policy_hash if group == "C" else None,
            "output_path": _relative_path(output_path, root=root),
            "status": "started",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        if codex_managed:
            if list(plan["selected_reference_ids"]) != [str(reference.get("reference_id")) for reference in references]:
                raise ExperimentError(f"Pilot {group} reference ID order differs from the selected references.")
            task_path = pilot_dir / "tasks" / f"case-01-{group}-r1.json"
            reference_hashes = [
                {
                    "reference_id": str(reference.get("reference_id")),
                    "path": str(reference["path"]),
                    "sha256": _reference_hash(reference),
                }
                for reference in references
            ]
            frozen_files: dict[str, str] = {}
            frozen_file_candidates = [
                prompt_path,
                selector_snapshot_path,
                root / "evaluation" / "style-regression" / "cases.yaml",
                _input_freeze_path(root),
                root / "scripts" / "reference_runtime.py",
                root / "scripts" / "arco_real_adapter.py",
                root / "runtime" / "generation.yaml",
                root / "runtime" / "style-policy.yaml",
                root / "character" / "assets.yaml",
                root / "character" / "style-baseline.yaml",
                _evaluation_path(case["external_reference"]["style_brief_path"], root=root),
            ]
            if group in ("B", "C"):
                frozen_file_candidates.append(context_path)
            for reference in references:
                frozen_file_candidates.append(Path(reference["path"]))
            for frozen_path in frozen_file_candidates:
                resolved = frozen_path.resolve()
                try:
                    relative_frozen_path = resolved.relative_to(root.resolve()).as_posix()
                except ValueError as exc:
                    raise ExperimentError(f"Pilot frozen input escapes the repository: {frozen_path}") from exc
                if not resolved.is_file():
                    raise ExperimentError(f"Pilot frozen input is missing: {relative_frozen_path}")
                frozen_files[relative_frozen_path] = sha256_file(resolved)
            frozen_hashes = {
                "compiled_prompt_file_sha256": prompt_hash,
                "compiled_prompt_text_sha256": hashlib.sha256(str(plan["prompt"]).encode("utf-8")).hexdigest(),
                "references": reference_hashes,
                "reference_snapshot_sha256": sha256_file(selector_snapshot_path),
                "resolved_style_context_sha256": context_hash if group in ("B", "C") else None,
                "runtime_sha256": (
                    corrected_legacy["runtime_sha256"]
                    if group == "A"
                    else sha256_file(root / "scripts" / "reference_runtime.py")
                ),
                "generation_config_sha256": sha256_file(root / "runtime" / "generation.yaml"),
                "style_policy_sha256": policy_hash,
                "files": frozen_files,
            }
            task = build_codex_task(
                task_id=f"pilot:case-01:{group}:r1",
                task_kind="pilot",
                case_id="case-01",
                group=group,
                replicate=1,
                prompt=str(plan["prompt"]),
                referenced_image_paths=list(plan["referenced_image_paths"]),
                reference_ids=list(plan["selected_reference_ids"]),
                expected_output_path=_relative_path(output_path, root=root),
                frozen_input_hashes=frozen_hashes,
                batch="4B.3-T",
            )
            write_codex_task(task, path=task_path)
            record.update(
                {
                    "status": "queued",
                    "batch": "4B.3-T",
                    "execution_mode": "codex-managed",
                    "engine": "Codex-managed",
                    "task_path": _relative_path(task_path, root=root),
                    "task_sha256": task["task_sha256"],
                    "prompt_sha256_exact": task["prompt_sha256"],
                    "reference_ids_ordered": list(task["reference_ids"]),
                    "reference_paths_ordered": list(task["referenced_image_paths"]),
                }
            )
            _upsert_manifest(record, path=manifest_path)
            counts["queued"] += 1
            continue
        _upsert_manifest(record, path=manifest_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            assert adapter is not None
            provider_path = adapter.generate(
                invocation_plan=plan,
                reference_contracts=references,
                reference_image_paths=plan["referenced_image_paths"],
            )
            if provider_path.resolve() != output_path.resolve():
                shutil.copy2(provider_path, output_path)
            record.update(
                {
                    "status": "succeeded",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "output_sha256": sha256_file(output_path),
                }
            )
            counts["succeeded"] += 1
        except Exception as exc:  # Every pilot failure is retained and never retried.
            record.update(
                {
                    "status": "failed",
                    "generation_failed_at": datetime.now(timezone.utc).isoformat(),
                    "failure_code": getattr(exc, "code", type(exc).__name__),
                }
            )
            counts["failed"] += 1
        _upsert_manifest(record, path=manifest_path)
    return counts


def _codex_pilot_manifest_record(
    task: Mapping[str, Any], task_path: Path, *, root: Path
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    if task.get("task_kind") != "pilot" or task.get("batch") != "4B.3-T":
        raise ExperimentError("Codex Pilot result must reference a Batch 4B.3-T Pilot task.")
    if task.get("case_id") != "case-01" or task.get("group") not in GENERATED_GROUPS or task.get("replicate") != 1:
        raise ExperimentError("Codex Pilot task identifiers are outside the isolated Case 01 A/B/C Pilot.")
    manifest_path = _pilot_manifest_path(root)
    rows = _load_jsonl(manifest_path)
    matches = [row for row in rows if row.get("task_sha256") == task.get("task_sha256")]
    if len(matches) != 1:
        raise ExperimentError("Codex Pilot task does not match exactly one Pilot manifest row.")
    record = dict(matches[0])
    if record.get("execution_mode") != "codex-managed" or record.get("task_path") != _relative_path(task_path, root=root):
        raise ExperimentError("Codex Pilot task metadata differs from its Pilot manifest row.")
    if record.get("status") != "queued":
        raise ExperimentError(f"Codex Pilot task already has status {record.get('status')}; retries are forbidden.")
    return manifest_path, record, rows


def _record_codex_pilot_failure(
    task: Mapping[str, Any], task_path: Path, *, failure_code: str, failure_message: str, root: Path
) -> dict[str, Any]:
    manifest_path, record, _ = _codex_pilot_manifest_record(task, task_path, root=root)
    record.update(
        {
            "status": "failed",
            "execution_failed_at": datetime.now(timezone.utc).isoformat(),
            "failure_code": failure_code,
            "failure_message": failure_message,
        }
    )
    _upsert_manifest(record, path=manifest_path)
    return record


def record_codex_pilot_failure(
    task_path: Path, *, failure_code: str, failure_message: str = "Codex image generation failed.", root: Path = ROOT
) -> dict[str, Any]:
    task = load_codex_task(task_path, root=root)
    if task.get("schema_version") != CODEX_TASK_SCHEMA_VERSION:
        raise ExperimentError("Codex Pilot acceptance requires UTF-8-safe schema version 2.")
    return _record_codex_pilot_failure(
        task,
        task_path,
        failure_code=failure_code,
        failure_message=failure_message,
        root=root,
    )


def accept_codex_pilot_output(
    task_path: Path, generated_path: Path | str, *, root: Path = ROOT
) -> dict[str, Any]:
    task = load_codex_task(task_path, root=root)
    manifest_path, record, _ = _codex_pilot_manifest_record(task, task_path, root=root)
    try:
        output = accept_codex_task_output(task_path, generated_path, root=root)
    except Exception as exc:
        _record_codex_pilot_failure(
            task,
            task_path,
            failure_code=getattr(exc, "code", type(exc).__name__),
            failure_message=str(exc),
            root=root,
        )
        raise
    record.update(
        {
            "status": "succeeded",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "output_sha256": output["output_sha256"],
            "output_size_bytes": output["size_bytes"],
            "codex_generated_source_path": str(output["source_path"]),
            "codex_source_sha256": output["source_sha256"],
            "receipt_path": output["receipt_path"],
            "receipt_sha256": output["receipt_sha256"],
        }
    )
    _upsert_manifest(record, path=manifest_path)
    return record


def _formal_checkpoint_next_pending_sample(rows: Sequence[Mapping[str, Any]]) -> str:
    indexed = _manifest_index(rows)
    for sample in _formal_sample_plan():
        sample_key = str(sample["sample_key"])
        row = indexed.get(sample_key)
        if row is not None and row.get("status") == "succeeded":
            continue
        attempt = len(row.get("attempts", [])) + 1 if row is not None else 1
        return f"{sample_key} attempt {attempt}"
    return "complete"


def _formal_continuation_checkpoint(
    root: Path = ROOT,
    *,
    legacy_runner_hash_allowlist: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Snapshot the immutable one-of-36 checkpoint without touching any sample."""
    manifest_path = _formal_manifest_path(root)
    rows = _load_jsonl(manifest_path)
    if [row.get("sample_key") for row in rows] != ["case-01:A:r1", "case-01:B:r1"]:
        raise ExperimentError("The formal continuation checkpoint must preserve the existing A-r1/B-r1 manifest prefix.")
    indexed = _manifest_index(rows)
    if any(indexed[sample_key].get("status") != "succeeded" for sample_key in indexed):
        raise ExperimentError("The r4 checkpoint may advance only from the receipt-validated A-r1/B-r1 2/36 state.")

    formal_files: dict[str, str] = {}
    source_files: dict[str, str] = {}
    for sample_key in ("case-01:A:r1", "case-01:B:r1"):
        row = indexed[sample_key]
        for attempt in row.get("attempts") or []:
            task_path = _repo_path(str(attempt.get("task_path", "")), root=root)
            if not task_path.is_file():
                raise ExperimentError(f"Checkpoint task is missing: {_relative_path(task_path, root=root)}")
            formal_files[_relative_path(task_path, root=root)] = sha256_file(task_path)
            if attempt.get("status") == "succeeded":
                for field in ("receipt_path",):
                    receipt_path = _repo_path(str(attempt.get(field, "")), root=root)
                    if not receipt_path.is_file():
                        raise ExperimentError(f"Checkpoint receipt is missing: {_relative_path(receipt_path, root=root)}")
                    formal_files[_relative_path(receipt_path, root=root)] = sha256_file(receipt_path)
                output_path = _repo_path(str(row.get("output_path", "")), root=root)
                if not output_path.is_file():
                    raise ExperimentError(f"Checkpoint accepted output is missing: {_relative_path(output_path, root=root)}")
                formal_files[_relative_path(output_path, root=root)] = sha256_file(output_path)
                source_path = Path(str(attempt.get("codex_generated_source_path", ""))).expanduser().resolve(strict=False)
                if not source_path.is_file():
                    raise ExperimentError("Checkpoint Codex-generated source image is missing.")
                source_files[str(source_path)] = sha256_file(source_path)
            elif attempt.get("status") == "invalidated":
                task = load_codex_task(task_path, root=root, verify_frozen_inputs=False)
                invalidated_output = _repo_path(str(task.get("expected_output_path", "")), root=root)
                if not invalidated_output.is_file():
                    raise ExperimentError("Checkpoint invalidated audit PNG is missing.")
                formal_files[_relative_path(invalidated_output, root=root)] = sha256_file(invalidated_output)

    counts = _compliant_formal_sample_counts(
        rows,
        root=root,
        legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
    )
    if counts != {"A": 1, "B": 1, "C": 0}:
        raise ExperimentError("The r4 continuation checkpoint must contain exactly A=1, B=1, C=0 compliant samples.")
    return {
        "schema_version": 1,
        "manifest_path": _relative_path(manifest_path, root=root),
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_rows": copy.deepcopy(rows),
        "manifest_rows_sha256": sha256_json(rows),
        "manifest_row_sha256": {str(row["sample_key"]): sha256_json(row) for row in rows},
        "attempt_prefix_sha256": {
            str(row["sample_key"]): [sha256_json(attempt) for attempt in row.get("attempts") or []]
            for row in rows
        },
        "formal_file_sha256": formal_files,
        "external_source_file_sha256": source_files,
        "formal_sample_counts": counts,
        "formal_sample_total": sum(counts.values()),
        "next_pending_sample": _formal_checkpoint_next_pending_sample(rows),
    }


def _formal_continuation_legacy_runner_allowlist(
    root: Path,
    parent_capture: Mapping[str, Any],
    parent_capture_sha256: str,
    checkpoint: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    """Carry the r3 A-r1 exception and add only the task completed since that capture."""
    parent_hashes = parent_capture.get("hashes")
    if not isinstance(parent_hashes, Mapping):
        raise ExperimentError("The parent r3 capture has no immutable hash set.")
    parent_runner_hash = parent_hashes.get("scripts/run_style_regression.py")
    current_runner_hash = sha256_file(root / "scripts" / "run_style_regression.py")
    checkpoint_files = checkpoint.get("formal_file_sha256")
    if not isinstance(checkpoint_files, Mapping):
        raise ExperimentError("The r4 checkpoint does not pin its formal task files.")

    r2_link = parent_capture.get("parent_capture")
    r2_relative = f"evaluation/style-regression/environment/{R_R2_PARENT_FINAL_PREFLIGHT_ENVIRONMENT_PATH}"
    if not isinstance(r2_link, Mapping) or r2_link.get("path") != r2_relative:
        raise ExperimentError("The r3 parent capture is not linked to the immutable r2 capture.")
    r2_path = _repo_path(r2_relative, root=root)
    if not r2_path.is_file() or r2_link.get("sha256") != sha256_file(r2_path):
        raise ExperimentError("The immutable r2 ancestor of the r3 capture is missing or changed.")
    r2_capture = _load_json(r2_path)
    r2_hashes = r2_capture.get("hashes")
    if not isinstance(r2_hashes, Mapping):
        raise ExperimentError("The immutable r2 ancestor has no runner hash.")

    prior_entries = parent_capture.get("legacy_task_compatibility")
    if not isinstance(prior_entries, list) or len(prior_entries) != 1:
        raise ExperimentError("The r3 parent compatibility list is not the exact single-task A-r1 exception.")
    allowlist: dict[str, dict[str, str]] = {}
    expected_prior_path = _relative_path(_formal_task_path("case-01", "A", 1, 2, root=root), root=root)
    for raw_entry in prior_entries:
        if not isinstance(raw_entry, Mapping) or set(raw_entry) != {
            "task_path", "task_sha256", "task_file_sha256", "task_kind", "runner_sha256"
        }:
            raise ExperimentError("The r3 parent compatibility entry has an invalid schema.")
        entry = {str(key): str(value) for key, value in raw_entry.items()}
        task_path = _repo_path(entry["task_path"], root=root)
        task = load_codex_task(task_path, root=root, verify_frozen_inputs=False, require_utf8_schema=True)
        task_files = (task.get("frozen_input_hashes") or {}).get("files", {})
        if (
            entry["task_path"] != expected_prior_path
            or entry["task_sha256"] != task.get("task_sha256")
            or entry["task_file_sha256"] != sha256_file(task_path)
            or checkpoint_files.get(entry["task_path"]) != entry["task_file_sha256"]
            or entry["task_kind"] != "formal"
            or task.get("task_id") != "formal:case-01:A:r1:attempt-2"
            or task_files.get("scripts/run_style_regression.py") != entry["runner_sha256"]
            or task_files.get(r2_relative) != r2_link["sha256"]
            or entry["runner_sha256"] != r2_hashes.get("scripts/run_style_regression.py")
        ):
            raise ExperimentError("The r3 A-r1 compatibility entry no longer matches its immutable task and r2 parent.")
        allowlist[entry["task_sha256"]] = entry

    parent_relative = f"evaluation/style-regression/environment/{R_PARENT_FINAL_PREFLIGHT_ENVIRONMENT_PATH}"
    discovered_legacy_tasks: set[str] = set()
    for relative_path in sorted(path for path in checkpoint_files if "/tasks/" in str(path)):
        task_path = _repo_path(str(relative_path), root=root)
        task = load_codex_task(task_path, root=root, verify_frozen_inputs=False)
        if task.get("schema_version") != CODEX_TASK_SCHEMA_VERSION:
            continue
        task_files = (task.get("frozen_input_hashes") or {}).get("files", {})
        task_runner_hash = task_files.get("scripts/run_style_regression.py")
        if task_runner_hash == current_runner_hash:
            continue
        task_sha256 = str(task.get("task_sha256"))
        discovered_legacy_tasks.add(task_sha256)
        if task_sha256 in allowlist:
            continue
        if (
            relative_path != _relative_path(_formal_task_path("case-01", "B", 1, 2, root=root), root=root)
            or task.get("task_id") != "formal:case-01:B:r1:attempt-2"
            or task.get("task_kind") != "formal"
            or task_runner_hash != parent_runner_hash
            or task_files.get(parent_relative) != parent_capture_sha256
        ):
            raise ExperimentError(f"Unapproved legacy runner task in the r4 checkpoint: {relative_path}.")
        entry = {
            "task_path": str(relative_path),
            "task_sha256": task_sha256,
            "task_file_sha256": sha256_file(task_path),
            "task_kind": "formal",
            "runner_sha256": str(task_runner_hash),
        }
        if checkpoint_files.get(str(relative_path)) != entry["task_file_sha256"]:
            raise ExperimentError("The r4 checkpoint does not pin the exact B-r1 attempt-2 task file.")
        allowlist[task_sha256] = entry

    if discovered_legacy_tasks != set(allowlist):
        raise ExperimentError("The r4 legacy task compatibility list does not exactly cover its old-runner checkpoint tasks.")
    return allowlist


def _validate_formal_continuation_checkpoint(
    capture: Mapping[str, Any], root: Path, legacy_runner_hash_allowlist: Mapping[str, Mapping[str, str]]
) -> None:
    checkpoint = capture.get("formal_continuation_checkpoint")
    if not isinstance(checkpoint, Mapping) or checkpoint.get("schema_version") != 1:
        raise ExperimentError("The r4 capture is missing its immutable 2/36 continuation checkpoint.")
    manifest_path = _formal_manifest_path(root)
    if checkpoint.get("manifest_path") != _relative_path(manifest_path, root=root):
        raise ExperimentError("The r4 checkpoint names a different formal manifest.")
    baseline_rows = checkpoint.get("manifest_rows")
    if not isinstance(baseline_rows, list) or checkpoint.get("manifest_rows_sha256") != sha256_json(baseline_rows):
        raise ExperimentError("The r4 checkpoint baseline manifest snapshot is invalid.")
    if [row.get("sample_key") for row in baseline_rows] != ["case-01:A:r1", "case-01:B:r1"]:
        raise ExperimentError("The r4 checkpoint baseline rows are not the exact A-r1/B-r1 prefix.")
    if any(row.get("status") != "succeeded" for row in baseline_rows):
        raise ExperimentError("The r4 checkpoint baseline rows are not both receipt-validated successes.")
    baseline_counts = checkpoint.get("formal_sample_counts")
    if (
        baseline_counts != {"A": 1, "B": 1, "C": 0}
        or checkpoint.get("formal_sample_total") != 2
        or checkpoint.get("next_pending_sample") != "case-01:C:r1 attempt 1"
    ):
        raise ExperimentError("The r4 checkpoint baseline or resume position is invalid.")
    baseline_row_counts = _compliant_formal_sample_counts(
        baseline_rows,
        root=root,
        legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
    )
    if baseline_row_counts != baseline_counts or _formal_checkpoint_next_pending_sample(baseline_rows) != checkpoint.get("next_pending_sample"):
        raise ExperimentError("The r4 checkpoint counts or first pending sample do not match its baseline manifest.")
    formal_baseline = capture.get("formal_baseline")
    if not isinstance(formal_baseline, Mapping) or (
        formal_baseline.get("compliant_counts") != baseline_counts
        or formal_baseline.get("compliant_total") != 2
        or formal_baseline.get("next_pending_sample") != checkpoint.get("next_pending_sample")
    ):
        raise ExperimentError("The r4 capture summary differs from its immutable manifest checkpoint.")
    current_rows = _load_jsonl(manifest_path)
    current_index = _manifest_index(current_rows)
    expected_row_hashes = checkpoint.get("manifest_row_sha256")
    expected_attempt_hashes = checkpoint.get("attempt_prefix_sha256")
    if not isinstance(expected_row_hashes, Mapping) or not isinstance(expected_attempt_hashes, Mapping):
        raise ExperimentError("The r4 checkpoint manifest and attempt-history pins are invalid.")
    for baseline_row in baseline_rows:
        sample_key = str(baseline_row.get("sample_key"))
        current_row = current_index.get(sample_key)
        if current_row is None:
            raise ExperimentError(f"The r4 checkpoint sample was removed: {sample_key}.")
        if expected_row_hashes.get(sample_key) != sha256_json(baseline_row) or sha256_json(current_row) != expected_row_hashes.get(sample_key):
            raise ExperimentError(f"The accepted {sample_key} checkpoint manifest row was edited.")
        baseline_attempt_hashes = expected_attempt_hashes.get(sample_key)
        attempts = current_row.get("attempts")
        if (
            not isinstance(baseline_attempt_hashes, list)
            or not isinstance(attempts, list)
            or len(attempts) < len(baseline_attempt_hashes)
            or [sha256_json(attempt) for attempt in attempts[: len(baseline_attempt_hashes)]] != baseline_attempt_hashes
        ):
            raise ExperimentError(f"The r4 checkpoint immutable attempt-history prefix changed for {sample_key}.")
    checkpoint_files = checkpoint.get("formal_file_sha256")
    if not isinstance(checkpoint_files, Mapping):
        raise ExperimentError("The r4 checkpoint task, receipt, or output file pins are invalid.")
    for relative_path, expected_hash in checkpoint_files.items():
        path = _repo_path(str(relative_path), root=root)
        if not path.is_file() or not isinstance(expected_hash, str) or sha256_file(path) != expected_hash:
            raise ExperimentError(f"The r4 checkpoint formal file is missing or changed: {relative_path}.")
    source_files = checkpoint.get("external_source_file_sha256")
    if not isinstance(source_files, Mapping):
        raise ExperimentError("The r4 checkpoint generated-source file pins are invalid.")
    for raw_path, expected_hash in source_files.items():
        source_path = Path(str(raw_path)).expanduser().resolve(strict=False)
        if not source_path.is_file() or not isinstance(expected_hash, str) or sha256_file(source_path) != expected_hash:
            raise ExperimentError("The r4 checkpoint Codex-generated source image is missing or changed.")
    if legacy_runner_hash_allowlist != _formal_continuation_legacy_runner_allowlist(
        root,
        _load_json(root / "evaluation" / "style-regression" / "environment" / R_PARENT_FINAL_PREFLIGHT_ENVIRONMENT_PATH),
        str((capture.get("parent_capture") or {}).get("sha256", "")),
        checkpoint,
    ):
        raise ExperimentError("The r3 legacy runner compatibility list is not the exact A-r1 checkpoint task.")


def _validate_r4_formal_capture(root: Path = ROOT) -> dict[str, Any]:
    """Require the current 4B.3-T continuation capture and recheck live readiness gates."""
    capture_path = root / "evaluation" / "style-regression" / "environment" / R_FINAL_PREFLIGHT_ENVIRONMENT_PATH
    if not capture_path.is_file():
        raise ExperimentError("Formal Codex task export requires the new Batch 4B.3-T final preflight capture.")
    capture = _load_json(capture_path)
    if capture.get("record_kind") != "batch-4b3t-final-preflight-capture":
        raise ExperimentError("The current final capture is not a Batch 4B.3-T Codex-managed capture.")
    if capture.get("execution_mode") != "codex-managed" or capture.get("engine") != "Codex-managed":
        raise ExperimentError("Formal Codex task export requires a Codex-managed final capture.")
    if capture.get("hard_preflight_ready") is not True or capture.get("experiment_ready") is not True:
        raise ExperimentError("Formal Codex task export requires READY hard preflight and passing A/B/C Pilot gates.")
    if capture.get("inputs_frozen") is not True or not capture.get("input_freeze_sha256"):
        raise ExperimentError("Formal Codex task export requires valid frozen inputs.")
    if capture.get("blocking_inputs") != []:
        raise ExperimentError("The Batch 4B.3-T capture contains blocking inputs.")
    parent = capture.get("parent_capture")
    parent_relative = f"evaluation/style-regression/environment/{R_PARENT_FINAL_PREFLIGHT_ENVIRONMENT_PATH}"
    if not isinstance(parent, Mapping) or parent.get("path") != parent_relative:
        raise ExperimentError("The r4 continuation capture is not linked to the immutable r3 parent capture.")
    parent_path = _repo_path(parent_relative, root=root)
    if not parent_path.is_file() or parent.get("sha256") != sha256_file(parent_path):
        raise ExperimentError("The immutable r3 parent capture is missing or changed.")
    parent_capture = _load_json(parent_path)
    if (
        parent_capture.get("record_kind") != "batch-4b3t-final-preflight-capture"
        or parent_capture.get("hard_preflight_ready") is not True
        or parent_capture.get("experiment_ready") is not True
    ):
        raise ExperimentError("The r3 parent is not the captured READY one-of-36 continuation state.")
    parent_baseline = parent_capture.get("formal_baseline")
    if not isinstance(parent_baseline, Mapping) or (
        parent_baseline.get("compliant_counts") != {"A": 1, "B": 0, "C": 0}
        or parent_baseline.get("compliant_total") != 1
        or parent_baseline.get("next_pending_sample") != "case-01:B:r1 attempt 2"
    ):
        raise ExperimentError("The r3 parent does not preserve the verified one-of-36 checkpoint.")
    cases_document = _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")
    captured_hashes = capture.get("hashes")
    if not isinstance(captured_hashes, Mapping):
        raise ExperimentError("The Batch 4B.3-T capture is missing its immutable hash set.")
    current_hashes = _runtime_hashes(root, cases_document)
    if captured_hashes != current_hashes:
        changed = sorted(key for key in set(captured_hashes) | set(current_hashes) if captured_hashes.get(key) != current_hashes.get(key))
        raise ExperimentError("The Batch 4B.3-T capture is stale; captured inputs changed: " + ", ".join(changed[:8]))
    parent_hashes = parent_capture.get("hashes")
    if not isinstance(parent_hashes, Mapping) or set(parent_hashes) != set(current_hashes):
        raise ExperimentError("The r3 parent and r4 continuation do not cover the same frozen runtime inputs.")
    permitted_hash_deltas = {"scripts/run_style_regression.py", "scripts/test_files_tree"}
    parent_deltas = {
        key for key in set(parent_hashes) | set(current_hashes)
        if parent_hashes.get(key) != current_hashes.get(key)
    }
    if parent_deltas != permitted_hash_deltas:
        raise ExperimentError(
            "The r4 continuation changed frozen inputs outside the runner and its test tree: "
            + ", ".join(sorted(parent_deltas - permitted_hash_deltas))
        )
    compatibility_entries = capture.get("legacy_task_compatibility")
    if not isinstance(compatibility_entries, list):
        raise ExperimentError("The r4 continuation is missing its bounded legacy task compatibility list.")
    compatibility_map: dict[str, dict[str, str]] = {}
    for entry in compatibility_entries:
        if not isinstance(entry, Mapping) or set(entry) != {
            "task_path", "task_sha256", "task_file_sha256", "task_kind", "runner_sha256"
        }:
            raise ExperimentError("The r4 legacy task compatibility entry has an invalid schema.")
        task_sha256 = entry.get("task_sha256")
        if not isinstance(task_sha256, str) or task_sha256 in compatibility_map:
            raise ExperimentError("The r4 legacy task compatibility list has an invalid or duplicate task hash.")
        compatibility_map[task_sha256] = {str(key): str(value) for key, value in entry.items()}
    _validate_formal_continuation_checkpoint(capture, root, compatibility_map)
    formal_baseline = capture.get("formal_baseline")
    if not isinstance(formal_baseline, Mapping) or (
        formal_baseline.get("compliant_counts") != {"A": 1, "B": 1, "C": 0}
        or formal_baseline.get("compliant_total") != 2
        or formal_baseline.get("next_pending_sample") != "case-01:C:r1 attempt 1"
    ):
        raise ExperimentError("The r4 capture does not report the preserved 2/36 resume checkpoint.")
    preflight_capture = capture.get("preflight_report")
    if not isinstance(preflight_capture, Mapping):
        raise ExperimentError("The Batch 4B.3-T capture is missing its preflight report hash.")
    preflight_path = root / "evaluation" / "style-regression" / R_PREFLIGHT_JSON_PATH
    if (
        not preflight_path.is_file()
        or preflight_capture.get("path") != f"evaluation/style-regression/{R_PREFLIGHT_JSON_PATH}"
        or preflight_capture.get("sha256") != sha256_file(preflight_path)
    ):
        raise ExperimentError("The captured Batch 4B.3-T preflight report is missing or has changed.")
    captured_report = _load_json(preflight_path)
    if (
        captured_report.get("status") != "READY"
        or captured_report.get("formal_sample_counts") != {"A": 1, "B": 1, "C": 0}
        or captured_report.get("formal_sample_total") != 2
    ):
        raise ExperimentError("The saved r4 final preflight must be READY with the exact 2/36 checkpoint.")
    completion = capture.get("completion_report")
    if not isinstance(completion, Mapping):
        raise ExperimentError("The Batch 4B.3-T capture is missing its readiness completion report.")
    completion_path = _repo_path(str(completion.get("path", "")), root=root)
    if not completion_path.is_file() or completion.get("sha256") != sha256_file(completion_path):
        raise ExperimentError("The captured Batch 4B.3-T completion report is missing or has changed.")
    if _validate_codex_smoke(root):
        raise ExperimentError("Formal Codex task export requires the existing passing reference-free Smoke.")
    preflight = collect_preflight(
        root,
        hard=True,
        codex_managed=True,
        allow_formal_progress=True,
        legacy_runner_hash_allowlist=compatibility_map,
    )
    if preflight.get("global_status") != "READY" or preflight.get("errors"):
        raise ExperimentError("Current hard preflight is not READY:\n- " + "\n- ".join(preflight.get("errors") or []))
    if any(preflight.get("case_statuses", {}).get(case_id, {}).get("status") != "READY" for case_id in CASE_IDS):
        raise ExperimentError("Formal Codex task export requires all four current Preflight cases READY.")
    if preflight.get("provider_binding", {}).get("smoke_status") != "PASS":
        raise ExperimentError("Formal Codex task export requires a passing Codex-managed Smoke.")
    current_counts = preflight.get("formal_sample_counts") or {}
    if any(current_counts.get(group, 0) < formal_baseline["compliant_counts"][group] for group in GENERATED_GROUPS):
        raise ExperimentError("Current formal state regressed below the immutable 2/36 continuation checkpoint.")
    _validate_formal_state(preflight, root=root)
    return preflight


def create_formal_continuation_capture(root: Path = ROOT) -> dict[str, Any]:
    """Create one immutable r4 continuation capture for the validated 2/36 checkpoint."""
    capture_path = root / "evaluation" / "style-regression" / "environment" / R_FINAL_PREFLIGHT_ENVIRONMENT_PATH
    parent_path = root / "evaluation" / "style-regression" / "environment" / R_PARENT_FINAL_PREFLIGHT_ENVIRONMENT_PATH
    if capture_path.exists():
        raise ExperimentError("The r4 formal continuation capture already exists; captured history is write-once.")
    if not parent_path.is_file():
        raise ExperimentError("The immutable r3 parent capture is missing.")
    parent_capture = _load_json(parent_path)
    parent_sha256 = sha256_file(parent_path)
    cases_document = _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")
    current_hashes = _runtime_hashes(root, cases_document)
    parent_hashes = parent_capture.get("hashes")
    if not isinstance(parent_hashes, Mapping) or set(parent_hashes) != set(current_hashes):
        raise ExperimentError("The r3 parent and r4 continuation do not cover the same frozen runtime inputs.")
    permitted_hash_deltas = {"scripts/run_style_regression.py", "scripts/test_files_tree"}
    parent_deltas = {
        key for key in set(parent_hashes) | set(current_hashes)
        if parent_hashes.get(key) != current_hashes.get(key)
    }
    if parent_deltas != permitted_hash_deltas:
        raise ExperimentError(
            "The r4 continuation may change only the runner and its test tree; detected: "
            + ", ".join(sorted(parent_deltas))
        )

    a2_task_path = _formal_task_path("case-01", "A", 1, 2, root=root)
    a2_relative = _relative_path(a2_task_path, root=root)
    b2_task_path = _formal_task_path("case-01", "B", 1, 2, root=root)
    b2_relative = _relative_path(b2_task_path, root=root)
    provisional_checkpoint = {
        "formal_file_sha256": {
            a2_relative: sha256_file(a2_task_path),
            b2_relative: sha256_file(b2_task_path),
        }
    }
    legacy_allowlist = _formal_continuation_legacy_runner_allowlist(
        root, parent_capture, parent_sha256, provisional_checkpoint
    )
    checkpoint = _formal_continuation_checkpoint(root, legacy_runner_hash_allowlist=legacy_allowlist)
    legacy_allowlist = _formal_continuation_legacy_runner_allowlist(root, parent_capture, parent_sha256, checkpoint)

    utf8_environment = os.environ.copy()
    utf8_environment["PYTHONUTF8"] = "1"
    utf8_environment["PYTHONIOENCODING"] = "utf-8"
    test_command = [sys.executable, "-m", "unittest", "discover", "-s", "scripts", "-p", "test_*.py"]
    test_result = subprocess.run(
        test_command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=utf8_environment,
    )
    test_output = test_result.stdout + test_result.stderr
    test_count_match = re.search(r"Ran (\d+) tests?", test_output)
    if test_result.returncode != 0 or test_count_match is None:
        raise ExperimentError("The full unittest suite must pass before r4 capture:\n" + test_output[-6000:])

    compile_files = [
        root / "scripts" / "run_style_regression.py",
        root / "scripts" / "test_style_regression.py",
    ]
    compile_result = subprocess.run(
        [sys.executable, "-m", "py_compile", *(str(path) for path in compile_files)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=utf8_environment,
    )
    if compile_result.returncode != 0:
        raise ExperimentError("py_compile must pass before r4 capture:\n" + compile_result.stdout + compile_result.stderr)

    preflight = collect_preflight(
        root,
        hard=True,
        codex_managed=True,
        allow_formal_progress=True,
        legacy_runner_hash_allowlist=legacy_allowlist,
    )
    if preflight.get("global_status") != "READY" or preflight.get("errors"):
        raise ExperimentError("The current hard preflight is not READY for r4 continuation:\n- " + "\n- ".join(preflight.get("errors") or []))
    rows, indexed, pending_index = _validate_formal_state(preflight, root=root)
    if (
        _compliant_formal_sample_counts(
            rows, root=root, legacy_runner_hash_allowlist=legacy_allowlist
        ) != {"A": 1, "B": 1, "C": 0}
        or pending_index != 2
        or indexed["case-01:A:r1"].get("status") != "succeeded"
        or indexed["case-01:B:r1"].get("status") != "succeeded"
    ):
        raise ExperimentError("The only permitted r4 starting point is the existing compliant 2/36 checkpoint.")

    report_path, markdown_path = _preflight_report_paths(root)
    if report_path.exists() or markdown_path.exists():
        raise ExperimentError("An r4 preflight report already exists; continuation capture history is write-once.")
    preflight_report = write_preflight_report(preflight, root=root)
    if preflight_report.get("status") != "READY" or preflight_report.get("formal_sample_total") != 2:
        raise ExperimentError("The saved r4 preflight report must be READY at the 2/36 checkpoint.")

    porcelain_result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    porcelain = porcelain_result.stdout.rstrip("\r\n")
    branch_status = _git_output(root, "status", "--short", "--branch")
    report_relative = _relative_path(report_path, root=root)
    parent_completion = parent_capture.get("completion_report")
    if not isinstance(parent_completion, Mapping):
        raise ExperimentError("The r3 parent capture is missing its passing Pilot completion report.")
    environment = copy.deepcopy(parent_capture)
    environment.update(
        {
            "schema_version": 1,
            "record_kind": "batch-4b3t-final-preflight-capture",
            "execution_mode": "codex-managed",
            "engine": "Codex-managed",
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "commit_sha": _git_output(root, "rev-parse", "HEAD"),
            "worktree_clean": not bool(porcelain),
            "git_status_short": branch_status,
            "dirty_paths": [line[3:] for line in porcelain.splitlines() if len(line) >= 4],
            "tests": {
                "command": "python -m unittest discover -s scripts -p \"test_*.py\"",
                "count": int(test_count_match.group(1)),
                "failures": 0,
                "errors": 0,
                "status": "PASS",
            },
            "py_compile": {"files": [_relative_path(path, root=root) for path in compile_files], "status": "PASS"},
            "hashes": current_hashes,
            "preflight_report": {
                "path": report_relative,
                "sha256": sha256_file(report_path),
                "status": preflight_report["status"],
            },
            "hard_preflight_ready": True,
            "experiment_ready": True,
            "blocking_inputs": [],
            "formal_baseline": {
                "compliant_counts": checkpoint["formal_sample_counts"],
                "compliant_total": checkpoint["formal_sample_total"],
                "invalid_technical_attempts": 1,
                "next_pending_sample": checkpoint["next_pending_sample"],
            },
            "parent_capture": {"path": _relative_path(parent_path, root=root), "sha256": parent_sha256},
            "formal_continuation_checkpoint": checkpoint,
            "legacy_task_compatibility": sorted(legacy_allowlist.values(), key=lambda entry: entry["task_path"]),
            "integrity_fix": {
                "issue": "Historical invalidation validation compared attempt 1 with the latest row output hash after retry acceptance.",
                "change": "Validate invalidated attempts against their own immutable data, and advance the resume index after each consecutive success.",
                "fail_closed_checks": [
                    "Exact invalidation incident kind, reason, excluded status, task identity, and historical PNG hash remain required.",
                    "Latest successful output, PNG signature, execution receipt, and manifest hashes remain linked and unique.",
                    "Queued, failed, and superseded rows cannot retain completion metadata or conflicting output files.",
                    "Legacy runner compatibility is limited to the hash-pinned A-r1 attempt-2 and B-r1 attempt-2 tasks.",
                ],
            },
        }
    )
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with capture_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(environment, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ExperimentError("The r3 formal continuation capture appeared concurrently; refusing replacement.") from exc
    _validate_r4_formal_capture(root)
    return environment


def _retry_fix_compatibility(
    rows: Sequence[Mapping[str, Any]], *, root: Path
) -> dict[str, dict[str, str]]:
    """Pin every pre-r5 task whose embedded runner hash is historical."""
    current_runner = sha256_file(root / "scripts" / "run_style_regression.py")
    compatibility: dict[str, dict[str, str]] = {}
    for row in rows:
        for attempt in row.get("attempts") or []:
            task_relative = attempt.get("task_path")
            task_digest = attempt.get("task_sha256")
            if not isinstance(task_relative, str) or not isinstance(task_digest, str):
                raise ExperimentError("The r5 checkpoint contains an attempt without an immutable task identity.")
            task_path = _repo_path(task_relative, root=root)
            task = _load_json(task_path)
            runner_digest = ((task.get("frozen_input_hashes") or {}).get("files") or {}).get(
                "scripts/run_style_regression.py"
            )
            if not isinstance(runner_digest, str):
                raise ExperimentError(f"The historical task does not pin its runner: {task_relative}.")
            if runner_digest == current_runner:
                continue
            if task.get("task_sha256") != task_digest:
                raise ExperimentError(f"The historical task digest differs from its manifest: {task_relative}.")
            entry = {
                "task_path": task_relative,
                "task_sha256": task_digest,
                "task_file_sha256": sha256_file(task_path),
                "task_kind": "formal",
                "runner_sha256": runner_digest,
            }
            if task_digest in compatibility and compatibility[task_digest] != entry:
                raise ExperimentError("The r5 compatibility table contains a conflicting task digest.")
            compatibility[task_digest] = entry
    return compatibility


def _retry_fix_checkpoint(root: Path) -> dict[str, Any]:
    manifest_path = _formal_manifest_path(root)
    rows = _load_jsonl(manifest_path)
    compatibility = _retry_fix_compatibility(rows, root=root)
    legacy_failures = sorted(
        sha256_json(attempt)
        for row in rows
        for attempt in row.get("attempts") or []
        if attempt.get("status") == "failed"
    )
    formal_files: dict[str, str] = {_relative_path(manifest_path, root=root): sha256_file(manifest_path)}
    source_files: dict[str, str] = {}
    for row in rows:
        for attempt in row.get("attempts") or []:
            for field in ("task_path", "receipt_path", "output_path"):
                raw_path = attempt.get(field)
                if not isinstance(raw_path, str):
                    continue
                path = _repo_path(raw_path, root=root)
                if path.is_file():
                    formal_files[_relative_path(path, root=root)] = sha256_file(path)
            source = attempt.get("codex_generated_source_path")
            if isinstance(source, str):
                source_path = Path(source).expanduser().resolve(strict=False)
                if not source_path.is_file():
                    raise ExperimentError("A captured Codex generated source image is missing.")
                source_files[str(source_path)] = sha256_file(source_path)
    preflight = collect_preflight(
        root,
        hard=True,
        codex_managed=True,
        allow_formal_progress=True,
        legacy_runner_hash_allowlist=compatibility,
    )
    preflight["legacy_failure_policy_allowlist"] = legacy_failures
    validated_rows, indexed, _ = _validate_formal_state(preflight, root=root)
    counts = _compliant_formal_sample_counts(
        validated_rows, root=root, legacy_runner_hash_allowlist=compatibility
    )
    blocked = indexed.get("case-04:B:r2") or {}
    if counts != {"A": 11, "B": 10, "C": 10} or blocked.get("status") != "failed":
        raise ExperimentError("The r5 capture is permitted only at the exact 31/36 blocked checkpoint.")
    latest = (blocked.get("attempts") or [])[-1]
    policy = classify_codex_failure(
        str(latest.get("failure_code", "")), str(latest.get("failure_reason", ""))
    )
    if policy["failure_code"] != "imagegen_safety_block" or policy["retryable"]:
        raise ExperimentError("The r5 checkpoint must terminate at the case-04:B:r2 safety refusal.")
    return {
        "manifest_path": _relative_path(manifest_path, root=root),
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_rows": validated_rows,
        "manifest_rows_sha256": sha256_json(validated_rows),
        "manifest_row_sha256": {str(row["sample_key"]): sha256_json(row) for row in validated_rows},
        "attempt_prefix_sha256": {
            str(row["sample_key"]): [sha256_json(attempt) for attempt in row.get("attempts") or []]
            for row in validated_rows
        },
        "formal_file_sha256": dict(sorted(formal_files.items())),
        "external_source_file_sha256": dict(sorted(source_files.items())),
        "formal_sample_counts": counts,
        "formal_sample_total": sum(counts.values()),
        "blocked_sample": "case-04:B:r2",
        "blocked_failure_code": "imagegen_safety_block",
        "legacy_task_compatibility": sorted(compatibility.values(), key=lambda item: item["task_path"]),
        "legacy_failure_policy_attempt_sha256": legacy_failures,
        "preflight": preflight,
    }


def create_formal_retry_fix_capture(root: Path = ROOT) -> dict[str, Any]:
    """Create the append-only r5 capture for the existing 31/36 terminal checkpoint."""
    capture_path = root / "evaluation" / "style-regression" / "environment" / R_RETRY_FIX_FINAL_CAPTURE_PATH
    parent_path = root / "evaluation" / "style-regression" / "environment" / R_FINAL_PREFLIGHT_ENVIRONMENT_PATH
    if capture_path.exists():
        raise ExperimentError("The r5 retry-fix capture already exists; captured history is write-once.")
    if not parent_path.is_file():
        raise ExperimentError("The immutable r4 continuation capture is missing.")
    utf8_environment = os.environ.copy()
    utf8_environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    test_result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "scripts", "-p", "test_*.py"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", env=utf8_environment,
    )
    test_output = test_result.stdout + test_result.stderr
    match = re.search(r"Ran (\d+) tests?", test_output)
    if test_result.returncode or match is None:
        raise ExperimentError("The full unittest suite must pass before r5 capture:\n" + test_output[-6000:])
    compile_files = [root / "scripts" / "run_style_regression.py", root / "scripts" / "test_style_regression.py"]
    compiled = subprocess.run(
        [sys.executable, "-m", "py_compile", *(str(path) for path in compile_files)],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", env=utf8_environment,
    )
    if compiled.returncode:
        raise ExperimentError("py_compile must pass before r5 capture:\n" + compiled.stdout + compiled.stderr)
    checkpoint = _retry_fix_checkpoint(root)
    preflight = checkpoint.pop("preflight")
    if preflight.get("global_status") != "READY" or preflight.get("errors"):
        raise ExperimentError("Current hard preflight is not READY for r5 capture.")
    cases_document = _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")
    parent_capture = _load_json(parent_path)
    current_hashes = _runtime_hashes(root, cases_document)
    parent_hashes = parent_capture.get("hashes") or {}
    deltas = sorted(key for key in set(parent_hashes) | set(current_hashes) if parent_hashes.get(key) != current_hashes.get(key))
    if set(deltas) - {"scripts/run_style_regression.py", "scripts/test_files_tree"}:
        raise ExperimentError("The r5 retry fix changes frozen runtime inputs outside the runner and tests.")
    capture = {
        "schema_version": 1,
        "record_kind": "batch-4b3t-formal-retry-fix-capture",
        "execution_mode": "codex-managed",
        "engine": "Codex-managed",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit_sha": _git_output(root, "rev-parse", "HEAD"),
        "parent_capture": {"path": _relative_path(parent_path, root=root), "sha256": sha256_file(parent_path)},
        "hashes": current_hashes,
        "permitted_parent_hash_deltas": deltas,
        "failure_policy": {"version": FAILURE_POLICY_VERSION, "sha256": sha256_json(CODEX_FAILURE_POLICIES)},
        "formal_baseline": {
            "compliant_counts": checkpoint["formal_sample_counts"],
            "compliant_total": checkpoint["formal_sample_total"],
            "blocked_sample": checkpoint["blocked_sample"],
            "failure_code": checkpoint["blocked_failure_code"],
        },
        "legacy_task_compatibility": checkpoint["legacy_task_compatibility"],
        "legacy_failure_policy_attempt_sha256": checkpoint["legacy_failure_policy_attempt_sha256"],
        "formal_retry_fix_checkpoint": checkpoint,
        "tests": {"command": "python -m unittest discover -s scripts -p \"test_*.py\"", "count": int(match.group(1)), "status": "PASS"},
        "py_compile": {"files": [_relative_path(path, root=root) for path in compile_files], "status": "PASS"},
    }
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with capture_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(capture, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ExperimentError("The r5 retry-fix capture appeared concurrently; refusing replacement.") from exc
    _validate_formal_capture(root)
    return capture


def _validate_r5_formal_capture(root: Path = ROOT) -> dict[str, Any]:
    """Validate the immutable r5 retry-fix capture and its exact 31/36 checkpoint."""
    capture_path = root / "evaluation" / "style-regression" / "environment" / R_RETRY_FIX_FINAL_CAPTURE_PATH
    if not capture_path.is_file():
        raise ExperimentError("Formal execution requires the Batch 4B.3-T r5 retry-fix capture.")
    capture = _load_json(capture_path)
    if capture.get("record_kind") != "batch-4b3t-formal-retry-fix-capture":
        raise ExperimentError("The current formal capture is not the r5 retry-fix capture.")
    parent = capture.get("parent_capture") or {}
    parent_path = _repo_path(str(parent.get("path", "")), root=root)
    if not parent_path.is_file() or parent.get("sha256") != sha256_file(parent_path):
        raise ExperimentError("The immutable r4 parent capture is missing or changed.")
    cases_document = _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")
    if capture.get("hashes") != _runtime_hashes(root, cases_document):
        raise ExperimentError("The r5 capture is stale; frozen runtime or test hashes changed.")
    if capture.get("failure_policy") != {
        "version": FAILURE_POLICY_VERSION,
        "sha256": sha256_json(CODEX_FAILURE_POLICIES),
    }:
        raise ExperimentError("The r5 failure policy changed after capture.")
    checkpoint = capture.get("formal_retry_fix_checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise ExperimentError("The r5 formal checkpoint is missing.")
    manifest_path = _repo_path(str(checkpoint.get("manifest_path", "")), root=root)
    rows = _load_jsonl(manifest_path)
    if sha256_file(manifest_path) != checkpoint.get("manifest_sha256") or sha256_json(rows) != checkpoint.get("manifest_rows_sha256"):
        raise ExperimentError("The r5 captured formal manifest changed.")
    for relative_path, expected in (checkpoint.get("formal_file_sha256") or {}).items():
        path = _repo_path(str(relative_path), root=root)
        if not path.is_file() or sha256_file(path) != expected:
            raise ExperimentError(f"The r5 captured formal artifact changed: {relative_path}.")
    for raw_path, expected in (checkpoint.get("external_source_file_sha256") or {}).items():
        path = Path(str(raw_path)).expanduser().resolve(strict=False)
        if not path.is_file() or sha256_file(path) != expected:
            raise ExperimentError("An r5 captured generated source image changed.")
    compatibility = _retry_fix_compatibility(rows, root=root)
    captured_compatibility = capture.get("legacy_task_compatibility")
    if sorted(compatibility.values(), key=lambda item: item["task_path"]) != captured_compatibility:
        raise ExperimentError("The exact r5 legacy task compatibility table changed.")
    legacy_failures = sorted(
        sha256_json(attempt)
        for row in rows
        for attempt in row.get("attempts") or []
        if attempt.get("status") == "failed"
    )
    if legacy_failures != capture.get("legacy_failure_policy_attempt_sha256"):
        raise ExperimentError("The exact r5 legacy failure-policy compatibility list changed.")
    preflight = collect_preflight(
        root, hard=True, codex_managed=True, allow_formal_progress=True,
        legacy_runner_hash_allowlist=compatibility,
    )
    preflight["legacy_failure_policy_allowlist"] = legacy_failures
    if preflight.get("global_status") != "READY" or preflight.get("errors"):
        raise ExperimentError("Current hard preflight is not READY under the r5 capture.")
    validated_rows, indexed, _ = _validate_formal_state(preflight, root=root)
    counts = _compliant_formal_sample_counts(validated_rows, root=root, legacy_runner_hash_allowlist=compatibility)
    if counts != {"A": 11, "B": 10, "C": 10} or indexed.get("case-04:B:r2", {}).get("status") != "failed":
        raise ExperimentError("The current state differs from the r5 31/36 terminal checkpoint.")
    preflight["legacy_runner_hash_allowlist"] = compatibility
    return preflight


def create_protocol_revision_capture(root: Path = ROOT) -> dict[str, Any]:
    """Freeze the authorized r6 prompt revision against the exact r5 checkpoint."""
    path = root / "evaluation" / "style-regression" / "environment" / R_PROTOCOL_REVISION_CAPTURE_PATH
    parent_path = root / "evaluation" / "style-regression" / "environment" / R_RETRY_FIX_FINAL_CAPTURE_PATH
    if path.exists():
        raise ExperimentError("The r6 protocol capture already exists; refusing replacement.")
    revision = _formal_protocol_revision("case-04:B:r2", root=root)
    if revision is None:
        raise ExperimentError("The authorized r6 protocol revision is missing.")
    parent = _load_json(parent_path)
    checkpoint = parent.get("formal_retry_fix_checkpoint") or {}
    manifest_path = _repo_path(str(checkpoint.get("manifest_path", "")), root=root)
    rows = _load_jsonl(manifest_path)
    if sha256_file(manifest_path) != checkpoint.get("manifest_sha256"):
        raise ExperimentError("The r5 manifest changed before the r6 protocol capture.")
    compatibility = _retry_fix_compatibility(rows, root=root)
    cases_document = _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")
    capture = {
        "schema_version": 1,
        "record_kind": "batch-4b3t-formal-protocol-revision-capture",
        "revision": "r6",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent_capture": {"path": _relative_path(parent_path, root=root), "sha256": sha256_file(parent_path)},
        "protocol_revision": {"path": R_PROTOCOL_REVISION_PATHS["case-04:B:r2"], "sha256": sha256_file(revision["path"])},
        "hashes": _runtime_hashes(root, cases_document),
        "baseline_manifest_rows": rows,
        "baseline_manifest_rows_sha256": sha256_json(rows),
        "baseline_formal_file_sha256": checkpoint.get("formal_file_sha256"),
        "baseline_source_file_sha256": checkpoint.get("external_source_file_sha256"),
        "legacy_task_compatibility": sorted(compatibility.values(), key=lambda item: item["task_path"]),
        "legacy_failure_policy_attempt_sha256": parent.get("legacy_failure_policy_attempt_sha256"),
        "formal_baseline": {"compliant_counts": {"A": 11, "B": 10, "C": 10}, "compliant_total": 31},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(capture, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return capture


def _validate_r6_formal_capture(root: Path = ROOT) -> dict[str, Any]:
    """Validate r6 when present; otherwise retain the exact r5 terminal checkpoint."""
    path = root / "evaluation" / "style-regression" / "environment" / R_PROTOCOL_REVISION_CAPTURE_PATH
    if not path.is_file():
        return _validate_r5_formal_capture(root)
    capture = _load_json(path)
    if capture.get("record_kind") != "batch-4b3t-formal-protocol-revision-capture":
        raise ExperimentError("The current formal capture is not the authorized r6 protocol revision.")
    parent = capture.get("parent_capture") or {}
    parent_path = _repo_path(str(parent.get("path", "")), root=root)
    if not parent_path.is_file() or sha256_file(parent_path) != parent.get("sha256"):
        raise ExperimentError("The immutable r5 parent capture is missing or changed.")
    revision = _formal_protocol_revision("case-04:B:r2", root=root)
    if revision is None or sha256_file(revision["path"]) != (capture.get("protocol_revision") or {}).get("sha256"):
        raise ExperimentError("The authorized r6 protocol revision changed after capture.")
    cases_document = _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")
    if capture.get("hashes") != _runtime_hashes(root, cases_document):
        raise ExperimentError("The r6 capture is stale; frozen runtime or tests changed.")
    baseline_rows = capture.get("baseline_manifest_rows")
    if not isinstance(baseline_rows, list) or sha256_json(baseline_rows) != capture.get("baseline_manifest_rows_sha256"):
        raise ExperimentError("The r6 baseline manifest pins are invalid.")
    manifest_path = _formal_manifest_path(root)
    rows = _load_jsonl(manifest_path)
    current = _manifest_index(rows)
    for baseline in baseline_rows:
        key = str(baseline["sample_key"])
        row = current.get(key)
        if row is None:
            raise ExperimentError(f"The r6 baseline sample was removed: {key}.")
        prefix = [sha256_json(item) for item in baseline.get("attempts") or []]
        attempts = row.get("attempts") or []
        if [sha256_json(item) for item in attempts[: len(prefix)]] != prefix:
            raise ExperimentError(f"The r6 immutable attempt prefix changed: {key}.")
        if key != "case-04:B:r2" and sha256_json(row) != sha256_json(baseline):
            raise ExperimentError(f"An accepted r6 baseline manifest row changed: {key}.")
    for relative_path, expected in (capture.get("baseline_formal_file_sha256") or {}).items():
        if str(relative_path).endswith("manifest.jsonl"):
            continue
        artifact = _repo_path(str(relative_path), root=root)
        if not artifact.is_file() or sha256_file(artifact) != expected:
            raise ExperimentError(f"An r6 baseline formal artifact changed: {relative_path}.")
    compatibility = _retry_fix_compatibility(rows, root=root)
    captured_compatibility = capture.get("legacy_task_compatibility")
    if sorted(compatibility.values(), key=lambda item: item["task_path"]) != captured_compatibility:
        raise ExperimentError("The r6 legacy task compatibility table changed.")
    legacy_failures = capture.get("legacy_failure_policy_attempt_sha256") or []
    preflight = collect_preflight(
        root, hard=True, codex_managed=True, allow_formal_progress=True,
        legacy_runner_hash_allowlist=compatibility,
    )
    preflight["legacy_failure_policy_allowlist"] = legacy_failures
    if preflight.get("global_status") != "READY" or preflight.get("errors"):
        raise ExperimentError("Current hard preflight is not READY under r6.")
    _validate_formal_state(preflight, root=root)
    preflight["legacy_runner_hash_allowlist"] = compatibility
    return preflight


def create_r7_protocol_capture(root: Path = ROOT) -> dict[str, Any]:
    path = root / "evaluation" / "style-regression" / "environment" / R_PROTOCOL_REVISION_R7_CAPTURE_PATH
    parent_path = root / "evaluation" / "style-regression" / "environment" / R_PROTOCOL_REVISION_CAPTURE_PATH
    if path.exists():
        raise ExperimentError("The r7 protocol capture already exists; refusing replacement.")
    if not parent_path.is_file():
        raise ExperimentError("The immutable r6 capture is missing.")
    rows = _load_jsonl(_formal_manifest_path(root))
    indexed = _manifest_index(rows)
    if indexed.get("case-04:B:r2", {}).get("status") != "succeeded" or indexed.get("case-04:C:r2", {}).get("status") != "failed":
        raise ExperimentError("The r7 capture requires the exact 32/36 checkpoint and terminal C-r2 attempt 1.")
    revisions = {}
    for key in ("case-04:B:r2", "case-04:C:r2"):
        revision = _formal_protocol_revision(key, root=root)
        if revision is None:
            raise ExperimentError(f"Missing authorized protocol revision for {key}.")
        revisions[key] = {"path": _relative_path(revision["path"], root=root), "sha256": sha256_file(revision["path"])}
    compatibility = _retry_fix_compatibility(rows, root=root)
    r5 = _load_json(root / "evaluation" / "style-regression" / "environment" / R_RETRY_FIX_FINAL_CAPTURE_PATH)
    cases_document = _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")
    capture = {
        "schema_version": 1,
        "record_kind": "batch-4b3t-formal-protocol-revision-capture",
        "revision": "r7",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent_capture": {"path": _relative_path(parent_path, root=root), "sha256": sha256_file(parent_path)},
        "protocol_revisions": revisions,
        "hashes": _runtime_hashes(root, cases_document),
        "baseline_manifest_rows": rows,
        "baseline_manifest_rows_sha256": sha256_json(rows),
        "legacy_task_compatibility": sorted(compatibility.values(), key=lambda item: item["task_path"]),
        "legacy_failure_policy_attempt_sha256": r5.get("legacy_failure_policy_attempt_sha256"),
        "formal_baseline": {"compliant_counts": {"A": 11, "B": 11, "C": 10}, "compliant_total": 32},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(capture, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return capture


def _validate_r7_formal_capture(root: Path = ROOT) -> dict[str, Any]:
    path = root / "evaluation" / "style-regression" / "environment" / R_PROTOCOL_REVISION_R7_CAPTURE_PATH
    if not path.is_file():
        return _validate_r6_formal_capture(root)
    capture = _load_json(path)
    if capture.get("record_kind") != "batch-4b3t-formal-protocol-revision-capture" or capture.get("revision") != "r7":
        raise ExperimentError("The current formal capture is not the authorized r7 revision.")
    parent = capture.get("parent_capture") or {}
    parent_path = _repo_path(str(parent.get("path", "")), root=root)
    if not parent_path.is_file() or sha256_file(parent_path) != parent.get("sha256"):
        raise ExperimentError("The immutable r6 parent capture is missing or changed.")
    for key, pin in (capture.get("protocol_revisions") or {}).items():
        revision = _formal_protocol_revision(str(key), root=root)
        if revision is None or sha256_file(revision["path"]) != pin.get("sha256"):
            raise ExperimentError(f"The authorized protocol revision changed: {key}.")
    cases_document = _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")
    if capture.get("hashes") != _runtime_hashes(root, cases_document):
        raise ExperimentError("The r7 capture is stale; frozen runtime or tests changed.")
    baseline = capture.get("baseline_manifest_rows") or []
    if sha256_json(baseline) != capture.get("baseline_manifest_rows_sha256"):
        raise ExperimentError("The r7 baseline manifest pins are invalid.")
    rows = _load_jsonl(_formal_manifest_path(root))
    current = _manifest_index(rows)
    for old in baseline:
        key = str(old["sample_key"])
        row = current.get(key)
        if row is None:
            raise ExperimentError(f"The r7 baseline sample was removed: {key}.")
        prefix = [sha256_json(item) for item in old.get("attempts") or []]
        if [sha256_json(item) for item in (row.get("attempts") or [])[: len(prefix)]] != prefix:
            raise ExperimentError(f"The r7 immutable attempt prefix changed: {key}.")
        if key != "case-04:C:r2" and sha256_json(row) != sha256_json(old):
            raise ExperimentError(f"An accepted r7 baseline row changed: {key}.")
    compatibility = _retry_fix_compatibility(rows, root=root)
    if sorted(compatibility.values(), key=lambda item: item["task_path"]) != capture.get("legacy_task_compatibility"):
        raise ExperimentError("The r7 legacy task compatibility table changed.")
    preflight = collect_preflight(root, hard=True, codex_managed=True, allow_formal_progress=True, legacy_runner_hash_allowlist=compatibility)
    preflight["legacy_failure_policy_allowlist"] = capture.get("legacy_failure_policy_attempt_sha256") or []
    if preflight.get("global_status") != "READY" or preflight.get("errors"):
        raise ExperimentError("Current hard preflight is not READY under r7.")
    _validate_formal_state(preflight, root=root)
    preflight["legacy_runner_hash_allowlist"] = compatibility
    return preflight


def create_r8_protocol_capture(root: Path = ROOT) -> dict[str, Any]:
    path = root / "evaluation" / "style-regression" / "environment" / R_PROTOCOL_REVISION_R8_CAPTURE_PATH
    parent_path = root / "evaluation" / "style-regression" / "environment" / R_PROTOCOL_REVISION_R7_CAPTURE_PATH
    if path.exists():
        raise ExperimentError("The r8 protocol capture already exists; refusing replacement.")
    rows = _load_jsonl(_formal_manifest_path(root))
    row = _manifest_index(rows).get("case-04:C:r2") or {}
    if row.get("status") != "queued" or (row.get("attempts") or [])[-1].get("attempt") != 2:
        raise ExperimentError("The r8 capture requires queued case-04:C:r2 attempt 2.")
    compatibility = _retry_fix_compatibility(rows, root=root)
    r5 = _load_json(root / "evaluation" / "style-regression" / "environment" / R_RETRY_FIX_FINAL_CAPTURE_PATH)
    revisions = {}
    for key in R_PROTOCOL_REVISION_PATHS:
        revision = _formal_protocol_revision(key, root=root)
        if revision is None:
            raise ExperimentError(f"Missing authorized protocol revision for {key}.")
        revisions[key] = {"path": _relative_path(revision["path"], root=root), "sha256": sha256_file(revision["path"])}
    capture = {
        "schema_version": 1, "record_kind": "batch-4b3t-formal-protocol-revision-capture", "revision": "r8",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent_capture": {"path": _relative_path(parent_path, root=root), "sha256": sha256_file(parent_path)},
        "protocol_revisions": revisions,
        "hashes": _runtime_hashes(root, _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")),
        "baseline_manifest_rows": rows, "baseline_manifest_rows_sha256": sha256_json(rows),
        "legacy_task_compatibility": sorted(compatibility.values(), key=lambda item: item["task_path"]),
        "legacy_failure_policy_attempt_sha256": r5.get("legacy_failure_policy_attempt_sha256"),
        "formal_baseline": {"compliant_counts": {"A": 11, "B": 11, "C": 10}, "compliant_total": 32},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(capture, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    return capture


def _validate_r8_formal_capture(root: Path = ROOT) -> dict[str, Any]:
    path = root / "evaluation" / "style-regression" / "environment" / R_PROTOCOL_REVISION_R8_CAPTURE_PATH
    if not path.is_file():
        return _validate_r7_formal_capture(root)
    capture = _load_json(path)
    if capture.get("record_kind") != "batch-4b3t-formal-protocol-revision-capture" or capture.get("revision") != "r8":
        raise ExperimentError("The current formal capture is not r8.")
    parent = capture.get("parent_capture") or {}; parent_path = _repo_path(str(parent.get("path", "")), root=root)
    if not parent_path.is_file() or sha256_file(parent_path) != parent.get("sha256"):
        raise ExperimentError("The immutable r7 parent capture changed.")
    if capture.get("hashes") != _runtime_hashes(root, _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")):
        raise ExperimentError("The r8 capture is stale.")
    for key, pin in (capture.get("protocol_revisions") or {}).items():
        revision = _formal_protocol_revision(str(key), root=root)
        if revision is None or sha256_file(revision["path"]) != pin.get("sha256"):
            raise ExperimentError(f"The r8 protocol revision changed: {key}.")
    baseline = capture.get("baseline_manifest_rows") or []
    if sha256_json(baseline) != capture.get("baseline_manifest_rows_sha256"):
        raise ExperimentError("The r8 baseline pins are invalid.")
    rows = _load_jsonl(_formal_manifest_path(root)); current = _manifest_index(rows)
    for old in baseline:
        key = str(old["sample_key"]); row = current.get(key)
        if row is None:
            raise ExperimentError(f"The r8 baseline sample was removed: {key}.")
        prefix = [sha256_json(item) for item in old.get("attempts") or []]
        if [sha256_json(item) for item in (row.get("attempts") or [])[:len(prefix)]] != prefix:
            raise ExperimentError(f"The r8 attempt prefix changed: {key}.")
        if key != "case-04:C:r2" and sha256_json(row) != sha256_json(old):
            raise ExperimentError(f"An accepted r8 baseline row changed: {key}.")
    compatibility = _retry_fix_compatibility(rows, root=root)
    if sorted(compatibility.values(), key=lambda item: item["task_path"]) != capture.get("legacy_task_compatibility"):
        raise ExperimentError("The r8 legacy compatibility table changed.")
    preflight = collect_preflight(root, hard=True, codex_managed=True, allow_formal_progress=True, legacy_runner_hash_allowlist=compatibility)
    preflight["legacy_failure_policy_allowlist"] = capture.get("legacy_failure_policy_attempt_sha256") or []
    if preflight.get("global_status") != "READY" or preflight.get("errors"):
        raise ExperimentError("Current hard preflight is not READY under r8.")
    _validate_formal_state(preflight, root=root); preflight["legacy_runner_hash_allowlist"] = compatibility
    return preflight


def create_r9_protocol_capture(root: Path = ROOT) -> dict[str, Any]:
    path = root / "evaluation" / "style-regression" / "environment" / R_PROTOCOL_REVISION_R9_CAPTURE_PATH
    parent_path = root / "evaluation" / "style-regression" / "environment" / R_PROTOCOL_REVISION_R8_CAPTURE_PATH
    if path.exists():
        raise ExperimentError("The r9 protocol capture already exists; refusing replacement.")
    rows = _load_jsonl(_formal_manifest_path(root)); compatibility = _retry_fix_compatibility(rows, root=root)
    r5 = _load_json(root / "evaluation" / "style-regression" / "environment" / R_RETRY_FIX_FINAL_CAPTURE_PATH)
    revisions = {}
    for key in R_PROTOCOL_REVISION_PATHS:
        revision = _formal_protocol_revision(key, root=root)
        if revision is None: raise ExperimentError(f"Missing protocol revision: {key}.")
        revisions[key] = {"path": _relative_path(revision["path"], root=root), "sha256": sha256_file(revision["path"])}
    capture = {
        "schema_version": 1, "record_kind": "batch-4b3t-formal-protocol-revision-capture", "revision": "r9",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent_capture": {"path": _relative_path(parent_path, root=root), "sha256": sha256_file(parent_path)},
        "protocol_revisions": revisions,
        "hashes": _runtime_hashes(root, _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")),
        "baseline_manifest_rows": rows, "baseline_manifest_rows_sha256": sha256_json(rows),
        "legacy_task_compatibility": sorted(compatibility.values(), key=lambda item: item["task_path"]),
        "legacy_failure_policy_attempt_sha256": r5.get("legacy_failure_policy_attempt_sha256"),
        "formal_baseline": {"compliant_counts": {"A": 11, "B": 11, "C": 10}, "compliant_total": 32},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(capture, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    return capture


def _validate_r9_formal_capture(root: Path = ROOT) -> dict[str, Any]:
    path = root / "evaluation" / "style-regression" / "environment" / R_PROTOCOL_REVISION_R9_CAPTURE_PATH
    if not path.is_file(): return _validate_r8_formal_capture(root)
    capture = _load_json(path)
    if capture.get("revision") != "r9": raise ExperimentError("The current formal capture is not r9.")
    parent = capture.get("parent_capture") or {}; parent_path = _repo_path(str(parent.get("path", "")), root=root)
    if not parent_path.is_file() or sha256_file(parent_path) != parent.get("sha256"): raise ExperimentError("The r8 parent changed.")
    if capture.get("hashes") != _runtime_hashes(root, _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")): raise ExperimentError("The r9 capture is stale.")
    for key, pin in (capture.get("protocol_revisions") or {}).items():
        revision = _formal_protocol_revision(str(key), root=root)
        if revision is None or sha256_file(revision["path"]) != pin.get("sha256"): raise ExperimentError(f"The r9 protocol changed: {key}.")
    baseline = capture.get("baseline_manifest_rows") or []
    if sha256_json(baseline) != capture.get("baseline_manifest_rows_sha256"): raise ExperimentError("The r9 baseline pins are invalid.")
    rows = _load_jsonl(_formal_manifest_path(root)); current = _manifest_index(rows)
    for old in baseline:
        key = str(old["sample_key"]); row = current.get(key)
        if row is None: raise ExperimentError(f"The r9 baseline sample was removed: {key}.")
        old_attempts = list(old.get("attempts") or [])
        if key == "case-04:C:r2" and old_attempts and old_attempts[-1].get("status") == "queued":
            old_attempts = old_attempts[:-1]
        prefix = [sha256_json(item) for item in old_attempts]
        if [sha256_json(item) for item in (row.get("attempts") or [])[:len(prefix)]] != prefix: raise ExperimentError(f"The r9 attempt prefix changed: {key}.")
        if key != "case-04:C:r2" and sha256_json(row) != sha256_json(old): raise ExperimentError(f"An accepted r9 row changed: {key}.")
    compatibility = _retry_fix_compatibility(rows, root=root)
    if sorted(compatibility.values(), key=lambda item: item["task_path"]) != capture.get("legacy_task_compatibility"): raise ExperimentError("The r9 compatibility table changed.")
    preflight = collect_preflight(root, hard=True, codex_managed=True, allow_formal_progress=True, legacy_runner_hash_allowlist=compatibility)
    preflight["legacy_failure_policy_allowlist"] = capture.get("legacy_failure_policy_attempt_sha256") or []
    if preflight.get("global_status") != "READY" or preflight.get("errors"): raise ExperimentError("Current hard preflight is not READY under r9.")
    _validate_formal_state(preflight, root=root); preflight["legacy_runner_hash_allowlist"] = compatibility
    return preflight


def create_r10_formal_capture(root: Path = ROOT) -> dict[str, Any]:
    path = root / "evaluation" / "style-regression" / "environment" / R_FORMAL_CONTINUATION_R10_CAPTURE_PATH
    parent_path = root / "evaluation" / "style-regression" / "environment" / R_PROTOCOL_REVISION_R9_CAPTURE_PATH
    if path.exists(): raise ExperimentError("The r10 formal capture already exists; refusing replacement.")
    rows = _load_jsonl(_formal_manifest_path(root)); compatibility = _retry_fix_compatibility(rows, root=root)
    counts = _compliant_formal_sample_counts(rows, root=root, legacy_runner_hash_allowlist=compatibility)
    if counts != {"A": 11, "B": 11, "C": 11} or any(row.get("status") != "succeeded" for row in rows):
        raise ExperimentError("The r10 capture requires the exact 33/36 succeeded checkpoint.")
    r5 = _load_json(root / "evaluation" / "style-regression" / "environment" / R_RETRY_FIX_FINAL_CAPTURE_PATH)
    capture = {
        "schema_version": 1, "record_kind": "batch-4b3t-formal-continuation-capture", "revision": "r10",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent_capture": {"path": _relative_path(parent_path, root=root), "sha256": sha256_file(parent_path)},
        "hashes": _runtime_hashes(root, _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")),
        "baseline_manifest_rows": rows, "baseline_manifest_rows_sha256": sha256_json(rows),
        "legacy_task_compatibility": sorted(compatibility.values(), key=lambda item: item["task_path"]),
        "legacy_failure_policy_attempt_sha256": r5.get("legacy_failure_policy_attempt_sha256"),
        "formal_baseline": {"compliant_counts": counts, "compliant_total": 33},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(capture, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    return capture


def _validate_r10_formal_capture(root: Path = ROOT) -> dict[str, Any]:
    path = root / "evaluation" / "style-regression" / "environment" / R_FORMAL_CONTINUATION_R10_CAPTURE_PATH
    if not path.is_file(): return _validate_r9_formal_capture(root)
    capture = _load_json(path)
    if capture.get("revision") != "r10": raise ExperimentError("The current formal capture is not r10.")
    parent = capture.get("parent_capture") or {}; parent_path = _repo_path(str(parent.get("path", "")), root=root)
    if not parent_path.is_file() or sha256_file(parent_path) != parent.get("sha256"): raise ExperimentError("The r9 parent changed.")
    if capture.get("hashes") != _runtime_hashes(root, _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")): raise ExperimentError("The r10 capture is stale.")
    baseline = capture.get("baseline_manifest_rows") or []
    if sha256_json(baseline) != capture.get("baseline_manifest_rows_sha256"): raise ExperimentError("The r10 baseline pins are invalid.")
    rows = _load_jsonl(_formal_manifest_path(root)); current = _manifest_index(rows)
    for old in baseline:
        key = str(old["sample_key"]); row = current.get(key)
        if row is None or sha256_json(row) != sha256_json(old): raise ExperimentError(f"An accepted r10 baseline row changed: {key}.")
    compatibility = _retry_fix_compatibility(rows, root=root)
    if sorted(compatibility.values(), key=lambda item: item["task_path"]) != capture.get("legacy_task_compatibility"): raise ExperimentError("The r10 compatibility table changed.")
    preflight = collect_preflight(root, hard=True, codex_managed=True, allow_formal_progress=True, legacy_runner_hash_allowlist=compatibility)
    preflight["legacy_failure_policy_allowlist"] = capture.get("legacy_failure_policy_attempt_sha256") or []
    if preflight.get("global_status") != "READY" or preflight.get("errors"): raise ExperimentError("Current hard preflight is not READY under r10.")
    _validate_formal_state(preflight, root=root); preflight["legacy_runner_hash_allowlist"] = compatibility
    return preflight


def create_r14_formal_capture(root: Path = ROOT) -> dict[str, Any]:
    path = root / "evaluation" / "style-regression" / "environment" / R_FORMAL_CONTINUATION_R14_CAPTURE_PATH
    parent_path = root / "evaluation" / "style-regression" / "environment" / R_FORMAL_CONTINUATION_R10_CAPTURE_PATH
    if path.exists(): raise ExperimentError("The r14 capture already exists; refusing replacement.")
    rows = _load_jsonl(_formal_manifest_path(root)); indexed = _manifest_index(rows)
    if indexed.get("case-04:A:r3", {}).get("status") != "failed": raise ExperimentError("r14 requires terminal A-r3 attempt 1.")
    compatibility = _retry_fix_compatibility(rows, root=root)
    r5 = _load_json(root / "evaluation" / "style-regression" / "environment" / R_RETRY_FIX_FINAL_CAPTURE_PATH)
    revisions = {}
    for key in R_PROTOCOL_REVISION_PATHS:
        revision = _formal_protocol_revision(key, root=root)
        if revision is None: raise ExperimentError(f"Missing protocol revision: {key}.")
        revisions[key] = {"path": _relative_path(revision["path"], root=root), "sha256": sha256_file(revision["path"])}
    capture = {
        "schema_version":1,"record_kind":"batch-4b3t-formal-continuation-capture","revision":"r14",
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "parent_capture":{"path":_relative_path(parent_path,root=root),"sha256":sha256_file(parent_path)},
        "protocol_revisions":revisions,
        "hashes":_runtime_hashes(root,_load_yaml(root/"evaluation"/"style-regression"/"cases.yaml")),
        "baseline_manifest_rows":rows,"baseline_manifest_rows_sha256":sha256_json(rows),
        "legacy_task_compatibility":sorted(compatibility.values(),key=lambda item:item["task_path"]),
        "legacy_failure_policy_attempt_sha256":r5.get("legacy_failure_policy_attempt_sha256"),
        "formal_baseline":{"compliant_counts":{"A":11,"B":11,"C":11},"compliant_total":33},
    }
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf-8",newline="\n") as handle:
        json.dump(capture,handle,ensure_ascii=False,indent=2,sort_keys=True);handle.write("\n");handle.flush();os.fsync(handle.fileno())
    return capture


def _validate_formal_capture(root: Path = ROOT) -> dict[str, Any]:
    path=root/"evaluation"/"style-regression"/"environment"/R_FORMAL_CONTINUATION_R14_CAPTURE_PATH
    if not path.is_file(): return _validate_r10_formal_capture(root)
    capture=_load_json(path)
    if capture.get("revision")!="r14": raise ExperimentError("The current formal capture is not r14.")
    parent=capture.get("parent_capture") or {};parent_path=_repo_path(str(parent.get("path","")),root=root)
    if not parent_path.is_file() or sha256_file(parent_path)!=parent.get("sha256"): raise ExperimentError("The r10 parent changed.")
    if capture.get("hashes")!=_runtime_hashes(root,_load_yaml(root/"evaluation"/"style-regression"/"cases.yaml")): raise ExperimentError("The r14 capture is stale.")
    for key,pin in (capture.get("protocol_revisions") or {}).items():
        revision=_formal_protocol_revision(str(key),root=root)
        if revision is None or sha256_file(revision["path"])!=pin.get("sha256"): raise ExperimentError(f"The r14 protocol changed: {key}.")
    baseline=capture.get("baseline_manifest_rows") or []
    if sha256_json(baseline)!=capture.get("baseline_manifest_rows_sha256"): raise ExperimentError("The r14 baseline pins are invalid.")
    rows=_load_jsonl(_formal_manifest_path(root));current=_manifest_index(rows)
    for old in baseline:
        key=str(old["sample_key"]);row=current.get(key)
        if row is None: raise ExperimentError(f"The r14 baseline sample was removed: {key}.")
        if key=="case-04:A:r3":
            prefix=[sha256_json(item) for item in old.get("attempts") or []]
            if [sha256_json(item) for item in (row.get("attempts") or [])[:len(prefix)]]!=prefix: raise ExperimentError("The r14 A-r3 attempt prefix changed.")
        elif sha256_json(row)!=sha256_json(old): raise ExperimentError(f"An accepted r14 row changed: {key}.")
    compatibility=_retry_fix_compatibility(rows,root=root)
    if sorted(compatibility.values(),key=lambda item:item["task_path"])!=capture.get("legacy_task_compatibility"): raise ExperimentError("The r14 compatibility table changed.")
    preflight=collect_preflight(root,hard=True,codex_managed=True,allow_formal_progress=True,legacy_runner_hash_allowlist=compatibility)
    preflight["legacy_failure_policy_allowlist"]=capture.get("legacy_failure_policy_attempt_sha256") or []
    if preflight.get("global_status")!="READY" or preflight.get("errors"): raise ExperimentError("Current hard preflight is not READY under r14.")
    _validate_formal_state(preflight,root=root);preflight["legacy_runner_hash_allowlist"]=compatibility
    return preflight


def _formal_expected_task(
    task: Mapping[str, Any],
    sample: Mapping[str, Any],
    preflight: Mapping[str, Any],
    *,
    root: Path,
    historical_audit: bool = False,
    legacy_runner_hash_allowlist: Mapping[str, Mapping[str, str]] | None = None,
) -> None:
    case_id, group, replicate = str(sample["case_id"]), str(sample["group"]), int(sample["replicate"])
    if (
        task.get("task_kind") != "formal"
        or task.get("batch") != "4B.3-F"
        or task.get("case_id") != case_id
        or task.get("group") != group
        or task.get("replicate") != replicate
    ):
        raise ExperimentError(f"Formal task identifiers or batch differ from the frozen sample {sample['sample_key']}.")
    if task.get("schema_version") == LEGACY_CODEX_TASK_SCHEMA_VERSION and not historical_audit:
        raise ExperimentError("Legacy schema-1 formal tasks are readable only as invalidated or superseded audit records.")
    if task.get("schema_version") == CODEX_TASK_SCHEMA_VERSION:
        verify_codex_task_prompt(task, str(task.get("prompt", "")))
    elif task.get("schema_version") != LEGACY_CODEX_TASK_SCHEMA_VERSION:
        raise ExperimentError("Formal task schema is unsupported.")
    plan = preflight["plans"][case_id]["plans"][group]
    expected_prompt = plan.get("prompt")
    protocol_revision = _formal_protocol_revision(str(sample["sample_key"]), root=root)
    if protocol_revision is not None and _task_attempt_number(task) > int(protocol_revision["supersedes_failure_attempt"]):
        expected_prompt = protocol_revision["prompt"]
    expected_output = _relative_path(
        _formal_task_output_path(case_id, group, replicate, _task_attempt_number(task), root=root),
        root=root,
    )
    if task.get("schema_version") == LEGACY_CODEX_TASK_SCHEMA_VERSION:
        expected_output = _relative_path(_output_path(case_id, group, replicate, root=root), root=root)
    if task.get("prompt") != expected_prompt:
        raise ExperimentError(f"Formal task prompt differs from the frozen prompt for {sample['sample_key']}.")
    if task.get("referenced_image_paths") != [str(path) for path in plan.get("referenced_image_paths", [])]:
        raise ExperimentError(f"Formal task ordered reference paths differ for {sample['sample_key']}.")
    if task.get("reference_ids") != list(plan.get("selected_reference_ids", [])):
        raise ExperimentError(f"Formal task ordered reference IDs differ for {sample['sample_key']}.")
    if task.get("expected_output_path") != expected_output:
        raise ExperimentError(f"Formal task expected output path differs for {sample['sample_key']}.")
    frozen_files = (task.get("frozen_input_hashes") or {}).get("files", {})
    if task.get("schema_version") == CODEX_TASK_SCHEMA_VERSION:
        runner_hash = frozen_files.get("scripts/run_style_regression.py")
        current_runner_hash = sha256_file(root / "scripts" / "run_style_regression.py")
        if runner_hash != current_runner_hash:
            task_path = _formal_task_path(case_id, group, replicate, _task_attempt_number(task), root=root)
            allowlisted = (legacy_runner_hash_allowlist or {}).get(str(task.get("task_sha256")))
            if not (
                isinstance(allowlisted, Mapping)
                and allowlisted.get("task_path") == _relative_path(task_path, root=root)
                and allowlisted.get("runner_sha256") == runner_hash
                and allowlisted.get("task_kind") == "formal"
                and allowlisted.get("task_file_sha256") == sha256_file(task_path)
            ):
                raise ExperimentError("Formal task does not freeze the current Batch 4B.3-T runner hash.")


def _validate_formal_state(
    preflight: Mapping[str, Any], *, root: Path = ROOT
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], int]:
    """Validate manifest, immutable task history, output hashes, and resume position."""
    manifest_path = _formal_manifest_path(root)
    rows = _load_jsonl(manifest_path)
    indexed = _manifest_index(rows)
    plan = _formal_sample_plan()
    expected_keys = [str(sample["sample_key"]) for sample in plan]
    if any(key not in expected_keys for key in indexed):
        raise ExperimentError("Formal manifest contains an unknown or non-formal sample.")
    if [str(row.get("sample_key")) for row in rows] != expected_keys[: len(rows)]:
        raise ExperimentError("Formal manifest rows are not a prefix of the frozen interleaved sample order.")

    referenced_task_paths: set[str] = set()
    legacy_runner_hash_allowlist = preflight.get("legacy_runner_hash_allowlist") or {}
    if not isinstance(legacy_runner_hash_allowlist, Mapping):
        raise ExperimentError("Formal continuation task compatibility map is invalid.")
    legacy_failure_policy_allowlist = set(preflight.get("legacy_failure_policy_allowlist") or [])
    seen_task_ids: set[str] = set()
    seen_output_hashes: set[str] = set()
    expected_outputs: set[str] = set()
    first_pending = len(plan)
    pending_started = False
    for position, sample in enumerate(plan):
        sample_key = str(sample["sample_key"])
        row = indexed.get(sample_key)
        if row is None:
            if first_pending == len(plan):
                first_pending = position
            pending_started = True
            continue
        if row.get("sample_key") != sample_key or any(
            row.get(field) != sample[field] for field in ("case_id", "group", "replicate")
        ):
            raise ExperimentError(f"Formal manifest identifiers conflict with frozen order at {sample_key}.")
        if (
            row.get("formal") is not True
            or row.get("pilot") is not False
            or row.get("execution_mode") != "codex-managed"
            or row.get("engine") != "Codex-managed"
        ):
            raise ExperimentError(f"Formal manifest metadata is invalid or crosses manifest boundaries for {sample_key}.")
        attempts = row.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise ExperimentError(f"Formal sample {sample_key} has no immutable task attempt history.")
        latest_status = attempts[-1].get("status") if isinstance(attempts[-1], Mapping) else None
        is_audit_only = latest_status in {"invalidated", "superseded"}
        if row.get("include_in_formal_analysis") is not (not is_audit_only):
            raise ExperimentError(f"Formal sample {sample_key} verdict-inclusion flag conflicts with its state.")
        for attempt_number, attempt in enumerate(attempts, start=1):
            if not isinstance(attempt, Mapping) or attempt.get("attempt") != attempt_number:
                raise ExperimentError(f"Formal sample {sample_key} attempt history is not sequential.")
            task_path = _formal_task_path(
                str(sample["case_id"]), str(sample["group"]), int(sample["replicate"]), attempt_number, root=root
            )
            relative_task_path = _relative_path(task_path, root=root)
            if attempt.get("task_path") != relative_task_path or relative_task_path in referenced_task_paths:
                raise ExperimentError(f"Formal task path is edited or duplicated for {sample_key}.")
            referenced_task_paths.add(relative_task_path)
            status = attempt.get("status")
            if status not in {"queued", "failed", "succeeded", "invalidated", "superseded"}:
                raise ExperimentError(f"Formal task attempt status is invalid for {sample_key}.")
            try:
                task = load_codex_task(
                    task_path,
                    root=root,
                    verify_frozen_inputs=status not in {"invalidated", "superseded"},
                    legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
                )
            except ExperimentError as exc:
                raise ExperimentError(f"Formal task is stale or edited for {sample_key}: {exc}") from exc
            expected_task_id = f"formal:{sample['case_id']}:{sample['group']}:r{sample['replicate']}:attempt-{attempt_number}"
            if task.get("task_id") != expected_task_id or task.get("task_id") in seen_task_ids:
                raise ExperimentError(f"Formal task ID is invalid or duplicated for {sample_key}.")
            seen_task_ids.add(str(task.get("task_id")))
            if attempt.get("task_id") != task.get("task_id") or attempt.get("task_sha256") != task.get("task_sha256"):
                raise ExperimentError(f"Formal task digest conflicts with attempt history for {sample_key}.")
            historical_audit = task.get("schema_version") == LEGACY_CODEX_TASK_SCHEMA_VERSION and status in {
                "invalidated", "superseded"
            }
            _formal_expected_task(
                task,
                sample,
                preflight,
                root=root,
                historical_audit=historical_audit,
                legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
            )
            if task.get("schema_version") == LEGACY_CODEX_TASK_SCHEMA_VERSION and not historical_audit:
                raise ExperimentError(f"Legacy formal task for {sample_key} cannot be executed or accepted.")
            if status == "failed":
                if (
                    not isinstance(attempt.get("failure_reason"), str)
                    or not attempt.get("failure_reason", "").strip()
                    or not isinstance(attempt.get("failure_kind"), str)
                ):
                    raise ExperimentError(f"Formal failure reason is missing for {sample_key}.")
                is_legacy_failure = sha256_json(attempt) in legacy_failure_policy_allowlist
                if not is_legacy_failure:
                    policy = classify_codex_failure(
                        str(attempt.get("failure_code", "imagegen_tool_error")),
                        str(attempt.get("failure_reason", "")),
                    )
                    prior_same_code = 0
                    for prior_attempt in attempts[:attempt_number]:
                        if prior_attempt.get("status") != "failed":
                            continue
                        prior_policy = classify_codex_failure(
                            str(prior_attempt.get("failure_code", "imagegen_tool_error")),
                            str(prior_attempt.get("failure_reason", "")),
                        )
                        if prior_policy["failure_code"] == policy["failure_code"]:
                            prior_same_code += 1
                    expected_retryable = bool(
                        policy["retryable"] and prior_same_code <= policy["max_new_attempts"]
                    )
                    if (
                        attempt.get("failure_policy_version") != FAILURE_POLICY_VERSION
                        or attempt.get("failure_kind") != policy["failure_kind"]
                        or attempt.get("failure_code") != policy["failure_code"]
                        or attempt.get("retryable") is not expected_retryable
                        or attempt.get("retry_allowed") is not expected_retryable
                        or attempt.get("next_action") != ("retry_after_backoff" if expected_retryable else "blocked")
                    ):
                        raise ExperimentError(f"Formal failure policy fields are invalid for {sample_key}.")
            if status == "invalidated":
                if (
                    sample_key != "case-01:A:r1"
                    or attempt_number != 1
                    or row.get("status") not in {"invalidated", "queued", "failed", "succeeded"}
                    or attempt.get("failure_kind") != "task_transport"
                    or attempt.get("failure_reason") != "prompt_encoding_corruption"
                    or attempt.get("excluded_from_verdict") is not True
                    or (
                        attempt_number == len(attempts)
                        and row.get("output_sha256") not in {None, attempt.get("output_sha256")}
                    )
                    or not attempt.get("output_sha256")
                ):
                    raise ExperimentError(f"Formal invalidation is not the recorded A-r1 prompt transport incident: {sample_key}.")
                output_path = _repo_path(str(task.get("expected_output_path", "")), root=root)
                if not output_path.is_file() or sha256_file(output_path) != attempt.get("output_sha256"):
                    raise ExperimentError(f"Invalidated audit output is missing or changed for {sample_key}.")
                expected_outputs.add(_relative_path(output_path, root=root))
                if attempt.get("output_sha256") in seen_output_hashes:
                    raise ExperimentError(f"Duplicate formal output hash is recorded for {sample_key}.")
                seen_output_hashes.add(str(attempt.get("output_sha256")))
            if status == "superseded":
                if (
                    sample_key != "case-01:B:r1"
                    or attempt_number != 1
                    or attempt.get("failure_kind") is not None
                    or attempt.get("generated_failure") is True
                    or row.get("status") not in {"superseded", "queued", "failed", "succeeded"}
                    or not str(attempt.get("superseded_reason", "")).strip()
                ):
                    raise ExperimentError(f"Formal supersession is not the recorded unexecuted B-r1 queue: {sample_key}.")
            if attempt_number > 1:
                previous_attempt = attempts[attempt_number - 2]
                if previous_attempt.get("status") in {"failed", "invalidated"}:
                    previous_is_legacy = sha256_json(previous_attempt) in legacy_failure_policy_allowlist
                    protocol_revision = _formal_protocol_revision(sample_key, root=root)
                    previous_is_authorized_protocol = bool(
                        protocol_revision is not None
                        and previous_attempt.get("attempt") == protocol_revision.get("supersedes_failure_attempt")
                        and previous_attempt.get("failure_code") == protocol_revision.get("superseded_failure_code")
                        and attempt.get("protocol_revision") == protocol_revision.get("revision")
                        and attempt.get("protocol_revision_sha256") == sha256_file(protocol_revision["path"])
                    )
                    if (
                        (
                            previous_attempt.get("retryable") is not True
                            and not previous_is_legacy
                            and not previous_is_authorized_protocol
                        )
                        or attempt.get("retry_of_attempt") != attempt_number - 1
                        or attempt.get("retry_reason") != previous_attempt.get("failure_reason")
                        or attempt.get("retry_failure_kind") != previous_attempt.get("failure_kind")
                    ):
                        raise ExperimentError(f"Formal retry is not linked to an allowlisted technical failure for {sample_key}.")
                elif previous_attempt.get("status") == "superseded":
                    if (
                        attempt.get("reissued_after_attempt") != attempt_number - 1
                        or attempt.get("reissue_reason") != previous_attempt.get("superseded_reason")
                    ):
                        raise ExperimentError(f"Formal reissue is not linked to the superseded queue for {sample_key}.")
                else:
                    raise ExperimentError(f"Formal retry history has no technical failure or superseded queue for {sample_key}.")
            if attempt_number < len(attempts) and status not in {"failed", "invalidated", "superseded"}:
                raise ExperimentError(f"Formal retries require a recorded technical failure or supersession for {sample_key}.")
            if status == "succeeded":
                if attempt.get("compliant") is not True:
                    raise ExperimentError(f"Formal success is not receipt-validated for {sample_key}.")
                output_path = _repo_path(str(task.get("expected_output_path", "")), root=root)
                source_path = Path(str(attempt.get("codex_generated_source_path", ""))).expanduser()
                receipt = verify_codex_execution_receipt(
                    task_path,
                    source_path,
                    root=root,
                    expected_receipt_path=str(attempt.get("receipt_path", "")),
                    expected_receipt_sha256=str(attempt.get("receipt_sha256", "")),
                    legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
                )
                if (
                    not output_path.is_file()
                    or sha256_file(output_path) != receipt.get("output_sha256")
                    or attempt.get("output_sha256") != receipt.get("output_sha256")
                    or row.get("output_sha256") != receipt.get("output_sha256")
                ):
                    raise ExperimentError(f"Completed formal output or receipt hash is missing or changed for {sample_key}.")
                with output_path.open("rb") as handle:
                    if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                        raise ExperimentError(f"Completed formal output is not a PNG for {sample_key}.")
                if receipt["output_sha256"] in seen_output_hashes:
                    raise ExperimentError(f"Duplicate formal output hash is recorded for {sample_key}.")
                seen_output_hashes.add(receipt["output_sha256"])
                expected_outputs.add(_relative_path(output_path, root=root))
                if attempt.get("receipt_path") != row.get("receipt_path") or attempt.get("receipt_sha256") != row.get("receipt_sha256"):
                    raise ExperimentError(f"Formal attempt receipt differs from its accepted manifest row for {sample_key}.")
        if row.get("status") != latest_status:
            raise ExperimentError(f"Formal manifest status differs from latest attempt for {sample_key}.")
        if latest_status in {"queued", "failed", "superseded"} and any(
            row.get(field) is not None
            for field in (
                "output_sha256",
                "output_size_bytes",
                "generated_at",
                "codex_generated_source_path",
                "codex_source_sha256",
                "receipt_path",
                "receipt_sha256",
            )
        ):
            raise ExperimentError(f"Uncompleted formal sample {sample_key} retains completed-output metadata.")
        latest_task_path = _repo_path(str(attempts[-1]["task_path"]), root=root)
        latest_task = load_codex_task(
            latest_task_path,
            root=root,
            verify_frozen_inputs=latest_status not in {"invalidated", "superseded"},
            legacy_runner_hash_allowlist=legacy_runner_hash_allowlist,
        )
        expected_current_output = _relative_path(
            _repo_path(str(latest_task["expected_output_path"]), root=root), root=root
        )
        if row.get("output_path") != expected_current_output:
            raise ExperimentError(f"Formal row output path differs from its latest immutable task for {sample_key}.")
        if latest_status in {"queued", "failed", "superseded"}:
            queued_output = _repo_path(str(latest_task["expected_output_path"]), root=root)
            if queued_output.exists():
                raise ExperimentError(f"Conflicting output exists for {latest_status} formal sample {sample_key}.")
        if latest_status == "succeeded":
            if pending_started:
                raise ExperimentError(f"Completed formal sample {sample_key} appears after the first pending sample.")
            first_pending = position + 1
        elif latest_status == "superseded":
            if first_pending == len(plan):
                first_pending = position
            pending_started = True
        else:
            if pending_started and not (sample_key == "case-01:B:r1" and latest_status == "superseded"):
                raise ExperimentError(f"Formal sample {sample_key} appears after the first pending sample.")
            if first_pending == len(plan):
                first_pending = position
            pending_started = True

    task_dir = _formal_task_dir(root)
    found_task_paths: set[str] = set()
    if task_dir.exists():
        for path in task_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() != ".json":
                raise ExperimentError(f"Unexpected file in immutable formal task exchange: {_relative_path(path, root=root)}")
            found_task_paths.add(_relative_path(path, root=root))
    if found_task_paths != referenced_task_paths:
        extra = sorted(found_task_paths - referenced_task_paths)
        missing = sorted(referenced_task_paths - found_task_paths)
        raise ExperimentError(f"Formal task exchange has duplicate, stale, or missing tasks; extra={extra}, missing={missing}.")

    output_dir = _style_regression_dir(root) / "outputs"
    actual_outputs = {
        _relative_path(path, root=root)
        for path in output_dir.rglob("*")
        if path.is_file()
    } if output_dir.exists() else set()
    if actual_outputs != expected_outputs:
        raise ExperimentError(
            "Formal outputs conflict with the manifest; "
            f"unrecorded={sorted(actual_outputs - expected_outputs)}, missing={sorted(expected_outputs - actual_outputs)}."
        )
    return rows, indexed, first_pending


def _create_formal_task(
    sample: Mapping[str, Any],
    preflight: Mapping[str, Any],
    *,
    attempt_number: int,
    previous_failure: Mapping[str, Any] | None = None,
    previous_superseded: Mapping[str, Any] | None = None,
    previous_record: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id, group, replicate = str(sample["case_id"]), str(sample["group"]), int(sample["replicate"])
    case = _case_by_id(preflight["cases_document"])[case_id]
    pair = preflight["plans"][case_id]
    plan = dict(pair["plans"][group])
    protocol_revision = _formal_protocol_revision(str(sample["sample_key"]), root=root)
    if protocol_revision is not None and attempt_number > int(protocol_revision["supersedes_failure_attempt"]):
        plan["prompt"] = protocol_revision["prompt"]
    references = pair["references_by_group"][group]
    if list(plan["selected_reference_ids"]) != [str(reference.get("reference_id")) for reference in references]:
        raise ExperimentError(f"Formal {sample['sample_key']} reference order differs from frozen selection.")
    context = pair["style_context"] if group in ("B", "C") else None
    if protocol_revision is not None and attempt_number > int(protocol_revision["supersedes_failure_attempt"]):
        prompt_file = protocol_revision["prompt_path"]
        context_file = _context_path(case_id, group, replicate, root=root) if context is not None else None
        base_file = _base_prompt_path(case_id, root=root)
        prompt_hash = sha256_file(prompt_file)
    else:
        prompt_file, context_file, base_file, prompt_hash = _persist_inputs(
            case, group, replicate, plan, context, root=root
        )
    selector_snapshot_path = _selection_path(case_id, root=root)
    output_path = _formal_task_output_path(case_id, group, replicate, attempt_number, root=root)
    task_path = _formal_task_path(case_id, group, replicate, attempt_number, root=root)
    capture_path = root / "evaluation" / "style-regression" / "environment" / R_FINAL_PREFLIGHT_ENVIRONMENT_PATH
    policy_hash = sha256_file(root / "runtime" / "style-policy.yaml")
    corrected_legacy = preflight.get("corrected_legacy") or _control_runtime_metadata(root)
    frozen_candidates = [
        prompt_file,
        base_file,
        selector_snapshot_path,
        root / "evaluation" / "style-regression" / "cases.yaml",
        _input_freeze_path(root),
        root / "scripts" / "run_style_regression.py",
        root / "scripts" / "reference_runtime.py",
        root / "scripts" / "arco_real_adapter.py",
        root / "runtime" / "generation.yaml",
        root / "runtime" / "style-policy.yaml",
        root / "character" / "assets.yaml",
        root / "character" / "style-baseline.yaml",
        _evaluation_path(case["external_reference"]["style_brief_path"], root=root),
        capture_path,
    ]
    if protocol_revision is not None and attempt_number > int(protocol_revision["supersedes_failure_attempt"]):
        frozen_candidates.extend([protocol_revision["path"], protocol_revision["prompt_path"]])
    if context_file is not None:
        frozen_candidates.append(context_file)
    frozen_candidates.extend(Path(reference["path"]) for reference in references)
    frozen_files: dict[str, str] = {}
    for frozen_path in frozen_candidates:
        resolved = frozen_path.resolve()
        try:
            relative_frozen_path = resolved.relative_to(root.resolve()).as_posix()
        except ValueError as exc:
            raise ExperimentError(f"Formal frozen input escapes repository: {frozen_path}") from exc
        if not resolved.is_file():
            raise ExperimentError(f"Formal frozen input is missing: {relative_frozen_path}")
        frozen_files[relative_frozen_path] = sha256_file(resolved)
    reference_hashes = [
        {"reference_id": str(reference.get("reference_id")), "path": str(reference["path"]), "sha256": _reference_hash(reference)}
        for reference in references
    ]
    frozen_hashes = {
        "compiled_prompt_file_sha256": prompt_hash,
        "compiled_prompt_text_sha256": hashlib.sha256(str(plan["prompt"]).encode("utf-8")).hexdigest(),
        "references": reference_hashes,
        "reference_snapshot_sha256": sha256_file(selector_snapshot_path),
        "resolved_style_context_sha256": sha256_file(context_file) if context_file is not None else None,
        "runtime_sha256": sha256_file(root / "scripts" / "reference_runtime.py") if group in ("B", "C") else corrected_legacy["runtime_sha256"],
        "generation_config_sha256": sha256_file(root / "runtime" / "generation.yaml"),
        "style_policy_sha256": policy_hash,
        "files": frozen_files,
    }
    task_id = f"formal:{case_id}:{group}:r{replicate}:attempt-{attempt_number}"
    task = build_codex_task(
        task_id=task_id,
        task_kind="formal",
        case_id=case_id,
        group=group,
        replicate=replicate,
        prompt=str(plan["prompt"]),
        referenced_image_paths=list(plan["referenced_image_paths"]),
        reference_ids=list(plan["selected_reference_ids"]),
        expected_output_path=_relative_path(output_path, root=root),
        frozen_input_hashes=frozen_hashes,
        batch="4B.3-F",
    )
    write_codex_task(task, path=task_path)
    attempt: dict[str, Any] = {
        "attempt": attempt_number,
        "task_id": task_id,
        "task_path": _relative_path(task_path, root=root),
        "task_sha256": task["task_sha256"],
        "output_path": task["expected_output_path"],
        "prompt_sha256_utf8": task["prompt_sha256_utf8"],
        "status": "queued",
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    if previous_failure is not None:
        attempt["retry_of_attempt"] = attempt_number - 1
        attempt["retry_reason"] = previous_failure["failure_reason"]
        attempt["retry_failure_kind"] = previous_failure["failure_kind"]
    if protocol_revision is not None and attempt_number > int(protocol_revision["supersedes_failure_attempt"]):
        attempt["protocol_revision"] = protocol_revision["revision"]
        attempt["protocol_revision_sha256"] = sha256_file(protocol_revision["path"])
    if previous_superseded is not None:
        attempt["reissued_after_attempt"] = attempt_number - 1
        attempt["reissue_reason"] = previous_superseded["superseded_reason"]
    record = dict(previous_record or {})
    if not record:
        metadata = _identity_and_external_metadata(references)
        record = {
            "sample_key": str(sample["sample_key"]),
            "experiment_id": "arco-style-transfer-v1-batch-4b.3f",
            "batch": "4B.3-F",
            "case_id": case_id,
            "group": group,
            "replicate": replicate,
            "runtime_type": "corrected_legacy" if group == "A" else "production",
            "runtime_sha256": frozen_hashes["runtime_sha256"],
            "image_transport_strategy": "referenced_image_paths",
            **metadata,
            "selected_reference_ids": list(plan["selected_reference_ids"]),
            "selected_reference_hashes": [_reference_hash(reference) for reference in references],
            "reference_snapshot_path": _relative_path(selector_snapshot_path, root=root),
            "reference_snapshot_sha256": sha256_file(selector_snapshot_path),
            "reference_roles": [reference.get("role") for reference in references],
            "reference_duties": [list(reference.get("duties") or reference.get("inherit") or []) for reference in references],
            "style_reference": {
                "reference_id": case["external_reference"]["reference_id"],
                "role": case["external_reference"]["role"],
                "duties": list(case["external_reference"]["duties"]),
                "style_axes": list(case["expected_relevant_style_axes"]),
                "style_priority": case["external_reference"]["style_priority"],
                "provenance": case["external_reference"]["provenance"],
                "sha256": case["external_reference"]["sha256"],
            },
            "resolved_style_context_path": _relative_path(context_file, root=root) if context_file else None,
            "resolved_style_context_sha256": sha256_file(context_file) if context_file else None,
            "style_context_hash": plan.get("style_context_hash"),
            "base_scene_prompt_path": _relative_path(base_file, root=root),
            "base_scene_prompt_sha256": sha256_file(base_file),
            "compiled_prompt_path": _relative_path(prompt_file, root=root),
            "compiled_prompt_sha256": prompt_hash,
            "hygiene_enabled": group == "C",
            "style_policy_sha256": policy_hash if group == "C" else None,
            "output_path": _relative_path(output_path, root=root),
            "formal": True,
            "pilot": False,
            "include_in_formal_analysis": True,
            "execution_mode": "codex-managed",
            "engine": "Codex-managed",
            "provider_payload_keys": ["prompt", "referenced_image_paths"],
            "attempts": [],
        }
    if previous_failure is not None:
        for stale_field in ("failure_kind", "failure_code", "failure_message", "failure_reason"):
            record.pop(stale_field, None)
    if previous_failure is not None or previous_superseded is not None:
        for stale_field in ("superseded_at", "superseded_reason"):
            record.pop(stale_field, None)
        record["excluded_from_verdict"] = False
    record["include_in_formal_analysis"] = True
    record["status"] = "queued"
    record["attempts"] = list(record.get("attempts", [])) + [attempt]
    record["task_path"] = attempt["task_path"]
    record["task_sha256"] = attempt["task_sha256"]
    record["output_path"] = task["expected_output_path"]
    record["prompt_sha256_exact"] = task["prompt_sha256"]
    record["prompt_sha256_utf8"] = task["prompt_sha256_utf8"]
    if protocol_revision is not None and attempt_number > int(protocol_revision["supersedes_failure_attempt"]):
        record["compiled_prompt_path"] = _relative_path(protocol_revision["prompt_path"], root=root)
        record["compiled_prompt_sha256"] = sha256_file(protocol_revision["prompt_path"])
        record["protocol_revision"] = protocol_revision["revision"]
        record["protocol_revision_sha256"] = sha256_file(protocol_revision["path"])
    record["reference_ids_ordered"] = list(task["reference_ids"])
    record["reference_paths_ordered"] = list(task["referenced_image_paths"])
    for stale_field in (
        "output_sha256",
        "output_size_bytes",
        "generated_at",
        "codex_generated_source_path",
        "codex_source_sha256",
        "receipt_path",
        "receipt_sha256",
    ):
        record.pop(stale_field, None)
    return task, record


def queue_next_formal_task(preflight: Mapping[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    """Reuse or create exactly the first pending immutable formal task."""
    preflight = _validate_formal_capture(root)
    if preflight.get("global_status") != "READY" or preflight.get("errors"):
        raise ExperimentError("Formal task exchange is gated on READY hard Preflight.")
    rows, indexed, pending_index = _validate_formal_state(preflight, root=root)
    plan = _formal_sample_plan()
    if pending_index >= len(plan):
        return {"status": "complete", "queued": False, "formal_sample_total": EXPECTED_SAMPLE_COUNT}
    sample = plan[pending_index]
    row = indexed.get(str(sample["sample_key"]))
    if row is not None and row.get("status") == "queued":
        latest = row["attempts"][-1]
        task_path = _repo_path(latest["task_path"], root=root)
        return {"status": "queued", "queued": False, "reused": True, "task_path": latest["task_path"], "task_sha256": latest["task_sha256"], "task_id": latest["task_id"]}
    previous_failure = None
    previous_superseded = None
    if row is not None:
        last_attempt = row["attempts"][-1]
        if last_attempt.get("status") in {"failed", "invalidated"}:
            previous_failure = last_attempt
            if not str(previous_failure.get("failure_reason", "")).strip():
                raise ExperimentError(f"Formal sample {sample['sample_key']} failed without a recorded reason.")
            if previous_failure.get("status") == "failed":
                policy = classify_codex_failure(
                    str(previous_failure.get("failure_code", "imagegen_tool_error")),
                    str(previous_failure.get("failure_reason", "")),
                )
                protocol_revision = _formal_protocol_revision(str(sample["sample_key"]), root=root)
                authorized_revision = bool(
                    protocol_revision is not None
                    and previous_failure.get("attempt") == protocol_revision.get("supersedes_failure_attempt")
                    and policy["failure_code"] == protocol_revision.get("superseded_failure_code")
                )
                if not authorized_revision and (
                    previous_failure.get("retryable") is not True or policy["retryable"] is not True
                ):
                    raise ExperimentError(f"Formal sample {sample['sample_key']} has a terminal failure and is not retryable.")
                same_code_failures = sum(
                    1
                    for historical_attempt in row["attempts"]
                    if historical_attempt.get("status") == "failed"
                    and classify_codex_failure(
                        str(historical_attempt.get("failure_code", "imagegen_tool_error")),
                        str(historical_attempt.get("failure_reason", "")),
                    )["failure_code"] == policy["failure_code"]
                )
                if not authorized_revision and same_code_failures > policy["max_new_attempts"]:
                    raise ExperimentError(f"Formal sample {sample['sample_key']} reached the {policy['failure_code']} retry limit.")
        elif last_attempt.get("status") == "superseded":
            previous_superseded = last_attempt
        else:
            raise ExperimentError(f"Formal sample {sample['sample_key']} is not eligible for a retry or reissue.")
    task, record = _create_formal_task(
        sample,
        preflight,
        attempt_number=len(row["attempts"]) + 1 if row is not None else 1,
        previous_failure=previous_failure,
        previous_superseded=previous_superseded,
        previous_record=row,
        root=root,
    )
    _upsert_manifest(record, path=_formal_manifest_path(root))
    return {
        "status": "queued",
        "queued": True,
        "reused": False,
        "task_path": record["task_path"],
        "task_sha256": task["task_sha256"],
        "task_id": task["task_id"],
        "sample_key": sample["sample_key"],
        "attempt": len(record["attempts"]),
        "formal_sample_total": sum(
            _compliant_formal_sample_counts(
                rows,
                root=root,
                legacy_runner_hash_allowlist=preflight.get("legacy_runner_hash_allowlist"),
            ).values()
        ),
    }


def formal_orchestration_status(*, root: Path = ROOT) -> dict[str, Any]:
    """Return the structured next action for the Codex-managed formal loop."""
    preflight = _validate_formal_capture(root)
    rows, indexed, pending_index = _validate_formal_state(preflight, root=root)
    counts = _compliant_formal_sample_counts(
        rows,
        root=root,
        legacy_runner_hash_allowlist=preflight.get("legacy_runner_hash_allowlist"),
    )
    total = sum(counts.values())
    plan = _formal_sample_plan()
    if pending_index >= len(plan):
        return {
            "status": "complete",
            "formal_sample_counts": counts,
            "formal_sample_total": total,
            "retry_allowed": False,
            "next_action": "complete",
        }
    sample = plan[pending_index]
    sample_key = str(sample["sample_key"])
    row = indexed.get(sample_key)
    result: dict[str, Any] = {
        "status": "pending",
        "sample_id": sample_key,
        "attempt": len(row.get("attempts", [])) + 1 if row else 1,
        "formal_sample_counts": counts,
        "formal_sample_total": total,
        "retry_allowed": True,
        "retry_after_seconds": 0,
        "next_action": "create_or_reuse_task",
    }
    if row and row.get("status") == "queued":
        latest = row["attempts"][-1]
        result.update(
            {
                "status": "queued",
                "attempt": latest["attempt"],
                "task_path": latest["task_path"],
                "next_action": "invoke_imagegen",
            }
        )
    elif row and row.get("status") == "failed":
        retry = codex_failure_retry_state(row["attempts"])
        result.update(
            {
                "status": "pending" if retry["retry_allowed"] else "blocked",
                "failure_code": retry["failure_code"],
                "failure_kind": retry["failure_kind"],
                "retry_allowed": retry["retry_allowed"],
                "retry_after_seconds": retry["retry_after_seconds"],
                "next_action": retry["next_action"],
            }
        )
    return result


def _codex_formal_manifest_record(
    task: Mapping[str, Any], task_path: Path, *, root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]], int, int]:
    if task.get("task_kind") != "formal" or task.get("batch") != "4B.3-F":
        raise ExperimentError("Codex formal result must reference a Batch 4B.3-F formal task.")
    preflight = _validate_formal_capture(root)
    rows, indexed, pending_index = _validate_formal_state(preflight, root=root)
    case_id, group, replicate = task.get("case_id"), task.get("group"), task.get("replicate")
    if case_id not in CASE_IDS or group not in GENERATED_GROUPS or not isinstance(replicate, int) or isinstance(replicate, bool):
        raise ExperimentError("Codex formal task identifiers are invalid.")
    sample_key = _sample_key(str(case_id), str(group), replicate)
    record = indexed.get(sample_key)
    if record is None or record.get("status") != "queued":
        raise ExperimentError(f"Codex formal task is not the queued first pending sample: {sample_key}.")
    plan = _formal_sample_plan()
    if pending_index >= len(plan) or plan[pending_index]["sample_key"] != sample_key:
        raise ExperimentError(f"Codex formal task is stale or out of order: {sample_key}.")
    matching_attempts = [
        (index, attempt)
        for index, attempt in enumerate(record["attempts"])
        if attempt.get("task_sha256") == task.get("task_sha256")
    ]
    if len(matching_attempts) != 1:
        raise ExperimentError("Codex formal task does not match exactly one immutable attempt record.")
    attempt_index, attempt = matching_attempts[0]
    if attempt_index != len(record["attempts"]) - 1 or attempt.get("status") != "queued":
        raise ExperimentError("Codex formal task attempt is no longer the active queued attempt.")
    if attempt.get("task_path") != _relative_path(task_path, root=root):
        raise ExperimentError("Codex formal task path differs from its immutable manifest record.")
    return record, rows, indexed, pending_index, attempt_index


def record_codex_formal_failure(
    task_path: Path,
    *,
    failure_kind: str,
    failure_code: str,
    failure_message: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    task = load_codex_task(task_path, root=root)
    record, _, _, _, attempt_index = _codex_formal_manifest_record(task, task_path, root=root)
    attempts = list(record["attempts"])
    attempt = dict(attempts[attempt_index])
    reason = failure_message.strip()
    if not isinstance(failure_kind, str) or not failure_kind.strip() or not reason:
        raise ExperimentError("Formal task failure requires a failure kind and non-empty reason.")
    policy = classify_codex_failure(failure_code, reason)
    if failure_kind != policy["failure_kind"]:
        raise ExperimentError(
            "Formal task failure kind conflicts with the failure-code policy: "
            f"{failure_kind} != {policy['failure_kind']}."
        )
    prior_failures = 0
    for historical_attempt in attempts[:attempt_index]:
        if historical_attempt.get("status") != "failed":
            continue
        try:
            historical_policy = classify_codex_failure(
                str(historical_attempt.get("failure_code", "imagegen_tool_error")),
                str(historical_attempt.get("failure_reason", "")),
            )
        except ExperimentError:
            continue
        if historical_policy["failure_code"] == policy["failure_code"]:
            prior_failures += 1
    failure_number = prior_failures + 1
    retry_allowed = bool(policy["retryable"] and failure_number <= policy["max_new_attempts"])
    retry_after_seconds = None
    if retry_allowed:
        backoff = policy["backoff_seconds"]
        retry_after_seconds = int(backoff[min(failure_number - 1, len(backoff) - 1)])
    attempt.update(
        {
            "status": "failed",
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "failure_policy_version": policy["failure_policy_version"],
            "failure_kind": policy["failure_kind"],
            "failure_code": policy["failure_code"],
            "failure_reason": policy["failure_reason"],
            "failure_number_for_code": failure_number,
            "retryable": retry_allowed,
            "retry_allowed": retry_allowed,
            "retry_after_seconds": retry_after_seconds,
            "next_action": "retry_after_backoff" if retry_allowed else "blocked",
        }
    )
    attempts[attempt_index] = attempt
    record["attempts"] = attempts
    record["status"] = "failed"
    record["failure_kind"] = policy["failure_kind"]
    record["failure_code"] = policy["failure_code"]
    record["failure_message"] = policy["failure_reason"]
    record["retry_allowed"] = retry_allowed
    record["retry_after_seconds"] = retry_after_seconds
    record["next_action"] = attempt["next_action"]
    _upsert_manifest(record, path=_formal_manifest_path(root))
    return record


def accept_codex_formal_output(
    task_path: Path, generated_path: Path | str, *, root: Path = ROOT
) -> dict[str, Any]:
    accepted_preflight = _validate_formal_capture(root)
    legacy_allowlist = accepted_preflight.get("legacy_runner_hash_allowlist")
    task = load_codex_task(
        task_path, root=root, require_utf8_schema=True,
        legacy_runner_hash_allowlist=legacy_allowlist,
    )
    record, _, _, _, attempt_index = _codex_formal_manifest_record(task, task_path, root=root)
    generated_source = Path(generated_path).expanduser().resolve(strict=False)
    existing_hashes: set[str] = set()
    for row in _load_jsonl(_formal_manifest_path(root)):
        for historical_attempt in row.get("attempts") or []:
            if historical_attempt.get("status") in {"succeeded", "invalidated"} and historical_attempt.get("output_sha256"):
                existing_hashes.add(str(historical_attempt["output_sha256"]))
    if generated_source.is_file() and sha256_file(generated_source) in existing_hashes:
        raise ExperimentError("Codex formal output duplicates an already accepted formal sample.")
    output = accept_codex_task_output(
        task_path, generated_path, root=root,
        legacy_runner_hash_allowlist=legacy_allowlist,
    )
    attempts = list(record["attempts"])
    attempt = dict(attempts[attempt_index])
    accepted_at = datetime.now(timezone.utc).isoformat()
    attempt.update(
        {
            "status": "succeeded",
            "accepted_at": accepted_at,
            "output_path": task["expected_output_path"],
            "output_sha256": output["output_sha256"],
            "output_size_bytes": output["size_bytes"],
            "codex_generated_source_path": str(output["source_path"]),
            "receipt_path": output["receipt_path"],
            "receipt_sha256": output["receipt_sha256"],
            "compliant": True,
            "include_in_formal_analysis": True,
        }
    )
    attempts[attempt_index] = attempt
    record["attempts"] = attempts
    record.update(
        {
            "status": "succeeded",
            "generated_at": accepted_at,
            "output_sha256": output["output_sha256"],
            "output_size_bytes": output["size_bytes"],
            "codex_generated_source_path": str(output["source_path"]),
            "codex_source_sha256": output["source_sha256"],
            "receipt_path": output["receipt_path"],
            "receipt_sha256": output["receipt_sha256"],
            "include_in_formal_analysis": True,
            "excluded_from_verdict": False,
        }
    )
    try:
        _upsert_manifest(record, path=_formal_manifest_path(root))
    except Exception:
        # Roll back only the output created by this acceptance attempt; a later
        # resume must never mistake an unmanifested file for completed data.
        if output["output_path"].is_file() and sha256_file(output["output_path"]) == output["output_sha256"]:
            output["output_path"].unlink()
        raise
    return record


def prepare_blind_review(root: Path = ROOT) -> int:
    evaluation_dir = root / "evaluation" / "style-regression"
    blind_map_path = evaluation_dir / "blind-map.private.json"
    records = _load_jsonl(evaluation_dir / "manifest.jsonl")
    indexed = _manifest_index(records)
    expected_keys = {
        _sample_key(case_id, group, replicate)
        for case_id in CASE_IDS
        for group in GROUPS
        for replicate in range(1, EXPECTED_REPLICATES + 1)
    }
    if set(indexed) != expected_keys:
        missing = sorted(expected_keys - set(indexed))
        extra = sorted(set(indexed) - expected_keys)
        raise ExperimentError(f"Blind review requires exactly 36 samples; missing={missing}, extra={extra}")
    for key, record in indexed.items():
        if record.get("status") != "succeeded":
            raise ExperimentError(f"Blind review blocked by non-successful sample {key}.")
        output = _repo_path(record["output_path"], root=root)
        if not output.is_file() or record.get("output_sha256") != sha256_file(output):
            raise ExperimentError(f"Blind review output missing or hash changed: {key}")

    if blind_map_path.exists():
        raise ExperimentError("Private blind map already exists; refusing to reshuffle an evaluated set.")
    private_blind_dir = evaluation_dir / "private-assets" / "blind-review"
    evaluation_forms_dir = evaluation_dir / "evaluations"
    for case_id in CASE_IDS:
        for index in range(1, EXPECTED_REPLICATES * len(GROUPS) + 1):
            if (evaluation_forms_dir / f"{case_id}-x{index:02d}.md").exists():
                raise ExperimentError("Evaluation forms already exist; refusing to reshuffle the blind set.")

    template = (evaluation_dir / "evaluation-template.md").read_text(encoding="utf-8")
    blind_map: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "samples": {},
    }
    blind_files: list[tuple[Path, Path]] = []
    form_files: list[tuple[Path, str]] = []
    for case_id in CASE_IDS:
        case_samples = [
            record
            for record in indexed.values()
            if record["case_id"] == case_id
        ]
        secrets.SystemRandom().shuffle(case_samples)
        for index, record in enumerate(case_samples, start=1):
            blind_id = f"{case_id}-x{index:02d}"
            source = _repo_path(record["output_path"], root=root)
            blind_path = private_blind_dir / f"{blind_id}.png"
            form_path = evaluation_forms_dir / f"{blind_id}.md"
            blind_files.append((source, blind_path))
            form_files.append(
                (
                    form_path,
                    template.replace("Sample:\n", f"Sample: {blind_id}\n", 1)
                    .replace("Case:\n", f"Case: {case_id}\n", 1)
                    .replace("Blind ID:\n", f"Blind ID: {blind_id}\n", 1),
                )
            )
            blind_map["samples"][blind_id] = {
                "case_id": case_id,
                "group": record["group"],
                "replicate": record["replicate"],
                "manifest_sample_key": record["sample_key"],
                "source_output_path": record["output_path"],
                "blind_image_path": _relative_path(blind_path, root=root),
            }

    for source, destination in blind_files:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for path, contents in form_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8", newline="\n")
    _write_json_atomic(blind_map_path, blind_map)
    return len(blind_files)


def _git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _runtime_hashes(root: Path, cases_document: Mapping[str, Any]) -> dict[str, Any]:
    fixture_dir = root / "scripts" / "fixtures" / "style_prompt"
    style_only = [
        path
        for path in fixture_dir.glob("*")
        if path.is_file() and (path.name.endswith(".input.json") or (path.name.endswith(".expected.txt") and ".hygiene." not in path.name))
    ]
    hygiene = [path for path in fixture_dir.glob("*.hygiene.expected.txt") if path.is_file()]
    file_paths = [
        "SKILL.md",
        "scripts/reference_runtime.py",
        "scripts/arco_real_adapter.py",
        "scripts/run_style_regression.py",
        "runtime/style-policy.yaml",
        "runtime/generation.yaml",
        "character/style-baseline.yaml",
        "character/identity.yaml",
        "character/assets.yaml",
        "variants/index.yaml",
        "variants/casual-outfit/variant.yaml",
        "evaluation/style-regression/cases.yaml",
        "evaluation/style-regression/prompts/base-scene.txt",
        "evaluation/style-regression/inputs-freeze.json",
        "evaluation/style-regression/reference-selection/selector-diff.json",
        "evaluation/style-regression/reference-selection/pre-selector-fix-evidence.json",
        "evaluation/style-regression/reference-selection/managed-selector-comparison.json",
        "evaluation/style-regression/control-runtime/corrected-legacy.json",
        "evaluation/style-regression/private-assets/historical/H/manifest.jsonl",
        "evaluation/style-regression/host-smoke/result.json",
        "evaluation/style-regression/host-smoke/codex-task.json",
        "evaluation/style-regression/pilot/runs/batch-4b3f/manifest.jsonl",
        "evaluation/style-regression/pilot/runs/batch-4b3f/tasks/case-01-A-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3f/tasks/case-01-B-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3f/tasks/case-01-C-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3t/manifest.jsonl",
        "evaluation/style-regression/pilot/runs/batch-4b3t/tasks/case-01-A-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3t/tasks/case-01-B-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3t/tasks/case-01-C-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3t/receipts/case-01-A-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3t/receipts/case-01-B-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3t/receipts/case-01-C-r1.json",
        "evaluation/style-regression/pilot/outputs/batch-4b3t/case-01/A-r1.png",
        "evaluation/style-regression/pilot/outputs/batch-4b3t/case-01/B-r1.png",
        "evaluation/style-regression/pilot/outputs/batch-4b3t/case-01/C-r1.png",
        "evaluation/style-regression/pilot/runs/batch-4b3t-r2/manifest.jsonl",
        "evaluation/style-regression/pilot/runs/batch-4b3t-r2/tasks/case-01-A-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3t-r2/tasks/case-01-B-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3t-r2/tasks/case-01-C-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3t-r2/receipts/case-01-A-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3t-r2/receipts/case-01-B-r1.json",
        "evaluation/style-regression/pilot/runs/batch-4b3t-r2/receipts/case-01-C-r1.json",
        "evaluation/style-regression/pilot/outputs/batch-4b3t-r2/case-01/A-r1.png",
        "evaluation/style-regression/pilot/outputs/batch-4b3t-r2/case-01/B-r1.png",
        "evaluation/style-regression/pilot/outputs/batch-4b3t-r2/case-01/C-r1.png",
    ]
    hashes: dict[str, Any] = {
        value: sha256_file(root / value) if (root / value).is_file() else None
        for value in file_paths
    }
    hashes["scripts/fixtures/style_prompt/batch3_style_only_tree"] = sha256_tree(style_only, root=root)
    hashes["scripts/fixtures/style_prompt/batch4a_hygiene_tree"] = sha256_tree(hygiene, root=root)
    hashes["scripts/test_files_tree"] = sha256_tree(list((root / "scripts").glob("test_*.py")), root=root)
    references: dict[str, str | None] = {}
    briefs: dict[str, str | None] = {}
    for case in cases_document.get("cases", []):
        external = case.get("external_reference") or {}
        try:
            path = _evaluation_path(external.get("path", ""), root=root)
            references[str(external.get("reference_id"))] = sha256_file(path) if path.is_file() else None
        except ExperimentError:
            references[str(external.get("reference_id"))] = None
        try:
            brief_path = _evaluation_path(external.get("style_brief_path", ""), root=root)
            briefs[str(external.get("reference_id"))] = sha256_file(brief_path) if brief_path.is_file() else None
        except ExperimentError:
            briefs[str(external.get("reference_id"))] = None
    hashes["style_reference_sha256"] = references
    hashes["style_brief_sha256"] = briefs
    hashes["reference_selection_snapshots"] = {
        case_id: {
            "frozen_with_style_reference": sha256_file(_selection_path(case_id, root=root))
            if _selection_path(case_id, root=root).is_file()
            else None,
            "current_managed_only": sha256_file(
                root / "evaluation" / "style-regression" / "reference-selection" / f"{case_id}.current-managed.json"
            )
            if (root / "evaluation" / "style-regression" / "reference-selection" / f"{case_id}.current-managed.json").is_file()
            else None,
        }
        for case_id in CASE_IDS
    }
    hashes["resolved_style_contexts"] = {
        case_id: {
            filename: sha256_file(_context_dir(case_id, root=root) / filename)
            if (_context_dir(case_id, root=root) / filename).is_file()
            else None
            for filename in ("resolved-style-context.json", "prompt-B.txt", "prompt-C.txt")
        }
        for case_id in CASE_IDS
    }
    hashes["inputs_freeze_sha256"] = (
        sha256_file(_input_freeze_path(root)) if _input_freeze_path(root).is_file() else None
    )
    frozen_artifacts: dict[str, str | None] = {}
    if _input_freeze_path(root).is_file():
        try:
            frozen_doc = _load_json(_input_freeze_path(root))
            frozen_files = frozen_doc.get("files")
            if isinstance(frozen_files, Mapping):
                frozen_artifacts = {
                    str(path): str(expected_hash)
                    for path, expected_hash in frozen_files.items()
                }
        except ExperimentError:
            frozen_artifacts = {}
    hashes["frozen_artifacts_sha256"] = frozen_artifacts
    hashes["external_reference_sha256"] = references
    history = cases_document.get("historical_baseline") or {}
    try:
        a_manifest = _evaluation_path(history.get("manifest_path", ""), root=root)
        hashes["historical_h_manifest_sha256"] = sha256_file(a_manifest) if a_manifest.is_file() else None
    except ExperimentError:
        hashes["historical_h_manifest_sha256"] = None
    return hashes


def _environment_checks_pass(environment: Mapping[str, Any]) -> bool:
    return all(
        isinstance(environment.get(key), Mapping)
        and environment[key].get("status") == "PASS"
        for key in ("tests", "corrected_legacy_tests", "py_compile")
    )


def write_completion_report(
    environment: Mapping[str, Any],
    preflight: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> Path:
    """Write the Batch 4B.3-T transport readiness record without a visual verdict."""
    codex_managed = environment.get("execution_mode") == "codex-managed"
    report_title = (
        "Batch 4B.3-T Codex-Managed Unicode Transport Readiness"
        if codex_managed
        else "Batch 4B.2-U Experiment Unblock and Pilot Record"
    )
    evaluation_dir = _style_regression_dir(root)
    cases_document = preflight.get("cases_document") or _load_yaml(evaluation_dir / "cases.yaml")
    case_confounds: dict[str, Any] = {}
    for evidence_name in ("selector-diff.json", "managed-selector-comparison.json"):
        evidence_path = evaluation_dir / "reference-selection" / evidence_name
        if evidence_path.is_file():
            evidence = _load_json(evidence_path)
            case_confounds = {
                item.get("case_id"): item
                for item in evidence.get("cases", [])
                if isinstance(item, Mapping)
            }
            if case_confounds:
                break
    pilot_manifest = _pilot_manifest_path(root)
    pilot_rows = _load_jsonl(pilot_manifest) if pilot_manifest.is_file() else []
    pilot_by_group = {row.get("group"): row for row in pilot_rows if row.get("case_id") == "case-01"}
    try:
        formal_rows = _load_jsonl(evaluation_dir / "manifest.jsonl")
    except ExperimentError:
        formal_rows = []
    formal_rows = [
        row for row in formal_rows
        if row.get("group") in GENERATED_GROUPS and not row.get("pilot")
    ]
    formal_counts = _compliant_formal_sample_counts(
        formal_rows,
        root=root,
        legacy_runner_hash_allowlist=preflight.get("legacy_runner_hash_allowlist"),
    )
    historical_h = preflight.get("historical_h") or _historical_group_h_summary(root, cases_document)
    provider_status = preflight.get("provider_binding") or {}
    smoke_path = evaluation_dir / "host-smoke" / "result.json"
    smoke_report = _load_json(smoke_path) if smoke_path.is_file() else {}
    control = preflight.get("corrected_legacy")
    if not isinstance(control, Mapping):
        try:
            control = _control_runtime_metadata(root)
        except ExperimentError:
            control = {}
    current_runtime_hashes = {
        "scripts/reference_runtime.py": sha256_file(root / "scripts" / "reference_runtime.py"),
        "scripts/arco_real_adapter.py": sha256_file(root / "scripts" / "arco_real_adapter.py"),
        "runtime/generation.yaml": sha256_file(root / "runtime" / "generation.yaml"),
    }
    implementation_hashes = {
        "scripts/run_style_regression.py": sha256_file(root / "scripts" / "run_style_regression.py"),
        "runtime/style-policy.yaml": sha256_file(root / "runtime" / "style-policy.yaml"),
    }
    baseline_runtime_hashes = (
        (control.get("main_workspace_at_batch_start") or {}).get("runtime_file_sha256", {})
        if isinstance(control, Mapping)
        else {}
    )
    baseline_environment_path = evaluation_dir / "environment.json"
    baseline_environment = _load_json(baseline_environment_path) if baseline_environment_path.is_file() else {}
    baseline_policy_hash = (baseline_environment.get("hashes") or {}).get("runtime/style-policy.yaml")
    style_policy_unchanged = bool(baseline_policy_hash) and implementation_hashes["runtime/style-policy.yaml"] == baseline_policy_hash
    runtime_unchanged = bool(baseline_runtime_hashes) and all(
        current_runtime_hashes.get(path) == expected
        for path, expected in baseline_runtime_hashes.items()
    )
    all_cases_ready = all(
        (preflight.get("case_statuses") or {}).get(case_id, {}).get("status") == "READY"
        for case_id in CASE_IDS
    )
    pilot_pass = (
        len(pilot_rows) == len(GENERATED_GROUPS)
        and set(pilot_by_group) == set(GENERATED_GROUPS)
        and all(
            pilot_by_group[group].get("status") == "succeeded"
            and pilot_by_group[group].get("pilot") is True
            and pilot_by_group[group].get("formal") is False
            and pilot_by_group[group].get("include_in_formal_analysis") is False
            and pilot_by_group[group].get("selector_parity") is True
            and pilot_by_group[group].get("scene_parity") is True
            and pilot_by_group[group].get("bc_context_parity") is True
            and pilot_by_group[group].get("bc_prompt_hygiene_only") is True
            and pilot_by_group[group].get("provider_payload_keys") == ["prompt", "referenced_image_paths"]
            and pilot_by_group[group].get("receipt_path")
            and pilot_by_group[group].get("receipt_sha256")
            for group in GENERATED_GROUPS
        )
    )
    formal_history_errors = _validate_pre_capture_formal_history(root)
    formal_zero = sum(formal_counts.values()) == 0 and not formal_history_errors
    experiment_ready = (
        preflight.get("global_status") == "READY"
        and all_cases_ready
        and pilot_pass
        and formal_zero
        and runtime_unchanged
        and style_policy_unchanged
        and _environment_checks_pass(environment)
    )
    status = "READY" if experiment_ready else "BLOCKED"
    lines = [
        f"# {report_title}",
        "",
        f"**Experiment status: {status}.** READY requires all four hard Preflight cases and the three receipt-validated Case 01 A/B/C Pilot runs to pass.",
        "",
        f"Main HEAD at Batch 4B.3-F start: {control.get('main_workspace_at_batch_start', {}).get('head_commit')}.",
        f"Current HEAD: {_git_output(root, 'rev-parse', 'HEAD')}; main worktree dirty: {str(bool(_git_output(root, 'status', '--porcelain=v1'))).lower()}.",
        f"Corrected Legacy worktree: {control.get('worktree_path')}; revision {control.get('selector_patch_revision')}; clean: {control.get('worktree_state') == 'clean'}.",
        f"Corrected Legacy patch SHA-256: {control.get('selector_patch_sha256')}; Runtime SHA-256: {control.get('runtime_sha256')}; runtime bundle SHA-256: {control.get('runtime_bundle_sha256')}.",
        "Corrected Legacy stale adapter expectation fixed: yes. Selector implementation changed: no.",
        "",
        "## Reference, context, and parity",
        "",
        f"Style Reference manifest: {('evaluation/style-regression/reference-selection/style-reference-manifest.json, SHA-256 ' + sha256_file(evaluation_dir / 'reference-selection' / 'style-reference-manifest.json')) if (evaluation_dir / 'reference-selection' / 'style-reference-manifest.json').is_file() else 'not frozen'}.",
        "",
        "| Case | Reference SHA-256 | Provenance | Duties | Axes | Priority | Brief SHA-256 | Context SHA-256 | Selector parity | Scene parity | B/C Context parity | B/C Hygiene diff | Historical confound |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for case in cases_document.get("cases", []):
        case_id = case.get("case_id")
        external = case.get("external_reference") or {}
        context_path = _context_dir(str(case_id), root=root) / "resolved-style-context.json"
        context_hash = sha256_file(context_path) if context_path.is_file() else "not frozen"
        pair = (preflight.get("plans") or {}).get(case_id, {})
        parity = "PASS" if pair.get("selector_parity") is True else "NOT VERIFIED"
        case_plans = pair.get("plans") or {}
        scene = compose_scene_prompt(case)
        scene_parity = (
            "PASS"
            if set(case_plans) == set(GROUPS)
            and all(scene in case_plans[group].get("prompt", "") for group in GROUPS)
            else "NOT VERIFIED"
        )
        hygiene_parity = (
            "PASS"
            if case_plans.get("C", {}).get("prompt")
            == f"{case_plans.get('B', {}).get('prompt', '')}\n\n{pair.get('hygiene_block', '')}"
            and case_plans.get("B", {}).get("prompt")
            else "NOT VERIFIED"
        )
        bc_context_parity = (
            "PASS"
            if case_plans.get("B", {}).get("style_context_hash")
            == case_plans.get("C", {}).get("style_context_hash")
            and case_plans.get("B", {}).get("style_context_hash")
            == (sha256_json(pair.get("style_context")) if pair.get("style_context") is not None else None)
            else "NOT VERIFIED"
        )
        confound = case_confounds.get(case_id, {}).get("selector_confound", "not recorded")
        axes = ", ".join(case.get("expected_relevant_style_axes") or []) or "not recorded"
        duties = ", ".join(external.get("duties") or []) or "not recorded"
        lines.append(
            f"| {case_id} | {external.get('sha256') or 'not frozen'} | {external.get('provenance') or 'not recorded'} | "
            f"{duties} | {axes} | {external.get('style_priority') or 'not recorded'} | "
            f"{external.get('style_brief_sha256') or 'not frozen'} | {context_hash} | "
            f"{parity} | {scene_parity} | {bc_context_parity} | {hygiene_parity} | {confound} |"
        )
    lines.extend(
        [
            "",
            "The four recorded historical selector confounds remain true: the pre-fix selection included identity-p01-crop, which the corrected selector excludes for upper_body. Group H is optional historical context, has no known manifest or samples, and is excluded from the verdict.",
            "",
            f"Group H: available {historical_h.get('available')}, samples {historical_h.get('sample_count', 0)}, provenance {historical_h.get('provenance_status')}; verdict excluded.",
            "",
            "## Execution, Preflight, and Pilot",
            "",
            (
                f"Engine: Codex-managed; built-in model ID: not exposed; reference-free Smoke status {provider_status.get('smoke_status', 'NOT RUN')} "
                f"(smoke={smoke_report.get('smoke', False)}, pilot={smoke_report.get('pilot', False)}, formal={smoke_report.get('formal', False)}); "
                f"Pilot successes {sum(1 for row in pilot_rows if row.get('status') == 'succeeded')}/3; formal samples {sum(formal_counts.values())}/{EXPECTED_SAMPLE_COUNT}; "
                f"Smoke prompt SHA-256 {smoke_report.get('prompt_sha256', 'not run')}; Smoke output SHA-256 {smoke_report.get('output_sha256', '—')}."
                if codex_managed
                else f"Host binding: {provider_status.get('binding')}; import/signature {provider_status.get('available', False)}; reference-free smoke {smoke_report.get('smoke', False)}; pilot {smoke_report.get('pilot', False)}; formal {smoke_report.get('formal', False)}; status {provider_status.get('smoke_status', 'NOT RUN')}; prompt SHA-256 {smoke_report.get('prompt_sha256', 'not run')}; output SHA-256 {smoke_report.get('output_sha256', '—')}."
            ),
            f"Hard Preflight: {preflight.get('global_status', 'BLOCKED')}. Production cases READY: {sum(1 for case_id in CASE_IDS if (preflight.get('case_statuses') or {}).get(case_id, {}).get('status') == 'READY')}/4.",
            "",
            "| Pilot group | Status | Prompt SHA-256 | Context SHA-256 | Reference snapshot SHA-256 | Output SHA-256 | Selector parity | Scene parity | B/C context | Hygiene-only delta | Payload keys | Formal analysis |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for group in GENERATED_GROUPS:
        row = pilot_by_group.get(group, {})
        lines.append(
            f"| {group} | {row.get('status', 'not run')} | "
            f"{row.get('compiled_prompt_sha256', '—')} | "
            f"{row.get('resolved_style_context_sha256') or '—'} | "
            f"{row.get('reference_snapshot_sha256', '—')} | "
            f"{row.get('output_sha256', '—')} | "
            f"{row.get('selector_parity', False)} | "
            f"{row.get('scene_parity', False)} | "
            f"{row.get('bc_context_parity', False)} | "
            f"{row.get('bc_prompt_hygiene_only', False)} | "
            f"{row.get('provider_payload_keys', '—')} | "
            f"{row.get('include_in_formal_analysis', False)} |"
        )
    lines.extend(
        [
            "",
            f"Formal A/B/C compliant sample count: **{sum(formal_counts.values())}/{EXPECTED_SAMPLE_COUNT}** "
            f"(A {formal_counts['A']}, B {formal_counts['B']}, C {formal_counts['C']}). Pilot rows are excluded.",
            "Invalid technical attempts: 1 (`case-01:A:r1` attempt 1, task_transport/prompt_encoding_corruption); excluded from the compliant count.",
            f"Preserved legacy formal history validated: {not formal_history_errors}.",
            *([f"Formal history blocker: {error}" for error in formal_history_errors] if formal_history_errors else []),
            "",
            "## Production runtime integrity",
            "",
            f"Production Style Runtime unchanged: **{current_runtime_hashes['scripts/reference_runtime.py'] == baseline_runtime_hashes.get('scripts/reference_runtime.py')}**. ArcoRealAdapter unchanged: **{current_runtime_hashes['scripts/arco_real_adapter.py'] == baseline_runtime_hashes.get('scripts/arco_real_adapter.py')}**. Provider payload schema file runtime/generation.yaml unchanged: **{current_runtime_hashes['runtime/generation.yaml'] == baseline_runtime_hashes.get('runtime/generation.yaml')}**. Rendering Hygiene policy unchanged: **{style_policy_unchanged}**.",
            "",
            "| File | SHA-256 at Batch 4B.2 start | Current SHA-256 |",
            "|---|---|---|",
        ]
    )
    for path, current_hash in current_runtime_hashes.items():
        lines.append(f"| {path} | {baseline_runtime_hashes.get(path, 'not recorded')} | {current_hash} |")
    lines.extend(["", "| Additional implementation evidence | Start SHA-256 | Current SHA-256 | Unchanged |", "|---|---|---|---|"])
    for path, current_hash in implementation_hashes.items():
        baseline_hash = baseline_policy_hash if path == "runtime/style-policy.yaml" else "implementation under test"
        unchanged = style_policy_unchanged if path == "runtime/style-policy.yaml" else "—"
        lines.append(f"| {path} | {baseline_hash} | {current_hash} | {unchanged} |")
    if environment.get("tests"):
        lines.extend(
            [
                "",
                f"Full unittest suite: {environment['tests'].get('count')} tests, "
                f"{environment['tests'].get('failures')} failures, {environment['tests'].get('errors')} errors "
                f"({environment['tests'].get('status')}).",
                f"py_compile: {environment.get('py_compile', {}).get('status', 'not recorded')}.",
            ]
        )
    if environment.get("corrected_legacy_tests"):
        legacy_tests = environment["corrected_legacy_tests"]
        lines.append(
            f"Corrected Legacy relevant tests: {legacy_tests.get('count')} tests, "
            f"{legacy_tests.get('failures')} failures, {legacy_tests.get('errors')} errors "
            f"({legacy_tests.get('status')})."
        )
    lines.extend(["", "## Preflight blockers", ""])
    blockers = preflight.get("errors") or []
    lines.extend(f"- {blocker}" for blocker in blockers)
    if not blockers:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "Visual verdict: NOT DETERMINED. Formal samples: 0/36. No formal generation, visual evaluation, or Phase 2 work was started. Batch 4B.3 formal task export may start from the first planned sample only after this capture reaches READY.",
            f"Required final checks passed: {_environment_checks_pass(environment)} (production tests, corrected Legacy tests, py_compile).",
            "",
        ]
    )
    report_path = (
        root / "evaluation" / "style-regression" / R_COMPLETION_REPORT_PATH
        if codex_managed
        else root / COMPLETION_REPORT_PATH.relative_to(ROOT)
    )
    report_contents = "\n".join(lines) + "\n"
    if report_path.exists():
        if report_path.read_text(encoding="utf-8") != report_contents:
            raise ExperimentError(f"Batch 4B completion report already exists with different contents: {report_path}")
    else:
        report_path.write_text(report_contents, encoding="utf-8", newline="\n")
    return report_path


def freeze_environment(
    root: Path = ROOT, *, provider_binding: str | None = None, codex_managed: bool = False
) -> dict[str, Any]:
    """Run required checks and write a new final-preflight revision record."""
    evaluation_dir = _style_regression_dir(root)
    history_dir = evaluation_dir / "environment"
    initial_environment = evaluation_dir / "environment.json"
    initial_archive = history_dir / "initial-post-selector-fix.json"
    if codex_managed and provider_binding:
        raise ExperimentError("Codex-managed finalization cannot use a provider binding.")
    if codex_managed:
        _require_utf8_execution_environment()
    final_capture_path = history_dir / (
        R_FINAL_PREFLIGHT_ENVIRONMENT_PATH if codex_managed else FINAL_PREFLIGHT_ENVIRONMENT_PATH.name
    )
    if final_capture_path.exists():
        raise ExperimentError("Batch 4B final preflight record already exists; refusing to overwrite captured history.")
    history_dir.mkdir(parents=True, exist_ok=True)
    if initial_environment.is_file():
        source_bytes = initial_environment.read_bytes()
        if initial_archive.exists() and initial_archive.read_bytes() != source_bytes:
            raise ExperimentError(
                "The archived initial post-selector-fix environment differs from environment.json; refusing to overwrite history."
            )
        if not initial_archive.exists():
            initial_archive.write_bytes(source_bytes)
    elif not initial_archive.is_file():
        raise ExperimentError("The initial post-selector-fix environment.json capture is missing.")
    corrected_legacy = _control_runtime_metadata(root)
    corrected_legacy_root = Path(corrected_legacy["worktree_path"]).resolve()
    utf8_environment = os.environ.copy()
    utf8_environment["PYTHONUTF8"] = "1"
    utf8_environment["PYTHONIOENCODING"] = "utf-8"
    legacy_test_command = [
        sys.executable,
        "-m",
        "unittest",
        "scripts.test_reference_runtime",
        "scripts.test_arco_real_adapter",
    ]
    legacy_test_result = subprocess.run(
        legacy_test_command,
        cwd=corrected_legacy_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=utf8_environment,
    )
    legacy_test_output = legacy_test_result.stdout + legacy_test_result.stderr
    legacy_count_match = re.search(r"Ran (\d+) tests?", legacy_test_output)
    legacy_summary_match = re.search(r"FAILED \(failures=(\d+), errors=(\d+)\)", legacy_test_output)
    legacy_test_count = int(legacy_count_match.group(1)) if legacy_count_match else None
    legacy_failures, legacy_errors = (
        (int(legacy_summary_match.group(1)), int(legacy_summary_match.group(2)))
        if legacy_summary_match
        else (0, 0)
    )
    if legacy_test_result.returncode != 0 or legacy_test_count is None:
        raise ExperimentError(
            "Corrected Legacy relevant unittest suite failed or could not be parsed:\n"
            + legacy_test_output[-6000:]
        )
    test_command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "scripts",
        "-p",
        "test_*.py",
    ]
    test_result = subprocess.run(
        test_command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=utf8_environment,
    )
    test_output = test_result.stdout + test_result.stderr
    count_match = re.search(r"Ran (\d+) tests?", test_output)
    summary_match = re.search(r"FAILED \(failures=(\d+), errors=(\d+)\)", test_output)
    test_count = int(count_match.group(1)) if count_match else None
    failures, errors = (int(summary_match.group(1)), int(summary_match.group(2))) if summary_match else (0, 0)
    if test_result.returncode != 0 or test_count is None:
        raise ExperimentError("Full unittest baseline failed or could not be parsed:\n" + test_output[-6000:])

    compile_files = [
        sys.executable,
        "-m",
        "py_compile",
        "scripts/reference_runtime.py",
        "scripts/arco_real_adapter.py",
        "scripts/run_style_regression.py",
        str(corrected_legacy_root / "scripts" / "reference_runtime.py"),
        str(corrected_legacy_root / "scripts" / "arco_real_adapter.py"),
    ]
    py_compile_paths = [
        "scripts/reference_runtime.py",
        "scripts/arco_real_adapter.py",
        "scripts/run_style_regression.py",
        str(corrected_legacy_root / "scripts" / "reference_runtime.py"),
        str(corrected_legacy_root / "scripts" / "arco_real_adapter.py"),
    ]
    host_module_path: str | None = None
    if provider_binding:
        try:
            provider = _load_provider_callable(provider_binding)
            provider_module = importlib.import_module(provider.__module__)
            module_file = getattr(provider_module, "__file__", None)
            if isinstance(module_file, str) and module_file.endswith(".py"):
                host_module_path = str(Path(module_file).resolve())
                compile_files.append(host_module_path)
                py_compile_paths.append(host_module_path)
        except ExperimentError:
            # The failed callable import is recorded as a hard-preflight blocker below.
            pass
    compile_result = subprocess.run(
        compile_files,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=utf8_environment,
    )
    if compile_result.returncode != 0:
        raise ExperimentError("py_compile baseline failed:\n" + compile_result.stdout + compile_result.stderr)

    cases_document = _load_yaml(root / "evaluation" / "style-regression" / "cases.yaml")
    cases = cases_document.get("cases") or []
    if cases:
        _write_frozen_text(
            root / "evaluation" / "style-regression" / "prompts" / "base-scene.txt",
            compose_scene_prompt(cases[0]),
        )
    preflight = collect_preflight(
        root, hard=True, provider_binding=provider_binding, codex_managed=codex_managed
    )
    preflight_report = write_preflight_report(preflight, root=root)

    porcelain_result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    # Preserve the two leading status columns; stripping them shifts paths that
    # begin with a dot (for example, `.gitignore`).
    porcelain = porcelain_result.stdout.rstrip("\r\n")
    branch_status = _git_output(root, "status", "--short", "--branch")
    dirty_paths = [line[3:] for line in porcelain.splitlines() if len(line) >= 4]
    hashes = _runtime_hashes(root, cases_document)
    if host_module_path:
        hashes[f"host_binding_module:{host_module_path}"] = sha256_file(Path(host_module_path))
    selector_comparison_path = evaluation_dir / "reference-selection" / "managed-selector-comparison.json"
    selector_comparison = _load_json(selector_comparison_path) if selector_comparison_path.is_file() else {"cases": []}
    selector_confounds = {
        item.get("case_id"): item.get("selector_confound")
        for item in selector_comparison.get("cases", [])
        if isinstance(item, Mapping)
    }
    environment = {
        "schema_version": 1,
        "experiment_id": cases_document.get("experiment_id"),
        "record_kind": "batch-4b3t-final-preflight-capture" if codex_managed else "final-preflight-capture",
        "execution_mode": "codex-managed" if codex_managed else "provider-binding",
        "engine": "Codex-managed" if codex_managed else "host-provider",
        "inputs_frozen": _input_freeze_path(root).is_file(),
        "input_freeze_sha256": (
            sha256_file(_input_freeze_path(root)) if _input_freeze_path(root).is_file() else None
        ),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit_sha": _git_output(root, "rev-parse", "HEAD"),
        "worktree_clean": not bool(porcelain),
        "git_status_short": branch_status,
        "dirty_paths": dirty_paths,
        "tests": {
            "command": "python -m unittest discover -s scripts -p \"test_*.py\"",
            "count": test_count,
            "failures": failures,
            "errors": errors,
            "status": "PASS" if failures == 0 and errors == 0 else "FAIL",
        },
        "corrected_legacy_tests": {
            "command": "python -m unittest scripts.test_reference_runtime scripts.test_arco_real_adapter",
            "count": legacy_test_count,
            "failures": legacy_failures,
            "errors": legacy_errors,
            "status": "PASS" if legacy_failures == 0 and legacy_errors == 0 else "FAIL",
            "revision": corrected_legacy["selector_patch_revision"],
            "patch_sha256": corrected_legacy["selector_patch_sha256"],
        },
        "py_compile": {
            "files": py_compile_paths,
            "status": "PASS",
        },
        "hashes": hashes,
        "selector_confounds": selector_confounds,
        "preflight_report": {
            "path": f"evaluation/style-regression/{R_PREFLIGHT_JSON_PATH}",
            "sha256": sha256_file(_preflight_report_paths(root)[0]),
            "status": preflight_report["status"],
        },
        "initial_post_selector_fix_environment": {
            "path": "evaluation/style-regression/environment/initial-post-selector-fix.json",
            "sha256": sha256_file(initial_archive),
            "source_path": "evaluation/style-regression/environment.json",
        },
        "preflight_runtime_fix": {
            "issue": "The reference selector included published assets whose excluded_for listed the requested exposure profile.",
            "fix": "select_references now omits profile-excluded assets before priority and coverage selection.",
            "regression_checks": [
                "test_selector_skips_assets_excluded_for_requested_exposure_profile",
                "test_published_selector_contracts_reach_adapter_read_only",
            ],
        },
        "hard_preflight_ready": preflight_report["status"] == "READY",
        "experiment_ready": False,
        "blocking_inputs": sorted(set(preflight["errors"])),
        "provider_binding": {
            "binding": None if codex_managed else provider_binding,
            "host_binding_available": provider_binding is not None and preflight["provider_binding"].get("available") is True,
            "codex_managed": codex_managed,
            "engine": "Codex-managed" if codex_managed else None,
            "host_module_path": host_module_path,
            "required_callable_signature": None if codex_managed else "builtin_image_gen(*, prompt: str, referenced_image_paths: list[str])",
        },
        "codex_prompt_transport": {
            "task_schema_version": CODEX_TASK_SCHEMA_VERSION,
            "prompt_encoding": "utf-8",
            "prompt_sha256_field": "prompt_sha256_utf8",
            "envelope": "ASCII JSON with strict Base64 UTF-8 prompt bytes",
            "execution_receipt_required_for_pilot_and_formal": True,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        },
        "formal_baseline": {
            "compliant_counts": {group: 0 for group in GENERATED_GROUPS},
            "compliant_total": 0,
            "invalid_technical_attempts": 1,
            "next_pending_sample": "case-01:A:r1 attempt 2",
        },
    }
    if _pilot_artifacts_present(root):
        completion_report = write_completion_report(environment, preflight, root=root)
        environment["experiment_ready"] = "**Experiment status: READY.**" in completion_report.read_text(encoding="utf-8")
        environment["completion_report"] = {
            "path": _relative_path(completion_report, root=root),
            "sha256": sha256_file(completion_report),
        }
    else:
        environment["experiment_ready"] = False
        environment["completion_report"] = None
    _write_json_atomic(final_capture_path, environment)
    return environment


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true", help="Validate every case and A/B/C selector parity; never generate.")
    modes.add_argument("--generate", action="store_true", help="Run formal samples through the configured Codex task exchange or legacy host binding.")
    modes.add_argument("--prepare-blind-review", action="store_true", help="Create private randomized blind copies after all 36 samples succeed.")
    modes.add_argument("--freeze-environment", action="store_true", help="Run tests/py_compile and record final preflight history without replacing environment.json.")
    modes.add_argument("--freeze-inputs", action="store_true", help="Freeze supplied Primary refs, Style Briefs, selector snapshots, contexts, and B/C prompts.")
    modes.add_argument("--preflight", action="store_true", help="Run the hard all-case READY/BLOCKED gate and write its report.")
    modes.add_argument("--host-smoke", action="store_true", help="Run the reference-free host transport smoke test once and record its output.")
    modes.add_argument("--pilot", action="store_true", help="After all cases are READY, run the isolated Case 01 A/B/C Pilot into the current pilot run.")
    modes.add_argument("--codex-smoke-task", action="store_true", help="Export the immutable reference-free Codex smoke task.")
    modes.add_argument("--codex-task-envelope", metavar="TASK_JSON", help="Emit an ASCII-only Base64 UTF-8 envelope for one immutable Codex task.")
    modes.add_argument("--verify-codex-prompt", metavar="TASK_JSON", help="Strictly decode and hash-check the exact UTF-8 prompt immediately before Codex generation.")
    modes.add_argument("--record-codex-task-receipt", metavar="TASK_JSON", help="Write a write-once execution receipt after Codex generation.")
    modes.add_argument("--formal-status", action="store_true", help="Validate formal audit state and show the first pending sample without creating a task.")
    modes.add_argument("--capture-formal-continuation", action="store_true", help="After passing integrity tests, freeze the existing one-of-36 checkpoint for formal resume.")
    modes.add_argument("--capture-formal-retry-fix", action="store_true", help="Freeze the append-only r5 retry-policy checkpoint at the existing 31/36 state.")
    modes.add_argument("--migrate-legacy-formal-transport", action="store_true", help="Quarantine the known A-r1 prompt corruption and supersede the unexecuted legacy B-r1 task.")
    modes.add_argument("--accept-codex-smoke-output", metavar="GENERATED_PNG", help="Accept the built-in Codex smoke image file.")
    modes.add_argument("--accept-codex-task", metavar="TASK_JSON", help="Accept one Codex Pilot or formal result for an immutable task.")
    modes.add_argument("--fail-codex-task", metavar="TASK_JSON", help="Record one failed Codex Pilot or formal task.")
    parser.add_argument("--case", choices=CASE_IDS, action="append", help="Limit to a Case; repeat to select more than one.")
    parser.add_argument("--group", choices=GENERATED_GROUPS, action="append", help="Limit formal generation to A, B, and/or C; repeat for multiple groups.")
    parser.add_argument("--provider-binding", help="Existing host callable as module.path:callable for legacy execution.")
    parser.add_argument("--codex-managed", action="store_true", help="Use the Codex-managed immutable task exchange for Smoke, Preflight, Pilot, or formal samples.")
    parser.add_argument("--generated-path", help="Local image path returned by Codex for --accept-codex-task.")
    parser.add_argument("--sent-prompt-base64", help="ASCII Base64 of the exact UTF-8 prompt passed to Codex image generation.")
    parser.add_argument("--failure-code", default="codex_generation_failed", help="Failure code recorded by --fail-codex-task.")
    parser.add_argument("--failure-message", default="Codex image generation failed.", help="Failure detail recorded by --fail-codex-task.")
    parser.add_argument("--failure-kind", help="Failure class; only allowlisted technical classes can be retried.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.codex_managed and args.provider_binding:
            raise ExperimentError("Choose either --codex-managed or --provider-binding, not both.")
        if args.codex_managed:
            _require_utf8_execution_environment()
        if args.codex_managed and not (
            args.freeze_environment or args.preflight or args.pilot or args.generate or args.codex_smoke_task
            or args.codex_task_envelope is not None or args.record_codex_task_receipt is not None or args.formal_status
            or args.capture_formal_continuation
            or args.capture_formal_retry_fix
            or args.verify_codex_prompt is not None
            or args.migrate_legacy_formal_transport
            or args.accept_codex_smoke_output is not None or args.accept_codex_task is not None
            or args.fail_codex_task is not None
        ):
            raise ExperimentError("--codex-managed is only valid for Codex Smoke, hard Preflight, Pilot, formal generation, or finalization.")
        if args.freeze_environment:
            environment = freeze_environment(provider_binding=args.provider_binding, codex_managed=args.codex_managed)
            print(json.dumps(environment, ensure_ascii=False, indent=2))
            return 0 if environment["tests"]["failures"] == 0 and environment["tests"]["errors"] == 0 else 1
        if args.migrate_legacy_formal_transport:
            if not args.codex_managed:
                raise ExperimentError("Legacy transport migration requires --codex-managed.")
            result = migrate_legacy_formal_transport_state(root=ROOT)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0
        if args.capture_formal_retry_fix:
            if not args.codex_managed:
                raise ExperimentError("The r5 retry-fix capture requires --codex-managed.")
            result = create_formal_retry_fix_capture(root=ROOT)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0
        if args.freeze_inputs:
            if args.codex_managed:
                raise ExperimentError("Run --freeze-inputs after the Codex-managed smoke task passes.")
            frozen = freeze_experiment_inputs()
            print(json.dumps(frozen, ensure_ascii=False, indent=2))
            return 0
        if args.codex_smoke_task:
            if not args.codex_managed:
                raise ExperimentError("Codex smoke task export requires --codex-managed.")
            result = export_codex_smoke_task()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.codex_task_envelope is not None:
            if not args.codex_managed:
                raise ExperimentError("Codex task envelope export requires --codex-managed.")
            task_path = _repo_path(args.codex_task_envelope)
            envelope = build_codex_task_envelope(task_path)
            serialized = json.dumps(envelope, ensure_ascii=True, separators=(",", ":"))
            if not serialized.isascii():
                raise ExperimentError("Codex task envelope unexpectedly contains non-ASCII transport text.")
            print(serialized)
            return 0
        if args.verify_codex_prompt is not None:
            if not args.codex_managed or not args.sent_prompt_base64:
                raise ExperimentError("Codex prompt verification requires --codex-managed and --sent-prompt-base64.")
            try:
                prompt_bytes = base64.b64decode(args.sent_prompt_base64.encode("ascii"), validate=True)
                intended_prompt = prompt_bytes.decode("utf-8", errors="strict")
            except (UnicodeEncodeError, binascii.Error, UnicodeDecodeError, ValueError) as exc:
                raise ExperimentError(f"Intended prompt is not strict UTF-8 Base64: {exc}") from exc
            task_path = _repo_path(args.verify_codex_prompt)
            task = load_codex_task(task_path, require_utf8_schema=True)
            sent_digest = verify_codex_task_prompt(task, intended_prompt)
            verified = {
                "task_id": task["task_id"],
                "task_sha256": task["task_sha256"],
                "sent_prompt_sha256_utf8": sent_digest,
                "prompt": intended_prompt,
                "reference_ids_ordered": list(task["reference_ids"]),
                "referenced_image_paths": list(task["referenced_image_paths"]),
                "expected_output_path": task["expected_output_path"],
            }
            serialized = json.dumps(verified, ensure_ascii=True, separators=(",", ":"))
            if not serialized.isascii():
                raise ExperimentError("Verified Codex prompt serialization unexpectedly contains non-ASCII text.")
            print(serialized)
            return 0
        if args.record_codex_task_receipt is not None:
            if not args.codex_managed or not args.generated_path or not args.sent_prompt_base64:
                raise ExperimentError("Codex receipt requires --codex-managed, --generated-path, and --sent-prompt-base64.")
            try:
                sent_prompt_bytes = base64.b64decode(args.sent_prompt_base64.encode("ascii"), validate=True)
                sent_prompt = sent_prompt_bytes.decode("utf-8", errors="strict")
            except (UnicodeEncodeError, binascii.Error, UnicodeDecodeError, ValueError) as exc:
                raise ExperimentError(f"Sent prompt receipt payload is not strict UTF-8 Base64: {exc}") from exc
            task_path = _repo_path(args.record_codex_task_receipt)
            task = load_codex_task(task_path, require_utf8_schema=True)
            verify_codex_task_prompt(task, sent_prompt)
            receipt = write_codex_execution_receipt(
                task_path,
                args.generated_path,
                sent_prompt=sent_prompt,
            )
            print(json.dumps(receipt, ensure_ascii=True, indent=2))
            return 0
        if args.accept_codex_smoke_output is not None:
            if not args.codex_managed:
                raise ExperimentError("Codex smoke result acceptance requires --codex-managed.")
            result = accept_codex_smoke_output(
                ROOT / CODEX_SMOKE_TASK_PATH,
                args.accept_codex_smoke_output,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("status") == "PASS" else 2
        if args.accept_codex_task is not None:
            if not args.codex_managed or not args.generated_path:
                raise ExperimentError("Codex result acceptance requires --codex-managed and --generated-path.")
            task_path = _repo_path(args.accept_codex_task)
            task = load_codex_task(task_path)
            if task.get("task_kind") == "formal":
                record = accept_codex_formal_output(task_path, args.generated_path)
                rows = _load_jsonl(_formal_manifest_path())
                accepted_preflight = _validate_formal_capture(ROOT)
                result = {
                    "accepted": record,
                    "formal_sample_total": sum(
                        _compliant_formal_sample_counts(
                            rows,
                            legacy_runner_hash_allowlist=accepted_preflight.get("legacy_runner_hash_allowlist"),
                        ).values()
                    ),
                    "formal_sample_target": EXPECTED_SAMPLE_COUNT,
                    "pilot": False,
                    "smoke": False,
                }
            elif task.get("task_kind") == "pilot":
                record = accept_codex_pilot_output(task_path, args.generated_path)
                rows = _load_jsonl(_pilot_manifest_path())
                result = {
                    "accepted": record,
                    "pilot_all_succeeded": len(rows) == len(GENERATED_GROUPS)
                    and all(row.get("status") == "succeeded" for row in rows),
                    "formal": False,
                    "smoke": False,
                }
            else:
                raise ExperimentError("--accept-codex-task accepts Pilot or formal tasks only; Smoke uses --accept-codex-smoke-output.")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.fail_codex_task is not None:
            if not args.codex_managed:
                raise ExperimentError("Codex task failure recording requires --codex-managed.")
            task_path = _repo_path(args.fail_codex_task)
            task = load_codex_task(task_path)
            if task.get("task_kind") == "formal":
                if not args.failure_kind:
                    raise ExperimentError("Formal task failure recording requires an allowlisted --failure-kind and a reason in --failure-message.")
                record = record_codex_formal_failure(
                    task_path,
                    failure_kind=args.failure_kind,
                    failure_code=args.failure_code,
                    failure_message=args.failure_message,
                )
            elif task.get("task_kind") == "pilot":
                record = record_codex_pilot_failure(
                    task_path,
                    failure_code=args.failure_code,
                    failure_message=args.failure_message,
                )
            else:
                raise ExperimentError("--fail-codex-task accepts Pilot or formal tasks only.")
            print(json.dumps(record, ensure_ascii=False, indent=2))
            return 1
        if args.host_smoke:
            if args.codex_managed:
                raise ExperimentError("Use --codex-smoke-task for Codex-managed image generation.")
            result = run_host_smoke(args.provider_binding)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("status") == "PASS" else 2
        if args.prepare_blind_review:
            count = prepare_blind_review()
            print(f"Prepared {count} private blind review images and evaluation forms.")
            return 0
        if args.formal_status:
            result = formal_orchestration_status(root=ROOT)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0
        if args.capture_formal_continuation:
            if not args.codex_managed:
                raise ExperimentError("Formal continuation capture requires --codex-managed.")
            result = create_formal_continuation_capture(ROOT)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        selected_cases = set(args.case) if args.case else None
        if args.generate and args.codex_managed:
            if selected_cases is not None or args.group:
                raise ExperimentError("Codex-managed formal execution follows the complete frozen order; omit --case and --group.")
            queued = queue_next_formal_task({}, root=ROOT)
            print(json.dumps(queued, ensure_ascii=False, indent=2))
            return 0
        if args.preflight or args.pilot:
            if selected_cases is not None or args.group:
                raise ExperimentError("Hard preflight and pilot always cover all four cases; omit --case and --group.")
            preflight = collect_preflight(
                ROOT,
                hard=True,
                provider_binding=args.provider_binding,
                codex_managed=args.codex_managed,
            )
            report = write_preflight_report(preflight)
            if args.preflight:
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 0 if report["status"] == "READY" else 2
            if report["status"] != "READY":
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 2
            if args.codex_managed:
                counts = run_pilot(preflight, execution_mode="codex-managed")
                print(json.dumps({"pilot": True, "execution_mode": "codex-managed", **counts}, ensure_ascii=False, indent=2))
                return 0
            if not args.provider_binding:
                raise ExperimentError("Real Pilot generation requires --provider-binding or --codex-managed.")
            provider = _load_provider_callable(args.provider_binding)
            counts = run_pilot(preflight, provider=provider)
            final_environment = freeze_environment(provider_binding=args.provider_binding)
            print(json.dumps({"pilot": True, **counts, "final_preflight": final_environment}, ensure_ascii=False, indent=2))
            return 1 if counts["failed"] or not final_environment.get("experiment_ready") else 0

        preflight = collect_preflight(ROOT, selected_cases=selected_cases)
        if args.dry_run:
            output = {
                "cases_found": len(preflight["cases_document"].get("cases", [])),
                "selected_case_count": len(preflight["cases"]),
                "expected_sample_count": preflight["cases_document"].get("expected_sample_count"),
                "generation_samples_planned": len(preflight["cases"]) * EXPECTED_REPLICATES * len(GENERATED_GROUPS),
                "a_b_c_selector_parity_checked": len(preflight["plans"]),
                "blockers": preflight["errors"],
                "status": "READY" if not preflight["errors"] else "BLOCKED",
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0 if not preflight["errors"] else 2
        if not args.provider_binding:
            raise ExperimentError("Real generation requires the existing host --provider-binding.")
        provider = _load_provider_callable(args.provider_binding)
        counts = run_generation(
            preflight,
            provider=provider,
            selected_cases=selected_cases,
            selected_groups=set(args.group) if args.group else None,
        )
        print(json.dumps(counts, ensure_ascii=False, indent=2))
        return 1 if counts["failed"] else 0
    except (ExperimentError, ReferenceRuntimeError, ArcoRealAdapterError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
