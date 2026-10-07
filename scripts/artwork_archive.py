"""Readable local artwork storage; never changes provider output identities."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
from typing import Any, Mapping

HK = timezone(timedelta(hours=8))


def file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return sha256(stream.read()).hexdigest()


def safe_name(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:48]
    if not name or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        return '阿尔可创作'
    return name


def artwork_title(request: Mapping[str, Any]) -> str:
    explicit = request.get('artwork_title')
    if explicit:
        return safe_name(explicit)
    prompt = request.get('base_prompt', '')
    for words, title in [(('楼梯', 'stair'), '楼梯回眸'), (('黄昏', 'twilight'), '黄昏栏杆'),
                         (('比耶', 'wink', '眨眼'), '眨眼比耶'), (('三姿态', 'collage'), '三姿态拼图')]:
        if any(word in prompt.lower() for word in words):
            return title
    text = re.split(r'[。！？\n]', prompt)[0]
    text = re.sub(r'^(请|画|生成|绘制|阿尔可|Arco|一张|图片|的|\s)+', '', text, flags=re.I)
    if not re.search(r'[\u4e00-\u9fff]', text):
        return '阿尔可创作'
    return safe_name(text[:24] or '阿尔可创作')


def previous_title(root: Path, output_id: str) -> str | None:
    path = Path(root)/'作品/.catalog.json'
    if not path.is_file():
        return None
    try:
        catalog = json.loads(path.read_text(encoding='utf-8'))
        row = _find_previous(catalog, output_id, Path(root)/'作品')
        return row['title'] if row else None
    except (OSError, ValueError, KeyError):
        return None


def _find_previous(catalog, output_id, gallery):
    if not output_id:
        return None
    direct = next((row for row in reversed(catalog) if row['output_id'] == output_id), None)
    if direct:
        return direct
    from archive_paths import relocate
    target = relocate(output_id, root=gallery.parent)
    return next((row for row in reversed(catalog) if gallery/row['image'] == target), None)


def _json(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    temp.replace(path)


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if file_hash(source) != file_hash(target):
        raise OSError(f'归档校验失败: {source}')


def write_gallery_index(gallery: Path, catalog) -> None:
    lines = ['# 阿尔可作品索引', '', '按主题 → 日期批次存放；每批包含原始参考和生成记录。最新版不自动代表用户定稿。', '']
    for title in sorted({row['title'] for row in catalog}):
        rows = [row for row in catalog if row['title'] == title]
        latest = rows[-1]
        lines += [f'## {title}', '', f'[{len(rows)} 个版本](<{gallery/title}>)', '',
                  f'![{title}](<{gallery/latest["image"]}>)', '']
    (gallery/'索引.md').write_text('\n'.join(lines), encoding='utf-8')


def archive_result(result, request: Mapping[str, Any], root: Path, previous: Mapping[str, Any] | None = None, *, created_on: str | None = None):
    """Return an enriched result, or a visible archive error with original intact."""
    gallery = Path(root).resolve() / '作品'
    lock = gallery / '.archive-lock'
    owned = False
    batch = None
    record = None
    created_files = []
    published = False
    try:
        gallery.mkdir(parents=True, exist_ok=True)
        lock.mkdir()  # Fail safely if another writer is publishing.
        owned = True
        catalog_path = gallery / '.catalog.json'
        catalog = json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.exists() else []
        parent = (previous or {}).get('output_id') or result.parent_output or result.reset_triggered_from_output
        match = _find_previous(catalog, parent, gallery)
        title = match['title'] if match else artwork_title(request)
        if match:
            batch = gallery / match['batch']
            batch.resolve().relative_to(gallery)
            if not batch.is_dir():
                raise OSError('上一版本归档目录缺失')
        else:
            today = created_on or datetime.now(HK).strftime('%Y-%m-%d')
            for number in range(1, 10000):
                candidate = gallery / title / f'{today}_{number:02d}'
                try:
                    candidate.mkdir(parents=True)
                    batch = candidate
                    break
                except FileExistsError:
                    continue
            if batch is None:
                raise OSError('作品批次编号已耗尽')
        versions = [row['version'] for row in catalog if row['batch'] == batch.relative_to(gallery).as_posix()]
        version = max(versions, default=0) + 1
        variant = request.get('variant_id') or '未指定服装'
        variant = {'casual-outfit': '常服', 'school-uniform': '校服'}.get(variant, variant)
        image = batch / f'阿尔可_{safe_name(variant)}_{title}_v{version:02d}{result.output_path.suffix.lower()}'
        if image.exists():
            raise OSError('作品版本路径已存在，拒绝覆盖')
        _copy(result.output_path, image)
        created_files.append(image)
        references = []
        for number, ref in enumerate(result.selected_references, 1):
            source = Path(str(ref.get('path', '')))
            entry = {'reference_id': ref.get('reference_id', ref.get('asset_id')), 'role': ref.get('role'),
                     'source_path': str(source), 'missing': not source.is_file()}
            if source.is_file():
                entry['sha256'] = file_hash(source)
                if ref.get('source_scope') == 'external_how':
                    destination = batch / '原始参考' / f'v{version:02d}_参考{number:02d}{source.suffix.lower()}'
                    _copy(source, destination)
                    entry['copy_path'] = destination.relative_to(batch).as_posix()
            references.append(entry)
        (batch / '原始参考').mkdir(exist_ok=True)
        records = batch / '生成记录'
        records.mkdir(exist_ok=True)
        record = records / f'v{version:02d}.json'
        row = {'title': title, 'batch': batch.relative_to(gallery).as_posix(), 'version': version,
               'output_id': result.output_id, 'parent_output': parent,
               'image': image.relative_to(gallery).as_posix(), 'sha256': file_hash(image),
               'status': '历史版本（未确认）' if created_on else ('修改稿' if parent else '初稿'), 'user_accepted': False,
               'created_at': datetime.now(HK).isoformat(), 'record': record.relative_to(gallery).as_posix()}
        enriched = replace(result, archive_image_path=image, archive_record_path=record, archive_error=None)
        _json(record, {'artwork': row, 'request': dict(request), 'references': references, 'result': enriched.as_dict()})
        created_files.append(record)
        (records / f'v{version:02d}_提示词.txt').write_text(result.prompt, encoding='utf-8')
        catalog.append(row)
        _json(catalog_path, catalog)
        published = True
        (batch / '作品说明.md').write_text(f'# {title}\n\n所有版本均保留；最新版不自动代表定稿。\n\n'
            + '\n'.join(f"- v{item['version']:02d}：{item['status']}；用户确认：{'是' if item['user_accepted'] else '未确认'}"
                        for item in catalog if item['batch'] == row['batch']) + '\n', encoding='utf-8')
        write_gallery_index(gallery, catalog)
        return enriched
    except Exception as exc:
        if published:
            return replace(enriched, archive_error=f'归档已保存，索引更新失败: {exc}')
        for path in created_files:
            if path.is_file():
                path.unlink()
        return replace(result, archive_image_path=None, archive_record_path=None, archive_error=f'{type(exc).__name__}: {exc}')
    finally:
        if owned:
            lock.rmdir()


def sync_review(result):
    """Keep archive review state aligned without asserting human acceptance."""
    if not result.archive_record_path:
        return result
    owned = False
    lock = None
    try:
        path = result.archive_record_path
        gallery = next(parent for parent in path.parents if parent.name == '作品')
        lock = gallery / '.archive-lock'
        lock.mkdir()
        owned = True
        data = json.loads(path.read_text(encoding='utf-8'))
        data['result'] = result.as_dict()
        if result.visual_review_status == 'degraded':
            old = result.archive_image_path
            failed = old if old.parent.name == '失败稿' else old.parent / '失败稿' / old.name
            failed.parent.mkdir(exist_ok=True)
            if old != failed:
                old.rename(failed)
                result = replace(result, archive_image_path=failed)
            data['artwork']['status'] = '失败稿'
            data['result'] = result.as_dict()
            data['artwork']['image'] = failed.relative_to(gallery).as_posix()
            catalog_path = gallery / '.catalog.json'
            catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
            for row in catalog:
                if row['record'] == path.relative_to(gallery).as_posix():
                    row.update(data['artwork'])
            _json(catalog_path, catalog)
            write_gallery_index(gallery, catalog)
        _json(path, data)
        return result
    except Exception as exc:
        return replace(result, archive_error=f'检查记录保存失败: {exc}')
    finally:
        if owned:
            lock.rmdir()
