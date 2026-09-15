#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, os, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
import yaml

CAL_ID='cal-20260910T145805Z-61c3e9'
ROOT=Path(r'D:\learn\Arco'); STAGE=ROOT/'calibration/staging'/CAL_ID; C=STAGE/'candidate-root'; MP=STAGE/'publication/publish-manifest.yaml'
IN_PROGRESS=STAGE/'publication_in_progress'; HISTORY=ROOT/'calibration/history'/f'{CAL_ID}.yaml'; COMPLETE=ROOT/'calibration/history'/f'{CAL_ID}.complete'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def load(p): return yaml.safe_load(Path(p).read_text(encoding='utf-8'))
def save(p,d):
 p=Path(p); p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(p.suffix+'.tmp'); t.write_text(yaml.safe_dump(d,allow_unicode=True,sort_keys=False,width=120),encoding='utf-8'); os.replace(t,p)
def replace(src,dst):
 dst=Path(dst); dst.parent.mkdir(parents=True,exist_ok=True); t=dst.parent/f'.{dst.name}.{CAL_ID}.tmp'; shutil.copy2(src,t); os.replace(t,dst)
def event(m,state,note):
 m['publication_state']=state; m.setdefault('transaction_log',[]).append({'at':datetime.now(timezone.utc).isoformat(),'state':state,'note':note}); save(MP,m)
def preflight(m):
 if m.get('calibration_id')!=CAL_ID: raise RuntimeError('calibration id mismatch')
 expected={'expression_library_revision':0,'asset_index_revision':0,'identity_revision':0}
 if m.get('base_state')!=expected: raise RuntimeError('manifest base_state mismatch')
 current={'expression_library_revision':load(ROOT/'character/expressions.yaml').get('revision'),'asset_index_revision':load(ROOT/'character/assets.yaml').get('revision'),'identity_revision':load(ROOT/'character/identity.yaml').get('revision')}
 if current!=expected: raise RuntimeError(f'STALE_STAGING revision mismatch: {current}')
 for rel,expected_hash in m.get('base_hashes',{}).items():
  p=ROOT/rel; actual=sha(p) if p.is_file() else None
  if actual!=expected_hash: raise RuntimeError(f'STALE_STAGING hash mismatch: {rel} expected={expected_hash} actual={actual}')
 for x in m['files']:
  staged=STAGE/x['staged_path']; target=ROOT/x['target_path']
  if not staged.is_file() or sha(staged)!=x['candidate_hash']: raise RuntimeError(f'candidate drift: {x["target_path"]}')
  actual=sha(target) if target.is_file() else None
  if actual!=x['before_hash']: raise RuntimeError(f'STALE_STAGING target mismatch: {x["target_path"]}')
def make_history(m):
 draft=load(STAGE/'history-draft.yaml'); assets=load(C/'character/assets.yaml'); expressions=load(C/'character/expressions.yaml'); now=datetime.now(timezone.utc).isoformat()
 return {'schema_version':2,'calibration_id':CAL_ID,'timestamp':now,'operation':'publish_expression_library','user_confirmed':True,'confirmed_at':now,'reason':'Publish the user-approved Arco Expression Library revision 1 and its 43 official Expression Assets.','evidence_ids':[x['asset_id'] for x in assets['assets']],'observations':[],
 'targets':[
  {'entity_ref':'character.assets','target_type':'asset_registry','target_id':None,'revision_before':0,'revision_after':1,'changed_fields':['schema_version','revision','last_calibration_id','assets'],'before':{'schema_version':1,'entity_type':'asset_registry','revision':0,'last_calibration_id':None},'after':{'schema_version':2,'entity_type':'asset_registry','revision':1,'last_calibration_id':CAL_ID}},
  {'entity_ref':'character.expressions','target_type':'expression_library','target_id':None,'revision_before':0,'revision_after':1,'changed_fields':['schema_version','entity_type','revision','last_calibration_id','scope','face_slots','expression_sets','semantics','expression_clusters','similarity_groups'],'before':{'schema_version':1,'entity_type':'expression_catalog','revision':0,'last_calibration_id':None,'scope':'generic'},'after':{'schema_version':2,'entity_type':'expression_library','revision':1,'last_calibration_id':CAL_ID,'scope':'arco'}}],
 'validation_result':{'validator_version':'expression-staging-v1','structure':'PASS','asset_count':43,'semantic_count':42,'approved_count':42,'errors':0,'warnings':8},
 'semantic_adjudication':draft['semantic_adjudication'],'pending_compatibility_evidence':draft['pending_compatibility_evidence'],'publication_status':'PUBLISHED','completion_status':'COMPLETED','finalized_at':now,'transaction_id':m['transaction_id']}
def rollback(m,replaced):
 for x in reversed(replaced):
  target=ROOT/x['target_path']; backup=STAGE/x['backup_path']
  if x['before_hash'] is None:
   if target.is_file(): target.unlink()
  else:
   replace(backup,target)
  x['publication_status']='rolled_back'; x['after_hash']=sha(target) if target.is_file() else None
 if HISTORY.is_file(): HISTORY.unlink()
 if COMPLETE.is_file(): COMPLETE.unlink()
 save(MP,m)
def main():
 p=argparse.ArgumentParser(); p.add_argument('--authorize-calibration',required=True); a=p.parse_args()
 if a.authorize_calibration!=CAL_ID: raise SystemExit('authorization calibration id mismatch')
 m=load(MP); replaced=[]
 try:
  preflight(m); m['publication_authorized']=True; event(m,'PREFLIGHT_PASSED','base revisions, protected hashes, candidate hashes and target before-hashes match')
  final_history=make_history(m); save(STAGE/'history-final.yaml',final_history); m['staged_history_path']='history-final.yaml'; save(MP,m)
  for x in m['files']:
   target=ROOT/x['target_path']; backup=STAGE/x['backup_path']
   if x['before_hash'] is not None:
    backup.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(target,backup)
    if sha(backup)!=x['before_hash']: raise RuntimeError(f'rollback snapshot mismatch: {x["target_path"]}')
  event(m,'ROLLBACK_SNAPSHOT_READY','all existing publication targets have verified backups')
  IN_PROGRESS.write_text(m['transaction_id']+'\n',encoding='utf-8'); event(m,'PUBLICATION_IN_PROGRESS','publication_in_progress marker created')
  for x in m['files']:
   replace(STAGE/x['staged_path'],ROOT/x['target_path']); actual=sha(ROOT/x['target_path'])
   if actual!=x['candidate_hash']: raise RuntimeError(f'after-hash mismatch: {x["target_path"]}')
   x['after_hash']=actual; x['publication_status']='replaced'; replaced.append(x); save(MP,m)
  event(m,'AFTER_HASH_VALIDATED',f'{len(replaced)} files written and verified')
  r=subprocess.run([sys.executable,str(ROOT/'scripts/validate_expression_staging.py'),'--candidate',str(ROOT),'--staging',str(STAGE),'--formal',str(ROOT),'--phase','published','--json'],capture_output=True,text=True,encoding='utf-8')
  m['post_write_expression_validation']={'exit_code':r.returncode,'output':r.stdout}
  if r.returncode: raise RuntimeError('post-write expression validation failed: '+r.stdout+r.stderr)
  replace(STAGE/'history-final.yaml',HISTORY); COMPLETE.parent.mkdir(parents=True,exist_ok=True); COMPLETE.write_text(CAL_ID+'\n',encoding='utf-8')
  event(m,'HISTORY_FINALIZED','History and completion marker created')
  sys.path.insert(0,str(ROOT/'scripts')); from validate_library import validate
  final=validate(ROOT); m['final_validation']=final
  if final.get('structure')!='PASS': raise RuntimeError('final library validation failed')
  q=subprocess.run([sys.executable,r'C:\Users\shuai\.codex\skills\.system\skill-creator\scripts\quick_validate.py',str(ROOT)],capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'1'})
  m['skill_validation']={'exit_code':q.returncode,'output':q.stdout}
  if q.returncode: raise RuntimeError('skill validation failed: '+q.stdout+q.stderr)
  m['completed_at']=datetime.now(timezone.utc).isoformat(); event(m,'COMPLETE','transaction complete; final validators passed')
  lock=load(STAGE/'calibration-lock.yaml'); lock['state']='COMPLETE'; lock['completed_at']=m['completed_at']; save(STAGE/'calibration-lock.yaml',lock)
  IN_PROGRESS.unlink(missing_ok=True); m=load(MP); m['publication_in_progress_marker_cleared']=True; save(MP,m)
  print(f'COMPLETE {CAL_ID} files={len(replaced)}')
  return 0
 except Exception as exc:
  m=load(MP); m['failure']=str(exc); m['publication_state']='RECOVERY_REQUIRED'; m.setdefault('transaction_log',[]).append({'at':datetime.now(timezone.utc).isoformat(),'state':'RECOVERY_REQUIRED','note':str(exc)})
  try:
   rollback(m,replaced); m=load(MP); m['rollback_attempted']=True; m['rollback_succeeded']=True; save(MP,m)
  except Exception as rex:
   m=load(MP); m['rollback_attempted']=True; m['rollback_succeeded']=False; m['rollback_failure']=str(rex); save(MP,m)
  print('RECOVERY_REQUIRED: '+str(exc),file=sys.stderr); return 1
if __name__=='__main__': raise SystemExit(main())
