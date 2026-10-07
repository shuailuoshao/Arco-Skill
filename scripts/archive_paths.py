"""Resolve retired locations without rewriting sealed historical records."""
from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=8)
def _mapping(root, modified=0):
    path = Path(root) / 'archive/整理记录/路径映射.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def relocate(path, *, root=ROOT):
    path = Path(path)
    root = Path(root).resolve()
    absolute = path if path.is_absolute() else root / path
    ledger = root / 'archive/整理记录/路径映射.json'
    modified = ledger.stat().st_mtime_ns if ledger.is_file() else 0
    mapped = _mapping(str(root), modified).get(str(absolute))
    if mapped and not mapped.endswith('.diff'):
        target = Path(mapped)
        if target.exists():
            return target
    try:
        parts = absolute.relative_to(root).parts
    except ValueError:
        return absolute
    if parts and parts[0] == 'evaluation':
        target = root / 'archive/实验' / Path(*parts)
        if target.exists():
            return target
    if parts and parts[0] in {'output', 'outputs'}:
        target = root / 'archive/旧开发记录' / Path(*parts)
        if target.exists():
            return target
    return absolute


def historical_file(path):
    path = Path(path)
    if path.name == 'SKILL.md' and not path.exists():
        retired = path.with_name('SKILL.history.txt')
        if retired.is_file():
            return retired
    return path


def historical_locator(path, *, root=ROOT):
    root = Path(root).resolve()
    relative = Path(path).resolve(strict=False).relative_to(root).as_posix()
    if (root/'archive/整理记录/路径映射.json').is_file() and relative.startswith('archive/实验/evaluation/'):
        return relative[len('archive/实验/'):]
    return relative
