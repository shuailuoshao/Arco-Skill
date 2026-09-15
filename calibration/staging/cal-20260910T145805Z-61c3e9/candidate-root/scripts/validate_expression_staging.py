#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import yaml

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()

def load(p): return yaml.safe_load(Path(p).read_text(encoding='utf-8'))

def validate(candidate:Path, staging:Path, formal:Path, phase:str='staging'):
    errors=[]; warnings=[]
    def req(x,m):
        if not x: errors.append(m)
    ad=load(candidate/'character/assets.yaml'); ed=load(candidate/'character/expressions.yaml')
    hd=load(staging/'history-draft.yaml'); md=load(staging/'publication/publish-manifest.yaml'); sh=load(staging/'source-hashes.yaml')
    assets=ad.get('assets',[]); sem=ed.get('semantics',[]); aids=[x.get('asset_id') for x in assets]; eids=[x.get('expression_id') for x in sem]
    aset=set(aids); eset=set(eids)
    req(ad.get('revision')==1 and ed.get('revision')==1,'candidate revisions must be 1')
    req(len(assets)==len(aset)==43,'expected 43 unique assets')
    req(len(sem)==len(eset)==42,'expected 42 unique semantics')
    req(all(x.get('semantic_review_status')=='APPROVED' for x in sem),'all semantics must be APPROVED')
    req(ed.get('prompt_compiler_gate',{}).get('default_semantic_review_status')=='APPROVED','compiler gate must require APPROVED')
    req(ed.get('direction_convention','').startswith('left/right means the direction the character face points'),'direction convention missing')
    for a in assets:
        aid=a.get('asset_id'); p=candidate/str(a.get('path','')); prov=a.get('provenance',{}); src=Path(str(prov.get('source_path','')))
        req(a.get('roles')==['expression_evidence'],f'{aid}: illegal role')
        req(a.get('asset_status')=='VERIFIED',f'{aid}: not VERIFIED')
        req(a.get('face_slot_membership')=='CONFIRMED',f'{aid}: slot membership not CONFIRMED')
        req(a.get('expression_id') in eset,f'{aid}: invalid expression reference')
        req(p.is_file(),f'{aid}: managed file missing')
        if p.is_file(): req(len(a.get('sha256',''))==64 and sha(p)==a.get('sha256'),f'{aid}: hash mismatch')
        req(src.is_file(),f'{aid}: source missing')
        if src.is_file() and p.is_file():
            req(sha(src)==sha(p),f'{aid}: copy differs from source'); req(sh.get(str(src))==sha(src),f'{aid}: source ledger mismatch')
        req(a.get('derived_from_asset_id') is None,f'{aid}: unexpected derived relation')
    dup=[a for a in assets if a.get('provenance',{}).get('original_filename') in {'アルコ_b_l_8250.png','アルコ_b_l_8467.png'}]
    req(len(dup)==2,'official duplicate pair missing')
    if len(dup)==2:
        req(dup[0]['asset_id']!=dup[1]['asset_id'],'duplicate pair asset IDs collapsed')
        req(dup[0]['sha256']==dup[1]['sha256'],'duplicate pair hashes differ')
        req({x['expression_id'] for x in dup}=={'expr-frontal-neutral-serious-01'},'duplicate pair semantic mismatch')
    slots={x.get('face_slot_id') for x in ed.get('face_slots',[])}; sets={x.get('expression_set_id') for x in ed.get('expression_sets',[])}
    groups={x.get('source_group_id') for x in ed.get('source_groups',[])}; sims={x.get('similarity_group_id') for x in ed.get('similarity_groups',[])}; poses={x.get('pose_family_id') for x in ed.get('pose_families',[])}
    req(len(slots)==2 and len(sets)==2,'expected 2 slots and 2 sets')
    req(all(a.get('face_slot_id') in slots and a.get('expression_set_id') in sets and a.get('source_group_id') in groups for a in assets),'asset reference invalid')
    req(all(set(x.get('similarity_group_ids',[]))<=sims for x in sem),'similarity reference invalid')
    for s in ed.get('expression_sets',[]):
        req(set(s.get('member_asset_ids',[]))<=aset,'expression set member invalid')
        for r in s.get('pose_compatibility',[]): req(r.get('target_id') in poses and r.get('status')=='PROVISIONAL','pose compatibility invalid or upgraded')
    clusters=ed.get('expression_clusters',[]); req(len(clusters)==8,'expected 8 clusters')
    for c in clusters: req(c.get('cluster_status')=='CONFIRMED' and set(c.get('member_expression_ids',[]))<=eset,'cluster invalid')
    req(ed.get('composite_compatibility')==[],'composite compatibility materialized')
    req(hd.get('draft') is True and hd.get('publication_status')=='NOT_PUBLISHED','History is not an unpublished draft')
    decisions=hd.get('semantic_adjudication',{}).get('decisions',[]); req(len(decisions)==19,'expected 19 adjudications')
    req(any(x.get('user_raw_decision')=='特别兴奋的呲牙😁' and x.get('display_name_zh')=='特别兴奋地呲牙' for x in decisions),'raw emoji decision not preserved')
    pending=hd.get('pending_compatibility_evidence',[]); req(len(pending)==4,'expected 4 pending compatibility evidence records'); proposed=set()
    for r in pending:
        for side in ('faceless_composite','full_composite'):
            v=r.get(side,{}); req(v.get('registration_status')=='UNREGISTERED','pending target is not UNREGISTERED')
            req(all(k in v for k in ('proposed_asset_id','original_filename','source_path')),'pending locator fields missing'); proposed.add(v.get('proposed_asset_id'))
            if v.get('original_filename') is None or v.get('source_path') is None: warnings.append(f"{r.get('expression_asset_source_key')} {side}: source locator outside current publication unit")
    req(not(proposed&aset),'proposed ID resolved as managed asset')
    if phase=='staging':
        req(md.get('publication_authorized') is False and md.get('publication_state')=='STAGED_VALIDATED_AWAITING_AUTHORIZATION','publication gate open')
    else:
        req(md.get('publication_authorized') is True and md.get('publication_state') in {'AFTER_HASH_VALIDATED','COMPLETE'},'publication transaction is not in a post-write validation state')
    req(md.get('base_state')=={'expression_library_revision':0,'asset_index_revision':0,'identity_revision':0},'base state mismatch')
    if phase=='staging':
        for rel,expected in md.get('base_hashes',{}).items(): req((formal/rel).is_file() and sha(formal/rel)==expected,f'STALE_STAGING: {rel}')
    else:
        for rel in ('character/identity.yaml','character/identity.md','variants/index.yaml'):
            req((formal/rel).is_file() and sha(formal/rel)==md.get('base_hashes',{}).get(rel),f'protected file changed: {rel}')
    for x in md.get('files',[]):
        p=staging/x.get('staged_path',''); req(p.is_file(),f"manifest file missing: {x.get('target_path')}")
        if p.is_file(): req(sha(p)==x.get('candidate_hash'),f"candidate hash mismatch: {x.get('target_path')}")
        if phase=='staging': req(x.get('after_hash') is None and x.get('publication_status')=='pending','publication progress found')
        else:
            target=formal/x.get('target_path',''); req(target.is_file() and sha(target)==x.get('candidate_hash')==x.get('after_hash') and x.get('publication_status')=='replaced',f"published target verification failed: {x.get('target_path')}")
    req(sha(candidate/'character/identity.yaml')==sha(formal/'character/identity.yaml'),'Identity changed')
    req(sha(candidate/'variants/index.yaml')==sha(formal/'variants/index.yaml'),'Variant index changed')
    return {'validator':'expression-staging-v1','calibration_id':hd.get('calibration_id'),'status':'PASS' if not errors else 'FAIL','counts':{'assets':len(assets),'semantics':len(sem),'approved':sum(x.get('semantic_review_status')=='APPROVED' for x in sem),'face_slots':len(slots),'expression_sets':len(sets),'confirmed_clusters':len(clusters),'similarity_groups':len(sims),'pending_compatibility_evidence':len(pending),'materialized_composite_compatibility':len(ed.get('composite_compatibility',[]))},'errors':errors,'warnings':sorted(set(warnings))}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--candidate',type=Path,required=True); p.add_argument('--staging',type=Path,required=True); p.add_argument('--formal',type=Path,required=True); p.add_argument('--phase',choices=['staging','published'],default='staging'); p.add_argument('--json',action='store_true'); a=p.parse_args()
    r=validate(a.candidate.resolve(),a.staging.resolve(),a.formal.resolve(),a.phase); print(json.dumps(r,ensure_ascii=False,indent=2) if a.json else f"{r['status']}: {len(r['errors'])} errors, {len(r['warnings'])} warnings"); return 0 if r['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
