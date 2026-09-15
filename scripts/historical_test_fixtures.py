"""Isolated historical/active fixtures for calibration regression tests.

These helpers deliberately never reinterpret a completed staging directory as
the current active transaction.  They copy the recorded candidate and rollback
snapshots into a temporary root so validators keep their production-strength
revision and hash checks.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IDENTITY_STAGING = PROJECT_ROOT / "calibration/staging/cal-20260911T031117Z-849ec7"
CASUAL_STAGING = PROJECT_ROOT / "calibration/staging/cal-20260914T070842Z-68b810"


def _copy_project(holder: tempfile.TemporaryDirectory[str]) -> Path:
    root = Path(holder.name) / "arco"
    shutil.copytree(
        PROJECT_ROOT,
        root,
        ignore=shutil.ignore_patterns(".venv", "__pycache__", "calibration"),
    )
    return root


def make_historical_identity_fixture() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Return the formal root recorded immediately after Identity publication."""
    holder = tempfile.TemporaryDirectory()
    root = _copy_project(holder)
    candidate = IDENTITY_STAGING / "candidate-root"

    # Published targets and their managed image payload come from the old
    # Identity transaction, not today's later Casual/Body revisions.
    for rel in (
        "character/identity.yaml",
        "character/assets.yaml",
        "character/expressions.yaml",
        "character/identity.md",
    ):
        source = candidate / rel
        if source.is_file():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    variants = candidate / "variants.index.yaml"
    shutil.copy2(variants, root / "variants/index.yaml")
    candidate_assets = candidate / "assets"
    if candidate_assets.is_dir():
        shutil.copytree(candidate_assets, root / "assets", dirs_exist_ok=True)

    # Preserve the immutable files referenced by the historical manifest.  The
    # current copies are valid for these paths, while the protected entities
    # above are pinned to the transaction's recorded revisions.
    history = root / "calibration/history"
    history.mkdir(parents=True, exist_ok=True)
    for name in (
        "cal-20260910T145805Z-61c3e9.yaml",
        "cal-20260910T145805Z-61c3e9.complete",
    ):
        source = PROJECT_ROOT / "calibration/history" / name
        if source.is_file():
            shutil.copy2(source, history / name)
    return holder, root


def make_active_casual_fixture() -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
    """Return (holder, formal pre-publication root, active staging copy)."""
    holder = tempfile.TemporaryDirectory()
    root = _copy_project(holder)
    staging = Path(holder.name) / CASUAL_STAGING.name
    shutil.copytree(CASUAL_STAGING, staging)

    # Restore the exact pre-Casual formal targets from the publication
    # rollback snapshots.  This is a temporary test root; the real completed
    # staging and formal published data remain untouched.
    rollback = CASUAL_STAGING / "publication/rollback"
    shutil.copy2(rollback / "character/assets.yaml", root / "character/assets.yaml")
    shutil.copy2(rollback / "variants/index.yaml", root / "variants/index.yaml")
    # Body-proportion publication may have advanced today's formal Identity to
    # revision 2.  The Casual staging transaction was created against Identity
    # revision 1, so pin this isolated fixture to the historical Identity
    # candidate and its matching markdown source revision.
    identity_candidate = IDENTITY_STAGING / "candidate-root"
    shutil.copy2(identity_candidate / "character/identity.yaml", root / "character/identity.yaml")
    shutil.copy2(identity_candidate / "character/identity.md", root / "character/identity.md")
    history = root / "calibration/history"
    history.mkdir(parents=True, exist_ok=True)
    for name in (
        "cal-20260910T145805Z-61c3e9.yaml",
        "cal-20260910T145805Z-61c3e9.complete",
        "cal-20260911T031117Z-849ec7.yaml",
        "cal-20260911T031117Z-849ec7.complete",
    ):
        source = PROJECT_ROOT / "calibration/history" / name
        if source.is_file():
            shutil.copy2(source, history / name)

    # The source directory is a completed publication record.  Turn only the
    # temporary copy into an active, pending candidate for staging tests.
    manifest_path = staging / "publish-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    manifest["publication_state"] = "STAGED_VALIDATED_AWAITING_AUTHORIZATION"
    manifest["publication_authorized"] = False
    manifest["publication_status"] = "pending"
    for item in manifest.get("files", []):
        item["after_hash"] = None
        item["publication_status"] = "pending"
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    lock = {
        "schema_version": 1,
        "calibration_id": staging.name,
        "state": "STAGED_VALIDATED_AWAITING_AUTHORIZATION",
        "targets": ["variants.index", "variants.casual-outfit", "character.assets"],
    }
    lock_path = staging / "calibration-lock.yaml"
    lock_path.write_text(
        yaml.safe_dump(lock, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return holder, root, staging
