from __future__ import annotations

import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publication_v3 import PublishError, publish
from validate_casual_variant_staging import validate_candidate
from historical_test_fixtures import make_active_casual_fixture


ROOT = Path(__file__).resolve().parents[1]


def dump(path: Path, data) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


class CasualVariantStagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_holder, cls.formal_root, cls.staging = make_active_casual_fixture()

    @classmethod
    def tearDownClass(cls):
        cls.fixture_holder.cleanup()

    def altered(self, mutator):
        holder = tempfile.TemporaryDirectory()
        staging = Path(holder.name) / self.staging.name
        shutil.copytree(self.staging, staging)
        mutator(staging)
        result = validate_candidate(self.formal_root, staging)
        holder.cleanup()
        return result

    def test_approved_candidate_passes(self):
        self.assertEqual(validate_candidate(self.formal_root, self.staging)["status"], "PASS")

    def test_dangling_evidence_fails(self):
        def mutate(staging):
            path = staging / "candidate-root/variants/casual-outfit/variant.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["facts"][0]["evidence_ids"] = ["missing-asset"]
            dump(path, data)
        result = self.altered(mutate)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("Dangling evidence" in item for item in result["errors"]))

    def test_duplicate_asset_id_fails(self):
        def mutate(staging):
            path = staging / "candidate-root/character/assets.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            duplicate = copy.deepcopy(data["assets"][-1])
            duplicate["asset_id"] = "casual-outfit-primary"
            data["assets"].append(duplicate)
            dump(path, data)
        self.assertEqual(self.altered(mutate)["status"], "FAIL")

    def test_evidence_only_permission_fails(self):
        def mutate(staging):
            path = staging / "candidate-root/character/assets.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            target = next(item for item in data["assets"] if item["asset_id"] == "casual-outfit-open-arms-no-horns-evidence")
            target["can_be_generation_reference"] = True
            target["generation_reference"] = copy.deepcopy(next(item for item in data["assets"] if item["asset_id"] == "casual-outfit-primary")["generation_reference"])
            dump(path, data)
        result = self.altered(mutate)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("evidence-only" in item for item in result["errors"]))

    def test_back_view_ready_fails(self):
        def mutate(staging):
            path = staging / "candidate-root/variants/casual-outfit/variant.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["coverage"]["back_view"] = "READY"
            data["coverage"]["overall"] = "READY"
            dump(path, data)
        self.assertEqual(self.altered(mutate)["status"], "FAIL")

    def test_duplicate_primary_fails_closed(self):
        def mutate(staging):
            asset_path = staging / "candidate-root/character/assets.yaml"
            assets = yaml.safe_load(asset_path.read_text(encoding="utf-8"))
            duplicate = copy.deepcopy(next(item for item in assets["assets"] if item["asset_id"] == "casual-outfit-primary"))
            duplicate["asset_id"] = "casual-outfit-primary-duplicate"
            duplicate["path"] = "assets/arco/variants/casual-outfit/primary/casual-outfit-primary-duplicate.png"
            assets["assets"].append(duplicate)
            dump(asset_path, assets)
            source = staging / "candidate-root/assets/arco/variants/casual-outfit/primary/casual-outfit-primary.png"
            shutil.copy2(source, staging / "candidate-root" / duplicate["path"])
            variant_path = staging / "candidate-root/variants/casual-outfit/variant.yaml"
            variant = yaml.safe_load(variant_path.read_text(encoding="utf-8"))
            variant["reference_asset_ids"]["primary"].append(duplicate["asset_id"])
            dump(variant_path, variant)
        self.assertEqual(self.altered(mutate)["status"], "FAIL")

    def test_missing_variant_primary_fails(self):
        def mutate(staging):
            path = staging / "candidate-root/variants/casual-outfit/variant.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["reference_asset_ids"]["primary"] = []
            dump(path, data)
        self.assertEqual(self.altered(mutate)["status"], "FAIL")

    def test_horns_cannot_enter_must_keep(self):
        def mutate(staging):
            path = staging / "candidate-root/variants/casual-outfit/variant.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["must_keep_fields"].append("overlay.horns")
            dump(path, data)
        self.assertEqual(self.altered(mutate)["status"], "FAIL")

    def test_publication_without_authorization_is_rejected(self):
        with self.assertRaises(PublishError):
            publish(self.formal_root, self.staging, authorization=None, validate_written=lambda *_: None, validate_complete=lambda *_: None)


if __name__ == "__main__":
    unittest.main()
