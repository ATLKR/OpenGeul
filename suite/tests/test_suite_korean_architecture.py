"""Execute Suite Korean setup architecture and offline source gates in PowerShell."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/ensure-korean-ime.ps1'
PWSH = shutil.which('pwsh')


@unittest.skipUnless(PWSH, 'PowerShell is required to execute prerequisite gates')
class SuiteKoreanArchitectureTests(unittest.TestCase):
    def run_gate(self, body):
        script = '''param([string]$Source)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Invalid prerequisite PowerShell source'}
foreach($name in @('Assert-SuiteNativeArchitecture','Assert-SuitePlainPath','Assert-SuiteKoreanOfflineSource','Get-SuiteKoreanPreparationDeadline','Copy-SuiteKoreanServicingTail','Test-SuiteKoreanLegacyCollectorWindow')) {
    $functions=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name},$true))
    if($functions.Count -ne 1){throw ('Missing single architecture gate: '+$name)}
    Invoke-Expression $functions[0].Extent.Text
}
''' + body
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'gate.ps1'
            path.write_text(script)
            result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-File', str(path), '-Source', str(SOURCE)],
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_native_requested_machine_must_equal_real_os_and_unemulated_controller(self):
        self.run_gate('''
foreach($row in @(@('x64',0,0x8664),@('arm64',0,0xAA64))) {
    Assert-SuiteNativeArchitecture -Architecture $row[0] -ProcessMachine $row[1] -NativeMachine $row[2]
}
foreach($row in @(@('arm64',0x8664,0xAA64),@('arm64',0,0x8664),@('x64',0,0xAA64),@('arm64',0,0xA641),@('x86',0,0x8664))) {
    $rejected=$false
    try { Assert-SuiteNativeArchitecture -Architecture $row[0] -ProcessMachine $row[1] -NativeMachine $row[2] } catch { $rejected=$true }
    if(-not $rejected){throw ('Wrong architecture accepted: '+($row -join ','))}
}
''')

    def test_offline_source_cannot_borrow_amd64_cabs_for_arm_or_unknown_os(self):
        self.run_gate('''
Assert-SuiteKoreanOfflineSource -NativeMachine 0x8664 -Build '26100' -InstallationType 'Server'
Assert-SuiteKoreanOfflineSource -NativeMachine 0x8664 -Build '26100' -InstallationType 'Server Core'
foreach($row in @(@(0xAA64,'26100','Server'),@(0x8664,'26200','Server'),@(0x8664,'26100','Client'),@(0xA641,'26100','Server'))) {
    $rejected=$false
    try { Assert-SuiteKoreanOfflineSource -NativeMachine $row[0] -Build $row[1] -InstallationType $row[2] } catch { $rejected=$true }
    if(-not $rejected){throw ('Unpinned offline source accepted: '+($row -join ','))}
}
''')


    def test_arm_online_capability_attempt_is_native_once_and_preserves_original_failure(self):
        self.run_gate('''
$installer=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Install-SuiteArm64KoreanCapability'},$true))
if($installer.Count -ne 1){throw 'Missing bounded native ARM Korean capability installer'}
Invoke-Expression $installer[0].Extent.Text
$global:ArmInstallCalls=@();$global:ArmInstallFailure=$false
$module=New-Module -Name Dism -ScriptBlock {
    function Add-WindowsCapability {
        param([switch]$Online,[string]$Name,[string]$LogPath,[string]$Source,[switch]$LimitAccess,[string]$ErrorAction)
        $global:ArmInstallCalls+=@([ordered]@{online=$Online.IsPresent;name=$Name;log=$LogPath;source=$PSBoundParameters.ContainsKey('Source');limit=$PSBoundParameters.ContainsKey('LimitAccess')})
        [IO.File]::WriteAllText($LogPath,'original raw DISM output 0x800f0950')
        if($global:ArmInstallFailure){throw 'original native ARM DISM failure 0x800f0950'}
        [pscustomobject]@{RestartNeeded=$false}
    }
    Export-ModuleMember -Function Add-WindowsCapability
}
$module | Import-Module -Force
$log=[IO.Path]::GetTempFileName()
try {
    foreach($row in @(@(0,0x8664),@(0x8664,0xAA64),@(0,0xA641))) {
        $rejected=$false
        try { Install-SuiteArm64KoreanCapability -ProcessMachine $row[0] -NativeMachine $row[1] -CapabilityName 'Language.Basic~~~ko-KR~0.0.1.0' -LogPath $log } catch { $rejected=$true }
        if(-not $rejected){throw 'Non-native ARM servicing accepted'}
    }
    if($global:ArmInstallCalls.Count -ne 0){throw 'Wrong-machine servicing ran'}
    $installed=@(Install-SuiteArm64KoreanCapability -ProcessMachine 0 -NativeMachine 0xAA64 -CapabilityName 'Language.Basic~~~ko-KR~0.0.1.0' -LogPath $log)
    if($installed.Count -ne 1 -or $installed[0].RestartNeeded -ne $false -or $global:ArmInstallCalls.Count -ne 1){throw 'Native capability attempt was retried or its result altered'}
    $call=$global:ArmInstallCalls[0]
    if(-not $call.online -or $call.name -cne 'Language.Basic~~~ko-KR~0.0.1.0' -or $call.source -or $call.limit){throw 'Native Windows Update call borrowed offline CAB/source options'}
    $global:ArmInstallCalls=@();$global:ArmInstallFailure=$true
    $message=$null
    try { Install-SuiteArm64KoreanCapability -ProcessMachine 0 -NativeMachine 0xAA64 -CapabilityName 'Language.Basic~~~ko-KR~0.0.1.0' -LogPath $log } catch { $message=$_.Exception.Message }
    if($message -cne 'original native ARM DISM failure 0x800f0950' -or $global:ArmInstallCalls.Count -ne 1){throw 'Original failure was hidden or retried'}
    if([IO.File]::ReadAllText($log) -cne 'original raw DISM output 0x800f0950'){throw 'Original DISM log was rewritten'}
} finally { Remove-Item -LiteralPath $log -Force; Remove-Module Dism -Force }
''')

    def test_only_native_arm64_gets_1800_seconds_and_receipts_bind_utc_deadline(self):
        self.run_gate('''
$started=[DateTime]::Parse('2026-10-17T00:00:00.0000000Z',$null,[Globalization.DateTimeStyles]::RoundtripKind)
foreach($row in @(@('x64',0,0x8664,600),@('arm64',0,0xAA64,1800))) {
    $deadline=Get-SuiteKoreanPreparationDeadline -Architecture $row[0] -ProcessMachine $row[1] -NativeMachine $row[2] -StartedUtc $started
    if($deadline.budgetSeconds -ne $row[3] -or $deadline.startedUtc -cne $started.ToString('o') -or $deadline.expiresUtc -cne $started.AddSeconds($row[3]).ToString('o')){throw 'Native budget or bounded UTC deadline is incorrect'}
}
foreach($row in @(@('arm64',0,0x8664),@('arm64',0x8664,0xAA64),@('x64',0,0xAA64),@('x86',0,0x8664))) {
    $rejected=$false;try{Get-SuiteKoreanPreparationDeadline -Architecture $row[0] -ProcessMachine $row[1] -NativeMachine $row[2] -StartedUtc $started}catch{$rejected=$true}
    if(-not $rejected){throw 'A transposed/emulated architecture received an extended budget'}
}
foreach($age in @(899,900,900.1,1800)) {
    if((Test-SuiteKoreanLegacyCollectorWindow -Architecture 'arm64' -ElapsedSeconds $age) -ne ($age -le 900)){throw 'Extended ARM attempt was passed to the legacy collector'}
    if(-not (Test-SuiteKoreanLegacyCollectorWindow -Architecture 'x64' -ElapsedSeconds $age)){throw 'Existing x64 collector routing changed'}
}
''')

    def test_long_arm_failure_tail_is_bounded_and_preserves_original_and_existing_evidence(self):
        self.run_gate('''
$root=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'));[void][IO.Directory]::CreateDirectory($root)
try {
    $source=Join-Path $root 'original.log';$target=Join-Path $root 'tail.log'
    $bytes=[byte[]]::new(2097152);$bytes[$bytes.Length-1]=42;[IO.File]::WriteAllBytes($source,$bytes)
    $record=Copy-SuiteKoreanServicingTail -Source $source -Destination $target
    if($record.tailBytes -ne 1048576 -or -not $record.truncated -or $record.tailStart -ne 1048576 -or [IO.File]::ReadAllBytes($target)[1048575] -ne 42){throw 'Independent ARM diagnostics exceeded/lost its bounded tail'}
    $rejected=$false;try{Copy-SuiteKoreanServicingTail -Source $source -Destination $target}catch{$rejected=$true}
    if(-not $rejected -or (Get-Item -LiteralPath $source).Length -ne 2097152){throw 'Original/existing diagnostic evidence was overwritten'}
}finally{Remove-Item -LiteralPath $root -Recurse -Force}
''')

    def test_controller_loop_uses_selected_deadline_at_the_observed_951_second_duration(self):
        self.run_gate('''
$loops=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.WhileStatementAst] -and $node.Condition.Extent.Text -ceq '$true'},$true))
if($loops.Count -ne 1){throw 'Owned preparation wait loop missing or ambiguous'}
$out=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'));[void][IO.Directory]::CreateDirectory($out)
try {
    foreach($row in @(@('arm64',0xAA64,951.6205443,$false),@('x64',0x8664,951.6205443,$true),@('arm64',0xAA64,1800.1,$true),@('x64',0x8664,599.9,$false))) {
        $deadline=Get-SuiteKoreanPreparationDeadline -Architecture $row[0] -ProcessMachine 0 -NativeMachine $row[1] -StartedUtc ([DateTime]::UtcNow)
        $clock=[pscustomobject]@{Elapsed=[pscustomobject]@{TotalMilliseconds=($row[2]*1000);TotalSeconds=$row[2]}}
        $child=[pscustomobject]@{waits=0}
        $child|Add-Member ScriptMethod WaitForExit {param($milliseconds) $this.waits++;return $true}
        $timedOut=$false;$deadlineError='actual bounded preparation deadline';$failed=$false
        try { Invoke-Expression $loops[0].Extent.Text } catch { $failed=$true;if($_.Exception.Message -cne $deadlineError){throw} }
        if($failed -ne $row[3] -or $timedOut -ne $row[3]){throw ('Actual controller loop used the wrong architecture budget at '+$row[2]+' seconds')}
        if($child.waits -ne $(if($row[3]){0}else{1})){throw 'Wait exceeded selected preparation budget'}
    }
}finally{Remove-Item -LiteralPath $out -Recurse -Force}
''')

    def test_worker_deadline_survives_json_string_or_typed_utc_timestamp_roundtrip(self):
        self.run_gate('''
$assignments=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -ceq '$deadlineStart'},$true))
if($assignments.Count -ne 1){throw 'Worker UTC timestamp assignment missing or ambiguous'}
$started=[DateTime]::Parse('2026-10-17T00:00:00.1234567Z',$null,[Globalization.DateTimeStyles]::RoundtripKind)
$original=[pscustomobject]@{preparationDeadline=[pscustomobject]@{startedUtc=$started.ToString('o')}}
foreach($savedDeadline in @($original,($original|ConvertTo-Json|ConvertFrom-Json))) {
    Invoke-Expression $assignments[0].Extent.Text
    $deadline=Get-SuiteKoreanPreparationDeadline -Architecture 'arm64' -ProcessMachine 0 -NativeMachine 0xAA64 -StartedUtc $deadlineStart
    if($deadlineStart.Kind -ne [DateTimeKind]::Utc -or $deadline.startedUtc -cne $started.ToString('o')){throw 'UTC deadline lost its kind or precision during JSON replay'}
}
''')

    def test_arm_timeout_preserves_original_error_and_tails_when_cleanup_or_receipt_fails(self):
        self.run_gate('''
$catches=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.CatchClauseAst] -and $node.Body.Extent.Text.Contains('$originalControllerFailure=$_')},$true))
if($catches.Count -ne 1){throw 'Owned controller failure handler missing or ambiguous'}
$body=($catches[0].Body.Statements|ForEach-Object {$_.Extent.Text}) -join "`n"
foreach($failureMode in @('cleanup','receipt','none')) {
    $Architecture='arm64';$controllerHost=@{processMachine=0;nativeMachine=0xAA64};$deadline=@{budgetSeconds=1800}
    $clock=[pscustomobject]@{Elapsed=[pscustomobject]@{TotalSeconds=1800}};$binding=@{};$timedOut=$true
    $started=[DateTime]::UtcNow;$child=[pscustomobject]@{HasExited=$false;StartTime=$started;FailureMode=$failureMode}
    $child|Add-Member ScriptMethod Kill {if($this.FailureMode -ceq 'cleanup'){throw 'cleanup race'}; $this.HasExited=$true}
    $child|Add-Member ScriptMethod WaitForExit {param($milliseconds) return $true}
    $script:tails=0;$script:receipts=0
    function Save-SuiteArm64FailureDiagnostics {param($HostRecord,$Deadline) $script:tails++}
    function Save-SuiteObservation {param($Name,$Value) $script:receipts++;if($failureMode -ceq 'receipt'){throw 'receipt write failed'}}
    $message=$null
    try { throw 'original preparation timeout' }
    catch { try { Invoke-Expression $body } catch { $message=$_.Exception.Message } }
    if($message -cne 'original preparation timeout' -or $script:tails -ne 1 -or $script:receipts -ne 1){throw ('Original timeout/tails were replaced by '+$failureMode+' failure')}
}
''')

if __name__ == '__main__': unittest.main()
