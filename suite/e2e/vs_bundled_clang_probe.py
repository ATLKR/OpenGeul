"""Read-only, x64-only VS-bundled Clang observation; never compiler admission.

This owns an independent 30/27 second diagnostic budget. Original observer
preparation, consumer authority, physical cases and their budgets are untouched.
"""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import time

import ascii_message_preparation as prep
from native_compiler_tools import pin_native_tool, STAT_FIELDS

_spec=importlib.util.spec_from_file_location('bundled_version_query',Path(__file__).with_name('vs_bundled_clang_version.py'))
helper_module=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helper_module)
_run_stage=prep._run_stage
TOOLS=('clang-cl.exe','lld-link.exe')
SYSTEM_DLL_NAMES=frozenset(x.casefold() for x in ('ADVAPI32.dll','KERNEL32.dll','ntdll.dll','ole32.dll','OLEAUT32.dll','SHELL32.dll','VERSION.dll'))
TOP_KEYS={'schemaVersion','kindCode','diagnosticOnly','acceptance','productionBudgetChanged','resultCode',
          'productionQualified','observedComplete','knownUnavailable','majorSupported',
          'sourceHeadWords','nativeHostMachine','sourceCount','sourcePinsBeforeAfterEqual','selectionStable',
          'cacheUsed','discoveryRequests','versionRequestsTotal','totalLimitMs','workLimitMs','elapsedMs',
          'pendingHandleCount','tools','stages','postPinResultCode','failureStageCode',
          'discoveryHelperResultCode','discoveryCaptureObservation','discoveryQuery','discoveryParseStage'}
TOOL_KEYS={'present','presenceKnown','knownUnavailable','observedComplete','majorSupported','peVerified','resultCode','postPinResultCode',
           'beforePinned','afterPinned','pinsEqual','statJoinMatched','bytes','machine','sha256Words',
           'major','minor','versionExit','versionRequests','naturalJob','jobEmpty','handlesClosed',
           'queryPid','queryCreationTime','queryNaturalExit','queryHandleClosed','helperResultCode','captureObservation'}
STAGE_KEYS={'stageCode','rootExit','natural','jobEmpty','handlesClosed','lastActive','queryCount','pid','creationTime'}

class ProbeFailure(Exception):
    def __init__(self,code):self.code=code

def finite_environment(windows,temp):
    windows,temp=prep._absolute(windows),prep._absolute(temp)
    program_data=os.environ.get('ProgramData')
    assert type(program_data) is str and 0<len(program_data)<=4096
    assert not program_data.replace('\\','/').startswith('//') and not any(c in program_data for c in '\0\r\n')
    program_data=prep._absolute(program_data)
    for part in (program_data,*program_data.parents):
        assert not getattr(part.lstat(),'st_file_attributes',0)&0x400, 'Reparse ProgramData path'
    assert program_data.is_dir(), 'ProgramData directory required'
    program_data=program_data.resolve(strict=True)
    assert not str(program_data).replace('\\','/').startswith('//')
    program_data=prep._absolute(program_data)
    return dict(COMSPEC=str(windows/'System32/cmd.exe'),SystemRoot=str(windows),WINDIR=str(windows),
                PATH=str(windows/'System32'),TEMP=str(temp),TMP=str(temp),
                PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',ProgramData=str(program_data))

class _Runtime(prep._Runtime):
    def __init__(self,environment):
        super().__init__()
        self.environment=environment
        self.processes=[]
    def start(self,argv,folder):
        assert Path(argv[0]) == Path(self.environment['COMSPEC']), 'Unexpected command host'
        prep._absolute(Path(argv[0]))
        process=self.native.OwnedOfficeProcess(argv,folder,environment=self.environment)
        self.processes.append(process)
        return process
    def pending_handles(self):
        return sum(bool(getattr(p,name,None)) for p in self.processes for name in ('handle','job'))

def _tool_row():
    return dict(present=False,presenceKnown=False,knownUnavailable=False,observedComplete=False,
                majorSupported=None,peVerified=False,resultCode=None,postPinResultCode=0,
                beforePinned=False,afterPinned=False,pinsEqual=False,statJoinMatched=False,
                bytes=None,machine=None,sha256Words=[None]*8,major=None,minor=None,versionExit=None,
                versionRequests=0,naturalJob=False,jobEmpty=False,handlesClosed=False,
                queryPid=None,queryCreationTime=None,queryNaturalExit=False,queryHandleClosed=False,
                helperResultCode=None,captureObservation=helper_module.capture_observation())

def _stage_numbers(row,code):
    samples=row.get('samples',[])
    last=samples[-1] if samples else {}
    root=last.get('root',{})
    empty=False
    if last.get('querySucceeded') is True and type(last.get('returnLength')) is int and last['returnLength']==48:
        raw=last.get('rawHex')
        if type(raw) is str and re.fullmatch('[0-9a-f]{96}',raw):
            total,active,terminated=struct.unpack_from('<III',bytes.fromhex(raw),36)
            empty=(type(last.get('activeProcesses')) is int and active==last['activeProcesses']==0
                   and type(last.get('totalProcesses')) is int and total==last['totalProcesses']
                   and type(last.get('terminatedProcesses')) is int and terminated==last['terminatedProcesses'])
    identity=row.get('identity',{})
    return dict(stageCode=code,rootExit=root.get('exitCode'),natural=row.get('natural') is True,
                jobEmpty=empty,handlesClosed=row.get('handlesClosed') is True and not row.get('cleanupErrors'),
                lastActive=last.get('activeProcesses'),queryCount=row.get('queryCount',0),
                pid=identity.get('pid'),creationTime=identity.get('creationTime'))

def _qualified(row,code):
    value=_stage_numbers(row,code)
    assert value['natural'] and value['jobEmpty'] and value['handlesClosed']
    assert type(value['rootExit']) is int and value['rootExit']==0
    assert type(row['samples'][-1]['root']['waitResult']) is int and row['samples'][-1]['root']['waitResult']==0
    assert type(row['cleanupErrors']) is list and not row['cleanupErrors']
    assert 'forcedOwnedJobCleanup' not in row and 'error' not in row
    assert type(value['queryCount']) is int and 1 <= value['queryCount'] <= prep.QUERY_CAP
    assert type(value['pid']) is int and value['pid']>0
    assert type(value['creationTime']) is int and value['creationTime']>0
    return value

def _stat_join(facts,pin):
    assert type(facts) is dict and set(facts)=={'pathBefore','fdBefore','fdAfter','pathAfter'}
    for snapshot in facts.values():
        assert type(snapshot) is dict and set(snapshot)==set(STAT_FIELDS)
        assert all(type(v) is int and v.bit_length()<=256 for v in snapshot.values())
        assert snapshot['st_size']==pin['bytes']
    assert facts['pathBefore']==facts['pathAfter'] and facts['fdBefore']==facts['fdAfter']
    assert all(facts['pathBefore'][k]==facts['fdBefore'][k] for k in ('st_dev','st_ino','st_size'))

def _sources(check):
    result={}
    for name in prep.SOURCES:
        check();result[name]=prep._pin(prep.SOURCE_ROOT/name);check()
    return result

def _private_json(path,value,limit=8192):
    raw=(json.dumps(value,sort_keys=True,allow_nan=False)+'\n').encode('ascii')
    assert len(raw)<=limit
    with Path(path).open('xb') as stream:stream.write(raw)

def _query(runtime,folder,budget,record,kind,tool,host_python):
    assert not any(p.name.casefold() in SYSTEM_DLL_NAMES for p in folder.iterdir())
    request=folder/('query-'+str(kind)+'.request.private.json')
    result=folder/('query-'+str(kind)+'.result.private.json')
    _private_json(request,dict(schemaVersion=1,kindCode=kind,tool=str(tool),deadline=budget.work_deadline))
    script=folder/('discover.cmd' if kind==0 else 'compile.cmd')
    expected=('@echo off\n"%~1" "%~2" --request "%~3" --result "%~4"\nexit /b %errorlevel%\n').encode('ascii')
    if not script.exists():script.write_bytes(expected)
    assert script.read_bytes()==expected
    helper=Path(__file__).with_name('vs_bundled_clang_version.py').resolve()
    request_pin=prep._pin(request)
    helper_pin=prep._pin(helper)
    try:
        _run_stage(runtime,folder,('probe-discovery','probe-clang-version','probe-lld-version')[kind],script,budget,record,
                   [Path(host_python),helper,request,result])
        _qualified(record['stages'][-1],kind)
    except BaseException:
        raise ProbeFailure(5)
    budget.now()
    assert prep._pin(request)==request_pin and prep._pin(helper)==helper_pin
    raw=prep._selection_read(result,8192,budget.now)
    value=json.loads(raw)
    assert type(value) is dict and set(value)==helper_module.RESULT_KEYS
    helper_module.validate_capture_observation(value['captureObservation'])
    assert type(value['schemaVersion']) is int and value['schemaVersion']==1
    assert type(value['kindCode']) is int and value['kindCode']==kind
    assert type(value['resultCode']) is int and 0<=value['resultCode']<=8
    for key in ('timedOut','outputCapReached','imageMatched','naturalExit','handlesClosed'):
        assert type(value[key]) is bool
    for key in ('stdoutBytes','stderrBytes'):
        assert type(value[key]) is int and 0<=value[key]<=(32768 if key=='stdoutBytes' and kind==0 else 4096)
    for key,maximum in (('pid',0xffffffff),('creationTime',0xffffffffffffffff)):
        assert value[key] is None or type(value[key]) is int and 0<value[key]<=maximum
    assert value['exitCode'] is None or type(value['exitCode']) is int and -0x80000000<=value['exitCode']<=0xffffffff
    stage=value['discoveryParseStage']
    assert type(stage) is int and 0<=stage<=5
    if kind==0:
        if value['resultCode']==0:assert stage==5
        elif value['resultCode']==8:assert 1<=stage<=4
        else:assert stage==0
        if stage:
            assert value['exitCode']==0 and all(value[k] is True for k in ('imageMatched','naturalExit','handlesClosed'))
            assert value['pid'] is not None and value['creationTime'] is not None
            assert not value['captureObservation']['observedMask']&2
            if stage>=2:assert 0<value['stdoutBytes']<=4096
    else:assert stage==0
    if value['resultCode']==0:
        assert value['exitCode']==0 and all(value[k] is True for k in ('imageMatched','naturalExit','handlesClosed'))
        assert not value['captureObservation']['observedMask']&2
    if kind:
        assert value['selectedRoot'] is None
        if value['resultCode']==0 or value['major'] is not None or value['minor'] is not None:
            assert type(value['major']) is int and 0<value['major']<=999
            assert type(value['minor']) is int and 0<=value['minor']<=999
    else:
        assert value['major'] is None and value['minor'] is None
        if value['resultCode']==0:
            assert type(value['selectedRoot']) is str and len(value['selectedRoot'])<=4096
            assert Path(value['selectedRoot']).is_absolute()
    budget.now()
    return value

def _require_query_success(value):
    if value['resultCode']!=0:raise ProbeFailure(6 if value['resultCode'] in (5,8) else 5)

def _cached_selection(path,budget,source_pins):
    path=prep._absolute(path)
    value=json.loads(prep._selection_read(path,1024*1024,budget.now))
    assert value['kind']=='ascii-message-observer-preparation' and value['architecture']=='x64'
    assert value['sourcePins']==source_pins and set(value['sourcePins'])==set(prep.SOURCES)
    _qualified(value['stages'][0],0)
    assert value['compiler']['mode']=='msvc'
    raw=prep._selection_read(path.parent/'discovery.stdout',32768,budget.now)
    found=raw.decode('utf-8-sig').strip()
    assert '\n' not in found and '\r' not in found
    selection,_=prep._msvc_selection(found,'x64',budget.now)
    assert selection==value['compiler']['selection']
    return selection

def run_probe(output,report,*,suite,windows,vswhere,host_python,expected_suite_source_commit,
              cached_preparation=None,runtime_factory=None,budget=None,_selection_sink=None):
    # compile-qualification:begin sink-preflight
    assert _selection_sink is None or type(_selection_sink) is dict and not _selection_sink
    # compile-qualification:end sink-preflight
    assert type(expected_suite_source_commit) is str and re.fullmatch('[0-9a-f]{40}',expected_suite_source_commit)
    budget=prep._Budget() if budget is None else budget
    assert budget.deadline==budget.started+30. and budget.work_deadline==budget.deadline-3.
    output,report,suite=map(prep._absolute,(output,report,suite))
    assert suite.is_dir() and not output.is_relative_to(suite) and not suite.is_relative_to(output)
    assert not report.is_relative_to(suite) and not report.is_relative_to(output)
    output.mkdir(parents=True,exist_ok=False)
    report.parent.mkdir(parents=True,exist_ok=True)
    temp=output/'temp';temp.mkdir()
    words=[int(expected_suite_source_commit[i:i+8],16) for i in range(0,40,8)]
    result=dict(schemaVersion=1,kindCode=1,diagnosticOnly=True,acceptance=False,productionQualified=False,
                productionBudgetChanged=False,observedComplete=False,knownUnavailable=False,majorSupported=None,
                resultCode=0,sourceHeadWords=words,nativeHostMachine=None,sourceCount=4,
                sourcePinsBeforeAfterEqual=False,selectionStable=False,cacheUsed=False,discoveryRequests=0,
                versionRequestsTotal=0,totalLimitMs=30000,workLimitMs=27000,elapsedMs=0,pendingHandleCount=0,
                tools=[_tool_row(),_tool_row()],stages=[],postPinResultCode=0,failureStageCode=0,
                discoveryHelperResultCode=None,discoveryCaptureObservation=helper_module.capture_observation(),
                discoveryQuery=None,discoveryParseStage=None)
    record={'stages':[]}
    runtime=None;source_pins=None;before_pins={};before_stats={};selection=None;paths=[]
    phase_code=1;step_code=1
    def fail(code,stage):
        if result['resultCode']==0:
            result['resultCode']=code;result['failureStageCode']=stage
    def code_for(error,default):
        if time.monotonic()>=budget.work_deadline:return 9
        return error.code if isinstance(error,ProbeFailure) else default
    try:
        budget.now()
        observed=prep.native_arch.validate_native_architecture(prep.native_arch.observe_native_architecture(),'x64')
        result['nativeHostMachine']=observed['nativeMachine']
        assert Path(host_python)==Path(sys.executable)
        prep._absolute(host_python)
        phase_code=11;step_code=2
        source_pins=_sources(budget.now)
        runtime=(_Runtime if runtime_factory is None else runtime_factory)(finite_environment(windows,temp))
        phase_code=2;step_code=3
        if cached_preparation is not None:
            result['cacheUsed']=True;phase_code=13
            selection=_cached_selection(cached_preparation,budget,source_pins)
        else:
            vswhere=prep._absolute(vswhere)
            assert vswhere.name=='vswhere.exe' and vswhere.is_file()
            before_discovery=prep._pin(vswhere)
            result['discoveryRequests']=1
            value=_query(runtime,output,budget,record,0,vswhere,host_python)
            result.update(discoveryHelperResultCode=value['resultCode'],discoveryCaptureObservation=value['captureObservation'])
            result.update(discoveryParseStage=value['discoveryParseStage'],discoveryQuery=dict(
                stdoutBytes=value['stdoutBytes'],stderrBytes=value['stderrBytes'],exitCode=value['exitCode'],
                imageMatched=value['imageMatched'],naturalExit=value['naturalExit'],handlesClosed=value['handlesClosed'],
                pid=value['pid'],creationTime=value['creationTime']))
            _require_query_success(value)
            assert prep._pin(vswhere)==before_discovery
            selection,_=prep._msvc_selection(value['selectedRoot'],'x64',budget.now)
        # compile-qualification:begin sink-path
        if _selection_sink is not None:
            assert not str(selection['installationRoot']).replace('\\','/').startswith('//')
        # compile-qualification:end sink-path
        tool_root=prep._absolute(Path(selection['installationRoot'])/'VC/Tools/Llvm/x64/bin')
        paths=[tool_root/name for name in TOOLS]
        phase_code=4;step_code=4
        for row,path in zip(result['tools'],paths):
            budget.now()
            row['present']=path.is_file();row['presenceKnown']=True
            row['knownUnavailable']=not row['present']
            if not row['present']:
                row['resultCode']=3;fail(3,4)
                continue
            try:
                facts={};pin=pin_native_tool(path,'x64',check=budget.now,facts=facts)
                _stat_join(facts,pin)
                before_pins[path.name],before_stats[path.name]=pin,facts
                row.update(beforePinned=True,peVerified=True,bytes=pin['bytes'],machine=pin['machine'],
                    sha256Words=[int(pin['sha256'][i:i+8],16) for i in range(0,64,8)])
            except BaseException as error:
                row['resultCode']=code_for(error,4);fail(row['resultCode'],4)
        for kind,(row,path) in enumerate(zip(result['tools'],paths),1):
            if not row['beforePinned']:continue
            phase_code=5;step_code=4+kind
            try:
                budget.now()
                row['versionRequests']=1;result['versionRequestsTotal']+=1
                try:value=_query(runtime,output,budget,record,kind,path,host_python)
                except AssertionError:raise ProbeFailure(6)
                row.update(major=value['major'],minor=value['minor'],versionExit=value['exitCode'],
                    queryPid=value['pid'],queryCreationTime=value['creationTime'],
                    queryNaturalExit=value['naturalExit'],queryHandleClosed=value['handlesClosed'])
                row.update(helperResultCode=value['resultCode'],captureObservation=value['captureObservation'])
                _require_query_success(value)
                row['resultCode']=0 if row['major']>=22 else 7
                if row['resultCode']:fail(row['resultCode'],step_code)
            except BaseException as error:
                row['resultCode']=code_for(error,5);fail(row['resultCode'],step_code)
            finally:
                matching=[x for x in record['stages'] if x['stage']==('probe-clang-version' if kind==1 else 'probe-lld-version')]
                if matching:
                    stage=_stage_numbers(matching[-1],kind)
                    row.update(naturalJob=stage['natural'],jobEmpty=stage['jobEmpty'],handlesClosed=stage['handlesClosed'])
            # A failed Job/close boundary stops further process starts. A missing,
            # old or naturally failed tool never becomes a compiler fallback.
            if row['versionRequests'] and not all(row[k] for k in ('naturalJob','jobEmpty','handlesClosed')):
                break
            if runtime.pending_handles() or time.monotonic()>=budget.work_deadline:break
    except BaseException as error:
        fail(code_for(error,phase_code),step_code)
    finally:
        for row,path in zip(result['tools'],paths):
            if path.name not in before_pins:continue
            try:
                facts={};pin=pin_native_tool(path,'x64',check=budget.now,facts=facts)
                _stat_join(facts,pin)
                row['afterPinned']=True;row['pinsEqual']=pin==before_pins[path.name]
                row['statJoinMatched']=facts==before_stats[path.name]
                assert row['pinsEqual'] and row['statJoinMatched']
            except BaseException:
                row['postPinResultCode']=9 if time.monotonic()>=budget.work_deadline else 8
                if result['postPinResultCode']==0:result['postPinResultCode']=row['postPinResultCode']
                if row['resultCode'] in (None,0):row['resultCode']=row['postPinResultCode']
                fail(row['postPinResultCode'],7)
        if selection is not None:
            try:
                result['selectionStable']=prep._msvc_selection(selection['installationRoot'],'x64',budget.now)[0]==selection
                assert result['selectionStable']
            except BaseException:
                if result['postPinResultCode']==0:result['postPinResultCode']=9 if time.monotonic()>=budget.work_deadline else 8
                fail(result['postPinResultCode'],7)
        stage_codes={'probe-discovery':0,'probe-clang-version':1,'probe-lld-version':2}
        result['stages']=[_stage_numbers(row,stage_codes[row['stage']]) for row in record['stages']]
        if runtime is not None:result['pendingHandleCount']=runtime.pending_handles()
        if result['pendingHandleCount']:fail(10,9)
        if source_pins is not None:
            try:
                result['sourcePinsBeforeAfterEqual']=_sources(budget.now)==source_pins
                if not result['sourcePinsBeforeAfterEqual']:fail(11,8)
            except BaseException:
                result['sourcePinsBeforeAfterEqual']=False;fail(9,8)
        stable=result['sourcePinsBeforeAfterEqual'] and result['selectionStable'] and result['pendingHandleCount']==0
        for row in result['tools']:
            lifecycle=(row['beforePinned'] and row['afterPinned'] and row['pinsEqual'] and row['statJoinMatched']
                and row['naturalJob'] and row['jobEmpty'] and row['handlesClosed'] and row['queryNaturalExit'] and row['queryHandleClosed'])
            row['observedComplete']=bool(stable and (row['knownUnavailable'] or lifecycle))
            if row['observedComplete'] and lifecycle and row['versionExit']==0 and type(row['major']) is int:
                row['majorSupported']=row['major']>=22
        result['knownUnavailable']=any(row['knownUnavailable'] for row in result['tools'])
        result['observedComplete']=all(row['observedComplete'] for row in result['tools'])
        if all(type(row['majorSupported']) is bool for row in result['tools']):
            result['majorSupported']=all(row['majorSupported'] for row in result['tools'])
        result['elapsedMs']=max(0,int((time.monotonic()-budget.started)*1000))
        validate_report(result)
        _private_json(report,result)
    # compile-qualification:begin sink-export
    if _selection_sink is not None and result['resultCode']==0:
        _selection_sink.update(selection=selection,toolPins=before_pins,statFacts=before_stats)
    # compile-qualification:end sink-export
    return result

def validate_report(value):
    assert type(value) is dict and set(value)==TOP_KEYS
    assert type(value['schemaVersion']) is int and value['schemaVersion']==1
    assert type(value['kindCode']) is int and value['kindCode']==1
    assert value['diagnosticOnly'] is True and value['acceptance'] is False and value['productionQualified'] is False and value['productionBudgetChanged'] is False
    for key in ('observedComplete','knownUnavailable','sourcePinsBeforeAfterEqual','selectionStable','cacheUsed'):assert type(value[key]) is bool
    assert value['majorSupported'] is None or type(value['majorSupported']) is bool
    for key,maximum in (('resultCode',14),('postPinResultCode',9),('failureStageCode',9),('discoveryRequests',1),('versionRequestsTotal',2),('elapsedMs',60000),('pendingHandleCount',6)):
        assert type(value[key]) is int and 0<=value[key]<=maximum
    assert value['totalLimitMs']==30000 and type(value['totalLimitMs']) is int
    assert value['workLimitMs']==27000 and type(value['workLimitMs']) is int
    assert value['sourceCount']==4 and type(value['sourceCount']) is int
    assert value['nativeHostMachine'] is None or type(value['nativeHostMachine']) is int and value['nativeHostMachine']==0x8664
    assert type(value['sourceHeadWords']) is list and len(value['sourceHeadWords'])==5
    assert all(type(x) is int and 0<=x<=0xffffffff for x in value['sourceHeadWords'])
    assert type(value['tools']) is list and len(value['tools'])==2
    discovery=value['discoveryHelperResultCode'];observation=value['discoveryCaptureObservation']
    assert discovery is None or type(discovery) is int and 0<=discovery<=8
    helper_module.validate_capture_observation(observation)
    if discovery is None:assert observation['observedMask']==0
    else:assert value['discoveryRequests']==1 and value['cacheUsed'] is False
    if value['cacheUsed']:assert value['discoveryRequests']==0 and discovery is None
    if discovery==0:assert not observation['observedMask']&2
    query=value['discoveryQuery'];stage=value['discoveryParseStage']
    if discovery is None:assert query is None and stage is None
    else:
        assert type(query) is dict and set(query)=={'stdoutBytes','stderrBytes','exitCode',
            'imageMatched','naturalExit','handlesClosed','pid','creationTime'}
        for key,maximum in (('stdoutBytes',32768),('stderrBytes',4096)):
            assert type(query[key]) is int and 0<=query[key]<=maximum
        for key in ('imageMatched','naturalExit','handlesClosed'):assert type(query[key]) is bool
        assert query['exitCode'] is None or type(query['exitCode']) is int and -0x80000000<=query['exitCode']<=0xffffffff
        for key,maximum in (('pid',0xffffffff),('creationTime',0xffffffffffffffff)):
            assert query[key] is None or type(query[key]) is int and 0<query[key]<=maximum
        assert type(stage) is int and 0<=stage<=5
        if discovery==0:assert stage==5
        elif discovery==8:assert 1<=stage<=4
        else:assert stage==0
        if stage:
            assert query['exitCode']==0 and all(query[key] is True for key in ('imageMatched','naturalExit','handlesClosed'))
            assert query['pid'] is not None and query['creationTime'] is not None
            assert not observation['observedMask']&2
            if stage>=2:assert 0<query['stdoutBytes']<=4096
    stable=value['sourcePinsBeforeAfterEqual'] and value['selectionStable'] and value['pendingHandleCount']==0
    for tool in value['tools']:
        assert type(tool) is dict and set(tool)==TOOL_KEYS
        assert tool['helperResultCode'] is None or type(tool['helperResultCode']) is int and 0<=tool['helperResultCode']<=8
        helper_module.validate_capture_observation(tool['captureObservation'])
        if tool['helperResultCode'] is None:assert tool['captureObservation']['observedMask']==0
        else:assert tool['versionRequests']==1
        if tool['helperResultCode']==0:
            assert tool['versionExit']==0 and tool['queryNaturalExit'] is tool['queryHandleClosed'] is True
            assert not tool['captureObservation']['observedMask']&2
        for key in ('present','presenceKnown','knownUnavailable','observedComplete','peVerified','beforePinned','afterPinned','pinsEqual','statJoinMatched','naturalJob','jobEmpty','handlesClosed','queryNaturalExit','queryHandleClosed'):
            assert type(tool[key]) is bool
        for key,maximum in (('bytes',512*1024*1024),('machine',0xffff),('major',999),('minor',999),('queryPid',0xffffffff),('queryCreationTime',0xffffffffffffffff)):
            assert tool[key] is None or type(tool[key]) is int and 0<=tool[key]<=maximum
        assert tool['versionExit'] is None or type(tool['versionExit']) is int and -0x80000000<=tool['versionExit']<=0xffffffff
        assert type(tool['versionRequests']) is int and tool['versionRequests'] in (0,1)
        assert type(tool['sha256Words']) is list and len(tool['sha256Words'])==8
        assert all(x is None for x in tool['sha256Words']) or all(type(x) is int and 0<=x<=0xffffffff for x in tool['sha256Words'])
        if tool['beforePinned']:
            assert tool['present'] and tool['bytes'] is not None and tool['bytes']>0 and tool['machine']==0x8664
            assert all(type(x) is int for x in tool['sha256Words'])
        else:
            assert tool['bytes'] is None and tool['machine'] is None and all(x is None for x in tool['sha256Words'])
        assert not tool['afterPinned'] or tool['beforePinned']
        assert not tool['pinsEqual'] or tool['afterPinned']
        assert not tool['statJoinMatched'] or tool['afterPinned']
        assert (tool['major'] is None)==(tool['minor'] is None)
        assert tool['majorSupported'] is None or type(tool['majorSupported']) is bool
        assert tool['resultCode'] is None or type(tool['resultCode']) is int and tool['resultCode'] in (0,3,4,5,6,7,8,9)
        assert type(tool['postPinResultCode']) is int and tool['postPinResultCode'] in (0,8,9)
        assert tool['knownUnavailable']==(tool['presenceKnown'] and not tool['present'])
        assert not tool['present'] or tool['presenceKnown']
        assert tool['peVerified']==tool['beforePinned']
        lifecycle=(tool['beforePinned'] and tool['afterPinned'] and tool['pinsEqual'] and tool['statJoinMatched']
            and tool['naturalJob'] and tool['jobEmpty'] and tool['handlesClosed'] and tool['queryNaturalExit'] and tool['queryHandleClosed'])
        assert tool['observedComplete']==bool(stable and (tool['knownUnavailable'] or lifecycle))
        expected_major=None
        if tool['observedComplete'] and lifecycle and tool['versionExit']==0 and type(tool['major']) is int:
            expected_major=tool['major']>=22
        assert tool['majorSupported'] is expected_major
        if tool['majorSupported'] is not None:
            assert tool['observedComplete'] and tool['versionExit']==0 and type(tool['major']) is int
            assert tool['majorSupported']==(tool['major']>=22)
    assert value['observedComplete']==all(t['observedComplete'] for t in value['tools'])
    assert value['knownUnavailable']==any(t['knownUnavailable'] for t in value['tools'])
    expected_major=all(t['majorSupported'] for t in value['tools']) if all(type(t['majorSupported']) is bool for t in value['tools']) else None
    assert value['majorSupported'] is expected_major
    assert value['versionRequestsTotal']==sum(t['versionRequests'] for t in value['tools'])
    assert value['resultCode'] in (0,1,2,3,4,5,6,7,8,9,10,11,13)
    assert value['postPinResultCode'] in (0,8,9)
    assert type(value['stages']) is list and len(value['stages'])<=3
    for stage in value['stages']:
        assert type(stage) is dict and set(stage)==STAGE_KEYS
        for key in ('natural','jobEmpty','handlesClosed'):assert type(stage[key]) is bool
        for key,maximum in (('stageCode',2),('lastActive',0xffffffff),('queryCount',prep.QUERY_CAP),('pid',0xffffffff),('creationTime',0xffffffffffffffff)):
            assert stage[key] is None or type(stage[key]) is int and 0<=stage[key]<=maximum
        assert stage['rootExit'] is None or type(stage['rootExit']) is int and -0x80000000<=stage['rootExit']<=0xffffffff
    if value['resultCode']==0:
        assert value['failureStageCode']==0 and value['postPinResultCode']==0
        assert value['observedComplete'] and value['majorSupported'] is True and value['sourcePinsBeforeAfterEqual'] and value['selectionStable'] and value['pendingHandleCount']==0
        assert all(t['major']>=22 and all(t[k] for k in ('beforePinned','afterPinned','pinsEqual','statJoinMatched','naturalJob','jobEmpty','handlesClosed','queryNaturalExit','queryHandleClosed')) and t['versionExit']==0 for t in value['tools'])
    assert len((json.dumps(value,sort_keys=True,allow_nan=False)+'\n').encode('ascii'))<=8192

def main(argv=None):
    import argparse
    class Parser(argparse.ArgumentParser):
        def error(self,message):raise ValueError
    arguments=list(sys.argv[1:] if argv is None else argv)
    if len(arguments)==2 and arguments[0]=='--validate-report':
        try:
            path=prep._absolute(Path(arguments[1]))
            validate_report(json.loads(prep._selection_read(path,8192,lambda:None)))
            return 0
        except BaseException:return 1
    parser=Parser(add_help=False)
    for name in ('output','report','suite','windows','vswhere','host-python','expected-suite-source-commit'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--cached-preparation')
    try:
        args=parser.parse_args(arguments)
        run_probe(Path(args.output),Path(args.report),suite=Path(args.suite),windows=Path(args.windows),
            vswhere=Path(args.vswhere),host_python=Path(args.host_python),
            expected_suite_source_commit=args.expected_suite_source_commit,
            cached_preparation=Path(args.cached_preparation) if args.cached_preparation else None)
        return 0
    except BaseException:return 1

# compile-qualification:begin helpers
QUALIFICATION_KEYS={'schemaVersion','kindCode','diagnosticOnly','acceptance','productionQualified',
    'compilerQualified','resultCode','failureStageCode','sourceHeadWords','nativeHostMachine','pair',
    'positive','negative','negativeStage','pe','sourcePinsBeforeAfterEqual','supportPinsBeforeAfterEqual',
    'toolPinsBeforeAfterEqual','selectionStable','pendingHandleCount','elapsedMs','workLimitMs','totalLimitMs'}
QUALIFICATION_PE_KEYS={'bytes','machine','optionalMagic','isDll','executable','clrAbsent','exportsMatch',
    'entryMappedExecutable','normalImportCount','delayImportCount','vcCrtImportCount','dynamicCrtImportCount','sha256Words'}


def _qualification_words(digest):
    assert type(digest) is str and re.fullmatch('[0-9a-f]{64}',digest)
    return [int(digest[i:i+8],16) for i in range(0,64,8)]


def _qualification_source_contract(expected,check):
    assert type(expected) is dict and set(expected)==set(prep.SOURCES)
    for pin in expected.values():
        assert type(pin) is dict and set(pin)=={'bytes','sha256'}
        assert type(pin['bytes']) is int and 0<pin['bytes']<=8*1024*1024
        _qualification_words(pin['sha256'])
    actual=_sources(check)
    assert actual==expected
    return actual


def _qualification_support_pins(check):
    root=Path(__file__).resolve().parents[1]
    paths=(Path(__file__),Path(helper_module.__file__),Path(prep.__file__),
        root/'e2e/native_compiler_tools.py',root/'e2e/native_suite_architecture.py',
        root/'payload.py',root/'pe_imports.py',root/'crt.py')
    pins=[]
    for path in paths:
        check();pins.append(prep._pin(prep._absolute(path)));check()
    return pins


def _qualification_recipe(version):
    assert type(version) is str and re.fullmatch(r'[0-9]{2}\.[0-9]{2}\.[0-9]{4,6}',version)
    return ('@echo off\nset "VSCMD_SKIP_SENDTELEMETRY=1"\ncall "%~1" x64 -vcvars_ver='+version
        +' >NUL 2>NUL\nif errorlevel 1 exit /b 1\n'
        +'"%~4" --no-default-config --target=x86_64-pc-windows-msvc /nologo /c /O2 /MT /EHsc /std:c++17 /W4 /WX /utf-8 "%~2"'
        +' /Foascii_message_observer.obj >NUL 2>NUL\nif errorlevel 1 exit /b 1\n'
        +'"%~5" /NOLOGO /DLL /WX /MACHINE:X64 /OUT:"%~3" /IMPLIB:ascii_message_observer.lib'
        +' ascii_message_observer.obj user32.lib kernel32.lib >NUL 2>NUL\nexit /b %errorlevel%\n')


def _qualification_pe(library,source,check):
    # Reuse the retained-file PE reader, not an executable dumpbin or LoadLibrary.
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('qualification_payload',root/'payload.py')
    payload=importlib.util.module_from_spec(spec);spec.loader.exec_module(payload)
    spec=importlib.util.spec_from_file_location('qualification_crt',root/'crt.py')
    crt=importlib.util.module_from_spec(spec);spec.loader.exec_module(crt)
    check();before=prep._pin(library);check()
    sys.path.insert(0,str(root))
    try:binary=payload._source_companion_pe(library)
    finally:sys.path.remove(str(root))
    check();assert prep._pin(library)==before;check()
    expected=re.findall(r'extern "C" __declspec\(dllexport\)[^{;]+?\b([A-Za-z_]\w*)\s*\(',source.read_text())
    assert len(expected)==len(set(expected))==12
    imports=binary['imports'];names=set(imports['normal'])|set(imports['delay'])
    vc=sum(bool(crt._VC_IMPORT.fullmatch(name)) for name in names)
    # This is a CRT-family rejection, not a new general DLL import allowlist.
    dynamic=sum(bool(crt._VC_IMPORT.fullmatch(name)) or bool(re.fullmatch(r'(?:ucrtbase|msvcrt)d?\.dll',name))
        or name.startswith('api-ms-win-crt-') for name in names)
    value=dict(bytes=binary['size'],machine=binary['machine'],optionalMagic=binary['optionalMagic'],
        isDll=binary['isDll'],executable=binary['executable'],clrAbsent=binary['clrRva']==binary['clrSize']==0,
        exportsMatch=binary['exports']==sorted(expected) and binary['exportModule']=='ascii-message-observer.dll',
        entryMappedExecutable=binary['entryMappedExecutable'],normalImportCount=len(imports['normal']),
        delayImportCount=len(imports['delay']),vcCrtImportCount=vc,dynamicCrtImportCount=dynamic,
        sha256Words=_qualification_words(binary['sha256']))
    assert value['bytes']==before['bytes'] and value['sha256Words']==_qualification_words(before['sha256'])
    assert value['machine']==0x8664 and value['optionalMagic']==0x20b
    assert all(value[k] is True for k in ('isDll','executable','clrAbsent','exportsMatch','entryMappedExecutable'))
    assert dynamic==vc==0
    check();return value


def _qualification_pair(pair,head_words):
    validate_report(pair)
    assert pair['sourceHeadWords']==head_words and pair['nativeHostMachine']==0x8664
    assert pair['cacheUsed'] is False and pair['resultCode']==pair['failureStageCode']==pair['postPinResultCode']==0
    assert pair['discoveryRequests']==1 and pair['versionRequestsTotal']==2
    assert pair['discoveryHelperResultCode']==0 and pair['discoveryParseStage']==5 and pair['elapsedMs']<27000
    assert [stage['stageCode'] for stage in pair['stages']]==[0,1,2]
    for stage in pair['stages']:
        assert stage['rootExit']==0 and stage['lastActive']==0
        assert all(stage[k] for k in ('natural','jobEmpty','handlesClosed'))
        assert stage['pid'] and stage['creationTime'] and stage['queryCount']
    for tool in pair['tools']:
        assert tool['helperResultCode']==tool['resultCode']==tool['postPinResultCode']==tool['versionExit']==0
        assert tool['versionRequests']==1


def validate_qualification_report(value):
    def numeric(v):
        if type(v) is dict:return all(type(k) is str and numeric(x) for k,x in v.items())
        if type(v) is list:return all(numeric(x) for x in v)
        return v is None or type(v) in (int,bool)
    assert numeric(value) and type(value) is dict and set(value)==QUALIFICATION_KEYS
    assert type(value['schemaVersion']) is int and value['schemaVersion']==1
    assert type(value['kindCode']) is int and value['kindCode']==2
    assert value['diagnosticOnly'] is True and value['acceptance'] is value['productionQualified'] is False
    for key in ('compilerQualified','sourcePinsBeforeAfterEqual','supportPinsBeforeAfterEqual','toolPinsBeforeAfterEqual','selectionStable'):
        assert type(value[key]) is bool
    for key,maximum in (('resultCode',10),('failureStageCode',9),('pendingHandleCount',12),('elapsedMs',60000)):
        assert type(value[key]) is int and 0<=value[key]<=maximum
    assert type(value['workLimitMs']) is int and value['workLimitMs']==27000
    assert type(value['totalLimitMs']) is int and value['totalLimitMs']==30000
    assert type(value['sourceHeadWords']) is list and len(value['sourceHeadWords'])==5
    assert all(type(n) is int and 0<=n<=0xffffffff for n in value['sourceHeadWords'])
    assert value['nativeHostMachine'] is None or type(value['nativeHostMachine']) is int and value['nativeHostMachine']==0x8664
    pair=value['pair']
    if pair is not None:
        validate_report(pair)
        assert pair['sourceHeadWords']==value['sourceHeadWords'] and pair['cacheUsed'] is False
    for key,code in (('positive',3),('negativeStage',4)):
        stage=value[key]
        if stage is None:continue
        assert type(stage) is dict and set(stage)==STAGE_KEYS and type(stage['stageCode']) is int and stage['stageCode']==code
        for name in ('natural','jobEmpty','handlesClosed'):assert type(stage[name]) is bool
        for name,limit in (('lastActive',0xffffffff),('queryCount',prep.QUERY_CAP),('pid',0xffffffff),('creationTime',0xffffffffffffffff)):
            assert stage[name] is None or type(stage[name]) is int and 0<=stage[name]<=limit
        assert stage['rootExit'] is None or type(stage['rootExit']) is int and -0x80000000<=stage['rootExit']<=0xffffffff
    if value['negative'] is not None:helper_module.validate_compile_result(value['negative'])
    pe=value['pe']
    if pe is not None:
        assert type(pe) is dict and set(pe)==QUALIFICATION_PE_KEYS
        for key in ('isDll','executable','clrAbsent','exportsMatch','entryMappedExecutable'):assert type(pe[key]) is bool
        for key,maximum in (('bytes',8*1024*1024),('machine',0xffff),('optionalMagic',0xffff),('normalImportCount',8192),('delayImportCount',8192),('vcCrtImportCount',16384),('dynamicCrtImportCount',16384)):
            assert type(pe[key]) is int and 0<=pe[key]<=maximum
        assert type(pe['sha256Words']) is list and len(pe['sha256Words'])==8 and all(type(n) is int and 0<=n<=0xffffffff for n in pe['sha256Words'])
    if value['compilerQualified']:
        assert value['resultCode']==value['failureStageCode']==0 and value['elapsedMs']<27000
        assert value['nativeHostMachine']==0x8664 and value['pendingHandleCount']==0
        assert all(value[k] for k in ('sourcePinsBeforeAfterEqual','supportPinsBeforeAfterEqual','toolPinsBeforeAfterEqual','selectionStable'))
        assert pair is not None
        _qualification_pair(pair,value['sourceHeadWords'])
        assert pair['elapsedMs']<=value['elapsedMs']
        for key in ('positive','negativeStage'):
            stage=value[key];assert stage is not None and stage['rootExit']==0 and stage['lastActive']==0
            assert all(stage[k] for k in ('natural','jobEmpty','handlesClosed'))
            assert stage['pid'] and stage['creationTime'] and stage['queryCount']
        negative=value['negative'];assert negative is not None and negative['resultCode']==0
        assert type(negative['exitCode']) is int and negative['exitCode']!=0
        assert pe is not None and pe['bytes']>0 and pe['machine']==0x8664 and pe['optionalMagic']==0x20b
        assert all(pe[k] for k in ('isDll','executable','clrAbsent','exportsMatch','entryMappedExecutable'))
        assert pe['vcCrtImportCount']==pe['dynamicCrtImportCount']==0
    else:assert value['resultCode']>0 and value['failureStageCode']>0
    assert len((json.dumps(value,sort_keys=True,allow_nan=False)+'\n').encode('ascii'))<=8192


def run_compile_qualification(output,report,*,suite,windows,vswhere,host_python,expected_suite_source_commit,
                              expected_source_pins,runtime_factory=None,budget=None):
    # No pair report/cache/descriptor is accepted. Only this call can create its
    # fresh observation directory, and all subsequent steps retain its budget.
    budget=prep._Budget() if budget is None else budget
    assert budget.deadline==budget.started+30. and budget.work_deadline==budget.deadline-3.
    assert type(expected_suite_source_commit) is str and re.fullmatch('[0-9a-f]{40}',expected_suite_source_commit)
    output,report,suite=map(prep._absolute,(output,report,suite))
    assert suite.is_dir() and not output.is_relative_to(suite) and not suite.is_relative_to(output)
    assert not report.is_relative_to(suite) and not report.is_relative_to(output)
    assert all(not str(p).replace('\\','/').startswith('//') for p in (output,report,suite))
    output.mkdir(parents=True,exist_ok=False);report.parent.mkdir(parents=True,exist_ok=True)
    value=dict(schemaVersion=1,kindCode=2,diagnosticOnly=True,acceptance=False,productionQualified=False,
        compilerQualified=False,resultCode=0,failureStageCode=0,
        sourceHeadWords=[int(expected_suite_source_commit[i:i+8],16) for i in range(0,40,8)],nativeHostMachine=None,
        pair=None,positive=None,negative=None,negativeStage=None,pe=None,sourcePinsBeforeAfterEqual=False,
        supportPinsBeforeAfterEqual=False,toolPinsBeforeAfterEqual=False,selectionStable=False,
        pendingHandleCount=0,elapsedMs=0,workLimitMs=27000,totalLimitMs=30000)
    record={'stages':[]};holder=[];phase=1;sources=None;support=None;selection=None;pins={};facts={};tools=[]
    def fail(code,stage):
        if value['resultCode']==0:value.update(resultCode=code,failureStageCode=stage)
    try:
        budget.now()
        value['nativeHostMachine']=prep.native_arch.validate_native_architecture(prep.native_arch.observe_native_architecture(),'x64')['nativeMachine']
        assert Path(host_python)==Path(sys.executable)
        sources=_qualification_source_contract(expected_source_pins,budget.now)
        support=_qualification_support_pins(budget.now)
        def runtime_for(environment):
            runtime=(_Runtime if runtime_factory is None else runtime_factory)(environment);holder.append(runtime);return runtime
        phase=2
        selected_state={}
        pair=run_probe(output/'observe',output/'pair.numeric.json',suite=suite,windows=windows,vswhere=vswhere,
            host_python=host_python,expected_suite_source_commit=expected_suite_source_commit,runtime_factory=runtime_for,budget=budget,
            _selection_sink=selected_state)
        value['pair']=pair;_qualification_pair(pair,value['sourceHeadWords'])
        assert pair['sourceHeadWords']==value['sourceHeadWords'] and len(holder)==1
        runtime=holder[0];assert runtime.pending_handles()==0
        # Only the successful fresh call above can fill this process-local sink.
        assert type(selected_state) is dict and set(selected_state)=={'selection','toolPins','statFacts'}
        selection=selected_state['selection']
        assert prep._msvc_selection(selection['installationRoot'],'x64',budget.now)[0]==selection
        root=prep._absolute(Path(selection['installationRoot']))
        assert not str(root).replace('\\','/').startswith('//')
        tools=[root/'VC/Tools/Llvm/x64/bin'/name for name in TOOLS]
        for tool,row in zip(tools,pair['tools']):
            budget.now();pin=selected_state['toolPins'][tool.name];observed=selected_state['statFacts'][tool.name]
            from native_compiler_tools import validate_tool_pin
            validate_tool_pin(pin,'x64',tool.name);assert pin['path']==str(tool);_stat_join(observed,pin)
            assert pin['bytes']==row['bytes'] and _qualification_words(pin['sha256'])==row['sha256Words'] and pin['machine']==row['machine']
            pins[tool.name]=pin;facts[tool.name]=observed
        phase=3
        positive=output/'positive';positive.mkdir()
        for name in prep.SOURCES:
            budget.now();raw=(prep.SOURCE_ROOT/name).read_bytes();(positive/name).write_bytes(raw)
            assert prep._pin(positive/name)==sources[name];budget.now()
        script=positive/'compile.cmd';script.write_text(_qualification_recipe(selection['toolsetVersion']),encoding='ascii')
        script_pin=prep._pin(script)
        _run_stage(runtime,positive,'qualify-positive',script,budget,record,
            [Path(selection['vcvars']['path']),positive/prep.SOURCES[0],positive/'ascii-message-observer.dll',*tools])
        value['positive']=_qualified(record['stages'][-1],3)
        assert prep._pin(script)==script_pin and runtime.pending_handles()==0
        phase=4;value['pe']=_qualification_pe(positive/'ascii-message-observer.dll',positive/prep.SOURCES[0],budget.now)
        phase=5;budget.now();negative=output/'negative';negative.mkdir()
        source=negative/'negative.cpp';source.write_bytes(helper_module.NEGATIVE_SOURCE)
        request=negative/'request.private.json';result=negative/'result.private.json'
        _private_json(request,dict(schemaVersion=1,kindCode=3,tool=str(tools[0]),source=str(source),object=str(negative/'negative.obj'),
            deadline=budget.work_deadline,sourcePin=prep._pin(source),toolPin=pins[tools[0].name]))
        request_pin=prep._pin(request);helper=Path(helper_module.__file__);helper_pin=prep._pin(helper)
        script=negative/'compile.cmd';script.write_text('@echo off\n"%~1" "%~2" --compile-request "%~3" --result "%~4"\nexit /b %errorlevel%\n',encoding='ascii')
        script_pin=prep._pin(script)
        _run_stage(runtime,negative,'qualify-negative',script,budget,record,[Path(host_python),helper,request,result])
        value['negativeStage']=_qualified(record['stages'][-1],4)
        assert prep._pin(request)==request_pin and prep._pin(helper)==helper_pin and prep._pin(script)==script_pin
        observed_negative=json.loads(prep._selection_read(result,8192,budget.now))
        helper_module.validate_compile_result(observed_negative)
        value['negative']=observed_negative
        assert value['negative']['resultCode']==0 and runtime.pending_handles()==0
        phase=6
        for tool in tools:
            observed={};pin=pin_native_tool(tool,'x64',check=budget.now,facts=observed);_stat_join(observed,pin)
            assert pin==pins[tool.name] and observed==facts[tool.name]
        value['toolPinsBeforeAfterEqual']=True
        value['selectionStable']=prep._msvc_selection(selection['installationRoot'],'x64',budget.now)[0]==selection
        assert value['selectionStable']
        budget.now()
        assert prep._pin(positive/'ascii-message-observer.dll')==dict(bytes=value['pe']['bytes'],
            sha256=''.join(f'{word:08x}' for word in value['pe']['sha256Words']))
        budget.now()
        for name in prep.SOURCES:assert prep._pin(positive/name)==sources[name]
        value['sourcePinsBeforeAfterEqual']=_qualification_source_contract(expected_source_pins,budget.now)==sources
        value['supportPinsBeforeAfterEqual']=_qualification_support_pins(budget.now)==support
        assert value['sourcePinsBeforeAfterEqual'] and value['supportPinsBeforeAfterEqual']
        budget.now();value['compilerQualified']=True
    except BaseException:
        fail(9 if time.monotonic()>=budget.work_deadline else phase,phase)
    finally:
        if holder:value['pendingHandleCount']=holder[0].pending_handles()
        if value['pendingHandleCount']:fail(10,9);value['compilerQualified']=False
        value['elapsedMs']=max(0,int((time.monotonic()-budget.started)*1000))
        if value['elapsedMs']>=27000:fail(9,8);value['compilerQualified']=False
        validate_qualification_report(value);_private_json(report,value)
    return value
def qualification_main(argv=None):
    import argparse
    class Parser(argparse.ArgumentParser):
        def error(self,message):raise ValueError
    args=list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args)==2 and args[0]=='--validate-qualification-report':
            value=json.loads(prep._selection_read(Path(args[1]),8192,lambda:None))
            validate_qualification_report(value);return 0
        if not args or args.pop(0)!='--qualify-compiler':return 1
        parser=Parser(add_help=False)
        for name in ('output','report','suite','windows','vswhere','host-python','expected-suite-source-commit','source-pins'):
            parser.add_argument('--'+name,required=True)
        selected=parser.parse_args(args);budget=prep._Budget()
        pins=json.loads(prep._selection_read(Path(selected.source_pins),8192,budget.now))
        run_compile_qualification(Path(selected.output),Path(selected.report),suite=Path(selected.suite),windows=Path(selected.windows),
            vswhere=Path(selected.vswhere),host_python=Path(selected.host_python),expected_suite_source_commit=selected.expected_suite_source_commit,
            expected_source_pins=pins,budget=budget)
        return 0  # Report generation does not imply compiler/product qualification.
    except BaseException:return 1
# compile-qualification:end helpers

# compile-qualification:begin entry
if __name__=='__main__':
    raise SystemExit(qualification_main() if sys.argv[1:2] in (['--qualify-compiler'],['--validate-qualification-report']) else main())
# compile-qualification:end entry
