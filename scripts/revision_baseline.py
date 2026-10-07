#!/usr/bin/env python3
"""Phase 0 baseline capture and replay checks for legacy Revision fixtures.

This module is deliberately an observer around the existing production
generation boundary.  It does not implement revision semantics, retries,
visual evaluation, routing, or a provider adapter of its own.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import inspect
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import yaml

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from arco_production import ProductionGenerationResult, run_production_generation


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "archive/实验/evaluation" / "revision-regression" / "cases.yaml"
DEFAULT_CAPTURE_DIR = ROOT / "archive/实验/evaluation" / "revision-regression" / "baseline"
APPROVED_BASELINE_COMMIT = "0b6713bc57f55eae3ad66b12015846d6b5b75a4c"
SCHEMA_VERSION = 1
CODEX_TASK_SCHEMA_VERSION = 1
EXPECTED_CASES = {
    "case-01": {
        "purpose": "iterative_artifact",
        "sequence": ["first-generation", "revision-1", "revision-2"],
    },
    "case-02": {
        "purpose": "character_detail_revision",
        "sequence": None,
    },
    "case-03": {
        "purpose": "large_scene_baseline",
        "sequence": ["baseline-generation"],
    },
}
PATH_TOKEN_RE = re.compile(r"\$\{previous_output:([^}]+)\}")
SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")
PRODUCTION_REQUEST_KEYS = frozenset(
    {
        "base_prompt", "exposure_profile", "variant_id", "arco_references",
        "request_scoped_arco_references", "external_references", "style_briefs",
        "user_style_overrides", "allow_uncertain_working", "rendering_hygiene",
    }
)


class RevisionBaselineError(Exception):
    """A deterministic validation or capture error."""

    def __init__(self, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            value["details"] = _to_builtin(self.details)
        return value


class FixtureBlocked(RevisionBaselineError):
    """The fixture is incomplete or an external capability is unavailable."""


class CodexTaskPending(Exception):
    """Internal control flow used after an immutable host task is exported."""


def _to_builtin(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _to_builtin(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_builtin(item) for item in value]
    if isinstance(value, set):
        return sorted(_to_builtin(item) for item in value)
    return value


def canonical_json(value: Any) -> str:
    """Serialize a record in a deterministic, JSON-only representation."""

    try:
        return json.dumps(
            _to_builtin(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RevisionBaselineError("SERIALIZATION_FAILED", str(exc)) from exc


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> str:
    from archive_paths import relocate
    path = relocate(path)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RevisionBaselineError("FILE_READ_FAILED", f"Could not hash {path}: {exc}") from exc
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_repo_path(value: str | Path, *, root: Path, field: str, must_exist: bool = False) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise RevisionBaselineError("PATH_REQUIRED", f"{field} must be a non-empty repository-relative path.")
    candidate = Path(value)
    if candidate.is_absolute():
        raise RevisionBaselineError("UNSAFE_PATH", f"{field} must be repository-relative: {value}")
    root_resolved = Path(root).resolve()
    from archive_paths import relocate
    resolved = relocate(root_resolved / candidate, root=root_resolved).resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise RevisionBaselineError("UNSAFE_PATH", f"{field} escapes the repository root: {value}") from exc
    if must_exist and not resolved.is_file():
        raise RevisionBaselineError("FILE_NOT_FOUND", f"Missing {field}: {value}")
    return resolved


def _stable_locator(path: str | Path, *, root: Path) -> str:
    resolved = Path(path).expanduser().resolve(strict=False)
    try:
        return resolved.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _canonical_path(value: str | Path) -> str:
    return str(Path(value).expanduser().resolve(strict=False)).casefold()


def _same_path_sequence(left: Sequence[str | Path], right: Sequence[str | Path]) -> bool:
    return [_canonical_path(value) for value in left] == [_canonical_path(value) for value in right]


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RevisionBaselineError("FIXTURE_READ_FAILED", f"Could not read fixture {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RevisionBaselineError("FIXTURE_SCHEMA_INVALID", "Fixture root must be a mapping.")
    return value


def _load_json_mapping(path: Path, *, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RevisionBaselineError("REQUEST_READ_FAILED", f"Could not read {field} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RevisionBaselineError("REQUEST_SCHEMA_INVALID", f"{field} must contain a JSON mapping.")
    return value


def _reason(code: str, message: str, **details: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": message}
    if details:
        item["details"] = _to_builtin(details)
    return item


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise RevisionBaselineError("GIT_CHECK_FAILED", str(detail).strip()) from exc
    return completed.stdout.strip()


def _status_paths(status: str) -> list[str]:
    paths: list[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        raw = line[3:]
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        raw = raw.strip().strip('"').replace("\\", "/")
        if raw:
            paths.append(raw)
    return paths


def snapshot_baseline(root: Path = ROOT, protected_paths: Sequence[str] | None = None) -> dict[str, Any]:
    """Check the approved commit and only fail on protected runtime drift."""

    root = Path(root).resolve()
    expected_paths = list(protected_paths or [])
    head = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    changed_paths = _status_paths(status)
    normalized_protected = {str(Path(item).as_posix()).casefold() for item in expected_paths}
    protected_dirty = sorted(
        path for path in changed_paths if path.casefold() in normalized_protected
    )
    if head != APPROVED_BASELINE_COMMIT:
        raise RevisionBaselineError(
            "BASELINE_COMMIT_MISMATCH",
            f"HEAD {head} differs from approved baseline {APPROVED_BASELINE_COMMIT}.",
            details={"head": head, "approved": APPROVED_BASELINE_COMMIT},
        )
    if protected_dirty:
        raise RevisionBaselineError(
            "PROTECTED_RUNTIME_DIRTY",
            "Protected production-runtime files have uncommitted changes.",
            details={"paths": protected_dirty},
        )
    hashes: dict[str, str] = {}
    for relative in expected_paths:
        path = _safe_repo_path(relative, root=root, field="protected runtime path", must_exist=True)
        hashes[Path(relative).as_posix()] = sha256_file(path)
    return {
        "approved_commit": APPROVED_BASELINE_COMMIT,
        "head": head,
        "working_tree_status": status.splitlines(),
        "non_protected_dirty_paths": [
            path for path in changed_paths if path.casefold() not in normalized_protected
        ],
        "protected_runtime_hashes": hashes,
    }


def _find_tokens(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.extend(match.group(1) for match in PATH_TOKEN_RE.finditer(value))
    elif isinstance(value, Mapping):
        for item in value.values():
            found.extend(_find_tokens(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            found.extend(_find_tokens(item))
    return found


def _reference_paths_from_request(request: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    result: list[tuple[str, Mapping[str, Any]]] = []
    # Managed Arco references are registry selectors (asset_id + role), not
    # physical request-scoped paths.  Requiring a path here rejects valid
    # production requests before the production registry can resolve them.
    for field in ("request_scoped_arco_references", "external_references"):
        values = request.get(field, [])
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            if isinstance(value, Mapping):
                result.append((f"{field}[{index}]", value))
    return result


def _validate_request_file(
    request_path: Path,
    *,
    request: Mapping[str, Any],
    root: Path,
    previous_output_from: str | None,
    field_prefix: str,
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    unknown = sorted(set(request) - PRODUCTION_REQUEST_KEYS)
    if unknown:
        reasons.append(_reason("REQUEST_FIELDS_UNSUPPORTED", f"{field_prefix} contains unsupported request fields: {unknown}"))
    prompt = request.get("base_prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        reasons.append(_reason("RAW_PROMPT_MISSING", f"{field_prefix} must contain a non-empty base_prompt."))
    for field, reference in _reference_paths_from_request(request):
        raw_path = reference.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            reasons.append(_reason("REFERENCE_PATH_MISSING", f"{field_prefix}.{field} is missing path."))
            continue
        if reference.get("source_scope") in {"request_scoped_arco", "external_how"}:
            for provenance_key in ("authority", "selection_reason", "confidence"):
                if not isinstance(reference.get(provenance_key), str) or not reference.get(provenance_key).strip():
                    reasons.append(_reason("REFERENCE_PROVENANCE_MISSING", f"{field_prefix}.{field} lacks {provenance_key}."))
        if PATH_TOKEN_RE.fullmatch(raw_path):
            continue
        try:
            resolved = _safe_repo_path(raw_path, root=root, field=f"{field_prefix}.{field}.path", must_exist=True)
        except RevisionBaselineError as exc:
            reasons.append(exc.as_dict())
            continue
        declared_hash = reference.get("sha256")
        if not isinstance(declared_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", declared_hash):
            reasons.append(_reason("REFERENCE_HASH_MISSING", f"{field_prefix}.{field} must declare a SHA-256."))
        elif declared_hash.casefold() != sha256_file(resolved).casefold():
            reasons.append(_reason("REFERENCE_HASH_MISMATCH", f"{field_prefix}.{field} SHA-256 does not match.", path=str(raw_path)))
        if reference.get("source_scope") == "external_how":
            provenance = reference.get("provenance")
            if not isinstance(provenance, Mapping) and not any(
                isinstance(reference.get(key), str) and reference.get(key).strip()
                for key in ("source", "source_url", "origin")
            ):
                reasons.append(_reason("REFERENCE_PROVENANCE_MISSING", f"{field_prefix}.{field} lacks source provenance."))
    tokens = _find_tokens(request)
    if previous_output_from:
        if tokens.count(previous_output_from) != 1:
            reasons.append(
                _reason(
                    "PRIOR_OUTPUT_TRANSFER_UNDECLARED",
                    f"{field_prefix} must contain exactly one prior-output token for {previous_output_from}.",
                )
            )
    elif tokens:
        reasons.append(_reason("PRIOR_OUTPUT_TRANSFER_UNDECLARED", f"{field_prefix} contains prior-output tokens without a declaration."))
    return reasons


def validate_evidence_manifest(manifest_path: Path, *, root: Path) -> list[dict[str, Any]]:
    """Validate Phase 0B-I evidence without treating it as executable input."""

    reasons: list[dict[str, Any]] = []
    try:
        manifest = _load_json_mapping(manifest_path, field="input evidence manifest")
    except RevisionBaselineError as exc:
        return [exc.as_dict()]
    if manifest.get("schema_version") != 1:
        reasons.append(_reason("EVIDENCE_SCHEMA_INVALID", "Evidence manifest schema_version must be 1."))
    if manifest.get("status") not in {"PARTIAL", "FROZEN"}:
        reasons.append(_reason("EVIDENCE_SCHEMA_INVALID", "Evidence manifest status must be PARTIAL or FROZEN."))
    if manifest.get("real_generation_executed") is not False or manifest.get("capture_executed") is not False:
        reasons.append(_reason("EVIDENCE_SCOPE_INVALID", "Phase 0B-I evidence must not claim generation or capture."))

    assets = manifest.get("assets")
    known_cases = set(EXPECTED_CASES)
    if not isinstance(assets, list):
        reasons.append(_reason("EVIDENCE_SCHEMA_INVALID", "Evidence assets must be a list."))
        assets = []
    asset_ids: set[str] = set()
    for index, asset in enumerate(assets):
        if not isinstance(asset, Mapping):
            reasons.append(_reason("EVIDENCE_SCHEMA_INVALID", f"assets[{index}] must be a mapping."))
            continue
        asset_id = asset.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            reasons.append(_reason("EVIDENCE_SCHEMA_INVALID", f"assets[{index}] has no asset_id."))
        elif asset_id in asset_ids:
            reasons.append(_reason("EVIDENCE_ASSET_DUPLICATE", f"Duplicate evidence asset: {asset_id}"))
        else:
            asset_ids.add(asset_id)
        used_in = asset.get("used_in_cases")
        if not isinstance(used_in, list) or not used_in or any(case_id not in known_cases for case_id in used_in):
            reasons.append(_reason("EVIDENCE_ASSET_ORPHAN", f"Evidence asset {asset_id} has no valid case association."))
        reasons.extend(_validate_evidence_file(asset, root=root, field=f"assets[{index}]"))

    cases = manifest.get("cases")
    if not isinstance(cases, list):
        reasons.append(_reason("EVIDENCE_SCHEMA_INVALID", "Evidence cases must be a list."))
        cases = []
    seen_cases: set[str] = set()
    prospective_targets: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            reasons.append(_reason("EVIDENCE_SCHEMA_INVALID", "Evidence case must be a mapping."))
            continue
        case_id = case.get("case_id")
        if case_id not in known_cases or case_id in seen_cases:
            reasons.append(_reason("EVIDENCE_SCHEMA_INVALID", f"Invalid or duplicate evidence case: {case_id}"))
            continue
        seen_cases.add(str(case_id))
        provenance = case.get("fixture_provenance")
        expected_class = "FROZEN_EXISTING_FIXTURE" if case_id == "case-03" else "CANONICAL_PROSPECTIVE_FIXTURE"
        if not isinstance(provenance, Mapping) or provenance.get("class") != expected_class:
            reasons.append(_reason("FIXTURE_PROVENANCE_INVALID", f"{case_id} must use provenance class {expected_class}."))
        elif case_id != "case-03":
            if provenance.get("historical_equivalence_claimed") is not False:
                reasons.append(_reason("FIXTURE_PROVENANCE_IMPERSONATION", f"{case_id} prospective fixture cannot claim historical equivalence."))
            recovery_targets = provenance.get("recovery_targets")
            if not isinstance(recovery_targets, list) or not recovery_targets:
                reasons.append(_reason("RECOVERY_LINK_MISSING", f"{case_id} prospective fixture must link recovery targets."))
            else:
                prospective_targets.update(str(item) for item in recovery_targets)
            canonical = case.get("canonical_fixture")
            requests = canonical.get("requests") if isinstance(canonical, Mapping) else None
            expected_sequence = EXPECTED_CASES[case_id]["sequence"] or [
                "first-generation", "background-revision", "character-detail-revision"
            ]
            if not isinstance(canonical, Mapping) or canonical.get("status") != "FROZEN" or not isinstance(requests, list):
                reasons.append(_reason("CANONICAL_FIXTURE_INVALID", f"{case_id} canonical fixture is not frozen."))
            elif [item.get("step_id") for item in requests if isinstance(item, Mapping)] != expected_sequence:
                reasons.append(_reason("CANONICAL_FIXTURE_INVALID", f"{case_id} canonical request sequence is invalid."))
            else:
                prior_ids: set[str] = set()
                for request_record in requests:
                    if not isinstance(request_record, Mapping):
                        reasons.append(_reason("CANONICAL_FIXTURE_INVALID", f"{case_id} has a malformed request record."))
                        continue
                    step_id = str(request_record.get("step_id"))
                    relative = request_record.get("path")
                    declared_hash = request_record.get("sha256")
                    previous = request_record.get("previous_output_from")
                    if not request_record.get("raw_prompt_source"):
                        reasons.append(_reason("CANONICAL_PROMPT_SOURCE_MISSING", f"{case_id}/{step_id} has no raw prompt source."))
                    try:
                        request_path = _safe_repo_path(relative, root=root, field=f"{case_id}/{step_id}.canonical_request", must_exist=True)
                        request = _load_json_mapping(request_path, field=f"{case_id}/{step_id}.canonical_request")
                        if not isinstance(declared_hash, str) or declared_hash.casefold() != sha256_file(request_path).casefold():
                            reasons.append(_reason("REQUEST_HASH_MISMATCH", f"{case_id}/{step_id} canonical request SHA-256 does not match."))
                        if previous is not None and previous not in prior_ids:
                            reasons.append(_reason("PRIOR_OUTPUT_ORDER_INVALID", f"{case_id}/{step_id} previous output is not earlier in the sequence."))
                        reasons.extend(_validate_request_file(
                            request_path, request=request, root=root,
                            previous_output_from=previous if isinstance(previous, str) else None,
                            field_prefix=f"{case_id}/{step_id}.canonical_request",
                        ))
                    except RevisionBaselineError as exc:
                        reasons.append(exc.as_dict())
                    prior_ids.add(step_id)
        elif provenance.get("historical_equivalence_claimed") is not True:
            reasons.append(_reason("FIXTURE_PROVENANCE_INVALID", "case-03 existing frozen provenance must remain explicit."))
        if case_id == "case-03":
            steps = case.get("steps")
            request_evidence = case.get("production_request_evidence")
            immutable_ok = (
                isinstance(steps, list)
                and len(steps) == 1
                and steps[0].get("step_id") == "baseline-generation"
                and steps[0].get("prompt", {}).get("sha256") == "7070abb1cf3882489370fcc8a5cc71be7859798ba0a3310201fd1e2cb971e54e"
                and isinstance(request_evidence, Mapping)
                and request_evidence.get("canonical_sha256") == "522b26dd0a31ae2688a0faaef45c32159636dd1e00a3a077b98041b1dde07ace"
            )
            if not immutable_ok:
                reasons.append(_reason("CASE03_IMMUTABILITY_VIOLATION", "case-03 prompt, request, or step structure changed."))
        steps = case.get("steps")
        if not isinstance(steps, list) or not steps:
            reasons.append(_reason("EVIDENCE_SCHEMA_INVALID", f"{case_id} has no evidence steps."))
            continue
        prior_source: str | None = None
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping) or step.get("sequence_index") != index:
                reasons.append(_reason("EVIDENCE_SEQUENCE_INVALID", f"{case_id} evidence sequence is invalid at index {index}."))
                continue
            prompt = step.get("prompt")
            output = step.get("historical_output")
            if isinstance(prompt, Mapping):
                reasons.extend(_validate_evidence_file(prompt, root=root, field=f"{case_id}.steps[{index}].prompt"))
            else:
                reasons.append(_reason("EVIDENCE_SCHEMA_INVALID", f"{case_id}.steps[{index}] has no prompt evidence."))
            if isinstance(output, Mapping):
                reasons.extend(_validate_evidence_file(output, root=root, field=f"{case_id}.steps[{index}].historical_output"))
            else:
                reasons.append(_reason("EVIDENCE_SCHEMA_INVALID", f"{case_id}.steps[{index}] has no output evidence."))
            transport = step.get("transport")
            if not isinstance(transport, Mapping):
                reasons.append(_reason("EVIDENCE_TRANSPORT_INVALID", f"{case_id}.steps[{index}] has no transport evidence."))
            elif index == 0 and transport.get("previous_output_source") is not None:
                reasons.append(_reason("EVIDENCE_TRANSPORT_INVALID", f"{case_id}.steps[0] unexpectedly declares a previous output."))
            elif index > 0:
                ordered = transport.get("ordered_source_paths")
                if transport.get("previous_output_source") != prior_source or not isinstance(ordered, list) or not ordered or ordered[0] != prior_source:
                    reasons.append(_reason("EVIDENCE_TRANSPORT_INVALID", f"{case_id}.steps[{index}] does not link the prior output exactly."))
            if isinstance(output, Mapping) and isinstance(output.get("source_path"), str):
                prior_source = str(output["source_path"])
        request_evidence = case.get("production_request_evidence")
        if isinstance(request_evidence, Mapping):
            for key in ("historical", "canonical"):
                record = {
                    "canonical_path": request_evidence.get(f"{key}_path"),
                    "sha256": request_evidence.get(f"{key}_sha256"),
                }
                reasons.extend(_validate_evidence_file(record, root=root, field=f"{case_id}.production_request_evidence.{key}"))
    if seen_cases != known_cases:
        reasons.append(_reason("EVIDENCE_SCHEMA_INVALID", "Evidence manifest must contain all three cases."))
    recovery = manifest.get("production_request_recovery")
    if not isinstance(recovery, Mapping):
        reasons.append(_reason("RECOVERY_MANIFEST_MISSING", "Phase 0B-R recovery manifest is required."))
    else:
        recovery_record = {"canonical_path": recovery.get("path"), "sha256": recovery.get("sha256")}
        recovery_errors = _validate_evidence_file(recovery_record, root=root, field="production_request_recovery")
        reasons.extend(recovery_errors)
        if not recovery_errors:
            recovery_path = _safe_repo_path(
                str(recovery["path"]), root=root, field="production_request_recovery", must_exist=True
            )
            reasons.extend(validate_recovery_manifest(recovery_path, evidence_manifest=manifest))
            recovery_document = _load_json_mapping(recovery_path, field="production request recovery manifest")
            unrecoverable_targets = {
                str(target.get("target_id"))
                for target in recovery_document.get("targets", [])
                if isinstance(target, Mapping) and target.get("classification") == "UNRECOVERABLE"
            }
            if prospective_targets != unrecoverable_targets:
                reasons.append(_reason("RECOVERY_LINK_MISMATCH", "Prospective fixtures must link exactly the five unrecoverable recovery targets."))
    return reasons


def _validate_evidence_file(record: Mapping[str, Any], *, root: Path, field: str) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    relative = record.get("canonical_path")
    declared_hash = record.get("sha256")
    if not isinstance(relative, str) or not relative:
        return [_reason("EVIDENCE_PATH_MISSING", f"{field} has no canonical_path.")]
    try:
        path = _safe_repo_path(relative, root=root, field=field, must_exist=True)
    except RevisionBaselineError as exc:
        return [exc.as_dict()]
    if not isinstance(declared_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", declared_hash):
        reasons.append(_reason("EVIDENCE_HASH_MISSING", f"{field} has no valid SHA-256."))
    elif sha256_file(path).casefold() != declared_hash.casefold():
        reasons.append(_reason("EVIDENCE_HASH_MISMATCH", f"{field} SHA-256 does not match."))
    return reasons


def validate_recovery_manifest(
    manifest_path: Path,
    *,
    evidence_manifest: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate Phase 0B-R classifications without reconstructing requests."""

    reasons: list[dict[str, Any]] = []
    try:
        manifest = _load_json_mapping(manifest_path, field="production request recovery manifest")
    except RevisionBaselineError as exc:
        return [exc.as_dict()]
    if manifest.get("schema_version") != 1 or manifest.get("recovery_id") != "arco-revision-regression-phase-0b-r":
        reasons.append(_reason("RECOVERY_SCHEMA_INVALID", "Unexpected recovery manifest identity or schema."))
    if manifest.get("approved_baseline_commit") != APPROVED_BASELINE_COMMIT:
        reasons.append(_reason("RECOVERY_BASELINE_MISMATCH", "Recovery manifest is not bound to the approved baseline."))
    if any(manifest.get(key) is not False for key in ("real_generation_executed", "capture_executed", "replay_check_executed")):
        reasons.append(_reason("RECOVERY_SCOPE_INVALID", "Recovery must not claim generation, capture, or replay-check."))
    mapping = manifest.get("mapping_contract")
    if not isinstance(mapping, Mapping) or mapping.get("upstream_mapper_present") is not False:
        reasons.append(_reason("RECOVERY_MAPPING_CONTRACT_INVALID", "The discovered request boundary is not recorded."))
    search = manifest.get("evidence_search")
    if not isinstance(search, Mapping) or search.get("completed") is not True or not search.get("locations"):
        reasons.append(_reason("RECOVERY_SEARCH_INCOMPLETE", "Required evidence search is not complete."))

    expected_targets = {
        ("case-01", "first-generation"),
        ("case-01", "revision-1"),
        ("case-01", "revision-2"),
        ("case-02", "background-revision"),
        ("case-02", "character-detail-revision"),
    }
    allowed = {"ORIGINAL_EVIDENCE_FOUND", "DETERMINISTICALLY_REDERIVED", "UNRECOVERABLE"}
    evidence_steps: dict[tuple[str, str], Mapping[str, Any]] = {}
    evidence_sessions: dict[str, str] = {}
    if isinstance(evidence_manifest, Mapping):
        for case in evidence_manifest.get("cases", []):
            if isinstance(case, Mapping):
                if isinstance(case.get("source_session_sha256"), str):
                    evidence_sessions[str(case.get("case_id"))] = str(case.get("source_session_sha256"))
                for step in case.get("steps", []):
                    if isinstance(step, Mapping):
                        evidence_steps[(str(case.get("case_id")), str(step.get("step_id")))] = step
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        return reasons + [_reason("RECOVERY_SCHEMA_INVALID", "Recovery targets must be a list.")]
    seen: set[tuple[str, str]] = set()
    for index, target in enumerate(targets):
        if not isinstance(target, Mapping):
            reasons.append(_reason("RECOVERY_SCHEMA_INVALID", f"targets[{index}] must be a mapping."))
            continue
        key = (str(target.get("case_id")), str(target.get("step_id")))
        if key not in expected_targets or key in seen:
            reasons.append(_reason("RECOVERY_TARGET_INVALID", f"Invalid or duplicate recovery target: {key}"))
            continue
        seen.add(key)
        classification = target.get("classification")
        if classification not in allowed:
            reasons.append(_reason("RECOVERY_CLASSIFICATION_INVALID", f"{key} has a forbidden classification."))
            continue
        for field in ("source_session_sha256", "provider_prompt_sha256", "historical_output_sha256"):
            if not isinstance(target.get(field), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", str(target.get(field))):
                reasons.append(_reason("RECOVERY_HASH_MISSING", f"{key} is missing {field}."))
        evidence_step = evidence_steps.get(key)
        if evidence_step is not None:
            if target.get("source_session_sha256") != evidence_sessions.get(key[0]):
                reasons.append(_reason("RECOVERY_LINKAGE_MISMATCH", f"{key} session hash does not match frozen evidence."))
            if target.get("source_call_id") != evidence_step.get("source_call_id"):
                reasons.append(_reason("RECOVERY_LINKAGE_MISMATCH", f"{key} call ID does not match frozen evidence."))
            if target.get("provider_prompt_sha256") != evidence_step.get("prompt", {}).get("sha256"):
                reasons.append(_reason("RECOVERY_LINKAGE_MISMATCH", f"{key} prompt hash does not match frozen evidence."))
            if target.get("historical_output_sha256") != evidence_step.get("historical_output", {}).get("sha256"):
                reasons.append(_reason("RECOVERY_LINKAGE_MISMATCH", f"{key} output hash does not match frozen evidence."))
        if classification == "UNRECOVERABLE":
            if not target.get("missing_evidence") or not target.get("hidden_dependency"):
                reasons.append(_reason("RECOVERY_PROVENANCE_MISSING", f"{key} lacks its unrecoverable dependency evidence."))
            if target.get("deterministic_recovery") != "NOT_PROVEN":
                reasons.append(_reason("RECOVERY_CLASSIFICATION_INVALID", f"{key} must record deterministic recovery as NOT_PROVEN."))
            if target.get("request_evidence_path") is not None or target.get("result_sha256") is not None:
                reasons.append(_reason("RECOVERY_GUESSED_REQUEST_FORBIDDEN", f"{key} must not materialize a guessed request."))
        elif classification == "ORIGINAL_EVIDENCE_FOUND":
            required = ("source_path", "source_sha256", "request_sha256", "case_step_linkage")
            if any(not target.get(field) for field in required):
                reasons.append(_reason("RECOVERY_PROVENANCE_MISSING", f"{key} lacks original-evidence provenance."))
        else:
            required = (
                "derived_from_commit", "mapping_entrypoint", "input_manifest", "input_hashes",
                "derivation_command", "result_path", "result_sha256", "run_1_sha256", "run_2_sha256",
            )
            if any(not target.get(field) for field in required):
                reasons.append(_reason("RECOVERY_PROVENANCE_MISSING", f"{key} lacks deterministic derivation provenance."))
            elif target.get("run_1_sha256") != target.get("run_2_sha256") or target.get("result_sha256") != target.get("run_1_sha256"):
                reasons.append(_reason("RECOVERY_NONDETERMINISTIC", f"{key} repeated derivation hashes differ."))
    if seen != expected_targets:
        reasons.append(_reason("RECOVERY_TARGETS_MISSING", "Recovery manifest must classify all five targets exactly once."))
    if manifest.get("status") != "PASS" or manifest.get("recovery_completed") != "PASS":
        reasons.append(_reason("RECOVERY_STATUS_INVALID", "A conclusive Phase 0B-R evidence search must be recorded as PASS."))
    if manifest.get("phase0_gate_at_recovery") != "BLOCKED":
        reasons.append(_reason("RECOVERY_STATUS_INVALID", "The historical Phase 0 gate must remain recorded as BLOCKED."))
    return reasons


def validate_fixture(
    fixture_path: str | Path = DEFAULT_FIXTURE,
    *,
    root: Path = ROOT,
    check_environment: bool = True,
) -> dict[str, Any]:
    """Validate structure and exact input availability without writing files."""

    root = Path(root).resolve()
    fixture = Path(fixture_path).resolve()
    reasons: list[dict[str, Any]] = []
    try:
        fixture.relative_to(root)
    except ValueError:
        reasons.append(_reason("UNSAFE_PATH", "Fixture must be inside the repository root."))
    if not fixture.is_file():
        reasons.append(_reason("FIXTURE_NOT_FOUND", str(fixture)))
        return {"status": "BLOCKED", "fixture_path": str(fixture), "reasons": reasons}
    try:
        document = _load_yaml(fixture)
    except RevisionBaselineError as exc:
        return {"status": "BLOCKED", "fixture_path": str(fixture), "reasons": [exc.as_dict()]}

    if document.get("schema_version") != SCHEMA_VERSION:
        reasons.append(_reason("FIXTURE_SCHEMA_INVALID", f"schema_version must be {SCHEMA_VERSION}."))
    if document.get("fixture_id") != "arco-revision-regression-phase-0":
        reasons.append(_reason("FIXTURE_SCHEMA_INVALID", "Unexpected fixture_id."))
    baseline = document.get("baseline")
    if not isinstance(baseline, Mapping):
        reasons.append(_reason("BASELINE_DECLARATION_MISSING", "baseline must be a mapping."))
        baseline = {}
    if baseline.get("commit") != APPROVED_BASELINE_COMMIT:
        reasons.append(_reason("BASELINE_COMMIT_MISMATCH", "Fixture baseline commit is not the approved commit."))
    if baseline.get("working_tree_policy") != "protected-runtime-must-be-clean":
        reasons.append(_reason("BASELINE_POLICY_INVALID", "Fixture must use protected-runtime-must-be-clean."))
    protected = baseline.get("protected_runtime_paths")
    if not isinstance(protected, list) or not protected or not all(isinstance(item, str) for item in protected):
        reasons.append(_reason("PROTECTED_PATHS_MISSING", "baseline.protected_runtime_paths must be a non-empty list."))
        protected = []
    else:
        for item in protected:
            try:
                _safe_repo_path(item, root=root, field="protected runtime path", must_exist=True)
            except RevisionBaselineError as exc:
                reasons.append(exc.as_dict())

    if check_environment and not any(item["code"] == "UNSAFE_PATH" for item in reasons):
        try:
            snapshot_baseline(root, protected)
        except RevisionBaselineError as exc:
            reasons.append(exc.as_dict())

    enforce_phase0c_provenance = False
    bundle = document.get("input_bundle")
    if not isinstance(bundle, Mapping):
        reasons.append(_reason("INPUT_BUNDLE_MISSING", "input_bundle must be a mapping."))
        bundle = {}
    bundle_status = bundle.get("status")
    if bundle_status == "PARTIAL":
        reasons.append(_reason("INPUT_BUNDLE_PARTIAL", "Canonical evidence exists, but executable production inputs remain unresolved."))
    elif bundle_status != "FROZEN":
        reasons.append(_reason("INPUT_BUNDLE_MISSING", "The exact user-provided input bundle is not frozen."))
    bundle_path = bundle.get("path")
    if bundle_status in {"PARTIAL", "FROZEN"} and not isinstance(bundle_path, str):
        reasons.append(_reason("INPUT_BUNDLE_PATH_MISSING", "Partial or frozen input bundle must declare input_bundle.path."))
    if bundle_path is not None:
        try:
            bundle_file = _safe_repo_path(bundle_path, root=root, field="input_bundle.path", must_exist=True)
            declared_bundle_hash = bundle.get("sha256")
            if bundle_file.is_file():
                if not isinstance(declared_bundle_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", declared_bundle_hash):
                    reasons.append(_reason("INPUT_BUNDLE_HASH_MISSING", "Frozen input bundle must declare a SHA-256."))
                elif declared_bundle_hash.casefold() != sha256_file(bundle_file).casefold():
                    reasons.append(_reason("INPUT_BUNDLE_HASH_MISMATCH", "Input bundle SHA-256 does not match."))
                elif bundle_file.suffix.casefold() == ".json":
                    bundle_document = _load_json_mapping(bundle_file, field="input bundle")
                    if bundle_document.get("bundle_id") == "arco-revision-regression-phase-0b-i":
                        enforce_phase0c_provenance = True
                        reasons.extend(validate_evidence_manifest(bundle_file, root=root))
        except RevisionBaselineError as exc:
            reasons.append(exc.as_dict())

    cases = document.get("cases")
    if not isinstance(cases, list):
        reasons.append(_reason("CASES_MISSING", "cases must be a list."))
        cases = []
    seen_cases: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            reasons.append(_reason("CASE_SCHEMA_INVALID", "Each case must be a mapping."))
            continue
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id not in EXPECTED_CASES:
            reasons.append(_reason("CASE_ID_INVALID", f"Unknown case_id: {case_id}"))
            continue
        if case_id in seen_cases:
            reasons.append(_reason("CASE_ID_DUPLICATE", f"Duplicate case_id: {case_id}"))
        seen_cases.add(case_id)
        expected = EXPECTED_CASES[case_id]
        if case.get("purpose") != expected["purpose"]:
            reasons.append(_reason("CASE_PURPOSE_INVALID", f"{case_id} has an unexpected purpose."))
        expected_provenance = "FROZEN_EXISTING_FIXTURE" if case_id == "case-03" else "CANONICAL_PROSPECTIVE_FIXTURE"
        if enforce_phase0c_provenance and case.get("provenance_class") != expected_provenance:
            reasons.append(_reason("FIXTURE_PROVENANCE_INVALID", f"{case_id} must use {expected_provenance}."))
        if enforce_phase0c_provenance and case_id != "case-03":
            if case.get("historical_equivalence_claimed") is not False:
                reasons.append(_reason("FIXTURE_PROVENANCE_IMPERSONATION", f"{case_id} cannot claim historical equivalence."))
            recovery_path = case.get("recovery_manifest_path")
            recovery_hash = case.get("recovery_manifest_sha256")
            if not isinstance(recovery_path, str):
                reasons.append(_reason("RECOVERY_LINK_MISSING", f"{case_id} has no recovery manifest path."))
            else:
                try:
                    resolved_recovery = _safe_repo_path(
                        recovery_path, root=root, field=f"{case_id}.recovery_manifest_path", must_exist=True
                    )
                    if not isinstance(recovery_hash, str) or sha256_file(resolved_recovery).casefold() != recovery_hash.casefold():
                        reasons.append(_reason("RECOVERY_LINK_MISMATCH", f"{case_id} recovery manifest hash does not match."))
                except RevisionBaselineError as exc:
                    reasons.append(exc.as_dict())
        elif enforce_phase0c_provenance and case.get("historical_equivalence_claimed") is not True:
            reasons.append(_reason("FIXTURE_PROVENANCE_INVALID", "case-03 existing frozen provenance must be explicit."))
        declared_sequence = case.get("expected_sequence")
        if not isinstance(declared_sequence, list) or not all(isinstance(item, str) for item in declared_sequence):
            reasons.append(_reason("CASE_SEQUENCE_INVALID", f"{case_id}.expected_sequence must be a list of step IDs."))
            declared_sequence = []
        if expected["sequence"] is not None and declared_sequence != expected["sequence"]:
            reasons.append(_reason("CASE_SEQUENCE_INVALID", f"{case_id} must use the fixed legacy step order."))
        if case_id == "case-02" and bundle_status == "FROZEN" and not declared_sequence:
            reasons.append(_reason("CASE_SEQUENCE_MISSING", "case-02 order must be supplied by the input bundle."))
        input_status = case.get("input_status")
        if input_status == "BLOCKED":
            blockers = case.get("blockers")
            if not isinstance(blockers, list) or not blockers:
                reasons.append(_reason("CASE_SCHEMA_INVALID", f"{case_id} BLOCKED status requires blockers."))
            else:
                for blocker in blockers:
                    if not isinstance(blocker, Mapping) or not isinstance(blocker.get("code"), str) or not isinstance(blocker.get("message"), str):
                        reasons.append(_reason("CASE_SCHEMA_INVALID", f"{case_id} has an invalid blocker."))
                    else:
                        reasons.append(_reason(str(blocker["code"]), str(blocker["message"]), case_id=case_id))
            continue
        steps = case.get("steps")
        if not isinstance(steps, list) or not steps:
            reasons.append(_reason("CASE_INPUT_MISSING", f"{case_id} has no frozen input steps."))
            continue
        step_ids = [step.get("step_id") for step in steps if isinstance(step, Mapping)]
        if step_ids != declared_sequence:
            reasons.append(_reason("CASE_SEQUENCE_INVALID", f"{case_id}.steps does not match expected_sequence."))
        if input_status != "FROZEN":
            reasons.append(_reason("CASE_INPUT_MISSING", f"{case_id} input_status is not FROZEN."))
        prior_ids: set[str] = set()
        for step in steps:
            if not isinstance(step, Mapping):
                reasons.append(_reason("STEP_SCHEMA_INVALID", f"{case_id} contains a non-mapping step."))
                continue
            step_id = step.get("step_id")
            if not isinstance(step_id, str) or not step_id:
                reasons.append(_reason("STEP_SCHEMA_INVALID", f"{case_id} contains a step without step_id."))
                continue
            request_value = step.get("request_path")
            if not isinstance(request_value, str) or not request_value:
                reasons.append(_reason("RAW_PROMPT_MISSING", f"{case_id}/{step_id} has no request_path."))
                continue
            try:
                request_path = _safe_repo_path(
                    request_value,
                    root=root,
                    field=f"{case_id}/{step_id}.request_path",
                    must_exist=True,
                )
                request = _load_json_mapping(request_path, field=f"{case_id}/{step_id}")
                declared_hash = step.get("request_sha256")
                actual_hash = sha256_file(request_path)
                if not isinstance(declared_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", declared_hash):
                    reasons.append(_reason("REQUEST_HASH_MISSING", f"{case_id}/{step_id} must declare request_sha256."))
                elif declared_hash.casefold() != actual_hash.casefold():
                    reasons.append(_reason("REQUEST_HASH_MISMATCH", f"{case_id}/{step_id} request SHA-256 does not match."))
                if enforce_phase0c_provenance and case_id == "case-03" and declared_hash != "522b26dd0a31ae2688a0faaef45c32159636dd1e00a3a077b98041b1dde07ace":
                    reasons.append(_reason("CASE03_IMMUTABILITY_VIOLATION", "case-03 request hash changed."))
                previous = step.get("previous_output_from")
                if previous is not None and (not isinstance(previous, str) or previous not in prior_ids):
                    reasons.append(_reason("PRIOR_OUTPUT_ORDER_INVALID", f"{case_id}/{step_id} previous_output_from is not an earlier step."))
                reasons.extend(
                    _validate_request_file(
                        request_path,
                        request=request,
                        root=root,
                        previous_output_from=previous if isinstance(previous, str) else None,
                        field_prefix=f"{case_id}/{step_id}",
                    )
                )
            except RevisionBaselineError as exc:
                reasons.append(exc.as_dict())
            prior_ids.add(step_id)

    missing_cases = sorted(set(EXPECTED_CASES) - seen_cases)
    for case_id in missing_cases:
        reasons.append(_reason("CASE_MISSING", f"Required case is missing: {case_id}"))
    return {
        "status": "READY" if not reasons else "BLOCKED",
        "fixture_path": str(fixture),
        "fixture": document,
        "reasons": reasons,
    }


def _replace_request_paths(value: Any, *, root: Path, previous_outputs: Mapping[str, Path]) -> Any:
    if isinstance(value, str):
        matches = list(PATH_TOKEN_RE.finditer(value))
        if not matches:
            return value
        if len(matches) != 1 or matches[0].span() != (0, len(value)):
            raise RevisionBaselineError("PRIOR_OUTPUT_TRANSFER_UNSUPPORTED", f"Prior-output token must be the complete path value: {value}")
        step_id = matches[0].group(1)
        if step_id not in previous_outputs:
            raise RevisionBaselineError("PRIOR_OUTPUT_NOT_AVAILABLE", f"No captured output is available for {step_id}.")
        return str(previous_outputs[step_id].resolve())
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            replaced = _replace_request_paths(item, root=root, previous_outputs=previous_outputs)
            if key == "path" and isinstance(replaced, str) and not Path(replaced).is_absolute():
                try:
                    replaced = str(_safe_repo_path(replaced, root=root, field="request reference path", must_exist=True))
                except RevisionBaselineError:
                    raise
            elif key == "path" and isinstance(replaced, str):
                from archive_paths import relocate
                replaced = str(relocate(replaced, root=root))
            result[str(key)] = replaced
        return result
    if isinstance(value, list):
        return [_replace_request_paths(item, root=root, previous_outputs=previous_outputs) for item in value]
    return copy.deepcopy(value)


def materialize_request(
    request: Mapping[str, Any],
    *,
    root: Path = ROOT,
    previous_outputs: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    previous = {key: Path(value).resolve() for key, value in (previous_outputs or {}).items()}
    materialized = _replace_request_paths(request, root=Path(root).resolve(), previous_outputs=previous)
    if not isinstance(materialized, dict):
        raise RevisionBaselineError("REQUEST_SCHEMA_INVALID", "Materialized request must be a mapping.")
    return materialized


class ObservingProvider:
    """Observe the exact arguments while preserving provider behavior."""

    def __init__(self, provider: Callable[..., Any]):
        if not callable(provider):
            raise RevisionBaselineError("INVALID_PROVIDER_BINDING", "Provider binding is not callable.")
        self.provider = provider
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *, prompt: str, referenced_image_paths: list[str]) -> Any:
        call: dict[str, Any] = {
            "prompt": prompt,
            "referenced_image_paths": list(referenced_image_paths),
            "started_at": _utc_now(),
        }
        try:
            result = self.provider(prompt=prompt, referenced_image_paths=list(referenced_image_paths))
        except Exception as exc:
            call["finished_at"] = _utc_now()
            call["error"] = {"type": type(exc).__name__, "message": str(exc)}
            self.calls.append(call)
            raise
        call["finished_at"] = _utc_now()
        call["result"] = _to_builtin(result)
        self.calls.append(call)
        return result


def load_provider_binding(spec: str) -> Callable[..., Any]:
    if not isinstance(spec, str) or ":" not in spec:
        raise FixtureBlocked("PROVIDER_BINDING_INVALID", "Provider binding must use module.path:callable.")
    module_name, callable_name = spec.rsplit(":", 1)
    if not module_name or not callable_name:
        raise FixtureBlocked("PROVIDER_BINDING_INVALID", "Provider binding must use module.path:callable.")
    try:
        module = importlib.import_module(module_name)
        provider = getattr(module, callable_name)
    except (ImportError, AttributeError) as exc:
        raise FixtureBlocked("PROVIDER_BINDING_UNAVAILABLE", f"Could not load provider binding {spec}: {exc}") from exc
    try:
        signature = inspect.signature(provider)
    except (TypeError, ValueError) as exc:
        raise FixtureBlocked("PROVIDER_SIGNATURE_INVALID", f"Could not inspect provider binding {spec}: {exc}") from exc
    parameters = list(signature.parameters.values())
    expected = {"prompt", "referenced_image_paths"}
    actual = {parameter.name for parameter in parameters}
    if actual != expected or any(parameter.kind is not inspect.Parameter.KEYWORD_ONLY for parameter in parameters):
        raise FixtureBlocked(
            "PROVIDER_SIGNATURE_INVALID",
            "Provider must expose exactly keyword-only prompt and referenced_image_paths parameters.",
            details={"binding": spec, "signature": str(signature)},
        )
    return provider


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RevisionBaselineError("MANIFEST_READ_FAILED", str(exc)) from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RevisionBaselineError("MANIFEST_INVALID", f"Invalid JSON on manifest line {line_number}.") from exc
        if not isinstance(record, dict):
            raise RevisionBaselineError("MANIFEST_INVALID", f"Manifest line {line_number} is not a mapping.")
        key = (str(record.get("case_id")), str(record.get("step_id")), int(record.get("attempt", -1)))
        if key in seen:
            raise RevisionBaselineError("MANIFEST_DUPLICATE", f"Duplicate manifest attempt: {key}")
        seen.add(key)
        records.append(record)
    return records


def _write_once(path: Path, payload: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise RevisionBaselineError("WRITE_ONCE_READ_FAILED", str(exc)) from exc
        if existing != payload:
            raise RevisionBaselineError("WRITE_ONCE_CONFLICT", f"Refusing to overwrite {path}.")
        return False
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        return _write_once(path, payload)
    except OSError as exc:
        raise RevisionBaselineError("WRITE_ONCE_FAILED", f"Could not write {path}: {exc}") from exc
    return True


def _codex_task_payload(task: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(task)
    payload.pop("task_sha256", None)
    return payload


def _codex_task_path(capture_dir: Path, case_id: str, step_id: str, attempt: int) -> Path:
    return capture_dir / "tasks" / _slug(case_id) / f"{_slug(step_id)}-attempt-{attempt}.json"


def _load_codex_task(path: Path, *, root: Path, capture_dir: Path) -> dict[str, Any]:
    try:
        task = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RevisionBaselineError("CODEX_TASK_INVALID", f"Could not read Codex task {path}: {exc}") from exc
    if not isinstance(task, dict) or task.get("schema_version") != CODEX_TASK_SCHEMA_VERSION:
        raise RevisionBaselineError("CODEX_TASK_INVALID", "Unsupported Codex task schema.")
    if task.get("task_sha256") != sha256_text(canonical_json(_codex_task_payload(task))):
        raise RevisionBaselineError("CODEX_TASK_HASH_MISMATCH", "Codex task hash is invalid.")
    prompt = task.get("prompt")
    paths = task.get("referenced_image_paths")
    references = task.get("references")
    if not isinstance(prompt, str) or task.get("prompt_sha256") != sha256_text(prompt):
        raise RevisionBaselineError("CODEX_TASK_PROMPT_MISMATCH", "Codex task prompt hash is invalid.")
    if not isinstance(paths, list) or not isinstance(references, list) or len(paths) != len(references):
        raise RevisionBaselineError("CODEX_TASK_REFERENCE_MISMATCH", "Codex task reference sequence is invalid.")
    for index, item in enumerate(references):
        if not isinstance(item, Mapping) or item.get("path") != paths[index]:
            raise RevisionBaselineError("CODEX_TASK_REFERENCE_MISMATCH", "Codex task reference order changed.")
        reference_path = Path(str(paths[index])).resolve(strict=False)
        if not reference_path.is_file() or sha256_file(reference_path) != item.get("sha256"):
            raise RevisionBaselineError("CODEX_TASK_REFERENCE_MISMATCH", f"Codex task reference changed: {paths[index]}")
    try:
        path.resolve().relative_to((capture_dir / "tasks").resolve())
    except ValueError as exc:
        raise RevisionBaselineError("UNSAFE_PATH", "Codex task must be inside baseline/tasks.") from exc
    return task


def _next_uncaptured_step(
    document: Mapping[str, Any], records: Sequence[Mapping[str, Any]], *, root: Path, capture_dir: Path
) -> tuple[Mapping[str, Any], Mapping[str, Any], dict[str, Path]] | None:
    for case in document["cases"]:
        prior_outputs: dict[str, Path] = {}
        for step in case["steps"]:
            success = _successful_record(records, str(case["case_id"]), str(step["step_id"]), prefer_real=True)
            if success is None:
                previous = step.get("previous_output_from")
                if previous and str(previous) not in prior_outputs:
                    raise RevisionBaselineError("PRIOR_OUTPUT_NOT_AVAILABLE", f"Canonical parent is missing for {case['case_id']}/{step['step_id']}.")
                return case, step, prior_outputs
            prior_outputs[str(step["step_id"])] = _output_path_from_record(success, root=root, capture_dir=capture_dir)
    return None


class _CodexTaskEmitter:
    def __init__(self, *, task_path: Path, case_id: str, step_id: str, attempt: int, request_path: Path):
        self.task_path = task_path
        self.case_id = case_id
        self.step_id = step_id
        self.attempt = attempt
        self.request_path = request_path

    def __call__(self, *, prompt: str, referenced_image_paths: list[str]) -> Any:
        references = [
            {"path": str(Path(path).resolve()), "sha256": sha256_file(Path(path).resolve())}
            for path in referenced_image_paths
        ]
        stable: dict[str, Any] = {
            "schema_version": CODEX_TASK_SCHEMA_VERSION,
            "task_id": f"{self.case_id}:{self.step_id}:attempt-{self.attempt}",
            "case_id": self.case_id,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "request_path": str(self.request_path),
            "request_sha256": sha256_file(self.request_path),
            "prompt": prompt,
            "prompt_sha256": sha256_text(prompt),
            "referenced_image_paths": [str(Path(path).resolve()) for path in referenced_image_paths],
            "references": references,
            "execution_mode": "codex-managed-real",
            "provider": "builtin_image_gen",
        }
        if self.task_path.is_file():
            existing = json.loads(self.task_path.read_text(encoding="utf-8"))
            comparable = dict(existing)
            comparable.pop("created_at", None)
            comparable.pop("task_sha256", None)
            if comparable != stable:
                raise RevisionBaselineError("WRITE_ONCE_CONFLICT", f"Refusing to replace changed task {self.task_path}.")
            raise CodexTaskPending(str(self.task_path))
        task = {**stable, "created_at": _utc_now()}
        task["task_sha256"] = sha256_text(canonical_json(task))
        _write_once(self.task_path, (canonical_json(task) + "\n").encode("utf-8"))
        raise CodexTaskPending(str(self.task_path))


class _AcceptedCodexProvider:
    def __init__(self, task: Mapping[str, Any], generated_path: Path):
        self.task = task
        self.generated_path = generated_path.resolve()

    def __call__(self, *, prompt: str, referenced_image_paths: list[str]) -> str:
        if prompt != self.task.get("prompt") or sha256_text(prompt) != self.task.get("prompt_sha256"):
            raise RevisionBaselineError("CODEX_TASK_PROMPT_MISMATCH", "Production prompt differs from immutable Codex task.")
        expected = [str(Path(path).resolve()) for path in self.task.get("referenced_image_paths", [])]
        actual = [str(Path(path).resolve()) for path in referenced_image_paths]
        if actual != expected:
            raise RevisionBaselineError("CODEX_TASK_REFERENCE_MISMATCH", "Production reference order differs from immutable Codex task.")
        if not self.generated_path.is_file() or self.generated_path.stat().st_size == 0:
            raise RevisionBaselineError("CODEX_OUTPUT_MISSING", "Codex generated output is missing or empty.")
        if self.generated_path.suffix.lower() != ".png" or self.generated_path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise RevisionBaselineError("CODEX_OUTPUT_INVALID", "Codex generated output must be a PNG.")
        if any(_canonical_path(self.generated_path) == _canonical_path(Path(path)) for path in referenced_image_paths):
            raise RevisionBaselineError("OUTPUT_INPUT_ALIAS", "Codex output aliases a reference input.")
        return str(self.generated_path)


def prepare_codex_task(
    fixture_path: str | Path = DEFAULT_FIXTURE, *, root: Path = ROOT, capture_dir: Path | None = None
) -> dict[str, Any]:
    root = Path(root).resolve()
    fixture = Path(fixture_path).resolve()
    validation = validate_fixture(fixture, root=root, check_environment=True)
    if validation["status"] != "READY":
        return {"status": "BLOCKED", "reasons": validation["reasons"]}
    artifact_root = (capture_dir or fixture.parent / "baseline").resolve()
    records = _read_manifest(artifact_root / "manifest.jsonl")
    target = _next_uncaptured_step(validation["fixture"], records, root=root, capture_dir=artifact_root)
    if target is None:
        return {"status": "COMPLETE", "message": "All real steps are already captured."}
    case, step, prior_outputs = target
    case_id, step_id = str(case["case_id"]), str(step["step_id"])
    attempt = _attempt_number(records, case_id, step_id)
    request_path = _safe_repo_path(step["request_path"], root=root, field="request_path", must_exist=True)
    request = _load_json_mapping(request_path, field=f"{case_id}/{step_id}")
    materialized = materialize_request(request, root=root, previous_outputs=prior_outputs)
    task_path = _codex_task_path(artifact_root, case_id, step_id, attempt)
    emitter = _CodexTaskEmitter(task_path=task_path, case_id=case_id, step_id=step_id, attempt=attempt, request_path=request_path)
    try:
        run_production_generation(materialized, builtin_image_gen=emitter, root=root)
    except Exception as exc:
        cause: BaseException | None = exc
        while cause is not None and not isinstance(cause, CodexTaskPending):
            cause = cause.__cause__
        if isinstance(cause, CodexTaskPending):
            task = _load_codex_task(task_path, root=root, capture_dir=artifact_root)
            return {"status": "READY", "task_path": str(task_path), "task": task}
        raise
    raise RevisionBaselineError("PROVIDER_OBSERVATION_MISSING", "Production path did not reach builtin_image_gen.")


def _append_manifest(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_manifest(path)
    key = (str(record.get("case_id")), str(record.get("step_id")), int(record.get("attempt", -1)))
    if any((str(item.get("case_id")), str(item.get("step_id")), int(item.get("attempt", -1))) == key for item in existing):
        raise RevisionBaselineError("MANIFEST_DUPLICATE", f"Refusing duplicate manifest attempt: {key}")
    line = (canonical_json(record) + "\n").encode("utf-8")
    try:
        with path.open("ab") as handle:
            handle.write(line)
            handle.flush()
    except OSError as exc:
        raise RevisionBaselineError("MANIFEST_WRITE_FAILED", f"Could not append {path}: {exc}") from exc


def _slug(value: str) -> str:
    result = SLUG_RE.sub("-", value).strip("-")
    return result or "item"


def _file_record(path: str | Path, *, root: Path, source: str | None = None) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve(strict=False)
    if not resolved.is_file():
        raise RevisionBaselineError("FILE_NOT_FOUND", f"Missing file: {path}")
    return {
        "path": _stable_locator(resolved, root=root),
        "source": source or _stable_locator(resolved, root=root),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _reference_record(reference: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    record = _to_builtin(reference)
    if not isinstance(record, dict):
        raise RevisionBaselineError("REFERENCE_RECORD_INVALID", "Reference must be a mapping.")
    path = record.get("path")
    if path:
        file_info = _file_record(path, root=root)
        declared = record.get("sha256")
        record["declared_sha256"] = declared
        record["sha256"] = file_info["sha256"]
        record["size_bytes"] = file_info["size_bytes"]
        record["path"] = file_info["path"]
        record["sha256_verified"] = not declared or str(declared).casefold() == file_info["sha256"].casefold()
        if not record["sha256_verified"]:
            raise RevisionBaselineError("REFERENCE_HASH_MISMATCH", f"Selected reference hash does not match: {path}")
    return record


def _stable_plan(plan: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    result = _to_builtin(plan)
    if not isinstance(result, dict):
        raise RevisionBaselineError("INVOCATION_PLAN_INVALID", "Invocation Plan must be a mapping.")
    paths = result.get("referenced_image_paths")
    if isinstance(paths, list):
        result["referenced_image_paths"] = [_stable_locator(path, root=root) for path in paths]
    return result


def _provider_payload_record(call: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    prompt = call.get("prompt")
    paths = call.get("referenced_image_paths")
    if not isinstance(prompt, str) or not isinstance(paths, list):
        raise RevisionBaselineError("PROVIDER_PAYLOAD_INVALID", "Observed provider payload is incomplete.")
    return {
        "prompt": prompt,
        "referenced_image_paths": [_stable_locator(path, root=root) for path in paths],
        "fields": ["prompt", "referenced_image_paths"],
    }


def _assert_provider_parity(
    result: ProductionGenerationResult,
    call: Mapping[str, Any],
) -> None:
    plan = result.invocation_plan
    if call.get("prompt") != plan.get("prompt") or result.prompt != call.get("prompt"):
        raise RevisionBaselineError("PROMPT_CAPTURE_MISMATCH", "Compiled prompt and provider prompt differ.")
    plan_paths = plan.get("referenced_image_paths")
    observed_paths = call.get("referenced_image_paths")
    if not isinstance(plan_paths, list) or not isinstance(observed_paths, list) or not _same_path_sequence(plan_paths, observed_paths):
        raise RevisionBaselineError("PROVIDER_PAYLOAD_MISMATCH", "Provider paths differ from Invocation Plan order.")


def _attempt_number(records: Sequence[Mapping[str, Any]], case_id: str, step_id: str) -> int:
    values = [
        int(item["attempt"])
        for item in records
        if item.get("case_id") == case_id and item.get("step_id") == step_id and isinstance(item.get("attempt"), int)
    ]
    return max(values, default=0) + 1


def _successful_record(
    records: Sequence[Mapping[str, Any]],
    case_id: str,
    step_id: str,
    *,
    prefer_real: bool = False,
) -> dict[str, Any] | None:
    matches = [
        dict(item)
        for item in records
        if item.get("case_id") == case_id and item.get("step_id") == step_id and item.get("status") == "SUCCESS"
    ]
    if prefer_real:
        real = [item for item in matches if item.get("execution_mode") == "real"]
        if real:
            matches = real
    if not matches:
        return None
    return sorted(matches, key=lambda item: int(item.get("attempt", 0)))[0]


def _output_path_from_record(record: Mapping[str, Any], *, root: Path, capture_dir: Path) -> Path:
    output = record.get("output")
    if not isinstance(output, Mapping) or not isinstance(output.get("copied_path"), str):
        raise RevisionBaselineError("OUTPUT_RECORD_INVALID", "Successful record lacks copied output path.")
    copied = output["copied_path"]
    candidate = Path(copied)
    if candidate.is_absolute():
        return candidate.resolve()
    return (capture_dir / copied).resolve()


def _make_execution(mode: str, started: str, finished: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mode": mode,
        "provider": "builtin_image_gen",
        "started_at": started,
        "finished_at": finished,
        "model": None,
        "seed": None,
        "generation_parameters": None,
        "unavailable_metadata": ["model", "seed", "generation_parameters"],
        "baseline_commit": snapshot.get("head"),
    }


def _receipt_path(capture_dir: Path, case_id: str, step_id: str, attempt: int) -> Path:
    return capture_dir / "receipts" / _slug(case_id) / f"{_slug(step_id)}-attempt-{attempt}.json"


def _output_destination(capture_dir: Path, case_id: str, step_id: str, attempt: int, source: Path) -> Path:
    suffix = source.suffix or ".bin"
    return capture_dir / "outputs" / _slug(case_id) / f"{_slug(step_id)}-attempt-{attempt}{suffix}"


def _copy_output_once(source: Path, destination: Path) -> dict[str, Any]:
    source = source.resolve()
    if not source.is_file():
        raise RevisionBaselineError("GENERATED_OUTPUT_NOT_FOUND", str(source))
    source_hash = sha256_file(source)
    if destination.exists():
        if sha256_file(destination) != source_hash:
            raise RevisionBaselineError("WRITE_ONCE_CONFLICT", f"Output destination already differs: {destination}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, destination)
        except OSError as exc:
            raise RevisionBaselineError("OUTPUT_COPY_FAILED", f"Could not copy output to {destination}: {exc}") from exc
    if sha256_file(destination) != source_hash:
        raise RevisionBaselineError("OUTPUT_HASH_MISMATCH", f"Output copy hash differs: {destination}")
    return {
        "source_path": str(source),
        "copied_path": str(destination.relative_to(destination.parents[2])) if len(destination.parents) >= 3 else str(destination),
        "sha256": source_hash,
        "size_bytes": destination.stat().st_size,
    }


def _record_attempt(
    *,
    record: Mapping[str, Any],
    capture_dir: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    base = _to_builtin(record)
    if not isinstance(base, dict):
        raise RevisionBaselineError("SERIALIZATION_FAILED", "Attempt record must be a mapping.")
    receipt_path = _receipt_path(capture_dir, str(base["case_id"]), str(base["step_id"]), int(base["attempt"]))
    base["receipt_path"] = _stable_locator(receipt_path, root=capture_dir)
    unsigned = dict(base)
    unsigned.pop("receipt_sha256", None)
    receipt_hash = sha256_text(canonical_json(unsigned))
    base["receipt_sha256"] = receipt_hash
    _write_once(receipt_path, (canonical_json(base) + "\n").encode("utf-8"))
    _append_manifest(manifest_path, base)
    return base


def _capture_error_record(
    *,
    case_id: str,
    step_id: str,
    attempt: int,
    execution_mode: str,
    request: Mapping[str, Any] | None,
    started: str,
    finished: str,
    snapshot: Mapping[str, Any],
    error: RevisionBaselineError | Exception,
) -> dict[str, Any]:
    if isinstance(error, RevisionBaselineError):
        error_record = error.as_dict()
    else:
        error_record = {"code": type(error).__name__, "message": str(error)}
    raw_prompt = request.get("base_prompt") if isinstance(request, Mapping) else None
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "step_id": step_id,
        "attempt": attempt,
        "status": "FAILED",
        "canonical": False,
        "execution_mode": execution_mode,
        "raw_prompt": raw_prompt,
        "raw_prompt_sha256": sha256_text(raw_prompt) if isinstance(raw_prompt, str) else None,
        "compiled_prompt": None,
        "compiled_prompt_sha256": None,
        "resolved_references": [],
        "invocation_plan": None,
        "invocation_plan_stable": None,
        "invocation_plan_sha256": None,
        "provider_payload": None,
        "input": {"request": None, "previous_outputs": []},
        "output": None,
        "execution": _make_execution(execution_mode, started, finished, snapshot),
        "error": error_record,
    }


def capture_fixture(
    fixture_path: str | Path = DEFAULT_FIXTURE,
    *,
    provider: Callable[..., Any] | None = None,
    provider_binding: str | None = None,
    root: Path = ROOT,
    capture_dir: Path | None = None,
    execution_mode: str = "real",
    max_new_successes: int | None = None,
) -> dict[str, Any]:
    """Capture all declared steps through the existing production boundary."""

    root = Path(root).resolve()
    fixture = Path(fixture_path).resolve()
    validation = validate_fixture(fixture, root=root, check_environment=True)
    if validation["status"] != "READY":
        return {"status": "BLOCKED", "fixture_path": str(fixture), "reasons": validation["reasons"], "cases": []}
    document = validation["fixture"]
    baseline = document["baseline"]
    snapshot = snapshot_baseline(root, baseline["protected_runtime_paths"])
    artifact_root = (capture_dir or fixture.parent / "baseline").resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    environment_path = artifact_root / "environment.json"
    environment_payload = {"schema_version": SCHEMA_VERSION, "baseline": snapshot}
    if environment_path.exists():
        try:
            existing_environment = json.loads(environment_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RevisionBaselineError("ENVIRONMENT_INVALID", f"Could not read {environment_path}: {exc}") from exc
        if existing_environment.get("baseline", {}).get("head") != snapshot.get("head") or existing_environment.get("baseline", {}).get("protected_runtime_hashes") != snapshot.get("protected_runtime_hashes"):
            raise RevisionBaselineError("WRITE_ONCE_CONFLICT", f"Baseline environment changed: {environment_path}")
    else:
        _write_once(environment_path, (canonical_json(environment_payload) + "\n").encode("utf-8"))
    manifest_path = artifact_root / "manifest.jsonl"
    records = _read_manifest(manifest_path)
    if provider is None:
        if not provider_binding:
            return {"status": "BLOCKED", "fixture_path": str(fixture), "reasons": [_reason("PROVIDER_BINDING_MISSING", "No builtin_image_gen provider binding was supplied.")], "cases": []}
        try:
            provider = load_provider_binding(provider_binding)
        except FixtureBlocked as exc:
            return {"status": "BLOCKED", "fixture_path": str(fixture), "reasons": [exc.as_dict()], "cases": []}
    observer = ObservingProvider(provider)
    results: list[dict[str, Any]] = []
    new_successes = 0
    stop_capture = False

    for case in document["cases"]:
        case_id = str(case["case_id"])
        case_result: dict[str, Any] = {"case_id": case_id, "status": "PASS", "steps": []}
        prior_outputs: dict[str, Path] = {}
        for step in case["steps"]:
            step_id = str(step["step_id"])
            existing_success = _successful_record(records, case_id, step_id, prefer_real=execution_mode == "real")
            if existing_success is not None and existing_success.get("execution_mode") == execution_mode:
                try:
                    prior_outputs[step_id] = _output_path_from_record(existing_success, root=root, capture_dir=artifact_root)
                except RevisionBaselineError as exc:
                    case_result["status"] = "BLOCKED"
                    case_result["steps"].append({"step_id": step_id, "status": "BLOCKED", "error": exc.as_dict()})
                    break
                case_result["steps"].append({"step_id": step_id, "status": "SKIPPED", "attempt": existing_success.get("attempt"), "execution_mode": execution_mode})
                continue
            attempt = _attempt_number(records, case_id, step_id)
            started = _utc_now()
            request: dict[str, Any] | None = None
            try:
                request_path = _safe_repo_path(step["request_path"], root=root, field=f"{case_id}/{step_id}.request_path", must_exist=True)
                request = _load_json_mapping(request_path, field=f"{case_id}/{step_id}")
                expected_hash = step.get("request_sha256")
                actual_hash = sha256_file(request_path)
                if str(expected_hash).casefold() != actual_hash.casefold():
                    raise RevisionBaselineError("REQUEST_HASH_MISMATCH", f"Request hash changed for {case_id}/{step_id}.")
                previous = step.get("previous_output_from")
                materialized = materialize_request(request, root=root, previous_outputs=prior_outputs)
                result = run_production_generation(materialized, builtin_image_gen=observer, root=root)
                if not observer.calls:
                    raise RevisionBaselineError("PROVIDER_OBSERVATION_MISSING", "Provider was not called by the production boundary.")
                call = observer.calls[-1]
                _assert_provider_parity(result, call)
                output_source = Path(result.output_path).resolve()
                if any(_canonical_path(output_source) == _canonical_path(path) for path in call["referenced_image_paths"]):
                    raise RevisionBaselineError("OUTPUT_INPUT_ALIAS", "Generated output aliases a reference input.")
                destination = _output_destination(artifact_root, case_id, step_id, attempt, output_source)
                output_record = _copy_output_once(output_source, destination)
                output_record["copied_path"] = _stable_locator(destination, root=artifact_root)
                resolved_references = [_reference_record(reference, root=root) for reference in result.selected_references]
                plan = _to_builtin(result.invocation_plan)
                stable_plan = _stable_plan(result.invocation_plan, root=root)
                finished = _utc_now()
                record = {
                    "schema_version": SCHEMA_VERSION,
                    "case_id": case_id,
                    "step_id": step_id,
                    "attempt": attempt,
                    "status": "SUCCESS",
                    "canonical": _successful_record(records, case_id, step_id) is None,
                    "execution_mode": execution_mode,
                    "raw_prompt": request.get("base_prompt"),
                    "raw_prompt_sha256": sha256_text(str(request.get("base_prompt"))),
                    "compiled_prompt": result.prompt,
                    "compiled_prompt_sha256": sha256_text(result.prompt),
                    "resolved_references": resolved_references,
                    "invocation_plan": plan,
                    "invocation_plan_stable": stable_plan,
                    "invocation_plan_sha256": sha256_text(canonical_json(stable_plan)),
                    "provider_payload": _provider_payload_record(call, root=root),
                    "input": {
                        "request": _file_record(request_path, root=root),
                        "previous_outputs": [
                            {
                                "step_id": str(previous),
                                "path": _stable_locator(prior_outputs[str(previous)], root=artifact_root.parent.parent),
                                "sha256": sha256_file(prior_outputs[str(previous)]),
                                "size_bytes": prior_outputs[str(previous)].stat().st_size,
                            }
                        ] if previous else [],
                    },
                    "output": output_record,
                    "execution": _make_execution(execution_mode, started, finished, snapshot),
                }
                saved = _record_attempt(record=record, capture_dir=artifact_root, manifest_path=manifest_path)
                records.append(saved)
                prior_outputs[step_id] = destination.resolve()
                case_result["steps"].append({"step_id": step_id, "status": "SUCCESS", "attempt": attempt, "execution_mode": execution_mode})
                new_successes += 1
                if max_new_successes is not None and new_successes >= max_new_successes:
                    stop_capture = True
                    break
            except Exception as exc:
                finished = _utc_now()
                if isinstance(exc, RevisionBaselineError):
                    error = exc
                elif hasattr(exc, "code"):
                    error = RevisionBaselineError(str(getattr(exc, "code")), str(exc))
                else:
                    error = RevisionBaselineError(type(exc).__name__, str(exc))
                failed = _capture_error_record(
                    case_id=case_id,
                    step_id=step_id,
                    attempt=attempt,
                    execution_mode=execution_mode,
                    request=request,
                    started=started,
                    finished=finished,
                    snapshot=snapshot,
                    error=error,
                )
                saved = _record_attempt(record=failed, capture_dir=artifact_root, manifest_path=manifest_path)
                records.append(saved)
                case_result["status"] = "BLOCKED" if isinstance(exc, FixtureBlocked) else "FAIL"
                case_result["steps"].append({"step_id": step_id, "status": case_result["status"], "attempt": attempt, "error": error.as_dict()})
                break
        if not stop_capture and case_result["status"] == "PASS" and len([item for item in case_result["steps"] if item["status"] in {"SUCCESS", "SKIPPED"}]) != len(case["steps"]):
            case_result["status"] = "BLOCKED"
        results.append(case_result)
        if stop_capture:
            break
    overall = "CAPTURED" if stop_capture else ("PASS" if results and all(item["status"] == "PASS" for item in results) else "FAIL")
    if any(item["status"] == "BLOCKED" for item in results):
        overall = "BLOCKED"
    return {"status": overall, "fixture_path": str(fixture), "manifest_path": str(manifest_path), "cases": results}


def accept_codex_task(
    task_path: str | Path,
    generated_path: str | Path,
    *,
    fixture_path: str | Path = DEFAULT_FIXTURE,
    root: Path = ROOT,
    capture_dir: Path | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    fixture = Path(fixture_path).resolve()
    artifact_root = (capture_dir or fixture.parent / "baseline").resolve()
    task_file = Path(task_path).resolve()
    task = _load_codex_task(task_file, root=root, capture_dir=artifact_root)
    validation = validate_fixture(fixture, root=root, check_environment=True)
    if validation["status"] != "READY":
        return {"status": "BLOCKED", "reasons": validation["reasons"]}
    records = _read_manifest(artifact_root / "manifest.jsonl")
    target = _next_uncaptured_step(validation["fixture"], records, root=root, capture_dir=artifact_root)
    if target is None:
        raise RevisionBaselineError("CODEX_TASK_STALE", "All frozen steps are already captured.")
    case, step, _ = target
    expected = (str(case["case_id"]), str(step["step_id"]), _attempt_number(records, str(case["case_id"]), str(step["step_id"])))
    actual = (str(task.get("case_id")), str(task.get("step_id")), int(task.get("attempt", -1)))
    if actual != expected:
        raise RevisionBaselineError("CODEX_TASK_STALE", f"Task {actual} is not the next frozen step {expected}.")
    result = capture_fixture(
        fixture,
        provider=_AcceptedCodexProvider(task, Path(generated_path)),
        root=root,
        capture_dir=artifact_root,
        execution_mode="real",
        max_new_successes=1,
    )
    result["accepted_task_path"] = str(task_file)
    return result


def fail_codex_task(
    task_path: str | Path,
    *,
    code: str,
    message: str,
    fixture_path: str | Path = DEFAULT_FIXTURE,
    root: Path = ROOT,
    capture_dir: Path | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    fixture = Path(fixture_path).resolve()
    artifact_root = (capture_dir or fixture.parent / "baseline").resolve()
    task_file = Path(task_path).resolve()
    task = _load_codex_task(task_file, root=root, capture_dir=artifact_root)
    validation = validate_fixture(fixture, root=root, check_environment=True)
    if validation["status"] != "READY":
        return {"status": "BLOCKED", "reasons": validation["reasons"]}
    records = _read_manifest(artifact_root / "manifest.jsonl")
    key = (str(task["case_id"]), str(task["step_id"]), int(task["attempt"]))
    if any((str(item.get("case_id")), str(item.get("step_id")), int(item.get("attempt", -1))) == key for item in records):
        raise RevisionBaselineError("MANIFEST_DUPLICATE", f"Attempt is already recorded: {key}")
    snapshot = snapshot_baseline(root, validation["fixture"]["baseline"]["protected_runtime_paths"])
    record = _capture_error_record(
        case_id=key[0],
        step_id=key[1],
        attempt=key[2],
        execution_mode="real",
        request=None,
        started=str(task["created_at"]),
        finished=_utc_now(),
        snapshot=snapshot,
        error=RevisionBaselineError(code, message, details={"task_path": str(task_file), "task_sha256": task["task_sha256"]}),
    )
    saved = _record_attempt(record=record, capture_dir=artifact_root, manifest_path=artifact_root / "manifest.jsonl")
    return {"status": "RECORDED", "record": saved}


def _record_references_valid(record: Mapping[str, Any], *, root: Path) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    references = record.get("resolved_references")
    if not isinstance(references, list):
        return [_reason("REFERENCES_MISSING", "Record has no resolved references.")]
    for reference in references:
        if not isinstance(reference, Mapping):
            failures.append(_reason("REFERENCE_RECORD_INVALID", "Resolved reference is not a mapping."))
            continue
        path = reference.get("path")
        declared = reference.get("sha256")
        if not isinstance(path, str) or not isinstance(declared, str):
            failures.append(_reason("REFERENCE_RECORD_INVALID", "Resolved reference lacks path or sha256."))
            continue
        try:
            resolved = _safe_repo_path(path, root=root, field="resolved reference", must_exist=True)
        except RevisionBaselineError:
            resolved = Path(path).resolve(strict=False)
        if not resolved.is_file() or sha256_file(resolved).casefold() != declared.casefold():
            failures.append(_reason("REFERENCE_HASH_MISMATCH", f"Resolved reference changed: {path}"))
    return failures


def _receipt_valid(record: Mapping[str, Any], *, capture_dir: Path) -> None:
    raw_path = record.get("receipt_path")
    if not isinstance(raw_path, str) or not raw_path:
        raise RevisionBaselineError("RECEIPT_MISSING", "Attempt record lacks receipt_path.")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        receipt_path = candidate.resolve()
    else:
        receipt_path = (capture_dir / candidate).resolve()
    try:
        receipt_path.relative_to(capture_dir.resolve())
    except ValueError as exc:
        raise RevisionBaselineError("UNSAFE_PATH", f"Receipt path escapes the baseline directory: {raw_path}") from exc
    if not receipt_path.is_file():
        raise RevisionBaselineError("RECEIPT_MISSING", f"Missing receipt: {raw_path}")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RevisionBaselineError("RECEIPT_INVALID", f"Could not read receipt {receipt_path}: {exc}") from exc
    if not isinstance(receipt, dict) or receipt.get("receipt_sha256") != record.get("receipt_sha256"):
        raise RevisionBaselineError("RECEIPT_MISMATCH", f"Receipt does not match manifest: {receipt_path}")
    unsigned = dict(receipt)
    receipt_hash = unsigned.pop("receipt_sha256", None)
    if not isinstance(receipt_hash, str) or sha256_text(canonical_json(unsigned)) != receipt_hash:
        raise RevisionBaselineError("RECEIPT_HASH_MISMATCH", f"Receipt hash is invalid: {receipt_path}")


def replay_check(
    fixture_path: str | Path = DEFAULT_FIXTURE,
    *,
    root: Path = ROOT,
    capture_dir: Path | None = None,
) -> dict[str, Any]:
    """Check recorded requests and artifacts without invoking a provider."""

    root = Path(root).resolve()
    fixture = Path(fixture_path).resolve()
    validation = validate_fixture(fixture, root=root, check_environment=True)
    if validation["status"] != "READY":
        return {"status": "BLOCKED", "fixture_path": str(fixture), "reasons": validation["reasons"], "cases": []}
    artifact_root = (capture_dir or fixture.parent / "baseline").resolve()
    records = _read_manifest(artifact_root / "manifest.jsonl")
    failures: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    for case in validation["fixture"]["cases"]:
        case_id = str(case["case_id"])
        step_results: list[dict[str, Any]] = []
        prior_output: dict[str, Path] = {}
        for step in case["steps"]:
            step_id = str(step["step_id"])
            success = _successful_record(records, case_id, step_id, prefer_real=False)
            if success is None:
                failure = _reason("CAPTURE_MISSING", f"No successful capture for {case_id}/{step_id}.")
                failures.append(failure)
                step_results.append({"step_id": step_id, "status": "BLOCKED", "error": failure})
                continue
            try:
                request_path = _safe_repo_path(step["request_path"], root=root, field="request_path", must_exist=True)
                request_hash = sha256_file(request_path)
                if request_hash.casefold() != str(step.get("request_sha256")).casefold():
                    raise RevisionBaselineError("REQUEST_HASH_MISMATCH", f"Request changed: {request_path}")
                request = _load_json_mapping(request_path, field=f"{case_id}/{step_id}")
                materialized = materialize_request(request, root=root, previous_outputs=prior_output)
                if success.get("raw_prompt") != materialized.get("base_prompt"):
                    raise RevisionBaselineError("RAW_PROMPT_MISMATCH", f"Raw prompt changed for {case_id}/{step_id}.")
                if success.get("raw_prompt_sha256") != sha256_text(str(materialized.get("base_prompt"))):
                    raise RevisionBaselineError("RAW_PROMPT_HASH_MISMATCH", f"Raw prompt hash changed for {case_id}/{step_id}.")
                _receipt_valid(success, capture_dir=artifact_root)
                reference_failures = _record_references_valid(success, root=root)
                if reference_failures:
                    raise RevisionBaselineError(
                        reference_failures[0]["code"],
                        reference_failures[0]["message"],
                        details=reference_failures,
                    )
                plan = success.get("invocation_plan_stable")
                payload = success.get("provider_payload")
                if not isinstance(plan, Mapping) or not isinstance(payload, Mapping):
                    raise RevisionBaselineError("INVOCATION_CAPTURE_MISSING", f"Invocation capture is incomplete for {case_id}/{step_id}.")
                if plan.get("prompt") != success.get("compiled_prompt") or payload.get("prompt") != plan.get("prompt"):
                    raise RevisionBaselineError("PROMPT_CAPTURE_MISMATCH", f"Recorded prompt capture differs for {case_id}/{step_id}.")
                plan_paths = plan.get("referenced_image_paths")
                payload_paths = payload.get("referenced_image_paths")
                if not isinstance(plan_paths, list) or not isinstance(payload_paths, list) or not _same_path_sequence(plan_paths, payload_paths):
                    raise RevisionBaselineError("PROVIDER_PAYLOAD_MISMATCH", f"Recorded provider paths differ for {case_id}/{step_id}.")
                output = success.get("output")
                if not isinstance(output, Mapping) or not isinstance(output.get("copied_path"), str):
                    raise RevisionBaselineError("OUTPUT_RECORD_INVALID", f"Output missing for {case_id}/{step_id}.")
                output_path = _output_path_from_record(success, root=root, capture_dir=artifact_root)
                if not output_path.is_file() or sha256_file(output_path).casefold() != str(output.get("sha256")).casefold():
                    raise RevisionBaselineError("OUTPUT_HASH_MISMATCH", f"Output changed for {case_id}/{step_id}.")
                if step.get("previous_output_from"):
                    previous_id = str(step["previous_output_from"])
                    input_record = success.get("input")
                    previous_records = input_record.get("previous_outputs") if isinstance(input_record, Mapping) else None
                    previous_record = previous_records[0] if isinstance(previous_records, list) and previous_records else None
                    if (
                        not prior_output.get(previous_id)
                        or not isinstance(previous_record, Mapping)
                        or previous_record.get("step_id") != previous_id
                        or sha256_file(prior_output[previous_id]).casefold() != str(previous_record.get("sha256")).casefold()
                    ):
                        raise RevisionBaselineError("PRIOR_OUTPUT_HASH_MISMATCH", f"Prior output changed for {case_id}/{step_id}.")
                prior_output[step_id] = output_path
                step_results.append({"step_id": step_id, "status": "PASS", "attempt": success.get("attempt"), "execution_mode": success.get("execution_mode")})
            except RevisionBaselineError as exc:
                failures.append(exc.as_dict())
                step_results.append({"step_id": step_id, "status": "FAIL", "error": exc.as_dict()})
        case_results.append({"case_id": case_id, "status": "PASS" if all(item["status"] == "PASS" for item in step_results) else "FAIL", "steps": step_results})
    if failures:
        status = "FAIL" if any(item.get("code") not in {"CAPTURE_MISSING"} for item in failures) else "BLOCKED"
    else:
        status = "PASS"
    return {"status": status, "fixture_path": str(fixture), "manifest_path": str(artifact_root / "manifest.jsonl"), "cases": case_results, "reasons": failures}


def _report_text(
    fixture_path: Path,
    validation: Mapping[str, Any],
    replay: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> str:
    fixture = validation.get("fixture") or {}
    real_success = [item for item in records if item.get("status") == "SUCCESS" and item.get("execution_mode") == "real"]
    mock_success = [item for item in records if item.get("status") == "SUCCESS" and item.get("execution_mode") != "real"]
    expected_steps = sum(len(case.get("steps", [])) for case in fixture.get("cases", []) if isinstance(case, Mapping))
    gate = "PASS" if validation.get("status") == "READY" and replay.get("status") == "PASS" and len(real_success) >= expected_steps and not mock_success else "BLOCKED"
    lines = [
        "# Arco-Skill Phase 0 structured report",
        "",
        f"- Fixture: `{fixture_path}`",
        f"- Approved baseline commit: `{APPROVED_BASELINE_COMMIT}`",
        f"- Generated at: `{_utc_now()}`",
        f"- Phase 0 Gate: **{gate}**",
        "",
        "## Scope",
        "",
        "This report covers baseline fixture validation, legacy production-path observation, write-once receipts, serialized Invocation Plans, and replay input checks. It does not score visual quality or claim stochastic pixel equality.",
        "",
        "## Fixture validation",
        "",
        f"- Status: `{validation.get('status')}`",
        f"- Reasons: `{len(validation.get('reasons', []))}`",
        "",
        "## Case matrix",
        "",
        "| Case | Expected sequence | Frozen steps | Successful real attempts | Successful non-real attempts |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for case in fixture.get("cases", []):
        if not isinstance(case, Mapping):
            continue
        case_id = case.get("case_id")
        rows = [item for item in records if item.get("case_id") == case_id]
        sequence = " -> ".join(str(item) for item in case.get("expected_sequence", [])) or "(bundle required)"
        lines.append(
            f"| `{case_id}` | `{sequence}` | {len(case.get('steps', []))} | {sum(item.get('status') == 'SUCCESS' and item.get('execution_mode') == 'real' for item in rows)} | {sum(item.get('status') == 'SUCCESS' and item.get('execution_mode') != 'real' for item in rows)} |"
        )
    lines.extend(
        [
            "",
            "## Capture boundary",
            "",
            "The capture script calls `run_production_generation()` and observes only the provider arguments. Compiled prompts, selected references, Invocation Plans, payloads, output hashes, and execution metadata are serialized per attempt.",
            "",
            "## Replay check",
            "",
            f"- Status: `{replay.get('status')}`",
            f"- Recorded attempts: `{len(records)}`",
            f"- Real successful attempts: `{len(real_success)}`",
            f"- Non-real successful attempts: `{len(mock_success)}`",
            "",
            "## Acceptance gate",
            "",
            "The gate requires every declared step to have a successful real output, compiled prompt, Invocation Plan, resolved references, write-once receipt, and passing replay-check. A fake-provider record is evidence for tests only and cannot satisfy the gate.",
            "",
            "## Blockers",
            "",
        ]
    )
    blocker_values: list[Mapping[str, Any]] = []
    seen_blockers: set[tuple[str, str]] = set()
    for item in list(validation.get("reasons", [])) + list(replay.get("reasons", [])):
        if not isinstance(item, Mapping):
            continue
        key = (str(item.get("code")), str(item.get("message")))
        if key not in seen_blockers:
            seen_blockers.add(key)
            blocker_values.append(item)
    if blocker_values:
        for item in blocker_values:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('code')}`: {item.get('message')}")
    else:
        lines.append("- None recorded.")
    lines.extend(
        [
            "",
            "## Production boundary",
            "",
            "No Revision Runtime, provider schema, routing, retry policy, re-anchor, readability gate, visual scoring, or formal Arco asset was changed by Phase 0.",
            "",
            "## Evidence locations",
            "",
            "- `baseline/manifest.jsonl` — append-only attempt records.",
            "- `baseline/receipts/` — write-once attempt receipts.",
            "- `baseline/outputs/` — isolated generated-output copies.",
            "- `phase-0-contract.md` — schema and fail-closed contract.",
            "",
        ]
    )
    return "\n".join(lines)


def report_fixture(
    fixture_path: str | Path = DEFAULT_FIXTURE,
    *,
    root: Path = ROOT,
    capture_dir: Path | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    fixture = Path(fixture_path).resolve()
    validation = validate_fixture(fixture, root=root, check_environment=True)
    artifact_root = (capture_dir or fixture.parent / "baseline").resolve()
    records = _read_manifest(artifact_root / "manifest.jsonl")
    replay = replay_check(fixture, root=root, capture_dir=artifact_root) if validation.get("status") == "READY" else {"status": "BLOCKED", "reasons": validation.get("reasons", [])}
    report_path = fixture.parent / "phase-0-report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_report_text(fixture, validation, replay, records), encoding="utf-8", newline="\n")
    gate = "PASS" if validation.get("status") == "READY" and replay.get("status") == "PASS" and all(item.get("execution_mode") == "real" for item in records if item.get("status") == "SUCCESS") and records else "BLOCKED"
    return {"status": gate, "fixture_path": str(fixture), "report_path": str(report_path), "validation": validation, "replay": replay, "record_count": len(records)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "replay-check", "report"):
        command = subparsers.add_parser(name)
        command.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    capture = subparsers.add_parser("capture")
    capture.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    capture.add_argument("--provider-binding")
    capture.add_argument("--codex-managed", action="store_true")
    prepare = subparsers.add_parser("prepare-codex-task")
    prepare.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    accept = subparsers.add_parser("accept-codex-task")
    accept.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    accept.add_argument("--task", required=True)
    accept.add_argument("--generated-path", required=True)
    failed = subparsers.add_parser("fail-codex-task")
    failed.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    failed.add_argument("--task", required=True)
    failed.add_argument("--code", required=True)
    failed.add_argument("--message", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            result = validate_fixture(args.fixture)
        elif args.command == "capture":
            if args.codex_managed and args.provider_binding:
                raise RevisionBaselineError("PROVIDER_MODE_CONFLICT", "Choose --codex-managed or --provider-binding, not both.")
            result = prepare_codex_task(args.fixture) if args.codex_managed else capture_fixture(args.fixture, provider_binding=args.provider_binding)
        elif args.command == "prepare-codex-task":
            result = prepare_codex_task(args.fixture)
        elif args.command == "accept-codex-task":
            result = accept_codex_task(args.task, args.generated_path, fixture_path=args.fixture)
        elif args.command == "fail-codex-task":
            result = fail_codex_task(args.task, code=args.code, message=args.message, fixture_path=args.fixture)
        elif args.command == "replay-check":
            result = replay_check(args.fixture)
        else:
            result = report_fixture(args.fixture)
    except RevisionBaselineError as exc:
        result = {"status": "FAIL", "error": exc.as_dict()}
    print(json.dumps(_to_builtin(result), ensure_ascii=False, indent=2, sort_keys=True))
    status = result.get("status")
    if status in {"PASS", "READY", "CAPTURED", "COMPLETE", "RECORDED"}:
        return 0
    if status == "BLOCKED":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "APPROVED_BASELINE_COMMIT",
    "FixtureBlocked",
    "ObservingProvider",
    "RevisionBaselineError",
    "canonical_json",
    "accept_codex_task",
    "capture_fixture",
    "fail_codex_task",
    "load_provider_binding",
    "main",
    "materialize_request",
    "prepare_codex_task",
    "replay_check",
    "report_fixture",
    "sha256_file",
    "sha256_text",
    "snapshot_baseline",
    "validate_fixture",
]
