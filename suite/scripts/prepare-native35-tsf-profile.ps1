[CmdletBinding()]
param(
    [ValidateSet('arm64', 'x64')][string]$Architecture,
    [string]$Workspace = $env:GITHUB_WORKSPACE,
    [string]$RunnerTemp = $env:RUNNER_TEMP,
    [switch]$StageOnly,
    [string]$SetupEvidence,
    [string]$ControlEvidence,
    [string]$StagingDestination
)
$ErrorActionPreference = 'Stop'

# Bounded redirected binary streams, exact owned Process handle/tree only.
# Each call's timeout includes termination and pipe collection; no background checkout.
if (-not ('Native31BoundedProcess' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
public sealed class Native31ProcessResult {
    public int ExitCode = -1;
    public bool TimedOut, Forced;
    public string Failure;
    public byte[] Stdout, Stderr;
    public double Seconds;
}
public static class Native31BoundedProcess {
    static async Task Drain(Stream source, MemoryStream target, int limit) {
        byte[] buffer = new byte[8192];
        while (true) {
            int count = await source.ReadAsync(buffer, 0, buffer.Length);
            if (count == 0) return;
            lock (target) {
                if (target.Length + count > limit) throw new IOException("Native31 output bound exceeded");
                target.Write(buffer, 0, count);
            }
        }
    }
    public static Native31ProcessResult Run(string executable, string[] argv, string cwd, int milliseconds, int limit) {
        if (milliseconds <= 2500) throw new TimeoutException("Native31 phase reserve exhausted");
        var result = new Native31ProcessResult();
        var clock = Stopwatch.StartNew();
        using (var stdout = new MemoryStream()) using (var stderr = new MemoryStream()) using (var process = new Process()) {
            process.StartInfo = new ProcessStartInfo(executable) { WorkingDirectory = cwd, UseShellExecute = false,
                RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
            foreach (var item in argv) process.StartInfo.ArgumentList.Add(item);
            process.StartInfo.Environment.Remove("PYTHONPATH");
            process.StartInfo.Environment.Remove("PYTHONSTARTUP");
            process.StartInfo.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
            process.StartInfo.Environment["PYTHONUTF8"] = "1";
            Task output = null, error = null;
            bool started = false;
            try {
                if (!process.Start()) throw new IOException("Native31 owned process start failed");
                started = true;
                output = Drain(process.StandardOutput.BaseStream, stdout, limit);
                error = Drain(process.StandardError.BaseStream, stderr, limit);
                while (!process.WaitForExit(20)) {
                    if (output.IsFaulted || error.IsFaulted) throw new IOException("Native31 output bound exceeded");
                    if (clock.ElapsedMilliseconds >= milliseconds - 2000) {
                        result.TimedOut = true;
                        throw new TimeoutException("Native31 owned process exceeded phase deadline");
                    }
                }
                result.ExitCode = process.ExitCode;
                int left = Math.Max(1, milliseconds - (int)clock.ElapsedMilliseconds);
                if (!Task.WaitAll(new[] { output, error }, left)) throw new TimeoutException("Native31 pipe deadline exceeded");
            } catch (Exception exception) {
                result.Failure = exception.GetType().Name + ": " + exception.Message;
                if (exception is TimeoutException) result.TimedOut = true;
            } finally {
                if (started && !process.HasExited) {
                    result.Forced = true;
                    try { process.Kill(true); } catch (Exception exception) { result.Failure += "; owned termination: " + exception.Message; }
                    int left = Math.Max(1, milliseconds - (int)clock.ElapsedMilliseconds);
                    if (!process.WaitForExit(left)) result.Failure += "; owned termination unconfirmed";
                }
                if (started && process.HasExited) result.ExitCode = process.ExitCode;
                lock (stdout) result.Stdout = stdout.ToArray();
                lock (stderr) result.Stderr = stderr.ToArray();
                result.Seconds = clock.Elapsed.TotalSeconds;
            }
        }
        return result;
    }
}
'@
}

$Native31Critical = @('e2e/native31_desktop_control.py', 'e2e/runner-ready.py', 'ci/policy.py',
    '.github/workflows/office-native31-desktop-control.yml', 'e2e/native31_privacy_prepare.py',
    '.github/workflows/office-native31-privacy-prepare.yml', 'suite/e2e/native_window_evidence.py',
    'e2e/native35_tsf_profile_prepare.py', '.github/workflows/office-suite-native35-tsf-diagnostic.yml', 'suite/scripts/prepare-native35-tsf-profile.ps1')

function Assert-Native31([bool]$Value, [string]$Message) { if (-not $Value) { throw $Message } }
function Get-Native31Hash([byte[]]$Bytes) { return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant() }
function Assert-Native31Path([string]$Path) {
    Assert-Native31 ([IO.Path]::IsPathFullyQualified($Path) -and $Path -notmatch '(^|[\\/])\.\.([\\/]|$)') 'Absolute unaliased path required.'
    $full = [IO.Path]::GetFullPath($Path)
    $part = $full
    while ($part) {
        if (Test-Path -LiteralPath $part) {
            $item = Get-Item -LiteralPath $part -Force
            Assert-Native31 (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Linked/reparse preparation path rejected.'
        }
        $part = [IO.Path]::GetDirectoryName($part)
    }
    return $full
}
function Write-Native31Json([string]$Path, $Value) {
    $null = Assert-Native31Path $Path
    $raw = [Text.Encoding]::UTF8.GetBytes(($Value | ConvertTo-Json -Depth 32) + "`n")
    Assert-Native31 ($raw.Length -le 262144) 'Setup JSON bound exceeded.'
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($raw, 0, $raw.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}
function Get-Native31Milliseconds($Clock, [double]$Cap) {
    $left = $Cap - $Clock.Elapsed.TotalSeconds
    Assert-Native31 ($left -gt 2.5) 'Native31 phase deadline reserve exhausted.'
    return [int][Math]::Floor($left * 1000)
}
function Invoke-Native31Git([string]$Root, [string[]]$Arguments, $State, [switch]$AllowFailure) {
    $argv = @('-C', $Root) + $Arguments
    $result = [Native31BoundedProcess]::Run('git', $argv, $Root, (Get-Native31Milliseconds $State.Clock 30), 262144)
    $State.Commands.Add(@{ executable='git'; argv=$argv; exitCode=$result.ExitCode; seconds=$result.Seconds;
        timedOut=$result.TimedOut; forced=$result.Forced; failure=$result.Failure;
        stdoutBytes=$result.Stdout.Length; stdoutSha256=(Get-Native31Hash $result.Stdout);
        stderrBytes=$result.Stderr.Length; stderrSha256=(Get-Native31Hash $result.Stderr);
        stderr=[Text.Encoding]::UTF8.GetString($result.Stderr, 0, [Math]::Min(2048, $result.Stderr.Length)) })
    Assert-Native31 ($State.Commands.Count -le 64) 'Setup command count exceeded.'
    Assert-Native31 (-not $result.Failure -and -not $result.TimedOut -and -not $result.Forced) 'Bounded Git setup failed.'
    Assert-Native31 ($AllowFailure -or $result.ExitCode -eq 0) 'Git setup returned failure.'
    return $result
}
function Get-Native31GitText([string]$Root, [string[]]$Arguments, $State) {
    $result = Invoke-Native31Git $Root $Arguments $State
    return [Text.Encoding]::UTF8.GetString($result.Stdout).Trim()
}
function Get-Native31Identity([string]$Root, $State) {
    $null = Assert-Native31Path $Root
    $inside = Get-Native31GitText $Root @('rev-parse', '--is-inside-work-tree') $State
    $prefix = Get-Native31GitText $Root @('rev-parse', '--show-prefix') $State
    $top = Get-Native31GitText $Root @('rev-parse', '--show-toplevel') $State
    $null = Assert-Native31Path $top
    if ($inside -cne 'true' -or $prefix -cne '') {
        $detail = @{requestedRoot=$Root; reportedTop=$top; insideWorkTree=$inside; prefix=$prefix; valuesTruncated=$false}
        foreach ($key in @('requestedRoot','reportedTop','insideWorkTree','prefix')) {
            if ($detail[$key].Length -gt 1024) { $detail[$key] = $detail[$key].Substring(0,1024); $detail.valuesTruncated = $true }
        }
        throw ('Requested directory is not an actual Git working-tree root: ' + ($detail | ConvertTo-Json -Compress))
    }
    return @{ root=$Root; gitTopLevel=$top; insideWorkTree=$inside; prefix=$prefix;
        head=(Get-Native31GitText $Root @('rev-parse', 'HEAD') $State);
        tree=(Get-Native31GitText $Root @('rev-parse', 'HEAD^{tree}') $State);
        commonDir=(Assert-Native31Path (Get-Native31GitText $Root @('rev-parse', '--path-format=absolute', '--git-common-dir') $State)) }
}
function Get-Native31SourceProof([string]$Root, [string]$Sha, $State) {
    $files = @{}
    foreach ($name in $Native31Critical) {
        $path = Assert-Native31Path (Join-Path $Root $name)
        $item = Get-Item -LiteralPath $path -Force
        Assert-Native31 (-not $item.PSIsContainer -and $item.Length -le 262144) 'Critical source file missing or oversized.'
        $actual = [IO.File]::ReadAllBytes($path)
        $blob = (Invoke-Native31Git $Root @('show', "${Sha}:$name") $State).Stdout
        $digest = Get-Native31Hash $actual
        Assert-Native31 ($actual.Length -eq $blob.Length -and $digest -ceq (Get-Native31Hash $blob)) 'Critical source bytes differ from exact commit.'
        $files[$name] = @{ bytes=$actual.Length; sha256=$digest }
    }
    return $files
}
function Assert-Native31Context([string]$Arch) {
    $ref = 'refs/heads/work/opengeul-office-native35-tsf-diagnostic'
    $expected = @{ GITHUB_ACTIONS='true'; RUNNER_ENVIRONMENT='github-hosted'; RUNNER_OS='Windows';
        RUNNER_ARCH=$(if ($Arch -ceq 'arm64') { 'ARM64' } else { 'X64' }); GITHUB_REPOSITORY='ATLKR/OpenGeul';
        GITHUB_EVENT_NAME='push'; GITHUB_JOB='windows-tsf-profile-diagnostic'; GITHUB_REF=$ref;
        GITHUB_WORKFLOW_REF="ATLKR/OpenGeul/.github/workflows/office-suite-native35-tsf-diagnostic.yml@$ref";
        GITHUB_RUN_ATTEMPT='1'; GITHUB_ACTOR='ATLKR'; GITHUB_ACTOR_ID='65988341' }
    foreach ($key in $expected.Keys) { Assert-Native31 ([Environment]::GetEnvironmentVariable($key) -ceq $expected[$key]) "Exact Suite binding differs: $key" }
    Assert-Native31 ($env:GITHUB_SHA -cmatch '\A[0-9a-f]{40}\z' -and $env:GITHUB_SHA -cne ('0' * 40) -and
        $env:GITHUB_WORKFLOW_SHA -ceq $env:GITHUB_SHA -and $env:GITHUB_RUN_ID -cmatch '\A[1-9][0-9]{0,19}\z') 'Suite source/run binding differs.'
    $eventPath = Assert-Native31Path $env:GITHUB_EVENT_PATH
    Assert-Native31 ((Get-Item -LiteralPath $eventPath).Length -le 262144) 'Event exceeds setup bound.'
    $event = Get-Content -LiteralPath $eventPath -Raw | ConvertFrom-Json
    Assert-Native31 ($event.repository.full_name -ceq 'ATLKR/OpenGeul' -and $event.repository.private -is [bool] -and
        -not $event.repository.private -and $event.repository.id -gt 0 -and $event.sender.login -ceq 'ATLKR' -and
        $event.sender.id -eq 65988341 -and $event.sender.type -ceq 'User' -and $event.ref -ceq $ref -and
        $event.deleted -is [bool] -and -not $event.deleted -and $event.after -ceq $env:GITHUB_SHA) 'Actual public owner push payload differs.'
}
function New-Native31Source([string]$Root, [string]$Source, [string]$Setup, $State) {
    Assert-Native31 (-not (Test-Path -LiteralPath $Source)) 'Fresh source worktree required; reuse rejected.'
    $main = Get-Native31Identity $Root $State
    Assert-Native31 ($main.head -ceq $env:GITHUB_SHA -and $main.tree -cmatch '\A[0-9a-f]{40}\z') 'Main HEAD/tree differs from event.'
    $before = Get-Native31SourceProof $Root $env:GITHUB_SHA $State
    $hooks = Join-Path $Setup 'hooks'; $null = New-Item -ItemType Directory -Path $hooks
    $command = @('-c','core.autocrlf=false','-c','core.longpaths=true','-c',"core.hooksPath=$hooks",'-c','submodule.recurse=false',
        'worktree','add','--detach',$Source,$env:GITHUB_SHA)
    $null = Invoke-Native31Git $Root $command $State
    $clean = Get-Native31Identity $Source $State
    Assert-Native31 ($clean.head -ceq $main.head -and $clean.tree -ceq $main.tree -and $clean.commonDir -ceq $main.commonDir) 'Detached source identity differs.'
    $dotgit = Get-Item -LiteralPath (Join-Path $Source '.git') -Force
    Assert-Native31 (-not $dotgit.PSIsContainer -and -not ($dotgit.Attributes -band [IO.FileAttributes]::ReparsePoint)) 'Linked worktree Git pointer must be a regular file.'
    $symbolic = Invoke-Native31Git $Source @('symbolic-ref','-q','HEAD') $State -AllowFailure
    Assert-Native31 ($symbolic.ExitCode -eq 1 -and $symbolic.Stdout.Length -eq 0) 'Source worktree must have detached HEAD.'
    Assert-Native31 ((Get-Native31GitText $Source @('status','--porcelain=v1','--untracked-files=all','--ignored') $State) -ceq '') 'Detached source is not strictly clean.'
    $after = Get-Native31SourceProof $Source $env:GITHUB_SHA $State
    foreach ($name in $Native31Critical) { Assert-Native31 ($before[$name].sha256 -ceq $after[$name].sha256) 'Main-to-action source bytes changed.' }
    $mainAfter = Get-Native31Identity $Root $State
    Assert-Native31 ($mainAfter.head -ceq $main.head -and $mainAfter.tree -ceq $main.tree) 'Main source changed during setup.'
    return @{ main=$main; action=$clean; files=$after; mainFiles=$before; detached=$true; strictClean=$true; retainedUntilJobEnd=$true }
}
function Copy-Native31Evidence([string]$Setup, [string]$Control, [string]$Destination, [double]$Seconds=15) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $null = Assert-Native31Path $Destination
    Assert-Native31 (-not (Test-Path -LiteralPath $Destination)) 'Fresh evidence staging target required.'
    $null = New-Item -ItemType Directory -Path $Destination
    $inventory = [Collections.Generic.List[object]]::new(); $total = 0L
    foreach ($group in @(@{name='setup';root=$Setup;count=8}, @{name='control';root=$Control;count=72})) {
        if (-not (Test-Path -LiteralPath $group.root)) { continue }
        $null = Assert-Native31Path $group.root
        Assert-Native31 ((Get-Item -LiteralPath $group.root).PSIsContainer) 'Evidence root is not a directory.'
        $target = Join-Path $Destination $group.name; $null = New-Item -ItemType Directory -Path $target
        $files = @(Get-ChildItem -LiteralPath $group.root -Force)
        Assert-Native31 ($files.Count -le ($group.count + $(if ($group.name -ceq 'setup') {1} else {0}))) 'Evidence file count exceeded.'
        foreach ($file in $files) {
            Assert-Native31 ($clock.Elapsed.TotalSeconds -lt $Seconds) 'Evidence staging deadline exhausted.'
            $null = Assert-Native31Path $file.FullName
            if ($group.name -ceq 'setup' -and $file.Name -ceq 'hooks' -and $file.PSIsContainer) {
                Assert-Native31 (@(Get-ChildItem -LiteralPath $file.FullName -Force).Count -eq 0) 'Setup hooks directory is not empty.'
                continue
            }
            Assert-Native31 (-not $file.PSIsContainer -and $file.Name -cmatch '\A[a-z0-9][a-z0-9.-]{0,95}\.(json|png)\z') 'Non-flat or unexpected evidence file.'
            $limit = if ($file.Extension -ceq '.png' -and $group.name -ceq 'control') { 8388608 } else { 262144 }
            Assert-Native31 ($file.Length -le $limit) 'Evidence file byte limit exceeded.'
            $total += $file.Length; Assert-Native31 ($total -le 41943040) 'Evidence total byte bound exceeded.'
            $raw = [IO.File]::ReadAllBytes($file.FullName)
            Assert-Native31 ($raw.Length -eq $file.Length) 'Original evidence size raced.'
            $copy = Join-Path $target $file.Name
            $stream = [IO.File]::Open($copy, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try { $stream.Write($raw, 0, $raw.Length); $stream.Flush($true) } finally { $stream.Dispose() }
            $digest = Get-Native31Hash $raw; $copied = [IO.File]::ReadAllBytes($copy)
            Assert-Native31 ($copied.Length -eq $raw.Length -and (Get-Native31Hash $copied) -ceq $digest) 'Evidence copy size/hash differs.'
            $inventory.Add(@{group=$group.name;name=$file.Name;original=$file.FullName;staged=$copy;bytes=$raw.Length;sha256=$digest})
        }
    }
    Assert-Native31 ($inventory.Count -gt 0 -and $clock.Elapsed.TotalSeconds -lt $Seconds) 'Evidence staging incomplete or exceeded deadline.'
    Write-Native31Json (Join-Path $Destination 'copy-inventory.json') @{schemaVersion=1;files=$inventory;bytes=$total;seconds=$clock.Elapsed.TotalSeconds;byteIdentical=$true}
}
function Invoke-Native31Suite([string]$Arch, [string]$Root, [string]$Temp) {
    Assert-Native31 ($Arch -cin @('arm64','x64')) 'Suite architecture required.'
    $Root = Assert-Native31Path $Root; $Temp = Assert-Native31Path $Temp
    Assert-Native31 ((Test-Path -LiteralPath $Root -PathType Container) -and (Test-Path -LiteralPath $Temp -PathType Container)) 'Owned source/temp roots unavailable.'
    Assert-Native31 ($env:GITHUB_RUN_ID -cmatch '\A[1-9][0-9]{0,19}\z' -and $env:GITHUB_RUN_ATTEMPT -ceq '1') 'Fresh run path identity required.'
    $suffix = "$Arch-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT"
    $setup = Join-Path $Temp "suite-native35-tsf-profile-setup-$suffix"
    $control = Join-Path $Temp "suite-native35-tsf-profile-privacy-preparation-$suffix"
    $source = Join-Path $Temp "suite-native35-tsf-profile-source-$suffix"
    foreach ($path in @($setup,$control,$source)) { $null = Assert-Native31Path $path; Assert-Native31 (-not (Test-Path -LiteralPath $path)) 'Fresh setup/control/source paths required.' }
    $null = New-Item -ItemType Directory -Path $setup
    $state = @{ Clock=[Diagnostics.Stopwatch]::StartNew(); Commands=[Collections.Generic.List[object]]::new() }
    $primary = $null; $stagingFailure = $null; $proof = $null
    Write-Native31Json (Join-Path $setup '00-setup-start.json') @{schemaVersion=1;architecture=$Arch;sourceCommit=$env:GITHUB_SHA;runId=$env:GITHUB_RUN_ID;
        runAttempt=$env:GITHUB_RUN_ATTEMPT;mainRoot=$Root;cleanRoot=$source;controlRoot=$control;setupSeconds=30;controllerSeconds=120;stagingSeconds=15;
        actions=@();inputsPerformed=0;closeRequests=0;consentActions=@();productExecuted=$false}
    try {
        Assert-Native31Context $Arch
        if ($Arch -ceq 'arm64') {
            $proof = New-Native31Source $Root $source $setup $state
            $actionRoot = $source
        } else {
            $identity = Get-Native31Identity $Root $state
            Assert-Native31 ($identity.head -ceq $env:GITHUB_SHA) 'x64 main HEAD differs.'
            $proof = @{main=$identity;files=(Get-Native31SourceProof $Root $env:GITHUB_SHA $state);notApplicable=$true;worktreeCreated=$false}
            $actionRoot = $Root
        }
        Assert-Native31 ($state.Clock.Elapsed.TotalSeconds -lt 30) 'Setup budget exceeded; no controller started.'
        Write-Native31Json (Join-Path $setup '10-source-setup.json') @{success=$true;proof=$proof;commands=$state.Commands;seconds=$state.Clock.Elapsed.TotalSeconds}
        $python = (Get-Command python -CommandType Application | Select-Object -First 1).Source
        $argv = @('-B',(Join-Path $actionRoot 'e2e/native35_tsf_profile_prepare.py'),'--architecture',$Arch,'--prepare-privacy','--output',$control)
        $env:NATIVE31_PWSH = (Get-Process -Id $PID).Path
        # 125s launch containment includes interpreter startup; core action budget stays120s.
        $milliseconds = if ($Arch -ceq 'arm64') {125000} else {Get-Native31Milliseconds $state.Clock 30}
        $result = [Native31BoundedProcess]::Run($python, $argv, $actionRoot, $milliseconds, 8192)
        Write-Native31Json (Join-Path $setup '20-entry-exit.json') @{argv=$argv;executable=$python;cwd=$actionRoot;exitCode=$result.ExitCode;
            seconds=$result.Seconds;timedOut=$result.TimedOut;forced=$result.Forced;failure=$result.Failure;
            stdout=[Text.Encoding]::UTF8.GetString($result.Stdout);stderr=[Text.Encoding]::UTF8.GetString($result.Stderr)}
        Assert-Native31 ($result.ExitCode -eq 0 -and -not $result.TimedOut -and -not $result.Forced -and -not $result.Failure) 'Suite native31 preparation entry failed.'
    } catch {
        $primary = $_
        try { Write-Native31Json (Join-Path $setup '90-caller-failure.json') @{failure=$primary.Exception.Message;commands=$state.Commands;proof=$proof} }
        catch { $primary.Exception.Data['receiptFailure'] = $_.Exception.Message }
    } finally {
        try {
            # Separate owned I/O-only worker gives blocked file I/O the same finite
            # containment as setup. It cannot invoke a controller or native action.
            $stager = if ($proof -and $Arch -ceq 'arm64') { Join-Path $source 'suite/scripts/prepare-native35-tsf-profile.ps1' } else { $PSCommandPath }
            $stageArgv = @('-NoLogo','-NoProfile','-NonInteractive','-File',$stager,'-StageOnly',
                '-SetupEvidence',$setup,'-ControlEvidence',$control,'-StagingDestination',(Join-Path $Root '.work/suite-native35-tsf-profile-privacy-preparation'))
            $staged = [Native31BoundedProcess]::Run((Get-Process -Id $PID).Path, $stageArgv, $Root, 15000, 8192)
            Assert-Native31 ($staged.ExitCode -eq 0 -and -not $staged.Failure -and -not $staged.Forced -and -not $staged.TimedOut) ('Evidence staging worker failed: ' + [Text.Encoding]::UTF8.GetString($staged.Stderr))
        }
        catch {
            $stagingFailure = $_
            try { Write-Native31Json (Join-Path $setup '99-staging-failure.json') @{primaryFailure=$(if ($primary) {$primary.Exception.Message} else {$null});stagingFailure=$stagingFailure.Exception.Message} }
            catch { $stagingFailure.Exception.Data['receiptFailure'] = $_.Exception.Message }
        }
    }
    if ($primary) { throw $primary }
    if ($stagingFailure) { throw $stagingFailure }
}
if ($MyInvocation.InvocationName -ne '.') {
    if ($StageOnly) { Copy-Native31Evidence $SetupEvidence $ControlEvidence $StagingDestination }
    else { Invoke-Native31Suite $Architecture $Workspace $RunnerTemp }
}
