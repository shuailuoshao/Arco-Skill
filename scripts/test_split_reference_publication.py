"""Permission publication must preserve every character/evidence fact."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publish_split_reference_permissions import candidate_assets, assert_metadata_only
from publish_calibration import PublishError, sha256

ROOT = Path(__file__).resolve().parents[1]


class PermissionPublicationTests(unittest.TestCase):
    def test_permission_patch_preserves_asset_evidence_and_pixels(self):
        original = yaml.safe_load((ROOT / "character/assets.yaml").read_text(encoding="utf-8"))
        candidate, changes = candidate_assets(original, "cal-test-only")
        assert_metadata_only(original, candidate)
        self.assertTrue(changes)
        self.assertEqual(candidate["revision"], original["revision"] + 1)
        for old, new in zip(original["assets"], candidate["assets"], strict=True):
            self.assertEqual(old["sha256"], new["sha256"])
            self.assertEqual(old["path"], new["path"])
            self.assertEqual(old.get("expression_id"), new.get("expression_id"))

    def test_identity_evidence_change_is_rejected(self):
        original = yaml.safe_load((ROOT / "character/assets.yaml").read_text(encoding="utf-8"))
        candidate, _ = candidate_assets(original, "cal-test-only")
        candidate["assets"][0]["view_class"] = "back"
        with self.assertRaises(PublishError):
            assert_metadata_only(original, candidate)

    def test_completed_publication_preserved_protected_facts(self):
        assets = yaml.safe_load((ROOT / "character/assets.yaml").read_text(encoding="utf-8"))
        cid = assets["last_calibration_id"]
        manifest = yaml.safe_load((ROOT / f"scripts/fixtures/calibration/{cid}/publish-manifest.yaml").read_text(encoding="utf-8"))
        history = yaml.safe_load((ROOT / f"calibration/history/{cid}.yaml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["publication_state"], "COMPLETE")
        self.assertFalse(history["knowledge_change"])
        self.assertEqual([item["target_path"] for item in manifest["files"]], ["character/assets.yaml"])
        for relative in ("character/identity.yaml", "character/expressions.yaml", "variants/index.yaml"):
            self.assertEqual(sha256(ROOT / relative), manifest["base_hashes"][relative])
        self.assertTrue((ROOT / f"calibration/history/{cid}.complete").exists())


if __name__ == "__main__":
    unittest.main()
