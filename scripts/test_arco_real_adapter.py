from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from arco_real_adapter import ArcoRealAdapter, ArcoRealAdapterError  # noqa: E402
from reference_runtime import (  # noqa: E402
    build_builtin_imagegen_args,
    build_invocation_plan,
    compile_reference_instructions,
    compile_prompt,
    select_references,
)


class FakeBuiltinImageGen:
    def __init__(self, output: Path | None = None, *, result=None, error: Exception | None = None):
        self.output = output
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []

    def __call__(self, *, prompt: str, referenced_image_paths: list[str]):
        self.calls.append(
            {
                "prompt": prompt,
                "referenced_image_paths": list(referenced_image_paths),
            }
        )
        if self.error is not None:
            raise self.error
        if self.output is not None:
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_bytes(b"generated-png-placeholder")
        if self.result is not None:
            return self.result
        return {"path": str(self.output)}


def make_contract(root: Path, reference_id: str = "request-arco-1") -> dict[str, object]:
    path = root / f"{reference_id}.png"
    path.write_bytes(reference_id.encode("utf-8"))
    return {
        "reference_id": reference_id,
        "request_reference_id": reference_id,
        "source_scope": "request_scoped_arco",
        "path": str(path),
        "role": "identity_reference",
        "authority": "user_request",
        "persistent": False,
        "calibrating": False,
        "inherit": ["identity"],
        "do_not_inherit": ["outfit", "pose", "expression"],
        "coverage": {
            "profiles": ["full_body"],
            "visible_fields": ["identity", "hair", "eyes", "face", "body.full"],
            "view_angles": ["three_quarter_right"],
            "occluded_fields": [],
        },
    }


def make_plan(contracts: list[dict[str, object]]) -> dict[str, object]:
    prompt = compile_reference_instructions(contracts) + " Arco stands in the rain."
    return build_invocation_plan(
        mode="reference_conditioned",
        prompt=prompt,
        selected_references=contracts,
    )


def make_raw_plan(contract: dict[str, object]) -> dict[str, object]:
    """Build a plan without invoking the planner's own contract gate."""

    return {
        "provider": "builtin_image_gen",
        "capability": "reference_conditioned_image_generation",
        "mode": "reference_conditioned",
        "prompt": "Reference request-arco-1: use to define identity. Do not inherit: outfit, pose, expression. Arco stands in the rain.",
        "selected_reference_ids": [contract["reference_id"]],
        "referenced_image_paths": [contract["path"]],
    }


class ArcoRealAdapterTests(unittest.TestCase):
    def assertCode(self, code: str, callback) -> None:
        with self.assertRaises(ArcoRealAdapterError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_valid_request_calls_builtin_with_exact_args_and_returns_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract = make_contract(root)
            plan = make_plan([contract])
            output = root / "generated" / "arco.png"
            provider = FakeBuiltinImageGen(output)
            watched = root / "character" / "identity.yaml"
            watched.parent.mkdir()
            watched.write_bytes(b"unchanged")
            before = hashlib.sha256(watched.read_bytes()).hexdigest()
            original_contract = copy.deepcopy(contract)

            result = ArcoRealAdapter(provider).generate(
                invocation_plan=plan,
                reference_contracts=[contract],
                reference_image_paths=[contract["path"]],
            )

            self.assertEqual(result, output.resolve())
            self.assertEqual(
                provider.calls,
                [{
                    "prompt": plan["prompt"],
                    "referenced_image_paths": [contract["path"]],
                }],
            )
            self.assertEqual(contract, original_contract)
            self.assertEqual(hashlib.sha256(watched.read_bytes()).hexdigest(), before)

    def test_adapter_schema_unchanged_after_style_and_hygiene_compilation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract = make_contract(root)
            style_context = {
                "mode": "official_fallback",
                "primary_reference_id": None,
                "secondary_reference_id": None,
                "resolved_axes": {
                    "linework": {
                        "description": "thin clean restrained contours",
                        "source": "official-test-baseline",
                        "source_type": "official_baseline",
                        "confidence": "HIGH",
                    },
                    "detail_density": {
                        "description": "moderate readable detail density",
                        "source": "official-test-baseline",
                        "source_type": "official_baseline",
                        "confidence": "MEDIUM",
                    }
                },
                "protected_identity_properties": ["hair_color", "eye_color", "variant_key_colors"],
            }
            prompt = compile_prompt(
                base_prompt="Arco stands in a quiet garden.",
                references=[contract],
                style_context=style_context,
                rendering_hygiene_policy=yaml.safe_load(
                    (ROOT / "runtime" / "style-policy.yaml").read_text(encoding="utf-8")
                ),
            )
            plan = build_invocation_plan(
                mode="reference_conditioned",
                prompt=prompt,
                selected_references=[contract],
            )
            provider = FakeBuiltinImageGen(root / "generated.png")

            result = ArcoRealAdapter(provider).generate(
                invocation_plan=plan,
                reference_contracts=[contract],
                reference_image_paths=[contract["path"]],
            )

            self.assertEqual(result, (root / "generated.png").resolve())
            self.assertEqual(
                provider.calls,
                [{"prompt": plan["prompt"], "referenced_image_paths": [contract["path"]]}],
            )
            self.assertEqual(set(provider.calls[0]), {"prompt", "referenced_image_paths"})

    def test_contract_ids_must_match_plan_order_before_provider_call(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract = make_contract(root)
            plan = make_plan([contract])
            plan["selected_reference_ids"] = ["different-id"]
            provider = FakeBuiltinImageGen(root / "generated.png")

            self.assertCode(
                "INVOCATION_CONTRACT_MISMATCH",
                lambda: ArcoRealAdapter(provider).generate(
                    invocation_plan=plan,
                    reference_contracts=[contract],
                    reference_image_paths=[contract["path"]],
                ),
            )
            self.assertEqual(provider.calls, [])

    def test_contract_and_supplied_paths_must_match_plan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract = make_contract(root)
            plan = make_plan([contract])
            other = root / "other.png"
            other.write_bytes(b"other")
            provider = FakeBuiltinImageGen(root / "generated.png")

            self.assertCode(
                "REFERENCE_PATH_MISMATCH",
                lambda: ArcoRealAdapter(provider).generate(
                    invocation_plan=plan,
                    reference_contracts=[contract],
                    reference_image_paths=[str(other)],
                ),
            )
            self.assertEqual(provider.calls, [])

    def test_missing_reference_file_fails_before_provider_call(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract = make_contract(root)
            path = Path(contract["path"])
            path.unlink()
            plan = make_plan([contract])
            provider = FakeBuiltinImageGen(root / "generated.png")

            self.assertCode(
                "REFERENCE_PATH_NOT_FOUND",
                lambda: ArcoRealAdapter(provider).generate(
                    invocation_plan=plan,
                    reference_contracts=[contract],
                    reference_image_paths=[contract["path"]],
                ),
            )
            self.assertEqual(provider.calls, [])

    def test_staging_contract_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staging = root / "calibration" / "staging" / "arco.png"
            staging.parent.mkdir(parents=True)
            staging.write_bytes(b"staging")
            contract = make_contract(root)
            contract["path"] = str(staging)
            plan = make_raw_plan(contract)
            provider = FakeBuiltinImageGen(root / "generated.png")

            self.assertCode(
                "UNPUBLISHED_ASSET",
                lambda: ArcoRealAdapter(provider).generate(
                    invocation_plan=plan,
                    reference_contracts=[contract],
                    reference_image_paths=[contract["path"]],
                ),
            )
            self.assertEqual(provider.calls, [])

    def test_managed_contract_requires_published_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract = make_contract(root)
            contract.update({
                "source_scope": "managed_arco",
                "asset_id": "identity-p01",
                "authority": "user_request",
                "persistent": False,
            })
            plan = make_plan([contract])
            provider = FakeBuiltinImageGen(root / "generated.png")

            self.assertCode(
                "UNPUBLISHED_ASSET",
                lambda: ArcoRealAdapter(provider).generate(
                    invocation_plan=plan,
                    reference_contracts=[contract],
                    reference_image_paths=[contract["path"]],
                ),
            )
            self.assertEqual(provider.calls, [])

    def test_prompt_must_preserve_contract_exclusions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract = make_contract(root)
            plan = make_plan([contract])
            plan["prompt"] = "Arco in the rain."
            provider = FakeBuiltinImageGen(root / "generated.png")

            self.assertCode(
                "QUALITY_GATE_FAILED",
                lambda: ArcoRealAdapter(provider).generate(
                    invocation_plan=plan,
                    reference_contracts=[contract],
                    reference_image_paths=[contract["path"]],
                ),
            )
            self.assertEqual(provider.calls, [])

    def test_prompt_only_plan_is_not_accepted_by_real_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract = make_contract(root)
            plan = make_plan([contract])
            plan["mode"] = "prompt_only"
            provider = FakeBuiltinImageGen(root / "generated.png")

            self.assertCode(
                "INVALID_ADAPTER_MODE",
                lambda: ArcoRealAdapter(provider).generate(
                    invocation_plan=plan,
                    reference_contracts=[contract],
                    reference_image_paths=[contract["path"]],
                ),
            )
            self.assertEqual(provider.calls, [])

    def test_provider_failure_is_normalized(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract = make_contract(root)
            plan = make_plan([contract])
            provider = FakeBuiltinImageGen(error=RuntimeError("provider failure"))

            self.assertCode(
                "BUILTIN_IMAGE_GEN_FAILED",
                lambda: ArcoRealAdapter(provider).generate(
                    invocation_plan=plan,
                    reference_contracts=[contract],
                    reference_image_paths=[contract["path"]],
                ),
            )
            self.assertEqual(len(provider.calls), 1)

    def test_malformed_or_missing_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract = make_contract(root)
            plan = make_plan([contract])

            missing = FakeBuiltinImageGen(result={"path": str(root / "missing.png")})
            self.assertCode(
                "GENERATED_OUTPUT_NOT_FOUND",
                lambda: ArcoRealAdapter(missing).generate(
                    invocation_plan=plan,
                    reference_contracts=[contract],
                    reference_image_paths=[contract["path"]],
                ),
            )

            malformed = FakeBuiltinImageGen(result={"image_url": "https://example.invalid/image.png"})
            self.assertCode(
                "INVALID_GENERATION_RESULT",
                lambda: ArcoRealAdapter(malformed).generate(
                    invocation_plan=plan,
                    reference_contracts=[contract],
                    reference_image_paths=[contract["path"]],
                ),
            )

    def test_generated_output_cannot_be_a_reference_input(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract = make_contract(root)
            plan = make_plan([contract])
            provider = FakeBuiltinImageGen(result={"path": contract["path"]})

            self.assertCode(
                "INVALID_GENERATION_RESULT",
                lambda: ArcoRealAdapter(provider).generate(
                    invocation_plan=plan,
                    reference_contracts=[contract],
                    reference_image_paths=[contract["path"]],
                ),
            )
            

    def test_published_selector_contracts_reach_adapter_read_only(self):
        assets = yaml.safe_load((ROOT / "character" / "assets.yaml").read_text(encoding="utf-8"))
        config = yaml.safe_load((ROOT / "runtime" / "generation.yaml").read_text(encoding="utf-8"))
        protected = [
            ROOT / "character" / "identity.yaml",
            ROOT / "character" / "assets.yaml",
            ROOT / "variants" / "index.yaml",
        ]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}

        selected = select_references(
            root=ROOT,
            managed_assets=assets["assets"],
            requested_roles=["identity_reference", "outfit_reference"],
            selected_variant_id="casual-outfit",
            exposure_profile="full_body",
            variant_required=True,
            config=config,
        )
        self.assertEqual(
            [reference["asset_id"] for reference in selected],
            ["identity-p01", "casual-outfit-primary"],
        )
        prompt = compile_reference_instructions(selected) + " Arco in a rainy night street."
        plan = build_invocation_plan(
            mode="reference_conditioned",
            prompt=prompt,
            selected_references=selected,
        )
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "generated.png"
            provider = FakeBuiltinImageGen(output)
            result = ArcoRealAdapter(provider).generate(
                invocation_plan=plan,
                reference_contracts=selected,
                reference_image_paths=[reference["path"] for reference in selected],
            )
            self.assertEqual(result, output.resolve())
            self.assertEqual(
                provider.calls[0],
                build_builtin_imagegen_args(plan),
            )
        self.assertEqual(
            {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected},
            before,
        )

    def test_published_selector_excludes_profile_for_upper_body(self):
        assets = yaml.safe_load((ROOT / "character" / "assets.yaml").read_text(encoding="utf-8"))
        config = yaml.safe_load((ROOT / "runtime" / "generation.yaml").read_text(encoding="utf-8"))

        selected = select_references(
            root=ROOT,
            managed_assets=assets["assets"],
            requested_roles=["identity_reference", "outfit_reference"],
            selected_variant_id="casual-outfit",
            exposure_profile="upper_body",
            variant_required=True,
            config=config,
        )

        self.assertEqual(
            [reference["asset_id"] for reference in selected],
            ["identity-p01", "casual-outfit-primary"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
