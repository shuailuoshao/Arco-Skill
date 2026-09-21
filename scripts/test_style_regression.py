from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_style_regression as regression


class StyleRegressionTests(unittest.TestCase):
    def _write_receipt(self, task_path: Path, generated: Path, root: Path) -> dict:
        task = regression.load_codex_task(task_path, root=root, require_utf8_schema=True)
        return regression.write_codex_execution_receipt(
            task_path,
            generated,
            sent_prompt=task["prompt"],
            root=root,
        )

    def _formal_exchange_fixture(self, root: Path) -> dict:
        evaluation_dir = root / "evaluation" / "style-regression"
        for relative, contents in {
            "scripts/run_style_regression.py": Path(__file__).with_name("run_style_regression.py").read_text(encoding="utf-8"),
            "scripts/reference_runtime.py": "runtime fixture\n",
            "scripts/arco_real_adapter.py": "adapter fixture\n",
            "runtime/generation.yaml": "generation: fixture\n",
            "runtime/style-policy.yaml": "policy: fixture\n",
            "character/assets.yaml": "assets: []\n",
            "character/style-baseline.yaml": "baseline: fixture\n",
            "evaluation/style-regression/cases.yaml": "fixture: true\n",
            "evaluation/style-regression/inputs-freeze.json": "{}\n",
        }.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        capture = evaluation_dir / "environment" / regression.R_FINAL_PREFLIGHT_ENVIRONMENT_PATH
        capture.parent.mkdir(parents=True, exist_ok=True)
        capture.write_text("{}\n", encoding="utf-8")

        cases = []
        plans = {}
        for case_id in regression.CASE_IDS:
            case_number = case_id[-2:]
            style_path = evaluation_dir / "private-assets" / "styles" / f"{case_id}.png"
            brief_path = evaluation_dir / "private-assets" / "briefs" / f"{case_id}.yaml"
            style_path.parent.mkdir(parents=True, exist_ok=True)
            brief_path.parent.mkdir(parents=True, exist_ok=True)
            style_path.write_bytes(b"style reference " + case_id.encode())
            brief_path.write_text("brief: frozen\n", encoding="utf-8")
            references = []
            for reference_id, role, scope in (
                ("identity-p01", "identity_reference", "managed_arco"),
                ("casual-outfit-primary", "outfit_reference", "managed_arco"),
                (f"external-style-{case_number}", "style_reference", "external_how"),
            ):
                reference_path = style_path if role == "style_reference" else evaluation_dir / "private-assets" / "managed" / f"{case_id}-{role}.png"
                if not reference_path.is_file():
                    reference_path.parent.mkdir(parents=True, exist_ok=True)
                    reference_path.write_bytes(f"{case_id} {role}".encode())
                references.append(
                    {
                        "reference_id": reference_id,
                        "role": role,
                        "duties": ["style_reference"] if role == "style_reference" else ["identity" if role == "identity_reference" else "outfit"],
                        "source_scope": scope,
                        "path": str(reference_path.resolve()),
                        "sha256": regression.sha256_file(reference_path),
                    }
                )
            selection_path = regression._selection_path(case_id, root=root)
            selection_path.parent.mkdir(parents=True, exist_ok=True)
            selection_path.write_text(json.dumps({"case_id": case_id, "references": [item["reference_id"] for item in references]}), encoding="utf-8")
            external_reference = {
                "reference_id": references[-1]["reference_id"],
                "path": regression._relative_path(style_path, root=root),
                "style_brief_path": f"private-assets/briefs/{case_id}.yaml",
                "sha256": regression.sha256_file(style_path),
                "role": "style_reference",
                "duties": ["style_reference"],
                "style_axes": ["linework"],
                "style_priority": "primary",
                "provenance": "test fixture",
            }
            case = {
                "case_id": case_id,
                "identity_variant": "casual-outfit",
                "state": None,
                "exposure_profile": "upper_body",
                "external_reference": external_reference,
                "expected_relevant_style_axes": ["linework"],
                "base_scene_prompt": "Full body portrait",
                "pose_requirement": "Standing",
                "composition_requirement": "Centered",
                "camera_requirement": "Eye level",
                "exposure_requirement": "Evenly lit",
            }
            cases.append(case)
            context = {"case_id": case_id, "resolved_axes": {"linework": {"description": "fixture"}}}
            group_plans = {}
            for group in regression.GENERATED_GROUPS:
                group_plans[group] = {
                    "prompt": f"exact frozen prompt {case_id} {group}",
                    "selected_reference_ids": [item["reference_id"] for item in references],
                    "referenced_image_paths": [item["path"] for item in references],
                    "style_context_hash": None if group == "A" else regression.sha256_json(context),
                }
            plans[case_id] = {
                "plans": group_plans,
                "references_by_group": {group: references for group in regression.GENERATED_GROUPS},
                "style_context": context,
            }
        return {
            "global_status": "READY",
            "errors": [],
            "case_statuses": {case_id: {"status": "READY"} for case_id in regression.CASE_IDS},
            "provider_binding": {"execution_mode": "codex-managed", "engine": "Codex-managed", "smoke_status": "PASS"},
            "corrected_legacy": {"runtime_sha256": "d" * 64, "selector_patch_revision": "c" * 40},
            "cases_document": {"cases": cases},
            "plans": plans,
        }

    def test_formal_sample_plan_has_36_samples_in_frozen_interleaved_order(self):
        plan = regression._formal_sample_plan()
        expected = [
            regression._sample_key(case_id, group, replicate)
            for case_id in regression.CASE_IDS
            for replicate in range(1, regression.EXPECTED_REPLICATES + 1)
            for group in regression.GENERATED_GROUPS
        ]
        self.assertEqual(len(plan), 36)
        self.assertEqual([sample["sample_key"] for sample in plan], expected)

    def test_formal_codex_queue_exports_one_immutable_task_and_reuses_pending(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preflight = self._formal_exchange_fixture(root)
            with mock.patch.object(regression, "_validate_formal_capture", return_value=preflight):
                first = regression.queue_next_formal_task(preflight, root=root)
                task_path = root / first["task_path"]
                before = task_path.read_bytes()
                task = regression.load_codex_task(task_path, root=root)
                again = regression.queue_next_formal_task(preflight, root=root)

            sample = preflight["plans"]["case-01"]
            self.assertTrue(first["queued"])
            self.assertFalse(again["queued"])
            self.assertTrue(again["reused"])
            self.assertEqual(first["task_sha256"], again["task_sha256"])
            self.assertEqual(task["task_kind"], "formal")
            self.assertEqual(task["batch"], "4B.3-F")
            self.assertEqual(task["task_id"], "formal:case-01:A:r1:attempt-1")
            self.assertEqual(task["prompt"], sample["plans"]["A"]["prompt"])
            self.assertEqual(task["referenced_image_paths"], sample["plans"]["A"]["referenced_image_paths"])
            self.assertEqual(task["reference_ids"], sample["plans"]["A"]["selected_reference_ids"])
            self.assertEqual(task["expected_output_path"], "evaluation/style-regression/outputs/case-01/A-r1.png")
            self.assertEqual(task["frozen_input_hashes"]["files"]["scripts/run_style_regression.py"], regression.sha256_file(root / "scripts/run_style_regression.py"))
            self.assertEqual(task_path.read_bytes(), before)
            self.assertEqual(len(regression._load_jsonl(regression._formal_manifest_path(root))), 1)
            self.assertFalse(regression._pilot_manifest_path(root).exists())
            self.assertFalse((root / regression.CODEX_SMOKE_REPORT_PATH).exists())
            self.assertFalse((root / "evaluation" / "style-regression" / "outputs").exists())

    def test_formal_resume_skips_hash_valid_result_and_queues_next_interleaved_sample(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preflight = self._formal_exchange_fixture(root)
            generated = root / "codex-generated.png"
            generated.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"first formal sample")
            with mock.patch.object(regression, "_validate_formal_capture", return_value=preflight):
                first = regression.queue_next_formal_task(preflight, root=root)
                self._write_receipt(root / first["task_path"], generated, root)
                regression.accept_codex_formal_output(root / first["task_path"], generated, root=root)
                second = regression.queue_next_formal_task(preflight, root=root)

            rows = regression._load_jsonl(regression._formal_manifest_path(root))
            self.assertEqual([row["sample_key"] for row in rows], ["case-01:A:r1", "case-01:B:r1"])
            self.assertEqual(rows[0]["status"], "succeeded")
            self.assertTrue(rows[0]["formal"])
            self.assertFalse(rows[0]["pilot"])
            self.assertTrue(rows[0]["include_in_formal_analysis"])
            self.assertEqual(second["sample_key"], "case-01:B:r1")
            self.assertFalse(regression._pilot_manifest_path(root).exists())

    def test_formal_technical_failure_creates_new_attempt_with_retry_reason(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preflight = self._formal_exchange_fixture(root)
            with mock.patch.object(regression, "_validate_formal_capture", return_value=preflight):
                first = regression.queue_next_formal_task(preflight, root=root)
                failed = regression.record_codex_formal_failure(
                    root / first["task_path"],
                    failure_kind="provider_tool_failure",
                    failure_code="imagegen_timeout",
                    failure_message="Image tool timed out before producing an output.",
                    root=root,
                )
                retry = regression.queue_next_formal_task(preflight, root=root)

            attempts = regression._load_jsonl(regression._formal_manifest_path(root))[0]["attempts"]
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0]["status"], "failed")
            self.assertEqual(attempts[0]["failure_reason"], "Image tool timed out before producing an output.")
            self.assertEqual(attempts[1]["retry_of_attempt"], 1)
            self.assertEqual(attempts[1]["retry_reason"], attempts[0]["failure_reason"])
            self.assertEqual(attempts[1]["task_id"], "formal:case-01:A:r1:attempt-2")
            self.assertNotEqual(attempts[0]["task_sha256"], attempts[1]["task_sha256"])
            self.assertTrue(attempts[1]["retry_reason"])
            self.assertEqual(retry["attempt"], 2)

    def test_formal_safety_refusal_is_terminal_even_if_caller_claims_provider_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preflight = self._formal_exchange_fixture(root)
            with mock.patch.object(regression, "_validate_formal_capture", return_value=preflight):
                first = regression.queue_next_formal_task(preflight, root=root)
                with self.assertRaisesRegex(regression.ExperimentError, "conflicts with the failure-code policy"):
                    regression.record_codex_formal_failure(
                        root / first["task_path"],
                        failure_kind="provider_tool_failure",
                        failure_code="imagegen_safety_block",
                        failure_message="HTTP 400 moderation_blocked safety_violations=[sexual]",
                        root=root,
                    )
                failed = regression.record_codex_formal_failure(
                    root / first["task_path"],
                    failure_kind="provider_policy_refusal",
                    failure_code="imagegen_safety_block",
                    failure_message="HTTP 400 moderation_blocked safety_violations=[sexual]",
                    root=root,
                )
                with self.assertRaisesRegex(regression.ExperimentError, "not retryable|terminal"):
                    regression.queue_next_formal_task(preflight, root=root)

            attempt = failed["attempts"][-1]
            self.assertEqual(attempt["failure_kind"], "provider_policy_refusal")
            self.assertEqual(attempt["failure_code"], "imagegen_safety_block")
            self.assertFalse(attempt["retryable"])
            self.assertEqual(attempt["next_action"], "blocked")

    def test_formal_generic_tool_error_detects_safety_refusal_from_message(self):
        policy = regression.classify_codex_failure(
            "imagegen_tool_error",
            "HTTP 400: request rejected by the safety system; code=moderation_blocked",
        )
        self.assertEqual(policy["failure_code"], "imagegen_safety_block")
        self.assertEqual(policy["failure_kind"], "provider_policy_refusal")
        self.assertFalse(policy["retryable"])

    def test_formal_network_and_timeout_retries_are_bounded(self):
        scenarios = (
            ("imagegen_network_send", 2),
            ("imagegen_timeout", 1),
        )
        for failure_code, allowed_retries in scenarios:
            with self.subTest(failure_code=failure_code), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                preflight = self._formal_exchange_fixture(root)
                with mock.patch.object(regression, "_validate_formal_capture", return_value=preflight):
                    queued = regression.queue_next_formal_task(preflight, root=root)
                    for retry_number in range(allowed_retries):
                        failed = regression.record_codex_formal_failure(
                            root / queued["task_path"],
                            failure_kind="provider_tool_failure",
                            failure_code=failure_code,
                            failure_message=f"transient {failure_code} {retry_number}",
                            root=root,
                        )
                        self.assertTrue(failed["attempts"][-1]["retryable"])
                        queued = regression.queue_next_formal_task(preflight, root=root)
                    failed = regression.record_codex_formal_failure(
                        root / queued["task_path"],
                        failure_kind="provider_tool_failure",
                        failure_code=failure_code,
                        failure_message=f"terminal {failure_code}",
                        root=root,
                    )
                    self.assertFalse(failed["attempts"][-1]["retryable"])
                    with self.assertRaisesRegex(regression.ExperimentError, "retry limit|not retryable|terminal"):
                        regression.queue_next_formal_task(preflight, root=root)

    def test_formal_unknown_provider_error_is_terminal(self):
        policy = regression.classify_codex_failure(
            "imagegen_tool_error",
            "Codex built-in image generation did not return a usable image.",
        )
        self.assertEqual(policy["failure_code"], "imagegen_tool_error")
        self.assertEqual(policy["failure_kind"], "provider_unknown_failure")
        self.assertFalse(policy["retryable"])

    def test_generated_png_path_resolution_prefers_structured_path_and_validates_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated_root = root / "generated_images"
            generated_root.mkdir()
            structured = generated_root / "structured.png"
            structured.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"structured")
            text_path = generated_root / "text.png"
            text_path.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"text")

            resolved = regression.resolve_codex_generated_png_path(
                {
                    "structuredContent": {"generated_path": str(structured)},
                    "content": [{"type": "text", "text": f"saved as {text_path}"}],
                },
                generated_root=generated_root,
            )
            self.assertEqual(resolved, structured.resolve())

            with self.assertRaisesRegex(regression.ExperimentError, "PNG path|outside"):
                regression.resolve_codex_generated_png_path(
                    {"path": str(root / "outside.png")},
                    generated_root=generated_root,
                )

    def test_generated_png_path_resolution_rejects_missing_and_non_png_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            generated_root = Path(temporary)
            not_png = generated_root / "bad.png"
            not_png.write_bytes(b"not a png")
            with self.assertRaisesRegex(regression.ExperimentError, "PNG path"):
                regression.resolve_codex_generated_png_path({}, generated_root=generated_root)
            with self.assertRaisesRegex(regression.ExperimentError, "signature"):
                regression.resolve_codex_generated_png_path(
                    {"generated_path": str(not_png)},
                    generated_root=generated_root,
                )

    def test_formal_exchange_rejects_edited_duplicate_stale_and_conflicting_artifacts(self):
        for mode in ("edited", "duplicate", "conflict", "stale", "duplicate-output"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                preflight = self._formal_exchange_fixture(root)
                generated = root / "codex-generated.png"
                generated.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"same generated content")
                with mock.patch.object(regression, "_validate_formal_capture", return_value=preflight):
                    first = regression.queue_next_formal_task(preflight, root=root)
                    task_path = root / first["task_path"]
                    if mode == "edited":
                        task_path.write_text(task_path.read_text(encoding="utf-8").replace("exact frozen prompt", "edited prompt"), encoding="utf-8")
                        with self.assertRaisesRegex(regression.ExperimentError, "hash|edited"):
                            regression.queue_next_formal_task(preflight, root=root)
                    elif mode == "duplicate":
                        duplicate = task_path.with_name("duplicate-copy.json")
                        duplicate.write_bytes(task_path.read_bytes())
                        with self.assertRaisesRegex(regression.ExperimentError, "duplicate|stale|missing"):
                            regression.queue_next_formal_task(preflight, root=root)
                    elif mode == "conflict":
                        output = root / "evaluation" / "style-regression" / "outputs" / "case-01" / "A-r1.png"
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(generated.read_bytes())
                        with self.assertRaisesRegex(regression.ExperimentError, "Conflicting output"):
                            regression.queue_next_formal_task(preflight, root=root)
                    elif mode == "stale":
                        os.utime(generated, (1, 1))
                        self._write_receipt(task_path, generated, root)
                        with self.assertRaisesRegex(regression.ExperimentError, "stale"):
                            regression.accept_codex_formal_output(task_path, generated, root=root)
                    else:
                        self._write_receipt(task_path, generated, root)
                        regression.accept_codex_formal_output(task_path, generated, root=root)
                        second = regression.queue_next_formal_task(preflight, root=root)
                        self._write_receipt(root / second["task_path"], generated, root)
                        with self.assertRaisesRegex(regression.ExperimentError, "duplicates"):
                            regression.accept_codex_formal_output(root / second["task_path"], generated, root=root)

    def test_nontechnical_formal_failure_is_terminal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preflight = self._formal_exchange_fixture(root)
            with mock.patch.object(regression, "_validate_formal_capture", return_value=preflight):
                first = regression.queue_next_formal_task(preflight, root=root)
                regression.record_codex_formal_failure(
                    root / first["task_path"],
                    failure_kind="operator_rejected",
                    failure_code="rejected",
                    failure_message="Operator rejected this attempt.",
                    root=root,
                )
                with self.assertRaisesRegex(regression.ExperimentError, "terminal failure|not retryable"):
                    regression.queue_next_formal_task(preflight, root=root)

    def test_formal_capture_rejects_legacy_revision_and_failed_gates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture_path = root / "evaluation" / "style-regression" / "environment" / regression.R_FINAL_PREFLIGHT_ENVIRONMENT_PATH
            capture_path.parent.mkdir(parents=True)
            capture_path.write_text(json.dumps({"record_kind": "batch-4b2r-final-preflight-capture"}), encoding="utf-8")
            with self.assertRaisesRegex(regression.ExperimentError, "not a Batch 4B.3-T"):
                regression._validate_r4_formal_capture(root)

            capture_path.write_text(
                json.dumps(
                    {
                        "record_kind": "batch-4b3t-final-preflight-capture",
                        "execution_mode": "codex-managed",
                        "engine": "Codex-managed",
                        "hard_preflight_ready": False,
                        "experiment_ready": False,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(regression.ExperimentError, "READY hard preflight"):
                regression._validate_r4_formal_capture(root)

    def test_preflight_report_after_capture_does_not_replace_capture_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_json, baseline_md = regression._preflight_report_paths(root)
            self.assertEqual(baseline_json.name, regression.R_PREFLIGHT_JSON_PATH)
            capture = root / "evaluation" / "style-regression" / "environment" / regression.R_FINAL_PREFLIGHT_ENVIRONMENT_PATH
            capture.parent.mkdir(parents=True)
            capture.write_text("{}\n", encoding="utf-8")

            live_json, live_md = regression._preflight_report_paths(root)

            self.assertEqual(live_json.name, regression.R_PREFLIGHT_LIVE_JSON_PATH)
            self.assertEqual(live_md.name, regression.R_PREFLIGHT_LIVE_MARKDOWN_PATH)
            self.assertNotEqual(live_json, baseline_json)
            self.assertNotEqual(live_md, baseline_md)

    def test_formal_manifest_rejects_retry_after_nontechnical_failure_even_if_attempt_is_present(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preflight = self._formal_exchange_fixture(root)
            with mock.patch.object(regression, "_validate_formal_capture", return_value=preflight):
                first = regression.queue_next_formal_task(preflight, root=root)
                record = regression.record_codex_formal_failure(
                    root / first["task_path"],
                    failure_kind="operator_rejected",
                    failure_code="rejected",
                    failure_message="Operator rejected this attempt.",
                    root=root,
                )
            first_attempt = record["attempts"][0]
            first_task = regression.load_codex_task(root / first_attempt["task_path"], root=root)
            second_task_path = regression._formal_task_path("case-01", "A", 1, 2, root=root)
            second_task = regression.build_codex_task(
                task_id="formal:case-01:A:r1:attempt-2",
                task_kind="formal",
                case_id="case-01",
                group="A",
                replicate=1,
                prompt=first_task["prompt"],
                referenced_image_paths=first_task["referenced_image_paths"],
                reference_ids=first_task["reference_ids"],
                expected_output_path=regression._relative_path(
                    regression._formal_task_output_path("case-01", "A", 1, 2, root=root),
                    root=root,
                ),
                frozen_input_hashes=first_task["frozen_input_hashes"],
                batch="4B.3-F",
            )
            regression.write_codex_task(second_task, path=second_task_path)
            tampered = dict(record)
            tampered["status"] = "queued"
            tampered["attempts"] = list(record["attempts"]) + [
                {
                    "attempt": 2,
                    "task_id": second_task["task_id"],
                    "task_path": regression._relative_path(second_task_path, root=root),
                    "task_sha256": second_task["task_sha256"],
                    "status": "queued",
                    "retry_of_attempt": 1,
                    "retry_reason": first_attempt["failure_reason"],
                    "retry_failure_kind": first_attempt["failure_kind"],
                }
            ]
            tampered["task_path"] = regression._relative_path(second_task_path, root=root)
            tampered["task_sha256"] = second_task["task_sha256"]
            regression._upsert_manifest(tampered, path=regression._formal_manifest_path(root))

            with self.assertRaisesRegex(regression.ExperimentError, "allowlisted technical failure"):
                regression._validate_formal_state(preflight, root=root)

    def test_codex_generate_cli_stops_when_current_final_capture_gate_fails(self):
        before = sorted(path.relative_to(regression._formal_task_dir()).as_posix() for path in regression._formal_task_dir().glob("*.json")) if regression._formal_task_dir().exists() else []
        with (
            mock.patch.dict(os.environ, {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}),
            mock.patch.object(regression, "_validate_formal_capture", side_effect=regression.ExperimentError("missing new final capture")),
            mock.patch.object(regression.sys, "stderr", io.StringIO()),
        ):
            exit_code = regression.main(["--generate", "--codex-managed"])

        self.assertEqual(exit_code, 2)
        after = sorted(path.relative_to(regression._formal_task_dir()).as_posix() for path in regression._formal_task_dir().glob("*.json")) if regression._formal_task_dir().exists() else []
        self.assertEqual(after, before)

    def test_codex_generation_task_freezes_exact_prompt_and_reference_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_path = root / "evaluation" / "style-regression" / "pilot" / "tasks" / "A.json"
            prompt = "Exact compiled prompt.\nKeep every token."
            reference_paths = ["refs/identity.png", "refs/outfit.png", "refs/style.jpg"]
            task = regression.build_codex_task(
                task_id="pilot:case-01:A:r1",
                task_kind="pilot",
                case_id="case-01",
                group="A",
                replicate=1,
                prompt=prompt,
                referenced_image_paths=reference_paths,
                reference_ids=["identity-p01", "casual-outfit-primary", "external-style-01"],
                expected_output_path="evaluation/style-regression/pilot/outputs/case-01/A-r1.png",
                frozen_input_hashes={
                    "references": [
                        {"reference_id": "identity-p01", "path": "refs/identity.png", "sha256": "a" * 64},
                        {"reference_id": "casual-outfit-primary", "path": "refs/outfit.png", "sha256": "b" * 64},
                        {"reference_id": "external-style-01", "path": "refs/style.jpg", "sha256": "c" * 64},
                    ],
                    "files": {},
                },
                created_at="2026-09-17T00:00:00+00:00",
            )

            written = regression.write_codex_task(task, path=task_path)
            loaded = regression.load_codex_task(task_path)

            self.assertEqual(loaded["prompt"], prompt)
            self.assertEqual(loaded["referenced_image_paths"], reference_paths)
            self.assertEqual(loaded["reference_ids"], ["identity-p01", "casual-outfit-primary", "external-style-01"])
            self.assertEqual(loaded["task_sha256"], written["task_sha256"])
            self.assertEqual(
                loaded["task_sha256"],
                regression.sha256_json({key: value for key, value in loaded.items() if key != "task_sha256"}),
            )
            with self.assertRaisesRegex(regression.ExperimentError, "already exists"):
                regression.write_codex_task(task, path=task_path)

            tampered = dict(loaded)
            tampered["prompt"] = "edited prompt"
            task_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(regression.ExperimentError, "hash"):
                regression.load_codex_task(task_path)

    def test_codex_task_v2_round_trips_chinese_prompt_as_exact_utf8_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_path = root / "evaluation" / "style-regression" / "formal" / "tasks" / "case-01-A-r1-attempt-2.json"
            prompt = "阿尔可站在庭院中，双手清楚可见。保持细腻线条与柔和色彩。"
            task = regression.build_codex_task(
                task_id="formal:case-01:A:r1:attempt-2",
                task_kind="formal",
                case_id="case-01",
                group="A",
                replicate=1,
                prompt=prompt,
                referenced_image_paths=[],
                reference_ids=[],
                expected_output_path="evaluation/style-regression/outputs/case-01/A-r1-attempt-2.png",
                frozen_input_hashes={"references": [], "files": {}},
            )
            regression.write_codex_task(task, path=task_path)

            loaded = regression.load_codex_task(task_path, root=root, require_utf8_schema=True)

            self.assertEqual(loaded["schema_version"], 2)
            self.assertEqual(loaded["prompt_encoding"], "utf-8")
            self.assertEqual(loaded["prompt_sha256_utf8"], regression.hashlib.sha256(prompt.encode("utf-8")).hexdigest())
            self.assertEqual(loaded["prompt"].encode("utf-8"), prompt.encode("utf-8"))
            self.assertEqual(loaded["prompt"], prompt)

    def test_legacy_runner_compatibility_is_bound_to_one_immutable_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner_path = root / "scripts" / "run_style_regression.py"
            other_path = root / "runtime" / "generation.yaml"
            runner_path.parent.mkdir(parents=True)
            other_path.parent.mkdir(parents=True)
            runner_path.write_text("parent runner\n", encoding="utf-8")
            other_path.write_text("frozen generation config\n", encoding="utf-8")
            task_path = root / "evaluation" / "style-regression" / "formal" / "tasks" / "case-01-A-r1-attempt-2.json"
            task = regression.build_codex_task(
                task_id="formal:case-01:A:r1:attempt-2",
                task_kind="formal",
                case_id="case-01",
                group="A",
                replicate=1,
                prompt="Exact frozen prompt",
                referenced_image_paths=[],
                reference_ids=[],
                expected_output_path="evaluation/style-regression/outputs/case-01/A-r1-attempt-2.png",
                frozen_input_hashes={
                    "references": [],
                    "files": {
                        "scripts/run_style_regression.py": regression.sha256_file(runner_path),
                        "runtime/generation.yaml": regression.sha256_file(other_path),
                    },
                },
                created_at="2026-09-18T00:00:00+00:00",
            )
            regression.write_codex_task(task, path=task_path)
            entry = {
                "task_path": regression._relative_path(task_path, root=root),
                "task_sha256": task["task_sha256"],
                "task_file_sha256": regression.sha256_file(task_path),
                "task_kind": "formal",
                "runner_sha256": task["frozen_input_hashes"]["files"]["scripts/run_style_regression.py"],
            }
            allowlist = {task["task_sha256"]: entry}
            runner_path.write_text("patched runner\n", encoding="utf-8")

            loaded = regression.load_codex_task(
                task_path,
                root=root,
                require_utf8_schema=True,
                legacy_runner_hash_allowlist=allowlist,
            )
            self.assertEqual(loaded["task_sha256"], task["task_sha256"])

            wrong_path = {task["task_sha256"]: {**entry, "task_path": "other/task.json"}}
            with self.assertRaisesRegex(regression.ExperimentError, "frozen input hash mismatch"):
                regression.load_codex_task(task_path, root=root, legacy_runner_hash_allowlist=wrong_path)
            wrong_file_pin = {task["task_sha256"]: {**entry, "task_file_sha256": "0" * 64}}
            with self.assertRaisesRegex(regression.ExperimentError, "frozen input hash mismatch"):
                regression.load_codex_task(task_path, root=root, legacy_runner_hash_allowlist=wrong_file_pin)
            wrong_kind = {task["task_sha256"]: {**entry, "task_kind": "pilot"}}
            with self.assertRaisesRegex(regression.ExperimentError, "frozen input hash mismatch"):
                regression.load_codex_task(task_path, root=root, legacy_runner_hash_allowlist=wrong_kind)

            other_path.write_text("changed generation config\n", encoding="utf-8")
            with self.assertRaisesRegex(regression.ExperimentError, "runtime/generation.yaml"):
                regression.load_codex_task(
                    task_path,
                    root=root,
                    legacy_runner_hash_allowlist=allowlist,
                )

    def test_codex_ascii_envelope_verifies_before_generator_and_rejects_transcoded_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_path = root / "evaluation" / "style-regression" / "pilot" / "tasks" / "case-01-A-r1.json"
            prompt = "阿尔可，柔和光线，清晰线条。"
            task = regression.build_codex_task(
                task_id="pilot:case-01:A:r1",
                task_kind="pilot",
                case_id="case-01",
                group="A",
                replicate=1,
                prompt=prompt,
                referenced_image_paths=[],
                reference_ids=[],
                expected_output_path="evaluation/style-regression/pilot/outputs/batch-4b3t-r2/case-01/A-r1.png",
                frozen_input_hashes={"references": [], "files": {}},
            )
            regression.write_codex_task(task, path=task_path)
            envelope = regression.build_codex_task_envelope(task_path, root=root)
            serialized = json.dumps(envelope, ensure_ascii=True)
            self.assertTrue(serialized.isascii())

            self.assertEqual(regression.decode_codex_task_envelope(envelope)["prompt"], prompt)
            generator = mock.Mock(return_value="generated")
            self.assertEqual(
                regression.dispatch_codex_task(task_path, envelope, generator, root=root),
                "generated",
            )
            self.assertEqual(generator.call_args.kwargs["prompt"], prompt)

            corrupted = dict(envelope)
            corrupted["prompt_utf8_base64"] = regression.base64.b64encode("不同的提示".encode("gbk")).decode("ascii")
            with self.assertRaisesRegex(regression.ExperimentError, "UTF-8|prompt hash"):
                regression.decode_codex_task_envelope(corrupted)
            generator.reset_mock()
            with self.assertRaisesRegex(regression.ExperimentError, "UTF-8|prompt hash|prompt digest|envelope"):
                regression.dispatch_codex_task(task_path, corrupted, generator, root=root)
            generator.assert_not_called()

    def test_codex_prompt_verification_cli_returns_ascii_escaped_prompt_only_on_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_path = root / "evaluation" / "style-regression" / "pilot" / "tasks" / "case-01-A-r1.json"
            prompt = "阿尔可，逐字节验证。"
            task = regression.build_codex_task(
                task_id="pilot:case-01:A:r1",
                task_kind="pilot",
                case_id="case-01",
                group="A",
                replicate=1,
                prompt=prompt,
                referenced_image_paths=[],
                reference_ids=[],
                expected_output_path="evaluation/style-regression/pilot/outputs/batch-4b3t-r2/case-01/A-r1.png",
                frozen_input_hashes={"references": [], "files": {}},
            )
            regression.write_codex_task(task, path=task_path)
            encoded = regression.base64.b64encode(prompt.encode("utf-8")).decode("ascii")
            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}),
                mock.patch.object(regression, "_repo_path", return_value=task_path),
                mock.patch.object(regression.sys, "stdout", stdout),
                mock.patch.object(regression.sys, "stderr", io.StringIO()),
            ):
                exit_code = regression.main(
                    ["--codex-managed", "--verify-codex-prompt", str(task_path), "--sent-prompt-base64", encoded]
                )
            output = stdout.getvalue().strip()
            verified = json.loads(output)
            self.assertEqual(exit_code, 0)
            self.assertTrue(output.isascii())
            self.assertEqual(verified["prompt"], prompt)
            self.assertEqual(verified["sent_prompt_sha256_utf8"], task["prompt_sha256_utf8"])

            stdout = io.StringIO()
            corrupted = regression.base64.b64encode("被转码的提示".encode("gbk")).decode("ascii")
            with (
                mock.patch.dict(os.environ, {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}),
                mock.patch.object(regression, "_repo_path", return_value=task_path),
                mock.patch.object(regression.sys, "stdout", stdout),
                mock.patch.object(regression.sys, "stderr", io.StringIO()),
            ):
                exit_code = regression.main(
                    ["--codex-managed", "--verify-codex-prompt", str(task_path), "--sent-prompt-base64", corrupted]
                )
            self.assertEqual(exit_code, 2)
            self.assertEqual(stdout.getvalue(), "")

    def test_execution_receipt_binds_task_prompt_references_and_output_hash(self):
        for tamper in ("task", "prompt", "references", "output"):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                ref_paths = [root / "refs" / "identity.png", root / "refs" / "style.png"]
                for path in ref_paths:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"reference:" + path.name.encode())
                reference_rows = [
                    {"reference_id": ref_id, "path": str(path), "sha256": regression.sha256_file(path)}
                    for ref_id, path in zip(("identity-p01", "external-style-01"), ref_paths)
                ]
                task_path = root / "evaluation" / "style-regression" / "formal" / "tasks" / "case-01-A-r1-attempt-1.json"
                task = regression.build_codex_task(
                    task_id="formal:case-01:A:r1:attempt-1",
                    task_kind="formal",
                    case_id="case-01",
                    group="A",
                    replicate=1,
                    prompt="阿尔可，准确传输。",
                    referenced_image_paths=[str(path) for path in ref_paths],
                    reference_ids=["identity-p01", "external-style-01"],
                    expected_output_path="evaluation/style-regression/outputs/case-01/A-r1.png",
                    frozen_input_hashes={"references": reference_rows, "files": {}},
                )
                regression.write_codex_task(task, path=task_path)
                generated = root / "generated.png"
                generated.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"receipt-bound-png")
                receipt = regression.write_codex_execution_receipt(
                    task_path,
                    generated,
                    sent_prompt=task["prompt"],
                    root=root,
                )
                receipt_path = regression._codex_execution_receipt_path(task_path, root=root)
                self.assertEqual(receipt["sample_id"], "case-01:A:r1")
                self.assertEqual(receipt["attempt"], 1)
                self.assertEqual(receipt["task_sha256"], task["task_sha256"])
                self.assertEqual(receipt["sent_prompt_sha256_utf8"], task["prompt_sha256_utf8"])
                self.assertEqual(receipt["references_ordered"], reference_rows)
                self.assertEqual(receipt["output_sha256"], regression.sha256_file(generated))

                tampered_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if tamper == "task":
                    tampered_receipt["task_sha256"] = "0" * 64
                elif tamper == "prompt":
                    tampered_receipt["sent_prompt_sha256_utf8"] = "0" * 64
                elif tamper == "references":
                    tampered_receipt["references_ordered"].reverse()
                else:
                    tampered_receipt["output_sha256"] = "0" * 64
                tampered_receipt["receipt_sha256"] = regression.sha256_json(
                    {key: value for key, value in tampered_receipt.items() if key != "receipt_sha256"}
                )
                receipt_path.write_text(json.dumps(tampered_receipt), encoding="utf-8")
                with self.assertRaises(regression.ExperimentError):
                    regression.verify_codex_execution_receipt(task_path, generated, root=root)

    def test_legacy_transport_migration_preserves_a1_and_allows_successful_attempt_scoped_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preflight = self._formal_exchange_fixture(root)
            rows = []
            a_output = root / "evaluation" / "style-regression" / "outputs" / "case-01" / "A-r1.png"
            a_output.parent.mkdir(parents=True, exist_ok=True)
            a_output.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"preserved-invalid-image")
            a_hash = regression.sha256_file(a_output)
            for group, status in (("A", "succeeded"), ("B", "queued")):
                sample = preflight["plans"]["case-01"]
                plan = sample["plans"][group]
                refs = sample["references_by_group"][group]
                frozen_references = [
                    {"reference_id": ref["reference_id"], "path": ref["path"], "sha256": ref["sha256"]}
                    for ref in refs
                ]
                task_path = regression._formal_task_path("case-01", group, 1, 1, root=root)
                task = regression.build_codex_task(
                    task_id=f"formal:case-01:{group}:r1:attempt-1",
                    task_kind="formal",
                    case_id="case-01",
                    group=group,
                    replicate=1,
                    prompt=plan["prompt"],
                    referenced_image_paths=plan["referenced_image_paths"],
                    reference_ids=plan["selected_reference_ids"],
                    expected_output_path=f"evaluation/style-regression/outputs/case-01/{group}-r1.png",
                    frozen_input_hashes={"references": frozen_references, "files": {}},
                    batch="4B.3-F",
                )
                legacy = dict(task)
                legacy["schema_version"] = regression.LEGACY_CODEX_TASK_SCHEMA_VERSION
                legacy.pop("prompt_encoding")
                legacy.pop("prompt_sha256_utf8")
                legacy["task_sha256"] = regression.sha256_json(
                    {key: value for key, value in legacy.items() if key != "task_sha256"}
                )
                task_path.parent.mkdir(parents=True, exist_ok=True)
                task_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
                attempt = {
                    "attempt": 1,
                    "task_id": legacy["task_id"],
                    "task_path": regression._relative_path(task_path, root=root),
                    "task_sha256": legacy["task_sha256"],
                    "status": status,
                }
                row = {
                    "sample_key": f"case-01:{group}:r1",
                    "case_id": "case-01",
                    "group": group,
                    "replicate": 1,
                    "formal": True,
                    "pilot": False,
                    "include_in_formal_analysis": True,
                    "execution_mode": "codex-managed",
                    "engine": "Codex-managed",
                    "output_path": legacy["expected_output_path"],
                    "status": status,
                    "attempts": [attempt],
                }
                if group == "A":
                    attempt["output_sha256"] = a_hash
                    row["attempts"] = [attempt]
                    row["output_sha256"] = a_hash
                rows.append(row)
            regression._write_manifest_atomic(regression._formal_manifest_path(root), rows)
            before = a_output.read_bytes()

            migrated = regression.migrate_legacy_formal_transport_state(root=root)

            migrated_rows = regression._load_jsonl(regression._formal_manifest_path(root))
            a_row, b_row = migrated_rows
            self.assertEqual(migrated["formal_sample_counts"], {group: 0 for group in regression.GENERATED_GROUPS})
            self.assertEqual(a_row["status"], "invalidated")
            self.assertFalse(a_row["include_in_formal_analysis"])
            self.assertTrue(a_row["excluded_from_verdict"])
            self.assertEqual(a_row["failure_kind"], "task_transport")
            self.assertEqual(a_row["failure_reason"], "prompt_encoding_corruption")
            self.assertEqual(a_row["output_sha256"], a_hash)
            self.assertEqual(a_output.read_bytes(), before)
            self.assertEqual(b_row["status"], "superseded")
            self.assertIsNone(b_row.get("failure_kind"))
            self.assertIsNone(b_row["attempts"][0].get("failure_kind"))
            self.assertEqual(regression._compliant_formal_sample_counts(migrated_rows, root=root), {group: 0 for group in regression.GENERATED_GROUPS})
            self.assertEqual(regression._validate_pre_capture_formal_history(root), [])
            validated_rows, validated_index, pending_index = regression._validate_formal_state(preflight, root=root)
            self.assertEqual(len(validated_rows), 2)
            self.assertEqual(set(validated_index), {"case-01:A:r1", "case-01:B:r1"})
            self.assertEqual(pending_index, 0)

            with mock.patch.object(regression, "_validate_formal_capture", return_value=preflight):
                retry = regression.queue_next_formal_task(preflight, root=root)
                retry_path = root / retry["task_path"]
                generated_retry = root / "codex-generated-A-r1-attempt-2.png"
                generated_retry.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"valid retry output")
                self._write_receipt(retry_path, generated_retry, root)
                accepted = regression.accept_codex_formal_output(retry_path, generated_retry, root=root)

            self.assertEqual(accepted["output_sha256"], regression.sha256_file(generated_retry))
            self.assertEqual(a_output.read_bytes(), before)
            validated_rows, validated_index, pending_index = regression._validate_formal_state(preflight, root=root)
            self.assertEqual(pending_index, 1)
            self.assertEqual(
                regression._compliant_formal_sample_counts(validated_rows, root=root),
                {"A": 1, "B": 0, "C": 0},
            )
            self.assertEqual(validated_index["case-01:A:r1"]["attempts"][0]["output_sha256"], a_hash)
            self.assertEqual(validated_index["case-01:A:r1"]["attempts"][1]["output_sha256"], accepted["output_sha256"])
            self.assertEqual(validated_index["case-01:A:r1"]["output_sha256"], accepted["output_sha256"])

            baseline_rows = regression._load_jsonl(regression._formal_manifest_path(root))
            tampered_rows = copy.deepcopy(baseline_rows)
            tampered_rows[0]["attempts"][0]["failure_reason"] = "different incident"
            regression._write_manifest_atomic(regression._formal_manifest_path(root), tampered_rows)
            with self.assertRaisesRegex(regression.ExperimentError, "recorded A-r1 prompt transport incident"):
                regression._validate_formal_state(preflight, root=root)

            regression._write_manifest_atomic(regression._formal_manifest_path(root), baseline_rows)
            tampered_rows = copy.deepcopy(baseline_rows)
            tampered_rows[0]["attempts"][0]["failure_kind"] = "provider_tool_failure"
            regression._write_manifest_atomic(regression._formal_manifest_path(root), tampered_rows)
            with self.assertRaisesRegex(regression.ExperimentError, "recorded A-r1 prompt transport incident"):
                regression._validate_formal_state(preflight, root=root)
            tampered_rows = copy.deepcopy(baseline_rows)
            tampered_rows[0]["attempts"][0]["excluded_from_verdict"] = False
            regression._write_manifest_atomic(regression._formal_manifest_path(root), tampered_rows)
            with self.assertRaisesRegex(regression.ExperimentError, "recorded A-r1 prompt transport incident"):
                regression._validate_formal_state(preflight, root=root)

            regression._write_manifest_atomic(regression._formal_manifest_path(root), baseline_rows)
            a_output.write_bytes(before + b"tampered")
            with self.assertRaisesRegex(regression.ExperimentError, "Invalidated audit output is missing or changed"):
                regression._validate_formal_state(preflight, root=root)
            a_output.write_bytes(before)

            tampered_rows = copy.deepcopy(baseline_rows)
            tampered_rows[0]["attempts"][0]["output_sha256"] = "f" * 64
            regression._write_manifest_atomic(regression._formal_manifest_path(root), tampered_rows)
            with self.assertRaisesRegex(regression.ExperimentError, "Invalidated audit output is missing or changed"):
                regression._validate_formal_state(preflight, root=root)
            regression._write_manifest_atomic(regression._formal_manifest_path(root), baseline_rows)

            tampered_rows = copy.deepcopy(baseline_rows)
            tampered_rows[0]["output_sha256"] = "f" * 64
            regression._write_manifest_atomic(regression._formal_manifest_path(root), tampered_rows)
            with self.assertRaisesRegex(regression.ExperimentError, "Completed formal output or receipt hash"):
                regression._validate_formal_state(preflight, root=root)
            regression._write_manifest_atomic(regression._formal_manifest_path(root), baseline_rows)

            accepted_output = root / accepted["output_path"]
            accepted_output_bytes = accepted_output.read_bytes()
            accepted_output.write_bytes(accepted_output_bytes + b"tampered")
            with self.assertRaisesRegex(regression.ExperimentError, "Completed formal output or receipt hash"):
                regression._validate_formal_state(preflight, root=root)
            accepted_output.write_bytes(accepted_output_bytes)
            receipt_path = root / accepted["receipt_path"]
            receipt_bytes = receipt_path.read_bytes()
            receipt_path.write_bytes(receipt_bytes + b"tampered")
            with self.assertRaisesRegex(regression.ExperimentError, "receipt cannot be read|receipt hash is invalid or tampered"):
                regression._validate_formal_state(preflight, root=root)
            receipt_path.write_bytes(receipt_bytes)

            with mock.patch.object(regression, "_validate_formal_capture", return_value=preflight):
                next_task = regression.queue_next_formal_task(preflight, root=root)
            self.assertEqual(next_task["sample_key"], "case-01:B:r1")
            queued_rows = regression._load_jsonl(regression._formal_manifest_path(root))
            tampered_rows = copy.deepcopy(queued_rows)
            tampered_rows[1]["output_sha256"] = a_hash
            regression._write_manifest_atomic(regression._formal_manifest_path(root), tampered_rows)
            with self.assertRaisesRegex(regression.ExperimentError, "retains completed-output metadata"):
                regression._validate_formal_state(preflight, root=root)
            regression._write_manifest_atomic(regression._formal_manifest_path(root), queued_rows)

            retry_task_path = root / next_task["task_path"]
            generated_b = root / "codex-generated-B-r1-attempt-2.png"
            generated_b.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"valid B retry output")
            self._write_receipt(retry_task_path, generated_b, root)
            with mock.patch.object(regression, "_validate_formal_capture", return_value=preflight):
                accepted_b = regression.accept_codex_formal_output(retry_task_path, generated_b, root=root)
            self.assertEqual(accepted_b["output_sha256"], regression.sha256_file(generated_b))
            _, validated_index, pending_index = regression._validate_formal_state(preflight, root=root)
            self.assertEqual(pending_index, 2)
            self.assertEqual(validated_index["case-01:B:r1"]["status"], "succeeded")
            self.assertEqual(
                regression._compliant_formal_sample_counts(
                    regression._load_jsonl(regression._formal_manifest_path(root)), root=root
                ),
                {"A": 1, "B": 1, "C": 0},
            )

            with mock.patch.object(regression, "_validate_formal_capture", return_value=preflight):
                third_task = regression.queue_next_formal_task(preflight, root=root)
            self.assertEqual(third_task["sample_key"], "case-01:C:r1")
            queued_rows = regression._load_jsonl(regression._formal_manifest_path(root))
            queued_rows[2]["output_sha256"] = accepted_b["output_sha256"]
            regression._write_manifest_atomic(regression._formal_manifest_path(root), queued_rows)
            with self.assertRaisesRegex(regression.ExperimentError, "retains completed-output metadata"):
                regression._validate_formal_state(preflight, root=root)

    def test_codex_result_acceptance_copies_fresh_nonempty_png_and_hashes_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_path = root / "evaluation" / "style-regression" / "host-smoke" / "codex-task.json"
            task = regression.build_codex_task(
                task_id="smoke:4b2r",
                task_kind="smoke",
                case_id=None,
                group=None,
                replicate=None,
                prompt=regression.HOST_SMOKE_PROMPT,
                referenced_image_paths=[],
                reference_ids=[],
                expected_output_path="evaluation/style-regression/host-smoke/outputs/output.png",
                frozen_input_hashes={"smoke_prompt_sha256": regression.hashlib.sha256(regression.HOST_SMOKE_PROMPT.encode("utf-8")).hexdigest(), "files": {}},
            )
            regression.write_codex_task(task, path=task_path)
            generated = root / "codex-generated.png"
            generated.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"smoke-png-payload")

            result = regression.accept_codex_task_output(task_path, generated, root=root)

            expected_output = root / task["expected_output_path"]
            self.assertEqual(result["output_path"], expected_output.resolve())
            self.assertEqual(expected_output.read_bytes(), generated.read_bytes())
            self.assertEqual(result["output_sha256"], regression.sha256_file(expected_output))
            with self.assertRaisesRegex(regression.ExperimentError, "already exists"):
                regression.accept_codex_task_output(task_path, generated, root=root)

    def test_codex_result_acceptance_rejects_invalid_and_stale_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_path = root / "task.json"
            task = regression.build_codex_task(
                task_id="smoke:stale-test",
                task_kind="smoke",
                case_id=None,
                group=None,
                replicate=None,
                prompt=regression.HOST_SMOKE_PROMPT,
                referenced_image_paths=[],
                reference_ids=[],
                expected_output_path="evaluation/style-regression/host-smoke/outputs/output.png",
                frozen_input_hashes={"files": {}},
                created_at="2020-01-01T00:00:00+00:00",
            )
            regression.write_codex_task(task, path=task_path)
            generated = root / "generated.png"
            generated.write_bytes(b"not a png")
            with self.assertRaisesRegex(regression.ExperimentError, "not a PNG"):
                regression.accept_codex_task_output(task_path, generated, root=root)

            generated.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"old")
            os.utime(generated, (1, 1))
            with self.assertRaisesRegex(regression.ExperimentError, "stale"):
                regression.accept_codex_task_output(task_path, generated, root=root)

    def test_codex_smoke_task_is_reference_free_and_gates_preflight(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = regression.export_codex_smoke_task(root=root)
            task_path = root / regression.CODEX_SMOKE_TASK_PATH
            self.assertEqual(task["prompt"], regression.HOST_SMOKE_PROMPT)
            self.assertEqual(task["referenced_image_paths"], [])
            self.assertEqual(regression._validate_codex_smoke(root), ["Codex-managed smoke result is missing."])
            generated = root / "codex.png"
            generated.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"smoke")

            report = regression.accept_codex_smoke_output(task_path, generated, root=root)

            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["engine"], "Codex-managed")
            self.assertIsNone(report["binding"])
            self.assertEqual(regression._validate_codex_smoke(root), [])
            with self.assertRaisesRegex(regression.ExperimentError, "already exists"):
                regression.accept_codex_smoke_output(task_path, generated, root=root)

    def test_codex_smoke_failure_is_recorded_and_cannot_be_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            regression.export_codex_smoke_task(root=root)
            task_path = root / regression.CODEX_SMOKE_TASK_PATH
            stale = root / "stale.png"
            stale.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"stale")
            os.utime(stale, (1, 1))

            with self.assertRaisesRegex(regression.ExperimentError, "stale"):
                regression.accept_codex_smoke_output(task_path, stale, root=root)

            report = regression._load_json(root / regression.CODEX_SMOKE_REPORT_PATH)
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["execution_mode"], "codex-managed")
            with self.assertRaisesRegex(regression.ExperimentError, "already exists"):
                regression.accept_codex_smoke_output(task_path, stale, root=root)

    def test_codex_pilot_failure_is_manifested_without_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_path = regression._pilot_dir(root) / "tasks" / "case-01-A-r1.json"
            task = regression.build_codex_task(
                task_id="pilot:case-01:A:r1",
                task_kind="pilot",
                case_id="case-01",
                group="A",
                replicate=1,
                prompt="exact pilot prompt",
                referenced_image_paths=[],
                reference_ids=[],
                expected_output_path=regression._relative_path(regression._pilot_output_path("case-01", "A", root=root), root=root),
                frozen_input_hashes={"files": {}},
                batch="4B.3-T",
            )
            regression.write_codex_task(task, path=task_path)
            manifest = regression._pilot_manifest_path(root)
            regression._upsert_manifest(
                {
                    "sample_key": "pilot:case-01:A:r1",
                    "case_id": "case-01",
                    "group": "A",
                    "replicate": 1,
                    "execution_mode": "codex-managed",
                    "task_path": regression._relative_path(task_path, root=root),
                    "task_sha256": task["task_sha256"],
                    "output_path": task["expected_output_path"],
                    "status": "queued",
                },
                path=manifest,
            )

            failed = regression.record_codex_pilot_failure(
                task_path,
                failure_code="generation_error",
                failure_message="built-in generation failed",
                root=root,
            )

            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["failure_code"], "generation_error")
            with self.assertRaisesRegex(regression.ExperimentError, "retries are forbidden"):
                regression.record_codex_pilot_failure(task_path, failure_code="retry", root=root)

    def test_codex_pilot_acceptance_updates_only_its_pilot_manifest_row(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_path = regression._pilot_dir(root) / "tasks" / "case-01-A-r1.json"
            task = regression.build_codex_task(
                task_id="pilot:case-01:A:r1",
                task_kind="pilot",
                case_id="case-01",
                group="A",
                replicate=1,
                prompt="unchanged Pilot prompt",
                referenced_image_paths=[],
                reference_ids=[],
                expected_output_path=regression._relative_path(regression._pilot_output_path("case-01", "A", root=root), root=root),
                frozen_input_hashes={"files": {}},
                batch="4B.3-T",
            )
            regression.write_codex_task(task, path=task_path)
            manifest = regression._pilot_manifest_path(root)
            regression._upsert_manifest(
                {
                    "sample_key": "pilot:case-01:A:r1",
                    "case_id": "case-01",
                    "group": "A",
                    "replicate": 1,
                    "execution_mode": "codex-managed",
                    "task_path": regression._relative_path(task_path, root=root),
                    "task_sha256": task["task_sha256"],
                    "output_path": task["expected_output_path"],
                    "status": "queued",
                },
                path=manifest,
            )
            generated = root / "codex-output.png"
            generated.write_bytes(bytes.fromhex("89504E470D0A1A0A") + b"pilot-output")
            self._write_receipt(task_path, generated, root)

            accepted = regression.accept_codex_pilot_output(task_path, generated, root=root)

            rows = regression._load_jsonl(manifest)
            output_path = root / task["expected_output_path"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "succeeded")
            self.assertEqual(rows[0]["output_sha256"], regression.sha256_file(output_path))
            self.assertEqual(accepted["output_path"], task["expected_output_path"])
            with self.assertRaisesRegex(regression.ExperimentError, "retries are forbidden"):
                regression.accept_codex_pilot_output(task_path, generated, root=root)

    def test_codex_managed_hard_preflight_uses_smoke_and_never_requires_binding(self):
        with (
            mock.patch.object(regression, "_validate_codex_smoke", return_value=[]),
            mock.patch.object(regression, "_validate_frozen_inputs", return_value=[]),
        ):
            preflight = regression.collect_preflight(ROOT, hard=True, codex_managed=True)

        self.assertEqual(preflight["provider_binding"]["execution_mode"], "codex-managed")
        self.assertEqual(preflight["provider_binding"]["engine"], "Codex-managed")
        self.assertEqual(preflight["provider_binding"]["smoke_status"], "PASS")
        self.assertFalse(any("provider-binding" in error for error in preflight["global_blockers"]))

    def test_frozen_case_schema_has_four_cases_and_reports_missing_intake(self):
        cases = yaml.safe_load(
            (ROOT / "evaluation" / "style-regression" / "cases.yaml").read_text(encoding="utf-8")
        )
        missing_intake = copy.deepcopy(cases)
        for case in missing_intake["cases"]:
            case["external_reference"]["sha256"] = None
            case["external_reference"]["style_brief_sha256"] = None
        errors = regression.validate_case_schema(missing_intake)

        self.assertEqual([case["case_id"] for case in cases["cases"]], regression.CASE_IDS)
        self.assertEqual(cases["expected_sample_count"], 36)
        self.assertEqual(sum("external reference SHA-256 is not frozen" in error for error in errors), 4)
        self.assertEqual(sum("Style Brief SHA-256 is not frozen" in error for error in errors), 4)

    def test_scene_composition_uses_the_same_frozen_requirements(self):
        cases = yaml.safe_load(
            (ROOT / "evaluation" / "style-regression" / "cases.yaml").read_text(encoding="utf-8")
        )
        prompts = [regression.compose_scene_prompt(case) for case in cases["cases"]]

        self.assertEqual(len(set(prompts)), 1)
        for requirement in (
            cases["shared_inputs"]["base_scene_prompt"],
            cases["shared_inputs"]["pose_requirement"],
            cases["shared_inputs"]["composition_requirement"],
            cases["shared_inputs"]["camera_requirement"],
            cases["shared_inputs"]["exposure_requirement"],
        ):
            self.assertIn(requirement, prompts[0])

    def test_frozen_batch4b_dry_run_rejects_v11_runtime_and_policy_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            isolated_manifest = Path(temporary) / "manifest.jsonl"
            isolated_manifest.write_text("", encoding="utf-8")
            with (
                mock.patch.object(regression, "_formal_manifest_path", return_value=isolated_manifest),
                mock.patch.object(regression, "_validate_pre_capture_formal_history", return_value=[]),
                mock.patch.object(
                    regression,
                    "_compliant_formal_sample_counts",
                    return_value={group: 0 for group in regression.GENERATED_GROUPS},
                ),
            ):
                preflight = regression.collect_preflight(ROOT)

        self.assertTrue(preflight["errors"])
        self.assertTrue(
            any(
                "frozen input hash mismatch" in error.lower()
                or "production runtime or transport schema changed" in error.lower()
                for error in preflight["errors"]
            )
        )
        self.assertFalse(any("historical h" in error.lower() for error in preflight["errors"]))
        self.assertEqual(preflight["historical_h"]["sample_count"], 0)
        self.assertFalse(preflight["historical_h"]["available"])
        self.assertEqual(preflight["plans"], {})
        self.assertEqual(preflight["formal_sample_counts"], {group: 0 for group in regression.GENERATED_GROUPS})

    def test_frozen_batch4b_hard_preflight_blocks_after_v11_runtime_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            isolated_manifest = Path(temporary) / "manifest.jsonl"
            isolated_manifest.write_text("", encoding="utf-8")
            with (
                mock.patch.object(regression, "_formal_manifest_path", return_value=isolated_manifest),
                mock.patch.object(regression, "_validate_pre_capture_formal_history", return_value=[]),
                mock.patch.object(
                    regression,
                    "_compliant_formal_sample_counts",
                    return_value={group: 0 for group in regression.GENERATED_GROUPS},
                ),
            ):
                preflight = regression.collect_preflight(ROOT, hard=True)

        self.assertEqual(set(preflight["case_statuses"]), set(regression.CASE_IDS))
        self.assertEqual(preflight["global_status"], "BLOCKED")
        self.assertTrue(all(row["status"] == "BLOCKED" for row in preflight["case_statuses"].values()))
        self.assertTrue(
            any(
                "frozen input hash mismatch" in error.lower()
                or "production runtime or transport schema changed" in error.lower()
                for error in preflight["global_blockers"]
            )
        )
        self.assertFalse(any("Host smoke test is missing" in error for error in preflight["global_blockers"]))
        self.assertEqual(preflight["formal_sample_counts"], {group: 0 for group in regression.GENERATED_GROUPS})
        self.assertFalse(any("historical h" in error.lower() for error in preflight["errors"]))
        self.assertEqual(preflight["historical_h"]["sample_count"], 0)

    def test_preflight_blocks_missing_corrected_legacy_control(self):
        with mock.patch.object(
            regression,
            "_control_runtime_metadata",
            side_effect=regression.ExperimentError("Corrected Legacy control runtime metadata is missing."),
        ):
            preflight = regression.collect_preflight(ROOT)

        self.assertEqual(preflight["global_status"], "BLOCKED")
        self.assertTrue(any("Corrected Legacy control runtime metadata is missing" in error for error in preflight["global_blockers"]))

    def test_preflight_blocks_selector_parity_mismatch_and_host_failure(self):
        with mock.patch.object(
            regression,
            "_validate_frozen_inputs",
            return_value=["case-01 A/B/C selector parity failed."],
        ):
            preflight = regression.collect_preflight(ROOT)
        self.assertTrue(any("selector parity failed" in error for error in preflight["case_statuses"]["case-01"]["blockers"]))

        hard_preflight = regression.collect_preflight(
            ROOT, hard=True, provider_binding="missing_host_module:missing_callable"
        )
        self.assertEqual(hard_preflight["global_status"], "BLOCKED")
        self.assertTrue(any("Cannot load existing host provider binding" in error for error in hard_preflight["global_blockers"]))

    def test_selector_parity_helper_rejects_a_b_c_selection_mismatch(self):
        reference = {
            "selection_order": 1,
            "reference_id": "identity-p01",
            "asset_id": "identity-p01",
            "roles": ["identity_reference"],
            "role": "identity_reference",
            "duties": ["identity"],
            "style_priority": None,
            "style_axes": [],
            "path": "assets/identity.png",
            "sha256": "a" * 64,
            "source_scope": "managed_arco",
            "canonical_role": "identity_reference",
            "source_family": "identity",
            "asset_type": "identity",
        }
        baseline = {
            "case_id": "case-01",
            "exposure_profile": "upper_body",
            "variant": "casual-outfit",
            "state": None,
            "scene_snapshot": {"base_scene_prompt": "same scene"},
            "selected_reference_ids": ["identity-p01"],
            "selected_reference_hashes": ["a" * 64],
            "reference_order": ["identity-p01"],
            "style_priority": "primary",
            "style_axes": ["linework"],
            "references": [reference],
        }
        snapshots = {group: copy.deepcopy(baseline) for group in regression.GROUPS}
        snapshots["B"]["selected_reference_hashes"] = ["b" * 64]

        errors = regression._selection_parity_errors(snapshots)

        self.assertTrue(any("A/B selector parity differs for selected_reference_hashes" in error for error in errors))

    def test_frozen_artifact_hash_mismatch_blocks_input_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evaluation_dir = root / "evaluation" / "style-regression"
            evaluation_dir.mkdir(parents=True)
            cases_path = evaluation_dir / "cases.yaml"
            cases_path.write_text("schema_version: 1\ncases: []\n", encoding="utf-8")
            scripts_dir = root / "scripts"
            scripts_dir.mkdir(parents=True)
            (scripts_dir / "reference_runtime.py").write_text("runtime\n", encoding="utf-8")
            (scripts_dir / "arco_real_adapter.py").write_text("adapter\n", encoding="utf-8")
            artifact_path = evaluation_dir / "style-context" / "case-01" / "resolved-style-context.json"
            artifact_path.parent.mkdir(parents=True)
            artifact_path.write_text("mutated", encoding="utf-8")
            freeze = {
                "schema_version": 1,
                "cases_sha256": regression.sha256_file(cases_path),
                "runtime_sha256": regression.sha256_file(scripts_dir / "reference_runtime.py"),
                "adapter_sha256": regression.sha256_file(scripts_dir / "arco_real_adapter.py"),
                "files": {
                    "evaluation/style-regression/style-context/case-01/resolved-style-context.json": "0" * 64
                },
                "selector_snapshots": {},
            }
            (evaluation_dir / "inputs-freeze.json").write_text(
                json.dumps(freeze), encoding="utf-8"
            )

            errors = regression._validate_frozen_inputs(root, {"cases": []}, {})

            self.assertEqual(sum("Frozen artifact hash mismatch" in error for error in errors), 1)

    def test_reference_image_hash_mismatch_blocks_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "evaluation" / "style-regression" / "private-assets" / "case-01.png"
            reference.parent.mkdir(parents=True)
            reference.write_bytes(b"user supplied style reference")
            case = {
                "case_id": "case-01",
                "external_reference": {
                    "reference_id": "external-style-01",
                    "path": "private-assets/case-01.png",
                    "sha256": "0" * 64,
                },
            }

            selected, errors = regression._validate_reference_assets(root, case, [], {})

            self.assertEqual(selected, [])
            self.assertTrue(any("external style image hash does not match" in error for error in errors))

    def test_case_schema_rejects_missing_reference_provenance(self):
        cases = yaml.safe_load((ROOT / "evaluation" / "style-regression" / "cases.yaml").read_text(encoding="utf-8"))
        cases["cases"][0]["external_reference"]["provenance"] = None

        errors = regression.validate_case_schema(cases)

        self.assertTrue(any("case-01 Style Reference provenance is missing" in error for error in errors))

    def test_style_brief_must_match_case_and_reference_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evaluation_dir = root / "evaluation" / "style-regression"
            brief_dir = evaluation_dir / "style-context" / "case-01"
            brief_dir.mkdir(parents=True)
            reference_dir = evaluation_dir / "private-assets" / "style-references"
            reference_dir.mkdir(parents=True)
            reference_path = reference_dir / "case-01.png"
            reference_path.write_bytes(b"style reference")
            reference_hash = regression.sha256_file(reference_path)
            brief_path = brief_dir / "style-brief.yaml"
            brief = {
                "schema_version": 1,
                "created_for_case": "case-01",
                "source_reference_id": "external-style-01",
                "source_reference_hash": reference_hash,
                "style_reference_sha256": reference_hash,
                "style_priority": "primary",
                "created_at": "2026-09-17T00:00:00Z",
                "runtime_revision": "test-fixture",
                "active_axes": ["linework"],
                "axes": {"linework": {"description": "controlled lines", "confidence": "HIGH"}},
            }
            case = {
                "case_id": "case-01",
                "expected_relevant_style_axes": ["linework"],
                "external_reference": {
                    "reference_id": "external-style-01",
                    "sha256": reference_hash,
                    "style_priority": "primary",
                    "style_brief_path": "style-context/case-01/style-brief.yaml",
                },
            }

            def write_brief(document):
                brief_path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
                case["external_reference"]["style_brief_sha256"] = regression.sha256_file(brief_path)

            write_brief(brief)
            self.assertEqual(regression._load_case_style_brief(case, root=root)["created_for_case"], "case-01")

            for field, wrong_value in (
                ("created_for_case", "case-02"),
                ("style_reference_sha256", "0" * 64),
            ):
                invalid = copy.deepcopy(brief)
                invalid[field] = wrong_value
                write_brief(invalid)
                with self.subTest(field=field), self.assertRaises(regression.ExperimentError):
                    regression._load_case_style_brief(case, root=root)

    def test_host_binding_signature_and_smoke_output_are_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            provider_output = root / "provider.png"
            calls = []

            def builtin_image_gen(*, prompt: str, referenced_image_paths: list[str]) -> str:
                calls.append((prompt, list(referenced_image_paths)))
                provider_output.write_bytes(b"reference-free smoke image")
                return str(provider_output)

            with mock.patch.object(
                regression.importlib,
                "import_module",
                return_value=SimpleNamespace(builtin_image_gen=builtin_image_gen),
            ):
                loaded = regression._load_provider_callable("host.binding:builtin_image_gen")

            result = regression.run_host_smoke(
                "host.binding:builtin_image_gen", provider=loaded, root=root
            )
            self.assertEqual(result["status"], "PASS")
            self.assertIs(result["smoke"], True)
            self.assertIs(result["pilot"], False)
            self.assertIs(result["formal"], False)
            started_at = datetime.fromisoformat(result["started_at"])
            completed_at = datetime.fromisoformat(result["completed_at"])
            self.assertLessEqual(started_at, completed_at)
            self.assertEqual(calls, [(regression.HOST_SMOKE_PROMPT, [])])
            self.assertEqual(regression._validate_host_smoke(root, "host.binding:builtin_image_gen"), [])
            self.assertFalse((root / "evaluation" / "style-regression" / "manifest.jsonl").exists())
            self.assertFalse(regression._pilot_manifest_path(root).exists())
            smoke_report_path = root / "evaluation" / "style-regression" / "host-smoke" / "result.json"
            invalid_smoke_report = regression._load_json(smoke_report_path)
            invalid_smoke_report["formal"] = True
            smoke_report_path.write_text(json.dumps(invalid_smoke_report), encoding="utf-8")
            self.assertTrue(
                any(
                    "smoke-only" in error
                    for error in regression._validate_host_smoke(root, "host.binding:builtin_image_gen")
                )
            )

            def invalid_provider(prompt: str, referenced_image_paths: list[str]) -> str:
                return str(provider_output)

            with self.assertRaisesRegex(regression.ExperimentError, "match builtin_image_gen"):
                regression._validate_host_provider(invalid_provider)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def empty_output(*, prompt: str, referenced_image_paths: list[str]) -> str:
                empty = root / "empty.png"
                empty.write_bytes(b"")
                return str(empty)

            failed = regression.run_host_smoke("host.binding:builtin_image_gen", provider=empty_output, root=root)
            self.assertEqual(failed["status"], "FAIL")
            self.assertIn("empty", failed.get("failure_message", ""))

    def test_host_smoke_rejects_an_old_output_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_output = root / "old-output.png"
            old_output.write_bytes(b"old image")
            os.utime(old_output, (1, 1))

            def stale_provider(*, prompt: str, referenced_image_paths: list[str]) -> str:
                return str(old_output)

            result = regression.run_host_smoke(
                "host.binding:builtin_image_gen", provider=stale_provider, root=root
            )

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("newly generated", result.get("failure_message", ""))

    def test_completion_requires_production_control_and_compile_checks(self):
        passing = {
            "tests": {"status": "PASS"},
            "corrected_legacy_tests": {"status": "PASS"},
            "py_compile": {"status": "PASS"},
        }

        self.assertTrue(regression._environment_checks_pass(passing))
        for key in passing:
            with self.subTest(missing_or_failed=key):
                missing = dict(passing)
                missing.pop(key)
                self.assertFalse(regression._environment_checks_pass(missing))
                failed = dict(passing)
                failed[key] = {"status": "FAIL"}
                self.assertFalse(regression._environment_checks_pass(failed))

    def test_selector_diff_records_pre_fix_reference_change_as_confound(self):
        cases = yaml.safe_load(
            (ROOT / "evaluation" / "style-regression" / "cases.yaml").read_text(encoding="utf-8")
        )
        case = cases["cases"][0]
        evidence = regression._load_pre_selector_evidence(root=ROOT)
        after_refs = [
            dict(item)
            for item in evidence["selected_references"]
            if item["reference_id"] != "identity-p01-crop"
        ]
        after_refs.append({
            "reference_id": case["external_reference"]["reference_id"],
            "role": "style_reference",
            "style_priority": "primary",
            "style_axes": case["expected_relevant_style_axes"],
            "sha256": "c" * 64,
        })
        after_ids = [item["reference_id"] for item in after_refs]
        snapshot = {
            "selector_revision": {"commit_sha": "1" * 40},
            "references": after_refs,
            "selected_reference_ids": after_ids,
            "selected_reference_hashes": [item["sha256"] for item in after_refs],
            "reference_order": after_ids,
        }

        difference = regression._selector_diff(case, snapshot, root=ROOT)

        self.assertTrue(difference["changed"])
        self.assertTrue(difference["selector_confound"])
        self.assertIn("identity-p01-crop", difference["before_selected_reference_ids"])
        self.assertNotIn("identity-p01-crop", difference["after_selected_reference_ids"])

    def test_historical_h_is_optional_ingestible_and_excluded_from_formal_groups(self):
        cases = yaml.safe_load(
            (ROOT / "evaluation" / "style-regression" / "cases.yaml").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            summary = regression._historical_group_h_summary(root, cases)
            self.assertFalse(summary["available"])
            self.assertEqual(summary["sample_count"], 0)
            self.assertNotIn("H", regression.GROUPS)
            self.assertEqual(regression.GENERATED_GROUPS, ("A", "B", "C"))

            historical_dir = root / "evaluation" / "style-regression" / "private-assets" / "historical" / "H"
            historical_dir.mkdir(parents=True)
            output = historical_dir / "case-01-H-r1.png"
            output.write_bytes(b"historical context sample")
            manifest = historical_dir / "manifest.jsonl"
            manifest.write_text(
                json.dumps({
                    "case_id": "case-01",
                    "group": "H",
                    "replicate": 1,
                    "provenance_status": "verified",
                    "output_path": output.relative_to(root).as_posix(),
                    "output_sha256": regression.sha256_file(output),
                }) + "\n",
                encoding="utf-8",
            )
            cases["historical_baseline"]["manifest_path"] = (
                "private-assets/historical/H/manifest.jsonl"
            )

            summary = regression._historical_group_h_summary(root, cases)

            self.assertTrue(summary["available"])
            self.assertEqual(summary["sample_count"], 1)
            self.assertEqual(summary["verified_sample_count"], 1)
            self.assertFalse(cases["groups"]["H"]["formal_verdict"])

    def test_corrected_legacy_control_remains_frozen_and_rejects_v11_runtime(self):
        with self.assertRaisesRegex(
            regression.ExperimentError,
            "Production Runtime or transport schema changed",
        ):
            regression._control_runtime_metadata(ROOT)

        metadata = json.loads(
            (
                ROOT
                / "evaluation"
                / "style-regression"
                / "control-runtime"
                / "corrected-legacy.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(metadata["type"], "corrected_legacy")
        self.assertEqual(metadata["purpose"], "evaluation_only")
        self.assertEqual(metadata["branch"], "codex/legacy-selector-fixed")
        self.assertEqual(
            set(metadata["included_changes"]),
            {
                "scripts/reference_runtime.py",
                "scripts/test_reference_runtime.py",
                "scripts/test_arco_real_adapter.py",
            },
        )
        self.assertFalse(metadata["style_transfer_v1"])
        self.assertFalse(metadata["rendering_hygiene"])

    def test_a_b_c_use_selector_parity_and_b_c_only_add_hygiene(self):
        cases = yaml.safe_load(
            (ROOT / "evaluation" / "style-regression" / "cases.yaml").read_text(encoding="utf-8")
        )
        case = copy.deepcopy(cases["cases"][0])
        with tempfile.TemporaryDirectory(prefix="style-regression-test-", dir=regression.EVALUATION_DIR) as temporary:
            reference_path = Path(temporary) / "style.png"
            reference_path.write_bytes(b"test reference bytes; no image generation")
            relative_path = reference_path.relative_to(regression.EVALUATION_DIR).as_posix()
            case["external_reference"]["path"] = relative_path
            case["external_reference"]["sha256"] = regression.sha256_file(reference_path)
            axes = case["expected_relevant_style_axes"]
            descriptions = {
                "linework": "controlled contours with restrained line weight variation",
                "shading": "soft form modeling with clear tonal groups",
                "highlight_language": "small grouped highlights on focal surfaces",
                "detail_density": "moderate detail with a readable focal hierarchy",
            }
            style_brief = {
                "schema_version": 1,
                "created_for_case": case["case_id"],
                "source_reference_id": case["external_reference"]["reference_id"],
                "source_reference_hash": case["external_reference"]["sha256"],
                "style_reference_sha256": case["external_reference"]["sha256"],
                "style_priority": "primary",
                "created_at": "2026-09-17T00:00:00Z",
                "runtime_revision": "test-fixture",
                "active_axes": axes,
                "axes": {
                    axis: {"description": descriptions[axis], "confidence": "HIGH"}
                    for axis in axes
                },
            }
            brief_path = Path(temporary) / "style-brief.yaml"
            brief_path.write_text(yaml.safe_dump(style_brief, allow_unicode=True), encoding="utf-8")
            case["external_reference"]["style_brief_path"] = brief_path.relative_to(regression.EVALUATION_DIR).as_posix()
            case["external_reference"]["style_brief_sha256"] = regression.sha256_file(brief_path)
            assets = yaml.safe_load((ROOT / "character" / "assets.yaml").read_text(encoding="utf-8"))
            generation = yaml.safe_load((ROOT / "runtime" / "generation.yaml").read_text(encoding="utf-8"))
            baseline = yaml.safe_load((ROOT / "character" / "style-baseline.yaml").read_text(encoding="utf-8"))
            policy = yaml.safe_load((ROOT / "runtime" / "style-policy.yaml").read_text(encoding="utf-8"))

            references, errors = regression._validate_reference_assets(
                ROOT, case, assets["assets"], generation
            )
            self.assertEqual(errors, [])
            metadata = json.loads(
                (
                    ROOT
                    / "evaluation"
                    / "style-regression"
                    / "control-runtime"
                    / "corrected-legacy.json"
                ).read_text(encoding="utf-8")
            )
            metadata["runtime_path"] = str(
                Path(metadata["worktree_path"]) / "scripts" / "reference_runtime.py"
            )
            with mock.patch.object(regression, "_control_runtime_metadata", return_value=metadata):
                pair = regression._build_pair(ROOT, case, references, baseline, policy)

            self.assertTrue(pair["selector_parity"])
            self.assertEqual(set(pair["plans"]), {"A", "B", "C"})
            self.assertEqual(
                regression._selection_parity_errors(pair["selector_snapshots"]), []
            )
            self.assertEqual(pair["plans"]["B"]["style_context_hash"], pair["plans"]["C"]["style_context_hash"])
            self.assertIsNone(pair["plans"]["A"]["style_context_hash"])
            scene = regression.compose_scene_prompt(case)
            self.assertTrue(all(scene in pair["plans"][group]["prompt"] for group in regression.GROUPS))
            self.assertEqual(pair["plans"]["B"]["selected_reference_ids"], pair["plans"]["C"]["selected_reference_ids"])
            self.assertEqual(pair["plans"]["B"]["referenced_image_paths"], pair["plans"]["C"]["referenced_image_paths"])
            self.assertEqual(
                pair["plans"]["C"]["prompt"],
                f"{pair['plans']['B']['prompt']}\n\n{pair['hygiene_block']}",
            )

    def test_manifest_upsert_keeps_one_record_per_sample(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "manifest.jsonl"
            first = {
                "sample_key": "case-01:B:r1",
                "case_id": "case-01",
                "group": "B",
                "replicate": 1,
                "status": "started",
            }
            regression._upsert_manifest(first, path=manifest)
            regression._upsert_manifest({**first, "status": "failed"}, path=manifest)

            rows = regression._load_jsonl(manifest)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "failed")

    def test_pilot_is_gated_on_all_case_readiness(self):
        provider = mock.Mock()
        blocked = {
            "global_status": "BLOCKED",
            "errors": ["missing inputs"],
            "case_statuses": {case_id: {"status": "READY"} for case_id in regression.CASE_IDS},
        }

        with self.assertRaisesRegex(regression.ExperimentError, "all four cases"):
            regression.run_pilot(blocked, provider=provider)

        provider.assert_not_called()

    def test_pilot_cli_freezes_final_environment_after_exact_pilot(self):
        events = []
        preflight = {
            "global_status": "READY",
            "errors": [],
            "case_statuses": {case_id: {"status": "READY"} for case_id in regression.CASE_IDS},
        }

        with (
            mock.patch.object(regression, "collect_preflight", side_effect=lambda *args, **kwargs: events.append("preflight") or preflight),
            mock.patch.object(regression, "write_preflight_report", side_effect=lambda *args, **kwargs: events.append("report") or {"status": "READY"}),
            mock.patch.object(regression, "_load_provider_callable", side_effect=lambda binding: events.append("provider") or (lambda **kwargs: None)),
            mock.patch.object(regression, "run_pilot", side_effect=lambda *args, **kwargs: events.append("pilot") or {"succeeded": 3, "failed": 0}),
            mock.patch.object(regression, "freeze_environment", side_effect=lambda **kwargs: events.append("final-freeze") or {"experiment_ready": True}),
            mock.patch.object(regression.sys, "stdout", io.StringIO()),
        ):
            exit_code = regression.main(["--pilot", "--provider-binding", "host.binding:builtin_image_gen"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(events, ["preflight", "report", "provider", "pilot", "final-freeze"])

    def test_pilot_manifest_and_outputs_are_isolated_from_formal_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evaluation_dir = root / "evaluation" / "style-regression"
            context_dir = evaluation_dir / "style-context" / "case-01"
            context_dir.mkdir(parents=True)
            selection_dir = evaluation_dir / "reference-selection"
            selection_dir.mkdir(parents=True)
            (root / "runtime").mkdir()
            scripts_dir = root / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "reference_runtime.py").write_text("runtime test", encoding="utf-8")
            (root / "runtime" / "style-policy.yaml").write_text("policy: test\n", encoding="utf-8")
            style_context = {"mode": "primary", "resolved_axes": {"linework": {"description": "clean"}}}
            (context_dir / "resolved-style-context.json").write_text(
                json.dumps(style_context), encoding="utf-8"
            )
            selection_path = selection_dir / "case-01.json"
            selection_path.write_text(json.dumps({"parity": True}), encoding="utf-8")
            reference_ids = ["identity-p01", "casual-outfit-primary", "external-style-01"]
            references = [
                {"reference_id": reference_ids[0], "role": "identity_reference", "duties": ["identity"], "path": "identity.png", "sha256": "a" * 64, "source_scope": "managed_arco"},
                {"reference_id": reference_ids[1], "role": "outfit_reference", "duties": ["outfit"], "path": "variant.png", "sha256": "b" * 64, "source_scope": "managed_arco"},
                {"reference_id": reference_ids[2], "role": "style_reference", "duties": ["style_reference"], "path": "style.png", "sha256": "c" * 64, "source_scope": "external_how"},
            ]
            scene_fields = {
                "base_scene_prompt": "Scene",
                "pose_requirement": "Pose",
                "composition_requirement": "Composition",
                "camera_requirement": "Camera",
                "exposure_requirement": "Exposure",
            }
            scene = "\n".join(scene_fields.values())
            prompt_b = f"{scene}\nstyle treatment"
            hygiene_block = "Rendering Hygiene block"
            shared_paths = ["identity.png", "variant.png", "style.png"]
            snapshot = {
                "case_id": "case-01",
                "exposure_profile": "upper_body",
                "variant": "casual-outfit",
                "state": None,
                "scene_snapshot": scene_fields,
                "selected_reference_ids": reference_ids,
                "selected_reference_hashes": ["a" * 64, "b" * 64, "c" * 64],
                "reference_order": reference_ids,
                "style_priority": "primary",
                "style_axes": ["linework"],
                "references": [
                    {
                        "selection_order": index,
                        "reference_id": reference["reference_id"],
                        "asset_id": reference["reference_id"],
                        "roles": [reference["role"]],
                        "role": reference["role"],
                        "duties": reference["duties"],
                        "style_priority": "primary" if reference["role"] == "style_reference" else None,
                        "style_axes": ["linework"] if reference["role"] == "style_reference" else [],
                        "path": reference["path"],
                        "sha256": reference["sha256"],
                        "source_scope": reference["source_scope"],
                        "canonical_role": None,
                        "source_family": None,
                        "asset_type": None,
                    }
                    for index, reference in enumerate(references, start=1)
                ],
            }
            pair = {
                "references": references,
                "references_by_group": {group: references for group in regression.GROUPS},
                "style_context": style_context,
                "hygiene_block": hygiene_block,
                "selector_parity": True,
                "selector_snapshots": {group: copy.deepcopy(snapshot) for group in regression.GROUPS},
                "plans": {
                    "A": {
                        "prompt": f"{scene}\nlegacy control",
                        "style_context_hash": None,
                        "selected_reference_ids": reference_ids,
                        "referenced_image_paths": shared_paths,
                    },
                    "B": {
                        "prompt": prompt_b,
                        "style_context_hash": regression.sha256_json(style_context),
                        "selected_reference_ids": reference_ids,
                        "referenced_image_paths": shared_paths,
                    },
                    "C": {
                        "prompt": f"{prompt_b}\n\n{hygiene_block}",
                        "style_context_hash": regression.sha256_json(style_context),
                        "selected_reference_ids": reference_ids,
                        "referenced_image_paths": shared_paths,
                    },
                },
            }
            plans = {case_id: pair for case_id in regression.CASE_IDS}
            preflight = {
                "global_status": "READY",
                "errors": [],
                "case_statuses": {case_id: {"status": "READY"} for case_id in regression.CASE_IDS},
                "provider_binding": {"available": True, "smoke_status": "PASS"},
                "corrected_legacy": {
                    "selector_patch_revision": "2" * 40,
                    "runtime_sha256": "d" * 64,
                },
                "cases_document": {
                    "cases": [
                        {
                            "case_id": case_id,
                            "identity_variant": "casual-outfit",
                            "state": None,
                            "exposure_profile": "upper_body",
                            "external_reference": {
                                "reference_id": "external-style-01",
                                "role": "style_reference",
                                "duties": ["style_reference"],
                                "style_priority": "primary",
                                "provenance": "test fixture",
                                "sha256": "c" * 64,
                            },
                            "expected_relevant_style_axes": ["linework"],
                            **scene_fields,
                        }
                        for case_id in regression.CASE_IDS
                    ]
                },
                "plans": plans,
            }

            invalid_preflights = [
                (
                    "selector",
                    lambda value: value["plans"]["case-01"]["selector_snapshots"]["C"]["selected_reference_hashes"].__setitem__(0, "f" * 64),
                    "Pilot selector parity failed",
                ),
                (
                    "scene",
                    lambda value: value["cases_document"]["cases"][0].update({"base_scene_prompt": "different scene"}),
                    "scene parity failed",
                ),
                (
                    "context",
                    lambda value: value["plans"]["case-01"]["plans"]["C"].update({"style_context_hash": "e" * 64}),
                    "Style Context hashes differ",
                ),
                (
                    "prompt_delta",
                    lambda value: value["plans"]["case-01"]["plans"]["C"].update({"prompt": "unauthorized delta"}),
                    "Hygiene must be the sole prompt difference",
                ),
            ]
            for label, mutate, expected_error in invalid_preflights:
                with self.subTest(parity_failure=label):
                    invalid = copy.deepcopy(preflight)
                    mutate(invalid)
                    provider = mock.Mock()
                    with (
                        mock.patch.object(regression, "_validate_frozen_inputs", return_value=[]),
                        self.assertRaisesRegex(regression.ExperimentError, expected_error),
                    ):
                        regression.run_pilot(invalid, provider=provider, root=root)
                    provider.assert_not_called()

            class AdapterStub:
                def __init__(self, provider):
                    self.calls = 0

                def generate(self, **kwargs):
                    self.calls += 1
                    output = root / f"provider-output-{self.calls}.png"
                    output.write_bytes(b"pilot image")
                    return output

            with (
                mock.patch.object(regression, "_validate_frozen_inputs", return_value=[]),
                mock.patch.object(regression, "_git_output", return_value="1" * 40),
                mock.patch.object(regression, "ArcoRealAdapter", AdapterStub),
            ):
                counts = regression.run_pilot(preflight, provider=lambda **kwargs: None, root=root)

            pilot_manifest = regression._pilot_manifest_path(root)
            pilot_rows = regression._load_jsonl(pilot_manifest)
            formal_manifest = evaluation_dir / "manifest.jsonl"

            self.assertEqual(counts, {"succeeded": 3, "failed": 0})
            self.assertEqual({row["group"] for row in pilot_rows}, {"A", "B", "C"})
            self.assertTrue(
                all(
                    row["pilot"] is True
                    and row["formal"] is False
                    and row["include_in_formal_analysis"] is False
                    and row["selector_parity"] is True
                    and row["scene_parity"] is True
                    and row["bc_context_parity"] is True
                    and row["bc_prompt_hygiene_only"] is True
                    and row["provider_payload_keys"] == ["prompt", "referenced_image_paths"]
                    for row in pilot_rows
                )
            )
            self.assertTrue(all(row["output_sha256"] for row in pilot_rows))
            self.assertTrue(all(row["compiled_prompt_sha256"] and row["reference_snapshot_sha256"] for row in pilot_rows))
            self.assertTrue(all((root / row["output_path"]).is_file() for row in pilot_rows))
            self.assertIsNone(next(row for row in pilot_rows if row["group"] == "A")["resolved_style_context_sha256"])
            self.assertEqual(
                next(row for row in pilot_rows if row["group"] == "B")["resolved_style_context_sha256"],
                next(row for row in pilot_rows if row["group"] == "C")["resolved_style_context_sha256"],
            )
            self.assertEqual(regression._load_jsonl(formal_manifest), [])
            self.assertFalse((evaluation_dir / "outputs").exists())
            self.assertEqual(len(pilot_rows), 3)
            self.assertEqual(regression._pilot_artifact_errors(root), [])

            pilot_output = root / pilot_rows[0]["output_path"]
            pilot_output.write_bytes(b"tampered pilot image")
            self.assertTrue(
                any("output hash" in error for error in regression._pilot_artifact_errors(root))
            )

    def test_blind_review_copies_hide_group_and_map_all_36_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evaluation_dir = root / "evaluation" / "style-regression"
            outputs_dir = evaluation_dir / "outputs"
            outputs_dir.mkdir(parents=True)
            shutil_template = ROOT / "evaluation" / "style-regression" / "evaluation-template.md"
            evaluation_dir.mkdir(parents=True, exist_ok=True)
            (evaluation_dir / "evaluation-template.md").write_bytes(shutil_template.read_bytes())
            records = []
            for case_id in regression.CASE_IDS:
                for group in regression.GROUPS:
                    for replicate in range(1, regression.EXPECTED_REPLICATES + 1):
                        relative = f"evaluation/style-regression/outputs/{case_id}-{group}-r{replicate}.png"
                        image = root / relative
                        image.write_bytes(f"private test image {case_id}-{group}-{replicate}".encode())
                        records.append(
                            {
                                "sample_key": regression._sample_key(case_id, group, replicate),
                                "case_id": case_id,
                                "group": group,
                                "replicate": replicate,
                                "status": "succeeded",
                                "output_path": relative,
                                "output_sha256": regression.sha256_file(image),
                            }
                        )
            regression._write_manifest_atomic(evaluation_dir / "manifest.jsonl", records)

            count = regression.prepare_blind_review(root)
            blind_map = json.loads((evaluation_dir / "blind-map.private.json").read_text(encoding="utf-8"))
            form_paths = sorted((evaluation_dir / "evaluations").glob("*.md"))

            self.assertEqual(count, 36)
            self.assertEqual(len(blind_map["samples"]), 36)
            self.assertEqual({item["group"] for item in blind_map["samples"].values()}, set(regression.GROUPS))
            self.assertEqual(len(form_paths), 36)
            self.assertTrue(all("group:" not in path.read_text(encoding="utf-8").lower() for path in form_paths))
            self.assertEqual(len(list((evaluation_dir / "private-assets" / "blind-review").glob("*.png"))), 36)


if __name__ == "__main__":
    unittest.main(verbosity=2)
