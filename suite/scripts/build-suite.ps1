param(
    [string]$WorkDirectory = '.work/office-suite',
    [string]$OutputDirectory = '',
    [ValidateSet('x64', 'arm64')]
    [string]$Architecture = 'x64',
    [string]$EngineArchive = '',
    [string]$EngineReceipt = ''
)
$ErrorActionPreference = 'Stop'
$Architecture = $Architecture.ToLowerInvariant()
$suiteRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot = Split-Path $suiteRoot -Parent
Push-Location $repoRoot
try {
    if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
        $lockName = if ($Architecture -eq 'arm64') { 'runtime.arm64.lock.json' } else { 'runtime.lock.json' }
        $lock = Get-Content (Join-Path $suiteRoot "config/$lockName") -Raw | ConvertFrom-Json
        $OutputDirectory = "dist/OpenGeul-Office-$($lock.version)-windows-$Architecture"
    }
    $workPath = [IO.Path]::GetFullPath($WorkDirectory)
    $outputPath = [IO.Path]::GetFullPath($OutputDirectory)
    if (Test-Path $outputPath) { throw 'Suite output already exists; preserve or remove it explicitly.' }
    $shellPath = Join-Path $workPath 'shell'
    if (Test-Path $shellPath) { throw 'Published shell directory already exists.' }
    dotnet publish suite/shell/OpenGeul.Office.csproj -c Release -r "win-$Architecture" --self-contained true -o $shellPath
    if ($LASTEXITCODE -ne 0) { throw 'Windows Suite shell publish failed.' }
    $prepareArguments = @('suite/prepare.py', '--architecture', $Architecture, '--work', $workPath,
                          '--shell', $shellPath, '--output', $outputPath)
    if (-not [string]::IsNullOrWhiteSpace($EngineArchive)) { $prepareArguments += @('--engine-archive', $EngineArchive) }
    if (-not [string]::IsNullOrWhiteSpace($EngineReceipt)) { $prepareArguments += @('--engine-receipt', $EngineReceipt) }
    python @prepareArguments
    if ($LASTEXITCODE -ne 0) { throw 'Suite input/extraction/branding/inventory verification failed.' }
    $zipPath = $outputPath + '.zip'
    if (Test-Path $zipPath) { throw 'Suite ZIP output already exists.' }
    python -c 'import pathlib,sys,zipfile; root=pathlib.Path(sys.argv[1]); out=pathlib.Path(sys.argv[2]); z=zipfile.ZipFile(out,"x",zipfile.ZIP_DEFLATED,compresslevel=6); [(z.write(p,p.relative_to(root).as_posix())) for p in sorted(root.rglob("*")) if p.is_file()]; z.close()' $outputPath $zipPath
    if ($LASTEXITCODE -ne 0) { throw 'Suite ZIP creation failed.' }
    Write-Host ('OpenGeul Office development package: ' + $zipPath)
} finally { Pop-Location }
