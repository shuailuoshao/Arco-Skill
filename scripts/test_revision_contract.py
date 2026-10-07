"""Phase 0C provenance and canonical fixture contract tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from scripts.revision_baseline import sha256_file, validate_evidence_manifest, validate_fixture


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "archive/实验/evaluation" / "revision-regression"
FIXTURE = BASE / "cases.yaml"
EVIDENCE = BASE / "input-bundle" / "manifest.json"
RECOVERY = BASE / "input-bundle" / "recovery" / "manifest.json"


class RevisionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def evidence_codes(self, document: dict[str, Any]) -> set[str]:
        with tempfile.TemporaryDirectory(dir=str(BASE)) as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            return {item["code"] for item in validate_evidence_manifest(path, root=ROOT)}

    def fixture_codes(self, document: dict[str, Any]) -> set[str]:
        with tempfile.TemporaryDirectory(dir=str(BASE)) as temp_dir:
            path = Path(temp_dir) / "cases.yaml"
            path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")
            return {item["code"] for item in validate_fixture(path, root=ROOT)["reasons"]}

    def test_complete_phase0c_fixture_is_ready(self) -> None:
        result = validate_fixture(FIXTURE, root=ROOT)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["reasons"], [])

    def test_prospective_fixture_cannot_impersonate_historical(self) -> None:
        changed = json.loads(json.dumps(self.evidence))
        changed["cases"][0]["fixture_provenance"]["class"] = "HISTORICAL_EXACT_FIXTURE"
        changed["cases"][0]["fixture_provenance"]["historical_equivalence_claimed"] = True
        self.assertIn("FIXTURE_PROVENANCE_INVALID", self.evidence_codes(changed))

    def test_recovery_evidence_remains_linked_exactly(self) -> None:
        changed = json.loads(json.dumps(self.evidence))
        changed["cases"][0]["fixture_provenance"]["recovery_targets"].pop()
        self.assertIn("RECOVERY_LINK_MISMATCH", self.evidence_codes(changed))
        recovery = json.loads(RECOVERY.read_text(encoding="utf-8"))
        self.assertEqual(len(recovery["targets"]), 5)
        self.assertTrue(all(item["classification"] == "UNRECOVERABLE" for item in recovery["targets"]))

    def test_tampered_or_missing_canonical_request_is_detected(self) -> None:
        changed = json.loads(json.dumps(self.evidence))
        changed["cases"][0]["canonical_fixture"]["requests"][0]["sha256"] = "0" * 64
        self.assertIn("REQUEST_HASH_MISMATCH", self.evidence_codes(changed))
        changed = json.loads(json.dumps(self.evidence))
        changed["cases"][0]["canonical_fixture"]["requests"][0]["path"] = "archive/实验/evaluation/revision-regression/missing.json"
        self.assertIn("FILE_NOT_FOUND", self.evidence_codes(changed))

    def test_case03_semantic_fixture_is_immutable(self) -> None:
        case = next(item for item in self.evidence["cases"] if item["case_id"] == "case-03")
        self.assertEqual(case["steps"][0]["prompt"]["sha256"], "7070abb1cf3882489370fcc8a5cc71be7859798ba0a3310201fd1e2cb971e54e")
        self.assertEqual(case["production_request_evidence"]["canonical_sha256"], "522b26dd0a31ae2688a0faaef45c32159636dd1e00a3a077b98041b1dde07ace")
        changed = json.loads(json.dumps(self.evidence))
        next(item for item in changed["cases"] if item["case_id"] == "case-03")["steps"][0]["prompt"]["sha256"] = "0" * 64
        self.assertIn("CASE03_IMMUTABILITY_VIOLATION", self.evidence_codes(changed))

    def test_revision_requests_use_only_legacy_prior_output_transport(self) -> None:
        requests = [
            ("case-01-revision-1.json", "case-01-revision-1.txt"),
            ("case-01-revision-2.json", "case-01-revision-2.txt"),
            ("case-02-background-revision.json", "case-02-background-revision.txt"),
            ("case-02-character-detail-revision.json", "case-02-character-detail-revision.txt"),
        ]
        for request_name, prompt_name in requests:
            request = json.loads((BASE / "input-bundle" / "requests" / request_name).read_text(encoding="utf-8"))
            prompt = (BASE / "input-bundle" / "prompts" / prompt_name).read_text(encoding="utf-8")
            self.assertEqual(request["base_prompt"], prompt)
            self.assertNotIn("variant_id", request)
            self.assertEqual(request["arco_references"], [])
            self.assertEqual(request["external_references"], [])
            self.assertEqual(len(request["request_scoped_arco_references"]), 1)
            self.assertEqual(request["request_scoped_arco_references"][0]["source_scope"], "request_scoped_arco")
            self.assertNotIn("asset_id", request["request_scoped_arco_references"][0])

    def test_fixture_hashes_and_step_order_are_frozen(self) -> None:
        fixture = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        expected = {
            "case-01": ["first-generation", "revision-1", "revision-2"],
            "case-02": ["first-generation", "background-revision", "character-detail-revision"],
            "case-03": ["baseline-generation"],
        }
        for case in fixture["cases"]:
            self.assertEqual([step["step_id"] for step in case["steps"]], expected[case["case_id"]])
            for step in case["steps"]:
                self.assertEqual(sha256_file(ROOT / step["request_path"]), step["request_sha256"])

    def test_wrong_previous_output_binding_fails_closed(self) -> None:
        fixture = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        fixture["cases"][0]["steps"][1]["previous_output_from"] = "not-an-earlier-step"
        self.assertIn("PRIOR_OUTPUT_ORDER_INVALID", self.fixture_codes(fixture))


if __name__ == "__main__":
    unittest.main()
