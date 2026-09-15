from __future__ import annotations
import shutil, tempfile, unittest
from pathlib import Path
import yaml
from validate_expression_staging import validate

HERE=Path(__file__).resolve(); CANDIDATE=HERE.parents[1]; STAGING=HERE.parents[2]; FORMAL=Path(r'D:\learn\Arco')
def load(p): return yaml.safe_load(Path(p).read_text(encoding='utf-8'))
def dump(p,d): Path(p).write_text(yaml.safe_dump(d,allow_unicode=True,sort_keys=False),encoding='utf-8')

class Tests(unittest.TestCase):
    def test_baseline(self): self.assertEqual(validate(CANDIDATE,STAGING,FORMAL)['status'],'PASS')
    def mutated(self,fn):
        with tempfile.TemporaryDirectory() as td:
            t=Path(td); shutil.copytree(CANDIDATE,t/'c'); shutil.copytree(STAGING,t/'s',ignore=shutil.ignore_patterns('candidate-root','.venv')); fn(t/'c',t/'s'); return validate(t/'c',t/'s',FORMAL)
    def test_missing_file(self):
        def f(c,s):
            d=load(c/'character/assets.yaml'); (c/d['assets'][0]['path']).unlink()
        self.assertEqual(self.mutated(f)['status'],'FAIL')
    def test_duplicate_id(self):
        def f(c,s):
            p=c/'character/assets.yaml'; d=load(p); d['assets'][1]['asset_id']=d['assets'][0]['asset_id']; dump(p,d)
        self.assertEqual(self.mutated(f)['status'],'FAIL')
    def test_reference_and_role(self):
        def f(c,s):
            p=c/'character/assets.yaml'; d=load(p); d['assets'][0]['expression_id']='missing'; d['assets'][0]['roles']=['face_evidence']; dump(p,d)
        self.assertEqual(self.mutated(f)['status'],'FAIL')
    def test_review_and_cluster(self):
        def f(c,s):
            p=c/'character/expressions.yaml'; d=load(p); d['semantics'][0]['semantic_review_status']='REVIEW_REQUIRED'; d['expression_clusters'][0]['member_expression_ids'].append('missing'); dump(p,d)
        self.assertEqual(self.mutated(f)['status'],'FAIL')
    def test_compatibility_upgrade(self):
        def f(c,s):
            p=c/'character/expressions.yaml'; d=load(p); d['composite_compatibility']=[{'status':'CONFIRMED'}]; dump(p,d)
        self.assertEqual(self.mutated(f)['status'],'FAIL')
    def test_proposed_id_is_not_asset(self):
        def f(c,s):
            h=load(s/'history-draft.yaml'); proposed=h['pending_compatibility_evidence'][0]['faceless_composite']['proposed_asset_id']; p=c/'character/assets.yaml'; d=load(p); d['assets'][0]['asset_id']=proposed; dump(p,d)
        self.assertEqual(self.mutated(f)['status'],'FAIL')
    def test_stale_base(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'formal'; shutil.copytree(FORMAL,f,ignore=shutil.ignore_patterns('calibration')); p=f/'character/identity.yaml'; p.write_text(p.read_text(encoding='utf-8')+'\n',encoding='utf-8'); r=validate(CANDIDATE,STAGING,f); self.assertEqual(r['status'],'FAIL'); self.assertTrue(any('STALE_STAGING' in x for x in r['errors']))
    def test_publication_gate(self):
        def f(c,s):
            p=s/'publication/publish-manifest.yaml'; d=load(p); d['publication_authorized']=True; dump(p,d)
        self.assertEqual(self.mutated(f)['status'],'FAIL')
if __name__=='__main__': unittest.main()
