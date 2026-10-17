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
foreach($name in @('Assert-SuiteNativeArchitecture','Assert-SuiteKoreanOfflineSource')) {
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

if __name__ == '__main__': unittest.main()
