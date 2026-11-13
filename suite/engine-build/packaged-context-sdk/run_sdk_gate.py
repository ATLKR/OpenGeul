"""Scratch-only SDK build/negative-smoke candidate. No package observation mode."""
from __future__ import annotations
import sys
if __name__=='__main__':raise SystemExit(3)
import argparse
import hashlib
import json
import math
import ntpath
import stat
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

SDK_COMPILER_FILES=('context_observer.hpp','context_observer_windows.cpp','sdk_smoke.hpp','windows_sdk_smoke.cpp')

def project_compiler_diagnostics(stdout,stderr,root):
    files={ntpath.normcase(str(root/name)):index for index,name in enumerate(SDK_COMPILER_FILES,1)}
    files.update({name:index for index,name in enumerate(SDK_COMPILER_FILES,1)})
    located=re.compile(r'^(.*?)\(([1-9][0-9]{0,6})(?:,[1-9][0-9]{0,6})?\)\s*:\s*([^:\r\n]{1,64}?)\s+(C|D|LNK)([0-9]{4})\s*:')
    driver=re.compile(r'^(?:[^:()\r\n]{1,64}\s*:\s*)?([^:()\r\n]{1,64}?)\s+(C|D|LNK)([0-9]{4})\s*:')
    kinds={'C':1,'D':2,'LNK':3};severities={'warning':1,'error':2,'fatal error':3,'command line warning':1,'command line error':2}
    value=dict(scanComplete=1,droppedCount=0,diagnostics=[])
    for stream,text in enumerate((stdout,stderr),1):
        if type(text)is not str:value['scanComplete']=0;continue
        if len(text)>65536:value['scanComplete']=0
        rows=text[:65536].splitlines()
        if len(rows)>512:value['scanComplete']=0
        for row in rows[:512]:
            if len(row)>4096:value['scanComplete']=0;continue
            match=located.match(row)
            if match:
                path,line,severity,kind,number=match.groups();code=files.get(ntpath.normcase(path.strip()),0);line=int(line)if code else 0
            else:
                match=driver.match(row)
                if not match:continue
                severity,kind,number=match.groups();code=line=0
            descriptor=dict(streamCode=stream,severity=severities.get(severity.strip().lower(),0),kind=kinds[kind],number=int(number),fileCode=code,line=line)
            if len(value['diagnostics'])<32:value['diagnostics'].append(descriptor)
            else:value['droppedCount']+=1
    return value

def project_first_c2338_detail(stdout,stderr,projection,sdk_paths):
    """One untrusted numeric hint from the already-read bounded streams."""
    first=next(((index,row)for index,row in enumerate(projection['diagnostics'],1)
      if row['kind']==1 and row['number']==2338),None)
    if first is None:return None
    ordinal,target=first;seen=0
    located=re.compile(r'^(.*?)\(([1-9][0-9]{0,6})(?:,[1-9][0-9]{0,6})?\)\s*:\s*([^:\r\n]{1,64}?)\s+(C|D|LNK)([0-9]{4})\s*:')
    driver=re.compile(r'^(?:[^:()\r\n]{1,64}\s*:\s*)?([^:()\r\n]{1,64}?)\s+(C|D|LNK)([0-9]{4})\s*:')
    literals=('Mismatched C++/WinRT headers.','Not an awaitable type.',
      'Only native x64/ARM64 observers are supported','T must be WinRT type.')
    paths={ntpath.normcase(path):slot for slot,path in sdk_paths.items()}
    for stream,text in enumerate((stdout,stderr),1):
        if type(text)is not str:continue
        for row in text[:65536].splitlines()[:512]:
            if len(row)>4096:continue
            match=located.match(row);path=None;line=0
            if match:path,line,_,kind,number=match.groups()
            else:
                match=driver.match(row)
                if not match:continue
                _,kind,number=match.groups()
            seen+=1
            if seen!=ordinal:continue
            if stream!=target['streamCode']or kind!='C'or int(number)!=2338:return None
            slot=paths.get(ntpath.normcase(path.strip()),0)if path is not None else 0
            classes=[index for index,literal in enumerate(literals,1)if literal in row[match.end():]]
            return dict(diagnosticOrdinal=ordinal,streamCode=stream,sdkSlot=slot,
              line=int(line)if slot else 0,assertionClass=classes[0]if len(classes)==1 else 0)
    return None

def project_source_assertion(stdout,stderr,projection):
    """Source-only first assertion body; never a general error/console collector."""
    from ci_entry import source_assertion_status
    first=next(((index,row)for index,row in enumerate(projection['diagnostics'],1)
      if row['kind']==1 and row['number']==2338),None)
    if first is None:return None
    ordinal,target=first;seen=0
    value=dict(diagnosticOrdinal=ordinal,streamCode=target['streamCode'],statusCode=8,text=None)
    # The unchanged numeric parser uses splitlines(). Do not bind a later LF row
    # to its ordinal if any other line separator can change that row sequence.
    if any(type(text)is str and re.search(r'[\v\f\x1c-\x1e\x85\u2028\u2029]|\r(?!\n)',text[:65536])for text in(stdout,stderr)):
        value['statusCode']=4;return value
    located=re.compile(r'^(.*?)\(([1-9][0-9]{0,6})(?:,[1-9][0-9]{0,6})?\)\s*:\s*([^:\r\n]{1,64}?)\s+(C|D|LNK)([0-9]{4})\s*:')
    driver=re.compile(r'^(?:[^:()\r\n]{1,64}\s*:\s*)?([^:()\r\n]{1,64}?)\s+(C|D|LNK)([0-9]{4})\s*:')
    for stream,text in enumerate((stdout,stderr),1):
        if type(text)is not str:continue
        lines=text[:65536].split('\n')
        for index,row in enumerate(lines[:512]):
            if index<len(lines)-1 and row.endswith('\r'):row=row[:-1]
            if len(row)>4096:continue
            match=located.match(row)
            if match:_,_,_,kind,number=match.groups()
            else:
                match=driver.match(row)
                if not match:continue
                _,kind,number=match.groups()
            seen+=1
            if seen!=ordinal:continue
            if stream!=target['streamCode']or kind!='C'or int(number)!=2338:return value
            body=row[match.end():];status=source_assertion_status(body)
            value.update(statusCode=status,text=body if status==1 else None)
            return value
    return value

class PortCompilerCapture:
    """Source-only port private files; these observations have no compiler authority."""
    LEAVES=('sdk-port.stdout','sdk-port.stderr')
    def __init__(self,root,deadline,*,clock=time.monotonic):
        self.root=Path(root);self.deadline=deadline;self.clock=clock
        self.identities=[];self.prepared=False;self.attempted=False;self.cancelled=False;self.prepare_status=0;self.cleanup_unknown=False;self.cancel_error=None
        self.sdk_paths={}
    def bind_sdk(self,sdk,architecture):
        # Caller supplies only the result of the existing SDK-16 authenticated read.
        # Construct fixed slot paths without re-reading headers or collecting metadata.
        try:
            if type(sdk)is not dict or set(sdk)!={'root','version','files'}or len(sdk['files'])!=16:raise GateFailure(2)
            members=tools.sdk_members(sdk['version'],architecture)
            if any(type(sdk['files'][slot-1])is not dict or type(sdk['files'][slot-1].get('slot'))is not int or sdk['files'][slot-1]['slot']!=slot for slot in(8,9)):raise GateFailure(2)
            self.sdk_paths={slot:str(Path(sdk['root'])/members[slot-1])for slot in(8,9)}
        except Exception:self.sdk_paths={}
    def remaining(self):
        if self.clock()>=self.deadline:raise GateFailure(10)
    def packet(self,statuses,counts=None,projection=None,detail=None,assertion=None):
        return dict(phaseCode=3,prepared=self.prepared,streamStatus=statuses,
          streamBytes=[None,None]if counts is None else counts,projection=projection,firstC2338Detail=detail,firstC2338SourceAssertion=assertion)
    def prepare(self):
        if self.attempted:return False
        self.attempted=True;pending=sys.exc_info()[1]
        try:
            self.remaining();tools.canonical(self.root,directory=True)
            for leaf in self.LEAVES:
                self.remaining();path=self.root/leaf;fd=None;primary=None;identity=None
                try:
                    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0),0o600)
                    before=os.fstat(fd);after=tools.canonical(path).stat()
                    if (not stat.S_ISREG(before.st_mode)or before.st_nlink!=1 or before.st_size!=0
                      or type(before.st_dev)is not int or type(before.st_ino)is not int or before.st_ino<=0
                      or tools._identity(before)!=tools._identity(after)):raise GateFailure(2)
                    identity=(before.st_dev,before.st_ino)
                except BaseException as error:primary=error
                finally:
                    if fd is not None:
                        try:os.close(fd)
                        except BaseException as error:
                            self.cleanup_unknown=True
                            if isinstance(error,(KeyboardInterrupt,SystemExit)):self.cancelled=True;self.cancel_error=error
                            if primary is None:primary=error
                if primary is not None:raise primary
                self.remaining();self.identities.append(identity)
            self.prepared=True;return True
        except BaseException as error:
            self.prepare_status=8 if isinstance(error,GateFailure)and error.code==10 else 9
            if self.cancel_error is not None and pending is None:raise self.cancel_error
            if isinstance(error,(KeyboardInterrupt,SystemExit)):
                self.cancelled=True
                if pending is None:raise
            return False
    def redirect(self,command):
        if not self.prepared:return command
        if type(command)is not str or any(c in command for c in '\r\n<>|&'):raise GateFailure(2)
        return command+' 1>"sdk-port.stdout" 2>"sdk-port.stderr"'
    def _read(self,index):
        self.remaining();path=tools.canonical(self.root/self.LEAVES[index]);before=path.stat()
        if (before.st_dev,before.st_ino)!=self.identities[index]:raise GateFailure(2)
        if before.st_size>65536:return 4,None,None
        fd=None;primary=None;data=None
        try:
            self.remaining();fd=os.open(path,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0))
            first=os.fstat(fd)
            if tools._identity(before)!=tools._identity(first):raise GateFailure(2)
            with os.fdopen(fd,'rb',closefd=False)as stream:data=stream.read(65537)
            after=os.fstat(fd)
            if len(data)>65536 or tools._identity(first)!=tools._identity(after)or tools._identity(after)!=tools._identity(tools.canonical(path).stat()):raise GateFailure(2)
        except BaseException as error:primary=error
        finally:
            if fd is not None:
                try:os.close(fd)
                except BaseException as error:
                    self.cleanup_unknown=True
                    if isinstance(error,(KeyboardInterrupt,SystemExit)):self.cancelled=True;self.cancel_error=error
                    if primary is None:primary=error
        if primary is not None:raise primary
        self.remaining();text=data.decode('utf-8','strict')
        return (1 if not data else 2),len(data),text
    def observe(self,row):
        pending=sys.exc_info()[1]
        if row.get('cancelled')is True:
            self.cancelled=True;return self.packet([7,7])
        if not self.prepared:return self.packet([self.prepare_status or 0]*2)
        if not BatchObservation.retired(row):return self.packet([7,7])
        values=[];statuses=[];counts=[]
        try:
            for index in range(2):
                try:status,count,text=self._read(index)
                except FileNotFoundError:status,count,text=3,None,None
                except UnicodeDecodeError:status,count,text=5,None,None
                except GateFailure as error:status,count,text=(8 if error.code==10 else 6),None,None
                except OSError:status,count,text=9,None,None
                if self.cancel_error is not None:raise self.cancel_error
                statuses.append(status);counts.append(count);values.append(text)
                if self.cleanup_unknown:
                    statuses.extend([9]*(2-len(statuses)));counts.extend([None]*(2-len(counts)));break
                if status==8:
                    statuses.extend([8]*(2-len(statuses)));counts.extend([None]*(2-len(counts)));break
            if all(status in(1,2)for status in statuses):
                self.remaining()
                value=project_compiler_diagnostics(values[0],values[1],self.root)
                detail=next((dict(diagnosticOrdinal=index,streamCode=row['streamCode'],sdkSlot=0,line=0,assertionClass=0)
                  for index,row in enumerate(value['diagnostics'],1)if row['kind']==1 and row['number']==2338),None)
                try:
                    observed=project_first_c2338_detail(values[0],values[1],value,self.sdk_paths)
                    if observed is not None:detail=observed
                except Exception:pass
                assertion=None if detail is None else dict(diagnosticOrdinal=detail['diagnosticOrdinal'],streamCode=detail['streamCode'],statusCode=8,text=None)
                try:assertion=project_source_assertion(values[0],values[1],value)
                except Exception:pass
                self.remaining();return self.packet(statuses,counts,value,detail,assertion)
            return self.packet(statuses,counts)
        except BaseException as error:
            if isinstance(error,(KeyboardInterrupt,SystemExit)):
                self.cancelled=True
                if pending is None:raise
            return self.packet([8,8]if isinstance(error,GateFailure)and error.code==10 else[10,10])

class BatchObservation:
    """Untrusted B hints only. No normal/default SDK entry point uses this."""
    def __init__(self,root,machine,manifest,deadline,*,clock=time.monotonic):
        if type(machine) is not int or machine not in tools.MACHINES.values() or type(manifest) is not str or not re.fullmatch('[0-9a-f]{64}',manifest):raise GateFailure(2)
        self.root=Path(root);self.deadline=deadline;self.clock=clock;self.cancelled=False;self.reason=0;self.enabled={}
        self.capture=PortCompilerCapture(self.root,deadline,clock=clock)
        self.value={'schemaVersion':4,'kind':'sdk-source-assert-private','mode':'source-assert',
          'architectureCode':machine,'approvedCodeManifestSha256':manifest,'expectedSourceInputsSha256':tools.SOURCE_INPUTS_SHA,
          'originalSdkGateExecuted':False,'acceptanceEligible':False,'qualification':False,'canService':False,
          'childWritable':True,'authority':False,'compilerInvocationProved':False,
          'canary':{'statusCode':0,'reasonCode':1,'returns':None},'phases':[],'compilerDiagnostics':None}
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
                value=batch_compile_template(original,phase)
                if phase==3:
                    prepared=self.capture.prepare()
                    if self.capture.cleanup_unknown:raise GateFailure(14)
                    if prepared:
                        command=original.splitlines()[-2]
                        if value.count(command)!=1:raise GateFailure(2)
                        value=value.replace(command,self.capture.redirect(command),1)
                self.enabled[phase]=True;return value
        except (KeyboardInterrupt,SystemExit):self.cancelled=True;self._drop(6);raise
        except Exception:
            if self.capture.cleanup_unknown:raise GateFailure(14)
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
            if phase==3:
                self.value['compilerDiagnostics']=self.capture.observe(row)
                if self.capture.cancelled:self.cancelled=True
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
    value.update(schemaVersion=4,kind='sdk-source-assert-helper',mode='source-assert',
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
            if tracker.capture.cleanup_unknown:raise GateFailure(14)
        require_fresh_outputs(root,('vswhere.json',))
        name=_fresh_text(root,'vs-discovery.cmd',batch_discovery_template(locations['vswhere']))
        phase([locations['command'],'/d','/v:off','/c',name],15.,phase_code=1)
        metadata=tools.vs_metadata(tools.read(root/'vswhere.json',256*1024))
        vs=tools.installed_vs(metadata,architecture)
        result['sdkCandidateObservation']={'operations':[],'failures':[],'failureCount':0,'truncated':False}
        sdk=tools.installed_sdk(locations['sdk'],architecture,observations=result['sdkCandidateObservation'],operation=1)
        tracker.capture.bind_sdk(sdk,architecture)
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
