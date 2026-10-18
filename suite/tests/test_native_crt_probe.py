"""Portable process/receipt boundaries; actual Windows native proof stays in CI."""
import ctypes
import json
import os
from pathlib import Path
import re
import secrets
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'suite/scripts/probe-native-crt.ps1'
PWSH=shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'

def quote(value):return "'"+str(value).replace("'","''")+"'"


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

    @unittest.skipUnless(shutil.which('c++'), 'Portable C++ serializer check needs a local compiler')
    def test_generated_cpp_serializes_actual_wstring_windows_paths_as_json(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'probe.cpp'
            self.ps('Write-CrtProbeSource '+quote(source))
            generated=source.read_text()
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
            local=root/'serializer.cpp';local.write_text(shim+serializer+'\nint main(){std::cout<<json(L'+literal+');}\n')
            executable=root/'serializer'
            result=subprocess.run([shutil.which('c++'),'-std=c++17','-Wall','-Werror=multichar',str(local),'-o',str(executable)],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
            result=subprocess.run([str(executable)],capture_output=True,text=True,check=True)
            self.assertEqual(path,json.loads(result.stdout))

if __name__=='__main__':unittest.main()
