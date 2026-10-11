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
$cert=$null;$trusted=$null;$installed=$null;$launched=$null;$addedFrameworks=@();$frameworkEvidence=@()
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
 foreach ($dependency in $manifest.SelectNodes("//*[local-name()='Dependencies']/*[local-name()='PackageDependency']")) {
  $name=$dependency.GetAttribute('Name');$minimum=[version]$dependency.GetAttribute('MinVersion');$requiredPublisher=$dependency.GetAttribute('Publisher')
  if ($name -ne 'Microsoft.VCLibs.140.00.UWPDesktop' -or $requiredPublisher -ne 'CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US') { throw 'Unreviewed package framework dependency.' }
  $framework=Get-AppxPackage -Name $name | Where-Object { $_.Publisher -eq $requiredPublisher -and [version]$_.Version -ge $minimum -and $_.Architecture -eq 'X64' } | Select-Object -First 1
  if (-not $framework) {
   $download=Join-Path $work 'Microsoft.VCLibs.x64.14.00.Desktop.appx'
   $url='https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx'
   Invoke-WebRequest $url -OutFile $download
   & $signer.FullName verify /pa $download
   $archive=[System.IO.Compression.ZipFile]::OpenRead($download)
   try {
    $reader=[System.IO.StreamReader]::new($archive.GetEntry('AppxManifest.xml').Open())
    try { [xml]$frameworkManifest=$reader.ReadToEnd() } finally { $reader.Dispose() }
   } finally { $archive.Dispose() }
   $frameworkIdentity=$frameworkManifest.Package.Identity
   if ($frameworkIdentity.Name -ne $name -or $frameworkIdentity.Publisher -ne $requiredPublisher -or $frameworkIdentity.ProcessorArchitecture -ne 'x64' -or [version]$frameworkIdentity.Version -lt $minimum) { throw 'Downloaded VCLibs framework identity/version does not match the declared dependency.' }
   Add-AppxPackage -Path $download -ErrorAction Stop
   $framework=Get-AppxPackage -Name $name | Where-Object { $_.Publisher -eq $requiredPublisher -and [version]$_.Version -ge $minimum -and $_.Architecture -eq 'X64' } | Select-Object -First 1
   if (-not $framework) { throw 'VCLibs framework registration failed.' }
   $addedFrameworks+=$framework.PackageFullName
   $frameworkEvidence+=@{packageFullName=$framework.PackageFullName;source=$url;sha256=(Get-FileHash $download -Algorithm SHA256).Hash}
  } else { $frameworkEvidence+=@{packageFullName=$framework.PackageFullName;source='already registered'} }
 }
 $frameworkEvidence | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $OutputDirectory 'frameworks.json') -Encoding utf8
 Add-AppxPackage -Path $copy -ErrorAction Stop
 $installed=Get-AppxPackage -Name $identity
 if (-not $installed -or $installed.Publisher -ne $publisher) { throw 'Installed identity does not match.' }
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
 [DllImport("user32.dll", ExactSpelling=true)]
 public static extern IntPtr GetWindowDpiAwarenessContext(IntPtr window);
 [DllImport("user32.dll", ExactSpelling=true)]
 public static extern int GetAwarenessFromDpiAwarenessContext(IntPtr context);
 [DllImport("user32.dll", ExactSpelling=true)]
 public static extern bool AreDpiAwarenessContextsEqual(IntPtr first, IntPtr second);
 [DllImport("user32.dll", ExactSpelling=true)]
 public static extern uint GetDpiForWindow(IntPtr window);
 [DllImport("shcore.dll", ExactSpelling=true)]
 public static extern int GetProcessDpiAwareness(IntPtr process, out int awareness);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true, ExactSpelling=true)]
 static extern IntPtr LoadLibraryExW(string file, IntPtr reserved, uint flags);
 [DllImport("kernel32.dll", SetLastError=true, ExactSpelling=true)]
 static extern bool FreeLibrary(IntPtr module);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true, ExactSpelling=true)]
 static extern IntPtr FindResourceW(IntPtr module, IntPtr name, IntPtr type);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true, ExactSpelling=true)]
 static extern IntPtr FindResourceExW(IntPtr module, IntPtr type, IntPtr name, ushort language);
 [DllImport("kernel32.dll", SetLastError=true, ExactSpelling=true)]
 static extern uint SizeofResource(IntPtr module, IntPtr resource);
 [DllImport("kernel32.dll", SetLastError=true, ExactSpelling=true)]
 static extern IntPtr LoadResource(IntPtr module, IntPtr resource);
 [DllImport("kernel32.dll", ExactSpelling=true)]
 static extern IntPtr LockResource(IntPtr resource);
 public static byte[] ReadManifest(string file, ushort language, bool defaultLookup) {
  var module=LoadLibraryExW(file,IntPtr.Zero,0x22);
  if(module==IntPtr.Zero) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
  try {
   var resource=defaultLookup ? FindResourceW(module,(IntPtr)1,(IntPtr)24) : FindResourceExW(module,(IntPtr)24,(IntPtr)1,language);
   if(resource==IntPtr.Zero) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
   var size=SizeofResource(module,resource);
   if(size==0) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
   if(size>65536) throw new InvalidOperationException("Unexpected bounded manifest size");
   var loaded=LoadResource(module,resource);
   if(loaded==IntPtr.Zero) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
   var address=LockResource(loaded);
   if(address==IntPtr.Zero) throw new InvalidOperationException("LockResource returned NULL");
   var bytes=new byte[size]; Marshal.Copy(address,bytes,0,(int)size); return bytes;
  } finally { FreeLibrary(module); }
 }
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
 @{success=$true;processId=$launched.Id;packageFullName=$processIdentity.ToString();executable=$launched.Path;windowTitle=$launched.MainWindowTitle} | ConvertTo-Json | Set-Content (Join-Path $OutputDirectory 'installed-launch.json') -Encoding utf8
 $context=[OpenGeulPackageIdentity]::GetWindowDpiAwarenessContext($launched.MainWindowHandle)
 $windowAwareness=[OpenGeulPackageIdentity]::GetAwarenessFromDpiAwarenessContext($context)
 $processAwareness=[int](-1)
 $hresult=[OpenGeulPackageIdentity]::GetProcessDpiAwareness($launched.Handle,[ref]$processAwareness)
 $os=Get-CimInstance Win32_OperatingSystem
 @{scope='read-only awareness query of the verified installed editor; no DPI setters or gate exemption';packageFullName=$processIdentity.ToString();editorSha256=(Get-FileHash $executable -Algorithm SHA256).Hash;processId=$launched.Id;runnerSessionId=(Get-Process -Id $PID).SessionId;editorSessionId=$launched.SessionId;windowContextValid=($context -ne [IntPtr]::Zero);windowAwareness=$windowAwareness;perMonitorV2=[OpenGeulPackageIdentity]::AreDpiAwarenessContextsEqual($context,[IntPtr](-4));windowDpi=[OpenGeulPackageIdentity]::GetDpiForWindow($launched.MainWindowHandle);processAwarenessHresult=$hresult;processAwareness=$processAwareness;osCaption=$os.Caption;osBuild=$os.BuildNumber} | ConvertTo-Json | Set-Content (Join-Path $OutputDirectory 'dpi-context.json') -Encoding utf8
 $resourceProbes=@()
 foreach ($lookup in @(@{name='default';language=0;default=$true},@{name='requested-lang0';language=0;default=$false},@{name='en-US';language=1033;default=$false},@{name='ko-KR';language=1042;default=$false})) {
  try {
   [byte[]]$resource=[OpenGeulPackageIdentity]::ReadManifest($executable,[uint16]$lookup.language,[bool]$lookup.default)
   $resourcePath=Join-Path $OutputDirectory ("manifest-resource-"+$lookup.name+'.xml')
   [System.IO.File]::WriteAllBytes($resourcePath,$resource)
   [xml]$doc=[System.Text.UTF8Encoding]::new($false,$true).GetString($resource)
   $resourceProbes+=@{lookup=$lookup.name;success=$true;bytes=$resource.Length;sha256=(Get-FileHash $resourcePath -Algorithm SHA256).Hash;dpiAware=$doc.SelectSingleNode("//*[local-name()='dpiAware' and namespace-uri()='http://schemas.microsoft.com/SMI/2005/WindowsSettings']").InnerText;dpiAwareness=$doc.SelectSingleNode("//*[local-name()='dpiAwareness' and namespace-uri()='http://schemas.microsoft.com/SMI/2016/WindowsSettings']").InnerText}
  } catch {
   $failure=$_.Exception.GetBaseException()
   $resourceProbes+=@{lookup=$lookup.name;success=$false;errorType=$failure.GetType().FullName;win32Error=if($failure -is [System.ComponentModel.Win32Exception]){$failure.NativeErrorCode}else{$null}}
  }
 }
 $resourceProbes | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $OutputDirectory 'manifest-resource-probes.json') -Encoding utf8
 $cli=Join-Path $installed.InstallLocation 'Tools/rhwp.exe'
 $cliResult=Join-Path (Resolve-Path $OutputDirectory).Path 'installed-cli.json'
 if (Test-Path $cliResult) { throw 'Refusing to reuse an installed CLI result.' }
 $probeArgs="-NoProfile -File `"$(Join-Path $PSScriptRoot 'installed-cli.ps1')`" -CliPath `"$cli`" -PackageFullName `"$($installed.PackageFullName)`" -OutputDirectory `"$((Resolve-Path $OutputDirectory).Path)`""
 Invoke-CommandInDesktopPackage -PackageFamilyName $installed.PackageFamilyName -AppId OpenGeul -Command (Get-Process -Id $PID).Path -Args $probeArgs -PreventBreakaway
 $deadline=(Get-Date).AddSeconds(60)
 while (-not (Test-Path $cliResult) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
 if (-not (Test-Path $cliResult)) { throw 'Installed CLI package-context probe did not complete within 60 seconds.' }
 $cliEvidence=Get-Content $cliResult -Raw | ConvertFrom-Json
 if (-not $cliEvidence.success -or $cliEvidence.packageFullName -ne $installed.PackageFullName) { throw 'Installed CLI package-context probe failed; see installed-cli.json.' }
 Stop-Process -Id $launched.Id -Force
 $launched=$null
 & (Join-Path $PSScriptRoot 'wack-binaryinfo-hosts.ps1') -ExecutablePath $executable -OutputDirectory $OutputDirectory -Label installed
 & (Join-Path $PSScriptRoot 'wack.ps1') -PackageFullName $installed.PackageFullName -Identity $identity -Version ([string]$manifest.Package.Identity.Version) -OutputDirectory $OutputDirectory
 @{
  success=$true; packageFullName=$installed.PackageFullName; publisher=$publisher;
  fileTypes=$types; originalSha256=$before;
  scope='test-only signing, AppX installation, package-identity activation, installed CLI, registered file types and uninstall; WACK status is reported separately in wack.json; not Store certification or real-printer/IME testing'
 } | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $OutputDirectory 'install.json') -Encoding utf8
} finally {
 if ($launched -and -not $launched.HasExited) { Stop-Process -Id $launched.Id -Force -ErrorAction Continue }
 if ($installed) { Get-Process -Name OpenGeul -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $installed.InstallLocation 'OpenGeul.exe') } | Stop-Process -Force -ErrorAction Continue }
 if ($installed) { Get-Process -Name rhwp -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $installed.InstallLocation 'Tools/rhwp.exe') } | Stop-Process -Force -ErrorAction Continue }
 if ($installed) { Remove-AppxPackage -Package $installed.PackageFullName -ErrorAction Continue }
 foreach ($framework in $addedFrameworks) { Remove-AppxPackage -Package $framework -ErrorAction Continue }
 if ($trusted) { Remove-Item ("Cert:\LocalMachine\TrustedPeople\"+$trusted.Thumbprint) -Force -ErrorAction Continue }
 if ($cert) { Remove-Item ("Cert:\CurrentUser\My\"+$cert.Thumbprint) -Force -ErrorAction Continue }
 Remove-Item $work -Recurse -Force -ErrorAction Continue
 if ((Get-FileHash $original[0].FullName -Algorithm SHA256).Hash -ne $before) { throw 'Unsigned release artifact was modified by install testing.' }
}
if (Get-AppxPackage -Name $identity) { throw 'Test package was not uninstalled.' }
