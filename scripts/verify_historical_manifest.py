"""Forward-compatible verification rules for published calibration manifests."""
from __future__ import annotations

from pathlib import PurePosixPath
import hashlib
from pathlib import Path
from typing import Any

import yaml

IMMUTABLE = {
    "character/expressions.yaml",
    "calibration/history/",
    "assets/arco/",
}
PROTECTED = {
    "character/identity.yaml",
    "character/assets.yaml",
    "variants/index.yaml",
}


def verification_class(target_path: str) -> str:
    p = PurePosixPath(target_path.replace("\\", "/"))
    value = str(p)
    if value in PROTECTED:
        return "protected_entity"
    if any(value == x or value.startswith(x) for x in IMMUTABLE):
        return "immutable_data"
    return "evolvable_tooling"


def annotate_manifest(data: dict) -> dict:
    """Return a copy annotated without rewriting historical values."""
    result = dict(data)
    result["verification_schema"] = "v3"
    result["verification_policy"] = {
        "immutable_data": "after_hash_exact",
        "protected_entity": "revision_lineage_and_history",
        "evolvable_tooling": "transaction_completion_only",
    }
    result["files"] = [
        {**item, "verification_class": verification_class(item.get("target_path", ""))}
        for item in data.get("files", [])
    ]
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_completed_manifest(manifest: dict[str, Any], formal_root: Path) -> dict[str, Any]:
    """Verify a historical transaction without freezing later tooling revisions.

    Immutable data must still equal the published after hash. Protected entities
    may advance through later calibrations, so this verifier requires only that
    their current revision is not older than the revision published by this
    transaction. Evolvable tooling is checked against the transaction's stored
    candidate/after hashes, never against today's checkout.
    """
    errors: list[str] = []
    if manifest.get("publication_state") != "COMPLETE":
        errors.append("historical transaction is not COMPLETE")
    for item in annotate_manifest(manifest).get("files", []):
        target = str(item.get("target_path", ""))
        kind = item["verification_class"]
        candidate_hash = item.get("candidate_hash")
        after_hash = item.get("after_hash")
        if not candidate_hash or candidate_hash != after_hash or item.get("publication_status") != "replaced":
            errors.append(f"transaction completion mismatch: {target}")
            continue
        current = formal_root / target
        if kind == "immutable_data":
            if not current.is_file() or _sha256(current) != after_hash:
                errors.append(f"immutable data drift: {target}")
        elif kind == "protected_entity":
            if not current.is_file():
                errors.append(f"protected entity missing: {target}")
                continue
            try:
                current_data = yaml.safe_load(current.read_text(encoding="utf-8")) or {}
            except (OSError, UnicodeError, yaml.YAMLError):
                errors.append(f"protected entity unreadable: {target}")
                continue
            published_path = formal_root / "calibration" / "staging" / str(manifest.get("calibration_id")) / str(item.get("staged_path", ""))
            if published_path.is_file():
                published_data = yaml.safe_load(published_path.read_text(encoding="utf-8")) or {}
                if int(current_data.get("revision", -1)) < int(published_data.get("revision", -1)):
                    errors.append(f"protected entity revision regressed: {target}")
                elif current_data.get('revision') == published_data.get('revision'):
                    if _sha256(current) != after_hash:
                        errors.append(f'protected entity same-revision drift: {target}')
                else:
                    from validate_library import validate
                    result = validate(formal_root)
                    if result['structure'] != 'PASS':
                        errors.append(f'protected entity lineage invalid: {target}')
    return {"status": "PASS" if not errors else "FAIL", "errors": errors}
