"""Capture one owned source-built TWAIN component; never qualify an engine."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import sys
import time
import zipfile

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from suite import payload

class Failure(RuntimeError):
    def __init__(self,phase):self.phase=phase;super().__init__('source_twain_capture_failed')

def _read(path,limit,deadline):
    path=payload._source_companion_regular(path)
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno())
        if before.st_size>limit:raise Failure(1)
        chunks=[];count=0
        while True:
            if time.monotonic()>=deadline:raise Failure(8)
            chunk=stream.read(min(65536,limit+1-count))
            if not chunk:break
            chunks.append(chunk);count+=len(chunk)
            if count>limit:raise Failure(1)
        after=os.fstat(stream.fileno());current=path.stat()
        identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
        if identity(before)!=identity(after) or identity(before)!=identity(current):raise Failure(1)
        return b''.join(chunks)

def _hash(path,size,deadline):
    path=payload._source_companion_regular(path);digest=hashlib.sha256()
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno());count=0
        if type(size) is not int or not 1<=size<=1024*1024*1024 or before.st_size!=size:raise Failure(3)
        while True:
            if time.monotonic()>=deadline:raise Failure(8)
            chunk=stream.read(1024*1024)
            if not chunk:break
            count+=len(chunk);digest.update(chunk)
            if count>size:raise Failure(3)
        after=os.fstat(stream.fileno());current=path.stat()
        identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
        if count!=size or identity(before)!=identity(after) or identity(before)!=identity(current):raise Failure(3)
    return digest.hexdigest()

def capture(source,runtime,stage_path,context_path,evidence,*,validate=False):
    source=Path(source).absolute();runtime=Path(runtime).absolute();evidence=Path(evidence).absolute()
    stage_path=Path(stage_path).absolute();context_path=Path(context_path).absolute();deadline=time.monotonic()+50
    phase=1;observed=None;diagnostic=payload._source_companion_diagnostic()
    try:
        if stage_path!=evidence/'installed-runtime-stage.json':raise Failure(1)
        if not validate and ((evidence/'source-twain-proof.json').exists() or (evidence/'source-twain').exists()):raise Failure(1)
        context=json.loads(_read(context_path,16384,deadline))
        if (type(context) is not dict or set(context)!={'schemaVersion','architecture','coreCommit','buildBinding','stageReceiptSha256','sourceEvidenceDirectory','cliPolicyEvidence','x86StaticRuntimeEvidence'}
                or type(context['schemaVersion']) is not int or context['schemaVersion']!=1
                or context['architecture']!='x64' or context['coreCommit']!=payload._SOURCE_COMPANION_CORE
                or type(context['stageReceiptSha256']) is not str or not payload.SHA.fullmatch(context['stageReceiptSha256'])):raise Failure(1)
        payload._source_companion_binding(context['buildBinding'])
        phase=2;retained=[];location_retained=[]
        policy=context['cliPolicyEvidence']
        directory_value=context['sourceEvidenceDirectory']
        if type(directory_value)is not str or not Path(directory_value).is_absolute() or str(Path(directory_value))!=directory_value or '..' in Path(directory_value).parts:raise Failure(2)
        source_evidence=Path(directory_value)
        if source_evidence!=evidence/'source-recipe' or type(policy) is not dict or set(policy)!={'original','effective'}:raise Failure(2)
        crt_sources=payload._source_companion_static_runtime_sources(source,source_evidence,context['x86StaticRuntimeEvidence'],_read,deadline)
        original_path=Path(policy['original']).absolute();effective_path=Path(policy['effective']).absolute()
        if (original_path.parent!=source_evidence or effective_path.parent!=source_evidence
                or original_path.name!='original-x64-CliNativeLibrary_cli_cppuhelper.mk'
                or effective_path.name!='effective-x64-CliNativeLibrary_cli_cppuhelper.mk'):raise Failure(2)
        for pin in payload.SOURCE_TWAIN_SOURCE_PINS:
            effective=_read(source/pin['path'],512*1024,deadline)
            if pin['path']=='cli_ure/CliNativeLibrary_cli_cppuhelper.mk':
                original=_read(original_path,512*1024,deadline)
                if _read(effective_path,512*1024,deadline)!=effective:raise Failure(2)
            elif pin['path'] in crt_sources:original=crt_sources[pin['path']]['original']
            else:original=effective
            if (len(original)!=pin['bytes'] or hashlib.sha256(original).hexdigest()!=pin['sha256']
                    or hashlib.sha1(b'blob '+str(len(original)).encode()+b'\0'+original).hexdigest()!=pin['gitBlob']
                    or len(effective)!=pin['effectiveBytes'] or hashlib.sha256(effective).hexdigest()!=pin['effectiveSha256']):raise Failure(2)
            retained.append((pin,original,effective))
        raw_config=_read(source/'config_host.mk',2*1024*1024,deadline)
        config=raw_config.decode('utf-8','strict')
        compilers=re.findall(r'^[ \t]*(?:export[ \t]+)?COM[ \t]*=[ \t]*(.*)$',config,re.M)
        if len(compilers)!=1 or compilers[0].strip()!='MSC':raise Failure(2)
        instroot,location_contract=payload._source_companion_locations(source,runtime,raw_config)
        for pin in payload.SOURCE_COMPANION_LOCATION_PINS:
            data=_read(source/pin['path'],512*1024,deadline)
            if len(data)!=pin['bytes'] or hashlib.sha256(data).hexdigest()!=pin['sha256'] or hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=pin['gitBlob']:raise Failure(2)
            location_retained.append((pin,data))
        configured=re.findall(r'^[ \t]*(?:export[ \t]+)?CXX_X86_BINARY[ \t]*[:?+]?=[ \t]*(.*)$',config,re.M)
        if len(configured)!=1 or not configured[0].strip():raise Failure(2)
        for name,expected in (('OS','WNT'),('CPUNAME','X86_64')):
            values=re.findall(r'^[ \t]*(?:export[ \t]+)?'+name+r'[ \t]*[:?+]?=[ \t]*(.*)$',config,re.M)
            if len(values)!=1 or values[0].strip()!=expected:raise Failure(2)
        phase=3;stage_raw=_read(stage_path,16*1024*1024,deadline)
        if hashlib.sha256(stage_raw).hexdigest()!=context['stageReceiptSha256']:raise Failure(3)
        stage=json.loads(stage_raw)
        if (stage.get('kind')!='source-built-installed-runtime-stage' or stage.get('passed') is not True or stage.get('architecture')!='x64'
                or Path(stage.get('runtimeRoot','')).absolute()!=runtime or type(stage.get('files')) is not list
                or not 1<=len(stage['files'])<=100000):raise Failure(3)
        selected={}
        for name in ('program/twain32shim.exe','program/scnlo.dll'):
            rows=[r for r in stage['files'] if type(r) is dict and str(r.get('path','')).casefold()==name.casefold()]
            if len(rows)!=1 or rows[0]['path']!=name:raise Failure(3)
            selected[name]=rows[0]
        archives=[r for r in stage['archives'] if r.get('path')==selected['program/twain32shim.exe'].get('archivePath')]
        if (len(archives)!=1 or archives[0].get('kind')!='main'
                or selected['program/scnlo.dll'].get('archivePath')!=archives[0]['path']):raise Failure(3)
        archive=archives[0]
        archive_path=Path(archive['path']).absolute()
        if '..' in archive_path.parts or not archive_path.is_relative_to(source/'workdir/installation'):raise Failure(3)
        if _hash(Path(archive['path']),archive['bytes'],deadline)!=archive['sha256']:raise Failure(3)
        with zipfile.ZipFile(archive_path) as archive_zip:
            names=archive_zip.namelist()
            if not 1<=len(names)<=100000 or len(set(n.casefold() for n in names))!=len(names):raise Failure(3)
            for name,row in selected.items():
                member=row.get('archiveMember')
                if type(member) is not str or '..' in Path(member).parts or not member.endswith('/'+name):raise Failure(3)
                entry=archive_zip.getinfo(member)
                if entry.file_size!=row.get('bytes') or not 64<=entry.file_size<=16*1024*1024:raise Failure(3)
                digest=hashlib.sha256();count=0
                with archive_zip.open(entry) as stream:
                    while True:
                        if time.monotonic()>=deadline:raise Failure(8)
                        chunk=stream.read(65536)
                        if not chunk:break
                        count+=len(chunk);digest.update(chunk)
                        if count>entry.file_size:raise Failure(3)
                if count!=entry.file_size or digest.hexdigest()!=row.get('sha256'):raise Failure(3)
        phase=4;observed=payload._source_companion_observe_pe(1,runtime/'program/twain32shim.exe',diagnostic)
        helper=payload._source_companion_observe_pe(2,runtime/'program/scnlo.dll',diagnostic,read_exports=False)
        target=payload._source_companion_observe_pe(3,instroot/'program/twain32shim.exe',diagnostic)
        helper_target=payload._source_companion_observe_pe(4,instroot/'program/scnlo.dll',diagnostic,read_exports=False)
        for role,name,actual,built in [(1,'program/twain32shim.exe',observed,target),(2,'program/scnlo.dll',helper,helper_target)]:
            if not payload._source_companion_observe_join(role,actual,selected[name].get('bytes'),selected[name].get('sha256'),diagnostic):raise Failure(4)
            if not payload._source_companion_observe_join(role+2,built,actual['size'],actual['sha256'],diagnostic):raise Failure(4)
        component=dict(schemaVersion=2,kind='source-built-x86-twain-companion',architecture='x64',coreCommit=payload._SOURCE_COMPANION_CORE,
            path='program/twain32shim.exe',role='x86CompatibilityHelper',machine=observed['machine'],size=observed['size'],sha256=observed['sha256'],
            buildBinding=context['buildBinding'],sourceIntent='twain-32bit-driver-process-bridge',sourceProofs=payload.SOURCE_TWAIN_SOURCE_PINS,
            staticRuntimeSourceProofs=payload.SOURCE_X86_COMPANION_CRT_PINS,configuredX86=True,linkTarget=dict(kind='gbuild-bookkeeping-prefix',path='workdir/LinkTarget/Executable/twain32shim.exe'),
            buildOutput=dict(path='instdir/program/twain32shim.exe',size=target['size'],sha256=target['sha256']),
            nativePeerBuildOutput=dict(path='instdir/program/scnlo.dll',size=helper_target['size'],sha256=helper_target['sha256']),locationContract=location_contract,
            nativePeer=dict(path='program/scnlo.dll',machine=helper['machine'],role='nativeX64',size=helper['size'],sha256=helper['sha256']),
            installedArchive=dict(kind='main',size=archive['bytes'],sha256=archive['sha256'],stageReceiptSha256=context['stageReceiptSha256']),
            exports=observed['exports'],imports=observed['imports'],dependencyPolicy='x86-twain-os-only-no-private-shadow-v1',
            fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
        phase=5;payload._source_twain_component(component,context['buildBinding']);payload._source_twain_runtime(runtime,component)
        phase=6;retained_root=evidence/'source-twain'
        if not validate:retained_root.mkdir()
        for pin,original,effective in retained:
            for phase_name,data,expected_sha in [('original',original,pin['sha256']),('effective',effective,pin['effectiveSha256'])]:
                path=retained_root/phase_name/pin['path']
                if not validate:
                    path.parent.mkdir(parents=True,exist_ok=True)
                    with path.open('xb') as stream:stream.write(data)
                if _hash(path,len(data),deadline)!=expected_sha:raise Failure(6)
        for pin in payload.SOURCE_X86_COMPANION_CRT_PINS:
            for side in ('original','effective'):
                raw=crt_sources[pin['path']][side];path=retained_root/'static-runtime'/side/pin['path']
                if not validate:
                    path.parent.mkdir(parents=True,exist_ok=True)
                    with path.open('xb') as stream:stream.write(raw)
                if _hash(path,len(raw),deadline)!=hashlib.sha256(raw).hexdigest():raise Failure(6)
        for pin,data in location_retained:
            path=retained_root/'location'/'source'/pin['path']
            if not validate:
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('xb') as stream:stream.write(data)
            if _hash(path,len(data),deadline)!=pin['sha256']:raise Failure(6)
        encoded=json.dumps(component,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
        if len(encoded)>65536 or time.monotonic()>=deadline:raise Failure(8)
        if validate:
            phase=7
            if _read(evidence/'source-twain-proof.json',65536,deadline)!=encoded:raise Failure(7)
        else:
            with (evidence/'source-twain-proof.json').open('xb') as stream:stream.write(encoded)
        return component
    except BaseException as error:
        payload._source_companion_closed_exception(error,diagnostic,capture,Failure)
        failure=dict(schemaVersion=1,kind='source-twain-capture-failure',phase=phase,passed=False,
            fullEngineQualified=False,acceptanceEligible=False,guiVerified=False,diagnostic=diagnostic)
        if observed:
            failure.update(machine=observed['machine'],optionalMagic=observed['optionalMagic'],size=observed['size'],sha256=observed['sha256'],
                clrRva=observed['clrRva'],clrSize=observed['clrSize'],exportCount=len(observed['exports']))
            imports=observed['imports']['normal']+observed['imports']['delay']
            failure['osImports']=sorted(set(n for n in imports if n in payload._SOURCE_TWAIN_OS_IMPORTS))
            failure['vcImports']=sorted(set(n for n in imports if re.fullmatch(r'(?:msvcp|vcruntime|concrt)[0-9][a-z0-9_.-]*\.dll',n)))
            failure['unknownImportCount']=sum(n not in failure['osImports'] and n not in failure['vcImports'] for n in imports)
            failure['unknownImports']={key:[n for n in observed['imports'][key] if n not in failure['osImports'] and n not in failure['vcImports']] for key in ('normal','delay')}
        try:
            with (evidence/'source-twain-failure.json').open('xb') as stream:stream.write(json.dumps(failure,sort_keys=True).encode()+b'\n')
        except BaseException:pass
        raise Failure(phase) from None

def main(argv=None):
    class Parser(argparse.ArgumentParser):
        def error(self,message):raise Failure(1)
    try:
        parser=Parser(add_help=False)
        for name in ('source','runtime','stage','context','evidence'):parser.add_argument('--'+name,type=Path,required=True)
        parser.add_argument('--validate',action='store_true')
        args=parser.parse_args(argv);capture(args.source,args.runtime,args.stage,args.context,args.evidence,validate=args.validate)
        return 0
    except BaseException:return 1

if __name__=='__main__':raise SystemExit(main())
