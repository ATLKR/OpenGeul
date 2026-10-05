# Windows x64, PowerShell 7, Python 3.11+, Node 24, Rustup and Windows SDK.
[CmdletBinding()]
param([switch]$Store, [string]$IdentityFile)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$env:PYTHONUTF8 = '1'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not $IsWindows) { throw 'Native builds require Windows.' }
foreach ($tool in @('python','git','node','rustup','corepack')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing prerequisite: $tool" }
}
$source = Join-Path $root '.work/hop'
$stage = Join-Path $root '.work/payload'
$output = Join-Path $root 'dist'
if ((Test-Path $stage) -or (Test-Path $output)) { throw 'Preserve previous outputs before rebuilding; .work/payload or dist already exists.' }
$product = Get-Content 'config/product.json' -Raw | ConvertFrom-Json
$lock = Get-Content 'config/upstream.lock.json' -Raw | ConvertFrom-Json
if ($Store -and -not $IdentityFile) { throw 'Store build requires real Partner Center identity.' }
python -m unittest discover -s tests -v
New-Item -ItemType Directory -Force $stage,$output | Out-Null
$manifestArgs = @('scripts/buildkit.py','manifest','--out',(Join-Path $stage 'AppxManifest.xml'))
if ($IdentityFile) { $manifestArgs += @('--identity',(Resolve-Path $IdentityFile).Path) }
if ($Store) { $manifestArgs += '--store' }
& python @manifestArgs
python scripts/prepare_upstream.py --fetch-only
rustup toolchain install $lock.rust --profile minimal --target x86_64-pc-windows-msvc
$env:RUSTUP_TOOLCHAIN = $lock.rust
$env:CARGO_TARGET_DIR = Join-Path $root '.work/target'
$env:CARGO_BUILD_JOBS = '2'
$env:CARGO_PROFILE_DEV_DEBUG = '0'
$env:CARGO_PROFILE_TEST_DEBUG = '0'
rustc --edition=2021 --test overlay/font_policy.rs -o .work/font-policy-tests.exe
& .work/font-policy-tests.exe
corepack enable
Push-Location $source
try {
    pnpm install --frozen-lockfile
    # Upstream's source/provenance and UI contracts run before intentional product-policy changes.
    # Only the reproduced Windows path-separator false positive is ported; no assertion is removed.
    pnpm run test:upstream
    pnpm run test:studio
} finally { Pop-Location }
python scripts/prepare_upstream.py --patch-only
Push-Location $source
try {
    # The actual modified frontend suite is a required gate, not the unchanged baseline alone.
    pnpm run test:studio
    Push-Location 'apps/desktop/src-tauri'
    try { cargo test --locked } finally { Pop-Location }
    pnpm tauri build --no-bundle --target x86_64-pc-windows-msvc
    Push-Location 'third_party/rhwp'
    try {
        # CLI retains native Skia PNG and direct PDF options, in addition to the standard engine.
        cargo build --release --locked --target x86_64-pc-windows-msvc --package rhwp --bin rhwp --features native-skia
    } finally { Pop-Location }
} finally { Pop-Location }
$release = Join-Path $env:CARGO_TARGET_DIR 'x86_64-pc-windows-msvc/release'
foreach ($name in @('hop-desktop.exe','rhwp.exe')) {
    if (-not (Test-Path (Join-Path $release $name))) { throw "Missing built runtime: $name" }
}
Copy-Item (Join-Path $release 'hop-desktop.exe') (Join-Path $stage 'OpenGeul.exe')
New-Item -ItemType Directory -Force (Join-Path $stage 'Tools') | Out-Null
Copy-Item (Join-Path $release 'rhwp.exe') (Join-Path $stage 'Tools/rhwp.exe')
Get-ChildItem $release -Filter '*.dll' -File | ForEach-Object { Copy-Item $_.FullName $stage }
# A real executable smoke test catches missing native loader dependencies.
$help = & (Join-Path $stage 'Tools/rhwp.exe') --help 2>&1 | Out-String
if ($help -notmatch '(?i)rhwp|usage|사용') { throw 'CLI did not return usable help.' }
$help | Set-Content (Join-Path $output 'rhwp-help.txt') -Encoding utf8
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
python scripts/buildkit.py audit $stage
$sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/bin'
$makeappx = Get-ChildItem $sdkRoot -Filter 'makeappx.exe' -Recurse |
    Where-Object { $_.Directory.Name -eq 'x64' } | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $makeappx) { throw 'Windows SDK MakeAppx.exe not found.' }
$suffix = if ($Store) { 'store-unsigned' } else { 'development-unsigned' }
$fileName = "OpenGeul_$($product.version).0_x64_$suffix.msix"
$package = Join-Path $output $fileName
& $makeappx.FullName pack /d $stage /p $package /o
& $makeappx.FullName unpack /p $package /d (Join-Path $root '.work/msix-verified') /o
python scripts/releasekit.py verify $package
# Portable form is useful before signing; it does not bypass organization/Windows security policy.
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath (Join-Path $output "OpenGeul_$($product.version)_windows-x64_unsigned-portable.zip")
Copy-Item (Join-Path $stage 'AppxManifest.xml') $output
python scripts/releasekit.py finish $output $source
Write-Host "Built and structurally verified unsigned MSIX: $package"
Write-Host 'No Store approval, trusted signature or manual document fidelity certification is implied.'
