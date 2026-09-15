"""Read-only final checks and honest interrupted-suite annotation; staging reports only."""
import copy
import json
from pathlib import Path
from unittest.mock import patch
import run_revalidation as audit

def main():
    h = audit.HERE
    report_path = h / 'IDENTITY STAGING REVALIDATION REPORT.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    stopped = json.loads((h / 'expression-regression-tests.json').read_text(encoding='utf-8'))
    stopped['status'] = 'INCOMPLETE'
    stopped['termination_reason'] = 'Operator stopped the specific test processes: pre-existing fixture resolves STAGING to D:/learn and starts copying the unrelated parent directory. Baseline had already errored. Not a timeout; no test code repaired.'
    stopped['observed_baseline_status'] = 'ERROR'
    audit.json_save(h / 'expression-regression-tests.json', stopped)
    report['test_runs'] = [stopped if r['name']=='expression-regression-tests' else r for r in report['test_runs']]
    # Safe baseline-only reproduction does not run the broken copying fixture.
    baseline = audit.run_command('expression-baseline-only', [str(audit.PYTHON), '-m', 'unittest', 'test_validate_expression_staging.Tests.test_baseline', '-v'])
    report['test_runs'].append(baseline)
    m = audit.load(audit.STAGING / 'publish-manifest.yaml')
    checks = report['checks']
    def check(name, condition, detail=None):
        checks.append({'name':name, 'status':'PASS' if condition else 'FAIL', 'category':'final_audit', 'detail':detail})
    check('failed_manifest_closed_and_five_hashes_current', m['publication_state']=='STAGED_REVALIDATION_FAILED' and m['publication_authorized'] is False and len(m['files'])==5 and all(audit.sha(audit.STAGING/f['staged_path'])==f['candidate_hash'] and f['after_hash'] is None for f in m['files']))
    check('no_identity_completion_or_history', not (audit.ROOT/'calibration/history'/f'{m["calibration_id"]}.yaml').exists() and not (audit.ROOT/'calibration/history'/f'{m["calibration_id"]}.complete').exists())
    # Negative-control manifests are in-memory only: do not invoke any publisher.
    def publication_preflight_allowed(manifest):
        return manifest.get('publication_authorized') is True and manifest.get('publication_state')=='STAGED_VALIDATED_AWAITING_AUTHORIZATION' and not audit.base_drift(manifest)
    check('unauthorized_publication_preflight_denied', not publication_preflight_allowed(m), 'Audit predicate only, not certification of the existing publisher implementation.')
    drifted = copy.deepcopy(m)
    drifted['base_hashes']['character/identity.yaml'] = '0'*64
    check('base_hash_drift_negative_control', bool(audit.base_drift(drifted)))
    before = json.loads((h/'protected-before.json').read_text(encoding='utf-8'))
    after = audit.protected()
    check('final_protected_hashes', before==after, {'count':len(before)})
    audit.json_save(h/'protected-after.json', after)
    report['formal_hashes_unchanged'] = before==after
    report['primary_visual_inspection'] = {'face':'complete including chin', 'both_eyes':'complete', 'bangs':'retained', 'top_of_head_and_hair_origin':'retained', 'side_locks':'face-framing upper locks retained; lower ends intentionally cropped', 'hair_silhouette':'adequate for portrait WHO; insufficient full length/pink tips', 'outfit_leakage':'LOW: small collar and suspender/shoulder edge', 'expression_leakage':'HIGH: wide open mouth; accepted by user', 'alpha':'RGBA matches source region; 25.98% fully transparent pixels, not dominant', 'primary_suitability':'Accepted portrait WHO anchor only; Runtime safety not certified'}
    report['regression_summary'] = {'core':'PASS 26/26', 'identity':'PASS 3/3', 'runtime_existing':'PASS 15/15', 'expression_suite':'INCOMPLETE / fixture error', 'expression_baseline':baseline['status'], 'all_related_regressions':'FAIL: supplemental Expression baseline error and incomplete suite'}
    report['candidate_validator'] = 'FAIL'
    report['recommendation'] = 'NOT_READY_FOR_IDENTITY_PUBLICATION'
    report['final_audit_timestamp'] = audit.utc()
    audit.json_save(h/'offline-checks.json', checks)
    audit.json_save(report_path, report)
    md = h/'IDENTITY STAGING REVALIDATION REPORT.md'
    text = md.read_text(encoding='utf-8').replace('| expression-regression-tests | FAIL |', '| expression-regression-tests | INCOMPLETE (stopped) |')
    text += '\n## Final audit / interrupted-suite clarification\n\n'
    text += '- 核心 regression **PASS 26/26**，57.031 秒；Identity tests **PASS 3/3**；既有 Runtime tests **PASS 15/15**。新增 Runtime 验收检查失败，不能由旧测试 PASS 抵消。\n'
    text += '- 补充 Expression suite **INCOMPLETE**：fixture 把 `D:/learn` 当作 staging 并复制父目录，因此主动停止其具体测试进程；不是 timeout。停止前 baseline 已 ERROR。没有修复或删除原始 fixture。该中断可能留下本地临时 fixture 文件，不属于正式发布数据。\n'
    text += f'- 安全单跑 Expression baseline：**{baseline["status"]}**，{baseline["duration_seconds"]} 秒；完整 traceback 见 expression-baseline-only.json。相关回归不能整体宣称 PASS。\n'
    text += '- Legacy staging validator 的 PASS 是关闭最终失败状态前的浅层检查结果，不证明 schema/Runtime 兼容；最终综合 candidate validator **FAIL**。\n'
    text += '- Schema 阻断具体为：现有 candidate schema_version=2 却启用 generation permission（validator 要求 v3）；source_authority=user_attested_official 不在枚举中；三张资产缺 view_angle；crop 的 Asset roles=identity_reference 不在 evidence-role 枚举中。均未擅自修复。\n'
    text += '- Primary 视觉复查：脸、下巴、双眼、刘海、头顶/发根完整；保留面旁上段发束，下段/粉色发梢不足交由 Secondary；少量领口与吊带边缘，outfit LOW；张嘴表情 HIGH 已接受。RGBA / alpha 与母图区完全一致。\n'
    text += '- 最终再次确认 5 个 manifest candidate hashes 正确、after_hash 均 null、publication_authorized=false；正式 Identity History/completion 未创建；87 个保护文件 Hash 未变。\n'
    text += '- 未授权发布的检查只验证本次草案 gate，不宣称现有 publisher 已实现全部安全机制；没有调用 publisher。\n'
    md.write_text(text, encoding='utf-8')
    history_path = audit.STAGING/'history-draft.yaml'
    history = audit.load(history_path)
    history['primary_replacement']['final_audit'] = {'status':'FAIL', 'report':'primary-replacement/IDENTITY STAGING REVALIDATION REPORT.json', 'regression_summary':report['regression_summary'], 'visual_inspection':report['primary_visual_inspection'], 'publication_executed':False}
    audit.save(history_path, history)
    print(json.dumps({'final_protected_hashes':before==after, 'expression_baseline':baseline['status'], 'recommendation':report['recommendation']}))

if __name__=='__main__':
    main()
