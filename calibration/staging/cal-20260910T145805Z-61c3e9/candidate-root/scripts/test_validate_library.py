#!/usr/bin/env python3
"""Regression tests for the Arco library validator and recovery publisher."""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from publish_calibration import publish, rollback
from validate_library import validate


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


class Fixture:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "arco"
        shutil.copytree(PROJECT_ROOT, self.root)
        # Regression fixtures start from a clean revision-0 library even when
        # PROJECT_ROOT is a staged revision-1 candidate.
        assets_path = self.root / "character" / "assets.yaml"
        assets = read_yaml(assets_path)
        assets["revision"] = 0
        assets["last_calibration_id"] = None
        assets["assets"] = []
        write_yaml(assets_path, assets)
        expressions_path = self.root / "character" / "expressions.yaml"
        expressions = read_yaml(expressions_path)
        expressions["revision"] = 0
        expressions["last_calibration_id"] = None
        write_yaml(expressions_path, expressions)
        # Published History belongs to PROJECT_ROOT, not to this synthetic
        # revision-0 fixture. Each test creates only the calibration records it needs.
        calibration_dir = self.root / "calibration"
        if calibration_dir.exists():
            shutil.rmtree(calibration_dir)

    def close(self) -> None:
        self.temp.cleanup()

    def add_asset(
        self,
        asset_id: str,
        *,
        group: str,
        level: str = "identity",
        variant_id=None,
        roles=None,
        view_angle: str = "front",
    ) -> dict:
        relative = Path("assets") / "arco" / f"{asset_id}.png"
        absolute = self.root / relative
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_bytes((asset_id + "\n").encode())
        registry_path = self.root / "character" / "assets.yaml"
        registry = read_yaml(registry_path)
        entry = {
            "asset_id": asset_id,
            "path": relative.as_posix(),
            "variant_id": variant_id,
            "state_ids": [],
            "reference_level": level,
            "view_angle": view_angle,
            "roles": roles or ["identity_evidence"],
            "purpose_note_zh": "测试证据",
            "source_kind": "official",
            "source_authority": "primary_official",
            "source_group_id": group,
            "derived_from_asset_id": None,
            "source_note": "测试夹具",
            "sha256": digest(absolute),
        }
        registry["assets"].append(entry)
        write_yaml(registry_path, registry)
        return entry

    def make_portrait_ready(self) -> None:
        self.add_asset("portrait-official", group="portrait-source")
        path = self.root / "character" / "identity.yaml"
        identity = read_yaml(path)
        for fact in identity["facts"]:
            if "portrait" in fact["required_for"]:
                fact["value"] = f"fixture-{fact['field_id']}"
                fact["status"] = "CANON"
                fact["evidence_ids"] = ["portrait-official"]
                fact["canon_basis"] = {
                    "kind": "explicit_official_definition",
                    "source_note": "测试夹具中的官方明确设定",
                }
        write_yaml(path, identity)

    def add_variant_with_states(self) -> None:
        self.add_asset(
            "test-variant-primary",
            group="variant-primary-source",
            level="primary",
            variant_id="test-variant",
            roles=["variant_evidence", "state_evidence"],
        )
        variant_dir = self.root / "variants" / "test-variant"
        state_dir = variant_dir / "states"
        state_dir.mkdir(parents=True, exist_ok=True)
        variant = {
            "schema_version": 1,
            "entity_type": "variant",
            "entity_ref": "variants.test-variant",
            "variant_id": "test-variant",
            "display_name_zh": "测试服装",
            "lifecycle_status": "published",
            "revision": 0,
            "last_calibration_id": None,
            "facts": [
                {
                    "field_id": "outfit.upper",
                    "display_name_zh": "上装",
                    "value": None,
                    "status": "TODO_CALIBRATION",
                    "evidence_ids": [],
                    "conflicts": [],
                    "required_global": True,
                    "required_for": ["upper_body", "full_body"],
                },
                {
                    "field_id": "outfit.lower",
                    "display_name_zh": "下装",
                    "value": None,
                    "status": "TODO_CALIBRATION",
                    "evidence_ids": [],
                    "conflicts": [],
                    "required_global": True,
                    "required_for": ["full_body"],
                },
                {
                    "field_id": "outfit.footwear",
                    "display_name_zh": "鞋袜",
                    "value": None,
                    "status": "TODO_CALIBRATION",
                    "evidence_ids": [],
                    "conflicts": [],
                    "required_global": True,
                    "required_for": ["full_body"],
                },
                {
                    "field_id": "outfit.back",
                    "display_name_zh": "服装背面",
                    "value": None,
                    "status": "TODO_CALIBRATION",
                    "evidence_ids": [],
                    "conflicts": [],
                    "required_global": True,
                    "required_for": ["back_view"],
                },
            ],
            "reference_asset_ids": {
                "primary": ["test-variant-primary"],
                "secondary": [],
                "detail": [],
            },
            "state_mutable_fields": ["hair.variant_state", "headwear.visibility"],
            "must_keep_fields": ["outfit.primary_silhouette"],
            "state_groups": {
                "hairstyle": {"compatible_groups": ["headwear"]},
                "headwear": {"compatible_groups": ["hairstyle"]},
            },
            "state_files": [
                "variants/test-variant/states/hair-tied.yaml",
                "variants/test-variant/states/hat-off.yaml",
                "variants/test-variant/states/hair-loose.yaml",
            ],
            "known_generation_risks": [],
        }
        write_yaml(variant_dir / "variant.yaml", variant)
        (variant_dir / "notes.md").write_text(
            "---\nsource_entity: variants.test-variant\nsource_revision: 0\n---\n\n# 测试说明\n",
            encoding="utf-8",
        )
        common = {
            "schema_version": 1,
            "entity_type": "state",
            "variant_id": "test-variant",
            "revision": 0,
            "last_calibration_id": None,
            "status": "CANON",
            "evidence_ids": ["test-variant-primary"],
            "canon_basis": {
                "kind": "explicit_official_definition",
                "source_note": "测试夹具中的官方 State 定义",
            },
            "compatible_with": [],
            "conflicts_with": [],
            "requires": [],
        }
        write_yaml(
            state_dir / "hair-tied.yaml",
            {
                **common,
                "entity_ref": "variants.test-variant.states.hair-tied",
                "state_id": "hair-tied",
                "display_name_zh": "扎发",
                "state_group": "hairstyle",
                "exclusive_group": "hairstyle-form",
                "overrides": {"hair.variant_state": "tied"},
            },
        )
        write_yaml(
            state_dir / "hair-loose.yaml",
            {
                **common,
                "entity_ref": "variants.test-variant.states.hair-loose",
                "state_id": "hair-loose",
                "display_name_zh": "披发",
                "state_group": "hairstyle",
                "exclusive_group": "hairstyle-form",
                "overrides": {"hair.variant_state": "loose"},
            },
        )
        write_yaml(
            state_dir / "hat-off.yaml",
            {
                **common,
                "entity_ref": "variants.test-variant.states.hat-off",
                "state_id": "hat-off",
                "display_name_zh": "摘帽",
                "state_group": "headwear",
                "exclusive_group": "headwear-form",
                "overrides": {"headwear.visibility": "off"},
            },
        )
        index_path = self.root / "variants" / "index.yaml"
        index = read_yaml(index_path)
        index["variants"].append(
            {
                "variant_id": "test-variant",
                "display_name_zh": "测试服装",
                "path": "variants/test-variant/variant.yaml",
            }
        )
        write_yaml(index_path, index)


class ValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def codes(self, result) -> set[str]:
        return {issue["code"] for issue in result["issues"]}

    def test_initial_library_is_structurally_valid_but_not_ready(self) -> None:
        result = validate(self.fixture.root)
        self.assertEqual(result["structure"], "PASS")
        self.assertEqual(result["identity_readiness"]["status"], "INCOMPLETE")
        self.assertEqual(result["request_readiness"]["status"], "INCOMPLETE")

    def test_asset_cannot_carry_evidence_status(self) -> None:
        self.fixture.add_asset("official-image", group="official-source")
        path = self.fixture.root / "character" / "assets.yaml"
        data = read_yaml(path)
        data["assets"][0]["evidence_status"] = "CANON"
        write_yaml(path, data)
        result = validate(self.fixture.root)
        self.assertIn("asset-evidence-status", self.codes(result))

    def test_visual_consensus_requires_independent_groups(self) -> None:
        self.fixture.add_asset("image-one", group="same-source")
        self.fixture.add_asset("image-two", group="same-source")
        path = self.fixture.root / "character" / "identity.yaml"
        data = read_yaml(path)
        fact = data["facts"][0]
        fact.update(value="pink", status="VISUAL_CONSENSUS", evidence_ids=["image-one", "image-two"])
        write_yaml(path, data)
        result = validate(self.fixture.root)
        self.assertIn("consensus-not-independent", self.codes(result))

    def test_official_image_alone_does_not_make_a_claim_canon(self) -> None:
        self.fixture.add_asset("official-sunset", group="official-sunset-source")
        path = self.fixture.root / "character" / "identity.yaml"
        data = read_yaml(path)
        fact = data["facts"][0]
        fact.update(value="暖橙色", status="CANON", evidence_ids=["official-sunset"])
        write_yaml(path, data)
        result = validate(self.fixture.root)
        self.assertIn("canon-without-explicit-definition", self.codes(result))

    def test_portrait_can_be_ready_while_global_identity_is_incomplete(self) -> None:
        self.fixture.make_portrait_ready()
        result = validate(self.fixture.root, profiles={"portrait"})
        self.assertEqual(result["identity_readiness"]["status"], "INCOMPLETE")
        self.assertEqual(result["request_readiness"]["status"], "READY")
        full = validate(self.fixture.root, profiles={"full_body"})
        self.assertEqual(full["request_readiness"]["status"], "INCOMPLETE")
        self.assertIn("body.leg_proportion", full["request_readiness"]["missing_fields"])

    def test_temporary_evidence_only_changes_request_readiness(self) -> None:
        required = {
            "hair.base_color",
            "hair.base_identity",
            "eyes.color",
            "face.shape",
            "face.feature_relationships",
        }
        result = validate(self.fixture.root, profiles={"portrait"}, temporary=required)
        self.assertEqual(result["identity_readiness"]["status"], "INCOMPLETE")
        self.assertEqual(result["request_readiness"]["status"], "READY")
        self.assertEqual(set(result["request_readiness"]["temporary_evidence_used"]), required)

    def test_full_body_variant_lists_lower_body_and_footwear_gaps(self) -> None:
        self.fixture.add_variant_with_states()
        identity_required = {
            fact["field_id"]
            for fact in read_yaml(self.fixture.root / "character" / "identity.yaml")["facts"]
            if "full_body" in fact["required_for"]
        }
        result = validate(
            self.fixture.root,
            profiles={"full_body"},
            variant_id="test-variant",
            temporary=identity_required,
        )
        missing = result["request_readiness"]["missing_fields"]
        self.assertIn("variant:test-variant:outfit.lower", missing)
        self.assertIn("variant:test-variant:outfit.footwear", missing)

    def test_back_view_needs_variant_back_fact_and_reference(self) -> None:
        self.fixture.add_variant_with_states()
        identity_required = {
            fact["field_id"]
            for fact in read_yaml(self.fixture.root / "character" / "identity.yaml")["facts"]
            if "back_view" in fact["required_for"]
        }
        result = validate(
            self.fixture.root,
            profiles={"back_view"},
            variant_id="test-variant",
            temporary=identity_required,
        )
        missing = result["request_readiness"]["missing_fields"]
        self.assertIn("variant:test-variant:outfit.back", missing)
        self.assertIn("variant:test-variant:back-reference", missing)

    def test_markdown_revision_mismatch_is_detected(self) -> None:
        path = self.fixture.root / "character" / "identity.md"
        text = path.read_text(encoding="utf-8").replace("source_revision: 0", "source_revision: 99")
        path.write_text(text, encoding="utf-8")
        result = validate(self.fixture.root)
        self.assertIn("markdown-revision-mismatch", self.codes(result))

    def test_revision_without_history_is_detected(self) -> None:
        path = self.fixture.root / "character" / "identity.yaml"
        data = read_yaml(path)
        data["revision"] = 1
        data["last_calibration_id"] = "cal-missing"
        write_yaml(path, data)
        result = validate(self.fixture.root)
        self.assertIn("history-chain-incomplete", self.codes(result))

    def test_one_calibration_can_record_multiple_fields_for_one_entity_revision(self) -> None:
        calibration_id = "cal-20260910T130000Z-b2c3d4"
        identity_path = self.fixture.root / "character" / "identity.yaml"
        identity = read_yaml(identity_path)
        identity["revision"] = 1
        identity["last_calibration_id"] = calibration_id
        changed = identity["facts"][:2]
        changed[0]["note_zh"] = "第一项说明"
        changed[1]["note_zh"] = "第二项说明"
        write_yaml(identity_path, identity)
        markdown_path = self.fixture.root / "character" / "identity.md"
        markdown_path.write_text(
            markdown_path.read_text(encoding="utf-8").replace("source_revision: 0", "source_revision: 1"),
            encoding="utf-8",
        )
        history = {
            "schema_version": 1,
            "calibration_id": calibration_id,
            "timestamp": "2026-09-10T13:00:00Z",
            "operation": "update",
            "user_confirmed": True,
            "confirmed_at": "2026-09-10T12:59:00Z",
            "reason": "同一实体的多字段标定测试",
            "evidence_ids": [],
            "targets": [
                {
                    "entity_ref": "character.identity",
                    "target_type": "identity_field",
                    "target_id": fact["field_id"],
                    "revision_before": 0,
                    "revision_after": 1,
                    "changed_fields": ["note_zh"],
                    "before": {"note_zh": "", "status": "TODO_CALIBRATION"},
                    "after": {"note_zh": fact["note_zh"], "status": "TODO_CALIBRATION"},
                    "status_before": "TODO_CALIBRATION",
                    "status_after": "TODO_CALIBRATION",
                }
                for fact in changed
            ],
            "validation_result": {"structure": "PASS"},
        }
        history_path = self.fixture.root / "calibration" / "history" / f"{calibration_id}.yaml"
        write_yaml(history_path, history)
        history_path.with_suffix(".complete").write_text("complete\n", encoding="utf-8")
        result = validate(self.fixture.root)
        self.assertEqual(result["structure"], "PASS")

    def test_state_group_compatibility_and_exclusivity(self) -> None:
        self.fixture.add_variant_with_states()
        valid = validate(
            self.fixture.root,
            profiles={"portrait"},
            variant_id="test-variant",
            selected_states=["hair-tied", "hat-off"],
            temporary={
                "hair.base_color",
                "hair.base_identity",
                "eyes.color",
                "face.shape",
                "face.feature_relationships",
            },
        )
        self.assertFalse(any(item.startswith("state:") for item in valid["request_readiness"]["missing_fields"]))
        invalid = validate(
            self.fixture.root,
            profiles={"portrait"},
            variant_id="test-variant",
            selected_states=["hair-tied", "hair-loose"],
            temporary={
                "hair.base_color",
                "hair.base_identity",
                "eyes.color",
                "face.shape",
                "face.feature_relationships",
            },
        )
        self.assertTrue(any("exclusive_group" in item for item in invalid["request_readiness"]["missing_fields"]))

    def test_state_requires_and_explicit_conflicts_block_selection(self) -> None:
        self.fixture.add_variant_with_states()
        state_dir = self.fixture.root / "variants" / "test-variant" / "states"
        hair_path = state_dir / "hair-tied.yaml"
        hat_path = state_dir / "hat-off.yaml"
        hair = read_yaml(hair_path)
        hair["requires"] = ["hat-off"]
        write_yaml(hair_path, hair)
        required = validate(self.fixture.root, profiles={"portrait"}, variant_id="test-variant", selected_states=["hair-tied"])
        self.assertTrue(any("requires" in item for item in required["request_readiness"]["missing_fields"]))
        hair["requires"] = []
        hair["conflicts_with"] = ["hat-off"]
        hat = read_yaml(hat_path)
        hat["conflicts_with"] = ["hair-tied"]
        write_yaml(hair_path, hair)
        write_yaml(hat_path, hat)
        conflict = validate(
            self.fixture.root,
            profiles={"portrait"},
            variant_id="test-variant",
            selected_states=["hair-tied", "hat-off"],
        )
        self.assertTrue(any("conflicts" in item for item in conflict["request_readiness"]["missing_fields"]))

    def test_state_cannot_override_must_keep(self) -> None:
        self.fixture.add_variant_with_states()
        path = self.fixture.root / "variants" / "test-variant" / "states" / "hair-tied.yaml"
        state = read_yaml(path)
        state["overrides"]["outfit.primary_silhouette"] = "changed"
        write_yaml(path, state)
        result = validate(self.fixture.root)
        self.assertIn("state-breaks-must-keep", self.codes(result))

    def test_unfinished_publish_blocks_structure(self) -> None:
        staging = self.fixture.root / "calibration" / "staging" / "cal-test"
        staging.mkdir(parents=True)
        write_yaml(staging / "publish-manifest.yaml", {"state": "publishing"})
        result = validate(self.fixture.root, check_staging=True)
        self.assertIn("unfinished-publish", self.codes(result))

    def test_observation_requires_intrinsic_and_rendering_layers(self) -> None:
        self.fixture.add_asset("observation-source", group="observation-source")
        path = self.fixture.root / "calibration" / "staging" / "cal-test" / "observations.yaml"
        write_yaml(
            path,
            {
                "observations": [
                    {
                        "observation_id": "obs-hair-tip-001",
                        "field_ref": "hair.base_color",
                        "evidence_ids": ["observation-source"],
                        "observation": "夕阳中呈暖橙色",
                        "intrinsic_interpretation": "",
                        "rendering_factors": {"lighting_sensitive": True},
                        "confidence": "medium",
                        "comparison": {
                            "corroborating_evidence_ids": [],
                            "conflicting_evidence_ids": [],
                        },
                        "proposed_status": "UNCERTAIN",
                    }
                ]
            },
        )
        result = validate(self.fixture.root, check_staging=True)
        self.assertIn("observation-missing-layer", self.codes(result))
        self.assertIn("invalid-rendering-factor", self.codes(result))

    def test_validator_is_read_only(self) -> None:
        watched = [
            self.fixture.root / "character" / "identity.yaml",
            self.fixture.root / "character" / "identity.md",
            self.fixture.root / "character" / "assets.yaml",
            self.fixture.root / "variants" / "index.yaml",
        ]
        before = {path: digest(path) for path in watched}
        validate(self.fixture.root, profiles={"portrait"})
        self.assertEqual(before, {path: digest(path) for path in watched})


class PublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def make_staging(self, calibration_id: str = "cal-20260910T120000Z-a1b2c3") -> Path:
        root = self.fixture.root
        staging = root / "calibration" / "staging" / calibration_id
        (staging / "files").mkdir(parents=True)
        target = root / "character" / "expressions.yaml"
        before = read_yaml(target)
        after = dict(before)
        after["revision"] = 1
        after["last_calibration_id"] = calibration_id
        staged_target = staging / "files" / "expressions.yaml"
        write_yaml(staged_target, after)
        history = {
            "schema_version": 1,
            "calibration_id": calibration_id,
            "timestamp": "2026-09-10T12:00:00Z",
            "operation": "update",
            "user_confirmed": True,
            "confirmed_at": "2026-09-10T11:59:00Z",
            "reason": "测试恢复型发布",
            "evidence_ids": [],
            "targets": [
                {
                    "entity_ref": "character.expressions",
                    "target_type": "expression_catalog",
                    "target_id": "generic",
                    "revision_before": 0,
                    "revision_after": 1,
                    "changed_fields": ["revision"],
                    "before": {"revision": 0},
                    "after": {"revision": 1},
                    "status_before": None,
                    "status_after": None,
                }
            ],
            "validation_result": {
                "validator_version": 1,
                "structure": "PASS",
                "identity_readiness": "INCOMPLETE",
                "variant_readiness": {},
                "errors": 0,
                "warnings": 0,
            },
        }
        write_yaml(staging / "history.yaml", history)
        manifest = {
            "calibration_id": calibration_id,
            "state": "prepared",
            "pre_validation": "PASS",
            "files": [
                {
                    "target_path": "character/expressions.yaml",
                    "staged_path": "files/expressions.yaml",
                    "backup_path": "backups/expressions.yaml",
                    "sha256_before": digest(target),
                    "sha256_after": digest(staged_target),
                    "publish_status": "pending",
                }
            ],
            "staged_history_path": "history.yaml",
            "history_path": f"calibration/history/{calibration_id}.yaml",
            "completion_marker": f"calibration/history/{calibration_id}.complete",
        }
        write_yaml(staging / "publish-manifest.yaml", manifest)
        return staging

    def test_publish_creates_history_and_completion_marker(self) -> None:
        staging = self.make_staging()
        result = publish(self.fixture.root, staging)
        self.assertEqual(result["state"], "complete")
        self.assertEqual(result["outcome"], "published")
        calibration_id = result["calibration_id"]
        self.assertTrue((self.fixture.root / "calibration" / "history" / f"{calibration_id}.yaml").is_file())
        self.assertTrue((self.fixture.root / "calibration" / "history" / f"{calibration_id}.complete").is_file())
        self.assertEqual(validate(self.fixture.root)["structure"], "PASS")

    def test_history_without_completion_marker_is_rejected(self) -> None:
        staging = self.make_staging()
        result = publish(self.fixture.root, staging)
        calibration_id = result["calibration_id"]
        marker = self.fixture.root / "calibration" / "history" / f"{calibration_id}.complete"
        marker.unlink()
        codes = {issue["code"] for issue in validate(self.fixture.root)["issues"]}
        self.assertIn("history-incomplete", codes)

    def test_one_calibration_advances_multiple_entities_independently(self) -> None:
        staging = self.make_staging()
        manifest_path = staging / "publish-manifest.yaml"
        manifest = read_yaml(manifest_path)
        calibration_id = manifest["calibration_id"]

        identity_target = self.fixture.root / "character" / "identity.yaml"
        identity = read_yaml(identity_target)
        identity["revision"] = 1
        identity["last_calibration_id"] = calibration_id
        staged_identity = staging / "files" / "identity.yaml"
        write_yaml(staged_identity, identity)
        manifest["files"].append(
            {
                "target_path": "character/identity.yaml",
                "staged_path": "files/identity.yaml",
                "backup_path": "backups/identity.yaml",
                "sha256_before": digest(identity_target),
                "sha256_after": digest(staged_identity),
                "publish_status": "pending",
            }
        )

        markdown_target = self.fixture.root / "character" / "identity.md"
        staged_markdown = staging / "files" / "identity.md"
        staged_markdown.write_text(
            markdown_target.read_text(encoding="utf-8").replace("source_revision: 0", "source_revision: 1"),
            encoding="utf-8",
        )
        manifest["files"].append(
            {
                "target_path": "character/identity.md",
                "staged_path": "files/identity.md",
                "backup_path": "backups/identity.md",
                "sha256_before": digest(markdown_target),
                "sha256_after": digest(staged_markdown),
                "publish_status": "pending",
            }
        )
        history_path = staging / "history.yaml"
        history = read_yaml(history_path)
        history["targets"].append(
            {
                "entity_ref": "character.identity",
                "target_type": "identity",
                "target_id": "arco",
                "revision_before": 0,
                "revision_after": 1,
                "changed_fields": ["revision"],
                "before": {"revision": 0},
                "after": {"revision": 1},
                "status_before": None,
                "status_after": None,
            }
        )
        write_yaml(history_path, history)
        write_yaml(manifest_path, manifest)

        result = publish(self.fixture.root, staging)
        self.assertEqual(result["state"], "complete")
        self.assertEqual(read_yaml(self.fixture.root / "character" / "identity.yaml")["revision"], 1)
        self.assertEqual(read_yaml(self.fixture.root / "character" / "expressions.yaml")["revision"], 1)
        self.assertEqual(validate(self.fixture.root)["structure"], "PASS")

    def test_resume_after_one_file_was_replaced(self) -> None:
        staging = self.make_staging()
        manifest_path = staging / "publish-manifest.yaml"
        manifest = read_yaml(manifest_path)
        target = self.fixture.root / manifest["files"][0]["target_path"]
        staged = staging / manifest["files"][0]["staged_path"]
        backup = staging / manifest["files"][0]["backup_path"]
        backup.parent.mkdir(parents=True)
        shutil.copy2(target, backup)
        shutil.copy2(staged, target)
        manifest["state"] = "publishing"
        write_yaml(manifest_path, manifest)
        result = publish(self.fixture.root, staging)
        self.assertEqual(result["state"], "complete")
        self.assertEqual(validate(self.fixture.root)["structure"], "PASS")

    def test_rollback_restores_original_hash(self) -> None:
        staging = self.make_staging()
        manifest_path = staging / "publish-manifest.yaml"
        manifest = read_yaml(manifest_path)
        item = manifest["files"][0]
        target = self.fixture.root / item["target_path"]
        before_hash = item["sha256_before"]
        backup = staging / item["backup_path"]
        backup.parent.mkdir(parents=True)
        shutil.copy2(target, backup)
        shutil.copy2(staging / item["staged_path"], target)
        item["publish_status"] = "replaced"
        manifest["state"] = "rollback_required"
        write_yaml(manifest_path, manifest)
        result = rollback(self.fixture.root, staging)
        self.assertEqual(result["outcome"], "rolled_back")
        self.assertEqual(digest(target), before_hash)
        self.assertEqual(validate(self.fixture.root)["structure"], "PASS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
