# Windows 네이티브 x64 또는 ARM64, PowerShell 7, Python 3.11+, Node 24, Rustup and Windows SDK.
[CmdletBinding()]
param(
    [switch]$Store, [string]$IdentityFile, [string]$WasmDirectory,
    [ValidateSet('All','Editor','Cli','Package')][string]$Phase = 'All',
    [ValidateSet('All','Prepare','NativeTests','Release')][string]$EditorStage = 'All',
    [string]$EditorComponent, [string]$CliComponent,
    [ValidateSet('x64','arm64')][string]$Architecture = 'x64'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$env:PYTHONUTF8 = '1'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not $IsWindows) { throw 'Native builds require Windows.' }
function Set-EditorCargoParallelism {
    param([ValidateSet('Native','Release')][string]$Workload = 'Native')
    # 새 컴파일을 시작할 때만 재측정한다. 실행 중 Cargo의 jobserver는 변경하지 않는다.
    $processorCount = [Environment]::ProcessorCount
    $totalMemory = 0; $availableMemory = 0; $cpuBusy = -1
    try {
        # 언어 독립 raw counter의 새 1초 구간만 사용한다. 지난 컴파일의 부하 값은 재사용하지 않는다.
        $before = @(Get-CimInstance Win32_PerfRawData_PerfOS_Processor -Filter "Name='_Total'" -OperationTimeoutSec 5 -ErrorAction Stop)
        Start-Sleep -Milliseconds 1000
        $after = @(Get-CimInstance Win32_PerfRawData_PerfOS_Processor -Filter "Name='_Total'" -OperationTimeoutSec 5 -ErrorAction Stop)
        [long]$idleBefore = 0; [long]$idleAfter = 0; [long]$tickBefore = 0; [long]$tickAfter = 0
        if ($before.Count -ne 1 -or $after.Count -ne 1 -or
            -not [long]::TryParse([string]$before[0].PercentProcessorTime, [ref]$idleBefore) -or
            -not [long]::TryParse([string]$after[0].PercentProcessorTime, [ref]$idleAfter) -or
            -not [long]::TryParse([string]$before[0].Timestamp_Sys100NS, [ref]$tickBefore) -or
            -not [long]::TryParse([string]$after[0].Timestamp_Sys100NS, [ref]$tickAfter) -or
            $idleBefore -lt 0 -or $tickBefore -lt 0 -or $tickAfter -le $tickBefore -or
            $idleAfter -lt $idleBefore -or ($idleAfter-$idleBefore) -gt ($tickAfter-$tickBefore)) { throw 'Invalid CPU interval.' }
        $cpuBusy = [int][Math]::Ceiling(100 * (1 - [decimal]($idleAfter-$idleBefore) / ($tickAfter-$tickBefore)))
        $systems = @(Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 5 -ErrorAction Stop)
        $processors = @(Get-CimInstance Win32_Processor -OperationTimeoutSec 5 -ErrorAction Stop)
        [long]$totalKiB = 0; [long]$availableKiB = 0
        if ($systems.Count -ne 1 -or
            -not [long]::TryParse([string]$systems[0].TotalVisibleMemorySize, [ref]$totalKiB) -or
            -not [long]::TryParse([string]$systems[0].FreePhysicalMemory, [ref]$availableKiB) -or
            $totalKiB -lt 1 -or $availableKiB -lt 0 -or $availableKiB -gt $totalKiB) { throw 'Invalid memory observation.' }
        $logicalCount = 0
        foreach ($processor in $processors) {
            [int]$cores = 0
            if (-not [int]::TryParse([string]$processor.NumberOfLogicalProcessors, [ref]$cores) -or
                $cores -lt 1) { throw 'Invalid CPU observation.' }
            $logicalCount += $cores
        }
        if ($logicalCount -lt 1) { throw 'Missing CPU observation.' }
        $processorCount = $logicalCount
        $totalMemory = $totalKiB * 1024; $availableMemory = $availableKiB * 1024
        $decision = python (Join-Path $root 'ci/build_progress.py') jobs --cpu $processorCount --total-memory $totalMemory --available-memory $availableMemory --cpu-busy $cpuBusy --architecture $Architecture --workload ($Workload.ToLowerInvariant()) --json | ConvertFrom-Json
        $x64Release = $Architecture -eq 'x64' -and $Workload -eq 'Release'
        if (($decision.jobs -isnot [int] -and $decision.jobs -isnot [long]) -or
            $decision.jobs -notin @(1,2,4,8,12) -or
            ($x64Release -and $decision.jobs -gt [Math]::Min($processorCount*3,12)) -or
            (-not $x64Release -and $decision.jobs -gt [Math]::Min($processorCount*2,8)) -or
            ($decision.jobs -eq 12 -and (-not $x64Release -or $cpuBusy -lt 0 -or $cpuBusy -gt 25 -or
                $totalMemory -lt 14GB -or $availableMemory -lt 11GB)) -or
            $decision.reason -notin @('singleCore','cpuUnavailable','cpuBusy','cpuLimited','memoryLimited','headroom')) { throw 'Invalid resource decision.' }
        $buildJobs = $decision.jobs; $reason = $decision.reason
    } catch {
        $buildJobs = [Math]::Min([Environment]::ProcessorCount, 2); $reason = 'observationUnavailable'
    }
    $env:CARGO_BUILD_JOBS = [string]$buildJobs
    Write-Host "빌드 자원 재측정: CPU=$processorCount; CPU busy=$cpuBusy%; RAM bytes=$totalMemory; 여유 RAM bytes=$availableMemory; cargo jobs=$buildJobs; reason=$reason. workload=$Workload; architecture=$Architecture."
}
if ($EditorStage -ne 'All' -and $Phase -ne 'Editor') { throw 'Editor stages require the Editor phase.' }
$prepareEditor = $Phase -ne 'Editor' -or $EditorStage -in @('All','Prepare')
$editorTests = $Phase -in @('All','Editor') -and $EditorStage -in @('All','NativeTests')
$editorRelease = $Phase -in @('All','Editor') -and $EditorStage -in @('All','Release')
if ($Phase -ne 'Package' -and -not $WasmDirectory) { throw 'Compilation requires source-bound rebuilt WASM.' }
if ($Phase -eq 'Package' -and (-not $EditorComponent -or -not $CliComponent)) { throw 'Packaging requires both same-run components.' }
$tools = if ($Phase -eq 'Package') { @('python') } else { @('python','git','node','rustup','corepack') }
foreach ($tool in $tools) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing prerequisite: $tool" }
}
$source = Join-Path $root '.work/hop'
$stage = Join-Path $root '.work/payload'
$output = Join-Path $root 'dist'
if ($Phase -eq 'Editor' -and $EditorStage -in @('NativeTests','Release')) {
    if (-not (Test-Path $stage -PathType Container) -or (Test-Path $output)) { throw 'Editor stage requires its existing payload and no package output.' }
    python ci/build_progress.py verify --stage $EditorStage --architecture $Architecture
} elseif ((Test-Path $stage) -or (Test-Path $output)) { throw 'Preserve previous outputs before rebuilding; .work/payload or dist already exists.' }
$product = Get-Content 'config/product.json' -Raw | ConvertFrom-Json
$lock = Get-Content 'config/upstream.lock.json' -Raw | ConvertFrom-Json
$target = python -c "import sys;sys.path.insert(0,'scripts');from windows_arch import target_triple;print(target_triple(sys.argv[1]))" $Architecture
New-Item -ItemType Directory -Force (Join-Path $root '.work') | Out-Null
$hostArchitectureOutput = if ($Phase -eq 'Editor' -and $EditorStage -ne 'All') {
    Join-Path $root ('.work/host-architecture-{0}-{1}.json' -f $Architecture,$EditorStage)
} else {
    Join-Path $root '.work/host-architecture.json'
}
python e2e/native_architecture.py host --architecture $Architecture --output $hostArchitectureOutput
if ($Store -and -not $IdentityFile) { throw 'Store build requires real Partner Center identity.' }
if ($Phase -eq 'Package') {
    $source = Join-Path $root '.work/package-source'
    # The join validates both complete inventories, source contracts and architecture-matched PE
    # bytes before creating any payload or restoring the release source ledger.
    python scripts/windows_components.py combine --editor $EditorComponent --cli $CliComponent --payload $stage --source $source --architecture $Architecture
} else {
if ($prepareEditor) {
if ($Phase -eq 'All') { python -m unittest discover -s tests -v }
if ($Phase -in @('All','Editor')) {
    node --experimental-strip-types --test tests/save-format.test.mjs tests/composition-final.test.mjs
}
New-Item -ItemType Directory -Force $stage | Out-Null
if ($Phase -in @('All','Editor')) {
$manifestArgs = @('scripts/buildkit.py','manifest','--out',(Join-Path $stage 'AppxManifest.xml'),'--architecture',$Architecture)
if ($IdentityFile) { $manifestArgs += @('--identity',(Resolve-Path $IdentityFile).Path) }
if ($Store) { $manifestArgs += '--store' }
& python @manifestArgs
}
python scripts/prepare_upstream.py --fetch-only
rustup toolchain install "$($lock.rust)-$target" --profile minimal --target $target
}
$env:RUSTUP_TOOLCHAIN = "$($lock.rust)-$target"
$env:CARGO_TARGET_DIR = Join-Path $root '.work/target'
$editorTarget = $env:CARGO_TARGET_DIR
$cliTarget = Join-Path $root '.work/target-cli'
$env:CARGO_PROFILE_DEV_DEBUG = '0'
$env:CARGO_PROFILE_TEST_DEBUG = '0'
if ($prepareEditor) {
Set-EditorCargoParallelism
rustc --target $target --edition=2021 --test overlay/font_policy.rs -o .work/font-policy-tests.exe
& .work/font-policy-tests.exe
corepack enable
Push-Location $source
try {
    pnpm install --frozen-lockfile
    pnpm run test:upstream
    pnpm run test:studio
} finally { Pop-Location }
# Observe the original unsupported HWPX save failing before changing production code.
python scripts/prepare_hwpx.py $source --red-probe
python scripts/font_test_contract.py $source
python scripts/prepare_upstream.py --patch-only
python scripts/prepare_hwpx.py $source
python scripts/patch_composition.py $source
node --experimental-strip-types --loader ./tests/hop/loader.mjs --test tests/hop/*.test.mjs
python scripts/patch_namespaces.py (Join-Path $source 'third_party/rhwp')
python scripts/wasm_artifacts.py install $WasmDirectory $source
$tableFixtures = Join-Path $root '.work/table-fixtures'
$tableVendor = Join-Path $source 'apps/studio-host/vendor/rhwp-core'
node e2e/table_height.mjs generate $tableVendor $tableFixtures
python e2e/table_height_fixtures.py $tableFixtures
node e2e/table_height.mjs verify $tableVendor $tableFixtures
python scripts/prepare_native_tests.py (Join-Path $source 'third_party/rhwp')
$env:OPENGEUL_TABLE_FIXTURES = $tableFixtures
} else {
    $tableFixtures = Join-Path $root '.work/table-fixtures'
    $env:OPENGEUL_TABLE_FIXTURES = $tableFixtures
}
Push-Location $source
try {
    if ($Phase -in @('All','Editor') -and $EditorStage -in @('All','Prepare')) {
    pnpm run test:studio
    pnpm run build:studio
    python ../../scripts/buildkit.py frontend apps/studio-host/dist
    }
    if ($Phase -eq 'Editor' -and $EditorStage -eq 'Prepare') { exit 0 }
    if ($editorTests) {
    # Reuse the native test graph for the table, PDF and stored line-origin regressions.
    # Keep it separate from the GUI's different feature graph.
    Push-Location 'third_party/rhwp'
    try {
        $env:CARGO_TARGET_DIR = $cliTarget
        Set-EditorCargoParallelism
        cargo test --locked --target $target --test opengeul_table_height
        Set-EditorCargoParallelism
        cargo test --locked --target $target --package rhwp --test opengeul_pdf_policy --features native-skia
        Set-EditorCargoParallelism
        cargo test --locked --target $target --test opengeul_stored_lineseg_origin --features native-skia
    } finally {
        $env:CARGO_TARGET_DIR = $editorTarget
        Pop-Location
    }
    Push-Location 'apps/desktop/src-tauri'
    try {
        Set-EditorCargoParallelism
        cargo test --locked --target $target
        Set-EditorCargoParallelism
        cargo test --locked --target $target --package opengeul-native-open
        Set-EditorCargoParallelism
        cargo run --locked --target $target --example opengeul-fixtures -- (Join-Path $root '.work/e2e-fixtures')
        Set-EditorCargoParallelism
        cargo build --locked --target $target --example opengeul-structured-fixtures
        $structuredGenerator = Join-Path $editorTarget "$target/debug/examples/opengeul-structured-fixtures.exe"
        $structuredSha = (Get-FileHash $structuredGenerator -Algorithm SHA256).Hash.ToLowerInvariant()
        python -m pip install Pillow==12.3.0
        python (Join-Path $root 'e2e/structured_cli_mcp/stage_structured.py') generate --generator-exe $structuredGenerator --expected-generator-sha256 $structuredSha --prepared-source $source --architecture $Architecture --out (Join-Path $root '.work/structured-fixtures')
    } finally { Pop-Location }
    }
    if ($editorRelease) {
        Set-EditorCargoParallelism -Workload Release
        pnpm tauri build --no-bundle --target $target
    }
    if ($Phase -in @('All','Cli')) {
    Push-Location 'third_party/rhwp'
    try {
        # cdylib/rlib outputs must not collide with the editor's different feature graph.
        $env:CARGO_TARGET_DIR = $cliTarget
        Set-EditorCargoParallelism -Workload Release
        cargo build --release --locked --target $target --package rhwp --bin rhwp --features native-skia
    } finally {
        $env:CARGO_TARGET_DIR = $editorTarget
        Pop-Location
    }
    }
} finally { Pop-Location }
if ($Phase -eq 'Editor' -and $EditorStage -eq 'NativeTests') { exit 0 }
$release = Join-Path $env:CARGO_TARGET_DIR "$target/release"
$cliRelease = Join-Path $cliTarget "$target/release"
if ($editorRelease) {
if (-not (Test-Path (Join-Path $release 'hop-desktop.exe'))) { throw 'Missing built editor runtime.' }
Copy-Item (Join-Path $release 'hop-desktop.exe') (Join-Path $stage 'OpenGeul.exe')
Get-ChildItem $release -Filter '*.dll' -File | ForEach-Object { Copy-Item $_.FullName $stage }
$assets = Join-Path $stage 'Assets'
python scripts/buildkit.py assets $assets
Remove-Item (Join-Path $assets 'app.ico'),(Join-Path $assets 'app.png')
$notices = Join-Path $stage 'Notices'
New-Item -ItemType Directory -Force $notices | Out-Null
Copy-Item 'LICENSE' (Join-Path $notices 'OpenGeul-LICENSE.txt')
Copy-Item (Join-Path $source 'LICENSE') (Join-Path $notices 'HOP-LICENSE.txt')
Copy-Item (Join-Path $source 'third_party/rhwp/LICENSE') (Join-Path $notices 'rhwp-LICENSE.txt')
Copy-Item 'THIRD_PARTY_NOTICES.md','docs/FONTS.md','docs/LICENSE_POLICY.md','config/upstream.lock.json' $notices
python scripts/collect_notices.py --source $source --out (Join-Path $notices 'Dependencies')
}
if ($Phase -in @('All','Cli')) {
if (-not (Test-Path (Join-Path $cliRelease 'rhwp.exe'))) { throw 'Missing built CLI runtime.' }
New-Item -ItemType Directory -Force (Join-Path $stage 'Tools') | Out-Null
Copy-Item (Join-Path $cliRelease 'rhwp.exe') (Join-Path $stage 'Tools/rhwp.exe')
}
if ($Phase -in @('Editor','Cli')) {
    $role = $Phase.ToLowerInvariant()
    python scripts/windows_components.py capture --role $role --payload $stage --source $source --out (Join-Path $root ".work/$role-component") --architecture $Architecture
    if ($role -eq 'editor') {
        python e2e/structured_cli_mcp/stage_structured.py seal --generator-exe (Join-Path $editorTarget "$target/debug/examples/opengeul-structured-fixtures.exe") --editor-component (Join-Path $root '.work/editor-component') --fixtures (Join-Path $root '.work/structured-fixtures') --architecture $Architecture --out (Join-Path $root '.work/structured-input-binding.json')
    }
    Write-Host "Built and source-bound $role component; release gates remain pending."
    exit 0
}
}
New-Item -ItemType Directory -Force $output | Out-Null
python e2e/native_architecture.py cli --architecture $Architecture --executable (Join-Path $stage 'Tools/rhwp.exe') --output (Join-Path $root '.work/cli-native-architecture.json') --help-output (Join-Path $output 'rhwp-help.txt')
python scripts/buildkit.py audit $stage
$sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/bin'
$makeappx = Get-ChildItem $sdkRoot -Filter 'makeappx.exe' -Recurse |
    Where-Object { $_.Directory.Name -eq 'x64' } | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $makeappx) { throw 'Windows SDK MakeAppx.exe not found.' }
$suffix = if ($Store) { 'store-unsigned' } else { 'development-unsigned' }
$fileName = "OpenGeul_$($product.version).0_${Architecture}_$suffix.msix"
$package = Join-Path $output $fileName
& $makeappx.FullName pack /d $stage /p $package /o
& $makeappx.FullName unpack /p $package /d (Join-Path $root '.work/msix-verified') /o
python scripts/releasekit.py verify $package --architecture $Architecture
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath (Join-Path $output "OpenGeul_$($product.version)_windows-${Architecture}_unsigned-portable.zip")
Copy-Item (Join-Path $stage 'AppxManifest.xml') $output
if ($Phase -eq 'Package') {
    python scripts/releasekit.py finish $output $source --architecture $Architecture --require-windows-components
} else {
    python scripts/releasekit.py finish $output $source --architecture $Architecture
}
Write-Host "Built and structurally verified unsigned MSIX: $package"
Write-Host 'E2E jobs must pass before release. No trusted signature or Store approval is implied.'
