"""Meaningful archive, persistence, grouping, export and HTTP contract checks."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from PIL import Image

from core import Archive, Conflict, artwork_key, digest_file, empty_review, markdown, validate_review
from server import Server


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Arco 审阅 test ')
        self.root = Path(self.temp.name)
        self.gallery = self.root / '作品'
        self.gallery.mkdir()
        self.external = self.root / '原始 图.jpg'
        Image.new('RGB', (40, 60), '#889977').save(self.external)
        external_hash = digest_file(self.external)
        rows = []
        self.expected = []
        for index, (batch, version, status, parent, day) in enumerate([
            ('主题 甲/2026-10-03_01', 1, '初稿', None, '2026-10-03'),
            ('主题 甲/2026-10-03_01', 2, '修改稿', 'output-0', '2026-10-06'),
            ('主题 乙/2026-10-04_01', 1, '失败稿', None, '2026-10-04'),
            ('历史 丙/2026-09-28_01', 1, '历史版本', None, '2026-10-01')]):
            directory = self.gallery / batch
            directory.mkdir(parents=True, exist_ok=True)
            image = directory / f'成图 v{version}.png'
            Image.new('RGB', (40, 60), (index * 50, 30, 60)).save(image)
            row = {'title': batch.split('/')[0], 'batch': batch, 'version': version, 'output_id': f'output-{index}',
                   'parent_output': parent, 'image': image.relative_to(self.gallery).as_posix(), 'sha256': digest_file(image),
                   'status': status, 'created_at': f'{day}T10:00:00+08:00', 'user_accepted': False,
                   'record': f'{batch}/生成记录/v{version:02}.json'}
            refs, selected = [], []
            if index != 3:
                # Both different aliases and a duplicate archived record of identical reference bytes.
                aliases = [f'reference-{index}'] + ([None] if index == 1 else [])
                for alias in aliases:
                    copy = directory / '原始参考' / f'v{version}_{len(refs)}.jpg'
                    copy.parent.mkdir(exist_ok=True)
                    copy.write_bytes(self.external.read_bytes())
                    refs.append({'reference_id': alias, 'source_path': str(self.external), 'sha256': external_hash,
                                 'copy_path': copy.relative_to(directory).as_posix(), 'role': 'style_reference'})
                    selected.append({'reference_id': alias, 'path': str(self.external), 'source_scope': 'external_how',
                                     'role': 'style_reference', 'duties': ['style_reference', 'pose_reference']})
            record = {'request': {'variant_id': 'casual-outfit'}, 'references': refs,
                      'result': {'selected_references': selected}}
            if index != 3:
                record['result']['invocation_plan'] = {'referenced_image_paths': [str(self.external)]}
            path = self.gallery / row['record']
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
            rows.append(row)
            self.expected.append(artwork_key(row['output_id'], row['sha256']))
        self.catalog = self.gallery / '.catalog.json'
        self.catalog.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        self.original_catalog = self.catalog.read_bytes()
        self.archive = Archive(self.root, self.root / '人评 数据')

    def tearDown(self):
        self.assertEqual(self.catalog.read_bytes(), self.original_catalog)
        self.temp.cleanup()

    def save(self, index, overall=None, **changes):
        review = empty_review()
        review['scores']['overall'] = overall
        review.update(changes)
        key = self.expected[index]
        revision = self.archive.store.all().get(key, {'revision': 0})['revision']
        return self.archive.save(key, review, revision)

    def test_all_versions_and_all_failed_fallback(self):
        result = self.archive.listing({'start': '2026-10-03'})
        self.assertEqual(result['scope_versions'], 3)
        self.assertEqual(result['total'], 2)
        self.assertIn(self.expected[2], result['keys'])
        self.assertIn(self.expected[1], result['keys'])
        self.assertNotIn(self.expected[0], result['keys'])
        self.assertEqual(self.archive.listing({'versions': 'all'})['total'], 4)

    def test_quick_classification_covers_all_versions_and_preserves_review(self):
        self.save(0, 5, decision='keep', notes='保留细节', directions=[{'text': '以后改光影', 'priority': 'medium'}])
        self.save(1, decision='discard')
        self.save(2, decision='repair')
        listing = self.archive.quick_listing()
        self.assertEqual(listing['total'], 4)
        self.assertEqual(listing['counts'], {'keep': 1, 'discard': 1, 'pending': 2})
        self.assertEqual(set(listing['keys']), {self.expected[2], self.expected[3]})
        self.assertEqual(len(self.archive.quick_listing('all')['keys']), 4)
        self.assertEqual(self.archive.quick_listing('keep')['keys'], [self.expected[0]])
        detail = self.archive.detail(self.expected[0])
        original = detail['review']
        changed = dict(original, decision='discard')
        saved = self.archive.save(detail['key'], changed, detail['revision'])
        self.assertEqual(saved['review']['scores']['overall'], 5)
        self.assertEqual(saved['review']['notes'], '保留细节')
        self.assertEqual(saved['review']['directions'], original['directions'])
        # Undo restores the previous review rather than inventing a score.
        restored = self.archive.save(detail['key'], original, saved['revision'])
        self.assertEqual(restored['review'], original)
        fresh = self.archive.detail(self.expected[3])
        saved = self.archive.save(fresh['key'], dict(fresh['review'], decision='keep'), fresh['revision'])
        self.assertEqual(saved['state'], 'reviewed')
        self.assertTrue(all(v is None for v in saved['review']['scores'].values()))
        undone = self.archive.save(fresh['key'], fresh['review'], saved['revision'])
        self.assertEqual(undone['state'], 'pending')
        with self.assertRaises(ValueError):
            self.archive.quick_listing('invalid')

    def test_archive_time_not_batch_time(self):
        result = self.archive.listing({'start': '2026-10-06'})
        self.assertEqual(result['keys'], [self.expected[1]])
        with self.assertRaises(ValueError):
            self.archive.listing({'start': '2026-10-07', 'end': '2026-10-03'})

    def test_score_boundaries(self):
        for value in (0, 6, 4.5, True, '5'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_review({'scores': {'overall': value}})
        for value in (None, 1, 5):
            self.assertEqual(validate_review({'scores': {'overall': value}})['scores']['overall'], value)

    def test_partial_review_and_viewing(self):
        self.archive.detail(self.expected[0])
        self.assertEqual(self.archive.store.all(), {})
        saved = self.save(0, notes='  想保留画风  ')
        self.assertEqual(saved['state'], 'reviewed')
        self.assertIsNone(saved['review']['scores']['overall'])
        self.assertEqual(self.archive.analysis({})['statistics']['unscored']['versions'], 4)
        cleared = self.save(0)
        self.assertEqual(cleared['state'], 'pending')
        self.assertEqual(self.save(0, deferred=True)['state'], 'deferred')

    def test_empty_direction_is_not_a_review(self):
        saved = self.save(0, directions=[{'text': ' ', 'priority': 'high'}])
        self.assertEqual(saved['state'], 'pending')

    def test_deferred_review_remains_reviewed_and_is_filterable(self):
        self.save(0, 4, deferred=True)
        result = self.archive.listing({'state': 'deferred'})
        self.assertEqual(result['keys'], [self.expected[0]])
        self.assertEqual(result['progress']['reviewed'], 1)
        self.assertEqual(result['progress']['deferred'], 1)

    def test_analysis_warns_about_changed_visual_evidence(self):
        self.save(0, 5)
        item = self.archive.get(self.expected[0])
        Image.new('RGB', (31, 33), 'purple').save(item['image_path'])
        ref = item['references'][0]
        Path(ref['path']).write_bytes(b'changed reference')
        packet = self.archive.analysis({})
        self.assertTrue(any('成图哈希变化' in w for w in packet['groups']['high'][0]['warnings']))
        self.assertTrue(any('参考哈希变化' in w for w in packet['references'][0]['warnings']))
        self.assertIn('成图哈希变化', markdown(packet))

    def test_filter_discovers_high_older_version(self):
        self.save(0, 5)
        result = self.archive.listing({'score': '5'})
        self.assertEqual(result['keys'], [self.expected[0]])

    def test_persistence_restart_refresh(self):
        self.save(0, 5, tags=['画风偏差'])
        self.archive.store.set_setting('session', {'key': self.expected[0]})
        restarted = Archive(self.root, self.root / '人评 数据')
        restarted.refresh()
        detail = restarted.detail(self.expected[0])
        self.assertEqual(detail['review']['scores']['overall'], 5)
        self.assertEqual(detail['revision'], 1)
        self.assertEqual(restarted.store.get_setting('session')['key'], self.expected[0])

    def test_failed_save_does_not_mutate_record(self):
        self.save(0, 2)
        with self.assertRaises(Conflict):
            self.archive.save(self.expected[0], {'scores': {'overall': 5}}, 0)
        self.assertEqual(self.archive.detail(self.expected[0])['review']['scores']['overall'], 2)
        with self.assertRaises(ValueError):
            self.archive.save(self.expected[0], {'scores': {'overall': 6}}, 1)
        self.assertEqual(self.archive.detail(self.expected[0])['revision'], 1)

    def test_changed_image_cannot_receive_old_hash_rating(self):
        item = self.archive.get(self.expected[0])
        Image.new('RGB', (31, 29), 'red').save(item['image_path'])
        self.assertFalse(self.archive.detail(self.expected[0])['image_integrity']['matches'])
        with self.assertRaises(Conflict):
            self.save(0, 5)
        self.assertEqual(self.archive.store.all(), {})

    def test_reference_copy_priority_and_drift(self):
        self.external.unlink()
        detail = self.archive.detail(self.expected[0])
        self.assertTrue(detail['references'][0]['archived_copy'])
        self.assertTrue(detail['references'][0]['integrity']['matches'])
        Path(detail['references'][0]['path']).write_bytes(b'changed')
        self.assertIn('参考哈希变化', self.archive.detail(self.expected[0])['references'][0]['warnings'][-1])

    def test_reference_missing_and_history(self):
        first = self.archive.get(self.expected[0])['references'][0]
        Path(first['path']).unlink()
        self.assertIn('参考图片缺失', self.archive.detail(self.expected[0])['references'][0]['warnings'])
        old = self.archive.detail(self.expected[3])
        self.assertTrue(any('调用证据不完整' in w for w in old['warnings']))
        self.assertIn('历史记录未保存参考', old['warnings'])

    def test_analysis_keeps_all_rated_versions_and_deduplicates_reference(self):
        self.save(0, 1)
        self.save(1, 5)
        packet = self.archive.analysis({'start': '2026-10-03'})
        self.assertEqual(packet['statistics']['high']['versions'], 1)
        self.assertEqual(packet['statistics']['low']['versions'], 1)
        self.assertEqual(len(packet['references']), 1)
        ref = packet['references'][0]
        self.assertEqual(ref['version_count'], 3)
        self.assertEqual(ref['chain_count'], 2)
        self.assertEqual(len(ref['groups']['high']), 1)
        self.assertEqual(len(ref['groups']['low']), 1)
        self.assertIn('reference-0', ref['aliases'])
        self.assertIn('reference-1', ref['aliases'])
        chain = self.expected[0]
        self.assertEqual(next(s for s in ref['initial'] if s['chain_key'] == chain)['score'], 1)
        self.assertEqual(next(s for s in ref['latest_scored'] if s['chain_key'] == chain)['score'], 5)
        self.assertTrue(next(s for s in ref['latest_scored'] if s['chain_key'] == chain)['is_revision'])

    def test_unscored_initial_is_not_inferred(self):
        self.save(1, 5)
        packet = self.archive.analysis({'start': '2026-10-06'})
        self.assertFalse(packet['stages']['initial'][0]['in_scope'])
        self.assertIsNone(packet['stages']['initial'][0]['score'])

    def test_thresholds_and_middle(self):
        for high, low in ((4, 4), (2, 4), (6, 1), (5, 0)):
            with self.assertRaises(ValueError):
                self.archive.analysis({'high': high, 'low': low})
        self.save(0, 4)
        self.save(1, 2)
        self.save(2, 3)
        packet = self.archive.analysis({})
        self.assertEqual([packet['statistics'][g]['versions'] for g in ('high', 'low', 'middle', 'unscored')], [1, 1, 1, 1])

    def test_modification_requirements_optional_and_priority(self):
        self.save(0, decision='repair')
        self.save(1, directions=[{'text': '修正鞋子', 'priority': 'high'}], decision='regenerate')
        packet = self.archive.modifications({})
        self.assertEqual(packet['items'][0]['key'], self.expected[1])
        self.assertTrue(packet['items'][1]['requirement_pending'])
        text = markdown(packet)
        self.assertIn('修改要求待补充', text)
        self.assertIn('高优先级：修正鞋子', text)
        self.assertIn(str(self.gallery), text)

    def test_markdown_analysis_has_paths_and_all_evidence(self):
        self.save(0, 5)
        packet = self.archive.analysis({})
        text = markdown(packet)
        self.assertIn('首次生成', text)
        self.assertIn('原始参考', text)
        self.assertIn(str(self.gallery), text)
        self.assertIn(self.expected[0], text)
        self.assertIn('全部命中作品', text)
        self.assertIn('未填总分', text)

    def test_backup_restore_preview_conflicts_and_unknown(self):
        self.save(0, 5)
        backup = self.archive.store.backup()
        fresh = Archive(self.root, self.root / '恢复 数据')
        result = fresh.store.restore(backup, fresh.items)
        self.assertEqual(result['new'], 1)
        self.assertEqual(fresh.store.all(), {})
        self.assertEqual(fresh.store.restore(backup, fresh.items, dry_run=False)['imported'], 1)
        self.assertEqual(fresh.store.restore(backup, fresh.items, dry_run=False)['unchanged'], 1)
        changed = json.loads(json.dumps(backup))
        changed['reviews'][0]['review']['scores']['overall'] = 2
        self.assertEqual(fresh.store.restore(changed, fresh.items, dry_run=False)['conflicts'], 1)
        self.assertEqual(fresh.detail(self.expected[0])['review']['scores']['overall'], 5)
        fresh.store.restore(changed, fresh.items, overwrite=True, dry_run=False)
        self.assertEqual(fresh.detail(self.expected[0])['review']['scores']['overall'], 2)
        self.assertEqual(fresh.store.restore(backup, {}, dry_run=False)['unknown'], 1)

    def test_restore_validates_whole_packet_before_write(self):
        self.save(0, 5)
        self.save(1, 3)
        backup = self.archive.store.backup()
        backup['reviews'][1]['review']['scores']['overall'] = 9
        fresh = Archive(self.root, self.root / '恢复 数据')
        with self.assertRaises(ValueError):
            fresh.store.restore(backup, fresh.items, dry_run=False)
        self.assertEqual(fresh.store.all(), {})

    def test_invalid_refresh_preserves_snapshot(self):
        self.catalog.write_text('invalid', encoding='utf-8')
        try:
            with self.assertRaises(ValueError):
                self.archive.refresh()
            self.assertEqual(len(self.archive.items), 4)
        finally:
            self.catalog.write_bytes(self.original_catalog)

    def test_http_media_save_exports_and_host(self):
        server = Server(self.archive, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        try:
            def request(method, url, data=None, headers=None):
                body = json.dumps(data) if data is not None else None
                connection.request(method, url, body, headers or {})
                response = connection.getresponse()
                return response.status, response.read(), response.getheaders()
            self.assertEqual(request('GET', '/')[0], 200)
            self.assertEqual(request('GET', '/api/bootstrap')[0], 200)
            with self.assertRaises(OSError):
                Server(self.archive, server.server_port)
            code, body, _ = request('GET', '/api/quick')
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body)['counts']['pending'], 4)
            self.assertEqual(request('GET', '/api/quick?bucket=invalid')[0], 400)
            key = self.expected[0]
            payload = {'review': {'scores': {'overall': 4}}, 'revision': 0}
            self.assertEqual(request('POST', f'/api/review/{key}', payload)[0], 403)
            headers = {'X-Arco-Token': server.token, 'Content-Type': 'application/json'}
            self.assertEqual(request('POST', f'/api/review/{key}', payload, headers)[0], 200)
            self.assertEqual(request('POST', f'/api/review/{key}', payload, headers)[0], 409)
            asset = self.archive.get(key)['image_asset']
            self.assertEqual(request('GET', f'/media/{asset}?size=thumb')[0], 200)
            self.assertEqual(request('GET', '/media/not-registered')[0], 404)
            self.assertEqual(request('GET', '/api/export?kind=analysis&format=md')[0], 200)
            code, body, _ = request('POST', '/api/export', {'kind': 'analysis', 'format': 'md', 'filters': {}}, headers)
            self.assertEqual(code, 200)
            exported = json.loads(body)
            self.assertTrue(Path(exported['path']).is_file())
            self.assertEqual(request('GET', exported['download_url'])[0], 200)
            self.assertEqual(request('GET', '/exports/../../reviews.sqlite3')[0], 404)
            self.assertEqual(request('GET', '/api/export?kind=analysis&high=2&low=4')[0], 400)
            self.assertEqual(request('GET', '/health', headers={'Host': 'external.example'})[0], 403)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
