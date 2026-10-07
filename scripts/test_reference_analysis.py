"""Production integration tests for split inputs, confirmation and one repair."""
from copy import deepcopy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import yaml
sys.path.insert(0, str(Path(__file__).resolve().parent))
from arco_production import (plan_production_generation, run_production_generation,
                             run_automatic_reference_repair)
from arco_real_adapter import ArcoRealAdapter
from reference_analysis import DETAILS, digest, file_hash, select_split_references
from reference_runtime import (ReferenceRuntimeError, resolve_style_context,
                               resolve_style_references, select_references,
                               build_builtin_imagegen_args)

PROJECT = Path(__file__).resolve().parents[1]


def analysis_request(root, profile="upper_body", expression_id="arco-expr-frontal-001"):
    assets = yaml.safe_load((root / "character/assets.yaml").read_text(encoding="utf-8"))["assets"]
    analysis = {"schema_version": 1, "expression": {"library_asset_id": expression_id}}
    refs = select_split_references(root=root, assets=assets, analysis=analysis,
                                   profile=profile, variant_id="casual-outfit")
    ids = [ref["reference_id"] for ref in refs]
    for dimension, fields in DETAILS.items():
        entry = analysis.setdefault(dimension, {})
        entry.update({"source_reference_ids": list(ids), "observations": "Visible reference evidence reviewed by the caller.",
                      "transfer_target": "Preserve the approved " + dimension + " relationships."})
        entry.update({field: "Observed " + field + " relationship; preserve the approved target." for field in fields})
    analysis["expression"]["library_adjustments"] = "Lower eyelids and raise inner eyebrows; retain Arco eye construction."
    context = resolve_style_context(resolved_style_references=resolve_style_references(refs), style_briefs=[],
                                    official_style_baseline=yaml.safe_load((root / "character/style-baseline.yaml").read_text(encoding="utf-8")))
    analysis.update(sources=list(ids), allowed_adjustments=["Adapt expression without changing facial structure."],
                    uncertainties=[], style={"context_sha256": digest(context)})
    return {"base_prompt": "Arco in her approved casual outfit, arm reaching toward the camera.",
            "variant_id": "casual-outfit", "exposure_profile": profile, "reference_analysis": analysis}


class Provider:
    def __init__(self, root):
        self.root, self.calls = root, []
    def __call__(self, **arguments):
        self.calls.append(arguments)
        path = self.root / f"output-{len(self.calls)}.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + str(len(self.calls)).encode())
        return path


class ReferenceAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.holder = tempfile.TemporaryDirectory(prefix="arco-split-tests-")
        cls.root = Path(cls.holder.name)
        for directory in ("character", "variants", "runtime"):
            shutil.copytree(PROJECT / directory, cls.root / directory)
        assets = yaml.safe_load((cls.root / "character/assets.yaml").read_text(encoding="utf-8"))["assets"]
        for asset in assets:
            destination = cls.root / asset["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT / asset["path"], destination)
    @classmethod
    def tearDownClass(cls):
        cls.holder.cleanup()
    def setUp(self):
        output = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(output.cleanup)
        self.provider = Provider(Path(output.name))
        self.request = analysis_request(self.root)
    def approve(self, request=None):
        request = deepcopy(request or self.request)
        plan = plan_production_generation(request, root=self.root)
        request["analysis_confirmation"] = {"user_confirmed": True,
            "plan_sha256": plan.analysis_preview["plan_sha256"], "user_message": "Human confirmed this exact preview."}
        return request, plan
    def assert_code(self, code, function):
        with self.assertRaises(ReferenceRuntimeError) as error:
            function()
        self.assertEqual(error.exception.code, code)
    def generate(self, request):
        return run_production_generation(request, builtin_image_gen=self.provider, root=self.root)
    def review(self, result, failed="expression"):
        return result.with_reference_review({"plan_sha256": result.analysis_preview["plan_sha256"],
            "output_sha256": file_hash(result.output_path), "inspected_original_size": True,
            "checks": {dimension: {"status": "FAIL" if dimension == failed else "PASS",
                                  "evidence": "Observed comparison to approved references."}
                       for dimension in ("identity", "composition_pose", "expression", "lighting_style")}})

    def test_planning_is_read_only_and_deduplicates_default_clothed_inputs(self):
        before = deepcopy(self.request)
        plan = plan_production_generation(self.request, root=self.root)
        self.assertEqual([ref["role"] for ref in plan.selected_references], ["outfit_reference", "face_reference"])
        self.assertIn("identity_reference", plan.selected_references[0]["duties"])
        self.assertEqual(len(set(plan.invocation_plan["referenced_image_paths"])), 2)
        self.assertEqual(self.request, before)
        self.assertNotIn("p01-full.png", " ".join(plan.invocation_plan["referenced_image_paths"]))
        self.assertEqual(self.provider.calls, [])
        self.assertIn("shadow_edges", plan.prompt)
        self.assertIn("Lower eyelids", plan.prompt)

    def test_default_clothed_identity_matches_view_for_each_supported_profile(self):
        for profile in ("portrait", "upper_body", "full_body"):
            for expression, identity in (
                ("arco-expr-frontal-001", "casual-outfit-crossed-arms-evidence"),
                ("arco-expr-oblique-017", "casual-outfit-open-arms-no-horns-evidence"),
            ):
                with self.subTest(profile=profile, expression=expression):
                    request = analysis_request(self.root, profile, expression)
                    approved, plan = self.approve(request)
                    refs = plan.selected_references
                    self.assertEqual(refs[0]["asset_id"], identity)
                    self.assertIn("body_proportions", refs[0]["inherit"])
                    self.assertEqual(len(refs), 2)
                    self.assertTrue(all(ref.get("asset_type") != "body_base" for ref in refs))
                    self.assertEqual(set(plan.analysis_preview["image_hashes"]),
                                     set(plan.invocation_plan["referenced_image_paths"]))
                    self.generate(approved)
                    self.assertEqual(self.provider.calls[-1]["referenced_image_paths"],
                                     plan.invocation_plan["referenced_image_paths"])

    def test_default_cross_variant_identity_excludes_clothing_inheritance(self):
        request = self.dressed_school_request()
        request["arco_references"] = []
        request["reference_analysis"]["identity"].pop("body_reference_mode")
        request["reference_analysis"]["identity"].pop("body_reference_reason")
        approved, plan = self.approve(request)
        identity, outfit, face = plan.selected_references
        self.assertEqual(identity["asset_id"], "casual-outfit-open-arms-no-horns-evidence")
        self.assertIn("body_proportions", identity["inherit"])
        self.assertTrue({"outfit", "variant"} <= set(identity["do_not_inherit"]))
        self.assertFalse({"outfit", "variant"} & set(identity["inherit"]))
        self.assertEqual(outfit["asset_id"], "school-uniform-primary")
        self.assertEqual(outfit["duties"], ["outfit_reference"])
        self.generate(approved)
        self.assertEqual(len(self.provider.calls[-1]["referenced_image_paths"]), 3)

    def test_body_base_mode_and_explicit_assets_are_rejected(self):
        request = deepcopy(self.request)
        request["reference_analysis"]["identity"]["body_reference_mode"] = "body_base"
        self.assert_code("BODY_BASE_NOT_ALLOWED", lambda: self.generate(request))
        for asset_id in ("identity-body-c07", "identity-body-c13", "identity-body-c14"):
            with self.subTest(asset_id=asset_id):
                request = deepcopy(self.request)
                request["arco_references"] = [{"asset_id": asset_id, "role": "identity_reference"}]
                self.assert_code("BODY_BASE_NOT_ALLOWED", lambda: self.generate(request))
        self.assertFalse(self.provider.calls)

    def test_body_base_copy_is_rejected_by_selector_and_serializer(self):
        path = self.provider.root / "renamed-reference.png"
        shutil.copy2(self.root / "assets/arco/identity/body-evidence/identity-body-c07.png", path)
        external = {"reference_id": "renamed-how", "source_scope": "external_how",
            "path": str(path), "role": "pose_reference", "authority": "user_request_external",
            "inherit": ["pose"], "do_not_inherit": ["identity"]}
        request = deepcopy(self.request)
        request["external_references"] = [external]
        self.assert_code("BODY_BASE_NOT_ALLOWED", lambda: self.generate(request))
        self.assert_code("BODY_BASE_NOT_ALLOWED", lambda: build_builtin_imagegen_args({
            "provider": "builtin_image_gen", "mode": "reference_conditioned",
            "prompt": "Arco", "referenced_image_paths": [str(path)]}))
        self.assertFalse(self.provider.calls)

    def test_missing_default_dressed_identity_does_not_use_another_body_asset(self):
        assets = yaml.safe_load((self.root / "character/assets.yaml").read_text(encoding="utf-8"))["assets"]
        assets = deepcopy(assets)
        next(asset for asset in assets if asset["asset_id"] == "casual-outfit-crossed-arms-evidence")["can_be_generation_reference"] = False
        self.assert_code("SPLIT_REFERENCE_INCOMPLETE", lambda: select_split_references(
            root=self.root, assets=assets, analysis=self.request["reference_analysis"],
            profile="upper_body", variant_id="casual-outfit"))

    def test_analysis_must_bind_to_the_replacement_identity_reference(self):
        request = self.dressed_school_request()
        request["reference_analysis"]["identity"]["source_reference_ids"].remove(
            "casual-outfit-open-arms-no-horns-evidence")
        self.assert_code("REFERENCE_ANALYSIS_SOURCE_MISMATCH", lambda: self.generate(request))
        request = deepcopy(self.request)
        request["reference_analysis"]["sources"].append("identity-body-c13")
        self.assert_code("REFERENCE_ANALYSIS_SOURCE_MISMATCH", lambda: self.generate(request))
        self.assertFalse(self.provider.calls)

    def test_portrait_omits_body_but_keeps_face_and_hair_layers(self):
        plan = plan_production_generation(analysis_request(self.root, "portrait"), root=self.root)
        self.assertEqual(len(plan.selected_references), 2)
        self.assertEqual({ref["role"] for ref in plan.selected_references}, {"outfit_reference", "face_reference"})

    def test_missing_confirmation_never_calls_provider(self):
        self.assert_code("ANALYSIS_CONFIRMATION_REQUIRED", lambda: self.generate(self.request))
        self.assertFalse(self.provider.calls)

    def test_confirmed_clothed_only_uses_dressed_identity_coverage(self):
        request = deepcopy(self.request)
        analysis = request["reference_analysis"]
        analysis["identity"].update(body_reference_mode="clothed_only", body_reference_reason="Human selected the dressed silhouette instead of the body layer.")
        body_ids = {ref["reference_id"] for ref in plan_production_generation(request=self.request, root=self.root).selected_references if ref.get("asset_type") == "body_base"}
        analysis["sources"] = [item for item in analysis["sources"] if item not in body_ids]
        for dimension in DETAILS:
            analysis[dimension]["source_reference_ids"] = [item for item in analysis[dimension]["source_reference_ids"] if item not in body_ids]
        approved, plan = self.approve(request)
        self.assertEqual(len(plan.selected_references), 2)
        self.assertTrue(all(ref.get("asset_type") != "body_base" for ref in plan.selected_references))
        self.assertIn("identity_reference", plan.selected_references[0]["duties"])
        self.generate(approved)
        self.assertEqual(len(self.provider.calls[0]["referenced_image_paths"]), 2)

    def test_clothed_only_requires_explained_selection(self):
        self.request["reference_analysis"]["identity"]["body_reference_mode"] = "clothed_only"
        self.assert_code("REFERENCE_ANALYSIS_INVALID", lambda: plan_production_generation(self.request, root=self.root))

    def dressed_school_request(self):
        request = deepcopy(self.request)
        request.update(variant_id="school-uniform", base_prompt="Arco wearing her approved school uniform.",
            arco_references=[
                {"asset_id": "casual-outfit-open-arms-no-horns-evidence", "role": "identity_reference"},
                {"asset_id": "school-uniform-primary", "role": "outfit_reference"},
                {"asset_id": "arco-expr-oblique-017", "role": "face_reference"}])
        analysis = request["reference_analysis"]
        analysis["identity"].update(body_reference_mode="clothed_only",
            body_reference_reason="Human excluded body layers and selected a permitted dressed identity image.")
        analysis["expression"]["library_asset_id"] = "arco-expr-oblique-017"
        ids = [ref["asset_id"] for ref in request["arco_references"]]
        analysis["sources"] = ids
        for dimension in DETAILS:
            analysis[dimension]["source_reference_ids"] = list(ids)
        return request

    def test_separate_dressed_identity_keeps_school_uniform_authority(self):
        approved, plan = self.approve(self.dressed_school_request())
        identity, outfit, face = plan.selected_references
        self.assertEqual(identity["asset_id"], "casual-outfit-open-arms-no-horns-evidence")
        self.assertNotIn("outfit", identity["inherit"])
        self.assertTrue({"outfit", "variant"} <= set(identity["do_not_inherit"]))
        self.assertEqual(outfit["variant_id"], "school-uniform")
        self.assertEqual(outfit["duties"], ["outfit_reference"])
        self.assertEqual(face["asset_id"], "arco-expr-oblique-017")
        self.assertTrue(all(ref.get("asset_type") != "body_base" for ref in plan.selected_references))
        self.generate(approved)
        self.assertEqual(self.provider.calls[0]["referenced_image_paths"], plan.invocation_plan["referenced_image_paths"])
        self.assertEqual(len(self.provider.calls[0]["referenced_image_paths"]), 3)

    def test_dressed_identity_refuses_body_base_without_fallback(self):
        request = self.dressed_school_request()
        request["arco_references"][0]["asset_id"] = "identity-body-c07"
        self.assert_code("BODY_BASE_NOT_ALLOWED", lambda: plan_production_generation(request, root=self.root))
        self.assertFalse(self.provider.calls)

    def test_dressed_identity_still_requires_permission_view_and_coverage(self):
        request = self.dressed_school_request()
        assets = yaml.safe_load((self.root / "character/assets.yaml").read_text(encoding="utf-8"))["assets"]
        for invalid in ("permission", "view", "coverage"):
            with self.subTest(invalid=invalid):
                changed = deepcopy(assets)
                identity = next(asset for asset in changed if asset["asset_id"] == "casual-outfit-open-arms-no-horns-evidence")
                if invalid == "permission":
                    identity["generation_reference"]["supported_roles"] = ["outfit_reference"]
                elif invalid == "view":
                    identity["view_class"] = "front"
                else:
                    identity["generation_reference"]["coverage"]["visible_fields"] = ["hair", "face"]
                if invalid == "coverage":
                    from reference_runtime import compute_request_reference_readiness
                    refs = select_split_references(root=self.root, assets=changed, analysis=request["reference_analysis"],
                        profile="upper_body", variant_id="school-uniform", descriptors=request["arco_references"])
                    readiness = compute_request_reference_readiness(exposure_profile="upper_body", references=refs,
                        variant_required=True, selected_variant_id="school-uniform")
                    self.assertNotEqual(readiness["status"], "READY")
                    self.assertIn("body.upper", readiness["missing_fields"])
                else:
                    self.assert_code("SPLIT_REFERENCE_INCOMPLETE", lambda: select_split_references(
                        root=self.root, assets=changed, analysis=request["reference_analysis"],
                        profile="upper_body", variant_id="school-uniform", descriptors=request["arco_references"]))

    def test_same_dressed_identity_and_outfit_is_only_sent_once(self):
        request = deepcopy(self.request)
        request["arco_references"] = [{"asset_id": "casual-outfit-crossed-arms-evidence", "role": role}
            for role in ("identity_reference", "outfit_reference")]
        analysis = request["reference_analysis"]
        analysis["identity"].update(body_reference_mode="clothed_only", body_reference_reason="Human selected one dressed silhouette.")
        ids = ["casual-outfit-crossed-arms-evidence", "arco-expr-frontal-001"]
        analysis["sources"] = ids
        for dimension in DETAILS:
            analysis[dimension]["source_reference_ids"] = list(ids)
        approved, plan = self.approve(request)
        self.assertEqual(len(plan.selected_references), 2)
        self.generate(approved)
        self.assertEqual(len(set(self.provider.calls[0]["referenced_image_paths"])), 2)

    def test_confirmed_plan_reaches_provider_without_internal_fields(self):
        request, _ = self.approve()
        result = self.generate(request)
        self.assertEqual(set(self.provider.calls[0]), {"prompt", "referenced_image_paths"})
        self.assertIsNone(result.visual_review)
        self.assertEqual(result.visual_review_status, "unchecked")

    def test_prompt_or_analysis_change_invalidates_confirmation(self):
        for key in ("base_prompt", "reference_analysis"):
            with self.subTest(key=key):
                request, _ = self.approve()
                if key == "base_prompt":
                    request[key] += " Different background."
                else:
                    request[key]["lighting"]["shadow_edges"] = "Different edge target."
                self.assert_code("ANALYSIS_CONFIRMATION_STALE", lambda: self.generate(request))
        self.assertFalse(self.provider.calls)

    def test_adapter_rejects_changed_image_after_confirmation(self):
        request, plan = self.approve()
        invocation = deepcopy(plan.invocation_plan)
        invocation["analysis_confirmation"] = request["analysis_confirmation"]
        path = Path(plan.selected_references[-1]["path"])
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"changed")
            self.assert_code("ANALYSIS_CONFIRMATION_STALE", lambda: ArcoRealAdapter(self.provider).generate(
                invocation_plan=invocation, reference_contracts=plan.selected_references,
                reference_image_paths=plan.invocation_plan["referenced_image_paths"]))
        finally:
            path.write_bytes(original)
        self.assertFalse(self.provider.calls)

    def test_missing_lighting_relationship_is_rejected(self):
        self.request["reference_analysis"]["lighting"].pop("shadow_edges")
        self.assert_code("REFERENCE_ANALYSIS_INVALID", lambda: plan_production_generation(self.request, root=self.root))

    def test_no_back_evidence_does_not_fall_back_to_full_standing_art(self):
        self.request["exposure_profile"] = "back_view"
        self.assert_code("SPLIT_REFERENCE_INCOMPLETE", lambda: plan_production_generation(self.request, root=self.root))

    def test_failed_review_can_repair_once_only(self):
        request, _ = self.approve()
        first = self.review(self.generate(request))
        repaired = run_automatic_reference_repair(first, source_request=request, builtin_image_gen=self.provider, root=self.root)
        self.assertEqual(repaired.automatic_repair_count, 1)
        self.assertEqual(len(self.provider.calls), 2)
        self.assert_code("AUTOMATIC_REPAIR_LIMIT", lambda: run_automatic_reference_repair(
            self.review(repaired), source_request=request, builtin_image_gen=self.provider, root=self.root))
        self.assert_code("AUTOMATIC_REPAIR_LIMIT", lambda: run_automatic_reference_repair(
            first, source_request=request, builtin_image_gen=self.provider, root=self.root))

    def test_identity_failure_rebuild_excludes_bad_output(self):
        request, _ = self.approve()
        first = self.review(self.generate(request), "identity")
        repaired = run_automatic_reference_repair(first, source_request=request, builtin_image_gen=self.provider, root=self.root)
        self.assertNotIn(str(first.output_path), self.provider.calls[-1]["referenced_image_paths"])
        self.assertEqual(repaired.reset_triggered_from_output, first.output_id)

    def test_unverified_check_cannot_report_pass(self):
        request, _ = self.approve()
        first = self.generate(request)
        review = self.review(first).visual_review
        review["checks"]["expression"]["status"] = "UNVERIFIED"
        checked = first.with_reference_review(review)
        self.assertEqual(checked.visual_review["status"], "UNVERIFIED")
        self.assertFalse(checked.visual_review["user_accepted"])

    def test_two_external_inputs_fit_five_image_budget(self):
        request = self.dressed_school_request()
        references = []
        for index in range(2):
            path = self.provider.root / f"external-{index}.png"
            path.write_bytes(b"test-reference")
            references.append({"reference_id": f"how-{index}", "source_scope": "external_how",
                "path": str(path), "role": "pose_reference", "authority": "user_request_external",
                "inherit": ["pose", "composition", "lighting", "expression"],
                "do_not_inherit": ["identity", "hair", "eyes", "face", "body_proportions", "outfit", "variant"]})
        request["external_references"] = references
        request["reference_analysis"]["sources"].extend(ref["reference_id"] for ref in references)
        for key in ("composition", "pose", "expression", "lighting"):
            request["reference_analysis"][key]["source_reference_ids"] = ["how-0", "how-1"]
        approved, plan = self.approve(request)
        self.assertEqual(len(plan.invocation_plan["referenced_image_paths"]), 5)
        first = self.review(self.generate(approved))
        repaired = run_automatic_reference_repair(first, source_request=approved, builtin_image_gen=self.provider, root=self.root)
        self.assertEqual(len(self.provider.calls[-1]["referenced_image_paths"]), 5)
        self.assertNotIn(str(first.output_path), self.provider.calls[-1]["referenced_image_paths"])

    def test_three_external_inputs_fail_before_provider(self):
        request = deepcopy(self.request)
        request["external_references"] = [{"reference_id": f"how-{index}", "source_scope": "external_how",
            "path": str(self.provider.root / f"external-{index}.png"), "role": "pose_reference",
            "authority": "user_request_external", "inherit": ["pose"], "do_not_inherit": ["identity"]}
            for index in range(3)]
        self.assert_code("REFERENCE_LIMIT_EXCEEDED", lambda: self.generate(request))
        self.assertFalse(self.provider.calls)

    def test_duplicate_physical_image_is_uploaded_once(self):
        plan = plan_production_generation(self.request, root=self.root)
        refs = list(plan.selected_references)
        duplicate = deepcopy(refs[-1])
        selected = select_references(root=self.root, managed_assets=[], requested_roles=[],
            request_scoped_references=[*refs, duplicate], config={"max_local_arco_references": 3,
                "max_external_references": 2, "max_total_image_inputs": 5})
        self.assertEqual(len(selected), 2)

    def test_generic_review_cannot_claim_split_result_passed(self):
        request, _ = self.approve()
        first = self.generate(request)
        self.assert_code("VISUAL_REVIEW_INVALID", lambda: first.with_visual_review("passed"))

    def test_tampered_prompt_is_rejected_at_adapter(self):
        request, plan = self.approve()
        invocation = deepcopy(plan.invocation_plan)
        invocation["analysis_confirmation"] = request["analysis_confirmation"]
        invocation["prompt"] += " Change approved lighting."
        self.assert_code("ANALYSIS_CONFIRMATION_STALE", lambda: ArcoRealAdapter(self.provider).generate(
            invocation_plan=invocation, reference_contracts=plan.selected_references,
            reference_image_paths=plan.invocation_plan["referenced_image_paths"]))


if __name__ == "__main__":
    unittest.main()
