param([Parameter(Mandatory)][string]$ExecutablePath,
      [Parameter(Mandatory)][string]$OutputDirectory,
      [Parameter(Mandatory)][ValidateSet('payload','installed')][string]$Label)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'BinaryInfo diagnostics require a disposable Actions runner.' }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$exe = (Resolve-Path -LiteralPath $ExecutablePath).Path
$out = (Resolve-Path -LiteralPath $OutputDirectory).Path
$probe = Join-Path $PSScriptRoot 'wack-binaryinfo-observation.ps1'
$hosts = @(
    @{ name='x64'; path=(Get-Process -Id $PID).Path },
    @{ name='x86'; path=(Join-Path $env:WINDIR 'SysWOW64/WindowsPowerShell/v1.0/powershell.exe') }
)
$before = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
foreach ($hostSpec in $hosts) {
    $probeLabel = $Label + '-' + $hostSpec.name
    $arguments = @('-NoProfile','-NonInteractive','-File',('"'+$probe+'"'),
                   '-ExecutablePath',('"'+$exe+'"'),'-OutputDirectory',('"'+$out+'"'),'-Label',$probeLabel)
    $child = $null
    $stdout = Join-Path $out ('binaryinfo-'+$probeLabel+'-stdout.log')
    $stderr = Join-Path $out ('binaryinfo-'+$probeLabel+'-stderr.log')
    $observation = @{scope='diagnostic SDK BinaryInfo host supervision';label=$probeLabel;
                     host=$hostSpec.name;completed=$false;exitCode=$null;logsTruncated=$false}
    try {
        $child = Start-Process -FilePath $hostSpec.path -ArgumentList $arguments -PassThru -NoNewWindow `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        while (-not $child.WaitForExit(100)) {
            if (@($stdout,$stderr | Where-Object { (Test-Path -LiteralPath $_) -and (Get-Item -LiteralPath $_).Length -gt 64KB }).Count -gt 0) {
                $observation.reasonCode='probe-log-limit'
                break
            }
            if ([DateTime]::UtcNow -ge $deadline) {
                $observation.reasonCode='probe-timeout'
                break
            }
        }
        $child.Refresh()
        if ($child.HasExited) {
            $observation.exitCode=$child.ExitCode
            $observation.completed=($child.ExitCode -eq 0)
            if ($child.ExitCode -ne 0) { $observation.reasonCode='probe-child-failure' }
        }
    } catch {
        $observation.reasonCode='probe-supervisor-error'
        $observation.errorType=$_.Exception.GetBaseException().GetType().Name
    } finally {
        if ($child -and -not $child.HasExited) {
            taskkill /PID $child.Id /T /F | Out-Null
            $null=$child.WaitForExit(5000)
        }
        foreach ($log in @($stdout,$stderr)) {
            if ((Test-Path -LiteralPath $log) -and (Get-Item -LiteralPath $log).Length -gt 64KB) {
                $stream=[IO.File]::Open($log,[IO.FileMode]::Open,[IO.FileAccess]::Write)
                try { $stream.SetLength(64KB) } finally { $stream.Dispose() }
                $observation.logsTruncated=$true
                $observation.completed=$false
            }
        }
        $observation | ConvertTo-Json -Compress |
            Set-Content (Join-Path $out ('binaryinfo-'+$probeLabel+'-host.json')) -Encoding utf8
        if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ne $before) { throw 'Diagnostic engine modified the executable.' }
    }
}
