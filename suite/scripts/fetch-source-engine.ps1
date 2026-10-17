param(
    [string]$SourceLockPath = 'suite/config/runtime.arm64.lock.json',
    [string]$Output = '.work/source-engine-input'
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

function Write-EngineFetchJson([string]$Path, $Value) {
    $Value | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function New-EngineFetchClient {
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseCookies = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromMinutes(20)
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

function Read-EngineApiJson($Client, [string]$Url, [string]$Token) {
    $request = New-EngineApiRequest $Url $Token
    $response = $null; $stream = $null; $body = [IO.MemoryStream]::new()
    try {
        $response = $Client.SendAsync($request, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        if ([int]$response.StatusCode -ne 200 -or $response.Content.Headers.ContentLength -gt 1048576) { throw 'GitHub metadata status/size rejected.' }
        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $buffer = [byte[]]::new(65536)
        while (($count = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ($body.Length + $count -gt 1048576) { throw 'GitHub metadata exceeds bound.' }
            $body.Write($buffer, 0, $count)
        }
        return ([Text.Encoding]::UTF8.GetString($body.ToArray()) | ConvertFrom-Json -AsHashtable)
    } finally {
        $body.Dispose(); if ($stream) { $stream.Dispose() }; if ($response) { $response.Dispose() }; $request.Dispose()
    }
}

function Copy-EngineBoundedStream($Stream, [string]$Destination, [long]$Size, [string]$Sha256) {
    $file = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $buffer = [byte[]]::new(1048576); [long]$total = 0
        while (($count = $Stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $total += $count
            if ($total -gt $Size) { throw 'Source engine download/extraction exceeds authenticated size.' }
            $file.Write($buffer, 0, $count)
        }
        if ($total -ne $Size) { throw 'Source engine download/extraction size mismatch.' }
    } finally { $file.Dispose() }
    if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Sha256) { throw 'Source engine byte hash mismatch.' }
}

function Save-EngineArtifact($ApiClient, $DownloadClient, [string]$Url, [string]$Token,
                             [string]$Destination, [long]$Size, [string]$Sha256) {
    $request = New-EngineApiRequest $Url $Token
    $redirect = $null; $response = $null; $stream = $null; $download = $null
    try {
        $redirect = $ApiClient.SendAsync($request, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        $location = $redirect.Headers.Location
        if ([int]$redirect.StatusCode -ne 302 -or -not $location -or -not $location.IsAbsoluteUri -or
            $location.Scheme -cne 'https' -or $location.UserInfo -or $location.Fragment -or $location.Port -ne 443) { throw 'GitHub signed download redirect rejected.' }
        # A separate no-auth client receives the signed URL. Never record that URL.
        $download = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get, $location)
        $response = $DownloadClient.SendAsync($download, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        if ([int]$response.StatusCode -ne 200 -or
            ($null -ne $response.Content.Headers.ContentLength -and $response.Content.Headers.ContentLength -ne $Size)) { throw 'Artifact download status/size rejected.' }
        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        Copy-EngineBoundedStream $stream $Destination $Size $Sha256
    } finally {
        if ($stream) { $stream.Dispose() }; if ($response) { $response.Dispose() }; if ($download) { $download.Dispose() }
        if ($redirect) { $redirect.Dispose() }; $request.Dispose()
    }
}

function Expand-EngineArtifact([string]$Archive, [string]$Output, $Runtime) {
    $engineName = 'OpenGeul-Office-engine-arm64.zip'; $receiptName = 'source-build-receipt.json'
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
            try { Copy-EngineBoundedStream $stream (Join-Path $Output $name) $entry.Length $expectedHash }
            finally { $stream.Dispose() }
        }
    } finally { $zip.Dispose() }
}

function Invoke-SourceEngineFetch([string]$SourceLockPath, [string]$Output, $ApiClient = $null, $DownloadClient = $null) {
    Assert-EngineUnlinkedPath $SourceLockPath
    $lock = Get-Content -LiteralPath $SourceLockPath -Raw | ConvertFrom-Json -AsHashtable
    $runtime = $lock.runtime; $build = $runtime.sourceBuild
    if ($lock.schemaVersion -ne 1 -or $lock.architecture -cne 'arm64' -or $runtime.format -cne 'source-built-zip' -or
        -not (Test-EnginePositiveInteger $runtime.size) -or $runtime.size -gt 8589934592 -or
        $runtime.sha256 -cnotmatch '^[0-9a-f]{64}$' -or $build.receiptSha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $build.artifactSha256 -cnotmatch '^[0-9a-f]{64}$' -or $build.patchManifestSha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $build.sourceCommit -cnotmatch '^[0-9a-f]{40}$' -or -not (Test-EnginePositiveInteger $build.runId) -or
        -not (Test-EnginePositiveInteger $build.artifactId) -or ($build.Contains('artifactSize') -and -not (Test-EnginePositiveInteger $build.artifactSize))) { throw 'Complete externally pinned ARM64 source-build lock is required.' }
    $token = if ($env:GH_TOKEN) { $env:GH_TOKEN } else { $env:GITHUB_TOKEN }
    if ([string]::IsNullOrWhiteSpace($token)) { throw 'GH_TOKEN or GITHUB_TOKEN with workflow artifact read access is required.' }
    Assert-EngineUnlinkedPath $Output
    if (Test-Path -LiteralPath $Output) { throw 'Source engine fetch output already exists; choose a fresh owned path.' }
    $outputPath = [IO.Path]::GetFullPath($Output)
    New-Item -ItemType Directory -Path $outputPath -ErrorAction Stop | Out-Null
    $ownApi = -not $ApiClient; $ownDownload = -not $DownloadClient
    $audit = [ordered]@{schemaVersion=1;kind='authenticated-source-engine-download';passed=$false;stage='github-metadata';
        repository='ATLKR/OpenGeul';artifactId=$build.artifactId;runId=$build.runId;sourceCommit=$build.sourceCommit;
        artifactSha256=$build.artifactSha256;startedUtc=[DateTime]::UtcNow.ToString('o')}
    try {
        if ($ownApi) { $ApiClient = New-EngineFetchClient }
        if ($ownDownload) { $DownloadClient = New-EngineFetchClient }
        $api = 'https://api.github.com/repos/ATLKR/OpenGeul/actions'
        $artifact = Read-EngineApiJson $ApiClient ($api+'/artifacts/'+$build.artifactId) $token
        $run = Read-EngineApiJson $ApiClient ($api+'/runs/'+$build.runId) $token
        if (-not (Test-EnginePositiveInteger $artifact.id) -or $artifact.id -ne $build.artifactId -or
            $artifact.digest -cne ('sha256:'+$build.artifactSha256) -or $artifact.expired -isnot [bool] -or $artifact.expired -or
            -not (Test-EnginePositiveInteger $artifact.size_in_bytes) -or $artifact.size_in_bytes -gt $runtime.size + 9437184 -or
            ($build.Contains('artifactSize') -and $artifact.size_in_bytes -ne $build.artifactSize) -or
            -not (Test-EnginePositiveInteger $run.id) -or $run.id -ne $build.runId -or $run.head_sha -cne $build.sourceCommit -or
            $run.status -cne 'completed' -or $run.conclusion -cne 'success' -or
            $run.path -cne '.github/workflows/office-native-engine.yml' -or -not (Test-EnginePositiveInteger $run.run_attempt) -or
            $artifact.name -cne ('opengeul-native-arm64-engine-'+$build.runId+'-'+$run.run_attempt) -or
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
        Save-EngineArtifact $ApiClient $DownloadClient ($api+'/artifacts/'+$build.artifactId+'/zip') $token $archive $artifact.size_in_bytes $build.artifactSha256
        $audit.artifactSize = $artifact.size_in_bytes
        $audit.stage = 'extract-exact-inputs'
        Expand-EngineArtifact $archive $outputPath $runtime
        $audit.engineSize = $runtime.size; $audit.engineSha256 = $runtime.sha256; $audit.receiptSha256 = $build.receiptSha256
        $audit.passed = $true; $audit.stage = 'complete'
    } catch {
        # HTTP exceptions can contain credentials or signed URLs. Never echo or serialize them.
        throw ('Source engine fetch failed at '+$audit.stage+'; inspect the sanitized download receipt.')
    } finally {
        $audit.finishedUtc = [DateTime]::UtcNow.ToString('o')
        Write-EngineFetchJson (Join-Path $outputPath 'source-engine-download.json') $audit
        if ($ownApi -and $ApiClient) { $ApiClient.Dispose() }; if ($ownDownload -and $DownloadClient) { $DownloadClient.Dispose() }
        $token = $null
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-SourceEngineFetch -SourceLockPath $SourceLockPath -Output $Output
    Write-Host 'Source engine inputs authenticated and extracted.'
}
