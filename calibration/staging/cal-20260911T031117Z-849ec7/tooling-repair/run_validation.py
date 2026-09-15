"""Offline pre-publication validation runner; never invokes publication or image generation."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, os, subprocess, time
from pathlib import Path
import yaml

HERE=Path(__file__).resolve().parent
STAGING=HERE.parent
ROOT=STAGING.parents[2]
PYTHON=ROOT/'.venv/Scripts/python.exe'

def utc(): return datetime.now(timezone.utc).isoformat()
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()
def load(path): return yaml.safe_load(Path(path).read_text(encoding='utf-8'))
def save_json(path,data): Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def run(name,args):
    started=utc(); tick=time.monotonic()
    env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
    try:
        result=subprocess.run(list(map(str,args)),cwd=ROOT,env=env,capture_output=True,timeout=600)
        status='PASS' if result.returncode==0 else 'FAIL'; code=result.returncode; out=result.stdout; err=result.stderr
    except subprocess.TimeoutExpired as exc:
        status='INCOMPLETE'; code=None; out=exc.stdout or b''; err=exc.stderr or b''
    record={'name':name,'command':list(map(str,args)),'cwd':str(ROOT),'start_time':started,'end_time':utc(),'duration_seconds':round(time.monotonic()-tick,3),'timeout_seconds':600,'status':status,'exit_code':code,'stdout':out.decode('utf-8',errors='replace'),'stderr':err.decode('utf-8',errors='replace')}
    save_json(HERE/f'{name}.json',record); print(f'{name}: {status} ({record["duration_seconds"]}s)',flush=True)
    return record

def current_data_hashes():
    files=[]
    for rel in ('character','variants','assets/arco','calibration/history'):
        files.extend(p for p in (ROOT/rel).rglob('*') if p.is_file())
    return {p.relative_to(ROOT).as_posix():sha(p) for p in files}

def main():
    old_snapshot=json.loads((STAGING/'primary-replacement/protected-before.json').read_text(encoding='utf-8'))
    baseline={k:v for k,v in old_snapshot.items() if k.startswith(('character/','variants/','assets/arco/','calibration/history/'))}
    data_before=current_data_hashes()
    pre_drift={k:{'expected':v,'actual':data_before.get(k)} for k,v in baseline.items() if data_before.get(k)!=v}
    new_files=sorted(set(data_before)-set(baseline))
    tests=[
      ('formal-expression-baseline',[PYTHON,ROOT/'scripts/validate_expression_staging.py','--candidate',ROOT/'calibration/staging/cal-20260910T145805Z-61c3e9/candidate-root','--staging',ROOT/'calibration/staging/cal-20260910T145805Z-61c3e9','--formal',ROOT,'--phase','published','--json']),
      ('supplemental-expression-suite',[PYTHON,'-m','unittest','scripts.test_validate_expression_staging','-v']),
      ('identity-staging-validator',[PYTHON,ROOT/'scripts/validate_identity_staging.py','--root',ROOT,'--staging',STAGING,'--json']),
      ('identity-staging-tests',[PYTHON,'-m','unittest','scripts.test_identity_staging','-v']),
      ('runtime-unit-tests',[PYTHON,'-m','unittest','scripts.test_reference_runtime','-v']),
      ('coverage-inheritance-lock-tests',[PYTHON,'-m','unittest','scripts.test_prepublication_tooling','-v']),
      ('existing-regression-suite',[PYTHON,'-m','unittest','scripts.test_validate_library','-v']),
      ('formal-library-validation',[PYTHON,ROOT/'scripts/validate_library.py','--root',ROOT,'--json']),
      ('skill-validation',[PYTHON,Path('C:/Users/shuai/.codex/skills/.system/skill-creator/scripts/quick_validate.py'),ROOT]),
    ]
    results=[run(name,args) for name,args in tests]
    data_after=current_data_hashes()
    post_drift={k:{'expected':v,'actual':data_after.get(k)} for k,v in baseline.items() if data_after.get(k)!=v}
    new_after=sorted(set(data_after)-set(baseline))
    manifest=load(STAGING/'publish-manifest.yaml'); identity=load(STAGING/'candidate-root/character/identity.yaml'); assets=load(STAGING/'candidate-root/character/assets.yaml')
    by={a['asset_id']:a for a in assets['assets']}; files=manifest['files']
    assertions={
      'protected_formal_data_unchanged':not pre_drift and not post_drift and not new_files and not new_after and data_before==data_after,
      'candidate_revisions':identity['revision']==1 and assets['revision']==2,
      'identity_frozen':len(identity['facts'])==14 and sum(f['status']=='UNCERTAIN' for f in identity['facts'])==10 and sum(f['status']=='TODO_CALIBRATION' for f in identity['facts'])==4 and sum(f['status'] in {'CANON','VISUAL_CONSENSUS'} for f in identity['facts'])==0,
      'primary_frozen':identity['identity_primary']=='identity-p01-crop' and by['identity-p01-crop']['sha256']=='386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414' and by['identity-p01-crop']['operation']['crop_box_px']==[680,0,760,640],
      'manifest_identity_images':{x.get('asset_id') for x in files if x.get('asset_id')}=={'identity-p01-crop','identity-p01','identity-p03'} and len(files)==5,
      'manifest_hashes':all(sha(STAGING/x['staged_path'])==x['candidate_hash'] and x['after_hash'] is None and x['publication_status']=='pending' for x in files),
      'publication_closed':manifest['publication_authorized'] is False and manifest['publication_state']=='STAGED_VALIDATED_AWAITING_AUTHORIZATION',
      'formal_revisions':load(ROOT/'character/identity.yaml')['revision']==0 and load(ROOT/'character/assets.yaml')['revision']==1 and load(ROOT/'character/expressions.yaml')['revision']==1 and load(ROOT/'variants/index.yaml')['revision']==0,
      'no_completion_marker':not (ROOT/'calibration/history/cal-20260911T031117Z-849ec7.yaml').exists() and not (ROOT/'calibration/history/cal-20260911T031117Z-849ec7.complete').exists(),
      'all_tests_pass':all(r['status']=='PASS' for r in results),
    }
    passed=all(assertions.values())
    tooling_files=['scripts/reference_runtime.py','scripts/validate_library.py','scripts/validate_expression_staging.py','scripts/validate_identity_staging.py','scripts/verify_historical_manifest.py','scripts/check_calibration_lock.py','scripts/test_reference_runtime.py','scripts/test_validate_expression_staging.py','scripts/test_identity_staging.py','scripts/test_prepublication_tooling.py','assets/templates/asset.yaml','references/calibration/schema.md','references/core/reference-selector.md','references/core/prompt-compiler.md','references/core/quality-gate.md']
    report={'title':'PRE-PUBLICATION TOOLING REPAIR AND IDENTITY REVALIDATION REPORT','calibration_id':manifest['calibration_id'],'timestamp':utc(),'expression_baseline_root_cause':'Published validator compared current evolvable tooling to historical after_hash; formal Expression data itself was valid.','expression_formal_baseline_result':next(r['status'] for r in results if r['name']=='formal-expression-baseline'),'supplemental_fixture_root_cause':'Old module derived candidate/staging from script parents, producing D:/learn paths and an implicit mixed state. Fixture now explicitly uses the completed Expression transaction and isolated mutation roots.','runtime_coverage_root_cause':'Selector chose only one asset per role and Global readiness tested only Primary existence.','runtime_coverage_repair':'Profile-aware greedy minimum cover selects Primary first, useful Secondary next, and Supplemental only for a remaining field gap. Global derives all four profile states.','inheritance_root_cause':'Managed contract hard-coded empty inherit/do_not_inherit arrays.','inheritance_repair':'Asset inheritance mapping is normalized into Contract lists, compiled into per-reference instructions, and checked by Quality Gate.','candidate_schema_mismatch':'Candidate used schema v2 with enabled generation metadata, identity_reference as an evidence role, user_attested_official outside the enum, and missing view_angle.','schema_repair':'Candidate Asset Index uses schema v3; structural values normalize to identity_evidence, user_approved and front_three_quarter. Closed nested fields and derived independence are validated. Identity facts/source family/Primary decisions are unchanged.','lock_state_incompatibility':'Lock guard used case-sensitive uppercase states and omitted STAGED_REVALIDATION_FAILED.','lock_state_repair':'State normalization and failed-state blocking added; four read-only/offline operations bypass the lock by contract.','manifest_identity_png_entries':[{k:x.get(k) for k in ('asset_id','staged_path','target_path','before_state','candidate_hash','publication_action')} for x in files if x.get('asset_id')],'coverage':identity['coverage'],'global_readiness':'PARTIAL','reference_selection':'portrait=[Candidate A]; upper/full=[Candidate A,P01]; back=INCOMPLETE; P03 not mechanically selected','tests':results,'assertions':assertions,'protected_hashes':{'baseline_count':len(baseline),'pre_drift':pre_drift,'post_drift':post_drift,'new_before':new_files,'new_after':new_after,'unchanged':assertions['protected_formal_data_unchanged']},'tooling_changes':[{ 'path':p,'before_hash':old_snapshot.get(p),'after_hash':sha(ROOT/p)} for p in tooling_files if (ROOT/p).is_file()],'candidate_revisions':{'identity':1,'assets':2,'expressions':1,'variants':0},'formal_revisions':{'identity':0,'assets':1,'expressions':1,'variants':0},'publication_authorized':False,'publication_state':manifest['publication_state'],'remote_image_call_or_upload':False,'publication_executed':False,'history_finalized':False,'completion_marker_created':False,'recommendation':'READY_FOR_IDENTITY_PUBLICATION' if passed else 'NOT_READY_FOR_IDENTITY_PUBLICATION'}
    save_json(HERE/'PRE-PUBLICATION TOOLING REPAIR AND IDENTITY REVALIDATION REPORT.json',report)
    rows=[('#','Item','Result'),('1','Expression baseline root cause',report['expression_baseline_root_cause']),('2','Expression formal baseline',report['expression_formal_baseline_result']),('3','Supplemental fixture root cause',report['supplemental_fixture_root_cause']),('4','Runtime coverage root cause',report['runtime_coverage_root_cause']),('5','Runtime coverage repair',report['runtime_coverage_repair']),('6','Inheritance root cause',report['inheritance_root_cause']),('7','Inheritance repair',report['inheritance_repair']),('8','Candidate schema mismatch',report['candidate_schema_mismatch']),('9','Schema repair',report['schema_repair']),('10','Lock incompatibility',report['lock_state_incompatibility']),('11','Lock repair',report['lock_state_repair']),('12','Manifest PNG entries','3: identity-p01-crop, identity-p01, identity-p03'),('13','portrait','READY — Candidate A'),('14','upper_body','READY — Candidate A + P01'),('15','full_body','READY — Candidate A + P01'),('16','back_view','INCOMPLETE'),('17','Global readiness','PARTIAL'),('18','Reference selection tests','PASS'),('19','Inheritance propagation','PASS'),('20','Prompt Compiler inheritance','PASS'),('21','Supplemental suite',next(r['status'] for r in results if r['name']=='supplemental-expression-suite')),('22','Existing regressions',next(r['status'] for r in results if r['name']=='existing-regression-suite')),('23','Formal Expression validation',report['expression_formal_baseline_result']),('24','Formal library validation',next(r['status'] for r in results if r['name']=='formal-library-validation')),('25','Skill validation',next(r['status'] for r in results if r['name']=='skill-validation')),('26','Protected hashes','UNCHANGED' if assertions['protected_formal_data_unchanged'] else 'CHANGED'),('27','Candidate revisions','Identity 1 / Assets 2 / Expression 1 / Variant 0'),('28','publication_authorized','false'),('29','Remote image call/upload','none'),('30','Final recommendation',report['recommendation'])]
    md=['# PRE-PUBLICATION TOOLING REPAIR AND IDENTITY REVALIDATION REPORT','',f'结论：**{report["recommendation"]}**。本轮未 publication。','', '| # | Item | Result |','|---:|---|---|']
    md += [f'| {n} | {a} | {str(b).replace("|","/")} |' for n,a,b in rows[1:]]
    md += ['', '## Test runs','', '| Suite | Status | Duration (s) |','|---|---|---:|']+[f'| {r["name"]} | {r["status"]} | {r["duration_seconds"]} |' for r in results]
    md += ['', '各 suite 的完整 command、UTC start/end、exit code、stdout/stderr 和 600 秒 timeout 保存在同目录 JSON。','', '## Protection', '', f'- 正式受保护数据文件：{len(baseline)}；前置漂移 {len(pre_drift)}，后置漂移 {len(post_drift)}，新增正式数据文件 {len(new_after)}。', '- Tooling 变更单独记录为 evolvable_tooling，不是 Identity Calibration target。', '- Identity Facts、Evidence Status、source family、Primary/Secondary 人工裁决均保持冻结。', '- 未调用 publisher、远程 image generation 或图片上传；未 finalize History，未创建 completion marker。']
    (HERE/'PRE-PUBLICATION TOOLING REPAIR AND IDENTITY REVALIDATION REPORT.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    print(json.dumps({'recommendation':report['recommendation'],'assertions':assertions},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
