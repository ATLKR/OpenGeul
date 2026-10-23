[CmdletBinding()]
param(
    [string]$Workspace = $env:GITHUB_WORKSPACE,
    [string]$RunnerTemp = $env:RUNNER_TEMP
)
$ErrorActionPreference = 'Stop'
$Native35Workspace = $Workspace
$Native35RunnerTemp = $RunnerTemp
$Native35DirectInvocation = $MyInvocation.InvocationName -ne '.'
$Native35LegacyCaller = Join-Path $PSScriptRoot 'prepare-native31.ps1'
# Reuse the immutable bounded process, source proof, and I/O-only staging code.
. $Native35LegacyCaller -Workspace $Workspace -RunnerTemp $RunnerTemp
$Native31Critical = @($Native31Critical) + @(
    'e2e/native35_input_witness_prepare.py',
    'suite/scripts/prepare-native35-input-witness.ps1',
    '.github/workflows/suite-native35-input-witness.yml'
)

function Assert-Native35DiagnosticContext {
    $ref = 'refs/heads/work/native35-arm64-input-witness'
    $expected = @{ GITHUB_ACTIONS='true'; RUNNER_ENVIRONMENT='github-hosted'; RUNNER_OS='Windows';
        RUNNER_ARCH='ARM64'; GITHUB_REPOSITORY='ATLKR/OpenGeul'; GITHUB_EVENT_NAME='push';
        GITHUB_JOB='windows-suite'; GITHUB_REF=$ref;
        GITHUB_WORKFLOW_REF="ATLKR/OpenGeul/.github/workflows/suite-native35-input-witness.yml@$ref";
        GITHUB_RUN_ATTEMPT='1'; GITHUB_ACTOR='ATLKR'; GITHUB_ACTOR_ID='65988341' }
    foreach ($key in $expected.Keys) {
        Assert-Native31 ([Environment]::GetEnvironmentVariable($key) -ceq $expected[$key]) "Exact diagnostic binding differs: $key"
    }
    Assert-Native31 ($env:GITHUB_SHA -cmatch '\A[0-9a-f]{40}\z' -and $env:GITHUB_SHA -cne ('0' * 40) -and
        $env:GITHUB_WORKFLOW_SHA -ceq $env:GITHUB_SHA -and $env:GITHUB_RUN_ID -cmatch '\A[1-9][0-9]{0,19}\z') 'Diagnostic source/run binding differs.'
    $eventPath = Assert-Native31Path $env:GITHUB_EVENT_PATH
    Assert-Native31 ((Get-Item -LiteralPath $eventPath).Length -le 262144) 'Event exceeds setup bound.'
    $event = Get-Content -LiteralPath $eventPath -Raw | ConvertFrom-Json
    Assert-Native31 ($event.repository.full_name -ceq 'ATLKR/OpenGeul' -and $event.repository.private -is [bool] -and
        -not $event.repository.private -and $event.repository.id -gt 0 -and $event.sender.login -ceq 'ATLKR' -and
        $event.sender.id -eq 65988341 -and $event.sender.type -ceq 'User' -and $event.ref -ceq $ref -and
        $event.deleted -is [bool] -and -not $event.deleted -and $event.after -ceq $env:GITHUB_SHA) 'Actual public owner diagnostic push payload differs.'
}

function Invoke-Native35InputWitnessPreparation([string]$Root, [string]$Temp) {
    $Root = Assert-Native31Path $Root
    $Temp = Assert-Native31Path $Temp
    Assert-Native31 ((Test-Path -LiteralPath $Root -PathType Container) -and
        (Test-Path -LiteralPath $Temp -PathType Container)) 'Owned source/temp roots unavailable.'
    Assert-Native31 ($env:GITHUB_RUN_ID -cmatch '\A[1-9][0-9]{0,19}\z' -and
        $env:GITHUB_RUN_ATTEMPT -ceq '1') 'Fresh diagnostic run path identity required.'
    $suffix = "$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT"
    $setup = Join-Path $Temp "suite-input-witness-setup-$suffix"
    $control = Join-Path $Temp "suite-input-witness-preparation-$suffix"
    $source = Join-Path $Temp "suite-input-witness-source-$suffix"
    foreach ($path in @($setup, $control, $source)) {
        $null = Assert-Native31Path $path
        Assert-Native31 (-not (Test-Path -LiteralPath $path)) 'Fresh diagnostic setup/control/source paths required.'
    }
    $null = New-Item -ItemType Directory -Path $setup
    $state = @{ Clock=[Diagnostics.Stopwatch]::StartNew(); Commands=[Collections.Generic.List[object]]::new() }
    $primary = $null; $stagingFailure = $null; $proof = $null
    Write-Native31Json (Join-Path $setup '00-setup-start.json') @{
        schemaVersion=1; kind='native35-input-witness-preparation-caller'; architecture='arm64';
        sourceCommit=$env:GITHUB_SHA; runId=$env:GITHUB_RUN_ID; runAttempt=$env:GITHUB_RUN_ATTEMPT;
        mainRoot=$Root; cleanRoot=$source; controlRoot=$control;
        setupSeconds=30; controllerSeconds=120; launchContainmentSeconds=125; stagingSeconds=15;
        diagnosticOnly=$true; success=$false; qualification=$false; privacyPreparationQualified=$false;
        hostReadyQualified=$false; productQualified=$false; officeReplacementCertified=$false;
        mainNativePrivacySetupPerformed=$false; diagnosticPreparationSeparatelyRecorded=$true;
        diagnosticPreparationEvidence='.work/suite-input-witness-preparation/'
    }
    try {
        Assert-Native35DiagnosticContext
        $proof = New-Native31Source $Root $source $setup $state
        Assert-Native31 ($state.Clock.Elapsed.TotalSeconds -lt 30) 'Diagnostic source setup budget exceeded; no controller started.'
        Write-Native31Json (Join-Path $setup '10-source-setup.json') @{
            success=$true; proof=$proof; commands=$state.Commands; seconds=$state.Clock.Elapsed.TotalSeconds
        }
        $python = (Get-Command python -CommandType Application | Select-Object -First 1).Source
        $argv = @('-B', (Join-Path $source 'e2e/native35_input_witness_prepare.py'), '--prepare-privacy', '--output', $control)
        $env:NATIVE31_PWSH = (Get-Process -Id $PID).Path
        # Launch containment includes startup; the existing core keeps its sole120s budget.
        $result = [Native31BoundedProcess]::Run($python, $argv, $source, 125000, 8192)
        Write-Native31Json (Join-Path $setup '20-entry-exit.json') @{
            argv=$argv; executable=$python; cwd=$source; exitCode=$result.ExitCode;
            seconds=$result.Seconds; timedOut=$result.TimedOut; forced=$result.Forced; failure=$result.Failure;
            stdout=[Text.Encoding]::UTF8.GetString($result.Stdout); stderr=[Text.Encoding]::UTF8.GetString($result.Stderr)
        }
        Assert-Native31 ($result.ExitCode -eq 0 -and -not $result.TimedOut -and -not $result.Forced -and
            -not $result.Failure) 'Diagnostic desktop preparation entry failed.'
    } catch {
        $primary = $_
        try {
            Write-Native31Json (Join-Path $setup '90-caller-failure.json') @{
                failure=$primary.Exception.Message; commands=$state.Commands; proof=$proof
            }
        } catch { $primary.Exception.Data['receiptFailure'] = $_.Exception.Message }
    } finally {
        try {
            # This unchanged StageOnly worker cannot run a controller or native action.
            $stager = if ($proof) { Join-Path $source 'suite/scripts/prepare-native31.ps1' } else { $Native35LegacyCaller }
            $stageArgv = @('-NoLogo', '-NoProfile', '-NonInteractive', '-File', $stager, '-StageOnly',
                '-SetupEvidence', $setup, '-ControlEvidence', $control,
                '-StagingDestination', (Join-Path $Root '.work/suite-input-witness-preparation'))
            $staged = [Native31BoundedProcess]::Run((Get-Process -Id $PID).Path, $stageArgv, $Root, 15000, 8192)
            Assert-Native31 ($staged.ExitCode -eq 0 -and -not $staged.Failure -and -not $staged.Forced -and
                -not $staged.TimedOut) ('Diagnostic evidence staging failed: ' + [Text.Encoding]::UTF8.GetString($staged.Stderr))
        } catch {
            $stagingFailure = $_
            try {
                Write-Native31Json (Join-Path $setup '99-staging-failure.json') @{
                    primaryFailure=$(if ($primary) { $primary.Exception.Message } else { $null });
                    stagingFailure=$stagingFailure.Exception.Message
                }
            } catch { $stagingFailure.Exception.Data['receiptFailure'] = $_.Exception.Message }
        }
    }
    if ($primary) { throw $primary }
    if ($stagingFailure) { throw $stagingFailure }
}

if ($Native35DirectInvocation) {
    Invoke-Native35InputWitnessPreparation $Native35Workspace $Native35RunnerTemp
}
