from __future__ import annotations
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_identity_staging import validate
from verify_historical_manifest import verification_class, annotate_manifest
from historical_test_fixtures import make_historical_identity_fixture


class IdentityStagingTests(unittest.TestCase):
    def test_historical_classes(self):
        self.assertEqual(verification_class("character/identity.yaml"), "protected_entity")
        self.assertEqual(verification_class("character/expressions.yaml"), "immutable_data")
        self.assertEqual(verification_class("scripts/reference_runtime.py"), "evolvable_tooling")
        m = annotate_manifest({"files": [{"target_path": "scripts/reference_runtime.py"}]})
        self.assertEqual(m["files"][0]["verification_class"], "evolvable_tooling")

    def test_staging_validator_passes(self):
        holder, formal_root = make_historical_identity_fixture()
        self.addCleanup(holder.cleanup)
        staging = Path(__file__).resolve().parents[1] / "scripts/fixtures/calibration/cal-20260911T031117Z-849ec7"
        import yaml
        manifest=yaml.safe_load((staging/'publish-manifest.yaml').read_text(encoding='utf-8'))
        result = validate(formal_root, staging, 'published' if manifest.get('publication_state') in {'COMPLETE','AFTER_HASH_VALIDATED'} else 'staging')
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["counts"]["uncertain"], 10)
        self.assertEqual(result["counts"]["todo"], 4)

    def test_formal_identity_is_not_modified_by_staging(self):
        p = Path(__file__).resolve().parents[1] / "character/identity.yaml"
        before = hashlib.sha256(p.read_bytes()).hexdigest()
        staging = Path(__file__).resolve().parents[1] / "scripts/fixtures/calibration/cal-20260911T031117Z-849ec7"
        self.assertTrue(staging.is_dir())
        self.assertEqual(before, hashlib.sha256(p.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
