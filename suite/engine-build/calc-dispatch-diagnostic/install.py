"""Apply a locked, Windows ARM64 only numeric save diagnostic to fresh LO source.

The build driver authenticates the full upstream archive before this hook. Every
source, exact patch result, and header payload is verified before source writes.
This helper neither builds nor qualifies a runtime.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import stat

HERE = Path(__file__).absolute().parent
CORE = 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
SOURCES = ('sc/source/ui/view/tabvwsha.cxx', 'sfx2/source/doc/objstor.cxx')
PAYLOADS = {name: 'include/opengeul_calc_dispatch/'+name
            for name in ('windows_runtime.h', 'recorder.h', 'wire.h')}
MAX_INPUT = 4*1024*1024


def unlinked(path: Path):
    """Reject symlinks and Windows junction/reparse ancestors, including roots."""
    for part in (path, *path.parents):
        try: info = part.lstat()
        except FileNotFoundError: continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked diagnostic input or output')


def _identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns


def read_regular(path: Path, maximum=MAX_INPUT) -> bytes:
    unlinked(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= maximum:
        raise ValueError('Diagnostic input must be a bounded unlinked regular file')
    with path.open('rb') as stream:
        if _identity(os.fstat(stream.fileno())) != _identity(before):
            raise ValueError('Diagnostic input changed while opening')
        raw = stream.read(maximum+1)
        if _identity(os.fstat(stream.fileno())) != _identity(before):
            raise ValueError('Diagnostic input changed while reading')
    unlinked(path)
    if _identity(path.lstat()) != _identity(before) or len(raw) != before.st_size:
        raise ValueError('Diagnostic input changed while reading')
    return raw


def _check(raw, expected):
    if (type(expected.get('bytes')) is not int or expected['bytes'] != len(raw)
            or not isinstance(expected.get('sha256'), str)
            or re.fullmatch('[0-9a-f]{64}', expected['sha256']) is None
            or hashlib.sha256(raw).hexdigest() != expected['sha256']):
        raise ValueError('Diagnostic byte count or SHA256 differs from lock')


def _patched(originals: dict[str, bytes], raw: bytes) -> dict[str, bytes]:
    """Apply exact unified hunks with no offset, fuzz, duplicate, or path fallback."""
    lines = raw.splitlines(keepends=True); index = 0; results = {}
    while index < len(lines):
        if not lines[index].startswith(b'--- a/') or index+1 >= len(lines):
            raise ValueError('Invalid diagnostic patch header')
        name = lines[index][6:].removesuffix(b'\n').decode('ascii')
        if name not in originals or name in results or lines[index+1] != b'+++ b/'+name.encode()+b'\n':
            raise ValueError('Unexpected or duplicate diagnostic patch target')
        source = originals[name].splitlines(keepends=True); output = []; cursor = 0; count = 0
        index += 2
        while index < len(lines) and not lines[index].startswith(b'--- a/'):
            header = re.fullmatch(rb'@@ -(\d+),(\d+) \+(\d+),(\d+) @@[^\n]*\n', lines[index])
            if header is None: raise ValueError('Invalid diagnostic patch hunk')
            old_start, old_count, new_start, new_count = map(int, header.groups())
            if old_start < 1 or old_start-1 < cursor or old_start-1 > len(source):
                raise ValueError('Invalid diagnostic patch hunk offset')
            output.extend(source[cursor:old_start-1]); cursor = old_start-1
            if new_start != len(output)+1: raise ValueError('Invalid diagnostic patch result offset')
            index += 1; removed = 0; added = 0
            while index < len(lines) and lines[index][:1] in (b' ', b'-', b'+'):
                line = lines[index]; tag = line[:1]; content = line[1:]
                if tag != b'+':
                    if cursor >= len(source) or source[cursor] != content:
                        raise ValueError('Diagnostic patch context differs from pinned source')
                    cursor += 1; removed += 1
                if tag != b'-': output.append(content); added += 1
                index += 1
                if removed == old_count and added == new_count: break
            if removed != old_count or added != new_count: raise ValueError('Diagnostic patch hunk size differs')
            count += 1
        if not count: raise ValueError('Empty diagnostic patch target')
        output.extend(source[cursor:]); results[name] = b''.join(output)
    if set(results) != set(originals): raise ValueError('Diagnostic patch omits a source target')
    return results


def install(source: Path, target: str, core_commit: str, *, package: Path=HERE) -> dict:
    if target != 'windows-arm64' or core_commit != CORE:
        raise ValueError('Diagnostic requires the exact pinned Windows ARM64 source')
    source = Path(source).absolute(); package = Path(package).absolute()
    unlinked(source); unlinked(package)
    if not source.is_dir() or not package.is_dir(): raise ValueError('Diagnostic roots must already exist')
    lock_raw = read_regular(package/'source-lock.json', 65536)
    lock = json.loads(lock_raw)
    if (lock.get('schemaVersion') != 1 or lock.get('kind') != 'calc-save-dispatch-diagnostic-source'
            or lock.get('coreCommit') != CORE or lock.get('target') != target
            or lock.get('acceptanceEligible') is not False):
        raise ValueError('Diagnostic source lock identity differs')
    source_pins = lock.get('sources', [])
    payload_pins = lock.get('payloads', [])
    if (len(source_pins) != len(SOURCES) or {s['path'] for s in source_pins} != set(SOURCES)
            or len(payload_pins) != len(PAYLOADS)
            or {(s['source'], s['path']) for s in payload_pins} != set(PAYLOADS.items())
            or lock['patch']['path'] != 'source.patch'):
        raise ValueError('Diagnostic source/payload set differs or duplicates')
    patch_raw = read_regular(package/'source.patch'); _check(patch_raw, lock['patch'])
    originals = {}
    for pin in source_pins:
        raw = read_regular(source/pin['path']); _check(raw, pin['before']); originals[pin['path']] = raw
    changed = _patched(originals, patch_raw)
    for pin in source_pins: _check(changed[pin['path']], pin['after'])
    payloads = {}
    payload_root = source/'include/opengeul_calc_dispatch'
    unlinked(payload_root)
    if payload_root.exists() or not payload_root.parent.is_dir():
        raise ValueError('Diagnostic payload directory already exists or is missing')
    for pin in payload_pins:
        path = source/pin['path']; unlinked(path)
        if path.exists(): raise ValueError('Diagnostic payload destination already exists')
        raw = read_regular(package/pin['source']); _check(raw, pin); payloads[pin['path']] = raw
    if read_regular(package/'source-lock.json', 65536) != lock_raw or read_regular(package/'source.patch') != patch_raw:
        raise ValueError('Diagnostic package changed after validation')
    for pin in payload_pins:
        if read_regular(package/pin['source']) != payloads[pin['path']]:
            raise ValueError('Diagnostic payload changed after validation')
    with ExitStack() as opened:
        streams = {}
        for name, original in originals.items():
            path = source/name
            if read_regular(path) != original: raise ValueError('Diagnostic source changed after validation')
            stream = opened.enter_context(path.open('r+b'))
            if (not stat.S_ISREG(os.fstat(stream.fileno()).st_mode)
                    or _identity(path.lstat()) != _identity(os.fstat(stream.fileno()))
                    or stream.read(MAX_INPUT+1) != original):
                raise ValueError('Diagnostic source changed before write')
            streams[name] = stream
        for name in payloads:
            path = source/name; unlinked(path)
            if path.exists(): raise ValueError('Diagnostic payload destination changed after validation')
        unlinked(payload_root)
        payload_root.mkdir()
        for name, raw in payloads.items():
            with (source/name).open('xb') as stream: stream.write(raw)
        for name, stream in streams.items():
            stream.seek(0); stream.write(changed[name]); stream.truncate(); stream.flush()
    for pin in source_pins: _check(read_regular(source/pin['path']), pin['after'])
    for pin in payload_pins: _check(read_regular(source/pin['path']), pin)
    return {'schemaVersion': 1, 'kind': lock['kind'], 'coreCommit': CORE, 'target': target,
            'lockSha256': hashlib.sha256(lock_raw).hexdigest(), 'patch': lock['patch'],
            'sources': source_pins, 'payloads': payload_pins,
            'fullEngineQualified': False, 'acceptanceEligible': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--target', required=True)
    parser.add_argument('--core-commit', required=True)
    args = parser.parse_args(argv)
    try: receipt = install(args.source_root, args.target, args.core_commit)
    except (ValueError, OSError, KeyError, TypeError, UnicodeError):
        print(json.dumps({'schemaVersion': 1, 'kind': 'calc-save-dispatch-diagnostic-source',
                          'passed': False, 'acceptanceEligible': False, 'error': 'source-authentication-rejected'}))
        return 1
    print(json.dumps({'passed': True, **receipt}, sort_keys=True)); return 0


if __name__ == '__main__': raise SystemExit(main())
