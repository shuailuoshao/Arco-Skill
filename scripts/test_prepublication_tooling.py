from __future__ import annotations
import copy, hashlib, shutil, sys, tempfile, unittest
from pathlib import Path
import yaml

SCRIPT_DIR=Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path: sys.path.insert(0,str(SCRIPT_DIR))

from check_calibration_lock import conflicts
from reference_runtime import (
    build_builtin_imagegen_args, build_invocation_plan,
    compile_reference_instructions, compute_global_reference_readiness,
    compute_request_reference_readiness, generation_allowed,
    select_references, validate_reference_instructions,
)
from validate_identity_staging import validate as validate_identity
from historical_test_fixtures import make_historical_identity_fixture

ROOT=Path(__file__).resolve().parents[1]
STAGING=ROOT/'calibration/staging/cal-20260911T031117Z-849ec7'
CONFIG=yaml.safe_load((ROOT/'runtime/generation.yaml').read_text(encoding='utf-8'))

class ToolingTests(unittest.TestCase):
    def setUp(self):
        self.fixture_holder, self.formal_root = make_historical_identity_fixture()
        registry=yaml.safe_load((STAGING/'candidate-root/character/assets.yaml').read_text(encoding='utf-8'))
        self.assets=[copy.deepcopy(a) for a in registry['assets'] if a['asset_id'] in {'identity-p01','identity-p01-crop','identity-p03'}]
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)/'published-fixture'
        for asset in self.assets:
            source=STAGING/'candidate-root'/asset['path']; target=self.root/asset['path']; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source,target)
    def tearDown(self):
        self.temp.cleanup()
        self.fixture_holder.cleanup()
    def select(self,profile):
        return select_references(root=self.root,managed_assets=self.assets,requested_roles=['identity_reference'],exposure_profile=profile,config=CONFIG)

    def test_portrait_primary_alone(self):
        selected=self.select('portrait')
        self.assertEqual([x['asset_id'] for x in selected],['identity-p01-crop'])
        self.assertEqual(compute_request_reference_readiness(exposure_profile='portrait',references=selected)['status'],'READY')

    def test_upper_and_full_add_minimal_secondary_not_supplemental(self):
        for profile in ('upper_body','full_body'):
            selected=self.select(profile)
            self.assertEqual([x['asset_id'] for x in selected],['identity-p01-crop','identity-p01'])
            self.assertNotIn('identity-p03',[x['asset_id'] for x in selected])
            self.assertEqual(compute_request_reference_readiness(exposure_profile=profile,references=selected)['status'],'READY')

    def test_back_is_incomplete_and_global_partial(self):
        selected=self.select('back_view')
        self.assertEqual(compute_request_reference_readiness(exposure_profile='back_view',references=selected)['status'],'INCOMPLETE')
        identity=yaml.safe_load((STAGING/'candidate-root/character/identity.yaml').read_text(encoding='utf-8'))
        global_result=compute_global_reference_readiness(identity,{'variants':[]},self.assets)
        self.assertEqual(global_result['identity_profiles'],{'portrait':'READY','upper_body':'READY','full_body':'READY','back_view':'INCOMPLETE'})
        self.assertEqual(global_result['overall'],'PARTIAL')

    def test_inheritance_metadata_to_contract_to_prompt_quality_gate(self):
        selected=self.select('full_body'); secondary=selected[1]
        self.assertEqual(set(secondary['inherit']),{'identity','body_proportions','hair_length'})
        self.assertEqual(set(secondary['do_not_inherit']),{'outfit','pose','expression'})
        instructions=compile_reference_instructions(selected)
        validate_reference_instructions(selected,instructions)
        self.assertIn('Reference identity-p01:',instructions)
        for field in ('outfit','pose','expression','body_proportions','hair_length'):
            self.assertIn(field,instructions)

    def test_forbidden_layers_and_legacy_permission_default(self):
        self.assertFalse(generation_allowed({'roles':['identity_evidence']}))
        self.assertFalse(generation_allowed({'roles':['expression_evidence'],'can_be_generation_reference':True,'generation_reference':{'supported_roles':['identity_reference']}}))
        self.assertFalse(generation_allowed({'asset_type':'body_base','roles':['body_evidence'],'can_be_generation_reference':True,'generation_reference':{'supported_roles':['identity_reference']}}))
        self.assertFalse(generation_allowed({'asset_type':'faceless_composite','roles':['identity_evidence'],'can_be_generation_reference':True,'generation_reference':{'supported_roles':['identity_reference']}}))

    def test_prompt_only_exact_args(self):
        plan=build_invocation_plan(mode='prompt_only',prompt='Arco',selected_references=[])
        self.assertEqual(build_builtin_imagegen_args(plan),{'prompt':'Arco'})

    def test_failed_lock_blocks_writes_but_not_read_only(self):
        lock=self.root/'calibration/staging/test/calibration-lock.yaml'
        lock.parent.mkdir(parents=True)
        lock.write_text('calibration_id: test\nstate: STAGED_REVALIDATION_FAILED\ntargets: [character.identity]\n',encoding='utf-8')
        self.assertTrue(conflicts(self.root,{'character.identity'},'publication'))
        self.assertTrue(conflicts(self.root,{'character.identity'},'begin-calibration'))
        self.assertEqual(conflicts(self.root,{'character.identity'},'offline-revalidation'),[])
        self.assertEqual(conflicts(self.root,set(),'formal-validation'),[])
        self.assertEqual(conflicts(self.root,set(),'runtime-planning'),[])

    def test_candidate_schema_and_manifest(self):
        m=yaml.safe_load((STAGING/'publish-manifest.yaml').read_text(encoding='utf-8'))
        result=validate_identity(self.formal_root,STAGING,'published' if m.get('publication_state') in {'COMPLETE','AFTER_HASH_VALIDATED'} else 'staging')
        self.assertEqual(result['status'],'PASS',result)

    def test_runtime_source_contains_no_staging_discovery_or_remote_adapter(self):
        source=(ROOT/'scripts/reference_runtime.py').read_text(encoding='utf-8').lower()
        self.assertNotIn('calibration/staging/*',source)
        self.assertNotIn('import openai',source)
        self.assertNotIn('image_gen__imagegen',source)

if __name__=='__main__': unittest.main(verbosity=2)
