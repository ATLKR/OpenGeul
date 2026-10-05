# A short-lived test certificate signs a COPY on this disposable runner only.
# No signing key, certificate or signed copy is published or used for production.
param([Parameter(Mandatory)][string]$PackageDirectory,[Parameter(Mandatory)][string]$OutputDirectory)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$true
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Install smoke is restricted to disposable GitHub Actions runners.' }
$original=@(Get-ChildItem $PackageDirectory -Filter '*.msix')
if ($original.Count -ne 1) { throw 'Exactly one package required.' }
$before=(Get-FileHash $original[0].FullName -Algorithm SHA256).Hash
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
$work=Join-Path $env:RUNNER_TEMP ("opengeul-test-sign-"+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $work | Out-Null
$cert=$null;$trusted=$null;$installed=$null
try {
 [xml]$manifest=Get-Content (Join-Path $PackageDirectory 'AppxManifest.xml') -Raw
 $publisher=[string]$manifest.Package.Identity.Publisher
 $identity=[string]$manifest.Package.Identity.Name
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
 Add-AppxPackage -Path $copy -ErrorAction Stop
 $installed=Get-AppxPackage -Name $identity
 if (-not $installed -or $installed.Publisher -ne $publisher) { throw 'Installed identity does not match.' }
 $registered=Get-AppxPackageManifest -Package $installed.PackageFullName
 $types=@($registered.SelectNodes("//*[local-name()='FileTypeAssociation']/*[local-name()='SupportedFileTypes']/*[local-name()='FileType']") | ForEach-Object { $_.InnerText })
 if ('.hwp' -notin $types -or '.hwpx' -notin $types) { throw 'Registered file associations missing.' }
 if (-not (Test-Path (Join-Path $installed.InstallLocation 'OpenGeul.exe'))) { throw 'Registered executable is missing.' }
 @{
  success=$true; packageFullName=$installed.PackageFullName; publisher=$publisher;
  fileTypes=$types; originalSha256=$before;
  scope='test-only signing, AppX installation, registered identity and file types, uninstall; not Store certification or real-printer/IME testing'
 } | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $OutputDirectory 'install.json') -Encoding utf8
} finally {
 if ($installed) { Remove-AppxPackage -Package $installed.PackageFullName -ErrorAction Continue }
 if ($trusted) { Remove-Item ("Cert:\LocalMachine\TrustedPeople\"+$trusted.Thumbprint) -Force -ErrorAction Continue }
 if ($cert) { Remove-Item ("Cert:\CurrentUser\My\"+$cert.Thumbprint) -Force -ErrorAction Continue }
 Remove-Item $work -Recurse -Force -ErrorAction Continue
 if ((Get-FileHash $original[0].FullName -Algorithm SHA256).Hash -ne $before) { throw 'Unsigned release artifact was modified by install testing.' }
}
if (Get-AppxPackage -Name $identity) { throw 'Test package was not uninstalled.' }
