"""Local, deterministic crop comparison. Does not update the candidate registry."""
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGING = HERE.parent
ROOT = STAGING.parents[2]
PARENT = STAGING / 'candidate-root/assets/arco/identity/p01-full.png'
EXPECTED = 'bddba1d7b1bed2c21572892003ac50dc6c2340d53e8262a56b6db69b16cf1f86'

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def pixels(path, box=None):
    cmd = ['ffmpeg', '-v', 'error', '-i', str(path)]
    if box:
        x, y, w, h = box
        cmd += ['-vf', f'crop={w}:{h}:{x}:{y}:exact=1']
    return subprocess.check_output(cmd + ['-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba', 'pipe:1'])

def protected():
    files = []
    for rel in ('character', 'variants', 'assets/arco', 'calibration/history'):
        files.extend((ROOT / rel).rglob('*'))
    files.extend((STAGING / 'candidate-root').rglob('*'))
    files.extend([STAGING/'publish-manifest.yaml', STAGING/'history-draft.yaml', STAGING/'calibration-lock.yaml'])
    return {str(p): digest(p) for p in files if p.is_file()}

def main():
    assert digest(PARENT) == EXPECTED
    before = protected()
    records = []
    for cid, box in [('A', [680, 0, 760, 640]), ('B', [560, 0, 1000, 760]), ('C', [400, 0, 1280, 840])]:
        x, y, w, h = box
        assert 0 <= x < x+w <= 2207 and 0 <= y < y+h <= 3813
        path = HERE / f'p01-candidate-{cid.lower()}.png'
        assert not path.exists(), 'Never overwrite a comparison candidate'
        subprocess.run(['ffmpeg', '-n', '-v', 'error', '-i', str(PARENT), '-vf', f'crop={w}:{h}:{x}:{y}:exact=1', '-frames:v', '1', '-pix_fmt', 'rgba', str(path)], check=True)
        expected = pixels(PARENT, box)
        actual = pixels(path)
        assert len(actual) == w*h*4 and actual == expected
        records.append({'candidate_id': f'identity-p01-crop-candidate-{cid.lower()}', 'path': str(path), 'crop_box_px': box, 'dimensions': [w,h], 'sha256': digest(path), 'parent_asset_id':'identity-p01', 'parent_sha256':EXPECTED, 'source_family_id':'arco-official-standing-art-system-01', 'source_group_id':'arco-standing-open-arms-oblique-01', 'independent_source_family_increment':0, 'decoded_rgba_equal_to_parent_region':True, 'alpha_equal_to_parent_region':True, 'rgba_pixel_sha256':hashlib.sha256(actual).hexdigest(), 'transparent_pixel_fraction':round(actual[3::4].count(0)/(w*h),4), 'proposed_preferred_for':['portrait'], 'selection_status':'AWAITING_USER_SELECTION'})
    after = protected()
    assert before == after, 'Protected content changed'
    (HERE/'verification.json').write_text(json.dumps({'parent_dimensions':[2207,3813], 'parent_sha256':EXPECTED, 'candidates':records, 'protected_file_count':len(before), 'protected_hashes_before':before, 'protected_hashes_after':after, 'protected_files_unchanged':True, 'publication_authorized':False}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
