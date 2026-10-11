param([Parameter(Mandatory)][string]$InstalledExecutablePath,
      [Parameter(Mandatory)][string]$PayloadExecutablePath,
      [Parameter(Mandatory)][string]$OutputDirectory)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or -not [Environment]::Is64BitProcess) {
    throw 'Path observations require a disposable x64 Actions runner.'
}
$installed = (Resolve-Path -LiteralPath $InstalledExecutablePath).Path
$payload = (Resolve-Path -LiteralPath $PayloadExecutablePath).Path
$output = (New-Item -ItemType Directory -Force -Path $OutputDirectory).FullName
$before = @{}
foreach ($file in @($installed,$payload)) {
    $before[$file] = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    if ($before[$file] -ne 'E282955C8E460CB66270949E51E492162BCE7CEBB75AE62562043C05885F8490') {
        throw 'Path observation input does not match the exact diagnostic editor.'
    }
}
$hostPath = (Get-Process -Id $PID).Path
if ([IO.Path]::GetFileName($hostPath) -ine 'pwsh.exe') { throw 'The supervisor requires x64 pwsh.' }
$stdout = Join-Path $output 'wack-path-stdout.log'
$stderr = Join-Path $output 'wack-path-stderr.log'
$record = @{scope='bounded path-observation supervisor; normal WACK remains independent';
            completed=$false;deadlineSeconds=90;exitCode=$null;logsTruncated=$false}
$child = $null
try {
    $arguments = @('-NoProfile','-NonInteractive','-File',('"'+(Join-Path $PSScriptRoot 'wack-path-observation.ps1')+'"'),
                   '-InstalledExecutablePath',('"'+$installed+'"'),'-PayloadExecutablePath',('"'+$payload+'"'),
                   '-OutputDirectory',('"'+$output+'"'))
    $child = Start-Process -FilePath $hostPath -ArgumentList $arguments -PassThru -NoNewWindow `
        -WorkingDirectory (Get-Location).ProviderPath -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    while (-not $child.WaitForExit(100)) {
        if (@($stdout,$stderr | Where-Object { (Test-Path -LiteralPath $_) -and (Get-Item -LiteralPath $_).Length -gt 64KB }).Count -gt 0) {
            $record.reasonCode='path-log-limit';break
        }
        if ([DateTime]::UtcNow -ge $deadline) { $record.reasonCode='path-timeout';break }
    }
    $child.Refresh()
    if ($child.HasExited) {
        $record.exitCode=$child.ExitCode
        $record.completed=($child.ExitCode -eq 0)
        if (-not $record.completed) { $record.reasonCode='path-child-failure' }
    }
} catch {
    $record.reasonCode='path-supervisor-error'
    $record.errorType=$_.Exception.GetBaseException().GetType().Name
} finally {
    if ($child) {
        try {
            if (-not $child.HasExited) { $child.Kill($true);$null=$child.WaitForExit(5000) }
            $record.childStopped=$child.HasExited
        } catch { $record.childStopped=$false;$record.completed=$false }
        $child.Dispose()
    }
    foreach ($log in @($stdout,$stderr)) {
        if ((Test-Path -LiteralPath $log) -and (Get-Item -LiteralPath $log).Length -gt 64KB) {
            $stream=[IO.File]::Open($log,[IO.FileMode]::Open,[IO.FileAccess]::Write)
            try { $stream.SetLength(64KB) } finally { $stream.Dispose() }
            $record.logsTruncated=$true;$record.completed=$false
        }
    }
    $record | ConvertTo-Json -Compress | Set-Content (Join-Path $output 'wack-path-host.json') -Encoding utf8
    foreach ($file in @($installed,$payload)) {
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $before[$file]) {
            throw 'Path diagnostic modified the exact executable.'
        }
    }
}
