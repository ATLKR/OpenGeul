"""Execute isolated producer functions and normal payload rejection, never Office."""
import hashlib
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from suite.tests.test_payload import PayloadFixture
from suite.tests.test_native_engine_build import PWSH as EXISTING_PWSH

ROOT=Path(__file__).resolve().parents[2]
DRIVER=ROOT/'suite/scripts/build-native-engine.ps1'
PWSH=shutil.which('pwsh') or EXISTING_PWSH


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module);return module


def quote(value):return "'"+str(value).replace("'","''")+"'"


def child_environment(platform,pwsh,python,owned_root,*,system_root=None,windir=None):
    values={'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'}
    if platform=='nt':
        paths=(pwsh,python,owned_root,system_root,windir)
        for value in paths:
            if (type(value) is not str or not ntpath.isabs(value) or len(ntpath.splitdrive(value)[0])!=2
                    or '\x00' in value or any(part in ('.','..') for part in value.replace('/','\\').split('\\'))):
                raise ValueError('Synthetic Windows bootstrap requires local absolute paths')
        system_root,windir=ntpath.normpath(system_root),ntpath.normpath(windir)
        if ntpath.normcase(system_root)!=ntpath.normcase(windir):raise ValueError('Windows system roots differ')
        join=ntpath.join
        directories=[ntpath.dirname(pwsh),ntpath.dirname(python),join(system_root,'System32'),system_root]
        values.update(SystemRoot=system_root,WINDIR=windir,PATH=';'.join(dict.fromkeys(directories)),
            TEMP=join(owned_root,'temp'),TMP=join(owned_root,'temp'),USERPROFILE=join(owned_root,'profile'),
            APPDATA=join(owned_root,'profile','AppData','Roaming'),LOCALAPPDATA=join(owned_root,'profile','AppData','Local'))
    elif platform=='posix':
        if any(not Path(value).is_absolute() for value in (pwsh,python,owned_root)):
            raise ValueError('Synthetic POSIX bootstrap requires absolute paths')
        directories=[str(Path(pwsh).parent),str(Path(python).parent),'/usr/bin','/bin']
        values.update(PATH=':'.join(dict.fromkeys(directories)),TEMP=str(Path(owned_root)/'temp'),TMP=str(Path(owned_root)/'temp'),
            XDG_CACHE_HOME=str(Path(owned_root)/'cache'),XDG_CONFIG_HOME=str(Path(owned_root)/'config'),XDG_DATA_HOME=str(Path(owned_root)/'data'))
    else:raise ValueError('Unknown bootstrap platform')
    return values


class BootstrapTests(unittest.TestCase):
    def test_synthetic_windows_bootstrap_uses_only_validated_tools_system_and_owned_directories(self):
        value=child_environment('nt',r'C:\Tools\PowerShell\pwsh.exe',r'C:\Tools\Python\python.exe',r'C:\Fixture',system_root=r'C:\Windows',windir=r'C:\WINDOWS')
        self.assertEqual(value['PATH'],r'C:\Tools\PowerShell;C:\Tools\Python;C:\Windows\System32;C:\Windows')
        self.assertEqual(value['TEMP'],r'C:\Fixture\temp');self.assertEqual(value['USERPROFILE'],r'C:\Fixture\profile')
        self.assertNotIn('HOME',value);self.assertNotIn('PYTHONPATH',value)
        for root in (None,r'\\server\Windows',r'C:\Windows\..\Other'):
            with self.assertRaises(ValueError):child_environment('nt',r'C:\Tools\pwsh.exe',r'C:\Tools\python.exe',r'C:\Fixture',system_root=root,windir=r'C:\Windows')


class WriterProducerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        if not PWSH or not Path(PWSH).is_file():self.skipTest('Existing PowerShell is unavailable; no installation attempted')
        if not Path(sys.executable).is_file():self.skipTest('Existing Python executable is unavailable')
        self.pwsh=str(Path(PWSH).resolve())
        roots={'system_root':os.environ.get('SystemRoot'),'windir':os.environ.get('WINDIR')} if os.name=='nt' else {}
        self.environment=child_environment(os.name,self.pwsh,str(Path(sys.executable).resolve()),str(self.root),**roots)
        for key in ('TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','XDG_CACHE_HOME','XDG_CONFIG_HOME','XDG_DATA_HOME'):
            if key in self.environment:Path(self.environment[key]).mkdir(parents=True,exist_ok=True)

    def installer_environment(self):
        names=('PATH','SystemRoot','WINDIR','TEMP','TMP','PYTHONUTF8','PYTHONDONTWRITEBYTECODE')
        return '@{'+''.join(quote(name)+'='+quote(self.environment[name])+';' for name in names if name in self.environment)+'}'

    def ps(self,body):
        script=self.root/'case.ps1';script.write_text("$ErrorActionPreference='Stop'\n. "+quote(DRIVER)+"\n"+body)
        result=subprocess.run([self.pwsh,'-NoLogo','-NoProfile','-File',str(script)],capture_output=True,text=True,env=self.environment,timeout=30)
        self.assertEqual(0,result.returncode,result.stdout+'\n'+result.stderr);return result.stdout.strip()

    def test_modes_are_mutually_exclusive_and_writer_never_qualifies(self):
        proof=json.loads(self.ps("Get-NativeEngineBuildMode Full -WriterServerObserverDiagnostic|ConvertTo-Json -Compress"))
        self.assertEqual('native-office-engine-writer-server-observer-diagnostic',proof['kind'])
        self.assertFalse(proof['fullEngineQualified']);self.assertFalse(proof['acceptanceEligible'])
        self.assertEqual('writer-server-observer-source-build-receipt.json',proof['receipt'])
        self.ps("foreach($case in 1,2){$rejected=$false;try{if($case -eq 1){Get-NativeEngineBuildMode Full -WriterServerObserverDiagnostic -CalcDispatchDiagnostic}else{Get-NativeEngineBuildMode Firebird -WriterServerObserverDiagnostic}}catch{$rejected=$true};if(-not $rejected){throw 'Mixed or partial mode admitted'}}")
        rows=json.loads(self.ps("@(Get-NativeEngineBuildMode Full;Get-NativeEngineBuildMode Full -CalcDispatchDiagnostic)|ConvertTo-Json -Compress"))
        self.assertTrue(rows[0]['fullEngineQualified']);self.assertFalse(rows[1]['fullEngineQualified'])

    def test_writer_exact_owner_push_requires_actual_source_binding(self):
        self.ps("""
$ref='refs/heads/work/opengeul-office-native-writer-observer';$sha='a'*40
$context=@{GITHUB_ACTIONS='true';RUNNER_ENVIRONMENT='github-hosted';RUNNER_OS='Windows';RUNNER_ARCH='ARM64';GITHUB_REPOSITORY='ATLKR/OpenGeul';GITHUB_REPOSITORY_OWNER='ATLKR';GITHUB_EVENT_NAME='push';GITHUB_JOB='native-firebird-and-office';GITHUB_REF=$ref;GITHUB_WORKFLOW_REF=('ATLKR/OpenGeul/.github/workflows/office-native-engine.yml@'+$ref);GITHUB_RUN_ATTEMPT='1';GITHUB_ACTOR='ATLKR';GITHUB_ACTOR_ID='65988341';GITHUB_SHA=$sha;GITHUB_WORKFLOW_SHA=$sha;GITHUB_RUN_ID='123';OPENGEUL_WRITER_SERVER_OBSERVER_BUILD='true';OPENGEUL_CALC_DISPATCH_BUILD='false'}
$event=@{repository=@{full_name='ATLKR/OpenGeul';private=$false;id=1405493151};sender=@{login='ATLKR';id=65988341;type='User'};ref=$ref;deleted=$false;after=$sha}
$binding=@{sourceCommit=$sha;sourceTree=('b'*40);sourceRun=123;runAttempt=1}
Assert-WriterServerObserverOwnerPush $context $event $binding
foreach($key in $context.Keys){$bad=$context.Clone();$bad[$key]='wrong';$rejected=$false;try{Assert-WriterServerObserverOwnerPush $bad $event $binding}catch{$rejected=$true};if(-not $rejected){throw 'Context drift admitted'}}
foreach($key in $binding.Keys){$bad=$binding.Clone();$bad[$key]=$null;$rejected=$false;try{Assert-WriterServerObserverOwnerPush $context $event $bad}catch{$rejected=$true};if(-not $rejected){throw 'Source drift admitted'}}
""")

    def test_actual_installer_cli_authenticates_both_source_libraries(self):
        package=ROOT/'suite/engine-build/writer-server-observer-diagnostic'
        if not package.is_dir():package=ROOT.parent/'backend-candidate/suite/engine-build/writer-server-observer-diagnostic'
        upstream=package/'tests/upstream'
        self.assertTrue(upstream.is_dir(),'Exact public pinned source fixture is required; no source-free pass')
        source=self.root/'lo';shutil.copytree(upstream,source);(source/'include').mkdir(exist_ok=True)
        repo=self.root/'repo';target=repo/'suite/engine-build/writer-server-observer-diagnostic';target.mkdir(parents=True)
        for name in ('install.py','source-lock.json','source.patch','wire-schema.json','wire.h','atomic.h','descriptor.h','private_sink.hxx','recorder.h','session.h','observer_api.hxx','native.cpp'):
            shutil.copyfile(package/name,target/name)
        evidence=self.root/'evidence';evidence.mkdir()
        from suite.tests import test_payload
        baseline=Path(test_payload.__file__).resolve().parents[2]
        lock=self.root/'runtime.lock.json';shutil.copyfile(baseline/'suite/config/runtime.arm64.lock.json',lock)
        raw=self.ps(f"$script:NativeEngineBuildBudget=New-NativeBuildBudget -MaximumMinutes 1;$pin=Get-SourcePin {quote(lock)};Install-WriterServerObserverSource {quote(source)} {quote(repo)} {quote(sys.executable)} {quote(evidence)} $pin -ChildEnvironment {self.installer_environment()}|ConvertTo-Json -Depth 12 -Compress")
        proof=json.loads(raw.splitlines()[-1])
        self.assertTrue(proof['passed']);self.assertFalse(proof['fullEngineQualified']);self.assertFalse(proof['acceptanceEligible']);self.assertFalse(proof['guiVerified'])
        self.assertEqual(['UAccCOM','winaccessibility'],proof['requiredRebuiltLibraries'])
        manifest=json.loads((target/'source-lock.json').read_bytes())
        for row in manifest['sources']:
            self.assertEqual(row['after']['sha256'],hashlib.sha256((source/row['path']).read_bytes()).hexdigest())

    def test_marker_requires_two_native_dlls_and_detects_one_dll_overlay(self):
        runtime=self.root/'runtime';(runtime/'program').mkdir(parents=True)
        raw=bytearray(512);raw[:2]=b'MZ';struct.pack_into('<I',raw,60,128);raw[128:132]=b'PE\0\0'
        struct.pack_into('<H',raw,132,0xaa64);struct.pack_into('<H',raw,148,240);struct.pack_into('<H',raw,152,0x20b)
        (runtime/'program/UAccCOM.dll').write_bytes(raw)
        proof="$proof=@{passed=$true;schemaVersion=1;target='windows-arm64';kind='writer-server-observer-diagnostic-source';lockSha256=('c'*64);coreCommit='bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1';ipcVersion=1;sinkAbiVersion=2;requiredRebuiltLibraries=@('UAccCOM','winaccessibility');fullEngineQualified=$false;acceptanceEligible=$false;guiVerified=$false;patch=@{sha256=('d'*64)};wireSchema=@{path='wire-schema.json';bytes=1;sha256=('e'*64)}};$binding=@{sourceCommit=('a'*40);sourceTree=('b'*40)};"
        self.ps(proof+f"$rejected=$false;try{{Write-WriterServerObserverRuntimeMarker {quote(runtime)} $binding $proof|Out-Null}}catch{{$rejected=$true}};if(-not $rejected){{throw 'One DLL admitted'}}")
        (runtime/'program/winaccessibility.dll').write_bytes(raw)
        self.ps(proof+f"Write-WriterServerObserverRuntimeMarker {quote(runtime)} $binding $proof|Out-Null")
        first=(runtime/'writer-server-observer-diagnostic.json').read_bytes()
        self.assertEqual(first,(runtime/'program/opengeul-writer-server-observer-diagnostic.json').read_bytes())
        marker=json.loads(first);self.assertFalse(marker['acceptanceEligible']);self.assertEqual(len(marker['binaries']),2)
        (runtime/'program/UAccCOM.dll').write_bytes(bytes(raw)+b'overlay')
        self.ps(f"$marker=Get-Content -LiteralPath {quote(runtime/'writer-server-observer-diagnostic.json')} -Raw|ConvertFrom-Json;$rejected=$false;try{{Assert-WriterServerObserverRuntime {quote(runtime)} $marker}}catch{{$rejected=$true}};if(-not $rejected){{throw 'Single DLL overlay admitted'}}")

    def test_workflow_dispatches_real_mode_and_uploads_only_its_family(self):
        text=(ROOT/'.github/workflows/office-native-engine.yml').read_text()
        build=text.split('      - name: Build and verify native Firebird before the full Office engine\n',1)[1].split('      - name:',1)[0]
        body=textwrap.dedent(build.split('        run: |\n',1)[1])
        body=body.replace('./suite/scripts/build-native-engine.ps1','Get-WorkflowSelectedMode')
        wrapper="function Get-WorkflowSelectedMode {param($Phase,$WorkDirectory,$OutputDirectory,$SourceLockPath,$DeadlineUtc,[switch]$MutexSymbols,[switch]$CalcDispatchDiagnostic,[switch]$WriterServerObserverDiagnostic);Get-NativeEngineBuildMode $Phase -CalcDispatchDiagnostic:$CalcDispatchDiagnostic -WriterServerObserverDiagnostic:$WriterServerObserverDiagnostic|ConvertTo-Json -Compress}\n"
        for flag,expected in [('true','native-office-engine-writer-server-observer-diagnostic'),('false','native-office-engine-calc-dispatch-diagnostic')]:
            value=json.loads(self.ps("$env:OPENGEUL_WRITER_SERVER_OBSERVER_BUILD="+quote(flag)+';\n'+wrapper+body).splitlines()[-1])
            self.assertEqual(expected,value['kind']);self.assertFalse(value['fullEngineQualified'])
        self.assertIn('runs-on: windows-11-arm',text);self.assertIn('timeout-minutes: 360',text);self.assertIn('AddMinutes(330)',text)
        for name in ['Retain the qualified native engine input','Retain the isolated Calc dispatch diagnostic engine']:
            block=text.split('      - name: '+name+'\n',1)[1].split('      - name:',1)[0]
            self.assertIn("env.OPENGEUL_WRITER_SERVER_OBSERVER_BUILD != 'true'",block)

    def test_actual_driver_admits_writer_before_download_and_hooks_before_configure(self):
        self.ps(f"""
$tokens=$null;$errors=$null;$tree=[System.Management.Automation.Language.Parser]::ParseFile({quote(DRIVER)},[ref]$tokens,[ref]$errors)
if($errors.Count){{throw 'Driver parse failed'}}
$build=@($tree.FindAll({{param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Invoke-NativeEngineBuild'}},$true))[0]
$commands=@($build.Body.FindAll({{param($n)$n -is [System.Management.Automation.Language.CommandAst]}},$true))
$admission=@($commands|Where-Object {{$_.GetCommandName() -ceq 'Assert-WriterServerObserverEnvironment'}})
$download=@($commands|Where-Object {{$_.GetCommandName() -ceq 'Get-AuthenticatedDownload'}})
$hook=@($commands|Where-Object {{$_.GetCommandName() -ceq 'Install-WriterServerObserverSource'}})
$configure=@($commands|Where-Object {{$_.GetCommandName() -ceq 'Get-ConfigureArguments'}})
$marker=@($commands|Where-Object {{$_.GetCommandName() -ceq 'Write-WriterServerObserverRuntimeMarker'}})
$archive=@($commands|Where-Object {{$_.GetCommandName() -ceq 'Write-NativeEngineArchive'}})
if($admission.Count -ne 1 -or $hook.Count -ne 1 -or $marker.Count -ne 1 -or
 $admission[0].Extent.StartOffset -ge $download[0].Extent.StartOffset -or $hook[0].Extent.StartOffset -ge $configure[0].Extent.StartOffset -or
 $marker[0].Extent.StartOffset -ge $archive[0].Extent.StartOffset){{throw 'Actual writer stage order differs'}}
""")

    def test_closed_installer_child_environment_does_not_inherit_private_synthetic_value(self):
        body="import os;assert 'WRITER_SYNTHETIC_PRIVATE' not in os.environ;print('closed')"
        prefix=self.root/'closed'
        self.ps(f"$env:WRITER_SYNTHETIC_PRIVATE='synthetic-only';$script:NativeEngineBuildBudget=New-NativeBuildBudget -MaximumMinutes 1;$r=Invoke-LoggedCommand {quote(sys.executable)} @('-c',{quote(body)}) {quote(self.root)} {quote(prefix)} -ChildEnvironment {self.installer_environment()};if((Get-Content -LiteralPath $r.stdout -Raw).Trim() -cne 'closed'){{throw 'Child environment differs'}}")

    def test_real_partial_build_failure_never_emits_normal_qualified_receipt(self):
        work=self.root/'work';evidence=self.root/'evidence'
        self.ps(f"function Get-NativeBuildHost{{throw 'Synthetic native host rejection'}};try{{Invoke-NativeEngineBuild Full {quote(work)} {quote(evidence)} '' 4 -WriterServerObserverDiagnostic}}catch{{}}")
        proof=json.loads((evidence/'writer-server-observer-source-build-receipt.json').read_text(encoding='utf-8-sig'))
        self.assertEqual('failed',proof['status']);self.assertFalse(proof['passed'])
        self.assertFalse(proof['fullEngineQualified']);self.assertFalse(proof['acceptanceEligible']);self.assertFalse(proof['guiVerified'])
        self.assertFalse((evidence/'source-build-receipt.json').exists());self.assertFalse(list(evidence.glob('*.zip')))


class WriterPayloadRejectionTests(PayloadFixture):
    def setUp(self):
        super().setUp();self.payload=load('writer_producer_payload',ROOT/'suite/payload.py')

    def test_markers_and_case_aliases_reject_before_metadata_or_pe(self):
        for name in ('writer-server-observer-diagnostic.json','WRITER-SERVER-OBSERVER-DIAGNOSTIC.JSON',
                     'Office/program/opengeul-writer-server-observer-diagnostic.json',
                     'OFFICE/PROGRAM/OPENGEUL-WRITER-SERVER-OBSERVER-DIAGNOSTIC.JSON'):
            with self.subTest(name=name):
                self.write(name,b'{}')
                with patch.object(self.payload,'_metadata',side_effect=AssertionError('Metadata reached')),patch.object(self.payload,'_pe',side_effect=AssertionError('PE reached')):
                    with self.assertRaisesRegex(ValueError,'Writer observer diagnostic'):
                        self.payload.create_inventory(self.root)
                    with self.assertRaisesRegex(ValueError,'Writer observer diagnostic'):
                        self.payload.verify_payload(self.root,{})
                (self.root/name).unlink()

    def test_receipt_marker_cannot_be_removed_from_disk_to_repackage(self):
        files={'writer-server-observer-diagnostic.json':{'size':0,'sha256':'a'*64}}
        with self.assertRaisesRegex(ValueError,'Writer observer diagnostic'):
            self.payload._validate(self.root,files,architecture='x64')

    def test_common_normal_ime_and_menu_launcher_rejects_before_pointer_or_popen(self):
        from suite.tests import test_payload
        baseline=Path(test_payload.__file__).resolve().parents[2]
        layout=self.root.parent/'launcher';e2e=layout/'suite/e2e';e2e.mkdir(parents=True)
        shutil.copyfile(ROOT/'suite/payload.py',layout/'suite/payload.py')
        shutil.copyfile(ROOT/'suite/e2e/windows_smoke.py',e2e/'windows_smoke.py')
        for name in ('native_window_evidence.py','ascii_editor_input.py'):
            shutil.copyfile(baseline/'suite/e2e'/name,e2e/name)
        with patch.object(sys,'path',[str(e2e),str(baseline/'suite/e2e'),*sys.path]):
            launcher=load('writer_normal_launcher',e2e/'windows_smoke.py')
        self.write('writer-server-observer-diagnostic.json',b'{}')
        with patch.object(launcher,'prepare_launch_pointer',side_effect=AssertionError('Pointer preparation reached')),patch.object(launcher.subprocess,'Popen',side_effect=AssertionError('Process launch reached')):
            with self.assertRaisesRegex(ValueError,'Writer observer diagnostic'):
                launcher.launch_suite(['synthetic.exe'],self.root,self.root.parent/'output','synthetic')

    def test_actual_normal_cli_guards_run_before_sdk_cohort_or_inventory(self):
        from suite.tests import test_payload
        baseline=Path(test_payload.__file__).resolve().parents[2]
        layout=self.root.parent/'cli';e2e=layout/'suite/e2e';e2e.mkdir(parents=True)
        shutil.copyfile(ROOT/'suite/payload.py',layout/'suite/payload.py')
        for name in ('windows_smoke.py','korean_ime_smoke.py','native_menu_smoke.py'):
            shutil.copyfile(ROOT/'suite/e2e'/name,e2e/name)
        for name in ('native_window_evidence.py','ascii_editor_input.py'):
            shutil.copyfile(baseline/'suite/e2e'/name,e2e/name)
        self.write('writer-server-observer-diagnostic.json',b'{}')
        with patch.object(sys,'path',[str(e2e),str(baseline/'suite/e2e'),*sys.path]):
            launcher=load('writer_cli_launcher',e2e/'windows_smoke.py')
            with patch.dict(sys.modules,{'windows_smoke':launcher}):
                modules=[launcher,load('writer_cli_ime',e2e/'korean_ime_smoke.py'),load('writer_cli_menu',e2e/'native_menu_smoke.py')]
                for module in modules:
                    args=['--suite',str(self.root)]
                    if module is not modules[1]:args+=['--fixtures',str(self.root.parent/'fixtures'),'--output',str(self.root.parent/'output')]
                    with self.subTest(caller=module.__name__),patch.object(module,'os',SimpleNamespace(name='nt')):
                        with self.assertRaisesRegex(ValueError,'Writer observer diagnostic'):module.main(args)


if __name__=='__main__':unittest.main()
