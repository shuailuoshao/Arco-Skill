"""Phase 5 request-only planning, compiler snapshots, and structural regression."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from legacy_generation_fixture import legacy_generation_root

from arco_production import run_production_generation
from composition_readability import ReadabilityPolicy, compile_readability, plan_composition_readability
from reference_runtime import compile_prompt
from revision_intent import GeneratedOutputRole, RevisionPlan, RevisionType, SourceStrategy
from revision_reference import run_production_revision


def policy():
    return ReadabilityPolicy.from_document(yaml.safe_load(
        (ROOT / "runtime/composition-readability.yaml").read_text(encoding="utf-8")))


def plan(text, **kwargs):
    return plan_composition_readability(text, policy(), **kwargs)


class ReadabilityContractTests(unittest.TestCase):
    def test_serialization_and_determinism(self):
        text = "人物约占画面10%，脸和衣服结构必须看清。"
        plans = [plan(text).as_dict() for _ in range(10)]
        self.assertEqual(plans, [plans[0]] * 10)
        self.assertEqual(list(plans[0]), [
            "composition_priority", "subject_scale", "requested_frame_ratio",
            "character_detail_requirement", "scale_readability_conflict",
            "recommended_subject_scale", "recommended_frame_ratio",
            "readability_guidance_enabled", "guidance",
        ])
        self.assertEqual(json.loads(json.dumps(plans[0]))["requested_frame_ratio"], 0.1)

    def test_invalid_input_fails_closed(self):
        for options in ({"composition_priority": "anything"}, {"subject_frame_height_ratio": 1.5},
                        {"subject_frame_height_ratio": True}, {"other": 1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                plan("Arco.", options=options)
        with self.assertRaises(ValueError):
            plan("Face must be clearly readable.", options={"character_detail_requirement": "low"})

    def test_policy_is_centralized_and_ordered(self):
        document = yaml.safe_load((ROOT / "runtime/composition-readability.yaml").read_text(encoding="utf-8"))
        self.assertEqual(policy().full_body_preferred_min_frame_height_ratio, 0.25)
        self.assertEqual(policy().full_body_preferred_target_frame_height_ratio, 0.30)
        document["composition_readability"]["full_body_preferred_target_frame_height_ratio"] = 0.35
        changed = ReadabilityPolicy.from_document(document)
        result = plan_composition_readability("人物约占画面10%，脸必须看清", changed,
                                              options={"composition_priority": "character_readability"})
        self.assertEqual(result.recommended_frame_ratio, 0.35)


class CompositionPriorityTests(unittest.TestCase):
    def test_atmosphere_is_authoritative(self):
        result = plan("人物只占画面约10%，保留大面积天空负空间，人物作为远景点缀，脸要看清。")
        self.assertEqual(result.composition_priority, "atmosphere")
        self.assertTrue(result.scale_readability_conflict)
        self.assertEqual(result.recommended_frame_ratio, 0.1)
        self.assertIn("negative space", result.guidance)

    def test_character_readability_priority(self):
        result = plan("大场景，人物约占画面10%，人物清晰优先，脸和服装必须看清。")
        self.assertEqual(result.composition_priority, "character_readability")
        self.assertEqual(result.recommended_frame_ratio, 0.30)

    def test_balanced_priority_and_ambiguous_default(self):
        result = plan("保留大场景，但人物约占画面10%，脸和服装要看清。")
        self.assertEqual(result.composition_priority, "balanced")
        self.assertEqual(result.recommended_frame_ratio, 0.25)
        self.assertEqual(plan("Arco stands in a garden.").composition_priority, "balanced")


class SubjectScaleTests(unittest.TestCase):
    def test_numeric_boundaries(self):
        expected = ((0.10, "very_small"), (0.15, "small"), (0.25, "medium"),
                    (0.30, "medium"), (0.50, "close"))
        for ratio, scale in expected:
            with self.subTest(ratio=ratio):
                self.assertEqual(plan("Arco.", options={"subject_frame_height_ratio": ratio}).subject_scale, scale)

    def test_discrete_never_fabricates_requested_ratio(self):
        result = plan("A small distant figure in a large environment; face readable.")
        self.assertEqual(result.subject_scale, "small")
        self.assertIsNone(result.requested_frame_ratio)
        self.assertTrue(result.scale_readability_conflict)

    def test_unknown_scale_stays_unknown(self):
        result = plan("Make the face clearly readable.")
        self.assertEqual(result.subject_scale, "unknown")
        self.assertIsNone(result.scale_readability_conflict)
        self.assertTrue(result.readability_guidance_enabled)


class ConflictResolutionTests(unittest.TestCase):
    def test_ten_percent_high_detail_conflicts(self):
        result = plan("人物约占画面10%，脸、眼睛和服装结构必须看清。",
                      options={"composition_priority": "character_readability"})
        self.assertTrue(result.scale_readability_conflict)
        self.assertEqual(result.recommended_frame_ratio, 0.30)

    def test_normal_thirty_percent_has_no_false_conflict(self):
        result = plan("人物约占画面30%。")
        self.assertFalse(result.scale_readability_conflict)
        self.assertFalse(result.readability_guidance_enabled)
        self.assertEqual(result.recommended_frame_ratio, 0.30)

    def test_close_and_medium_are_not_enlarged(self):
        for ratio in (0.30, 0.60):
            with self.subTest(ratio=ratio):
                result = plan("Keep the face clear.", options={"subject_frame_height_ratio": ratio})
                self.assertFalse(result.scale_readability_conflict)
                self.assertEqual(result.recommended_frame_ratio, ratio)

    def test_revision_scale_change_boundary(self):
        text = "人物往近一点，让脸清楚"
        source = "人物约占画面10%，保留大场景。"
        allowed = plan(text, source_text=source, options={"composition_priority": "character_readability"})
        blocked = plan(text, source_text=source, options={"composition_priority": "character_readability"},
                       allow_scale_change=False)
        self.assertEqual(allowed.recommended_frame_ratio, 0.30)
        self.assertEqual(blocked.recommended_frame_ratio, 0.10)
        self.assertTrue(blocked.scale_readability_conflict)

    def test_revision_readability_balances_source_atmosphere(self):
        result = plan("人物往近一点，让脸清楚", source_text="人物占画面10%，保留大面积天空负空间。")
        self.assertEqual(result.composition_priority, "balanced")
        self.assertEqual(result.recommended_frame_ratio, 0.25)
        structured = plan("人物往近一点，让脸清楚", source_text="人物占画面10%。",
                          source_options={"composition_priority": "atmosphere"})
        self.assertEqual(structured.composition_priority, "balanced")

    def test_revision_explicit_scale_supersedes_source_ratio(self):
        result = plan("Make the face clear; use a medium shot.", source_text="Character occupies 10% of frame.")
        self.assertEqual(result.subject_scale, "medium")
        self.assertIsNone(result.requested_frame_ratio)
        self.assertFalse(result.scale_readability_conflict)


class PromptIntegrationTests(unittest.TestCase):
    def test_six_prompt_structure_snapshots(self):
        guidance = {
            "atmosphere": "Preserve the requested distant character scale and environmental negative space. Keep the main identity and outfit silhouette recognizable where that scale permits; detailed facial features may be limited.",
            "readability": "Keep substantial environment visible while placing the character at about 30% of frame height so the face and primary outfit structure remain distinguishable.",
            "balanced": "Keep substantial environment visible while placing the character at about 25% of frame height so the face and primary outfit structure remain distinguishable.",
            "source_reset": "Keep substantial environment visible while placing the character at about 30% of frame height so the face and primary outfit structure remain distinguishable.",
            "direct_edit": "Keep substantial environment visible while placing the character at about 30% of frame height so the face and primary outfit structure remain distinguishable.",
        }
        cases = (
            ("normal", "Arco stands in a garden.", {}, False, None),
            ("atmosphere", "人物占画面10%，保留大面积天空负空间，人物作为远景点缀，脸要看清。", {}, True, "negative space"),
            ("readability", "人物占画面10%，人物清晰优先，脸和服装要看清。", {}, True, "30%"),
            ("balanced", "保留大场景，人物占画面10%，脸和服装要看清。", {}, True, "25%"),
            ("source_reset", "Create a fresh image from Source Truth. Character occupies 10% of the frame; face must be clearly readable.", {}, True, "30%"),
            ("direct_edit", "人物往近一点，让脸清楚", {"source_text": "人物占画面10%。"}, True, "30%"),
        )
        for name, request, kwargs, present, phrase in cases:
            with self.subTest(name=name):
                options = {"composition_priority": "character_readability"} if name == "direct_edit" else None
                result = plan(request, options=options, **kwargs)
                prompt = compile_prompt(base_prompt=request, references=[], composition_readability_plan=result)
                self.assertEqual("[Composition Readability]" in prompt, present)
                expected = request if not present else (
                    request + " [Composition Readability]\n" + guidance[name] + "\n[/Composition Readability]"
                )
                self.assertEqual(prompt, expected)
                if phrase:
                    self.assertIn(phrase, prompt)
                if name == "source_reset":
                    self.assertNotIn("[Revision Stability", prompt)
                for banned in ("8k", "ultra high resolution", "best quality", "masterpiece",
                               "extremely detailed", "super sharp"):
                    self.assertNotIn(banned, compile_readability(result).lower())

    def test_production_result_exposes_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.png"
            def provider(*, prompt, referenced_image_paths):
                output.write_bytes(b"\x89PNG\r\n\x1a\nphase5")
                return output
            result = run_production_generation(
                {"base_prompt": "Arco stands in a garden.", "exposure_profile": "upper_body"},
                builtin_image_gen=provider, root=legacy_generation_root())
            self.assertEqual(result.as_dict()["composition_readability_plan"]["composition_priority"], "balanced")
            self.assertNotIn("[Composition Readability]", result.prompt)

    def test_readability_does_not_change_reference_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = []
            def provider(*, prompt, referenced_image_paths):
                output = Path(tmp) / f"out-{len(outputs)}.png"
                output.write_bytes(b"\x89PNG\r\n\x1a\nphase5")
                outputs.append(output)
                return output
            base = {"base_prompt": "人物占画面10%，脸要看清。", "exposure_profile": "full_body",
                    "variant_id": "casual-outfit"}
            default = run_production_generation(base, builtin_image_gen=provider, root=legacy_generation_root())
            selected = run_production_generation({**base, "composition_readability": {
                "composition_priority": "character_readability"}}, builtin_image_gen=provider, root=legacy_generation_root())
            authority = lambda result: [(ref.get("source_scope"), ref.get("role"), ref.get("authority"),
                                         ref.get("variant_id"), ref.get("path")) for ref in result.selected_references]
            self.assertEqual(authority(default), authority(selected))
            self.assertEqual(default.generation_depth, selected.generation_depth)

    def test_direct_edit_and_source_reset_keep_strategy_and_stability(self):
        from test_revision_lineage import Provider, previous_from_result
        with tempfile.TemporaryDirectory() as tmp:
            provider = Provider(tmp)
            source = {"base_prompt": "人物约占画面10%，保留大场景。", "exposure_profile": "upper_body"}
            first = run_production_generation(source, builtin_image_gen=provider, root=legacy_generation_root())
            previous = previous_from_result(first)
            revision = {"base_prompt": "人物往近一点，让脸清楚", "exposure_profile": "upper_body",
                        "composition_readability": {"composition_priority": "character_readability"}}
            composition = RevisionPlan(RevisionType.COMPOSITION, SourceStrategy.EDIT_CURRENT,
                                       GeneratedOutputRole.COMPOSITION_ANCHOR, False, False, False)
            edit = run_production_revision(revision, revision_plan=composition, previous_output=previous,
                                           source_request=source, builtin_image_gen=provider, root=legacy_generation_root())
            self.assertEqual(edit.generation_depth, 1)
            self.assertIn("[Composition Readability]", edit.prompt)
            self.assertIn("[Revision Stability", edit.prompt)
            self.assertIn("30%", edit.prompt)
            reset = run_production_revision(revision, revision_plan=composition,
                                            previous_output=previous_from_result(edit), source_request=source,
                                            builtin_image_gen=provider, root=legacy_generation_root())
            self.assertEqual(reset.generation_depth, 0)
            self.assertIn("[Composition Readability]", reset.prompt)
            self.assertNotIn("[Revision Stability", reset.prompt)
            self.assertIn("fresh image", reset.prompt)


class Case03StructuralRegressionTests(unittest.TestCase):
    def test_frozen_case03_structure(self):
        source = ROOT / "archive/实验/evaluation/revision-regression/input-bundle/requests/case-03-baseline-generation.json"
        request = json.loads(source.read_text(encoding="utf-8"))
        result = plan(request["base_prompt"])
        self.assertEqual(result.composition_priority, "atmosphere")
        self.assertEqual(result.requested_frame_ratio, 0.40)
        self.assertEqual(result.subject_scale, "medium")
        self.assertEqual(result.character_detail_requirement, "normal")
        self.assertFalse(result.scale_readability_conflict)
        self.assertEqual(result.recommended_frame_ratio, 0.40)
        self.assertIn("silhouette", compile_readability(result))


if __name__ == "__main__":
    unittest.main()
