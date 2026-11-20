# Only the original HWP worker and one direct acquisition child share this clock.
# This is preparation, never native input/readiness or Store qualification.
$script:OpenGeulFodHelperSha256='50ee6a3939f5fb01507fbc405196d63e07fa5f846a022e9f35e847fd40b9ab35'
$script:OpenGeulFodWrapperSha256='08fa5ffa06dff724ae17ec2bac691750bb5a66e35a82cf7ed0c74c05d7869d1c'
function Get-OpenGeulFodSha([string]$Path) {
    $stream=$null;$hash=$null
    try {$stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);$hash=[Security.Cryptography.SHA256]::Create();return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}
    finally {if($null -ne $hash){$hash.Dispose()};if($null -ne $stream){$stream.Dispose()}}
}
function Get-OpenGeulFodTextSha([string]$Text) {
    $hash=[Security.Cryptography.SHA256]::Create()
    try {return [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::ASCII.GetBytes($Text))).Replace('-','').ToLowerInvariant()} finally {$hash.Dispose()}
}
function Get-OpenGeulFodWorkEnd([double]$LaunchElapsed) {
    if([double]::IsNaN($LaunchElapsed) -or [double]::IsInfinity($LaunchElapsed) -or $LaunchElapsed -lt 0){throw 'Invalid FoD clock.'}
    return [Math]::Min($LaunchElapsed+240,590)
}
function Get-OpenGeulFodWaitMs([double]$Elapsed,[double]$End) {
    if([double]::IsNaN($Elapsed) -or [double]::IsInfinity($Elapsed) -or $Elapsed -lt 0 -or [double]::IsNaN($End) -or [double]::IsInfinity($End) -or $End -lt 0){throw 'Invalid FoD clock.'}
    return [int][Math]::Max(0,[Math]::Min(15000,[Math]::Floor(($End-$Elapsed)*1000)))
}
function Assert-OpenGeulFodBinding($Binding) {
    if($Binding.sourceCommit -isnot [string] -or $Binding.sourceCommit -cnotmatch '\A[0-9a-f]{40}\z' -or $Binding.sourceRun -isnot [string] -or $Binding.sourceRun -cnotmatch '\A[1-9][0-9]{0,19}\z' -or $Binding.runAttempt -cne '1' -or $Binding.repository -cne 'ATLKR/OpenGeul' -or $Binding.job -cne 'native-e2e' -or $Binding.architecture -cne 'x64'){throw 'Invalid FoD Source binding.'}
}
function Test-OpenGeulFodLane($Binding,[int]$Native,[int]$Controller,[string]$Build,[string]$Installation,[string]$Before) {
    return ($Binding.job -ceq 'native-e2e' -and $Binding.architecture -ceq 'x64' -and $Native -eq 34404 -and $Controller -eq 0 -and $Build -ceq '26100' -and @('Server','Server Core') -ccontains $Installation -and $Before -ceq 'NotPresent')
}
function Get-OpenGeulFodIdentityAscii($Binding,[int]$WorkerPid,[long]$WorkerCreated,[int]$InstallationCode) {
    Assert-OpenGeulFodBinding $Binding
    if($WorkerPid -le 0 -or $WorkerCreated -le 0 -or $InstallationCode -notin @(1,2)){throw 'Invalid FoD worker identity.'}
    return '"binding":{"sourceCommit":"'+$Binding.sourceCommit+'","sourceRun":"'+$Binding.sourceRun+'","runAttempt":"1","repository":"ATLKR/OpenGeul","job":"native-e2e","architecture":"x64"},"workerPid":'+$WorkerPid.ToString([Globalization.CultureInfo]::InvariantCulture)+',"workerCreationFileTime":'+$WorkerCreated.ToString([Globalization.CultureInfo]::InvariantCulture)+',"generation":1,"nativeMachine":34404,"processMachine":0,"build":"26100","installationTypeCode":'+$InstallationCode+',"capabilityNameCode":1,"capabilityStateCode":0'
}
function New-OpenGeulFodRequest($Binding,[int]$WorkerPid,[long]$WorkerCreated,[int]$InstallationCode) {
    return '{"schemaVersion":1,"kindCode":1,'+(Get-OpenGeulFodIdentityAscii $Binding $WorkerPid $WorkerCreated $InstallationCode)+'}'
}
function Assert-OpenGeulFodAscii([string]$Text) {
    if($Text.Length -gt 4096 -or $Text -cmatch '[^\x00-\x7f]'){throw 'Invalid finite FoD protocol.'}
}
function Read-OpenGeulFodRequest([string]$Text,$Binding,[int]$WorkerPid,[long]$WorkerCreated) {
    Assert-OpenGeulFodAscii $Text;Assert-OpenGeulFodBinding $Binding
    $pattern='\A\{"schemaVersion":1,"kindCode":1,"binding":\{"sourceCommit":"(?<source>[0-9a-f]{40})","sourceRun":"(?<run>[1-9][0-9]{0,19})","runAttempt":"1","repository":"ATLKR/OpenGeul","job":"native-e2e","architecture":"x64"\},"workerPid":(?<pid>[1-9][0-9]{0,9}),"workerCreationFileTime":(?<created>[1-9][0-9]{0,18}),"generation":1,"nativeMachine":34404,"processMachine":0,"build":"26100","installationTypeCode":(?<install>[12]),"capabilityNameCode":1,"capabilityStateCode":0\}\z'
    $m=[regex]::Match($Text,$pattern,[Text.RegularExpressions.RegexOptions]::CultureInvariant,[TimeSpan]::FromMilliseconds(100))
    [int]$parsedPid=0;[long]$parsedCreated=0
    if(-not $m.Success -or -not [int]::TryParse($m.Groups['pid'].Value,[Globalization.NumberStyles]::None,[Globalization.CultureInfo]::InvariantCulture,[ref]$parsedPid) -or -not [long]::TryParse($m.Groups['created'].Value,[Globalization.NumberStyles]::None,[Globalization.CultureInfo]::InvariantCulture,[ref]$parsedCreated)){throw 'Invalid finite FoD request.'}
    if($m.Groups['source'].Value -cne $Binding.sourceCommit -or $m.Groups['run'].Value -cne $Binding.sourceRun -or $parsedPid -ne $WorkerPid -or $parsedCreated -ne $WorkerCreated){throw 'Stale FoD request.'}
    return [pscustomobject]@{binding=$Binding;workerPid=$parsedPid;workerCreationFileTime=$parsedCreated;installationTypeCode=[int]::Parse($m.Groups['install'].Value,[Globalization.CultureInfo]::InvariantCulture);requestSha256=(Get-OpenGeulFodTextSha $Text)}
}
function Get-OpenGeulFodReadyPrefix($Request) {
    return '{"schemaVersion":1,"kindCode":2,"ready":1,'+(Get-OpenGeulFodIdentityAscii $Request.binding $Request.workerPid $Request.workerCreationFileTime $Request.installationTypeCode)+',"requestSha256":"'+$Request.requestSha256+'","helperCodeSha256":"'+$script:OpenGeulFodHelperSha256+'","wrapperCodeSha256":"'+$script:OpenGeulFodWrapperSha256+'",'
}
function New-OpenGeulFodReady($Request,$Helper,[string]$PythonSha,[string]$ReceiptSha) {
    if($PythonSha -cnotmatch '\A[0-9a-f]{64}\z' -or $ReceiptSha -cnotmatch '\A[0-9a-f]{64}\z' -or -not $Helper.IdentityKnown -or $Helper.Pid -le 0 -or $Helper.Created -le 0 -or $Helper.Retired -ne $true -or $Helper.ExitCode -ne 0){throw 'Invalid FoD helper receipt.'}
    return (Get-OpenGeulFodReadyPrefix $Request)+'"pythonExecutableCode":1,"pythonExecutableSha256":"'+$PythonSha+'","helperPid":'+$Helper.Pid+',"helperCreationFileTime":'+$Helper.Created+',"helperExitCode":0,"helperRetired":true,"ownedRootId":"'+$Request.requestSha256+'","ownedRootCreatedExclusive":true,"ownedRootNoReparse":true,"ownedRootOutsideCheckoutAndUploads":true,"acquisitionReceiptSha256":"'+$ReceiptSha+'","cabCount":9,"cabBytes":21154053,"allNinePinsMatched":true,"diagnosticOnly":1,"acceptanceEligible":0,"productInputVerified":0,"sourceQualified":0,"storeQualified":0}'
}
function Read-OpenGeulFodReady([string]$Text,$Request) {
    Assert-OpenGeulFodAscii $Text;$prefix=Get-OpenGeulFodReadyPrefix $Request
    if(-not $Text.StartsWith($prefix,[StringComparison]::Ordinal)){throw 'Stale FoD ready.'}
    $pattern='\A"pythonExecutableCode":1,"pythonExecutableSha256":"(?<python>[0-9a-f]{64})","helperPid":(?<pid>[1-9][0-9]{0,9}),"helperCreationFileTime":(?<created>[1-9][0-9]{0,18}),"helperExitCode":0,"helperRetired":true,"ownedRootId":"'+$Request.requestSha256+'","ownedRootCreatedExclusive":true,"ownedRootNoReparse":true,"ownedRootOutsideCheckoutAndUploads":true,"acquisitionReceiptSha256":"(?<receipt>[0-9a-f]{64})","cabCount":9,"cabBytes":21154053,"allNinePinsMatched":true,"diagnosticOnly":1,"acceptanceEligible":0,"productInputVerified":0,"sourceQualified":0,"storeQualified":0\}\z'
    $m=[regex]::Match($Text.Substring($prefix.Length),$pattern,[Text.RegularExpressions.RegexOptions]::CultureInvariant,[TimeSpan]::FromMilliseconds(100))
    [int]$pidValue=0;[long]$createdValue=0
    if(-not $m.Success -or -not [int]::TryParse($m.Groups['pid'].Value,[Globalization.NumberStyles]::None,[Globalization.CultureInfo]::InvariantCulture,[ref]$pidValue) -or -not [long]::TryParse($m.Groups['created'].Value,[Globalization.NumberStyles]::None,[Globalization.CultureInfo]::InvariantCulture,[ref]$createdValue) -or $pidValue -eq $Request.workerPid){throw 'Invalid finite FoD ready.'}
    return [pscustomobject]@{helperPid=$pidValue;helperCreationFileTime=$createdValue;helperExitCode=0;helperRetired=$true;pythonExecutableSha256=$m.Groups['python'].Value;acquisitionReceiptSha256=$m.Groups['receipt'].Value;cabCount=9;cabBytes=21154053;acceptanceEligible=0;sourceQualified=0}
}
function Publish-OpenGeulFodAscii([string]$Path,[string]$Text) {
    Assert-OpenGeulFodAscii $Text
    if([IO.File]::Exists($Path)){throw 'Duplicate FoD protocol publication.'}
    $temp=$Path+'.tmp';$stream=$null
    try {$stream=[IO.File]::Open($temp,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);$bytes=[Text.Encoding]::ASCII.GetBytes($Text);$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)} finally {if($null -ne $stream){$stream.Dispose()}}
    [IO.File]::Move($temp,$Path)
}
function Read-OpenGeulFodAscii([string]$Path) {
    Assert-OpenGeulFodNoReparse $Path;$stream=$null
    try {$stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);if($stream.Length -le 0 -or $stream.Length -gt 4096){throw 'Invalid FoD protocol file.'};$bytes=[byte[]]::new(4097);$count=$stream.Read($bytes,0,4097);if($count -ne $stream.Length -or $count -gt 4096 -or @($bytes[0..($count-1)]|Where-Object {$_ -gt 127}).Count -ne 0){throw 'Invalid FoD protocol bytes.'};Assert-OpenGeulFodNoReparse $Path;return [Text.Encoding]::ASCII.GetString($bytes,0,$count)}
    finally {if($null -ne $stream){$stream.Dispose()}}
}
function Assert-OpenGeulFodReadyGate($Request,$Worker,$Helper,[double]$Elapsed,[double]$WorkEnd) {
    if((Get-OpenGeulFodWaitMs $Elapsed $WorkEnd) -le 0 -or $Elapsed -ge 590 -or -not $Worker.IdentityKnown -or $Worker.Pid -ne $Request.workerPid -or $Worker.Created -ne $Request.workerCreationFileTime -or $Worker.Handle -eq [IntPtr]::Zero -or -not $Helper.IdentityKnown -or $Helper.Retired -ne $true -or $Helper.ExitCode -ne 0 -or $Helper.Handle -eq [IntPtr]::Zero){throw 'FoD ready gate unavailable.'}
    $Worker.Process.Refresh()
    if($Worker.Process.HasExited){throw 'FoD worker exited before handoff.'}
}
function Get-OpenGeulFodProcessCreation($Process) {return $Process.StartTime.ToUniversalTime().ToFileTimeUtc()}
function Start-OpenGeulFodOwnedProcess([Diagnostics.ProcessStartInfo]$Info,[ref]$Slot,$Clock,[double]$WorkEnd) {
    if($null -eq $Clock -or (Get-OpenGeulFodWaitMs $Clock.Elapsed.TotalSeconds $WorkEnd) -le 0){throw 'FoD child launch budget exhausted.'}
    $Slot.Value=[pscustomobject]@{Process=[Diagnostics.Process]::new();Handle=[IntPtr]::Zero;Pid=$null;Created=$null;IdentityKnown=$false;Retired=$null;ExitCode=$null}
    $p=$Slot.Value.Process;$p.StartInfo=$Info
    if(-not $p.Start()){throw 'FoD process start unavailable.'}
    # Close unused read ends immediately; a controlled wrapper owns NUL output.
    try {if($Info.RedirectStandardOutput){$p.StandardOutput.Dispose()};if($Info.RedirectStandardError){$p.StandardError.Dispose()};if($Info.RedirectStandardInput){$p.StandardInput.Dispose()}}
    finally {$Slot.Value.Handle=$p.Handle}
    $Slot.Value.Pid=[int]$p.Id;$Slot.Value.Created=[long](Get-OpenGeulFodProcessCreation $p)
    if($Slot.Value.Pid -le 0 -or $Slot.Value.Created -le 0){throw 'FoD process identity unavailable.'}
    $Slot.Value.IdentityKnown=$true
}
function Update-OpenGeulFodRetirement($State) {
    if($null -ne $State -and $State.Handle -ne [IntPtr]::Zero -and $State.Process.WaitForExit(0)){$State.Retired=$true;$State.ExitCode=[int]$State.Process.ExitCode;return $true}
    return $false
}
function Stop-OpenGeulFodChildren([object[]]$States,$Clock) {
    $cleanupEnd=[Math]::Min($Clock.Elapsed.TotalSeconds+10,600)
    # Stop both before waiting for either. There is only one shared grace period.
    foreach($s in $States){if($null -eq $s){continue};try {if($s.Handle -ne [IntPtr]::Zero -and -not $s.Process.HasExited){$s.Process.Kill()}} catch { }}
    foreach($s in $States){if($null -eq $s){continue};try {if($s.Handle -eq [IntPtr]::Zero){continue};$remaining=Get-OpenGeulFodWaitMs $Clock.Elapsed.TotalSeconds $cleanupEnd;if($remaining -gt 0 -and $s.Process.WaitForExit($remaining) -and $Clock.Elapsed.TotalSeconds -le $cleanupEnd){$s.Retired=$true;$s.ExitCode=[int]$s.Process.ExitCode}} catch { }}
}
function Initialize-OpenGeulFodNative {
    if(-not ('OpenGeulFodNative' -as [type])){
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class OpenGeulFodNative {
 [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)]
 [return:MarshalAs(UnmanagedType.Bool)] public static extern bool CreateDirectoryW(string name,IntPtr security);
 [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)] public static extern uint GetWindowsDirectoryW(StringBuilder text,uint size);
 [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)] public static extern uint GetSystemDirectoryW(StringBuilder text,uint size);
}
'@
    }
}
function Assert-OpenGeulFodNoReparse([string]$Path) {
    $current=[IO.Path]::GetFullPath($Path)
    while($current){if(([IO.File]::GetAttributes($current) -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'FoD private path has a reparse point.'};$current=[IO.Path]::GetDirectoryName($current)}
}
function Get-OpenGeulFodRunnerTemp([string]$Repo,[string]$Out) {
    $root=[IO.Path]::GetFullPath([Environment]::GetEnvironmentVariable('RUNNER_TEMP'))
    Assert-OpenGeulFodNoReparse $root
    foreach($excluded in @($Repo,$Out)){if($root.Equals($excluded,[StringComparison]::OrdinalIgnoreCase) -or $root.StartsWith($excluded+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'FoD private root overlaps published Source evidence.'}}
    return $root
}
function New-OpenGeulFodDirectory([string]$Path) {
    Assert-OpenGeulFodNoReparse ([IO.Path]::GetDirectoryName($Path))
    # The PS5.1 worker reuses its original already-compiled native host type;
    # do not launch a second framework compiler in the worker.
    if('OpenGeulKoreanSetupHost' -as [type]){$created=[OpenGeulKoreanSetupHost]::CreateDirectoryW($Path,[IntPtr]::Zero)}
    else {Initialize-OpenGeulFodNative;$created=[OpenGeulFodNative]::CreateDirectoryW($Path,[IntPtr]::Zero)}
    if(-not $created){throw 'FoD private root was not exclusively created.'}
    Assert-OpenGeulFodNoReparse $Path
    return $Path
}
function Get-OpenGeulFodPackages {
    return @'
[{"relativePath":"LanguagesAndOptionalFeatures/Microsoft-Windows-LanguageFeatures-Fonts-Kore-Package~31bf3856ad364e35~amd64~~.cab","start":1431003136,"bytes":9748860,"sha256":"d6cf56321dde503390a3f448b090b6dec70f6a9270573b51b376c092a3314f34"},{"relativePath":"LanguagesAndOptionalFeatures/Microsoft-Windows-LanguageFeatures-Basic-ko-kr-Package~31bf3856ad364e35~amd64~~.cab","start":805877760,"bytes":9744372,"sha256":"0c66033dfc692605c7887cd6ad3cf02366e5e0dcf1f130a81c4a19b174e1dfd2"},{"relativePath":"LanguagesAndOptionalFeatures/Microsoft-Windows-FodMetadataServicing-Server-Metadata-Package.cab","start":258222080,"bytes":460849,"sha256":"25d2b8449d77b0f2f395ca3e0bfd00eba888301cd8eeaea9100880be71ff51c4"},{"relativePath":"LanguagesAndOptionalFeatures/Microsoft-Windows-FodMetadataServicing-Server-CompDB-Package.cab","start":258050048,"bytes":171839,"sha256":"8aa109fd5a7112ca78114a46b526aad88301b21a3ffc0a59ccb1b04f74f99c7a"},{"relativePath":"LanguagesAndOptionalFeatures/FoDMetadata_Client.cab","start":11231232,"bytes":510772,"sha256":"b825461369a531e76f3dda84840ec457d5f8062afd84381dd40938f69a60305b"},{"relativePath":"LanguagesAndOptionalFeatures/metadata/ServerTargetCompDB_FOD_Neutral.xml.cab","start":6193278976,"bytes":47763,"sha256":"057bcf0ac6d870ba9fca2b60aa40e78c901e4a3ffafea5b7b567c06d89bf632e"},{"relativePath":"LanguagesAndOptionalFeatures/metadata/ServerTargetCompDB_FOD_Metadata_Neutral.xml.cab","start":6192836608,"bytes":441350,"sha256":"37a9f5761b2c17e2abc60706a74d6422620c17264e8be44025689814fb02d6ef"},{"relativePath":"LanguagesAndOptionalFeatures/metadata/ServerTargetCompDBForISO_ko-KR.xml.cab","start":6192582656,"bytes":10573,"sha256":"7fabab57ea8eaddb593b63178c9422fa6a2c129d428304af40e3e125c230dc83"},{"relativePath":"LanguagesAndOptionalFeatures/metadata/ServerTargetCompDBForISO_FOD_ko-KR.xml.cab","start":6191998976,"bytes":17675,"sha256":"ebfe30e2fab9c5c1985ce69a08d59684446ddf29c5d3e4a41a79c64264cbde50"}]
'@ | ConvertFrom-Json
}
function Assert-OpenGeulFodSourcePins([string]$Repo) {
    if((Get-OpenGeulFodSha (Join-Path $Repo 'suite/scripts/korean_fod_source.py')) -cne $script:OpenGeulFodHelperSha256 -or (Get-OpenGeulFodSha (Join-Path $Repo 'scripts/korean_fod_acquire_silent.py')) -cne $script:OpenGeulFodWrapperSha256){throw 'FoD acquisition source pin mismatch.'}
    $workflowPins=@'
[{"file":".github/workflows/msix.yml","sha256":"a63da0dfe53dd8c8067aa87db49b3586d433a9a13683c32b83e038fb35a04820"},{"file":".github/workflows/office-native31-desktop-control.yml","sha256":"34ccd2f4584302db1329e4343569bafd963a49c8fa606a7646de4090a7341395"},{"file":".github/workflows/office-native31-privacy-prepare.yml","sha256":"d979a5bf67a97f3b1af9fc91669b1324ec500a079c9fbe8945413b27fb9f022f"}]
'@ | ConvertFrom-Json
    foreach($pin in $workflowPins){if((Get-OpenGeulFodSha (Join-Path $Repo $pin.file)) -cne $pin.sha256){throw 'FoD reviewed upload scope changed.'}}
}
function Assert-OpenGeulFodAcquisition([string]$Source) {
    Assert-OpenGeulFodNoReparse $Source;$path=Join-Path $Source 'source-acquisition.json';$info=[IO.FileInfo]::new($path)
    if(-not $info.Exists -or $info.Length -le 0 -or $info.Length -gt 32768){throw 'FoD acquisition receipt is unavailable.'}
    $record=[Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($path)) | ConvertFrom-Json
    $packages=@(Get-OpenGeulFodPackages)
    if($record.formatVersion -ne 1 -or $record.success -isnot [bool] -or -not $record.success -or $record.productInputVerified -ne $false -or $record.storeQualified -ne $false -or @($record.packages).Count -ne 9 -or -not ([IO.Path]::GetFullPath($record.sourceDirectory)).Equals((Join-Path $Source 'LanguagesAndOptionalFeatures'),[StringComparison]::OrdinalIgnoreCase)){throw 'FoD acquisition receipt rejected.'}
    for($i=0;$i -lt 9;$i++){$pin=$packages[$i];$actual=$record.packages[$i];$file=Join-Path $Source $pin.relativePath;Assert-OpenGeulFodNoReparse $file;$fileInfo=[IO.FileInfo]::new($file)
        if($actual.relativePath -cne $pin.relativePath -or $actual.rangeStart -ne $pin.start -or $actual.rangeEnd -ne ($pin.start+$pin.bytes-1) -or $actual.bytes -ne $pin.bytes -or $actual.sha256 -cne $pin.sha256 -or $fileInfo.Length -ne $pin.bytes -or (Get-OpenGeulFodSha $file) -cne $pin.sha256){throw 'FoD CAB bytes or pins rejected.'}}
    return Get-OpenGeulFodSha $path
}
function Get-OpenGeulFodPython([string]$SourceRoot) {
    # Presence only. Do not obtain, measure, hash, log or copy override values.
    foreach($name in @('HTTPS_PROXY','HTTP_PROXY','ALL_PROXY','NO_PROXY','SSL_CERT_FILE','SSL_CERT_DIR')){if(Test-Path -LiteralPath ('Env:'+ $name)){throw 'FoD acquisition routing environment is unsupported.'}}
    $location=[Environment]::GetEnvironmentVariable('pythonLocation');$exe=[IO.Path]::GetFullPath((Join-Path $location 'python.exe'))
    if($exe.IndexOf(';') -ge 0){throw 'FoD exact Python path is unavailable.'}
    $command=Get-Command python.exe -CommandType Application -ErrorAction Stop
    if(-not $exe.Equals([IO.Path]::GetFullPath($command.Path),[StringComparison]::OrdinalIgnoreCase)){throw 'FoD exact Python executable is unavailable.'}
    Assert-OpenGeulFodNoReparse $exe
    $version=[Diagnostics.FileVersionInfo]::GetVersionInfo($exe)
    if($version.FileMajorPart -ne 3 -or $version.FileMinorPart -ne 12){throw 'FoD Python version is unavailable.'}
    $stream=$null;$reader=$null
    try {$stream=[IO.File]::OpenRead($exe);$reader=[IO.BinaryReader]::new($stream);if($reader.ReadUInt16() -ne 0x5a4d){throw 'FoD Python PE is unavailable.'};$stream.Position=0x3c;$offset=$reader.ReadInt32();if($offset -lt 64 -or $offset -gt $stream.Length-6){throw 'FoD Python PE is unavailable.'};$stream.Position=$offset;if($reader.ReadUInt32() -ne 0x4550 -or $reader.ReadUInt16() -ne 34404){throw 'FoD Python native machine is unavailable.'}}
    finally {if($null -ne $reader){$reader.Dispose()}elseif($null -ne $stream){$stream.Dispose()}}
    Initialize-OpenGeulFodNative;$windows=[Text.StringBuilder]::new(32768);$system=[Text.StringBuilder]::new(32768)
    $n=[OpenGeulFodNative]::GetWindowsDirectoryW($windows,$windows.Capacity);$m=[OpenGeulFodNative]::GetSystemDirectoryW($system,$system.Capacity)
    if($n -eq 0 -or $n -ge $windows.Capacity -or $m -eq 0 -or $m -ge $system.Capacity){throw 'FoD actual Windows root is unavailable.'}
    Assert-OpenGeulFodNoReparse $windows.ToString();Assert-OpenGeulFodNoReparse $system.ToString()
    $temp=New-OpenGeulFodDirectory (Join-Path $SourceRoot 'temp')
    return [pscustomobject]@{Path=$exe;Sha256=(Get-OpenGeulFodSha $exe);Environment=[ordered]@{SystemRoot=$windows.ToString();WINDIR=$windows.ToString();PATH=([IO.Path]::GetDirectoryName($exe)+';'+$system.ToString());TEMP=$temp;TMP=$temp}}
}
function New-OpenGeulFodStartInfo($Python,[string]$Repo,[string]$Source) {
    $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$Python.Path;$info.UseShellExecute=$false;$info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true;$info.Environment.Clear()
    foreach($key in @('SystemRoot','WINDIR','PATH','TEMP','TMP')){$info.Environment[$key]=$Python.Environment[$key]}
    foreach($arg in @('-I','-B','-X','utf8',(Join-Path $Repo 'scripts/korean_fod_acquire_silent.py'),(Join-Path $Repo 'suite/scripts/korean_fod_source.py'),$Source)){$info.ArgumentList.Add($arg)}
    return $info
}
function New-OpenGeulFodContext([string]$Repo,[string]$Out,$Binding,$Worker) {
    $runner=$null;$control=$null
    if($Binding.job -ceq 'native-e2e' -and $Binding.architecture -ceq 'x64'){
        # Derive a possible request location without adding a prerequisite to
        # 2022/Installed. The full private-root guard runs only on a request.
        try {
            $candidate=[Environment]::GetEnvironmentVariable('RUNNER_TEMP')
            if(-not [string]::IsNullOrWhiteSpace($candidate) -and [IO.Path]::IsPathRooted($candidate)){
                $runner=[IO.Path]::GetFullPath($candidate)
                $control=Join-Path $runner ('opengeul-hwp-ko-fod-control-g1-'+$Worker.Pid+'-'+$Worker.Created)
            }
        } catch {$runner=$null;$control=$null}
    }
    return [pscustomobject]@{RunnerTemp=$runner;Out=$Out;Control=$control;Offline=$false;Attempted=$false;Ready=$false;Request=$null;Helper=$null;WorkEnd=0.0;SourceRoot=$null;WorkerComplete=$false;CustodyElapsedMs=$null;ReasonCode=0}
}
function Invoke-OpenGeulFodTick($Context,$Worker,$Clock,$Binding,[string]$Repo) {
    if($null -eq $Context.Control){return}
    $requestPath=Join-Path $Context.Control 'request.json'
    if(-not $Context.Attempted -and [IO.File]::Exists($requestPath)){
        $Context.Offline=$true;$Context.Attempted=$true;$Context.ReasonCode=4
        if(-not $Worker.IdentityKnown -or $Worker.Handle -eq [IntPtr]::Zero){throw 'FoD original worker identity unavailable.'}
        $Context.RunnerTemp=Get-OpenGeulFodRunnerTemp $Repo $Context.Out
        $expected=Join-Path $Context.RunnerTemp ('opengeul-hwp-ko-fod-control-g1-'+$Worker.Pid+'-'+$Worker.Created)
        if(-not $expected.Equals($Context.Control,[StringComparison]::OrdinalIgnoreCase)){throw 'FoD private request location changed.'}
        Assert-OpenGeulFodNoReparse $Context.Control
        $Context.Request=Read-OpenGeulFodRequest (Read-OpenGeulFodAscii $requestPath) $Binding $Worker.Pid $Worker.Created
        $Worker.Process.Refresh();if($Worker.Process.HasExited){$Context.ReasonCode=5;throw 'FoD original worker exited.'}
        if((Get-OpenGeulFodWaitMs $Clock.Elapsed.TotalSeconds 590) -le 0){$Context.ReasonCode=6;throw 'FoD worker work budget exhausted.'}
        Assert-OpenGeulFodSourcePins $Repo
        $Context.SourceRoot=New-OpenGeulFodDirectory (Join-Path $Context.RunnerTemp ('opengeul-hwp-ko-fod-g1-'+$Context.Request.requestSha256))
        $python=Get-OpenGeulFodPython $Context.SourceRoot
        $Context|Add-Member NoteProperty Python $python
        $info=New-OpenGeulFodStartInfo $python $Repo (Join-Path $Context.SourceRoot 'source')
        $Context.WorkEnd=Get-OpenGeulFodWorkEnd $Clock.Elapsed.TotalSeconds
        if((Get-OpenGeulFodWaitMs $Clock.Elapsed.TotalSeconds $Context.WorkEnd) -le 0){$Context.ReasonCode=6;throw 'FoD helper work budget exhausted.'}
        $owned=$null;$Context.ReasonCode=1
        try {Start-OpenGeulFodOwnedProcess $info ([ref]$owned) $Clock $Context.WorkEnd}
        finally {$Context.Helper=$owned}
    }
    if($Context.Offline -and -not $Context.Ready){
        if((Get-OpenGeulFodWaitMs $Clock.Elapsed.TotalSeconds $Context.WorkEnd) -le 0){$Context.ReasonCode=6;throw 'FoD helper work budget exhausted.'}
        $Worker.Process.Refresh();if($Worker.Process.HasExited){$Context.ReasonCode=5;throw 'FoD original worker exited.'}
        if(Update-OpenGeulFodRetirement $Context.Helper){
            $Context.ReasonCode=7;if($Context.Helper.ExitCode -ne 0){throw 'FoD acquisition failed.'}
            $Context.ReasonCode=4;$receipt=Assert-OpenGeulFodAcquisition (Join-Path $Context.SourceRoot 'source')
            Assert-OpenGeulFodSourcePins $Repo
            if((Get-OpenGeulFodSha $Context.Python.Path) -cne $Context.Python.Sha256){throw 'FoD exact Python executable changed.'}
            $Context.ReasonCode=8
            Assert-OpenGeulFodReadyGate $Context.Request $Worker $Context.Helper $Clock.Elapsed.TotalSeconds $Context.WorkEnd
            $ready=New-OpenGeulFodReady $Context.Request $Context.Helper $Context.Python.Sha256 $receipt
            Assert-OpenGeulFodReadyGate $Context.Request $Worker $Context.Helper $Clock.Elapsed.TotalSeconds $Context.WorkEnd
            Publish-OpenGeulFodAscii (Join-Path $Context.Control 'ready.json') $ready
            $Context.Ready=$true;$Context.ReasonCode=0
        }
    }
}
function Complete-OpenGeulFodWorker($Context,$Worker,$Clock) {
    if($Context.Offline){
        $Context.CustodyElapsedMs=[long][Math]::Floor($Clock.Elapsed.TotalMilliseconds)
        $Context.ReasonCode=8
        if(-not $Context.Ready -or $Clock.Elapsed.TotalSeconds -ge 590 -or -not (Update-OpenGeulFodRetirement $Worker) -or $Worker.ExitCode -ne 0 -or $Context.Helper.Retired -ne $true -or $Context.Helper.ExitCode -ne 0){throw 'FoD worker custody did not complete.'}
        $Context.WorkerComplete=$true;$Context.ReasonCode=0
    }
}
function Save-OpenGeulFodCustody($Context,$Worker,[string]$Out) {
    if(-not $Context.Offline){return}
    $helperRetired=$null;$helperExit=$null
    if($null -ne $Context.Helper){$helperRetired=$Context.Helper.Retired;$helperExit=$Context.Helper.ExitCode}
    $row=[ordered]@{schemaVersion=1;diagnosticOnly=1;acceptanceEligible=0;generation=1;readyPublished=[bool]$Context.Ready;workerComplete=[bool]$Context.WorkerComplete;workerRetired=$Worker.Retired;helperRetired=$helperRetired;helperExitCode=$helperExit;reasonCode=[int]$Context.ReasonCode;custodyElapsedMs=$Context.CustodyElapsedMs;wholeScript600Claim=$false;productInputVerified=$false;sourceQualified=$false;storeQualified=$false}
    $json=$row|ConvertTo-Json -Compress
    if([Text.Encoding]::UTF8.GetByteCount($json) -gt 4096){throw 'FoD numeric custody receipt exceeded its bound.'}
    [IO.File]::WriteAllText((Join-Path $Out 'fod-custody.numeric.json'),$json,[Text.UTF8Encoding]::new($false))
}
function Wait-OpenGeulFodSource([string]$Repo,[string]$Out,$Binding,[int]$InstallationCode) {
    $runner=Get-OpenGeulFodRunnerTemp $Repo $Out;Assert-OpenGeulFodSourcePins $Repo
    $self=[Diagnostics.Process]::GetCurrentProcess()
    try {$creation=[long](Get-OpenGeulFodProcessCreation $self);$text=New-OpenGeulFodRequest $Binding $PID $creation $InstallationCode;$request=Read-OpenGeulFodRequest $text $Binding $PID $creation}
    finally {$self.Dispose()}
    $controlFull=New-OpenGeulFodDirectory (Join-Path $runner ('opengeul-hwp-ko-fod-control-g1-'+$PID+'-'+$creation))
    Publish-OpenGeulFodAscii (Join-Path $controlFull 'request.json') $text
    $readyPath=Join-Path $controlFull 'ready.json'
    # The original parent owns this wait's 590/600 clock and retained worker.
    while(-not [IO.File]::Exists($readyPath)){Start-Sleep -Milliseconds 100}
    $ready=Read-OpenGeulFodReady (Read-OpenGeulFodAscii $readyPath) $request
    $root=Join-Path $runner ('opengeul-hwp-ko-fod-g1-'+$request.requestSha256);Assert-OpenGeulFodNoReparse $root
    $source=Join-Path $root 'source';$receipt=Assert-OpenGeulFodAcquisition $source
    $python=[IO.Path]::GetFullPath((Join-Path ([Environment]::GetEnvironmentVariable('pythonLocation')) 'python.exe'));Assert-OpenGeulFodNoReparse $python
    if((Get-OpenGeulFodSha $python) -cne $ready.pythonExecutableSha256 -or $receipt -cne $ready.acquisitionReceiptSha256){throw 'FoD private source identity changed.'}
    return Join-Path $source 'LanguagesAndOptionalFeatures'
}
