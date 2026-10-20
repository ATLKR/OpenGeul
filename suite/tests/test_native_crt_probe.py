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
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'suite/scripts/probe-native-crt.ps1'
PWSH=shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'

def quote(value):return "'"+str(value).replace("'","''")+"'"


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
    result=subprocess.run([str(installer),'-latest','-products','*','-version','[17.0,19.0)','-format','json','-utf8'],
                          capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=15)
    assert result.returncode==0, 'Native serializer VS discovery failed: '+result.stderr
    instances=json.loads(result.stdout)
    assert isinstance(instances,list) and len(instances)==1, 'One installed VS17/18 native compiler is required'
    plan=_serializer_tools(instances[0],native.value)
    assert plan['arch']==arch
    plan['controller']={'processMachine':process.value,'nativeMachine':native.value,'image':controller}
    plan['commandProcessor']=_serializer_pe(Path(os.environ['SystemRoot'])/'System32/cmd.exe',native.value)
    return plan


def _compile_windows_serializer(root, source, plan):
    root=_serializer_path(root);source=_serializer_path(source,root)
    exe=_serializer_path(root/'serializer.exe',root,exists=False)
    obj=_serializer_path(root/'serializer.obj',root,exists=False)
    batch=_serializer_path(root/'compile-serializer.cmd',root,exists=False)
    cl=_serializer_pe(plan['cl']['path'],plan['machine']);link=_serializer_pe(plan['link']['path'],plan['machine'])
    assert cl==plan['cl'] and link==plan['link'], 'Native tools changed before compile'
    dev=_serializer_path(plan['devcmd']);command=plan['commandProcessor']
    assert _serializer_pe(command['path'],plan['machine'])==command, 'Native command processor changed'
    lines=['@echo off','chcp 65001 >nul','if errorlevel 1 exit /b %errorlevel%',
           'call "'+str(dev)+'" -no_logo -arch='+plan['arch']+' -host_arch='+plan['arch'],
           'if errorlevel 1 exit /b %errorlevel%','chcp 65001 >nul','if errorlevel 1 exit /b %errorlevel%',
           'set "CL="','set "_CL_="','set "PATH='+str(Path(link['path']).parent)+';%PATH%"',
           '"'+cl['path']+'" /nologo /std:c++17 /EHsc /utf-8 /MT /W4 /WX /D_SILENCE_CXX17_CODECVT_HEADER_DEPRECATION_WARNING '+
           '/Fe:"'+str(exe)+'" /Fo:"'+str(obj)+'" "'+str(source)+'" /link /MACHINE:'+plan['arch'].upper()+' /INCREMENTAL:NO',
           'exit /b %errorlevel%']
    batch.write_text('\r\n'.join(lines)+'\r\n',encoding='utf-8',newline='')
    environment={k:v for k,v in os.environ.items() if k.upper() not in ('CL','_CL_')}
    # Both the command processor and batch are absolute, checked paths; the
    # double outer quotes are CMD /s /c syntax, not shell=True interpretation.
    command_line='"'+command['path']+'" /d /v:off /s /c ""'+str(batch)+'""'
    source_identity={'path':str(source),'size':source.stat().st_size,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    result=subprocess.run(command_line,cwd=root,env=environment,capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=60)
    compile_receipt={'exitCode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    print('native-serializer-compile '+json.dumps({'toolchain':plan,'source':source_identity,
          'testModuleSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'compile':compile_receipt},ensure_ascii=True),flush=True)
    assert result.returncode==0, 'Native serializer compile failed exit '+str(result.returncode)+': '+result.stderr
    output=_serializer_pe(exe,plan['machine'])
    assert _serializer_pe(cl['path'],plan['machine'])==cl and _serializer_pe(link['path'],plan['machine'])==link, 'Native tools changed during compile'
    return exe,{'toolchain':plan,'source':source_identity,
                'output':output,'compile':compile_receipt,'processWitness':'PE/selected-path evidence; no retained compiler/output process HANDLE witness'}


def _run_windows_serializer(executable, receipt):
    result=subprocess.run([str(executable)],cwd=executable.parent,capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=15)
    # Delay the exit assertion until raw failed-run output is retained.
    receipt['run']={'exitCode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    print('native-serializer-run '+json.dumps({'output':receipt['output'],'run':receipt['run']},ensure_ascii=True),flush=True)
    after=_serializer_pe(executable,receipt['output']['machine'])
    assert after==receipt['output'], 'Serializer output changed during execution'
    receipt['outputAfterRun']=after
    assert result.returncode==0, 'Native serializer run failed exit '+str(result.returncode)+': '+result.stderr
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
                self.assertEqual(0,result.returncode,result.stderr)
            else:
                executable=root/'serializer'
                result=subprocess.run([shutil.which('c++'),'-std=c++17','-Wall','-Werror=multichar',str(local),'-o',str(executable)],capture_output=True,text=True)
                self.assertEqual(0,result.returncode,result.stderr)
                result=subprocess.run([str(executable)],capture_output=True,text=True,check=True)
            self.assertEqual(path,json.loads(result.stdout))


class NativeSerializerFixtureTests(unittest.TestCase):
    """Portable controls for the test-only native compiler boundary."""
    def helper(self, name):
        self.assertTrue(callable(globals().get(name)), 'Missing native serializer boundary: '+name)
        return globals()[name]

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
            environment=dict(os.environ);environment.update(CL='/unsafe',_CL_='/unsafe')
            with mock.patch.dict(os.environ,environment,clear=True),mock.patch.object(subprocess,'run',return_value=subprocess.CompletedProcess([],2,'compile stdout','compile stderr')) as run,mock.patch('builtins.print') as logged:
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
            with mock.patch.object(subprocess,'run',side_effect=compile_foreign) as run:
                with self.assertRaisesRegex(AssertionError,'machine'):compile_fixture(root,source,plan)
                self.assertEqual(1,run.call_count)

if __name__=='__main__':unittest.main()
