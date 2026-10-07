"""Controlled-provider contract tests; fixture inspections do not assess pixels."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arco_real_adapter import ArcoRealAdapter
from arco_production import plan_production_generation, run_production_generation
from identity_preparation import plan_identity_calibration, create_identity_preparation
from outfit_design import SLOTS
from outfit_preparation import (plan_outfit_preparation, create_preparation, plan_remaining_views,
    approve_main_and_views, revise_preparation, adopt_primary)
from preparation_publication import plan_publication, stage_publication, publish_preparation, recover_publication, plan_reference_pack, record_pack_review
from preparation_support import (CHECKS, load, write, locked, workspace, run_candidate, record_visual_review, resume_preparation)
from reference_analysis import DETAILS, digest, file_hash, select_split_references
from reference_runtime import ReferenceRuntimeError, compute_request_reference_readiness, validate_reference_contract, resolve_style_context, resolve_style_references
from validate_library import validate

ROOT = Path(__file__).resolve().parents[1]


def copy_library(source: Path, target: Path):
    for directory in ("character", "variants", "runtime", "calibration/history"):
        shutil.copytree(source / directory, target / directory)
    shutil.copy2(source / "SKILL.md", target / "SKILL.md")
    for asset in load(source / "character/assets.yaml")["assets"]:
        destination = target / asset["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / asset["path"], destination)


def approval(preview):
    return {"user_confirmed": True, "preview_sha256": preview["preview_sha256"], "user_message": "Fixture human accepts the complete displayed preview."}


class ControlledProvider:
    def __init__(self, root):
        self.root, self.calls, self.fail = root, [], False
    def __call__(self, **arguments):
        self.calls.append(deepcopy(arguments))
        if self.fail:
            raise RuntimeError("Controlled provider failure")
        path = self.root / ("controlled-output-" + str(len(self.calls)) + ".png")
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + str(len(self.calls)).encode())
        return path


def inspected(root, pid, candidate, *, failed=None):
    review = {"output_sha256": candidate["sha256"], "plan_sha256": candidate["plan_sha256"], "inspected_original_size": True,
        "checks": {key: {"status": "FAIL" if key == failed else "PASS", "evidence": "Controlled fixture inspection: " + key} for key in CHECKS}}
    return record_visual_review(root=root, preparation_id=pid, candidate_id=candidate["candidate_id"], review=review)


def calibrate_back(root):
    before = deepcopy(load(root / "character/identity.yaml")["facts"])
    preview = plan_identity_calibration({"back_definition": {"schema_version": 1,
        "fixed_constraints": ["Preserve approved rear hair topology and body silhouette."],
        "completion_decisions": ["User-designed unseen rear hair connections."]}}, root=root)
    record = create_identity_preparation(preview, approval(preview), root=root)
    provider = ControlledProvider(root)
    candidate = run_candidate(root=root, preparation_id=record["preparation_id"], view_id="identity-back", adapter=ArcoRealAdapter(provider))
    inspected(root, record["preparation_id"], candidate)
    final = plan_publication(root=root, preparation_id=record["preparation_id"])
    stage_publication(final, approval(final), root=root)
    published = publish_preparation(root=root, preparation_id=record["preparation_id"])
    assert published["publication_state"] == "COMPLETE"
    assert load(root / "character/identity.yaml")["facts"] == before
    return record["preparation_id"]


def request(root, *, mixed=False, kind="partial", details=True):
    path = root / "product-top.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nexternal-top")
    sources = [{"source_id": "top", "path": str(path), "kind": kind, "view": "front upper only", "occlusions": "rear and lower half unseen",
        "source_note": "User image, visible garment only", "parts": [{"part_id": "shirt", "slot": "upper", "region": {"kind": "box", "xyxy": [0.1, 0.1, 0.9, 0.7]},
            "observations": "Visible blue shirt collar and short sleeves", "evidence_status": "UNCERTAIN"}]}]
    upper = {"description": "Original blue shirt", "origin": "source", "source_bindings": [{"source_id": "top", "part_id": "shirt"}], "fixed_features": ["Preserve blue color and original shirt length"]}
    parts = {slot: {"description": "Explicitly omitted " + slot, "origin": "omitted", "source_bindings": [], "fixed_features": []} for slot in SLOTS}
    parts["upper"] = upper
    parts["lower"] = {"description": "Approved gray knee-length skirt", "origin": "completion", "source_bindings": [], "fixed_features": ["Gray knee-length hem"], "decision_reason": "Complete the unseen lower half as selected by the user"}
    parts["footwear"] = {"description": "Plain black shoes", "origin": "completion", "source_bindings": [], "fixed_features": ["Black closed toe shoes"], "decision_reason": "Complete footwear explicitly"}
    combination = {"upper": deepcopy(upper["source_bindings"])}
    if mixed:
        assets = load(root / "character/assets.yaml")["assets"]
        lower_asset = next(a for a in assets if a.get("variant_id") == "school-uniform" and "outfit_reference" in (a.get("generation_reference") or {}).get("supported_roles", []))
        sources.append({"source_id": "bottom", "asset_id": lower_asset["asset_id"], "kind": "published_variant", "view": "front", "occlusions": "none for selected region", "source_note": "Published school uniform lower garment",
            "parts": [{"part_id": "skirt", "slot": "lower", "region": {"kind": "box", "xyxy": [0.2, 0.45, 0.8, 0.75]}, "observations": "School skirt unchanged", "evidence_status": "UNCERTAIN"}]})
        parts["lower"] = {"description": "Original school skirt", "origin": "source", "source_bindings": [{"source_id": "bottom", "part_id": "skirt"}], "fixed_features": ["Original skirt construction and color"]}
        combination["lower"] = deepcopy(parts["lower"]["source_bindings"])
    design = {"schema_version": 1, "design_id": "tucked", "parts": parts,
        "wearing_relations": ["Tuck the unchanged shirt into the skirt; skirt waist covers the hem."],
        "fixed_constraints": ["No unrelated jewelry or source-person hair"],
        "detail_requirements": [{"view_id": "detail-collar", "description": "Collar construction hidden by hair, garment-only detail on plain background", "source_ids": ["top"]}] if details else [],
        "gap_resolutions": {"rear": "Approved plain back panel without new trims"}}
    alternative = deepcopy(design)
    alternative["design_id"] = "untucked"
    alternative["wearing_relations"] = ["Leave original shirt untucked over the skirt waist."]
    return {"variant_id": "new-outfit", "name": "新套装", "sources": sources, "designs": [design, alternative], "selected_design_id": "tucked",
        "combination": combination, "gaps": [{"gap_id": "rear", "slot": "upper", "description": "Rear panel not visible", "critical": True}], "text_supplements": ["Preserve original cuts"]}


def production_request(root, variant_id, profile="full_body"):
    assets = load(root / "character/assets.yaml")["assets"]
    front_available = any(a.get("variant_id") == variant_id and a.get("view_class") in {"front", "frontal"} and a.get("can_be_generation_reference") for a in assets)
    expression = {"face_visible": False} if profile == "back_view" else {"library_asset_id": "arco-expr-frontal-001" if front_available else "arco-expr-oblique-001", "library_adjustments": "Preserve approved feature relationships."}
    analysis = {"schema_version": 1, "expression": expression, "identity": {"body_reference_mode": "clothed_only", "body_reference_reason": "Approved clothed identity."}}
    refs = select_split_references(root=root, assets=load(root / "character/assets.yaml")["assets"], analysis=analysis, profile=profile, variant_id=variant_id)
    ids = [r["reference_id"] for r in refs]
    for dimension in DETAILS:
        entry = analysis.setdefault(dimension, {})
        entry.update(source_reference_ids=ids, observations="Actual fixture view relationships.", transfer_target="Preserve the approved " + dimension + " relationships.")
        if not (profile == "back_view" and dimension == "expression"):
            entry.update({key: "Visible fixture relationship: " + key for key in DETAILS[dimension]})
    context = resolve_style_context(resolved_style_references=resolve_style_references(refs), style_briefs=[],
        official_style_baseline=load(root / "character/style-baseline.yaml"), user_style_overrides=None)
    analysis.update(sources=ids, style={"context_sha256": digest(context)}, allowed_adjustments=[], uncertainties=[])
    return {"base_prompt": "Arco standing with the selected approved outfit.", "variant_id": variant_id,
        "exposure_profile": profile, "reference_analysis": analysis}


class OutfitPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.base_temp.name)
        copy_library(ROOT, cls.base)
        cls.identity_preparation_id = calibrate_back(cls.base)
    @classmethod
    def tearDownClass(cls):
        cls.base_temp.cleanup()
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        copy_library(self.base, self.root)
        self.provider = ControlledProvider(self.root)
        self.adapter = ArcoRealAdapter(self.provider)
    def assert_code(self, code, fn):
        with self.assertRaises(ReferenceRuntimeError) as raised:
            fn()
        self.assertEqual(raised.exception.code, code)
    def create(self, **options):
        self.request = request(self.root, **options)
        preview = plan_outfit_preparation(self.request, root=self.root)
        self.record = create_preparation(preview, approval(preview), root=self.root)
        self.pid = self.record["preparation_id"]
        return self.record
    def generate(self, view="front", repair=False):
        return run_candidate(root=self.root, preparation_id=self.pid, view_id=view, adapter=self.adapter, repair=repair)
    def accept_main(self):
        main = self.generate()
        inspected(self.root, self.pid, main)
        preview = plan_remaining_views(root=self.root, preparation_id=self.pid, main_candidate_id=main["candidate_id"])
        approve_main_and_views(preview, approval(preview), root=self.root)
        return main
    def pack(self, **options):
        self.create(**options)
        return self.finish_pack()
    def finish_pack(self):
        self.accept_main()
        for view in self.record["required_views"]:
            if view != "front":
                candidate = self.generate(view)
                inspected(self.root, self.pid, candidate)
        pack = plan_reference_pack(root=self.root, preparation_id=self.pid)
        review = {"preview_sha256": pack["preview_sha256"], "inspected_original_size": True,
            "checks": {key: {"status": "PASS", "evidence": "Controlled full-pack comparison: " + key} for key in CHECKS}}
        record_pack_review(root=self.root, preparation_id=self.pid, preview=pack, review=review)
        return plan_publication(root=self.root, preparation_id=self.pid)

    def test_partial_reference_is_read_only_and_keeps_authored_completion_separate(self):
        value = request(self.root)
        value.pop("selected_design_id")
        preview = plan_outfit_preparation(value, root=self.root)
        self.assertEqual(preview["status"], "NEEDS_DESIGN_SELECTION")
        self.assertFalse((self.root / "calibration/preparations").exists())
        value["selected_design_id"] = "tucked"
        selected = plan_outfit_preparation(value, root=self.root)
        self.assertEqual(selected["selected_design"]["parts"]["lower"]["origin"], "completion")
        self.assertEqual(selected["sources"][0]["parts"][0]["evidence_status"], "UNCERTAIN")
        self.assertEqual(selected["status"], "READY")

    def test_missing_back_returns_independent_identity_prerequisite(self):
        other = self.root / "original"
        other.mkdir()
        copy_library(ROOT, other)
        # Keep this prerequisite fixture independent of the live library's
        # growing set of published rear identity references.
        registry = load(other / "character/assets.yaml")
        for asset in registry["assets"]:
            metadata = asset.get("generation_reference") or {}
            visible = set((metadata.get("coverage") or {}).get("visible_fields") or [])
            if {"identity", "hair.back", "body.back"} <= visible:
                metadata["supported_roles"] = [role for role in metadata.get("supported_roles", []) if role != "identity_reference"]
        write(other / "character/assets.yaml", registry)
        value = request(other)
        preview = plan_outfit_preparation(value, root=other)
        self.assertEqual(preview["status"], "IDENTITY_CALIBRATION_REQUIRED")
        self.assertTrue(preview["identity_prerequisites"][0]["identity_change"])
        self.assertNotIn("main_plan", preview)
        self.assert_code("PREPARATION_PREREQUISITE_REQUIRED", lambda: create_preparation(preview, approval(preview), root=other))
        self.assertFalse((other / "calibration/preparations").exists())

    def test_unresolved_completion_stops_before_tryon_and_cannot_escalate_evidence(self):
        value = request(self.root)
        value["designs"][0]["gap_resolutions"]["rear"] = ""
        self.assertEqual(plan_outfit_preparation(value, root=self.root)["status"], "NEEDS_COMPLETION")
        value = request(self.root)
        value["sources"][0]["parts"][0]["evidence_status"] = "CANON"
        self.assert_code("OUTFIT_EVIDENCE_ESCALATION", lambda: plan_outfit_preparation(value, root=self.root))

    def test_product_and_other_wearer_only_contribute_selected_parts(self):
        for kind in ("product", "other_wearer"):
            with self.subTest(kind=kind):
                preview = plan_outfit_preparation(request(self.root, kind=kind), root=self.root)
                ref = preview["main_plan"]["references"][1]
                self.assertEqual(ref["usage"], "garment")
                self.assertIn("source_person_identity", ref["exclude"])
                self.assertIn("source_style", ref["exclude"])
                self.assertEqual(ref["parts"][0]["region"]["xyxy"], [0.1, 0.1, 0.9, 0.7])

    def test_mix_preserves_sources_and_wearing_before_redesign(self):
        self.create(mixed=True)
        source = self.record["sources"][1]
        self.assertEqual(source["source_variant_id"], "school-uniform")
        self.assertEqual(source["source_variant_revision"], load(self.root / "variants/school-uniform/variant.yaml")["revision"])
        candidate = self.generate()
        prompt = self.provider.calls[-1]["prompt"]
        self.assertIn("Tuck the unchanged shirt", prompt)
        self.assertIn("Original school skirt", prompt)
        self.assertFalse(candidate["user_accepted"])

    def test_garment_detail_generates_flat_lay_without_wearing_framing(self):
        value = request(self.root)
        design = value["designs"][0]
        design["detail_requirements"] = [{"view_id": "detail-hosiery-footwear",
            "description": "Garment-only flat lay of opaque white garter stockings, white waistbelt, four straps and clips, and plain black low-heel shoes",
            "source_ids": []}]
        design["parts"]["hosiery"] = {"description": "White garter stockings and belt", "origin": "completion",
            "source_bindings": [], "fixed_features": ["Opaque white stockings with plain tops", "Four white garter straps with small clips"],
            "decision_reason": "User-approved hidden hosiery construction"}
        preview = plan_outfit_preparation(value, root=self.root)
        self.record = create_preparation(preview, approval(preview), root=self.root)
        self.pid = self.record["preparation_id"]
        self.accept_main()
        self.generate("detail-hosiery-footwear")
        prompt = self.provider.calls[-1]["prompt"]
        self.assertIn("Garment-only detail reference", prompt)
        self.assertIn("flat lay", prompt)
        self.assertIn("Do not depict a person, human body, head, hair or facial features", prompt)
        self.assertIn("Four white garter straps with small clips", prompt)
        self.assertIn("official Arco rendering style only", prompt)
        self.assertIn("human-accepted garment design anchor", prompt)
        self.assertNotIn("Faceless wearing reference", prompt)
        self.assertNotIn("full-body", prompt)
        self.assertNotIn("identity silhouette/proportions", prompt)
        self.assertEqual(len(self.provider.calls[-1]["referenced_image_paths"]), 2)
        main_prompt = self.provider.calls[0]["prompt"]
        self.assertIn("Faceless wearing reference", main_prompt)
        self.assertIn("unobstructed full-body framing", main_prompt)
        self.assertIn("identity silhouette/proportions", main_prompt)

    def test_same_published_identity_and_garment_image_is_sent_once(self):
        value = request(self.root, mixed=True)
        source = value["sources"][0]
        source.pop("path")
        source.update(asset_id="casual-outfit-crossed-arms-evidence", kind="published_variant")
        preview = plan_outfit_preparation(value, root=self.root)
        refs = preview["main_plan"]["references"]
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0]["usage"], "identity_and_garment")
        record = create_preparation(preview, approval(preview), root=self.root)
        run_candidate(root=self.root, preparation_id=record["preparation_id"], view_id="front", adapter=self.adapter)
        self.assertEqual(len(self.provider.calls[-1]["referenced_image_paths"]), 2)

    def test_body_base_copies_and_preparation_inputs_are_isolated(self):
        value = request(self.root)
        asset = next(a for a in load(self.root / "character/assets.yaml")["assets"] if a.get("asset_type") == "body_base")
        disguised = self.root / "shirt-renamed.png"
        shutil.copy2(self.root / asset["path"], disguised)
        value["sources"][0]["path"] = str(disguised)
        self.assert_code("BODY_BASE_NOT_ALLOWED", lambda: plan_outfit_preparation(value, root=self.root))
        self.create()
        candidate = self.generate()
        contract = {"reference_id": "unpublished", "source_scope": "request_scoped_arco", "path": candidate["path"],
            "role": "outfit_reference", "inherit": ["outfit"], "do_not_inherit": [], "persistent": False, "calibrating": False}
        self.assert_code("UNPUBLISHED_ASSET", lambda: validate_reference_contract(contract))

    def test_confirmation_and_changed_source_block_provider(self):
        value = request(self.root)
        preview = plan_outfit_preparation(value, root=self.root)
        self.assert_code("PREPARATION_CONFIRMATION_REQUIRED", lambda: create_preparation(preview, {}, root=self.root))
        self.create()
        Path(self.request["sources"][0]["path"]).write_bytes(b"changed")
        self.assert_code("PREPARATION_PLAN_STALE", self.generate)
        self.assertEqual(self.provider.calls, [])

    def test_tampered_saved_prompt_cannot_reuse_approved_preview(self):
        self.create()
        path = workspace(self.root, self.pid) / "preparation.yaml"
        record = load(path)
        record["plans"]["front"]["prompt"] += "\nChange the design secretly."
        record["plans"]["front"]["plan_sha256"] = digest({k: v for k, v in record["plans"]["front"].items() if k != "plan_sha256"})
        write(path, record)
        self.assert_code("PREPARATION_PLAN_STALE", self.generate)
        self.assertEqual(self.provider.calls, [])

    def test_saved_design_edits_return_to_confirmation(self):
        self.create()
        path = workspace(self.root, self.pid) / "preparation.yaml"
        record = load(path)
        record["design_definition"]["parts"]["footwear"]["description"] = "Unapproved red boots"
        write(path, record)
        self.assert_code("PREPARATION_CONFIRMATION_STALE", self.generate)
        self.assertEqual(self.provider.calls, [])

    def test_visual_review_does_not_approve_and_unverified_pack_is_blocked(self):
        self.create()
        candidate = self.generate()
        self.assert_code("MAIN_VISUAL_REVIEW_REQUIRED", lambda: plan_remaining_views(root=self.root, preparation_id=self.pid, main_candidate_id=candidate["candidate_id"]))
        review = inspected(self.root, self.pid, candidate)
        self.assertFalse(review["user_accepted"])
        self.assertFalse(load(workspace(self.root, self.pid) / "preparation.yaml")["candidates"][0]["user_accepted"])

    def test_failed_calls_consume_two_repairs_and_survive_resume(self):
        self.create()
        self.provider.fail = True
        for repair in (False, True, True):
            self.assert_code("BUILTIN_IMAGE_GEN_FAILED", lambda: self.generate(repair=repair))
        self.assert_code("AUTOMATIC_REPAIR_LIMIT", lambda: self.generate(repair=True))
        record = resume_preparation(root=self.root, preparation_id=self.pid)
        self.assertEqual([x["repair_number"] for x in record["attempts"]], [0, 1, 2])
        self.assertEqual(record["state"], "NEEDS_USER_DECISION")
        self.assertEqual(len(self.provider.calls), 3)

    def test_repair_is_bound_to_failed_check_and_retains_both_versions(self):
        self.create()
        first = self.generate()
        inspected(self.root, self.pid, first, failed="parts")
        repaired = self.generate(repair=True)
        self.assertIn("original targets for: parts", self.provider.calls[-1]["prompt"])
        self.assertNotIn(first["path"], self.provider.calls[-1]["referenced_image_paths"])
        self.assertTrue(Path(first["path"]).is_file() and Path(repaired["path"]).is_file())
        inspected(self.root, self.pid, repaired)
        self.assert_code("AUTOMATIC_REPAIR_REVIEW_REQUIRED", lambda: self.generate(repair=True))

    def test_interrupted_reservation_remains_consumed_on_resume(self):
        self.create()
        path = workspace(self.root, self.pid) / "preparation.yaml"
        record = load(path)
        record["attempts"].append({"attempt_id": "interrupted", "view_id": "front", "plan_sha256": record["plans"]["front"]["plan_sha256"], "repair_number": 0, "state": "RESERVED"})
        write(path, record)
        resumed = resume_preparation(root=self.root, preparation_id=self.pid)
        self.assertEqual(resumed["attempts"][0]["state"], "INTERRUPTED")
        candidate = self.generate(repair=True)
        self.assertEqual(candidate["repair_number"], 1)

    def test_same_view_back_knee_edit_keeps_identity_authority_and_publication_trace(self):
        preview = plan_identity_calibration({"back_definition": {"schema_version": 1,
            "fixed_constraints": ["Preserve approved Arco rear identity and body proportions."],
            "completion_decisions": ["Natural loose rear hair connections."]}}, root=self.root)
        record = create_identity_preparation(preview, approval(preview), root=self.root)
        pid = record["preparation_id"]
        first = run_candidate(root=self.root, preparation_id=pid, view_id="identity-back", adapter=self.adapter)
        inspected(self.root, pid, first, failed="identity")
        repaired = run_candidate(root=self.root, preparation_id=pid, view_id="identity-back", adapter=self.adapter,
            repair=True, repair_target_candidate_id=first["candidate_id"], correction_code="back-knee-orientation",
            user_repair_message="Correct the knees to a rear view; retain everything else.")
        arguments = self.provider.calls[-1]
        self.assertEqual(arguments["referenced_image_paths"][:-1], preview["main_plan"]["referenced_image_paths"])
        self.assertEqual(arguments["referenced_image_paths"][-1], first["path"])
        self.assertIn("Remove anterior kneecap bulges", arguments["prompt"])
        self.assertIn("Preserve every region outside the knees", arguments["prompt"])
        self.assertEqual(repaired["repair_number"], 1)
        self.assertEqual(repaired["repair_source_candidate_id"], first["candidate_id"])
        self.assertTrue(Path(first["path"]).is_file())
        inspected(self.root, pid, repaired)
        final = plan_publication(root=self.root, preparation_id=pid)
        stage_publication(final, approval(final), root=self.root)
        publish_preparation(root=self.root, preparation_id=pid)
        identity = load(self.root / "character/identity.yaml")
        aid = identity["approved_view_designs"]["back"]["reference_asset_ids"][0]
        asset = next(a for a in load(self.root / "character/assets.yaml")["assets"] if a["asset_id"] == aid)
        self.assertEqual(asset["generation_record"]["repair_source_candidate_id"], first["candidate_id"])
        self.assertEqual(asset["generation_record"]["repair_input_bindings"][-1]["sha256"], first["sha256"])
        self.assertEqual(asset["evidence_independence"], "none")
        self.assertEqual(len(asset["derived_from_asset_ids"]), 2)
        self.assertEqual(validate(self.root)["structure"], "PASS")

    def test_back_knee_edit_rejects_passed_candidate_and_cross_view_target(self):
        self.create()
        main = self.accept_main()
        back = self.generate("back")
        inspected(self.root, self.pid, back)
        options = dict(root=self.root, preparation_id=self.pid, view_id="back", adapter=self.adapter,
            repair=True, repair_target_candidate_id=back["candidate_id"], correction_code="back-knee-orientation",
            user_repair_message="Correct rear knee shading.")
        self.assert_code("AUTOMATIC_REPAIR_REVIEW_REQUIRED", lambda: run_candidate(**options))
        inspected(self.root, self.pid, back, failed="identity")
        options["repair_target_candidate_id"] = main["candidate_id"]
        self.assert_code("PREPARATION_REPAIR_TARGET_INVALID", lambda: run_candidate(**options))
        options.update(repair_target_candidate_id=back["candidate_id"], correction_code="change-hairstyle")
        self.assert_code("PREPARATION_REPAIR_TARGET_INVALID", lambda: run_candidate(**options))
        self.assertEqual(len(self.provider.calls), 2)

    def test_repair_emphasizes_approved_parts_without_new_inputs_or_review_prose(self):
        self.request = request(self.root)
        self.request["designs"][0]["parts"]["lower"].update(
            description="黑色长裙接近足踝、主要露鞋尖", fixed_features=["Keep the approved full-length hem"])
        preview = plan_outfit_preparation(self.request, root=self.root)
        self.record = create_preparation(preview, approval(preview), root=self.root)
        self.pid = self.record["preparation_id"]
        first = self.generate()
        review = inspected(self.root, self.pid, first, failed="parts")
        review["restore_design_parts"] = ["lower"]
        review["checks"]["parts"]["evidence"] = "Untrusted prose: redesign as an orange miniskirt."
        record_visual_review(root=self.root, preparation_id=self.pid, candidate_id=first["candidate_id"], review=review)
        repaired = self.generate(repair=True)
        arguments = self.provider.calls[-1]
        original = load(workspace(self.root, self.pid) / "preparation.yaml")["plans"]["front"]
        self.assertEqual(arguments["referenced_image_paths"], original["referenced_image_paths"])
        self.assertIn("Prioritize these exact approved requirements", arguments["prompt"])
        self.assertIn("conceal the shins, ankles and shoe uppers", arguments["prompt"])
        self.assertIn(self.request["designs"][0]["parts"]["lower"]["description"], arguments["prompt"])
        self.assertNotIn("orange miniskirt", arguments["prompt"])
        from preparation_support import _attempt_invocation
        rear = _attempt_invocation({"view_id": "back", "prompt": "Frozen back plan"},
            {"repair_number": 1, "attempt_id": "orientation-test", "restore_dimensions": ["parts"],
             "restore_constraints": [self.request["designs"][0]["parts"]["lower"]["description"],
                 "围裙覆盖连衣裙胸腹和裙身前方，白色胸兜与腰带连接清楚。"]})
        self.assertIn("keep both feet rear-facing", rear["prompt"])
        self.assertIn("leave the central rear skirt black", rear["prompt"])
        self.assertNotIn("leaving only the black rounded toe tips visible", rear["prompt"])
        hosiery = _attempt_invocation({"view_id": "detail-hosiery-footwear", "prompt": "Frozen flat-lay plan"},
            {"repair_number": 1, "attempt_id": "connection-test", "restore_dimensions": ["parts"],
             "restore_constraints": ["四条白色吊带（每腿前后各一条）", "黑色长裙接近足踝、主要露鞋尖"]})
        self.assertIn("each ending in a small plain clip actually gripping the stocking cuff", hosiery["prompt"])
        self.assertIn("Do not duplicate the belt", hosiery["prompt"])
        self.assertNotIn("conceal the shins, ankles and shoe uppers", hosiery["prompt"])
        front = _attempt_invocation({"view_id": "front", "prompt": "Frozen wearing plan"},
            {"repair_number": 1, "attempt_id": "wearing-test", "restore_dimensions": ["parts"],
             "restore_constraints": ["四条白色吊带（每腿前后各一条）"]})
        self.assertNotIn("connection diagram", front["prompt"])
        self.assertEqual(repaired["repair_number"], 1)
        review = inspected(self.root, self.pid, repaired, failed="parts")
        review["restore_design_parts"] = ["lower"]
        record_visual_review(root=self.root, preparation_id=self.pid, candidate_id=repaired["candidate_id"], review=review)

        class TamperedAdapter:
            def generate_preparation(inner, **kwargs):
                path = workspace(self.root, self.pid) / "preparation.yaml"
                record = load(path)
                record["attempts"][-1]["restore_constraints"] = ["New unapproved orange miniskirt"]
                write(path, record)
                return self.adapter.generate_preparation(**kwargs)

        self.assert_code("PREPARATION_PLAN_STALE", lambda: run_candidate(root=self.root,
            preparation_id=self.pid, view_id="front", adapter=TamperedAdapter(), repair=True))
        self.assertEqual(len(self.provider.calls), 2)
        review["restore_design_parts"] = ["unapproved"]
        self.assert_code("VISUAL_REVIEW_INVALID", lambda: record_visual_review(root=self.root,
            preparation_id=self.pid, candidate_id=repaired["candidate_id"], review=review))

    def test_live_record_lock_blocks_duplicate_operations_and_is_reusable(self):
        self.create()
        path = workspace(self.root, self.pid)
        with locked(path):
            self.assert_code("PREPARATION_BUSY", lambda: resume_preparation(root=self.root, preparation_id=self.pid))
        self.assertEqual(resume_preparation(root=self.root, preparation_id=self.pid)["state"], "MAIN_READY")

    def test_main_confirmation_rechecks_review_after_lock_acquisition(self):
        self.create()
        main = self.generate()
        inspected(self.root, self.pid, main)
        preview = plan_remaining_views(root=self.root, preparation_id=self.pid, main_candidate_id=main["candidate_id"])

        @contextmanager
        def intervening_review(path):
            # Another reviewer finishes between preparing the preview and
            # acquiring its acceptance lock.
            inspected(self.root, self.pid, main, failed="parts")
            with locked(path):
                yield

        with patch("outfit_preparation.locked", intervening_review):
            self.assert_code("MAIN_VISUAL_REVIEW_REQUIRED", lambda: approve_main_and_views(preview, approval(preview), root=self.root))
        record = load(workspace(self.root, self.pid) / "preparation.yaml")
        self.assertNotIn("locked_main", record)
        self.assertNotIn("main_and_views", record["approvals"])

    def test_manual_new_round_needs_new_confirmation_after_repair_limit(self):
        self.create()
        self.provider.fail = True
        for repair in (False, True, True):
            self.assert_code("BUILTIN_IMAGE_GEN_FAILED", lambda: self.generate(repair=repair))
        value = deepcopy(self.request)
        value["manual_restart"] = "User explicitly requests a new try-on round with the same design."
        preview = plan_outfit_preparation(value, root=self.root)
        self.assert_code("PREPARATION_CONFIRMATION_REQUIRED", lambda: revise_preparation(root=self.root, preparation_id=self.pid, preview=preview, confirmation={}))
        revise_preparation(root=self.root, preparation_id=self.pid, preview=preview, confirmation=approval(preview))
        self.provider.fail = False
        candidate = self.generate()
        self.assertEqual(candidate["repair_number"], 0)
        self.assertEqual(len(load(workspace(self.root, self.pid) / "preparation.yaml")["attempts"]), 4)

    def test_other_views_only_use_locked_main_and_formal_identity(self):
        self.create()
        main = self.accept_main()
        side = self.generate("right-three-quarter")
        inspected(self.root, self.pid, side)
        back = self.generate("back")
        refs = self.provider.calls[-1]["referenced_image_paths"]
        self.assertIn(main["path"], refs)
        self.assertNotIn(side["path"], refs)
        self.assertNotIn(back["path"], refs)
        self.assertIn("face invisible", self.provider.calls[-1]["prompt"])

    def test_design_reconfirmation_retains_versions_and_invalidates_dependencies(self):
        self.create()
        main = self.accept_main()
        side = self.generate("right-three-quarter")
        value = deepcopy(self.request)
        value["selected_design_id"] = "untucked"
        preview = plan_outfit_preparation(value, root=self.root)
        revised = revise_preparation(root=self.root, preparation_id=self.pid, preview=preview, confirmation=approval(preview))
        self.assertNotIn("locked_main", revised)
        self.assertTrue(all(c["invalidated"] for c in revised["candidates"]))
        self.assertTrue(Path(main["path"]).exists() and Path(side["path"]).exists())
        self.assert_code("PREPARATION_CONFIRMATION_REQUIRED", lambda: self.generate("back"))

    def test_main_repair_invalidates_old_views_before_new_main_acceptance(self):
        self.create()
        main = self.accept_main()
        side = self.generate("right-three-quarter")
        inspected(self.root, self.pid, side)
        inspected(self.root, self.pid, main, failed="parts")
        repaired = self.generate(repair=True)
        inspected(self.root, self.pid, repaired)
        preview = plan_remaining_views(root=self.root, preparation_id=self.pid, main_candidate_id=repaired["candidate_id"])
        record = approve_main_and_views(preview, approval(preview), root=self.root)
        self.assertTrue(next(c for c in record["candidates"] if c["candidate_id"] == side["candidate_id"])["invalidated"])
        self.assert_code("REFERENCE_PACK_INCOMPLETE", lambda: plan_publication(root=self.root, preparation_id=self.pid))

    def test_existing_worn_primary_enters_review_without_generation(self):
        value = request(self.root, kind="arco_worn")
        value["existing_primary_source_id"] = "top"
        preview = plan_outfit_preparation(value, root=self.root)
        record = create_preparation(preview, approval(preview), root=self.root)
        candidate = adopt_primary(root=self.root, preparation_id=record["preparation_id"])
        self.assertEqual(self.provider.calls, [])
        self.assertFalse(candidate["user_accepted"])
        self.assert_code("MAIN_VISUAL_REVIEW_REQUIRED", lambda: plan_remaining_views(root=self.root, preparation_id=record["preparation_id"], main_candidate_id=candidate["candidate_id"]))

    def test_publication_is_final_approval_only_and_uses_multi_input_lineage(self):
        preview = self.pack(mixed=True)
        self.assertFalse((self.root / "calibration/staging").exists())
        self.assert_code("PREPARATION_CONFIRMATION_REQUIRED", lambda: stage_publication(preview, {}, root=self.root))
        stage_publication(preview, approval(preview), root=self.root)
        published = publish_preparation(root=self.root, preparation_id=self.pid)
        self.assertEqual(published["publication_state"], "COMPLETE")
        variant = load(self.root / "variants/new-outfit/variant.yaml")
        self.assertEqual(variant["source_materials"][0]["parts"][0]["evidence_status"], "UNCERTAIN")
        self.assertEqual(variant["design_definition"]["parts"]["footwear"]["origin"], "completion")
        assets = load(self.root / "character/assets.yaml")["assets"]
        main = next(a for a in assets if a["asset_id"] == "new-outfit-front")
        self.assertEqual(main["evidence_independence"], "none")
        self.assertGreaterEqual(len(main["derived_from_asset_ids"]), 3)
        self.assertEqual(validate(self.root)["structure"], "PASS")
        self.assertTrue((self.root / published["completion_marker"]).is_file())
        new_request = production_request(self.root, "new-outfit")
        normal = plan_production_generation(new_request, root=self.root)
        self.assertIn("[Approved Variant Design]", normal.prompt)
        self.assertIn("Tuck the unchanged shirt", normal.prompt)
        self.assertIn("Plain black shoes", normal.prompt)
        self.assertIn("Approved plain back panel without new trims", normal.prompt)
        new_request["analysis_confirmation"] = {"user_confirmed": True, "plan_sha256": normal.analysis_preview["plan_sha256"], "user_message": "Fixture approves production preview."}
        run_production_generation(new_request, root=self.root, builtin_image_gen=self.provider)
        back = plan_production_generation(production_request(self.root, "new-outfit", "back_view"), root=self.root)
        self.assertEqual([r["role"] for r in back.selected_references], ["identity_reference", "outfit_reference"])
        self.assertIn("[Approved Back Identity]", back.prompt)
        self.assertNotIn("Expression library adjustment", back.prompt)
        for variant_id in ("casual-outfit", "school-uniform", "swimsuit"):
            legacy = plan_production_generation(production_request(self.root, variant_id), root=self.root)
            self.assertNotIn("[Approved Variant Design]", legacy.prompt)
        (self.root / published["completion_marker"]).unlink()
        self.assert_code("UNPUBLISHED_VARIANT", lambda: plan_production_generation(new_request, root=self.root))
        variant["facts"] = [{"field_id": "outfit.fake-consensus", "value": "generated views agree", "status": "VISUAL_CONSENSUS", "evidence_ids": ["new-outfit-front", "new-outfit-back"], "required_for": []}]
        write(self.root / "variants/new-outfit/variant.yaml", variant)
        self.assertIn("consensus-not-independent", {i["code"] for i in validate(self.root)["issues"]})

    def test_saved_json_publication_preview_keeps_candidate_file_hashes(self):
        preview = self.pack(mixed=True)
        saved = self.root / "publication-preview.json"
        saved.write_text(json.dumps(preview, ensure_ascii=False), encoding="utf-8")
        restored = json.loads(saved.read_text(encoding="utf-8"))
        self.assertEqual(restored, preview)
        stage_publication(restored, approval(restored), root=self.root)
        published = publish_preparation(root=self.root, preparation_id=self.pid)
        self.assertEqual(published["publication_state"], "COMPLETE")
        for item in restored["files"]:
            self.assertEqual(file_hash(self.root / item["target_path"]), item["candidate_hash"])
        self.assertEqual(validate(self.root)["structure"], "PASS")

    def test_final_pack_review_is_required_and_image_changes_expire_it(self):
        self.create(details=False)
        self.accept_main()
        for view in ("right-three-quarter", "back"):
            candidate = self.generate(view)
            inspected(self.root, self.pid, candidate)
        self.assert_code("REFERENCE_PACK_REVIEW_REQUIRED", lambda: plan_publication(root=self.root, preparation_id=self.pid))
        preview = plan_reference_pack(root=self.root, preparation_id=self.pid)
        review = {"preview_sha256": preview["preview_sha256"], "inspected_original_size": True,
            "checks": {key: {"status": "PASS", "evidence": "Controlled full pack comparison"} for key in CHECKS}}
        record_pack_review(root=self.root, preparation_id=self.pid, preview=preview, review=review)
        Path(candidate["path"]).write_bytes(b"changed back structure")
        self.assert_code("PREPARATION_CANDIDATE_STALE", lambda: plan_publication(root=self.root, preparation_id=self.pid))

    def test_pack_review_rechecks_locked_snapshot_and_keeps_previous_inspection(self):
        self.pack(details=False)
        preview = plan_reference_pack(root=self.root, preparation_id=self.pid)
        candidate = preview["images"]["back"]
        review = {"preview_sha256": preview["preview_sha256"], "inspected_original_size": True,
            "checks": {key: {"status": "PASS", "evidence": "Controlled pack reinspection"} for key in CHECKS}}

        @contextmanager
        def intervening_review(path):
            changed = deepcopy(candidate["review"])
            changed["checks"]["parts"]["evidence"] = "Updated rear structure inspection"
            record_visual_review(root=self.root, preparation_id=self.pid, candidate_id=candidate["candidate_id"], review=changed)
            with locked(path):
                yield

        with patch("preparation_publication.locked", intervening_review):
            self.assert_code("REFERENCE_PACK_STALE", lambda: record_pack_review(root=self.root, preparation_id=self.pid, preview=preview, review=review))
        record = load(workspace(self.root, self.pid) / "preparation.yaml")
        self.assertNotIn("pack_review", record)
        self.assertEqual(record["pack_review_history"][-1]["preview"]["preview_sha256"], preview["preview_sha256"])
        self.assertEqual(record["candidates"][-1]["review_history"][-1], candidate["review"])

    def test_back_identity_and_outfit_coverages_cannot_substitute_for_each_other(self):
        refs = [{"reference_id": "front-mislabeled", "source_scope": "managed_arco", "role": "identity_reference", "coverage": {"view_angles": ["front"], "visible_fields": ["identity", "hair.back", "body.back"]}},
                {"reference_id": "rear-clothes", "source_scope": "managed_arco", "role": "outfit_reference", "variant_id": "new-outfit", "coverage": {"view_angles": ["back"], "visible_fields": ["identity", "hair.back", "body.back", "variant.back_outfit"]}}]
        result = compute_request_reference_readiness(exposure_profile="back_view", references=refs, variant_required=True, selected_variant_id="new-outfit")
        self.assertNotEqual(result["status"], "READY")
        self.assertTrue({"identity", "hair.back", "body.back"} <= set(result["missing_fields"]))

    def test_processed_source_keeps_original_and_does_not_add_independent_evidence(self):
        value = request(self.root, details=False)
        original = Path(value["sources"][0]["path"])
        processed = self.root / "shirt-isolated.png"
        processed.write_bytes(b"\x89PNG\r\n\x1a\nisolated-shirt-fixture")
        source = value["sources"][0]
        source.update(path=str(processed), original_path=str(original), processing_records=[{
            "operation": "Controlled isolation fixture; preserve original colors", "input_sha256": file_hash(original), "output_sha256": file_hash(processed)}])
        preview = plan_outfit_preparation(value, root=self.root)
        self.assertEqual(preview["sources"][0]["evidence_independence"], "none")
        self.record = create_preparation(preview, approval(preview), root=self.root)
        self.pid = self.record["preparation_id"]
        self.assertEqual(file_hash(self.record["sources"][0]["retained_original_path"]), file_hash(original))
        final = self.finish_pack()
        stage_publication(final, approval(final), root=self.root)
        publish_preparation(root=self.root, preparation_id=self.pid)
        assets = {a["asset_id"]: a for a in load(self.root / "character/assets.yaml")["assets"]}
        selected = assets["new-outfit-source-top"]
        self.assertEqual(selected["derived_from_asset_id"], "new-outfit-source-top-original")
        self.assertEqual(selected["source_group_id"], assets[selected["derived_from_asset_id"]]["source_group_id"])
        self.assertEqual(selected["evidence_independence"], "none")

    def test_staging_failure_is_resumable_without_extra_authorization(self):
        preview = self.pack(details=False)
        before = file_hash(self.root / "character/assets.yaml")
        with patch("preparation_publication._validate", side_effect=RuntimeError("Controlled interrupted staging validation")):
            with self.assertRaises(RuntimeError):
                stage_publication(preview, approval(preview), root=self.root)
        record = load(workspace(self.root, self.pid) / "preparation.yaml")
        self.assertEqual(record["state"], "RECOVERY_REQUIRED")
        self.assertEqual(file_hash(self.root / "character/assets.yaml"), before)
        recovered = recover_publication(root=self.root, preparation_id=self.pid)
        self.assertEqual(recovered["publication_state"], "STAGED_VALIDATED_AWAITING_AUTHORIZATION")
        self.assertEqual(publish_preparation(root=self.root, preparation_id=self.pid)["publication_state"], "COMPLETE")

    def test_publication_target_tampering_cannot_reuse_final_approval(self):
        preview = self.pack(details=False)
        manifest = stage_publication(preview, approval(preview), root=self.root)
        staging = Path(load(workspace(self.root, self.pid) / "preparation.yaml")["publication_staging"])
        item = next(i for i in manifest["files"] if i["target_path"] == "variants/new-outfit/variant.yaml")
        target = staging / item["staged_path"]
        entity = load(target)
        entity["display_name_zh"] = "Altered after final acceptance"
        write(target, entity)
        item["candidate_hash"] = file_hash(target)
        write(staging / "publish-manifest.yaml", manifest)
        self.assert_code("PREPARATION_PLAN_STALE", lambda: publish_preparation(root=self.root, preparation_id=self.pid))
        self.assertFalse((self.root / "variants/new-outfit/variant.yaml").exists())

    def test_new_confirmed_design_retires_unwritten_staging_and_preserves_it(self):
        final = self.pack(details=False)
        stage_publication(final, approval(final), root=self.root)
        old = Path(load(workspace(self.root, self.pid) / "preparation.yaml")["publication_staging"])
        value = deepcopy(self.request)
        value["selected_design_id"] = "untucked"
        preview = plan_outfit_preparation(value, root=self.root)
        revised = revise_preparation(root=self.root, preparation_id=self.pid, preview=preview, confirmation=approval(preview))
        self.assertEqual(load(old / "publish-manifest.yaml")["publication_state"], "CANCELLED")
        self.assertTrue(old.is_dir())
        self.assertNotEqual(revised["next_calibration_id"], final["calibration_id"])
        self.assertEqual(revised["state"], "MAIN_READY")
        self.assertFalse((self.root / "variants/new-outfit/variant.yaml").exists())

    def test_reference_limit_requires_explicit_curation_and_never_silently_drops_sources(self):
        value = request(self.root)
        original = deepcopy(value["sources"][0])
        bindings = value["designs"][0]["parts"]["upper"]["source_bindings"]
        for i in range(4):
            source = deepcopy(original)
            source["source_id"] = "top-" + str(i)
            image = self.root / ("top-" + str(i) + ".png")
            image.write_bytes(b"\x89PNG\r\n\x1a\nsource-" + str(i).encode())
            source["path"] = str(image)
            value["sources"].append(source)
            bindings.append({"source_id": source["source_id"], "part_id": "shirt"})
        value["combination"]["upper"] = deepcopy(bindings)
        self.assert_code("REFERENCE_LIMIT_EXCEEDED", lambda: plan_outfit_preparation(value, root=self.root))

    def test_publication_interruption_restores_then_retries_same_approved_pack(self):
        preview = self.pack(details=False)
        before = file_hash(self.root / "character/assets.yaml")
        stage_publication(preview, approval(preview), root=self.root)
        with self.assertRaises(Exception):
            publish_preparation(root=self.root, preparation_id=self.pid, fail_after="character/assets.yaml")
        self.assertEqual(file_hash(self.root / "character/assets.yaml"), before)
        self.assertFalse((self.root / "assets/arco/variants/new-outfit/references/front.png").exists())
        recover_publication(root=self.root, preparation_id=self.pid)
        result = publish_preparation(root=self.root, preparation_id=self.pid)
        self.assertEqual(result["publication_state"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()
