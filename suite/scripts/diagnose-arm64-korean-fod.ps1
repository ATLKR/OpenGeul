param(
    [Parameter(Mandatory=$true)][string]$Output,
    [switch]$Worker,
    [string]$Nonce,
    [int]$ParentPid
)
# One ephemeral diagnostic attempt. This does not change Suite's ten-minute
# qualification gate, configure input profiles, or establish product readiness.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function Assert-Arm64FodNativeHost([UInt16]$ProcessMachine,[UInt16]$NativeMachine) {
    if ($ProcessMachine -ne 0 -or $NativeMachine -ne 0xAA64) { throw 'Diagnostic requires an actual native ARM64 controller and OS.' }
}
function Assert-Arm64FodPlainPath([string]$Path) {
    $check=[IO.Path]::GetFullPath($Path)
    while ($check) {
        if ((Test-Path -LiteralPath $check) -and ((Get-Item -LiteralPath $check).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Diagnostic path contains a reparse point.'
        }
        $check=[IO.Path]::GetDirectoryName($check)
    }
}
function Resolve-Arm64FodOutput([string]$Repo,[string]$Output,[bool]$Worker) {
    $resolved=[IO.Path]::GetFullPath($(if ([IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path $Repo $Output }))
    if (-not $resolved.StartsWith($Repo+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or
        $resolved.IndexOfAny([char[]]@('"',"`r","`n")) -ge 0) { throw 'Diagnostic output must stay inside the actual checkout.' }
    Assert-Arm64FodPlainPath $resolved
    if (-not $Worker -and (Test-Path -LiteralPath $resolved)) { throw 'Preserve existing diagnostic evidence; choose a new output directory.' }
    if ($Worker -and -not (Test-Path -LiteralPath $resolved -PathType Container)) { throw 'Owned diagnostic output is missing.' }
    return $resolved
}
function Invoke-Arm64FodOnlineAttempt([UInt16]$ProcessMachine,[UInt16]$NativeMachine,[string]$LogPath) {
    Assert-Arm64FodNativeHost $ProcessMachine $NativeMachine
    Dism\Add-WindowsCapability -Online -Name 'Language.Basic~~~ko-KR~0.0.1.0' -LogPath $LogPath -ErrorAction Stop
}
function Copy-Arm64FodLogTail([string]$Source,[string]$Destination) {
    Assert-Arm64FodPlainPath $Source
    Assert-Arm64FodPlainPath $Destination
    $inputStream=$null;$outputStream=$null
    try {
        $inputStream=[IO.File]::Open($Source,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
        [long]$size=$inputStream.Length
        [long]$start=[Math]::Max(0,$size-1MB)
        [void]$inputStream.Seek($start,[IO.SeekOrigin]::Begin)
        $buffer=[byte[]]::new([int][Math]::Min(1MB,$size))
        $used=0
        while ($used -lt $buffer.Length) {
            $read=$inputStream.Read($buffer,$used,$buffer.Length-$used)
            if ($read -eq 0) { break }
            $used+=$read
        }
        $outputStream=[IO.File]::Open($Destination,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        $outputStream.Write($buffer,0,$used)
        return [ordered]@{sourcePath=$Source;sourceBytes=$size;tailStart=$start;tailBytes=$used;truncated=($start -gt 0)}
    } finally {
        if ($null -ne $outputStream) { $outputStream.Dispose() }
        if ($null -ne $inputStream) { $inputStream.Dispose() }
    }
}
function Save-Arm64FodObservation([string]$Name,$Value) {
    $json=$Value | ConvertTo-Json -Depth 12 -Compress
    $bytes=[Text.UTF8Encoding]::new($false).GetBytes($json)
    if ($bytes.Length -gt 65536) { throw 'Diagnostic observation exceeds its bound.' }
    $stream=[IO.File]::Open((Join-Path $out $Name),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    try { $stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
}
function Get-Arm64FodNativeHost {
    if (-not ('Arm64FodDiagnosticHost' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class Arm64FodDiagnosticHost {
    [DllImport("kernel32")] public static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32",SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)]
    public static extern bool IsWow64Process2(IntPtr process,out ushort processMachine,out ushort nativeMachine);
}
'@
    }
    [UInt16]$processMachine=0;[UInt16]$nativeMachine=0
    if (-not [Arm64FodDiagnosticHost]::IsWow64Process2([Arm64FodDiagnosticHost]::GetCurrentProcess(),[ref]$processMachine,[ref]$nativeMachine)) {
        throw 'Actual diagnostic process architecture is unavailable.'
    }
    Assert-Arm64FodNativeHost $processMachine $nativeMachine
    return [ordered]@{processId=$PID;controllerMachine=[int]$processMachine;nativeMachine=[int]$nativeMachine}
}
function Get-Arm64FodEnvironment {
    $services=@()
    foreach ($name in @('wuauserv','BITS','TrustedInstaller')) {
        try {
            $service=Get-Service -Name $name -ErrorAction Stop
            $services+=@([ordered]@{name=$name;status=[string]$service.Status;startType=[string]$service.StartType})
        } catch { $services+=@([ordered]@{name=$name;errorType=$_.Exception.GetType().FullName}) }
    }
    # Only these nonsecret DWORDs are admitted. Never read WUServer URLs,
    # proxy configuration/credentials, user policies, or arbitrary registry data.
    $selected=@(
        @('SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate','DoNotConnectToWindowsUpdateInternetLocations'),
        @('SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate','DisableWindowsUpdateAccess'),
        @('SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate','SetDisableUXWUAccess'),
        @('SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate','UseUpdateClassPolicySource'),
        @('SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate','SetPolicyDrivenUpdateSourceForOtherUpdates'),
        @('SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate','SetPolicyDrivenUpdateSourceForQualityUpdates'),
        @('SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU','UseWUServer'),
        @('SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU','NoAutoUpdate'),
        @('SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU','AUOptions'),
        @('SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Servicing','UseWindowsUpdate'),
        @('SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Servicing','RepairContentServerSource'))
    $policies=@();$registry=$null
    try {
        $registry=[Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,[Microsoft.Win32.RegistryView]::Registry64)
        foreach ($pair in $selected) {
            $key=$null;$row=[ordered]@{key=$pair[0];name=$pair[1];present=$false}
            try {
                $key=$registry.OpenSubKey($pair[0],$false)
                if ($null -ne $key -and $key.GetValueNames() -ccontains $pair[1]) {
                    $row.present=$true;$row.kind=[string]$key.GetValueKind($pair[1])
                    if ($key.GetValueKind($pair[1]) -eq [Microsoft.Win32.RegistryValueKind]::DWord) {
                        [long]$value=$key.GetValue($pair[1]);if ($value -lt 0) { $value+=4294967296 }
                        $row.value=$value
                    }
                }
            } catch { $row.errorType=$_.Exception.GetType().FullName }
            finally { if ($null -ne $key) { $key.Dispose() } }
            $policies+=@($row)
        }
    } finally { if ($null -ne $registry) { $registry.Dispose() } }
    return [ordered]@{observedUtc=[DateTime]::UtcNow.ToString('o');services=$services;selectedMachinePolicyDwords=$policies}
}
function Save-Arm64FodDiagnostics {
    $record=[ordered]@{source=$binding;observedUtc=[DateTime]::UtcNow.ToString('o');logs=@();errors=@();
        diagnosticOnly=$true;productInputVerified=$false;qualification=$false;sourceQualified=$false;storeQualified=$false}
    try { $record.environment=Get-Arm64FodEnvironment } catch { $record.errors+=@('environment: '+$_.Exception.GetType().FullName) }
    $windows=[Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)
    foreach ($pair in @(@((Join-Path $out 'dism.log'),'owned-dism-tail.log'),
            @((Join-Path $windows 'Logs/CBS/CBS.log'),'cbs-tail.log'),
            @((Join-Path $windows 'Logs/DISM/dism.log'),'system-dism-tail.log'))) {
        try { $record.logs+=@(Copy-Arm64FodLogTail -Source $pair[0] -Destination (Join-Path $out $pair[1])) }
        catch { $record.errors+=@($pair[1]+': '+$_.Exception.GetType().FullName) }
    }
    # This standalone tail collector supports this 30-minute experiment. The
    # existing Suite collector deliberately accepts only 15-minute attempts.
    Save-Arm64FodObservation 'diagnostics.json' $record
}

$repo=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or -not [Environment]::Is64BitProcess -or
    $env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
    $env:RUNNER_OS -cne 'Windows' -or $env:GITHUB_JOB -cne 'arm64-fod-diagnostic' -or
    $env:GITHUB_REPOSITORY -cne 'ATLKR/OpenGeul' -or $env:GITHUB_SHA -cnotmatch '\A[0-9a-f]{40}\z' -or
    $env:GITHUB_RUN_ID -cnotmatch '\A[1-9][0-9]*\z' -or $env:GITHUB_RUN_ATTEMPT -cnotmatch '\A[1-9][0-9]*\z') {
    throw 'Diagnostic requires the actual hosted ARM64 FoD diagnostic job and complete source/run binding.'
}
$head=@(& git -C $repo rev-parse --verify HEAD)
if ($LASTEXITCODE -ne 0 -or $head.Count -ne 1 -or $head[0] -cne $env:GITHUB_SHA) { throw 'Diagnostic checkout differs from the actual source SHA.' }
$binding=[ordered]@{sourceCommit=$head[0];repository=$env:GITHUB_REPOSITORY;job=$env:GITHUB_JOB;
    sourceRun=$env:GITHUB_RUN_ID;runAttempt=$env:GITHUB_RUN_ATTEMPT;architecture='arm64'}
$hostRecord=Get-Arm64FodNativeHost
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'The hosted native diagnostic worker requires capability servicing elevation.'
}
$out=Resolve-Arm64FodOutput -Repo $repo -Output $Output -Worker $Worker.IsPresent
if ($Worker) {
    if ($Nonce -cnotmatch '\A[0-9a-f]{32}\z' -or $ParentPid -le 0) { throw 'Owned worker identity is missing.' }
    $intent=Get-Content -LiteralPath (Join-Path $out 'controller.json') -Raw | ConvertFrom-Json
    if ($intent.nonce -cne $Nonce -or $intent.parentPid -ne $ParentPid -or
        $intent.source.sourceCommit -cne $binding.sourceCommit -or $intent.source.sourceRun -cne $binding.sourceRun -or
        $intent.source.runAttempt -cne $binding.runAttempt -or $intent.source.job -cne $binding.job) { throw 'Worker differs from its owned controller source/run/nonce.' }
    $parent=Get-Process -Id $ParentPid -ErrorAction Stop
    if ($parent.StartTime.ToUniversalTime().ToString('o') -cne $intent.parentStartedUtc) { throw 'Owned controller process identity changed.' }
    $started=[DateTime]::UtcNow;$clock=[Diagnostics.Stopwatch]::StartNew();$stage='worker-start'
    Save-Arm64FodObservation 'worker-start.json' ([ordered]@{source=$binding;host=$hostRecord;nonce=$Nonce;startedUtc=$started.ToString('o');
        diagnosticOnly=$true;productInputVerified=$false;qualification=$false})
    try {
        $manifest=Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell/v1.0/Modules/Dism/Dism.psd1'
        Assert-Arm64FodPlainPath $manifest
        Import-Module -Name $manifest -ErrorAction Stop
        $stage='capability-before';$capabilityName='Language.Basic~~~ko-KR~0.0.1.0';$dismLog=Join-Path $out 'dism.log'
        $before=@(Dism\Get-WindowsCapability -Online -Name $capabilityName -LogPath $dismLog -ErrorAction Stop | Where-Object Name -eq $capabilityName)
        if ($before.Count -ne 1) { throw 'Named Korean Basic capability is missing or ambiguous.' }
        $beforeState=[string]$before[0].State
        Save-Arm64FodObservation 'before.json' ([ordered]@{source=$binding;host=$hostRecord;capabilityName=$capabilityName;state=$beforeState;
            observedUtc=[DateTime]::UtcNow.ToString('o');diagnosticOnly=$true;productInputVerified=$false;qualification=$false})
        $attempted=$false;$restartNeeded=$false;$attemptSeconds=0
        if ($beforeState -ceq 'NotPresent') {
            $stage='one-native-online-add';$attempted=$true;$attemptClock=[Diagnostics.Stopwatch]::StartNew()
            Save-Arm64FodObservation 'attempt-start.json' ([ordered]@{source=$binding;startedUtc=[DateTime]::UtcNow.ToString('o');
                acquisition='native-arm64-WindowsUpdate-Korean-Basic';attemptCount=1;workerPid=$PID;diagnosticOnly=$true;productInputVerified=$false;qualification=$false})
            $installed=@(Invoke-Arm64FodOnlineAttempt -ProcessMachine $hostRecord.controllerMachine -NativeMachine $hostRecord.nativeMachine -LogPath $dismLog)
            $attemptSeconds=$attemptClock.Elapsed.TotalSeconds
            if ($installed.Count -ne 1 -or $installed[0].RestartNeeded -isnot [bool]) { throw 'Original servicing restart result is missing or ambiguous.' }
            $restartNeeded=$installed[0].RestartNeeded
        } elseif ($beforeState -cne 'Installed') { throw 'Korean Basic is pending or unknown; no servicing attempt is authorized.' }
        $stage='capability-after'
        $after=@(Dism\Get-WindowsCapability -Online -Name $capabilityName -LogPath $dismLog -ErrorAction Stop | Where-Object Name -eq $capabilityName)
        $afterState=if ($after.Count -eq 1) { [string]$after[0].State } else { $null }
        $success=($afterState -ceq 'Installed' -and -not $restartNeeded)
        Save-Arm64FodObservation 'result.json' ([ordered]@{source=$binding;host=$hostRecord;nonce=$Nonce;capabilityName=$capabilityName;
            capabilityBefore=$beforeState;capabilityAfter=$afterState;restartNeeded=$restartNeeded;attempted=$attempted;attemptSeconds=$attemptSeconds;
            elapsedSeconds=$clock.Elapsed.TotalSeconds;success=$success;diagnosticOnly=$true;productInputVerified=$false;qualification=$false;sourceQualified=$false;storeQualified=$false})
        if (-not $success) { throw 'Observed capability/restart state does not qualify even this diagnostic attempt as completed.' }
    } catch {
        $original=$_
        try { Save-Arm64FodObservation 'worker-failure.json' ([ordered]@{source=$binding;host=$hostRecord;stage=$stage;elapsedSeconds=$clock.Elapsed.TotalSeconds;
            message=$original.Exception.Message;exceptionType=$original.Exception.GetType().FullName;hresult=$original.Exception.HResult;
            fullyQualifiedErrorId=$original.FullyQualifiedErrorId;scriptLine=$original.InvocationInfo.ScriptLineNumber;
            diagnosticOnly=$true;productInputVerified=$false;qualification=$false;sourceQualified=$false;storeQualified=$false}) }
        catch { Write-Warning ('Could not save failure receipt: '+$_.Exception.GetType().FullName) }
        throw $original
    }
    return
}

[void](New-Item -ItemType Directory -Path $out)
$nonceValue=[guid]::NewGuid().ToString('N');$parentStarted=(Get-Process -Id $PID).StartTime.ToUniversalTime().ToString('o')
Save-Arm64FodObservation 'controller.json' ([ordered]@{source=$binding;host=$hostRecord;nonce=$nonceValue;parentPid=$PID;parentStartedUtc=$parentStarted;
    maximumWorkerSeconds=1800;diagnosticOnly=$true;productInputVerified=$false;qualification=$false;sourceQualified=$false;storeQualified=$false})
Save-Arm64FodObservation 'before-environment.json' ([ordered]@{source=$binding;environment=(Get-Arm64FodEnvironment);
    diagnosticOnly=$true;productInputVerified=$false;qualification=$false;sourceQualified=$false;storeQualified=$false})
$windowsPowerShell=Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell/v1.0/powershell.exe'
Assert-Arm64FodPlainPath $windowsPowerShell
$arguments=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',('"'+$PSCommandPath+'"'),
    '-Output',('"'+$out+'"'),'-Worker','-Nonce',$nonceValue,'-ParentPid',[string]$PID)
$child=$null;$childStarted=$null;$clock=[Diagnostics.Stopwatch]::StartNew();$timedOut=$false;$failure=$null;$result=$null
try {
    $child=Start-Process -FilePath $windowsPowerShell -ArgumentList $arguments -PassThru -NoNewWindow `
        -RedirectStandardOutput (Join-Path $out 'worker.log') -RedirectStandardError (Join-Path $out 'worker-error.log')
    $childStarted=$child.StartTime
    while ($true) {
        $remaining=[int][Math]::Floor(1800000-$clock.Elapsed.TotalMilliseconds)
        if ($remaining -le 0) { $timedOut=$true;throw 'Owned diagnostic worker exceeded its 30-minute bound.' }
        $finished=$child.WaitForExit([Math]::Min(15000,$remaining))
        [long]$consoleBytes=0
        foreach ($name in @('worker.log','worker-error.log')) {
            $path=Join-Path $out $name;if (Test-Path -LiteralPath $path) { $consoleBytes+=(Get-Item -LiteralPath $path).Length }
        }
        $log=Join-Path $out 'dism.log'
        if ($consoleBytes -gt 4MB -or ((Test-Path -LiteralPath $log) -and (Get-Item -LiteralPath $log).Length -gt 32MB)) { throw 'Owned diagnostic logs exceeded their finite bounds; original bytes retained.' }
        if ($finished) { break }
        if ($clock.Elapsed.TotalMilliseconds -ge 1800000) { $timedOut=$true;throw 'Owned diagnostic worker exceeded its 30-minute bound.' }
        Write-Host ('ARM64 Korean FoD diagnostic: '+[int]$clock.Elapsed.TotalSeconds+' seconds; one original attempt, no retries.')
    }
    if ($child.ExitCode -ne 0) { throw 'Owned diagnostic worker failed; original exception and DISM output are retained.' }
    $result=Get-Content -LiteralPath (Join-Path $out 'result.json') -Raw | ConvertFrom-Json
    if ($result.source.sourceCommit -cne $binding.sourceCommit -or $result.source.sourceRun -cne $binding.sourceRun -or
        $result.source.runAttempt -cne $binding.runAttempt -or $result.source.job -cne $binding.job -or $result.nonce -cne $nonceValue -or
        $result.host.nativeMachine -ne 0xAA64 -or $result.host.controllerMachine -ne 0 -or
        $result.success -ne $true -or $result.capabilityAfter -cne 'Installed' -or $result.restartNeeded -ne $false -or
        $result.productInputVerified -ne $false -or $result.qualification -ne $false) { throw 'Worker result does not match its owned native diagnostic attempt.' }
} catch { $failure=$_ }
finally {
    $cleanup=[ordered]@{workerPid=if ($null -ne $child) { $child.Id } else { $null };killedOwnedWorker=$false;workerExited=$null;systemServicingMayContinue=$false}
    if ($null -ne $child) {
        try {
            if (-not $child.HasExited -and $child.StartTime -eq $childStarted) {
                $child.Kill();$cleanup.killedOwnedWorker=$true;$cleanup.systemServicingMayContinue=$true
                [void]$child.WaitForExit(10000)
            }
            $cleanup.workerExited=$child.HasExited
        } catch { $cleanup.errorType=$_.Exception.GetType().FullName }
        finally { $child.Dispose() }
    }
    try { Save-Arm64FodDiagnostics } catch { Write-Warning ('Diagnostic collection failed: '+$_.Exception.GetType().FullName) }
    try { Save-Arm64FodObservation 'controller-result.json' ([ordered]@{source=$binding;host=$hostRecord;timedOut=$timedOut;elapsedSeconds=$clock.Elapsed.TotalSeconds;
        success=($null -eq $failure);message=if ($null -ne $failure) { $failure.Exception.Message } else { $null };cleanup=$cleanup;
        diagnosticOnly=$true;productInputVerified=$false;qualification=$false;sourceQualified=$false;storeQualified=$false}) }
    catch {
        if ($null -eq $failure) { $failure=$_ }
        else { Write-Warning ('Could not save controller result: '+$_.Exception.GetType().FullName) }
    }
}
if ($null -ne $failure) { throw $failure }
