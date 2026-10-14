"""Preparation policy tests; no Windows capability/profile success is simulated."""
import copy
import importlib.util
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

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


if __name__=='__main__':unittest.main(verbosity=2)
