"""Validate explicit calibration edits of published outfit reference images.

This lane does not invoke ordinary production, change Identity, or publish.
The host freezes a concrete, authorized image edit and records its inspection.
"""
from __future__ import annotations
import json
from pathlib import Path
from reference_analysis import digest, file_hash, fail
from reference_runtime import validate_generation_reference_input
from preparation_support import load

def validate_reference_correction(plan: dict, *, root: Path, preview_path: Path) -> dict:
    root = root.resolve()
    preview_path = preview_path.resolve()
    if not preview_path.is_relative_to(root / 'output'):
        fail('REFERENCE_CORRECTION_INVALID', 'The retained correction preview must be in the workspace output area.')
    preview = json.loads(preview_path.read_text(encoding='utf-8'))
    if preview.get('preview_sha256') != digest({k:v for k,v in preview.items() if k!='preview_sha256'}):
        fail('REFERENCE_CORRECTION_STALE', 'Correction preview changed.')
    if preview.get('purpose') != 'published_reference_correction' or preview.get('authorization',{}).get('user_confirmed') is not True:
        fail('REFERENCE_CORRECTION_CONFIRMATION_REQUIRED', 'Explicit reference-edit authorization is required.')
    if not preview['authorization'].get('user_message'):
        fail('REFERENCE_CORRECTION_CONFIRMATION_REQUIRED', 'Retain the actual user instruction.')
    if plan != preview.get('invocation_plan') or plan.get('purpose') != preview['purpose']:
        fail('REFERENCE_CORRECTION_STALE', 'Only the exact frozen invocation may execute.')
    if not 0 <= plan.get('repair_number',-1) <= 2:
        fail('AUTOMATIC_REPAIR_LIMIT', 'At most two corrections per image.')
    if plan['repair_number'] and preview.get('prior_review',{}).get('decision') != 'FAIL':
        fail('AUTOMATIC_REPAIR_REVIEW_REQUIRED', 'A further correction requires a failed visual inspection.')
    for path, expected in preview['bindings'].items():
        p = Path(path)
        if not p.is_file() or file_hash(p) != expected:
            fail('REFERENCE_CORRECTION_STALE', 'An input or protected formal file changed: '+path)
    references = plan.get('references',[])
    if not 1 <= len(references) <= 5 or len(references) != len(plan.get('referenced_image_paths',[])):
        fail('REFERENCE_LIMIT_EXCEEDED', 'Correction inputs must be explicit, at most five.')
    registry = {a['asset_id']:a for a in load(root/'character/assets.yaml')['assets']}
    for ref,path in zip(references,plan['referenced_image_paths'],strict=True):
        if path != ref['path'] or file_hash(path) != ref['sha256']:
            fail('REFERENCE_CORRECTION_STALE', 'Reference image binding changed.')
        validate_generation_reference_input(ref,root=root)
        if ref['usage']=='accepted_corrected_primary':
            review=preview.get('primary_review',{})
            if review.get('decision')!='PASS' or review.get('output_sha256')!=ref['sha256']:
                fail('REFERENCE_CORRECTION_REVIEW_REQUIRED','Use a visually accepted corrected main only.')
        else:
            asset=registry.get(ref.get('asset_id'),{})
            if asset.get('sha256')!=ref['sha256'] or str((root/asset.get('path','')).resolve())!=str(Path(path).resolve()):
                fail('REFERENCE_CORRECTION_STALE','Managed reference does not match its published asset.')
            if asset.get('can_be_generation_reference') is not True:
                fail('UNPUBLISHED_ASSET','The edit target and identity baseline must be approved published inputs.')
    return {'prompt':plan['prompt'],'referenced_image_paths':plan['referenced_image_paths']}
