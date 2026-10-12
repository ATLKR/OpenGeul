# A short-lived test certificate signs a COPY on this disposable runner only.
# No signing key, certificate or signed copy is published or used for production.
param([Parameter(Mandatory)][string]$PackageDirectory,[Parameter(Mandatory)][string]$OutputDirectory,
      [Parameter(Mandatory)][string]$McpFixtureDirectory,
      [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedCliSha256,
      [ValidateSet('x64','arm64')][string]$Architecture='x64')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$true
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Install smoke is restricted to disposable GitHub Actions runners.' }
$McpFixtureDirectory=(Resolve-Path -LiteralPath $McpFixtureDirectory -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath (Join-Path $McpFixtureDirectory 'e2e-fixtures/basic.hwpx')) -or -not (Test-Path -LiteralPath (Join-Path $McpFixtureDirectory 'password-fixtures/manifest.json'))) { throw '검증한 같은 소스 실행의 MCP QA 원본이 필요합니다.' }
$original=@(Get-ChildItem $PackageDirectory -Filter '*.msix')
if ($original.Count -ne 1) { throw 'Exactly one package required.' }
$before=(Get-FileHash $original[0].FullName -Algorithm SHA256).Hash
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
$work=Join-Path $env:RUNNER_TEMP ("opengeul-test-sign-"+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $work | Out-Null
$cert=$null;$trusted=$null;$installed=$null;$launched=$null;$addedFrameworks=@();$frameworkEvidence=@()
try {
 [xml]$manifest=Get-Content (Join-Path $PackageDirectory 'AppxManifest.xml') -Raw
 $publisher=[string]$manifest.Package.Identity.Publisher
 $identity=[string]$manifest.Package.Identity.Name
 if ([string]$manifest.Package.Identity.ProcessorArchitecture -cne $Architecture) { throw '설치 후보의 아키텍처가 기대값과 다릅니다.' }
 python (Join-Path $PSScriptRoot 'native_architecture.py') host --architecture $Architecture --output (Join-Path $OutputDirectory 'host-architecture.json')
 if (-not $publisher -or -not $identity) { throw 'Package identity missing.' }
 if (Get-AppxPackage -Name $identity) { throw 'Refusing to replace an existing package.' }
 $cert=New-SelfSignedCertificate -Type Custom -Subject $publisher -KeyUsage DigitalSignature -KeyExportPolicy Exportable -CertStoreLocation 'Cert:\CurrentUser\My' -NotAfter (Get-Date).AddDays(1) -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3','2.5.29.19={text}')
 $password=[guid]::NewGuid().ToString('N')
 $secure=ConvertTo-SecureString $password -AsPlainText -Force
 Export-PfxCertificate -Cert $cert -FilePath (Join-Path $work 'test.pfx') -Password $secure | Out-Null
 Export-Certificate -Cert $cert -FilePath (Join-Path $work 'test.cer') | Out-Null
 $trusted=Import-Certificate -FilePath (Join-Path $work 'test.cer') -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople'
 $copy=Join-Path $work 'test-only.msix'
 Copy-Item $original[0].FullName $copy
 $sdk=Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/bin'
 $signer=Get-ChildItem $sdk -Filter signtool.exe -Recurse | Where-Object { $_.Directory.Name -eq 'x64' } | Sort-Object FullName -Descending | Select-Object -First 1
 if (-not $signer) { throw 'Windows SDK SignTool is missing.' }
 & $signer.FullName sign /fd SHA256 /f (Join-Path $work 'test.pfx') /p $password $copy
 & $signer.FullName verify /pa $copy
 $signedCopySha256=(Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash
 foreach ($dependency in $manifest.SelectNodes("//*[local-name()='Dependencies']/*[local-name()='PackageDependency']")) {
  $name=$dependency.GetAttribute('Name');$minimum=[version]$dependency.GetAttribute('MinVersion');$requiredPublisher=$dependency.GetAttribute('Publisher')
  if ($name -ne 'Microsoft.VCLibs.140.00.UWPDesktop' -or $requiredPublisher -ne 'CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US') { throw 'Unreviewed package framework dependency.' }
  $framework=Get-AppxPackage -Name $name | Where-Object { $_.Publisher -eq $requiredPublisher -and [version]$_.Version -ge $minimum -and $_.Architecture.ToString().ToLowerInvariant() -eq $Architecture } | Select-Object -First 1
  if (-not $framework) {
   $download=Join-Path $work "Microsoft.VCLibs.$Architecture.14.00.Desktop.appx"
   $url=if ($Architecture -eq 'arm64') { 'https://aka.ms/Microsoft.VCLibs.arm64.14.00.Desktop.appx' } else { 'https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx' }
   Invoke-WebRequest $url -OutFile $download
   & $signer.FullName verify /pa $download
   $archive=[System.IO.Compression.ZipFile]::OpenRead($download)
   try {
    $reader=[System.IO.StreamReader]::new($archive.GetEntry('AppxManifest.xml').Open())
    try { [xml]$frameworkManifest=$reader.ReadToEnd() } finally { $reader.Dispose() }
   } finally { $archive.Dispose() }
   $frameworkIdentity=$frameworkManifest.Package.Identity
   if ($frameworkIdentity.Name -ne $name -or $frameworkIdentity.Publisher -ne $requiredPublisher -or $frameworkIdentity.ProcessorArchitecture -cne $Architecture -or [version]$frameworkIdentity.Version -lt $minimum) { throw 'Downloaded VCLibs framework identity/version does not match the declared dependency.' }
   Add-AppxPackage -Path $download -ErrorAction Stop
   $framework=Get-AppxPackage -Name $name | Where-Object { $_.Publisher -eq $requiredPublisher -and [version]$_.Version -ge $minimum -and $_.Architecture.ToString().ToLowerInvariant() -eq $Architecture } | Select-Object -First 1
   if (-not $framework) { throw 'VCLibs framework registration failed.' }
   $addedFrameworks+=$framework.PackageFullName
   $frameworkEvidence+=@{packageFullName=$framework.PackageFullName;source=$url;sha256=(Get-FileHash $download -Algorithm SHA256).Hash}
  } else { $frameworkEvidence+=@{packageFullName=$framework.PackageFullName;source='already registered'} }
 }
 $frameworkEvidence | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $OutputDirectory 'frameworks.json') -Encoding utf8
 Add-AppxPackage -Path $copy -ErrorAction Stop
 $installed=Get-AppxPackage -Name $identity
 if (-not $installed -or $installed.Publisher -ne $publisher -or $installed.Architecture.ToString().ToLowerInvariant() -ne $Architecture) { throw 'Installed identity does not match.' }
 $registered=Get-AppxPackageManifest -Package $installed.PackageFullName
 $types=@($registered.SelectNodes("//*[local-name()='FileTypeAssociation']/*[local-name()='SupportedFileTypes']/*[local-name()='FileType']") | ForEach-Object { $_.InnerText })
 if ('.hwp' -notin $types -or '.hwpx' -notin $types) { throw 'Registered file associations missing.' }
 $executable=Join-Path $installed.InstallLocation 'OpenGeul.exe'
 if (-not (Test-Path $executable)) { throw 'Registered executable is missing.' }
 Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class OpenGeulPackageIdentity {
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true)]
 public static extern int GetPackageFullName(IntPtr process, ref uint length, StringBuilder name);
}
'@
 $launchStarted=Get-Date
 Start-Process explorer.exe -ArgumentList "shell:AppsFolder\$($installed.PackageFamilyName)!OpenGeul"
 $deadline=(Get-Date).AddSeconds(60)
 do {
  $launched=Get-Process -Name OpenGeul -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $executable -and $_.StartTime -ge $launchStarted -and $_.MainWindowHandle -ne 0 } | Select-Object -First 1
  if (-not $launched) { Start-Sleep -Milliseconds 250 }
 } while (-not $launched -and (Get-Date) -lt $deadline)
 if (-not $launched) { throw 'Installed app activation did not produce a visible owned window within 60 seconds.' }
 $length=[uint32]0
 if ([OpenGeulPackageIdentity]::GetPackageFullName($launched.Handle,[ref]$length,$null) -ne 122) { throw 'Launched installed process has no verifiable package identity.' }
 $processIdentity=[System.Text.StringBuilder]::new([int]$length)
 if ([OpenGeulPackageIdentity]::GetPackageFullName($launched.Handle,[ref]$length,$processIdentity) -ne 0 -or $processIdentity.ToString() -ne $installed.PackageFullName) { throw 'Launched process package identity does not match the installed candidate.' }
 Start-Sleep -Seconds 3
 $launched.Refresh()
 if ($launched.HasExited -or $launched.MainWindowHandle -eq 0) { throw 'Installed app exited or lost its window during startup smoke.' }
 python (Join-Path $PSScriptRoot 'native_architecture.py') process --architecture $Architecture --pid $launched.Id --executable $executable --package-full-name $installed.PackageFullName --webview2 --output (Join-Path $OutputDirectory 'installed-native-architecture.json')
 $nativeEvidence=Get-Content (Join-Path $OutputDirectory 'installed-native-architecture.json') -Raw | ConvertFrom-Json
 @{success=$true;architecture=$Architecture;nativeArchitecture=$nativeEvidence;processId=$launched.Id;packageFullName=$processIdentity.ToString();executable=$launched.Path;windowTitle=$launched.MainWindowTitle} | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $OutputDirectory 'installed-launch.json') -Encoding utf8
 $cli=Join-Path $installed.InstallLocation 'Tools/rhwp.exe'
 $cliResult=Join-Path (Resolve-Path $OutputDirectory).Path 'installed-cli.json'
 if (Test-Path $cliResult) { throw 'Refusing to reuse an installed CLI result.' }
 $probeArgs="-NoProfile -File `"$(Join-Path $PSScriptRoot 'installed-cli.ps1')`" -CliPath `"$cli`" -PackageFullName `"$($installed.PackageFullName)`" -OutputDirectory `"$((Resolve-Path $OutputDirectory).Path)`" -McpFixtureDirectory `"$McpFixtureDirectory`" -ExpectedCliSha256 $ExpectedCliSha256 -Architecture $Architecture -PythonPath `"$((Get-Command python -ErrorAction Stop).Source)`""
 Invoke-CommandInDesktopPackage -PackageFamilyName $installed.PackageFamilyName -AppId OpenGeul -Command (Get-Process -Id $PID).Path -Args $probeArgs -PreventBreakaway
 $deadline=(Get-Date).AddSeconds(60)
 while (-not (Test-Path $cliResult) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
 if (-not (Test-Path $cliResult)) { throw 'Installed CLI package-context probe did not complete within 60 seconds.' }
 $cliEvidence=Get-Content $cliResult -Raw | ConvertFrom-Json
 if (-not $cliEvidence.success -or $cliEvidence.packageFullName -ne $installed.PackageFullName -or $cliEvidence.nativeArchitecture.architecture -ne $Architecture) { throw 'Installed CLI package-context probe failed; see installed-cli.json.' }
 Stop-Process -Id $launched.Id -Force
 $launched=$null
 # WACK's documented package-input mode analyses a temporary extraction, avoiding
 # the WindowsApps activation-context access failure observed in full-name mode.
 # Keep the test certificate trusted until WACK completes; do not alter the package.
 Remove-AppxPackage -Package $installed.PackageFullName -ErrorAction Stop
 if (Get-AppxPackage -Name $identity) { throw 'Installed smoke candidate remains registered before package-input WACK.' }
 & (Join-Path $PSScriptRoot 'wack.ps1') -PackagePath $copy -ExpectedPackageSha256 $signedCopySha256 -Identity $identity -Version ([string]$manifest.Package.Identity.Version) -OutputDirectory $OutputDirectory
 @{
  success=$true; architecture=$Architecture; packageFullName=$installed.PackageFullName; publisher=$publisher;
  fileTypes=$types; originalSha256=$before; signedTestPackageSha256=$signedCopySha256;
  mcp=$cliEvidence.mcp;
  scope='test-only signing, AppX installation, package-identity activation, installed CLI, registered file types and uninstall; WACK status is reported separately in wack.json; not Store certification or real-printer/IME testing'
 } | ConvertTo-Json -Depth 20 | Set-Content (Join-Path $OutputDirectory 'install.json') -Encoding utf8
} finally {
 if ($launched -and -not $launched.HasExited) { Stop-Process -Id $launched.Id -Force -ErrorAction Continue }
 if ($installed) { Get-Process -Name OpenGeul -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $installed.InstallLocation 'OpenGeul.exe') } | Stop-Process -Force -ErrorAction Continue }
 if ($installed) { Get-Process -Name rhwp -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $installed.InstallLocation 'Tools/rhwp.exe') } | Stop-Process -Force -ErrorAction Continue }
 if ($installed -and (Get-AppxPackage -Name $identity | Where-Object { $_.PackageFullName -eq $installed.PackageFullName })) { Remove-AppxPackage -Package $installed.PackageFullName -ErrorAction Continue }
 foreach ($framework in $addedFrameworks) { Remove-AppxPackage -Package $framework -ErrorAction Continue }
 if ($trusted) { Remove-Item ("Cert:\LocalMachine\TrustedPeople\"+$trusted.Thumbprint) -Force -ErrorAction Continue }
 if ($cert) { Remove-Item ("Cert:\CurrentUser\My\"+$cert.Thumbprint) -Force -ErrorAction Continue }
 Remove-Item $work -Recurse -Force -ErrorAction Continue
 if ((Get-FileHash $original[0].FullName -Algorithm SHA256).Hash -ne $before) { throw 'Unsigned release artifact was modified by install testing.' }
}
if (Get-AppxPackage -Name $identity) { throw 'Test package was not uninstalled.' }
