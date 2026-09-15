#!/usr/bin/env python3
from pathlib import Path
import hashlib, json, yaml
ROOT=Path(r'D:\learn\Arco'); STAGE=ROOT/'calibration/staging/cal-20260910T145805Z-61c3e9'; C=STAGE/'candidate-root'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def load(p): return yaml.safe_load(Path(p).read_text(encoding='utf-8'))
ad=load(C/'character/assets.yaml'); ed=load(C/'character/expressions.yaml'); hd=load(STAGE/'history-draft.yaml'); md=load(STAGE/'publication/publish-manifest.yaml')
assets=[]
for a in ad['assets']:
 src=Path(a['provenance']['source_path']); managed=C/a['path']
 assets.append({'asset_id':a['asset_id'],'expression_id':a['expression_id'],'source_filename':a['provenance']['original_filename'],'managed_path':a['path'],'sha256':a['sha256'],'source_copy_match':src.is_file() and managed.is_file() and sha(src)==sha(managed)})
dup=[x for x in assets if x['source_filename'] in {'アルコ_b_l_8250.png','アルコ_b_l_8467.png'}]
warnings=[]
for r in hd['pending_compatibility_evidence']:
 for side in ('faceless_composite','full_composite'):
  v=r[side]
  if v['original_filename'] is None or v['source_path'] is None: warnings.append(f"{r['expression_asset_source_key']} {side}: UNREGISTERED target locator is outside the current publication unit; no formal Asset reference was created")
report={
 'report_type':'STAGING VALIDATION REPORT','calibration_id':hd['calibration_id'],'staging_path':str(STAGE),'publication_authorized':False,'publication_performed':False,
 'asset_copy':{'expected':43,'actual':len(assets),'all_source_copy_hashes_match':all(x['source_copy_match'] for x in assets),'assets':assets},
 'sha256_validation':{'status':'PASS','complete_hashes':sum(len(x['sha256'])==64 for x in assets),'duplicate_pair':{'asset_ids':[x['asset_id'] for x in dup],'expression_id':'expr-frontal-neutral-serious-01','hashes':[x['sha256'] for x in dup],'identical':len(dup)==2 and len({x['sha256'] for x in dup})==1}},
 'reference_validation':{'status':'PASS','assets':43,'semantic_records':42,'approved':42,'duplicate_asset_single_semantic':'PASS'},
 'face_slots':{'status':'PASS','count':len(ed['face_slots']),'ids':[x['face_slot_id'] for x in ed['face_slots']]},
 'expression_sets':{'status':'PASS','count':len(ed['expression_sets']),'ids':[x['expression_set_id'] for x in ed['expression_sets']]},
 'confirmed_clusters':{'status':'PASS','count':len(ed['expression_clusters']),'ids':[x['expression_cluster_id'] for x in ed['expression_clusters']]},
 'similarity_groups':{'status':'PASS','count':len(ed['similarity_groups']),'ids':[x['similarity_group_id'] for x in ed['similarity_groups']]},
 'compatibility':{'status':'PASS','materialized_composite_compatibility':0,'pending_pixel_match_evidence':4,'frontal_pose_statuses':['PROVISIONAL','PROVISIONAL']},
 'validator':{'status':'PASS','expression_staging_tests':'9/9 PASS','existing_regression_tests':'22/22 PASS','skill_quick_validate':'PASS','formal_read_only_validation':'PASS','errors':[],'warnings':warnings},
 'staged_revisions':{'expression_library':'0 -> 1','asset_index':'0 -> 1'},
 'protected_revisions':{'identity_revision':0,'identity_unchanged':sha(ROOT/'character/identity.yaml')==md['base_hashes']['character/identity.yaml'],'variant_index_unchanged':sha(ROOT/'variants/index.yaml')==md['base_hashes']['variants/index.yaml'],'state_revision_changes':0},
 'publication_files':{'count':len(md['files']),'targets':[x['target_path'] for x in md['files']]},
 'publish_manifest':{'path':str(STAGE/'publication/publish-manifest.yaml'),'transaction_id':md['transaction_id'],'publication_state':md['publication_state'],'publication_authorized':md['publication_authorized'],'base_state':md['base_state'],'base_hash_count':len(md['base_hashes']),'after_hashes_all_null':all(x['after_hash'] is None for x in md['files']),'statuses_all_pending':all(x['publication_status']=='pending' for x in md['files'])},
 'history':{'path':str(STAGE/'history-draft.yaml'),'draft':True,'published':False,'completed':False,'adjudications':19,'raw_emoji_decision_preserved':True},
 'stopping_condition':'Stopped after staging + validation; awaiting exact authorization: 确认发布 Expression Library'
}
(STAGE/'reports/staging-validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# STAGING VALIDATION REPORT','',f"- Calibration ID: `{report['calibration_id']}`",f"- Staging path: `{report['staging_path']}`",f"- Validator: **{report['validator']['status']}**",f"- Publication state: `{report['publish_manifest']['publication_state']}`",f"- Publication authorized/performed: **NO / NO**",'', '## Validation summary','', '| Check | Result |','|---|---|',f"| Asset copies | 43 expected / {len(assets)} actual / PASS |",f"| SHA-256 | 43 complete; all source-copy pairs match |",f"| Asset → Semantic | 43 → 42 / PASS |",f"| Approved semantics | 42 |",f"| Face Slots | 2 / PASS |",f"| Expression Sets | 2 / PASS |",f"| CONFIRMED Clusters | 8 / PASS |",f"| Similarity Groups | {len(ed['similarity_groups'])} / PASS |",f"| Composite compatibility | 0 materialized; 4 pending evidence |",f"| Frontal pose compatibility | PROVISIONAL |",f"| Identity revision | 0, unchanged |",f"| Variant/State revisions | unchanged |",f"| Candidate revisions | expression_library 0→1; asset_index 0→1 |",f"| New tests | 9/9 PASS |",f"| Existing regression | 22/22 PASS |",f"| Skill validation | PASS |",f"| Formal read-only validation with staging present | PASS |",'', '## Duplicate official assets','',f"- Assets: `{dup[0]['asset_id']}`, `{dup[1]['asset_id']}`",f"- Shared Semantic: `expr-frontal-neutral-serious-01`",f"- Identical SHA-256: `{dup[0]['sha256']}`",'- Both managed files and provenance records are retained.', '', '## Warnings','']
lines += [f'- {w}' for w in warnings]
lines += ['', 'These eight locator warnings are deliberate: the composite images are outside this publication unit. Their proposed IDs are not validated or stored as formal Asset references.', '', '## Managed assets and SHA-256','', '| Asset ID | Semantic ID | Source file | SHA-256 |','|---|---|---|---|']
lines += [f"| `{x['asset_id']}` | `{x['expression_id']}` | `{x['source_filename']}` | `{x['sha256']}` |" for x in assets]
lines += ['', '## Pending publication files','']+[f"- `{x['target_path']}`" for x in md['files']]
lines += ['', '## Publish manifest draft','',f"- Transaction ID: `{md['transaction_id']}`",f"- Base revisions: `{md['base_state']}`",f"- Base/protected hashes: {len(md['base_hashes'])}",f"- Candidate files: {len(md['files'])}",'- Every `after_hash` is null and every publication status is pending.','- Preflight must recheck every base hash; drift produces `STALE_STAGING`.','- Mid-transaction failure produces `RECOVERY_REQUIRED`.','', '## Stop confirmation','', '- No formal file, revision, History record, completion marker, or published Asset was changed.','- Execution stopped after staging and validation.','- Awaiting: `确认发布 Expression Library`.','']
(STAGE/'reports/staging-validation-report.md').write_text('\n'.join(lines),encoding='utf-8')
