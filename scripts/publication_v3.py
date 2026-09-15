"""Hash-guarded v3 publication. No automatic authorization or remote adapters."""
from __future__ import annotations
import hashlib, json, os, shutil
from pathlib import Path
import yaml
from publish_calibration import PublishError, sha256, resolve_inside, replace_from_source

def load(p): return yaml.safe_load(p.read_text(encoding='utf-8'))
def write(p,data):
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.tmp')
    tmp.write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding='utf-8')
    os.replace(tmp,p)

def preflight(root,staging):
    m=load(staging/'publish-manifest.yaml')
    from check_calibration_lock import conflicts
    calibration_targets = set(m.get('calibration_targets') or [])
    if not calibration_targets:
        raise PublishError('Manifest calibration_targets must be a non-empty list')
    other=[x for x in conflicts(root,calibration_targets,'write') if x['calibration_id']!=m.get('calibration_id')]
    if other: raise PublishError('Conflicting calibration lock: '+str(other))
    if m.get('schema_version')!=3 or m.get('publication_authorized') is not False or m.get('publication_state')!='STAGED_VALIDATED_AWAITING_AUTHORIZATION':
        raise PublishError('Unauthorized or invalid initial transaction state')
    if m.get('revalidation_status')!='PASS': raise PublishError('Candidate validation not PASS')
    for rel,expected in m['base_hashes'].items():
        p=resolve_inside(root,rel,'base hash')
        if (sha256(p) if p.is_file() else None)!=expected: raise PublishError('STALE_STAGING: '+rel)
    revision_paths = {
        'identity_revision': 'character/identity.yaml',
        'asset_index_revision': 'character/assets.yaml',
        'expression_library_revision': 'character/expressions.yaml',
        'variant_index_revision': 'variants/index.yaml',
    }
    for key, expected in (m.get('base_state') or {}).items():
        rel = revision_paths.get(key)
        if rel is None:
            continue
        if load(root/rel)['revision']!=expected: raise PublishError('STALE_STAGING revision: '+rel)
    targets=[]
    for item in m['files']:
        p=resolve_inside(root,item['target_path'],'target'); s=resolve_inside(staging,item['staged_path'],'source')
        if p in targets: raise PublishError('Duplicate publication target')
        targets.append(p)
        if not s.is_file() or sha256(s)!=item['candidate_hash']: raise PublishError('Candidate hash: '+str(s))
        if (sha256(p) if p.is_file() else None)!=item['before_hash']: raise PublishError('STALE_STAGING: '+str(p))
    for key in ['history_path','completion_marker','in_progress_marker']:
        if resolve_inside(root,m[key],key).exists(): raise PublishError('Transaction artifact already exists: '+key)
    if sha256(staging/m['staged_history_path'])!=m['history_candidate_hash']: raise PublishError('History candidate drift')
    return m

def publish(root,staging,*,authorization,validate_written,validate_complete,fail_after=None):
    if not authorization or not authorization.get('user_confirmed'): raise PublishError('Explicit publication authorization required')
    m=preflight(root,staging)
    cid=m['calibration_id']; manifest_path=staging/'publish-manifest.yaml'
    history=load(staging/m['staged_history_path'])
    marker=resolve_inside(root,m['in_progress_marker'],'marker')
    def persist(): write(manifest_path,m)
    journal=[]
    # All snapshots precede the first formal write.
    for item in m['files']:
        target=root/item['target_path']
        backup=staging/'publication/rollback'/item['target_path']
        if target.exists():
            if backup.exists(): raise PublishError('Rollback snapshot already exists')
            backup.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(target,backup)
            if sha256(backup)!=item['before_hash']: raise PublishError('Rollback snapshot hash mismatch')
        item['backup_path']=backup.relative_to(staging).as_posix() if target.exists() else None
    m['publication_authorized']=True; m['authorization']=authorization
    m['publication_state']='PUBLICATION_IN_PROGRESS'; m['write_journal']=journal; persist()
    try:
        marker.parent.mkdir(parents=True,exist_ok=True)
        marker.write_text(json.dumps({'calibration_id':cid,'pending_history_sha256':hashlib.sha256(json.dumps(history,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'candidate_hashes':{x['target_path']:x['candidate_hash'] for x in m['files']}},ensure_ascii=False),encoding='utf-8')
        def replace(source,target,expected,before,label):
            record={'path':target.relative_to(root).as_posix(),'before_hash':before,'candidate_hash':expected,'label':label}
            journal.append(record); persist()
            current=sha256(target) if target.is_file() else None
            if current!=before: raise PublishError('Unexpected concurrent target drift: '+str(target))
            replace_from_source(source,target,cid)
            if sha256(target)!=expected: raise PublishError('After-hash mismatch')
            if fail_after==label: raise PublishError('INJECTED_FAILURE: '+label)
        ordered=sorted(m['files'],key=lambda x: 0 if x.get('asset_id') else 1 if x['target_path']=='character/assets.yaml' else 2 if x['target_path']=='character/identity.yaml' else 3)
        for item in ordered:
            replace(staging/item['staged_path'],root/item['target_path'],item['candidate_hash'],item['before_hash'],item.get('asset_id') or item['target_path'])
            item['after_hash']=item['candidate_hash']; item['publication_status']='replaced'; persist()
        validate_written(root,staging,history)
        replace(staging/m['staged_history_path'],root/m['history_path'],m['history_candidate_hash'],None,'history')
        completion_source=staging/'publication/completion-candidate.txt'
        completion_source.write_text(cid+'\n',encoding='utf-8')
        replace(completion_source,root/m['completion_marker'],sha256(completion_source),None,'completion_marker')
        m['publication_state']='AFTER_HASH_VALIDATED'; persist()
        validation=validate_complete(root,staging)
        m['final_validation']=validation; m['publication_state']='COMPLETE'; m['publication_status']='complete'; m['recovery_occurred']=False; persist()
        lock=load(staging/'calibration-lock.yaml'); lock['state']='COMPLETE'; write(staging/'calibration-lock.yaml',lock)
        marker.unlink()
        return m
    except Exception as exc:
        m['publication_state']='RECOVERY_REQUIRED'; m['failure']=str(exc); m['recovery_occurred']=True; persist()
        recovery=[]
        for record in reversed(journal):
            target=resolve_inside(root,record['path'],'rollback target'); current=sha256(target) if target.is_file() else None
            if current==record['before_hash']: continue
            if current!=record['candidate_hash']:
                recovery.append('UNKNOWN_HASH: '+record['path']); continue
            if record['before_hash'] is None: target.unlink()
            else:
                backup=staging/'publication/rollback'/record['path']
                if not backup.is_file() or sha256(backup)!=record['before_hash']:
                    recovery.append('INVALID_BACKUP: '+record['path']); continue
                replace_from_source(backup,target,cid)
        m['rollback_errors']=recovery; m['rollback_status']='PASS' if not recovery else 'FAIL'; persist()
        if not recovery: marker.unlink(missing_ok=True)
        raise PublishError(str(exc)) from exc
