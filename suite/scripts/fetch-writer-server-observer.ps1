param([string]$DiagnosticLockPath, [string]$Output,
      [ValidateRange(1,1200)][int]$TimeoutSeconds=1200)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'fetch-source-engine.ps1') -Output $Output -TimeoutSeconds $TimeoutSeconds

function Assert-WriterObserverValues($Value, [hashtable]$Strings=@{}, [hashtable]$Numbers=@{}, [hashtable]$Flags=@{}) {
    if ($Value -isnot [Collections.IDictionary]) { throw 'Writer diagnostic object required.' }
    foreach ($key in $Strings.Keys) {
        if ($Value[$key] -isnot [string] -or $Value[$key] -cne $Strings[$key]) { throw 'Writer diagnostic identity differs.' }
    }
    foreach ($key in $Numbers.Keys) {
        if (($Value[$key] -isnot [int] -and $Value[$key] -isnot [long]) -or $Value[$key] -ne $Numbers[$key]) { throw 'Writer diagnostic integer identity differs.' }
    }
    foreach ($key in $Flags.Keys) {
        if ($Value[$key] -isnot [bool] -or $Value[$key] -ne $Flags[$key]) { throw 'Writer diagnostic qualification differs.' }
    }
}

function Assert-WriterObserverLibraries($Value) {
    if ($Value -isnot [array] -or $Value.Count -ne 2 -or $Value[0] -isnot [string] -or $Value[0] -cne 'UAccCOM' -or
        $Value[1] -isnot [string] -or $Value[1] -cne 'winaccessibility') { throw 'Both Writer source libraries are required.' }
}

function Assert-WriterObserverDescriptor($Value, [string]$Path, [string]$Hash) {
    Assert-WriterObserverValues $Value @{path=$Path;sha256=$Hash}
    if ($Value.Count -ne 3 -or -not (Test-EnginePositiveInteger $Value.bytes) -or $Value.bytes -gt 8388608) { throw 'Writer source descriptor differs.' }
}

function Assert-WriterObserverMarker($Marker, $Lock, $Hooks, $Reference=$null) {
    Assert-WriterObserverValues $Marker @{kind='writer-server-observer-diagnostic';family='writer-server-observer-diagnostic';
        sourceCommit=$Lock.sourceCommit;sourceTree=$Lock.sourceTree;coreCommit=$Lock.coreCommit;
        sourceLockSha256=$Lock.sourceLockSha256;patchSha256=$Lock.patchSha256} @{
        schemaVersion=1;sourceRun=$Lock.runId;runAttempt=$Lock.runAttempt;ipcVersion=1;sinkAbiVersion=2;mappingBytes=131328;descriptorSchemaVersion=1} @{
        fullEngineQualified=$false;acceptanceEligible=$false;guiVerified=$false}
    $keys=@('schemaVersion','kind','family','sourceCommit','sourceTree','sourceRun','runAttempt','coreCommit','sourceLockSha256','patchSha256',
        'wireSchema','ipcVersion','sinkAbiVersion','mappingBytes','descriptorSchemaVersion','requiredRebuiltLibraries',
        'binaries','fullEngineQualified','acceptanceEligible','guiVerified')
    if ($Marker.Count -ne $keys.Count -or @($Marker.Keys|Where-Object {$_ -cnotin $keys}).Count) { throw 'Writer runtime marker shape differs.' }
    Assert-WriterObserverLibraries $Marker.requiredRebuiltLibraries
    Assert-WriterObserverDescriptor $Marker.wireSchema 'wire-schema.json' $Lock.wireSchemaSha256
    if ($Marker.wireSchema.bytes -ne $Hooks.wireSchema.bytes -or $Marker.binaries -isnot [array] -or $Marker.binaries.Count -ne 2) { throw 'Writer runtime descriptor join differs.' }
    $paths=@('program/UAccCOM.dll','program/winaccessibility.dll')
    for ($index=0;$index -lt 2;$index++) {
        $binary=$Marker.binaries[$index]
        Assert-WriterObserverValues $binary @{path=$paths[$index]} @{machine=0xaa64}
        if ($binary.Count -ne 4 -or -not (Test-EnginePositiveInteger $binary.bytes) -or $binary.bytes -gt 1073741824 -or
            $binary.sha256 -isnot [string] -or $binary.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Writer DLL descriptor differs.' }
        if ($null -ne $Reference) {
            $expected=$Reference.binaries[$index]
            Assert-WriterObserverValues $binary @{path=$expected.path;sha256=$expected.sha256} @{bytes=$expected.bytes;machine=$expected.machine}
        }
    }
}

function Assert-WriterObserverReceipt($Proof, $Lock) {
    Assert-WriterObserverValues $Proof @{kind='native-office-engine-writer-server-observer-diagnostic';phase='Full';
        architecture='arm64';stage='complete';status='native-engine-writer-server-observer-diagnostic-built';
        sourceCommit=$Lock.sourceCommit;sourceTree=$Lock.sourceTree;sourceLockSha256=$Lock.sourceLockSha256} @{
        schemaVersion=1;sourceRun=$Lock.runId;runAttempt=1} @{passed=$true;fullEngineQualified=$false;acceptanceEligible=$false;guiVerified=$false}
    Assert-WriterObserverValues $Proof.sourcePin @{coreCommit=$Lock.coreCommit}
    Assert-WriterObserverValues $Proof.host @{} @{processMachine=0;nativeMachine=0xaa64} @{isWindows=$true}
    $hooks=$Proof.writerServerObserverSourceHooks
    Assert-WriterObserverValues $hooks @{kind='writer-server-observer-diagnostic-source';target='windows-arm64';
        coreCommit=$Lock.coreCommit;lockSha256=$Lock.sourceLockSha256} @{
        schemaVersion=1;ipcVersion=1;sinkAbiVersion=2;mappingBytes=131328;descriptorSchemaVersion=1} @{
        passed=$true;fullEngineQualified=$false;acceptanceEligible=$false;guiVerified=$false}
    Assert-WriterObserverLibraries $hooks.requiredRebuiltLibraries
    Assert-WriterObserverDescriptor $hooks.patch 'source.patch' $Lock.patchSha256
    Assert-WriterObserverDescriptor $hooks.wireSchema 'wire-schema.json' $Lock.wireSchemaSha256
    Assert-WriterObserverMarker $Proof.writerServerObserverRuntime $Lock $hooks
    if ($Proof.artifact -isnot [Collections.IDictionary] -or -not (Test-EnginePositiveInteger $Proof.artifact.size) -or
        $Proof.artifact.size -gt 8589934592 -or $Proof.artifact.sha256 -isnot [string] -or
        $Proof.artifact.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Writer inner ZIP identity differs.' }
}

function Read-WriterObserverEntry($Entry, [Threading.CancellationToken]$CancellationToken) {
    if ($Entry.Length -le 0 -or $Entry.Length -gt 8388608) { throw 'Writer diagnostic JSON exceeds bound.' }
    $memory=[IO.MemoryStream]::new();$stream=$Entry.Open()
    try {
        $buffer=[byte[]]::new(65536)
        while (($count=$stream.ReadAsync($buffer,0,$buffer.Length,$CancellationToken).WaitAsync($CancellationToken).GetAwaiter().GetResult()) -gt 0) {
            if ($memory.Length+$count -gt $Entry.Length) { throw 'Writer diagnostic JSON exceeds its member size.' }
            $memory.Write($buffer,0,$count)
        }
        $CancellationToken.ThrowIfCancellationRequested()
        if ($memory.Length -ne $Entry.Length) { throw 'Writer diagnostic JSON is incomplete.' }
        $bytes=$memory.ToArray()
        return @{sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant();
            json=([Text.UTF8Encoding]::new($false,$true).GetString($bytes)|ConvertFrom-Json -AsHashtable)}
    } finally {$stream.Dispose();$memory.Dispose()}
}

function Read-WriterObserverDll($Entry, $Expected, [Threading.CancellationToken]$CancellationToken) {
    if ($Entry.Length -ne $Expected.bytes) { throw 'Writer DLL size differs from its receipt.' }
    $stream=$Entry.Open();$prefix=[IO.MemoryStream]::new()
    $hash=[Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
    try {
        $buffer=[byte[]]::new(65536);[long]$total=0
        while (($count=$stream.ReadAsync($buffer,0,$buffer.Length,$CancellationToken).WaitAsync($CancellationToken).GetAwaiter().GetResult()) -gt 0) {
            $total+=$count
            if ($total -gt $Expected.bytes) { throw 'Writer DLL exceeds its receipt size.' }
            $hash.AppendData($buffer,0,$count)
            $retain=[Math]::Min($count,1048602-$prefix.Length)
            if ($retain -gt 0) {$prefix.Write($buffer,0,[int]$retain)}
        }
        $CancellationToken.ThrowIfCancellationRequested()
        $actual=[Convert]::ToHexString($hash.GetHashAndReset()).ToLowerInvariant()
        if ($total -ne $Expected.bytes -or $actual -cne $Expected.sha256) { throw 'Writer DLL bytes differ from its receipt.' }
        $data=$prefix.ToArray()
        if ($data.Length -lt 64 -or $data[0] -ne 77 -or $data[1] -ne 90) { throw 'Writer DLL DOS header differs.' }
        $offset=[BitConverter]::ToUInt32($data,60)
        if ($offset -lt 64 -or $offset -gt 1048576 -or $offset+26 -gt $data.Length -or
            [BitConverter]::ToUInt32($data,[int]$offset) -ne 17744 -or
            [BitConverter]::ToUInt16($data,[int]$offset+4) -ne 0xaa64 -or
            [BitConverter]::ToUInt16($data,[int]$offset+24) -ne 0x20b -or
            -not ([BitConverter]::ToUInt16($data,[int]$offset+22) -band 0x2000)) { throw 'Writer DLL is not native ARM64 PE32+.' }
    } finally {$hash.Dispose();$prefix.Dispose();$stream.Dispose()}
}

function Get-WriterObserverMembers($Engine) {
    if ($Engine.Entries.Count -le 0 -or $Engine.Entries.Count -gt 100000) { throw 'Writer inner ZIP member count exceeds bound.' }
    $members=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::OrdinalIgnoreCase)
    $prefixes=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::OrdinalIgnoreCase)
    [long]$total=0
    foreach ($entry in $Engine.Entries) {
        $name=$entry.FullName;$directory=$name.EndsWith('/')
        $canonical=if($directory){$name.Substring(0,$name.Length-1)}else{$name}
        [long]$attributes=[long]$entry.ExternalAttributes -band 0xffffffffL;$kind=($attributes -shr 16) -band 0xf000
        $parts=$canonical.Split('/')
        if (-not $canonical -or $name.Contains('\') -or $name -match '[\x00-\x1f\x7f:]' -or
            @($parts|Where-Object {$_ -in @('','.','..')}).Count -or $members.ContainsKey($canonical) -or
            ($attributes -band 0x400) -or ($directory -and ($kind -notin @(0,0x4000) -or $entry.Length -ne 0)) -or
            (-not $directory -and ($kind -notin @(0,0x8000) -or ($attributes -band 0x10) -or $entry.Length -gt 1073741824))) { throw 'Unsafe Writer inner ZIP member.' }
        $members.Add($canonical,$entry);$prefix=''
        for($index=0;$index -lt $parts.Count;$index++) {
            $prefix=if($index){$prefix+'/'+$parts[$index]}else{$parts[$index]}
            $isDirectory=$index -lt $parts.Count-1 -or $directory
            if ($prefixes.ContainsKey($prefix)) {
                $old=$prefixes[$prefix]
                if ($old.name -cne $prefix -or -not $old.directory -or -not $isDirectory) { throw 'Writer inner ZIP path alias/collision.' }
            } else {$prefixes.Add($prefix,@{name=$prefix;directory=$isDirectory})}
        }
        $total+=$entry.Length
        if ($total -gt 8589934592) { throw 'Writer inner ZIP uncompressed bytes exceed bound.' }
    }
    return ,$members
}

function Expand-WriterObserverArtifact([string]$Archive, [string]$Output, $Lock, [Threading.CancellationToken]$CancellationToken) {
    $engineName='OpenGeul-Office-engine-arm64-writer-server-observer.zip';$receiptName='writer-server-observer-source-build-receipt.json'
    $CancellationToken.ThrowIfCancellationRequested();$zip=[IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        if ($zip.Entries.Count -ne 2) { throw 'Exactly two Writer diagnostic outer members required.' }
        $members=@{}
        foreach ($entry in $zip.Entries) {
            $name=$entry.FullName;[long]$attributes=[long]$entry.ExternalAttributes -band 0xffffffffL;$kind=($attributes -shr 16) -band 0xf000
            if (($name -cne $engineName -and $name -cne $receiptName) -or $members.ContainsKey($name) -or $kind -notin @(0,0x8000) -or
                ($attributes -band 0x410) -or $entry.Length -le 0 -or ($name -ceq $engineName -and $entry.Length -gt 8589934592) -or
                ($name -ceq $receiptName -and $entry.Length -gt 8388608)) { throw 'Unsafe Writer outer ZIP member.' }
            $members[$name]=$entry
        }
        $receipt=Read-WriterObserverEntry $members[$receiptName] $CancellationToken
        $proof=$receipt.json;Assert-WriterObserverReceipt $proof $Lock
        if ($members[$engineName].Length -ne $proof.artifact.size) { throw 'Writer inner ZIP receipt size differs.' }
        foreach ($name in @($receiptName,$engineName)) {
            $expected=if($name -ceq $receiptName){$receipt.sha256}else{$proof.artifact.sha256}
            $stream=$members[$name].Open()
            try {Copy-EngineBoundedStream $stream (Join-Path $Output $name) $members[$name].Length $expected $CancellationToken}
            finally {$stream.Dispose()}
        }
        $engine=[IO.Compression.ZipFile]::OpenRead((Join-Path $Output $engineName))
        try {
            $inner=Get-WriterObserverMembers $engine
            $markers=@('writer-server-observer-diagnostic.json','program/opengeul-writer-server-observer-diagnostic.json');$first=$null
            foreach ($path in $markers) {
                if (-not $inner.ContainsKey($path) -or $inner[$path].FullName -cne $path) { throw 'Both canonical Writer markers are required.' }
                $marker=Read-WriterObserverEntry $inner[$path] $CancellationToken
                Assert-WriterObserverMarker $marker.json $Lock $proof.writerServerObserverSourceHooks $proof.writerServerObserverRuntime
                if ($first -and $first -cne $marker.sha256) { throw 'Writer paired marker raw bytes differ.' }
                $first=$marker.sha256
            }
            foreach ($binary in $proof.writerServerObserverRuntime.binaries) {
                if (-not $inner.ContainsKey($binary.path) -or $inner[$binary.path].FullName -cne $binary.path) { throw 'Both canonical Writer DLLs are required.' }
                Read-WriterObserverDll $inner[$binary.path] $binary $CancellationToken
            }
            $CancellationToken.ThrowIfCancellationRequested()
        } finally {$engine.Dispose()}
        return @{engineSize=$proof.artifact.size;engineSha256=$proof.artifact.sha256;receiptSha256=$receipt.sha256}
    } finally {$zip.Dispose()}
}

function Invoke-WriterServerObserverFetch([string]$DiagnosticLockPath, [string]$Output, $ApiClient=$null, $DownloadClient=$null,
                                          [ValidateRange(1,1200)][int]$TimeoutSeconds=1200) {
    Assert-EngineUnlinkedPath $DiagnosticLockPath;$file=Get-Item -LiteralPath $DiagnosticLockPath
    if ($file.PSIsContainer -or $file.Length -le 0 -or $file.Length -gt 65536) { throw 'Writer diagnostic input lock exceeds bound.' }
    $lock=Get-Content -LiteralPath $DiagnosticLockPath -Raw|ConvertFrom-Json -AsHashtable
    $keys=@('schemaVersion','kind','architecture','repository','repositoryId','sourceCommit','sourceTree','runId','runAttempt',
        'artifactId','artifactSha256','artifactSize','sourceLockSha256','coreCommit','patchSha256','wireSchemaSha256')
    Assert-WriterObserverValues $lock @{kind='writer-server-observer-diagnostic-input';architecture='arm64';repository='ATLKR/OpenGeul';
        coreCommit='9dea406ab7695df6325b11b0e19fdca8db4b7276';
        sourceLockSha256='5717878d19d95c56383accb8b451271a741539f9752470bfb41cb3de4649beed';
        patchSha256='7cdab1afebc8c83ea2a50e8b36bff98fda1b5e7de101607e2e41774c41fb4825';
        wireSchemaSha256='bdf17ce841c6f3a7af900bf27b57bc2a1b871c19962dffe15c9a4349a19ec084'} @{schemaVersion=1;repositoryId=1405493151;runAttempt=1}
    if ($lock.Count -ne $keys.Count -or @($lock.Keys|Where-Object {$_ -cnotin $keys}).Count) { throw 'Exactly sixteen Writer external lock fields required.' }
    foreach ($key in @('sourceCommit','sourceTree')) {
        if ($lock[$key] -isnot [string] -or $lock[$key] -cnotmatch '^[0-9a-f]{40}$' -or $lock[$key] -ceq ('0'*40)) { throw 'Writer external source pin differs.' }
    }
    foreach ($key in @('artifactSha256','sourceLockSha256','patchSha256','wireSchemaSha256')) {
        if ($lock[$key] -isnot [string] -or $lock[$key] -cnotmatch '^[0-9a-f]{64}$') { throw 'Writer external digest pin differs.' }
    }
    foreach ($key in @('runId','artifactId','artifactSize')) {if (-not (Test-EnginePositiveInteger $lock[$key])) { throw 'Writer external numeric pin differs.' }}
    if ($lock.artifactSize -gt 8599371776) { throw 'Writer outer ZIP exceeds bound.' }
    $token=if($env:GH_TOKEN){$env:GH_TOKEN}else{$env:GITHUB_TOKEN}
    if ([string]::IsNullOrWhiteSpace($token)) { throw 'A workflow artifact read credential is required.' }
    Assert-EngineUnlinkedPath $Output
    if (Test-Path -LiteralPath $Output) { throw 'Preserve existing Writer fetch evidence.' }
    $outputPath=[IO.Path]::GetFullPath($Output);New-Item -ItemType Directory -Path $outputPath -ErrorAction Stop|Out-Null
    $ownApi=$null -eq $ApiClient;$ownDownload=$null -eq $DownloadClient
    $started=[DateTime]::UtcNow;$clock=[Diagnostics.Stopwatch]::StartNew()
    $cancellation=[Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($TimeoutSeconds));$failure=$null
    $audit=[ordered]@{schemaVersion=1;kind='authenticated-writer-server-observer-download';passed=$false;stage='github-metadata';
        repository=$lock.repository;artifactId=$lock.artifactId;runId=$lock.runId;runAttempt=$lock.runAttempt;sourceCommit=$lock.sourceCommit;
        sourceTree=$lock.sourceTree;sourceLockSha256=$lock.sourceLockSha256;coreCommit=$lock.coreCommit;patchSha256=$lock.patchSha256;
        wireSchemaSha256=$lock.wireSchemaSha256;artifactSha256=$lock.artifactSha256;artifactSize=$lock.artifactSize;
        startedUtc=$started.ToString('o');timeoutSeconds=$TimeoutSeconds;deadlineUtc=$started.AddSeconds($TimeoutSeconds).ToString('o');deadlineExceeded=$false}
    try {
        if ($ownApi) {$ApiClient=New-EngineFetchClient};if ($ownDownload) {$DownloadClient=New-EngineFetchClient}
        $api='https://api.github.com/repos/ATLKR/OpenGeul/actions'
        $artifact=Read-EngineApiJson $ApiClient ($api+'/artifacts/'+$lock.artifactId) $token $cancellation.Token
        $run=Read-EngineApiJson $ApiClient ($api+'/runs/'+$lock.runId) $token $cancellation.Token
        Assert-WriterObserverValues $run @{head_sha=$lock.sourceCommit;status='completed';conclusion='success';event='push';
            head_branch='work/opengeul-office-native-writer-observer-9dea';path='.github/workflows/office-native-engine.yml'} @{id=$lock.runId;run_attempt=1}
        Assert-WriterObserverValues $run.actor @{login='ATLKR';type='User'} @{id=65988341}
        foreach($repository in @($run.repository,$run.head_repository)) {
            Assert-WriterObserverValues $repository @{full_name=$lock.repository} @{id=$lock.repositoryId} @{private=$false}
        }
        Assert-WriterObserverValues $artifact @{name=('opengeul-native-arm64-writer-server-observer-'+$lock.runId+'-1');
            digest=('sha256:'+$lock.artifactSha256)} @{id=$lock.artifactId;size_in_bytes=$lock.artifactSize} @{expired=$false}
        Assert-WriterObserverValues $artifact.workflow_run @{head_sha=$lock.sourceCommit;head_branch='work/opengeul-office-native-writer-observer-9dea'} @{
            id=$lock.runId;repository_id=$lock.repositoryId;head_repository_id=$lock.repositoryId}
        $jobs=Read-EngineApiJson $ApiClient ($api+'/runs/'+$lock.runId+'/attempts/1/jobs?per_page=100') $token $cancellation.Token
        Assert-WriterObserverValues $jobs @{} @{total_count=1}
        if ($jobs.jobs -isnot [array] -or $jobs.jobs.Count -ne 1 -or -not (Test-EnginePositiveInteger $jobs.jobs[0].id)) { throw 'Exactly one Writer producer job required.' }
        Assert-WriterObserverValues $jobs.jobs[0] @{name='native-firebird-and-office';head_sha=$lock.sourceCommit;status='completed';conclusion='success'} @{run_id=$lock.runId}
        $metadata=@{schemaVersion=1;repository=$lock.repository;artifact=@{id=$artifact.id;name=$artifact.name;digest=$artifact.digest;size_in_bytes=$artifact.size_in_bytes};
            run=@{id=$run.id;run_attempt=$run.run_attempt;head_sha=$run.head_sha;event=$run.event;head_branch=$run.head_branch;path=$run.path};
            job=@{id=$jobs.jobs[0].id;name=$jobs.jobs[0].name;run_id=$lock.runId;head_sha=$lock.sourceCommit;status='completed';conclusion='success'}}
        Write-EngineFetchJson (Join-Path $outputPath 'artifact-server-metadata.json') $metadata
        $audit.stage='authenticated-outer-zip';$archive=Join-Path $outputPath 'github-artifact.zip'
        Save-EngineArtifact $ApiClient $DownloadClient ($api+'/artifacts/'+$lock.artifactId+'/zip') $token $archive $lock.artifactSize $lock.artifactSha256 $cancellation.Token
        $audit.stage='extract-exact-inputs';$inputs=Expand-WriterObserverArtifact $archive $outputPath $lock $cancellation.Token
        foreach ($key in $inputs.Keys) {$audit[$key]=$inputs[$key]}
        $cancellation.Token.ThrowIfCancellationRequested();$audit.passed=$true;$audit.stage='complete'
    } catch {
        $audit.deadlineExceeded=$cancellation.IsCancellationRequested
        $failure=[InvalidOperationException]::new('Writer observer fetch failed at '+$audit.stage+'; inspect the sanitized download receipt.')
    } finally {
        $audit.finishedUtc=[DateTime]::UtcNow.ToString('o');$audit.elapsedSeconds=$clock.Elapsed.TotalSeconds
        try {
            if ($audit.passed) {$cancellation.Token.ThrowIfCancellationRequested()}
            Write-EngineFetchJson (Join-Path $outputPath 'writer-server-observer-download.json') $audit
            if ($audit.passed) {$cancellation.Token.ThrowIfCancellationRequested()}
        } catch {
            $audit.passed=$false;$audit.deadlineExceeded=$cancellation.IsCancellationRequested
            if ($null -eq $failure) {$failure=[InvalidOperationException]::new('Writer observer fetch failed at finalization; inspect the sanitized download receipt.')}
            try {Write-EngineFetchJson (Join-Path $outputPath 'writer-server-observer-download.json') $audit} catch {}
        }
        foreach ($resource in @($(if($ownApi){$ApiClient}),$(if($ownDownload){$DownloadClient}),$cancellation)) {
            if ($null -ne $resource) {
                try {$resource.Dispose()} catch {if ($null -eq $failure) {$failure=[InvalidOperationException]::new('Writer observer fetch failed at finalization; inspect the sanitized download receipt.')}}
            }
        }
        $token=$null
    }
    if ($null -ne $failure) {throw $failure}
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-WriterServerObserverFetch -DiagnosticLockPath $DiagnosticLockPath -Output $Output -TimeoutSeconds $TimeoutSeconds
    Write-Host 'Locked Writer server observer diagnostic inputs authenticated and retained.'
}
