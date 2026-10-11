param([Parameter(Mandatory)][string]$PackageFullName,[Parameter(Mandatory)][string]$Identity,
      [Parameter(Mandatory)][string]$Version,[Parameter(Mandatory)][string]$OutputDirectory)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'WACK automation is restricted to disposable GitHub Actions runners.' }
$output=(New-Item -ItemType Directory -Force $OutputDirectory).FullName
$summary=Join-Path $output 'wack.json'
$appcert=Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/App Certification Kit/appcert.exe'
if (-not (Test-Path $appcert)) {
 @{status='unavailable';passed=$false;reason='Windows App Certification Kit is not installed on this runner';
   expectedIdentity=$Identity;expectedVersion=$Version;scope='WACK has not run; this is not certification evidence'} |
  ConvertTo-Json | Set-Content $summary -Encoding utf8
 Write-Warning 'WACK unavailable; review wack.json. Installation smoke is not WACK approval.'
 return
}
$process=$null
try {
 & $appcert reset *> (Join-Path $output 'wack-reset.log')
 if ($LASTEXITCODE -ne 0) { throw 'WACK reset failed.' }
 $report=Join-Path $output 'wack.xml'
 if (Test-Path $report) { throw 'Refusing to reuse an existing WACK report.' }
 $process=Start-Process $appcert -ArgumentList @('test','-packagefullname',$PackageFullName,'-reportoutputpath',"`"$report`"") -PassThru -NoNewWindow -RedirectStandardOutput (Join-Path $output 'wack-stdout.log') -RedirectStandardError (Join-Path $output 'wack-stderr.log')
 if (-not $process.WaitForExit(900000)) { throw 'WACK exceeded the 15 minute runner deadline.' }
 $process.Refresh()
 python (Join-Path $PSScriptRoot 'wack_result.py') --report $report --out $summary --identity $Identity --version $Version --exit-code $process.ExitCode
 if ($LASTEXITCODE -ne 0) { throw 'WACK report validation failed; see wack.json and wack.xml.' }
} catch {
 if (-not (Test-Path $summary)) {
  @{status='failed';passed=$false;reason=$_.Exception.Message;expectedIdentity=$Identity;expectedVersion=$Version} |
   ConvertTo-Json | Set-Content $summary -Encoding utf8
 }
 throw
} finally {
 if ($process -and -not $process.HasExited) { taskkill /PID $process.Id /T /F | Out-Null }
}
