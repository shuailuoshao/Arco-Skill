import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from revision_intent import GeneratedOutputRole, RevisionPlan, RevisionType, SourceStrategy
from revision_lineage import ExecutionStrategy, GenerationLineage, choose_execution_strategy
from revision_stability import build_revision_stability_guard, compile_revision_stability
from reference_runtime import compile_prompt


def plan(kind):
    return RevisionPlan(kind, SourceStrategy.SOURCE_RESET if kind is RevisionType.ARTIFACT_REPAIR else SourceStrategy.EDIT_CURRENT,
                        GeneratedOutputRole.EXCLUDED if kind is RevisionType.ARTIFACT_REPAIR else GeneratedOutputRole.PRIMARY_EDIT_SOURCE,
                        False, False, False)


class RevisionStabilityTests(unittest.TestCase):
    def guard(self, kind, request="Change the requested detail."):
        return build_revision_stability_guard(plan(kind), ExecutionStrategy.DIRECT_EDIT, request)

    def test_structured_deterministic_scope_and_serialization(self):
        cases = {
            RevisionType.SCENE_ONLY: ("scene properties", "character appearance"),
            RevisionType.CHARACTER_DETAIL: ("character detail", "background"),
            RevisionType.COMPOSITION: ("geometry changes", "character design"),
            RevisionType.STYLE: ("style transformation", "scene content"),
            RevisionType.MIXED: ("every component", "unrelated"),
        }
        for kind, (allowed, preserved) in cases.items():
            with self.subTest(kind=kind):
                guard = self.guard(kind)
                self.assertEqual(guard, self.guard(kind))
                self.assertEqual(guard.as_dict()["execution_scope"], "DIRECT_EDIT")
                self.assertIn(allowed, guard.requested_scope)
                self.assertIn(preserved, " ".join(guard.preserve_unaffected_regions))
                self.assertIn("change the requested detail.", guard.requested_scope)

    def test_low_frequency_and_no_quality_stuffing(self):
        block = compile_revision_stability(self.guard(RevisionType.SCENE_ONLY))
        for term in ("smooth backgrounds", "gradients", "blurred regions", "flat-color", "soft lighting transitions",
                     "atmospheric haze", "shadow fields", "broad glow", "ripple-like", "moire-like", "repetitive textures",
                     "unrequested detail or texture"):
            self.assertIn(term, block)
        for term in ("masterpiece", "best quality", "high quality", "ultra detailed", "4k", "8k", "super sharp"):
            self.assertNotIn(term, block.lower())

    def test_activation_and_prompt_structure_snapshots(self):
        first = compile_prompt(base_prompt="First generation.", references=[])
        self.assertNotIn("[Revision Stability", first)
        for kind in (RevisionType.SCENE_ONLY, RevisionType.CHARACTER_DETAIL, RevisionType.COMPOSITION):
            with self.subTest(kind=kind):
                prompt = compile_prompt(base_prompt="Requested revision.", references=[],
                                        revision_stability_guard=self.guard(kind))
                self.assertLess(prompt.index("Requested revision."), prompt.index("[Revision Stability — DIRECT_EDIT]"))
                self.assertIn("[/Revision Stability]", prompt)
        reset_guard = build_revision_stability_guard(plan(RevisionType.SCENE_ONLY), ExecutionStrategy.SOURCE_RESET, "Change scene")
        self.assertIsNone(reset_guard)
        reset = compile_prompt(base_prompt="Create a fresh image from Source Truth. Requested revision: Change scene.", references=[],
                               revision_stability_guard=reset_guard)
        self.assertNotIn("[Revision Stability", reset)
        self.assertNotIn("preserve every unchanged pixel", reset.lower())

    def test_artifact_repair_remains_reset(self):
        root = GenerationLineage("root", 0, None, "root", None)
        artifact = plan(RevisionType.ARTIFACT_REPAIR)
        strategy = choose_execution_strategy(root, artifact)
        self.assertIs(strategy, ExecutionStrategy.SOURCE_RESET)
        self.assertIsNone(build_revision_stability_guard(artifact, strategy, "Repair moire"))

    def test_case01_frozen_structure(self):
        receipts = ROOT / "archive/实验/evaluation/revision-regression/baseline/receipts/case-01"
        first = json.loads((receipts / "first-generation-attempt-2.json").read_text(encoding="utf-8"))
        edit = json.loads((receipts / "revision-1-attempt-1.json").read_text(encoding="utf-8"))
        source = first["output"]["sha256"]
        changed = edit["output"]["sha256"]
        root = GenerationLineage(source, 0, None, source, None)
        depth1 = GenerationLineage(changed, 1, source, source, None)
        scene = plan(RevisionType.SCENE_ONLY)
        first_decision = choose_execution_strategy(root, scene)
        second_decision = choose_execution_strategy(depth1, scene)
        self.assertIs(first_decision, ExecutionStrategy.DIRECT_EDIT)
        self.assertIsNotNone(build_revision_stability_guard(scene, first_decision, "背景亮一点"))
        self.assertIs(second_decision, ExecutionStrategy.SOURCE_RESET)
        self.assertIsNone(build_revision_stability_guard(scene, second_decision, "背景亮一点"))


if __name__ == "__main__":
    unittest.main()
