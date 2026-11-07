"""Real file/PE/COFF boundaries for installed Windows Java build tools."""
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile
import unittest
import zipfile

from suite.tests.test_native_engine_build import PWSH, SOURCE, quote
from suite.tests.test_payload import pe


def import_library(machine):
    member = struct.pack('<HHHHIIHH', 0, 0xffff, 0, machine, 0, 8, 0, 0) + b'jvm\0jvm\0'
    header = ('jvm.dll/'.ljust(16) + '0'.ljust(12) + '0'.ljust(6) + '0'.ljust(6)
              + '100644'.ljust(8) + str(len(member)).ljust(10) + '`\n').encode('ascii')
    return b'!<arch>\n' + header + member + (b'\n' if len(member) % 2 else b'')


class NativeJavaPrerequisiteTests(unittest.TestCase):
    def crt_observation_tree(self, count=1):
        vs=self.root/'VS';redist=vs/'VC/Redist/MSVC';redist.mkdir(parents=True)
        for index in range(count):
            family=redist/f'14.44.{35200+index}'/'x64/Microsoft.VC143.CRT';family.mkdir(parents=True)
            (family/'msvcp140.dll').write_bytes(pe(0x8664,dll=True))
        defaults=vs/'VC/Auxiliary/Build';defaults.mkdir(parents=True)
        (defaults/'Microsoft.VCToolsVersion.default.txt').write_text('14.44.35207\n')
        (defaults/'Microsoft.VCToolsRedistVersion.default.txt').write_text('14.44.35200\n')
        return vs

    def crt_failure_case(self, observation='normal'):
        vs=self.crt_observation_tree();compiler=vs/'VC/Tools/MSVC/14.44.35207'
        tools=compiler/'bin/Hostx64/x64';tools.mkdir(parents=True)
        for name in ('cl','link','lib'):(tools/(name+'.exe')).write_bytes(pe(0x8664))
        sdk=self.root/'SDK';version='10.0.26100.0'
        for name in (f'Include/{version}/um/Windows.h',f'Include/{version}/shared/sdkddkver.h',f'Include/{version}/ucrt/stdio.h',
                     f'Lib/{version}/um/x64/kernel32.lib',f'Lib/{version}/ucrt/x64/ucrt.lib'):
            q=sdk/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b'synthetic SDK fixture')
        rc=sdk/f'bin/{version}/x64/rc.exe';rc.parent.mkdir(parents=True);rc.write_bytes(pe(0x8664))
        vswhere=self.root/'Microsoft Visual Studio/Installer/vswhere.exe';vswhere.parent.mkdir(parents=True);vswhere.write_bytes(b'synthetic seam')
        found=self.root/'instances.json';found.write_text(json.dumps([dict(installationPath=str(vs),installationVersion='17.14.1',isComplete=True,isLaunchable=True,isPrerelease=False)]))
        evidence=self.root/'evidence'
        body=f"""
${{env:ProgramFiles(x86)}}={quote(self.root)}
function Assert-NativeEngineEnvironment {{param($Architecture)}}
function Get-NativeBuildHost {{param($Architecture) @{{isWindows=$true;processMachine=0;nativeMachine=34404}}}}
function Get-SourceRunBinding {{@{{sourceCommit=('a'*40);sourceTree=('b'*40)}}}}
function Resolve-NativeJdk {{@{{home='synthetic'}}}};function Resolve-Ant {{@{{home='synthetic'}}}}
function Get-ItemProperty {{@{{InstallationFolder={quote(sdk)};ProductVersion='10.0.26100'}}}}
function Get-NativeCompilerFileVersion($Path) {{if([IO.Path]::GetFileName($Path) -ceq 'cl.exe'){{'19.44.35229.0'}}elseif($Path.EndsWith('.exe')){{'14.44.35229.0'}}else{{'14.44.35200.0'}}}}
$expectedCompiler=Get-NativeCompilerPlan {quote(vs)} '17.14.1' x64
$expectedSdk=Get-NativeSdkPlan {quote(sdk)} '{version}' x64
$script:actualCrt=${{function:Get-AppLocalCrtPlan}}
function Get-AppLocalCrtPlan($CompilerRoot,$Toolset,$Architecture,$ActualCompilerRuntimeFloor) {{
 if($CompilerRoot -cne {quote(compiler)} -or $Toolset -cne 'v143' -or $Architecture -cne 'x64' -or $ActualCompilerRuntimeFloor -cne '14.44.35207.0'){{throw 'CRT selection arguments changed'}}
 foreach($entry in @(@('native-selected-compiler.json',$expectedCompiler),@('native-selected-sdk.json',$expectedSdk))) {{
  $saved=Get-Content -LiteralPath (Join-Path {quote(evidence)} $entry[0]) -Raw|ConvertFrom-Json
  if(-not $saved.diagnosticOnly -or -not $saved.sourceOnly -or $saved.fullEngineQualified){{throw 'Plan was promoted to qualification'}}
  if(($saved.plan|ConvertTo-Json -Depth 30 -Compress) -cne ($entry[1]|ConvertTo-Json -Depth 30 -Compress)){{throw 'Selected plan not preserved before CRT'}}
 }}
 &$script:actualCrt $CompilerRoot $Toolset $Architecture $ActualCompilerRuntimeFloor
}}
function Invoke-LoggedCommand($FilePath,$Arguments,$WorkingDirectory,$LogPrefix,[switch]$NativeEnvironment) {{
 if($FilePath -cne {quote(vswhere)}){{throw 'COMPILER MUST NOT RUN'}}
 @{{stdout={quote(found)};exitCode=0;passed=$true}}
}}
function Get-AuthenticatedDownload {{throw 'DOWNLOAD MUST NOT RUN'}}
$script:actualObservation=${{function:Save-NativeCrtObservation}}
if('{observation}' -ceq 'failure'){{function Save-NativeCrtObservation {{throw 'Synthetic observation failure'}}}}
if('{observation}' -ceq 'expired'){{function Save-NativeCrtObservation($InstallationPath,$OutputPath) {{
 $script:NativeEngineBuildBudget.clock=[pscustomobject]@{{Elapsed=[pscustomobject]@{{TotalMilliseconds=($script:NativeEngineBuildBudget.record.timeoutMilliseconds+1);TotalSeconds=20000}}}}
 &$script:actualObservation $InstallationPath $OutputPath
}}}}
$failed=$false
try{{Invoke-NativeEngineBuild Full {quote(self.root/'work')} {quote(evidence)} '' 4 -Architecture x64}}
catch{{if($_.Exception.Message -notmatch 'No native VC redist.*14.44.35207.0'){{throw}};$failed=$true}}
if(-not $failed){{throw 'CRT rejection was rescued'}}
"""
        self.ps(body)
        self.assertEqual((vs/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt').read_bytes(),
                         (evidence/'native-selected-toolset-version.txt').read_bytes())
        if observation=='failure':
            self.assertFalse((evidence/'native-crt-observation.json').exists())
        else:
            result=json.loads((evidence/'native-crt-observation.json').read_text())
            self.assertTrue(result['diagnosticOnly']);self.assertTrue(result['sourceOnly'])
            self.assertFalse(result['fullEngineQualified']);self.assertFalse(result['selectedForBuild'])
            if observation=='normal':
                self.assertTrue(result['observationCompleted']);row=result['versionDirectories'][0]
                self.assertEqual('14.44.35200',row['directory'])
                present=[f for f in row['files'] if f['exists']]
                self.assertEqual([dict(name='msvcp140.dll',exists=True,fileVersion='14.44.35200.0')],present)
                self.assertEqual(9,len(row['files']))
                self.assertEqual(['14.44.35207','14.44.35200'],[d['version'] for d in result['defaults']])
            else:
                self.assertFalse(result['observationCompleted']);self.assertEqual([],result['versionDirectories'])
        proof=json.loads((evidence/'source-build-receipt.json').read_text())
        for field in ('passed','fullEngineQualified','acceptanceEligible','guiVerified'):self.assertIs(False,proof[field])
        self.assertFalse(list(evidence.glob('*.zip')))

    def test_x64_crt_failure_preserves_exact_selected_plans_before_observation(self):
        self.crt_failure_case()

    def test_x64_crt_observation_failure_preserves_original_rejection(self):
        self.crt_failure_case('failure')

    def test_x64_crt_observation_expiry_preserves_original_rejection(self):
        self.crt_failure_case('expired')

    def test_crt_observation_caps_directories_and_reuses_nine_names_without_selection(self):
        vs=self.crt_observation_tree(17);output=self.root/'observation.json'
        self.ps(f"$script:NativeEngineBuildBudget=New-NativeBuildBudget '' 1; $before=$script:NativeEngineBuildBudget; function Get-NativeCompilerFileVersion {{'14.44.35200.0'}}; Save-NativeCrtObservation {quote(vs)} {quote(output)}; if(-not [object]::ReferenceEquals($before,$script:NativeEngineBuildBudget)){{throw 'Budget reset'}}")
        result=json.loads(output.read_text());self.assertTrue(result['observationCompleted'])
        self.assertEqual(16,len(result['versionDirectories']));self.assertTrue(result['directoryLimitReached'])
        self.assertLessEqual(result['timeoutMilliseconds'],60000)
        names=json.loads(self.ps("@(Get-CrtNames x64)|ConvertTo-Json -Compress"))
        for row in result['versionDirectories']:self.assertEqual(names,[f['name'] for f in row['files']])
        original=output.read_bytes()
        self.rejected(f"Save-NativeCrtObservation {quote(vs)} {quote(output)}")
        self.assertEqual(original,output.read_bytes())

    def test_crt_observation_rejects_linked_and_oversized_or_invalid_default_metadata(self):
        vs=self.crt_observation_tree();path=vs/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'
        for index,raw in enumerate((b'x'*4097,b'not a version')):
            with self.subTest(case=index):
                path.write_bytes(raw);output=self.root/f'bad-{index}.json'
                self.ps(f"function Get-NativeCompilerFileVersion {{'14.44.35200.0'}}; Save-NativeCrtObservation {quote(vs)} {quote(output)}")
                result=json.loads(output.read_text());self.assertFalse(result['observationCompleted'])
                self.assertNotIn(raw.decode(),output.read_text());self.assertFalse(result['fullEngineQualified'])
                self.assertEqual(1,len(result['versionDirectories']))
        path.unlink();target=self.root/'other.txt';target.write_text('14.44.35207')
        path.symlink_to(target);output=self.root/'linked.json'
        self.ps(f"Save-NativeCrtObservation {quote(vs)} {quote(output)}")
        self.assertFalse(json.loads(output.read_text())['observationCompleted'])

    def test_crt_observation_rejects_linked_redist_directory_before_resource_reads(self):
        vs=self.crt_observation_tree();path=vs/'VC/Redist/MSVC/14.44.35200'
        target=self.root/'other-directory';path.rename(target);path.symlink_to(target,target_is_directory=True)
        output=self.root/'linked-directory.json'
        self.ps(f"function Get-NativeCompilerFileVersion {{throw 'MUST NOT READ VERSION'}}; Save-NativeCrtObservation {quote(vs)} {quote(output)}")
        result=json.loads(output.read_text());self.assertFalse(result['observationCompleted'])
        self.assertEqual([],result['versionDirectories'])

    def test_crt_observation_expired_budget_does_not_read_versions(self):
        vs=self.crt_observation_tree();output=self.root/'expired.json'
        self.ps(f"$script:NativeEngineBuildBudget=[pscustomobject]@{{record=@{{timeoutMilliseconds=1}};clock=[pscustomobject]@{{Elapsed=[pscustomobject]@{{TotalMilliseconds=2}}}}}}; function Get-NativeCompilerFileVersion {{throw 'MUST NOT READ VERSION'}}; Save-NativeCrtObservation {quote(vs)} {quote(output)}")
        result=json.loads(output.read_text());self.assertFalse(result['observationCompleted'])
        self.assertEqual([],result['versionDirectories']);self.assertEqual([],result['defaults'])

    def vs_selection_failure(self, count, diagnostic='success'):
        case=self.root/(str(count)+'-'+diagnostic);case.mkdir()
        vswhere=case/'Microsoft Visual Studio/Installer/vswhere.exe'
        vswhere.parent.mkdir(parents=True);vswhere.write_bytes(b'synthetic vswhere seam')
        instance=dict(installationPath=str(case/'VS'),installationVersion='17.14.1',
                      isComplete=True,isLaunchable=True,isPrerelease=False)
        filtered=case/'filtered.json';filtered.write_text(json.dumps([instance]*count))
        unfiltered=case/'installed.json';unfiltered.write_text(json.dumps([instance]))
        evidence=case/'evidence';calls=case/'calls.json'
        body=f"""
${{env:ProgramFiles(x86)}}={quote(case)}
function Assert-NativeEngineEnvironment {{param($Architecture)}}
function Get-NativeBuildHost {{param($Architecture) @{{isWindows=$true;processMachine=0;nativeMachine=34404}}}}
function Get-SourceRunBinding {{@{{sourceCommit=('a'*40);sourceTree=('b'*40)}}}}
function Resolve-NativeJdk {{@{{home='synthetic'}}}}
function Resolve-Ant {{@{{home='synthetic'}}}}
function Get-NativeCompilerPlan {{throw 'COMPILER MUST NOT RUN'}}
function Get-AuthenticatedDownload {{throw 'DOWNLOAD MUST NOT RUN'}}
$script:queries=[Collections.Generic.List[object]]::new();$script:diagnosticChildStarted=$false
function Invoke-LoggedCommand($FilePath,$Arguments,$WorkingDirectory,$LogPrefix,[switch]$NativeEnvironment,[double]$TimeoutMinutes=350) {{
 if(-not $NativeEnvironment -or $FilePath -cne {quote(vswhere)}){{throw 'Unexpected native query'}}
 if($script:queries.Count -eq 0) {{
  $script:queryBudget=$script:NativeEngineBuildBudget;$script:queryRemaining=Get-NativeBuildRemaining
  $script:queries.Add(@{{arguments=@($Arguments);prefix=[IO.Path]::GetFileName($LogPrefix)}})
  if('{diagnostic}' -ceq 'expired'){{$script:queryBudget.clock=[pscustomobject]@{{Elapsed=[pscustomobject]@{{TotalMilliseconds=($script:queryBudget.record.timeoutMilliseconds+1);TotalSeconds=20000}}}}}}
  return @{{stdout={quote(filtered)};exitCode=0;passed=$true}}
 }}
 if(-not [object]::ReferenceEquals($script:queryBudget,$script:NativeEngineBuildBudget) -or (Get-NativeBuildRemaining) -gt $script:queryRemaining){{throw 'Diagnostic reset original budget'}}
 $script:diagnosticChildStarted=$true
 $script:queries.Add(@{{arguments=@($Arguments);prefix=[IO.Path]::GetFileName($LogPrefix);timeoutMinutes=$TimeoutMinutes}})
 if('{diagnostic}' -ceq 'failure'){{throw 'Synthetic diagnostic query failure'}}
 return @{{stdout={quote(unfiltered)};exitCode=0;passed=$true}}
}}
$failed=$false
try {{Invoke-NativeEngineBuild Full {quote(case/'work')} {quote(evidence)} '' 4 -Architecture x64}}
catch {{if($_.Exception.Message -notmatch 'Exactly one complete installed release VS2022 native profile'){{throw}};$failed=$true}}
if(-not $failed){{throw 'Invalid profile produced success'}}
Write-BuildJson {quote(calls)} @{{queries=@($script:queries);diagnosticChildStarted=$script:diagnosticChildStarted}}
"""
        self.ps(body)
        receipt=json.loads((evidence/'source-build-receipt.json').read_text())
        for field in ('passed','fullEngineQualified','acceptanceEligible','guiVerified'):
            self.assertIs(False,receipt[field])
        self.assertEqual('native-toolchain-preflight',receipt['stage'])
        self.assertFalse(list(evidence.glob('*.zip')))
        observed=json.loads(calls.read_text())
        self.assertEqual(['-products','*','-version','[17,18)','-requires',
            'Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-format','json','-utf8'],observed['queries'][0]['arguments'])
        proof=json.loads((evidence/'native-vs-installed-diagnostic.json').read_text())
        self.assertTrue(proof['diagnosticOnly']);self.assertFalse(proof['selectedForBuild'])
        self.assertEqual(count,proof['filteredInstanceCount'])
        return observed,proof

    def test_x64_missing_or_ambiguous_vs_retains_diagnostics_without_selecting_them(self):
        for count in (0,2):
            with self.subTest(count=count):
                observed,proof=self.vs_selection_failure(count)
                self.assertTrue(proof['queryPassed']);self.assertTrue(observed['diagnosticChildStarted'])
                self.assertEqual(2,len(observed['queries']))
                self.assertEqual(['-all','-prerelease','-products','*','-format','json','-utf8'],observed['queries'][1]['arguments'])
                self.assertEqual('native-vs-installed',observed['queries'][1]['prefix'])
                self.assertEqual(1,observed['queries'][1]['timeoutMinutes'])

    def test_x64_failed_vs_diagnostic_preserves_original_profile_rejection(self):
        observed,proof=self.vs_selection_failure(0,'failure')
        self.assertFalse(proof['queryPassed']);self.assertTrue(observed['diagnosticChildStarted'])
        self.assertIn('errorType',proof)

    def test_x64_vs_diagnostic_expiry_cannot_reset_budget_or_start_child(self):
        observed,proof=self.vs_selection_failure(0,'expired')
        self.assertFalse(proof['queryPassed']);self.assertFalse(observed['diagnosticChildStarted'])
        self.assertEqual(1,len(observed['queries']))

    def test_x64_compiler_profile_requires_exact_native_cl_link_and_lib(self):
        root=self.root/'VS';compiler=root/'VC/Tools/MSVC/14.44.35207';tools=compiler/'bin/Hostx64/x64';tools.mkdir(parents=True)
        for name in ('cl','link','lib'): (tools/(name+'.exe')).write_bytes(pe(0x8664))
        metadata=root/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt';metadata.parent.mkdir(parents=True);metadata.write_bytes(b'14.44.35207\r\n')
        version="function Get-NativeCompilerFileVersion($Path) { if([IO.Path]::GetFileName($Path) -ceq 'cl.exe'){'19.44.35229.0'}else{'14.44.35229.0'} }; "
        call=f"Get-NativeCompilerPlan {quote(root)} '17.14.1' -Architecture x64"
        data=json.loads(self.ps(version+call+'|ConvertTo-Json -Depth 12 -Compress'))
        self.assertEqual(str(compiler),data['compilerRoot']);self.assertEqual('14.44.35207.0',data['minimumRuntimeVersion'])
        self.assertEqual('selected-msvc-package-v1',data['runtimeFloorBasis'])
        self.assertEqual(dict(path=str(metadata),size=13,sha256=hashlib.sha256(metadata.read_bytes()).hexdigest(),version='14.44.35207'),data['toolsetMetadata'])
        self.assertEqual('19.44.35229.0',data['tools']['cl']['version'])
        self.assertEqual('14.44.35229.0',data['tools']['link']['version'])
        self.assertEqual(['cl','link','lib'],list(data['tools']))
        for name in ('cl','link','lib'):
            path=tools/(name+'.exe');path.write_bytes(pe(0xaa64));self.rejected(version+call);path.write_bytes(pe(0x8664))
        self.rejected(version+call.replace("'17.14.1'","'18.0.1'"))
        self.rejected(version.replace('19.44.35229.0','19.43.35229.0')+call)
        self.rejected(version.replace('19.44.35229.0','19.44.35206.0')+call)

    def test_x64_package_metadata_is_fixed_bounded_and_rechecked_after_preflight(self):
        root=self.root/'VS';compiler=root/'VC/Tools/MSVC/14.44.35207';tools=compiler/'bin/Hostx64/x64';tools.mkdir(parents=True)
        for name in ('cl','link','lib'):(tools/(name+'.exe')).write_bytes(pe(0x8664))
        metadata=root/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt';metadata.parent.mkdir(parents=True)
        version="function Get-NativeCompilerFileVersion($Path) {if([IO.Path]::GetFileName($Path) -ceq 'cl.exe'){'19.44.35229.0'}else{'14.44.35229.0'}}; "
        call=f"Get-NativeCompilerPlan {quote(root)} '17.14.1' x64"
        self.rejected(version+call)
        for raw in (b'14.44.35206',b'14.43.35207',b'14.44.35207.0',b'14.44.35207\nextra',b'x'*4097):
            metadata.write_bytes(raw);self.rejected(version+call)
        metadata.write_bytes(b'14.44.35207\r\n')
        snapshot=self.root/'compiler.json'
        self.ps(version+f"$plan={call}; Write-BuildJson {quote(snapshot)} $plan; Assert-NativeToolsetMetadata $plan|Out-Null")
        plan=json.loads(snapshot.read_text())
        self.ps(f"Assert-NativeToolsetMetadata (Get-Content {quote(snapshot)} -Raw|ConvertFrom-Json)|Out-Null")
        configured=f"""
function Get-NativeLongPath($Path) {{[IO.Path]::GetFullPath($Path)}}
$compiler=Get-Content {quote(snapshot)} -Raw|ConvertFrom-Json -AsHashtable
$sdk=@{{root={quote(self.root/'SDK')};version='10.0.26100.0'}}
$preflight=@{{passed=$true;architecture='x64';compiler=$compiler;sdk=$sdk}}
$configuration=@{{VCTOOLSET='v143';VCVER='17.14';UCRTVERSION=$sdk.version;WINDOWS_SDK_LIB_SUBDIR=$sdk.version;UCRTSDKDIR=$sdk.root;WINDOWS_SDK_HOME=$sdk.root;CC=$compiler.tools.cl.path;CXX=$compiler.tools.cl.path;MSVC_CXX=$compiler.tools.cl.path}}
Assert-NativeConfiguredToolchain {quote(compiler)} $configuration $preflight|Out-Null
"""
        self.ps(version+configured)
        metadata.write_bytes(b'14.44.35207\n');self.rejected(version+configured)
        metadata.write_bytes(b'14.44.35207\r\n')
        for field,value in [('runtimeFloorBasis','resource-max'),('minimumRuntimeVersion','14.44.35229.0')]:
            changed=dict(plan,**{field:value});snapshot.write_text(json.dumps(changed));self.rejected(f"Assert-NativeToolsetMetadata (Get-Content {quote(snapshot)} -Raw|ConvertFrom-Json)")
        for field,value in [('sha256','0'*64),('path',str(self.root/'foreign/default.txt')),('version','14.44.35206'),('size',12)]:
            changed=dict(plan,toolsetMetadata=dict(plan['toolsetMetadata'],**{field:value}));snapshot.write_text(json.dumps(changed));self.rejected(f"Assert-NativeToolsetMetadata (Get-Content {quote(snapshot)} -Raw|ConvertFrom-Json)")
        snapshot.write_text(json.dumps(plan));metadata.write_bytes(b'14.44.35207\n')
        self.rejected(f"Assert-NativeToolsetMetadata (Get-Content {quote(snapshot)} -Raw|ConvertFrom-Json)")
        metadata.unlink();outside=self.root/'outside.txt';outside.write_bytes(b'14.44.35207');metadata.symlink_to(outside)
        self.rejected(version+call)

    def test_x64_final_qualification_rechecks_package_before_archive(self):
        raw=SOURCE.read_text()
        final=raw.split('function Assert-NativeX64Qualification(',1)[1].split('\nfunction ',1)[0]
        self.assertIn('Assert-NativeToolsetMetadata $Receipt.nativePreflight.compiler|Out-Null',final)
        self.assertLess(final.index('Assert-NativeToolsetMetadata'),final.index('Assert-NativeBuildHost'))
        lifecycle=raw.split('function Invoke-NativeEngineBuild(',1)[1]
        self.assertLess(lifecycle.index('Assert-NativeX64Qualification $receipt $instdir'),lifecycle.index('Write-NativeEngineArchive $instdir $zip $evidence'))

    def test_x64_sdk_requires_complete_selected_headers_libraries_and_native_tools(self):
        root=self.root/'SDK';version='10.0.26100.0'
        for name in ('Include/'+version+'/um/Windows.h','Include/'+version+'/shared/sdkddkver.h','Include/'+version+'/ucrt/stdio.h',
                     'Lib/'+version+'/um/x64/kernel32.lib','Lib/'+version+'/ucrt/x64/ucrt.lib'):
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'owned sdk fixture')
        tool=root/'bin'/version/'x64/rc.exe';tool.parent.mkdir(parents=True);tool.write_bytes(pe(0x8664))
        call=f"Get-NativeSdkPlan {quote(root)} '{version}' -Architecture x64"
        data=json.loads(self.ps(call+'|ConvertTo-Json -Depth 12 -Compress'));self.assertEqual(version,data['version'])
        tool.write_bytes(pe(0xaa64));self.rejected(call);tool.write_bytes(pe(0x8664))
        (root/'Include'/version/'ucrt/stdio.h').unlink();self.rejected(call)

    def test_x64_jdk_requires_native_launchers_jvm_jni_and_metadata(self):
        jdk=self.jdk('x64',0x8664)
        (jdk/'release').write_text('JAVA_VERSION="21.0.12"\nOS_ARCH="amd64"\n')
        data=json.loads(self.ps(f"Get-NativeJdkPlan {quote(jdk)} -Architecture x64|ConvertTo-Json -Depth 12 -Compress"))
        self.assertTrue(all(row['machine']==0x8664 for row in data['nativeFiles']))
        for relative in ('bin/java.exe','bin/javac.exe','bin/server/jvm.dll','bin/jawt.dll','lib/jvm.lib','lib/jawt.lib'):
            with self.subTest(relative=relative):
                path=jdk/relative; original=path.read_bytes()
                path.write_bytes(import_library(0xaa64) if path.suffix=='.lib' else pe(0xaa64,dll=path.suffix=='.dll'))
                self.rejected(f"Get-NativeJdkPlan {quote(jdk)} -Architecture x64")
                path.write_bytes(original)
        (jdk/'release').write_text('JAVA_VERSION="21.0.12"\nOS_ARCH="aarch64"\n')
        self.rejected(f"Get-NativeJdkPlan {quote(jdk)} -Architecture x64")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(strict=True)

    def ps(self, body):
        script = self.root/'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. " + quote(SOURCE) + '\n' + body, encoding='utf-8')
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(script)],
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + '\n' + result.stderr)
        return result.stdout.strip()

    def rejected(self, body):
        self.ps("$rejected=$false; try { " + body + " } catch { if($_.Exception -is [System.Management.Automation.CommandNotFoundException]){throw}; $rejected=$true }; if(-not $rejected){throw 'Invalid prerequisite was accepted'}")

    def jdk(self, name='native jdk', machine=0xaa64):
        root = self.root/name
        for relative in ('bin/java.exe', 'bin/javac.exe', 'bin/server/jvm.dll', 'bin/jawt.dll'):
            path = root/relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(pe(machine, dll=path.suffix == '.dll'))
        for relative in ('lib/jvm.lib', 'lib/jawt.lib'):
            path = root/relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(import_library(machine))
        for relative in ('include/jni.h', 'include/win32/jni_md.h'):
            path = root/relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('/* JNI fixture */')
        (root/'release').write_text('JAVA_VERSION="21.0.12"\nOS_ARCH="aarch64"\nIMPLEMENTOR="Fixture JDK"\n')
        return root

    def ant(self):
        root = self.root/'apache ant'
        (root/'bin').mkdir(parents=True)
        (root/'bin/ant').write_text('#!/bin/sh\nexec java org.apache.tools.ant.Main "$@"\n')
        (root/'lib').mkdir()
        for filename, main in (('ant.jar', 'org/apache/tools/ant/Main.class'),
                               ('ant-launcher.jar', 'org/apache/tools/ant/launch/Launcher.class')):
            with zipfile.ZipFile(root/'lib'/filename, 'w') as jar:
                jar.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\nImplementation-Version: 1.10.18\n')
                jar.writestr(main, bytes.fromhex('cafebabe'))
        return root

    def test_actual_native_jdk_pe_and_jni_import_libraries_are_bound_to_receipt(self):
        jdk = self.jdk()
        data = json.loads(self.ps(f"Get-NativeJdkPlan {quote(jdk)}|ConvertTo-Json -Depth 12 -Compress"))
        self.assertEqual(str(jdk), data['home'])
        self.assertEqual('21.0.12', data['javaVersion'])
        self.assertEqual(4, len(data['nativeFiles']))
        self.assertTrue(all(row['machine'] == 0xaa64 for row in data['nativeFiles']))
        self.assertEqual(2, len(data['importLibraries']))
        self.assertTrue(all(row['machines'] == [0xaa64] for row in data['importLibraries']))
        self.assertEqual(hashlib.sha256((jdk/'release').read_bytes()).hexdigest(), data['releaseSha256'])

    def test_native_launchers_cannot_hide_foreign_jvm_or_import_library(self):
        for relative in ('bin/java.exe', 'bin/javac.exe', 'bin/server/jvm.dll', 'lib/jvm.lib', 'lib/jawt.lib'):
            with self.subTest(relative=relative):
                jdk = self.jdk(relative.replace('/', '-'))
                path = jdk/relative
                path.write_bytes(import_library(0x8664) if path.suffix == '.lib' else pe(0x8664, dll=path.suffix == '.dll'))
                self.rejected(f"Get-NativeJdkPlan {quote(jdk)}")

    def test_missing_jni_and_malformed_import_libraries_fail_closed(self):
        jdk = self.jdk()
        (jdk/'include/win32/jni_md.h').unlink()
        self.rejected(f"Get-NativeJdkPlan {quote(jdk)}")
        (jdk/'include/win32/jni_md.h').write_text('/* JNI */')
        (jdk/'lib/jvm.lib').write_bytes(b'!<arch>\n')
        self.rejected(f"Get-NativeJdkPlan {quote(jdk)}")

    def test_aarch64_environment_home_is_selected_before_foreign_default_home(self):
        native = self.jdk(); foreign = self.jdk('foreign', 0x8664)
        data = json.loads(self.ps(f"$env:JAVA_HOME_21_AARCH64={quote(native)};$env:JAVA_HOME={quote(foreign)}; Resolve-NativeJdk ''|ConvertTo-Json -Depth 12 -Compress"))
        self.assertEqual(str(native), data['home'])
        self.assertEqual('JAVA_HOME_21_AARCH64', data['selection'])
        self.rejected(f"$env:JAVA_HOME_21_AARCH64={quote(native)};Resolve-NativeJdk {quote(foreign)}")

    def test_installed_ant_jars_and_launcher_are_bound_without_product_changes(self):
        ant = self.ant()
        data = json.loads(self.ps(f"Get-AntPlan {quote(ant)}|ConvertTo-Json -Depth 8 -Compress"))
        self.assertEqual(str(ant), data['home'])
        self.assertEqual(2, len(data['jars']))
        self.assertEqual('1.10.18', data['version'])
        self.assertEqual(hashlib.sha256((ant/'lib/ant.jar').read_bytes()).hexdigest(), data['jars'][0]['sha256'])
        (ant/'lib/ant-launcher.jar').write_bytes(b'not a JAR')
        self.rejected(f"Get-AntPlan {quote(ant)}")

    def test_explicit_java_and_ant_homes_reach_single_configure_arguments(self):
        result = json.loads(self.ps("@(Get-ConfigureArguments '/owned/cache' '/cygdrive/c/native jdk' '/cygdrive/c/apache ant')|ConvertTo-Json -Compress"))
        self.assertIn('--with-jdk-home=/cygdrive/c/native jdk', result)
        self.assertIn('--with-ant-home=/cygdrive/c/apache ant', result)
        self.assertNotIn('--without-java', result)
        self.assertNotIn('--disable-odk', result)

    def test_distro_documentation_tools_are_in_the_cygwin_setup_request(self):
        packages = self.ps('Get-CygwinBuildPackages').split(',')
        self.assertIn('doxygen', packages)
        self.assertIn('graphviz', packages)
        self.assertNotIn('ant', packages)
        self.assertNotIn('nasm', packages)

    def nasm_case(self, shell_version='2.16.03', perl_version='2.16.03', resolved='owned'):
        bindir = self.root/'cygwin/bin'; bindir.mkdir(parents=True, exist_ok=True)
        for name in ('nasm.exe', 'perl.exe', 'bash.exe', 'cygpath.exe'):
            (bindir/name).write_bytes(('synthetic Cygwin '+name).encode())
        commands = self.root/'commands'; commands.mkdir(exist_ok=True)
        evidence = self.root/'evidence'; evidence.mkdir(exist_ok=True)
        output = self.root/'probe.stdout'
        nasm = bindir/'nasm.exe' if resolved == 'owned' else self.root/'foreign/nasm.exe'
        output.write_text(f'nasmPath={nasm}\nperlPath={bindir / "perl.exe"}\n'
                          f'shellVersion=NASM version {shell_version}\nperlVersion=NASM version {perl_version}\n')
        receipt = self.root/'probe.command.json'; receipt.write_text('{"passed":true,"exitCode":0}')
        prefix = f"""
function Invoke-CygwinScript($Bash,$Cygpath,$Script,$WorkingDirectory,$LogPrefix) {{
 if($Bash -cne {quote(bindir/'bash.exe')} -or $Cygpath -cne {quote(bindir/'cygpath.exe')} -or
    $WorkingDirectory -cne {quote(self.root)} -or $LogPrefix -cne {quote(evidence/'nasm-prerequisite')} -or
    -not(Test-Path -LiteralPath $Script)){{throw 'Wrong owned Cygwin boundary'}}
 @{{stdout={quote(output)};receipt={quote(receipt)}}}
}}
"""
        call = f'Invoke-CygwinNasmPreflight {quote(bindir/"bash.exe")} {quote(bindir/"cygpath.exe")} {quote(commands)} {quote(self.root)} {quote(evidence)}'
        return bindir, output, prefix, call

    def test_x64_cygwin_dependency_adds_nasm_without_changing_arm_packages(self):
        result = json.loads(self.ps("@{arm=(Get-CygwinBuildPackages arm64);x64=(Get-CygwinBuildPackages x64);default=(Get-CygwinBuildPackages)}|ConvertTo-Json -Compress"))
        original = 'autoconf,automake,make,perl,python3,patch,bison,flex,gperf,unzip,zip,libtool,curl,git,diffutils,which,pkg-config,gcc-g++,gettext-devel,doxygen,graphviz'
        self.assertEqual(original, result['arm'])
        self.assertEqual(original, result['default'])
        self.assertEqual(original+',nasm', result['x64'])

    def test_cygwin_nasm_preflight_binds_owned_tools_and_both_probe_versions(self):
        bindir, _, prefix, call = self.nasm_case()
        result = json.loads(self.ps(prefix+f'$result={call};$result|ConvertTo-Json -Depth 8 -Compress'))
        self.assertEqual('2.16.03', result['version'])
        self.assertEqual(str(bindir/'nasm.exe'), result['nasm']['path'])
        for name in ('nasm', 'perl'):
            self.assertEqual(hashlib.sha256((bindir/(name+'.exe')).read_bytes()).hexdigest(), result[name]['sha256'])
        for flag in ('productPayload', 'fullEngineQualified', 'acceptanceEligible', 'guiVerified'):
            self.assertIs(False, result[flag])
        self.assertTrue((self.root/'evidence/cygwin-nasm-prerequisite.json').is_file())

    def test_cygwin_nasm_rejects_missing_or_wrong_resolved_tool(self):
        bindir, output, prefix, call = self.nasm_case(resolved='foreign')
        self.rejected(prefix+call)
        output.write_text(f'nasmPath={bindir / "nasm.exe"}\nperlPath={bindir / "perl.exe"}\nshellVersion=NASM version 2.16.03\nperlVersion=NASM version 2.16.03\n')
        tool = bindir/'nasm.exe'; tool.unlink()
        self.rejected(prefix+call)

    def test_cygwin_nasm_rejects_linked_tool(self):
        bindir, _, prefix, call = self.nasm_case()
        tool = bindir/'nasm.exe'; raw = tool.read_bytes(); tool.unlink()
        target = self.root/'nasm-target'; target.write_bytes(raw)
        try:
            tool.symlink_to(target)
        except OSError:
            self.skipTest('Host does not permit the symbolic-link fixture')
        self.rejected(prefix+call)

    def test_cygwin_nasm_rejects_unsupported_mismatched_or_malformed_probe(self):
        _, output, prefix, call = self.nasm_case()
        original = output.read_text()
        packets = [original.replace('2.16.03', '2.08'), original.replace('perlVersion=NASM version 2.16.03', 'perlVersion=NASM version 2.15'),
                   original+'extra=synthetic\n', original.replace('shellVersion=NASM version 2.16.03\n', ''),
                   original.replace('shellVersion=NASM version 2.16.03', 'shellVersion=not-nasm')]
        for index, packet in enumerate(packets):
            with self.subTest(case=index):
                output.write_text(packet); self.rejected(prefix+call)

    def test_cygwin_nasm_rejects_probe_time_mutation_and_changed_configuration(self):
        bindir, _, prefix, call = self.nasm_case()
        changed = prefix.replace('@{stdout=', f"[IO.File]::AppendAllText({quote(bindir/'nasm.exe')},'changed');@{{stdout=")
        self.rejected(changed+call)
        (bindir/'nasm.exe').write_bytes(b'synthetic Cygwin nasm.exe')
        self.ps(prefix+f"$p={call};$config=@{{NASM='nasm';PERL={quote(bindir/'perl.exe')}}};Assert-CygwinNasmConfiguration $config $p;"
                "$config.NASM='';$bad=$false;try{Assert-CygwinNasmConfiguration $config $p}catch{$bad=$true};if(-not $bad){throw 'Empty NASM accepted'};"
                f"$config.NASM='nasm';$config.PERL={quote(self.root/'other-perl.exe')};$bad=$false;try{{Assert-CygwinNasmConfiguration $config $p}}catch{{$bad=$true}};if(-not $bad){{throw 'Foreign Perl accepted'}};"
                f"$config.PERL={quote(bindir/'perl.exe')};[IO.File]::AppendAllText({quote(bindir/'perl.exe')},'changed');$bad=$false;try{{Assert-CygwinNasmConfiguration $config $p}}catch{{$bad=$true}};if(-not $bad){{throw 'Changed Perl accepted'}}")

    def test_cygwin_nasm_configuration_accepts_serialized_proof_and_rejects_malformed_flags(self):
        bindir, _, prefix, call = self.nasm_case()
        self.ps(prefix+f"$p={call};$serialized=$p|ConvertTo-Json -Depth 8;$good=$serialized|ConvertFrom-Json;$config=@{{NASM='nasm';PERL={quote(bindir/'perl.exe')}}};Assert-CygwinNasmConfiguration $config $good;"+"""
foreach($pair in @(@('schemaVersion',$true),@('kind','other'),@('passed',1),@('version','2.08'),@('version',@('2.16.03')),@('productPayload',0),@('fullEngineQualified',$true),@('acceptanceEligible',$null),@('guiVerified',$true))) {
 $bad=$serialized|ConvertFrom-Json;$bad.($pair[0])=$pair[1];$rejected=$false
 try{Assert-CygwinNasmConfiguration $config $bad}catch{$rejected=$true}
 if(-not $rejected){throw 'Malformed Cygwin prerequisite proof accepted'}
}
foreach($field in @('size','sha256')) {
 $bad=$serialized|ConvertFrom-Json
 if($field -ceq 'size'){$bad.nasm.size=$true}else{$bad.nasm.sha256=@($bad.nasm.sha256)}
 $rejected=$false;try{Assert-CygwinNasmConfiguration $config $bad}catch{$rejected=$true}
 if(-not $rejected){throw 'Malformed Cygwin file identity accepted'}
}
""")

    def test_driver_binds_installed_java_tools_before_large_source_downloads(self):
        jdk, ant = self.jdk(), self.ant()
        work, output = self.root/'owned-work', self.root/'evidence'
        self.ps("function Assert-NativeEngineEnvironment {param($Architecture)}; function Get-NativeBuildHost { @{isWindows=$true;processMachine=0;nativeMachine=43620} }; "
                "function Get-SourceRunBinding { @{sourceCommit=('a'*40);sourceTree=('b'*40)} }; "
                "function Get-AuthenticatedDownload { throw 'stopped before downloading actual sources' }; "
                f"try {{Invoke-NativeEngineBuild Full {quote(work)} {quote(output)} '' 4 {quote(jdk)} {quote(ant)}}} catch {{}}")
        receipt = json.loads((output/'source-build-receipt.json').read_text())
        self.assertEqual(str(jdk), receipt.get('javaTools', {}).get('jdk', {}).get('home'))
        self.assertEqual(str(ant), receipt.get('javaTools', {}).get('ant', {}).get('home'))
        self.assertEqual('authenticated-downloads', receipt['stage'])
        self.assertFalse(receipt['passed'])
        self.assertIn('stopped before downloading', receipt['error'])

    def test_nonzero_owned_command_emits_bounded_original_failure_tails(self):
        child = self.root/'failed_tool.py'
        child.write_text("import sys\nprint('DISCARDED_STDOUT_PREFIX')\nprint('stdout filler\\n'*1000)\nprint('ORIGINAL_CONFIGURE_STDOUT_CAUSE')\nsys.stderr.write('DISCARDED_STDERR_PREFIX\\n'+'stderr filler\\n'*1000+'ORIGINAL_CONFIGURE_STDERR_CAUSE\\n')\nsys.exit(9)\n")
        prefix = self.root/'failure'
        output = self.ps(f"try {{Invoke-LoggedCommand {quote(os.sys.executable)} @({quote(child)}) {quote(self.root)} {quote(prefix)}}} catch {{}}")
        self.assertIn('ORIGINAL_CONFIGURE_STDOUT_CAUSE', output)
        self.assertIn('ORIGINAL_CONFIGURE_STDERR_CAUSE', output)
        self.assertNotIn('DISCARDED_STDOUT_PREFIX', output)
        self.assertNotIn('DISCARDED_STDERR_PREFIX', output)
        self.assertLess(len(output), 18000)
        receipt = json.loads((self.root/'failure.command.json').read_text())
        self.assertEqual(9, receipt['exitCode'])
        self.assertFalse(receipt['passed'])
        self.assertIn('DISCARDED_STDOUT_PREFIX', (self.root/'failure.stdout.log').read_text())

    @unittest.skipUnless(os.name == 'posix', 'Portable actual bash boundary requires POSIX')
    def test_identity_receipt_runs_only_explicit_user_and_platform_queries(self):
        commands, evidence = self.root/'commands', self.root/'evidence'
        commands.mkdir(); evidence.mkdir()
        raw = self.ps("function Invoke-CygwinScript { param($Bash,$Cygpath,$Script,$WorkingDirectory,$LogPrefix) "
                      "Invoke-LoggedCommand '/bin/bash' @($Script) $WorkingDirectory $LogPrefix }; "
                      f"Get-CygwinIdentity '/bin/bash' '' {quote(commands)} {quote(self.root)} {quote(evidence)}|ConvertTo-Json -Depth 8 -Compress")
        data = json.loads(raw.splitlines()[-1])
        self.assertEqual(str(os.getuid()), data['userId'])
        self.assertEqual(str(os.getgid()), data['groupId'])
        self.assertEqual(platform.machine(), data['machine'])
        self.assertEqual(platform.release(), data['kernelRelease'])
        self.assertTrue(data['operatingSystem'])
        self.assertTrue(data['kernelVersion'])
        script = (commands/'cygwin-identity.sh').read_text()
        self.assertNotIn('env', script)
        self.assertNotIn('whoami', script)
        self.assertIn('/usr/bin/id -u', script)
        self.assertIn('/usr/bin/uname -v', script)
        receipt = json.loads((evidence/'cygwin-identity.command.json').read_text())
        self.assertTrue(receipt['passed'])


if __name__ == '__main__': unittest.main()
