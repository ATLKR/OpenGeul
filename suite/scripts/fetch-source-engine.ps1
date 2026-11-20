param(
    [string]$SourceLockPath = 'suite/config/runtime.arm64.lock.json',
    [string]$Output = '.work/source-engine-input',
    [ValidateRange(1,1200)][int]$TimeoutSeconds = 1200
)
$ErrorActionPreference = 'Stop'

function Test-EnginePositiveInteger($Value) {
    return (($Value -is [int] -or $Value -is [long]) -and $Value -gt 0)
}

function Assert-EngineUnlinkedPath([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked fetch input/output path is forbidden.' }
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

function Test-EngineExactString($Value, [string]$Expected) {
    return ($Value -is [string] -and $Value -ceq $Expected)
}

function Get-EngineNativeTarget([string]$Architecture) {
    if ($Architecture -cnotin @('arm64','x64')) { throw 'Unsupported source engine architecture.' }
    $folder = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../engine-build'))
    $policyPath = Join-Path $folder 'native-targets.json'
    $manifestPath = Join-Path $folder 'source-build.json'
    Assert-EngineUnlinkedPath $policyPath; Assert-EngineUnlinkedPath $manifestPath
    $expected = 'ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc'
    $bytes = [IO.File]::ReadAllBytes($policyPath)
    if ($bytes.Length -ne 1987 -or [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant() -cne $expected) {
        throw 'Tracked native target policy differs from reviewed bytes.'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json -AsHashtable
    $descriptor = $manifest.nativeTargets
    if ($descriptor -isnot [Collections.IDictionary] -or $descriptor.Count -ne 3 -or
        -not (Test-EngineExactString $descriptor.filename 'native-targets.json') -or
        -not (Test-EnginePositiveInteger $descriptor.size) -or $descriptor.size -ne 1987 -or
        -not (Test-EngineExactString $descriptor.sha256 $expected)) { throw 'Native target manifest binding differs.' }
    $policy = [Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json -AsHashtable
    return $policy.targets[$Architecture]
}

function Assert-EngineX64ServerBinding($Artifact, $Run, $Jobs, $Target, $Build) {
    $branch = $Target.ref.Substring('refs/heads/'.Length)
    $strings = @(
        @{actual=$Run.status;expected='completed'}, @{actual=$Run.conclusion;expected='success'},
        @{actual=$Run.event;expected='push'}, @{actual=$Run.path;expected=$Target.workflow},
        @{actual=$Run.head_branch;expected=$branch}, @{actual=$Run.head_sha;expected=$Build.sourceCommit},
        @{actual=$Run.repository.full_name;expected='ATLKR/OpenGeul'},
        @{actual=$Run.head_repository.full_name;expected='ATLKR/OpenGeul'},
        @{actual=$Run.actor.login;expected='ATLKR'}, @{actual=$Run.actor.type;expected='User'},
        @{actual=$Run.triggering_actor.login;expected='ATLKR'}, @{actual=$Run.triggering_actor.type;expected='User'},
        @{actual=$Artifact.workflow_run.head_branch;expected=$branch},
        @{actual=$Artifact.workflow_run.head_sha;expected=$Build.sourceCommit},
        @{actual=$Artifact.name;expected=($Target.artifactPrefix+$Build.runId+'-1')}
    )
    foreach ($pair in $strings) { if (-not (Test-EngineExactString $pair.actual $pair.expected)) { throw 'x64 source owner/run binding differs.' } }
    foreach ($value in @($Run.repository.id,$Run.head_repository.id,$Artifact.workflow_run.repository_id,$Artifact.workflow_run.head_repository_id)) {
        if (-not (Test-EnginePositiveInteger $value) -or $value -ne 1405493151) { throw 'x64 source repository identity differs.' }
    }
    foreach ($value in @($Run.actor.id,$Run.triggering_actor.id)) {
        if (-not (Test-EnginePositiveInteger $value) -or $value -ne 65988341) { throw 'x64 source actor identity differs.' }
    }
    if (-not (Test-EnginePositiveInteger $Run.run_attempt) -or $Run.run_attempt -ne 1 -or
        -not (Test-EnginePositiveInteger $Jobs.total_count) -or $Jobs.total_count -ne 1 -or
        $Jobs.jobs -isnot [array] -or $Jobs.jobs.Count -ne 1) { throw 'x64 source requires one first-attempt fixed job.' }
    $job = $Jobs.jobs[0]
    if (-not (Test-EnginePositiveInteger $job.id) -or -not (Test-EnginePositiveInteger $job.run_id) -or $job.run_id -ne $Build.runId -or
        -not (Test-EngineExactString $job.name $Target.job) -or -not (Test-EngineExactString $job.head_sha $Build.sourceCommit) -or
        -not (Test-EngineExactString $job.status 'completed') -or -not (Test-EngineExactString $job.conclusion 'success')) { throw 'x64 fixed native job did not qualify.' }
    return $job
}

function Assert-EngineX64ReceiptBinding([string]$Path, $Runtime, $Target) {
    $proof = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable
    $build = $Runtime.sourceBuild; $binding = $proof.workflowBinding
    if ($proof -isnot [Collections.IDictionary] -or -not (Test-EnginePositiveInteger $proof.schemaVersion) -or $proof.schemaVersion -ne 2 -or
        $binding -isnot [Collections.IDictionary]) { throw 'x64 source receipt schema differs.' }
    foreach ($flag in @('passed','fullEngineQualified','acceptanceEligible')) {
        if ($proof[$flag] -isnot [bool] -or -not $proof[$flag]) { throw 'x64 source receipt is unqualified.' }
    }
    if ($proof.guiVerified -isnot [bool] -or $proof.guiVerified) { throw 'Source proof cannot qualify GUI behavior.' }
    $strings = @(
        @{actual=$proof.kind;expected='native-office-engine-source-build'}, @{actual=$proof.phase;expected='Full'},
        @{actual=$proof.architecture;expected='x64'}, @{actual=$proof.status;expected='native-engine-source-build-qualified'},
        @{actual=$proof.sourceCommit;expected=$build.sourceCommit}, @{actual=$proof.sourceTree;expected=$build.sourceTree},
        @{actual=$proof.driverSha256;expected=$build.driverSha256}, @{actual=$proof.nativeTargetsSha256;expected=$build.nativeTargetsSha256},
        @{actual=$proof.sourcePortManifestSha256;expected=$build.patchManifestSha256},
        @{actual=$binding.workflow;expected=$Target.workflow}, @{actual=$binding.ref;expected=$Target.ref},
        @{actual=$binding.workflowRef;expected=('ATLKR/OpenGeul/'+$Target.workflow+'@'+$Target.ref)},
        @{actual=$binding.job;expected=$Target.job}, @{actual=$binding.sourceCommit;expected=$build.sourceCommit},
        @{actual=$binding.sourceTree;expected=$build.sourceTree}, @{actual=$proof.artifact.sha256;expected=$Runtime.sha256}
    )
    foreach ($pair in $strings) { if (-not (Test-EngineExactString $pair.actual $pair.expected)) { throw 'x64 receipt differs from reviewed external source pins.' } }
    foreach ($value in @($proof.sourceRun,$binding.sourceRun)) {
        if (-not (Test-EnginePositiveInteger $value) -or $value -ne $build.runId) { throw 'x64 receipt source run differs.' }
    }
    foreach ($value in @($proof.runAttempt,$binding.runAttempt)) {
        if (-not (Test-EnginePositiveInteger $value) -or $value -ne 1) { throw 'x64 receipt requires the first source attempt.' }
    }
    if (-not (Test-EnginePositiveInteger $proof.artifact.size) -or $proof.artifact.size -ne $Runtime.size) { throw 'x64 receipt engine size differs.' }
}

function Write-EngineFetchJson([string]$Path, $Value) {
    $Value | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function New-EngineFetchClient {
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseCookies = $false
    $client = [Net.Http.HttpClient]::new($handler)
    # One operation-owned cancellation deadline covers every request and body.
    $client.Timeout = [Threading.Timeout]::InfiniteTimeSpan
    return $client
}

function New-EngineApiRequest([string]$Url, [string]$Token) {
    $request = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get, $Url)
    $request.Headers.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $Token)
    $request.Headers.UserAgent.ParseAdd('OpenGeul-Office-source-engine-fetch/1')
    $request.Headers.Accept.ParseAdd('application/vnd.github+json')
    $request.Headers.Add('X-GitHub-Api-Version', '2022-11-28')
    return $request
}

function Read-EngineApiJson($Client, [string]$Url, [string]$Token,
                            [Threading.CancellationToken]$CancellationToken = [Threading.CancellationToken]::None) {
    $request = New-EngineApiRequest $Url $Token
    $response = $null; $stream = $null; $body = [IO.MemoryStream]::new()
    try {
        $response = $Client.SendAsync($request, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $CancellationToken).WaitAsync($CancellationToken).GetAwaiter().GetResult()
        if ([int]$response.StatusCode -ne 200 -or $response.Content.Headers.ContentLength -gt 1048576) { throw 'GitHub metadata status/size rejected.' }
        $stream = $response.Content.ReadAsStreamAsync($CancellationToken).WaitAsync($CancellationToken).GetAwaiter().GetResult()
        $buffer = [byte[]]::new(65536)
        while (($count = $stream.ReadAsync($buffer, 0, $buffer.Length, $CancellationToken).WaitAsync($CancellationToken).GetAwaiter().GetResult()) -gt 0) {
            if ($body.Length + $count -gt 1048576) { throw 'GitHub metadata exceeds bound.' }
            $body.Write($buffer, 0, $count)
        }
        $CancellationToken.ThrowIfCancellationRequested()
        return ([Text.Encoding]::UTF8.GetString($body.ToArray()) | ConvertFrom-Json -AsHashtable)
    } finally {
        $body.Dispose(); if ($stream) { $stream.Dispose() }; if ($response) { $response.Dispose() }; $request.Dispose()
    }
}

function Copy-EngineBoundedStream($Stream, [string]$Destination, [long]$Size, [string]$Sha256,
                                  [Threading.CancellationToken]$CancellationToken = [Threading.CancellationToken]::None) {
    $file = $null; $hash = $null
    try {
        $CancellationToken.ThrowIfCancellationRequested()
        $file = [IO.FileStream]::new($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write,
                                   [IO.FileShare]::None, 65536, [IO.FileOptions]::Asynchronous)
        $hash = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
        $buffer = [byte[]]::new(1048576); [long]$total = 0
        while (($count = $Stream.ReadAsync($buffer, 0, $buffer.Length, $CancellationToken).WaitAsync($CancellationToken).GetAwaiter().GetResult()) -gt 0) {
            $total += $count
            if ($total -gt $Size) { throw 'Source engine download/extraction exceeds authenticated size.' }
            $file.WriteAsync($buffer, 0, $count, $CancellationToken).WaitAsync($CancellationToken).GetAwaiter().GetResult() | Out-Null
            $hash.AppendData($buffer, 0, $count)
        }
        $CancellationToken.ThrowIfCancellationRequested()
        if ($total -ne $Size) { throw 'Source engine download/extraction size mismatch.' }
        $actual = [Convert]::ToHexString($hash.GetHashAndReset()).ToLowerInvariant()
        if ($actual -cne $Sha256) { throw 'Source engine byte hash mismatch.' }
    } finally { if ($hash) { $hash.Dispose() }; if ($file) { $file.Dispose() } }
}

function Save-EngineArtifact($ApiClient, $DownloadClient, [string]$Url, [string]$Token,
                             [string]$Destination, [long]$Size, [string]$Sha256,
                             [Threading.CancellationToken]$CancellationToken = [Threading.CancellationToken]::None) {
    $request = New-EngineApiRequest $Url $Token
    $redirect = $null; $response = $null; $stream = $null; $download = $null
    try {
        $redirect = $ApiClient.SendAsync($request, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $CancellationToken).WaitAsync($CancellationToken).GetAwaiter().GetResult()
        $location = $redirect.Headers.Location
        if ([int]$redirect.StatusCode -ne 302 -or -not $location -or -not $location.IsAbsoluteUri -or
            $location.Scheme -cne 'https' -or $location.UserInfo -or $location.Fragment -or $location.Port -ne 443) { throw 'GitHub signed download redirect rejected.' }
        # A separate no-auth client receives the signed URL. Never record that URL.
        $download = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get, $location)
        $response = $DownloadClient.SendAsync($download, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $CancellationToken).WaitAsync($CancellationToken).GetAwaiter().GetResult()
        if ([int]$response.StatusCode -ne 200 -or
            ($null -ne $response.Content.Headers.ContentLength -and $response.Content.Headers.ContentLength -ne $Size)) { throw 'Artifact download status/size rejected.' }
        $stream = $response.Content.ReadAsStreamAsync($CancellationToken).WaitAsync($CancellationToken).GetAwaiter().GetResult()
        Copy-EngineBoundedStream $stream $Destination $Size $Sha256 $CancellationToken
    } finally {
        if ($stream) { $stream.Dispose() }; if ($response) { $response.Dispose() }; if ($download) { $download.Dispose() }
        if ($redirect) { $redirect.Dispose() }; $request.Dispose()
    }
}

function Expand-EngineArtifact([string]$Archive, [string]$Output, $Runtime,
                               [Threading.CancellationToken]$CancellationToken = [Threading.CancellationToken]::None,
                               [ValidateSet('arm64','x64',IgnoreCase=$false)][string]$Architecture = 'arm64') {
    $CancellationToken.ThrowIfCancellationRequested()
    $target = Get-EngineNativeTarget $Architecture
    $engineName = $target.archive; $receiptName = 'source-build-receipt.json'
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        if ($zip.Entries.Count -ne 2) { throw 'Engine artifact must contain exactly the two qualified input files.' }
        $members = @{}
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName
            [long]$attributes = [long]$entry.ExternalAttributes -band 0xffffffffL
            $kind = ($attributes -shr 16) -band 0xf000
            if (($name -cne $engineName -and $name -cne $receiptName) -or $members.ContainsKey($name) -or
                $kind -notin @(0, 0x8000) -or ($attributes -band 0x410)) { throw 'Unsafe or aliased engine artifact member.' }
            if (($name -ceq $engineName -and $entry.Length -ne $Runtime.size) -or
                ($name -ceq $receiptName -and ($entry.Length -le 0 -or $entry.Length -gt 8388608))) { throw 'Engine artifact member exceeds locked size/bound.' }
            $members[$name] = $entry
        }
        if ($members.Count -ne 2 -or -not $members.ContainsKey($engineName) -or -not $members.ContainsKey($receiptName)) { throw 'Engine artifact input family is incomplete.' }
        foreach ($name in @($engineName, $receiptName)) {
            $expectedHash = if ($name -ceq $engineName) { $Runtime.sha256 } else { $Runtime.sourceBuild.receiptSha256 }
            $entry = $members[$name]; $stream = $entry.Open()
            try { Copy-EngineBoundedStream $stream (Join-Path $Output $name) $entry.Length $expectedHash $CancellationToken }
            finally { $stream.Dispose() }
        }
    } finally { $zip.Dispose() }
}

function Invoke-SourceEngineFetch([string]$SourceLockPath, [string]$Output, $ApiClient = $null, $DownloadClient = $null,
                                  [ValidateRange(1,1200)][int]$TimeoutSeconds = 1200) {
    Assert-EngineUnlinkedPath $SourceLockPath
    $lock = Get-Content -LiteralPath $SourceLockPath -Raw | ConvertFrom-Json -AsHashtable
    $runtime = $lock.runtime; $build = $runtime.sourceBuild
    if ($lock -isnot [Collections.IDictionary] -or -not (Test-EnginePositiveInteger $lock.schemaVersion) -or $lock.schemaVersion -ne 1 -or
        $lock.architecture -isnot [string] -or $lock.architecture -cnotin @('arm64','x64') -or
        $runtime -isnot [Collections.IDictionary] -or $build -isnot [Collections.IDictionary] -or
        -not (Test-EngineExactString $runtime.format 'source-built-zip') -or
        -not (Test-EnginePositiveInteger $runtime.size) -or $runtime.size -gt 8589934592 -or
        $build.sourceCommit -isnot [string] -or $build.sourceCommit -cnotmatch '^[0-9a-f]{40}$' -or
        -not (Test-EnginePositiveInteger $build.runId) -or -not (Test-EnginePositiveInteger $build.artifactId) -or
        ($build.Contains('artifactSize') -and -not (Test-EnginePositiveInteger $build.artifactSize))) {
        throw 'Complete externally pinned native source-build lock is required.'
    }
    foreach ($value in @($runtime.sha256,$build.receiptSha256,$build.artifactSha256,$build.patchManifestSha256)) {
        if ($value -isnot [string] -or $value -cnotmatch '^[0-9a-f]{64}$') { throw 'Source engine lock hashes require exact scalar digests.' }
    }
    $target = Get-EngineNativeTarget $lock.architecture
    if ($lock.architecture -ceq 'x64' -and ($build.sourceTree -isnot [string] -or $build.sourceTree -cnotmatch '^[0-9a-f]{40}$' -or
        $build.driverSha256 -isnot [string] -or $build.driverSha256 -cnotmatch '^[0-9a-f]{64}$' -or
        -not (Test-EngineExactString $build.nativeTargetsSha256 'ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc'))) {
        throw 'x64 source build requires independently reviewed tree, driver and policy pins.'
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
    $audit = [ordered]@{schemaVersion=1;kind='authenticated-source-engine-download';passed=$false;stage='github-metadata';
        repository='ATLKR/OpenGeul';architecture=$lock.architecture;artifactId=$build.artifactId;runId=$build.runId;sourceCommit=$build.sourceCommit;
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
            -not (Test-EnginePositiveInteger $artifact.size_in_bytes) -or $artifact.size_in_bytes -gt $runtime.size + 9437184 -or
            ($build.Contains('artifactSize') -and $artifact.size_in_bytes -ne $build.artifactSize) -or
            -not (Test-EnginePositiveInteger $run.id) -or $run.id -ne $build.runId -or $run.head_sha -cne $build.sourceCommit -or
            $run.status -cne 'completed' -or $run.conclusion -cne 'success' -or
            $run.path -cne $target.workflow -or -not (Test-EnginePositiveInteger $run.run_attempt) -or
            $artifact.name -cne ($target.artifactPrefix+$build.runId+'-'+$run.run_attempt) -or
            $run.repository.full_name -cne 'ATLKR/OpenGeul' -or $run.head_repository.full_name -cne 'ATLKR/OpenGeul' -or
            -not (Test-EnginePositiveInteger $run.repository.id) -or -not (Test-EnginePositiveInteger $run.head_repository.id) -or
            $run.head_repository.id -ne $run.repository.id -or -not (Test-EnginePositiveInteger $artifact.workflow_run.id) -or
            $artifact.workflow_run.id -ne $build.runId -or -not (Test-EnginePositiveInteger $artifact.workflow_run.repository_id) -or
            $artifact.workflow_run.repository_id -ne $run.repository.id -or -not (Test-EnginePositiveInteger $artifact.workflow_run.head_repository_id) -or
            $artifact.workflow_run.head_repository_id -ne $run.repository.id -or $artifact.workflow_run.head_sha -cne $build.sourceCommit) { throw 'GitHub artifact/run metadata differs from locked successful source build.' }
        $job = $null
        if ($lock.architecture -ceq 'x64') {
            $jobs = Read-EngineApiJson $ApiClient ($api+'/runs/'+$build.runId+'/attempts/1/jobs?per_page=100') $token $cancellation.Token
            $job = Assert-EngineX64ServerBinding $artifact $run $jobs $target $build
            $audit.sourceTree=$build.sourceTree; $audit.driverSha256=$build.driverSha256; $audit.nativeTargetsSha256=$build.nativeTargetsSha256
        }
        $metadata = [ordered]@{schemaVersion=1;repository='ATLKR/OpenGeul';
            artifact=@{id=$artifact.id;name=$artifact.name;size_in_bytes=$artifact.size_in_bytes;digest=$artifact.digest;expired=$artifact.expired;
                workflow_run=@{id=$artifact.workflow_run.id;repository_id=$artifact.workflow_run.repository_id;head_repository_id=$artifact.workflow_run.head_repository_id;head_sha=$artifact.workflow_run.head_sha}};
            run=@{id=$run.id;run_attempt=$run.run_attempt;head_sha=$run.head_sha;status=$run.status;conclusion=$run.conclusion;path=$run.path;
                repository=@{id=$run.repository.id;full_name=$run.repository.full_name};head_repository=@{id=$run.head_repository.id;full_name=$run.head_repository.full_name}}}
        if ($job) {
            $metadata.job=@{id=$job.id;run_id=$job.run_id;head_sha=$job.head_sha;name=$job.name;status=$job.status;conclusion=$job.conclusion}
            $metadata.run.event=$run.event; $metadata.run.head_branch=$run.head_branch
            $metadata.run.actor=@{id=$run.actor.id;login=$run.actor.login;type=$run.actor.type}
            $metadata.run.triggering_actor=@{id=$run.triggering_actor.id;login=$run.triggering_actor.login;type=$run.triggering_actor.type}
            $metadata.artifact.workflow_run.head_branch=$artifact.workflow_run.head_branch
        }
        Write-EngineFetchJson (Join-Path $outputPath 'artifact-server-metadata.json') $metadata
        $audit.stage = 'authenticated-outer-zip'
        $archive = Join-Path $outputPath 'github-artifact.zip'
        Save-EngineArtifact $ApiClient $DownloadClient ($api+'/artifacts/'+$build.artifactId+'/zip') $token $archive $artifact.size_in_bytes $build.artifactSha256 $cancellation.Token
        $audit.artifactSize = $artifact.size_in_bytes
        $audit.stage = 'extract-exact-inputs'
        Expand-EngineArtifact $archive $outputPath $runtime $cancellation.Token -Architecture $lock.architecture
        if ($lock.architecture -ceq 'x64') {
            $audit.stage='source-receipt-binding'
            Assert-EngineX64ReceiptBinding (Join-Path $outputPath 'source-build-receipt.json') $runtime $target
        }
        $audit.engineSize = $runtime.size; $audit.engineSha256 = $runtime.sha256; $audit.receiptSha256 = $build.receiptSha256
        $cancellation.Token.ThrowIfCancellationRequested()
        $audit.passed = $true; $audit.stage = 'complete'
    } catch {
        $audit.deadlineExceeded = $cancellation.IsCancellationRequested
        # HTTP exceptions can contain credentials or signed URLs. Never echo or serialize them.
        throw ('Source engine fetch failed at '+$audit.stage+'; inspect the sanitized download receipt.')
    } finally {
        $audit.finishedUtc = [DateTime]::UtcNow.ToString('o')
        $audit.elapsedSeconds = $clock.Elapsed.TotalSeconds
        Write-EngineFetchJson (Join-Path $outputPath 'source-engine-download.json') $audit
        if ($ownApi -and $ApiClient) { $ApiClient.Dispose() }; if ($ownDownload -and $DownloadClient) { $DownloadClient.Dispose() }
        $cancellation.Dispose(); $token = $null
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-SourceEngineFetch -SourceLockPath $SourceLockPath -Output $Output -TimeoutSeconds $TimeoutSeconds
    Write-Host 'Source engine inputs authenticated and extracted.'
}
