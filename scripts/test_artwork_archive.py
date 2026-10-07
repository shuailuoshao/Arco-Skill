from dataclasses import dataclass
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from artwork_archive import archive_result, artwork_title, file_hash, sync_review


@dataclass(frozen=True)
class Result:
    output_path: Path
    output_id: str
    prompt: str = '确认的提示词'
    parent_output: str | None = None
    reset_triggered_from_output: str | None = None
    selected_references: tuple = ()
    archive_image_path: Path | None = None
    archive_record_path: Path | None = None
    archive_error: str | None = None
    visual_review_status: str = 'unchecked'

    def as_dict(self):
        return {'output_id': self.output_id, 'output_path': str(self.output_path),
                'visual_review_status': self.visual_review_status}


class ArchiveTests(unittest.TestCase):
    def test_names_references_versions_and_original_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            image=root/'exec-code.png'; image.write_bytes(b'unchanged pixels')
            ref=root/'参考.jpg'; ref.write_bytes(b'original reference')
            result=Result(image,'stable-provider-id', selected_references=(
                {'path':str(ref),'source_scope':'external_how','role':'style_reference'},
                {'path':str(root/'missing.png'),'source_scope':'managed_arco'}))
            first=archive_result(result, {'artwork_title':'楼梯/回眸','variant_id':'casual-outfit'},root,created_on='2026-10-01')
            self.assertIsNone(first.archive_error)
            self.assertEqual(first.output_id,'stable-provider-id')
            self.assertEqual(first.output_path,image)
            self.assertEqual(file_hash(image),file_hash(first.archive_image_path))
            data=json.loads(first.archive_record_path.read_text(encoding='utf-8'))
            self.assertTrue(data['references'][1]['missing'])
            self.assertFalse(data['artwork']['user_accepted'])
            second=archive_result(Result(image,'second-provider-id'),{'base_prompt':'调整面部'},root,{'output_id':first.output_id})
            self.assertEqual(first.archive_image_path.parent, second.archive_image_path.parent)
            self.assertIn('v02',second.archive_image_path.name)
            independent=archive_result(result,{'artwork_title':'楼梯/回眸'},root,created_on='2026-10-01')
            self.assertEqual(independent.archive_image_path.parent.name,'2026-10-01_02')

    def test_copy_failure_preserves_provider_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); image=root/'image.png';image.write_bytes(b'pixels')
            with patch('artwork_archive.shutil.copy2',side_effect=OSError('disk full')):
                result=archive_result(Result(image,'id'),{},root)
            self.assertIsNone(result.archive_image_path)
            self.assertIn('disk full',result.archive_error)
            self.assertEqual(image.read_bytes(),b'pixels')
            self.assertFalse((root/'作品/.archive-lock').exists())

    def test_historical_provider_alias_keeps_revision_in_original_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);image=root/'old-friendly.png';image.write_bytes(b'pixels')
            first=archive_result(Result(image,str(image)),{'artwork_title':'旧作品'},root)
            old=str(root/'retired/exec-code.png')
            report=root/'archive/整理记录/路径映射.json';report.parent.mkdir(parents=True)
            report.write_text(json.dumps({old:str(first.archive_image_path)}),encoding='utf-8')
            second=archive_result(Result(image,'new-id'),{'base_prompt':'调整面部'},root,{'output_id':old})
            self.assertEqual(second.archive_image_path.parent,first.archive_image_path.parent)
            self.assertIn('v02',second.archive_image_path.name)

    def test_review_failure_is_idempotent_and_not_human_acceptance(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);image=root/'image.png';image.write_bytes(b'pixels')
            result=archive_result(Result(image,'id'),{},root)
            result=sync_review(replace(result,visual_review_status='degraded'))
            twice=sync_review(result)
            self.assertEqual(twice.archive_image_path,result.archive_image_path)
            self.assertEqual(result.archive_image_path.parent.name,'失败稿')
            self.assertTrue(result.archive_image_path.is_file())
            data=json.loads(result.archive_record_path.read_text(encoding='utf-8'))
            self.assertFalse(data['artwork']['user_accepted'])
            self.assertEqual(data['artwork']['status'],'失败稿')

    def test_busy_writer_fails_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);image=root/'image.png';image.write_bytes(b'pixels')
            (root/'作品/.archive-lock').mkdir(parents=True)
            result=archive_result(Result(image,'id'),{},root)
            self.assertIsNotNone(result.archive_error)
            self.assertTrue((root/'作品/.archive-lock').exists())

    def test_title_comes_from_confirmed_text_or_user_name(self):
        self.assertEqual(artwork_title({'base_prompt':'阿尔可在楼梯回眸'}),'楼梯回眸')
        self.assertEqual(artwork_title({'artwork_title':'我的黄昏'}),'我的黄昏')
        self.assertNotIn('/',artwork_title({'artwork_title':'../con'}))


if __name__=='__main__': unittest.main()
