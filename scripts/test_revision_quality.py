"""Exercise the real production bridge with an offline provider."""
import copy
import unittest

import test_revision_lineage as lineage_tests
from test_revision_lineage import previous_from_result
from functools import partial
from legacy_generation_fixture import legacy_generation_root
from arco_production import ProductionGenerationError, run_production_generation
from revision_reference import run_production_revision
from revision_intent import resolve_revision_intent, SourceStrategy


run_production_generation = partial(run_production_generation, root=legacy_generation_root())
run_production_revision = partial(run_production_revision, root=legacy_generation_root())

class RevisionQualityTests(unittest.TestCase):
    setUp = lineage_tests.Phase3LineageTests.setUp
    first = lineage_tests.Phase3LineageTests.first

    def edit(self, previous, text, **kwargs):
        request = {"base_prompt": text, "exposure_profile": "upper_body",
                   "request_scoped_arco_references": [previous]}
        return run_production_revision(request, revision_plan=resolve_revision_intent(text),
            previous_output=previous, builtin_image_gen=self.provider, **kwargs)

    def test_marked_output_cannot_bypass_revision_entry(self):
        first = self.first()
        with self.assertRaises(ProductionGenerationError) as error:
            run_production_generation(dict(self.source, request_scoped_arco_references=[previous_from_result(first)]),
                                      builtin_image_gen=self.provider)
        self.assertEqual(error.exception.code, "REVISION_ENTRY_REQUIRED")
        self.assertEqual(len(self.provider.calls), 1)

    def test_history_survives_multiple_resets_and_later_conflict(self):
        root = self.first()
        one = self.edit(previous_from_result(root), "Change Image 1 expression to smiling.")
        two = self.edit(previous_from_result(one), "Simplify clothing folds.")
        self.assertEqual(two.generation_depth, 0)
        self.assertIn("expression to smiling", two.prompt)
        self.assertIn("Simplify clothing folds", two.prompt)
        self.assertIn(str(one.output_path), self.provider.calls[-1][1])
        three = self.edit(previous_from_result(two), "Make the background brighter.")
        four = self.edit(previous_from_result(three), "Change the expression to serious instead of smiling.")
        history = four.revision_context["revisions"]
        self.assertEqual(len(history), 4)
        self.assertLess(four.prompt.index("expression to smiling"), four.prompt.index("expression to serious"))
        self.assertIn("Later explicit requests supersede", four.prompt)
        self.assertNotIn("Change Image 1 expression", four.prompt)
        self.assertEqual(four.prompt.count("Original source request:"), 1)

    def test_degraded_review_excludes_parent_at_either_depth(self):
        root = self.first()
        edited = self.edit(previous_from_result(root), "Make background brighter.")
        for result in (root, edited):
            previous = previous_from_result(result.with_visual_review("degraded"))
            reset = self.edit(previous, "Make background darker.")
            self.assertEqual(reset.generation_depth, 0)
            self.assertNotIn(str(result.output_path), self.provider.calls[-1][1])
            self.assertEqual(reset.visual_review_status, "unchecked")

    def test_reported_artifact_forces_reset(self):
        root = self.first()
        for text in ("修复边缘发糊", "消除重影", "去掉发丝重复细纹", "消除异常模糊"):
            reset = self.edit(previous_from_result(root), text)
            self.assertEqual(reset.generation_depth, 0)
            self.assertNotIn(str(root.output_path), self.provider.calls[-1][1])

    def test_preserved_soft_focus_does_not_trigger_repair(self):
        for text in ("保留柔焦背景，修改表情", "保持背景模糊不变，修改表情", "保留头发，不要增加重影，背景变亮"):
            self.assertNotEqual(resolve_revision_intent(text).source_strategy, SourceStrategy.SOURCE_RESET)

    def test_legacy_missing_history_fails_before_provider(self):
        first = self.first()
        edit = self.edit(previous_from_result(first), "Make background brighter.")
        previous = previous_from_result(edit)
        del previous["revision_context"]
        count = len(self.provider.calls)
        with self.assertRaises(ProductionGenerationError) as error:
            self.edit(previous, "Make background darker.", source_request=self.source)
        self.assertEqual(error.exception.code, "REVISION_HISTORY_REQUIRED")
        self.assertEqual(len(self.provider.calls), count)
        recovered = self.edit(previous, "Make background darker.", revision_context=edit.as_dict()["revision_context"])
        self.assertIn("Make background brighter", recovered.prompt)

    def test_legacy_root_can_recover_from_source(self):
        previous = previous_from_result(self.first())
        del previous["revision_context"]
        result = self.edit(previous, "消除重影", source_request=self.source)
        self.assertTrue(result.revision_context["history_complete"])

    def test_style_override_survives_reset(self):
        source = copy.deepcopy(self.source)
        source["user_style_overrides"] = {"linework": {"description": "Clean continuous thin lines.", "confidence": "HIGH"}}
        first = run_production_generation(source, builtin_image_gen=self.provider)
        one = self.edit(previous_from_result(first), "Make background brighter.")
        reset = self.edit(previous_from_result(one), "Make background darker.")
        self.assertIn("Clean continuous thin lines", reset.prompt)

    def test_review_is_explicit_and_serialized(self):
        first = self.first()
        self.assertEqual(first.as_dict()["visual_review_status"], "unchecked")
        self.assertEqual(first.with_visual_review("passed").as_dict()["visual_review_status"], "passed")
        with self.assertRaises(ProductionGenerationError):
            first.with_visual_review("automatic_pass")

    def test_degraded_parent_cannot_be_overridden_to_passed(self):
        previous = previous_from_result(self.first().with_visual_review("degraded"))
        reset = self.edit(previous, "Make background brighter.", visual_review_status="passed")
        self.assertNotIn(previous["path"], reset.invocation_plan["referenced_image_paths"])

    def test_history_and_source_are_not_mutated(self):
        previous = previous_from_result(self.first())
        snapshot = copy.deepcopy(previous)
        self.edit(previous, "Make background brighter.")
        self.assertEqual(previous, snapshot)

    def test_original_source_image_numbers_are_not_reused(self):
        source = dict(self.source, base_prompt="Arco in the pose from Image 1.")
        first = run_production_generation(source, builtin_image_gen=self.provider)
        reset = self.edit(previous_from_result(first), "消除重影")
        self.assertNotIn("pose from Image 1", reset.prompt)

    def test_new_external_reference_survives_reset(self):
        first = self.first()
        one = self.edit(previous_from_result(first), "Make background brighter.")
        previous = previous_from_result(one)
        external = {"reference_id": "new-pose", "source_scope": "external_how", "role": "pose_reference",
                    "path": str(lineage_tests.ROOT / "archive/实验/evaluation/revision-regression/private-assets/case-01-external-how.jpg"),
                    "authority": "user_request_external", "inherit": ["pose"],
                    "do_not_inherit": ["identity", "outfit", "variant"]}
        text = "使用外部参考图的姿势"
        request = {"base_prompt": text, "exposure_profile": "upper_body", "external_references": [external]}
        result = run_production_revision(request, previous_output=previous,
            revision_plan=resolve_revision_intent(text, external_references=[external]),
            builtin_image_gen=self.provider)
        self.assertIn(external["path"], result.invocation_plan["referenced_image_paths"])


if __name__ == "__main__":
    unittest.main()
