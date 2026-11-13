"""Apply a locked, ARM64 numeric Writer observer diagnostic to fresh LO source.

The build driver authenticates the full upstream archive before this hook. Every
source, exact patch result, and header payload is verified before source writes.
This helper neither builds nor qualifies a runtime.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import re
import stat

HERE = Path(__file__).absolute().parent
CORE = '9dea406ab7695df6325b11b0e19fdca8db4b7276'
SOURCES = ('winaccessibility/source/UAccCOM/MAccessible.cxx',
 'winaccessibility/source/service/AccObjectWinManager.cxx','winaccessibility/inc/AccObjectWinManager.hxx',
 'winaccessibility/Library_uacccom.mk','winaccessibility/Library_winaccessibility.mk')
PAYLOADS = {name: 'include/opengeul_writer_observer/'+name for name in
 ('wire.h','atomic.h','descriptor.h','private_sink.hxx','recorder.h','session.h','observer_api.hxx')}
PAYLOADS['native.cpp']='winaccessibility/source/UAccCOM/OpenGeulWriterObserver.cxx'
DEPENDENCIES=('winaccessibility/source/UAccCOM/MAccessible.h', 'winaccessibility/inc/AccObject.hxx', 'winaccessibility/source/service/AccObject.cxx', 'winaccessibility/source/UAccCOM/UAccCOM.cxx')
MAX_INPUT = 4*1024*1024



_ACTIVE = ContextVar('writer_installer_numeric_diagnostic', default=None)


class FailureState:
    def __init__(self, source, package):
        self.source, self.package = Path(source).absolute(), Path(package).absolute()
        self.stage = self.file = self.detail = self.identity_mask = 0

    def locate(self, path):
        path=Path(path)
        if path==self.source:return 30
        if path==self.package:return 31
        try:
            relative=path.relative_to(self.source).as_posix()
            if relative in SOURCES:return SOURCES.index(relative)+1
            if relative in DEPENDENCIES:return DEPENDENCIES.index(relative)+6
            if relative=='include/opengeul_writer_observer':return 29
            destinations=list(PAYLOADS.values())
            if relative in destinations:return destinations.index(relative)+21
        except ValueError:pass
        try:
            relative=path.relative_to(self.package).as_posix()
            controls={'source-lock.json':10,'wire-schema.json':11,'source.patch':12}
            if relative in controls:return controls[relative]
            if relative in PAYLOADS:return list(PAYLOADS).index(relative)+13
        except ValueError:pass
        return 0

    def result(self, error):
        classes={ValueError:1,OSError:2,PermissionError:3,FileNotFoundError:4,KeyError:5,TypeError:6,UnicodeError:7,json.JSONDecodeError:8}
        winerror=getattr(error,'winerror',None)
        known=type(winerror) is int and 0<=winerror<=0xffffffff
        return {'version':1,'stage':self.stage,'file':self.file,'detail':self.detail,
                'errorClass':classes.get(type(error),0),'winerrorKnown':int(known),
                'winerror':winerror if known else 0,'identityMask':self.identity_mask}


def _stage(code,path=None):
    state=_ACTIVE.get()
    if state is not None:
        state.stage=code;state.detail=0
        if path is not None:state.file=state.locate(path)


def _point(code,path=None):
    state=_ACTIVE.get()
    if state is not None:
        state.detail=code
        if path is not None:state.file=state.locate(path)


def _mask(value):
    state=_ACTIVE.get()
    if state is not None:state.identity_mask|=value


def _same_identity(left,right):
    a,b=_identity(left),_identity(right)
    mask=sum(1<<index for index,(x,y) in enumerate(zip(a,b)) if x!=y)
    _mask(mask)
    return mask==0


def _same_bytes(left,right):
    _point(8)
    return left==right

def unlinked(path: Path):
    """Reject symlinks and Windows junction/reparse ancestors, including roots."""
    _point(1,path)
    for part in (path, *path.parents):
        try: info = part.lstat()
        except FileNotFoundError: continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked diagnostic input or output')


def _identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_nlink


def read_regular(path: Path, maximum=MAX_INPUT) -> bytes:
    unlinked(path)
    _point(2,path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= maximum:
        _mask((0 if stat.S_ISREG(before.st_mode) else 4)|(0 if before.st_nlink==1 else 32)|(0 if 0<before.st_size<=maximum else 8))
        raise ValueError('Diagnostic input must be a bounded unlinked regular file')
    _point(3)
    with path.open('rb') as stream:
        _point(4)
        if not _same_identity(os.fstat(stream.fileno()), before):
            raise ValueError('Diagnostic input changed while opening')
        _point(5)
        raw = stream.read(maximum+1)
        _point(6)
        if not _same_identity(os.fstat(stream.fileno()), before):
            raise ValueError('Diagnostic input changed while reading')
    unlinked(path)
    _point(7)
    if not _same_identity(path.lstat(), before) or len(raw) != before.st_size:
        raise ValueError('Diagnostic input changed while reading')
    return raw


def _check(raw, expected):
    _point(8)
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


def _install(source: Path, target: str, core_commit: str=CORE, *, package: Path=HERE) -> dict:
    _stage(1)
    if target != 'windows-arm64' or core_commit != CORE:
        raise ValueError('Diagnostic requires the exact pinned Windows ARM64 9dea source')
    source = Path(source).absolute(); package = Path(package).absolute()
    _stage(2,source)
    unlinked(source); unlinked(package)
    if not source.is_dir() or not package.is_dir(): raise ValueError('Diagnostic roots must already exist')
    _stage(3,package/'source-lock.json')
    lock_raw = read_regular(package/'source-lock.json', 65536)
    _stage(4,package/'source-lock.json');_point(17)
    lock = json.loads(lock_raw)
    _point(18)
    if (lock.get('schemaVersion') != 1 or lock.get('kind') != 'writer-server-observer-diagnostic-source'
            or lock.get('coreCommit') != CORE or lock.get('targets') != ['windows-arm64']
            or lock.get('acceptanceEligible') is not False or lock.get('fullEngineQualified') is not False
            or lock.get('requiredRebuiltLibraries') != ['UAccCOM','winaccessibility']
            or lock.get('guiVerified') is not False or lock.get('mappingBytes') != 131328
            or lock.get('descriptorSchemaVersion') != 1 or lock.get('ipcVersion') != 1 or lock.get('sinkAbiVersion') != 2):
        raise ValueError('Diagnostic source lock identity differs')
    source_pins = lock.get('sources', [])
    payload_pins = lock.get('payloads', [])
    if (len(source_pins) != len(SOURCES) or {s['path'] for s in source_pins} != set(SOURCES)
            or len(payload_pins) != len(PAYLOADS)
            or {(s['source'], s['path']) for s in payload_pins} != set(PAYLOADS.items())
            or lock['patch']['path'] != 'source.patch'):
        raise ValueError('Diagnostic source/payload set differs or duplicates')
    dependencies=lock.get('dependencies',[])
    if len(dependencies)!=len(DEPENDENCIES) or {p['path'] for p in dependencies}!=set(DEPENDENCIES):
        raise ValueError('Diagnostic dependency set differs')
    for pin in dependencies:
        _stage(5,source/pin['path']);_check(read_regular(source/pin['path']),pin)
    _stage(6,package/'wire-schema.json')
    _check(read_regular(package/'wire-schema.json'),lock['wireSchema'])
    _stage(7,package/'source.patch')
    patch_raw = read_regular(package/'source.patch'); _check(patch_raw, lock['patch'])
    originals = {}
    for pin in source_pins:
        _stage(8,source/pin['path'])
        raw = read_regular(source/pin['path']); _check(raw, pin['before']); originals[pin['path']] = raw
    _stage(9,package/'source.patch');_point(16)
    changed = _patched(originals, patch_raw)
    for pin in source_pins:
        _stage(10,source/pin['path']);_check(changed[pin['path']], pin['after'])
    payloads = {}
    payload_root = source/'include/opengeul_writer_observer'
    _stage(11,payload_root)
    unlinked(payload_root)
    if payload_root.exists() or not payload_root.parent.is_dir():
        raise ValueError('Diagnostic payload directory already exists or is missing')
    for pin in payload_pins:
        _stage(11)
        path = source/pin['path']; unlinked(path)
        if path.exists(): raise ValueError('Diagnostic payload destination already exists')
        raw = read_regular(package/pin['source']); _check(raw, pin); payloads[pin['path']] = raw
    _stage(12,package/'source-lock.json')
    if not _same_bytes(read_regular(package/'source-lock.json',65536),lock_raw) or not _same_bytes(read_regular(package/'source.patch'),patch_raw):
        raise ValueError('Diagnostic package changed after validation')
    for pin in payload_pins:
        _stage(12,package/pin['source'])
        if not _same_bytes(read_regular(package/pin['source']),payloads[pin['path']]):
            raise ValueError('Diagnostic payload changed after validation')
    with ExitStack() as opened:
        streams = {}
        for name, original in originals.items():
            path = source/name
            _stage(13,path)
            if not _same_bytes(read_regular(path),original): raise ValueError('Diagnostic source changed after validation')
            _stage(14,path);_point(9)
            stream = opened.enter_context(path.open('r+b'))
            _point(10)
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                _mask(4);raise ValueError('Diagnostic source changed before write')
            _point(10)
            if os.fstat(stream.fileno()).st_nlink != 1:
                _mask(32);raise ValueError('Diagnostic source changed before write')
            _point(11)
            path_info=path.lstat()
            _point(10)
            if not _same_identity(path_info,os.fstat(stream.fileno())):
                raise ValueError('Diagnostic source changed before write')
            _point(12)
            if stream.read(MAX_INPUT+1) != original:
                raise ValueError('Diagnostic source changed before write')
            streams[name] = stream
        for name in payloads:
            _stage(15,source/name)
            path = source/name; unlinked(path)
            if path.exists(): raise ValueError('Diagnostic payload destination changed after validation')
        unlinked(payload_root)
        _stage(16,payload_root);_point(14)
        payload_root.mkdir()
        for name, raw in payloads.items():
            _stage(16,source/name);_point(9)
            with (source/name).open('xb') as stream:
                _point(13);stream.write(raw)
        for name, stream in streams.items():
            _stage(17,source/name);_point(13)
            stream.seek(0); stream.write(changed[name]); stream.truncate(); stream.flush()
    for pin in dependencies:
        _stage(18,source/pin['path']);_check(read_regular(source/pin['path']),pin)
    for pin in source_pins:
        _stage(18,source/pin['path']);_check(read_regular(source/pin['path']),pin['after'])
    for pin in payload_pins:
        _stage(18,source/pin['path']);_check(read_regular(source/pin['path']),pin)
    return {'schemaVersion': 1, 'kind': lock['kind'], 'coreCommit': CORE, 'target': target,
            'lockSha256': hashlib.sha256(lock_raw).hexdigest(), 'patch': lock['patch'],
            'sources': source_pins, 'payloads': payload_pins, 'dependencies': dependencies,
            'guiVerified':False,'mappingBytes':131328,'descriptorSchemaVersion':1,'wireSchema':lock['wireSchema'],
            'ipcVersion':1,'sinkAbiVersion':2, 'requiredRebuiltLibraries':['UAccCOM','winaccessibility'],
            'fullEngineQualified': False, 'acceptanceEligible': False}



def install(source: Path, target: str, core_commit: str=CORE, *, package: Path=HERE) -> dict:
    state=FailureState(source,package)
    token=_ACTIVE.set(state)
    try:
        return _install(source,target,core_commit,package=package)
    except (ValueError,OSError,KeyError,TypeError,UnicodeError) as error:
        error.writer_installer_diagnostic=state.result(error)
        raise
    finally:
        _ACTIVE.reset(token)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--target', required=True)
    parser.add_argument('--core-commit', required=True)
    args = parser.parse_args(argv)
    try: receipt = install(args.source_root, args.target, args.core_commit)
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as error:
        print(json.dumps({'schemaVersion': 1, 'kind': 'writer-server-observer-diagnostic-source',
                          'passed': False, 'acceptanceEligible': False, 'fullEngineQualified': False, 'guiVerified': False, 'error': 'source-authentication-rejected',
                          'diagnostic':getattr(error,'writer_installer_diagnostic',None) or {'version':1,'stage':0,'file':0,'detail':0,'errorClass':0,'winerrorKnown':0,'winerror':0,'identityMask':0}}))
        return 1
    print(json.dumps({'passed': True, **receipt}, sort_keys=True)); return 0


if __name__ == '__main__': raise SystemExit(main())
