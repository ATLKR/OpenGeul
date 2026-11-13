"""Authenticate Writer diagnostic bytes over a completely verified normal ARM Suite.

This reuses the Calc staging/branding and payload path/hash checks. Its explicit
byte inventory never calls the normal inventory scanner with diagnostic markers.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import sys
import tempfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from suite import payload
from suite.runtime_branding import brand_runtime

FAMILY='writer-server-observer-diagnostic'
CORE='bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
MARKER='program/opengeul-writer-server-observer-diagnostic.json'
OVERLAY='writer-server-observer-diagnostic.json'
RECEIPT='writer-server-observer-source-build-receipt.json'
SOURCE_LOCK='writer-server-observer-source-lock.json'
ENGINE='OpenGeul-Office-engine-arm64-writer-server-observer.zip'
BINARIES=('program/UAccCOM.dll','program/winaccessibility.dll')
MARKER_KEYS=frozenset('schemaVersion family kind sourceCommit sourceTree coreCommit sourceLockSha256 patchSha256 wireSchema descriptorSchemaVersion mappingBytes ipcVersion sinkAbiVersion requiredRebuiltLibraries binaries fullEngineQualified acceptanceEligible guiVerified'.split())
MAX_ARCHIVE_BYTES=8*1024**3
MAX_EXTRACTED_BYTES=8*1024**3
MAX_MEMBER_BYTES=1024**3
MAX_DLL_BYTES=1024**3
LOCK_KEYS=frozenset('schemaVersion kind architecture repository repositoryId sourceCommit sourceTree runId runAttempt artifactId artifactSha256 artifactSize sourceLockSha256 coreCommit patchSha256 wireSchemaSha256'.split())


def _check(check):
    if check is not None:check()


def _local(path):
    path=Path(path).absolute()
    if str(path).startswith(('\\\\','//')):raise ValueError('Local diagnostic paths required')
    for part in (*reversed(path.parents),path):
        if part.exists() or part.is_symlink():payload._kind(part)
    return path.resolve(strict=False)


def _positive(value,maximum):return type(value) is int and 0<value<=maximum
def _digest(value):return type(value) is str and payload.SHA.fullmatch(value) is not None
def _commit(value):return type(value) is str and payload.COMMIT.fullmatch(value) is not None and value!='0'*40
def _same(left,right):return json.dumps(left,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(right,sort_keys=True,separators=(',',':'),allow_nan=False)


def _hash(path,check=None):
    _check(check);before=payload._kind(path)
    if not stat.S_ISREG(before.st_mode):raise ValueError('Diagnostic requires regular files')
    result=hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            _check(check);block=stream.read(1024*1024)
            if not block:break
            result.update(block)
    after=payload._kind(path)
    if any(getattr(before,key)!=getattr(after,key) for key in ('st_size','st_mtime_ns','st_dev','st_ino')):
        raise ValueError('Diagnostic file changed while hashing')
    _check(check);return result.hexdigest()


def _raw(path,maximum=payload.MAX_METADATA,check=None):
    _check(check)
    info=payload._kind(path)
    if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=maximum:raise ValueError('Diagnostic JSON bound exceeded')
    fields=('st_dev','st_ino','st_mode','st_size','st_mtime_ns')
    with path.open('rb') as stream:
        if any(getattr(info,k)!=getattr(os.fstat(stream.fileno()),k) for k in fields):raise ValueError('Diagnostic JSON changed while opening')
        raw=stream.read(maximum+1)
        if any(getattr(info,k)!=getattr(os.fstat(stream.fileno()),k) for k in fields):raise ValueError('Diagnostic JSON changed while reading')
    after=payload._kind(path)
    if len(raw)!=info.st_size or any(getattr(info,k)!=getattr(after,k) for k in fields):raise ValueError('Diagnostic JSON changed after read')
    _check(check);return raw


def _json(path,maximum=payload.MAX_METADATA):
    return payload._json_bytes(_raw(path,maximum),path.name)


def _lock(path,source_lock,check):
    lock=_json(_local(path),65536)
    if (type(lock) is not dict or set(lock)!=LOCK_KEYS or type(lock['schemaVersion']) is not int or lock['schemaVersion']!=1
            or lock['kind']!='writer-server-observer-diagnostic-input' or lock['architecture']!='arm64'
            or lock['repository']!='ATLKR/OpenGeul' or type(lock['repositoryId']) is not int or lock['repositoryId']!=1405493151
            or lock['coreCommit']!=CORE or not all(_commit(lock[k]) for k in ('sourceCommit','sourceTree'))
            or not all(_positive(lock[k],2**63-1) for k in ('runId','artifactId'))
            or type(lock['runAttempt']) is not int or lock['runAttempt']!=1
            or not _positive(lock['artifactSize'],MAX_ARCHIVE_BYTES+9437184)
            or not all(_digest(lock[k]) for k in ('artifactSha256','sourceLockSha256','patchSha256','wireSchemaSha256'))):
        raise ValueError('Complete externally pinned Writer input required')
    source_lock=_local(source_lock)
    source_raw=_raw(source_lock,65536,check)
    if hashlib.sha256(source_raw).hexdigest()!=lock['sourceLockSha256']:raise ValueError('Writer source lock hash differs')
    source=payload._json_bytes(source_raw,source_lock.name)
    if (source.get('schemaVersion')!=1 or type(source['schemaVersion']) is not int or source.get('kind')!='writer-server-observer-diagnostic-source'
            or source.get('coreCommit')!=CORE or 'windows-arm64' not in source.get('targets',[])
            or source.get('requiredRebuiltLibraries')!=['UAccCOM','winaccessibility']
            or any(source.get(k) is not False for k in ('fullEngineQualified','acceptanceEligible','guiVerified'))
            or any(type(source.get(k)) is not int or source[k]!=value for k,value in [('ipcVersion',1),('sinkAbiVersion',2),('mappingBytes',131328),('descriptorSchemaVersion',1)])
            or source.get('patch',{}).get('sha256')!=lock['patchSha256']
            or source.get('wireSchema',{}).get('sha256')!=lock['wireSchemaSha256']):
        raise ValueError('Writer source lock family or ABI differs')
    return lock,source,source_raw


def _receipt(proof,lock,source):
    strings=dict(kind='native-office-engine-writer-server-observer-diagnostic',phase='Full',architecture='arm64',stage='complete',
        status='native-engine-writer-server-observer-diagnostic-built',sourceCommit=lock['sourceCommit'],sourceTree=lock['sourceTree'],sourceLockSha256=lock['sourceLockSha256'])
    if (type(proof) is not dict or any(type(proof.get(k)) is not str or proof[k]!=v for k,v in strings.items())
            or type(proof.get('schemaVersion')) is not int or proof['schemaVersion']!=1
            or type(proof.get('sourceRun')) is not int or proof['sourceRun']!=lock['runId']
            or type(proof.get('runAttempt')) is not int or proof['runAttempt']!=1 or proof.get('passed') is not True
            or any(proof.get(k) is not False for k in ('fullEngineQualified','acceptanceEligible','guiVerified'))
            or proof.get('sourcePin',{}).get('coreCommit')!=CORE):raise ValueError('Writer receipt is failed, unbound or qualified')
    host=proof.get('host',{})
    if host.get('isWindows') is not True or type(host.get('processMachine')) is not int or host['processMachine']!=0 or type(host.get('nativeMachine')) is not int or host['nativeMachine']!=0xaa64:
        raise ValueError('Writer producer is not native ARM64 Windows')
    hooks=proof.get('writerServerObserverSourceHooks',{})
    if (hooks.get('passed') is not True or hooks.get('target')!='windows-arm64' or hooks.get('kind')!=source['kind']
            or hooks.get('lockSha256')!=lock['sourceLockSha256'] or hooks.get('coreCommit')!=CORE
            or any(hooks.get(k) is not False for k in ('fullEngineQualified','acceptanceEligible','guiVerified'))
            or any(not _same(hooks.get(k),source.get(k)) for k in ('schemaVersion','patch','wireSchema','sources','payloads','dependencies','ipcVersion','sinkAbiVersion','mappingBytes','descriptorSchemaVersion','requiredRebuiltLibraries'))):
        raise ValueError('Writer source hook join differs')
    item=proof.get('artifact',{})
    if not _positive(item.get('size'),MAX_ARCHIVE_BYTES) or not _digest(item.get('sha256')):raise ValueError('Writer inner archive descriptor differs')
    return proof


def _entry_bytes(zipped,entry,limit,check):
    if not 0<entry.file_size<=limit:raise ValueError('Diagnostic member bound exceeded')
    result=bytearray()
    with zipped.open(entry) as stream:
        while True:
            _check(check);block=stream.read(min(1024*1024,limit+1-len(result)))
            if not block:break
            result.extend(block)
            if len(result)>entry.file_size:raise ValueError('Diagnostic member changed')
    if len(result)!=entry.file_size:raise ValueError('Diagnostic member incomplete')
    return bytes(result)


def _entry_hash(zipped,entry,check):
    value=hashlib.sha256();count=0
    with zipped.open(entry) as stream:
        while True:
            _check(check);block=stream.read(1024*1024)
            if not block:break
            value.update(block);count+=len(block)
            if count>entry.file_size:raise ValueError('Diagnostic member exceeds size')
    if count!=entry.file_size:raise ValueError('Diagnostic member incomplete')
    return value.hexdigest()


def _native_dll(zipped,entry,row,check):
    if not _positive(row.get('bytes'),MAX_DLL_BYTES) or row['bytes']!=entry.file_size or not _digest(row.get('sha256')) or type(row.get('machine')) is not int or row['machine']!=0xaa64:
        raise ValueError('Writer DLL descriptor differs')
    with zipped.open(entry) as stream:
        header=stream.read(min(entry.file_size,1048576+26))
    if len(header)<64 or header[:2]!=b'MZ':raise ValueError('Writer DLL has invalid PE header')
    offset=struct.unpack_from('<I',header,60)[0]
    if not 64<=offset<=1048576 or offset+26>len(header) or header[offset:offset+4]!=b'PE\0\0' or struct.unpack_from('<H',header,offset+4)[0]!=0xaa64 or struct.unpack_from('<H',header,offset+24)[0]!=0x20b or not struct.unpack_from('<H',header,offset+22)[0]&0x2000:
        raise ValueError('Writer DLL is not native ARM64 PE32+')
    if _entry_hash(zipped,entry,check)!=row['sha256']:raise ValueError('Writer DLL byte hash differs')


def _members(zipped,proof,lock,source,check):
    entries=zipped.infolist();aliases=set();nodes={};spellings={};total=0
    if not entries or len(entries)>payload.MAX_FILES:raise ValueError('Writer archive count exceeds bound')
    for entry in entries:
        _check(check);name=payload._name(entry.filename.rstrip('/'));key=name.casefold();directory=entry.is_dir();kind=stat.S_IFMT(entry.external_attr>>16)
        if (key in aliases or entry.flag_bits&1 or entry.external_attr&0x400 or kind not in ((0,stat.S_IFDIR) if directory else (0,stat.S_IFREG))
                or entry.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) or directory and entry.file_size!=0
                or not directory and entry.external_attr&0x10 or entry.file_size>MAX_MEMBER_BYTES
                or key in ('calc-dispatch-diagnostic.json','program/opengeul-calc-dispatch-diagnostic.json','opengeul-branding.json')
                or name.split('/')[0].casefold() in ('hwp','office','worker',payload.INVENTORY)):
            raise ValueError('Unsafe or foreign-family Writer archive member')
        aliases.add(key);nodes[key]=directory
        parts=name.split('/')
        for index in range(1,len(parts)+1):
            prefix='/'.join(parts[:index]);folded=prefix.casefold()
            if folded in spellings and spellings[folded]!=prefix:raise ValueError('Writer archive directory case alias')
            spellings[folded]=prefix
        total+=entry.file_size
        if total>MAX_EXTRACTED_BYTES:raise ValueError('Writer archive total size exceeds bound')
    for name in nodes:
        for parent in Path(name).parents:
            if str(parent)!='.' and nodes.get(parent.as_posix()) is False:raise ValueError('Writer file/directory collision')
    for name in (OVERLAY,MARKER,*BINARIES,'program/soffice.bin','program/soffice.exe','program/python.exe'):
        if nodes.get(name.casefold()) is not False or name not in zipped.namelist():raise ValueError('Writer runtime missing canonical required member')
    root_raw=_entry_bytes(zipped,zipped.getinfo(OVERLAY),payload.MAX_METADATA,check)
    program_raw=_entry_bytes(zipped,zipped.getinfo(MARKER),payload.MAX_METADATA,check)
    if root_raw!=program_raw:raise ValueError('Writer runtime marker bytes differ')
    marker=payload._json_bytes(root_raw,OVERLAY)
    if (type(marker) is not dict or set(marker)!=MARKER_KEYS or not _same(marker,proof.get('writerServerObserverRuntime')) or marker.get('schemaVersion')!=1 or type(marker['schemaVersion']) is not int
            or marker.get('kind')!=FAMILY or marker.get('family')!=FAMILY or marker.get('coreCommit')!=CORE
            or any(marker.get(k)!=lock[k] for k in ('sourceCommit','sourceTree','sourceLockSha256','patchSha256'))
            or not _same(marker.get('wireSchema'),source['wireSchema']) or marker.get('requiredRebuiltLibraries')!=['UAccCOM','winaccessibility']
            or any(marker.get(k) is not False for k in ('fullEngineQualified','acceptanceEligible','guiVerified'))
            or any(type(marker.get(k)) is not int or marker[k]!=v for k,v in [('ipcVersion',1),('sinkAbiVersion',2),('mappingBytes',131328),('descriptorSchemaVersion',1)])
            or type(marker.get('binaries')) is not list or any(type(r) is not dict or set(r)!=set(('path','bytes','sha256','machine')) for r in marker['binaries'])
            or [r.get('path') for r in marker['binaries']]!=list(BINARIES)):
        raise ValueError('Writer marker source/ABI/DLL pair differs')
    for row in marker['binaries']:_native_dll(zipped,zipped.getinfo(row['path']),row,check)
    return entries,marker


@contextmanager
def _authenticated(artifact,diagnostic_lock,source_lock,*,archive=None,receipt=None,check=None):
    _check(check);lock,source,source_lock=_lock(diagnostic_lock,source_lock,check)
    artifact=_local(artifact)
    if payload._kind(artifact).st_size!=lock['artifactSize'] or _hash(artifact,check)!=lock['artifactSha256']:raise ValueError('Writer outer archive differs from external pin')
    with zipfile.ZipFile(artifact) as outer,tempfile.TemporaryDirectory(prefix='writer-auth-') as temporary:
        entries=outer.infolist()
        if len(entries)!=2 or {e.filename for e in entries}!={ENGINE,RECEIPT}:raise ValueError('Writer outer family differs')
        for entry in entries:
            if entry.is_dir() or entry.flag_bits&1 or entry.external_attr&0x410 or stat.S_IFMT(entry.external_attr>>16) not in (0,stat.S_IFREG) or entry.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):raise ValueError('Unsafe Writer outer member')
        raw=_entry_bytes(outer,outer.getinfo(RECEIPT),payload.MAX_METADATA,check)
        proof=_receipt(payload._json_bytes(raw,RECEIPT),lock,source)
        inner=outer.getinfo(ENGINE)
        if inner.file_size!=proof['artifact']['size'] or _entry_hash(outer,inner,check)!=proof['artifact']['sha256']:raise ValueError('Writer authenticated inner digest differs')
        if receipt is not None and _raw(_local(receipt),payload.MAX_METADATA,check)!=raw:raise ValueError('Writer receipt differs from authenticated outer bytes')
        if archive is not None:
            archive=_local(archive)
            if payload._kind(archive).st_size!=inner.file_size or _hash(archive,check)!=proof['artifact']['sha256']:raise ValueError('Writer inner input differs from authenticated outer')
        else:
            archive=Path(temporary)/ENGINE
            with outer.open(inner) as src,archive.open('xb') as dst:
                while True:
                    _check(check);block=src.read(1024*1024)
                    if not block:break
                    dst.write(block)
            if _hash(archive,check)!=proof['artifact']['sha256']:raise ValueError('Writer inner copy changed')
        with zipfile.ZipFile(archive) as zipped:
            runtime_entries,marker=_members(zipped,proof,lock,source,check)
            if _hash(artifact,check)!=lock['artifactSha256']:raise ValueError('Writer outer input changed')
            yield lock,source,source_lock,proof,raw,zipped,runtime_entries,marker
        if _hash(artifact,check)!=lock['artifactSha256']:raise ValueError('Writer outer input changed after use')


def _baseline(path,commit,check):
    _check(check);path=_local(path);inventory=payload._json(path/payload.INVENTORY)
    payload.verify_payload(path,inventory);_check(check)
    if not _commit(commit) or inventory['architecture']!='arm64' or payload._json(path/'suite-provenance.json')['sourceCommit']!=commit:
        raise ValueError('Normal ARM baseline source differs')
    if any((path/p).exists() for p in ('calc-dispatch-diagnostic.json','Office/program/opengeul-calc-dispatch-diagnostic.json')):
        raise ValueError('Calc diagnostic baseline is forbidden')
    return path,inventory


def _manifest(baseline,inventory,check):
    raw=_raw(baseline/'suite-product.json',payload.MAX_METADATA,check)
    expected=inventory['files']['suite-product.json']
    if len(raw)!=expected['size'] or hashlib.sha256(raw).hexdigest()!=expected['sha256']:raise ValueError('Normal baseline manifest changed')
    return payload._json_bytes(raw,'suite-product.json')


def _byte_files(root,check,prefix=''):
    files={};aliases=set()
    def visit(folder):
        for path in sorted(folder.iterdir()):
            _check(check);name=payload._name(path.relative_to(root).as_posix());key=name.casefold()
            if key in aliases:raise ValueError('Diagnostic byte inventory case alias')
            aliases.add(key);info=payload._kind(path);directory=stat.S_ISDIR(info.st_mode);payload._layout(prefix+name,directory=directory)
            if directory:visit(path)
            elif stat.S_ISREG(info.st_mode):
                if prefix or name!=payload.INVENTORY:
                    if len(files)>=payload.MAX_FILES:raise ValueError('Diagnostic byte inventory count exceeded')
                    files[name]=dict(size=info.st_size,sha256=payload._hash(path));_check(check)
            else:raise ValueError('Diagnostic byte inventory special file')
    visit(root)
    return dict(sorted(files.items()))


def _diagnostic_inventory(root,overlay,check):
    if overlay.get('family')!=FAMILY or overlay.get('stageComplete') is not True or any(overlay.get(k) is not False for k in ('fullEngineQualified','acceptanceEligible','guiVerified')):
        raise ValueError('Writer-only inventory requires completed diagnostic authority')
    files=_byte_files(root,check)
    if payload.REQUIRED-files.keys() or any(files[n]['size']==0 for n in payload.REQUIRED):raise ValueError('Diagnostic byte inventory missing required Suite file')
    return dict(schemaVersion=1,kind='writer-server-observer-diagnostic-byte-inventory',architecture='arm64',fullEngineQualified=False,acceptanceEligible=False,guiVerified=False,files=dict(sorted(files.items())))


def _expected_office(zipped,entries,manifest,check):
    with tempfile.TemporaryDirectory(prefix='writer-office-proof-') as temporary:
        root=Path(temporary)
        (root/OVERLAY).write_text(json.dumps(dict(family=FAMILY,fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)),encoding='utf-8')
        raw=root/'raw';raw.mkdir();_extract_runtime(zipped,entries,raw,check)
        office=root/'Office'
        _check(check);brand_runtime(raw,office,manifest);_check(check)
        return _byte_files(office,check,'Office/')


def _extract_runtime(zipped,entries,raw,check):
    for entry in entries:
        _check(check);target=raw/entry.filename.rstrip('/')
        if entry.is_dir():target.mkdir(parents=True,exist_ok=True)
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            with zipped.open(entry) as source,target.open('xb') as destination:
                while True:
                    _check(check);block=source.read(1024*1024)
                    if not block:break
                    destination.write(block)
            if target.stat().st_size!=entry.file_size:raise ValueError('Writer extracted member size changed')


def _overlay(marker,lock,inventory,baseline,commit,raw,check):
    return dict(**marker,diagnosticOnly=True,baselineMetadataOnly=True,baselineSuiteSourceCommit=commit,
        baselineInventorySha256=_hash(baseline/payload.INVENTORY,check),stageComplete=False,
        inputs=dict(artifactSha256=lock['artifactSha256'],artifactBytes=lock['artifactSize'],receiptSha256=hashlib.sha256(raw).hexdigest()))


def stage(*,baseline,artifact,archive,receipt,source_lock,diagnostic_lock,output,expected_suite_source_commit,check=None):
    baseline,inventory=_baseline(baseline,expected_suite_source_commit,check);output=_local(output)
    inputs=[_local(p) for p in (artifact,archive,receipt,source_lock,diagnostic_lock)]
    if output.exists() or output==baseline or baseline in output.parents or output in baseline.parents or any(output==p or output in p.parents for p in inputs):
        raise ValueError('Fresh diagnostic output outside baseline and inputs required')
    with _authenticated(artifact,diagnostic_lock,source_lock,archive=archive,receipt=receipt,check=check) as (lock,source,source_lock,proof,raw,zipped,entries,marker):
        overlay=_overlay(marker,lock,inventory,baseline,expected_suite_source_commit,raw,check)
        output.mkdir(parents=True,exist_ok=False)
        with (output/OVERLAY).open('x',encoding='utf-8') as marker_file:marker_file.write(json.dumps(overlay,sort_keys=True)+'\n')
        _check(check)
        shutil.copytree(baseline,output,dirs_exist_ok=True,ignore=lambda folder,names:['Office'] if Path(folder)==baseline else [])
        _check(check)
        (output/SOURCE_LOCK).write_bytes(source_lock);(output/RECEIPT).write_bytes(raw)
        with tempfile.TemporaryDirectory(prefix='raw-runtime-',dir=output) as extracted:
            raw_runtime=Path(extracted);_extract_runtime(zipped,entries,raw_runtime,check)
            _check(check);brand_runtime(raw_runtime,output/'Office',_manifest(baseline,inventory,check));_check(check)
        payload.verify_payload(baseline,inventory);_check(check)
        for row in marker['binaries']:
            path=output/'Office'/row['path']
            if path.stat().st_size!=row['bytes'] or _hash(path,check)!=row['sha256']:raise ValueError('Writer branding changed DLL pair')
        overlay['stageComplete']=True
        (output/OVERLAY).write_text(json.dumps(overlay,sort_keys=True)+'\n',encoding='utf-8')
        fresh=_diagnostic_inventory(output,overlay,check)
        for name,record in inventory['files'].items():
            if not name.startswith('Office/') and fresh['files'].get(name)!=record:raise ValueError('Writer changed non-Office baseline bytes')
        (output/payload.INVENTORY).write_text(json.dumps(fresh,sort_keys=True)+'\n',encoding='utf-8')
    return fresh


def require_writer_observer_stage(*,output,baseline,artifact,diagnostic_lock,source_lock,expected_suite_source_commit,check=None):
    baseline,inventory=_baseline(baseline,expected_suite_source_commit,check);output=_local(output)
    with _authenticated(artifact,diagnostic_lock,source_lock,check=check) as (lock,source,source_lock,proof,raw,zipped,entries,marker):
        expected=_overlay(marker,lock,inventory,baseline,expected_suite_source_commit,raw,check);expected['stageComplete']=True
        if not _same(_json(output/OVERLAY),expected) or _raw(output/SOURCE_LOCK,65536,check)!=source_lock or _raw(output/RECEIPT,payload.MAX_METADATA,check)!=raw:
            raise ValueError('Writer stage source authority changed')
        for name in (OVERLAY,MARKER):
            if _raw(output/'Office'/name,payload.MAX_METADATA,check)!=_entry_bytes(zipped,zipped.getinfo(name),payload.MAX_METADATA,check):raise ValueError('Writer original marker bytes changed')
        fresh=_diagnostic_inventory(output,expected,check)
        if not _same(_json(output/payload.INVENTORY),fresh):raise ValueError('Writer diagnostic byte inventory changed')
        for name,record in inventory['files'].items():
            if not name.startswith('Office/') and fresh['files'].get(name)!=record:raise ValueError('Writer non-Office baseline bytes changed')
        expected_office=_expected_office(zipped,entries,_manifest(baseline,inventory,check),check)
        actual_office={name[len('Office/'):]:record for name,record in fresh['files'].items() if name.startswith('Office/')}
        if actual_office!=expected_office:raise ValueError('Writer Office bytes differ from authenticated archive and branding')
        for row in marker['binaries']:
            if _hash(output/'Office'/row['path'],check)!=row['sha256']:raise ValueError('Writer staged DLL pair changed')
        payload.verify_payload(baseline,inventory);_check(check)
        _check(check)
        return dict(family=FAMILY,architecture='arm64',payloadRoot=str(output),runtimeRoot=str(output/'Office'),
            sourceCommit=lock['sourceCommit'],sourceTree=lock['sourceTree'],sourceLockSha256=lock['sourceLockSha256'],patchSha256=lock['patchSha256'],wireSchemaSha256=lock['wireSchemaSha256'],
            ipcVersion=1,sinkAbiVersion=2,mappingBytes=131328,descriptorSchemaVersion=1,binaries=marker['binaries'],diagnosticByteInventorySha256=_hash(output/payload.INVENTORY,check),
            diagnosticOnly=True,fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','artifact','archive','receipt','source-lock','diagnostic-lock','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--expected-suite-source-commit',required=True)
    try:result=stage(**vars(parser.parse_args(argv)))
    except Exception:
        print(json.dumps(dict(family=FAMILY,passed=False,fullEngineQualified=False,acceptanceEligible=False,guiVerified=False,error='writer-stage-rejected')));return 1
    print(json.dumps(dict(family=FAMILY,diagnosticBytesVerified=True,fileCount=len(result['files']),fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)));return 0


if __name__=='__main__':raise SystemExit(main())
