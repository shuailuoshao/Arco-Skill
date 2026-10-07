"""Focused tests for Phase 0B-R request-recovery evidence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.revision_baseline import validate_recovery_manifest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "archive/实验/evaluation" / "revision-regression" / "input-bundle" / "manifest.json"
RECOVERY_PATH = ROOT / "archive/实验/evaluation" / "revision-regression" / "input-bundle" / "recovery" / "manifest.json"


class RevisionRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        self.recovery = json.loads(RECOVERY_PATH.read_text(encoding="utf-8"))

    def reasons_for(self, document: dict[str, Any]) -> set[str]:
        with tempfile.TemporaryDirectory(dir=str(ROOT / "archive/实验/evaluation" / "revision-regression")) as temp_dir:
            path = Path(temp_dir) / "recovery.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            return {item["code"] for item in validate_recovery_manifest(path, evidence_manifest=self.evidence)}

    def test_canonical_recovery_manifest_is_valid(self) -> None:
        self.assertEqual(validate_recovery_manifest(RECOVERY_PATH, evidence_manifest=self.evidence), [])
        self.assertEqual({item["classification"] for item in self.recovery["targets"]}, {"UNRECOVERABLE"})

    def test_forbidden_best_guess_is_rejected(self) -> None:
        changed = json.loads(json.dumps(self.recovery))
        changed["targets"][0]["classification"] = "BEST_GUESS"
        self.assertIn("RECOVERY_CLASSIFICATION_INVALID", self.reasons_for(changed))

    def test_duplicate_and_missing_targets_are_rejected(self) -> None:
        changed = json.loads(json.dumps(self.recovery))
        changed["targets"][-1] = json.loads(json.dumps(changed["targets"][0]))
        codes = self.reasons_for(changed)
        self.assertIn("RECOVERY_TARGET_INVALID", codes)
        self.assertIn("RECOVERY_TARGETS_MISSING", codes)

    def test_prompt_output_session_and_call_linkage_are_checked(self) -> None:
        for field in ("provider_prompt_sha256", "historical_output_sha256", "source_session_sha256"):
            changed = json.loads(json.dumps(self.recovery))
            changed["targets"][0][field] = "0" * 64
            self.assertIn("RECOVERY_LINKAGE_MISMATCH", self.reasons_for(changed))
        changed = json.loads(json.dumps(self.recovery))
        changed["targets"][0]["source_call_id"] = "call_wrong"
        self.assertIn("RECOVERY_LINKAGE_MISMATCH", self.reasons_for(changed))

    def test_unrecoverable_target_cannot_materialize_a_guessed_request(self) -> None:
        changed = json.loads(json.dumps(self.recovery))
        changed["targets"][0]["request_evidence_path"] = "guessed.json"
        changed["targets"][0]["result_sha256"] = "0" * 64
        self.assertIn("RECOVERY_GUESSED_REQUEST_FORBIDDEN", self.reasons_for(changed))

    def test_original_and_rederived_provenance_contracts_are_enforced(self) -> None:
        original = json.loads(json.dumps(self.recovery))
        original["targets"][0]["classification"] = "ORIGINAL_EVIDENCE_FOUND"
        self.assertIn("RECOVERY_PROVENANCE_MISSING", self.reasons_for(original))

        rederived = json.loads(json.dumps(self.recovery))
        rederived["targets"][0]["classification"] = "DETERMINISTICALLY_REDERIVED"
        self.assertIn("RECOVERY_PROVENANCE_MISSING", self.reasons_for(rederived))

    def test_rederived_runs_must_be_identical(self) -> None:
        changed = json.loads(json.dumps(self.recovery))
        target = changed["targets"][0]
        target.update(
            {
                "classification": "DETERMINISTICALLY_REDERIVED",
                "derived_from_commit": changed["approved_baseline_commit"],
                "mapping_entrypoint": "scripts.arco_production:run_production_generation",
                "input_manifest": "frozen.json",
                "input_hashes": ["a" * 64],
                "derivation_command": "python helper.py",
                "result_path": "result.json",
                "result_sha256": "a" * 64,
                "run_1_sha256": "a" * 64,
                "run_2_sha256": "b" * 64,
            }
        )
        self.assertIn("RECOVERY_NONDETERMINISTIC", self.reasons_for(changed))


if __name__ == "__main__":
    unittest.main()
