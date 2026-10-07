"""Controlled-provider checks for the dedicated calibration reference-edit lane."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from arco_real_adapter import ArcoRealAdapter
from preparation_support import load,freeze
from reference_analysis import file_hash
from reference_runtime import ReferenceRuntimeError

ROOT=Path(__file__).resolve().parents[1]

class ReferenceCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'output')
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        asset=next(a for a in load(ROOT/'character/assets.yaml')['assets'] if a['asset_id']=='casual-outfit-open-arms-no-horns-evidence')
        self.ref={'asset_id':asset['asset_id'],'path':str((ROOT/asset['path']).resolve()),'sha256':asset['sha256'],'usage':'clothed_identity_chest_proportion'}
        self.plan={'purpose':'published_reference_correction','repair_number':0,'prompt':'Controlled approved edit',
            'references':[self.ref],'referenced_image_paths':[self.ref['path']]}
        self.preview={'purpose':self.plan['purpose'],'invocation_plan':self.plan,
            'authorization':{'user_confirmed':True,'user_message':'Correct this reference'},'bindings':{self.ref['path']:self.ref['sha256']}}
        self.calls=[]
        def provider(**args):
            self.calls.append(args);path=self.folder/'controlled.png';path.write_bytes(b'controlled output');return path
        self.adapter=ArcoRealAdapter(provider)
        self.path=self.folder/'preview.json'
        self.save()
    def save(self):
        self.path.write_text(json.dumps(freeze(self.preview),ensure_ascii=False),encoding='utf-8')
    def invoke(self):
        return self.adapter.generate_reference_correction(invocation_plan=self.plan,root=ROOT,preview_path=self.path)
    def rejected(self,code):
        with self.assertRaises(ReferenceRuntimeError) as error:self.invoke()
        self.assertEqual(error.exception.code,code)
        self.assertEqual(self.calls,[])
    def test_exact_bound_call_and_prompt_tampering(self):
        self.assertTrue(self.invoke().is_file())
        self.assertEqual(self.calls,[{'prompt':self.plan['prompt'],'referenced_image_paths':[self.ref['path']]}])
        self.calls.clear();self.plan=deepcopy(self.plan);self.plan['prompt']='Unapproved redesign'
        self.rejected('REFERENCE_CORRECTION_STALE')
    def test_confirmation_and_input_hash_drift_fail_before_provider(self):
        self.preview['authorization']['user_confirmed']=False;self.save()
        self.rejected('REFERENCE_CORRECTION_CONFIRMATION_REQUIRED')
        self.preview['authorization']['user_confirmed']=True
        self.preview['bindings'][self.ref['path']]='0'*64;self.save()
        self.rejected('REFERENCE_CORRECTION_STALE')
    def test_bounded_repair_requires_failed_inspection(self):
        self.plan['repair_number']=1;self.save()
        self.rejected('AUTOMATIC_REPAIR_REVIEW_REQUIRED')
        self.preview['prior_review']={'decision':'FAIL'};self.plan['repair_number']=3;self.save()
        self.rejected('AUTOMATIC_REPAIR_LIMIT')

if __name__=='__main__':unittest.main()
