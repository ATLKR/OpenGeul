# Windows 네이티브 x64 또는 ARM64, PowerShell 7, Python 3.11+, Node 24, Rustup and Windows SDK.
[CmdletBinding()]
param(
    [switch]$Store, [string]$IdentityFile, [string]$WasmDirectory,
    [ValidateSet('All','Editor','Cli','Package')][string]$Phase = 'All',
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
if ($Phase -ne 'Package' -and -not $WasmDirectory) { throw 'Compilation requires source-bound rebuilt WASM.' }
if ($Phase -eq 'Package' -and (-not $EditorComponent -or -not $CliComponent)) { throw 'Packaging requires both same-run components.' }
$tools = if ($Phase -eq 'Package') { @('python') } else { @('python','git','node','rustup','corepack') }
foreach ($tool in $tools) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing prerequisite: $tool" }
}
$source = Join-Path $root '.work/hop'
$stage = Join-Path $root '.work/payload'
$output = Join-Path $root 'dist'
if ((Test-Path $stage) -or (Test-Path $output)) { throw 'Preserve previous outputs before rebuilding; .work/payload or dist already exists.' }
$product = Get-Content 'config/product.json' -Raw | ConvertFrom-Json
$lock = Get-Content 'config/upstream.lock.json' -Raw | ConvertFrom-Json
$target = python -c "import sys;sys.path.insert(0,'scripts');from windows_arch import target_triple;print(target_triple(sys.argv[1]))" $Architecture
New-Item -ItemType Directory -Force (Join-Path $root '.work') | Out-Null
python e2e/native_architecture.py host --architecture $Architecture --output (Join-Path $root '.work/host-architecture.json')
if ($Store -and -not $IdentityFile) { throw 'Store build requires real Partner Center identity.' }
if ($Phase -eq 'Package') {
    $source = Join-Path $root '.work/package-source'
    # The join validates both complete inventories, source contracts and architecture-matched PE
    # bytes before creating any payload or restoring the release source ledger.
    python scripts/windows_components.py combine --editor $EditorComponent --cli $CliComponent --payload $stage --source $source --architecture $Architecture
} else {
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
$env:RUSTUP_TOOLCHAIN = "$($lock.rust)-$target"
$env:CARGO_TARGET_DIR = Join-Path $root '.work/target'
$editorTarget = $env:CARGO_TARGET_DIR
$cliTarget = Join-Path $root '.work/target-cli'
$env:CARGO_BUILD_JOBS = '2'
$env:CARGO_PROFILE_DEV_DEBUG = '0'
$env:CARGO_PROFILE_TEST_DEBUG = '0'
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
Push-Location $source
try {
    if ($Phase -in @('All','Editor')) {
    pnpm run test:studio
    pnpm run build:studio
    python ../../scripts/buildkit.py frontend apps/studio-host/dist
    # Reuse the native test graph for the table and PDF policy regressions.
    # Keep it separate from the GUI's different feature graph.
    Push-Location 'third_party/rhwp'
    try {
        $env:CARGO_TARGET_DIR = $cliTarget
        cargo test --locked --target $target --test opengeul_table_height
        cargo test --locked --target $target --package rhwp --test opengeul_pdf_policy --features native-skia
    } finally {
        $env:CARGO_TARGET_DIR = $editorTarget
        Pop-Location
    }
    Push-Location 'apps/desktop/src-tauri'
    try {
        cargo test --locked --target $target
        cargo test --locked --target $target --package opengeul-native-open
        cargo run --locked --target $target --example opengeul-fixtures -- (Join-Path $root '.work/e2e-fixtures')
    } finally { Pop-Location }
    pnpm tauri build --no-bundle --target $target
    }
    if ($Phase -in @('All','Cli')) {
    Push-Location 'third_party/rhwp'
    try {
        # cdylib/rlib outputs must not collide with the editor's different feature graph.
        $env:CARGO_TARGET_DIR = $cliTarget
        cargo build --release --locked --target $target --package rhwp --bin rhwp --features native-skia
    } finally {
        $env:CARGO_TARGET_DIR = $editorTarget
        Pop-Location
    }
    }
} finally { Pop-Location }
$release = Join-Path $env:CARGO_TARGET_DIR "$target/release"
$cliRelease = Join-Path $cliTarget "$target/release"
if ($Phase -in @('All','Editor')) {
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
