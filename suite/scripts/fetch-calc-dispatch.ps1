param([string]$DiagnosticLockPath, [string]$Output,
      [ValidateRange(1,1200)][int]$TimeoutSeconds=1200)
$ErrorActionPreference='Stop'
# Preserve the caller's paths and deadline when importing the ordinary fetch primitives.
. (Join-Path $PSScriptRoot 'fetch-source-engine.ps1') -Output $Output -TimeoutSeconds $TimeoutSeconds

function Read-CalcDispatchEntry($Entry, [Threading.CancellationToken]$CancellationToken) {
    if ($Entry.Length -le 0 -or $Entry.Length -gt 8388608) { throw 'Diagnostic JSON member exceeds bound.' }
    $memory=[IO.MemoryStream]::new(); $stream=$Entry.Open()
    try {
        $buffer=[byte[]]::new(65536)
        while (($count=$stream.ReadAsync($buffer,0,$buffer.Length,$CancellationToken).WaitAsync($CancellationToken).GetAwaiter().GetResult()) -gt 0) {
            if ($memory.Length+$count -gt $Entry.Length) { throw 'Diagnostic JSON exceeds its authenticated member size.' }
            $memory.Write($buffer,0,$count)
        }
        $CancellationToken.ThrowIfCancellationRequested()
        if ($memory.Length -ne $Entry.Length) { throw 'Diagnostic JSON member is incomplete.' }
        $bytes=$memory.ToArray()
        return @{bytes=$bytes;sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant();
            json=([Text.UTF8Encoding]::new($false,$true).GetString($bytes) | ConvertFrom-Json -AsHashtable)}
    } finally { $stream.Dispose(); $memory.Dispose() }
}

function Assert-CalcDispatchReceipt([Collections.IDictionary]$Proof, $Lock) {
    $strings=@{kind='native-office-engine-calc-dispatch-diagnostic';phase='Full';architecture='arm64';stage='complete';
        status='native-engine-calc-dispatch-diagnostic-built';sourceCommit=$Lock.sourceCommit;sourceLockSha256=$Lock.sourceLockSha256}
    foreach ($key in $strings.Keys) {
        if ($Proof[$key] -isnot [string] -or $Proof[$key] -cne $strings[$key]) { throw 'Diagnostic receipt source or build identity differs.' }
    }
    if (-not (Test-EnginePositiveInteger $Proof.schemaVersion) -or $Proof.schemaVersion -ne 1 -or
        -not (Test-EnginePositiveInteger $Proof.sourceRun) -or $Proof.sourceRun -ne $Lock.runId -or
        -not (Test-EnginePositiveInteger $Proof.runAttempt) -or $Proof.runAttempt -ne 1 -or
        $Proof.sourceTree -isnot [string] -or $Proof.sourceTree -cnotmatch '^[0-9a-f]{40}$') { throw 'Diagnostic receipt source run differs.' }
    foreach ($key in @('passed','fullEngineQualified','acceptanceEligible','guiVerified')) {
        $expected=$key -ceq 'passed'
        if ($Proof[$key] -isnot [bool] -or $Proof[$key] -ne $expected) { throw 'Diagnostic receipt qualification flags differ.' }
    }
    $hooks=$Proof.calcDispatchSourceHooks
    if ($hooks -isnot [Collections.IDictionary] -or $Proof.sourcePin -isnot [Collections.IDictionary] -or
        $Proof.sourcePin.coreCommit -isnot [string] -or $Proof.sourcePin.coreCommit -cne $Lock.coreCommit) { throw 'Diagnostic source pin is absent or differs.' }
    $strings=@{kind='calc-save-dispatch-diagnostic-source';target='windows-arm64';coreCommit=$Lock.coreCommit;lockSha256=$Lock.sourceLockSha256}
    foreach ($key in $strings.Keys) {
        if ($hooks[$key] -isnot [string] -or $hooks[$key] -cne $strings[$key]) { throw 'Diagnostic source hook joins differ.' }
    }
    if (-not (Test-EnginePositiveInteger $hooks.schemaVersion) -or $hooks.schemaVersion -ne 1) { throw 'Diagnostic source hook schema differs.' }
    foreach ($key in @('passed','fullEngineQualified','acceptanceEligible')) {
        $expected=$key -ceq 'passed'
        if ($hooks[$key] -isnot [bool] -or $hooks[$key] -ne $expected) { throw 'Diagnostic source hook qualification differs.' }
    }
    $buildHost=$Proof.host
    if ($buildHost.isWindows -isnot [bool] -or -not $buildHost.isWindows -or
        ($buildHost.processMachine -isnot [int] -and $buildHost.processMachine -isnot [long]) -or $buildHost.processMachine -ne 0 -or
        -not (Test-EnginePositiveInteger $buildHost.nativeMachine) -or $buildHost.nativeMachine -ne 0xaa64) { throw 'Diagnostic producer was not native ARM64 Windows.' }
    if (-not (Test-EnginePositiveInteger $Proof.artifact.size) -or $Proof.artifact.size -gt 8589934592 -or
        $Proof.artifact.sha256 -isnot [string] -or $Proof.artifact.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Diagnostic engine size/hash is invalid.' }
}

function Expand-CalcDispatchArtifact([string]$Archive, [string]$Output, $Lock,
                                     [Threading.CancellationToken]$CancellationToken) {
    $engineName='OpenGeul-Office-engine-arm64-calc-dispatch.zip'
    $receiptName='calc-dispatch-source-build-receipt.json'
    $CancellationToken.ThrowIfCancellationRequested()
    $zip=[IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        if ($zip.Entries.Count -ne 2) { throw 'Exactly two diagnostic artifact inputs required.' }
        $members=@{}
        foreach ($entry in $zip.Entries) {
            $name=$entry.FullName
            [long]$attributes=[long]$entry.ExternalAttributes -band 0xffffffffL
            $kind=($attributes -shr 16) -band 0xf000
            if (($name -cne $engineName -and $name -cne $receiptName) -or $members.ContainsKey($name) -or
                $kind -notin @(0,0x8000) -or ($attributes -band 0x410) -or $entry.Length -le 0 -or
                ($name -ceq $engineName -and $entry.Length -gt 8589934592) -or
                ($name -ceq $receiptName -and $entry.Length -gt 8388608)) { throw 'Unsafe or oversized diagnostic artifact member.' }
            $members[$name]=$entry
        }
        if (-not $members.ContainsKey($engineName) -or -not $members.ContainsKey($receiptName)) { throw 'Diagnostic artifact input family is incomplete.' }
        # The outer ZIP has already matched the externally pinned GitHub digest.
        # Inner digests are derived only inside that authenticated byte boundary.
        $receipt=Read-CalcDispatchEntry $members[$receiptName] $CancellationToken
        Assert-CalcDispatchReceipt $receipt.json $Lock
        $proof=$receipt.json
        if ($members[$engineName].Length -ne $proof.artifact.size) { throw 'Diagnostic engine differs from its authenticated receipt size.' }
        foreach ($name in @($receiptName,$engineName)) {
            $expected=if ($name -ceq $receiptName) {$receipt.sha256} else {$proof.artifact.sha256}
            $stream=$members[$name].Open()
            try { Copy-EngineBoundedStream $stream (Join-Path $Output $name) $members[$name].Length $expected $CancellationToken }
            finally { $stream.Dispose() }
        }
        $engine=[IO.Compression.ZipFile]::OpenRead((Join-Path $Output $engineName))
        try {
            if ($engine.Entries.Count -gt 100000) { throw 'Diagnostic engine member count exceeds bound.' }
            $markers=@($engine.Entries | Where-Object FullName -CEQ 'program/opengeul-calc-dispatch-diagnostic.json')
            if ($markers.Count -ne 1) { throw 'Exactly one diagnostic runtime marker required.' }
            $marker=(Read-CalcDispatchEntry $markers[0] $CancellationToken).json
            foreach ($key in @('kind','sourceCommit','sourceLockSha256','coreCommit')) {
                if ($marker[$key] -isnot [string]) { throw 'Diagnostic runtime marker requires scalar source fields.' }
            }
            if (-not (Test-EnginePositiveInteger $marker.schemaVersion) -or $marker.schemaVersion -ne 1 -or
                $marker.kind -cne 'calc-save-dispatch-diagnostic' -or $marker.sourceCommit -cne $Lock.sourceCommit -or
                $marker.sourceLockSha256 -cne $Lock.sourceLockSha256 -or $marker.coreCommit -cne $Lock.coreCommit -or
                $marker.acceptanceEligible -isnot [bool] -or $marker.acceptanceEligible -or
                $marker.fullEngineQualified -isnot [bool] -or $marker.fullEngineQualified) { throw 'Diagnostic runtime marker source joins differ.' }
        } finally { $engine.Dispose() }
        return @{engineSize=$proof.artifact.size;engineSha256=$proof.artifact.sha256;receiptSha256=$receipt.sha256}
    } finally { $zip.Dispose() }
}

function Invoke-CalcDispatchFetch([string]$DiagnosticLockPath, [string]$Output, $ApiClient=$null, $DownloadClient=$null,
                                  [ValidateRange(1,1200)][int]$TimeoutSeconds=1200) {
    Assert-EngineUnlinkedPath $DiagnosticLockPath
    $lockFile=Get-Item -LiteralPath $DiagnosticLockPath
    if ($lockFile.PSIsContainer -or $lockFile.Length -le 0 -or $lockFile.Length -gt 65536) { throw 'Diagnostic artifact lock exceeds bound.' }
    $lock=Get-Content -LiteralPath $DiagnosticLockPath -Raw | ConvertFrom-Json -AsHashtable
    foreach ($key in @('kind','architecture','repository','coreCommit')) {
        if ($lock[$key] -isnot [string]) { throw 'Diagnostic lock requires scalar identity fields.' }
    }
    $keys=@('schemaVersion','kind','architecture','repository','repositoryId','sourceCommit','runId','runAttempt',
        'artifactId','artifactSha256','artifactSize','sourceLockSha256','coreCommit')
    if ($lock -isnot [Collections.IDictionary] -or $lock.Count -ne $keys.Count -or @($lock.Keys | Where-Object {$_ -cnotin $keys}).Count -or
        -not (Test-EnginePositiveInteger $lock.schemaVersion) -or $lock.schemaVersion -ne 1 -or
        $lock.kind -cne 'calc-dispatch-diagnostic-input' -or $lock.architecture -cne 'arm64' -or $lock.repository -cne 'ATLKR/OpenGeul' -or
        -not (Test-EnginePositiveInteger $lock.repositoryId) -or $lock.repositoryId -ne 1405493151 -or
        $lock.coreCommit -cne 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1' -or
        $lock.sourceCommit -isnot [string] -or $lock.sourceCommit -cnotmatch '^[0-9a-f]{40}$' -or $lock.sourceCommit -ceq ('0'*40) -or
        $lock.sourceLockSha256 -isnot [string] -or $lock.sourceLockSha256 -cnotmatch '^[0-9a-f]{64}$' -or
        -not (Test-EnginePositiveInteger $lock.runId) -or -not (Test-EnginePositiveInteger $lock.runAttempt) -or $lock.runAttempt -ne 1 -or
        -not (Test-EnginePositiveInteger $lock.artifactId) -or -not (Test-EnginePositiveInteger $lock.artifactSize) -or $lock.artifactSize -gt 8599371776 -or
        $lock.artifactSha256 -isnot [string] -or $lock.artifactSha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Complete externally pinned diagnostic artifact lock required.' }
    $token=if ($env:GH_TOKEN) {$env:GH_TOKEN} else {$env:GITHUB_TOKEN}
    if ([string]::IsNullOrWhiteSpace($token)) { throw 'GH_TOKEN or GITHUB_TOKEN with workflow artifact read access is required.' }
    Assert-EngineUnlinkedPath $Output
    if (Test-Path -LiteralPath $Output) { throw 'Diagnostic fetch output already exists; preserve the original owned evidence.' }
    $outputPath=[IO.Path]::GetFullPath($Output)
    New-Item -ItemType Directory -Path $outputPath -ErrorAction Stop | Out-Null
    $ownApi=-not $ApiClient; $ownDownload=-not $DownloadClient
    $started=[DateTime]::UtcNow; $clock=[Diagnostics.Stopwatch]::StartNew()
    $cancellation=[Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($TimeoutSeconds))
    $audit=[ordered]@{schemaVersion=1;kind='authenticated-calc-dispatch-download';passed=$false;stage='github-metadata';
        repository=$lock.repository;artifactId=$lock.artifactId;runId=$lock.runId;runAttempt=$lock.runAttempt;sourceCommit=$lock.sourceCommit;
        sourceLockSha256=$lock.sourceLockSha256;coreCommit=$lock.coreCommit;artifactSha256=$lock.artifactSha256;artifactSize=$lock.artifactSize;
        startedUtc=$started.ToString('o');timeoutSeconds=$TimeoutSeconds;deadlineUtc=$started.AddSeconds($TimeoutSeconds).ToString('o');deadlineExceeded=$false}
    try {
        if ($ownApi) {$ApiClient=New-EngineFetchClient}
        if ($ownDownload) {$DownloadClient=New-EngineFetchClient}
        $api='https://api.github.com/repos/ATLKR/OpenGeul/actions'
        $artifact=Read-EngineApiJson $ApiClient ($api+'/artifacts/'+$lock.artifactId) $token $cancellation.Token
        $run=Read-EngineApiJson $ApiClient ($api+'/runs/'+$lock.runId) $token $cancellation.Token
        foreach ($key in @('head_sha','status','conclusion','event','head_branch','path')) {
            if ($run[$key] -isnot [string]) { throw 'Diagnostic producer run requires scalar identity fields.' }
        }
        if (-not (Test-EnginePositiveInteger $run.id) -or $run.id -ne $lock.runId -or
            -not (Test-EnginePositiveInteger $run.run_attempt) -or $run.run_attempt -ne 1 -or
            $run.head_sha -cne $lock.sourceCommit -or $run.status -cne 'completed' -or $run.conclusion -cne 'success' -or
            $run.event -cne 'push' -or $run.head_branch -cne 'work/opengeul-office-native-engine' -or
            $run.path -cne '.github/workflows/office-native-engine.yml' -or
            $run.actor.login -isnot [string] -or $run.actor.login -cne 'ATLKR' -or
            $run.actor.type -isnot [string] -or $run.actor.type -cne 'User' -or
            -not (Test-EnginePositiveInteger $run.actor.id) -or $run.actor.id -ne 65988341) { throw 'Diagnostic producer run differs from the pinned first owner push.' }
        foreach ($repository in @($run.repository,$run.head_repository)) {
            if ($repository.full_name -isnot [string] -or $repository.full_name -cne $lock.repository -or -not (Test-EnginePositiveInteger $repository.id) -or
                $repository.id -ne $lock.repositoryId -or $repository.private -isnot [bool] -or $repository.private) { throw 'Diagnostic producer repository differs.' }
        }
        if (-not (Test-EnginePositiveInteger $artifact.id) -or $artifact.id -ne $lock.artifactId -or
            $artifact.name -isnot [string] -or $artifact.name -cne ('opengeul-native-arm64-calc-dispatch-'+$lock.runId+'-1') -or
            $artifact.digest -isnot [string] -or $artifact.digest -cne ('sha256:'+$lock.artifactSha256) -or $artifact.expired -isnot [bool] -or $artifact.expired -or
            -not (Test-EnginePositiveInteger $artifact.size_in_bytes) -or $artifact.size_in_bytes -ne $lock.artifactSize -or
            -not (Test-EnginePositiveInteger $artifact.workflow_run.id) -or $artifact.workflow_run.id -ne $lock.runId -or
            -not (Test-EnginePositiveInteger $artifact.workflow_run.repository_id) -or $artifact.workflow_run.repository_id -ne $lock.repositoryId -or
            -not (Test-EnginePositiveInteger $artifact.workflow_run.head_repository_id) -or $artifact.workflow_run.head_repository_id -ne $lock.repositoryId -or
            $artifact.workflow_run.head_sha -isnot [string] -or $artifact.workflow_run.head_sha -cne $lock.sourceCommit) { throw 'Diagnostic artifact metadata differs from the external pins.' }
        $metadata=@{schemaVersion=1;repository=$lock.repository;
            artifact=@{id=$artifact.id;name=$artifact.name;digest=$artifact.digest;size_in_bytes=$artifact.size_in_bytes;expired=$artifact.expired;
                workflow_run=@{id=$artifact.workflow_run.id;repository_id=$artifact.workflow_run.repository_id;
                    head_repository_id=$artifact.workflow_run.head_repository_id;head_sha=$artifact.workflow_run.head_sha}};
            run=@{id=$run.id;run_attempt=$run.run_attempt;head_sha=$run.head_sha;status=$run.status;conclusion=$run.conclusion;
                event=$run.event;head_branch=$run.head_branch;path=$run.path;actor=@{id=$run.actor.id;login=$run.actor.login};repositoryId=$lock.repositoryId}}
        Write-EngineFetchJson (Join-Path $outputPath 'artifact-server-metadata.json') $metadata
        $audit.stage='authenticated-outer-zip'
        $archive=Join-Path $outputPath 'github-artifact.zip'
        Save-EngineArtifact $ApiClient $DownloadClient ($api+'/artifacts/'+$lock.artifactId+'/zip') $token $archive $lock.artifactSize $lock.artifactSha256 $cancellation.Token
        $audit.stage='extract-exact-inputs'
        $inputs=Expand-CalcDispatchArtifact $archive $outputPath $lock $cancellation.Token
        foreach ($key in $inputs.Keys) {$audit[$key]=$inputs[$key]}
        $cancellation.Token.ThrowIfCancellationRequested()
        $audit.passed=$true; $audit.stage='complete'
    } catch {
        $audit.deadlineExceeded=$cancellation.IsCancellationRequested
        # HTTP exceptions may contain credentials or signed URLs. Preserve only the stage.
        throw ('Calc dispatch fetch failed at '+$audit.stage+'; inspect the sanitized download receipt.')
    } finally {
        $audit.finishedUtc=[DateTime]::UtcNow.ToString('o'); $audit.elapsedSeconds=$clock.Elapsed.TotalSeconds
        Write-EngineFetchJson (Join-Path $outputPath 'calc-dispatch-download.json') $audit
        if ($ownApi -and $ApiClient) {$ApiClient.Dispose()}
        if ($ownDownload -and $DownloadClient) {$DownloadClient.Dispose()}
        $cancellation.Dispose(); $token=$null
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-CalcDispatchFetch -DiagnosticLockPath $DiagnosticLockPath -Output $Output -TimeoutSeconds $TimeoutSeconds
    Write-Host 'Locked Calc dispatch diagnostic inputs authenticated and extracted.'
}
