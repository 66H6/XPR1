"""Small, deterministic I/O helpers. No data are uploaded."""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def relative_path(root, value):
    path = Path(value)
    if path.is_absolute():
        raise ValueError('项目路径必须为相对路径')
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError('路径越出项目目录')
    return resolved


def read_manifest(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        required = {'PDB_ID', 'paper_family', 'structure_scope', 'primary_citation',
                    'PMID', 'DOI', 'species', 'reported_state', 'curation_notes'}
        if set(reader.fieldnames or []) != required or len(reader.fieldnames) != len(required):
            raise ValueError('结构表列名缺失、重复或与约定不符')
        rows = list(reader)
    if not rows or any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError('结构表为空或有列数不一致的记录')
    return rows


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
