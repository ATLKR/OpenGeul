"""Scratch-only SDK build/negative-smoke candidate. No package observation mode."""
from __future__ import annotations
import sys
if __name__=='__main__':raise SystemExit(3)
import argparse
import hashlib
import json
import math
import os
from pathlib import Path,PureWindowsPath
import re
import time
from supervisor import GateFailure,Runner,child_environment,phase_deadline
import toolchain as tools

ROOT=Path(__file__).resolve().parent

def empty_receipt():
    return {'schemaVersion':2,'kind':'packaged-context-sdk-negative-gate','stage':0,'failureCode':0,
      'sdkGatePassed':False,'actualWindowsExecuted':False,'nativeSdkCompiled':False,'nativeLinked':False,
      'negativeSmokePassed':False,'actualPackageObservation':False,'qualification':False,'canService':False,
      'originalHelperHandleKnown':False,'packagedHelperLauncherImplemented':False,'watchdogVerified':False,
      'synchronousOsCallPreemptionVerified':False,'osImplicitEffectsKnown':False,'frozenV2Preserved':False,
      'pure40TestsRerun':False,'lease6TestsRerun':False,'workRootCreated':False,'codeApprovalVerified':False,
      'commandProcessorBinding':None,'phaseResults':[],'phaseActiveObservations':[],'failureObservation':None,'sdkCandidateObservation':None}

def _fresh_text(root,name,text):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}\.cmd',name):raise GateFailure(2)
    p=root/name
    with p.open('x',encoding='utf-8',newline='') as stream:stream.write(text.replace('\n','\r\n'))
    return name

def require_fresh_outputs(root,names):
    tools.canonical(root,directory=True)
    allowed={'vswhere.json','observer.obj','smoke.obj','sdk-smoke.exe'}
    if type(names) is not tuple or not names or any(name not in allowed for name in names):raise GateFailure(2)
    for name in names:
        p=root/name
        if p.exists() or p.is_symlink():raise GateFailure(2)
    return True

def discovery_batch(vswhere):
    return '@echo off\n"'+tools.cmd_path(vswhere)+'" -latest -products * -version "[17.0,19.0)" -format json -utf8 > vswhere.json\nexit /b %errorlevel%\n'

def compile_batch(phase,vs,sdk,root,arch):
    if phase not in ('port','smoke','link') or arch not in tools.MACHINES:raise GateFailure(2)
    root=tools.cmd_path(str(root));q=lambda s:'"'+tools.cmd_path(str(s))+'"'
    ver=sdk['version']
    if not re.fullmatch(r'10\.0\.\d{4,6}\.\d{1,5}',ver):raise GateFailure(2)
    head=['@echo off','call '+q(vs['devcmd'])+' -no_logo -host_arch='+arch+' -arch='+arch+' -winsdk='+ver,
      'if errorlevel 1 exit /b %errorlevel%','set "CL="','set "_CL_="','set "LINK="','set "_LINK_="',
      'set "PATH='+str(PureWindowsPath(vs['cl']).parent)+';%PATH%"']
    if phase in ('port','smoke'):
        src='context_observer_windows.cpp' if phase=='port' else 'windows_sdk_smoke.cpp'
        obj='observer.obj' if phase=='port' else 'smoke.obj'
        command=q(vs['cl'])+' /nologo /c /std:c++17 /EHsc /utf-8 /W4 /WX /MT /DUNICODE /D_UNICODE /DWINVER=0x0A00 /D_WIN32_WINNT=0x0A00 /I'+q(root)+' /I'+q(PureWindowsPath(sdk['root'])/'Include'/ver/'cppwinrt')+' '+q(PureWindowsPath(root)/src)+' /Fo:'+q(PureWindowsPath(root)/obj)
    else:
        command=q(vs['link'])+' /NOLOGO /INCREMENTAL:NO /SUBSYSTEM:CONSOLE /MACHINE:'+arch.upper()+' /OUT:'+q(PureWindowsPath(root)/'sdk-smoke.exe')+' '+q(PureWindowsPath(root)/'observer.obj')+' '+q(PureWindowsPath(root)/'smoke.obj')
    return '\n'.join(head+[command,'exit /b %errorlevel%',''])

def _owned_root(root):
    # One explicitly allowed nonsecret parent lookup, never a copy/iteration.
    temp=os.environ.get('RUNNER_TEMP')
    if type(temp) is not str or not temp:raise GateFailure(2)
    parent=tools.canonical(temp,directory=True);root=Path(root)
    if root.parent!=parent or not re.fullmatch(r'opengeul-sdk-gate-[0-9a-f]{32}',root.name) or root.exists() or root.is_symlink():raise GateFailure(2)
    tools.cmd_path(str(root));root.mkdir();tools.canonical(root,directory=True)
    for name in ('temp','profile','appdata','local'):(root/name).mkdir()
    return root

def overall_window(now,start=None,deadline=None):
    if start is None and deadline is None:return now,now+180.
    if type(start) not in (float,int) or type(deadline) not in (float,int) or not all(math.isfinite(v) for v in (now,start,deadline)) or not start<=now<deadline or abs((deadline-start)-180.)>0.000001 or deadline>now+180.:raise GateFailure(2)
    return start,deadline

def execute(architecture,source_bundle,work_root,*,code_admission=None,outer_start=None,outer_deadline=None):
    result=empty_receipt()
    try:start,overall=overall_window(time.monotonic(),outer_start,outer_deadline)
    except GateFailure:result['failureCode']=2;return result
    try:
        from approved_launch import require_admission
        code_admission=require_admission(code_admission,ROOT)
        result['codeApprovalVerified']=True;result['approvedCodeManifestSha256']=code_admission.manifest_sha256
    except BaseException:result['failureCode']=3;return result
    if sys.platform!='win32':result['failureCode']=1;return result
    source_bundle=Path(source_bundle);root=None;tools_before=None;command_lease=None
    def remaining():
        if time.monotonic()>=overall:raise GateFailure(10)
    try:
        result['stage']=1
        if architecture not in tools.MACHINES:raise GateFailure(2)
        before=tools.verify_bundle(source_bundle);remaining()
        root=_owned_root(work_root);result['workRootCreated']=True
        locations=tools.system_locations(architecture,deadline=overall);command_lease=locations['commandLease']
        machine=tools.MACHINES[architecture];remaining()
        result['architectureCode']=machine;result['controller']=locations['controller']
        result['commandProcessor']=locations['commandRecord'];result['vswhereSha256']=locations['vswhereSha256']
        from owned_job_win32 import NativeApi
        api=NativeApi();runner=Runner(api)
        environment=child_environment(locations['system'],locations['programFiles'],locations['programFilesX86'],str(root))
        def phase(argv,seconds):
            end=phase_deadline(time.monotonic(),overall,seconds)
            command_lease.verify(deadline=end)
            observation={}
            row=runner.run(argv,str(root),environment,end,active_observation=observation)
            result['phaseResults'].append(row)
            result['actualWindowsExecuted']=True
            try:
                if result['phaseActiveObservations'] is not None:
                    result['phaseActiveObservations'].append(None)
                    from ci_entry import validate_phase_active_observations
                    result['phaseActiveObservations'][-1]=validate_phase_active_observations([observation],1)[0]
            except Exception:result['phaseActiveObservations']=None
            command_lease.verify(deadline=end)
            if not row['completed']:raise GateFailure(10 if row['failureCode']==10 else 13)
        require_fresh_outputs(root,('vswhere.json',))
        name=_fresh_text(root,'vs-discovery.cmd',discovery_batch(locations['vswhere']))
        phase([locations['command'],'/d','/v:off','/c',name],15.)
        metadata=tools.vs_metadata(tools.read(root/'vswhere.json',256*1024))
        vs=tools.installed_vs(metadata,architecture)
        result['sdkCandidateObservation']={'operations':[],'failures':[],'failureCount':0,'truncated':False}
        sdk=tools.installed_sdk(locations['sdk'],architecture,observations=result['sdkCandidateObservation'],operation=1)
        for p in (vs['devcmd'],vs['cl'],vs['link'],sdk['root']):tools.cmd_path(p)
        result.update(stage=2,compiler=vs['records']['cl'],linker=vs['records']['link'],compilerVersion=vs['version'],
          installationVersion=vs['installationVersion'],devcmdSha256=vs['devcmdSha256'],sdkVersion=sdk['version'],sdkInputs=sdk['files'])
        tools_before=(vs['records'],vs['devcmdSha256'],locations['commandRecord'])
        inputs={name:source_bundle/name for name in ('context_observer.hpp','context_observer_windows.cpp')}
        inputs.update({name:ROOT/name for name in ('sdk_smoke.hpp','windows_sdk_smoke.cpp')})
        hashes=[]
        for index,(name,src) in enumerate(inputs.items(),1):
            b=code_admission.read_approved(name) if name in ('sdk_smoke.hpp','windows_sdk_smoke.cpp') else tools.read(src,1024*1024)
            with (root/name).open('xb') as stream:stream.write(b)
            hashes.append({'slot':index,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
        result['compileInputs']=hashes
        for code,p in ((3,'port'),(4,'smoke'),(5,'link')):
            remaining();result['stage']=code
            if tools.pe(vs['cl'],machine)!=vs['records']['cl'] or tools.pe(vs['link'],machine)!=vs['records']['link']:raise GateFailure(3)
            require_fresh_outputs(root,({'port':'observer.obj','smoke':'smoke.obj','link':'sdk-smoke.exe'}[p],))
            name=_fresh_text(root,'compile-'+p+'.cmd',compile_batch(p,vs,sdk,root,architecture))
            phase([locations['command'],'/d','/v:off','/c',name],30.)
            if p=='port':result['portObject']=tools.coff(root/'observer.obj',machine);result['nativeSdkCompiled']=True
            elif p=='smoke':result['smokeObject']=tools.coff(root/'smoke.obj',machine)
            else:result['executable']=tools.pe(root/'sdk-smoke.exe',machine);result['nativeLinked']=True
        result['stage']=6;exe=root/'sdk-smoke.exe'
        phase([str(exe)],10.)
        if tools.pe(exe,machine)!=result['executable']:raise GateFailure(3)
        result['negativeSmokePassed']=True
        for index,(name,src) in enumerate(inputs.items()):
            if hashlib.sha256(tools.read(src,1024*1024)).hexdigest()!=hashes[index]['sha256'] or hashlib.sha256(tools.read(root/name,1024*1024)).hexdigest()!=hashes[index]['sha256']:raise GateFailure(3)
        after=(dict(cl=tools.pe(vs['cl'],machine),link=tools.pe(vs['link'],machine)),hashlib.sha256(tools.read(vs['devcmd'],1024*1024)).hexdigest(),command_lease.verify())
        if after!=tools_before or tools.installed_sdk(locations['sdk'],architecture,observations=result['sdkCandidateObservation'],operation=2)!=sdk:raise GateFailure(3)
        code_admission.require_root(ROOT)
        if tools.verify_bundle(source_bundle)!=before:raise GateFailure(3)
        remaining();result.update(stage=7,frozenV2Preserved=True,sdkGatePassed=True)
    except BaseException as error:
        from ci_entry import failure_observation
        result['failureObservation']=failure_observation(error,result['stage'])
        result['failureCode']=error.code if isinstance(error,GateFailure) else 31
        result['cancelled']=isinstance(error,(KeyboardInterrupt,SystemExit))
    finally:
        if command_lease is not None:
            if not command_lease.close():result['sdkGatePassed']=False;result['failureCode']=14
            result['commandProcessorBinding']=command_lease.observation()
        result['startedAt']=start;result['deadline']=overall;result['finishedAt']=time.monotonic()
        if result['finishedAt']>overall:result['sdkGatePassed']=False;result['failureCode']=10
    return result

class Parser(argparse.ArgumentParser):
    def error(self,message):raise GateFailure(2)

def main(argv=None,*,code_admission=None):
    try:
        p=Parser(add_help=False);p.add_argument('--diagnostic-sdk-only',action='store_true',required=True)
        p.add_argument('--architecture',choices=('x64','arm64'),required=True)
        p.add_argument('--source-bundle',required=True);p.add_argument('--work-root',required=True);p.add_argument('--output',required=True)
        p.add_argument('--overall-start',type=float);p.add_argument('--overall-deadline',type=float)
        a=p.parse_args(argv);root=Path(a.work_root);output=Path(a.output)
        if output.parent!=root or output.name!='sdk-gate.numeric.json':raise GateFailure(2)
        value=execute(a.architecture,Path(a.source_bundle),root,code_admission=code_admission,outer_start=a.overall_start,outer_deadline=a.overall_deadline)
        encoded=json.dumps(value,sort_keys=True,separators=(',',':')).encode()+b'\n'
        if len(encoded)>16384:raise GateFailure(2)
        if value['workRootCreated']:
            tools.canonical(root,directory=True)
            with output.open('xb') as stream:stream.write(encoded)
        print(json.dumps({'schemaVersion':1,'kind':value['kind'],'stage':value['stage'],'failureCode':value['failureCode'],
          'sdkGatePassed':value['sdkGatePassed'],'actualWindowsExecuted':value['actualWindowsExecuted'],
          'nativeSdkCompiled':value['nativeSdkCompiled'],'qualification':False,'canService':False},sort_keys=True))
        return 0 if value['sdkGatePassed'] else 2
    except BaseException:return 2

def _batch_rows(data):
    if type(data) is not bytes or not 0<len(data)<=64 or not data.endswith(b'\r\n'):raise GateFailure(2)
    rows=data[:-2].split(b'\r\n')
    if not 1<=len(rows)<=4:raise GateFailure(2)
    result=[]
    for stage,line in enumerate(rows,1):
        match=re.fullmatch(rb'([1-4]) (0|-[1-9][0-9]{0,9}|[1-9][0-9]{0,9})',line)
        if match is None:raise GateFailure(2)
        code,value=map(int,match.groups())
        if code!=stage or not -2147483648<=value<=4294967295:raise GateFailure(2)
        result.append([code,value])
    return result

def decode_batch_canary(trace,returned):
    rows=_batch_rows(trace)
    if type(returned) is not bytes or not 0<len(returned)<=64 or not returned.endswith(b'\r\n'):raise GateFailure(2)
    values=returned[:-2].split(b'\r\n')
    if rows!=[[1,0],[2,2],[3,5]] or values!=[b'0',b'2',b'5']:raise GateFailure(2)
    return {'statusCode':1,'reasonCode':0,'returns':[int(value) for value in values]}

def decode_batch_trace(data):
    rows=_batch_rows(data)
    status=1 if len(rows)==4 and rows[1][1]<1 else 2 if len(rows)==2 and rows[1][1]>=1 else 0
    if not status:raise GateFailure(2)
    return {'statusCode':status,'reasonCode':0,'rows':rows}

def _batch_mark(stage):
    return ['set "OPENGEUL_SERIALIZER_RC=%errorlevel%"',
      'call :serializer_phase '+str(stage)+' %OPENGEUL_SERIALIZER_RC%']

def _batch_marker(leaf):
    if leaf not in ('sdk-canary.phase','sdk-port.phase','sdk-smoke.phase','sdk-link.phase'):raise GateFailure(2)
    return [':serializer_phase','>>"'+leaf+'" echo %1 %2','exit /b %2']

def batch_discovery_template(vswhere):
    original=discovery_batch(vswhere).splitlines()
    if len(original)!=3 or original[-1]!='exit /b %errorlevel%':raise GateFailure(2)
    lines=original[:-1]+['set "OPENGEUL_SDK_DISCOVERY_RC=%errorlevel%"',
      'if not "%OPENGEUL_SDK_DISCOVERY_RC%"=="0" exit /b %OPENGEUL_SDK_DISCOVERY_RC%']
    for stage,value in enumerate((0,2,5),1):
        lines+=['call :sdk_canary_return '+str(value)]+_batch_mark(stage)+['>>"sdk-canary.return" echo %errorlevel%']
    lines+=['exit /b %OPENGEUL_SDK_DISCOVERY_RC%',':sdk_canary_return','exit /b %1']+_batch_marker('sdk-canary.phase')
    return '\n'.join(lines)+'\n'

def batch_compile_template(original,phase):
    if type(original) is not str or type(phase) is not int or phase not in (3,4,5):raise GateFailure(2)
    lines=original.splitlines()
    if (len(lines)<5 or lines[0]!='@echo off' or not lines[1].startswith('call "')
        or lines[2]!='if errorlevel 1 exit /b %errorlevel%' or lines[-1]!='exit /b %errorlevel%'
        or not lines[-2].startswith('"')):raise GateFailure(2)
    leaf={3:'sdk-port.phase',4:'sdk-smoke.phase',5:'sdk-link.phase'}[phase]
    value=lines[:1]+_batch_mark(1)+lines[1:2]+_batch_mark(2)+lines[2:-2]+_batch_mark(3)+lines[-2:-1]+_batch_mark(4)+lines[-1:]+_batch_marker(leaf)
    return '\n'.join(value)+'\n'

class BatchObservation:
    """Untrusted B hints only. No normal/default SDK entry point uses this."""
    def __init__(self,root,machine,manifest,deadline,*,clock=time.monotonic):
        if type(machine) is not int or machine not in tools.MACHINES.values() or type(manifest) is not str or not re.fullmatch('[0-9a-f]{64}',manifest):raise GateFailure(2)
        self.root=Path(root);self.deadline=deadline;self.clock=clock;self.cancelled=False;self.reason=0;self.enabled={}
        self.value={'schemaVersion':1,'kind':'sdk-batch-hints-private','mode':'instrumented-batch-hints',
          'architectureCode':machine,'approvedCodeManifestSha256':manifest,'expectedSourceInputsSha256':tools.SOURCE_INPUTS_SHA,
          'originalSdkGateExecuted':False,'acceptanceEligible':False,'qualification':False,'canService':False,
          'childWritable':True,'authority':False,'compilerInvocationProved':False,
          'canary':{'statusCode':0,'reasonCode':1,'returns':None},'phases':[]}
    def _read(self,leaf):
        if leaf not in ('sdk-canary.phase','sdk-canary.return','sdk-port.phase','sdk-smoke.phase','sdk-link.phase'):raise GateFailure(2)
        if self.clock()>=self.deadline:raise GateFailure(10)
        value=tools.read(self.root/leaf,64)
        if self.clock()>=self.deadline:raise GateFailure(10)
        return value
    def _drop(self,reason):
        self.value=None;self.reason=reason
    def template(self,original,phase):
        if self.cancelled:raise SystemExit(130)
        enabled=False
        try:
            if self.value is not None and self.value['canary']['statusCode']==1:
                value=batch_compile_template(original,phase);self.enabled[phase]=True;return value
        except (KeyboardInterrupt,SystemExit):self.cancelled=True;self._drop(6);raise
        except Exception:pass
        try:self.enabled[phase]=enabled
        except Exception:self._drop(6)
        return original
    @staticmethod
    def retired(row):
        return (type(row) is dict and all(row.get(key) is True for key in ('cleanupProved','rootExitObserved','jobEmptyObserved','identityRechecked'))
          and type(row.get('handlesClosed')) is int and row['handlesClosed']==4)
    def collect(self,phase,row):
        if self.cancelled or self.value is None:return
        pending=sys.exc_info()[1]
        try:
            if row.get('cancelled') is True:
                self.cancelled=True;self._drop(7);return
            enabled=self.enabled.get(phase,False)
            if not self.retired(row) or (phase==1 and (row.get('completed') is not True or row.get('forcedCleanup') is not False or row.get('exitCode')!=0)):
                reason=2;record=None
            elif phase==1:
                record=decode_batch_canary(self._read('sdk-canary.phase'),self._read('sdk-canary.return'));reason=0
            elif not enabled:record=None;reason=8 if self.value['canary']['statusCode']==1 else 1
            else:
                leaf={3:'sdk-port.phase',4:'sdk-smoke.phase',5:'sdk-link.phase'}[phase]
                record=decode_batch_trace(self._read(leaf));reason=0
        except BaseException as error:
            if isinstance(error,(KeyboardInterrupt,SystemExit)):
                self.cancelled=True;self._drop(6)
                if pending is None:raise
                return
            reason=3 if isinstance(error,FileNotFoundError) else 5 if isinstance(error,GateFailure) and error.code==10 else 4 if isinstance(error,GateFailure) else 6
            record=None
        try:
            if phase==1:self.value['canary']=record if record is not None else {'statusCode':2,'reasonCode':reason,'returns':None}
            else:self.value['phases'].append({'phaseCode':phase,'enabled':enabled,**(record if record is not None else {'statusCode':0,'reasonCode':reason,'rows':None})})
        except BaseException as error:
            self._drop(6)
            if isinstance(error,(KeyboardInterrupt,SystemExit)):
                self.cancelled=True
                if pending is None:raise





def _batch_collect_preserving(tracker,phase,row):
    pending=sys.exc_info()[1]
    try:tracker.collect(phase,row)
    except BaseException as error:
        if isinstance(error,(KeyboardInterrupt,SystemExit)):tracker.cancelled=True
        try:tracker._drop(6)
        except BaseException:pass
        if isinstance(error,(KeyboardInterrupt,SystemExit)) and pending is None:raise

def empty_batch_receipt():
    value=empty_receipt()
    value.update(schemaVersion=1,kind='sdk-batch-instrumented-helper',mode='instrumented-batch-hints',
      originalSdkGateExecuted=False,acceptanceEligible=False,sourceInputsVerified=False,batchObservation=None,batchUnavailableReasonCode=7)
    for old,new in (('sdkGatePassed','instrumentedChecksPassed'),('nativeSdkCompiled','instrumentedPortObjectVerified'),
      ('nativeLinked','instrumentedLinkVerified'),('negativeSmokePassed','instrumentedNegativeSmokePassed')):
        value[new]=value.pop(old)
    return value

def execute_instrumented(architecture,source_bundle,work_root,*,code_admission=None,outer_start=None,outer_deadline=None):
    result=empty_batch_receipt()
    try:start,overall=overall_window(time.monotonic(),outer_start,outer_deadline)
    except GateFailure:result['failureCode']=2;return result
    try:
        from approved_launch import require_batch_admission
        code_admission=require_batch_admission(code_admission,ROOT)
        result['codeApprovalVerified']=True;result['approvedCodeManifestSha256']=code_admission.manifest_sha256
    except (KeyboardInterrupt,SystemExit):raise
    except BaseException:result['failureCode']=3;return result
    if sys.platform!='win32':result['failureCode']=1;return result
    source_bundle=Path(source_bundle);root=None;tools_before=None;command_lease=None;tracker=None
    def remaining():
        if time.monotonic()>=overall:raise GateFailure(10)
    try:
        result['stage']=1
        if architecture not in tools.MACHINES:raise GateFailure(2)
        before=tools.verify_bundle(source_bundle);result['sourceInputsVerified']=True;remaining()
        root=_owned_root(work_root);result['workRootCreated']=True
        locations=tools.system_locations(architecture,deadline=overall);command_lease=locations['commandLease']
        machine=tools.MACHINES[architecture];remaining()
        tracker=BatchObservation(root,machine,code_admission.manifest_sha256,overall,clock=time.monotonic)
        result['architectureCode']=machine;result['controller']=locations['controller']
        result['commandProcessor']=locations['commandRecord'];result['vswhereSha256']=locations['vswhereSha256']
        from owned_job_win32 import NativeApi
        api=NativeApi();runner=Runner(api)
        environment=child_environment(locations['system'],locations['programFiles'],locations['programFilesX86'],str(root))
        def phase(argv,seconds,*,phase_code=None):
            end=phase_deadline(time.monotonic(),overall,seconds)
            command_lease.verify(deadline=end)
            observation={}
            row=runner.run(argv,str(root),environment,end,active_observation=observation)
            result['phaseResults'].append(row)
            result['actualWindowsExecuted']=True
            try:
                if result['phaseActiveObservations'] is not None:
                    result['phaseActiveObservations'].append(None)
                    from ci_entry import validate_phase_active_observations
                    result['phaseActiveObservations'][-1]=validate_phase_active_observations([observation],1)[0]
            except Exception:result['phaseActiveObservations']=None
            if row.get('cancelled') is True:tracker.cancelled=True
            try:
                command_lease.verify(deadline=end)
                if tracker.cancelled:raise SystemExit(130)
                if not row['completed']:raise GateFailure(10 if row['failureCode']==10 else 13)
            finally:
                if phase_code is not None:_batch_collect_preserving(tracker,phase_code,row)
            if tracker.cancelled:raise SystemExit(130)
        require_fresh_outputs(root,('vswhere.json',))
        name=_fresh_text(root,'vs-discovery.cmd',batch_discovery_template(locations['vswhere']))
        phase([locations['command'],'/d','/v:off','/c',name],15.,phase_code=1)
        metadata=tools.vs_metadata(tools.read(root/'vswhere.json',256*1024))
        vs=tools.installed_vs(metadata,architecture)
        result['sdkCandidateObservation']={'operations':[],'failures':[],'failureCount':0,'truncated':False}
        sdk=tools.installed_sdk(locations['sdk'],architecture,observations=result['sdkCandidateObservation'],operation=1)
        for p in (vs['devcmd'],vs['cl'],vs['link'],sdk['root']):tools.cmd_path(p)
        result.update(stage=2,compiler=vs['records']['cl'],linker=vs['records']['link'],compilerVersion=vs['version'],
          installationVersion=vs['installationVersion'],devcmdSha256=vs['devcmdSha256'],sdkVersion=sdk['version'],sdkInputs=sdk['files'])
        tools_before=(vs['records'],vs['devcmdSha256'],locations['commandRecord'])
        inputs={name:source_bundle/name for name in ('context_observer.hpp','context_observer_windows.cpp')}
        inputs.update({name:ROOT/name for name in ('sdk_smoke.hpp','windows_sdk_smoke.cpp')})
        hashes=[]
        for index,(name,src) in enumerate(inputs.items(),1):
            b=code_admission.read_approved(name) if name in ('sdk_smoke.hpp','windows_sdk_smoke.cpp') else tools.read(src,1024*1024)
            with (root/name).open('xb') as stream:stream.write(b)
            hashes.append({'slot':index,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
        result['compileInputs']=hashes
        for code,p in ((3,'port'),(4,'smoke'),(5,'link')):
            remaining();result['stage']=code
            if tools.pe(vs['cl'],machine)!=vs['records']['cl'] or tools.pe(vs['link'],machine)!=vs['records']['link']:raise GateFailure(3)
            require_fresh_outputs(root,({'port':'observer.obj','smoke':'smoke.obj','link':'sdk-smoke.exe'}[p],))
            name=_fresh_text(root,'compile-'+p+'.cmd',tracker.template(compile_batch(p,vs,sdk,root,architecture),code))
            phase([locations['command'],'/d','/v:off','/c',name],30.,phase_code=code)
            if p=='port':result['portObject']=tools.coff(root/'observer.obj',machine);result['instrumentedPortObjectVerified']=True
            elif p=='smoke':result['smokeObject']=tools.coff(root/'smoke.obj',machine)
            else:result['executable']=tools.pe(root/'sdk-smoke.exe',machine);result['instrumentedLinkVerified']=True
        result['stage']=6;exe=root/'sdk-smoke.exe'
        phase([str(exe)],10.)
        if tools.pe(exe,machine)!=result['executable']:raise GateFailure(3)
        result['instrumentedNegativeSmokePassed']=True
        for index,(name,src) in enumerate(inputs.items()):
            if hashlib.sha256(tools.read(src,1024*1024)).hexdigest()!=hashes[index]['sha256'] or hashlib.sha256(tools.read(root/name,1024*1024)).hexdigest()!=hashes[index]['sha256']:raise GateFailure(3)
        after=(dict(cl=tools.pe(vs['cl'],machine),link=tools.pe(vs['link'],machine)),hashlib.sha256(tools.read(vs['devcmd'],1024*1024)).hexdigest(),command_lease.verify())
        if after!=tools_before or tools.installed_sdk(locations['sdk'],architecture,observations=result['sdkCandidateObservation'],operation=2)!=sdk:raise GateFailure(3)
        code_admission.require_root(ROOT)
        if tools.verify_bundle(source_bundle)!=before:raise GateFailure(3)
        remaining();result.update(stage=7,frozenV2Preserved=True,instrumentedChecksPassed=True)
    except BaseException as error:
        from ci_entry import failure_observation
        result['failureObservation']=failure_observation(error,result['stage'])
        result['failureCode']=error.code if isinstance(error,GateFailure) else 31
        result['cancelled']=isinstance(error,(KeyboardInterrupt,SystemExit))
    finally:
        if tracker is not None:
            try:
                result['cancelled']=bool(result.get('cancelled',False) or tracker.cancelled)
                result['batchObservation']=tracker.value;result['batchUnavailableReasonCode']=tracker.reason
            except BaseException as error:
                if isinstance(error,(KeyboardInterrupt,SystemExit)):result['cancelled']=True
                result['batchObservation']=None;result['batchUnavailableReasonCode']=6
        if command_lease is not None:
            if not command_lease.close():result['instrumentedChecksPassed']=False;result['failureCode']=14
            result['commandProcessorBinding']=command_lease.observation()
        result['startedAt']=start;result['deadline']=overall;result['finishedAt']=time.monotonic()
        if result['finishedAt']>overall:result['instrumentedChecksPassed']=False;result['failureCode']=10
    return result

def batch_main(argv=None,*,code_admission=None):
    """Explicit B helper. Its output can never be a normal SDK report."""
    try:
        p=Parser(add_help=False)
        for name in ('architecture','source-bundle','work-root','output'):p.add_argument('--'+name,required=True)
        p.add_argument('--overall-start',type=float);p.add_argument('--overall-deadline',type=float)
        a=p.parse_args(argv);root=Path(a.work_root);output=Path(a.output)
        if a.architecture not in tools.MACHINES or output!=root/'sdk-batch.numeric.json':raise GateFailure(2)
        value=execute_instrumented(a.architecture,Path(a.source_bundle),root,code_admission=code_admission,
          outer_start=a.overall_start,outer_deadline=a.overall_deadline)
        if value.get('cancelled') is True:return 130
        encoded=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
        if len(encoded)>16384:raise GateFailure(2)
        if value['workRootCreated']:
            tools.canonical(root,directory=True)
            with output.open('xb') as stream:stream.write(encoded)
        return 0 if value['instrumentedChecksPassed'] else 2
    except (KeyboardInterrupt,SystemExit):return 130
    except Exception:return 2

if __name__=='__main__':raise SystemExit(main())
