# Scan the native ARM producer's EXACT signed bytes using the stock x64 SDK.
# Only a public, short-lived CER is imported; this host never installs the ARM app.
param([Parameter(Mandatory)][string]$PackageDirectory,
      [Parameter(Mandatory)][string]$NativeDirectory,
      [Parameter(Mandatory)][string]$OutputDirectory,[string]$OriginalDirectory)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$true

function Assert-OpenGeulSelectedUnsignedPackage {
 param([Parameter(Mandatory)][string]$PackageDirectory,
       [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSha256)
 $selected=@(Get-ChildItem -LiteralPath $PackageDirectory -Filter '*.msix' -ErrorAction Stop)
 if ($selected.Count -ne 1 -or $selected[0].PSIsContainer -or
     ($selected[0].Attributes -band [IO.FileAttributes]::ReparsePoint) -or
     (Get-FileHash -LiteralPath $selected[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedSha256) {
  throw '선택한 unsigned ARM64 후보가 전체 원본 검증에서 확인한 바이트와 다릅니다.'
 }
}

function ConvertTo-OpenGeulUtcSecond {
 param([Parameter(Mandatory)][AllowNull()][object]$Value)
 $format="yyyy-MM-ddTHH:mm:ss'Z'"
 $culture=[Globalization.CultureInfo]::InvariantCulture
 if ($Value -is [string]) {
  $parsed=[DateTime]::MinValue
  $styles=[Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal
  if ($Value -cnotmatch '\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\z' -or
      -not [DateTime]::TryParseExact($Value,$format,$culture,$styles,[ref]$parsed) -or
      $parsed.ToString($format,$culture) -cne $Value) { throw '정확한 UTC 전체 초 인증서 날짜가 필요합니다.' }
  return $Value
 }
 # PowerShell 7.4 ConvertFrom-Json turns ISO Z strings into UTC DateTime.
 # Reject values whose timezone or fractional ticks would be lost by formatting.
 if ($Value -is [DateTime] -and $Value.Kind -eq [DateTimeKind]::Utc -and
     $Value.Ticks % [TimeSpan]::TicksPerSecond -eq 0) { return $Value.ToString($format,$culture) }
 throw '인증서 날짜를 손실 없이 UTC 전체 초로 확인할 수 없습니다.'
}

function Get-OpenGeulNativePublicCertificate {
 param([Parameter(Mandatory)][string]$FilePath,[Parameter(Mandatory)]$Metadata,
       [Parameter(Mandatory)][string]$Publisher)
 $der=[IO.File]::ReadAllBytes($FilePath)
 if ($der.Length -eq 0 -or $der.Length -gt 65536 -or
     [Security.Cryptography.X509Certificates.X509Certificate2]::GetCertContentType($der) -ne [Security.Cryptography.X509Certificates.X509ContentType]::Cert) {
  throw '공개 DER 인증서만 가져올 수 있습니다.'
 }
 $public=[Security.Cryptography.X509Certificates.X509Certificate2]::new($der)
 try {
  $sha=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($der)).ToLowerInvariant()
  $codeSigning=@($public.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.37' } | ForEach-Object { $_.EnhancedKeyUsages | Where-Object { $_.Value -eq '1.3.6.1.5.5.7.3.3' } }).Count -eq 1
  $now=[DateTime]::UtcNow
  if ($public.HasPrivateKey -or [Convert]::ToBase64String($public.RawData) -cne [Convert]::ToBase64String($der) -or
      [Convert]::ToBase64String($der) -cne $Metadata.derBase64 -or $sha -cne $Metadata.sha256 -or
      $public.Thumbprint -cne $Metadata.thumbprint -or $public.Thumbprint -cne $Metadata.signerThumbprint -or
      $public.Subject -cne $Publisher -or $public.Subject -cne $Metadata.subject -or $public.Issuer -cne $Publisher -or
      $public.NotBefore.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss'Z'") -cne (ConvertTo-OpenGeulUtcSecond -Value $Metadata.notBefore) -or
      $public.NotAfter.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss'Z'") -cne (ConvertTo-OpenGeulUtcSecond -Value $Metadata.notAfter) -or
      $public.NotBefore.ToUniversalTime() -gt $now -or $public.NotAfter.ToUniversalTime() -le $now -or
      ($public.NotAfter.ToUniversalTime()-$public.NotBefore.ToUniversalTime()).TotalSeconds -gt 86400 -or
      -not $codeSigning -or $Metadata.codeSigning -isnot [bool] -or $Metadata.codeSigning -ne $true -or
      $Metadata.publicOnly -isnot [bool] -or $Metadata.publicOnly -ne $true -or $Metadata.signatureStatus -cne 'Valid') {
   throw '실제 공개 인증서와 ARM 네이티브 생산자의 서명 증거가 다릅니다.'
  }
  return $public
 } catch { $public.Dispose();throw }
}

if ($env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
    $env:GITHUB_REPOSITORY -cne 'ATLKR/OpenGeul' -or $env:GITHUB_SHA -cnotmatch '^[0-9a-f]{40}$' -or
    $env:GITHUB_RUN_ID -cnotmatch '^[1-9][0-9]{0,19}$' -or $env:GITHUB_RUN_ATTEMPT -cnotmatch '^[1-9][0-9]{0,19}$' -or
    $env:GITHUB_JOB -cnotin @('msix-install-arm64','store-wack')) {
 throw '현재 공개 CI의 ARM64 SDK 검사 역할만 허용합니다.'
}
$PackageDirectory=(Resolve-Path -LiteralPath $PackageDirectory).Path
$NativeDirectory=(Resolve-Path -LiteralPath $NativeDirectory).Path
if (-not $OriginalDirectory) { $OriginalDirectory=$PackageDirectory }
$OriginalDirectory=(Resolve-Path -LiteralPath $OriginalDirectory).Path
$helper=Join-Path $PSScriptRoot '../scripts/native_wack_transport.py'
# Validate current run/head/attempt, APIs, all PE/runtime/manifest bytes and both
# source artifact hashes before a public certificate can enter TrustedPeople.
python $helper validate-input --package-directory $OriginalDirectory --native-directory $NativeDirectory --output-directory $OutputDirectory
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
$pending=Get-Content -LiteralPath (Join-Path $OutputDirectory 'pending-native.json') -Raw | ConvertFrom-Json
Assert-OpenGeulSelectedUnsignedPackage -PackageDirectory $PackageDirectory -ExpectedSha256 $pending.unsignedSha256
$certificate=Get-OpenGeulNativePublicCertificate -FilePath (Join-Path $NativeDirectory 'test.cer') -Metadata $pending.native.certificate -Publisher $pending.packageIdentity.Publisher
$copy=Join-Path $NativeDirectory 'test-only.msix'
$trusted=$null
try {
 python (Join-Path $PSScriptRoot 'native_architecture.py') host --architecture x64 --output (Join-Path $OutputDirectory 'host-architecture.json')
 $trustPath='Cert:\LocalMachine\TrustedPeople\'+$certificate.Thumbprint
 if (Test-Path -LiteralPath $trustPath) { throw '기존 신뢰 인증서를 수정하지 않습니다.' }
 $trusted=Import-Certificate -FilePath (Join-Path $NativeDirectory 'test.cer') -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople'
 if ($trusted.Thumbprint -cne $certificate.Thumbprint -or $trusted.HasPrivateKey) { throw '가져온 공개 인증서가 다릅니다.' }
 $signature=Get-AuthenticodeSignature -LiteralPath $copy
 if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate -or
     $signature.SignerCertificate.Thumbprint -cne $certificate.Thumbprint -or
     [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($signature.SignerCertificate.RawData)).ToLowerInvariant() -cne $pending.native.certificate.sha256) {
  throw 'WACK 입력의 실제 Authenticode 서명자가 네이티브 설치 후보와 다릅니다.'
 }
 $appcert=Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/App Certification Kit/appcert.exe'
 if (-not (Test-Path -LiteralPath $appcert -PathType Leaf)) { throw '기본 경로의 stock Microsoft WACK SDK가 필요합니다.' }
 $tool=Get-Item -LiteralPath $appcert
 $toolSignature=Get-AuthenticodeSignature -LiteralPath $appcert
 if ($toolSignature.Status -ne 'Valid' -or -not $toolSignature.SignerCertificate -or
     $toolSignature.SignerCertificate.Subject -cnotmatch '(^|,\s*)O=Microsoft Corporation(,|$)') {
  throw 'stock SDK의 유효한 Microsoft Authenticode 서명이 필요합니다.'
 }
 $version=@($tool.VersionInfo.FileMajorPart,$tool.VersionInfo.FileMinorPart,$tool.VersionInfo.FileBuildPart,$tool.VersionInfo.FilePrivatePart) -join '.'
 if ($version -cnotmatch '^10\.[0-9]+\.[0-9]+\.[0-9]+$' -or $tool.VersionInfo.ProductVersion -cne $version) { throw 'SDK의 실제 파일·제품 버전이 다릅니다.' }
 python (Join-Path $PSScriptRoot 'wack-controller.py') --exe $appcert --output (Join-Path $OutputDirectory 'sdk-tool-process.json')
 $observed=Get-Content -LiteralPath (Join-Path $OutputDirectory 'sdk-tool-process.json') -Raw | ConvertFrom-Json
 if ($observed.path -cne $tool.FullName -or $observed.sha256 -cne (Get-FileHash -LiteralPath $appcert -Algorithm SHA256).Hash.ToLowerInvariant() -or
     $observed.bytes -ne $tool.Length -or $observed.peMachine -ne 0x8664 -or $observed.processMachine -ne 0 -or
     $observed.nativeMachine -ne 0x8664 -or $observed.ordinaryExit -ne $true -or $observed.processId -le 0) {
  throw '실제 stock SDK process 관측이 현재 도구 바이트와 다릅니다.'
 }
 $controller=[ordered]@{binding=@{repository=$env:GITHUB_REPOSITORY;commit=$env:GITHUB_SHA;runId=$env:GITHUB_RUN_ID;runAttempt=$env:GITHUB_RUN_ATTEMPT};
  job=$env:GITHUB_JOB;observedAt=$observed.observedAt;host=(Get-Content -LiteralPath (Join-Path $OutputDirectory 'host-architecture.json') -Raw | ConvertFrom-Json);
  tool=@{path=$observed.path;sha256=$observed.sha256;bytes=$observed.bytes;version=$version;fileVersion=$tool.VersionInfo.FileVersion;productVersion=$tool.VersionInfo.ProductVersion;
   signatureStatus='Valid';signer='Microsoft Corporation';signerSubject=$toolSignature.SignerCertificate.Subject;peMachine=$observed.peMachine;
   processId=$observed.processId;processMachine=$observed.processMachine;nativeMachine=$observed.nativeMachine;ordinaryExit=$true;helpExitCode=$observed.helpExitCode};
  signedSignature=@{status='Valid';thumbprint=$signature.SignerCertificate.Thumbprint;certificateSha256=$pending.native.certificate.sha256}}
 $controller | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'sdk-controller.json') -Encoding utf8
 # Invoke the unchanged SDK/report validator with the exact native signed input.
 & (Join-Path $PSScriptRoot 'wack.ps1') -PackagePath $copy -ExpectedPackageSha256 $pending.signedSha256 -Identity $pending.packageIdentity.Name -Version $pending.packageIdentity.Version -OutputDirectory $OutputDirectory
} finally {
 if ($trusted) { Remove-Item ('Cert:\LocalMachine\TrustedPeople\'+$trusted.Thumbprint) -Force -ErrorAction Continue }
 $certificate.Dispose()
 if ($trusted -and (Test-Path -LiteralPath ('Cert:\LocalMachine\TrustedPeople\'+$trusted.Thumbprint))) { throw 'SDK 검사에서 가져온 테스트 신뢰 인증서를 제거하지 못했습니다.' }
 if ((Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash.ToLowerInvariant() -cne $pending.signedSha256) { throw 'SDK 검사 중 정확한 서명 입력이 변경되었습니다.' }
 Assert-OpenGeulSelectedUnsignedPackage -PackageDirectory $PackageDirectory -ExpectedSha256 $pending.unsignedSha256
}
# A final install.json exists only after full required/optional WACK, successful
# native proof, input invariance and SDK trust cleanup. This helper also joins APIs.
python $helper finalize --package-directory $OriginalDirectory --native-directory $NativeDirectory --output-directory $OutputDirectory --controller (Join-Path $OutputDirectory 'sdk-controller.json')
