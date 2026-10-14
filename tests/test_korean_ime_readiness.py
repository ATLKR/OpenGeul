"""Preparation policy tests; no Windows capability/profile success is simulated."""
import copy
import importlib.util
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import datetime
import json
import os
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('korean_ime_readiness', ROOT/'scripts/korean_ime_readiness.py')


class KoreanImeReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SPEC is None or SPEC.loader is None or not (ROOT/'scripts/korean_ime_readiness.py').is_file():
            cls.policy=None
            return
        cls.policy = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(cls.policy)

    def setUp(self):
        self.assertIsNotNone(self.policy,'Hosted Korean readiness policy is missing')
        self.head='a'*40
        self.env={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows',
            'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1',
            'GITHUB_JOB':'native-e2e','GITHUB_SHA':self.head,'E2E_ARCHITECTURE':'x64'}
        self.binding={'sourceCommit':self.head,'sourceRun':'123','runAttempt':'1',
            'repository':'ATLKR/OpenGeul','job':'native-e2e','architecture':'x64'}
        clsid='{A028AE76-01B1-46C2-99C4-ACD9858AE02F}'
        guid='{B5FE1F02-D5F2-4445-9C03-C568F23C99A1}'
        tip='0412:'+clsid+guid
        self.record={'formatVersion':1,'source':self.binding,'nativeMachine':0x8664,'controllerMachine':0,
            'systemDirectory':'C:\\Windows\\System32','capabilityName':'Language.Basic~~~ko-KR~0.0.1.0',
            'capabilityBefore':'NotPresent','capabilityAfter':'Installed','restartNeeded':False,
            'userLanguageConfigured':True,'defaultInputTip':tip,'configuredInputTips':[tip],
            'profile':{'inputTip':tip,'providerClsid':clsid,'profileGuid':guid,'languageId':0x0412,
                'registered':True,'registryView':'Registry64','component':{
                    'path':'C:\\Windows\\System32\\IME\\IMEKR\\imkr.dll','bytes':1024,
                    'sha256':'b'*64,'machine':0x8664,'signatureStatus':'Valid',
                    'signerSubject':'CN=Microsoft Windows, O=Microsoft Corporation, C=US'}},
            'profileScope':'current-user configured; target HWND/thread unverified',
            'productInputVerified':False,'sourceQualified':False}

    def test_exact_host_checkout_binding_is_required_before_preparation(self):
        self.assertEqual(self.policy.host_binding(self.env,self.head,self.head,platform='nt'),self.binding)
        for key,value in [('GITHUB_ACTIONS','false'),('RUNNER_ENVIRONMENT','self-hosted'),
                          ('GITHUB_REPOSITORY','other/repo'),('GITHUB_JOB','preflight'),
                          ('GITHUB_RUN_ATTEMPT','2'),('GITHUB_SHA','c'*40),('E2E_ARCHITECTURE','x86')]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.policy.host_binding({**self.env,key:value},self.head,self.head,platform='nt')
        with self.assertRaises(ValueError):self.policy.host_binding(self.env,self.head,'c'*40,platform='nt')
        with self.assertRaises(ValueError):self.policy.host_binding(self.env,self.head,self.head,platform='posix')

    def test_genuine_ready_record_stays_unqualified_for_product_input(self):
        receipt=self.policy.validate_record(self.record,self.binding)
        self.assertFalse(receipt['sourceQualified'])
        self.assertFalse(receipt['productInputVerified'])

    def test_missing_capability_profile_or_required_restart_cannot_pass(self):
        for key,value in [('capabilityAfter','NotPresent'),('capabilityAfter','InstallPending'),
                          ('restartNeeded',True),('userLanguageConfigured',False),
                          ('defaultInputTip','0409:00000409'),('configuredInputTips',[])]:
            row=copy.deepcopy(self.record);row[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.policy.validate_record(row,self.binding)

    def test_native_registry_profile_and_provider_must_match_actual_tip(self):
        for key,value in [('providerClsid','{00000000-0000-0000-0000-000000000000}'),
                          ('profileGuid','{00000000-0000-0000-0000-000000000000}'),
                          ('languageId',0x409),('registered',False),('registryView','Registry32')]:
            row=copy.deepcopy(self.record);row['profile'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.policy.validate_record(row,self.binding)

    def test_foreign_unsigned_or_wrong_native_component_cannot_pass(self):
        for key,value in [('signatureStatus','NotSigned'),('signerSubject','O=Other Vendor'),
                          ('signerSubject','O=Microsoft Corporation Evil'),('machine',0xAA64),
                          ('path','C:\\temp\\imkr.dll'),('path','C:\\Windows\\System32\\..\\temp\\imkr.dll'),
                          ('bytes',0),('sha256','not a hash')]:
            row=copy.deepcopy(self.record);row['profile']['component'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.policy.validate_record(row,self.binding)

    def test_controller_or_configured_profile_cannot_be_labeled_target_success(self):
        for key,value in [('sourceQualified',True),('productInputVerified',True),
                          ('profileScope','actual active app-thread Microsoft profile')]:
            row=copy.deepcopy(self.record);row[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.policy.validate_record(row,self.binding)
        row=copy.deepcopy(self.record);row['source']['sourceCommit']='c'*40
        with self.assertRaises(ValueError):self.policy.validate_record(row,self.binding)

    def test_arm64_requires_native_component_but_allows_explicit_x64_controller(self):
        row=copy.deepcopy(self.record);row['nativeMachine']=0xAA64;row['controllerMachine']=0x8664
        row['source']['job']='native-e2e-arm64';row['source']['architecture']='arm64'
        row['profile']['component']['machine']=0xAA64
        self.policy.validate_record(row,row['source'])
        row['profile']['component']['machine']=0x8664
        with self.assertRaises(ValueError):self.policy.validate_record(row,row['source'])

    def test_impossible_controller_host_pair_and_boolean_format_version_fail(self):
        for key,value in [('controllerMachine',0xAA64),('controllerMachine',0x8664),('formatVersion',True)]:
            row=copy.deepcopy(self.record);row[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.policy.validate_record(row,self.binding)

    def test_setup_guard_precedes_all_host_mutations_and_parent_reports_bounded_progress(self):
        script=(ROOT/'scripts/ensure-korean-ime.ps1').read_text()
        guard=script.index('python $policy --guard')
        for mutation in ('New-Item -ItemType Directory','Add-WindowsCapability','Set-WinUserLanguageList',
                         'Set-WinDefaultInputMethodOverride','Start-Process -FilePath'):
            self.assertLess(guard,script.index(mutation))
        self.assertTrue('$nativeMachine -ne $expectedMachine' in script,'Actual native architecture must be checked before servicing')
        self.assertLess(script.index('$nativeMachine -ne $expectedMachine'),script.index('Add-WindowsCapability'))
        self.assertFalse('WaitForExit(600000)' in script,'One silent ten-minute blocking wait remains')
        self.assertIn('$clock=[Diagnostics.Stopwatch]::StartNew()',script)
        self.assertIn('$child.WaitForExit($waitMs)',script)
        self.assertIn('[Math]::Min(15000,',script)
        self.assertIn('$logBytes -gt 1MB',script)
        self.assertIn('한국어 입력 준비 진행',script)
        self.assertIn('$child.StartTime -eq $started',script)

    def test_actual_worker_hashing_does_not_require_the_missing_file_hash_cmdlet(self):
        self.assertNotIn('Get-FileHash',(ROOT/'scripts/ensure-korean-ime.ps1').read_text())
        powershell=shutil.which('powershell') or shutil.which('pwsh') or '/workspace/OpenGeul-ci-build-progress/.work/powershell746/bin/pwsh'
        if not Path(powershell).is_file():self.skipTest('PowerShell runtime unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            fixtures=[b'', '한글 입력 준비\n'.encode('utf-8'), bytes(range(256))*257]
            for index,raw in enumerate(fixtures):(root/f'{index}.bin').write_bytes(raw)
            script=root/'hash-worker.ps1'
            script.write_text(r'''
param([string]$Source,[string]$FixtureRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'production parse failure'}
$function=$tree.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-OpenGeulFileSha256'},$true)
if($null -eq $function){throw 'module-independent worker hashing is missing'}
function Get-FileHash { throw 'Source112 worker cmdlet is unavailable' }
Invoke-Expression $function.Extent.Text
for($index=0;$index -lt 3;$index++) {
    $path=[IO.Path]::Combine($FixtureRoot,([string]$index+'.bin'))
    $before=Get-OpenGeulFileSha256 $path
    [IO.File]::Move($path,$path+'.moved')
    $after=Get-OpenGeulFileSha256 ($path+'.moved')
    if($before -cne $after){throw 'fresh hash changed without a byte change'}
    [IO.File]::Delete($path+'.moved')
    Write-Output $before
}
$missingRejected=$false
try { Get-OpenGeulFileSha256 ([IO.Path]::Combine($FixtureRoot,'missing.bin')) | Out-Null }
catch { $missingRejected=$true }
if(-not $missingRejected){throw 'missing input did not fail closed'}
$changing=[IO.Path]::Combine($FixtureRoot,'changing.bin')
[IO.File]::WriteAllBytes($changing,[byte[]]@(0,1,2))
$before=Get-OpenGeulFileSha256 $changing
[IO.File]::WriteAllBytes($changing,[byte[]]@(0,1,3))
if($before -ceq (Get-OpenGeulFileSha256 $changing)){throw 'input mutation escaped fresh hashing'}
[IO.File]::Delete($changing)
''',encoding='utf-8')
            result=subprocess.run([str(powershell),'-NoLogo','-NoProfile','-NonInteractive','-File',str(script),
                '-Source',str(ROOT/'scripts/ensure-korean-ime.ps1'),'-FixtureRoot',str(root)],
                capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(result.stdout.splitlines(),[hashlib.sha256(raw).hexdigest() for raw in fixtures])

    def test_actual_builtin_cmdlet_resolution_bypasses_missing_autoload_and_ambient_functions(self):
        powershell=shutil.which('powershell') or shutil.which('pwsh') or '/workspace/OpenGeul-ci-build-progress/.work/powershell746/bin/pwsh'
        if not Path(powershell).is_file():self.skipTest('PowerShell runtime unavailable')
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/'builtin-command.ps1'
            script.write_text(r'''
param([string]$Source)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'production parse failure'}
$resolver=$tree.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-OpenGeulBuiltinCmdlet'},$true)
if($null -eq $resolver){throw 'trusted exported cmdlet resolver missing'}
Invoke-Expression $resolver.Extent.Text
# Exercise the actual generic resolver with a real installed built-in cmdlet.
# Linux has no Authenticode command: this proves resolution, never signatures.
$manifest=[IO.Path]::Combine($PSHOME,'Modules','Microsoft.PowerShell.Utility','Microsoft.PowerShell.Utility.psd1')
Remove-Module Microsoft.PowerShell.Utility -Force -ErrorAction SilentlyContinue
$PSModuleAutoLoadingPreference='None'
$bareUnavailable=$false
try { Get-Date -Date '2026-10-14' | Out-Null } catch { $bareUnavailable=$_.Exception -is [Management.Automation.CommandNotFoundException] }
if(-not $bareUnavailable){throw 'isolated bare command did not reproduce absent autoload'}
function Get-Date { throw 'ambient function must not execute' }
$command=Get-OpenGeulBuiltinCmdlet $manifest 'Microsoft.PowerShell.Utility' 'Get-Date' 'Microsoft.PowerShell.Commands.GetDateCommand' 'Microsoft.PowerShell.Commands.Utility'
if($command -isnot [Management.Automation.CmdletInfo]){throw 'selected command is not real CmdletInfo'}
$date=& $command -Date '2026-10-14T00:00:00'
if($date.Year -ne 2026 -or $date.Month -ne 10 -or $date.Day -ne 14){throw 'actual direct cmdlet invocation failed'}
$rejected=0
foreach($bad in @(
    @($manifest+'.missing','Microsoft.PowerShell.Utility','Get-Date','Microsoft.PowerShell.Commands.GetDateCommand','Microsoft.PowerShell.Commands.Utility'),
    @($manifest,'Microsoft.PowerShell.Security','Get-Date','Microsoft.PowerShell.Commands.GetDateCommand','Microsoft.PowerShell.Commands.Utility'),
    @($manifest,'Microsoft.PowerShell.Utility','Get-AuthenticodeSignature','Microsoft.PowerShell.Commands.GetDateCommand','Microsoft.PowerShell.Commands.Utility'),
    @($manifest,'Microsoft.PowerShell.Utility','Get-Date','Other.ImplementingType','Microsoft.PowerShell.Commands.Utility'),
    @($manifest,'Microsoft.PowerShell.Utility','Get-Date','Microsoft.PowerShell.Commands.GetDateCommand','Other.Assembly')
)) {
    try { Get-OpenGeulBuiltinCmdlet $bad[0] $bad[1] $bad[2] $bad[3] $bad[4] | Out-Null }
    catch { $rejected++ }
}
if($rejected -ne 5){throw 'missing/wrong command or assembly origin was accepted'}
# ConvertTo-Json is now from the same explicitly imported real utility module.
@{passed=$true;bareUnavailable=$bareUnavailable;actualCmdlet=$command.Name;
  module=$command.ModuleName;implementation=$command.ImplementingType.FullName;
  invalidOriginsRejected=$rejected;windowsAuthenticodeQualified=$false;sourceQualified=$false}|ConvertTo-Json -Compress
''',encoding='utf-8')
            result=subprocess.run([str(powershell),'-NoLogo','-NoProfile','-NonInteractive','-File',str(script),
                '-Source',str(ROOT/'scripts/ensure-korean-ime.ps1')],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            import json
            observed=json.loads(result.stdout)
            self.assertTrue(observed['passed'])
            self.assertTrue(observed['bareUnavailable'])
            self.assertEqual(observed['actualCmdlet'],'Get-Date')
            self.assertEqual(observed['module'],'Microsoft.PowerShell.Utility')
            self.assertEqual(observed['implementation'],'Microsoft.PowerShell.Commands.GetDateCommand')
            self.assertEqual(observed['invalidOriginsRejected'],5)
            self.assertFalse(observed['windowsAuthenticodeQualified'])
            self.assertFalse(observed['sourceQualified'])

    def test_signature_call_binds_actual_controller_home_and_exported_cmdlet(self):
        script=(ROOT/'scripts/ensure-korean-ime.ps1').read_text()
        self.assertIn('function Get-OpenGeulAuthenticodeCmdlet',script)
        self.assertIn('[Diagnostics.Process]::GetCurrentProcess()',script)
        self.assertIn("'powershell.exe'",script)
        self.assertIn('$PSHOME',script)
        self.assertIn("'Microsoft.PowerShell.Commands.GetAuthenticodeSignatureCommand'",script)
        self.assertIn('$authenticodeCmdlet=Get-OpenGeulAuthenticodeCmdlet $systemPath',script)
        self.assertIn('$signature=& $authenticodeCmdlet -LiteralPath $component',script)
        self.assertNotIn('$signature=Get-AuthenticodeSignature',script)
        self.assertNotIn('$env:PSModulePath',script)
        self.assertNotIn('.Module.Path -',script)

    def test_actual_controller_resolver_preserves_read_only_home_before_native_guard(self):
        powershell=shutil.which('powershell') or shutil.which('pwsh') or '/workspace/OpenGeul-ci-build-progress/.work/powershell746/bin/pwsh'
        if not Path(powershell).is_file():self.skipTest('PowerShell runtime unavailable')
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/'controller-resolver-home.ps1'
            script.write_text(r'''
param([string]$Source)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'production parse failure'}
$resolver=$tree.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-OpenGeulAuthenticodeCmdlet'},$true)
if($null -eq $resolver){throw 'actual controller resolver missing'}
$homeBefore=[string]$HOME
$homeOptions=(Get-Variable -Name HOME).Options
if(-not ($homeOptions -band [Management.Automation.ScopedItemOptions]::ReadOnly)){throw 'actual HOME is not read-only'}
$process=[Diagnostics.Process]::GetCurrentProcess()
try { $actualExecutable=[IO.Path]::GetFullPath($process.MainModule.FileName) }
finally { $process.Dispose() }
# Invoke the complete production resolver without changing its source, process,
# HOME, PSHOME, or Windows APIs. On this real non-Windows-PowerShell controller,
# the native controller guard must reject before any security module resolution.
if([IO.Path]::GetFileName($actualExecutable) -ieq 'powershell.exe') {
    @{actualWindowsPowerShell=$true;sourceQualified=$false}|ConvertTo-Json -Compress
    exit 77
}
$script:moduleCalls=0
function Get-OpenGeulBuiltinCmdlet {
    $script:moduleCalls++
    throw 'native guard unexpectedly reached module resolution'
}
Invoke-Expression $resolver.Extent.Text
$failure=$null
try { Get-OpenGeulAuthenticodeCmdlet ([IO.Path]::Combine([IO.Path]::GetDirectoryName($actualExecutable),'System32')) | Out-Null }
catch { $failure=$_ }
$homePreserved=([string]$HOME -ceq $homeBefore -and (Get-Variable -Name HOME).Options -eq $homeOptions)
$nativeGuardRejected=($null -ne $failure -and $failure.Exception.Message -ceq 'Actual Windows PowerShell controller home is outside the observed Windows system root.')
$forbiddenWrites=@($resolver.FindAll({param($node)
    if($node -is [Management.Automation.Language.AssignmentStatementAst]) {
        $variable=$node.Left.Find({param($child) $child -is [Management.Automation.Language.VariableExpressionAst]},$true)
        return $null -ne $variable -and @('HOME','PSHOME','CODEX_HOME') -icontains $variable.VariablePath.UserPath
    }
    return $false
},$true)).Count
@{passed=($homePreserved -and $nativeGuardRejected -and $script:moduleCalls -eq 0 -and $forbiddenWrites -eq 0);
  homePreserved=$homePreserved;homeReadOnly=$true;nativeGuardRejected=$nativeGuardRejected;
  forbiddenWrites=$forbiddenWrites;moduleCalls=$script:moduleCalls;
  failureType=if($null -eq $failure){$null}else{$failure.Exception.GetType().FullName};
  actualWindowsPowerShell51=$false;windowsAuthenticodeQualified=$false;sourceQualified=$false}|ConvertTo-Json -Compress
if(-not $homePreserved -or -not $nativeGuardRejected -or $script:moduleCalls -ne 0 -or $forbiddenWrites -ne 0){exit 1}
''',encoding='utf-8')
            result=subprocess.run([str(powershell),'-NoLogo','-NoProfile','-NonInteractive','-File',str(script),
                '-Source',str(ROOT/'scripts/ensure-korean-ime.ps1')],capture_output=True,text=True,timeout=30)
            if result.returncode==77:self.skipTest('This bounded regression requires the actual non-Windows-PowerShell controller')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            import json
            observed=json.loads(result.stdout)
            self.assertTrue(observed['passed'])
            self.assertTrue(observed['homePreserved'])
            self.assertTrue(observed['homeReadOnly'])
            self.assertTrue(observed['nativeGuardRejected'])
            self.assertEqual(observed['forbiddenWrites'],0)
            self.assertEqual(observed['moduleCalls'],0)
            self.assertFalse(observed['actualWindowsPowerShell51'])
            self.assertFalse(observed['windowsAuthenticodeQualified'])
            self.assertFalse(observed['sourceQualified'])

    def test_servicing_observation_bounds_actual_call_and_subsequent_query(self):
        script=(ROOT/'scripts/ensure-korean-ime.ps1').read_text()
        call=script.index('$installed=Add-WindowsCapability')
        query=script.index('$after=@(Get-WindowsCapability')
        self.assertLess(script.index("'install-entry'"),call)
        self.assertLess(call,script.index("'install-return'"))
        self.assertLess(script.index("'after-query-entry'"),query)
        self.assertLess(query,script.index("'after-query-return'"))
        self.assertIn("Save-ObservedJson 'servicing-observation.json'",script)
        self.assertIn('elapsedSeconds=',script)
        self.assertIn('$clock.Elapsed.TotalSeconds -ge 600',script)
        self.assertIn('$child.StartTime -eq $started',script)
        self.assertIn('$json) -gt 32768',script)

    def test_actual_worker_architecture_initializers_resolve_without_newer_type_aliases(self):
        powershell=shutil.which('powershell') or shutil.which('pwsh') or '/workspace/OpenGeul-ci-build-progress/.work/powershell746/bin/pwsh'
        if not Path(powershell).is_file():self.skipTest('PowerShell runtime unavailable')
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/'worker-numeric-types.ps1'
            script.write_text(r'''
param([string]$Source)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
# Remove the newer built-in before parsing: parsing can populate the process
# type cache, which must not accidentally preserve the alias being excluded.
$accelerators=[psobject].Assembly.GetType('System.Management.Automation.TypeAccelerators')
$builtin=$accelerators.GetField('builtinTypeAccelerators',[Reflection.BindingFlags]'NonPublic,Static').GetValue($null)
$null=$builtin.Remove('ushort')
if($builtin.ContainsKey('ushort')){throw 'isolated newer alias was not removed'}
$tokens=$null;$errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'production parse failure'}
$assignments=@($tree.FindAll({param($node)
    if($node -is [Management.Automation.Language.AssignmentStatementAst] -and
       $node.Left -is [Management.Automation.Language.AttributedExpressionAst]) {
        $variable=$node.Left.Find({param($child) $child -is [Management.Automation.Language.VariableExpressionAst]},$true)
        return $null -ne $variable -and @('controllerMachine','nativeMachine') -contains $variable.VariablePath.UserPath
    }
    return $false
},$true) | Sort-Object { $_.Extent.StartOffset })
if($assignments.Count -ne 2){throw 'actual architecture initialization pair missing/duplicated'}
# This fresh child models only the documented older alias absence. It never
# runs the hosted setup script, changes CI identity, or calls Windows APIs.
$declarations=($assignments | ForEach-Object { $_.Extent.Text }) -join ';'
try {
    $types=@(&([scriptblock]::Create($declarations+';$controllerMachine.GetType().FullName;$nativeMachine.GetType().FullName')))
    if($types.Count -ne 2 -or @($types | Where-Object { $_ -cne 'System.UInt16' }).Count -ne 0){throw 'actual interop initialization types differ'}
    @{passed=$true;types=$types;actualWindowsPowerShell51=$false;sourceQualified=$false}|ConvertTo-Json -Compress
} catch {
    @{passed=$false;failureId=$_.FullyQualifiedErrorId;exceptionType=$_.Exception.GetType().FullName;
      hresult=$_.Exception.HResult;actualWindowsPowerShell51=$false;sourceQualified=$false}|ConvertTo-Json -Compress
    exit 1
}
''',encoding='utf-8')
            result=subprocess.run([str(powershell),'-NoLogo','-NoProfile','-NonInteractive','-File',str(script),
                '-Source',str(ROOT/'scripts/ensure-korean-ime.ps1')],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            import json
            observed=json.loads(result.stdout)
            self.assertTrue(observed['passed'])
            self.assertEqual(observed['types'],['System.UInt16','System.UInt16'])
            self.assertFalse(observed['actualWindowsPowerShell51'])
            self.assertFalse(observed['sourceQualified'])

    def diagnostic_api(self,name):
        function=getattr(self.policy,name,None)
        self.assertTrue(callable(function),'Bounded servicing diagnostics are missing: '+name)
        return function

    def assert_diagnostic_gate_counts(self,result,**nonzero):
        expected=dict.fromkeys(('line_too_long','format_unmatched','timestamp_invalid',
            'outside_worker_window','field_marker_mismatch','pid_rejected','session_rejected',
            'ownership_unjoined','hresult_rejected','no_event_fields','record_retained',
            'record_limit_reached'),0)
        expected.update(nonzero)
        self.assertEqual(result.get('gateCounts'),expected)
        for value in result['gateCounts'].values():
            self.assertIs(type(value),int)
            self.assertGreaterEqual(value,0)
            self.assertLessEqual(value,512)
        self.assertLessEqual(sum(result['gateCounts'].values()),result['linesExamined'])
        self.assertFalse(result['sourceQualified'])
        self.assertFalse(result['productInputVerified'])

    def test_diagnostic_gate_counts_distinguish_empty_correlations(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        prefix=stamp.strftime('%Y-%m-%d %H:%M:%S')
        previous=(stamp-datetime.timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
        cases=[('format_unmatched','dism',prefix+', Error DISM unrelated message PID=4452'),
            ('outside_worker_window','dism',previous+', Error DISM PID=4452 HRESULT=0x800F0954'),
            ('pid_rejected','dism',prefix+', Error DISM PID=4453 HRESULT=0x800F0954'),
            ('ownership_unjoined','cbs',prefix+', Error CBS Session: 123_456 HRESULT=0x800F0954'),
            ('no_event_fields','dism',prefix+', Info DISM PID=4452')]
        for gate,kind,line in cases:
            with self.subTest(gate=gate):
                raw=(line+'\n').encode()
                result=parse(raw,kind,4452,start,start+60)
                self.assertEqual(result['status'],'correlation_unavailable')
                self.assertEqual(result['records'],[])
                self.assertEqual(result['sessions'],[])
                self.assert_diagnostic_gate_counts(result,**{gate:1})
                self.assertEqual({key:value for key,value in result.items() if key!='gateCounts'},
                    {'status':'correlation_unavailable','logKind':kind,'bytesRead':len(raw),
                     'tailSha256':hashlib.sha256(raw).hexdigest(),'linesExamined':1,'records':[],
                     'sessions':[],'productInputVerified':False,'sourceQualified':False})

    def test_diagnostic_gate_counts_classify_first_rejection_without_exporting_tokens(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        prefix=stamp.strftime('%Y-%m-%d %H:%M:%S')
        cases=[('line_too_long','x'*4097),
            ('format_unmatched','https://PRIVATE.invalid/PID=4452?HRESULT=0x800FDEAD'),
            ('format_unmatched',prefix+', Error CBS PID=4452 HRESULT=0x800FDEAD'),
            ('format_unmatched',prefix+', Error DISM https://PRIVATE.invalid/PID=4452?HRESULT=0x800FDEAD'),
            ('format_unmatched','2026-13-14 19:24:00, Error DISM unrelated PID=PRIVATE'),
            ('timestamp_invalid','2026-13-14 19:24:00, Error DISM PID=4452 HRESULT=0x800FDEAD'),
            ('timestamp_invalid','2026-13-14 19:24:00, Error DISM PID=PRIVATE Session: PRIVATE HRESULT=PRIVATE'),
            ('outside_worker_window','2026-10-14 19:25:01, Error DISM PID=4452 HRESULT=0x800FDEAD'),
            ('outside_worker_window','2026-10-14 19:25:01, Error DISM PID=PRIVATE Session: PRIVATE HRESULT=PRIVATE'),
            ('field_marker_mismatch',prefix+', Error DISM PID=4452 HRESULT=0x800FDEAD Session:'),
            ('field_marker_mismatch',prefix+', Error DISM PID=4452 Session: 123_456 HRESULT='),
            ('field_marker_mismatch',prefix+', Error DISM Session: 123_456 PID='),
            ('field_marker_mismatch',prefix+', Error DISM PID=PRIVATE Session:'),
            ('pid_rejected',prefix+', Error DISM PID=4452 PID=4453 Session: 123_456'),
            ('pid_rejected',prefix+', Error DISM PID=PRIVATE Session: 123_456'),
            ('pid_rejected',prefix+', Error DISM PID=0 Session: 123_456'),
            ('pid_rejected',prefix+', Error DISM PID=PRIVATE Session: PRIVATE HRESULT=PRIVATE'),
            ('session_rejected',prefix+', Error DISM PID=4452 Session: PRIVATE HRESULT=0x800FDEAD'),
            ('session_rejected',prefix+', Error DISM PID=4452 Session: 123_456 Session: 999_999'),
            ('session_rejected',prefix+', Error DISM Session: PRIVATE HRESULT=PRIVATE'),
            ('ownership_unjoined',prefix+', Error DISM Session: 123_456 HRESULT=0x800FDEAD'),
            ('ownership_unjoined',prefix+', Error DISM Session: 123_456 HRESULT=PRIVATE'),
            ('hresult_rejected',prefix+', Error DISM PID=4452 HRESULT=PRIVATE'),
            ('hresult_rejected',prefix+', Error DISM PID=4452 HRESULT=0x800FDEAD HRESULT=0x80070005')]
        raw=('\n'.join(line for _,line in cases)+'\n').encode()
        result=parse(raw,'dism',4452,start,start+60)
        expected={gate:sum(candidate==gate for candidate,_ in cases) for gate,_ in cases}
        self.assert_diagnostic_gate_counts(result,**expected)
        self.assertEqual(sum(result['gateCounts'].values()),len(cases))
        self.assertEqual(result['linesExamined'],len(cases))
        self.assertEqual(result['status'],'correlation_unavailable')
        self.assertEqual(result['records'],[])
        self.assertEqual(result['sessions'],[])
        encoded=json.dumps(result)
        for forbidden in ('PRIVATE','https','800FDEAD','80070005','4453','123_456','999_999'):
            self.assertNotIn(forbidden,encoded)

    def test_diagnostic_gate_counts_cannot_join_foreign_or_dangling_cbs_fields(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        prefix=stamp.strftime('%Y-%m-%d %H:%M:%S')
        cases=[('pid_rejected','PID=4453 Session: 123_456 HRESULT=0x800FDEAD'),
            ('pid_rejected','PID=0 Session: 123_456 HRESULT=0x800FDEAD'),
            ('field_marker_mismatch','Session: 123_456 HRESULT=0x800FDEAD PID='),
            ('session_rejected','PID=4452 Session: PRIVATE HRESULT=0x800FDEAD'),
            ('ownership_unjoined','Session: 999_999 HRESULT=0x800FDEAD')]
        for gate,body in cases:
            with self.subTest(gate=gate,body=body):
                result=parse((prefix+', Error CBS '+body+'\n').encode(),'cbs',4452,
                    start,start+60,sessions=['123_456'])
                self.assert_diagnostic_gate_counts(result,**{gate:1})
                self.assertEqual(result['status'],'correlation_unavailable')
                self.assertEqual(result['records'],[])
                self.assertEqual(result['sessions'],['123_456'])
                self.assertNotIn('800FDEAD',json.dumps(result))

    def test_diagnostic_gate_counts_preserve_owned_records_sessions_and_original_bytes(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        prefix=stamp.strftime('%Y-%m-%d %H:%M:%S')
        lines=[prefix+', Info CBS PID=4452 Session: 123_456 한글\r\n',
            prefix+', Error CBS Session: 123_456 HRESULT=0x800F0954\r\n']
        raw=b'\xef\xbb\xbf'+''.join(lines).encode()
        result=parse(raw,'cbs',4452,start,start+60)
        self.assert_diagnostic_gate_counts(result,record_retained=2)
        self.assertEqual(result['status'],'available')
        self.assertEqual(result['sessions'],['123_456'])
        expected=[]
        for index,line in enumerate(lines):
            record={'timestamp':prefix,'timestampKind':'source-local-time',
                'eventCode':'session_join' if index==0 else 'hresult','workerPid':4452,
                'lineSha256':hashlib.sha256((b'\xef\xbb\xbf' if index==0 else b'')+line.encode()).hexdigest(),
                'session':'123_456'}
            if index==1:record['hresult']='0x800f0954'
            expected.append(record)
        self.assertEqual(result['records'],expected)
        self.assertEqual(result['tailSha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['bytesRead'],len(raw))
        self.assertEqual(result['linesExamined'],2)
        complete=prefix+', Error DISM PID=4452 HRESULT=0x800F0954 한글\r\n'
        raw=b'x'*65536+b'\n'+complete.encode()+b'PARTIAL'
        result=parse(raw,'dism',4452,start,start+60)
        self.assert_diagnostic_gate_counts(result,record_retained=1)
        self.assertEqual(result['linesExamined'],1)
        self.assertEqual(result['records'],[{'timestamp':prefix,'timestampKind':'source-local-time',
            'eventCode':'hresult','workerPid':4452,'lineSha256':hashlib.sha256(complete.encode()).hexdigest(),
            'hresult':'0x800f0954'}])
        self.assertEqual(result['bytesRead'],65536)
        self.assertEqual(result['tailSha256'],hashlib.sha256(raw[-65536:]).hexdigest())

    def test_diagnostic_gate_counts_preserve_record_limit_break(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        prefix=stamp.strftime('%Y-%m-%d %H:%M:%S')
        line=prefix+', Info DISM PID=4452 Session: 123_456\n'
        result=parse((line*64).encode(),'dism',4452,start,start+60)
        self.assert_diagnostic_gate_counts(result,record_retained=64)
        self.assertEqual(result['status'],'available')
        self.assertEqual(len(result['records']),64)
        sixty_fifth=prefix+', Info DISM PID=4452 Session: 999_999\n'
        result=parse((line*64+sixty_fifth+'UNPROCESSED\n'*5).encode(),'dism',4452,start,start+60)
        self.assert_diagnostic_gate_counts(result,record_retained=64,record_limit_reached=1)
        self.assertEqual(result['status'],'records_truncated')
        self.assertEqual(len(result['records']),64)
        self.assertEqual(result['sessions'],['123_456','999_999'])
        self.assertEqual(result['linesExamined'],70)
        self.assertEqual(sum(result['gateCounts'].values()),65)

    def test_diagnostic_gate_counts_cover_only_complete_bounded_lines(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        for raw,count in [(b'',0),(b'PARTIAL',0),(b'?\r\n'*600+b'PARTIAL',512),
                (b'x'*65536+b'\n?\r\n'*100,199)]:
            with self.subTest(raw_bytes=len(raw)):
                result=parse(raw,'dism',4452,start,start+60)
                self.assert_diagnostic_gate_counts(result,format_unmatched=count)
                self.assertEqual(result['linesExamined'],count)
                self.assertEqual(sum(result['gateCounts'].values()),count)
                self.assertEqual(result['bytesRead'],min(len(raw),65536))
                self.assertEqual(result['tailSha256'],hashlib.sha256(raw[-65536:]).hexdigest())

    def test_diagnostic_gate_counts_stay_zero_when_decoding_is_unavailable(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        for raw in (b'\xff\xff\n',b'\xff\xfe\x00'):
            with self.subTest(raw=raw):
                result=parse(raw,'dism',4452,start,start+60)
                self.assert_diagnostic_gate_counts(result)
                self.assertEqual(result['status'],'encoding_unavailable')
                self.assertEqual(result['linesExamined'],0)
                self.assertEqual(result['records'],[])
                self.assertEqual(result['sessions'],[])

    def test_diagnostic_gate_counts_do_not_raise_existing_json_size_limit(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        prefix=stamp.strftime('%Y-%m-%d %H:%M:%S')
        raw=((prefix+', Error DISM PID=4452 HRESULT=0x800F0954\n')*64).encode()
        result=parse(raw,'dism',4452,start,start+60)
        self.assert_diagnostic_gate_counts(result,record_retained=64)
        encoded_bytes=len(json.dumps(result,separators=(',',':')).encode())
        self.assertEqual(self.policy.DIAGNOSTIC_JSON_BYTES,32768)
        self.assertLessEqual(encoded_bytes,32768)
        with mock.patch.object(self.policy,'DIAGNOSTIC_JSON_BYTES',encoded_bytes-1):
            with self.assertRaisesRegex(ValueError,'^diagnostic_size_unavailable$'):
                parse(raw,'dism',4452,start,start+60)

    def test_diagnostic_trigger_requires_live_owned_worker_and_reserved_parent_budget(self):
        budget=self.diagnostic_api('diagnostic_budget')
        for elapsed,attempted,live,want in [(539.999,False,True,0),(540,False,True,5000),
                (570,False,True,5000),(570.001,False,True,0),(600,False,True,0),
                (540,True,True,0),(540,False,False,0),(float('nan'),False,True,0),
                (float('inf'),False,True,0),(-1,False,True,0)]:
            with self.subTest(elapsed=elapsed,attempted=attempted,live=live):
                self.assertEqual(budget(elapsed,attempted,live),want)

    def test_diagnostic_parser_exports_only_finite_owned_worker_fields(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0)
        start=stamp.timestamp()
        prefix=stamp.strftime('%Y-%m-%d %H:%M:%S')
        raw=('\n'.join([
            prefix+', Error DISM PID=4452 TID=20 HRESULT=0x800F0954 https://secret.invalid/token?secret=VALUE user=private',
            prefix+', Error DISM PID=4453 HRESULT=0x80070005',
            prefix+', Error DISM Language.Basic~~~ko-KR~0.0.1.0 HRESULT=0x80070005',
            '2026-10-13 19:24:00, Error DISM PID=4452 HRESULT=0x80070005',
            prefix+', Info DISM PID=4452 Session: 123_456',
        ])+'\n').encode()
        result=parse(raw,'dism',4452,start,start+60)
        self.assertEqual(len(result['records']),2)
        self.assertEqual(result['records'][0]['hresult'],'0x800f0954')
        self.assertEqual(result['sessions'],['123_456'])
        encoded=json.dumps(result,sort_keys=True)
        for forbidden in ['https','secret.invalid','VALUE','private','TID=','Language.Basic','4453']:
            self.assertNotIn(forbidden,encoded)
        self.assertFalse(result['sourceQualified'])
        self.assertFalse(result['productInputVerified'])

    def test_cbs_correlation_requires_explicit_owned_pid_session_join(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        prefix=stamp.strftime('%Y-%m-%d %H:%M:%S')
        raw=('\n'.join([
            prefix+', Error CBS Session: 123_456 HRESULT=0x800F0954',
            prefix+', Error CBS Session: 999_999 HRESULT=0x80070005',
            prefix+', Error CBS PID=4453 Session: 123_456 HRESULT=0x80070005',
        ])+'\n').encode()
        unbound=parse(raw,'cbs',4452,start,start+60)
        self.assertEqual(unbound['status'],'correlation_unavailable')
        self.assertEqual(unbound['records'],[])
        bound=parse(raw,'cbs',4452,start,start+60,sessions=['123_456'])
        self.assertEqual(len(bound['records']),1)
        self.assertEqual(bound['records'][0]['session'],'123_456')
        self.assertEqual(bound['records'][0]['hresult'],'0x800f0954')

    def test_diagnostic_tail_and_projection_bounds_are_finite(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        line=stamp.strftime('%Y-%m-%d %H:%M:%S')+', Error DISM PID=4452 HRESULT=0x800F0954\n'
        result=parse(line.encode()*1200,'dism',4452,start,start+60)
        self.assertLessEqual(result['bytesRead'],65536)
        self.assertLessEqual(result['linesExamined'],512)
        self.assertLessEqual(len(result['records']),64)
        self.assertLessEqual(len(json.dumps(result).encode()),32768)
        self.assertEqual(parse(b'\xff\xff\n','dism',4452,start,start+60)['status'],'encoding_unavailable')

    def test_diagnostic_line_hash_binds_original_utf8_and_utf16_bytes(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        line=stamp.strftime('%Y-%m-%d %H:%M:%S')+', Error DISM PID=4452 HRESULT=0x800F0954\r\n'
        for encoding in ['utf-8','utf-16']:
            raw=line.encode(encoding)
            with self.subTest(encoding=encoding):
                result=parse(raw,'dism',4452,start,start+60)
                self.assertEqual(result['records'][0]['lineSha256'],hashlib.sha256(raw).hexdigest())

    def test_diagnostic_attribution_rejects_precreation_url_ambiguous_and_invalid_pid(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        prefix=stamp.strftime('%Y-%m-%d %H:%M:%S')
        previous=(stamp-datetime.timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
        cases=[('dism',previous+', Error DISM PID=4452 HRESULT=0x800F0954',[]),
               ('dism',prefix+', Error DISM https://example.invalid/PID=4452?HRESULT=0x800F0954',[]),
               ('dism',prefix+', Error DISM PID=4452 Session: 123_456 Session: 999_999 HRESULT=0x800F0954',[]),
               ('cbs',prefix+', Error CBS PID=0 Session: 123_456 HRESULT=0x800F0954',['123_456'])]
        for kind,line,sessions in cases:
            with self.subTest(kind=kind,line=line):
                result=parse((line+'\n').encode(),kind,4452,start,start+60,sessions=sessions)
                self.assertEqual(result['status'],'correlation_unavailable')
                self.assertEqual(result['records'],[])

    def test_diagnostic_attribution_rejects_dangling_fields_and_unknown_message_shapes(self):
        parse=self.diagnostic_api('parse_diagnostic_tail')
        stamp=datetime.datetime(2026,10,14,19,24,0);start=stamp.timestamp()
        prefix=stamp.strftime('%Y-%m-%d %H:%M:%S')
        cases=[('cbs',prefix+', Error CBS Session: 123_456 HRESULT=0x800F0954 PID=', ['123_456']),
               ('dism',prefix+', Error DISM PID=4452 HRESULT=0x800F0954 Session:', []),
               ('dism',prefix+', Error DISM PID=4452 Session: 123_456 HRESULT=', []),
               ('cbs',prefix+', Error CBS unrelated message mentions PID=4452 HRESULT=0x800F0954', [])]
        for kind,line,sessions in cases:
            with self.subTest(kind=kind,line=line):
                result=parse((line+'\n').encode(),kind,4452,start,start+60,sessions=sessions)
                self.assertEqual(result['status'],'correlation_unavailable')
                self.assertEqual(result['records'],[])

    def test_diagnostic_context_pid_and_creation_are_exact_integers(self):
        validate=self.diagnostic_api('validate_diagnostic_context')
        host={'source':self.binding,'workerPid':1,'scriptSha256':'a'*64,
              'systemDirectory':'C:\\Windows\\System32','productInputVerified':False,'sourceQualified':False}
        observed={'source':self.binding,'workerPid':1,'scriptSha256':'a'*64,'stage':'install-entry','elapsedSeconds':0}
        worker={'pid':1,'createdFiletime':1,'running':True}
        for target,key in [('host','workerPid'),('observed','workerPid'),('worker','pid'),('worker','createdFiletime')]:
            rows={'host':copy.deepcopy(host),'observed':copy.deepcopy(observed),'worker':copy.deepcopy(worker)}
            rows[target][key]=True
            with self.subTest(target=target,key=key),self.assertRaises(ValueError):
                validate(rows['host'],rows['observed'],self.binding,1,1,'a'*64,rows['worker'])

    def test_actual_read_only_tail_rejects_symlink_missing_and_rotated_input(self):
        read=self.diagnostic_api('read_diagnostic_tail')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'dism.log';raw=b'header\n'+b'line\n'*15000
            path.write_bytes(raw);before=path.read_bytes()
            result=read(path)
            self.assertEqual(result['raw'],raw[-65536:])
            self.assertEqual(result['offset'],len(raw)-65536)
            self.assertEqual(path.read_bytes(),before)
            with self.assertRaises(ValueError):read(root/'missing.log')
            with mock.patch.object(self.policy,'_open_read_only_log',side_effect=PermissionError):
                with self.assertRaises(ValueError):read(path)
            if os.name!='nt':
                (root/'link.log').symlink_to(path)
                with self.assertRaises(ValueError):read(root/'link.log')
            real_fstat=os.fstat;calls=0
            def shrunk(fd):
                nonlocal calls
                calls+=1;actual=real_fstat(fd)
                if calls>1:
                    values=list(actual);values[6]=0
                    return os.stat_result(values)
                return actual
            with mock.patch.object(self.policy.os,'fstat',side_effect=shrunk):
                with self.assertRaises(ValueError):read(path)

    def test_diagnostic_context_rejects_stale_pid_creation_source_and_helper(self):
        validate=self.diagnostic_api('validate_diagnostic_context')
        host={'source':self.binding,'workerPid':4452,'scriptSha256':'a'*64,
              'systemDirectory':'C:\\Windows\\System32','productInputVerified':False,'sourceQualified':False}
        observed={'source':self.binding,'workerPid':4452,'scriptSha256':'a'*64,'stage':'install-entry','elapsedSeconds':0}
        worker={'pid':4452,'createdFiletime':133000000000000000,'running':True}
        validate(host,observed,self.binding,4452,133000000000000000,'a'*64,worker)
        for target,key,value in [('worker','createdFiletime',133000000000000001),('worker','pid',4453),
                ('worker','running',False),('host','scriptSha256','b'*64),('observed','stage','install-return'),
                ('observed','source',{**self.binding,'sourceRun':'124'}),('host','sourceQualified',True)]:
            rows={'host':copy.deepcopy(host),'observed':copy.deepcopy(observed),'worker':copy.deepcopy(worker)}
            rows[target][key]=value
            with self.subTest(target=target,key=key),self.assertRaises(ValueError):
                validate(rows['host'],rows['observed'],self.binding,4452,133000000000000000,'a'*64,rows['worker'])

    def test_actual_powershell_diagnostic_child_deadline_and_parent_budget(self):
        source=(ROOT/'scripts/ensure-korean-ime.ps1').read_text()
        self.assertIn('function Get-OpenGeulDiagnosticBudget',source,'Actual parent diagnostic budget function missing')
        self.assertIn('function Invoke-OpenGeulBoundedDiagnosticChild',source,'Actual owned collector lifetime function missing')
        powershell=shutil.which('pwsh') or '/workspace/OpenGeul-ci-build-progress/.work/powershell746/bin/pwsh'
        if not Path(powershell).is_file():self.skipTest('PowerShell runtime unavailable')
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/'diagnostic-parent-budget.ps1'
            script.write_text(r'''
param([string]$Source,[string]$Python)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'production parse failure'}
foreach($name in @('Get-OpenGeulDiagnosticBudget','Invoke-OpenGeulBoundedDiagnosticChild')) {
    $function=$tree.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if($null -eq $function){throw 'production diagnostic parent function missing'}
    Invoke-Expression $function.Extent.Text
}
foreach($case in @(@(539.999,$false,$true,0),@(540,$false,$true,5000),@(570,$false,$true,5000),
                   @(570.001,$false,$true,0),@(600,$false,$true,0),@(540,$true,$true,0),@(540,$false,$false,0))) {
    if((Get-OpenGeulDiagnosticBudget $case[0] $case[1] $case[2]) -ne $case[3]){throw 'parent remaining budget changed'}
}
$startInfo=[Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName=$Python
$startInfo.Arguments='-c "import time;time.sleep(2)"'
$clock=[Diagnostics.Stopwatch]::StartNew()
$result=Invoke-OpenGeulBoundedDiagnosticChild $startInfo 150
if($result.status -cne 'collector_timeout' -or $clock.Elapsed.TotalSeconds -ge 1.5){throw 'actual owned collector was not bounded'}
$startInfo=[Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName=$Python
$startInfo.Arguments='-c "import sys;sys.exit(7)"'
$result=Invoke-OpenGeulBoundedDiagnosticChild $startInfo 1000
if($result.status -cne 'collector_exit_nonzero' -or $result.exitCode -ne 7){throw 'collector failure changed setup semantics'}
@{passed=$true;actualWindowsServicing=$false;sourceQualified=$false}|ConvertTo-Json -Compress
''',encoding='utf-8')
            result=subprocess.run([str(powershell),'-NoLogo','-NoProfile','-NonInteractive','-File',str(script),
                '-Source',str(ROOT/'scripts/ensure-korean-ime.ps1'),'-Python',sys.executable],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            observed=json.loads(result.stdout)
            self.assertTrue(observed['passed'])
            self.assertFalse(observed['actualWindowsServicing'])
            self.assertFalse(observed['sourceQualified'])


    def _actual_language_projection(self,cases):
        powershell=shutil.which('pwsh') or '/workspace/OpenGeul-ci-build-progress/.work/powershell746/bin/pwsh'
        if not Path(powershell).is_file():self.skipTest('PowerShell runtime unavailable')
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/'language-projection.ps1'
            script.write_text(r'''
param([string]$Source)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
class OpenGeulLanguageProjectionTestShape {
    [object]$LanguageTag
    [Collections.Generic.List[string]]$InputMethodTips
    OpenGeulLanguageProjectionTestShape([object]$Tag,[string]$Tip) {
        $this.LanguageTag=$Tag
        $this.InputMethodTips=[Collections.Generic.List[string]]::new()
        if($Tip){$this.InputMethodTips.Add($Tip)}
    }
}
$tokens=$null;$errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'production parse failure'}
$predicate=$tree.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-OpenGeulKoreanLanguageTag'},$true)
if($null -ne $predicate){Invoke-Expression $predicate.Extent.Text}
$preselection=$tree.FindAll({param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left -is [Management.Automation.Language.VariableExpressionAst] -and $node.Left.VariablePath.UserPath -eq 'korean'},$true)
$set=$tree.Find({param($node) $node -is [Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Set-WinUserLanguageList'},$true)
$projection=$tree.Find({param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left -is [Management.Automation.Language.VariableExpressionAst] -and $node.Left.VariablePath.UserPath -eq 'observedTips'},$true)
$postselection=$tree.Find({param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left -is [Management.Automation.Language.VariableExpressionAst] -and $node.Left.VariablePath.UserPath -eq 'observedKorean'},$true)
$generation=$tree.Find({param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left -is [Management.Automation.Language.VariableExpressionAst] -and $node.Left.VariablePath.UserPath -eq 'generated'},$true)
$registry=$tree.Find({param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left -is [Management.Automation.Language.VariableExpressionAst] -and $node.Left.VariablePath.UserPath -eq 'registry'},$true)
if($preselection.Count -ne 2 -or $null -eq $set -or $null -eq $projection -or $null -eq $generation -or $null -eq $registry){throw 'actual production language boundaries missing'}
$sourceText=$tree.Extent.Text
$generatedGuardText=$sourceText.Substring($generation.Extent.EndOffset,$registry.Extent.StartOffset-$generation.Extent.EndOffset)
$configureText=$sourceText.Substring($preselection[0].Extent.StartOffset,$set.Extent.StartOffset-$preselection[0].Extent.StartOffset)
$projectionStart=if($null -eq $postselection){$projection.Extent.StartOffset}else{$postselection.Extent.StartOffset}
$projectionText=$sourceText.Substring($projectionStart,$projection.Extent.EndOffset-$projectionStart)
$selectedTip='0412:{A028AE76-01B1-46C2-99C4-ACD9858AE02F}{B5FE1F02-D5F2-4445-9C03-C568F23C99A1}'
function Invoke-ActualLanguageProjection([object]$List,[bool]$Configure=$false,[object]$GeneratedList=$null) {
    $languages=$List;$observedLanguages=$List;$generated=$GeneratedList
    $profile=@{inputTip=$selectedTip};$korean=@();$observedTips=@()
    $completed=$false;$failure=$null;$candidateCount=$null
    try {
        if($Configure){Invoke-Expression $generatedGuardText}
        Invoke-Expression $preselection[0].Extent.Text
        $candidateCount=$korean.Count
        if($Configure){Invoke-Expression $configureText}
        Invoke-Expression $projectionText
        $completed=$true
    } catch {$failure=$_.Exception.Message}
    return @{completed=$completed;failure=$failure;tips=@($observedTips);candidateCount=$candidateCount;
        languageCount=$List.Count;otherTips=@($List[0].InputMethodTips)}
}
$results=@()
'''+cases+r'''
@{results=$results;actualProductionAst=$true;representativeTypedShapesOnly=$true;
  actualWindowsCmdletsInvoked=$false;actualWindowsInternationalAssembly=$false;
  productInputVerified=$false;sourceQualified=$false}|ConvertTo-Json -Depth 12 -Compress
''',encoding='utf-8')
            result=subprocess.run([str(powershell),'-NoLogo','-NoProfile','-NonInteractive','-File',str(script),
                '-Source',str(ROOT/'scripts/ensure-korean-ime.ps1')],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            observed=json.loads(result.stdout)
            self.assertTrue(observed['actualProductionAst'])
            self.assertTrue(observed['representativeTypedShapesOnly'])
            self.assertFalse(observed['actualWindowsCmdletsInvoked'])
            self.assertFalse(observed['actualWindowsInternationalAssembly'])
            self.assertFalse(observed['productInputVerified'])
            self.assertFalse(observed['sourceQualified'])
            return observed['results']

    def test_actual_language_projection_accepts_exact_regional_and_neutral_tags(self):
        rows=self._actual_language_projection(r'''
foreach($tag in @('ko-KR','kO-kR','KO-kr','ko','KO','kO')) {
    $list=[Collections.Generic.List[OpenGeulLanguageProjectionTestShape]]::new()
    $list.Add([OpenGeulLanguageProjectionTestShape]::new('en-US','0409:00000409'))
    $list.Add([OpenGeulLanguageProjectionTestShape]::new($tag,$selectedTip))
    $results+=,@{tag=$tag;projection=(Invoke-ActualLanguageProjection $list)}
}
''')
        self.assertEqual(len(rows),6)
        for row in rows:
            with self.subTest(tag=row['tag']):
                projection=row['projection']
                self.assertTrue(projection['completed'],projection['failure'])
                self.assertEqual(projection['tips'],[self.record['profile']['inputTip']])
                self.assertEqual(projection['candidateCount'],1)
                self.assertEqual(projection['languageCount'],2)
                record=copy.deepcopy(self.record);record['configuredInputTips']=projection['tips']
                self.assertEqual(self.policy.validate_record(record,self.binding),record)

    def test_actual_language_projection_rejects_unapproved_tags_with_the_selected_tip(self):
        rows=self._actual_language_projection(r'''
$tags=@('en-US','ko-KP','ko-x',$null,'',' ko','ko ','ko-KR ',('ko'+[char]10),('ko-KR'+[char]13+[char]10),[cultureinfo]::GetCultureInfo('ko-KR'))
for($index=0;$index -lt $tags.Count;$index++) {
    $list=[Collections.Generic.List[OpenGeulLanguageProjectionTestShape]]::new()
    $list.Add([OpenGeulLanguageProjectionTestShape]::new('en-US','0409:00000409'))
    $list.Add([OpenGeulLanguageProjectionTestShape]::new($tags[$index],$selectedTip))
    $results+=,@{case=$index;projection=(Invoke-ActualLanguageProjection $list)}
}
''')
        self.assertEqual(len(rows),11)
        for row in rows:
            with self.subTest(case=row['case']):
                self.assertFalse(row['projection']['completed'])
                self.assertEqual(row['projection']['tips'],[])
                self.assertEqual(row['projection']['languageCount'],2)

    def test_actual_language_projection_preserves_raw_tips_for_exact_policy_rejection(self):
        rows=self._actual_language_projection(r'''
foreach($tag in @('ko-KR','ko')) {
    $tips=@('', '0409:00000409',$selectedTip.Substring(0,$selectedTip.Length-1),$selectedTip.ToLowerInvariant(),$selectedTip.Replace('A028AE76','00000000'))
    for($index=0;$index -lt $tips.Count;$index++) {
        $list=[Collections.Generic.List[OpenGeulLanguageProjectionTestShape]]::new()
        $list.Add([OpenGeulLanguageProjectionTestShape]::new('en-US',$selectedTip))
        $list.Add([OpenGeulLanguageProjectionTestShape]::new($tag,$tips[$index]))
        $results+=,@{tag=$tag;case=$index;rawTip=$tips[$index];projection=(Invoke-ActualLanguageProjection $list)}
    }
}
''')
        self.assertEqual(len(rows),10)
        for row in rows:
            with self.subTest(tag=row['tag'],case=row['case']):
                projection=row['projection']
                self.assertTrue(projection['completed'],projection['failure'])
                self.assertEqual(projection['candidateCount'],1)
                self.assertEqual(projection['tips'],[row['rawTip']] if row['rawTip'] else [])
                record=copy.deepcopy(self.record);record['configuredInputTips']=projection['tips']
                with self.assertRaises(ValueError):self.policy.validate_record(record,self.binding)

    def test_actual_language_union_rejects_duplicate_and_mixed_entries_before_tip_projection(self):
        rows=self._actual_language_projection(r'''
foreach($tags in @(@('ko','ko'),@('ko-KR','ko-KR'),@('ko','ko-KR'))) {
    foreach($configure in @($false,$true)) {
        $list=[Collections.Generic.List[OpenGeulLanguageProjectionTestShape]]::new()
        $list.Add([OpenGeulLanguageProjectionTestShape]::new('en-US','0409:00000409'))
        $list.Add([OpenGeulLanguageProjectionTestShape]::new($tags[0],$selectedTip))
        # Ambiguity is about language objects even when only one has the TIP.
        $list.Add([OpenGeulLanguageProjectionTestShape]::new($tags[1],'0409:00000409'))
        $generated=@([OpenGeulLanguageProjectionTestShape]::new('ko-KR',$selectedTip))
        $results+=,@{tags=$tags;configure=$configure;projection=(Invoke-ActualLanguageProjection $list $configure $generated);
            secondTips=@($list[2].InputMethodTips)}
    }
}
''')
        self.assertEqual(len(rows),6)
        for row in rows:
            with self.subTest(tags=row['tags'],configure=row['configure']):
                self.assertFalse(row['projection']['completed'])
                self.assertEqual(row['projection']['tips'],[])
                self.assertEqual(row['projection']['languageCount'],3)
                self.assertEqual(row['secondTips'],['0409:00000409'])

    def test_actual_language_configuration_uses_existing_single_allowed_object(self):
        rows=self._actual_language_projection(r'''
foreach($tag in @('ko-KR','kO-kR','ko','KO')) {
    $list=[Collections.Generic.List[OpenGeulLanguageProjectionTestShape]]::new()
    $list.Add([OpenGeulLanguageProjectionTestShape]::new('en-US',$selectedTip))
    $existing=[OpenGeulLanguageProjectionTestShape]::new($tag,'0409:00000409')
    $list.Add($existing)
    $generated=@([OpenGeulLanguageProjectionTestShape]::new('ko-KR',$selectedTip))
    $projection=Invoke-ActualLanguageProjection $list $true $generated
    $results+=,@{tag=$tag;projection=$projection;sameObject=[object]::ReferenceEquals($existing,$list[1]);
        existingTips=@($existing.InputMethodTips);generatedTips=@($generated[0].InputMethodTips)}
}
''')
        self.assertEqual(len(rows),4)
        for row in rows:
            with self.subTest(tag=row['tag']):
                self.assertTrue(row['projection']['completed'],row['projection']['failure'])
                self.assertEqual(row['projection']['languageCount'],2)
                self.assertTrue(row['sameObject'])
                self.assertEqual(row['projection']['tips'],['0409:00000409',self.record['profile']['inputTip']])
                self.assertEqual(row['existingTips'],row['projection']['tips'])
                self.assertEqual(row['projection']['otherTips'],[self.record['profile']['inputTip']])
                self.assertEqual(row['generatedTips'],[self.record['profile']['inputTip']])

    def test_actual_language_configuration_validates_generated_tag_before_adding(self):
        rows=self._actual_language_projection(r'''
$tags=@('ko-KR','KO-kr','ko','KO','en-US','ko-KP','ko-x',$null,' ko',('ko'+[char]10),[cultureinfo]::GetCultureInfo('ko-KR'))
for($index=0;$index -lt $tags.Count;$index++) {
    foreach($existingTag in @('absent','ko','ko-KR')) {
        $list=[Collections.Generic.List[OpenGeulLanguageProjectionTestShape]]::new()
        $list.Add([OpenGeulLanguageProjectionTestShape]::new('en-US','0409:00000409'))
        if($existingTag -ne 'absent'){$list.Add([OpenGeulLanguageProjectionTestShape]::new($existingTag,$selectedTip))}
        $candidate=[OpenGeulLanguageProjectionTestShape]::new($tags[$index],$selectedTip)
        $projection=Invoke-ActualLanguageProjection $list $true @($candidate)
        $results+=,@{case=$index;existingTag=$existingTag;projection=$projection;addedActualObject=$list.Contains($candidate)}
    }
}
''')
        self.assertEqual(len(rows),33)
        for row in rows:
            with self.subTest(case=row['case'],existingTag=row['existingTag']):
                allowed=row['case']<4
                adding=row['existingTag']=='absent'
                projection=row['projection']
                self.assertEqual(projection['completed'],allowed,projection['failure'])
                self.assertEqual(projection['languageCount'],1+int(not adding)+int(allowed and adding))
                self.assertEqual(row['addedActualObject'],allowed and adding)
                self.assertEqual(projection['tips'],[self.record['profile']['inputTip']] if allowed else [])

    def _actual_language_observation(self,cases):
        source=(ROOT/'scripts/ensure-korean-ime.ps1').read_text()
        self.assertTrue('function Get-OpenGeulLanguageObservation' in source,
                        'Actual finite language observation helper is missing')
        powershell=shutil.which('pwsh') or '/workspace/OpenGeul-ci-build-progress/.work/powershell746/bin/pwsh'
        if not Path(powershell).is_file():self.skipTest('PowerShell runtime unavailable')
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/'language-observation.ps1'
            script.write_text(r'''
param([string]$Source)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
class OpenGeulLanguageObservationTestShape {
    [string]$LanguageTag
    [Collections.Generic.List[string]]$InputMethodTips
    OpenGeulLanguageObservationTestShape([string]$Tag,[string]$Tip) {
        $this.LanguageTag=$Tag
        $this.InputMethodTips=[Collections.Generic.List[string]]::new()
        if($Tip){$this.InputMethodTips.Add($Tip)}
    }
}
$tokens=$null;$errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'production parse failure'}
$helper=$tree.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-OpenGeulLanguageObservation'},$true)
if($null -eq $helper){throw 'production language observation helper missing'}
Invoke-Expression $helper.Extent.Text
$predicate=$tree.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-OpenGeulKoreanLanguageTag'},$true)
if($null -ne $predicate){Invoke-Expression $predicate.Extent.Text}
$projection=$tree.Find({param($node)
    $node -is [Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left -is [Management.Automation.Language.VariableExpressionAst] -and
    $node.Left.VariablePath.UserPath -eq 'observedTips'
},$true)
$postselection=$tree.Find({param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left -is [Management.Automation.Language.VariableExpressionAst] -and $node.Left.VariablePath.UserPath -eq 'observedKorean'},$true)
$projectionStart=if($null -eq $postselection){$projection.Extent.StartOffset}else{$postselection.Extent.StartOffset}
$projectionText=$tree.Extent.Text.Substring($projectionStart,$projection.Extent.EndOffset-$projectionStart)
$selectedTip='0412:{A028AE76-01B1-46C2-99C4-ACD9858AE02F}{B5FE1F02-D5F2-4445-9C03-C568F23C99A1}'
$results=@()
'''+cases+r'''
@{passed=$true;results=$results;actualProductionHelper=$true;
  representativeTypedShapesOnly=$true;actualWindowsCmdletsInvoked=$false;
  actualWindowsInternationalAssembly=$false;sourceQualified=$false}|ConvertTo-Json -Depth 12 -Compress
''',encoding='utf-8')
            result=subprocess.run([str(powershell),'-NoLogo','-NoProfile','-NonInteractive','-File',str(script),
                '-Source',str(ROOT/'scripts/ensure-korean-ime.ps1')],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            value=json.loads(result.stdout)
            self.assertTrue(value['passed'])
            self.assertTrue(value['actualProductionHelper'])
            self.assertFalse(value['actualWindowsCmdletsInvoked'])
            self.assertFalse(value['actualWindowsInternationalAssembly'])
            self.assertFalse(value['sourceQualified'])
            return value['results']

    def test_actual_language_observation_is_finite_and_preserves_existing_projection(self):
        rows=self._actual_language_observation(r'''
foreach($shape in @('list','array','single','empty-list','null','selected-outside-filter')) {
    $list=[Collections.Generic.List[OpenGeulLanguageObservationTestShape]]::new()
    if($shape -notin @('empty-list','null')) {
        $list.Add([OpenGeulLanguageObservationTestShape]::new('en-US','0409:00000409'))
        $tag=if($shape -eq 'selected-outside-filter'){'ko'}else{'ko-KR'}
        $list.Add([OpenGeulLanguageObservationTestShape]::new($tag,$selectedTip))
    }
    if($shape -eq 'array'){$observedLanguages=@($list)}
    elseif($shape -eq 'single'){$observedLanguages=$list[1]}
    elseif($shape -eq 'null'){$observedLanguages=$null}
    else{$observedLanguages=$list}
    $beforeOutcome='completed';$observedTips=@()
    try { Invoke-Expression $projectionText }
    catch { $beforeOutcome=$_.Exception.GetType().FullName+'|'+$_.FullyQualifiedErrorId }
    $before=@($observedTips)
    $row=Get-OpenGeulLanguageObservation $observedLanguages $selectedTip
    $afterOutcome='completed';$observedTips=@()
    try { Invoke-Expression $projectionText }
    catch { $afterOutcome=$_.Exception.GetType().FullName+'|'+$_.FullyQualifiedErrorId }
    if($beforeOutcome -cne $afterOutcome -or ($before -join '|') -cne ($observedTips -join '|')){throw 'diagnostic changed actual projection'}
    $results+=,@{shape=$shape;observation=$row;projectionPreserved=$true}
}
''')
        expected={'list':(2,1,1,0),'array':(2,1,1,0),'single':(1,1,1,0),
                  'empty-list':(0,0,0,0),'null':(0,0,0,0),'selected-outside-filter':(2,0,1,1)}
        self.assertEqual(len(rows),len(expected))
        for row in rows:
            with self.subTest(shape=row['shape']):
                observed=row['observation'];languages,filtered,matches,outside=expected[row['shape']]
                self.assertEqual(observed['status'],'observed')
                self.assertEqual(observed['languageCount'],languages)
                self.assertEqual(observed['exactFilterLanguageCount'],filtered)
                self.assertEqual(observed['selectedNativeTipExactMatches'],matches)
                self.assertEqual(observed['outsideExactFilterSelectedTipMatches'],outside)
                self.assertTrue(row['projectionPreserved'])
                self.assertFalse(observed['productInputVerified'])
                self.assertFalse(observed['sourceQualified'])
                self.assertLessEqual(len(json.dumps(observed).encode()),32768)
                for forbidden in ['ko-KR','en-US','0412:','A028AE76','OpenGeulLanguageObservationTestShape']:
                    self.assertNotIn(forbidden,json.dumps(observed))

    def test_actual_language_observation_rejects_malformed_and_oversized_properties(self):
        rows=self._actual_language_observation(r'''
foreach($shape in @('missing-tag','missing-tips','raw-url-tag','raw-url-tip','too-many-languages','too-many-tips','too-long-tag','too-long-tip','invalid-selected-tip')) {
    $observedLanguages=[OpenGeulLanguageObservationTestShape]::new('ko-KR',$selectedTip)
    $tip=$selectedTip
    switch($shape) {
        'missing-tag' {$observedLanguages=[pscustomobject]@{InputMethodTips=@($selectedTip)}}
        'missing-tips' {$observedLanguages=[pscustomobject]@{LanguageTag='ko-KR'}}
        'raw-url-tag' {$observedLanguages=[pscustomobject]@{LanguageTag='https://private.invalid/secret';InputMethodTips=@($selectedTip)}}
        'raw-url-tip' {$observedLanguages=[pscustomobject]@{LanguageTag='ko-KR';InputMethodTips=@('https://private.invalid/secret')}}
        'too-many-languages' {$observedLanguages=@(1..65|ForEach-Object {[OpenGeulLanguageObservationTestShape]::new('ko-KR',$selectedTip)})}
        'too-many-tips' {$observedLanguages=[pscustomobject]@{LanguageTag='ko-KR';InputMethodTips=@(1..65|ForEach-Object {$selectedTip})}}
        'too-long-tag' {$observedLanguages=[pscustomobject]@{LanguageTag=('x'*65);InputMethodTips=@($selectedTip)}}
        'too-long-tip' {$observedLanguages=[pscustomobject]@{LanguageTag='ko-KR';InputMethodTips=@('x'*97)}}
        'invalid-selected-tip' {$tip='https://private.invalid/secret'}
    }
    $row=Get-OpenGeulLanguageObservation $observedLanguages $tip
    $results+=,@{shape=$shape;observation=$row}
}
''')
        self.assertEqual(len(rows),9)
        for row in rows:
            with self.subTest(shape=row['shape']):
                value=row['observation']
                self.assertIn(value['status'],('malformed_unavailable','size_unavailable'))
                self.assertIsNone(value['languageCount'])
                self.assertEqual(value['languages'],[])
                self.assertFalse(value['sourceQualified'])
                self.assertFalse(value['productInputVerified'])
                for forbidden in ['https','private','secret','0412:','A028AE76']:
                    self.assertNotIn(forbidden,json.dumps(value))

    def test_actual_language_observation_maximum_bound_and_exact_tip_membership(self):
        rows=self._actual_language_observation(r'''
$observedLanguages=[Collections.Generic.List[OpenGeulLanguageObservationTestShape]]::new()
for($index=0;$index -lt 64;$index++) {
    $item=[OpenGeulLanguageObservationTestShape]::new('ko-KR',$selectedTip)
    for($tipIndex=1;$tipIndex -lt 64;$tipIndex++){$item.InputMethodTips.Add($selectedTip)}
    $observedLanguages.Add($item)
}
$results+=,@{shape='maximum';observation=(Get-OpenGeulLanguageObservation $observedLanguages $selectedTip)}
$observedLanguages=[OpenGeulLanguageObservationTestShape]::new('ko-KR',$selectedTip.ToLowerInvariant())
$results+=,@{shape='different-case';observation=(Get-OpenGeulLanguageObservation $observedLanguages $selectedTip)}
''')
        maximum,case=rows
        self.assertEqual(maximum['observation']['languageCount'],64)
        self.assertEqual(maximum['observation']['tipCount'],4096)
        self.assertEqual(maximum['observation']['selectedNativeTipExactMatches'],4096)
        self.assertLessEqual(len(json.dumps(maximum['observation']).encode()),32768)
        self.assertEqual(case['observation']['selectedNativeTipExactMatches'],0)
        self.assertEqual(case['observation']['selectedNativeTipIgnoreCaseMatches'],1)
        self.assertFalse(case['observation']['sourceQualified'])
        self.assertFalse(case['observation']['productInputVerified'])

    def test_actual_language_observation_rejects_trailing_line_feeds(self):
        rows=self._actual_language_observation(r'''
foreach($shape in @('tag-lf','tip-lf','selected-lf')) {
    $tag=if($shape -eq 'tag-lf'){'ko-KR'+[char]10}else{'ko-KR'}
    $tip=if($shape -eq 'tip-lf'){$selectedTip+[char]10}else{$selectedTip}
    $selected=if($shape -eq 'selected-lf'){$selectedTip+[char]10}else{$selectedTip}
    $observedLanguages=[OpenGeulLanguageObservationTestShape]::new($tag,$tip)
    $results+=,@{shape=$shape;observation=(Get-OpenGeulLanguageObservation $observedLanguages $selected)}
}
''')
        self.assertEqual(len(rows),3)
        for row in rows:
            with self.subTest(shape=row['shape']):
                value=row['observation']
                self.assertEqual(value['status'],'malformed_unavailable')
                self.assertIsNone(value['languageCount'])
                self.assertEqual(value['languages'],[])
                self.assertFalse(value['sourceQualified'])
                self.assertFalse(value['productInputVerified'])

    def test_language_observation_is_saved_before_unchanged_projection_and_policy(self):
        script=(ROOT/'scripts/ensure-korean-ime.ps1').read_text()
        self.assertTrue("Save-ObservedJson 'user-language-observation.json'" in script,
                        'Actual pre-policy language observation is not retained')
        read=script.index('$observedLanguages=Get-WinUserLanguageList -ErrorAction Stop')
        save=script.index("Save-ObservedJson 'user-language-observation.json'")
        projection=script.index('$observedKorean=@($observedLanguages | Where-Object')
        policy=script.index("--record (Join-Path $out 'readiness.json')",read)
        self.assertLess(read,save);self.assertLess(save,projection);self.assertLess(save,policy)
        self.assertIn('workerPid=[int]$PID;scriptSha256=$hostObservation.scriptSha256',script[read:save])
        self.assertEqual(script.count('Get-WinUserLanguageList -ErrorAction Stop'),3)
        self.assertEqual(script.count('Set-WinUserLanguageList -LanguageList $languages -Force -ErrorAction Stop'),1)
        self.assertEqual(script.count('Set-WinDefaultInputMethodOverride -InputTip $profile.inputTip -ErrorAction Stop'),1)


if __name__=='__main__':unittest.main(verbosity=2)
