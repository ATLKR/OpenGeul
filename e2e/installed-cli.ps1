param([Parameter(Mandatory)][string]$CliPath,[Parameter(Mandatory)][string]$PackageFullName,
      [Parameter(Mandatory)][string]$OutputDirectory,
      [Parameter(Mandatory)][string]$McpFixtureDirectory,
      [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedCliSha256,
      [Parameter(Mandatory)][ValidateSet('true',IgnoreCase=$false)][string]$CiActions,
      [Parameter(Mandatory)][ValidateSet('github-hosted',IgnoreCase=$false)][string]$CiRunnerEnvironment,
      [Parameter(Mandatory)][ValidateSet('ATLKR/OpenGeul',IgnoreCase=$false)][string]$CiRepository,
      [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$',Options='None')][string]$CiCommit,
      [Parameter(Mandatory)][ValidatePattern('^[1-9][0-9]{0,19}$')][string]$CiRunId,
      [Parameter(Mandatory)][ValidatePattern('^[1-9][0-9]{0,19}$')][string]$CiRunAttempt,
      [ValidateSet('x64','arm64')][string]$Architecture='x64',
      [Parameter(Mandatory)][string]$PythonPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$true
$result=@{success=$false;expectedPackageFullName=$PackageFullName;scope='Installed CLI launched within the declared desktop package graph'}
try {
 $publicCiEnvironment=[ordered]@{GITHUB_ACTIONS=$CiActions;RUNNER_ENVIRONMENT=$CiRunnerEnvironment;
  GITHUB_REPOSITORY=$CiRepository;GITHUB_SHA=$CiCommit;GITHUB_RUN_ID=$CiRunId;GITHUB_RUN_ATTEMPT=$CiRunAttempt}
 foreach ($name in $publicCiEnvironment.Keys) {
  $existing=[Environment]::GetEnvironmentVariable($name,'Process')
  if (-not [string]::IsNullOrEmpty($existing) -and $existing -cne $publicCiEnvironment[$name]) { throw '패키지 child 환경이 현재 CI 실행과 다릅니다.' }
 }
 foreach ($name in $publicCiEnvironment.Keys) {
  [Environment]::SetEnvironmentVariable($name,$publicCiEnvironment[$name],'Process')
 }
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
 $mcpDirectory=Join-Path $OutputDirectory 'installed-mcp'
 $mcpPath=Join-Path $mcpDirectory 'mcp-result.json'
 & $PythonPath (Join-Path $PSScriptRoot 'mcp_worker.py') --exe $CliPath --architecture $Architecture --expected-sha256 $ExpectedCliSha256 --context installed --package-full-name $PackageFullName --fixtures (Join-Path $McpFixtureDirectory 'e2e-fixtures') --password-fixtures (Join-Path $McpFixtureDirectory 'password-fixtures') --out $mcpDirectory
 & $PythonPath (Join-Path $PSScriptRoot '../scripts/mcp_qualification.py') --receipt $mcpPath --architecture $Architecture --cli-sha256 $ExpectedCliSha256 --package-full-name $PackageFullName
 $result.mcp=Get-Content $mcpPath -Raw | ConvertFrom-Json
 $result.success=$true
} catch { $result.reason=$_.Exception.Message }
finally {
 $temporary=Join-Path $OutputDirectory 'installed-cli.json.tmp'
 $result | ConvertTo-Json -Depth 20 | Set-Content $temporary -Encoding utf8
 Move-Item $temporary (Join-Path $OutputDirectory 'installed-cli.json')
}
if (-not $result.success) { exit 1 }
