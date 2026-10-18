"""Immutable method declaration and first-access record for a fresh source.

Hashing reads raw bytes without parsing measurements or labels. This is an
audit trail, not an access-control sandbox or proof about external human use.
The final runner must call check_protocol before reading any held-out rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def now():return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):digest.update(part)
    return digest.hexdigest()


def _exclusive_json(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(content,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')


def declare_protocol(root, output, configuration, code_paths, data_paths):
    root = Path(root).resolve();output = Path(output).resolve()
    if not code_paths or not data_paths:raise ValueError('Executable code and raw source paths are mandatory')
    def records(paths):
        result = {}
        for item in paths:
            path = Path(item).resolve()
            relative = str(path.relative_to(root))
            if not path.is_file():raise ValueError(f'Not a file: {relative}')
            result[relative] = {'sha256':sha256(path),'bytes':path.stat().st_size}
        return result
    payload = {'frozen_at_utc':now(),'configuration':configuration,
        'code':records(code_paths),'raw_sources':records(data_paths),
        'semantics':'Configuration and source hashes declared before first row/label parsing for this evaluation. Prior source exposure must be separately disclosed in configuration.'}
    _exclusive_json(output/'protocol.json',payload)
    return payload


def check_protocol(root, output):
    root = Path(root).resolve();output = Path(output).resolve()
    protocol = json.loads((output/'protocol.json').read_text())
    for group in ('code','raw_sources'):
        for relative, expected in protocol[group].items():
            path = (root/relative).resolve()
            path.relative_to(root)
            if path.stat().st_size != expected['bytes'] or sha256(path) != expected['sha256']:
                raise ValueError(f'Frozen {group} changed: {relative}')
    return protocol


def begin_first_access(root, output):
    """Call once immediately before parsing fresh values, after method checking."""
    output = Path(output).resolve()
    protocol = check_protocol(root,output)
    record = {'first_access_at_utc':now(),'protocol_sha256':sha256(output/'protocol.json'),
        'sources':list(protocol['raw_sources']),
        'note':'These sources are no longer untouched once this evaluation accesses them. Failed results cannot be retuned and called a fresh test.'}
    _exclusive_json(output/'source_access_started.json',record)
    return record
