from __future__ import annotations
import shutil, sys, tempfile, unittest
from pathlib import Path
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from validate_expression_staging import validate

ROOT = Path(__file__).resolve().parents[1]
EXPRESSION_STAGING = ROOT / "calibration/staging/cal-20260910T145805Z-61c3e9"
FORMAL = ROOT

def load(path): return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
def dump(path, data): Path(path).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

class Tests(unittest.TestCase):
    """Explicit published-Expression fixtures; never mix in Identity staging."""
    def test_formal_published_baseline(self):
        result = validate(EXPRESSION_STAGING / "candidate-root", EXPRESSION_STAGING, FORMAL, "published")
        self.assertEqual(result["status"], "PASS", result)

    def mutated(self, callback, *, mutate_formal=False):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); candidate=base/"candidate-root"; staging=base/"expression-staging"
            formal=base/"formal" if mutate_formal else FORMAL
            shutil.copytree(EXPRESSION_STAGING/"candidate-root", candidate)
            staging.mkdir()
            shutil.copy2(EXPRESSION_STAGING/"history-draft.yaml", staging/"history-draft.yaml")
            shutil.copy2(EXPRESSION_STAGING/"source-hashes.yaml", staging/"source-hashes.yaml")
            shutil.copytree(EXPRESSION_STAGING/"publication", staging/"publication")
            if mutate_formal:
                shutil.copytree(FORMAL/"character", formal/"character")
                shutil.copytree(FORMAL/"variants", formal/"variants")
                shutil.copytree(FORMAL/"assets/arco/expressions", formal/"assets/arco/expressions")
                shutil.copytree(FORMAL/"calibration/staging/cal-20260910T145805Z-61c3e9", formal/"calibration/staging/cal-20260910T145805Z-61c3e9")
            callback(candidate, staging, formal)
            return validate(candidate, staging, formal, "published")

    def test_missing_file(self):
        def change(c,s,f):
            data=load(c/"character/assets.yaml"); (c/data["assets"][0]["path"]).unlink()
        self.assertEqual(self.mutated(change)["status"],"FAIL")

    def test_duplicate_id(self):
        def change(c,s,f):
            p=c/"character/assets.yaml"; d=load(p); d["assets"][1]["asset_id"]=d["assets"][0]["asset_id"]; dump(p,d)
        self.assertEqual(self.mutated(change)["status"],"FAIL")

    def test_reference_and_role(self):
        def change(c,s,f):
            p=c/"character/assets.yaml"; d=load(p); d["assets"][0]["expression_id"]="missing"; d["assets"][0]["roles"]=["face_evidence"]; dump(p,d)
        self.assertEqual(self.mutated(change)["status"],"FAIL")

    def test_review_and_cluster(self):
        def change(c,s,f):
            p=c/"character/expressions.yaml"; d=load(p); d["semantics"][0]["semantic_review_status"]="REVIEW_REQUIRED"; d["expression_clusters"][0]["member_expression_ids"].append("missing"); dump(p,d)
        self.assertEqual(self.mutated(change)["status"],"FAIL")

    def test_compatibility_upgrade(self):
        def change(c,s,f):
            p=c/"character/expressions.yaml"; d=load(p); d["composite_compatibility"]=[{"status":"CONFIRMED"}]; dump(p,d)
        self.assertEqual(self.mutated(change)["status"],"FAIL")

    def test_proposed_id_is_not_asset(self):
        def change(c,s,f):
            h=load(s/"history-draft.yaml"); proposed=h["pending_compatibility_evidence"][0]["faceless_composite"]["proposed_asset_id"]
            p=c/"character/assets.yaml"; d=load(p); d["assets"][0]["asset_id"]=proposed; dump(p,d)
        self.assertEqual(self.mutated(change)["status"],"FAIL")

    def test_immutable_formal_expression_drift(self):
        def change(c,s,f):
            p=f/"character/expressions.yaml"; p.write_bytes(p.read_bytes()+b"\n")
        result=self.mutated(change,mutate_formal=True)
        self.assertEqual(result["status"],"FAIL")
        self.assertTrue(any("immutable data drift" in error for error in result["errors"]),result)

    def test_publication_gate(self):
        def change(c,s,f):
            p=s/"publication/publish-manifest.yaml"; d=load(p); d["publication_authorized"]=False; dump(p,d)
        self.assertEqual(self.mutated(change)["status"],"FAIL")

if __name__=="__main__": unittest.main(verbosity=2)
