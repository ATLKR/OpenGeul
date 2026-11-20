param([string]$CandidateRoot,[string]$FixtureRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$rows=[Collections.Generic.List[object]]::new()
. (Join-Path $CandidateRoot 'scripts/korean_fod_custody.ps1')
$script:FodUnsafeAttempts=0
function Initialize-OpenGeulFodNative { $script:FodUnsafeAttempts++;throw 'Native API forbidden in synthetic gates.' }
function New-OpenGeulFodDirectory { $script:FodUnsafeAttempts++;throw 'Native directory operation forbidden in synthetic gates.' }
function Start-OpenGeulFodOwnedProcess { $script:FodUnsafeAttempts++;throw 'Real process launch forbidden in synthetic gates.' }
function Check([bool]$Value) { if (-not $Value) { throw 'Synthetic check failed.' } }
function Reject([scriptblock]$Body) { $failed=$false;try { & $Body | Out-Null } catch { $failed=$true };Check $failed }
function Case([int]$Id,[scriptblock]$Body) { $ok=$false;try { & $Body;$ok=$true } catch { };$rows.Add([ordered]@{case=$Id;ok=$ok}) }
$binding=[pscustomobject][ordered]@{sourceCommit=('a'*40);sourceRun='123';runAttempt='1';repository='ATLKR/OpenGeul';job='native-e2e';architecture='x64'}
Case 1 { Check ((Get-OpenGeulFodWorkEnd 100) -eq 340);Check ((Get-OpenGeulFodWorkEnd 500) -eq 590) }
Case 2 { Check ((Get-OpenGeulFodWaitMs 590 590) -eq 0);Reject { Get-OpenGeulFodWorkEnd ([double]::NaN) };Reject { Get-OpenGeulFodWaitMs -1 590 } }
Case 3 { Check (Test-OpenGeulFodLane $binding 34404 0 '26100' 'Server' 'NotPresent');Check (-not (Test-OpenGeulFodLane $binding 34404 0 '20348' 'Server' 'NotPresent'));Check (-not (Test-OpenGeulFodLane $binding 34404 0 '26100' 'Server' 'Installed'));Check (-not (Test-OpenGeulFodLane $binding 43620 0 '26100' 'Server' 'NotPresent')) }
Case 4 { $raw=New-OpenGeulFodRequest $binding 42 133123456789012345 1;$r=Read-OpenGeulFodRequest $raw $binding 42 133123456789012345;Check ($r.workerPid -eq 42);Check ($r.workerCreationFileTime -eq 133123456789012345);Check ($r.requestSha256 -match '\A[0-9a-f]{64}\z') }
Case 5 { $raw=New-OpenGeulFodRequest $binding 42 133123456789012345 1;Reject { Read-OpenGeulFodRequest ($raw.Replace('"generation":1','"generation":1,"generation":1')) $binding 42 133123456789012345 };Reject { Read-OpenGeulFodRequest ($raw.Replace('"generation":1','"Generation":1')) $binding 42 133123456789012345 };Reject { Read-OpenGeulFodRequest ($raw.Replace('"generation":1','"generation":1.0')) $binding 42 133123456789012345 };Reject { Read-OpenGeulFodRequest ($raw.Replace('"workerPid":42','"workerPid":true')) $binding 42 133123456789012345 } }
Case 6 { $raw=New-OpenGeulFodRequest $binding 42 133123456789012345 1;Reject { Read-OpenGeulFodRequest $raw $binding 43 133123456789012345 };Reject { Read-OpenGeulFodRequest $raw $binding 42 133123456789012346 };Reject { Read-OpenGeulFodRequest ($raw.Replace('"generation":1','"generation":2')) $binding 42 133123456789012345 };Reject { Read-OpenGeulFodRequest $raw.Substring(0,$raw.Length-1) $binding 42 133123456789012345 } }
Case 7 { $raw=New-OpenGeulFodRequest $binding 42 133123456789012345 1;Reject { Read-OpenGeulFodRequest ($raw.Replace('ATLKR/OpenGeul','ATLKR\u002fOpenGeul')) $binding 42 133123456789012345 };Reject { Read-OpenGeulFodRequest ($raw+(' '*4096)) $binding 42 133123456789012345 };Reject { New-OpenGeulFodRequest $binding 0 1 1 };Reject { New-OpenGeulFodRequest $binding 42 0 1 } }
function FakeProcess([bool]$Exited) { $p=[pscustomobject]@{HasExited=$Exited;ExitCode=0};$p|Add-Member ScriptMethod Refresh { };return $p }
function Owned([bool]$Exited) { return [pscustomobject]@{Process=(FakeProcess $Exited);Handle=[IntPtr]1;Pid=$(if($Exited){43}else{42});Created=[long]133123456789012345;IdentityKnown=$true;Retired=$Exited;ExitCode=0} }
Case 8 { $r=Read-OpenGeulFodRequest (New-OpenGeulFodRequest $binding 42 133123456789012345 1) $binding 42 133123456789012345;$w=Owned $false;$h=Owned $true;Assert-OpenGeulFodReadyGate $r $w $h 339 340;Reject { Assert-OpenGeulFodReadyGate $r $w $h 340 340 };$w.Process.HasExited=$true;Reject { Assert-OpenGeulFodReadyGate $r $w $h 339 340 } }
Case 9 { $r=Read-OpenGeulFodRequest (New-OpenGeulFodRequest $binding 42 133123456789012345 1) $binding 42 133123456789012345;$w=Owned $false;$h=Owned $true;$h.IdentityKnown=$false;Reject { Assert-OpenGeulFodReadyGate $r $w $h 300 340 };$h.IdentityKnown=$true;$h.Retired=$null;Reject { Assert-OpenGeulFodReadyGate $r $w $h 300 340 };$h.Retired=$true;$h.ExitCode=1;Reject { Assert-OpenGeulFodReadyGate $r $w $h 300 340 } }
Case 10 { $r=Read-OpenGeulFodRequest (New-OpenGeulFodRequest $binding 42 133123456789012345 1) $binding 42 133123456789012345;$h=Owned $true;$raw=New-OpenGeulFodReady $r $h ('b'*64) ('c'*64);$ready=Read-OpenGeulFodReady $raw $r;Check ($ready.helperExitCode -eq 0);Check ($ready.helperRetired -eq $true);Reject { Read-OpenGeulFodReady ($raw.Replace('"helperRetired":true','"helperRetired":false')) $r };Reject { Read-OpenGeulFodReady ($raw.Replace('"ready":1','"ready":1,"ready":1')) $r };Reject { Read-OpenGeulFodReady ($raw.Replace('"requestSha256":"','"requestSha256":"0')) $r } }
Case 11 { $clock=[pscustomobject]@{Elapsed=[pscustomobject]@{TotalSeconds=590.0}};$events=[Collections.Generic.List[string]]::new();$waits=[Collections.Generic.List[int]]::new();$states=@();foreach($n in 1,2){$proc=[pscustomobject]@{HasExited=$false;ExitCode=1;Clock=$clock;Events=$events;Waits=$waits};$proc|Add-Member ScriptMethod Kill { $this.Events.Add('kill') };$proc|Add-Member ScriptMethod WaitForExit { param($ms);$this.Events.Add('wait');$this.Waits.Add($ms);$this.Clock.Elapsed.TotalSeconds+=6;$this.HasExited=$true;return $true };$states+= [pscustomobject]@{Process=$proc;Handle=[IntPtr]1;Retired=$null;ExitCode=$null}};Stop-OpenGeulFodChildren $states $clock;Check ($events[0] -eq 'kill' -and $events[1] -eq 'kill');Check ($waits.Count -eq 2 -and $waits[0] -eq 10000 -and $waits[1] -eq 4000) }
Case 12 { $clock=[pscustomobject]@{Elapsed=[pscustomobject]@{TotalSeconds=600.0}};$p=[pscustomobject]@{HasExited=$false;ExitCode=1;Calls=0};$p|Add-Member ScriptMethod Kill { };$p|Add-Member ScriptMethod WaitForExit { param($ms);$this.Calls++;return $false };$s=[pscustomobject]@{Process=$p;Handle=[IntPtr]1;Retired=$null;ExitCode=$null};Stop-OpenGeulFodChildren @($s) $clock;Check ($null -eq $s.Retired -and $p.Calls -eq 0) }
Case 13 { $root=Join-Path $FixtureRoot ('fod-atomic-'+[Guid]::NewGuid().ToString('N'));[IO.Directory]::CreateDirectory($root)|Out-Null;try{$f=Join-Path $root 'ready.json';Publish-OpenGeulFodAscii $f '{"ready":1}';Reject { Publish-OpenGeulFodAscii $f '{"ready":0}' };Check ([IO.File]::ReadAllText($f) -eq '{"ready":1}');Check (@([IO.Directory]::GetFiles($root)).Count -eq 1)}finally{[IO.Directory]::Delete($root,$true)} }
Case 14 { $r=Read-OpenGeulFodRequest (New-OpenGeulFodRequest $binding 42 133123456789012345 1) $binding 42 133123456789012345;$h=Owned $true;$raw=New-OpenGeulFodReady $r $h ('b'*64) ('c'*64);$ready=Read-OpenGeulFodReady $raw $r;Check ($ready.cabCount -eq 9 -and $ready.cabBytes -eq 21154053);Check ($ready.acceptanceEligible -eq 0);Check ($ready.sourceQualified -eq 0);Reject { Read-OpenGeulFodReady ($raw.Replace('"allNinePinsMatched":true','"allNinePinsMatched":false')) $r } }
Case 15 { $path=Join-Path $CandidateRoot 'scripts/korean_fod_acquire_silent.py';Assert-OpenGeulFodSourcePins $CandidateRoot;Reject { Assert-OpenGeulFodSourcePins (Join-Path $CandidateRoot 'missing') };Check ([IO.File]::Exists($path)) }
Case 16 { $packages=@(Get-OpenGeulFodPackages);Check ($packages.Count -eq 9);Check (($packages|Measure-Object -Property bytes -Sum).Sum -eq 21154053);$r=Join-Path $FixtureRoot ('fod-partial-'+[Guid]::NewGuid().ToString('N'));[IO.Directory]::CreateDirectory($r)|Out-Null;try{Reject { Assert-OpenGeulFodAcquisition $r }}finally{[IO.Directory]::Delete($r,$true)} }
Case 17 { $py=[pscustomobject]@{Path='/fixed/python.exe';Environment=[ordered]@{SystemRoot='X:\Windows';WINDIR='X:\Windows';PATH='X:\Python;X:\Windows\System32';TEMP='X:\owned\temp';TMP='X:\owned\temp'}};$info=New-OpenGeulFodStartInfo $py $CandidateRoot '/private/source';Check ($info.Environment.Count -eq 5);Check (-not $info.Environment.ContainsKey('GH_TOKEN'));Check (-not $info.Environment.ContainsKey('GITHUB_TOKEN'));Check (($info.ArgumentList[0..3] -join ',') -ceq '-I,-B,-X,utf8');Check ($info.RedirectStandardInput -and $info.RedirectStandardOutput -and $info.RedirectStandardError -and -not $info.UseShellExecute) }
Case 21 { $clock=[pscustomobject]@{Elapsed=[pscustomobject]@{TotalSeconds=340.0}};$ctx=[pscustomobject]@{Control=$FixtureRoot;Attempted=$true;Offline=$true;Ready=$false;WorkEnd=340.0;ReasonCode=0};Reject { Invoke-OpenGeulFodTick $ctx (Owned $false) $clock $binding $CandidateRoot };Check ($ctx.ReasonCode -eq 6) }
Case 22 { foreach($rel in @('scripts/ensure-korean-ime.ps1','scripts/korean_fod_custody.ps1')){$tokens=$null;$errors=$null;[Management.Automation.Language.Parser]::ParseFile((Join-Path $CandidateRoot $rel),[ref]$tokens,[ref]$errors)|Out-Null;Check ($errors.Count -eq 0)} }
Case 23 { $root=Join-Path $FixtureRoot ('fod-pin-'+[Guid]::NewGuid().ToString('N'));[IO.Directory]::CreateDirectory((Join-Path $root 'scripts'))|Out-Null;[IO.Directory]::CreateDirectory((Join-Path $root 'suite/scripts'))|Out-Null;try{[IO.File]::Copy((Join-Path $CandidateRoot 'suite/scripts/korean_fod_source.py'),(Join-Path $root 'suite/scripts/korean_fod_source.py'));[IO.File]::WriteAllText((Join-Path $root 'scripts/korean_fod_acquire_silent.py'),'synthetic-changed-source');Reject { Assert-OpenGeulFodSourcePins $root }}finally{[IO.Directory]::Delete($root,$true)} }
Case 24 { $r=Read-OpenGeulFodRequest (New-OpenGeulFodRequest $binding 42 133123456789012345 1) $binding 42 133123456789012345;$w=Owned $false;$h=Owned $true;$w.IdentityKnown=$false;Reject { Assert-OpenGeulFodReadyGate $r $w $h 300 340 };$w.IdentityKnown=$true;$w.Handle=[IntPtr]::Zero;Reject { Assert-OpenGeulFodReadyGate $r $w $h 300 340 } }
Case 27 { $clock=[pscustomobject]@{Elapsed=[pscustomobject]@{TotalSeconds=590.0}};$p=[pscustomobject]@{HasExited=$false;ExitCode=0;Clock=$clock};$p|Add-Member ScriptMethod Kill { };$p|Add-Member ScriptMethod WaitForExit {param($ms);$this.Clock.Elapsed.TotalSeconds=601;return $true};$s=[pscustomobject]@{Process=$p;Handle=[IntPtr]1;Retired=$null;ExitCode=$null};Stop-OpenGeulFodChildren @($s) $clock;Check ($null -eq $s.Retired -and $null -eq $s.ExitCode) }
Case 28 {
    $saved=${function:Get-OpenGeulFodRunnerTemp};$script:FodGuardCalls=0
    function Get-OpenGeulFodRunnerTemp { $script:FodGuardCalls++;throw 'New guard must stay lazy.' }
    try {
        foreach($row in @(@('20348','Server','NotPresent'),@('26100','Server','Installed'))){
            Check (-not (Test-OpenGeulFodLane $binding 34404 0 $row[0] $row[1] $row[2]))
            $worker=Owned $false;$ctx=New-OpenGeulFodContext $CandidateRoot (Join-Path $FixtureRoot 'out') $binding $worker
            Check (-not $ctx.Offline)
            Invoke-OpenGeulFodTick $ctx $worker ([Diagnostics.Stopwatch]::StartNew()) $binding $CandidateRoot
        }
        Check ($script:FodGuardCalls -eq 0)
    } finally { Set-Item Function:Get-OpenGeulFodRunnerTemp $saved }
}
Case 29 {
    $saved=${function:Get-OpenGeulFodRunnerTemp};$script:FodGuardCalls=0
    function Get-OpenGeulFodRunnerTemp { $script:FodGuardCalls++;throw 'Offline request guard fixture.' }
    try {
        $worker=Owned $false;$ctx=New-OpenGeulFodContext $CandidateRoot (Join-Path $FixtureRoot 'out') $binding $worker
        [IO.Directory]::CreateDirectory($ctx.Control)|Out-Null
        Publish-OpenGeulFodAscii (Join-Path $ctx.Control 'request.json') (New-OpenGeulFodRequest $binding $worker.Pid $worker.Created 1)
        Reject { Invoke-OpenGeulFodTick $ctx $worker ([Diagnostics.Stopwatch]::StartNew()) $binding $CandidateRoot }
        Check ($script:FodGuardCalls -eq 1)
        Check (-not [IO.File]::Exists((Join-Path $ctx.Control 'ready.json')))
    } finally { Set-Item Function:Get-OpenGeulFodRunnerTemp $saved }
}
Case 30 { Check ($script:FodUnsafeAttempts -eq 0) }
if($rows.Count -gt 32){throw 'Synthetic case count exceeded its bound.'}
$bad=@($rows|Where-Object {-not $_.ok}).Count
[ordered]@{schemaVersion=1;ran=$rows.Count;failed=$bad;cases=@($rows);unsafeAttempts=$script:FodUnsafeAttempts}|ConvertTo-Json -Depth 4 -Compress
exit $(if($bad){1}else{0})
