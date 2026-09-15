"""Validate an Identity Calibration candidate without reading it as production data."""
from __future__ import annotations
from collections import Counter
import argparse, hashlib, json
from pathlib import Path
import yaml

GEN_KEYS={"priority","supported_roles","preferred_for","excluded_for","coverage","inheritance"}
COVERAGE_KEYS={"profiles","visible_fields","view_angles","occluded_fields"}
PROFILES={"portrait","upper_body","full_body","back_view"}
INHERITANCE={"inherit","do_not_inherit"}
SAFE_STATES={"STAGED_REVALIDATION_FAILED","STAGED_VALIDATED_AWAITING_AUTHORIZATION"}
EXPECTED_HASHES={
 "identity-p01":"bddba1d7b1bed2c21572892003ac50dc6c2340d53e8262a56b6db69b16cf1f86",
 "identity-p01-crop":"386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414",
 "identity-p03":"0056f16ff4468a0e26505b521a2fcd8f13a032ddb10e468c22c06c433a38206d",
}

def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()
def load(path): return yaml.safe_load(Path(path).read_text(encoding='utf-8'))

def validate(root:Path,staging:Path,phase:str='staging'):
    errors=[]; warnings=[]; candidate=staging/'candidate-root'
    identity=load(candidate/'character/identity.yaml'); assets=load(candidate/'character/assets.yaml')
    expressions=load(candidate/'character/expressions.yaml'); variants=load(candidate/'variants.index.yaml')
    manifest=load(staging/'publish-manifest.yaml'); history=load(staging/'history-draft.yaml')
    def req(ok,msg):
        if not ok: errors.append(msg)
    req(identity.get('revision')==1,'identity candidate revision must be 1')
    req(assets.get('revision')==2 and assets.get('schema_version')==3,'Asset candidate must be revision 2 schema v3')
    req(expressions.get('revision')==1 and sha(candidate/'character/expressions.yaml')==sha(root/'character/expressions.yaml'),'Expression revision/data changed')
    req(variants.get('revision')==0 and sha(candidate/'variants.index.yaml')==sha(root/'variants/index.yaml'),'Variant changed')
    facts=identity.get('facts',[]); counts=Counter(f.get('status') for f in facts)
    req(len(facts)==14 and counts==Counter({'UNCERTAIN':10,'TODO_CALIBRATION':4}),'Identity fact/status freeze violated')
    frozen=staging/'primary-replacement/before/candidate-root/character/identity.yaml'
    if frozen.is_file():
        original=load(frozen).get('facts')
        for before,after in zip(original,facts):
            if before['field_id']=='body.head_to_body_ratio':
                req(after['value'] is None and before['value'] in after['note_zh'] and before['status']==after['status'],'approved TODO normalization invalid')
                req({k:v for k,v in before.items() if k not in {'value','note_zh'}}=={k:v for k,v in after.items() if k not in {'value','note_zh'}},'TODO unrelated fields changed')
            else: req(before==after,'Identity facts changed after adjudication')
    entries=assets.get('assets',[]); ids=[a.get('asset_id') for a in entries]; by={a.get('asset_id'):a for a in entries}
    req(len(ids)==len(set(ids))==46,'Expected 46 unique candidate assets')
    req(set(EXPECTED_HASHES)<=set(by),'Identity assets missing')
    req(entries[:43]==load(candidate/'character/assets.base.yaml').get('assets'),'43 published Expression Asset records changed')
    for aid,expected in EXPECTED_HASHES.items():
        asset=by.get(aid,{}) ; path=candidate/str(asset.get('path',''))
        req(path.is_file() and sha(path)==expected==asset.get('sha256'),f'{aid}: file/hash mismatch')
        req(asset.get('source_family_id')=='arco-official-standing-art-system-01',f'{aid}: source family changed')
        req(asset.get('source_authority')=='user_approved',f'{aid}: source authority must use schema enum user_approved')
        req(asset.get('view_angle')=='front_three_quarter',f'{aid}: view_angle invalid')
        req(asset.get('roles')==['identity_evidence'],f'{aid}: roles must remain evidence roles')
        req(asset.get('can_be_generation_reference') is True,f'{aid}: generation permission missing')
        meta=asset.get('generation_reference')
        req(isinstance(meta,dict) and set(meta)==GEN_KEYS,f'{aid}: generation_reference is not the closed schema')
        if isinstance(meta,dict):
            req(meta.get('priority') in {'primary','secondary','supplemental'},f'{aid}: invalid priority')
            req(meta.get('supported_roles')==['identity_reference'],f'{aid}: invalid supported_roles')
            req(isinstance(meta.get('preferred_for'),list) and not(set(meta['preferred_for'])-PROFILES),f'{aid}: invalid preferred_for')
            req(isinstance(meta.get('excluded_for'),list) and not(set(meta['excluded_for'])-PROFILES) and not(set(meta['preferred_for'])&set(meta['excluded_for'])),f'{aid}: invalid excluded_for')
            cov=meta.get('coverage'); req(isinstance(cov,dict) and not(set(cov)-COVERAGE_KEYS),f'{aid}: invalid/unknown coverage fields')
            inheritance=meta.get('inheritance'); req(isinstance(inheritance,dict) and inheritance and not(set(inheritance.values())-INHERITANCE),f'{aid}: invalid inheritance')
            req({'outfit','pose','expression'}<=set(k for k,v in (inheritance or {}).items() if v=='do_not_inherit'),f'{aid}: leakage exclusions missing')
    primaries=[a['asset_id'] for a in entries if a.get('can_be_generation_reference') and a.get('generation_reference',{}).get('priority')=='primary']
    req(primaries==['identity-p01-crop'] and identity.get('identity_primary')=='identity-p01-crop','Primary must be Candidate A only')
    crop=by.get('identity-p01-crop',{}); op=crop.get('operation',{})
    req(crop.get('derived_from_asset_id')==crop.get('parent_asset_id')=='identity-p01','crop parent relationship invalid')
    req(crop.get('evidence_independence')==op.get('evidence_independence')=='none','crop increases evidence independence')
    req(op.get('crop_box_px')==[680,0,760,640] and crop.get('dimensions_px')==[760,640],'Candidate A crop geometry changed')
    req(crop.get('generation_reference',{}).get('preferred_for')==['portrait'],'Primary must be portrait-only')
    req(set(crop.get('generation_reference',{}).get('excluded_for',[]))=={'upper_body','full_body','back_view'},'Primary exclusions invalid')
    req(by.get('identity-p01',{}).get('generation_reference',{}).get('priority')=='secondary','P01 must remain Secondary')
    req(by.get('identity-p03',{}).get('generation_reference',{}).get('priority')=='supplemental','P03 must remain supplemental')
    req(identity.get('coverage')=={'portrait':'READY','upper_body':'READY','full_body':'READY','back_view':'INCOMPLETE'} and identity.get('global_reference_readiness')=='PARTIAL','Candidate coverage/readiness invalid')
    if phase=='staging':
        req(manifest.get('publication_authorized') is False,'publication authorization must remain false')
        req(manifest.get('publication_state') in SAFE_STATES,'manifest state is not safe for offline revalidation')
    else:
        req(manifest.get('publication_authorized') is True,'publication authorization missing')
        req(manifest.get('publication_state') in {'AFTER_HASH_VALIDATED','COMPLETE'},'invalid final phase')
    req(manifest.get('base_state')=={'expression_library_revision':1,'asset_index_revision':1,'identity_revision':0},'base state mismatch')
    for rel,expected in manifest.get('base_hashes',{}).items():
        if phase!='staging' and rel in {f['target_path'] for f in manifest['files']}: continue
        path=root/rel; req(path.is_file() and sha(path)==expected,f'STALE_STAGING: {rel}')
    files=manifest.get('files',[]); req(len(files)==6,'Manifest must contain two YAML, Markdown and three Identity images')
    payload={x.get('asset_id'):x for x in files if x.get('asset_id')}
    req(set(payload)==set(EXPECTED_HASHES),'Manifest Identity image asset IDs invalid')
    for item in files:
        staged=staging/str(item.get('staged_path','')); target=root/str(item.get('target_path',''))
        req(staged.is_file() and sha(staged)==item.get('candidate_hash'),f"Manifest candidate hash mismatch: {item.get('target_path')}")
        if phase=='staging': req(item.get('after_hash') is None and item.get('publication_status')=='pending','Manifest records publication progress')
        else: req(target.is_file() and sha(target)==item.get('candidate_hash')==item.get('after_hash'),'Formal target hash mismatch')
        if item.get('asset_id'):
            req(item.get('before_hash') is None and item.get('before_state')=='absent' and (phase!='staging' or not target.exists()),'New managed target must be absent')
            req(item.get('publication_action')=='create_managed_asset','Identity image publication action missing')
    req(history.get('publication_not_executed') is True,'History draft claims publication')
    return {'validator':'identity-staging-v2','status':'PASS' if not errors else 'FAIL','calibration_id':manifest.get('calibration_id'),'counts':{'identity_facts':len(facts),'uncertain':counts['UNCERTAIN'],'todo':counts['TODO_CALIBRATION'],'todo_calibration':counts['TODO_CALIBRATION'],'canon':counts['CANON'],'visual_consensus':counts['VISUAL_CONSENSUS'],'candidate_assets':len(entries),'identity_generation_assets':3},'errors':errors,'warnings':warnings,'publication_executed':False}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]); p.add_argument('--staging',type=Path,required=True); p.add_argument('--json',action='store_true'); a=p.parse_args()
    result=validate(a.root.resolve(),a.staging.resolve(),'published' if load(a.staging/'publish-manifest.yaml').get('publication_state') in {'COMPLETE','AFTER_HASH_VALIDATED'} else 'staging'); print(json.dumps(result,ensure_ascii=False,indent=2) if a.json else f"{result['status']}: {len(result['errors'])} errors"); return 0 if result['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
