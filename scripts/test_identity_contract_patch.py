"""Regression tests for the Identity Primary generation-contract patch."""
from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from reference_runtime import (  # noqa: E402
    build_builtin_imagegen_args,
    build_invocation_plan,
    compile_reference_instructions,
    select_references,
)


class IdentityContractPatchTests(unittest.TestCase):
    def setUp(self):
        self.assets = yaml.safe_load((ROOT / "character/assets.yaml").read_text(encoding="utf-8"))["assets"]
        self.identity = next(x for x in self.assets if x["asset_id"] == "identity-p01-crop")
        self.variant = next(x for x in self.assets if x["asset_id"] == "casual-outfit-primary")

    def test_patch_contract_is_explicit_and_does_not_change_image(self):
        patched = copy.deepcopy(self.identity)
        patched["generation_reference"]["inheritance"] = {
            "identity": "inherit", "face": "inherit", "hair": "inherit", "eyes": "inherit",
            "outfit": "do_not_inherit", "pose": "do_not_inherit", "expression": "do_not_inherit",
        }
        self.assertEqual(set(k for k, v in patched["generation_reference"]["inheritance"].items() if v == "inherit"), {"identity", "face", "hair", "eyes"})
        self.assertEqual(patched["sha256"], self.identity["sha256"])
        self.assertEqual(patched["path"], self.identity["path"])
        self.assertEqual(self.variant["generation_reference"]["inheritance"], {"outfit": "inherit", "identity": "do_not_inherit", "face": "do_not_inherit", "hair": "do_not_inherit", "eyes": "do_not_inherit", "body_proportions": "do_not_inherit", "pose": "do_not_inherit", "expression": "do_not_inherit"})

    def test_prompt_compiler_preserves_identity_semantics(self):
        ref = {"reference_id": "identity-p01-crop", "source_scope": "managed_arco", "asset_id": "identity-p01-crop", "role": "identity_reference", "inherit": ["identity", "face", "hair", "eyes"], "do_not_inherit": ["outfit", "pose", "expression"]}
        text = compile_reference_instructions([ref]).lower()
        for phrase in ("identity", "face", "hair", "eyes", "outfit", "pose", "expression"):
            self.assertIn(phrase, text)
        self.assertIn("including her face, hair and eyes", text)

    def test_adapter_order_remains_identity_then_variant(self):
        identity = copy.deepcopy(self.identity)
        identity["generation_reference"]["inheritance"] = {"identity": "inherit", "face": "inherit", "hair": "inherit", "eyes": "inherit", "outfit": "do_not_inherit", "pose": "do_not_inherit", "expression": "do_not_inherit"}
        selected = select_references(root=ROOT, managed_assets=[identity, self.variant], requested_roles=["identity_reference", "outfit_reference"], selected_variant_id="casual-outfit", exposure_profile="portrait", variant_required=True, config=yaml.safe_load((ROOT / "runtime/generation.yaml").read_text(encoding="utf-8")))
        self.assertEqual([ref["asset_id"] for ref in selected], ["identity-p01-crop", "casual-outfit-primary"])
        plan = build_invocation_plan(mode="reference_conditioned", prompt="test", selected_references=selected)
        args = build_builtin_imagegen_args(plan)
        self.assertEqual(args["referenced_image_paths"], [str(ROOT / self.identity["path"]), str(ROOT / self.variant["path"])])


if __name__ == "__main__":
    unittest.main(verbosity=2)
