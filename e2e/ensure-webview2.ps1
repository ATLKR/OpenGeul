# Test-host prerequisite only; the application package is not changed.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'This setup script is restricted to ephemeral GitHub Actions runners.' }
$paths=@(
 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
 'HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
 'HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
)
function RuntimeVersion {
 foreach ($path in $paths) {
  $item=Get-ItemProperty -Path $path -Name pv -ErrorAction SilentlyContinue
  if ($item -and $item.pv -and $item.pv -ne '0.0.0.0') { return $item.pv }
 }
 return $null
}
$version=RuntimeVersion
if (-not $version) {
 $installer=Join-Path $env:RUNNER_TEMP 'OpenGeul-WebView2-setup.exe'
 try {
  Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $installer
  $signature=Get-AuthenticodeSignature $installer
  if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') { throw 'WebView2 installer signature validation failed.' }
  $process=Start-Process $installer -ArgumentList '/silent','/install' -PassThru
  if (-not $process.WaitForExit(180000)) { $process.Kill(); throw 'WebView2 installation timed out.' }
  if ($process.ExitCode -ne 0) { throw "WebView2 installer failed: $($process.ExitCode)" }
 } finally { Remove-Item $installer -Force -ErrorAction SilentlyContinue }
 $version=RuntimeVersion
 if (-not $version) { throw 'WebView2 runtime not found after installation.' }
}
Write-Host "WebView2 test prerequisite: $version"
