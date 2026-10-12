$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$inventoryRoot = Join-Path $pwd 'python-inventory'
if (Test-Path $inventoryRoot) { throw 'Existing inventory must be preserved.' }
New-Item -ItemType Directory $inventoryRoot | Out-Null
$inventoryCommands = @()
$inventoryToolCache = Join-Path $env:RUNNER_TOOL_CACHE 'Python'
function Test-InventorySystemPath([string]$inventoryPath) {
    $inventoryFullPath = [IO.Path]::GetFullPath($inventoryPath)
    return $inventoryFullPath.StartsWith($inventoryToolCache + '\',[StringComparison]::OrdinalIgnoreCase) -or $inventoryFullPath -match '^C:\\(?:Program Files(?: \(x86\))?\\Python[^\\]*|Python[^\\]*)\\'
}
function Test-InventoryPe([string]$inventoryPath) {
    $inventoryStream = [IO.File]::OpenRead($inventoryPath)
    try {
        $inventoryReader = [IO.BinaryReader]::new($inventoryStream)
        if ($inventoryStream.Length -lt 64 -or $inventoryReader.ReadUInt16() -ne 0x5A4D) { throw 'Interpreter is not PE.' }
        $inventoryStream.Position = 60
        $inventoryPeOffset = $inventoryReader.ReadUInt32()
        if ($inventoryPeOffset -lt 64 -or $inventoryPeOffset -gt 1MB -or $inventoryPeOffset + 6 -gt $inventoryStream.Length) { throw 'Invalid PE offset.' }
        $inventoryStream.Position = $inventoryPeOffset
        if ($inventoryReader.ReadUInt32() -ne 0x00004550 -or $inventoryReader.ReadUInt16() -notin @(0x014C,0x8664,0xAA64)) { throw 'Unsupported interpreter PE machine.' }
    } finally { $inventoryStream.Dispose() }
}
$inventoryCandidates = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($inventoryName in @('python','python3','py')) {
    $inventoryCommand = Get-Command $inventoryName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($inventoryCommand) {
        $inventoryCommands += [ordered]@{ name = $inventoryName; path = $inventoryCommand.Source }
        if ($inventoryName -ne 'py' -and $inventoryCommand.Source -notlike '*\WindowsApps\*' -and (Test-InventorySystemPath $inventoryCommand.Source)) {
            [void]$inventoryCandidates.Add($inventoryCommand.Source)
        }
    }
}
$inventoryVersions = @()
if (Test-Path $inventoryToolCache -PathType Container) {
    $inventoryDirectories = @(Get-ChildItem $inventoryToolCache -Directory | Sort-Object Name)
    if ($inventoryDirectories.Count -gt 24) { throw 'Too many Python versions.' }
    foreach ($inventoryVersion in $inventoryDirectories) {
        foreach ($inventoryArchitecture in @('x64','arm64','x86')) {
            $inventoryExecutable = Join-Path $inventoryVersion.FullName "$inventoryArchitecture/python.exe"
            if (Test-Path $inventoryExecutable -PathType Leaf) {
                $inventoryVersions += [ordered]@{ version = $inventoryVersion.Name; architecture = $inventoryArchitecture; executable = $inventoryExecutable }
                [void]$inventoryCandidates.Add($inventoryExecutable)
            }
        }
    }
}
if ($inventoryCandidates.Count -gt 12) { throw 'Too many Python candidates.' }
$inventoryMetadata = [ordered]@{
    schemaVersion = 1; scope = 'preinstalled-Python inventory only'; sourceQualified = $false
    repository = $env:GITHUB_REPOSITORY; head = $env:GITHUB_SHA; runId = $env:GITHUB_RUN_ID; attempt = $env:GITHUB_RUN_ATTEMPT
    runnerOs = $env:RUNNER_OS; runnerArchitecture = $env:RUNNER_ARCH
    pathCommands = $inventoryCommands; toolCachePython = $inventoryVersions
    candidateCount = $inventoryCandidates.Count; downloads = 0; installs = 0; cacheRestores = 0; productCompiles = 0
}
$inventoryMetadata | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $inventoryRoot 'inventory.json')
$inventoryIndex = 0
foreach ($inventoryCandidate in ($inventoryCandidates | Sort-Object)) {
    $inventoryItem = Get-Item $inventoryCandidate
    $inventoryAllowed = Test-InventorySystemPath $inventoryCandidate
    if (-not $inventoryAllowed -or ($inventoryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $inventoryItem.Length -gt 32MB) { throw 'Unsafe interpreter candidate.' }
    $inventoryAncestor = $inventoryItem.Directory
    while ($inventoryAncestor) {
        if (($inventoryAncestor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Interpreter ancestor is a reparse point.' }
        $inventoryAncestor = $inventoryAncestor.Parent
    }
    Test-InventoryPe $inventoryCandidate
    $inventoryIndex++
    $inventoryProcess = [Diagnostics.Process]::new()
    $inventoryProcess.StartInfo.FileName = $inventoryCandidate
    $inventoryProcess.StartInfo.ArgumentList.Add('-I')
    $inventoryProcess.StartInfo.ArgumentList.Add((Join-Path $pwd 'ci/diagnostics/python_inventory.py'))
    $inventoryProcess.StartInfo.UseShellExecute = $false
    $inventoryProcess.StartInfo.RedirectStandardOutput = $true
    $inventoryProcess.StartInfo.RedirectStandardError = $true
    [void]$inventoryProcess.Start()
    $inventoryOutput = $inventoryProcess.StandardOutput.ReadToEndAsync()
    $inventoryError = $inventoryProcess.StandardError.ReadToEndAsync()
    # The fixed, isolated stdlib reporter emits one small JSON object. The 16 KiB
    # check below bounds retained artifact content after this owned process exits.
    if (-not $inventoryProcess.WaitForExit(20000)) {
        $inventoryProcess.Kill($true)
        $inventoryProcess.WaitForExit()
        throw 'Interpreter inventory timed out.'
    }
    $inventoryRaw = $inventoryOutput.GetAwaiter().GetResult()
    $inventoryStderr = $inventoryError.GetAwaiter().GetResult()
    if ($inventoryRaw.Length -gt 16384 -or $inventoryStderr.Length -gt 16384) { throw 'Interpreter inventory output exceeds its bound.' }
    if ($inventoryProcess.ExitCode -ne 0) { throw 'Interpreter inventory failed; raw stderr is withheld.' }
    $inventoryReport = $inventoryRaw | ConvertFrom-Json
    $inventoryReport | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $inventoryRoot "interpreter-$inventoryIndex.json")
    $inventoryProcess.Dispose()
}
$inventoryTotal = (Get-ChildItem $inventoryRoot -File | Measure-Object Length -Sum).Sum
if ($inventoryTotal -gt 256KB) { throw 'Inventory artifact exceeds its bound.' }
Write-Host "Preinstalled Python inventory complete: $($inventoryCandidates.Count) candidate(s)."
