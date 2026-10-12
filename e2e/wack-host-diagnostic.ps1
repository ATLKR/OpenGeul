param([Parameter(Mandatory)][ValidateSet('arm-inventory-install','x64-inspect-arm')][string]$Mode)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop';$PSNativeCommandUseErrorActionPreference=$true
if($env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or $env:GITHUB_REPOSITORY -cne 'ATLKR/OpenGeul' -or $env:GITHUB_EVENT_NAME -cne 'workflow_dispatch' -or $env:GITHUB_REF -cne 'refs/heads/diagnostic/wack-host-75'){throw 'Owned hosted diagnostic workflow only'}
$event=Get-Content -LiteralPath $env:GITHUB_EVENT_PATH -Raw|ConvertFrom-Json
if($event.repository.private -ne $false -or $event.repository.id -ne 1405493151 -or $event.sender.id -ne 65988341){throw 'Exact public repository and manual actor required'}
$evidence=Join-Path (Get-Location) 'wack-host-evidence';if(Test-Path $evidence){throw 'Fresh evidence required'};New-Item -ItemType Directory $evidence|Out-Null
$work=Join-Path $env:RUNNER_TEMP ('opengeul-wack-host-'+[guid]::NewGuid().ToString('N'));New-Item -ItemType Directory $work|Out-Null
$cert=$null;$trusted=$null;$originalFile=$null;$originalSha=$null
$result=[ordered]@{mode=$Mode;diagnosticCommit=$env:GITHUB_SHA;diagnosticRun=$env:GITHUB_RUN_ID;diagnosticAttempt=$env:GITHUB_RUN_ATTEMPT;sourceCommit='f104fd4080214bc072cf39a24e73454685dd4254';sourceRun='38237687615';sourceAttempt='1';sourceQualified=$false;installedNativeReplaced=$false;storeCertified=$false;success=$false}
function Write-PublicJson($value,$name){$value|ConvertTo-Json -Depth 15|Set-Content -LiteralPath (Join-Path $evidence $name) -Encoding utf8}
function Require-MicrosoftSignature($path){$s=Get-AuthenticodeSignature -LiteralPath $path;if($s.Status -ne 'Valid' -or -not $s.SignerCertificate -or $s.SignerCertificate.Subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)'){throw 'Valid Microsoft Authenticode required'};return $s.SignerCertificate.Subject}
function Tool-Inventory {
 $roots=@();foreach($name in @('ProgramFiles(x86)','ProgramFiles','ProgramW6432')){$v=[Environment]::GetEnvironmentVariable($name,'Process');if($v){$roots+=Join-Path $v 'Windows Kits/10'}}
 foreach($key in @('HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows Kits\Installed Roots')){if(Test-Path $key){$v=Get-ItemPropertyValue -LiteralPath $key -Name KitsRoot10 -ErrorAction SilentlyContinue;if($v){$roots+=$v}}}
 $rows=@();foreach($root in @($roots|Select-Object -Unique)){$path=Join-Path $root 'App Certification Kit/appcert.exe';$found=Test-Path -LiteralPath $path -PathType Leaf;$row=[ordered]@{kitRoot=$root;path=$path;exists=$found};if($found){$f=Get-Item $path;$s=Get-AuthenticodeSignature $path;$row.bytes=$f.Length;$row.sha256=(Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant();$row.fileVersion=$f.VersionInfo.FileVersion;$row.productVersion=$f.VersionInfo.ProductVersion;$row.signatureStatus=$s.Status.ToString();$row.signer=if($s.SignerCertificate){$s.SignerCertificate.Subject}else{$null}};$rows+=$row};return $rows
}
try {
 $arch=if($Mode -eq 'arm-inventory-install'){'arm64'}else{'x64'}
 python e2e/native_architecture.py host --architecture $arch --output (Join-Path $evidence 'host-architecture.json')
 Write-PublicJson @(Tool-Inventory) 'kit-inventory-before.json'
 if($Mode -eq 'arm-inventory-install'){
  $url='https://download.microsoft.com/download/46742ab5-6592-4968-a793-129e7f3bc55a/KIT_BUNDLE_WINDOWSSDK_MEDIACREATION/winsdksetup.exe';$setup=Join-Path $work 'winsdksetup.exe';Invoke-WebRequest $url -OutFile $setup -TimeoutSec 120
  if((Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant() -cne 'b0bdbad38ae74c40ccae8cdbcf229807627fba2bc3100be28301c4ba884f755e'){throw 'Pinned official SDK26100.9457 bytes differ'}
  $signer=Require-MicrosoftSignature $setup;$v=(Get-Item $setup).VersionInfo
  Write-PublicJson @{url=$url;bytes=(Get-Item $setup).Length;sha256=(Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant();signer=$signer;fileVersion=$v.FileVersion;productVersion=$v.ProductVersion;features='OptionId.WindowsSoftwareLogoToolkit';architectureOverrides=@();conditionsModified=$false} 'sdk-installer.json'
  $p=Start-Process $setup -ArgumentList @('/quiet','/norestart','/ceip','off','/features','OptionId.WindowsSoftwareLogoToolkit','/log',('"'+(Join-Path $evidence 'sdk-install.log')+'"')) -PassThru
  if(-not $p.WaitForExit(1200000)){throw 'Ordinary SDK install did not exit in twenty minutes'};$p.Refresh();$result.sdkInstallerExitCode=$p.ExitCode;$result.sdkInstallerOrdinaryExit=$true
  if($p.ExitCode -ne 0){throw 'SDK ordinary exit nonzero; unsupported/reboot not ignored'}
  Write-PublicJson @(Tool-Inventory) 'kit-inventory-after.json'
  $tool=Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/App Certification Kit/appcert.exe';if(-not (Test-Path $tool -PathType Leaf)){throw 'Normal official feature install did not provide documented appcert path; no Arch/condition overrides'}
  Require-MicrosoftSignature $tool|Out-Null;python e2e/wack-tool-probe.py --exe $tool --out (Join-Path $evidence 'tool-probe')
  $result.success=$true;$result.scope='Ordinary signed SDK component install/tool availability only; no product WACK test'
 }else{
  $json=&gh api 'repos/ATLKR/OpenGeul/actions/artifacts/11743755197';$meta=$json|ConvertFrom-Json;$json|Set-Content (Join-Path $evidence 'source-artifact.api.json') -Encoding utf8
  if($meta.id -ne 11743755197 -or $meta.name -cne 'opengeul-windows-arm64-38237687615' -or $meta.expired -ne $false -or $meta.size_in_bytes -ne 57766062 -or $meta.digest -cne 'sha256:f966d502362c7c792ab9f2372b0794ee15d35292ffc8fc6dfd0062309a270efb' -or $meta.workflow_run.id -ne 38237687615 -or $meta.workflow_run.head_sha -cne $result.sourceCommit -or $meta.workflow_run.repository_id -ne 1405493151 -or $meta.workflow_run.head_repository_id -ne 1405493151){throw 'Exact source artifact metadata differs/expired'}
  $package=Join-Path $work 'package';gh run download 38237687615 --repo ATLKR/OpenGeul --name $meta.name --dir $package
  python e2e/prepare_payload.py $package (Join-Path $work 'verified-runtime') --architecture arm64
  $original=@(Get-ChildItem $package -Filter '*.msix');if($original.Count -ne 1){throw 'Exact original MSIX required'};$originalFile=$original[0].FullName;$originalSha=(Get-FileHash $originalFile -Algorithm SHA256).Hash.ToLowerInvariant()
  if($originalSha -cne '41f66b47f6d9b9d948b50c679f948e3e78d78dd4aaffe3d09b65656958b5361f'){throw 'Root-verified ARM MSIX bytes differ'}
  $prov=Get-Content (Join-Path $package 'provenance.json') -Raw|ConvertFrom-Json;if($prov.commit -cne $result.sourceCommit -or $prov.runId -cne $result.sourceRun -or $prov.architecture -cne 'arm64' -or $prov.windowsComponents.runAttempt -cne '1'){throw 'Source provenance differs'}
  [xml]$m=Get-Content (Join-Path $package 'AppxManifest.xml') -Raw;if($m.Package.Identity.ProcessorArchitecture -cne 'arm64'){throw 'Original manifest architecture differs'}
  $publisher=[string]$m.Package.Identity.Publisher;$identity=[string]$m.Package.Identity.Name;$version=[string]$m.Package.Identity.Version
  $cert=New-SelfSignedCertificate -Type Custom -Subject $publisher -KeyUsage DigitalSignature -KeyExportPolicy Exportable -CertStoreLocation 'Cert:\CurrentUser\My' -NotAfter (Get-Date).AddDays(1) -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3','2.5.29.19={text}')
  $password=[guid]::NewGuid().ToString('N');$secure=ConvertTo-SecureString $password -AsPlainText -Force;Export-PfxCertificate -Cert $cert -FilePath (Join-Path $work 'test.pfx') -Password $secure|Out-Null;Export-Certificate -Cert $cert -FilePath (Join-Path $work 'test.cer')|Out-Null
  $trusted=Import-Certificate -FilePath (Join-Path $work 'test.cer') -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople';$copy=Join-Path $work 'test-only-arm.msix';Copy-Item $original[0].FullName $copy
  $sdk=Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/bin';$signer=Get-ChildItem $sdk -Filter signtool.exe -Recurse|Where-Object {$_.Directory.Name -eq 'x64'}|Sort-Object FullName -Descending|Select-Object -First 1
  if(-not $signer){throw 'Stock signer absent'};Require-MicrosoftSignature $signer.FullName|Out-Null
  &$signer.FullName sign /fd SHA256 /f (Join-Path $work 'test.pfx') /p $password $copy
  &$signer.FullName verify /pa $copy
  $signed=(Get-FileHash $copy -Algorithm SHA256).Hash.ToLowerInvariant();Write-PublicJson @{originalSha256=$originalSha;signedInputSha256=$signed;identity=$identity;version=$version;architecture='arm64';testSigning=$true;certificateThumbprint=$cert.Thumbprint;packageInstalledOnX64=$false;sourceCommit=$result.sourceCommit;sourceRun=$result.sourceRun;sourceAttempt='1';nativeArmSmokeReplaced=$false} 'exact-signed-input.json'
  $tool=Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/App Certification Kit/appcert.exe';Require-MicrosoftSignature $tool|Out-Null;python e2e/wack-tool-probe.py --exe $tool --out (Join-Path $evidence 'tool-probe')
  &(Join-Path $PSScriptRoot 'wack.ps1') -PackagePath $copy -ExpectedPackageSha256 $signed -Identity $identity -Version $version -OutputDirectory (Join-Path $evidence 'wack')
  if((Get-FileHash $original[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant() -cne $originalSha){throw 'Unsigned original changed'}
  $result.success=$true;$result.scope='Stock x64 WACK exact test-signed ARM package-input; native ARM installation/MCP remain separate mandatory proof'
 }
}catch{$result.reason=$_.Exception.Message;throw}
finally{if($originalFile -and (Test-Path $originalFile)){$result.originalUnsignedPackageUnchanged=((Get-FileHash $originalFile -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $originalSha)};Write-PublicJson $result 'diagnostic-result.json';if($trusted){Remove-Item ('Cert:\LocalMachine\TrustedPeople\'+$trusted.Thumbprint) -Force -ErrorAction Continue};if($cert){Remove-Item ('Cert:\CurrentUser\My\'+$cert.Thumbprint) -Force -ErrorAction Continue};Remove-Item $work -Recurse -Force -ErrorAction Continue}
