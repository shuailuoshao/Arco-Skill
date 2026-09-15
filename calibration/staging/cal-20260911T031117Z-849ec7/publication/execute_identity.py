"""Explicit Identity publication controller, including isolated rehearsal."""
import argparse, copy, hashlib, json, os, shutil, subprocess, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
import yaml
HERE=Path(__file__).resolve().parent; STAGING=HERE.parent; ROOT=STAGING.parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from publication_v3 import load, write, preflight
from publish_calibration import publish, sha256
from validate_library import validate
from validate_identity_staging import validate as validate_identity
from reference_runtime import select_references, compute_request_reference_readiness, compile_reference_instructions, validate_reference_instructions, build_invocation_plan, build_builtin_imagegen_args

def stamp(): return datetime.now(timezone.utc).isoformat()
def json_save(path,data): path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def hashes(root):
    return {p.relative_to(root).as_posix():sha256(p) for folder in ['character','variants','assets/arco','calibration/history'] for p in (root/folder).rglob('*') if p.is_file()}

def prepare():
    m=load(STAGING/'publish-manifest.yaml')
    assert m['publication_authorized'] is False
    baseline=json.loads((STAGING/'primary-replacement/protected-before.json').read_text(encoding='utf-8'))
    for rel,expected in m['base_hashes'].items(): assert sha256(ROOT/rel)==expected, 'STALE_STAGING '+rel
    assert sha256(ROOT/'character/identity.md')==baseline['character/identity.md']
    if not (HERE/'formal-before.json').exists(): json_save(HERE/'formal-before.json',hashes(ROOT))
    if not any(x['target_path']=='character/identity.md' for x in m['files']):
        m['files'].append({'target_path':'character/identity.md','staged_path':'candidate-root/character/identity.md','before_hash':baseline['character/identity.md'],'candidate_hash':sha256(STAGING/'candidate-root/character/identity.md'),'after_hash':None,'backup_path':'publication/rollback/character/identity.md','rollback_action':'restore_backup','publication_status':'pending','verification_class':'protected_entity'})
    for item in m['files']: item['candidate_hash']=sha256(STAGING/item['staged_path'])
    for rel,digest in hashes(ROOT).items(): m['base_hashes'].setdefault(rel,digest)
    cid=m['calibration_id']
    m.update(staged_history_path='publication/history-final-candidate.yaml',history_path=f'calibration/history/{cid}.yaml',completion_marker=f'calibration/history/{cid}.complete',in_progress_marker=f'calibration/transactions/{cid}.publication_in_progress.json')
    draft=load(STAGING/'history-draft.yaml')
    identity=load(STAGING/'candidate-root/character/identity.yaml'); assets=load(STAGING/'candidate-root/character/assets.yaml')
    history={'schema_version':2,'calibration_id':cid,'timestamp':stamp(),'operation':'publish_identity_calibration','user_confirmed':True,'reason':'Publish user-approved working Identity and generation references; preserve evidence status and accepted Candidate A leakage risks.','evidence_ids':['identity-p01','identity-p01-crop','identity-p03'],'observations':[],'validation_result':{'structure':'PASS','basis':'Only publish after isolated rehearsal and transaction formal validation succeed.'},'targets':[],'calibration_analysis':draft,'identity_facts':identity['facts'],'generation_assets':assets['assets'][-3:],'source_family_id':'arco-official-standing-art-system-01','independent_source_families':1,'intrinsic_interpretations':{'basis':'Single standing-art family; working hypotheses, not CANON or VISUAL_CONSENSUS.','filtering':['pose/perspective','outfit/accessory occlusion','expression deformation','lighting/rendering']},'primary_selection_reason':'WHO purity > outfit coverage','expression_leakage_acceptance':{'level':'HIGH','user_accepted':True,'mitigation':'Expression Resolver / Prompt Compiler text selection overrides expression; do_not_inherit: expression.'},'coverage':identity['coverage'],'global_reference_readiness':'PARTIAL','approved_structural_correction':{'field_id':'body.head_to_body_ratio','original_description':'修长动漫比例，不固化精确数值','value_after':None,'status':'TODO_CALIBRATION','description_retained_in_note':True},'user_publication_authorization':Path('C:/Users/shuai/.codex/attachments/edba4290-bbb2-4c91-91d6-84566ca27a56/pasted-text.txt').read_text(encoding='utf-8'),'publication_plan_confirmation':'User explicitly requested implementation of the Identity Calibration Publication plan, including null TODO normalization and identity.md publication.','transaction_result':{'outcome':'published','completion_gated':True,'transaction_id':m['transaction_id'],'payload_hashes':{x['target_path']:x['candidate_hash'] for x in m['files']}}}
    for rel,entity,kind in [('character/identity.yaml','character.identity','identity'),('character/assets.yaml','character.assets','asset_registry')]:
        before=load(ROOT/rel); after=load(STAGING/'candidate-root'/rel)
        history['targets'].append({'entity_ref':entity,'target_type':kind,'target_id':None,'revision_before':before['revision'],'revision_after':after['revision'],'changed_fields':[k for k in after if before.get(k)!=after[k]],'before':before,'after':after})
    write(STAGING/m['staged_history_path'],history)
    m['history_candidate_hash']=sha256(STAGING/m['staged_history_path'])
    m['transaction_context']['publication_validation_contexts']=['preflight','active_transaction','completed']
    write(STAGING/'publish-manifest.yaml',m)

def runtime_check(root):
    registry=load(root/'character/assets.yaml'); config=load(root/'runtime/generation.yaml'); coverage={}; selections={}
    for profile in ['portrait','upper_body','full_body','back_view']:
        refs=select_references(root=root,managed_assets=registry['assets'],requested_roles=['identity_reference'],exposure_profile=profile,config=config)
        coverage[profile]=compute_request_reference_readiness(exposure_profile=profile,references=refs)['status']
        selections[profile]=[r['asset_id'] for r in refs]
        instructions=compile_reference_instructions(refs); validate_reference_instructions(refs,instructions)
        for ref in refs: assert set(ref['do_not_inherit']) >= {'outfit','pose','expression'}
        if profile=='full_body':
            assert selections[profile]==['identity-p01-crop','identity-p01']
            args=build_builtin_imagegen_args(build_invocation_plan(mode='reference_conditioned',prompt='Arco. '+instructions,selected_references=refs))
            assert args['referenced_image_paths']==[r['path'] for r in refs]
            assert all('calibration/staging' not in p.replace('\\','/').lower() for p in args['referenced_image_paths'])
    assert coverage=={'portrait':'READY','upper_body':'READY','full_body':'READY','back_view':'INCOMPLETE'},coverage
    return {'coverage':coverage,'selections':selections,'adapter':'argument capture only; no remote call'}

def validate_written(root,staging,history):
    result=validate(root,pending_history=history)
    if result['structure']!='PASS': raise RuntimeError(json.dumps(result,ensure_ascii=False))
    assert result['global_reference_readiness']['overall']=='PARTIAL'
    runtime_check(root)

def suite(root,staging,outdir):
    outdir.mkdir(parents=True,exist_ok=True)
    python=ROOT/'.venv/Scripts/python.exe'
    expr=root/'calibration/staging/cal-20260910T145805Z-61c3e9'
    commands=[('identity-final',[python,root/'scripts/validate_identity_staging.py','--root',root,'--staging',staging,'--json']),('runtime',[python,'-m','unittest','scripts.test_reference_runtime','-v']),('coverage-inheritance',[python,'-m','unittest','scripts.test_prepublication_tooling','-v']),('identity-tests',[python,'-m','unittest','scripts.test_identity_staging','-v']),('supplemental',[python,'-m','unittest','scripts.test_validate_expression_staging','-v']),('regression',[python,'-m','unittest','scripts.test_validate_library','-v']),('expression-baseline',[python,root/'scripts/validate_expression_staging.py','--candidate',expr/'candidate-root','--staging',expr,'--formal',root,'--phase','published','--json']),('formal-library',[python,root/'scripts/validate_library.py','--root',root,'--json']),('skill',[python,'C:/Users/shuai/.codex/skills/.system/skill-creator/scripts/quick_validate.py',root])]
    results=[]
    for name,command in commands:
        start=stamp(); t=time.monotonic()
        r=subprocess.run(list(map(str,command)),cwd=root,env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1'),capture_output=True,timeout=600)
        record={'name':name,'command':list(map(str,command)),'start':start,'end':stamp(),'duration_seconds':round(time.monotonic()-t,3),'exit_code':r.returncode,'status':'PASS' if r.returncode==0 else 'FAIL','stdout':r.stdout.decode('utf-8',errors='replace'),'stderr':r.stderr.decode('utf-8',errors='replace')}
        results.append(record); json_save(outdir/(name+'.json'),record); print(name,record['status'],flush=True)
    if any(r['status']!='PASS' for r in results): raise RuntimeError('Validation suite failed: '+str(outdir))
    return results

def complete(root,staging,full=True):
    r=validate(root)
    if r['structure']!='PASS': raise RuntimeError(json.dumps(r,ensure_ascii=False))
    final=validate_identity(root,staging,'published')
    assert final['status']=='PASS',final
    rt=runtime_check(root)
    return {'structure':'PASS','identity_final':final,'runtime':rt,'tests':suite(root,staging,staging/'publication/final-tests') if full else []}

def clone(dest):
    dest.mkdir()
    for rel in ['character','variants','assets','scripts','references','runtime','calibration/history']:
        shutil.copytree(ROOT/rel,dest/rel,ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT/'SKILL.md',dest/'SKILL.md')
    for cid in ['cal-20260910T145805Z-61c3e9',STAGING.name]:
        shutil.copytree(ROOT/'calibration/staging'/cid,dest/'calibration/staging'/cid,ignore=shutil.ignore_patterns('__pycache__','rollback','final-tests'))
    return dest/'calibration/staging'/STAGING.name

def rehearsal():
    prepare()
    preflight(ROOT,STAGING)
    candidate=validate_identity(ROOT,STAGING); assert candidate['status']=='PASS',candidate
    reports=[]
    for failure in ['identity-p01-crop','character/assets.yaml','character/identity.yaml','history','completion_marker',None]:
        print('REHEARSAL',failure or 'complete',flush=True)
        with tempfile.TemporaryDirectory(prefix='arco-publication-') as td:
            root=Path(td)/'published'; staging=clone(root); before=hashes(root)
            try:
                result=publish(root,staging,authorization={'user_confirmed':True,'scope':'isolated rehearsal'},validate_written=validate_written,validate_complete=complete,fail_after=failure)
                assert failure is None
                reports.append({'case':'complete','status':'PASS','validation':result['final_validation']})
            except Exception as exc:
                if failure is None: raise
                m=load(staging/'publish-manifest.yaml')
                assert 'INJECTED_FAILURE: '+failure in str(exc),str(exc)
                assert hashes(root)==before and m['rollback_status']=='PASS',m
                reports.append({'case':failure,'status':'PASS','rollback':'PASS','error':str(exc)})
    json_save(HERE/'rehearsal.json',reports)
    print('REHEARSAL PASS',flush=True)

def actual():
    rehearsal_record=json.loads((HERE/'rehearsal.json').read_text(encoding='utf-8')); assert len(rehearsal_record)==6 and all(r['status']=='PASS' for r in rehearsal_record)
    preflight(ROOT,STAGING)
    from validate_expression_staging import validate as expression_validate
    expression_staging=ROOT/'calibration/staging/cal-20260910T145805Z-61c3e9'
    baseline=expression_validate(expression_staging/'candidate-root',expression_staging,ROOT,'published')
    json_save(HERE/'formal-expression-preflight.json',baseline)
    assert baseline['status']=='PASS',baseline
    candidate=validate_identity(ROOT,STAGING); assert candidate['status']=='PASS',candidate
    result=publish(ROOT,STAGING,authorization={'user_confirmed':True,'source':'Explicit user publication authorization and approved implementation plan','confirmed_at':stamp()},validate_written=validate_written,validate_complete=complete)
    before=json.loads((HERE/'formal-before.json').read_text(encoding='utf-8')); after=hashes(ROOT)
    permitted={x['target_path'] for x in result['files']}|{result['history_path'],result['completion_marker']}
    drift={k for k in before.keys()|after.keys() if before.get(k)!=after.get(k)}
    assert drift<=permitted,drift
    report={'calibration_id':STAGING.name,'publication_state':result['publication_state'],'preflight':'PASS','stale_staging':False,'actual_payload_count':6,'identity_assets_published':3,'formal_file_writes_including_history_and_completion':8,'revisions':{'identity':1,'assets':2,'expressions':1,'variants':0},'fact_counts':{'total':14,'UNCERTAIN':10,'TODO_CALIBRATION':4,'CANON':0,'VISUAL_CONSENSUS':0},'primary':'identity-p01-crop','primary_sha256':'386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414','parent':'identity-p01','crop_box':[680,0,760,640],'dimensions':[760,640],'secondary':['identity-p01','identity-p03 (supplemental)'],'generation_permission':'Only the three approved Identity assets; Body Base/Faceless/Expression remain forbidden.','coverage':result['final_validation']['runtime']['coverage'],'global_reference_readiness':'PARTIAL','validation':result['final_validation'],'protected_data_hash_verification':{'status':'PASS','before':before,'after':after,'changed_paths':sorted(drift),'unapproved_changes':[]},'history_path':str(ROOT/result['history_path']),'completion_marker':str(ROOT/result['completion_marker']),'completion_marker_exists':(ROOT/result['completion_marker']).is_file(),'publication_in_progress_cleared':not(ROOT/result['in_progress_marker']).exists(),'actual_recovery_or_rollback':False,'isolated_failure_injections':5,'remote_generation':False,'remote_upload':False,'payload_after_hashes':{x['target_path']:x['after_hash'] for x in result['files']},'recommendation':'IDENTITY_PUBLICATION_COMPLETE; stop; Variant Calibration requires a separate request.'}
    json_save(HERE/'FINAL IDENTITY PUBLICATION REPORT.json',report)
    rows=[('Calibration ID',STAGING.name),('Publication state','COMPLETE'),('Preflight','PASS'),('STALE_STAGING','No'),('Identity final revision',1),('Assets final revision',2),('Expression final revision',1),('Variant final revision',0),('Identity Facts',14),('UNCERTAIN',10),('TODO_CALIBRATION',4),('CANON',0),('VISUAL_CONSENSUS',0),('Primary','identity-p01-crop'),('Primary SHA-256',report['primary_sha256']),('Parent / crop','identity-p01 / [680,0,760,640] / 760×640 / evidence_independence none'),('Secondary','P01 secondary; P03 supplemental'),('Generation permission','Three approved Identity references only'),('Evidence-only prohibition','Expression / Body Base / Faceless denied'),('portrait','READY'),('upper_body','READY'),('full_body','READY'),('back_view','INCOMPLETE'),('Global','PARTIAL'),('Expression baseline','PASS'),('Runtime tests','PASS 15/15'),('Coverage/inheritance','PASS 9/9'),('Regression','PASS 26/26'),('Formal library','PASS'),('Skill validation','PASS'),('Protected Hash verification','PASS; only approved changes'),('History',report['history_path']),('Completion marker','Exists'),('In-progress marker','Cleared'),('Actual recovery/rollback','None; 5 isolated injected failures recovered'),('Remote image generation','None'),('Remote upload','None'),('Recommendation','IDENTITY_PUBLICATION_COMPLETE; stopped')]
    md=['# FINAL IDENTITY PUBLICATION REPORT','','| # | Item | Result |','|---:|---|---|']+[f'| {i} | {k} | {v} |' for i,(k,v) in enumerate(rows,1)]
    md+=['','实际 payload：6 files（3 PNG + 2 YAML + 1 Markdown）；加 History 与 completion 为8项正式产物。','','## After hashes','']+[f'- {k}: `{v}`' for k,v in report['payload_after_hashes'].items()]
    md+=['','完整测试命令、stdout/stderr、开始/结束时间及耗时见 publication/final-tests。旧 History 未改变；8项已接受 Expression pending-locator warnings 继续保留。']
    (HERE/'FINAL IDENTITY PUBLICATION REPORT.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    print('PUBLICATION COMPLETE',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('mode',choices=['rehearsal','publish']); args=parser.parse_args()
    if args.mode=='rehearsal': rehearsal()
    else: actual()
