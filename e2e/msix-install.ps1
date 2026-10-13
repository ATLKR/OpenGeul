# A short-lived test certificate signs a COPY on this disposable runner only.
# ARM native proof transports only the signed COPY and public CER to the stock
# x64 SDK scanner. A private signing key/password never leaves this runner.
param([Parameter(Mandatory)][string]$PackageDirectory,[Parameter(Mandatory)][string]$OutputDirectory,
      [Parameter(Mandatory)][string]$McpFixtureDirectory,
      [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedCliSha256,
      [ValidateSet('x64','arm64')][string]$Architecture='x64',
      [switch]$NativeOnly,[string]$TransportDirectory)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$true
function Get-OpenGeulNativeOriginalEvidence {
 param([Parameter(Mandatory)][string]$OutputDirectory)
 $result=[ordered]@{}
 foreach ($name in @('installed-launch.json','installed-cli.json')) {
  $path=Join-Path $OutputDirectory $name
  $item=Get-Item -LiteralPath $path -ErrorAction Stop
  if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -le 0 -or $item.Length -gt 512*1024) {
   throw '실제 설치 증거의 정규 원본 파일이 필요합니다.'
  }
  $raw=[IO.File]::ReadAllBytes($path)
  $result[$name]=@{rawBase64=[Convert]::ToBase64String($raw);bytes=$raw.Length;
   sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($raw)).ToLowerInvariant()}
 }
 return $result
}
function Write-OpenGeulNativeResult {
 param([Parameter(Mandatory)][string]$TransportDirectory,[Parameter(Mandatory)]$Record)
 foreach ($field in @('candidateUninstalled','unsignedUnchanged','privateKeyRemoved','trustedCertificateRemoved','frameworksRemoved')) {
  if ($Record.cleanup[$field] -isnot [bool] -or $Record.cleanup[$field] -ne $true) { throw "네이티브 검증 정리를 완료하지 못했습니다: $field" }
 }
 if ($Record.formatVersion -ne 1 -or $Record.success -isnot [bool] -or $Record.success -ne $true -or $Record.scope -cne 'native-arm64-install-only' -or
     $Record.installation.success -ne $true -or $Record.installation.architecture -cne 'arm64' -or
     $Record.installation.uninstalled -ne $true -or $Record.launch.success -ne $true -or $Record.cli.success -ne $true) {
  throw '완료한 ARM64 네이티브 설치 증거만 게시할 수 있습니다.'
 }
 $files=@(Get-ChildItem -LiteralPath $TransportDirectory -Force)
 if ($files.Count -ne 2 -or (@($files.Name | Sort-Object) -join ',') -cne 'test-only.msix,test.cer' -or
     @($files | Where-Object { $_.PSIsContainer -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) }).Count) {
  throw '서명한 MSIX와 공개 CER 두 개만 전송할 수 있습니다.'
 }
 if ((Get-FileHash -LiteralPath (Join-Path $TransportDirectory 'test-only.msix') -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Record.installation.signedTestPackageSha256.ToLowerInvariant() -or
     (Get-FileHash -LiteralPath (Join-Path $TransportDirectory 'test.cer') -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Record.certificate.sha256) {
  throw '전송할 서명 패키지 또는 공개 인증서 바이트가 다릅니다.'
 }
 $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Record | ConvertTo-Json -Depth 40)+"`n")
 if ($bytes.Length -gt 512*1024) { throw '네이티브 전송 JSON 크기를 초과했습니다.' }
 $stream=[IO.File]::Open((Join-Path $TransportDirectory 'native-install.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
 try { $stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
}
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Install smoke is restricted to disposable GitHub Actions runners.' }
$publicCiContext=[ordered]@{CiActions=[string]$env:GITHUB_ACTIONS;CiRunnerEnvironment=[string]$env:RUNNER_ENVIRONMENT;
 CiRepository=[string]$env:GITHUB_REPOSITORY;CiCommit=[string]$env:GITHUB_SHA;
 CiRunId=[string]$env:GITHUB_RUN_ID;CiRunAttempt=[string]$env:GITHUB_RUN_ATTEMPT}
if ($publicCiContext.CiActions -cne 'true' -or $publicCiContext.CiRunnerEnvironment -cne 'github-hosted' -or
 $publicCiContext.CiRepository -cne 'ATLKR/OpenGeul' -or $publicCiContext.CiCommit -cnotmatch '^[0-9a-f]{40}$' -or
 $publicCiContext.CiRunId -cnotmatch '^[1-9][0-9]{0,19}$' -or $publicCiContext.CiRunAttempt -cnotmatch '^[1-9][0-9]{0,19}$') {
 throw '현재 공개 CI 실행 정보가 올바르지 않습니다.'
}
if ($NativeOnly) {
 if ($Architecture -cne 'arm64' -or $env:GITHUB_JOB -cnotin @('msix-native-arm64','store-native-arm64') -or -not $TransportDirectory) {
  throw 'NativeOnly는 현재 공개 ARM64 설치 producer에서만 사용할 수 있습니다.'
 }
 if (Test-Path -LiteralPath $OutputDirectory) { throw '기존 네이티브 설치 증거 디렉터리를 재사용하지 않습니다.' }
 if (Test-Path -LiteralPath $TransportDirectory) { throw '기존 네이티브 전송 디렉터리를 재사용하지 않습니다.' }
 New-Item -ItemType Directory $TransportDirectory | Out-Null
 $TransportDirectory=(Resolve-Path -LiteralPath $TransportDirectory).Path
} elseif ($TransportDirectory) { throw '전송 디렉터리는 NativeOnly 검증에만 사용할 수 있습니다.' }
$McpFixtureDirectory=(Resolve-Path -LiteralPath $McpFixtureDirectory -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath (Join-Path $McpFixtureDirectory 'e2e-fixtures/basic.hwpx')) -or -not (Test-Path -LiteralPath (Join-Path $McpFixtureDirectory 'password-fixtures/manifest.json'))) { throw '검증한 같은 소스 실행의 MCP QA 원본이 필요합니다.' }
$original=@(Get-ChildItem $PackageDirectory -Filter '*.msix')
if ($original.Count -ne 1) { throw 'Exactly one package required.' }
$before=(Get-FileHash $original[0].FullName -Algorithm SHA256).Hash
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
$work=Join-Path $env:RUNNER_TEMP ("opengeul-test-sign-"+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $work | Out-Null
$cert=$null;$trusted=$null;$installed=$null;$launched=$null;$addedFrameworks=@();$frameworkEvidence=@();$nativeRecord=$null;$privateKeyPath=$null
try {
 [xml]$manifest=Get-Content (Join-Path $PackageDirectory 'AppxManifest.xml') -Raw
 $publisher=[string]$manifest.Package.Identity.Publisher
 $identity=[string]$manifest.Package.Identity.Name
 if ([string]$manifest.Package.Identity.ProcessorArchitecture -cne $Architecture) { throw '설치 후보의 아키텍처가 기대값과 다릅니다.' }
 python (Join-Path $PSScriptRoot 'native_architecture.py') host --architecture $Architecture --output (Join-Path $OutputDirectory 'host-architecture.json')
 if (-not $publisher -or -not $identity) { throw 'Package identity missing.' }
 if (Get-AppxPackage -Name $identity) { throw 'Refusing to replace an existing package.' }
 if ($NativeOnly) {
  $now=Get-Date
  $cert=New-SelfSignedCertificate -Type Custom -Subject $publisher -KeyUsage DigitalSignature -KeyExportPolicy Exportable -Provider 'Microsoft Software Key Storage Provider' -KeyAlgorithm RSA -CertStoreLocation 'Cert:\CurrentUser\My' -NotBefore $now.AddMinutes(-5) -NotAfter $now.AddHours(23) -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3','2.5.29.19={text}')
  $cert=Get-Item -LiteralPath ("Cert:\CurrentUser\My\"+$cert.Thumbprint) -ErrorAction Stop
  if ($cert -isnot [Security.Cryptography.X509Certificates.X509Certificate2] -or -not $cert.HasPrivateKey) { throw '실제 생성한 개인 인증서를 확인할 수 없습니다.' }
  $key=[Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)
  try {
   if ($key -isnot [Security.Cryptography.RSACng] -or -not $key.Key.UniqueName) { throw '생성한 테스트 CNG 개인 키를 확인할 수 없습니다.' }
   $privateKeyPath=Join-Path $env:APPDATA ('Microsoft/Crypto/Keys/'+$key.Key.UniqueName)
   if (-not (Test-Path -LiteralPath $privateKeyPath -PathType Leaf)) { throw '테스트 개인 키의 실제 파일을 확인할 수 없습니다.' }
  } finally { if ($key) { $key.Dispose() } }
 } else {
  $cert=New-SelfSignedCertificate -Type Custom -Subject $publisher -KeyUsage DigitalSignature -KeyExportPolicy Exportable -CertStoreLocation 'Cert:\CurrentUser\My' -NotAfter (Get-Date).AddDays(1) -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3','2.5.29.19={text}')
 }
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
 $probeArgs+=" -CiActions $($publicCiContext.CiActions) -CiRunnerEnvironment $($publicCiContext.CiRunnerEnvironment) -CiRepository $($publicCiContext.CiRepository) -CiCommit $($publicCiContext.CiCommit) -CiRunId $($publicCiContext.CiRunId) -CiRunAttempt $($publicCiContext.CiRunAttempt)"
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
 $installation=@{
  success=$true; architecture=$Architecture; packageFullName=$installed.PackageFullName; publisher=$publisher;
  fileTypes=$types; originalSha256=$before; signedTestPackageSha256=$signedCopySha256;
  mcp=$cliEvidence.mcp;
  scope='test-only signing, AppX installation, package-identity activation, installed CLI, registered file types and uninstall; WACK status is reported separately in wack.json; not Store certification or real-printer/IME testing'
 }
 if (-not $NativeOnly) {
  & (Join-Path $PSScriptRoot 'wack.ps1') -PackagePath $copy -ExpectedPackageSha256 $signedCopySha256 -Identity $identity -Version ([string]$manifest.Package.Identity.Version) -OutputDirectory $OutputDirectory
  $installation | ConvertTo-Json -Depth 20 | Set-Content (Join-Path $OutputDirectory 'install.json') -Encoding utf8
 } else {
  $signature=Get-AuthenticodeSignature -LiteralPath $copy
  if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate -or $signature.SignerCertificate.Thumbprint -cne $cert.Thumbprint) {
   throw '서명한 네이티브 설치 후보의 실제 Authenticode 인증서가 다릅니다.'
  }
  $publicPath=Join-Path $work 'test.cer'
  $der=[IO.File]::ReadAllBytes($publicPath)
  $public=[Security.Cryptography.X509Certificates.X509Certificate2]::new($der)
  try {
   $codeSigning=@($public.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.37' } | ForEach-Object { $_.EnhancedKeyUsages | Where-Object { $_.Value -eq '1.3.6.1.5.5.7.3.3' } }).Count -eq 1
   if ($public.HasPrivateKey -or $public.Subject -cne $publisher -or $public.Thumbprint -cne $cert.Thumbprint -or
       -not $codeSigning -or ($public.NotAfter.ToUniversalTime()-$public.NotBefore.ToUniversalTime()).TotalSeconds -gt 86400) {
    throw '하루 이내의 공개 코드 서명 인증서만 전송할 수 있습니다.'
   }
   $certificate=@{derBase64=[Convert]::ToBase64String($der);sha256=(Get-FileHash -LiteralPath $publicPath -Algorithm SHA256).Hash.ToLowerInvariant();
    thumbprint=$public.Thumbprint;subject=$public.Subject;notBefore=$public.NotBefore.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss'Z'");
    notAfter=$public.NotAfter.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss'Z'");codeSigning=$true;publicOnly=$true;
    signatureStatus='Valid';signerThumbprint=$signature.SignerCertificate.Thumbprint}
  } finally { $public.Dispose() }
  Copy-Item -LiteralPath $copy -Destination (Join-Path $TransportDirectory 'test-only.msix') -ErrorAction Stop
  Copy-Item -LiteralPath $publicPath -Destination (Join-Path $TransportDirectory 'test.cer') -ErrorAction Stop
  $installation.uninstalled=$true
  $installation.scope='ARM64 native installation, GUI, CLI, isolated MCP, file associations and uninstall only; SDK WACK must pass separately for these exact signed bytes'
  $nativeRecord=[ordered]@{formatVersion=1;success=$true;scope='native-arm64-install-only';
   binding=@{repository=$publicCiContext.CiRepository;commit=$publicCiContext.CiCommit;runId=$publicCiContext.CiRunId;runAttempt=$publicCiContext.CiRunAttempt};
   installation=$installation;launch=(Get-Content -LiteralPath (Join-Path $OutputDirectory 'installed-launch.json') -Raw | ConvertFrom-Json);
   cli=$cliEvidence;certificate=$certificate;originalEvidence=(Get-OpenGeulNativeOriginalEvidence -OutputDirectory $OutputDirectory)}
 }
} finally {
 if ($launched -and -not $launched.HasExited) { Stop-Process -Id $launched.Id -Force -ErrorAction Continue }
 if ($installed) { Get-Process -Name OpenGeul -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $installed.InstallLocation 'OpenGeul.exe') } | Stop-Process -Force -ErrorAction Continue }
 if ($installed) { Get-Process -Name rhwp -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $installed.InstallLocation 'Tools/rhwp.exe') } | Stop-Process -Force -ErrorAction Continue }
 if ($installed -and (Get-AppxPackage -Name $identity | Where-Object { $_.PackageFullName -eq $installed.PackageFullName })) { Remove-AppxPackage -Package $installed.PackageFullName -ErrorAction Continue }
 foreach ($framework in $addedFrameworks) { Remove-AppxPackage -Package $framework -ErrorAction Continue }
 if ($trusted) { Remove-Item ("Cert:\LocalMachine\TrustedPeople\"+$trusted.Thumbprint) -Force -ErrorAction Continue }
 if ($cert) {
  if ($NativeOnly) { Remove-Item ("Cert:\CurrentUser\My\"+$cert.Thumbprint) -DeleteKey -Force -ErrorAction Continue }
  else { Remove-Item ("Cert:\CurrentUser\My\"+$cert.Thumbprint) -Force -ErrorAction Continue }
 }
 Remove-Item $work -Recurse -Force -ErrorAction Continue
 if ((Get-FileHash $original[0].FullName -Algorithm SHA256).Hash -ne $before) { throw 'Unsigned release artifact was modified by install testing.' }
}
if (Get-AppxPackage -Name $identity) { throw 'Test package was not uninstalled.' }
if ($NativeOnly) {
 if (-not $nativeRecord) { throw 'ARM64 네이티브 설치 검증을 완료하지 못했습니다.' }
 $remainingFrameworks=@(foreach ($framework in $addedFrameworks) { Get-AppxPackage | Where-Object { $_.PackageFullName -eq $framework } })
 $nativeRecord.cleanup=[ordered]@{candidateUninstalled=$true;unsignedUnchanged=((Get-FileHash -LiteralPath $original[0].FullName -Algorithm SHA256).Hash -ceq $before);
  privateKeyRemoved=(-not (Test-Path -LiteralPath ("Cert:\CurrentUser\My\"+$cert.Thumbprint)) -and $privateKeyPath -and -not (Test-Path -LiteralPath $privateKeyPath) -and -not (Test-Path -LiteralPath $work));
  trustedCertificateRemoved=(-not (Test-Path -LiteralPath ("Cert:\LocalMachine\TrustedPeople\"+$trusted.Thumbprint)));
  frameworksRemoved=($remainingFrameworks.Count -eq 0)}
 $nativeRecord.completedAt=[DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss'Z'")
 Write-OpenGeulNativeResult -TransportDirectory $TransportDirectory -Record $nativeRecord
}
