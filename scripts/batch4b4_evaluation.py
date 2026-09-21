#!/usr/bin/env python3
"""Batch 4B.4 blind visual evaluation driver.

This task-local driver deliberately keeps the frozen verdict inputs read-only.
It creates private byte-identical blind copies, validates manually entered
blinded judgements, and performs exactly one unblind step after both passes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import secrets
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
EVALUATION_DIR = ROOT / "evaluation" / "style-regression"
VERDICT_SET_PATH = EVALUATION_DIR / "verdict-set.json"
MANIFEST_PATH = EVALUATION_DIR / "manifest.jsonl"
CASES_PATH = EVALUATION_DIR / "cases.yaml"
PRIVATE_DIR = EVALUATION_DIR / "private-assets"
BLIND_DIR = PRIVATE_DIR / "blind-review"
BLIND_MAP_PATH = EVALUATION_DIR / "blind-map.private.json"
PAIRING_PATH = PRIVATE_DIR / "blind-pairing.private.json"
JUDGEMENTS_PATH = PRIVATE_DIR / "blind-judgments.private.json"
PAIRWISE_JUDGEMENTS_PATH = PRIVATE_DIR / "pairwise-judgments.private.json"
HASH_SNAPSHOT_PATH = PRIVATE_DIR / "batch-4b.4-input-hashes.private.json"
BLIND_CSV_PATH = EVALUATION_DIR / "blind-evaluation.csv"
PAIRWISE_CSV_PATH = EVALUATION_DIR / "pairwise-evaluation.csv"
RESULTS_PATH = EVALUATION_DIR / "batch-4b.4-results.md"
VERDICT_PATH = EVALUATION_DIR / "style-transfer-v1-verdict.md"

STYLE_AXES = [
    "linework",
    "shading",
    "color_logic",
    "highlight_language",
    "material_rendering",
    "texture_language",
    "lighting_language",
    "background_rendering",
    "detail_density",
    "edge_treatment",
]
ARTIFACT_FIELDS = [
    "unsupported_detail_inflation",
    "highlight_organization_drift",
    "texture_noise_drift",
    "material_rendering_drift",
    "lighting_effect_inflation",
    "detail_hierarchy_flattening",
]
STRUCTURAL_FIELDS = [
    "hands",
    "anatomy",
    "object_geometry",
    "perspective",
    "structural_consistency",
]
IDENTITY_VALUES = {"PASS", "MINOR", "FAIL"}
STYLE_VALUES = {"0", "1", "2", "N/A"}
ARTIFACT_VALUES = {"NONE", "MINOR", "MAJOR"}
STRUCTURAL_VALUES = {"PASS", "MINOR", "MAJOR"}
CHOICE_VALUES = {"left", "right", "tie"}
CONFIDENCE_VALUES = {"low", "medium", "high"}
ARTIFACT_SCORE = {"NONE": 0, "MINOR": 1, "MAJOR": 2}
STRUCTURAL_SCORE = {"PASS": 0, "MINOR": 1, "MAJOR": 2}
IDENTITY_SCORE = {"FAIL": 0, "MINOR": 1, "PASS": 2}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover - the project already requires PyYAML
        raise RuntimeError("PyYAML is required to read the frozen cases.yaml") from exc
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError("Frozen cases.yaml must contain a mapping")
    return value


def load_cases() -> tuple[dict[str, Mapping[str, Any]], dict[str, list[str]]]:
    document = load_yaml(CASES_PATH)
    cases = {}
    active = {}
    for item in document.get("cases", []):
        if not isinstance(item, Mapping) or not isinstance(item.get("case_id"), str):
            raise RuntimeError("Frozen cases.yaml contains an invalid case")
        case_id = str(item["case_id"])
        cases[case_id] = item
        axes = item.get("expected_relevant_style_axes") or []
        if not isinstance(axes, list) or not all(isinstance(axis, str) for axis in axes):
            raise RuntimeError(f"{case_id} has invalid expected_relevant_style_axes")
        active[case_id] = list(axes)
    if set(cases) != {f"case-{index:02d}" for index in range(1, 5)}:
        raise RuntimeError("Frozen cases.yaml must contain exactly case-01 through case-04")
    return cases, active


def load_manifest() -> dict[str, Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = row.get("sample_key")
        if isinstance(key, str):
            rows[key] = row
    return rows


def parse_sample_id(sample_id: str) -> tuple[str, str, int]:
    parts = sample_id.split(":")
    if len(parts) != 3 or not parts[0].startswith("case-") or parts[1] not in {"A", "B", "C"}:
        raise RuntimeError(f"Invalid frozen sample id: {sample_id}")
    try:
        replicate = int(parts[2][1:]) if parts[2].startswith("r") else -1
    except ValueError as exc:
        raise RuntimeError(f"Invalid frozen replicate in {sample_id}") from exc
    if replicate not in {1, 2, 3}:
        raise RuntimeError(f"Invalid frozen replicate in {sample_id}")
    return parts[0], parts[1], replicate


def load_frozen_samples() -> tuple[Mapping[str, Any], list[dict[str, Any]]]:
    verdict = load_json(VERDICT_SET_PATH)
    if verdict.get("status") != "FROZEN":
        raise RuntimeError("The verdict set is not frozen")
    if verdict.get("visual_evaluation_performed") is not False:
        raise RuntimeError("The verdict set already records visual evaluation")
    samples = verdict.get("samples")
    if not isinstance(samples, list) or len(samples) != 36:
        raise RuntimeError("The frozen verdict set must contain exactly 36 samples")
    manifest = load_manifest()
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in samples:
        sample_id = sample.get("sample_id")
        if not isinstance(sample_id, str) or sample_id in seen:
            raise RuntimeError("Frozen verdict samples contain a missing or duplicate sample_id")
        seen.add(sample_id)
        case_id, group, replicate = parse_sample_id(sample_id)
        replacement = sample.get("replacement_provenance")
        if isinstance(replacement, Mapping) and replacement.get("replacement_output_path"):
            output_rel = str(replacement["replacement_output_path"])
            source_kind = "replacement"
        else:
            manifest_row = manifest.get(sample_id)
            if not isinstance(manifest_row, Mapping):
                raise RuntimeError(f"Manifest row missing for frozen sample {sample_id}")
            output_rel = str(manifest_row["output_path"])
            source_kind = "formal_manifest"
        output_path = ROOT / output_rel
        expected_hash = sample.get("output_sha256")
        if not output_path.is_file():
            raise RuntimeError(f"Frozen verdict image is missing: {output_rel}")
        actual_hash = sha256_file(output_path)
        if actual_hash != expected_hash:
            raise RuntimeError(f"Frozen verdict image hash mismatch: {sample_id}")
        resolved.append(
            {
                "sample_id": sample_id,
                "case_id": case_id,
                "group": group,
                "replicate": replicate,
                "source_kind": source_kind,
                "source_output_path": output_rel,
                "source_output_sha256": actual_hash,
                "validity_classification": sample.get("validity_classification"),
            }
        )
    expected = {f"case-{case:02d}:{group}:r{replicate}" for case in range(1, 5) for group in "ABC" for replicate in range(1, 4)}
    if {row["sample_id"] for row in resolved} != expected:
        raise RuntimeError("Frozen verdict set does not cover the complete 4x3x3 design")
    return verdict, resolved


def protected_paths(source_rows: Iterable[Mapping[str, Any]]) -> list[Path]:
    paths: set[Path] = {VERDICT_SET_PATH, CASES_PATH, EVALUATION_DIR / "inputs-freeze.json"}
    for relative_root in (
        EVALUATION_DIR / "style-context",
        EVALUATION_DIR / "prompts",
        EVALUATION_DIR / "verdict-replacements" / "batch-4b.3v" / "prompts",
        ROOT / "runtime",
    ):
        if relative_root.is_dir():
            paths.update(path for path in relative_root.rglob("*") if path.is_file())
    for relative in (
        "references/core/rendering-hygiene.md",
        "references/core/style-brief.md",
        "references/core/style-reference.md",
    ):
        path = ROOT / relative
        if path.is_file():
            paths.add(path)
    for row in source_rows:
        path = ROOT / str(row["source_output_path"])
        if path.is_file():
            paths.add(path)
    return sorted(paths)


def build_hash_snapshot(source_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    files = []
    for path in protected_paths(source_rows):
        files.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return {
        "schema_version": 1,
        "batch": "4B.4",
        "created_at": utc_now(),
        "verdict_set_sha256": sha256_file(VERDICT_SET_PATH),
        "files": files,
    }


def verify_hash_snapshot(snapshot: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for item in snapshot.get("files", []):
        if not isinstance(item, Mapping):
            errors.append("hash snapshot contains a non-object file entry")
            continue
        relative = item.get("path")
        expected = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            errors.append("hash snapshot contains an invalid file entry")
            continue
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"protected file is missing: {relative}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            errors.append(f"protected file changed: {relative}")
    verdict_hash = snapshot.get("verdict_set_sha256")
    if verdict_hash != sha256_file(VERDICT_SET_PATH):
        errors.append("verdict-set.json changed")
    return errors


def blind_row_headers() -> list[str]:
    return [
        "blind_id",
        "case_id",
        "blind_image_path",
        "evaluator",
        "reviewed_at",
        "identity_fidelity",
        *STYLE_AXES,
        *ARTIFACT_FIELDS,
        *STRUCTURAL_FIELDS,
        "core_style_mean",
        "artifact_burden",
        "structural_burden",
        "identity_score",
        "notes",
    ]


def pairwise_row_headers() -> list[str]:
    return [
        "pair_id",
        "case_id",
        "replicate",
        "criterion",
        "left_blind_id",
        "right_blind_id",
        "left_image_path",
        "right_image_path",
        "evaluator",
        "reviewed_at",
        "choice",
        "confidence",
        "notes",
        "comparison",
        "left_sample_id",
        "right_sample_id",
        "left_group",
        "right_group",
        "winner_group",
        "style_delta_b_minus_a",
        "artifact_delta_c_minus_b",
    ]


def write_csv(path: Path, headers: list[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})
    temporary.replace(path)


def prepare() -> None:
    verdict, samples = load_frozen_samples()
    if BLIND_MAP_PATH.exists() or PAIRING_PATH.exists() or BLIND_DIR.exists() and any(BLIND_DIR.iterdir()):
        raise RuntimeError("Blind artifacts already exist; refusing to reshuffle the frozen set")
    source_snapshot = build_hash_snapshot(samples)
    write_json(HASH_SNAPSHOT_PATH, source_snapshot)
    rng = secrets.SystemRandom()
    blind_map: dict[str, Any] = {
        "schema_version": 1,
        "batch": "4B.4",
        "created_at": utc_now(),
        "verdict_set_path": "evaluation/style-regression/verdict-set.json",
        "verdict_set_sha256": sha256_file(VERDICT_SET_PATH),
        "source_count": len(samples),
        "samples": {},
    }
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        by_case[str(sample["case_id"])].append(sample)
    blind_ids_by_key: dict[tuple[str, str, int], str] = {}
    for case_id in sorted(by_case):
        case_samples = list(by_case[case_id])
        rng.shuffle(case_samples)
        for index, sample in enumerate(case_samples, start=1):
            blind_id = f"{case_id}-x{index:02d}"
            destination = BLIND_DIR / f"{blind_id}.png"
            source = ROOT / str(sample["source_output_path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if sha256_file(destination) != sample["source_output_sha256"]:
                raise RuntimeError(f"Blind copy hash mismatch: {blind_id}")
            blind_ids_by_key[(case_id, str(sample["group"]), int(sample["replicate"]))] = blind_id
            blind_map["samples"][blind_id] = {
                "case_id": sample["case_id"],
                "group": sample["group"],
                "replicate": sample["replicate"],
                "sample_id": sample["sample_id"],
                "source_kind": sample["source_kind"],
                "source_output_path": sample["source_output_path"],
                "source_output_sha256": sample["source_output_sha256"],
                "blind_image_path": destination.relative_to(ROOT).as_posix(),
            }

    pairings = []
    pair_index = 1
    for case_number in range(1, 5):
        case_id = f"case-{case_number:02d}"
        for replicate in range(1, 4):
            for criterion, first_group, second_group in (
                ("style_match", "A", "B"),
                ("hygiene_cleanup", "B", "C"),
            ):
                left = blind_ids_by_key[(case_id, first_group, replicate)]
                right = blind_ids_by_key[(case_id, second_group, replicate)]
                if rng.choice([False, True]):
                    left, right = right, left
                pairings.append(
                    {
                        "pair_id": f"{case_id}-r{replicate}-p{pair_index:02d}",
                        "case_id": case_id,
                        "replicate": replicate,
                        "criterion": criterion,
                        "left_blind_id": left,
                        "right_blind_id": right,
                        "left_image_path": f"evaluation/style-regression/private-assets/blind-review/{left}.png",
                        "right_image_path": f"evaluation/style-regression/private-assets/blind-review/{right}.png",
                    }
                )
                pair_index += 1
    write_json(PAIRING_PATH, {"schema_version": 1, "batch": "4B.4", "created_at": utc_now(), "pairs": pairings})
    write_json(BLIND_MAP_PATH, blind_map)

    blind_rows = []
    for blind_id in sorted(blind_map["samples"]):
        item = blind_map["samples"][blind_id]
        blind_rows.append({"blind_id": blind_id, "case_id": item["case_id"], "blind_image_path": item["blind_image_path"]})
    write_csv(BLIND_CSV_PATH, blind_row_headers(), blind_rows)
    write_csv(PAIRWISE_CSV_PATH, pairwise_row_headers(), pairings)
    print(json.dumps({
        "status": "BLINDED",
        "verdict_set_sha256": sha256_file(VERDICT_SET_PATH),
        "sample_count": len(samples),
        "pair_count": len(pairings),
        "blind_map": str(BLIND_MAP_PATH),
        "blind_directory": str(BLIND_DIR),
        "pass1_csv": str(BLIND_CSV_PATH),
        "pass2_csv": str(PAIRWISE_CSV_PATH),
    }, ensure_ascii=False, indent=2))


def load_json_list(path: Path, key: str) -> list[Mapping[str, Any]]:
    if not path.is_file():
        raise RuntimeError(f"Missing judgement file: {path}")
    value = load_json(path)
    rows = value.get(key) if isinstance(value, Mapping) else None
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise RuntimeError(f"{path} must contain a {key} list")
    return list(rows)


def current_blind_map() -> Mapping[str, Any]:
    if not BLIND_MAP_PATH.is_file():
        raise RuntimeError("Blind map is missing")
    value = load_json(BLIND_MAP_PATH)
    if not isinstance(value, Mapping) or not isinstance(value.get("samples"), Mapping):
        raise RuntimeError("Blind map is malformed")
    return value


def current_pairings() -> list[Mapping[str, Any]]:
    if not PAIRING_PATH.is_file():
        raise RuntimeError("Private pairings are missing")
    value = load_json(PAIRING_PATH)
    pairs = value.get("pairs") if isinstance(value, Mapping) else None
    if not isinstance(pairs, list) or not all(isinstance(row, Mapping) for row in pairs):
        raise RuntimeError("Private pairings are malformed")
    return list(pairs)


def reject_unblind_fields(row: Mapping[str, Any], row_name: str) -> None:
    # Pairing rows carry an anonymous replicate number so the blind protocol can
    # remain within-case/within-replicate.  Replicate is not a condition label;
    # only sample/condition/source fields are premature unblind data.
    forbidden = {"sample_id", "group", "source_output_path", "source_output_sha256", "winner_group"}
    found = sorted(forbidden.intersection(row))
    if found:
        raise RuntimeError(f"{row_name} contains premature unblind fields: {found}")


def validate_pass1(*, export: bool = True) -> list[Mapping[str, Any]]:
    cases, active_axes = load_cases()
    blind_map = current_blind_map()
    expected = blind_map["samples"]
    rows = load_json_list(JUDGEMENTS_PATH, "judgements")
    if len(rows) != 36 or {row.get("blind_id") for row in rows} != set(expected):
        raise RuntimeError("Pass 1 must contain exactly one judgement for each of 36 blind IDs")
    seen: set[str] = set()
    for row in rows:
        blind_id = row.get("blind_id")
        if not isinstance(blind_id, str) or blind_id in seen:
            raise RuntimeError("Pass 1 contains a missing or duplicate blind_id")
        seen.add(blind_id)
        reject_unblind_fields(row, f"Pass 1 row {blind_id}")
        if row.get("case_id") != expected[blind_id].get("case_id"):
            raise RuntimeError(f"Pass 1 case mismatch for {blind_id}")
        if row.get("identity_fidelity") not in IDENTITY_VALUES:
            raise RuntimeError(f"Invalid Identity Fidelity for {blind_id}")
        for axis in STYLE_AXES:
            value = row.get(axis)
            if value not in STYLE_VALUES:
                raise RuntimeError(f"Invalid style score for {blind_id}:{axis}")
            if axis not in active_axes[str(row["case_id"])] and value != "N/A":
                raise RuntimeError(f"Non-relevant style axis must be N/A for {blind_id}:{axis}")
        for field in ARTIFACT_FIELDS:
            if row.get(field) not in ARTIFACT_VALUES:
                raise RuntimeError(f"Invalid rendering-artifact rating for {blind_id}:{field}")
        for field in STRUCTURAL_FIELDS:
            if row.get(field) not in STRUCTURAL_VALUES:
                raise RuntimeError(f"Invalid structural rating for {blind_id}:{field}")
        if not isinstance(row.get("notes", ""), str):
            raise RuntimeError(f"Pass 1 notes must be text for {blind_id}")
    if export:
        write_csv(BLIND_CSV_PATH, blind_row_headers(), rows)
    print(json.dumps({"status": "PASS_1_VALIDATED", "row_count": len(rows), "path": str(BLIND_CSV_PATH)}, indent=2))
    return rows


def validate_pass2(*, export: bool = True) -> list[Mapping[str, Any]]:
    expected_pairs = {str(row["pair_id"]): row for row in current_pairings()}
    rows = load_json_list(PAIRWISE_JUDGEMENTS_PATH, "pairwise_judgements")
    if len(rows) != 24 or {row.get("pair_id") for row in rows} != set(expected_pairs):
        raise RuntimeError("Pass 2 must contain exactly one judgement for each of 24 blind pairs")
    seen: set[str] = set()
    for row in rows:
        pair_id = row.get("pair_id")
        if not isinstance(pair_id, str) or pair_id in seen:
            raise RuntimeError("Pass 2 contains a missing or duplicate pair_id")
        seen.add(pair_id)
        reject_unblind_fields(row, f"Pass 2 row {pair_id}")
        expected = expected_pairs[pair_id]
        for field in ("case_id", "replicate", "criterion", "left_blind_id", "right_blind_id"):
            if row.get(field) != expected.get(field):
                raise RuntimeError(f"Pass 2 pairing mismatch for {pair_id}:{field}")
        if row.get("choice") not in CHOICE_VALUES:
            raise RuntimeError(f"Invalid pairwise choice for {pair_id}")
        if row.get("confidence") not in CONFIDENCE_VALUES:
            raise RuntimeError(f"Invalid pairwise confidence for {pair_id}")
        if not isinstance(row.get("notes", ""), str):
            raise RuntimeError(f"Pass 2 notes must be text for {pair_id}")
    if export:
        write_csv(PAIRWISE_CSV_PATH, pairwise_row_headers(), rows)
    print(json.dumps({"status": "PASS_2_VALIDATED", "row_count": len(rows), "path": str(PAIRWISE_CSV_PATH)}, indent=2))
    return rows


def safe_mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return round(mean(values), 4) if values else None


def style_mean(row: Mapping[str, Any], active_axes: Mapping[str, list[str]]) -> float | None:
    values = [float(row[axis]) for axis in active_axes[str(row["case_id"])] if str(row[axis]) in {"0", "1", "2"}]
    return safe_mean(values)


def enrich_individual_rows(
    rows: list[Mapping[str, Any]],
    blind_map: Mapping[str, Any],
    active_axes: Mapping[str, list[str]],
) -> list[dict[str, Any]]:
    enriched = []
    for row in rows:
        blind_id = str(row["blind_id"])
        source = blind_map["samples"][blind_id]
        item = dict(row)
        item.update(
            {
                "sample_id": source["sample_id"],
                "group": source["group"],
                "replicate": source["replicate"],
                "source_kind": source["source_kind"],
                "source_output_path": source["source_output_path"],
                "source_output_sha256": source["source_output_sha256"],
                "core_style_mean": style_mean(row, active_axes),
                "artifact_burden": sum(ARTIFACT_SCORE[str(row[field])] for field in ARTIFACT_FIELDS),
                "structural_burden": sum(STRUCTURAL_SCORE[str(row[field])] for field in STRUCTURAL_FIELDS),
                "identity_score": IDENTITY_SCORE[str(row["identity_fidelity"])],
            }
        )
        enriched.append(item)
    return enriched


def unblind_pairs(
    pair_rows: list[Mapping[str, Any]],
    blind_map: Mapping[str, Any],
    individual_rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_blind = {str(row["blind_id"]): row for row in individual_rows}
    enriched = []
    for row in pair_rows:
        left_id = str(row["left_blind_id"])
        right_id = str(row["right_blind_id"])
        left = blind_map["samples"][left_id]
        right = blind_map["samples"][right_id]
        if left["case_id"] != right["case_id"] or left["replicate"] != right["replicate"]:
            raise RuntimeError(f"Pair crosses case or replicate: {row['pair_id']}")
        groups = {left["group"], right["group"]}
        if groups == {"A", "B"} and row["criterion"] == "style_match":
            comparison = "A→B"
        elif groups == {"B", "C"} and row["criterion"] == "hygiene_cleanup":
            comparison = "B→C"
        else:
            raise RuntimeError(f"Unexpected blinded pair type: {row['pair_id']}")
        choice = str(row["choice"])
        winner_group = "TIE" if choice == "tie" else (left["group"] if choice == "left" else right["group"])
        item = dict(row)
        item.update(
            {
                "comparison": comparison,
                "left_sample_id": left["sample_id"],
                "right_sample_id": right["sample_id"],
                "left_group": left["group"],
                "right_group": right["group"],
                "winner_group": winner_group,
            }
        )
        if comparison == "A→B":
            a_id = left_id if left["group"] == "A" else right_id
            b_id = left_id if left["group"] == "B" else right_id
            item["style_delta_b_minus_a"] = round(float(by_blind[b_id]["core_style_mean"]) - float(by_blind[a_id]["core_style_mean"]), 4)
            item["artifact_delta_c_minus_b"] = ""
        else:
            b_id = left_id if left["group"] == "B" else right_id
            c_id = left_id if left["group"] == "C" else right_id
            item["style_delta_b_minus_a"] = ""
            item["artifact_delta_c_minus_b"] = int(by_blind[c_id]["artifact_burden"]) - int(by_blind[b_id]["artifact_burden"])
        enriched.append(item)
    return enriched


def condition_rows(individual_rows: Iterable[Mapping[str, Any]], case_id: str, group: str) -> list[Mapping[str, Any]]:
    return [row for row in individual_rows if row["case_id"] == case_id and row["group"] == group]


def condition_metrics(individual_rows: list[Mapping[str, Any]], case_id: str, group: str, active_axes: Mapping[str, list[str]]) -> dict[str, Any]:
    rows = condition_rows(individual_rows, case_id, group)
    return {
        "count": len(rows),
        "core_style_mean": safe_mean(float(row["core_style_mean"]) for row in rows),
        "artifact_burden_mean": safe_mean(float(row["artifact_burden"]) for row in rows),
        "structural_burden_mean": safe_mean(float(row["structural_burden"]) for row in rows),
        "identity_pass": sum(row["identity_fidelity"] == "PASS" for row in rows),
        "identity_minor": sum(row["identity_fidelity"] == "MINOR" for row in rows),
        "identity_fail": sum(row["identity_fidelity"] == "FAIL" for row in rows),
        "identity_fail_rate": round(sum(row["identity_fidelity"] == "FAIL" for row in rows) / len(rows), 4) if rows else None,
        "major_structural_count": sum(
            any(row[field] == "MAJOR" for field in STRUCTURAL_FIELDS) for row in rows
        ),
        "axis_means": {
            axis: safe_mean(float(row[axis]) for row in rows if str(row[axis]) in {"0", "1", "2"})
            for axis in active_axes[case_id]
        },
    }


def pair_metrics(pair_rows: list[Mapping[str, Any]], case_id: str, comparison: str) -> dict[str, Any]:
    rows = [row for row in pair_rows if row["case_id"] == case_id and row["comparison"] == comparison]
    target = "B" if comparison == "A→B" else "C"
    wins = sum(row["winner_group"] == target for row in rows)
    ties = sum(row["winner_group"] == "TIE" for row in rows)
    return {"count": len(rows), "target_wins": wins, "ties": ties, "target_win_rate": round(wins / len(rows), 4) if rows else None}


def verdict_computation(individual_rows: list[Mapping[str, Any]], pair_rows: list[Mapping[str, Any]], active_axes: Mapping[str, list[str]]) -> dict[str, Any]:
    cases = {}
    for case_number in range(1, 5):
        case_id = f"case-{case_number:02d}"
        metrics = {group: condition_metrics(individual_rows, case_id, group, active_axes) for group in "ABC"}
        metrics["A_to_B_pairwise"] = pair_metrics(pair_rows, case_id, "A→B")
        metrics["B_to_C_pairwise"] = pair_metrics(pair_rows, case_id, "B→C")
        metrics["style_delta_b_minus_a"] = round(metrics["B"]["core_style_mean"] - metrics["A"]["core_style_mean"], 4)
        metrics["artifact_delta_c_minus_b"] = round(metrics["C"]["artifact_burden_mean"] - metrics["B"]["artifact_burden_mean"], 4)
        metrics["style_clear"] = bool(
            metrics["A_to_B_pairwise"]["target_wins"] >= 2
            and metrics["style_delta_b_minus_a"] >= 0.25
        )
        metrics["artifact_nonworse"] = metrics["C"]["artifact_burden_mean"] <= metrics["B"]["artifact_burden_mean"]
        metrics["cleanup_clear"] = bool(
            metrics["B_to_C_pairwise"]["target_wins"] >= 2
            and metrics["artifact_delta_c_minus_b"] <= -0.5
        )
        metrics["case04_texture_preserved"] = True
        if case_id == "case-04":
            c_texture = metrics["C"]["axis_means"].get("texture_language")
            b_texture = metrics["B"]["axis_means"].get("texture_language")
            c_material = metrics["C"]["axis_means"].get("material_rendering")
            b_material = metrics["B"]["axis_means"].get("material_rendering")
            metrics["case04_texture_preserved"] = bool(
                c_texture is not None and b_texture is not None and c_texture >= b_texture
                and c_material is not None and b_material is not None and c_material >= b_material - 0.25
            )
        metrics["case02_painterly_preserved"] = True
        if case_id == "case-02":
            metrics["case02_painterly_preserved"] = metrics["C"]["core_style_mean"] >= metrics["B"]["core_style_mean"] - 0.25
        cases[case_id] = metrics

    style_clear_cases = sum(cases[case]["style_clear"] for case in cases)
    nonworse_cases = sum(cases[case]["artifact_nonworse"] for case in cases)
    cleanup_cases = sum(cases[case]["cleanup_clear"] for case in cases)
    style_preservation = all(cases[case]["case02_painterly_preserved"] and cases[case]["case04_texture_preserved"] for case in ("case-02", "case-04"))

    identity = {}
    for group in "BC":
        aggregate = {
            "fail_count": sum(cases[case][group]["identity_fail"] for case in cases),
            "fail_rate": sum(cases[case][group]["identity_fail"] for case in cases) / 12,
            "regression_cases": sum(cases[case][group]["identity_fail"] > cases[case]["A"]["identity_fail"] for case in cases),
        }
        identity[group] = aggregate
    identity_safe = all(
        identity[group]["fail_rate"] <= sum(cases[case]["A"]["identity_fail"] for case in cases) / 12
        and identity[group]["regression_cases"] <= 1
        for group in "BC"
    )

    return {
        "cases": cases,
        "style_clear_cases": style_clear_cases,
        "artifact_nonworse_cases": nonworse_cases,
        "cleanup_clear_cases": cleanup_cases,
        "style_preservation": style_preservation,
        "identity": identity,
        "identity_safe": identity_safe,
        "style_verdict": "PASS" if style_clear_cases >= 3 and style_preservation else "FAIL",
        "hygiene_verdict": "PASS" if nonworse_cases >= 3 and cleanup_cases >= 2 and cases["case-04"]["case04_texture_preserved"] else "FAIL",
        "identity_verdict": "PASS" if identity_safe else "FAIL",
    }


def fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    return str(value)


def build_results_report(
    verdict: Mapping[str, Any],
    individual_rows: list[Mapping[str, Any]],
    pair_rows: list[Mapping[str, Any]],
    metrics: Mapping[str, Any],
    hash_errors: list[str],
) -> str:
    lines = [
        "# Style Transfer V1.0 — Batch 4B.4 Results",
        "",
        "Status: COMPLETE — blinded visual evaluation, pairwise comparison, and unblinding finished.",
        "",
        "## Frozen input and protocol",
        "",
        f"- Verdict set: `evaluation/style-regression/verdict-set.json`",
        f"- Verdict-set SHA-256: `{sha256_file(VERDICT_SET_PATH)}`",
        f"- Frozen samples: `{len(individual_rows)}/36`; pairwise rows: `{len(pair_rows)}/24`.",
        "- Source resolution used the frozen replacement provenance before falling back to the formal manifest.",
        "- Evaluator: single-rater Codex visual judge; no multi-rater reliability estimate.",
        "- Pass 1: individual blinded evaluation. Pass 2: blinded pairwise evaluation within case/replicate.",
        "- A/B/C mappings were read only after both pass records validated.",
        "",
        "## Per-case results",
        "",
        "| Case | A core style | B core style | C core style | B−A | B artifact | C artifact | C−B artifact | A→B wins | B→C wins | A→B clear | C artifact <= B | B→C clear |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for case_id in ("case-01", "case-02", "case-03", "case-04"):
        case = metrics["cases"][case_id]
        lines.append(
            "| {case} | {a} | {b} | {c} | {delta} | {ba} | {ca} | {ad} | {abw}/3 | {bcw}/3 | {style} | {nonworse} | {cleanup} |".format(
                case=case_id,
                a=fmt(case["A"]["core_style_mean"]),
                b=fmt(case["B"]["core_style_mean"]),
                c=fmt(case["C"]["core_style_mean"]),
                delta=fmt(case["style_delta_b_minus_a"]),
                ba=fmt(case["B"]["artifact_burden_mean"]),
                ca=fmt(case["C"]["artifact_burden_mean"]),
                ad=fmt(case["artifact_delta_c_minus_b"]),
                abw=case["A_to_B_pairwise"]["target_wins"],
                bcw=case["B_to_C_pairwise"]["target_wins"],
                style=fmt(case["style_clear"]),
                nonworse=fmt(case["artifact_nonworse"]),
                cleanup=fmt(case["cleanup_clear"]),
            )
        )
    lines.extend(
        [
            "",
            "## Identity and structural summary",
            "",
            "| Case | Condition | Identity PASS/MINOR/FAIL | Identity FAIL rate | Structural burden mean | Major structural samples |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    for case_id in ("case-01", "case-02", "case-03", "case-04"):
        for group in "ABC":
            data = metrics["cases"][case_id][group]
            lines.append(
                f"| {case_id} | {group} | {data['identity_pass']}/{data['identity_minor']}/{data['identity_fail']} | {data['identity_fail_rate']} | {data['structural_burden_mean']} | {data['major_structural_count']} |"
            )
    lines.extend(
        [
            "",
            "## Pairwise outcomes",
            "",
            "| Pair | Case | Replicate | Criterion | Left | Right | Choice | Winner | Confidence | Style delta B−A | Artifact delta C−B |",
            "|---|---|---:|---|---|---|---|---|---|---:|---:|",
        ]
    )
    for row in pair_rows:
        lines.append(
            "| {pair} | {case} | {replicate} | {criterion} | {left} ({left_group}) | {right} ({right_group}) | {choice} | {winner} | {confidence} | {style_delta} | {artifact_delta} |".format(
                pair=row["pair_id"],
                case=row["case_id"],
                replicate=row["replicate"],
                criterion=row["criterion"],
                left=row["left_sample_id"],
                left_group=row["left_group"],
                right=row["right_sample_id"],
                right_group=row["right_group"],
                choice=row["choice"],
                winner=row["winner_group"],
                confidence=row["confidence"],
                style_delta=row.get("style_delta_b_minus_a", ""),
                artifact_delta=row.get("artifact_delta_c_minus_b", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Acceptance gates",
            "",
            f"- Style Fidelity: `{metrics['style_verdict']}` — clear A→B cases `{metrics['style_clear_cases']}/4`; preservation guard `{fmt(metrics['style_preservation'])}`.",
            f"- Rendering Hygiene: `{metrics['hygiene_verdict']}` — C artifact burden <= B in `{metrics['artifact_nonworse_cases']}/4`; clear C-over-B cleanup `{metrics['cleanup_clear_cases']}/4`; Case 04 preservation `{fmt(metrics['cases']['case-04']['case04_texture_preserved'])}`.",
            f"- Identity Safety: `{metrics['identity_verdict']}` — B aggregate FAIL rate `{metrics['identity']['B']['fail_rate']}`, C aggregate FAIL rate `{metrics['identity']['C']['fail_rate']}`; per-case regression counts B `{metrics['identity']['B']['regression_cases']}`, C `{metrics['identity']['C']['regression_cases']}`.",
            "- Structural artifacts are reported independently; any systematic major increase is included in the final verdict discussion.",
            "",
            "## Evaluator limitations",
            "",
            "- This is a single-rater Codex visual judgment; no independent human raters, inter-rater agreement, or statistical confidence interval is available.",
            "- Scores are ordinal visual judgments against the frozen style references; small differences near the 0.25/0.5 gates should be treated as decision-boundary evidence, not population estimates.",
            "- Pairwise choices use randomized left/right presentation and allow ties, but they are not a substitute for a multi-rater perceptual study.",
            "",
            "## Integrity checks",
            "",
            f"- Protected-input hash recheck: `{('PASS' if not hash_errors else 'FAIL')}`.",
            *(f"- {error}" for error in hash_errors),
            "- Verdict images were copied byte-for-byte into the private blind-review directory; no source verdict image was overwritten.",
            "- Phase 2 was not started.",
            "",
        ]
    )
    return "\n".join(lines)


def build_final_verdict_report(metrics: Mapping[str, Any], hash_errors: list[str]) -> str:
    overall = "PASS" if all(metrics[key] == "PASS" for key in ("style_verdict", "hygiene_verdict", "identity_verdict")) else "FAIL"
    failing = [
        label for label, key in (
            ("Style Fidelity", "style_verdict"),
            ("Rendering Hygiene", "hygiene_verdict"),
            ("Identity Safety", "identity_verdict"),
        ) if metrics[key] != "PASS"
    ]
    lines = [
        "# Style Transfer V1.0 Verdict",
        "",
        f"Overall Style Transfer V1.0 Verdict: **{overall}**",
        "",
        "Evaluation used the frozen 36-sample verdict set and completed both blinded passes before unblinding. This is a single-rater Codex visual judgment, not a multi-rater human study.",
        "",
        "## Style Fidelity Verdict",
        "",
        f"**{metrics['style_verdict']}** — clear A→B improvement was observed in `{metrics['style_clear_cases']}/4` cases; the required threshold is 3/4. Painterly and watercolor/grain preservation guards: `{fmt(metrics['style_preservation'])}`.",
        "",
        "## Rendering Hygiene Verdict",
        "",
        f"**{metrics['hygiene_verdict']}** — C artifact burden was no greater than B in `{metrics['artifact_nonworse_cases']}/4` cases, with clear cleanup in `{metrics['cleanup_clear_cases']}/4`; Case 04 texture preservation: `{fmt(metrics['cases']['case-04']['case04_texture_preserved'])}`.",
        "",
        "## Identity Safety Verdict",
        "",
        f"**{metrics['identity_verdict']}** — B aggregate identity FAIL rate: `{metrics['identity']['B']['fail_rate']}`; C aggregate identity FAIL rate: `{metrics['identity']['C']['fail_rate']}`. B per-case regression count: `{metrics['identity']['B']['regression_cases']}`; C: `{metrics['identity']['C']['regression_cases']}`.",
        "",
        "Structural artifacts were scored separately across hands, anatomy, object geometry, perspective, and structural consistency. Any major structural pattern is documented in the results report.",
        "",
        "## Overall Style Transfer V1.0 Verdict",
        "",
        f"**{overall}** — all three acceptance layers must pass for an overall PASS. Failing layers: `{', '.join(failing) if failing else 'none'}`.",
        "",
        "## Boundary",
        "",
        "- The frozen verdict set, verdict images, prompts, Style Briefs, Style Contexts, Runtime, Hygiene policy, and experiment inputs remain unchanged.",
        "- Phase 2 was not started automatically.",
        f"- Protected-input hash recheck: **{('PASS' if not hash_errors else 'FAIL')}**.",
        "",
    ]
    return "\n".join(lines)


def unblind() -> None:
    # These validations intentionally happen before loading the private A/B/C map.
    pass1 = validate_pass1(export=False)
    pass2 = validate_pass2(export=False)
    blind_map = current_blind_map()
    verdict, samples = load_frozen_samples()
    _, active_axes = load_cases()
    enriched_individual = enrich_individual_rows(pass1, blind_map, active_axes)
    enriched_pairs = unblind_pairs(pass2, blind_map, enriched_individual)
    metrics = verdict_computation(enriched_individual, enriched_pairs, active_axes)
    snapshot = load_json(HASH_SNAPSHOT_PATH)
    hash_errors = verify_hash_snapshot(snapshot)
    snapshot = dict(snapshot)
    snapshot["after_unblind_at"] = utc_now()
    snapshot["after_unblind_errors"] = hash_errors
    write_json(HASH_SNAPSHOT_PATH, snapshot)

    final_individual_headers = [
        "blind_id", "case_id", "sample_id", "group", "replicate", "source_kind", "blind_image_path",
        "source_output_path", "source_output_sha256", "evaluator", "reviewed_at", "identity_fidelity",
        *STYLE_AXES, *ARTIFACT_FIELDS, *STRUCTURAL_FIELDS, "core_style_mean", "artifact_burden",
        "structural_burden", "identity_score", "notes",
    ]
    write_csv(BLIND_CSV_PATH, final_individual_headers, enriched_individual)
    write_csv(PAIRWISE_CSV_PATH, pairwise_row_headers(), enriched_pairs)
    results = build_results_report(verdict, enriched_individual, enriched_pairs, metrics, hash_errors)
    RESULTS_PATH.write_text(results, encoding="utf-8", newline="\n")
    VERDICT_PATH.write_text(build_final_verdict_report(metrics, hash_errors), encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": "UNBLINDED_COMPLETE",
        "verdict_set_sha256": sha256_file(VERDICT_SET_PATH),
        "sample_count": len(enriched_individual),
        "pair_count": len(enriched_pairs),
        "style_fidelity_verdict": metrics["style_verdict"],
        "rendering_hygiene_verdict": metrics["hygiene_verdict"],
        "identity_safety_verdict": metrics["identity_verdict"],
        "overall_verdict": "PASS" if all(metrics[key] == "PASS" for key in ("style_verdict", "hygiene_verdict", "identity_verdict")) else "FAIL",
        "hash_errors": hash_errors,
        "results_report": str(RESULTS_PATH),
        "final_verdict_report": str(VERDICT_PATH),
    }, ensure_ascii=False, indent=2))


def status() -> None:
    result = {
        "verdict_set_sha256": sha256_file(VERDICT_SET_PATH),
        "blind_map_exists": BLIND_MAP_PATH.exists(),
        "pairing_exists": PAIRING_PATH.exists(),
        "pass1_judgements_exists": JUDGEMENTS_PATH.exists(),
        "pass2_judgements_exists": PAIRWISE_JUDGEMENTS_PATH.exists(),
        "blind_csv_exists": BLIND_CSV_PATH.exists(),
        "pairwise_csv_exists": PAIRWISE_CSV_PATH.exists(),
        "results_report_exists": RESULTS_PATH.exists(),
        "verdict_report_exists": VERDICT_PATH.exists(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--validate-pass1", action="store_true")
    modes.add_argument("--validate-pass2", action="store_true")
    modes.add_argument("--unblind", action="store_true")
    modes.add_argument("--status", action="store_true")
    args = parser.parse_args()
    try:
        if args.prepare:
            prepare()
        elif args.validate_pass1:
            validate_pass1()
        elif args.validate_pass2:
            validate_pass2()
        elif args.unblind:
            unblind()
        else:
            status()
        return 0
    except (OSError, RuntimeError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
