param([Parameter(Mandatory)][string]$CliPath,[Parameter(Mandatory)][string]$PackageFullName,
      [Parameter(Mandatory)][string]$OutputDirectory,
      [ValidateSet('x64','arm64')][string]$Architecture='x64',
      [Parameter(Mandatory)][string]$PythonPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$true
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
 & $PythonPath (Join-Path $PSScriptRoot 'native_architecture.py') cli --architecture $Architecture --executable $CliPath --package-full-name $PackageFullName --output (Join-Path $OutputDirectory 'installed-cli-native.json') --help-output (Join-Path $OutputDirectory 'installed-cli-help.txt')
 $actual=Get-Content (Join-Path $OutputDirectory 'installed-cli-native.json') -Raw | ConvertFrom-Json
 if (-not $actual.success -or $actual.packageFullName -ne $PackageFullName -or $actual.nativeArchitecture.architecture -ne $Architecture) { throw '설치 CLI의 실제 native process 또는 package identity 검증에 실패했습니다.' }
 $result.exitCode=$actual.exitCode
 $result.nativeArchitecture=$actual.nativeArchitecture
 $result.helpBytes=$actual.helpBytes
 $result.helpSha256=$actual.helpSha256
 $result.success=$true
} catch { $result.reason=$_.Exception.Message }
finally {
 $temporary=Join-Path $OutputDirectory 'installed-cli.json.tmp'
 $result | ConvertTo-Json -Depth 10 | Set-Content $temporary -Encoding utf8
 Move-Item $temporary (Join-Path $OutputDirectory 'installed-cli.json')
}
if (-not $result.success) { exit 1 }
