"""Phase 5R: real Phase 1 plan through the production revision planning bridge."""

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from legacy_generation_fixture import legacy_generation_root

from arco_production import run_production_generation
from revision_intent import RevisionType, resolve_revision_intent
from revision_reference import run_production_revision
from test_revision_lineage import Provider, previous_from_result


class RevisionReadabilityRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.provider = Provider(self.temp.name)  # Writes placeholder bytes; no real image generation.
        self.source = {
            "base_prompt": "人物约占画面10%。",
            "exposure_profile": "upper_body",
            "variant_id": "casual-outfit",
        }
        first = run_production_generation(self.source, builtin_image_gen=self.provider, root=legacy_generation_root())
        self.previous = previous_from_result(first)

    def revision(self, raw, *, source_request=None):
        actual_plan = resolve_revision_intent(raw)
        result = run_production_revision(
            {"base_prompt": raw, "exposure_profile": "upper_body",
             "request_scoped_arco_references": [self.previous]},
            revision_plan=actual_plan,
            previous_output=self.previous,
            source_request=source_request,
            selected_variant_id="casual-outfit",
            builtin_image_gen=self.provider,
            root=legacy_generation_root(),
        )
        return actual_plan, result

    def test_canonical_raw_request_preserves_composition_through_phase5(self):
        raw = "人物往近一点，让脸清楚"
        actual_plan, result = self.revision(raw, source_request=self.source)
        readability = result.composition_readability_plan
        self.assertIs(actual_plan.revision_type, RevisionType.MIXED)
        self.assertTrue(actual_plan.requires_original_identity)
        self.assertEqual(readability.requested_frame_ratio, 0.10)
        self.assertEqual(readability.recommended_frame_ratio, 0.30)
        self.assertTrue(readability.readability_guidance_enabled)
        self.assertIn("30%", result.prompt)
        self.assertIn("[Revision Stability", result.prompt)
        self.assertEqual(result.generation_depth, 1)

    def test_outfit_readability_preserves_outfit_authority_and_scale(self):
        actual_plan, result = self.revision("人物再大一点，让衣服能看清", source_request=self.source)
        self.assertIs(actual_plan.revision_type, RevisionType.MIXED)
        self.assertTrue(actual_plan.requires_original_outfit)
        self.assertTrue(result.composition_readability_plan.readability_guidance_enabled)
        self.assertGreater(result.composition_readability_plan.recommended_frame_ratio, 0.10)
        self.assertTrue(any(ref.get("role") == "outfit_reference" for ref in result.selected_references))

    def test_atmosphere_tradeoff_preserves_unknown_and_known_scale(self):
        raw = "人物太远了，但我想保留大面积天空"
        context = self.previous.pop("revision_context")
        unknown_plan, unknown_result = self.revision(raw)
        self.assertIs(unknown_plan.revision_type, RevisionType.COMPOSITION)
        self.assertEqual(unknown_result.composition_readability_plan.composition_priority, "atmosphere")
        self.assertEqual(unknown_result.composition_readability_plan.subject_scale, "unknown")
        self.assertIsNone(unknown_result.composition_readability_plan.requested_frame_ratio)
        self.previous["revision_context"] = context
        _, inherited_result = self.revision(raw)
        self.assertEqual(inherited_result.composition_readability_plan.subject_scale, "very_small")
        known_plan, known_result = self.revision(raw, source_request=self.source)
        self.assertEqual(known_plan, unknown_plan)
        self.assertEqual(known_result.composition_readability_plan.subject_scale, "very_small")
        self.assertEqual(known_result.composition_readability_plan.recommended_frame_ratio, 0.10)


if __name__ == "__main__":
    unittest.main()
