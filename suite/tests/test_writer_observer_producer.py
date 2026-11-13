"""Execute isolated producer functions and ARM9dea producer boundaries, never Office."""
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
import unittest

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


class ProducerPowerShellHarness(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        if not PWSH or not Path(PWSH).is_file():self.skipTest('Existing PowerShell is unavailable; no installation attempted')
        if not Path(sys.executable).is_file():self.skipTest('Existing Python executable is unavailable')
        self.pwsh=str(Path(PWSH).resolve())
        roots={'system_root':os.environ.get('SystemRoot'),'windir':os.environ.get('WINDIR')} if os.name=='nt' else {}
        self.environment=child_environment(os.name,self.pwsh,str(Path(sys.executable).resolve()),str(self.root),**roots)
        for key in ('TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','XDG_CACHE_HOME','XDG_CONFIG_HOME','XDG_DATA_HOME'):
            if key in self.environment:Path(self.environment[key]).mkdir(parents=True,exist_ok=True)

    def ps(self,body):
        script=self.root/'case.ps1';script.write_text("$ErrorActionPreference='Stop'\n. "+quote(DRIVER)+"\n"+body)
        result=subprocess.run([self.pwsh,'-NoLogo','-NoProfile','-File',str(script)],capture_output=True,text=True,env=self.environment,timeout=30)
        self.assertEqual(0,result.returncode,result.stdout+'\n'+result.stderr);return result.stdout.strip()


class WriterProducerTests(ProducerPowerShellHarness):
    def test_modes_are_mutually_exclusive_and_writer_never_qualifies(self):
        proof=json.loads(self.ps("Get-NativeEngineBuildMode Full -WriterServerObserverDiagnostic|ConvertTo-Json -Compress"))
        self.assertEqual('native-office-engine-writer-server-observer-diagnostic',proof['kind'])
        self.assertFalse(proof['fullEngineQualified']);self.assertFalse(proof['acceptanceEligible'])
        self.assertEqual('writer-server-observer-source-build-receipt.json',proof['receipt'])
        self.ps("foreach($case in 1,2,3){$rejected=$false;try{if($case -eq 1){Get-NativeEngineBuildMode Full -WriterServerObserverDiagnostic -CalcDispatchDiagnostic}elseif($case -eq 2){Get-NativeEngineBuildMode Firebird -WriterServerObserverDiagnostic}else{Get-NativeEngineBuildMode Full -WriterServerObserverDiagnostic -Architecture x64}}catch{$rejected=$true};if(-not $rejected){throw 'Mixed or partial mode admitted'}}")
        rows=json.loads(self.ps("@(Get-NativeEngineBuildMode Full;Get-NativeEngineBuildMode Full -CalcDispatchDiagnostic)|ConvertTo-Json -Compress"))
        self.assertTrue(rows[0]['fullEngineQualified']);self.assertFalse(rows[1]['fullEngineQualified'])

    def test_writer_exact_owner_push_requires_actual_source_binding(self):
        self.ps("""
$ref='refs/heads/work/opengeul-office-native-writer-observer-9dea';$sha='a'*40
$context=@{GITHUB_ACTIONS='true';RUNNER_ENVIRONMENT='github-hosted';RUNNER_OS='Windows';RUNNER_ARCH='ARM64';GITHUB_REPOSITORY='ATLKR/OpenGeul';GITHUB_REPOSITORY_OWNER='ATLKR';GITHUB_EVENT_NAME='push';GITHUB_JOB='native-firebird-and-office';GITHUB_REF=$ref;GITHUB_WORKFLOW_REF=('ATLKR/OpenGeul/.github/workflows/office-native-engine.yml@'+$ref);GITHUB_RUN_ATTEMPT='1';GITHUB_ACTOR='ATLKR';GITHUB_ACTOR_ID='65988341';GITHUB_SHA=$sha;GITHUB_WORKFLOW_SHA=$sha;GITHUB_RUN_ID='123';OPENGEUL_WRITER_SERVER_OBSERVER_BUILD='true';OPENGEUL_CALC_DISPATCH_BUILD='false'}
$event=@{repository=@{full_name='ATLKR/OpenGeul';private=$false;id=1405493151};sender=@{login='ATLKR';id=65988341;type='User'};ref=$ref;deleted=$false;after=$sha}
$binding=@{sourceCommit=$sha;sourceTree=('b'*40);sourceRun=123;runAttempt=1}
Assert-WriterServerObserverOwnerPush $context $event $binding
foreach($key in $context.Keys){$bad=$context.Clone();$bad[$key]='wrong';$rejected=$false;try{Assert-WriterServerObserverOwnerPush $bad $event $binding}catch{$rejected=$true};if(-not $rejected){throw 'Context drift admitted'}}
foreach($key in $binding.Keys){$bad=$binding.Clone();$bad[$key]=$null;$rejected=$false;try{Assert-WriterServerObserverOwnerPush $context $event $bad}catch{$rejected=$true};if(-not $rejected){throw 'Source drift admitted'}}
foreach($mutation in @('repository-id','repository-private','sender-id','sender-type','ref','deleted','after')) {
 $bad=$event|ConvertTo-Json -Depth 8|ConvertFrom-Json
 switch($mutation){'repository-id'{$bad.repository.id=1};'repository-private'{$bad.repository.private=$true};'sender-id'{$bad.sender.id=1};'sender-type'{$bad.sender.type='Bot'};'ref'{$bad.ref='refs/heads/work/opengeul-office-native-writer-observer'};'deleted'{$bad.deleted=$true};'after'{$bad.after='c'*40}}
 $rejected=$false;try{Assert-WriterServerObserverOwnerPush $context $bad $binding}catch{$rejected=$true};if(-not $rejected){throw 'Event drift admitted'}
}
$rejected=$false;try{Assert-NativeEngineOwnerPush $context $event arm64}catch{$rejected=$true};if(-not $rejected){throw 'Normal target admitted diagnostic ref'}

""")

    def test_owner_identity_rejects_array_null_and_boolean_scalars(self):
        proof=json.loads(self.ps("""
$ref='refs/heads/work/opengeul-office-native-writer-observer-9dea';$sha='a'*40
$context=@{GITHUB_ACTIONS='true';RUNNER_ENVIRONMENT='github-hosted';RUNNER_OS='Windows';RUNNER_ARCH='ARM64';GITHUB_REPOSITORY='ATLKR/OpenGeul';GITHUB_REPOSITORY_OWNER='ATLKR';GITHUB_EVENT_NAME='push';GITHUB_JOB='native-firebird-and-office';GITHUB_REF=$ref;GITHUB_WORKFLOW_REF=('ATLKR/OpenGeul/.github/workflows/office-native-engine.yml@'+$ref);GITHUB_RUN_ATTEMPT='1';GITHUB_ACTOR='ATLKR';GITHUB_ACTOR_ID='65988341';GITHUB_SHA=$sha;GITHUB_WORKFLOW_SHA=$sha;GITHUB_RUN_ID='123';OPENGEUL_WRITER_SERVER_OBSERVER_BUILD='true';OPENGEUL_CALC_DISPATCH_BUILD='false'}
$event=@{repository=@{full_name='ATLKR/OpenGeul';private=$false;id=1405493151};sender=@{login='ATLKR';id=65988341;type='User'};ref=$ref;deleted=$false;after=$sha}
$binding=@{sourceCommit=$sha;sourceTree=('b'*40);sourceRun=123;runAttempt=1}

Assert-WriterServerObserverOwnerPush $context $event $binding
$checked=0;$accepted=0;$rejected=0
foreach($group in @('context','binding','event')) {
 $keys=switch($group){'context'{@($context.Keys)};'binding'{@('sourceCommit','sourceTree')};'event'{@('repository.full_name','sender.login','sender.type','ref','after')}}
 foreach($key in $keys) {
  $value=switch($group){'context'{$context[$key]};'binding'{$binding[$key]};'event'{$current=$event;foreach($part in $key.Split('.')){$current=$current[$part]};$current}}
  $mutations=[Collections.Generic.List[object]]::new();$mutations.Add([string[]]@($value));$mutations.Add([string[]]@($value,$value));$mutations.Add($null);$mutations.Add($true)
  foreach($mutation in $mutations) {
   $badContext=$context.Clone();$badBinding=$binding.Clone();$badEvent=$event|ConvertTo-Json -Depth 8|ConvertFrom-Json -AsHashtable
   switch($group){'context'{$badContext[$key]=$mutation};'binding'{$badBinding[$key]=$mutation};'event'{$parent=$badEvent;$parts=$key.Split('.');for($i=0;$i -lt $parts.Count-1;$i++){$parent=$parent[$parts[$i]]};$parent[$parts[-1]]=$mutation}}
   $checked++;$denied=$false;try{Assert-WriterServerObserverOwnerPush $badContext $badEvent $badBinding}catch{if($_.Exception -is [Management.Automation.CommandNotFoundException]){throw};$denied=$true}
   if($denied){$rejected++}else{$accepted++}
  }
 }
}
Assert-WriterServerObserverOwnerPush $context $event $binding
[ordered]@{checked=$checked;accepted=$accepted;rejected=$rejected;validScalarAccepted=1}|ConvertTo-Json -Compress
"""))
        self.assertEqual(proof,dict(checked=100,accepted=0,rejected=100,validScalarAccepted=1))

    def test_runtime_marker_and_source_descriptor_reject_coerced_scalar_types(self):
        runtime=self.root/'typed-runtime';(runtime/'program').mkdir(parents=True)
        raw=bytearray(512);raw[:2]=b'MZ';struct.pack_into('<I',raw,60,128);raw[128:132]=b'PE\0\0'
        struct.pack_into('<H',raw,132,0xaa64);struct.pack_into('<H',raw,148,240);struct.pack_into('<H',raw,152,0x20b)
        for name in ('UAccCOM.dll','winaccessibility.dll'):(runtime/'program'/name).write_bytes(raw)
        package=ROOT/'suite/engine-build/writer-server-observer-diagnostic'
        proof="$proof=(Get-Content -LiteralPath "+quote(package/'source-lock.json')+" -Raw|ConvertFrom-Json);$proof|Add-Member -NotePropertyName passed -NotePropertyValue $true;$proof|Add-Member -NotePropertyName target -NotePropertyValue 'windows-arm64';$proof|Add-Member -NotePropertyName lockSha256 -NotePropertyValue "+quote(hashlib.sha256((package/'source-lock.json').read_bytes()).hexdigest())+";$binding=@{sourceCommit=('a'*40);sourceTree=('b'*40);sourceRun=123;runAttempt=1};"
        result=json.loads(self.ps(proof+"$runtime="+quote(runtime)+";\n"+r"""
$marker=Write-WriterServerObserverRuntimeMarker $runtime $binding $proof
$validMarker=$marker|ConvertTo-Json -Depth 12 -Compress;$validSource=$proof|ConvertTo-Json -Depth 12 -Compress;$validBinding=$binding|ConvertTo-Json -Compress
function Clear-FixtureMarkers {
 foreach($name in @('writer-server-observer-diagnostic.json','program/opengeul-writer-server-observer-diagnostic.json')) {Remove-Item -LiteralPath (Join-Path $runtime $name) -ErrorAction SilentlyContinue}
}
Clear-FixtureMarkers
$checked=0;$accepted=0;$rejected=0
foreach($family in @('marker','source','binding')) {
 $keys=if($family -ceq 'marker'){@('schemaVersion','ipcVersion','sinkAbiVersion','descriptorSchemaVersion','mappingBytes','sourceRun','runAttempt','kind','family','sourceCommit','sourceTree','coreCommit','sourceLockSha256','patchSha256','wireSchema.path','wireSchema.bytes','wireSchema.sha256','binaries.0.path','binaries.0.bytes','binaries.0.sha256','binaries.0.machine','binaries.1.path','binaries.1.bytes','binaries.1.sha256','binaries.1.machine','fullEngineQualified','acceptanceEligible','guiVerified')}elseif($family -ceq 'source'){@('schemaVersion','ipcVersion','sinkAbiVersion','descriptorSchemaVersion','mappingBytes','kind','coreCommit','target','lockSha256','patch.path','patch.bytes','patch.sha256','wireSchema.path','wireSchema.bytes','wireSchema.sha256','passed','fullEngineQualified','acceptanceEligible','guiVerified')}else{@('sourceCommit','sourceTree','sourceRun','runAttempt')}
 $template=if($family -ceq 'marker'){$validMarker}elseif($family -ceq 'source'){$validSource}else{$validBinding}
 foreach($key in $keys) {
  $original=$template|ConvertFrom-Json -AsHashtable;$parts=$key.Split('.');$value=$original
  foreach($part in $parts){$value=if($value -is [array]){$value[[int]$part]}else{$value[$part]}}
  $mutations=[Collections.Generic.List[object]]::new();$mutations.Add([object[]]@($value));$mutations.Add([object[]]@($value,$value));$mutations.Add($null)
  $mutations.Add($(if($value -is [bool]){[int]$value}else{$true}))
  if($value -isnot [bool] -and $value -isnot [string]){$mutations.Add([double]$value)}
  foreach($mutation in $mutations) {
   $bad=$template|ConvertFrom-Json -AsHashtable;$node=$bad
   for($i=0;$i -lt $parts.Count-1;$i++){$node=if($node -is [array]){$node[[int]$parts[$i]]}else{$node[$parts[$i]]}}
   $node[$parts[-1]]=$mutation
   $checked++;$denied=$false
   try{if($family -ceq 'marker'){Assert-WriterServerObserverRuntime $runtime $bad}elseif($family -ceq 'source'){Write-WriterServerObserverRuntimeMarker $runtime $binding $bad|Out-Null}else{Write-WriterServerObserverRuntimeMarker $runtime $bad ($validSource|ConvertFrom-Json)|Out-Null}}
   catch{if($_.Exception -is [Management.Automation.CommandNotFoundException]){throw};$denied=$true}
   if($denied){$rejected++}else{$accepted++}
   Clear-FixtureMarkers
  }
 }
}
# Both real helper positives must still admit the exact scalar fixture.
Assert-WriterServerObserverRuntime $runtime ($validMarker|ConvertFrom-Json)
Write-WriterServerObserverRuntimeMarker $runtime $binding ($validSource|ConvertFrom-Json)|Out-Null
[ordered]@{checked=$checked;accepted=$accepted;rejected=$rejected;validScalarAccepted=1}|ConvertTo-Json -Compress
"""))
        self.assertEqual(result,dict(checked=225,accepted=0,rejected=225,validScalarAccepted=1))

    def test_actual_installer_cli_authenticates_both_source_libraries(self):
        package=ROOT/'suite/engine-build/writer-server-observer-diagnostic'
        upstream=package/'tests/upstream'
        self.assertTrue(upstream.is_dir(),'Exact public pinned source fixture is required; no source-free pass')
        source=self.root/'lo';shutil.copytree(upstream,source);(source/'include').mkdir(exist_ok=True)
        repo=self.root/'repo';target=repo/'suite/engine-build/writer-server-observer-diagnostic';target.mkdir(parents=True)
        for name in ('install.py','source-lock.json','source.patch','wire-schema.json','wire.h','atomic.h','descriptor.h','private_sink.hxx','recorder.h','session.h','observer_api.hxx','native.cpp'):
            shutil.copyfile(package/name,target/name)
        evidence=self.root/'evidence';evidence.mkdir()
        lock=ROOT/'suite/engine-build/source-input.lock.json'
        raw=self.ps(f"$env:SystemRoot='/';$script:NativeEngineBuildBudget=New-NativeBuildBudget -MaximumMinutes 1;$pin=Get-SourcePin {quote(lock)};Install-WriterServerObserverSource {quote(source)} {quote(repo)} {quote(sys.executable)} {quote(evidence)} $pin|ConvertTo-Json -Depth 12 -Compress")
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
        package=ROOT/'suite/engine-build/writer-server-observer-diagnostic'
        proof="$proof=(Get-Content -LiteralPath "+quote(package/'source-lock.json')+" -Raw|ConvertFrom-Json);$proof|Add-Member -NotePropertyName passed -NotePropertyValue $true;$proof|Add-Member -NotePropertyName target -NotePropertyValue 'windows-arm64';$proof|Add-Member -NotePropertyName lockSha256 -NotePropertyValue "+quote(hashlib.sha256((package/'source-lock.json').read_bytes()).hexdigest())+";$binding=@{sourceCommit=('a'*40);sourceTree=('b'*40);sourceRun=123;runAttempt=1};"
        self.ps(proof+f"$rejected=$false;try{{Write-WriterServerObserverRuntimeMarker {quote(runtime)} $binding $proof|Out-Null}}catch{{$rejected=$true}};if(-not $rejected){{throw 'One DLL admitted'}}")
        (runtime/'program/winaccessibility.dll').write_bytes(raw)
        self.ps(proof+f"Write-WriterServerObserverRuntimeMarker {quote(runtime)} $binding $proof|Out-Null")
        first=(runtime/'writer-server-observer-diagnostic.json').read_bytes()
        self.assertEqual(first,(runtime/'program/opengeul-writer-server-observer-diagnostic.json').read_bytes())
        marker=json.loads(first);self.assertFalse(marker['acceptanceEligible']);self.assertEqual(len(marker['binaries']),2);self.assertEqual(marker['coreCommit'],'9dea406ab7695df6325b11b0e19fdca8db4b7276');self.assertEqual(marker['sourceRun'],123);self.assertEqual(marker['runAttempt'],1)
        (runtime/'program/UAccCOM.dll').write_bytes(bytes(raw)+b'overlay')
        self.ps(f"$marker=Get-Content -LiteralPath {quote(runtime/'writer-server-observer-diagnostic.json')} -Raw|ConvertFrom-Json;$rejected=$false;try{{Assert-WriterServerObserverRuntime {quote(runtime)} $marker}}catch{{$rejected=$true}};if(-not $rejected){{throw 'Single DLL overlay admitted'}}")

    def test_existing_normal_consumer_rejects_false_qualification_and_diagnostic_kind(self):
        from suite.tests.test_prepare import implementation,source_build_fixture,pin_source_receipt
        with tempfile.TemporaryDirectory() as temporary:
            _,runtime,path,normal=source_build_fixture(Path(temporary))
            module=implementation()
            module.validate_source_build_receipt(runtime,path,architecture='arm64')
            for change in ({'fullEngineQualified':False},
                           {'kind':'native-office-engine-writer-server-observer-diagnostic'},
                           {'status':'native-engine-writer-server-observer-diagnostic-built'}):
                with self.subTest(change=tuple(change)):
                    diagnostic=dict(normal,**change);pin_source_receipt(runtime,path,diagnostic)
                    with self.assertRaisesRegex(ValueError,'does not qualify an authenticated full native ARM64 engine'):
                        module.validate_source_build_receipt(runtime,path,architecture='arm64')

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
$focus=@($commands|Where-Object {{$_.GetCommandName() -ceq 'Install-WriterServerObserverFocusBaseline'}})
$baseline=@($commands|Where-Object {{$_.GetCommandName() -ceq 'Assert-WinAccFocusSourcePatchReceipt'}})
$marker=@($commands|Where-Object {{$_.GetCommandName() -ceq 'Write-WriterServerObserverRuntimeMarker'}})
$archive=@($commands|Where-Object {{$_.GetCommandName() -ceq 'Write-NativeEngineArchive'}})
if($focus.Count -ne 0 -or $baseline.Count -ne 1 -or $baseline[0].Extent.StartOffset -ge $hook[0].Extent.StartOffset -or $admission.Count -ne 1 -or $hook.Count -ne 1 -or $marker.Count -ne 1 -or
 $admission[0].Extent.StartOffset -ge $download[0].Extent.StartOffset -or $hook[0].Extent.StartOffset -ge $configure[0].Extent.StartOffset -or
 $marker[0].Extent.StartOffset -ge $archive[0].Extent.StartOffset){{throw 'Actual writer stage order differs'}}
""")

    def test_closed_installer_child_environment_does_not_inherit_private_synthetic_value(self):
        body="import os;assert 'WRITER_SYNTHETIC_PRIVATE' not in os.environ;print('closed')"
        prefix=self.root/'closed'
        self.ps(f"$env:SystemRoot='/';$env:WRITER_SYNTHETIC_PRIVATE='synthetic-only';$script:NativeEngineBuildBudget=New-NativeBuildBudget -MaximumMinutes 1;$r=Invoke-LoggedCommand {quote(sys.executable)} @('-c',{quote(body)}) {quote(self.root)} {quote(prefix)} -NativeEnvironment;if((Get-Content -LiteralPath $r.stdout -Raw).Trim() -cne 'closed'){{throw 'Child environment differs'}}")

    def test_actual_entry_rejects_context_before_prerequisites_or_download(self):
        # Only external host/Git/tool/network boundaries are synthetic. Execute
        # the real entry, source descriptor, event reader and owner admission.
        event_path=self.root/'event.json'
        self.ps(f"""
$ref='refs/heads/work/opengeul-office-native-writer-observer-9dea';$sha='a'*40
$context=@{{GITHUB_ACTIONS='true';RUNNER_ENVIRONMENT='github-hosted';RUNNER_OS='Windows';RUNNER_ARCH='ARM64';GITHUB_REPOSITORY='ATLKR/OpenGeul';GITHUB_REPOSITORY_OWNER='ATLKR';GITHUB_EVENT_NAME='push';GITHUB_JOB='native-firebird-and-office';GITHUB_REF=$ref;GITHUB_WORKFLOW_REF=('ATLKR/OpenGeul/.github/workflows/office-native-engine.yml@'+$ref);GITHUB_RUN_ATTEMPT='1';GITHUB_ACTOR='ATLKR';GITHUB_ACTOR_ID='65988341';GITHUB_SHA=$sha;GITHUB_WORKFLOW_SHA=$sha;GITHUB_RUN_ID='123';OPENGEUL_WRITER_SERVER_OBSERVER_BUILD='true';OPENGEUL_CALC_DISPATCH_BUILD='false'}}
foreach($key in $context.Keys){{[Environment]::SetEnvironmentVariable($key,$context[$key])}}
$event=@{{repository=@{{full_name='ATLKR/OpenGeul';private=$false;id=1405493151}};sender=@{{login='ATLKR';id=65988341;type='User'}};ref=$ref;deleted=$false;after=$sha}}
$event|ConvertTo-Json -Depth 8|Set-Content -LiteralPath {quote(event_path)} -Encoding utf8NoBOM
$env:GITHUB_EVENT_PATH={quote(event_path)}
function Get-NativeBuildHost {{return @{{isWindows=$true;processMachine=0;nativeMachine=43620}}}}
function Get-SourceRunBinding {{return @{{sourceCommit=('a'*40);sourceTree=('b'*40);sourceRun=123;runAttempt=1}}}}
function Resolve-NativeJdk {{$script:prerequisites++;return @{{}}}}
function Resolve-Ant {{$script:prerequisites++;return @{{}}}}
function Get-AuthenticatedWindowsPkgconf {{$script:downloads++;throw 'Synthetic network boundary; no download'}}
foreach($case in 1,2,3,4) {{
 $script:prerequisites=0;$script:downloads=0;$env:GITHUB_REF=$ref;$env:OPENGEUL_WRITER_SERVER_OBSERVER='';$env:MAKEFLAGS=''
 if($case -eq 2){{$env:GITHUB_REF='refs/heads/work/opengeul-office-native-engine'}}
 if($case -eq 3){{$env:OPENGEUL_WRITER_SERVER_OBSERVER='synthetic-no-capture'}}
 if($case -eq 4){{$env:MAKEFLAGS='synthetic-override'}}
 $work=Join-Path {quote(self.root)} ('work-'+$case);$evidence=Join-Path {quote(self.root)} ('evidence-'+$case)
 try{{Invoke-NativeEngineBuild Full $work $evidence {quote(ROOT/'suite/engine-build/source-input.lock.json')} 4 -WriterServerObserverDiagnostic}}catch{{}}
 $proof=Get-Content -LiteralPath (Join-Path $evidence 'writer-server-observer-source-build-receipt.json') -Raw|ConvertFrom-Json
 if($proof.passed -or $proof.fullEngineQualified -or $proof.acceptanceEligible -or $proof.guiVerified -or $proof.kind -cne 'native-office-engine-writer-server-observer-diagnostic'){{throw 'Failed diagnostic proof differs'}}
 if($case -eq 1){{if($script:prerequisites -ne 2 -or $script:downloads -ne 1 -or $proof.stage -cne 'authenticated-downloads'){{throw 'Valid admission never reached synthetic boundary'}}}}
 elseif($script:prerequisites -ne 0 -or $script:downloads -ne 0 -or $proof.stage -cne 'bind-actual-source-run'){{throw 'Rejected context reached prerequisites/network'}}
 if(Test-Path -LiteralPath (Join-Path $evidence 'source-build-receipt.json')){{throw 'Normal receipt emitted'}}
 if(@(Get-ChildItem -LiteralPath $evidence -Filter '*.zip').Count){{throw 'Failed diagnostic archive retained'}}
}}
""")

    def test_actual_failure_catch_revokes_partial_diagnostic_archive(self):
        archive=self.root/'partial-writer.zip';archive.write_bytes(b'synthetic interrupted packaging sentinel')
        proof=json.loads(self.ps(f"""
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile({quote(DRIVER)},[ref]$tokens,[ref]$errors)
$build=$ast.Find({{param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Invoke-NativeEngineBuild'}},$true)
$outer=$build.Body.Find({{param($n)$n -is [Management.Automation.Language.TryStatementAst]}},$true)
$Architecture='arm64';$WriterServerObserverDiagnostic=$true;$zip={quote(archive)}
$receipt=@{{passed=$true;fullEngineQualified=$false;acceptanceEligible=$false;guiVerified=$false;status='native-engine-writer-server-observer-diagnostic-built'}}
try{{& ([scriptblock]::Create('try {{throw ''Synthetic package failure''}} catch '+$outer.CatchClauses[0].Body.Extent.Text))}}catch{{}}
[ordered]@{{archivePresent=(Test-Path -LiteralPath $zip);passed=$receipt.passed;fullEngineQualified=$receipt.fullEngineQualified;acceptanceEligible=$receipt.acceptanceEligible;guiVerified=$receipt.guiVerified;status=$receipt.status}}|ConvertTo-Json -Compress
"""))
        self.assertEqual(proof,dict(archivePresent=False,passed=False,fullEngineQualified=False,acceptanceEligible=False,guiVerified=False,status='failed'))

    def test_real_partial_build_failure_never_emits_normal_qualified_receipt(self):
        work=self.root/'work';evidence=self.root/'evidence'
        self.ps(f"function Get-NativeBuildHost{{throw 'Synthetic native host rejection'}};try{{Invoke-NativeEngineBuild Full {quote(work)} {quote(evidence)} '' 4 -WriterServerObserverDiagnostic}}catch{{}}")
        proof=json.loads((evidence/'writer-server-observer-source-build-receipt.json').read_text(encoding='utf-8-sig'))
        self.assertEqual('failed',proof['status']);self.assertFalse(proof['passed'])
        self.assertFalse(proof['fullEngineQualified']);self.assertFalse(proof['acceptanceEligible']);self.assertFalse(proof['guiVerified'])
        self.assertFalse((evidence/'source-build-receipt.json').exists());self.assertFalse(list(evidence.glob('*.zip')))


if __name__=='__main__':unittest.main()
