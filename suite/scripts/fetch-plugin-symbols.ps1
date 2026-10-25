param([string]$SymbolLockPath,[string]$Output,[ValidateRange(1,1200)][int]$TimeoutSeconds=1200)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'fetch-source-engine.ps1')

function Expand-PluginSymbols([string]$Archive,[string]$Output,$Lock,
                              [Threading.CancellationToken]$CancellationToken) {
    $CancellationToken.ThrowIfCancellationRequested()
    $zip=[IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        if ($zip.Entries.Count -ne 3) { throw 'Exactly three symbol inputs required.' }
        $members=@{}
        foreach ($entry in $zip.Entries) {
            $CancellationToken.ThrowIfCancellationRequested()
            $name=$entry.FullName
            [long]$attributes=[long]$entry.ExternalAttributes -band 0xffffffffL
            $kind=($attributes -shr 16) -band 0xf000
            if (-not $Lock.files.Contains($name) -or $members.ContainsKey($name) -or $kind -notin @(0,0x8000) -or
                ($attributes -band 0x410) -or $entry.Length -ne $Lock.files[$name].bytes) { throw 'Unsafe or incorrectly sized symbol member.' }
            $members[$name]=$entry
        }
        $pair=Join-Path $Output 'pair'
        New-Item -ItemType Directory -Path $pair -ErrorAction Stop | Out-Null
        foreach ($name in @('receipt.json','vclplug_winlo.dll','vclplug_winlo.pdb')) {
            $entry=$members[$name];$stream=$entry.Open()
            try { Copy-EngineBoundedStream $stream (Join-Path $pair $name) $entry.Length $Lock.files[$name].sha256 $CancellationToken }
            finally { $stream.Dispose() }
        }
    } finally { $zip.Dispose() }
}

function Invoke-PluginSymbolFetch([string]$SymbolLockPath, [string]$Output, $ApiClient = $null, $DownloadClient = $null,
                                  [ValidateRange(1,1200)][int]$TimeoutSeconds = 1200) {
    Assert-EngineUnlinkedPath $SymbolLockPath
    $lock = Get-Content -LiteralPath $SymbolLockPath -Raw | ConvertFrom-Json -AsHashtable
    $build = $lock
    if ($lock.schemaVersion -ne 1 -or $lock.kind -cne 'native-arm64-plugin-symbols' -or $lock.architecture -cne 'arm64' -or
        $build.artifactSha256 -cnotmatch '^[0-9a-f]{64}$' -or $build.sourceCommit -cnotmatch '^[0-9a-f]{40}$' -or
        -not (Test-EnginePositiveInteger $build.runId) -or -not (Test-EnginePositiveInteger $build.runAttempt) -or
        -not (Test-EnginePositiveInteger $build.artifactId) -or -not (Test-EnginePositiveInteger $build.artifactSize) -or
        $build.artifactSize -gt 536870912 -or $build.files.Count -ne 3) { throw 'Complete symbol artifact pins required.' }
    foreach ($name in @('receipt.json','vclplug_winlo.dll','vclplug_winlo.pdb')) {
        $pin=$build.files[$name]
        $max=if ($name -ceq 'receipt.json') {65536} elseif ($name -ceq 'vclplug_winlo.dll') {33554432} else {268435456}
        if (-not $pin -or -not (Test-EnginePositiveInteger $pin.bytes) -or $pin.bytes -gt $max -or $pin.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid symbol member pin.' }
    }
    $token = if ($env:GH_TOKEN) { $env:GH_TOKEN } else { $env:GITHUB_TOKEN }
    if ([string]::IsNullOrWhiteSpace($token)) { throw 'GH_TOKEN or GITHUB_TOKEN with workflow artifact read access is required.' }
    Assert-EngineUnlinkedPath $Output
    if (Test-Path -LiteralPath $Output) { throw 'Source engine fetch output already exists; choose a fresh owned path.' }
    $outputPath = [IO.Path]::GetFullPath($Output)
    New-Item -ItemType Directory -Path $outputPath -ErrorAction Stop | Out-Null
    $ownApi = -not $ApiClient; $ownDownload = -not $DownloadClient
    $started = [DateTime]::UtcNow; $clock = [Diagnostics.Stopwatch]::StartNew()
    $cancellation = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($TimeoutSeconds))
    $audit = [ordered]@{schemaVersion=1;kind='authenticated-plugin-symbol-download';passed=$false;stage='github-metadata';
        repository='ATLKR/OpenGeul';artifactId=$build.artifactId;runId=$build.runId;sourceCommit=$build.sourceCommit;
        artifactSha256=$build.artifactSha256;startedUtc=$started.ToString('o');
        timeoutSeconds=$TimeoutSeconds;deadlineUtc=$started.AddSeconds($TimeoutSeconds).ToString('o');deadlineExceeded=$false}
    try {
        if ($ownApi) { $ApiClient = New-EngineFetchClient }
        if ($ownDownload) { $DownloadClient = New-EngineFetchClient }
        $api = 'https://api.github.com/repos/ATLKR/OpenGeul/actions'
        $artifact = Read-EngineApiJson $ApiClient ($api+'/artifacts/'+$build.artifactId) $token $cancellation.Token
        $run = Read-EngineApiJson $ApiClient ($api+'/runs/'+$build.runId) $token $cancellation.Token
        if (-not (Test-EnginePositiveInteger $artifact.id) -or $artifact.id -ne $build.artifactId -or
            $artifact.digest -cne ('sha256:'+$build.artifactSha256) -or $artifact.expired -isnot [bool] -or $artifact.expired -or
            -not (Test-EnginePositiveInteger $artifact.size_in_bytes) -or $artifact.size_in_bytes -gt 536870912 -or
            ($build.Contains('artifactSize') -and $artifact.size_in_bytes -ne $build.artifactSize) -or
            -not (Test-EnginePositiveInteger $run.id) -or $run.id -ne $build.runId -or $run.head_sha -cne $build.sourceCommit -or
            $run.status -cne 'completed' -or $run.conclusion -cne 'success' -or
            $run.run_attempt -ne $build.runAttempt -or $run.path -cne '.github/workflows/office-native-engine.yml' -or -not (Test-EnginePositiveInteger $run.run_attempt) -or
            $artifact.name -cne ('opengeul-native-arm64-plugin-symbols-'+$build.runId+'-'+$run.run_attempt) -or
            $run.repository.full_name -cne 'ATLKR/OpenGeul' -or $run.head_repository.full_name -cne 'ATLKR/OpenGeul' -or
            -not (Test-EnginePositiveInteger $run.repository.id) -or -not (Test-EnginePositiveInteger $run.head_repository.id) -or
            $run.head_repository.id -ne $run.repository.id -or -not (Test-EnginePositiveInteger $artifact.workflow_run.id) -or
            $artifact.workflow_run.id -ne $build.runId -or -not (Test-EnginePositiveInteger $artifact.workflow_run.repository_id) -or
            $artifact.workflow_run.repository_id -ne $run.repository.id -or -not (Test-EnginePositiveInteger $artifact.workflow_run.head_repository_id) -or
            $artifact.workflow_run.head_repository_id -ne $run.repository.id -or $artifact.workflow_run.head_sha -cne $build.sourceCommit) { throw 'GitHub artifact/run metadata differs from locked successful source build.' }
        $metadata = [ordered]@{schemaVersion=1;repository='ATLKR/OpenGeul';
            artifact=@{id=$artifact.id;name=$artifact.name;size_in_bytes=$artifact.size_in_bytes;digest=$artifact.digest;expired=$artifact.expired;
                workflow_run=@{id=$artifact.workflow_run.id;repository_id=$artifact.workflow_run.repository_id;head_repository_id=$artifact.workflow_run.head_repository_id;head_sha=$artifact.workflow_run.head_sha}};
            run=@{id=$run.id;run_attempt=$run.run_attempt;head_sha=$run.head_sha;status=$run.status;conclusion=$run.conclusion;path=$run.path;
                repository=@{id=$run.repository.id;full_name=$run.repository.full_name};head_repository=@{id=$run.head_repository.id;full_name=$run.head_repository.full_name}}}
        Write-EngineFetchJson (Join-Path $outputPath 'artifact-server-metadata.json') $metadata
        $audit.stage = 'authenticated-outer-zip'
        $archive = Join-Path $outputPath 'github-artifact.zip'
        Save-EngineArtifact $ApiClient $DownloadClient ($api+'/artifacts/'+$build.artifactId+'/zip') $token $archive $artifact.size_in_bytes $build.artifactSha256 $cancellation.Token
        $audit.artifactSize = $artifact.size_in_bytes
        $audit.stage = 'extract-exact-inputs'
        Expand-PluginSymbols $archive $outputPath $build $cancellation.Token
        $cancellation.Token.ThrowIfCancellationRequested()
        $audit.passed = $true; $audit.stage = 'complete'
    } catch {
        $audit.deadlineExceeded = $cancellation.IsCancellationRequested
        # HTTP exceptions can contain credentials or signed URLs. Never echo or serialize them.
        throw ('Source engine fetch failed at '+$audit.stage+'; inspect the sanitized download receipt.')
    } finally {
        $audit.finishedUtc = [DateTime]::UtcNow.ToString('o')
        $audit.elapsedSeconds = $clock.Elapsed.TotalSeconds
        Write-EngineFetchJson (Join-Path $outputPath 'plugin-symbol-download.json') $audit
        if ($ownApi -and $ApiClient) { $ApiClient.Dispose() }; if ($ownDownload -and $DownloadClient) { $DownloadClient.Dispose() }
        $cancellation.Dispose(); $token = $null
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-PluginSymbolFetch -SymbolLockPath $SymbolLockPath -Output $Output -TimeoutSeconds $TimeoutSeconds
    Write-Host 'Exact matched plugin inputs authenticated and extracted.'
}
