"""Validate the approved Identity body-proportion calibration staging."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import yaml

EXPECTED = {"identity-body-c07", "identity-body-c13", "identity-body-c14"}
P01_SHA = "386f95c28441a1adf4900cfc3ce52e1c52f0ce7435376bd4576dd9cc32976414"

def sha(p):
    h = hashlib.sha256(); h.update(p.read_bytes()); return h.hexdigest()
def load(p): return yaml.safe_load(Path(p).read_text(encoding="utf-8"))
def validate(root, staging):
    errors=[]; root=Path(root); staging=Path(staging); c=staging/'candidate-root'
    i=load(c/'character/identity.yaml'); a=load(c/'character/assets.yaml'); f=load(root/'character/assets.yaml')
    fact=next((x for x in i.get('facts',[]) if x.get('field_id')=='body.chest_proportion'), {})
    def req(ok,msg):
        if not ok: errors.append(msg)
    req(i.get('revision')==2, 'Identity candidate revision must be 2')
    req(a.get('revision')==5, 'Asset Index candidate revision must be 5')
    req(fact.get('value')=='small-to-modest' and fact.get('status')=='UNCERTAIN', 'chest fact value/status invalid')
    req(set(fact.get('evidence_ids',[]))==EXPECTED|{'identity-p01','identity-p03'}, 'chest evidence closure invalid')
    by={x['asset_id']:x for x in a['assets']}; formal={x['asset_id']:x for x in f['assets']}
    req(set(by)-set(formal)==EXPECTED, 'candidate asset delta is not exactly C07/C13/C14')
    for aid in EXPECTED:
        x=by.get(aid,{}); p=c/str(x.get('path',''))
        req(x.get('roles')==['body_evidence'] and x.get('asset_type')=='body_base', f'{aid} role/type invalid')
        req(x.get('can_be_generation_reference') is False, f'{aid} generation permission invalid')
        req(p.is_file() and sha(p)==x.get('sha256'), f'{aid} file/hash invalid')
        req(x.get('source_family_id')=='arco-official-standing-art-system-01', f'{aid} source family invalid')
    req(by['identity-p01-crop']['sha256']==P01_SHA and formal['identity-p01-crop']['sha256']==P01_SHA, 'P01 crop SHA changed')
    manifest=load(staging/'publish-manifest.yaml'); lock=load(staging/'calibration-lock.yaml'); history=load(staging/'history-draft.yaml')
    req(manifest.get('publication_authorized') is False and manifest.get('publication_executed') is False, 'publication flags invalid')
    req(manifest.get('image_generation_called') is False and manifest.get('remote_upload') is False, 'generation/upload flags invalid')
    req(lock.get('state')=='staged_validated_awaiting_authorization', 'calibration lock state invalid')
    req(history.get('user_confirmed') is True and history.get('publication_not_executed') is True, 'history confirmation flags invalid')
    return {'status':'PASS' if not errors else 'FAIL','calibration_id':manifest.get('calibration_id'),'errors':errors,'publication_executed':False,'image_generation_called':False,'remote_upload':False}
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]); p.add_argument('--staging',type=Path,required=True); p.add_argument('--json',action='store_true'); x=validate(p.parse_args().root.resolve(),p.parse_args().staging.resolve()); print(json.dumps(x,ensure_ascii=False,indent=2) if p.parse_args().json else f"{x['status']}: {len(x['errors'])} errors"); raise SystemExit(0 if x['status']=='PASS' else 1)
