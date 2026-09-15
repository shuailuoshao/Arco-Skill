"""Record pre-existing guard mismatch; preserve original lock bytes, no tooling repair."""
import json
import run_revalidation as a

p = a.HERE/'IDENTITY STAGING REVALIDATION REPORT.json'
r = json.loads(p.read_text(encoding='utf-8'))
restored = a.sha(a.STAGING/'calibration-lock.yaml') == a.sha(a.HERE/'before/calibration-lock.yaml')
detail = {'original_lock_preserved':restored, 'state':a.load(a.STAGING/'calibration-lock.yaml')['state'], 'issue':'Pre-existing check_calibration_lock.ACTIVE uses uppercase states; original lock is lowercase. New failed manifest state is also absent from ACTIVE. Guard enforcement is not certified; no formal guard repair authorized.'}
r['checks'].append({'name':'target_lock_guard_compatibility','status':'FAIL','category':'pre_existing_tooling','detail':detail})
r['lock_audit'] = detail
r['formal_hashes_unchanged'] = a.protected() == json.loads((a.HERE/'protected-before.json').read_text(encoding='utf-8'))
a.json_save(p,r)
a.json_save(a.HERE/'offline-checks.json',r['checks'])
md=a.HERE/'IDENTITY STAGING REVALIDATION REPORT.md'
md.write_text(md.read_text(encoding='utf-8')+'\n## Existing lock guard limitation\n\n原 calibration-lock.yaml 已按快照逐字节恢复，避免本轮额外改变锁协议。现有 lock 的小写 state 不在正式 guard 的大写 ACTIVE 集合中；新失败 manifest 状态同样未被该 guard 支持。这是另一个既有工具兼容阻断，不宣称冲突锁已正确生效；未修改 guard。Manifest 仍 STAGED_REVALIDATION_FAILED / publication_authorized=false。\n',encoding='utf-8')
hp=a.STAGING/'history-draft.yaml'
history=a.load(hp)
history['primary_replacement']['final_audit']['lock_guard_limitation']=detail
a.save(hp,history)
print(json.dumps({'original_lock_restored':restored,'formal_hashes_unchanged':r['formal_hashes_unchanged']}))
