param(
    [Parameter(Mandatory=$true)][string]$Output,
    [switch]$Worker
)
# Ephemeral Suite CI prerequisite only. Target input and Store qualification
# remain separate from installation and current-user profile configuration.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repo=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or
    -not [Environment]::Is64BitProcess -or
    $env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
    $env:RUNNER_OS -cne 'Windows' -or $env:GITHUB_JOB -cne 'windows-suite' -or
    $env:GITHUB_SHA -cnotmatch '\A[0-9a-f]{40}\z') {
    throw 'Korean prerequisite setup requires the actual hosted Windows Suite job.'
}
$head=@(& git -C $repo rev-parse --verify HEAD)
if ($LASTEXITCODE -ne 0 -or $head.Count -ne 1 -or $head[0] -cne $env:GITHUB_SHA) {
    throw 'Hosted Windows Suite SHA differs from the actual checkout HEAD.'
}
$binding=[ordered]@{sourceCommit=$head[0];job=$env:GITHUB_JOB;repository=$env:GITHUB_REPOSITORY;
    sourceRun=$env:GITHUB_RUN_ID;runAttempt=$env:GITHUB_RUN_ATTEMPT}
$out=[IO.Path]::GetFullPath($(if ([IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path $repo $Output }))
if (-not $out.StartsWith($repo+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or
    $out.IndexOfAny([char[]]@('"',"`r","`n")) -ge 0) {
    throw 'Suite prerequisite evidence must stay inside the actual checkout.'
}
function Assert-SuitePlainPath([string]$Path) {
    $check=[IO.Path]::GetFullPath($Path)
    while ($check) {
        if ((Test-Path -LiteralPath $check) -and
            ((Get-Item -LiteralPath $check).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Suite prerequisite path contains a reparse point.'
        }
        $check=[IO.Path]::GetDirectoryName($check)
    }
}
Assert-SuitePlainPath $out
New-Item -ItemType Directory -Path $out -Force | Out-Null
function Save-SuiteObservation([string]$Name,$Value) {
    $json=$Value | ConvertTo-Json -Depth 12 -Compress
    if ([Text.Encoding]::UTF8.GetByteCount($json) -gt 32768) { throw 'Suite prerequisite observation exceeds its bound.' }
    [IO.File]::WriteAllText((Join-Path $out $Name),$json,[Text.UTF8Encoding]::new($false))
}
if (-not $Worker) {
    foreach ($name in @('readiness.json','failure.json','setup.log','setup-error.log','dism.log')) {
        if (Test-Path -LiteralPath (Join-Path $out $name)) { throw 'Preserve existing Suite prerequisite evidence; use a new output directory.' }
    }
    $windowsPowerShell=Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell/v1.0/powershell.exe'
    Assert-SuitePlainPath $windowsPowerShell
    $arguments=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',('"'+$PSCommandPath+'"'),
        '-Output',('"'+$out+'"'),'-Worker')
    $child=Start-Process -FilePath $windowsPowerShell -ArgumentList $arguments -PassThru -NoNewWindow `
        -RedirectStandardOutput (Join-Path $out 'setup.log') -RedirectStandardError (Join-Path $out 'setup-error.log')
    $started=$child.StartTime
    $clock=[Diagnostics.Stopwatch]::StartNew()
    try {
        while ($true) {
            $remaining=[int][Math]::Floor(600000-$clock.Elapsed.TotalMilliseconds)
            if ($remaining -le 0) { throw 'Owned Suite Korean prerequisite worker exceeded ten minutes.' }
            $finished=$child.WaitForExit([Math]::Min(15000,$remaining))
            [long]$consoleBytes=0
            foreach ($name in @('setup.log','setup-error.log')) {
                $path=Join-Path $out $name
                if (Test-Path -LiteralPath $path) { $consoleBytes+=(Get-Item -LiteralPath $path).Length }
            }
            $dismPath=Join-Path $out 'dism.log'
            if ($consoleBytes -gt 1MB -or ((Test-Path -LiteralPath $dismPath) -and (Get-Item -LiteralPath $dismPath).Length -gt 8MB)) {
                throw 'Owned Suite Korean prerequisite logs exceeded their bounds; original logs are retained.'
            }
            if ($clock.Elapsed.TotalSeconds -ge 600) { throw 'Owned Suite Korean prerequisite worker exceeded ten minutes.' }
            if ($finished) { break }
            Write-Host ('Suite Korean prerequisite setup: '+[int]$clock.Elapsed.TotalSeconds+' seconds; original logs retained.')
        }
        if ($child.ExitCode -ne 0) { throw 'Suite Korean prerequisite worker failed; inspect the original setup logs and failure.json.' }
        $record=Get-Content -LiteralPath (Join-Path $out 'readiness.json') -Raw | ConvertFrom-Json
        if ($record.source.sourceCommit -cne $head[0] -or $record.source.job -cne 'windows-suite' -or
            $record.suiteOnly -ne $true -or $record.productInputVerified -ne $false -or
            $record.storeQualified -ne $false -or $record.capabilityAfter -cne 'Installed' -or
            $record.restartNeeded -ne $false -or $record.userLanguageConfigured -ne $true -or
            $record.profile.registered -ne $true) {
            throw 'Suite prerequisite worker did not produce a ready, Suite-only observation.'
        }
    } catch {
        if (-not $child.HasExited -and $child.StartTime -eq $started) {
            $child.Kill()
            [void]$child.WaitForExit(10000)
        }
        Save-SuiteObservation 'controller-failure.json' ([ordered]@{source=$binding;message=$_.Exception.Message;
            elapsedSeconds=[int]$clock.Elapsed.TotalSeconds;suiteOnly=$true;productInputVerified=$false;storeQualified=$false})
        throw
    } finally { $child.Dispose() }
    return
}

function Get-SuiteFileSha256([string]$Path) {
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
function Test-SuiteKoreanLanguageTag([AllowNull()][object]$Tag) {
    return ($Tag -is [string] -and ($Tag.Equals('ko-KR',[StringComparison]::OrdinalIgnoreCase) -or
        $Tag.Equals('ko',[StringComparison]::OrdinalIgnoreCase)))
}
$stage='native-host'
$servicingFailed=$false
$servicingStartedUtc=$null
try {
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $principal=[Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Online Windows capability servicing requires the hosted elevated user.'
    }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SuiteKoreanSetupHost {
    [DllImport("kernel32")] public static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32",SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)]
    public static extern bool IsWow64Process2(IntPtr process,out ushort processMachine,out ushort nativeMachine);
}
'@
    [UInt16]$processMachine=0;[UInt16]$nativeMachine=0
    if (-not [SuiteKoreanSetupHost]::IsWow64Process2([SuiteKoreanSetupHost]::GetCurrentProcess(),[ref]$processMachine,[ref]$nativeMachine) -or
        $processMachine -ne 0 -or @(0x8664,0xAA64) -notcontains [int]$nativeMachine) {
        throw 'Suite Korean setup requires native 64-bit Windows PowerShell.'
    }
    $systemPath=[IO.Path]::GetFullPath([Environment]::SystemDirectory)
    $modules=Join-Path $systemPath 'WindowsPowerShell/v1.0/Modules'
    foreach ($name in @('Dism','International','Microsoft.PowerShell.Security')) {
        $manifest=Join-Path $modules ($name+'/'+$name+'.psd1')
        Assert-SuitePlainPath $manifest
        Import-Module -Name $manifest -ErrorAction Stop
    }
    $signatureCommand=Get-Command 'Microsoft.PowerShell.Security\Get-AuthenticodeSignature' -CommandType Cmdlet -ErrorAction Stop
    if ($signatureCommand.ImplementingType.FullName -cne 'Microsoft.PowerShell.Commands.GetAuthenticodeSignatureCommand') {
        throw 'Built-in Authenticode cmdlet identity is unavailable.'
    }
    $capabilityName='Language.Basic~~~ko-KR~0.0.1.0'
    $dismLog=Join-Path $out 'dism.log'
    $stage='capability-before'
    $capability=@(Dism\Get-WindowsCapability -Online -Name $capabilityName -LogPath $dismLog -ErrorAction Stop |
        Where-Object Name -eq $capabilityName)
    if ($capability.Count -ne 1) { throw 'Named Korean Basic capability is missing or ambiguous.' }
    $before=[string]$capability[0].State
    $languages=International\Get-WinUserLanguageList -ErrorAction Stop
    Save-SuiteObservation 'before.json' ([ordered]@{source=$binding;capabilityName=$capabilityName;capabilityBefore=$before;
        userSid=$identity.User.Value;nativeMachine=[int]$nativeMachine;
        languages=@($languages | ForEach-Object { [ordered]@{tag=[string]$_.LanguageTag;inputMethodTips=@($_.InputMethodTips)} });
        suiteOnly=$true;productInputVerified=$false;storeQualified=$false})
    $stage='capability-install'
    $restartNeeded=$false
    $acquisition='already-installed'
    if ($before -eq 'NotPresent') {
        $stage='matching-official-server-media'
        $version=Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
        if ($nativeMachine -ne 0x8664 -or $version.CurrentBuildNumber -cne '26100' -or
            $version.InstallationType -notin @('Server','Server Core')) {
            throw 'Pinned offline language FOD media requires actual Server 2025 amd64 build 26100.'
        }
        $sourceRoot=Join-Path $out 'fod-source'
        $sourceHelper=Join-Path $PSScriptRoot 'korean_fod_source.py'
        & python $sourceHelper --output $sourceRoot
        if ($LASTEXITCODE -ne 0) { throw 'Pinned official Server language FOD source acquisition failed.' }
        $sourceReceipt=Get-Content -LiteralPath (Join-Path $sourceRoot 'source-acquisition.json') -Raw | ConvertFrom-Json
        $sourceDirectory=Join-Path $sourceRoot 'LanguagesAndOptionalFeatures'
        Assert-SuitePlainPath $sourceDirectory
        if ($sourceReceipt.success -ne $true -or $sourceReceipt.productInputVerified -ne $false -or
            $sourceReceipt.storeQualified -ne $false -or $sourceReceipt.packages.Count -ne 9 -or
            [IO.Path]::GetFullPath($sourceReceipt.sourceDirectory) -cne [IO.Path]::GetFullPath($sourceDirectory)) {
            throw 'Official offline FOD acquisition receipt does not identify the owned source.'
        }
        $acquisition='pinned-official-Server2025-amd64-26100-language-FOD-source'
        $stage='offline-capability-install'
        # Language FODs are complete monolithic CABs. Preserve selected original
        # Server metadata too; DISM validates package catalogs and must prove
        # this source is sufficient. Never query WU or alter its host policy.
        $servicingStartedUtc=[DateTime]::UtcNow
        $servicingFailed=$true
        $installed=@(Dism\Add-WindowsCapability -Online -Name $capabilityName -Source $sourceDirectory -LimitAccess -LogPath $dismLog -ErrorAction Stop)
        $servicingFailed=$false
        if ($installed.Count -ne 1 -or $installed[0].RestartNeeded -isnot [bool]) { throw 'Windows servicing restart status is unavailable.' }
        $restartNeeded=$installed[0].RestartNeeded
    } elseif ($before -ne 'Installed') { throw 'Korean Basic capability is pending or unknown.' }
    $stage='capability-after'
    $after=@(Dism\Get-WindowsCapability -Online -Name $capabilityName -LogPath $dismLog -ErrorAction Stop |
        Where-Object Name -eq $capabilityName)
    Save-SuiteObservation 'capability.json' ([ordered]@{source=$binding;capabilityBefore=$before;
        capabilityAfter=if ($after.Count -eq 1) { [string]$after[0].State } else { $null };
        restartNeeded=$restartNeeded;suiteOnly=$true;productInputVerified=$false;storeQualified=$false})
    if ($after.Count -ne 1 -or [string]$after[0].State -ne 'Installed' -or $restartNeeded) {
        throw 'Korean Basic capability did not become Installed without restart.'
    }
    $stage='registered-Microsoft-TSF-profile'
    $generated=International\New-WinUserLanguageList -Language 'ko-KR' -ErrorAction Stop
    if ($generated.Count -ne 1 -or -not (Test-SuiteKoreanLanguageTag $generated[0].LanguageTag)) {
        throw 'Windows did not generate one Korean language entry.'
    }
    $registry=[Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,[Microsoft.Win32.RegistryView]::Registry64)
    $profiles=@()
    $guidPattern='\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}'
    try {
        foreach ($tip in @($generated[0].InputMethodTips)) {
            if ($tip -notmatch ('\A0412:('+$guidPattern+')('+$guidPattern+')\z')) { continue }
            $provider=$Matches[1];$profileGuid=$Matches[2]
            $registration=$registry.OpenSubKey('SOFTWARE\Microsoft\CTF\TIP\'+$provider+'\LanguageProfile\0x00000412\'+$profileGuid)
            $server=$registry.OpenSubKey('SOFTWARE\Classes\CLSID\'+$provider+'\InprocServer32')
            try {
                if ($null -eq $registration -or $null -eq $server) { continue }
                $serverValue=$server.GetValue('')
                if ($serverValue -isnot [string]) { continue }
                $component=[IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($serverValue))
                if (-not $component.StartsWith($systemPath+'\',[StringComparison]::OrdinalIgnoreCase) -or
                    -not (Test-Path -LiteralPath $component -PathType Leaf)) { continue }
                Assert-SuitePlainPath $component
                $item=Get-Item -LiteralPath $component
                if ($item.Length -lt 64 -or $item.Length -gt 64MB) { continue }
                $sha=Get-SuiteFileSha256 $component
                $signature=& $signatureCommand -LiteralPath $component
                if ([string]$signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate) { continue }
                $subject=[string]$signature.SignerCertificate.Subject
                if ($subject -notmatch '(?:^|,\s*)O=Microsoft Corporation(?:,|$)') { continue }
                $bytes=[IO.File]::ReadAllBytes($component)
                if ($bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) { continue }
                $pe=[BitConverter]::ToInt32($bytes,0x3c)
                if ($pe -lt 64 -or $pe -gt $bytes.Length-6 -or [BitConverter]::ToUInt32($bytes,$pe) -ne 0x4550) { continue }
                $machine=[int][BitConverter]::ToUInt16($bytes,$pe+4)
                if ($machine -ne $nativeMachine -or (Get-SuiteFileSha256 $component) -cne $sha) { continue }
                $profiles+=,[ordered]@{inputTip=[string]$tip;providerClsid=$provider;profileGuid=$profileGuid;languageId=0x0412;
                    registered=$true;registryView='Registry64';component=[ordered]@{path=$component;sha256=$sha;
                        signatureStatus=[string]$signature.Status;signerSubject=$subject;machine=$machine;bytes=[long]$item.Length}}
            } finally {
                if ($null -ne $registration) { $registration.Dispose() }
                if ($null -ne $server) { $server.Dispose() }
            }
        }
    } finally { $registry.Dispose() }
    if ($profiles.Count -ne 1) { throw 'Exactly one registered native Microsoft Korean TSF default profile is required.' }
    $profile=$profiles[0]
    $stage='current-user-language-configuration'
    $languages=International\Get-WinUserLanguageList -ErrorAction Stop
    $korean=@($languages | Where-Object { Test-SuiteKoreanLanguageTag $_.LanguageTag })
    if ($korean.Count -eq 0) { $languages.Add($generated[0]) }
    elseif ($korean.Count -ne 1) { throw 'Current-user Korean language entries are ambiguous.' }
    $korean=@($languages | Where-Object { Test-SuiteKoreanLanguageTag $_.LanguageTag })
    if ($korean.Count -ne 1) { throw 'Current-user Korean language configuration is unavailable.' }
    if ($korean[0].InputMethodTips -notcontains $profile.inputTip) { $korean[0].InputMethodTips.Add($profile.inputTip) }
    International\Set-WinUserLanguageList -LanguageList $languages -Force -ErrorAction Stop
    $observed=International\Get-WinUserLanguageList -ErrorAction Stop
    $observedKorean=@($observed | Where-Object { Test-SuiteKoreanLanguageTag $_.LanguageTag })
    if ($observedKorean.Count -ne 1 -or @($observedKorean[0].InputMethodTips) -notcontains $profile.inputTip) {
        throw 'Read-back did not confirm the selected current-user Microsoft Korean TSF profile.'
    }
    Save-SuiteObservation 'readiness.json' ([ordered]@{formatVersion=1;source=$binding;
        nativeMachine=[int]$nativeMachine;systemDirectory=$systemPath;capabilityName=$capabilityName;
        capabilityBefore=$before;capabilityAfter=[string]$after[0].State;restartNeeded=$restartNeeded;acquisition=$acquisition;
        userLanguageConfigured=$true;configuredInputTips=@($observedKorean[0].InputMethodTips);profile=$profile;
        profileScope='current-user configured; target HWND/thread unverified';
        suiteOnly=$true;productInputVerified=$false;sourceQualified=$false;storeQualified=$false})
} catch {
    $originalFailure=$_
    Save-SuiteObservation 'failure.json' ([ordered]@{source=$binding;stage=$stage;message=$originalFailure.Exception.Message;
        failureType=$originalFailure.Exception.GetType().FullName;scriptLine=[int]$originalFailure.InvocationInfo.ScriptLineNumber;
        suiteOnly=$true;productInputVerified=$false;sourceQualified=$false;storeQualified=$false})
    if ($servicingFailed -and $null -ne $servicingStartedUtc) {
        # One owned, read-only collector runs only after the actual DISM call
        # throws. It cannot replace the original error or extend setup retries.
        $diagnosticProcess=$null
        $diagnosticStarted=$null
        $collection=[ordered]@{source=$binding;status='collector-unavailable';exitCode=$null;
            suiteOnly=$true;productInputVerified=$false;sourceQualified=$false;storeQualified=$false}
        try {
            $collector=Join-Path $PSScriptRoot 'korean_servicing_diagnostics.py'
            $diagnostics=Join-Path $out 'servicing-diagnostics'
            $arguments=@(('"'+$collector+'"'),'--output',('"'+$diagnostics+'"'),
                '--since-utc',$servicingStartedUtc.ToString('yyyy-MM-ddTHH:mm:ss.fffffffZ'))
            $python=(Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
            $diagnosticProcess=Start-Process -FilePath $python -ArgumentList $arguments -PassThru -NoNewWindow `
                -RedirectStandardOutput (Join-Path $out 'diagnostic-collector.log') `
                -RedirectStandardError (Join-Path $out 'diagnostic-collector-error.log')
            $diagnosticStarted=$diagnosticProcess.StartTime
            if ($diagnosticProcess.WaitForExit(10000)) {
                $collection.exitCode=[int]$diagnosticProcess.ExitCode
                $collection.status=if ($collection.exitCode -eq 0) { 'collector-completed' } else { 'collector-failed' }
            } else { $collection.status='collector-timeout' }
        } catch { $collection.status='collector-unavailable' }
        finally {
            if ($null -ne $diagnosticProcess) {
                try {
                    if (-not $diagnosticProcess.HasExited -and $diagnosticProcess.StartTime -eq $diagnosticStarted) {
                        $diagnosticProcess.Kill()
                        [void]$diagnosticProcess.WaitForExit(2000)
                    }
                } catch { $collection.status='collector-cleanup-unavailable' }
                $diagnosticProcess.Dispose()
            }
            try { Save-SuiteObservation 'diagnostic-collection.json' $collection } catch { }
        }
    }
    throw $originalFailure
}
