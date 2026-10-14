param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSource,
    [Parameter(Mandatory=$true)][string]$Output,
    [switch]$Worker
)
# Ephemeral hosted test prerequisite only. No product, CI identity, or result is rewritten.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repo=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$policy=Join-Path $PSScriptRoot 'korean_ime_readiness.py'
$bindingText=& python $policy --guard --source-root $repo --expected-source $ExpectedSource
if ($LASTEXITCODE -ne 0) { throw 'Actual hosted Windows Source guard rejected Korean setup.' }
$binding=$bindingText | ConvertFrom-Json
$outputPath=if ([IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path $repo $Output }
$out=[IO.Path]::GetFullPath($outputPath)
if (-not $out.StartsWith($repo+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Korean setup evidence must stay inside the actual Source checkout.'
}
$ancestor=$out
while ($ancestor -and $ancestor.StartsWith($repo,[StringComparison]::OrdinalIgnoreCase)) {
    if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Korean evidence path has a reparse point.'
    }
    $ancestor=[IO.Path]::GetDirectoryName($ancestor)
}
New-Item -ItemType Directory -Path $out -Force | Out-Null
if (-not $Worker) {
    # International/DISM run in Windows PowerShell; the parent bounds servicing to ten minutes.
    $arguments=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',('"'+$PSCommandPath+'"'),
        '-ExpectedSource',$ExpectedSource,'-Output',('"'+$out+'"'),'-Worker')
    $child=Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -PassThru -NoNewWindow `
        -RedirectStandardOutput (Join-Path $out 'setup.log') -RedirectStandardError (Join-Path $out 'setup-error.log')
    $started=$child.StartTime
    try {
        $clock=[Diagnostics.Stopwatch]::StartNew()
        while ($true) {
            $remainingMs=[Math]::Floor((600-$clock.Elapsed.TotalSeconds)*1000)
            if ($remainingMs -le 0) { throw 'Owned Korean setup worker exceeded its ten-minute bound.' }
            $waitMs=[int][Math]::Min(15000,[Math]::Max(1,$remainingMs))
            $finished=$child.WaitForExit($waitMs)
            [long]$logBytes=0
            foreach ($logName in @('setup.log','setup-error.log')) {
                $logPath=Join-Path $out $logName
                if (Test-Path -LiteralPath $logPath) { $logBytes+=(Get-Item -LiteralPath $logPath).Length }
            }
            if ($logBytes -gt 1MB) { throw 'Owned Korean setup worker logs exceeded their combined one-MiB bound.' }
            if ($clock.Elapsed.TotalSeconds -ge 600) { throw 'Owned Korean setup worker exceeded its ten-minute bound.' }
            if ($finished) { break }
            Write-Host ('한국어 입력 준비 진행: 실제 Windows 기능·등록 프로필 확인, '+[int]$clock.Elapsed.TotalSeconds+'초, 로그 '+$logBytes+'바이트')
        }
        if ($child.ExitCode -ne 0) { throw 'Actual Korean capability/profile setup failed; original bounded evidence is retained.' }
        & python $policy --source-root $repo --expected-source $ExpectedSource --record (Join-Path $out 'readiness.json')
        if ($LASTEXITCODE -ne 0) { throw 'Actual Korean setup evidence did not satisfy the fail-closed contract.' }
    } catch {
        if (-not $child.HasExited -and $child.StartTime -eq $started) { $child.Kill(); $child.WaitForExit(10000) | Out-Null }
        throw
    } finally { $child.Dispose() }
    return
}

# Windows PowerShell workers cannot depend on the parent's module availability.
# Use framework APIs shared by Windows PowerShell 5.1 and PowerShell 7.
function Get-OpenGeulFileSha256([string]$Path) {
    $stream=$null;$algorithm=$null
    try {
        $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
        $algorithm=[Security.Cryptography.SHA256]::Create()
        return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant()
    } finally {
        if ($null -ne $algorithm) { $algorithm.Dispose() }
        if ($null -ne $stream) { $stream.Dispose() }
    }
}
$stage='actual-host-observation'
$hostObservation=[ordered]@{source=$binding;workerPid=[int]$PID;
    scriptSha256=$null;
    powerShellVersion=[string]$PSVersionTable.PSVersion;elevated=$null;
    architectureQuerySucceeded=$null;nativeMachine=$null;controllerMachine=$null;
    systemDirectory=$null;capabilityMatches=$null;capabilityState=$null;
    productInputVerified=$false;sourceQualified=$false}
# These finite, source-owned reasons may be published. Raw exception messages,
# command invocations and environment values must never enter diagnostics.
$failureCodes=@{
    'Official online language capability servicing requires the hosted elevated user.'='elevation_required';
    'Actual OS/controller architecture is unavailable.'='architecture_query_failed';
    'Actual OS/controller machine disagrees with the authorized native Source job.'='architecture_mismatch';
    'Actual system directory is unavailable.'='system_directory_unavailable';
    'Named Korean Basic capability is absent/ambiguous on the actual host.'='capability_missing_or_ambiguous';
    'Actual Korean capability is pending/unknown.'='capability_pending_or_unknown';
    'Korean capability did not become Installed without a restart.'='capability_not_ready';
    'Exactly one genuinely registered native Microsoft Korean default profile is required.'='registered_native_profile_missing_or_ambiguous';
    'Current-user Korean language entries are ambiguous.'='user_language_ambiguous';
    'Observed Korean configuration failed the readiness policy.'='readiness_policy_rejected'
}
function Save-ObservedJson([string]$Name,$Value) {
    $json=$Value | ConvertTo-Json -Depth 12 -Compress
    if ([Text.Encoding]::UTF8.GetByteCount($json) -gt 32768) { throw 'Actual Korean setup evidence exceeded its bound.' }
    [IO.File]::WriteAllText((Join-Path $out $Name),$json,[Text.UTF8Encoding]::new($false))
}
try {
    $hostObservation.scriptSha256=Get-OpenGeulFileSha256 $PSCommandPath
    $stage='actual-host-elevation'
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $principal=[Security.Principal.WindowsPrincipal]::new($identity)
    $hostObservation.elevated=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    Save-ObservedJson 'host-observation.json' $hostObservation
    if (-not $hostObservation.elevated) {
        throw 'Official online language capability servicing requires the hosted elevated user.'
    }
    $stage='actual-host-architecture'
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class OpenGeulKoreanSetupHost {
    [DllImport("kernel32", SetLastError=true)] public static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32", SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)]
    public static extern bool IsWow64Process2(IntPtr p,out ushort processMachine,out ushort nativeMachine);
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern uint GetSystemDirectoryW(StringBuilder value,uint count);
}
'@
    [ushort]$controllerMachine=0;[ushort]$nativeMachine=0
    $hostObservation.architectureQuerySucceeded=[OpenGeulKoreanSetupHost]::IsWow64Process2([OpenGeulKoreanSetupHost]::GetCurrentProcess(),[ref]$controllerMachine,[ref]$nativeMachine)
    $hostObservation.nativeMachine=[int]$nativeMachine
    $hostObservation.controllerMachine=[int]$controllerMachine
    Save-ObservedJson 'host-observation.json' $hostObservation
    if (-not $hostObservation.architectureQuerySucceeded) {
        throw 'Actual OS/controller architecture is unavailable.'
    }
    $expectedMachine=if ($binding.architecture -eq 'arm64') { 0xAA64 } else { 0x8664 }
    $allowedController=if ($expectedMachine -eq 0xAA64) { @(0,0x8664) } else { @(0) }
    if ($nativeMachine -ne $expectedMachine -or $allowedController -notcontains [int]$controllerMachine) {
        throw 'Actual OS/controller machine disagrees with the authorized native Source job.'
    }
    $stage='actual-host-system-directory'
    $system=[Text.StringBuilder]::new(32768)
    $systemLength=[OpenGeulKoreanSetupHost]::GetSystemDirectoryW($system,$system.Capacity)
    if ($systemLength -eq 0 -or $systemLength -ge $system.Capacity) { throw 'Actual system directory is unavailable.' }
    $systemPath=[IO.Path]::GetFullPath($system.ToString())
    $hostObservation.systemDirectory=$systemPath
    Save-ObservedJson 'host-observation.json' $hostObservation
    $stage='actual-host-capability-query'
    $capabilityName='Language.Basic~~~ko-KR~0.0.1.0'
    $capability=@(Get-WindowsCapability -Online -Name $capabilityName -ErrorAction Stop | Where-Object Name -eq $capabilityName)
    $hostObservation.capabilityMatches=$capability.Count
    if ($capability.Count -eq 1) { $hostObservation.capabilityState=[string]$capability[0].State }
    Save-ObservedJson 'host-observation.json' $hostObservation
    if ($capability.Count -ne 1) { throw 'Named Korean Basic capability is absent/ambiguous on the actual host.' }
    $before=[string]$capability[0].State
    $stage='actual-host-user-language-query'
    $languages=Get-WinUserLanguageList -ErrorAction Stop
    Save-ObservedJson 'before.json' ([ordered]@{
        source=$binding;nativeMachine=[int]$nativeMachine;controllerMachine=[int]$controllerMachine;
        capabilityName=$capabilityName;capabilityState=$before;userSid=$identity.User.Value;
        languages=@($languages | ForEach-Object { [ordered]@{tag=[string]$_.LanguageTag;inputMethodTips=@($_.InputMethodTips)} });
        productInputVerified=$false;sourceQualified=$false
    })
    $stage='official-capability-install'
    $restartNeeded=$false
    if ($before -eq 'NotPresent') {
        $installed=Add-WindowsCapability -Online -Name $capabilityName -ErrorAction Stop
        $restartNeeded=[bool]$installed.RestartNeeded
    } elseif ($before -ne 'Installed') { throw 'Actual Korean capability is pending/unknown.' }
    $after=@(Get-WindowsCapability -Online -Name $capabilityName -ErrorAction Stop | Where-Object Name -eq $capabilityName)
    if ($after.Count -ne 1 -or [string]$after[0].State -ne 'Installed' -or $restartNeeded) {
        throw 'Korean capability did not become Installed without a restart.'
    }
    $stage='registered-native-Microsoft-profile'
    $generated=New-WinUserLanguageList -Language 'ko-KR' -ErrorAction Stop
    $registry=[Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,[Microsoft.Win32.RegistryView]::Registry64)
    $profiles=@()
    try {
        foreach ($tip in @($generated[0].InputMethodTips)) {
            if ($tip -notmatch '^0412:(\{[0-9a-fA-F-]{36}\})(\{[0-9a-fA-F-]{36}\})$') { continue }
            $provider=$Matches[1];$profileGuid=$Matches[2]
            $registration=$registry.OpenSubKey('SOFTWARE\Microsoft\CTF\TIP\'+$provider+'\LanguageProfile\0x00000412\'+$profileGuid)
            $server=$registry.OpenSubKey('SOFTWARE\Classes\CLSID\'+$provider+'\InprocServer32')
            try {
                if ($null -eq $registration -or $null -eq $server) { continue }
                $serverValue=$server.GetValue('')
                if ($serverValue -isnot [string]) { continue }
                $component=[IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($serverValue))
                if (-not $component.StartsWith($systemPath+'\',[StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $component -PathType Leaf)) { continue }
                $check=$component
                while ($check.StartsWith($systemPath,[StringComparison]::OrdinalIgnoreCase)) {
                    if ((Get-Item -LiteralPath $check).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Registered IME component has a reparse point.' }
                    $check=[IO.Path]::GetDirectoryName($check)
                }
                $item=Get-Item -LiteralPath $component
                if ($item.Length -le 0 -or $item.Length -gt 64MB) { continue }
                $sha=Get-OpenGeulFileSha256 $component
                $signature=Get-AuthenticodeSignature -LiteralPath $component
                if ([string]$signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate) { continue }
                $subject=[string]$signature.SignerCertificate.Subject
                if ($subject -notmatch '(?:^|,\s*)O=Microsoft Corporation(?:,|$)') { continue }
                $bytes=[IO.File]::ReadAllBytes($component)
                if ($bytes.Length -lt 64 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) { continue }
                $pe=[BitConverter]::ToInt32($bytes,0x3c)
                if ($pe -lt 64 -or $pe -gt $bytes.Length-6 -or [BitConverter]::ToUInt32($bytes,$pe) -ne 0x4550) { continue }
                $machine=[int][BitConverter]::ToUInt16($bytes,$pe+4)
                if ($machine -ne $nativeMachine -or (Get-OpenGeulFileSha256 $component) -ne $sha) { continue }
                $profiles+=,[ordered]@{inputTip=[string]$tip;providerClsid=$provider;profileGuid=$profileGuid;languageId=0x0412;
                    registered=$true;registryView='Registry64';component=[ordered]@{path=$component;bytes=[long]$item.Length;
                        sha256=$sha;machine=$machine;signatureStatus=[string]$signature.Status;signerSubject=$subject}}
            } finally {
                if ($null -ne $registration) { $registration.Dispose() }
                if ($null -ne $server) { $server.Dispose() }
            }
        }
    } finally { $registry.Dispose() }
    if ($profiles.Count -ne 1) { throw 'Exactly one genuinely registered native Microsoft Korean default profile is required.' }
    $profile=$profiles[0]
    $stage='current-user-language-configuration'
    $languages=Get-WinUserLanguageList -ErrorAction Stop
    $korean=@($languages | Where-Object LanguageTag -eq 'ko-KR')
    if ($korean.Count -eq 0) { $languages.Add($generated[0]) }
    elseif ($korean.Count -ne 1) { throw 'Current-user Korean language entries are ambiguous.' }
    $korean=@($languages | Where-Object LanguageTag -eq 'ko-KR')
    if ($korean[0].InputMethodTips -notcontains $profile.inputTip) { $korean[0].InputMethodTips.Add($profile.inputTip) }
    Set-WinUserLanguageList -LanguageList $languages -Force -ErrorAction Stop
    Set-WinDefaultInputMethodOverride -InputTip $profile.inputTip -ErrorAction Stop
    $observedLanguages=Get-WinUserLanguageList -ErrorAction Stop
    $observedTips=@($observedLanguages | Where-Object LanguageTag -eq 'ko-KR' | ForEach-Object { $_.InputMethodTips })
    $default=Get-WinDefaultInputMethodOverride -ErrorAction Stop
    $record=[ordered]@{formatVersion=1;source=$binding;nativeMachine=[int]$nativeMachine;controllerMachine=[int]$controllerMachine;
        systemDirectory=$systemPath;capabilityName=$capabilityName;capabilityBefore=$before;capabilityAfter=[string]$after[0].State;
        restartNeeded=$restartNeeded;userLanguageConfigured=($observedTips -contains $profile.inputTip);
        defaultInputTip=[string]$default.InputMethodTip;configuredInputTips=$observedTips;profile=$profile;
        profileScope='current-user configured; target HWND/thread unverified';productInputVerified=$false;sourceQualified=$false}
    Save-ObservedJson 'readiness.json' $record
    & python $policy --source-root $repo --expected-source $ExpectedSource --record (Join-Path $out 'readiness.json')
    if ($LASTEXITCODE -ne 0) { throw 'Observed Korean configuration failed the readiness policy.' }
} catch {
    $message=[string]$_.Exception.Message
    $failureCode='unclassified'
    if ($failureCodes.ContainsKey($message)) { $failureCode=$failureCodes[$message] }
    $scriptLine=if ($null -ne $_.InvocationInfo) { [int]$_.InvocationInfo.ScriptLineNumber } else { 0 }
    Save-ObservedJson 'host-observation.json' $hostObservation
    Save-ObservedJson 'failure.json' ([ordered]@{source=$binding;stage=$stage;failureType=$_.Exception.GetType().FullName;
        failureCode=$failureCode;hresult=[int]$_.Exception.HResult;scriptLine=$scriptLine;
        productInputVerified=$false;sourceQualified=$false})
    Write-Error ('Actual hosted Korean setup failed at '+$stage+'; bounded original observations are retained.')
    exit 1
}
