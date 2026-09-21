from __future__ import annotations

import unittest
import sys
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import audit_style_regression_validity as validity


class StyleRegressionValidityTests(unittest.TestCase):
    def test_common_safety_block_is_byte_exact_and_prepended(self):
        body = "Reference roles\nScene and composition"
        prompt = validity.build_replacement_prompt(body)
        self.assertTrue(prompt.startswith(validity.SAFETY_CLARIFICATION + "\n\n"))
        self.assertEqual(
            prompt[len(validity.SAFETY_CLARIFICATION) + 2 :],
            body,
        )
        self.assertEqual(
            validity.SAFETY_BLOCK_SHA256,
            "bb692a91cb8ae55788859924fba99165749c5a915612bd83c389aad60b45779c",
        )

    def test_bc_delta_requires_exact_hygiene_suffix(self):
        base = "shared prompt"
        hygiene = "\n\nRendering hygiene guardrails:\n- Keep the hierarchy."
        self.assertTrue(validity._bc_hygiene_only(base, base + hygiene)["valid"])
        self.assertFalse(validity._bc_hygiene_only(base, base + "\n\nextra")["valid"])
        self.assertFalse(validity._bc_hygiene_only(base, "different" + hygiene)["valid"])

    def test_safety_signature_detects_missing_and_structurally_different_clarification(self):
        shared = validity.SAFETY_CLARIFICATION
        self.assertTrue(validity._safety_signature(shared)["present"])
        self.assertFalse(validity._safety_signature("ordinary scene only")["present"])
        variant = shared.replace("adult woman", "adult female")
        self.assertNotEqual(
            validity._safety_signature(shared),
            validity._safety_signature(variant),
        )

    def test_current_formal_capture_audits_expected_counts_and_confounds(self):
        original_loader = validity.runner.load_codex_task

        def load_historical_task(path, **kwargs):
            return original_loader(path, **{**kwargs, "verify_frozen_inputs": False})

        with mock.patch.object(validity.runner, "load_codex_task", side_effect=load_historical_task):
            audit = validity.audit_original_samples()
        self.assertEqual(audit["original_sample_count"], 36)
        self.assertEqual(
            audit["original_classification_counts"],
            {"CLEAN": 31, "PROMPT_REVISED": 5},
        )
        self.assertEqual(
            audit["affected_triplets"],
            ["case-04:r2", "case-04:r3"],
        )
        triplets = {item["triplet_id"]: item for item in audit["triplets"]}
        self.assertFalse(triplets["case-04:r2"]["safety_equivalent_semantically_and_structurally"])
        self.assertFalse(triplets["case-04:r3"]["safety_equivalent_semantically_and_structurally"])
        self.assertTrue(triplets["case-04:r2"]["bc_difference_hygiene_only"])
        self.assertTrue(triplets["case-04:r3"]["bc_difference_hygiene_only"])
        self.assertTrue(all(item["reference_parity"] for item in audit["triplets"]))
        self.assertTrue(all(item["ordered_reference_parity"] for item in audit["triplets"]))
        self.assertTrue(all(item["bc_style_context_parity"] for item in audit["triplets"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
