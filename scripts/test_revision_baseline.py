"""Tests for the isolated Phase 0 revision baseline observer."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from scripts.revision_baseline import (
    APPROVED_BASELINE_COMMIT,
    RevisionBaselineError,
    canonical_json,
    capture_fixture,
    materialize_request,
    replay_check,
    sha256_file,
    sha256_text,
    validate_evidence_manifest,
    validate_fixture,
    _AcceptedCodexProvider,
    _CodexTaskEmitter,
    _load_codex_task,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "archive/实验/evaluation" / "revision-regression" / "cases.yaml"


class RevisionBaselineTests(unittest.TestCase):
    def test_codex_task_is_write_once_and_binds_exact_payload(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as temp_dir:
            base = Path(temp_dir)
            request = base / "request.json"
            reference = base / "reference.png"
            request.write_text('{"base_prompt":"x"}', encoding="utf-8")
            reference.write_bytes(b"reference")
            task_path = base / "baseline" / "tasks" / "case-01" / "first-generation-attempt-1.json"
            emitter = _CodexTaskEmitter(
                task_path=task_path,
                case_id="case-01",
                step_id="first-generation",
                attempt=1,
                request_path=request,
            )
            with self.assertRaises(Exception):
                emitter(prompt="exact prompt", referenced_image_paths=[str(reference)])
            task = _load_codex_task(task_path, root=base, capture_dir=base / "baseline")
            self.assertEqual(task["prompt"], "exact prompt")
            self.assertEqual(task["references"][0]["sha256"], sha256_file(reference))
            with self.assertRaises(RevisionBaselineError):
                emitter(prompt="changed prompt", referenced_image_paths=[str(reference)])

    def test_codex_accept_provider_rejects_prompt_reference_and_non_png_drift(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as temp_dir:
            base = Path(temp_dir)
            reference = base / "reference.png"
            output = base / "output.png"
            other = base / "other.png"
            reference.write_bytes(b"reference")
            other.write_bytes(b"other")
            output.write_bytes(b"not-png")
            task = {
                "prompt": "exact",
                "prompt_sha256": sha256_text("exact"),
                "referenced_image_paths": [str(reference.resolve())],
            }
            provider = _AcceptedCodexProvider(task, output)
            with self.assertRaisesRegex(RevisionBaselineError, "prompt"):
                provider(prompt="changed", referenced_image_paths=[str(reference)])
            with self.assertRaisesRegex(RevisionBaselineError, "reference order"):
                provider(prompt="exact", referenced_image_paths=[str(other)])
            with self.assertRaisesRegex(RevisionBaselineError, "PNG"):
                provider(prompt="exact", referenced_image_paths=[str(reference)])
    def test_phase0c_bundle_is_ready_without_historical_mapping_blockers(self) -> None:
        result = validate_fixture(FIXTURE, root=ROOT)
        self.assertEqual(result["status"], "READY")
        codes = {item["code"] for item in result["reasons"]}
        self.assertNotIn("INPUT_BUNDLE_PARTIAL", codes)
        self.assertNotIn("PRODUCTION_REQUEST_MAPPING_UNKNOWN", codes)
        self.assertNotIn("CASE_INPUT_MISSING", codes)
        self.assertNotIn("REFERENCE_PATH_MISSING", codes)

    def test_canonical_evidence_manifest_integrity_and_tamper_detection(self) -> None:
        manifest_path = ROOT / "archive/实验/evaluation" / "revision-regression" / "input-bundle" / "manifest.json"
        self.assertEqual(validate_evidence_manifest(manifest_path, root=ROOT), [])
        original = json.loads(manifest_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(dir=str(ROOT / "archive/实验/evaluation" / "revision-regression")) as temp_dir:
            temp_path = Path(temp_dir) / "manifest.json"

            def codes_for(document: dict[str, Any]) -> set[str]:
                temp_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
                return {item["code"] for item in validate_evidence_manifest(temp_path, root=ROOT)}

            changed = json.loads(json.dumps(original))
            changed["assets"][0]["canonical_path"] = "archive/实验/evaluation/revision-regression/private-assets/missing.png"
            self.assertIn("FILE_NOT_FOUND", codes_for(changed))

            changed = json.loads(json.dumps(original))
            changed["assets"][0]["sha256"] = "0" * 64
            self.assertIn("EVIDENCE_HASH_MISMATCH", codes_for(changed))

            changed = json.loads(json.dumps(original))
            changed["cases"][0]["steps"][0]["prompt"]["sha256"] = "0" * 64
            self.assertIn("EVIDENCE_HASH_MISMATCH", codes_for(changed))

            changed = json.loads(json.dumps(original))
            changed["assets"].append(json.loads(json.dumps(changed["assets"][0])))
            self.assertIn("EVIDENCE_ASSET_DUPLICATE", codes_for(changed))

            changed = json.loads(json.dumps(original))
            changed["assets"][0]["used_in_cases"] = []
            self.assertIn("EVIDENCE_ASSET_ORPHAN", codes_for(changed))

            changed = json.loads(json.dumps(original))
            changed["cases"][0]["steps"][1]["transport"]["previous_output_source"] = "wrong.png"
            self.assertIn("EVIDENCE_TRANSPORT_INVALID", codes_for(changed))

    def test_canonical_json_round_trip_and_hash(self) -> None:
        value = {"b": [2, 1], "a": "阿尔可"}
        encoded = canonical_json(value)
        self.assertEqual(encoded, '{"a":"阿尔可","b":[2,1]}')
        self.assertEqual(json.loads(encoded), value)
        self.assertEqual(sha256_text(encoded), hashlib.sha256(encoded.encode("utf-8")).hexdigest())

    def test_materialize_request_expands_only_declared_prior_output(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as temp_dir:
            root = Path(temp_dir)
            image = root / "input.png"
            image.write_bytes(b"input")
            request = {
                "base_prompt": "a frozen prompt",
                "request_scoped_arco_references": [{"path": "input.png"}],
                "external_references": [],
            }
            output = root / "prior.png"
            output.write_bytes(b"prior")
            materialized = materialize_request(
                {**request, "request_scoped_arco_references": [{"path": "${previous_output:first}"}]},
                root=root,
                previous_outputs={"first": output},
            )
            self.assertEqual(materialized["request_scoped_arco_references"][0]["path"], str(output.resolve()))
            self.assertEqual(materialized["base_prompt"], request["base_prompt"])
            with self.assertRaises(RevisionBaselineError):
                materialize_request(
                    {"base_prompt": "x", "request_scoped_arco_references": [{"path": "../outside.png"}]},
                    root=root,
                )

    def test_write_once_conflict_is_not_silent(self) -> None:
        # Exercise the public behavior through two captures with the same
        # fixture/artifact directory.  The second capture reuses the exact
        # successful attempt and therefore does not overwrite its receipt.
        fixture_root, fixture_path, _ = self._make_fixture()
        try:
            provider, outputs = self._fake_provider(fixture_root)
            artifact = fixture_root / "baseline"
            first = capture_fixture(
                fixture_path,
                provider=provider,
                root=ROOT,
                capture_dir=artifact,
                execution_mode="mock",
            )
            self.assertEqual(first["status"], "PASS")
            second = capture_fixture(
                fixture_path,
                provider=provider,
                root=ROOT,
                capture_dir=artifact,
                execution_mode="mock",
            )
            self.assertEqual(second["status"], "PASS")
            self.assertEqual(len(outputs), 6)
            receipts = list((artifact / "receipts").rglob("*.json"))
            self.assertEqual(len(receipts), 6)
        finally:
            fixture_root and self._remove_tree(fixture_root)

    def test_fake_provider_capture_preserves_prompt_plan_payload_and_replay_inputs(self) -> None:
        fixture_root, fixture_path, _ = self._make_fixture()
        try:
            provider, outputs = self._fake_provider(fixture_root)
            artifact = fixture_root / "baseline"
            result = capture_fixture(
                fixture_path,
                provider=provider,
                root=ROOT,
                capture_dir=artifact,
                execution_mode="mock",
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(len(outputs), 6)
            manifest = artifact / "manifest.jsonl"
            records = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
            successes = [record for record in records if record["status"] == "SUCCESS"]
            self.assertEqual(len(successes), 6)
            for record in successes:
                self.assertEqual(record["compiled_prompt"], record["provider_payload"]["prompt"])
                self.assertEqual(
                    record["invocation_plan_stable"]["referenced_image_paths"],
                    record["provider_payload"]["referenced_image_paths"],
                )
                self.assertTrue(record["output"]["sha256"])
                self.assertTrue(record["receipt_path"])
            replay = replay_check(fixture_path, root=ROOT, capture_dir=artifact)
            self.assertEqual(replay["status"], "PASS")
            self.assertTrue(all(item["execution_mode"] == "mock" for item in successes))
        finally:
            self._remove_tree(fixture_root)

    def test_frozen_case_order_and_request_hash_are_required(self) -> None:
        fixture_root, fixture_path, _ = self._make_fixture()
        try:
            document = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
            document["cases"][0]["expected_sequence"] = ["revision-1", "first-generation", "revision-2"]
            fixture_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            result = validate_fixture(fixture_path, root=ROOT)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("CASE_SEQUENCE_INVALID", {item["code"] for item in result["reasons"]})
        finally:
            self._remove_tree(fixture_root)

    def test_failed_attempt_is_retained_and_retry_gets_a_new_attempt_number(self) -> None:
        fixture_root, fixture_path, _ = self._make_fixture()
        try:
            provider, outputs = self._fake_provider(fixture_root)
            state = {"failed": False}

            def flaky_provider(*, prompt: str, referenced_image_paths: list[str]):
                if not state["failed"]:
                    state["failed"] = True
                    raise RuntimeError("synthetic provider failure")
                return provider(prompt=prompt, referenced_image_paths=referenced_image_paths)

            artifact = fixture_root / "baseline"
            first = capture_fixture(
                fixture_path,
                provider=flaky_provider,
                root=ROOT,
                capture_dir=artifact,
                execution_mode="mock",
            )
            self.assertEqual(first["status"], "FAIL")
            first_records = [json.loads(line) for line in (artifact / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
            failed = [record for record in first_records if record["status"] == "FAILED"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["attempt"], 1)

            second = capture_fixture(
                fixture_path,
                provider=flaky_provider,
                root=ROOT,
                capture_dir=artifact,
                execution_mode="mock",
            )
            self.assertEqual(second["status"], "PASS")
            all_records = [json.loads(line) for line in (artifact / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
            retried = [
                record for record in all_records
                if record["case_id"] == "case-01" and record["step_id"] == "first-generation"
            ]
            self.assertEqual([record["attempt"] for record in retried], [1, 2])
            self.assertEqual(len(outputs), 6)
        finally:
            self._remove_tree(fixture_root)

    def test_complete_fixture_without_host_binding_is_blocked_precisely(self) -> None:
        fixture_root, fixture_path, _ = self._make_fixture()
        try:
            result = capture_fixture(
                fixture_path,
                root=ROOT,
                capture_dir=fixture_root / "baseline",
                execution_mode="real",
            )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["reasons"][0]["code"], "PROVIDER_BINDING_MISSING")
        finally:
            self._remove_tree(fixture_root)

    def _make_fixture(self) -> tuple[Path, Path, list[dict[str, Any]]]:
        fixture_root = Path(tempfile.mkdtemp(prefix="revision-baseline-test-", dir=str(ROOT / "archive/实验/evaluation" / "revision-regression")))
        request_root = fixture_root / "input-bundle"
        request_root.mkdir(parents=True)
        how_path = request_root / "large-scene-how.png"
        how_path.write_bytes(b"how-reference")
        bundle_path = request_root / "bundle.json"
        bundle_path.write_text('{"provided": true}\n', encoding="utf-8")

        calls: list[dict[str, Any]] = []

        def write_request(name: str, request: dict[str, Any]) -> str:
            path = request_root / name
            path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return path.relative_to(ROOT).as_posix()

        def base(prompt: str, *, prior: str | None = None, external: bool = False) -> dict[str, Any]:
            request: dict[str, Any] = {
                "base_prompt": prompt,
                "exposure_profile": "upper_body",
                "variant_id": "casual-outfit",
                "arco_references": [],
                "request_scoped_arco_references": [],
                "external_references": [],
                "style_briefs": [],
                "rendering_hygiene": "off",
            }
            if prior:
                request["request_scoped_arco_references"] = [
                    {
                        "reference_id": f"prior-{prior}",
                        "source_scope": "request_scoped_arco",
                        "role": "identity_reference",
                        "path": f"${{previous_output:{prior}}}",
                        "authority": "user_request",
                        "selection_reason": "explicit legacy prior output",
                        "confidence": "high",
                        "persistent": False,
                        "calibrating": False,
                        "inherit": ["identity", "face", "hair", "eyes"],
                        "do_not_inherit": ["outfit", "scene", "lighting"],
                        "coverage": {"visible_fields": ["identity", "face", "hair", "eyes", "body.upper"]},
                    }
                ]
            if external:
                request["external_references"] = [
                    {
                        "reference_id": "case-03-how",
                        "source_scope": "external_how",
                        "role": "style_reference",
                        "duties": ["style_reference"],
                        "path": how_path.relative_to(ROOT).as_posix(),
                        "sha256": sha256_file(how_path),
                        "authority": "user_request_external",
                        "selection_reason": "explicit large-scene HOW reference",
                        "confidence": "high",
                        "persistent": False,
                        "calibrating": False,
                        "provenance": {"provided_by": "user-input-bundle", "source": "large-scene-how"},
                        "inherit": ["linework", "composition", "lighting"],
                        "do_not_inherit": ["identity", "outfit", "face"],
                        "style_axes": ["linework"],
                    }
                ]
                request["style_briefs"] = [
                    {
                        "schema_version": 1,
                        "source_reference_id": "case-03-how",
                        "style_priority": "primary",
                        "active_axes": ["linework"],
                        "axes": {
                            "linework": {
                                "description": "thin clean restrained contours",
                                "confidence": "HIGH",
                            }
                        },
                    }
                ]
            return request

        request_specs = [
            ("case-01-first.json", base("case 01 first generation"), "case-01", "first-generation", None),
            ("case-01-rev1.json", base("case 01 revision one", prior="first-generation"), "case-01", "revision-1", "first-generation"),
            ("case-01-rev2.json", base("case 01 revision two", prior="revision-1"), "case-01", "revision-2", "revision-1"),
            ("case-02-first.json", base("case 02 first generation"), "case-02", "first-generation", None),
            ("case-02-detail.json", base("case 02 character detail revision", prior="first-generation"), "case-02", "detail-revision", "first-generation"),
            ("case-03-large.json", base("case 03 large scene baseline", external=True), "case-03", "baseline-generation", None),
        ]
        steps_by_case: dict[str, list[dict[str, Any]]] = {"case-01": [], "case-02": [], "case-03": []}
        for name, request, case_id, step_id, previous in request_specs:
            relative = write_request(name, request)
            request_path = ROOT / relative
            steps_by_case[case_id].append(
                {
                    "step_id": step_id,
                    "request_path": relative,
                    "request_sha256": sha256_file(request_path),
                    "previous_output_from": previous,
                    "attempt_policy": "first_success",
                }
            )
        fixture = {
            "schema_version": 1,
            "fixture_id": "arco-revision-regression-phase-0",
            "baseline": {
                "commit": APPROVED_BASELINE_COMMIT,
                "protected_runtime_paths": [
                    "scripts/arco_production.py",
                    "scripts/reference_runtime.py",
                    "scripts/arco_real_adapter.py",
                    "runtime/generation.yaml",
                    "runtime/production.yaml",
                    "character/identity.yaml",
                    "character/assets.yaml",
                    "character/style-baseline.yaml",
                    "runtime/style-policy.yaml",
                    "variants/index.yaml",
                    "variants/casual-outfit/variant.yaml",
                ],
                "working_tree_policy": "protected-runtime-must-be-clean",
            },
            "input_bundle": {
                "status": "FROZEN",
                "path": bundle_path.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(bundle_path),
                "note": "test bundle",
            },
            "cases": [
                {
                    "case_id": "case-01",
                    "purpose": "iterative_artifact",
                    "expected_sequence": ["first-generation", "revision-1", "revision-2"],
                    "input_status": "FROZEN",
                    "steps": steps_by_case["case-01"],
                },
                {
                    "case_id": "case-02",
                    "purpose": "character_detail_revision",
                    "expected_sequence": ["first-generation", "detail-revision"],
                    "input_status": "FROZEN",
                    "steps": steps_by_case["case-02"],
                },
                {
                    "case_id": "case-03",
                    "purpose": "large_scene_baseline",
                    "expected_sequence": ["baseline-generation"],
                    "input_status": "FROZEN",
                    "steps": steps_by_case["case-03"],
                },
            ],
        }
        fixture_path = fixture_root / "cases.yaml"
        fixture_path.write_text(yaml.safe_dump(fixture, sort_keys=False), encoding="utf-8")
        return fixture_root, fixture_path, calls

    def _fake_provider(self, fixture_root: Path):
        outputs: list[Path] = []

        def provider(*, prompt: str, referenced_image_paths: list[str]):
            index = len(outputs) + 1
            output = fixture_root / f"provider-output-{index}.png"
            output.write_bytes(b"\x89PNG\r\n" + prompt.encode("utf-8")[:20])
            outputs.append(output)
            return str(output)

        return provider, outputs

    def _remove_tree(self, path: Path) -> None:
        import shutil

        shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
