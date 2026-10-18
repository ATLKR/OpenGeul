"""Portable process/receipt boundaries; actual Windows native proof stays in CI."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'suite/scripts/probe-native-crt.ps1'
PWSH=shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'

def quote(value):return "'"+str(value).replace("'","''")+"'"

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
            root=Path(folder);child=root/'child.py';prefix=root/'pipe'
            child.write_text("import subprocess,sys\nsubprocess.Popen([sys.executable,'-c','import time;time.sleep(4)'])\n")
            self.ps("try { Invoke-CrtProbeCommand -FilePath "+quote(sys.executable)+
                    " -Arguments @("+quote(child)+") -WorkingDirectory "+quote(root)+" -Prefix "+quote(prefix)+
                    " -TimeoutSeconds 1 | Out-Null } catch {}")
            receipt=json.loads(prefix.with_suffix('.command.json').read_text())
            self.assertFalse(receipt['passed'], 'A retained pipe cannot silently extend the deadline')
            self.assertEqual(0,receipt['exitCode'])
            self.assertFalse(receipt['pipeDrainComplete'])
            self.assertLess(receipt['elapsedSeconds'],3)

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
