import sys
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from legacy_generation_fixture import legacy_generation_root

from arco_production import run_production_generation
from revision_reference import run_production_revision
from reference_runtime import ReferenceRuntimeError, validate_reference_contract
from revision_intent import GeneratedOutputRole, RevisionPlan, RevisionType, SourceStrategy, resolve_revision_intent


class FakeProvider:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def __call__(self, *, prompt, referenced_image_paths):
        self.calls.append(list(referenced_image_paths))
        self.output.write_bytes(b"\x89PNG\r\n\x1a\nrevision-plan")
        return self.output


class RevisionReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.provider = FakeProvider(Path(self.temp.name) / "out.png")
        self.previous_path = ROOT / "archive/实验/evaluation/revision-regression/baseline/outputs/case-02/background-revision-attempt-1.png"
        self.previous = {
            "reference_id": "previous-output", "source_scope": "request_scoped_arco",
            "role": "identity_reference", "path": str(self.previous_path),
            "output_id": str(self.previous_path.resolve()), "generation_depth": 0,
            "parent_output": None, "source_generation_id": str(self.previous_path.resolve()),
            "reset_triggered_from_output": None,
            "authority": "user_request", "persistent": False, "calibrating": False,
            "inherit": ["identity", "face", "hair", "eyes"], "do_not_inherit": [],
            "coverage": {"visible_fields": ["identity", "face", "hair", "eyes", "body.upper"]},
            "provenance": {"transport": "previous_output"},
        }
        self.request = {
            "base_prompt": "Background brighter; face unchanged.",
            "exposure_profile": "upper_body",
            "request_scoped_arco_references": [self.previous],
        }

    def plan(self, *, identity=False, outfit=False, external=False, role=GeneratedOutputRole.COMPOSITION_ANCHOR):
        return RevisionPlan(RevisionType.CHARACTER_DETAIL, SourceStrategy.REANCHOR_AND_REGENERATE,
                            role, identity, outfit, external)

    def run_revision(self, plan, request=None, selected_variant_id=None):
        return run_production_revision(request or self.request, revision_plan=plan,
                                       previous_output=self.previous, selected_variant_id=selected_variant_id,
                                       builtin_image_gen=self.provider, root=legacy_generation_root())

    def test_identity_reanchor_follows_plan_not_prompt(self):
        result = self.run_revision(self.plan(identity=True))
        managed = [r for r in result.selected_references if r["source_scope"] == "managed_arco"]
        previous = [r for r in result.selected_references if r.get("generated_output_role")]
        self.assertEqual([r["role"] for r in managed], ["identity_reference"])
        self.assertEqual(len(previous), 1)
        self.assertEqual(previous[0]["generated_output_role"], "composition_anchor")
        self.assertNotIn("identity", previous[0]["inherit"])
        self.assertEqual(previous[0]["coverage"], {})
        self.assertEqual(result.invocation_plan["selected_reference_ids"][0], "previous-output")

    def test_face_eye_hair_and_anatomy_plan_requirements(self):
        for prompt in ("修正脸", "修正眼睛", "修正头发", "修正身体比例"):
            with self.subTest(prompt=prompt):
                request = dict(self.request, base_prompt=prompt)
                plan = self.plan(identity=True)
                result = self.run_revision(plan, request)
                self.assertTrue(any(r["role"] == "identity_reference" and r["source_scope"] == "managed_arco"
                                    for r in result.selected_references))

    def test_outfit_reanchor(self):
        request = dict(self.request, variant_id="casual-outfit")
        result = self.run_revision(self.plan(outfit=True), request)
        self.assertEqual({r["role"] for r in result.selected_references if r["source_scope"] == "managed_arco"},
                         {"identity_reference", "outfit_reference"})

    def test_identity_outfit_and_external_fit_four(self):
        request = dict(self.request, variant_id="casual-outfit", external_references=[{
            "reference_id": "external-how", "source_scope": "external_how",
            "role": "pose_reference", "path": str(ROOT / "archive/实验/evaluation/revision-regression/private-assets/case-02-external-how.jpg"),
            "authority": "user_request_external", "inherit": ["pose"],
            "do_not_inherit": ["identity", "outfit", "variant"],
        }])
        result = self.run_revision(self.plan(identity=True, outfit=True, external=True), request)
        self.assertEqual(len(result.selected_references), 4)
        self.assertEqual(len(result.invocation_plan["referenced_image_paths"]), 4)
        self.assertEqual(len(set(result.invocation_plan["referenced_image_paths"])), 4)
        self.assertEqual(len(self.provider.calls), 1)

    def test_missing_identity_fails_closed(self):
        request = dict(self.request, arco_references=[{"asset_id": "casual-outfit-primary", "role": "outfit_reference"}], variant_id="casual-outfit")
        with self.assertRaises(ReferenceRuntimeError) as error:
            self.run_revision(self.plan(identity=True), request)
        self.assertEqual(error.exception.code, "ORIGINAL_IDENTITY_REQUIRED")
        self.assertFalse(self.provider.calls)

    def test_missing_outfit_fails_closed(self):
        with self.assertRaises(ReferenceRuntimeError) as error:
            self.run_revision(self.plan(outfit=True))
        self.assertEqual(error.exception.code, "VARIANT_SELECTION_REQUIRED")
        self.assertFalse(self.provider.calls)

    def test_missing_how_fails_closed(self):
        with self.assertRaises(ReferenceRuntimeError) as error:
            self.run_revision(self.plan(identity=True, external=True))
        self.assertEqual(error.exception.code, "EXTERNAL_REFERENCE_REQUIRED")

    def test_excluded_previous_not_reinserted(self):
        result = self.run_revision(self.plan(identity=True, role=GeneratedOutputRole.EXCLUDED))
        self.assertNotIn("previous-output", result.invocation_plan["selected_reference_ids"])

    def test_source_reset_requires_source_context(self):
        plan = RevisionPlan(RevisionType.ARTIFACT_REPAIR, SourceStrategy.SOURCE_RESET,
                            GeneratedOutputRole.EXCLUDED, True, False, False)
        with self.assertRaises(ReferenceRuntimeError) as error:
            self.run_revision(plan)
        self.assertEqual(error.exception.code, "SOURCE_CONTEXT_REQUIRED")
        self.assertFalse(self.provider.calls)

    def test_contract_rejects_generated_output_who(self):
        bad = dict(self.previous, role="composition_reference", authority="previous_output_continuity",
                   generated_output_role="composition_anchor",
                   do_not_inherit=["identity", "hair", "eyes", "face", "body_proportions", "outfit", "variant"])
        with self.assertRaises(ReferenceRuntimeError) as error:
            validate_reference_contract(bad)
        self.assertEqual(error.exception.code, "GENERATED_OUTPUT_AUTHORITY")

    def test_contract_rejects_generated_output_variant(self):
        bad = dict(self.previous, role="composition_reference", authority="previous_output_continuity",
                   generated_output_role="primary_edit_source", inherit=["outfit"],
                   do_not_inherit=["identity", "hair", "eyes", "face", "body_proportions", "variant"])
        with self.assertRaises(ReferenceRuntimeError) as error:
            validate_reference_contract(bad)
        self.assertEqual(error.exception.code, "GENERATED_OUTPUT_AUTHORITY")

    def test_primary_edit_role_kept_without_character_authority(self):
        result = self.run_revision(self.plan(identity=True, role=GeneratedOutputRole.PRIMARY_EDIT_SOURCE))
        previous = next(r for r in result.selected_references if r.get("generated_output_role"))
        self.assertEqual(previous["generated_output_role"], "primary_edit_source")
        self.assertFalse(set(previous["inherit"]) & {"identity", "outfit", "variant"})

    def test_mixed_character_plan_keeps_identity(self):
        plan = RevisionPlan(RevisionType.MIXED, SourceStrategy.REANCHOR_AND_REGENERATE,
                            GeneratedOutputRole.COMPOSITION_ANCHOR, True, False, False)
        result = self.run_revision(plan)
        self.assertTrue(any(r["source_scope"] == "managed_arco" and r["role"] == "identity_reference"
                            for r in result.selected_references))

    def test_request_scoped_character_authority_conflict_fails(self):
        unrelated = dict(self.previous, reference_id="unrelated", provenance={})
        request = dict(self.request, request_scoped_arco_references=[self.previous, unrelated])
        with self.assertRaises(ReferenceRuntimeError) as error:
            self.run_revision(self.plan(identity=True), request)
        self.assertEqual(error.exception.code, "REVISION_AUTHORITY_CONFLICT")

    def test_scene_only_parity(self):
        plan = RevisionPlan(RevisionType.SCENE_ONLY, SourceStrategy.EDIT_CURRENT,
                            GeneratedOutputRole.PRIMARY_EDIT_SOURCE, False, False, False)
        with self.assertRaises(ReferenceRuntimeError) as error:
            run_production_generation(self.request, builtin_image_gen=self.provider, root=legacy_generation_root())
        self.assertEqual(error.exception.code, "REVISION_ENTRY_REQUIRED")
        revised = self.run_revision(plan)
        self.assertEqual(revised.invocation_plan["referenced_image_paths"], [str(self.previous_path)])
        self.assertIn("[Revision Stability — DIRECT_EDIT]", revised.prompt)
        with_variant_context = self.run_revision(plan, selected_variant_id="casual-outfit")
        self.assertEqual(revised.invocation_plan, with_variant_context.invocation_plan)

    def test_scene_only_with_required_how_keeps_legacy_route(self):
        external = {
            "reference_id": "scene-how", "source_scope": "external_how", "role": "pose_reference",
            "path": str(ROOT / "archive/实验/evaluation/revision-regression/private-assets/case-02-external-how.jpg"),
            "authority": "user_request_external", "inherit": ["pose"],
            "do_not_inherit": ["identity", "outfit", "variant"],
        }
        request = dict(self.request, external_references=[external])
        plan = RevisionPlan(RevisionType.SCENE_ONLY, SourceStrategy.EDIT_CURRENT,
                            GeneratedOutputRole.PRIMARY_EDIT_SOURCE, False, False, True)
        with self.assertRaises(ReferenceRuntimeError) as error:
            run_production_generation(request, builtin_image_gen=self.provider, root=legacy_generation_root())
        self.assertEqual(error.exception.code, "REVISION_ENTRY_REQUIRED")
        revised = self.run_revision(plan, request)
        self.assertEqual(revised.invocation_plan["referenced_image_paths"], [str(self.previous_path), external["path"]])
        self.assertIn("[Revision Stability — DIRECT_EDIT]", revised.prompt)

    def test_scene_only_missing_required_how_fails(self):
        plan = RevisionPlan(RevisionType.SCENE_ONLY, SourceStrategy.EDIT_CURRENT,
                            GeneratedOutputRole.PRIMARY_EDIT_SOURCE, False, False, True)
        with self.assertRaises(ReferenceRuntimeError) as error:
            self.run_revision(plan)
        self.assertEqual(error.exception.code, "EXTERNAL_REFERENCE_REQUIRED")

    def test_first_generation_unchanged(self):
        request = {"base_prompt": "Arco stands.", "exposure_profile": "upper_body"}
        result = run_production_generation(request, builtin_image_gen=self.provider, root=legacy_generation_root())
        self.assertEqual([r["role"] for r in result.selected_references], ["identity_reference"])

    def test_conflicting_duplicate_inputs_fail_without_provider_call(self):
        extra = {
            "reference_id": "second-how", "source_scope": "external_how",
            "role": "lighting_reference", "path": str(self.previous_path),
            "authority": "user_request_external", "inherit": ["lighting"],
            "do_not_inherit": ["identity", "outfit", "variant"],
        }
        request = dict(self.request, variant_id="casual-outfit", external_references=[extra, dict(extra, reference_id="third-how")])
        with self.assertRaises(ReferenceRuntimeError) as error:
            self.run_revision(self.plan(identity=True, outfit=True, external=True), request)
        self.assertEqual(error.exception.code, "REFERENCE_DUPLICATE_CONFLICT")
        self.assertFalse(self.provider.calls)

    def test_case02_structural_regression(self):
        receipt_path = ROOT / "archive/实验/evaluation/revision-regression/baseline/receipts/case-02/character-detail-revision-attempt-1.json"
        request_path = ROOT / "archive/实验/evaluation/revision-regression/input-bundle/requests/case-02-character-detail-revision.json"
        legacy = json.loads(receipt_path.read_text(encoding="utf-8"))
        request = json.loads(request_path.read_text(encoding="utf-8"))
        first_generation = json.loads((ROOT / "archive/实验/evaluation/revision-regression/input-bundle/requests/case-02-first-generation.json").read_text(encoding="utf-8"))
        plan = resolve_revision_intent(request["base_prompt"])
        self.assertTrue(plan.requires_original_identity)
        self.assertTrue(plan.requires_original_outfit)
        request["request_scoped_arco_references"][0]["path"] = str(self.previous_path)
        request["arco_references"] = []
        result = self.run_revision(plan, request, selected_variant_id=first_generation["variant_id"])
        self.assertEqual(len(legacy["resolved_references"]), 1)
        self.assertEqual(legacy["resolved_references"][0]["role"], "identity_reference")
        self.assertEqual(legacy["resolved_references"][0]["source_scope"], "request_scoped_arco")
        self.assertTrue(any(r["role"] == "identity_reference" and r["source_scope"] == "managed_arco"
                            for r in result.selected_references))
        self.assertTrue(any(r["role"] == "outfit_reference" and r["source_scope"] == "managed_arco"
                            for r in result.selected_references))
        self.assertTrue(any(r.get("generated_output_role") == "composition_anchor"
                            for r in result.selected_references))


if __name__ == "__main__":
    unittest.main()
