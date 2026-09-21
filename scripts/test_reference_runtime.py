from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from reference_runtime import (
    RENDERING_HYGIENE_HEADER,
    ReferenceRuntimeError,
    STYLE_AXES,
    build_builtin_imagegen_args,
    build_invocation_plan,
    compile_reference_instructions,
    compile_rendering_hygiene,
    compile_style_instructions,
    compile_prompt,
    compute_global_reference_readiness,
    compute_request_reference_readiness,
    generation_allowed,
    resolve_identity_fact_prompt_fragments,
    resolve_mode,
    resolve_style_references,
    resolve_style_context,
    select_references,
    validate_style_baseline,
    validate_style_brief,
    validate_style_prompt,
    validate_rendering_hygiene,
    validate_reference_contract,
)


CONFIG = {
    "generation": {
        "max_local_arco_references": 3,
        "max_external_references": 2,
        "max_total_image_inputs": 4,
    }
}
STYLE_POLICY = yaml.safe_load(
    (SCRIPT_DIR.parent / "runtime" / "style-policy.yaml").read_text(encoding="utf-8")
)


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


def external_ref(reference_id="external-1", role="pose_reference", path="C:/request/pose.png", *, duties=None, style_priority=None, style_axes=None):
    reference = {
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
    if duties is not None:
        reference["duties"] = list(duties)
    if style_priority is not None:
        reference["style_priority"] = style_priority
    if style_axes is not None:
        reference["style_axes"] = list(style_axes)
    return reference


def style_ref(reference_id="external-style-1", *, priority=None, axes=None, path=None):
    return external_ref(
        reference_id,
        role="style_reference",
        path=path or f"C:/request/{reference_id}.png",
        style_priority=priority,
        style_axes=axes or [],
    )


def style_brief(reference_id, priority, axes, *, confidence="high", description_prefix="clean rendering"):
    return {
        "schema_version": 1,
        "source_reference_id": reference_id,
        "style_priority": priority,
        "active_axes": list(axes),
        "axes": {
            axis: {
                "description": f"{description_prefix} for {axis}",
                "confidence": confidence,
            }
            for axis in axes
        },
    }


def baseline_fixture():
    return {
        "schema_version": 1,
        "baseline_id": "test-official-baseline",
        "mode": "fallback_only",
        "source_family_id": "test-official-family",
        "evidence": {
            "asset_ids": ["identity-p01", "identity-p03"],
            "sha256": ["hash-p01", "hash-p03"],
        },
        "consensus_rule": {
            "minimum_support": 2,
            "outlier_features_excluded": True,
        },
        "axes": {
            axis: {
                "description": f"conservative rendering language for {axis}",
                "confidence": "medium",
            }
            for axis in [
                "linework",
                "shading",
                "color_logic",
                "highlight_language",
                "texture_language",
                "detail_density",
            ]
        },
    }


def compile_style_prompt_fixture(case_name, *, rendering_hygiene_policy=None):
    fixture_root = SCRIPT_DIR / "fixtures" / "style_prompt"
    fixture = json.loads((fixture_root / f"{case_name}.input.json").read_text(encoding="utf-8"))
    resolved_references = resolve_style_references(fixture["references"])
    style_context = resolve_style_context(
        resolved_style_references=resolved_references,
        style_briefs=fixture.get("style_briefs", []),
        official_style_baseline=fixture.get("official_style_baseline"),
        user_style_overrides=fixture.get("user_style_overrides"),
    )
    prompt = compile_prompt(
        base_prompt=fixture["base_prompt"],
        references=fixture["references"],
        identity=fixture.get("identity"),
        exposure_profile=fixture.get("exposure_profile"),
        allow_uncertain_working=fixture.get("allow_uncertain_working", False),
        style_context=style_context,
        rendering_hygiene_policy=rendering_hygiene_policy,
    )
    return style_context, prompt


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

    def test_selector_skips_assets_excluded_for_requested_exposure_profile(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            excluded_primary = managed_ref(
                root,
                "excluded-upper-body-primary",
                role="identity_reference",
                fields=["identity", "hair", "eyes", "face", "body.upper"],
            )
            excluded_primary["generation_reference"]["excluded_for"] = ["upper_body"]
            allowed_secondary = managed_ref(
                root,
                "allowed-upper-body-secondary",
                role="identity_reference",
                priority="secondary",
                fields=["identity", "hair", "eyes", "face", "body.upper"],
            )

            selected = select_references(
                root=root,
                managed_assets=[excluded_primary, allowed_secondary],
                requested_roles=["identity_reference"],
                exposure_profile="upper_body",
                config=CONFIG,
            )

            self.assertEqual(
                [item["asset_id"] for item in selected],
                ["allowed-upper-body-secondary"],
            )

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

    def test_external_duties_are_backward_compatible_and_multi_duty_is_one_reference(self):
        legacy = external_ref("legacy-style", role="style_reference")
        resolved = resolve_style_references([legacy])
        self.assertEqual(resolved["references"][0]["duties"], ["style_reference"])
        self.assertEqual(resolved["primary_reference_id"], "legacy-style")

        multi = external_ref(
            "multi-duty-style",
            role="style_reference",
            duties=["style_reference", "composition_reference", "lighting_reference", "pose_reference"],
            path="C:/request/multi-duty.png",
        )
        selected = select_references(
            root=Path.cwd(),
            managed_assets=[],
            requested_roles=[],
            external_references=[multi],
            config=CONFIG,
        )
        self.assertEqual(len(selected), 1)
        plan = build_invocation_plan(mode="reference_conditioned", prompt="Arco prompt", selected_references=selected)
        self.assertEqual(build_builtin_imagegen_args(plan)["referenced_image_paths"], ["C:/request/multi-duty.png"])

    def test_external_duties_fail_closed(self):
        missing_role = external_ref(
            "missing-role",
            role="style_reference",
            duties=["composition_reference"],
        )
        self.assertCode("INVALID_REFERENCE_DUTIES", lambda: validate_reference_contract(missing_role))

        who_duty = external_ref(
            "who-duty",
            role="style_reference",
            duties=["style_reference", "identity_reference"],
        )
        self.assertCode("INVALID_REFERENCE_DUTIES", lambda: validate_reference_contract(who_duty))

        invalid_duty = external_ref(
            "invalid-duty",
            role="style_reference",
            duties=["style_reference", "style"],
        )
        self.assertCode("INVALID_REFERENCE_DUTIES", lambda: validate_reference_contract(invalid_duty))

        scene = external_ref("scene-duty", role="scene_reference", duties=["scene_reference"])
        validate_reference_contract(scene)

    def test_style_priority_resolution_and_conflicts(self):
        implicit = resolve_style_references([external_ref("implicit", role="style_reference")])
        self.assertEqual(implicit["primary_reference_id"], "implicit")
        self.assertEqual(implicit["references"][0]["style_priority"], "primary")

        primary = external_ref("primary", role="style_reference", style_priority="primary")
        secondary = external_ref("secondary", role="style_reference", style_priority="secondary")
        resolved = resolve_style_references([secondary, primary])
        self.assertEqual(resolved["primary_reference_id"], "primary")
        self.assertEqual(resolved["secondary_reference_ids"], ["secondary"])

        duplicate_primary = external_ref("primary-2", role="style_reference", style_priority="primary")
        self.assertCode("STYLE_PRIMARY_CONFLICT", lambda: resolve_style_references([primary, duplicate_primary]))

        missing_priority = external_ref("missing-priority", role="style_reference")
        self.assertCode("STYLE_PRIMARY_CONFLICT", lambda: resolve_style_references([primary, missing_priority]))

        invalid_priority = external_ref("invalid-priority", role="style_reference", style_priority="high")
        self.assertCode("STYLE_PRIORITY_INVALID", lambda: validate_reference_contract(invalid_priority))

        secondary_2 = external_ref("secondary-2", role="style_reference", style_priority="secondary")
        self.assertCode("STYLE_SECONDARY_CONFLICT", lambda: resolve_style_references([secondary, secondary_2]))

    def test_style_axis_ownership_is_deterministic_and_conflicts_fail_closed(self):
        primary = external_ref(
            "axis-primary",
            role="style_reference",
            style_priority="primary",
            style_axes=["shading", "linework"],
        )
        secondary = external_ref(
            "axis-secondary",
            role="style_reference",
            style_priority="secondary",
            style_axes=["texture_language", "color_logic"],
        )
        resolved = resolve_style_references([secondary, primary])
        self.assertEqual(
            resolved["axis_owners"],
            {
                "linework": "axis-primary",
                "shading": "axis-primary",
                "color_logic": "axis-secondary",
                "texture_language": "axis-secondary",
            },
        )

        overlap = external_ref(
            "axis-secondary-overlap",
            role="style_reference",
            style_priority="secondary",
            style_axes=["shading"],
        )
        self.assertCode("STYLE_AXIS_CONFLICT", lambda: resolve_style_references([primary, overlap]))

        invalid_axis = external_ref(
            "invalid-axis",
            role="style_reference",
            style_axes=["unknown_axis"],
        )
        self.assertCode("STYLE_AXIS_INVALID", lambda: validate_reference_contract(invalid_axis))

    def test_style_brief_validation_binds_to_resolved_reference_and_normalizes_confidence(self):
        resolved = resolve_style_references([
            style_ref("brief-primary", priority="primary", axes=["linework", "shading"]),
        ])
        brief = style_brief("brief-primary", "primary", ["linework"], confidence="mEdIuM")
        original = copy.deepcopy(brief)
        normalized = validate_style_brief(brief, resolved_style_references=resolved)
        self.assertEqual(normalized["axes"]["linework"]["confidence"], "MEDIUM")
        self.assertEqual(brief, original)

        unknown_source = style_brief("not-resolved", "primary", ["linework"])
        self.assertCode("STYLE_BRIEF_SOURCE_MISMATCH", lambda: validate_style_brief(unknown_source, resolved_style_references=resolved))
        wrong_priority = style_brief("brief-primary", "secondary", ["linework"])
        self.assertCode("STYLE_BRIEF_PRIORITY_MISMATCH", lambda: validate_style_brief(wrong_priority, resolved_style_references=resolved))

    def test_style_brief_axis_and_who_guards_fail_closed(self):
        resolved = resolve_style_references([
            style_ref("brief-axis", priority="primary", axes=["linework"]),
        ])
        unowned = style_brief("brief-axis", "primary", ["shading"])
        self.assertCode("STYLE_BRIEF_AXIS_UNOWNED", lambda: validate_style_brief(unowned, resolved_style_references=resolved))

        invalid_axis = style_brief("brief-axis", "primary", ["unknown_axis"])
        self.assertCode("STYLE_BRIEF_AXIS_INVALID", lambda: validate_style_brief(invalid_axis, resolved_style_references=resolved))

        invalid_confidence = style_brief("brief-axis", "primary", ["linework"], confidence="certain")
        self.assertCode("STYLE_BRIEF_CONFIDENCE_INVALID", lambda: validate_style_brief(invalid_confidence, resolved_style_references=resolved))

        empty_description = style_brief("brief-axis", "primary", ["linework"])
        empty_description["axes"]["linework"]["description"] = "  "
        self.assertCode("STYLE_BRIEF_INVALID", lambda: validate_style_brief(empty_description, resolved_style_references=resolved))

        who_description = style_brief("brief-axis", "primary", ["linework"])
        who_description["axes"]["linework"]["description"] = "clean linework and blue hair"
        self.assertCode("STYLE_BRIEF_WHO_POLLUTION", lambda: validate_style_brief(who_description, resolved_style_references=resolved))

    def test_style_brief_axes_keys_must_match_active_axes(self):
        resolved = resolve_style_references([
            style_ref("brief-shape", priority="primary", axes=["linework", "shading"]),
        ])
        mismatch = style_brief("brief-shape", "primary", ["linework"])
        mismatch["axes"]["shading"] = {"description": "soft cel shading", "confidence": "high"}
        self.assertCode("STYLE_BRIEF_AXIS_INVALID", lambda: validate_style_brief(mismatch, resolved_style_references=resolved))

    def test_official_style_baseline_validation_and_registry_fixture(self):
        baseline_path = Path(__file__).parents[1] / "character" / "style-baseline.yaml"
        with baseline_path.open("r", encoding="utf-8") as handle:
            official = yaml.safe_load(handle)
        normalized = validate_style_baseline(official)
        self.assertEqual(normalized["baseline_id"], "arco-official-style-v1")
        self.assertEqual(normalized["evidence"]["asset_ids"], ["identity-p01", "identity-p03"])
        self.assertEqual(normalized["axes"]["linework"]["confidence"], "HIGH")

    def test_style_baseline_evidence_and_shape_guards(self):
        insufficient = baseline_fixture()
        insufficient["evidence"]["asset_ids"] = ["identity-p01"]
        insufficient["evidence"]["sha256"] = ["hash-p01"]
        self.assertCode("STYLE_BASELINE_EVIDENCE_INSUFFICIENT", lambda: validate_style_baseline(insufficient))

        duplicate_asset = baseline_fixture()
        duplicate_asset["evidence"]["asset_ids"] = ["identity-p01", "identity-p01"]
        self.assertCode("STYLE_BASELINE_DUPLICATE_EVIDENCE", lambda: validate_style_baseline(duplicate_asset))

        duplicate_hash = baseline_fixture()
        duplicate_hash["evidence"]["sha256"] = ["same-hash", "same-hash"]
        self.assertCode("STYLE_BASELINE_DUPLICATE_EVIDENCE", lambda: validate_style_baseline(duplicate_hash))

        mismatched_lengths = baseline_fixture()
        mismatched_lengths["evidence"]["sha256"] = ["hash-p01"]
        self.assertCode("STYLE_BASELINE_INVALID", lambda: validate_style_baseline(mismatched_lengths))

        bad_schema = baseline_fixture()
        bad_schema["schema_version"] = 2
        self.assertCode("STYLE_BASELINE_INVALID", lambda: validate_style_baseline(bad_schema))
        bad_mode = baseline_fixture()
        bad_mode["mode"] = "active"
        self.assertCode("STYLE_BASELINE_INVALID", lambda: validate_style_baseline(bad_mode))

        bad_source = baseline_fixture()
        bad_source["source_family_id"] = ""
        self.assertCode("STYLE_BASELINE_SOURCE_MISMATCH", lambda: validate_style_baseline(bad_source))

        unknown_axis = baseline_fixture()
        unknown_axis["axes"]["unknown_axis"] = {"description": "rendering", "confidence": "high"}
        self.assertCode("STYLE_BASELINE_INVALID", lambda: validate_style_baseline(unknown_axis))
        missing_core = baseline_fixture()
        del missing_core["axes"]["linework"]
        self.assertCode("STYLE_BASELINE_INVALID", lambda: validate_style_baseline(missing_core))
        bad_consensus = baseline_fixture()
        bad_consensus["consensus_rule"]["minimum_support"] = 1
        self.assertCode("STYLE_BASELINE_INVALID", lambda: validate_style_baseline(bad_consensus))
        self.assertCode("STYLE_BASELINE_MISSING", lambda: validate_style_baseline(None))

    def test_style_context_primary_ignores_baseline_and_preserves_provenance(self):
        references = resolve_style_references([
            style_ref("context-primary", priority="primary", axes=["linework"]),
        ])
        context = resolve_style_context(
            resolved_style_references=references,
            style_briefs=[style_brief("context-primary", "primary", ["linework"])],
            official_style_baseline={"this": "must be ignored"},
        )
        self.assertEqual(context["mode"], "external")
        self.assertEqual(context["primary_reference_id"], "context-primary")
        self.assertIsNone(context["secondary_reference_id"])
        self.assertEqual(context["resolved_axes"]["linework"]["source"], "context-primary")
        self.assertEqual(context["resolved_axes"]["linework"]["source_type"], "primary")
        self.assertNotIn("shading", context["resolved_axes"])
        self.assertEqual(context["protected_identity_properties"], ["hair_color", "eye_color", "variant_key_colors"])

    def test_style_context_primary_secondary_only_fills_unowned_axes(self):
        references = resolve_style_references([
            style_ref("context-secondary", priority="secondary", axes=["shading", "texture_language"]),
            style_ref("context-primary", priority="primary", axes=["linework"]),
        ])
        context = resolve_style_context(
            resolved_style_references=references,
            style_briefs=[
                style_brief("context-primary", "primary", ["linework"]),
                style_brief("context-secondary", "secondary", ["shading", "texture_language"]),
            ],
            official_style_baseline=baseline_fixture(),
        )
        self.assertEqual(list(context["resolved_axes"]), ["linework", "shading", "texture_language"])
        self.assertEqual(context["resolved_axes"]["shading"]["source_type"], "secondary")
        self.assertNotIn("color_logic", context["resolved_axes"])

    def test_style_context_requires_primary_brief_for_owned_axes(self):
        references = resolve_style_references([
            style_ref("missing-primary-brief", priority="primary", axes=["linework"]),
        ])
        self.assertCode(
            "STYLE_BRIEF_MISSING",
            lambda: resolve_style_context(
                resolved_style_references=references,
                style_briefs=[],
                official_style_baseline=None,
            ),
        )

    def test_style_context_secondary_only_uses_baseline_without_mixing(self):
        references = resolve_style_references([
            style_ref("secondary-only", priority="secondary", axes=["linework"]),
        ])
        context = resolve_style_context(
            resolved_style_references=references,
            style_briefs=[style_brief("secondary-only", "secondary", ["linework"])],
            official_style_baseline=baseline_fixture(),
        )
        self.assertEqual(context["mode"], "official_fallback")
        self.assertIsNone(context["primary_reference_id"])
        self.assertEqual(context["secondary_reference_id"], "secondary-only")
        self.assertEqual(context["resolved_axes"]["linework"]["source_type"], "official_baseline")
        self.assertEqual(context["resolved_axes"]["linework"]["source"], "test-official-baseline")

    def test_style_context_official_fallback_and_user_axis_override(self):
        empty = resolve_style_references([])
        context = resolve_style_context(
            resolved_style_references=empty,
            style_briefs=[],
            official_style_baseline=baseline_fixture(),
            user_style_overrides={
                "linework": {"description": "user-defined contour language"},
                "edge_treatment": {"description": "user-defined clean edge grouping", "confidence": "low"},
            },
        )
        self.assertEqual(context["mode"], "official_fallback")
        self.assertEqual(context["resolved_axes"]["linework"]["source_type"], "user_override")
        self.assertEqual(context["resolved_axes"]["linework"]["confidence"], "HIGH")
        self.assertEqual(context["resolved_axes"]["edge_treatment"]["confidence"], "LOW")
        self.assertEqual(context["protected_identity_properties"], ["hair_color", "eye_color", "variant_key_colors"])

        self.assertCode(
            "STYLE_OVERRIDE_AXIS_INVALID",
            lambda: resolve_style_context(
                resolved_style_references=empty,
                style_briefs=[],
                official_style_baseline=baseline_fixture(),
                user_style_overrides={"unknown_axis": {"description": "bad"}},
            ),
        )
        self.assertCode(
            "STYLE_OVERRIDE_DESCRIPTION_INVALID",
            lambda: resolve_style_context(
                resolved_style_references=empty,
                style_briefs=[],
                official_style_baseline=baseline_fixture(),
                user_style_overrides={"linework": {"description": ""}},
            ),
        )

    def test_compile_style_instructions_stable_axis_order(self):
        context = {
            "mode": "external",
            "primary_reference_id": "style-primary",
            "secondary_reference_id": None,
            "resolved_axes": {
                axis: {
                    "description": f"description for {axis}",
                    "source": "style-primary",
                    "source_type": "primary",
                    "confidence": "LOW",
                }
                for axis in reversed(STYLE_AXES)
            },
            "protected_identity_properties": [],
        }
        compiled = compile_style_instructions(context)
        labels = [line[2:].split(":", 1)[0] for line in compiled.splitlines() if line.startswith("- ")]
        expected = [
            "Linework", "Shading", "Color logic", "Highlight language", "Material rendering",
            "Texture language", "Lighting language", "Background rendering", "Detail density",
            "Edge treatment",
        ]
        self.assertEqual(labels, expected)
        self.assertEqual(
            compiled,
            compile_style_instructions({**context, "resolved_axes": dict(reversed(list(context["resolved_axes"].items())))}),
        )

    def test_style_prompt_snapshots_are_stable(self):
        fixture_root = SCRIPT_DIR / "fixtures" / "style_prompt"
        for case_name in ("external_primary", "primary_secondary_override", "official_fallback"):
            with self.subTest(case_name=case_name):
                _context, prompt = compile_style_prompt_fixture(case_name)
                expected = (fixture_root / f"{case_name}.expected.txt").read_text(encoding="utf-8").rstrip("\r\n")
                self.assertEqual(prompt, expected)

    def test_style_hygiene_v11_snapshots_are_stable(self):
        fixture_root = SCRIPT_DIR / "fixtures" / "style_prompt"
        for case_name in ("external_primary", "primary_secondary_override", "official_fallback"):
            with self.subTest(case_name=case_name):
                _context, prompt = compile_style_prompt_fixture(
                    case_name,
                    rendering_hygiene_policy=STYLE_POLICY,
                )
                expected = (fixture_root / f"{case_name}.hygiene-v1.1.expected.txt").read_text(encoding="utf-8").rstrip("\r\n")
                self.assertEqual(prompt, expected)

    def test_style_only_snapshots_remain_unchanged_when_hygiene_is_omitted(self):
        fixture_root = SCRIPT_DIR / "fixtures" / "style_prompt"
        for case_name in ("external_primary", "primary_secondary_override", "official_fallback"):
            with self.subTest(case_name=case_name):
                _context, style_only = compile_style_prompt_fixture(case_name)
                _same_context, with_disabled_policy = compile_style_prompt_fixture(
                    case_name,
                    rendering_hygiene_policy={
                        **STYLE_POLICY,
                        **{
                            family: {**STYLE_POLICY[family], "enabled": False}
                            for family in (
                            "unsupported_detail_inflation",
                            "highlight_organization_drift",
                            "texture_noise_drift",
                            "material_rendering_drift",
                            "lighting_effect_inflation",
                            "detail_hierarchy_flattening",
                            )
                        },
                    },
                )
                self.assertEqual(with_disabled_policy, style_only)
                expected = (fixture_root / f"{case_name}.expected.txt").read_text(encoding="utf-8").rstrip("\r\n")
                self.assertEqual(style_only, expected)

    def test_hygiene_policy_accepts_registered_rules_and_is_deterministic(self):
        context, _prompt = compile_style_prompt_fixture("external_primary")
        first = compile_rendering_hygiene(context, policy=STYLE_POLICY)
        self.assertTrue(first)
        self.assertEqual(first, compile_rendering_hygiene(context, policy=STYLE_POLICY))

    def test_hygiene_policy_v11_axis_matrix_is_frozen(self):
        self.assertEqual(STYLE_POLICY["schema_version"], 2)
        self.assertEqual(STYLE_POLICY["policy_id"], "style-aware-rendering-hygiene-v1.1")
        self.assertEqual(
            {
                family: rule["requires"]["any_of"]
                for family, rule in STYLE_POLICY.items()
                if family not in {"schema_version", "policy_id"}
            },
            {
                "unsupported_detail_inflation": ["detail_density"],
                "highlight_organization_drift": ["highlight_language"],
                "texture_noise_drift": ["texture_language"],
                "material_rendering_drift": ["material_rendering"],
                "lighting_effect_inflation": ["lighting_language"],
                "detail_hierarchy_flattening": ["detail_density", "background_rendering"],
            },
        )

    def test_hygiene_policy_rejects_unknown_rule(self):
        context, _prompt = compile_style_prompt_fixture("external_primary")
        unknown_policy = {**STYLE_POLICY, "future_unregistered_rule": {"enabled": True}}
        self.assertCode(
            "RENDERING_HYGIENE_UNSUPPORTED_RULE",
            lambda: compile_rendering_hygiene(context, policy=unknown_policy),
        )

    def test_hygiene_policy_rejects_incomplete_or_invalid_policy(self):
        context, _prompt = compile_style_prompt_fixture("external_primary")
        incomplete = dict(STYLE_POLICY)
        incomplete.pop("texture_noise_drift")
        self.assertCode(
            "RENDERING_HYGIENE_POLICY_INVALID",
            lambda: compile_rendering_hygiene(context, policy=incomplete),
        )
        invalid_toggle = {**STYLE_POLICY, "texture_noise_drift": {"enabled": "yes"}}
        self.assertCode(
            "RENDERING_HYGIENE_POLICY_INVALID",
            lambda: compile_rendering_hygiene(context, policy=invalid_toggle),
        )
        invalid_requires = copy.deepcopy(STYLE_POLICY)
        invalid_requires["texture_noise_drift"]["requires"]["any_of"] = ["not_a_style_axis"]
        self.assertCode(
            "RENDERING_HYGIENE_POLICY_INVALID",
            lambda: compile_rendering_hygiene(context, policy=invalid_requires),
        )
        duplicate_requires = copy.deepcopy(STYLE_POLICY)
        duplicate_requires["texture_noise_drift"]["requires"]["any_of"] = [
            "texture_language",
            "texture_language",
        ]
        self.assertCode(
            "RENDERING_HYGIENE_POLICY_INVALID",
            lambda: compile_rendering_hygiene(context, policy=duplicate_requires),
        )

    def test_hygiene_compiler_is_relative_and_includes_escape_clause(self):
        context, _prompt = compile_style_prompt_fixture("external_primary")
        hygiene = compile_rendering_hygiene(context, policy=STYLE_POLICY)
        lowered = hygiene.lower()
        self.assertIn(RENDERING_HYGIENE_HEADER.lower(), lowered)
        self.assertIn("resolved style", lowered)
        self.assertIn("explicit user requests", lowered)
        self.assertIn("do not suppress any rendering characteristic supported by either", lowered)
        self.assertIn("constrain only unsupported additions", lowered)
        for forced_style in ("cel shading only", "painterly rendering", "smooth texture", "watercolor style"):
            self.assertNotIn(forced_style, lowered)

    def test_hygiene_compiler_does_not_emit_who_description(self):
        context, _prompt = compile_style_prompt_fixture("external_primary")
        hygiene = compile_rendering_hygiene(context, policy=STYLE_POLICY).lower()
        for identity_term in ("hair color", "eye color", "face:", "body shape", "outfit", "variant", "arco"):
            self.assertNotIn(identity_term, hygiene)

    def test_hygiene_compiler_does_not_mutate_style_context_or_axes(self):
        context, _prompt = compile_style_prompt_fixture("external_primary")
        before = copy.deepcopy(context)
        axes_before = copy.deepcopy(context["resolved_axes"])
        compile_rendering_hygiene(context, policy=STYLE_POLICY)
        self.assertEqual(context, before)
        self.assertEqual(context["resolved_axes"], axes_before)

    def test_hygiene_does_not_globally_ban_grain_gloss_or_lighting(self):
        context, _prompt = compile_style_prompt_fixture("external_primary")
        hygiene = compile_rendering_hygiene(context, policy=STYLE_POLICY).lower()
        self.assertNotIn("no grain", hygiene)
        self.assertNotIn("remove grain", hygiene)
        self.assertNotIn("no gloss", hygiene)
        self.assertNotIn("no rim light", hygiene)
        self.assertNotIn("no bloom", hygiene)
        self.assertIn("constrain only unsupported texture noise", hygiene)

    def test_hygiene_all_disabled_compiles_to_empty_text(self):
        context, _prompt = compile_style_prompt_fixture("external_primary")
        policy = {
            **STYLE_POLICY,
            **{
                family: {**STYLE_POLICY[family], "enabled": False}
                for family in (
                "unsupported_detail_inflation",
                "highlight_organization_drift",
                "texture_noise_drift",
                "material_rendering_drift",
                "lighting_effect_inflation",
                "detail_hierarchy_flattening",
                )
            },
        }
        self.assertEqual(compile_rendering_hygiene(context, policy=policy), "")

    def test_hygiene_preserves_clean_cel_painterly_and_watercolor_styles(self):
        style_cases = {
            "clean-cel": {
                "linework": "clean linework",
                "shading": "restrained cel shading",
                "highlight_language": "grouped highlights",
                "texture_language": "low texture",
            },
            "painterly": {
                "shading": "soft painterly shading",
                "texture_language": "visible brush texture",
                "edge_treatment": "soft edge treatment",
            },
            "watercolor-grain": {
                "texture_language": "visible paper texture, pigment granulation, and grain",
                "shading": "watercolor edge behavior",
            },
        }
        forbidden_global_commands = (
            "no texture",
            "no highlights",
            "flat shading only",
            "clean cel shading",
            "smooth texture",
            "hard anime edges",
            "no grain",
            "remove texture",
            "smooth surface",
        )
        compiled_prompts = {}
        for case_name, axes in style_cases.items():
            style_context = {
                "mode": "official_fallback",
                "primary_reference_id": None,
                "secondary_reference_id": None,
                "resolved_axes": {
                    axis: {
                        "description": description,
                        "source": "test-official-baseline",
                        "source_type": "official_baseline",
                    }
                    for axis, description in axes.items()
                },
                "protected_identity_properties": [],
            }
            prompt = compile_prompt(
                base_prompt="Arco stands in a quiet scene.",
                references=[],
                style_context=style_context,
                rendering_hygiene_policy=STYLE_POLICY,
            )
            compiled_prompts[case_name] = prompt
            for description in axes.values():
                self.assertIn(description, prompt)
            hygiene = prompt[prompt.index(RENDERING_HYGIENE_HEADER):]
            lowered_hygiene = hygiene.lower()
            for command in forbidden_global_commands:
                self.assertNotIn(command, lowered_hygiene)
            self.assertIn("priority: honor explicit user requests first", lowered_hygiene)
        self.assertEqual(len(set(compiled_prompts.values())), 3)

    def test_hygiene_activation_uses_axis_keys_not_free_text_keywords(self):
        context = {
            "resolved_axes": {
                "linework": {
                    "description": (
                        "words about detail density, highlights, texture, materials, and lighting "
                        "that do not declare those structured axes"
                    )
                }
            },
            "protected_identity_properties": [],
        }
        self.assertEqual(compile_rendering_hygiene(context, policy=STYLE_POLICY), "")

    def test_hygiene_case01_axis_activation_omits_lighting_material_and_texture(self):
        context = json.loads(
            (SCRIPT_DIR.parent / "evaluation" / "style-regression" / "style-context" / "case-01" / "resolved-style-context.json")
            .read_text(encoding="utf-8")
        )
        hygiene = compile_rendering_hygiene(context, policy=STYLE_POLICY)
        self.assertIn("Detail density:", hygiene)
        self.assertIn("Highlight organization:", hygiene)
        self.assertIn(context["resolved_axes"]["detail_density"]["description"], hygiene)
        self.assertIn(context["resolved_axes"]["highlight_language"]["description"], hygiene)
        self.assertNotIn("Texture:", hygiene)
        self.assertNotIn("Material rendering:", hygiene)
        self.assertNotIn("Lighting:", hygiene)

    def test_hygiene_case04_axis_activation_preserves_watercolor_and_grain(self):
        context = json.loads(
            (SCRIPT_DIR.parent / "evaluation" / "style-regression" / "style-context" / "case-04" / "resolved-style-context.json")
            .read_text(encoding="utf-8")
        )
        hygiene = compile_rendering_hygiene(context, policy=STYLE_POLICY)
        self.assertIn("Texture:", hygiene)
        self.assertIn("Material rendering:", hygiene)
        self.assertIn("Detail hierarchy:", hygiene)
        self.assertIn(context["resolved_axes"]["texture_language"]["description"], hygiene)
        self.assertIn(context["resolved_axes"]["material_rendering"]["description"], hygiene)
        self.assertIn(context["resolved_axes"]["background_rendering"]["description"], hygiene)
        self.assertNotIn("Highlight organization:", hygiene)
        self.assertNotIn("Lighting:", hygiene)
        for preserved in ("paperlike grain", "translucent color washes", "subtle granulation"):
            self.assertIn(preserved, hygiene)

    def test_lighting_hygiene_does_not_introduce_unsupported_effect_vocabulary(self):
        plain_description = "balanced directional illumination with restrained secondary accents"
        context = {
            "resolved_axes": {"lighting_language": {"description": plain_description}},
            "protected_identity_properties": [],
        }
        hygiene = compile_rendering_hygiene(context, policy=STYLE_POLICY).lower()
        self.assertIn(plain_description, hygiene)
        for unsupported in ("bloom", "rim light", "rim-light", "volumetric glow"):
            self.assertNotIn(unsupported, hygiene)

        supported_description = "diffuse bloom with a restrained rim light"
        supported = copy.deepcopy(context)
        supported["resolved_axes"]["lighting_language"]["description"] = supported_description
        supported_hygiene = compile_rendering_hygiene(supported, policy=STYLE_POLICY).lower()
        self.assertIn(supported_description, supported_hygiene)

    def test_detail_hierarchy_is_relational_not_generic_detail_reduction(self):
        context = {
            "resolved_axes": {
                "background_rendering": {"description": "simple pale background fields"},
            },
            "protected_identity_properties": [],
        }
        hygiene = compile_rendering_hygiene(context, policy=STYLE_POLICY).lower()
        self.assertIn("relative subject, secondary-element, and background hierarchy", hygiene)
        self.assertIn("do not globally raise or lower detail density", hygiene)
        for generic_reduction in ("reduce detail", "lower detail everywhere", "simplify all detail"):
            self.assertNotIn(generic_reduction, hygiene)

    def test_compile_prompt_places_hygiene_after_scene_and_before_identity_constraint(self):
        _context, prompt = compile_style_prompt_fixture(
            "external_primary",
            rendering_hygiene_policy=STYLE_POLICY,
        )
        self.assertLess(prompt.index("Arco stands beneath a tree."), prompt.index(RENDERING_HYGIENE_HEADER))
        self.assertLess(prompt.index(RENDERING_HYGIENE_HEADER), prompt.index("no exaggerated chest volume"))

    def test_compile_prompt_hygiene_keeps_resolved_style_block_unchanged(self):
        _context, style_only = compile_style_prompt_fixture("primary_secondary_override")
        _context, with_hygiene = compile_style_prompt_fixture(
            "primary_secondary_override",
            rendering_hygiene_policy=STYLE_POLICY,
        )
        style_start = style_only.index("Rendering style requirements:")
        style_end = style_only.index("\n\n", style_start)
        hygiene_style_start = with_hygiene.index("Rendering style requirements:")
        hygiene_style_end = with_hygiene.index("\n\n", hygiene_style_start)
        self.assertEqual(style_only[style_start:style_end], with_hygiene[hygiene_style_start:hygiene_style_end])
        self.assertIn("visible brush modulation", with_hygiene)
        self.assertIn("layered painterly surface marks", with_hygiene)

    def test_compile_prompt_with_enabled_hygiene_requires_style_context(self):
        self.assertCode(
            "STYLE_CONTEXT_MISSING",
            lambda: compile_prompt(
                base_prompt="Arco stands beneath a tree.",
                references=[],
                rendering_hygiene_policy=STYLE_POLICY,
            ),
        )

    def test_validate_rendering_hygiene_accepts_valid_relative_block(self):
        context, prompt = compile_style_prompt_fixture(
            "external_primary",
            rendering_hygiene_policy=STYLE_POLICY,
        )
        self.assertIsNone(validate_rendering_hygiene(context, prompt, policy=STYLE_POLICY))

    def test_validate_rendering_hygiene_detects_missing_block(self):
        context, prompt = compile_style_prompt_fixture(
            "external_primary",
            rendering_hygiene_policy=STYLE_POLICY,
        )
        hygiene = compile_rendering_hygiene(context, policy=STYLE_POLICY)
        prompt_without_hygiene = prompt.replace(f"\n\n{hygiene}", "", 1)
        self.assertCode(
            "RENDERING_HYGIENE_MISSING",
            lambda: validate_rendering_hygiene(context, prompt_without_hygiene, policy=STYLE_POLICY),
        )

    def test_validate_rendering_hygiene_rejects_identity_pollution(self):
        context, prompt = compile_style_prompt_fixture(
            "external_primary",
            rendering_hygiene_policy=STYLE_POLICY,
        )
        expected = compile_rendering_hygiene(context, policy=STYLE_POLICY)
        polluted = expected.replace(
            RENDERING_HYGIENE_HEADER,
            f"{RENDERING_HYGIENE_HEADER}\n- Face: Preserve the face.",
            1,
        )
        polluted_prompt = prompt.replace(expected, polluted, 1)
        self.assertCode(
            "RENDERING_HYGIENE_IDENTITY_POLLUTION",
            lambda: validate_rendering_hygiene(context, polluted_prompt, policy=STYLE_POLICY),
        )

    def test_validate_rendering_hygiene_rejects_template_style_conflict(self):
        context, prompt = compile_style_prompt_fixture(
            "external_primary",
            rendering_hygiene_policy=STYLE_POLICY,
        )
        expected = compile_rendering_hygiene(context, policy=STYLE_POLICY)
        conflicting = expected.replace(
            "constrain only unsupported additions",
            "remove all grain regardless of the resolved style",
        )
        conflicting_prompt = prompt.replace(expected, conflicting, 1)
        self.assertCode(
            "RENDERING_HYGIENE_STYLE_CONFLICT",
            lambda: validate_rendering_hygiene(context, conflicting_prompt, policy=STYLE_POLICY),
        )

    def test_compile_style_instructions_primary_context(self):
        _context, prompt = compile_style_prompt_fixture("external_primary")
        self.assertIn("Linework: thin, clean, restrained contours", prompt)
        self.assertIn("Shading: restrained cel shading with compact shadows", prompt)
        self.assertNotIn("confidence", prompt.lower())
        self.assertNotIn("HIGH", prompt)

    def test_compile_style_instructions_secondary_axis(self):
        _context, prompt = compile_style_prompt_fixture("primary_secondary_override")
        self.assertIn("Edge treatment: soft transitions with selectively retained crisp edges", prompt)

    def test_compile_style_instructions_user_override(self):
        _context, prompt = compile_style_prompt_fixture("primary_secondary_override")
        self.assertIn("Lighting language: cold blue night illumination", prompt)
        self.assertIn("Shading: painterly form transitions with visible brush modulation", prompt)
        self.assertIn("Texture language: layered painterly surface marks", prompt)
        self.assertNotIn("warm lighting", prompt)
        self.assertNotIn("warm directional lighting", prompt)

    def test_compile_style_instructions_official_fallback(self):
        context, prompt = compile_style_prompt_fixture("official_fallback")
        self.assertEqual(context["mode"], "official_fallback")
        self.assertIn("Linework: conservative clean linework with controlled contours", prompt)
        self.assertNotIn("external style reference", prompt.lower())
        self.assertNotIn("primary external style", prompt.lower())
        self.assertNotIn("secondary external style", prompt.lower())

    def test_compile_style_instructions_preserves_intrinsic_color_scope(self):
        _context, prompt = compile_style_prompt_fixture("primary_secondary_override")
        self.assertIn("overall rendering and palette relationships only", prompt)
        self.assertIn("hair color", prompt)
        self.assertIn("eye color", prompt)
        self.assertIn("variant key colors", prompt)

    def test_compile_style_instructions_does_not_emit_missing_axis(self):
        context = {
            "resolved_axes": {
                "linework": {"description": "thin clean contours"},
                "shading": {"description": "restrained cel shading"},
                "texture_language": {"description": "low texture"},
            },
            "protected_identity_properties": [],
        }
        compiled = compile_style_instructions(context)
        self.assertNotIn("Lighting language:", compiled)
        self.assertNotIn("lighting style", compiled.lower())

    def test_compile_style_instructions_does_not_invent_rendering_terms(self):
        context = {
            "resolved_axes": {"linework": {"description": "thin, clean, restrained"}},
            "protected_identity_properties": [],
        }
        compiled = compile_style_instructions(context).lower()
        for term in ("cinematic", "volumetric", "painterly", "glossy", "strong rim light", "rich texture"):
            self.assertNotIn(term, compiled)

    def test_compile_style_instructions_rejects_unknown_axis(self):
        context = {
            "resolved_axes": {"unlisted_axis": {"description": "invented style"}},
            "protected_identity_properties": [],
        }
        self.assertCode("STYLE_AXIS_UNDECLARED", lambda: compile_style_instructions(context))

    def test_reference_instructions_name_style_source_responsibility(self):
        instructions = compile_reference_instructions([
            style_ref("style-source-primary", priority="primary", axes=["linework"]),
            style_ref("style-source-secondary", priority="secondary", axes=["shading"]),
        ])
        self.assertIn("Use as the primary Style Reference.", instructions)
        self.assertIn("Use as the secondary Style Reference.", instructions)
        self.assertNotIn("thin clean", instructions)

    def test_compile_prompt_without_style_context_preserves_legacy_behavior(self):
        reference = request_ref("legacy-identity")
        identity = {"facts": [{"field_id": "body.chest_proportion", "value": "small-to-modest", "status": "UNCERTAIN"}]}
        fragments = resolve_identity_fact_prompt_fragments(
            identity, exposure_profile="portrait", allow_uncertain_working=True
        )
        reference_text = compile_reference_instructions([reference])
        expected = " ".join(
            [item["text"] for item in fragments["fragments"]]
            + [reference_text, "Arco stands beneath a tree.", " ".join(item["text"] for item in fragments["soft_constraints"])]
        ).strip()
        prompt = compile_prompt(
            base_prompt="Arco stands beneath a tree.",
            references=[reference],
            identity=identity,
            exposure_profile="portrait",
            allow_uncertain_working=True,
        )
        self.assertEqual(prompt, expected)

    def test_compile_prompt_with_style_context_places_style_before_scene(self):
        _context, prompt = compile_style_prompt_fixture("external_primary")
        self.assertLess(prompt.index("a slim, lightly built figure"), prompt.index("Rendering style requirements:"))
        self.assertLess(prompt.index("Rendering style requirements:"), prompt.index("Reference external-style-01:"))
        self.assertLess(prompt.index("Reference external-style-01:"), prompt.index("Arco stands beneath a tree."))
        self.assertLess(prompt.index("Arco stands beneath a tree."), prompt.index("no exaggerated chest volume"))

    def test_compile_prompt_requires_context_when_style_reference_exists(self):
        self.assertCode(
            "STYLE_CONTEXT_MISSING",
            lambda: compile_prompt(
                base_prompt="Arco in a quiet garden.",
                references=[style_ref("missing-context", priority="primary", axes=["linework"])],
            ),
        )

    def test_compile_prompt_external_context_does_not_emit_baseline(self):
        _context, prompt = compile_style_prompt_fixture("external_primary")
        self.assertNotIn("test-official-baseline", prompt)
        self.assertNotIn("Official Baseline-only rendering characteristics", prompt)

    def test_compile_prompt_secondary_only_context_uses_official_fallback(self):
        resolved_references = resolve_style_references([
            style_ref("secondary-only-prompt", priority="secondary", axes=["linework"]),
        ])
        context = resolve_style_context(
            resolved_style_references=resolved_references,
            style_briefs=[style_brief("secondary-only-prompt", "secondary", ["linework"])],
            official_style_baseline=baseline_fixture(),
        )
        prompt = compile_prompt(
            base_prompt="Arco in a quiet garden.",
            references=resolved_references["references"],
            style_context=context,
        )
        self.assertEqual(context["mode"], "official_fallback")
        self.assertIn("Linework: conservative rendering language for linework", prompt)
        self.assertNotIn("clean rendering for linework", prompt)

    def test_compile_prompt_user_override_remains_axis_local(self):
        _context, prompt = compile_style_prompt_fixture("primary_secondary_override")
        self.assertIn("Shading: painterly form transitions with visible brush modulation", prompt)
        self.assertIn("Texture language: layered painterly surface marks", prompt)
        self.assertIn("Edge treatment: soft transitions with selectively retained crisp edges", prompt)
        self.assertIn("Lighting language: cold blue night illumination", prompt)
        self.assertNotIn("warm lighting", prompt)

    def test_validate_style_prompt_accepts_valid_external_style(self):
        _context, prompt = compile_style_prompt_fixture("external_primary")
        self.assertIsNone(validate_style_prompt(_context, prompt))

    def test_validate_style_prompt_detects_missing_axis(self):
        context, prompt = compile_style_prompt_fixture("primary_secondary_override")
        prompt = prompt.replace(
            "- Shading: painterly form transitions with visible brush modulation\n",
            "",
        )
        self.assertCode("STYLE_AXIS_NOT_COMPILED", lambda: validate_style_prompt(context, prompt))

    def test_validate_style_prompt_detects_undeclared_axis(self):
        context, prompt = compile_style_prompt_fixture("external_primary")
        prompt = prompt.replace(
            "\n\nReference arco-identity-01:",
            "\n- Lighting language: dramatic rim lighting\n\nReference arco-identity-01:",
            1,
        )
        self.assertCode("STYLE_AXIS_UNDECLARED", lambda: validate_style_prompt(context, prompt))

    def test_validate_style_prompt_detects_missing_identity_protection(self):
        context, prompt = compile_style_prompt_fixture("primary_secondary_override")
        prompt = "\n".join(
            line for line in prompt.splitlines()
            if not line.startswith("  Color scope:")
        )
        self.assertCode("STYLE_IDENTITY_PROTECTION_MISSING", lambda: validate_style_prompt(context, prompt))

    def test_validate_style_prompt_detects_who_pollution(self):
        context, prompt = compile_style_prompt_fixture("external_primary")
        context = copy.deepcopy(context)
        context["resolved_axes"]["linework"]["description"] = "long blonde hair with clean contours"
        self.assertCode("STYLE_PROMPT_WHO_POLLUTION", lambda: validate_style_prompt(context, prompt))

    def test_validate_style_prompt_detects_unused_style_reference(self):
        context, _prompt = compile_style_prompt_fixture("external_primary")
        self.assertCode(
            "STYLE_REFERENCE_UNUSED",
            lambda: validate_style_prompt(context, "Arco stands beneath a tree."),
        )

    def test_validate_style_prompt_detects_reference_context_mismatch(self):
        mismatched_context, _prompt = compile_style_prompt_fixture("external_primary")
        self.assertCode(
            "STYLE_CONTEXT_REFERENCE_MISMATCH",
            lambda: compile_prompt(
                base_prompt="Arco stands beneath a tree.",
                references=[style_ref("external-style-99", priority="primary", axes=["linework"])],
                style_context=mismatched_context,
            ),
        )

    def test_compile_prompt_rejects_official_fallback_when_external_primary_exists(self):
        fallback_context, _prompt = compile_style_prompt_fixture("official_fallback")
        self.assertCode(
            "STYLE_CONTEXT_REFERENCE_MISMATCH",
            lambda: compile_prompt(
                base_prompt="Arco stands beneath a tree.",
                references=[style_ref("actual-primary", priority="primary", axes=["linework"])],
                style_context=fallback_context,
            ),
        )

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
