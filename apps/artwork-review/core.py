"""Read-only archive adapter and independent human-review store."""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import threading

SCORES = {'overall': '总体满意度', 'identity': '角色一致性', 'outfit': '服装准确性',
          'pose_expression': '姿态表情', 'style': '画风还原',
          'composition': '构图场景', 'quality': '画面瑕疵'}
DECISIONS = {'keep': '保留', 'repair': '局部修改', 'regenerate': '重新生成', 'discard': '弃用'}
VARIANTS = {'casual-outfit': '常服', 'school-uniform': '校服', 'maid-outfit': '女仆',
            'swimwear': '泳装', 'swimsuit': '泳装'}
DUTIES = {'style_reference': '画风', 'composition_reference': '构图', 'pose_reference': '姿态',
          'scene_reference': '场景', 'lighting_reference': '光影', 'expression_reference': '表情',
          'identity_reference': '角色', 'outfit_reference': '服装', 'face_reference': '脸部'}
DEFAULT_START = '2026-10-03'


class Conflict(ValueError):
    pass


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')


def digest_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def normalize_path(path):
    return str(path or '').replace('\\', '/').rstrip('/').casefold()


def artwork_key(output_id, sha256):
    return hashlib.sha256((output_id + '\0' + sha256).encode('utf-8')).hexdigest()


def empty_review():
    return {'scores': {key: None for key in SCORES}, 'decision': None, 'tags': [],
            'notes': '', 'directions': [], 'deferred': False}


def validate_review(value):
    if not isinstance(value, dict):
        raise ValueError('人评必须是对象')
    result = empty_review()
    scores = value.get('scores', {})
    if not isinstance(scores, dict) or set(scores) - set(SCORES):
        raise ValueError('评分维度无效')
    for key, score in scores.items():
        if score is not None and (type(score) is not int or not 1 <= score <= 5):
            raise ValueError('评分必须为空或 1–5 的整数')
        result['scores'][key] = score
    decision = value.get('decision')
    if decision is not None and decision not in DECISIONS:
        raise ValueError('人工结论无效')
    result['decision'] = decision
    tags = value.get('tags', [])
    if not isinstance(tags, list) or len(tags) > 40 or any(not isinstance(t, str) or len(t) > 80 for t in tags):
        raise ValueError('问题标签无效')
    result['tags'] = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
    notes = value.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 20000:
        raise ValueError('备注过长或格式无效')
    result['notes'] = notes.strip()
    directions = value.get('directions', [])
    if not isinstance(directions, list) or len(directions) > 100:
        raise ValueError('修改方向无效')
    for entry in directions:
        if not isinstance(entry, dict) or entry.get('priority', 'medium') not in ('high', 'medium', 'low'):
            raise ValueError('修改优先级无效')
        text = entry.get('text', '')
        if not isinstance(text, str) or len(text) > 10000:
            raise ValueError('修改说明无效')
        # An untouched, empty direction is not a meaningful human review.
        if text.strip():
            result['directions'].append({'text': text.strip(), 'priority': entry.get('priority', 'medium')})
    if type(value.get('deferred', False)) is not bool:
        raise ValueError('暂缓状态无效')
    result['deferred'] = value.get('deferred', False)
    return result


def review_state(review):
    if (any(v is not None for v in review['scores'].values()) or review['decision'] or
            review['tags'] or review['notes'] or review['directions']):
        return 'reviewed'
    return 'deferred' if review['deferred'] else 'pending'


class ReviewStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('CREATE TABLE IF NOT EXISTS reviews (key TEXT PRIMARY KEY, output_id TEXT NOT NULL, '
                         'sha256 TEXT NOT NULL, review TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def unpack(row):
        if row is None:
            return {'review': empty_review(), 'revision': 0, 'updated_at': None, 'state': 'pending'}
        review = json.loads(row['review'])
        return {'review': review, 'revision': row['revision'], 'updated_at': row['updated_at'],
                'state': review_state(review)}

    def all(self):
        with self.connect() as conn:
            return {r['key']: self.unpack(r) for r in conn.execute('SELECT * FROM reviews')}

    def save(self, item, value, revision):
        review = validate_review(value)
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old = conn.execute('SELECT * FROM reviews WHERE key=?', (item['key'],)).fetchone()
            current = old['revision'] if old else 0
            if type(revision) is not int or revision != current:
                raise Conflict('此图人评已在另一窗口更新；草稿已保留，请先处理版本冲突')
            conn.execute('INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,?)',
                         (item['key'], item['output_id'], item['sha256'], json.dumps(review, ensure_ascii=False),
                          current + 1, now()))
            return self.unpack(conn.execute('SELECT * FROM reviews WHERE key=?', (item['key'],)).fetchone())

    def set_setting(self, key, value):
        with self.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def get_setting(self, key):
        with self.connect() as conn:
            row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            return json.loads(row['value']) if row else None

    def backup(self):
        with self.connect() as conn:
            rows = [dict(r) for r in conn.execute('SELECT * FROM reviews ORDER BY key')]
        for row in rows:
            row['review'] = json.loads(row['review'])
        return {'schema_version': 1, 'kind': 'arco-human-review-backup', 'exported_at': now(), 'reviews': rows}

    def restore(self, packet, items, overwrite=False, dry_run=True):
        if (not isinstance(packet, dict) or packet.get('kind') != 'arco-human-review-backup' or
                packet.get('schema_version') != 1 or not isinstance(packet.get('reviews'), list)):
            raise ValueError('请选择此软件导出的 JSON 人评备份')
        prepared = []
        seen = set()
        stats = {'new': 0, 'conflicts': 0, 'unchanged': 0, 'unknown': 0, 'imported': 0}
        # Validate the whole packet before making any writes.
        for row in packet['reviews']:
            if not isinstance(row, dict) or not isinstance(row.get('output_id'), str) or not isinstance(row.get('sha256'), str):
                raise ValueError('备份条目格式无效')
            key = artwork_key(row['output_id'], row['sha256'])
            if row.get('key') != key or key in seen:
                raise ValueError('备份主键错误或重复')
            seen.add(key)
            review = validate_review(row.get('review'))
            if key not in items:
                stats['unknown'] += 1
                continue
            prepared.append((key, row, review))
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for key, row, review in prepared:
                old = conn.execute('SELECT * FROM reviews WHERE key=?', (key,)).fetchone()
                if old and json.loads(old['review']) == review:
                    stats['unchanged'] += 1
                    continue
                bucket = 'conflicts' if old else 'new'
                stats[bucket] += 1
                if not dry_run and (not old or overwrite):
                    conn.execute('INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,?)',
                                 (key, row['output_id'], row['sha256'], json.dumps(review, ensure_ascii=False),
                                  old['revision'] + 1 if old else 1, now()))
                    stats['imported'] += 1
        return stats


class Archive:
    def __init__(self, root, data_dir):
        self.root = Path(root).resolve()
        self.gallery = self.root / '作品'
        self.data_dir = Path(data_dir).resolve()
        self.store = ReviewStore(self.data_dir / 'reviews.sqlite3')
        self.lock = threading.RLock()
        self.hash_lock = threading.Lock()
        self.hashes = {}
        scripts = str(Path(__file__).resolve().parents[2] / 'scripts')
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from archive_paths import relocate
        self.relocate = relocate
        self.refresh()

    def resolve(self, source):
        return self.relocate(source, root=self.root).resolve()

    def refresh(self):
        # Publish only a fully constructed snapshot, preserving the last good one on failure.
        catalog = json.loads((self.gallery / '.catalog.json').read_text(encoding='utf-8-sig'))
        if not isinstance(catalog, list):
            raise ValueError('作品登记表格式无效')
        items, assets, problems = {}, {}, []
        by_output = {normalize_path(r['output_id']): r for r in catalog}

        def register(path, expected):
            asset_id = hashlib.sha256((str(path) + '\0' + str(expected)).encode('utf-8')).hexdigest()
            assets[asset_id] = {'path': str(path), 'expected': expected}
            return asset_id

        for row in catalog:
            key = artwork_key(row['output_id'], row['sha256'])
            if key in items:
                raise ValueError('作品登记表包含重复版本')
            record_path = (self.gallery / row['record']).resolve()
            image_path = (self.gallery / row['image']).resolve()
            if not record_path.is_relative_to(self.gallery) or not image_path.is_relative_to(self.gallery):
                raise ValueError('归档记录路径超出作品目录')
            warnings = []
            try:
                record = json.loads(record_path.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError) as exc:
                record = {}
                warnings.append(f'生成记录无法读取：{exc}')
                problems.append(f'{row["title"]} v{row["version"]} 记录无法读取')
            request, result = record.get('request', {}), record.get('result', {})
            invocation = result.get('invocation_plan') or {}
            invoked = invocation.get('referenced_image_paths')
            if not isinstance(invoked, list):
                invoked = None
                warnings.append('调用证据不完整：记录未保存实际输入路径')
            invoked_paths = {normalize_path(p) for p in invoked or []}
            selected = result.get('selected_references') or []
            archived = record.get('references') or []
            if not archived:
                warnings.append('历史记录未保存参考')
            external_ids = {r.get('reference_id') for r in request.get('external_references', [])}
            references = []
            for ref in archived:
                rid, source = ref.get('reference_id'), ref.get('source_path', '')
                matches = [s for s in selected if rid and rid in (s.get('reference_id'), s.get('asset_id'))]
                if not matches:
                    matches = [s for s in selected if normalize_path(s.get('path')) == normalize_path(source)]
                scoped = next((s for s in matches if s.get('source_scope')), matches[0] if matches else {})
                scope = scoped.get('source_scope', '')
                if not scope and (rid in external_ids or ref.get('copy_path')):
                    scope = 'external_how'
                copy = ref.get('copy_path')
                source_path = self.resolve(source) if source else None
                parent = by_output.get(normalize_path(source))
                if parent:
                    source_path = (self.gallery / parent['image']).resolve()
                ref_warnings = []
                if copy:
                    copy_path = (self.gallery / row['batch'] / copy).resolve()
                    if not copy_path.is_relative_to(self.gallery):
                        raise ValueError('参考副本路径超出作品目录')
                    if copy_path.is_file():
                        path = copy_path
                    else:
                        path = source_path
                        ref_warnings.append('归档参考副本缺失；当前展示源文件，需核对哈希')
                else:
                    path = source_path
                duties = list(dict.fromkeys(d for s in matches for d in s.get('duties', [])))
                if not duties and ref.get('role'):
                    duties = [ref['role']]
                aliases = list(dict.fromkeys(s.get('reference_id') or s.get('asset_id') for s in matches
                                             if s.get('reference_id') or s.get('asset_id')))
                if rid and rid not in aliases:
                    aliases.append(rid)
                references.append({'reference_id': rid, 'aliases': aliases, 'sha256': ref.get('sha256'),
                                   'source_path': source, 'path': str(path) if path else '',
                                   'archived_copy': bool(copy and path and path == copy_path),
                                   'asset_id': register(path, ref.get('sha256')) if path else None,
                                   'scope': scope, 'role': ref.get('role'), 'duties': duties,
                                   'duty_labels': [DUTIES.get(d, d) for d in duties],
                                   'inherit': list(dict.fromkeys(v for s in matches for v in s.get('inherit', []))),
                                   'do_not_inherit': list(dict.fromkeys(v for s in matches for v in s.get('do_not_inherit', []))),
                                   'sent': None if invoked is None else (normalize_path(source) in invoked_paths),
                                   'warnings': ref_warnings})
            item = dict(row, key=key, image_path=str(image_path), record_path=str(record_path),
                        image_asset=register(image_path, row['sha256']), warnings=warnings,
                        variant_id=request.get('variant_id', ''),
                        variant=VARIANTS.get(request.get('variant_id'), request.get('variant_id') or '未记录'),
                        references=references, prompt=request.get('base_prompt', ''),
                        machine_review=result.get('visual_review_status', ''), parent_key=None,
                        chain_key=key, catalog_order=len(items))
            items[key] = item
        outputs = {normalize_path(item['output_id']): item['key'] for item in items.values()}
        for item in items.values():
            parent = normalize_path(item.get('parent_output'))
            item['parent_key'] = outputs.get(parent)
            if parent and not item['parent_key']:
                item['warnings'].append('父版本未登记，生成链证据不完整')
            visited, current = set(), item
            while current['parent_key']:
                if current['key'] in visited:
                    item['warnings'].append('父版本关系成环，生成链证据不完整')
                    break
                visited.add(current['key'])
                current = items[current['parent_key']]
            item['chain_key'] = current['key']
        with self.lock:
            self.items, self.assets, self.problems = items, assets, problems
            self.refreshed_at = now()
        return {'versions': len(items), 'refreshed_at': self.refreshed_at, 'problems': problems}

    def integrity(self, asset_id):
        with self.lock:
            asset = self.assets.get(asset_id)
        if not asset:
            raise KeyError('图片未登记')
        path = Path(asset['path'])
        try:
            stat = path.stat()
            signature = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            with self.hash_lock:
                actual = self.hashes.get(signature)
            if actual is None:
                actual = digest_file(path)
                with self.hash_lock:
                    self.hashes[signature] = actual
            return dict(asset, exists=True, actual_sha256=actual,
                        matches=None if not asset['expected'] else actual == asset['expected'])
        except OSError:
            return dict(asset, exists=False, actual_sha256=None, matches=False)

    def get(self, key):
        with self.lock:
            if key not in self.items:
                raise KeyError('作品版本未找到，请刷新归档')
            return self.items[key]

    @staticmethod
    def date_scope(items, params):
        start, end = params.get('start', ''), params.get('end', '')
        for date in (start, end):
            if date:
                datetime.strptime(date, '%Y-%m-%d')
        if start and end and start > end:
            raise ValueError('起始日期不能晚于结束日期')
        return [i for i in items if (not start or i['created_at'][:10] >= start)
                and (not end or i['created_at'][:10] <= end)]

    def rows(self):
        saved = self.store.all()
        with self.lock:
            return [dict(i, **saved.get(i['key'], self.store.unpack(None))) for i in self.items.values()]

    @staticmethod
    def summary(item):
        fields = ('key', 'title', 'batch', 'version', 'status', 'created_at', 'variant', 'variant_id',
                  'image_asset', 'parent_key', 'chain_key', 'review', 'revision', 'state', 'updated_at', 'warnings')
        return {k: item[k] for k in fields}

    def listing(self, params):
        scoped = self.date_scope(self.rows(), params)
        progress = dict(Counter(i['state'] for i in scoped))
        # Deferred is a queue flag: an already reviewed item can also be deferred.
        progress['deferred'] = sum(i['review']['deferred'] for i in scoped)
        rows = scoped
        query = params.get('q', '').strip().casefold()
        if query:
            rows = [i for i in rows if query in (i['title'] + ' ' + i['batch']).casefold()]
        for param, field in (('variant', 'variant_id'), ('status', 'status'), ('state', 'state')):
            if params.get(param):
                rows = [i for i in rows if (i['review']['deferred'] if param == 'state' and params[param] == 'deferred'
                                           else i[field] == params[param])]
        if params.get('score'):
            score = params['score']
            rows = [i for i in rows if (i['review']['scores']['overall'] is None if score == 'unscored'
                                       else i['review']['scores']['overall'] == int(score))]
        matched_count = len(rows)
        groups = defaultdict(list)
        # Apply review filters before collapsing: a rated older version remains discoverable.
        for item in rows:
            groups[item['batch']].append(item)
        if params.get('versions', 'latest') != 'all':
            rows = []
            for versions in groups.values():
                candidates = [i for i in versions if i['status'] != '失败稿'] or versions
                rows.append(max(candidates, key=lambda i: (i['version'], i['created_at'], i['catalog_order'])))
        rows.sort(key=lambda i: (i['created_at'], i['catalog_order']), reverse=True)
        offset = max(0, int(params.get('offset', 0)))
        limit = min(100, max(1, int(params.get('limit', 24))))
        return {'items': [dict(self.summary(i), version_count=len(groups[i['batch']])) for i in rows[offset:offset+limit]],
                'keys': [i['key'] for i in rows], 'total': len(rows), 'matched_versions': matched_count,
                'scope_versions': len(scoped), 'progress': progress, 'scored': sum(i['review']['scores']['overall'] is not None for i in scoped)}

    def quick_listing(self, bucket='pending'):
        """All archived versions, independently of the detailed gallery filters."""
        if bucket not in ('pending', 'keep', 'discard', 'all'):
            raise ValueError('快速筛选分组无效')
        rows = self.rows()
        counts = {'keep': 0, 'discard': 0, 'pending': 0}
        for item in rows:
            decision = item['review']['decision']
            counts[decision if decision in ('keep', 'discard') else 'pending'] += 1
        selected = [i for i in rows if bucket == 'all' or
                    (i['review']['decision'] == bucket if bucket != 'pending' else
                     i['review']['decision'] not in ('keep', 'discard'))]
        selected.sort(key=lambda i: (i['created_at'], i['catalog_order']), reverse=True)
        return {'keys': [i['key'] for i in selected], 'counts': counts, 'total': len(rows), 'bucket': bucket}

    def detail(self, key):
        item = self.get(key)
        saved = self.store.all().get(key, self.store.unpack(None))
        refs = []
        for ref in item['references']:
            integrity = self.integrity(ref['asset_id']) if ref['asset_id'] else {'exists': False, 'matches': False}
            warnings = list(ref['warnings'])
            if not integrity['exists']:
                warnings.append('参考图片缺失')
            elif integrity['matches'] is False:
                warnings.append('参考哈希变化：当前文件与当时记录不一致')
            refs.append(dict(ref, warnings=warnings, integrity=integrity))
        versions = [dict(self.summary(i), image_path=i['image_path']) for i in self.rows() if i['batch'] == item['batch']]
        versions.sort(key=lambda i: i['version'])
        return dict(item, **saved, references=refs, versions=versions, image_integrity=self.integrity(item['image_asset']))

    def save(self, key, value, revision):
        item = self.get(key)
        integrity = self.integrity(item['image_asset'])
        if not integrity['exists'] or not integrity['matches']:
            raise Conflict('成图缺失或哈希变化，未保存评分；请先核对归档')
        return self.store.save(item, value, revision)

    def analysis(self, params):
        high, low = int(params.get('high', 4)), int(params.get('low', 2))
        if not 1 <= low < high <= 5:
            raise ValueError('门槛需满足 1 ≤ 低分上限 < 高分下限 ≤ 5')
        rows = self.date_scope(self.rows(), params)
        by_key = {i['key']: i for i in rows}
        groups = {'high': [], 'low': [], 'middle': [], 'unscored': []}
        references = {}
        for item in rows:
            score = item['review']['scores']['overall']
            group = 'unscored' if score is None else 'high' if score >= high else 'low' if score <= low else 'middle'
            evidence = self.export_item(item)
            groups[group].append(evidence)
            used = set()
            for ref in item['references']:
                if ref['scope'] != 'external_how' or not ref['sha256'] or ref['sha256'] in used:
                    continue
                used.add(ref['sha256'])
                entry = references.setdefault(ref['sha256'], {'sha256': ref['sha256'], 'asset_id': ref['asset_id'],
                    'path': ref['path'], 'aliases': set(), 'source_paths': set(), 'duties': set(),
                    'groups': defaultdict(list), 'unverified_input_keys': [], 'warnings': []})
                entry['aliases'].update(ref['aliases'])
                entry['source_paths'].add(ref['source_path'])
                entry['duties'].update(ref['duty_labels'])
                entry['groups'][group].append(item['key'])
                if ref['sent'] is not True:
                    entry['unverified_input_keys'].append(item['key'])
        chains = defaultdict(list)
        for item in rows:
            chains[item['chain_key']].append(item)
        with self.lock:
            all_items = dict(self.items)
        stages = {'initial': [], 'latest_scored': []}
        for chain, versions in chains.items():
            root = all_items[chain]
            # An unscored or out-of-scope root is explicitly unscored/out-of-scope, never guessed.
            first = by_key.get(chain)
            stages['initial'].append({'chain_key': chain, 'key': root['key'], 'title': root['title'],
                'score': first['review']['scores']['overall'] if first else None, 'in_scope': first is not None,
                'versions_in_scope': len(versions)})
            scored = [i for i in versions if i['review']['scores']['overall'] is not None]
            latest = max(scored, key=lambda i: (i['created_at'], i['catalog_order'])) if scored else None
            stages['latest_scored'].append({'chain_key': chain, 'key': latest['key'] if latest else None,
                'score': latest['review']['scores']['overall'] if latest else None,
                'is_revision': bool(latest and latest['parent_key'])})
        for ref in references.values():
            integrity = self.integrity(ref['asset_id']) if ref['asset_id'] else {'exists': False, 'matches': False}
            if not integrity['exists']:
                ref['warnings'].append('参考图片缺失')
            elif integrity['matches'] is False:
                ref['warnings'].append('参考哈希变化：当前文件与当时记录不一致')
            if ref['unverified_input_keys']:
                ref['warnings'].append('部分关联版本缺少实际调用证据，仅能确认归档参考关系')
            ref['aliases'] = sorted(ref['aliases'])
            ref['source_paths'] = sorted(ref['source_paths'])
            ref['duties'] = sorted(ref['duties'])
            ref['groups'] = {g: ref['groups'].get(g, []) for g in groups}
            ref['chain_count'] = len({by_key[k]['chain_key'] for keys in ref['groups'].values() for k in keys})
            ref['version_count'] = sum(len(v) for v in ref['groups'].values())
            related_chains = {by_key[k]['chain_key'] for keys in ref['groups'].values() for k in keys}
            ref['initial'] = [s for s in stages['initial'] if s['chain_key'] in related_chains]
            ref['latest_scored'] = [s for s in stages['latest_scored'] if s['chain_key'] in related_chains]
        stats = {}
        for name, evidence in groups.items():
            members = [by_key[i['key']] for i in evidence]
            stats[name] = {'versions': len(members), 'chains': len({i['chain_key'] for i in members}),
                'references': sum(bool(r['groups'][name]) for r in references.values()),
                'score_distribution': dict(Counter(i['review']['scores']['overall'] for i in members)),
                'outfits': dict(Counter(i['variant'] for i in members)),
                'duties': dict(Counter(d for r in references.values() if r['groups'][name] for d in r['duties']))}
        return {'schema_version': 1, 'kind': 'arco-reference-analysis', 'exported_at': now(),
            'filters': {'start': params.get('start', ''), 'end': params.get('end', ''), 'high': high, 'low': low},
            'statistics': stats, 'stages': stages, 'groups': groups, 'references': list(references.values()),
            'limitations': ['参考用途与服装来自生成记录，不是自动识别的视觉共性。',
                '版本与修订不作为独立生成样本；原图去重不等于独立试验。',
                '高低分两组可以共享同一参考图；不能把作品分数直接归因于参考。',
                '多数参考仅有一条生成链，需结合角色、服装、提示词和修订影响人工判断。',
                '首次生成未评分或不在日期范围时保持空值；最新已评分阶段按总体满意度取值。',
                '图片文件仅以本机路径提供，后续分析需在可访问这些路径的环境中进行。']}

    def export_item(self, item):
        fields = ('key', 'output_id', 'sha256', 'title', 'batch', 'version', 'created_at', 'status', 'variant',
                  'image_path', 'record_path', 'parent_key', 'chain_key', 'review', 'state', 'updated_at', 'warnings')
        value = {k: item[k] for k in fields}
        value['warnings'] = list(value['warnings'])
        value['image_integrity'] = self.integrity(item['image_asset'])
        if not value['image_integrity']['exists']:
            value['warnings'].append('成图缺失：该评分仍绑定归档时的图片哈希')
        elif value['image_integrity']['matches'] is False:
            value['warnings'].append('成图哈希变化：当前图片不能作为原评分的可靠视觉证据')
        value['external_references'] = [dict(r) for r in item['references'] if r['scope'] == 'external_how']
        return value

    def modifications(self, params):
        rows = self.date_scope(self.rows(), params)
        selected = [self.export_item(i) for i in rows if i['review']['decision'] in ('repair', 'regenerate')
                    or i['review']['directions']]
        order = {'high': 0, 'medium': 1, 'low': 2}
        selected.sort(key=lambda i: min((order[d['priority']] for d in i['review']['directions']), default=1))
        for item in selected:
            item['requirement_pending'] = not bool(item['review']['directions'] or item['review']['notes'])
            item['all_references'] = self.get(item['key'])['references']
        return {'schema_version': 1, 'kind': 'arco-modification-list', 'exported_at': now(),
                'filters': {'start': params.get('start', ''), 'end': params.get('end', '')}, 'items': selected}

    def audit(self, hashes=False):
        with self.lock:
            items, assets = list(self.items.values()), dict(self.assets)
        failures = []
        for key, asset in assets.items():
            if not Path(asset['path']).is_file():
                failures.append({'asset': key, 'path': asset['path'], 'problem': 'missing'})
            elif hashes and self.integrity(key)['matches'] is False:
                failures.append({'asset': key, 'path': asset['path'], 'problem': 'hash_changed'})
        return {'versions': len(items), 'assets': len(assets), 'references': sum(len(i['references']) for i in items),
                'batches': len({i['batch'] for i in items}), 'chains': len({i['chain_key'] for i in items}),
                'external_images': len({r['sha256'] for i in items for r in i['references']
                                        if r['scope'] == 'external_how' and r['sha256']}),
                'missing_invocations': sum(any('调用证据' in w for w in i['warnings']) for i in items),
                'empty_references': sum(not i['references'] for i in items),
                'hashes_checked': hashes, 'failures': failures, 'record_problems': self.problems}


def markdown(packet):
    def link(label, path):
        return f'[{label}](<{path}>)' if path else '未保存路径'
    def block(text):
        return str(text).replace('\n', '\n> ')
    if packet['kind'] == 'arco-modification-list':
        lines = ['# Arco 后续修改清单', '', f'导出时间：{packet["exported_at"]}',
                 f'日期范围：{packet["filters"]}', '']
        for i in packet['items']:
            r = i['review']
            lines += [f'## {i["title"]} · v{i["version"]:02}', '',
                f'人工结论：{DECISIONS.get(r["decision"], "未选择")}；总分：{r["scores"]["overall"] or "未评分"}', '',
                link('生成图片', i['image_path']), '', f'版本主键：`{i["key"]}`',
                f'生成链：`{i["chain_key"]}`', '', f'分项：{json.dumps(r["scores"], ensure_ascii=False)}',
                f'问题标签：{"、".join(r["tags"]) or "未填写"}', '']
            for warning in i['warnings']:
                lines += [f'> {block(warning)}', '']
            if i['requirement_pending']:
                lines += ['**修改要求待补充**', '']
            for d in r['directions']:
                lines += [f'- {dict(high="高", medium="中", low="低")[d["priority"]]}优先级：{d["text"]}', '']
            if r['notes']:
                lines += [f'> {block(r["notes"])}', '']
            lines += ['参考图：', '']
            for ref in i['all_references']:
                lines += [f'- {link("、".join(ref["aliases"]) or "参考", ref["path"])} · {"、".join(ref["duty_labels"])}']
            lines += ['', link('生成记录', i['record_path']), '']
        return '\n'.join(lines)
    lines = ['# Arco 高低分外部参考分析资料', '', f'导出时间：{packet["exported_at"]}',
             f'筛选条件：{packet["filters"]}', '', '## 分组统计', '']
    labels = {'high': '高分', 'low': '低分', 'middle': '中间分', 'unscored': '未填总分'}
    lines += ['| 分组 | 版本数 | 生成链数 | 外部原图数 |', '| --- | ---: | ---: | ---: |']
    for key, s in packet['statistics'].items():
        lines += [f'| {labels[key]} | {s["versions"]} | {s["chains"]} | {s["references"]} |']
    lines += ['', '## 判断边界', ''] + [f'- {l}' for l in packet['limitations']]
    lines += ['', '## 后续视觉分析问题', '',
        '请实际查看以下外部原图，比较高分与低分组的画风、姿态、构图、场景、光影和表情。',
        '区分视觉观察与记录元数据，列出支持每条共性的具体图片及反例；考虑初稿、修订和样本数量。',
        '提出哪些参考特征值得进一步试验，以及尚不能确定的部分，不直接从作品分数推出因果结论。', '',
        '## 外部原图与证据', '']
    by_key = {i['key']: i for members in packet['groups'].values() for i in members}
    refs = sorted(packet['references'], key=lambda r: (not bool(r['groups']['high']), not bool(r['groups']['low']), r['sha256']))
    for ref in refs:
        lines += [f'### {" / ".join(ref["aliases"]) or ref["sha256"][:12]}', '', link('外部原图', ref['path']), '',
            f'内容 SHA-256：`{ref["sha256"]}`', f'用途：{"、".join(ref["duties"])}',
            f'生成链数：{ref["chain_count"]}；版本数：{ref["version_count"]}', '']
        for group, keys in ref['groups'].items():
            for key in keys:
                i = by_key[key]
                lines += [f'- {labels[group]} · {link(i["title"] + " v" + str(i["version"]), i["image_path"])}'
                    f' · 总分 {i["review"]["scores"]["overall"] or "未填"} · {i["variant"]}'
                    f' · 分项 {json.dumps(i["review"]["scores"], ensure_ascii=False)}',
                    f'  - 备注：{i["review"]["notes"] or "未填写"}；标签：{"、".join(i["review"]["tags"])}']
        for warning in ref['warnings']:
            lines += [f'> {block(warning)}', '']
        lines += ['', '阶段对照：', '']
        for first in ref['initial']:
            last = next(s for s in ref['latest_scored'] if s['chain_key'] == first['chain_key'])
            initial = first['score'] if first['in_scope'] else '不在日期范围'
            lines += [f'- 链 `{first["chain_key"]}`：首次生成 {initial if initial is not None else "未评分"}'
                      f' → 最新已评分 {last["score"] if last["score"] is not None else "未评分"}；'
                      f'最新评分来自修订：{"是" if last["is_revision"] else "否"}']
        lines += ['']
    # Keep all matching works, including those whose old record has no external reference.
    lines += ['## 全部命中作品', '']
    for group, members in packet['groups'].items():
        lines += [f'### {labels[group]}', '']
        for i in members:
            lines += [f'- {link(i["title"] + " v" + str(i["version"]), i["image_path"])} · '
                      f'总分 {i["review"]["scores"]["overall"] or "未填"} · 主键 `{i["key"]}`']
            for warning in i['warnings']:
                lines += [f'  - 注意：{warning}']
        lines += ['']
    return '\n'.join(lines)
