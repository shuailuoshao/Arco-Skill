from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from reference_runtime import (
    ReferenceRuntimeError,
    build_builtin_imagegen_args,
    build_invocation_plan,
    compile_prompt,
    compute_global_reference_readiness,
    compute_request_reference_readiness,
    generation_allowed,
    resolve_identity_fact_prompt_fragments,
    resolve_mode,
    select_references,
    validate_reference_contract,
)


CONFIG = {
    "generation": {
        "max_local_arco_references": 3,
        "max_external_references": 2,
        "max_total_image_inputs": 4,
    }
}


def request_ref(reference_id="request-arco-1", *, profile="portrait", fields=None, view="front", path="C:/request/arco.png"):
    return {
        "reference_id": reference_id,
        "request_reference_id": reference_id,
        "source_scope": "request_scoped_arco",
        "path": path,
        "role": "identity_reference",
        "authority": "user_request",
        "persistent": False,
        "calibrating": False,
        "inherit": ["identity"],
        "do_not_inherit": ["scene", "lighting"],
        "coverage": {
            "profiles": [profile],
            "visible_fields": fields or ["identity", "hair", "eyes", "face"],
            "view_angles": [view],
            "occluded_fields": [],
        },
    }


def external_ref(reference_id="external-1", role="pose_reference", path="C:/request/pose.png"):
    return {
        "reference_id": reference_id,
        "source_scope": "external_how",
        "path": path,
        "role": role,
        "authority": "user_request_external",
        "persistent": False,
        "calibrating": False,
        "inherit": ["pose", "composition"],
        "do_not_inherit": ["identity", "hair", "eyes", "face", "body_proportions", "outfit", "variant"],
        "coverage": {},
    }


def managed_ref(
    root,
    asset_id,
    *,
    role,
    priority="primary",
    variant_id=None,
    fields=None,
    view="front",
    inheritance=None,
):
    path = root / "assets" / f"{asset_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asset_id.encode("utf-8")
    path.write_bytes(payload)
    return {
        "asset_id": asset_id,
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "asset_status": "VERIFIED",
        "roles": ["variant_evidence" if role == "outfit_reference" else "identity_evidence"],
        "variant_id": variant_id,
        "can_be_generation_reference": True,
        "generation_reference": {
            "priority": priority,
            "supported_roles": [role],
            "preferred_for": ["portrait", "upper_body", "full_body"],
            "excluded_for": ["back_view"],
            "coverage": {
                "visible_fields": fields or [],
                "view_angles": [view],
                "occluded_fields": [],
            },
            "inheritance": inheritance or ({"outfit": "inherit", "identity": "do_not_inherit"} if role == "outfit_reference" else {"identity": "inherit", "outfit": "do_not_inherit"}),
        },
    }


class CaptureAdapter:
    def __init__(self):
        self.actual_args = None

    def invoke(self, args):
        self.actual_args = copy.deepcopy(args)


class RuntimeTests(unittest.TestCase):
    def assertCode(self, code, callback):
        with self.assertRaises(ReferenceRuntimeError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_current_global_readiness_is_incomplete(self):
        result = compute_global_reference_readiness({"revision": 0}, {"variants": []}, [])
        self.assertEqual(result, {"identity": "INCOMPLETE", "identity_profiles": {"portrait": "INCOMPLETE", "upper_body": "INCOMPLETE", "full_body": "INCOMPLETE", "back_view": "INCOMPLETE"}, "variants": {}, "variant_profiles": {}, "overall": "INCOMPLETE"})

    def test_request_scoped_never_changes_global(self):
        reference = request_ref()
        global_result = compute_global_reference_readiness({"revision": 0}, {"variants": []}, [])
        request_result = compute_request_reference_readiness(exposure_profile="portrait", references=[reference])
        self.assertEqual(global_result["overall"], "INCOMPLETE")
        self.assertEqual(request_result["status"], "READY")

    def test_request_coverage_profiles(self):
        portrait = request_ref()
        self.assertEqual(compute_request_reference_readiness(exposure_profile="full_body", references=[portrait])["status"], "PARTIAL")
        self.assertEqual(compute_request_reference_readiness(exposure_profile="back_view", references=[portrait])["status"], "INCOMPLETE")
        full = request_ref(profile="full_body", fields=["identity", "hair", "eyes", "face", "body.upper", "body.full", "outfit.upper", "outfit.lower", "footwear"])
        self.assertEqual(compute_request_reference_readiness(exposure_profile="full_body", references=[full])["status"], "READY")
        back = request_ref(profile="back_view", fields=["identity", "hair.back", "body.back", "outfit.back"], view="back")
        self.assertEqual(compute_request_reference_readiness(exposure_profile="back_view", references=[back])["status"], "READY")
        upper = request_ref(profile="upper_body", fields=["identity", "hair", "eyes", "face", "body.upper", "outfit.upper"])
        self.assertEqual(compute_request_reference_readiness(exposure_profile="upper_body", references=[upper])["status"], "READY")

    def test_variant_coverage_is_required(self):
        reference = request_ref()
        result = compute_request_reference_readiness(exposure_profile="portrait", references=[reference], variant_required=True)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertIn("variant.visible_headwear_accessories", result["missing_fields"])

    def test_global_variant_readiness_is_profile_aware(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            primary = managed_ref(
                root,
                "casual-primary",
                role="outfit_reference",
                variant_id="casual-outfit",
                fields=[
                    "variant.visible_headwear_accessories",
                    "variant.upper_body_outfit",
                    "variant.full_outfit",
                    "variant.footwear",
                ],
                view="three_quarter_right",
            )
            result = compute_global_reference_readiness(
                {"revision": 1},
                {"variants": [{"variant_id": "casual-outfit"}]},
                [primary],
            )
            self.assertEqual(result["variants"]["casual-outfit"], "PARTIAL")
            self.assertEqual(
                result["variant_profiles"]["casual-outfit"],
                {
                    "portrait": "READY",
                    "upper_body": "READY",
                    "full_body": "READY",
                    "back_view": "INCOMPLETE",
                },
            )
            duplicate = managed_ref(root, "casual-primary-duplicate", role="outfit_reference", variant_id="casual-outfit", fields=["variant.full_outfit", "variant.footwear"])
            conflicted = compute_global_reference_readiness(
                {"revision": 1},
                {"variants": [{"variant_id": "casual-outfit"}]},
                [primary, duplicate],
            )
            self.assertEqual(conflicted["variants"]["casual-outfit"], "CONFLICT")
            self.assertEqual(conflicted["overall"], "CONFLICT")

    def test_selector_requires_and_filters_selected_variant(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            other = managed_ref(root, "aaa-other-primary", role="outfit_reference", variant_id="other", fields=["variant.full_outfit", "variant.footwear"])
            casual = managed_ref(root, "casual-primary", role="outfit_reference", variant_id="casual-outfit", fields=["variant.full_outfit", "variant.footwear"])
            assets = [other, casual]
            self.assertCode(
                "VARIANT_SELECTION_REQUIRED",
                lambda: select_references(root=root, managed_assets=assets, requested_roles=["outfit_reference"], exposure_profile="full_body", variant_required=True, config=CONFIG),
            )
            selected = select_references(
                root=root,
                managed_assets=assets,
                requested_roles=["outfit_reference"],
                selected_variant_id="casual-outfit",
                exposure_profile="full_body",
                variant_required=True,
                config=CONFIG,
            )
            self.assertEqual([item["asset_id"] for item in selected], ["casual-primary"])
            self.assertEqual(selected[0]["variant_id"], "casual-outfit")

    def test_selector_fails_closed_for_missing_or_ambiguous_variant_primary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            supplemental = managed_ref(root, "casual-supplemental", role="outfit_reference", priority="supplemental", variant_id="casual-outfit", fields=["variant.full_outfit"])
            self.assertCode(
                "VARIANT_PRIMARY_MISSING",
                lambda: select_references(root=root, managed_assets=[supplemental], requested_roles=["outfit_reference"], selected_variant_id="casual-outfit", exposure_profile="full_body", variant_required=True, config=CONFIG),
            )
            first = managed_ref(root, "casual-primary-a", role="outfit_reference", variant_id="casual-outfit", fields=["variant.full_outfit", "variant.footwear"])
            second = managed_ref(root, "casual-primary-b", role="outfit_reference", variant_id="casual-outfit", fields=["variant.full_outfit", "variant.footwear"])
            self.assertCode(
                "VARIANT_PRIMARY_CONFLICT",
                lambda: select_references(root=root, managed_assets=[first, second], requested_roles=["outfit_reference"], selected_variant_id="casual-outfit", exposure_profile="full_body", variant_required=True, config=CONFIG),
            )
            self.assertCode(
                "VARIANT_REFERENCE_NOT_FOUND",
                lambda: select_references(root=root, managed_assets=[first], requested_roles=["outfit_reference"], selected_variant_id="unknown", exposure_profile="full_body", variant_required=True, config=CONFIG),
            )

    def test_identity_and_outfit_coverage_are_selected_by_role(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity = managed_ref(root, "identity-primary", role="identity_reference", fields=["identity", "hair", "eyes", "face"])
            outfit = managed_ref(root, "casual-primary", role="outfit_reference", variant_id="casual-outfit", fields=["variant.full_outfit", "variant.footwear"])
            irrelevant = managed_ref(root, "identity-supplemental", role="identity_reference", priority="supplemental", fields=["variant.full_outfit", "variant.footwear"])
            selected = select_references(
                root=root,
                managed_assets=[identity, outfit, irrelevant],
                requested_roles=["identity_reference", "outfit_reference"],
                selected_variant_id="casual-outfit",
                exposure_profile="portrait",
                variant_required=True,
                config=CONFIG,
            )
            self.assertEqual([item["asset_id"] for item in selected], ["identity-primary", "casual-primary"])
            self.assertEqual(selected[0]["inherit"], ["identity"])
            self.assertEqual(selected[1]["inherit"], ["outfit"])

    def test_request_readiness_rejects_cross_variant_contract(self):
        reference = request_ref()
        outfit = request_ref("wrong-outfit", fields=["variant.upper_body_outfit"])
        outfit.update(role="outfit_reference", variant_id="other-outfit", inherit=["outfit"], do_not_inherit=["identity"])
        result = compute_request_reference_readiness(
            exposure_profile="upper_body",
            references=[reference, outfit],
            variant_required=True,
            selected_variant_id="casual-outfit",
        )
        self.assertEqual(result["status"], "CONFLICT")
        self.assertEqual(result["conflicting_reference_ids"], ["wrong-outfit"])

    def test_identity_variant_external_adapter_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity = managed_ref(root, "identity-primary", role="identity_reference", fields=["identity", "hair", "eyes", "face"])
            casual = managed_ref(root, "casual-primary", role="outfit_reference", variant_id="casual-outfit", fields=["variant.upper_body_outfit"])
            other = managed_ref(root, "other-primary", role="outfit_reference", variant_id="other-outfit", fields=["variant.upper_body_outfit"])
            external = external_ref("external-pose", path="C:/request/pose.png")
            selected = select_references(
                root=root,
                managed_assets=[other, identity, casual],
                requested_roles=["identity_reference", "outfit_reference"],
                selected_variant_id="casual-outfit",
                exposure_profile="upper_body",
                variant_required=True,
                external_references=[external],
                config=CONFIG,
            )
            plan = build_invocation_plan(mode="reference_conditioned", prompt="Arco in casual outfit", selected_references=selected)
            args = build_builtin_imagegen_args(plan)
            adapter = CaptureAdapter()
            adapter.invoke(args)
            self.assertEqual(
                adapter.actual_args["referenced_image_paths"],
                [
                    str((root / identity["path"]).resolve()),
                    str((root / casual["path"]).resolve()),
                    "C:/request/pose.png",
                ],
            )
            self.assertNotIn(str((root / other["path"]).resolve()), adapter.actual_args["referenced_image_paths"])

    def test_incomplete_and_conflict(self):
        self.assertEqual(compute_request_reference_readiness(exposure_profile="portrait", references=[])["status"], "INCOMPLETE")
        self.assertEqual(compute_request_reference_readiness(exposure_profile="portrait", references=[], conflict=True)["status"], "CONFLICT")

    def test_mode_resolution(self):
        self.assertEqual(resolve_mode(explicit_mode="prompt_only", wants_generation=True, request_reference_readiness="READY")["mode"], "prompt_only")
        auto = resolve_mode(explicit_mode=None, wants_generation=True, request_reference_readiness="INCOMPLETE")
        self.assertEqual((auto["mode"], auto["decision"]), ("prompt_only", "FALLBACK"))
        forced = resolve_mode(explicit_mode="reference_conditioned", wants_generation=True, request_reference_readiness="INCOMPLETE")
        self.assertEqual((forced["mode"], forced["decision"]), ("reference_conditioned", "REVIEWER"))

    def test_permission_missing_is_false_and_layers_are_denied(self):
        self.assertFalse(generation_allowed({"roles": ["identity_evidence"]}))
        self.assertFalse(generation_allowed({"roles": ["expression_evidence"], "can_be_generation_reference": True, "generation_reference": {"supported_roles": ["identity_reference"]}}))
        self.assertFalse(generation_allowed({"asset_type": "body_base", "roles": ["body_evidence"], "can_be_generation_reference": True, "generation_reference": {"supported_roles": ["identity_reference"]}}))
        self.assertFalse(generation_allowed({"asset_type": "faceless_composite", "roles": ["identity_evidence"], "can_be_generation_reference": True, "generation_reference": {"supported_roles": ["identity_reference"]}}))

    def test_request_scope_and_external_who_rules(self):
        invalid = request_ref()
        invalid["asset_id"] = "forbidden"
        self.assertCode("REQUEST_REFERENCE_HAS_ASSET_ID", lambda: validate_reference_contract(invalid))
        polluted = external_ref()
        polluted["do_not_inherit"].remove("hair")
        polluted["inherit"].append("hair")
        self.assertCode("EXTERNAL_IDENTITY_POLLUTION", lambda: validate_reference_contract(polluted))
        staged = external_ref(path="D:/learn/Arco/calibration/staging/x/a.png")
        self.assertCode("UNPUBLISHED_ASSET", lambda: validate_reference_contract(staged))

    def test_reference_limits(self):
        refs = [request_ref(f"r{i}", path=f"C:/request/{i}.png") for i in range(4)]
        self.assertCode("REFERENCE_LIMIT_EXCEEDED", lambda: select_references(root=Path.cwd(), managed_assets=[], requested_roles=[], request_scoped_references=refs, config=CONFIG))
        externals = [external_ref(f"e{i}", path=f"C:/request/e{i}.png") for i in range(3)]
        self.assertCode("REFERENCE_LIMIT_EXCEEDED", lambda: select_references(root=Path.cwd(), managed_assets=[], requested_roles=[], external_references=externals, config=CONFIG))
        combined = [request_ref(f"l{i}", path=f"C:/request/l{i}.png") for i in range(3)]
        self.assertCode("REFERENCE_LIMIT_EXCEEDED", lambda: select_references(root=Path.cwd(), managed_assets=[], requested_roles=[], request_scoped_references=combined, external_references=[external_ref("e") , external_ref("e2", path="C:/request/e2.png")], config=CONFIG))

    def test_prompt_only_args_have_prompt_only(self):
        plan = build_invocation_plan(mode="prompt_only", prompt="hello", selected_references=[])
        self.assertEqual(build_builtin_imagegen_args(plan), {"prompt": "hello"})

    def test_identity_body_fact_maps_when_working_fact_is_explicitly_allowed(self):
        identity = {"facts": [{"field_id": "body.chest_proportion", "value": "small-to-modest", "status": "UNCERTAIN"}]}
        resolved = resolve_identity_fact_prompt_fragments(
            identity, exposure_profile="portrait", allow_uncertain_working=True
        )
        self.assertEqual(len(resolved["fragments"]), 1)
        text = resolved["fragments"][0]["text"]
        for phrase in ("slim", "lightly built", "narrow upper torso", "small-to-modest", "understated bust"):
            self.assertIn(phrase, text)

    def test_uncertain_body_fact_is_omitted_without_working_fact_opt_in(self):
        identity = {"facts": [{"field_id": "body.chest_proportion", "value": "small-to-modest", "status": "UNCERTAIN"}]}
        resolved = resolve_identity_fact_prompt_fragments(identity, exposure_profile="upper_body")
        self.assertEqual(resolved["fragments"], [])
        self.assertEqual(resolved["omitted"][0]["reason"], "UNCERTAIN_NOT_OPTED_IN")

    def test_todo_body_fact_never_becomes_prompt_constraint(self):
        identity = {"facts": [{"field_id": "body.chest_proportion", "value": "small-to-modest", "status": "TODO_CALIBRATION"}]}
        resolved = resolve_identity_fact_prompt_fragments(
            identity, exposure_profile="full_body", allow_uncertain_working=True
        )
        self.assertEqual(resolved["fragments"], [])
        self.assertEqual(resolved["omitted"][0]["reason"], "TODO_CALIBRATION")

    def test_body_fact_routes_to_portrait_upper_and_full_but_not_back_view(self):
        identity = {"facts": [{"field_id": "body.chest_proportion", "value": "small-to-modest", "status": "UNCERTAIN"}]}
        for profile in ("portrait", "upper_body", "full_body"):
            self.assertTrue(
                resolve_identity_fact_prompt_fragments(
                    identity, exposure_profile=profile, allow_uncertain_working=True
                )["fragments"]
            )
        self.assertFalse(
            resolve_identity_fact_prompt_fragments(
                identity, exposure_profile="back_view", allow_uncertain_working=True
            )["fragments"]
        )

    def test_body_prompt_has_one_mild_constraint_and_no_banned_phrases(self):
        identity = {"facts": [{"field_id": "body.chest_proportion", "value": "small-to-modest", "status": "UNCERTAIN"}]}
        prompt = compile_prompt(
            base_prompt="Arco, portrait chest-up, gentle smile.",
            references=[],
            identity=identity,
            exposure_profile="portrait",
            allow_uncertain_working=True,
        ).lower()
        self.assertEqual(prompt.count("no exaggerated chest volume"), 1)
        for phrase in ("flat chest", "tiny breasts", "very small breasts"):
            self.assertNotIn(phrase, prompt)

    def test_body_prompt_deduplicates_duplicate_candidate_facts(self):
        identity = {"facts": [
            {"field_id": "body.chest_proportion", "value": "small-to-modest", "status": "UNCERTAIN"},
            {"field_id": "body.chest_proportion", "value": "small-to-modest", "status": "UNCERTAIN"},
        ]}
        resolved = resolve_identity_fact_prompt_fragments(
            identity, exposure_profile="portrait", allow_uncertain_working=True
        )
        self.assertEqual(len(resolved["fragments"]), 1)
        self.assertEqual(len(resolved["soft_constraints"]), 1)

    def test_portrait_body_prompt_does_not_change_reference_selection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity_ref = managed_ref(root, "identity-p01-crop", role="identity_reference", fields=["identity", "hair", "eyes", "face"])
            outfit_ref = managed_ref(root, "casual-outfit-primary", role="outfit_reference", variant_id="casual-outfit", fields=["variant.visible_headwear_accessories"])
            selected = select_references(
                root=root,
                managed_assets=[identity_ref, outfit_ref],
                requested_roles=["identity_reference", "outfit_reference"],
                selected_variant_id="casual-outfit",
                exposure_profile="portrait",
                variant_required=True,
                config=CONFIG,
            )
            self.assertEqual([ref["asset_id"] for ref in selected], ["identity-p01-crop", "casual-outfit-primary"])
            identity = {"facts": [{"field_id": "body.chest_proportion", "value": "small-to-modest", "status": "UNCERTAIN"}]}
            prompt = compile_prompt(
                base_prompt="Arco portrait chest-up.",
                references=selected,
                identity=identity,
                exposure_profile="portrait",
                allow_uncertain_working=True,
            )
            self.assertIn("identity-p01-crop", prompt)
            self.assertIn("casual-outfit-primary", prompt)
            self.assertNotIn("body-c07", prompt)

    def test_body_evidence_assets_never_reach_image_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            body = managed_ref(root, "identity-body-c07", role="identity_reference", fields=["body.upper"])
            body["asset_type"] = "body_base"
            body["roles"] = ["body_evidence"]
            body["can_be_generation_reference"] = False
            body.pop("generation_reference", None)
            identity = managed_ref(root, "identity-p01-crop", role="identity_reference", fields=["identity", "hair", "eyes", "face"])
            selected = select_references(root=root, managed_assets=[body, identity], requested_roles=["identity_reference"], exposure_profile="portrait", config=CONFIG)
            self.assertEqual([ref["asset_id"] for ref in selected], ["identity-p01-crop"])

    def test_conversation_transport_is_exact(self):
        refs = [request_ref("r1", path=None), external_ref("r2", path=None)]
        for ref in refs:
            ref["conversation_image"] = True
        plan = build_invocation_plan(mode="reference_conditioned", prompt="hello", selected_references=refs, num_last_images_to_include=2)
        self.assertEqual(build_builtin_imagegen_args(plan)["num_last_images_to_include"], 2)
        self.assertCode("IMAGE_INPUT_BUILD_FAILED", lambda: build_invocation_plan(mode="reference_conditioned", prompt="hello", selected_references=refs, num_last_images_to_include=3))

    def test_adapter_boundary_contains_real_selected_paths_only(self):
        a = request_ref("identity-a", path="C:/selected/A.png")
        b = dict(external_ref("pose-b", path="C:/selected/B.png"))
        selected = select_references(root=Path.cwd(), managed_assets=[], requested_roles=[], request_scoped_references=[a], external_references=[b], config=CONFIG)
        plan = build_invocation_plan(mode="reference_conditioned", prompt="Arco prompt", selected_references=selected)
        args = build_builtin_imagegen_args(plan)
        adapter = CaptureAdapter()
        adapter.invoke(args)
        self.assertEqual(adapter.actual_args, {"prompt": "Arco prompt", "referenced_image_paths": ["C:/selected/A.png", "C:/selected/B.png"]})
        serialized = repr(adapter.actual_args)
        self.assertNotIn("unselected", serialized)
        self.assertNotIn("expressions", serialized)
        self.assertNotIn("calibration/staging", serialized.replace("\\", "/").lower())

    def test_managed_selector_checks_hash_and_role(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "assets" / "identity.png"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"identity")
            asset = {
                "asset_id": "identity-primary", "path": "assets/identity.png", "sha256": hashlib.sha256(b"identity").hexdigest(),
                "asset_status": "VERIFIED", "roles": ["identity_evidence"], "can_be_generation_reference": True,
                "generation_reference": {"priority": "primary", "supported_roles": ["identity_reference"], "coverage": {"visible_fields": ["identity", "hair", "eyes", "face"], "view_angles": ["front"]}},
            }
            selected = select_references(root=root, managed_assets=[asset], requested_roles=["identity_reference"], config=CONFIG)
            self.assertEqual(selected[0]["asset_id"], "identity-primary")
            asset["sha256"] = "0" * 64
            self.assertCode("ASSET_HASH_MISMATCH", lambda: select_references(root=root, managed_assets=[asset], requested_roles=["identity_reference"], config=CONFIG))

    def test_selector_does_not_pick_unpermitted_or_random_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            random = root / "random-arco.png"
            random.write_bytes(b"not registered")
            asset = {"asset_id": "unapproved", "path": "random-arco.png", "asset_status": "VERIFIED", "roles": ["identity_evidence"], "sha256": hashlib.sha256(random.read_bytes()).hexdigest()}
            selected = select_references(root=root, managed_assets=[asset], requested_roles=["identity_reference"], config=CONFIG)
            self.assertEqual(selected, [])

    def test_runtime_planning_is_read_only_and_has_no_remote_client(self):
        source = (Path(__file__).parent / "reference_runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("import openai", source.lower())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            watched = root / "watched.txt"
            watched.write_text("stable", encoding="utf-8")
            before = hashlib.sha256(watched.read_bytes()).hexdigest()
            ref = request_ref(path=str(root / "request.png"))
            selected = select_references(root=root, managed_assets=[], requested_roles=[], request_scoped_references=[ref], config=CONFIG)
            plan = build_invocation_plan(mode="reference_conditioned", prompt="test", selected_references=selected)
            build_builtin_imagegen_args(plan)
            self.assertEqual(hashlib.sha256(watched.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
