"""Native ARM64, file-only call inspection under a caller-owned analysis budget."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'e2e'))
import ascii_message_preparation as shared
import native_compiler_tools

_classifier_spec=importlib.util.spec_from_file_location('mutex_call_reason_codes',Path(__file__).with_name('mutex_call_classification.py'))
_classifier=importlib.util.module_from_spec(_classifier_spec)
_classifier_spec.loader.exec_module(_classifier)
REASON_CODES=_classifier.REASON_CODES

MAX_FILE = 32*1024*1024
MAX_OUTPUT = 256*1024


def _read(path, limit, budget, *, empty=False):
    budget.now()
    path=shared._absolute(path)
    before=path.stat()
    assert path.is_file() and 0 <= before.st_size <= limit, 'Static inspection file size rejected'
    with path.open('rb') as stream:
        opened=os.fstat(stream.fileno())
        raw=stream.read(limit+1)
        after=os.fstat(stream.fileno())
    budget.now()
    final=path.stat()
    budget.now()
    def identity(value,fields=native_compiler_tools.STAT_FIELDS):
        return tuple(getattr(value,key) for key in fields)
    # Windows path and held-FD ctime can differ; compare each API to itself.
    assert identity(opened)==identity(after), 'Static inspection held file changed'
    assert identity(before)==identity(final), 'Static inspection path changed'
    fields=('st_dev','st_ino','st_size')
    assert identity(before,fields)==identity(opened,fields), 'Static inspection file identity differs'
    assert len(raw)==before.st_size and (empty or raw), 'Static inspection read rejected'
    return raw


def _stages(rows):
    result=[]
    for stage in rows[:3]:
        row={k:stage[k] for k in ('stage','startedAt','finishedAt','natural','queryCount',
             'droppedSamples','handlesClosed','forcedOwnedJobCleanup') if k in stage}
        row['cleanupErrorTypes']=[v['type'] for v in stage.get('cleanupErrors',[])[:4]]
        if 'error' in stage:row['errorType']=stage['error']['type']
        sample=stage.get('cleanupLastSample') or (stage.get('samples') or [None])[-1]
        if sample:
            row['root']={k:sample['root'][k] for k in ('waitResult','exitCode')}
            row['activeProcesses']=sample['activeProcesses']
            row['accountingSucceeded']=sample['querySucceeded']
        result.append(row)
    return result


def _range(base, extent, *, maximum):
    assert type(base) is int and 0 < base < 2**64 and base%65536==0
    assert type(extent) is dict and set(extent)=={'beginRva','endRvaExclusive'}
    begin,end=extent['beginRva'],extent['endRvaExclusive']
    assert type(begin) is int and type(end) is int and 0 < begin < end <= 2**32
    assert begin%4==end%4==0 and end-begin<=maximum and base+end<2**64
    return f'/RANGE:0x{base+begin:X},0x{base+end-4:X}'


def inspect_calls(production_bytes,fixture_bytes, *, production_base,production_range,
                  fixture_base,fixture_range,fixture_target,condition_iat,budget,classify):
    budget.now()
    assert budget.deadline==budget.started+30 and budget.work_deadline==budget.deadline-3
    ranges=[_range(fixture_base,fixture_range,maximum=100),
            _range(production_base,production_range,maximum=100)]
    assert type(fixture_target) is int and 0 < fixture_target < 2**32
    assert type(condition_iat) is int and 0 < condition_iat < 2**32
    for data in (fixture_bytes,production_bytes):
        assert type(data) is bytes and 0 < len(data) <= MAX_FILE
    shared.native_arch.validate_native_architecture(shared.native_arch.observe_native_architecture(),'arm64')
    budget.now()
    folder=Path(tempfile.mkdtemp(prefix='opengeul-static-calls-')).resolve()
    receipt=dict(schemaVersion=1,kind='native-static-call-inspection',success=False,
                 attributionProved=False,temporaryFilesRemoved=False,stages=[])
    internal={'stages':[]};primary=None
    try:
        runtime=shared._Runtime()
        vswhere=shared._absolute(Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Microsoft Visual Studio/Installer/vswhere.exe')
        assert vswhere.is_file(), 'Existing MSVC discovery unavailable'
        discovery=folder/'discover.cmd'
        discovery.write_text('@echo off\n"%~1" -utf8 -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.ARM64 -property installationPath >"%~2" 2>"%~3"\nexit /b %errorlevel%\n',encoding='ascii')
        shared._run_stage(runtime,folder,'discovery',discovery,budget,internal,
                          [vswhere,folder/'discovery.stdout',folder/'discovery.stderr'])
        install=_read(folder/'discovery.stdout',32768,budget).decode('utf-8-sig').strip()
        _read(folder/'discovery.stderr',MAX_OUTPUT,budget,empty=True)
        assert install and '\n' not in install and '\r' not in install, 'Ambiguous MSVC installation'
        install=shared._absolute(Path(install))
        version=_read(install/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt',128,budget).decode('ascii').strip()
        assert re.fullmatch(r'[0-9]{2}\.[0-9]{2}\.[0-9]{4,6}',version), 'Invalid MSVC version'
        tool=install/'VC/Tools/MSVC'/version/'bin/Hostarm64/arm64/dumpbin.exe'
        tool_pin=native_compiler_tools.pin_native_tool(tool,'arm64',check=budget.now)
        receipt['tool']={k:tool_pin[k] for k in ('machine','bytes','sha256')}
        for index,(label,data,base,extent) in enumerate((
            ('fixture',fixture_bytes,fixture_base,fixture_range),
            ('production',production_bytes,production_base,production_range))):
            budget.now()
            target=folder/(label+'.dll')
            target.write_bytes(data)
            assert _read(target,MAX_FILE,budget)==data, 'Materialized input differs'
            shared.native_arch.require_native_pe(target,'arm64');budget.now()
            script=folder/'compile.cmd'
            script.write_text('@echo off\n"%~1" /NOPDB /DISASM:NOBYTES '+ranges[index]+' "%~2" >"%~3" 2>"%~4"\nexit /b %errorlevel%\n',encoding='ascii')
            assert native_compiler_tools.pin_native_tool(tool,'arm64',check=budget.now)==tool_pin, 'Disassembler changed'
            shared._run_stage(runtime,folder,label+'-disassembly',script,budget,internal,
                              [tool,target,folder/'query.stdout',folder/'query.stderr'])
            assert _read(target,MAX_FILE,budget)==data, 'Inspected input changed'
            assert native_compiler_tools.pin_native_tool(tool,'arm64',check=budget.now)==tool_pin, 'Disassembler changed'
            output=_read(folder/'query.stdout',MAX_OUTPUT,budget)
            error=_read(folder/'query.stderr',MAX_OUTPUT,budget,empty=True)
            assert not error.strip(), 'Disassembler stderr is not empty'
            classified=classify(output.decode('utf-8-sig'),image_base=base,function_range=extent,
                               condition_iat=condition_iat if index else None,
                               fixture_target=fixture_target if not index else None)
            budget.now()
            assert type(classified) is dict and classified.get('complete') is True
            assert len(json.dumps(classified,allow_nan=False))<=8192, 'Classification receipt bound'
            if index==0:assert classified.get('fixtureValidated') is True, 'Fixture disassembly was not validated'
            receipt[label]=classified
            receipt[label+'Sha256']=hashlib.sha256(data).hexdigest()
        receipt.update(success=True,finishedAt=budget.now())
    except BaseException as exc:
        primary=exc
        receipt.update(errorType=type(exc).__name__)
        reason=getattr(exc,'reason_code',None)
        if type(reason) is str and reason in REASON_CODES:
            receipt['classificationReason']=reason
        raise
    finally:
        receipt['stages']=_stages(internal['stages'])
        try:
            shutil.rmtree(folder)
            assert not folder.exists(), 'Private disassembly cleanup remained incomplete'
            receipt['temporaryFilesRemoved']=True
            budget.now(cleanup=True)
        except BaseException as cleanup:
            receipt['success']=False
            receipt['cleanupErrorType']=type(cleanup).__name__
            if primary is None:
                cleanup.callInspection=receipt
                raise
        if primary is not None:primary.callInspection=receipt
    return receipt
