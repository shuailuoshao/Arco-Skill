import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from legacy_generation_fixture import legacy_generation_root

from arco_production import ProductionGenerationError, run_production_generation
from revision_intent import GeneratedOutputRole, RevisionPlan, RevisionType, SourceStrategy
from revision_lineage import ExecutionStrategy, GenerationLineage, choose_execution_strategy, direct_edit_lineage
from revision_reference import run_production_revision
from reference_runtime import ReferenceRuntimeError


class Provider:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.calls = []

    def __call__(self, *, prompt, referenced_image_paths):
        self.calls.append((prompt, list(referenced_image_paths)))
        output = self.directory / f"generated-{len(self.calls)}.png"
        output.write_bytes(b"\x89PNG\r\n\x1a\nphase3")
        return output


def previous_from_result(result):
    return {
        "reference_id": f"output-{result.output_path.stem}",
        "path": str(result.output_path),
        "source_scope": "request_scoped_arco",
        "role": "identity_reference",
        "authority": "user_request", "persistent": False, "calibrating": False,
        "inherit": ["identity", "face", "hair", "eyes", "outfit", "pose", "composition"],
        "do_not_inherit": [], "coverage": {"visible_fields": ["identity", "face", "hair", "eyes", "body.upper"]},
        "provenance": {"transport": "previous_output"},
        **{key: result.as_dict()[key] for key in (
            "output_id", "generation_depth", "parent_output", "source_generation_id", "reset_triggered_from_output", "revision_context", "visual_review_status"
        )},
    }


class Phase3LineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.provider = Provider(self.temp.name)
        self.source = {"base_prompt": "Arco holds a book on a white background.",
                       "exposure_profile": "upper_body", "variant_id": "casual-outfit"}
        self.scene = {"base_prompt": "Make the background brighter.", "exposure_profile": "upper_body"}
        self.scene_plan = RevisionPlan(RevisionType.SCENE_ONLY, SourceStrategy.EDIT_CURRENT,
                                       GeneratedOutputRole.PRIMARY_EDIT_SOURCE, False, False, False)
        self.artifact_plan = RevisionPlan(RevisionType.ARTIFACT_REPAIR, SourceStrategy.SOURCE_RESET,
                                          GeneratedOutputRole.EXCLUDED, False, False, False)

    def first(self):
        return run_production_generation(self.source, builtin_image_gen=self.provider, root=legacy_generation_root())

    def revision(self, request, plan, previous, *, source=True):
        request = dict(request, request_scoped_arco_references=[previous])
        return run_production_revision(request, revision_plan=plan, previous_output=previous,
                                       source_request=self.source if source else None,
                                       builtin_image_gen=self.provider, root=legacy_generation_root())

    def test_first_generation_root_and_serialization(self):
        result = self.first()
        self.assertNotIn("[Revision Stability — DIRECT_EDIT]", result.prompt)
        self.assertEqual(result.generation_depth, 0)
        self.assertIsNone(result.parent_output)
        self.assertEqual(result.source_generation_id, result.output_id)
        self.assertIsNone(result.reset_triggered_from_output)
        self.assertEqual(result.as_dict()["output_id"], str(result.output_path.resolve()))

    def test_decision_table_and_artifact_fuse(self):
        root = self.first()
        parent0 = GenerationLineage.from_output(previous_from_result(root))
        parent1 = GenerationLineage.from_output(previous_from_result(
            self.revision(self.scene, self.scene_plan, previous_from_result(root))))
        for parent, plan, expected in (
            (parent0, self.scene_plan, ExecutionStrategy.DIRECT_EDIT),
            (parent1, self.scene_plan, ExecutionStrategy.SOURCE_RESET),
            (parent0, self.artifact_plan, ExecutionStrategy.SOURCE_RESET),
            (parent1, self.artifact_plan, ExecutionStrategy.SOURCE_RESET),
        ):
            with self.subTest(depth=parent.generation_depth, plan=plan.revision_type):
                self.assertIs(choose_execution_strategy(parent, plan), expected)

    def test_first_edit_parity_and_second_edit_reset(self):
        root = self.first()
        first_edit = self.revision(self.scene, self.scene_plan, previous_from_result(root))
        self.assertIn("[Revision Stability — DIRECT_EDIT]", first_edit.prompt)
        self.assertEqual(first_edit.generation_depth, 1)
        self.assertEqual(first_edit.parent_output, root.output_id)
        self.assertEqual(first_edit.source_generation_id, root.output_id)
        self.assertEqual(self.provider.calls[1][1], [str(root.output_path.resolve())])
        reset = self.revision(self.scene, self.scene_plan, previous_from_result(first_edit))
        self.assertEqual(reset.generation_depth, 0)
        self.assertIsNone(reset.parent_output)
        self.assertEqual(reset.source_generation_id, reset.output_id)
        self.assertEqual(reset.reset_triggered_from_output, first_edit.output_id)
        self.assertIn("Original source request:", reset.prompt)
        self.assertIn("Requested revision:", reset.prompt)
        self.assertNotIn("[Revision Stability — DIRECT_EDIT]", reset.prompt)
        self.assertNotIn("preserve every unchanged pixel", reset.prompt.lower())
        self.assertTrue(any(r["role"] == "identity_reference" and r["source_scope"] == "managed_arco"
                            for r in reset.selected_references))
        previous = [r for r in reset.selected_references if r.get("generated_output_role")]
        self.assertEqual(len(previous), 1)
        self.assertEqual(previous[0]["generated_output_role"], "composition_anchor")
        self.assertEqual(previous[0]["coverage"], {})
        self.assertFalse({"identity", "outfit", "variant"} & set(previous[0]["inherit"]))
        self.assertNotEqual(reset.invocation_plan["selected_reference_ids"][0], previous[0]["reference_id"])

    def test_artifact_reset_at_both_depths_excludes_previous(self):
        root = self.first()
        edit = self.revision(self.scene, self.scene_plan, previous_from_result(root))
        for parent in (root, edit):
            with self.subTest(depth=parent.generation_depth):
                reset = self.revision(self.scene, self.artifact_plan, previous_from_result(parent))
                self.assertEqual(reset.generation_depth, 0)
                self.assertEqual(reset.reset_triggered_from_output, parent.output_id)
                self.assertFalse(any(r.get("generated_output_role") for r in reset.selected_references))

    def test_source_strategy_triggers_reset_independently(self):
        root = self.first()
        plan = RevisionPlan(RevisionType.SCENE_ONLY, SourceStrategy.SOURCE_RESET,
                            GeneratedOutputRole.COMPOSITION_ANCHOR, False, False, False)
        reset = self.revision(self.scene, plan, previous_from_result(root))
        self.assertEqual(reset.generation_depth, 0)
        self.assertEqual(reset.reset_triggered_from_output, root.output_id)

    def test_illegal_direct_depth_two_rejected(self):
        root = self.first()
        edit = self.revision(self.scene, self.scene_plan, previous_from_result(root))
        before = len(self.provider.calls)
        with self.assertRaises(ProductionGenerationError) as caught:
            direct_edit_lineage(GenerationLineage.from_output(previous_from_result(edit)))
        self.assertEqual(caught.exception.code, "EDIT_DEPTH_EXCEEDED")
        self.assertEqual(len(self.provider.calls), before)

    def test_missing_lineage_and_source_fail_before_provider(self):
        root = self.first()
        previous = previous_from_result(root)
        del previous["generation_depth"]
        with self.assertRaises(ProductionGenerationError) as caught:
            self.revision(self.scene, self.scene_plan, previous)
        self.assertEqual(caught.exception.code, "LINEAGE_REQUIRED")
        with self.assertRaises(ProductionGenerationError) as caught:
            self.revision(self.scene, self.artifact_plan, {k: v for k, v in previous_from_result(root).items() if k != "revision_context"}, source=False)
        self.assertEqual(caught.exception.code, "SOURCE_CONTEXT_REQUIRED")
        self.assertEqual(len(self.provider.calls), 1)

    def test_malformed_lineage_fails_before_provider(self):
        root = self.first()
        previous = previous_from_result(root)
        previous["generation_depth"] = 2
        with self.assertRaises(ProductionGenerationError) as caught:
            self.revision(self.scene, self.scene_plan, previous)
        self.assertEqual(caught.exception.code, "LINEAGE_INVALID")
        self.assertEqual(len(self.provider.calls), 1)

    def test_reset_identity_outfit_and_how(self):
        root = self.first()
        source = dict(self.source, external_references=[{
            "reference_id": "case01-how", "source_scope": "external_how", "role": "pose_reference",
            "path": str(ROOT / "archive/实验/evaluation/revision-regression/private-assets/case-01-external-how.jpg"),
            "authority": "user_request_external", "inherit": ["pose"],
            "do_not_inherit": ["identity", "outfit", "variant"],
        }])
        result = run_production_revision(self.scene, revision_plan=self.artifact_plan,
            previous_output=previous_from_result(root), source_request=source,
            builtin_image_gen=self.provider, root=legacy_generation_root())
        roles = {(r["source_scope"], r["role"]) for r in result.selected_references}
        self.assertIn(("managed_arco", "identity_reference"), roles)
        self.assertIn(("managed_arco", "outfit_reference"), roles)
        self.assertIn(("external_how", "pose_reference"), roles)
        self.assertNotIn(str(root.output_path.resolve()), result.invocation_plan["referenced_image_paths"])

    def test_reset_uses_canonical_variant_when_revision_omits_it(self):
        root = self.first()
        plan = RevisionPlan(RevisionType.CHARACTER_DETAIL, SourceStrategy.SOURCE_RESET,
                            GeneratedOutputRole.EXCLUDED, True, True, False)
        reset = self.revision(self.scene, plan, previous_from_result(root))
        self.assertTrue(any(r["role"] == "outfit_reference" and r["variant_id"] == "casual-outfit"
                            for r in reset.selected_references))

    def test_reset_missing_formal_identity_fails_closed(self):
        root = self.first()
        source = dict(self.source, arco_references=[{"asset_id": "casual-outfit-primary", "role": "outfit_reference"}])
        before = len(self.provider.calls)
        with self.assertRaises(ProductionGenerationError) as caught:
            run_production_revision(self.scene, revision_plan=self.artifact_plan,
                previous_output=previous_from_result(root), source_request=source,
                builtin_image_gen=self.provider, root=legacy_generation_root())
        self.assertEqual(caught.exception.code, "ORIGINAL_IDENTITY_REQUIRED")
        self.assertEqual(len(self.provider.calls), before)

    def test_reset_missing_formal_outfit_fails_closed(self):
        root = self.first()
        source = dict(self.source, arco_references=[{"asset_id": "identity-p01", "role": "identity_reference"}])
        before = len(self.provider.calls)
        with self.assertRaises(ReferenceRuntimeError) as caught:
            run_production_revision(self.scene, revision_plan=self.artifact_plan,
                previous_output=previous_from_result(root), source_request=source,
                builtin_image_gen=self.provider, root=legacy_generation_root())
        self.assertEqual(caught.exception.code, "VARIANT_REFERENCE_NOT_FOUND")
        self.assertEqual(len(self.provider.calls), before)

    def test_reset_missing_required_how_fails_closed(self):
        root = self.first()
        plan = RevisionPlan(RevisionType.SCENE_ONLY, SourceStrategy.SOURCE_RESET,
                            GeneratedOutputRole.EXCLUDED, False, False, True)
        before = len(self.provider.calls)
        with self.assertRaises(ProductionGenerationError) as caught:
            self.revision(self.scene, plan, previous_from_result(root))
        self.assertEqual(caught.exception.code, "EXTERNAL_REFERENCE_REQUIRED")
        self.assertEqual(len(self.provider.calls), before)

    def test_case01_frozen_chain_is_structural_only(self):
        base = ROOT / "archive/实验/evaluation/revision-regression/input-bundle/requests"
        requests = [json.loads((base / f"case-01-{name}.json").read_text(encoding="utf-8"))
                    for name in ("first-generation", "revision-1", "revision-2")]
        self.assertEqual(len(requests), 3)
        receipts = ROOT / "archive/实验/evaluation/revision-regression/baseline/receipts/case-01"
        first_receipt = json.loads((receipts / "first-generation-attempt-2.json").read_text(encoding="utf-8"))
        edit_receipt = json.loads((receipts / "revision-1-attempt-1.json").read_text(encoding="utf-8"))
        second_receipt = json.loads((receipts / "revision-2-attempt-1.json").read_text(encoding="utf-8"))
        root_id = first_receipt["output"]["sha256"]
        edit_id = edit_receipt["output"]["sha256"]
        self.assertEqual(edit_receipt["input"]["previous_outputs"][0]["sha256"], root_id)
        self.assertEqual(second_receipt["input"]["previous_outputs"][0]["sha256"], edit_id)
        root = GenerationLineage(root_id, 0, None, root_id, None)
        edit = GenerationLineage(edit_id, 1, root_id, root_id, None)
        self.assertIs(choose_execution_strategy(root, self.scene_plan), ExecutionStrategy.DIRECT_EDIT)
        self.assertIs(choose_execution_strategy(edit, self.scene_plan), ExecutionStrategy.SOURCE_RESET)
        reset = GenerationLineage("new-reset-root", 0, None, "new-reset-root", edit_id)
        reset.validate()
        self.assertEqual(reset.reset_triggered_from_output, edit_id)
        self.assertEqual(len(self.provider.calls), 0)


if __name__ == "__main__":
    unittest.main()
