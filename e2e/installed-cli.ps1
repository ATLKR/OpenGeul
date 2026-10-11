param([Parameter(Mandatory)][string]$CliPath,[Parameter(Mandatory)][string]$PackageFullName,
      [Parameter(Mandatory)][string]$OutputDirectory)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Installed CLI smoke is restricted to disposable GitHub Actions runners.' }
$result=@{success=$false;expectedPackageFullName=$PackageFullName;scope='Installed CLI launched within the declared desktop package graph'}
try {
 Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class OpenGeulCliIdentity {
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true)]
 public static extern int GetCurrentPackageFullName(ref uint length, StringBuilder name);
}
'@
 $length=[uint32]0
 if ([OpenGeulCliIdentity]::GetCurrentPackageFullName([ref]$length,$null) -ne 122) { throw 'CLI probe was not launched in a package context.' }
 $identity=[System.Text.StringBuilder]::new([int]$length)
 if ([OpenGeulCliIdentity]::GetCurrentPackageFullName([ref]$length,$identity) -ne 0 -or $identity.ToString() -ne $PackageFullName) { throw 'CLI probe has a different package identity.' }
 $result.packageFullName=$identity.ToString()
 $help=& $CliPath --help 2>&1 | Out-String
 $result.exitCode=$LASTEXITCODE
 $help | Set-Content (Join-Path $OutputDirectory 'installed-cli-help.txt') -Encoding utf8
 if ($result.exitCode -ne 0 -or $help -notmatch '(?i)rhwp|usage|사용') { throw 'Installed CLI did not return usable help.' }
 $result.success=$true
} catch { $result.reason=$_.Exception.Message }
finally {
 $temporary=Join-Path $OutputDirectory 'installed-cli.json.tmp'
 $result | ConvertTo-Json | Set-Content $temporary -Encoding utf8
 Move-Item $temporary (Join-Path $OutputDirectory 'installed-cli.json')
}
if (-not $result.success) { exit 1 }
