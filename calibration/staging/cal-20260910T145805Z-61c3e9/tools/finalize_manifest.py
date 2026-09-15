#!/usr/bin/env python3
from pathlib import Path
import hashlib, yaml
ROOT=Path(r'D:\learn\Arco'); STAGE=ROOT/'calibration/staging/cal-20260910T145805Z-61c3e9'; C=STAGE/'candidate-root'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def load(p): return yaml.safe_load(Path(p).read_text(encoding='utf-8'))
def dump(p,d): Path(p).write_text(yaml.safe_dump(d,allow_unicode=True,sort_keys=False,width=120),encoding='utf-8')
m=load(STAGE/'publication/publish-manifest.yaml')
assets=[a['path'] for a in load(C/'character/assets.yaml')['assets']]
changed=['SKILL.md','assets/templates/asset.yaml','character/assets.yaml','character/expressions.yaml','references/calibration/schema.md','references/calibration/workflow.md','references/calibration/expression-schema.md','references/core/prompt-compiler.md','references/core/reference-routing.md','references/core/expression-compiler.md','scripts/validate_library.py','scripts/test_validate_library.py','scripts/validate_expression_staging.py','scripts/test_validate_expression_staging.py','scripts/check_calibration_lock.py']+assets
protected=sorted(set(changed+['character/identity.yaml','character/identity.md','variants/index.yaml']))
m['base_hashes']={p:sha(ROOT/p) for p in protected if (ROOT/p).is_file()}
m['files']=[]
for target in changed:
 formal=ROOT/target; staged=C/target
 m['files'].append({'target_path':target,'staged_path':f'candidate-root/{target}','before_hash':sha(formal) if formal.is_file() else None,'candidate_hash':sha(staged),'after_hash':None,'backup_path':f'backups/{target}','rollback_action':'restore_backup' if formal.is_file() else 'delete_created_file','publication_status':'pending'})
dump(STAGE/'publication/publish-manifest.yaml',m)
