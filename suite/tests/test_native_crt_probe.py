"""Portable process/receipt boundaries; actual Windows native proof stays in CI."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import select
import shutil
import socket
import subprocess
import struct
import sys
import tempfile
import time
import traceback
import unittest
from types import SimpleNamespace as NS
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'suite/scripts/probe-native-crt.ps1'
PWSH=shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'

def quote(value):return "'"+str(value).replace("'","''")+"'"


def _serializer_environment():
    # The offline compiler needs Windows/tool discovery, never service tokens.
    names=('SystemRoot','WINDIR','SystemDrive','ComSpec','PATH','PATHEXT','TEMP','TMP',
           'ProgramFiles','ProgramFiles(x86)','ProgramW6432','CommonProgramFiles',
           'CommonProgramFiles(x86)','CommonProgramW6432','ProgramData','ALLUSERSPROFILE',
           'USERPROFILE','LOCALAPPDATA','APPDATA','OS','NUMBER_OF_PROCESSORS',
           'PROCESSOR_ARCHITECTURE','PROCESSOR_IDENTIFIER','PROCESSOR_LEVEL','PROCESSOR_REVISION')
    return {name:value for name in names if (value:=os.environ.get(name)) is not None}


def _serializer_capture(command, *, label, require_zero=False, **options):
    assert label in ('owned-native-vs-discovery','owned-native-serializer-run',
                     'owned-native-portable-compile','owned-native-portable-run')
    try:result=subprocess.run(command,**options)
    except subprocess.TimeoutExpired as primary:
        raise subprocess.TimeoutExpired(label,primary.timeout) from None
    if require_zero:assert result.returncode==0, label+' failed'
    return result


def _serializer_path(path, root=None, *, exists=True):
    """Keep the standalone compile's quoted CMD inputs and output namespace finite."""
    path=Path(path)
    assert path.is_absolute() and '..' not in path.parts, 'Serializer path must be absolute and owned'
    assert not any(c in str(path) for c in '%!&|<>^\r\n"'), 'Unsafe CMD serializer path'
    for item in (path,*path.parents):
        if item.exists() or item.is_symlink():
            assert not item.is_symlink() and not (getattr(item.stat(),'st_file_attributes',0)&0x400), 'Serializer path is linked'
    resolved=path.resolve(strict=exists)
    if root is not None:
        assert resolved.is_relative_to(Path(root).resolve(strict=True)), 'Serializer path escapes owned temporary root'
    if not exists:assert not path.exists(), 'Serializer output must be fresh'
    return resolved


def _serializer_pe(path, machine):
    path=_serializer_path(path)
    assert path.is_file() and 152<=path.stat().st_size<=128*1024*1024, 'Invalid serializer PE file size'
    data=path.read_bytes()
    assert data[:2]==b'MZ', 'Serializer tool/output lacks DOS signature'
    offset=struct.unpack_from('<I',data,0x3c)[0]
    assert 64<=offset<=len(data)-26 and data[offset:offset+4]==b'PE\0\0', 'Invalid serializer PE header'
    actual=struct.unpack_from('<H',data,offset+4)[0]
    assert actual==machine, 'Serializer tool/output PE machine is not native'
    characteristics=struct.unpack_from('<H',data,offset+22)[0]
    assert characteristics&2 and not characteristics&0x2000, 'Serializer PE must be executable, not DLL'
    assert struct.unpack_from('<H',data,offset+24)[0]==0x20b, 'Serializer PE must be PE32+'
    return {'path':str(path),'machine':actual,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def _serializer_arch(native_machine, process_machine, controller_machine):
    assert native_machine in (0x8664,0xaa64) and process_machine==0 and controller_machine==native_machine, 'Serializer controller must be native x64 or ARM64'
    return {0x8664:'x64',0xaa64:'arm64'}[native_machine]


def _serializer_tools(instance, machine):
    assert re.fullmatch(r'(17|18)\.\d+(?:\.\d+){1,2}',instance['installationVersion']), 'VS17 or VS18 required for native serializer'
    vs=_serializer_path(instance['installationPath'])
    version_file=_serializer_path(vs/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt')
    version=version_file.read_text(encoding='utf-8-sig').strip()
    assert re.fullmatch(r'14\.\d+\.\d+(?:\.\d+)?',version), 'Invalid native MSVC version'
    arch={0x8664:'x64',0xaa64:'arm64'}[machine]
    binary=vs/'VC/Tools/MSVC'/version/'bin'/('Host'+arch)/arch
    dev=_serializer_path(vs/'Common7/Tools/VsDevCmd.bat')
    assert dev.is_file(), 'VsDevCmd must be an installed file'
    return {'machine':machine,'arch':arch,'installationPath':str(vs),'compilerVersion':version,
            'devcmd':str(dev),'cl':_serializer_pe(binary/'cl.exe',machine),'link':_serializer_pe(binary/'link.exe',machine)}


def _serializer_windows_plan():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.argtypes=[];kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.IsWow64Process2.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint16),ctypes.POINTER(ctypes.c_uint16)]
    kernel.IsWow64Process2.restype=ctypes.c_int
    kernel.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_wchar),ctypes.c_uint32]
    kernel.GetModuleFileNameW.restype=ctypes.c_uint32
    process,native=ctypes.c_uint16(),ctypes.c_uint16()
    if not kernel.IsWow64Process2(kernel.GetCurrentProcess(),ctypes.byref(process),ctypes.byref(native)):
        raise ctypes.WinError(ctypes.get_last_error())
    image=ctypes.create_unicode_buffer(32768);length=kernel.GetModuleFileNameW(None,image,len(image))
    assert 0<length<len(image), 'Native controller image query failed or truncated'
    controller=_serializer_pe(image.value,native.value)
    arch=_serializer_arch(native.value,process.value,controller['machine'])
    installer=_serializer_path(Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe')
    result=_serializer_capture([str(installer),'-latest','-products','*','-version','[17.0,19.0)','-format','json','-utf8'],label='owned-native-vs-discovery',
                          env=_serializer_environment(),capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=15)
    assert result.returncode==0, 'Native serializer VS discovery failed'
    instances=json.loads(result.stdout)
    assert isinstance(instances,list) and len(instances)==1, 'One installed VS17/18 native compiler is required'
    plan=_serializer_tools(instances[0],native.value)
    assert plan['arch']==arch
    plan['controller']={'processMachine':process.value,'nativeMachine':native.value,'image':controller}
    plan['commandProcessor']=_serializer_pe(Path(os.environ['SystemRoot'])/'System32/cmd.exe',native.value)
    return plan


def _serializer_timeout_observation(root, phase, exe, obj):
    value=dict(phaseCode=0,phaseReadStatus=0,objectState=0,executableState=0)
    try:
        checked=_serializer_path(phase,root)
        assert checked.is_file()
        with checked.open('rb') as stream:raw=stream.read(17)
        rows=raw.splitlines()
        assert len(raw)<=16 and raw.endswith(b'\n') and 1<=len(rows)<=4
        assert rows==[str(n).encode('ascii') for n in range(1,len(rows)+1)]
        value.update(phaseCode=len(rows),phaseReadStatus=1)
    except FileNotFoundError:pass
    except BaseException:value['phaseReadStatus']=2
    for key,path in (('objectState',obj),('executableState',exe)):
        try:value[key]=2 if _serializer_path(path,root).is_file() else 0
        except FileNotFoundError:value[key]=1
        except BaseException:pass
    return value


def _serializer_process_state(process):
    value=dict(pid=process.pid,pollKnown=0,exited=0,exitCode=0,
               waitResult=0xffffffff,handleMatchesPid=0)
    try:
        code=process.poll()
        value.update(pollKnown=1,exited=int(code is not None),exitCode=code if code is not None else 0)
        if os.name=='nt':
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            wait=kernel.WaitForSingleObject;wait.argtypes=[ctypes.c_void_p,ctypes.c_uint32];wait.restype=ctypes.c_uint32
            pid=kernel.GetProcessId;pid.argtypes=[ctypes.c_void_p];pid.restype=ctypes.c_uint32
            handle=int(process._handle)
            value['handleMatchesPid']=int(pid(handle)==process.pid)
            value['waitResult']=int(wait(handle,0))
    except BaseException:pass
    return value


def _serializer_bounded_cleanup(process, deadline, *, kill):
    value=dict(pending=0,killAttempted=0,directHandleClosed=0,
               stdoutReaderAlive=0,stderrReaderAlive=0,stdoutClosed=0,stderrClosed=0)
    if kill:
        try:
            owned=_serializer_process_state(process)
            if owned['handleMatchesPid']==1 and owned['waitResult']==258 and owned['pollKnown']==1 and not owned['exited'] and time.monotonic()<deadline:
                value['killAttempted']=1;process.kill()
            elif owned['handleMatchesPid']!=1 or owned['waitResult']!=0:value['pending']=1
        except BaseException:value['pending']=1
    try:
        remaining=deadline-time.monotonic()
        if process.returncode is None and remaining>0:process.wait(timeout=remaining)
    except BaseException:value['pending']=1
    after=_serializer_process_state(process)
    value['afterCleanup']=after
    for name in ('stdout','stderr'):
        thread=getattr(process,name+'_thread',None)
        stream=getattr(process,name,None)
        try:
            remaining=deadline-time.monotonic()
            if thread is not None and thread.is_alive() and remaining>0:thread.join(remaining)
            alive=thread is not None and thread.is_alive()
            value[name+'ReaderAlive']=int(alive)
            if not alive and stream is not None:stream.close();value[name+'Closed']=1
            elif alive:value['pending']=1
        except BaseException:value['pending']=1
    if after['handleMatchesPid']==1 and after['waitResult']==0:
        try:
            code=process.poll()
            after.update(pollKnown=1,exited=int(code is not None),exitCode=code if code is not None else 0)
            assert type(code) is int and code==process.returncode, 'Direct child exit code remains unobserved'
            process._handle.Close();value['directHandleClosed']=1
        except BaseException:value['pending']=1
    else:value['pending']=1
    return value


def _serializer_compile_process(command_line, *, cwd, env, timeout, observe_phase):
    assert timeout==60
    deadline=time.monotonic()+timeout
    # One second is reserved from, never added to, the original wait budget.
    process=subprocess.Popen(command_line,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             text=True,encoding='utf-8',errors='strict')
    try:
        remaining=deadline-time.monotonic()-1.
        if remaining<=0:raise subprocess.TimeoutExpired(command_line,timeout)
        stdout,stderr=process.communicate(timeout=remaining)
    except subprocess.TimeoutExpired as primary:
        state=dict(cleanupReserveMilliseconds=1000,beforeCleanup=_serializer_process_state(process))
        try:state['phase']=observe_phase()
        except BaseException:state['phase']=dict(phaseCode=0,phaseReadStatus=2,objectState=0,executableState=0)
        try:state['cleanup']=_serializer_bounded_cleanup(process,deadline,kill=True)
        except BaseException:state['cleanup']=dict(pending=1,cleanupObservationFailed=1)
        try:primary._opengeul_serializer_timeout=state
        except BaseException:pass
        raise
    except BaseException:
        try:_serializer_bounded_cleanup(process,deadline,kill=True)
        except BaseException:pass
        raise
    returncode=process.returncode
    observation_failed=0
    try:
        pending=_serializer_bounded_cleanup(process,deadline,kill=False)['pending']
        assert type(pending) is int and pending in (0,1)
    except BaseException:pending=1;observation_failed=1
    completion=dict(completedWithinBudget=int(time.monotonic()<deadline),
                    cleanupPending=pending,cleanupObservationFailed=observation_failed)
    result=subprocess.CompletedProcess(command_line,returncode,stdout,stderr)
    result._opengeul_serializer_completion=completion
    if returncode==0:
        assert completion['completedWithinBudget']==1, 'Native serializer exceeded its original wait deadline'
        assert completion['cleanupPending']==0, 'Native serializer process resources remain unproved'
    return result


def _compile_windows_serializer(root, source, plan):
    root=_serializer_path(root);source=_serializer_path(source,root)
    exe=_serializer_path(root/'serializer.exe',root,exists=False)
    obj=_serializer_path(root/'serializer.obj',root,exists=False)
    batch=_serializer_path(root/'compile-serializer.cmd',root,exists=False)
    phase=_serializer_path(root/'serializer-compile.phase',root,exists=False)
    cl=_serializer_pe(plan['cl']['path'],plan['machine']);link=_serializer_pe(plan['link']['path'],plan['machine'])
    assert cl==plan['cl'] and link==plan['link'], 'Native tools changed before compile'
    dev=_serializer_path(plan['devcmd']);command=plan['commandProcessor']
    assert _serializer_pe(command['path'],plan['machine'])==command, 'Native command processor changed'
    def mark(code):return ['set "OPENGEUL_SERIALIZER_RC=%errorlevel%"',
                           'call :serializer_phase '+str(code)+' %OPENGEUL_SERIALIZER_RC%']
    lines=['@echo off','chcp 65001 >nul','if errorlevel 1 exit /b %errorlevel%']+mark(1)+[
           'call "'+str(dev)+'" -no_logo -arch='+plan['arch']+' -host_arch='+plan['arch']]+mark(2)+[
           'if errorlevel 1 exit /b %errorlevel%','chcp 65001 >nul','if errorlevel 1 exit /b %errorlevel%',
           'set "CL="','set "_CL_="','set "PATH='+str(Path(link['path']).parent)+';%PATH%"']+mark(3)+[
           '"'+cl['path']+'" /nologo /std:c++17 /EHsc /utf-8 /MT /W4 /WX /D_SILENCE_CXX17_CODECVT_HEADER_DEPRECATION_WARNING '+
           '/Fe:"'+str(exe)+'" /Fo:"'+str(obj)+'" "'+str(source)+'" /link /MACHINE:'+plan['arch'].upper()+' /INCREMENTAL:NO']+mark(4)+[
           'exit /b %errorlevel%',':serializer_phase','>>"'+str(phase)+'" echo %1','exit /b %2']
    batch.write_text('\r\n'.join(lines)+'\r\n',encoding='utf-8',newline='')
    environment=_serializer_environment()
    # Both the command processor and batch are absolute, checked paths; the
    # double outer quotes are CMD /s /c syntax, not shell=True interpretation.
    command_line='"'+command['path']+'" /d /v:off /s /c ""'+str(batch)+'""'
    source_identity={'path':str(source),'size':source.stat().st_size,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    try:
        result=_serializer_compile_process(command_line,cwd=root,env=environment,timeout=60,
            observe_phase=lambda:_serializer_timeout_observation(root,phase,exe,obj))
    except subprocess.TimeoutExpired as primary:
        state={}
        try:
            state=vars(primary).get('_opengeul_serializer_timeout',{})
            observation=state.get('phase') or _serializer_timeout_observation(root,phase,exe,obj)
            print('native-serializer-timeout '+json.dumps(dict(schemaVersion=1,timeoutSeconds=60,
                machine=plan['machine'],sourceSha256=source_identity['sha256'],compilerSha256=cl['sha256'],
                linkerSha256=link['sha256'],commandProcessorSha256=command['sha256'],
                testModuleSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                **observation,processObservation={key:state[key] for key in ('cleanupReserveMilliseconds','beforeCleanup','cleanup') if key in state}),
                separators=(',',':')),flush=True)
        except BaseException:pass
        redacted=subprocess.TimeoutExpired('owned-native-serializer',60)
        redacted._opengeul_serializer_timeout=state
        raise redacted from None
    compile_receipt={'exitCode':result.returncode,'stdoutBytes':len(result.stdout.encode('utf-8')),
                     'stderrBytes':len(result.stderr.encode('utf-8'))}
    if hasattr(result,'_opengeul_serializer_completion'):
        compile_receipt['processCompletion']=result._opengeul_serializer_completion
    print('native-serializer-compile '+json.dumps({'toolchain':plan,'source':source_identity,
          'testModuleSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'compile':compile_receipt},ensure_ascii=True),flush=True)
    assert result.returncode==0, 'Native serializer compile failed exit '+str(result.returncode)
    output=_serializer_pe(exe,plan['machine'])
    assert _serializer_pe(cl['path'],plan['machine'])==cl and _serializer_pe(link['path'],plan['machine'])==link, 'Native tools changed during compile'
    return exe,{'toolchain':plan,'source':source_identity,
                'output':output,'compile':compile_receipt,'processWitness':'PE/selected-path evidence; no retained compiler/output process HANDLE witness'}


def _run_windows_serializer(executable, receipt):
    result=_serializer_capture([str(executable)],label='owned-native-serializer-run',cwd=executable.parent,env=_serializer_environment(),capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=15)
    # Retain exit/count metadata before the original execution assertion.
    receipt['run']={'exitCode':result.returncode,'stdoutBytes':len(result.stdout.encode('utf-8')),
                    'stderrBytes':len(result.stderr.encode('utf-8'))}
    print('native-serializer-run '+json.dumps({'output':receipt['output'],'run':receipt['run']},ensure_ascii=True),flush=True)
    after=_serializer_pe(executable,receipt['output']['machine'])
    assert after==receipt['output'], 'Serializer output changed during execution'
    receipt['outputAfterRun']=after
    assert result.returncode==0, 'Native serializer run failed exit '+str(result.returncode)
    return result


class OwnedInheritedPipeFixture:
    """Own the negative pipe holder until its separately measured cleanup."""
    def __init__(self, root):
        self.root=Path(root)
        self.listener=self.connection=None
        self.handle=self.pidfd=None
        self.original_subreaper=None
        self.observation=None

    def __enter__(self):
        try:
            if sys.platform=='linux':
                self.libc=ctypes.CDLL(None,use_errno=True)
                self.libc.prctl.argtypes=[ctypes.c_int]+[ctypes.c_ulong]*4
                self.libc.prctl.restype=ctypes.c_int
                previous=ctypes.c_int()
                self.prctl(37,ctypes.addressof(previous))
                self.original_subreaper=previous.value
                self.prctl(36,1)
            elif os.name!='nt':
                raise RuntimeError('Owned pipe fixture supports Windows and Linux controllers')
            self.listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            self.listener.bind(('127.0.0.1',0));self.listener.listen(1)
            self.nonce=secrets.token_hex(24)
            self.pidfile=self.root/'owned-pipe-holder.pid'
            parent=self.root/'owned-pipe-holder.py'
            parent.write_text(
                "import json,os,pathlib,socket,subprocess,sys\n"
                "if sys.argv[1]=='holder':\n"
                "    with socket.create_connection(('127.0.0.1',int(sys.argv[2])),timeout=10) as control:\n"
                "        control.sendall((json.dumps({'pid':os.getpid(),'nonce':sys.argv[3]})+'\\n').encode())\n"
                "        if control.recv(1)!=b'q':sys.exit(7)\n"
                "else:\n"
                "    child=subprocess.Popen([sys.executable,__file__,'holder',sys.argv[1],sys.argv[2]],stdout=sys.stdout,stderr=sys.stderr)\n"
                "    pathlib.Path(sys.argv[3]).write_text(str(child.pid))\n"
                "    print('direct parent exited',flush=True)\n",encoding='utf-8')
            self.arguments=[str(parent),str(self.listener.getsockname()[1]),self.nonce,str(self.pidfile)]
            return self
        except BaseException:
            self.close_resources()
            raise

    def prctl(self, option, value):
        if self.libc.prctl(option,value,0,0,0)!=0:
            raise OSError(ctypes.get_errno(),'Fixture child-subreaper operation failed')

    def remaining(self):
        value=self.deadline-time.monotonic()
        if value<=0:raise TimeoutError('Owned fixture cleanup exceeded its separate five-second budget')
        return value

    def bind_windows(self, pid):
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        handle=ctypes.c_void_p;dword=ctypes.c_uint32
        class FileTime(ctypes.Structure):
            _fields_=[('low',dword),('high',dword)]
        self.kernel.OpenProcess.argtypes=[dword,ctypes.c_int,dword]
        self.kernel.OpenProcess.restype=handle
        self.kernel.GetProcessId.argtypes=[handle];self.kernel.GetProcessId.restype=dword
        self.kernel.GetProcessTimes.argtypes=[handle]+[ctypes.POINTER(FileTime)]*4
        self.kernel.GetProcessTimes.restype=ctypes.c_int
        self.kernel.WaitForSingleObject.argtypes=[handle,dword];self.kernel.WaitForSingleObject.restype=dword
        self.kernel.GetExitCodeProcess.argtypes=[handle,ctypes.POINTER(dword)]
        self.kernel.GetExitCodeProcess.restype=ctypes.c_int
        self.kernel.CloseHandle.argtypes=[handle];self.kernel.CloseHandle.restype=ctypes.c_int
        self.handle=self.kernel.OpenProcess(0x00100000|0x1000,False,pid)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        if self.kernel.GetProcessId(self.handle)!=pid:raise AssertionError('Fixture process handle PID differs')
        creation,exit_time,kernel,user=(FileTime() for _ in range(4))
        if not self.kernel.GetProcessTimes(self.handle,*map(ctypes.byref,(creation,exit_time,kernel,user))):
            raise ctypes.WinError(ctypes.get_last_error())
        if self.kernel.WaitForSingleObject(self.handle,0)!=258:
            raise AssertionError('Authenticated fixture exited before its controlled release')
        return {'clock':'Windows FILETIME','rawTicks':(creation.high<<32)|creation.low}

    def complete(self):
        self.deadline=time.monotonic()+5
        self.listener.settimeout(self.remaining())
        self.connection,_=self.listener.accept()
        data=b''
        while b'\n' not in data:
            self.connection.settimeout(self.remaining())
            part=self.connection.recv(1024)
            if not part or len(data)+len(part)>1024:raise AssertionError('Invalid fixture ownership handshake')
            data+=part
        identity=json.loads(data.decode())
        if (set(identity)!={'pid','nonce'} or type(identity['pid']) is not int or identity['pid']<=0
                or not isinstance(identity['nonce'],str) or not secrets.compare_digest(identity['nonce'],self.nonce)
                or int(self.pidfile.read_text())!=identity['pid']):
            raise AssertionError('Fixture nonce/PID ownership differs')
        pid=identity['pid']
        if os.name=='nt':
            creation=self.bind_windows(pid)
        else:
            self.pidfd=os.pidfd_open(pid)
            stat=(Path('/proc')/str(pid)/'stat').read_text()
            fields=stat[stat.rindex(')')+2:].split()
            if int(fields[1])!=os.getpid() or fields[0]=='Z':
                raise AssertionError('Fixture is not a live child of its temporary subreaper')
            creation={'clock':'Linux proc starttime','rawTicks':int(fields[19])}
        self.observation={'pid':pid,'creationIdentity':creation,'authenticated':True,
                          'productReceiptUnmodified':True,'forcedTermination':False}
        self.connection.settimeout(self.remaining());self.connection.sendall(b'q')
        if os.name=='nt':
            if self.kernel.WaitForSingleObject(self.handle,max(1,int(self.remaining()*1000)))!=0:
                raise TimeoutError('Owned Windows fixture process death unproved')
            code=ctypes.c_uint32()
            if not self.kernel.GetExitCodeProcess(self.handle,ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            exit_code=code.value
        else:
            ready,_,_=select.select([self.pidfd],[],[],self.remaining())
            if not ready:raise TimeoutError('Owned Linux fixture process death unproved')
            waited,status=os.waitpid(pid,0)
            if waited!=pid:raise AssertionError('Reaped an unrelated fixture PID')
            exit_code=os.waitstatus_to_exitcode(status)
        if exit_code!=0:raise AssertionError('Owned fixture did not exit normally with zero: '+str(exit_code))
        self.observation.update(exitCode=exit_code,normalDeathObserved=True)

    def close_resources(self):
        errors=[]
        for name in ('connection','listener'):
            resource=getattr(self,name)
            if resource is not None:
                try:resource.close()
                except BaseException as error:errors.append(error)
                setattr(self,name,None)
        if self.handle is not None:
            try:
                if not self.kernel.CloseHandle(self.handle):raise ctypes.WinError(ctypes.get_last_error())
            except BaseException as error:errors.append(error)
            self.handle=None
        if self.pidfd is not None:
            try:os.close(self.pidfd)
            except BaseException as error:errors.append(error)
            self.pidfd=None
        if self.original_subreaper is not None:
            try:
                self.prctl(36,self.original_subreaper)
                restored=ctypes.c_int();self.prctl(37,ctypes.addressof(restored))
                if restored.value!=self.original_subreaper:raise AssertionError('Fixture subreaper flag was not restored')
            except BaseException as error:errors.append(error)
            self.original_subreaper=None
        if errors:raise BaseExceptionGroup('Owned fixture resource cleanup failed',errors)

    def __exit__(self, exc_type, exc, traceback):
        errors=[]
        try:self.complete()
        except BaseException as error:errors.append(error)
        finally:
            try:self.close_resources()
            except BaseException as error:errors.append(error)
        if errors:raise BaseExceptionGroup('Owned pipe fixture completion failed',errors)
        self.observation.update(resourcesClosed=True,subreaperRestored=True,testBodyFailed=exc_type is not None)
        (self.root/'owned-pipe-fixture-cleanup.json').write_text(json.dumps(self.observation),encoding='utf-8')
        print('owned-pipe-fixture '+json.dumps(self.observation,sort_keys=True))
        return False


class NativeCrtProbeTests(unittest.TestCase):
    def ps(self,body):
        self.assertTrue(SOURCE.is_file(), 'Focused native CRT diagnostic script is required')
        with tempfile.TemporaryDirectory() as folder:
            script=Path(folder)/'test.ps1'
            script.write_text("$ErrorActionPreference='Stop'\n. "+quote(SOURCE)+"\n"+body)
            result=subprocess.run([PWSH,'-NoProfile','-File',str(script)],capture_output=True,text=True,timeout=15)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            return result.stdout.strip()

    def test_eight_names_exclude_x64_only_runtime_and_do_not_change_product_family(self):
        names=json.loads(self.ps('ConvertTo-Json -InputObject @(Get-CrtProbeNames) -Compress'))
        self.assertEqual(8,len(names));self.assertNotIn('vcruntime140_1.dll',names)
        self.assertIn('vcruntime140_threads.dll',names)
        driver=(ROOT/'suite/scripts/build-native-engine.ps1').read_text()
        self.assertIn("'vcruntime140_1.dll'",driver)

    def test_actual_owned_command_receipts_cover_zero_nonzero_and_timeout(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,body,code,forced in [('zero',"Write-Output 'raw output'; exit 0",0,False),
                                          ('nonzero',"Write-Error 'raw failure' -ErrorAction Continue; exit 7",7,False),
                                          ('timeout','Start-Sleep -Seconds 20',None,True)]:
                child=root/(name+'.ps1');child.write_text(body)
                prefix=root/name
                budget=1 if forced else 5
                self.ps("try { Invoke-CrtProbeCommand -FilePath "+quote(PWSH)+" -Arguments @('-NoProfile','-File',"+quote(child)+") -WorkingDirectory "+quote(root)+" -Prefix "+quote(prefix)+" -TimeoutSeconds "+str(budget)+" | Out-Null } catch {}")
                receipt=json.loads(prefix.with_suffix('.command.json').read_text())
                self.assertEqual(code,receipt['exitCode']);self.assertEqual(forced,receipt['forcedTermination'])
                self.assertEqual(name=='zero',receipt['passed']);self.assertTrue(prefix.with_suffix('.stdout.log').exists())
                self.assertTrue(prefix.with_suffix('.stderr.log').exists())
                self.assertLess(receipt['elapsedSeconds'],8)

    def test_launch_failure_still_retains_failed_receipt_and_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);prefix=root/'launch'
            self.ps("try { Invoke-CrtProbeCommand -FilePath "+quote(root/'missing-executable')+
                    " -Arguments @() -WorkingDirectory "+quote(root)+" -Prefix "+quote(prefix)+
                    " -TimeoutSeconds 1 | Out-Null } catch {}")
            self.assertTrue(prefix.with_suffix('.command.json').is_file(), 'Launch failure must keep its receipt')
            receipt=json.loads(prefix.with_suffix('.command.json').read_text())
            self.assertFalse(receipt['passed']);self.assertIsNone(receipt['exitCode'])

    def test_exited_parent_with_inherited_pipe_cannot_extend_original_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);prefix=root/'pipe'
            with OwnedInheritedPipeFixture(root) as fixture:
                self.ps("try { Invoke-CrtProbeCommand -FilePath "+quote(sys.executable)+
                        " -Arguments @("+','.join(map(quote,fixture.arguments))+") -WorkingDirectory "+quote(root)+" -Prefix "+quote(prefix)+
                        " -TimeoutSeconds 1 | Out-Null } catch {}")
                receipt=json.loads(prefix.with_suffix('.command.json').read_text())
                self.assertFalse(receipt['passed'], 'A retained pipe cannot silently extend the deadline')
                self.assertEqual(0,receipt['exitCode'])
                self.assertFalse(receipt['pipeDrainComplete'])
                self.assertLess(receipt['elapsedSeconds'],3)
                self.assertFalse(receipt['forcedTermination'])
            self.assertEqual(0,fixture.observation['exitCode'])

    def test_runtime_proof_rejects_emulation_wrong_pid_foreign_module_and_missing_exception(self):
        with tempfile.TemporaryDirectory() as folder:
            program=Path(folder);exe=program/'probe.exe'
            proof=dict(schemaVersion=1,pid=123,image=str(exe),processMachine=0,nativeMachine=43620,
                       compiledArm64=True,compiledArm64Ec=False,exceptionObserved=True,vectorCount=4096,
                       loadedModules=[dict(name=n,path=str(program/n),machine=43620)
                                      for n in ('msvcp140.dll','vcruntime140.dll')])
            for damage in ('valid','emulation','pid','exception','foreign','outside','x64-one'):
                changed=json.loads(json.dumps(proof))
                if damage=='emulation':changed['processMachine']=34404
                elif damage=='pid':changed['pid']=999
                elif damage=='exception':changed['exceptionObserved']=False
                elif damage=='foreign':changed['loadedModules'][0]['machine']=34404
                elif damage=='outside':changed['loadedModules'][0]['path']=str(program.parent/'foreign.dll')
                elif damage=='x64-one':changed['loadedModules'].append(dict(name='vcruntime140_1.dll',path=str(program/'vcruntime140_1.dll'),machine=34404))
                path=program/'proof.json';path.write_text(json.dumps(changed))
                body="$proof=Get-Content -Raw "+quote(path)+"|ConvertFrom-Json; $rejected=$false;try { Assert-CrtProbeRuntime $proof 123 "+quote(exe)+" "+quote(program)+" } catch {$rejected=$true}; if($rejected -ne "+('$false' if damage=='valid' else '$true')+"){throw 'Wrong native proof decision'}"
                self.ps(body)

    def test_workflow_retains_raw_evidence_after_failure_and_no_full_engine_work(self):
        path=ROOT/'.github/workflows/office-native-crt-probe.yml'
        self.assertTrue(path.is_file(), 'Focused diagnostic workflow is required')
        text=path.read_text()
        self.assertIn('windows-11-arm',text);self.assertIn('if: always()',text)
        self.assertIn('include-hidden-files: true',text)
        self.assertIn('probe-native-crt.ps1',text)
        self.assertNotIn('build-native-engine.ps1 -Phase',text)

    @unittest.skipUnless(os.name=='nt' or shutil.which('c++'), 'Portable C++ serializer check needs a local compiler')
    def test_generated_cpp_serializes_actual_wstring_windows_paths_as_json(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve(strict=True);source=root/'probe.cpp'
            self.ps('Write-CrtProbeSource '+quote(source))
            generated=source.read_text(encoding='utf-8-sig')
            serializer=re.search(r'static std::string json\(.*?\n}',generated,re.S).group()
            # Only the Windows UTF-8 conversion API is replaced for this local
            # serializer execution. The generated C++ escaping body is exact.
            shim=r'''
#include <string>
#include <iostream>
#include <codecvt>
#include <locale>
#include <algorithm>
const unsigned CP_UTF8=65001;
int WideCharToMultiByte(unsigned,int,const wchar_t* w,int n,char* out,int,void*,void*) {
    std::wstring_convert<std::codecvt_utf8<wchar_t>> converter;
    auto bytes=converter.to_bytes(w,w+n);
    if(out)std::copy(bytes.begin(),bytes.end(),out);
    return (int)bytes.size();
}
'''
            path='C:\\Program Files\\Microsoft Visual Studio\\한글\\vcruntime140.dll'
            literal=json.dumps(path,ensure_ascii=False)
            local=root/'serializer.cpp';local.write_text(shim+serializer+'\nint main(){std::cout<<json(L'+literal+');}\n',encoding='utf-8')
            if os.name=='nt':
                executable,receipt=_compile_windows_serializer(root,local,_serializer_windows_plan())
                result=_run_windows_serializer(executable,receipt)
                receipt.update(generatedSourceSha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                               escapingBodySha256=hashlib.sha256(serializer.encode('utf-8')).hexdigest(),
                               shimSha256=hashlib.sha256(shim.encode('utf-8')).hexdigest(),
                               testModuleSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
                print('native-serializer-fixture '+json.dumps(receipt,ensure_ascii=True),flush=True)
                self.assertEqual(0,result.returncode,'Native serializer run failed')
            else:
                executable=root/'serializer'
                result=_serializer_capture([shutil.which('c++'),'-std=c++17','-Wall','-Werror=multichar',str(local),'-o',str(executable)],label='owned-native-portable-compile',require_zero=True,env=_serializer_environment(),capture_output=True,text=True)
                result=_serializer_capture([str(executable)],label='owned-native-portable-run',require_zero=True,env=_serializer_environment(),capture_output=True,text=True)
            self.assertEqual(path,json.loads(result.stdout))


class NativeSerializerFixtureTests(unittest.TestCase):
    """Portable controls for the test-only native compiler boundary."""
    def setUp(self):
        environment=mock.patch.dict(os.environ,{'SERIALIZER_TEST_ONLY':'1'},clear=True)
        environment.start();self.addCleanup(environment.stop)

    def helper(self, name):
        self.assertTrue(callable(globals().get(name)), 'Missing native serializer boundary: '+name)
        return globals()[name]

    def compile_inputs(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name).resolve(strict=True);instance,_=self.installation(root,0x8664)
        plan=_serializer_tools(instance,0x8664)
        plan['commandProcessor']=_serializer_pe(self.pe(root/'cmd.exe',0x8664),0x8664)
        source=root/'serializer.cpp';source.write_text('int main(){}',encoding='utf-8')
        return root,source,plan

    def test_compile_timeout_redacts_outer_exception_and_prints_only_fixed_phase_and_hashes(self):
        class Private:
            def __str__(self):raise AssertionError('No private text conversion')
            def __repr__(self):raise AssertionError('No private text representation')
        for phase in (1,2,3,4):
            with self.subTest(phase=phase):
                root,source,plan=self.compile_inputs()
                plan['privateUnrelatedValue']=Private()
                original=subprocess.TimeoutExpired(Private(),60,output=Private(),stderr=Private())
                def timeout(*args,**options):
                    (root/'serializer-compile.phase').write_bytes(b''.join(str(n).encode()+b'\r\n' for n in range(1,phase+1)))
                    (root/'serializer.obj').write_bytes(b'partial')
                    if phase==4:self.pe(root/'serializer.exe',0x8664)
                    raise original
                with mock.patch.dict(os.environ,{'SERIALIZER_TEST_ONLY':'1'},clear=True), \
                     mock.patch.object(sys.modules[__name__],'_serializer_compile_process',side_effect=timeout) as run,mock.patch('builtins.print') as logged:
                    with self.assertRaises(subprocess.TimeoutExpired) as caught:_compile_windows_serializer(root,source,plan)
                self.assertIsNot(caught.exception,original);self.assertEqual(run.call_count,1)
                self.assertEqual(caught.exception.cmd,'owned-native-serializer')
                self.assertEqual(caught.exception.timeout,60)
                self.assertIsNone(caught.exception.stdout);self.assertIsNone(caught.exception.stderr)
                rendered=''.join(traceback.format_exception(caught.exception))
                self.assertNotIn(str(root),rendered)
                self.assertNotIn('Private',repr(caught.exception))
                self.assertEqual(run.call_args.kwargs['timeout'],60)
                self.assertEqual(set(run.call_args.kwargs),{'cwd','env','timeout','observe_phase'})
                self.assertEqual(logged.call_count,1,'The bounded timeout diagnostic is missing')
                payload=logged.call_args.args[0];self.assertTrue(payload.startswith('native-serializer-timeout '))
                value=json.loads(payload.split(' ',1)[1])
                self.assertEqual(set(value),{'schemaVersion','timeoutSeconds','machine','phaseCode','phaseReadStatus',
                    'objectState','executableState','sourceSha256','compilerSha256','linkerSha256','commandProcessorSha256','testModuleSha256','processObservation'})
                self.assertEqual((value['phaseCode'],value['phaseReadStatus']),(phase,1))
                self.assertEqual(value['objectState'],2)
                self.assertEqual(value['executableState'],2 if phase==4 else 1)
                self.assertEqual(value['sourceSha256'],hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertEqual(value['compilerSha256'],plan['cl']['sha256'])
                self.assertEqual(value['linkerSha256'],plan['link']['sha256'])
                self.assertNotIn(str(root),payload)
                self.assertEqual(value['timeoutSeconds'],60)

    def test_timeout_phase_read_is_bounded_ordered_and_rejects_links(self):
        observe=self.helper('_serializer_timeout_observation')
        root,_,_=self.compile_inputs();phase=root/'serializer-compile.phase'
        exe,obj=root/'serializer.exe',root/'serializer.obj'
        self.assertEqual(observe(root,phase,exe,obj),dict(phaseCode=0,phaseReadStatus=0,objectState=1,executableState=1))
        for raw in (b'',b'1',b'2\n',b'1\n3\n',b'1\n2\n1\n',b'1\n2\n3\n4\n5\n',b'1\n'+b' '*64):
            with self.subTest(length=len(raw)):
                phase.write_bytes(raw);value=observe(root,phase,exe,obj)
                self.assertEqual((value['phaseCode'],value['phaseReadStatus']),(0,2))
        phase.write_bytes(b'1\n2\n3\n4\n')
        self.assertEqual(observe(root,phase,exe,obj)['phaseCode'],4)
        if os.name!='nt':
            other=root/'other';other.write_bytes(b'1\n');phase.unlink();phase.symlink_to(other)
            value=observe(root,phase,exe,obj)
            self.assertEqual((value['phaseCode'],value['phaseReadStatus']),(0,2))

    def test_optional_timeout_observation_or_output_errors_keep_the_same_timeout(self):
        self.helper('_serializer_timeout_observation')
        for observation_error,output_error in ((OSError('private'),None),(KeyboardInterrupt(),None),(None,OSError('private'))):
            with self.subTest(observationError=type(observation_error).__name__,outputError=type(output_error).__name__):
                root,source,plan=self.compile_inputs();original=subprocess.TimeoutExpired('private-command',60)
                with mock.patch.dict(os.environ,{'SERIALIZER_TEST_ONLY':'1'},clear=True), \
                     mock.patch.object(sys.modules[__name__],'_serializer_compile_process',side_effect=original) as run, \
                     mock.patch.object(sys.modules[__name__],'_serializer_timeout_observation',side_effect=observation_error) as observed, \
                     mock.patch('builtins.print',side_effect=output_error):
                    if observation_error is None:observed.return_value=dict(phaseCode=0,phaseReadStatus=0,objectState=1,executableState=1)
                    with self.assertRaises(subprocess.TimeoutExpired) as caught:_compile_windows_serializer(root,source,plan)
                self.assertIsNot(caught.exception,original);self.assertEqual(run.call_count,1)
                self.assertEqual(caught.exception.cmd,'owned-native-serializer')

    def test_phase_markers_save_and_restore_external_command_errorlevels(self):
        root,source,plan=self.compile_inputs()
        with mock.patch.dict(os.environ,{'SERIALIZER_TEST_ONLY':'1'},clear=True), \
             mock.patch.object(sys.modules[__name__],'_serializer_compile_process',return_value=subprocess.CompletedProcess([],2,'','')),mock.patch('builtins.print'):
            with self.assertRaises(AssertionError):_compile_windows_serializer(root,source,plan)
        lines=(root/'compile-serializer.cmd').read_text(encoding='utf-8').splitlines()
        capture='set "OPENGEUL_SERIALIZER_RC=%errorlevel%"'
        for code,anchor in ((2,'call "'+plan['devcmd']+'"'),(4,'"'+plan['cl']['path']+'"')):
            index=next(i for i,line in enumerate(lines) if line.startswith(anchor))
            self.assertEqual(lines[index+1:index+3],[capture,'call :serializer_phase '+str(code)+' %OPENGEUL_SERIALIZER_RC%'])
        self.assertIn('call :serializer_phase 1 %OPENGEUL_SERIALIZER_RC%',lines)
        self.assertIn('call :serializer_phase 3 %OPENGEUL_SERIALIZER_RC%',lines)
        self.assertEqual(lines[-3:],[':serializer_phase','>>"'+str(root/'serializer-compile.phase')+'" echo %1','exit /b %2'])
        self.assertEqual(lines[lines.index(':serializer_phase')-1],'exit /b %errorlevel%')

    def test_existing_phase_file_is_not_overwritten_or_used_for_admission(self):
        root,source,plan=self.compile_inputs();phase=root/'serializer-compile.phase';phase.write_bytes(b'1\n2\n3\n4\n')
        with mock.patch.dict(os.environ,{'SERIALIZER_TEST_ONLY':'1'},clear=True), \
             mock.patch.object(sys.modules[__name__],'_serializer_compile_process',return_value=subprocess.CompletedProcess([],2,'','')) as run,mock.patch('builtins.print'):
            with self.assertRaises(AssertionError):_compile_windows_serializer(root,source,plan)
        self.assertEqual(run.call_count,0);self.assertEqual(phase.read_bytes(),b'1\n2\n3\n4\n')

    def bounded_compile(self, *, held_pipe=False, unproved_death=False, foreign_handle=False, expire_phase=False):
        run=self.helper('_serializer_compile_process')
        clock=type('Clock',(),{'now':0.,'__call__':lambda self:self.now})()
        calls=[];original=subprocess.TimeoutExpired('synthetic-command',59.)
        class Stream:
            closed=False
            def close(self):calls.append('stream-close');self.closed=True
        class Thread:
            alive=True
            def is_alive(self):return self.alive
            def join(self,timeout):
                calls.append(('join',timeout));self_test.assertGreater(timeout,0)
                self_test.assertLessEqual(timeout,60.-clock.now)
                if held_pipe or unproved_death:clock.now+=timeout
                else:self.alive=False
        class Handle:
            def Close(self):calls.append('handle-close')
        class Process:
            pid=77;returncode=None;_handle=Handle()
            stdout=Stream();stderr=Stream();stdout_thread=Thread();stderr_thread=Thread()
            def communicate(self,timeout):
                calls.append(('communicate',timeout));clock.now+=timeout
                if held_pipe:self.returncode=0
                raise original
            def poll(self):calls.append('poll');return self.returncode
            def kill(self):calls.append('kill')
            def wait(self,timeout):
                calls.append(('wait',timeout));self_test.assertLessEqual(timeout,60.-clock.now)
                if unproved_death:
                    clock.now+=timeout;raise subprocess.TimeoutExpired('synthetic-cleanup',timeout)
                self.returncode=0;return 0
        self_test=self;process=Process()
        def state(p):
            calls.append('native-observe')
            return dict(pid=77,pollKnown=1,exited=int(p.returncode is not None),exitCode=p.returncode or 0,
                waitResult=0 if p.returncode is not None else 258,handleMatchesPid=int(not foreign_handle))
        def phase():
            if expire_phase:clock.now=60.
            return dict(phaseCode=3,phaseReadStatus=1,objectState=1,executableState=1)
        with mock.patch.dict(os.environ,{'SERIALIZER_TEST_ONLY':'1'},clear=True), \
             mock.patch.object(subprocess,'Popen',return_value=process) as popen, \
             mock.patch.object(sys.modules[__name__],'_serializer_process_state',side_effect=state), \
             mock.patch.object(time,'monotonic',side_effect=clock):
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                run('synthetic-command',cwd=Path('/synthetic'),env={'SYNTHETIC':'1'},timeout=60,
                    observe_phase=phase)
        self.assertIs(caught.exception,original);self.assertEqual(popen.call_count,1)
        self.assertEqual([c for c in calls if isinstance(c,tuple) and c[0]=='communicate'],[('communicate',59.)])
        self.assertLessEqual(clock.now,60.)
        return process,original,calls

    def test_compile_timeout_observes_retained_child_before_bounded_owned_cleanup(self):
        process,error,calls=self.bounded_compile()
        state=vars(error)['_opengeul_serializer_timeout']
        self.assertLess(calls.index('native-observe'),calls.index('kill'))
        self.assertEqual(state['beforeCleanup']['waitResult'],258)
        self.assertEqual(state['cleanup']['pending'],0)
        self.assertIn('handle-close',calls)
        self.assertTrue(process.stdout.closed and process.stderr.closed)

    def test_inherited_pipe_holder_is_pending_without_second_communicate_or_blocking_close(self):
        process,error,calls=self.bounded_compile(held_pipe=True)
        state=vars(error)['_opengeul_serializer_timeout']
        self.assertEqual(state['beforeCleanup']['waitResult'],0)
        self.assertEqual(state['cleanup']['pending'],1)
        self.assertNotIn('kill',calls);self.assertNotIn('stream-close',calls)
        self.assertIn('handle-close',calls)
        self.assertFalse(process.stdout.closed or process.stderr.closed)

    def test_unproved_direct_child_death_keeps_handle_pending_and_never_guesses_descendants(self):
        process,error,calls=self.bounded_compile(unproved_death=True)
        state=vars(error)['_opengeul_serializer_timeout']
        self.assertEqual(state['cleanup']['pending'],1)
        self.assertNotIn('handle-close',calls);self.assertNotIn('stream-close',calls)
        self.assertEqual(calls.count('kill'),1)

    def test_foreign_or_expired_cleanup_cannot_start_a_kill(self):
        for options in (dict(foreign_handle=True,unproved_death=True),dict(expire_phase=True)):
            with self.subTest(mode=next(iter(options))):
                _,error,calls=self.bounded_compile(**options)
                self.assertNotIn('kill',calls);self.assertNotIn('handle-close',calls)
                self.assertEqual(vars(error)['_opengeul_serializer_timeout']['cleanup']['pending'],1)

    def test_late_creation_communicate_or_cleanup_never_returns_a_success(self):
        run=self.helper('_serializer_compile_process')
        for late in ('creation','communicate','cleanup'):
            with self.subTest(late=late):
                clock=NS(now=0.)
                def close():
                    if late=='cleanup':clock.now=60.
                process=NS(pid=77,returncode=0,_handle=NS(Close=lambda:None),
                    stdout=NS(close=close),stderr=NS(close=close),poll=lambda:0)
                def communicate(timeout):
                    if late=='communicate':clock.now=60.
                    return '',''
                def create(*args,**kwargs):
                    if late=='creation':clock.now=60.
                    return process
                process.communicate=communicate
                state=dict(pid=77,pollKnown=1,exited=1,exitCode=0,waitResult=0,handleMatchesPid=1)
                with mock.patch.dict(os.environ,{'SERIALIZER_TEST_ONLY':'1'},clear=True), \
                     mock.patch.object(subprocess,'Popen',side_effect=create), \
                     mock.patch.object(sys.modules[__name__],'_serializer_process_state',return_value=state), \
                     mock.patch.object(time,'monotonic',side_effect=lambda:clock.now):
                    with self.assertRaises((subprocess.TimeoutExpired,AssertionError)):
                        run('synthetic-command',cwd=Path('/synthetic'),env={},timeout=60,observe_phase=lambda:{})

    def test_nonzero_compile_preserves_exit_with_pending_failed_or_late_cleanup(self):
        for mode in ('pending','cleanup-error','late'):
            with self.subTest(mode=mode):
                root,source,plan=self.compile_inputs();clock=NS(now=0.)
                process=NS(returncode=2,communicate=mock.Mock(return_value=('synthetic stdout','synthetic stderr')))
                def cleanup(*args,**options):
                    if mode=='cleanup-error':raise OSError('synthetic cleanup failure')
                    if mode=='late':clock.now=60.
                    return dict(pending=int(mode=='pending'))
                with mock.patch.object(subprocess,'Popen',return_value=process) as popen, \
                     mock.patch.object(sys.modules[__name__],'_serializer_bounded_cleanup',side_effect=cleanup), \
                     mock.patch.object(time,'monotonic',side_effect=lambda:clock.now),mock.patch('builtins.print') as logged:
                    with self.assertRaises(AssertionError) as caught:_compile_windows_serializer(root,source,plan)
                self.assertEqual(str(caught.exception),'Native serializer compile failed exit 2')
                self.assertEqual(popen.call_count,1);self.assertEqual(logged.call_count,1)
                evidence=json.loads(logged.call_args.args[0].split(' ',1)[1])['compile']
                self.assertEqual(evidence['exitCode'],2)
                self.assertEqual(evidence['processCompletion'],dict(completedWithinBudget=int(mode!='late'),
                    cleanupPending=int(mode!='late'),cleanupObservationFailed=int(mode=='cleanup-error')))

    def test_zero_exit_with_pending_cleanup_still_fails(self):
        process=NS(returncode=0,communicate=mock.Mock(return_value=('','')))
        with mock.patch.object(subprocess,'Popen',return_value=process), \
             mock.patch.object(sys.modules[__name__],'_serializer_bounded_cleanup',return_value=dict(pending=1)), \
             mock.patch.object(time,'monotonic',return_value=0.):
            with self.assertRaisesRegex(AssertionError,'resources remain unproved'):
                _serializer_compile_process('synthetic-command',cwd=Path('/synthetic'),env={},timeout=60,observe_phase=lambda:{})

    def test_offline_serializer_environment_reads_only_the_nonsecret_allowlist(self):
        environment=self.helper('_serializer_environment')
        values={'SystemRoot':'synthetic-windows','PATH':'synthetic-tools','TEMP':'synthetic-temp',
                'CREDENTIAL_TOKEN':'synthetic-secret','CL':'/unsafe','_CL_':'/unsafe'}
        with mock.patch.dict(os.environ,values,clear=True):
            result=environment()
        self.assertEqual(result,{'SystemRoot':'synthetic-windows','PATH':'synthetic-tools','TEMP':'synthetic-temp'})

    def test_cleanup_observation_failure_cannot_replace_the_inner_timeout(self):
        self.helper('_serializer_compile_process')
        with mock.patch.object(sys.modules[__name__],'_serializer_bounded_cleanup',side_effect=OSError('synthetic cleanup failure')):
            try:self.bounded_compile()
            except OSError:self.fail('Optional cleanup observation replaced the original timeout')

    def test_native_child_snapshot_queries_only_the_retained_handle(self):
        for native_pid,wait_result in ((77,258),(88,258),(77,0xffffffff)):
            with self.subTest(pid=native_pid,wait=wait_result):
                kernel=NS(GetProcessId=mock.Mock(return_value=native_pid),
                          WaitForSingleObject=mock.Mock(return_value=wait_result))
                process=NS(pid=77,_handle=9,poll=lambda:None)
                with mock.patch.object(os,'name','nt'),mock.patch.object(ctypes,'WinDLL',return_value=kernel,create=True):
                    value=_serializer_process_state(process)
                self.assertEqual(value['handleMatchesPid'],int(native_pid==77))
                self.assertEqual(value['waitResult'],wait_result)
                self.assertEqual(kernel.GetProcessId.call_args.args,(9,))
                self.assertEqual(kernel.WaitForSingleObject.call_args.args,(9,0))

    def test_signaled_child_race_refreshes_cached_exit_before_handle_close(self):
        cleanup=self.helper('_serializer_bounded_cleanup')
        for refreshed_code in (0,None):
            with self.subTest(exitCodeKnown=refreshed_code is not None):
                calls=[]
                process=NS(pid=77,returncode=None,stdout=None,stderr=None)
                def poll():
                    calls.append('poll');process.returncode=refreshed_code;return refreshed_code
                def close():
                    self.assertIsNotNone(process.returncode,'A still-uncached Popen must retain its HANDLE')
                    calls.append('close')
                process.poll=poll;process._handle=NS(Close=close)
                # The native wait became signaled after this observation's
                # poll returned None, while Popen's cached result stayed None.
                observed=dict(pid=77,pollKnown=1,exited=0,exitCode=0,waitResult=0,handleMatchesPid=1)
                with mock.patch.object(sys.modules[__name__],'_serializer_process_state',return_value=observed), \
                     mock.patch.object(time,'monotonic',return_value=60.):
                    value=cleanup(process,60.,kill=False)
                self.assertEqual(calls,['poll','close'] if refreshed_code is not None else ['poll'])
                self.assertEqual(value['directHandleClosed'],int(refreshed_code is not None))
                self.assertEqual(value['pending'],int(refreshed_code is None))
                self.assertEqual(value['afterCleanup']['exited'],int(refreshed_code is not None))

    def test_serializer_capture_redacts_timeout_and_portable_nonzero_messages(self):
        capture=self.helper('_serializer_capture')
        class Private:
            def __str__(self):raise AssertionError('No command or stderr conversion')
            def __repr__(self):raise AssertionError('No command or stderr representation')
        for label in ('owned-native-vs-discovery','owned-native-serializer-run',
                      'owned-native-portable-compile','owned-native-portable-run'):
            with self.subTest(label=label):
                original=subprocess.TimeoutExpired(Private(),15,output=Private(),stderr=Private())
                with mock.patch.object(subprocess,'run',side_effect=original) as run:
                    with self.assertRaises(subprocess.TimeoutExpired) as caught:
                        capture(Private(),label=label,timeout=15)
                self.assertEqual(run.call_count,1)
                self.assertTrue(type(caught.exception.cmd) is str)
                self.assertEqual(caught.exception.cmd,label);self.assertEqual(caught.exception.timeout,15)
                self.assertIsNone(caught.exception.stdout);self.assertIsNone(caught.exception.stderr)
                self.assertTrue(caught.exception.__suppress_context__)
                self.assertNotIn('Private',repr(caught.exception))
                self.assertNotIn('Private',''.join(traceback.format_exception(caught.exception)))
        for label in ('owned-native-portable-compile','owned-native-portable-run'):
            with self.subTest(label=label),mock.patch.object(subprocess,'run',return_value=NS(returncode=7,stderr=Private())) as run:
                with self.assertRaises(AssertionError) as caught:capture(Private(),label=label,require_zero=True)
                self.assertEqual(str(caught.exception),label+' failed')
                self.assertNotIn('check',run.call_args.kwargs)

    def test_real_serializer_vs_discovery_and_execution_use_redacted_timeout_boundary(self):
        class Private:
            def __str__(self):raise AssertionError('No raw timeout command conversion')
            def __repr__(self):raise AssertionError('No raw timeout command representation')
        root,_,_=self.compile_inputs();controller=self.pe(root/'controller.exe',0x8664)
        installer=root/'Microsoft Visual Studio/Installer/vswhere.exe';installer.parent.mkdir(parents=True);installer.write_bytes(b'fixture')
        def architecture(handle,process,native):
            ctypes.cast(process,ctypes.POINTER(ctypes.c_uint16)).contents.value=0
            ctypes.cast(native,ctypes.POINTER(ctypes.c_uint16)).contents.value=0x8664
            return 1
        def module_name(handle,buffer,size):buffer.value=str(controller);return len(str(controller))
        kernel=NS(GetCurrentProcess=mock.Mock(return_value=1),IsWow64Process2=mock.Mock(side_effect=architecture),
                  GetModuleFileNameW=mock.Mock(side_effect=module_name))
        exe=self.pe(root/'serializer.exe',0x8664);receipt={'output':_serializer_pe(exe,0x8664)}
        for label,call in (('owned-native-vs-discovery',_serializer_windows_plan),
                           ('owned-native-serializer-run',lambda:_run_windows_serializer(exe,receipt))):
            with self.subTest(label=label),mock.patch.dict(os.environ,{'ProgramFiles(x86)':str(root),'SystemRoot':str(root)},clear=True), \
                 mock.patch.object(ctypes,'WinDLL',return_value=kernel,create=True), \
                 mock.patch.object(subprocess,'run',side_effect=subprocess.TimeoutExpired(Private(),15,output=Private(),stderr=Private())) as run:
                with self.assertRaises(subprocess.TimeoutExpired) as caught:call()
                self.assertEqual(run.call_count,1);self.assertTrue(type(caught.exception.cmd) is str)
                self.assertEqual(caught.exception.cmd,label);self.assertEqual(caught.exception.timeout,15)
                self.assertTrue(caught.exception.__suppress_context__)
                self.assertNotIn('Private',''.join(traceback.format_exception(caught.exception)))

    def pe(self, path, machine):
        path.parent.mkdir(parents=True,exist_ok=True)
        data=bytearray(512);data[:2]=b'MZ';struct.pack_into('<I',data,0x3c,128)
        data[128:132]=b'PE\0\0';struct.pack_into('<H',data,132,machine)
        struct.pack_into('<H',data,148,240);struct.pack_into('<H',data,150,2)
        struct.pack_into('<H',data,152,0x20b);path.write_bytes(data)
        return path

    def installation(self, root, machine):
        arch={0x8664:'x64',0xaa64:'arm64'}[machine]
        vs=root/'Visual Studio 한글';version='14.51.36231'
        version_file=vs/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'
        version_file.parent.mkdir(parents=True);version_file.write_text(version,encoding='utf-8')
        binary=vs/'VC/Tools/MSVC'/version/'bin'/('Host'+arch)/arch
        for name in ('cl.exe','link.exe'):self.pe(binary/name,machine)
        dev=vs/'Common7/Tools/VsDevCmd.bat';dev.parent.mkdir(parents=True);dev.write_text('@exit /b 0\n')
        return {'installationPath':str(vs),'installationVersion':'18.0.1'},binary

    def test_exact_native_x64_and_arm64_tools_selected(self):
        select=self.helper('_serializer_tools');arch=self.helper('_serializer_arch')
        for machine in (0x8664,0xaa64):
            with self.subTest(machine=machine),tempfile.TemporaryDirectory() as folder:
                root=Path(folder).resolve(strict=True);instance,binary=self.installation(root,machine)
                self.assertEqual({0x8664:'x64',0xaa64:'arm64'}[machine],arch(machine,0,machine))
                plan=select(instance,machine)
                for name in ('cl','link'):
                    self.assertEqual(str((binary/(name+'.exe')).resolve(strict=True)),plan[name]['path'])
                    self.assertEqual(machine,plan[name]['machine'])
                    self.assertEqual(hashlib.sha256((binary/(name+'.exe')).read_bytes()).hexdigest(),plan[name]['sha256'])

    def test_emulated_or_foreign_controller_never_counts_as_native(self):
        arch=self.helper('_serializer_arch')
        for raw in ((0xaa64,0,0x8664),(0xaa64,0x8664,0xaa64),(0x8664,0,0xaa64),(0xa641,0,0xa641)):
            with self.subTest(raw=raw),self.assertRaisesRegex(AssertionError,'native'):
                arch(*raw)

    def test_missing_or_foreign_native_compiler_and_linker_fail(self):
        select=self.helper('_serializer_tools')
        for damage in ('missing-cl','missing-link','foreign-cl','foreign-link','foreign-vs'):
            with self.subTest(damage=damage),tempfile.TemporaryDirectory() as folder:
                instance,binary=self.installation(Path(folder).resolve(strict=True),0xaa64)
                if damage.startswith('missing-'):(binary/(damage[8:]+'.exe')).unlink()
                elif damage.startswith('foreign-') and damage!='foreign-vs':self.pe(binary/(damage[8:]+'.exe'),0x8664)
                else:instance['installationVersion']='19.0.1'
                with self.assertRaises((AssertionError,FileNotFoundError)):select(instance,0xaa64)

    def test_compile_paths_reject_escape_links_and_cmd_metacharacters(self):
        owned=self.helper('_serializer_path')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve(strict=True);source=root/'owned.cpp';source.write_text('owned')
            self.assertEqual(source,owned(source,root))
            for text in ('../escape.cpp','bad%.cpp','bad!.cpp','bad&.cpp','bad|.cpp','bad<.cpp','bad>.cpp','bad^.cpp','bad\r.cpp','bad\n.cpp','bad".cpp'):
                with self.subTest(text=text),self.assertRaises(AssertionError):owned(root/text,root,exists=False)
            alias=root/'alias.cpp'
            if os.name!='nt':
                alias.symlink_to(source)
                with self.assertRaisesRegex(AssertionError,'linked'):owned(alias,root)

    def test_compile_failure_stops_and_preserves_parent_environment(self):
        compile_fixture=self.helper('_compile_windows_serializer')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve(strict=True);instance,_=self.installation(root,0x8664)
            plan=self.helper('_serializer_tools')(instance,0x8664)
            plan['commandProcessor']=self.helper('_serializer_pe')(self.pe(root/'cmd.exe',0x8664),0x8664)
            source=root/'serializer.cpp';source.write_text('int main(){}',encoding='utf-8')
            environment=dict(SERIALIZER_TEST_ONLY='1',CL='/unsafe',_CL_='/unsafe')
            with mock.patch.dict(os.environ,environment,clear=True),mock.patch.object(sys.modules[__name__],'_serializer_compile_process',return_value=subprocess.CompletedProcess([],2,'compile stdout','compile stderr')) as run,mock.patch('builtins.print') as logged:
                with self.assertRaisesRegex(AssertionError,'compile.*2'):
                    compile_fixture(root,source,plan)
                self.assertEqual(1,run.call_count)
                evidence=json.loads(logged.call_args.args[0].split(' ',1)[1])
                self.assertIn('toolchain',evidence,'Failed compile must retain selected native tool identities')
                self.assertEqual(plan,evidence['toolchain'])
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),evidence['source']['sha256'])
                self.assertEqual(2,evidence['compile']['exitCode'])
                child_env=run.call_args.kwargs['env']
                self.assertNotIn('CL',child_env);self.assertNotIn('_CL_',child_env)
                self.assertEqual('/unsafe',os.environ['CL']);self.assertEqual('/unsafe',os.environ['_CL_'])
            batch=(root/'compile-serializer.cmd').read_text(encoding='utf-8')
            for flag in ('/std:c++17','/EHsc','/utf-8','/MT','/W4','/WX','/D_SILENCE_CXX17_CODECVT_HEADER_DEPRECATION_WARNING','/MACHINE:X64'):
                self.assertIn(flag,batch)
            self.assertIn('set "PATH='+str(Path(plan['link']['path']).parent)+';%PATH%"',batch)
            self.assertNotIn('/MD',batch);self.assertNotIn('/wd',batch)

    def test_executed_output_identity_must_remain_exact(self):
        run_fixture=self.helper('_run_windows_serializer')
        with tempfile.TemporaryDirectory() as folder:
            exe=self.pe(Path(folder).resolve(strict=True)/'serializer.exe',0xaa64)
            receipt={'output':self.helper('_serializer_pe')(exe,0xaa64)}
            def changed_output(*args,**kwargs):
                exe.write_bytes(exe.read_bytes()+b'changed')
                return subprocess.CompletedProcess([],0,'"same JSON"','')
            with mock.patch.object(subprocess,'run',side_effect=changed_output) as run,mock.patch('builtins.print') as logged:
                with self.assertRaisesRegex(AssertionError,'changed.*execution'):run_fixture(exe,receipt)
                self.assertEqual(1,run.call_count)
                evidence=json.loads(logged.call_args.args[0].split(' ',1)[1])
                self.assertIn('output',evidence,'Failed execution must retain original compiled output identity')
                self.assertEqual(receipt['output'],evidence['output'])
                self.assertEqual(0,evidence['run']['exitCode'])

    def test_compiled_output_must_be_native_before_execution(self):
        compile_fixture=self.helper('_compile_windows_serializer')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve(strict=True);instance,_=self.installation(root,0xaa64)
            plan=self.helper('_serializer_tools')(instance,0xaa64)
            plan['commandProcessor']=self.helper('_serializer_pe')(self.pe(root/'cmd.exe',0xaa64),0xaa64)
            source=root/'serializer.cpp';source.write_text('int main(){}',encoding='utf-8')
            def compile_foreign(*args,**kwargs):
                self.pe(root/'serializer.exe',0x8664)
                return subprocess.CompletedProcess([],0,'','')
            with mock.patch.dict(os.environ,{'SERIALIZER_TEST_ONLY':'1'},clear=True), mock.patch.object(sys.modules[__name__],'_serializer_compile_process',side_effect=compile_foreign) as run:
                with self.assertRaisesRegex(AssertionError,'machine'):compile_fixture(root,source,plan)
                self.assertEqual(1,run.call_count)

if __name__=='__main__':unittest.main()
