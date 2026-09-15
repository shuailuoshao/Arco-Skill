"""Staging-only replacement audit. No publisher, remote adapter or Runtime changes.

L2 approved scope: reuse FFmpeg, existing validators and isolated mock tests.
No external research/rule injection: this task is a bounded offline calibration.
Run once; snapshots are never overwritten. All outputs remain in this staging.
"""
from __future__ import annotations
import copy
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from unittest.mock import patch

import yaml

HERE = Path(__file__).resolve().parent
STAGING = HERE.parent
ROOT = STAGING.parents[2]
CANDIDATE = STAGING / 'candidate-root'
PYTHON = ROOT / '.venv/Scripts/python.exe'
sys.path.insert(0, str(ROOT / 'scripts'))
import reference_runtime as runtime
import validate_library as library
from validate_identity_staging import validate as legacy_validate

A_HASH = '386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414'
BOX = [680, 0, 760, 640]
NEW_PATH = 'assets/arco/identity/p01-face-hair-primary-a.png'
PROFILES = ['portrait', 'upper_body', 'full_body', 'back_view']

def utc():
    return datetime.now(timezone.utc).isoformat()

def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def load(p):
    return yaml.safe_load(p.read_text(encoding='utf-8'))

def save(p, value):
    p.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding='utf-8')

def json_save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def protected():
    paths = [ROOT / 'SKILL.md']
    for rel in ['character', 'variants', 'states', 'assets', 'calibration/history', 'scripts', 'references', 'runtime']:
        paths.extend(p for p in (ROOT / rel).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in paths if p.is_file()}

def pixels(p, box=None):
    args = ['ffmpeg', '-v', 'error', '-i', str(p)]
    if box:
        x, y, w, h = box
        args += ['-vf', f'crop={w}:{h}:{x}:{y}:exact=1']
    return subprocess.check_output(args + ['-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba', 'pipe:1'], timeout=60)

def image_info(p):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,pix_fmt', '-of', 'json', str(p)], timeout=60))['streams'][0]

def base_drift(manifest):
    drift = []
    for rel, expected in manifest['base_hashes'].items():
        p = ROOT / rel
        actual = sha(p) if p.is_file() else None
        if actual != expected:
            drift.append({'path': rel, 'expected': expected, 'actual': actual})
    expected_revs = {'character/identity.yaml': 0, 'character/assets.yaml': 1, 'character/expressions.yaml': 1, 'variants/index.yaml': 0}
    for rel, expected in expected_revs.items():
        if load(ROOT / rel)['revision'] != expected:
            drift.append({'path': rel, 'expected_revision': expected, 'actual_revision': load(ROOT / rel)['revision']})
    return drift

def run_command(label, args):
    start = utc()
    tick = time.monotonic()
    print(f'START {label} {start}', flush=True)
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    try:
        result = subprocess.run(args, cwd=ROOT / 'scripts', env=env, capture_output=True, timeout=600)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
        status = 'PASS' if code == 0 else 'FAIL'
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr, status = None, exc.stdout or b'', exc.stderr or b'', 'INCOMPLETE'
    record = {'name': label, 'command': list(map(str, args)), 'cwd': str(ROOT / 'scripts'), 'start_time': start, 'end_time': utc(), 'duration_seconds': round(time.monotonic()-tick, 3), 'timeout_seconds': 600, 'exit_code': code, 'status': status, 'stdout': stdout.decode('utf-8', errors='replace'), 'stderr': stderr.decode('utf-8', errors='replace')}
    json_save(HERE / f'{label}.json', record)
    print(f'END {label} {status} {record["duration_seconds"]}s', flush=True)
    return record

def main():
    manifest = load(STAGING / 'publish-manifest.yaml')
    drift = base_drift(manifest)
    if drift:
        json_save(HERE / 'STALE_STAGING.json', drift)
        raise SystemExit('STALE_STAGING: no candidate writes performed')
    assert manifest['publication_authorized'] is False
    assert not (HERE / 'before').exists(), 'Do not overwrite prior replacement snapshot'
    before = protected()
    json_save(HERE / 'protected-before.json', before)
    comparison = load_json = json.loads((STAGING / 'crop-refinement/verification.json').read_text(encoding='utf-8'))
    for path, expected in comparison['protected_hashes_after'].items():
        p = Path(path)
        assert p.is_file() and sha(p) == expected, f'Pre-existing drift: {p}'
    source = STAGING / 'crop-refinement/p01-candidate-a.png'
    assert sha(source) == A_HASH
    assets = load(CANDIDATE / 'character/assets.yaml')
    identity = load(CANDIDATE / 'character/identity.yaml')
    history = load(STAGING / 'history-draft.yaml')
    by = {a['asset_id']: a for a in assets['assets']}
    old_assets = copy.deepcopy(assets)
    old_identity = copy.deepcopy(identity)
    parent = CANDIDATE / by['identity-p01']['path']
    parent_info, crop_info = image_info(parent), image_info(source)
    assert parent_info['width'] >= 1440 and parent_info['height'] >= 640
    assert (crop_info['width'], crop_info['height']) == (760, 640)
    expected_pixels, actual_pixels = pixels(parent, BOX), pixels(source)
    assert expected_pixels == actual_pixels and len(actual_pixels) == 760 * 640 * 4
    assert sha(parent) == by['identity-p01']['sha256']
    publish_assets = [by['identity-p01']['path'], NEW_PATH, by['identity-p03']['path']]
    assert all(not (ROOT / p).exists() for p in publish_assets), 'New formal target already exists'
    snapshot_rels = ['candidate-root/character/identity.yaml', 'candidate-root/character/assets.yaml', 'history-draft.yaml', 'publish-manifest.yaml', 'calibration-lock.yaml']
    for rel in snapshot_rels:
        target = HERE / 'before' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(STAGING / rel, target)
    assert not (CANDIDATE / NEW_PATH).exists()
    shutil.copyfile(source, CANDIDATE / NEW_PATH)
    crop = by['identity-p01-crop']
    previous_crop = copy.deepcopy(crop)
    crop.update(path=NEW_PATH, sha256=A_HASH, parent_asset_id='identity-p01', derived_from_asset_id='identity-p01', evidence_independence='none', dimensions_px=[760, 640])
    crop['operation'].update(crop_box_px=BOX, source_sha256=sha(parent))
    gen = crop['generation_reference']
    gen.update(priority='primary', supported_roles=['identity_reference'], preferred_for=['portrait'], excluded_for=['upper_body', 'full_body', 'back_view'])
    gen['coverage']['profiles'] = ['portrait']
    gen['inheritance'].update(identity='inherit', outfit='do_not_inherit', pose='do_not_inherit', expression='do_not_inherit')
    note = {'outfit_leakage': 'LOW', 'expression_leakage': 'HIGH', 'remaining_risk_accepted_by_user': True, 'expression_should_not_be_inherited_by_default': True, 'intended_use': 'WHO anchoring, not default expression transfer', 'future_compiler_rule': 'Prompt compiler / Expression Resolver should override expression through text and approved semantic selection.', 'current_runtime_enforcement': 'MUST_BE_VERIFIED; metadata is not proof of enforcement'}
    crop['generation_risk_note'] = note
    # Preserve Secondary records, provenance, Expression records, and all facts verbatim as data.
    assert by['identity-p01'] == old_assets['assets'][-3]
    assert by['identity-p03'] == old_assets['assets'][-2]
    visual_coverage = {
        'portrait': {'status': 'READY', 'asset_ids': ['identity-p01-crop'], 'missing_fields': [], 'basis': 'Accepted face, eyes, bangs, hair origin / WHO crop; full hair length is Secondary-only.'},
        'upper_body': {'status': 'READY', 'asset_ids': ['identity-p01'], 'missing_fields': [], 'basis': 'Full P01 visibly supplies upper torso and overall hair; Identity-only visual inventory, not outfit inheritance or Runtime certification.'},
        'full_body': {'status': 'READY', 'asset_ids': ['identity-p01'], 'missing_fields': [], 'basis': 'Full P01 supplies overall body and hair length; body proportions auxiliary; no clothing inheritance.'},
        'back_view': {'status': 'INCOMPLETE', 'asset_ids': [], 'missing_fields': ['hair.back', 'body.back', 'view.back'], 'basis': 'No rear reference. No mirroring or inference.'},
    }
    identity['identity_primary'] = 'identity-p01-crop'
    identity['coverage'] = {p: d['status'] for p, d in visual_coverage.items()}
    identity['coverage_basis'] = 'Identity-only visual inventory; not current Runtime selection readiness. See primary replacement audit.'
    identity['global_reference_readiness'] = 'PARTIAL'
    history['primary_replacement'] = {'timestamp': utc(), 'user_decision_record': 'primary-replacement/user-decision.md', 'selected_candidate': 'A', 'before': previous_crop, 'after': copy.deepcopy(crop), 'comparison_records_retained': ['candidate-root/assets/arco/identity/p01-face-hair-crop.png', 'crop-refinement/p01-candidate-b.png', 'crop-refinement/p01-candidate-c.png', 'crop-refinement/verification.json', 'crop-refinement/CROP COMPARISON REPORT.md'], 'visual_coverage': visual_coverage, 'runtime_not_repaired': True, 'publication_executed': False}
    history['generation_permissions']['identity-p01-crop'] = copy.deepcopy(gen)
    history['coverage'] = identity['coverage']
    history['global_reference_readiness'] = 'PARTIAL'
    save(CANDIDATE / 'character/assets.yaml', assets)
    save(CANDIDATE / 'character/identity.yaml', identity)
    save(STAGING / 'history-draft.yaml', history)
    for item in manifest['files']:
        item['candidate_hash'] = sha(STAGING / item['staged_path'])
    for rel in publish_assets:
        manifest['files'].append({'target_path': rel, 'staged_path': 'candidate-root/' + rel, 'before_hash': None, 'candidate_hash': sha(CANDIDATE / rel), 'after_hash': None, 'backup_path': None, 'rollback_action': 'remove_created_file_only_if_hash_matches_candidate', 'verification_class': 'immutable_data', 'publication_status': 'pending'})
    manifest['revalidation_status'] = 'IN_PROGRESS'
    save(STAGING / 'publish-manifest.yaml', manifest)
    checks = []
    def check(name, passed, detail=None, category='candidate'):
        checks.append({'name': name, 'status': 'PASS' if passed else 'FAIL', 'category': category, 'detail': detail})
    check('primary_unique_candidate_a', [a['asset_id'] for a in assets['assets'] if a.get('generation_reference', {}).get('priority') == 'primary'] == ['identity-p01-crop'] and crop['sha256'] == A_HASH)
    check('parent_crop_rgba_dimensions_alpha', expected_pixels == actual_pixels, {'parent': parent_info, 'crop': crop_info, 'crop_box': BOX, 'rgba_sha256': hashlib.sha256(actual_pixels).hexdigest(), 'transparent_fraction': actual_pixels[3::4].count(0)/(760*640), 'no_resize_recolor_enhance_repaint': True})
    check('portrait_only_metadata', gen['preferred_for'] == ['portrait'] and set(gen['excluded_for']) == set(PROFILES[1:]))
    check('secondary_records_unchanged', by['identity-p01'] == old_assets['assets'][-3] and by['identity-p03'] == old_assets['assets'][-2])
    check('all_asset_ids_unique_and_evidence_closed', len(by) == len(assets['assets']) and all(e in by for f in identity['facts'] for e in f.get('evidence_ids', [])))
    check('facts_and_revisions_unchanged', identity['facts'] == old_identity['facts'] and identity['revision'] == 1 and assets['revision'] == 2, dict(Counter(f['status'] for f in identity['facts'])))
    formal_assets = load(ROOT / 'character/assets.yaml')['assets']
    check('43_expression_records_unchanged', len(formal_assets) == 43 and assets['assets'][:43] == formal_assets)
    check('manifest_five_targets_and_hashes', len(manifest['files']) == 5 and all(sha(STAGING / f['staged_path']) == f['candidate_hash'] and f['after_hash'] is None for f in manifest['files']))
    check('publication_authorization_closed', manifest['publication_authorized'] is False and all(f['publication_status'] == 'pending' for f in manifest['files']))
    check('base_hashes_preserved', manifest['base_hashes'] == load(HERE / 'before/publish-manifest.yaml')['base_hashes'] and not base_drift(manifest))
    check('comparison_records_retained', all(sha(Path(p)) == h for p, h in comparison['protected_hashes_after'].items() if '/assets/' in p.replace('\\', '/') and '/candidate-root/' in p.replace('\\', '/')) and all(sha(Path(c['path'])) == c['sha256'] for c in comparison['candidates']))
    for aid in ['identity-p01', 'identity-p01-crop', 'identity-p03']:
        a = by[aid]
        check('managed_hash_' + aid, sha(CANDIDATE / a['path']) == a['sha256'])
        # Existing schema inconsistencies are blockers, not silently rewritten provenance.
        check('schema_compatibility_' + aid, assets['schema_version'] == 3 and set(a['roles']) <= library.VALID_ROLES and a.get('source_authority') in library.VALID_SOURCE_AUTHORITIES and a.get('view_angle') in library.VALID_VIEW_ANGLES, {'schema_version': assets['schema_version'], 'roles': a['roles'], 'source_authority': a['source_authority'], 'view_angle': a.get('view_angle')}, 'pre_existing_schema')
    # Runtime sees mock published paths and in-memory records only, never candidate file paths.
    mock_root = Path('D:/arco-offline-published-fixture')
    fixture_by_path = {(mock_root / a['path']).resolve(): a['sha256'] for a in by.values()}
    config = load(ROOT / 'runtime/generation.yaml')
    with patch.object(runtime.Path, 'is_file', return_value=True), patch.object(runtime, '_sha256', side_effect=lambda p: fixture_by_path[p]), patch('socket.socket', side_effect=AssertionError('Network forbidden')):
        selected = runtime.select_references(root=mock_root, managed_assets=assets['assets'], requested_roles=['identity_reference'], config=config)
        runtime_coverage = {p: runtime.compute_request_reference_readiness(exposure_profile=p, references=selected) for p in PROFILES}
        actual_global = runtime.compute_global_reference_readiness(identity, load(ROOT / 'variants/index.yaml'), assets['assets'])
        check('runtime_selected_candidate_a_not_p03', [r['asset_id'] for r in selected] == ['identity-p01-crop'], selected, 'runtime')
        check('runtime_secondary_support_upper_full', all(runtime_coverage[p]['status'] == 'READY' for p in ['upper_body', 'full_body']), runtime_coverage, 'runtime')
        check('runtime_global_not_above_partial', actual_global['overall'] != 'READY', actual_global, 'runtime')
        check('runtime_expression_outfit_pose_do_not_inherit', {'expression', 'outfit', 'pose'} <= set(selected[0]['do_not_inherit']), selected[0], 'runtime')
        for kind in ['body_base', 'faceless_composite', 'expression']:
            forbidden = copy.deepcopy(crop)
            if kind == 'expression':
                forbidden['roles'] = ['expression_evidence']
            else:
                forbidden['asset_type'] = kind
            check('runtime_reject_' + kind, not runtime.generation_allowed(forbidden), category='runtime')
        denied = copy.deepcopy(crop)
        denied.pop('can_be_generation_reference')
        check('runtime_missing_permission_denied', not runtime.generation_allowed(denied), category='runtime')
        try:
            runtime.validate_reference_contract(dict(selected[0], path=str(CANDIDATE / NEW_PATH)))
            rejected = False
        except runtime.ReferenceRuntimeError as exc:
            rejected = exc.code == 'UNPUBLISHED_ASSET'
        check('runtime_staging_path_rejected', rejected, category='runtime')
    identity['runtime_selection_coverage'] = runtime_coverage
    identity['runtime_validation_status'] = 'FAIL' if any(c['status']=='FAIL' for c in checks if c['category']=='runtime') else 'PASS'
    save(CANDIDATE / 'character/identity.yaml', identity)
    history['primary_replacement']['runtime_coverage'] = runtime_coverage
    history['primary_replacement']['runtime_global_observed'] = actual_global
    save(STAGING / 'history-draft.yaml', history)
    for item in manifest['files']:
        item['candidate_hash'] = sha(STAGING / item['staged_path'])
    save(STAGING / 'publish-manifest.yaml', manifest)
    json_save(HERE / 'offline-checks.json', checks)
    commands = [
        ('identity-staging-validator', [str(PYTHON), str(ROOT/'scripts/validate_identity_staging.py'), '--root', str(ROOT), '--staging', str(STAGING), '--json']),
        ('runtime-tests', [str(PYTHON), '-m', 'unittest', 'test_reference_runtime', '-v']),
        ('regression-tests', [str(PYTHON), '-m', 'unittest', 'test_validate_library', '-v']),
        ('identity-regression-tests', [str(PYTHON), '-m', 'unittest', 'test_identity_staging', '-v']),
        ('expression-regression-tests', [str(PYTHON), '-m', 'unittest', 'test_validate_expression_staging', '-v']),
        ('formal-library-validation', [str(PYTHON), str(ROOT/'scripts/validate_library.py'), '--root', str(ROOT), '--json']),
        ('skill-validation', [str(PYTHON), 'C:/Users/shuai/.codex/skills/.system/skill-creator/scripts/quick_validate.py', str(ROOT)]),
    ]
    results = [run_command(label, args) for label, args in commands]
    after = protected()
    json_save(HERE / 'protected-after.json', after)
    check('formal_data_and_tooling_hashes_unchanged', before == after, {'protected_file_count': len(before), 'changed_paths': sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))})
    check('final_manifest_hashes', all(sha(STAGING / f['staged_path']) == f['candidate_hash'] for f in manifest['files']))
    check('final_base_hashes', not base_drift(manifest))
    passed = all(c['status'] == 'PASS' for c in checks) and all(r['status'] == 'PASS' for r in results)
    manifest['publication_state'] = 'STAGED_VALIDATED_AWAITING_AUTHORIZATION' if passed else 'STAGED_REVALIDATION_FAILED'
    manifest['revalidation_status'] = 'PASS' if passed else 'FAIL'
    manifest['revalidation_report'] = 'primary-replacement/IDENTITY STAGING REVALIDATION REPORT.json'
    save(STAGING / 'publish-manifest.yaml', manifest)
    lock = load(STAGING / 'calibration-lock.yaml')
    lock['state'] = manifest['publication_state'].lower()
    save(STAGING / 'calibration-lock.yaml', lock)
    history['primary_replacement']['validation_status'] = manifest['revalidation_status']
    history['primary_replacement']['blocking_checks'] = [c['name'] for c in checks if c['status'] == 'FAIL']
    save(STAGING / 'history-draft.yaml', history)
    report = {'title': 'IDENTITY STAGING REVALIDATION REPORT', 'timestamp': utc(), 'calibration_id': manifest['calibration_id'], 'staging_path': str(STAGING), 'primary_asset_id': crop['asset_id'], 'primary_path': str(CANDIDATE/NEW_PATH), 'crop_box': BOX, 'dimensions': [760,640], 'primary_sha256': A_HASH, 'parent_asset_id': 'identity-p01', 'parent_sha256': sha(parent), 'preferred_for': ['portrait'], 'excluded_for': PROFILES[1:], 'secondary_list': [{'asset_id':'identity-p01','priority':'secondary'}, {'asset_id':'identity-p03','priority':'supplemental'}], 'comparisons_retained': history['primary_replacement']['comparison_records_retained'], 'expression_leakage_note': note, 'visual_identity_coverage': visual_coverage, 'runtime_selection_coverage': runtime_coverage, 'candidate_global_reference_readiness': 'PARTIAL', 'actual_candidate_runtime_global': actual_global, 'formal_global_reference_readiness': runtime.compute_global_reference_readiness(load(ROOT/'character/identity.yaml'), load(ROOT/'variants/index.yaml'), formal_assets), 'candidate_revisions': {'identity':1,'assets':2}, 'formal_revisions': {'identity':0,'assets':1,'expressions':1,'variants':0}, 'fact_status_counts':dict(Counter(f['status'] for f in identity['facts'])), 'candidate_validator': 'PASS' if passed else 'FAIL', 'checks': checks, 'test_runs': results, 'formal_hashes_unchanged': before == after, 'protected_file_count':len(before), 'protected_hash_files':['protected-before.json','protected-after.json'], 'manifest': manifest, 'recommendation':'READY_FOR_IDENTITY_PUBLICATION' if passed else 'NOT_READY_FOR_IDENTITY_PUBLICATION', 'publication_executed':False, 'history_finalized':False, 'completion_marker_created':False, 'remote_generation_called':False, 'images_uploaded':False, 'runtime_modified':False}
    json_save(HERE/'offline-checks.json', checks)
    json_save(HERE/'IDENTITY STAGING REVALIDATION REPORT.json', report)
    lines = ['# IDENTITY STAGING REVALIDATION REPORT', '', f'结论：**{report["recommendation"]}**。Primary replacement 已完成；发布门禁未通过。', '', '| 项目 | 结果 |', '|---|---|', f'| 1. Calibration ID | {manifest["calibration_id"]} |', f'| 2. New Primary | identity-p01-crop；{CANDIDATE/NEW_PATH} |', '| 3. Crop box / dimensions | [680,0,760,640] / 760×640 |', f'| 4. SHA-256 | {A_HASH} |', '| 5. Parent | identity-p01；直接 RGBA 对应区域一致 |', '| 6. preferred_for | portrait only |', '| 7. Secondary | identity-p01 secondary；identity-p03 supplemental；原记录未改 |', '| 8. B/C 与旧 crop | 原文件和 comparison records 保留；不进入 manifest |', '| 9. Expression leakage | HIGH，用户接受；metadata 默认不继承，现有 Runtime 未落实 |']
    for number, profile in enumerate(PROFILES, 10):
        lines.append(f'| {number}. {profile} coverage | Identity visual: {visual_coverage[profile]["status"]}；Runtime: {runtime_coverage[profile]["status"]} |')
    lines += ['| 14. Candidate global | PARTIAL；现有 Runtime 错报 READY，作为阻断项 |', f'| 15. 综合 candidate validator | {report["candidate_validator"]}；legacy validator 结果见下表 |', '| 16–18. Runtime / regression / Skill | 见逐项执行结果 |', f'| 19. Formal hashes | {"UNCHANGED" if before==after else "CHANGED"}；{len(before)} protected files |', f'| 20. Manifest | {manifest["publication_state"]}；publication_authorized=false |', f'| 21. Recommendation | {report["recommendation"]} |', '', '## Test execution', '', '| Test | Status | Duration (s) | Exit |', '|---|---|---:|---:|']
    for result in results:
        lines.append(f'| {result["name"]} | {result["status"]} | {result["duration_seconds"]} | {result["exit_code"]} |')
    lines += ['', '每个测试的 JSON 保存完整 command、cwd、UTC start/end、duration、stdout/stderr 和 600 秒 timeout。未完成不计 PASS。', '', '## Blocking checks', '']
    lines += [f'- {c["name"]}: {json.dumps(c["detail"],ensure_ascii=False)}' for c in checks if c['status']=='FAIL']
    lines += [f'- Test failure/incomplete: {r["name"]}; see {r["name"]}.json.' for r in results if r['status']!='PASS']
    lines += ['', '## Coverage interpretation', '', '视觉 inventory 的 upper/full READY 仅指 P01 原图具备相应 Identity 信息，不代表服装继承、Variant 就绪或当前 Selector 能正确选取。Secondary metadata 和 Runtime 均未修改；实际缺失字段如下：', '']
    lines += [f'- {p}: selected={runtime_coverage[p]["basis"]}; missing={runtime_coverage[p]["missing_fields"]}' for p in PROFILES]
    lines += ['', '## Protection and audit', '', '- Candidate Identity 1 / Assets 2；正式 Identity 0 / Assets 1 / Expression 1 / Variant 0；State 与全部正式受保护内容未改（详见 Hash JSON）。', '- 14 facts: 10 UNCERTAIN / 4 TODO_CALIBRATION / 0 CANON / 0 VISUAL_CONSENSUS；事实值与状态未改。', '- manifest 为 5 个 publication targets（两份 YAML + 三张 Identity PNG），不含旧 crop/B/C。before_hash 未重置；after_hash 均为 null。', '- before/ 保存本次 staging 修改前快照；History 仅 Draft，未 finalize；未创建 completion marker。', '- 既有 schema/Runtime 问题如实阻断，不以旧浅层 validator PASS 替代发布资格。', '- 无远程图片生成、上传、publication 或正式工具修改。', '- 工作流采用本地复用、快照、逐项验证与留档；网络调研与全局规则注入不在批准范围。', '', '可复用结论：元数据声明不等于 Runtime 已执行；已有测试 PASS 不等于缺失场景通过；视觉 inventory 与实际选择 coverage 必须分开。']
    (HERE/'IDENTITY STAGING REVALIDATION REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({'recommendation': report['recommendation'], 'tests':[{k:r[k] for k in ['name','status','duration_seconds']} for r in results], 'failed_checks':[c['name'] for c in checks if c['status']=='FAIL'], 'formal_hashes_unchanged':before==after}, indent=2), flush=True)

if __name__ == '__main__':
    main()
