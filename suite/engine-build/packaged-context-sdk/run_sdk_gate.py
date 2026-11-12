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
    return {'schemaVersion':1,'kind':'packaged-context-sdk-negative-gate','stage':0,'failureCode':0,
      'sdkGatePassed':False,'actualWindowsExecuted':False,'nativeSdkCompiled':False,'nativeLinked':False,
      'negativeSmokePassed':False,'actualPackageObservation':False,'qualification':False,'canService':False,
      'originalHelperHandleKnown':False,'packagedHelperLauncherImplemented':False,'watchdogVerified':False,
      'synchronousOsCallPreemptionVerified':False,'osImplicitEffectsKnown':False,'frozenV2Preserved':False,
      'pure40TestsRerun':False,'lease6TestsRerun':False,'workRootCreated':False,'codeApprovalVerified':False,
      'commandProcessorBinding':None,'phaseResults':[],'failureObservation':None}

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
            row=runner.run(argv,str(root),environment,end);result['phaseResults'].append(row)
            result['actualWindowsExecuted']=True
            command_lease.verify(deadline=end)
            if not row['completed']:raise GateFailure(10 if row['failureCode']==10 else 13)
        require_fresh_outputs(root,('vswhere.json',))
        name=_fresh_text(root,'vs-discovery.cmd',discovery_batch(locations['vswhere']))
        phase([locations['command'],'/d','/v:off','/c',name],15.)
        metadata=tools.vs_metadata(tools.read(root/'vswhere.json',256*1024))
        vs=tools.installed_vs(metadata,architecture);sdk=tools.installed_sdk(locations['sdk'],architecture)
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
        if after!=tools_before or tools.installed_sdk(locations['sdk'],architecture)!=sdk:raise GateFailure(3)
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

if __name__=='__main__':raise SystemExit(main())
