#!/usr/bin/env python3
"""Target-scoped guard for calibration and formal write entrypoints."""
from __future__ import annotations
import argparse
from pathlib import Path
import yaml
ACTIVE={"STAGED_VALIDATED_AWAITING_AUTHORIZATION","STAGED_REVALIDATION_FAILED","PUBLICATION_IN_PROGRESS","RECOVERY_REQUIRED","STALE_STAGING"}
READ_ONLY_OPERATIONS={"offline-revalidation","formal-validation","runtime-planning","prompt-only-planning"}
def normalize_state(value): return str(value or '').strip().upper()
def conflicts(root:Path,targets:set[str],operation:str):
    if operation in READ_ONLY_OPERATIONS:
        return []
    found=[]
    for path in (root/'calibration/staging').glob('*/calibration-lock.yaml'):
        data=yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        state=normalize_state(data.get('state'))
        if state not in ACTIVE: continue
        locked=set(data.get('targets',[]))
        if operation in {'write','publication','recovery'} or locked&targets:
            found.append({'calibration_id':data.get('calibration_id'),'state':state,'overlap':sorted(locked&targets),'path':str(path)})
    return found
def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); p.add_argument('--operation',choices=['begin-calibration','write','publication','recovery',*sorted(READ_ONLY_OPERATIONS)],required=True); p.add_argument('--target',action='append',default=[]); a=p.parse_args(); found=conflicts(a.root.resolve(),set(a.target),a.operation)
    for x in found: print(f"BLOCKED {x['calibration_id']} {x['state']} overlap={','.join(x['overlap']) or '(global write guard)'}")
    return 2 if found else 0
if __name__=='__main__': raise SystemExit(main())
