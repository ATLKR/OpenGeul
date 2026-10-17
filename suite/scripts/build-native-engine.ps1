param(
    [ValidateSet('Firebird','Full')][string]$Phase='Firebird',
    [string]$WorkDirectory='.work/native-engine',
    [string]$OutputDirectory='.work/native-engine-evidence',
    [string]$SourceLockPath='',
    [ValidateRange(1,64)][int]$Jobs=4
)
$ErrorActionPreference='Stop'

function Write-BuildJson($Path,$Value) {
    $Value|ConvertTo-Json -Depth 30|Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Assert-NativeBuildHost($Identity) {
    if($Identity.isWindows -ne $true -or $Identity.processMachine -ne 0 -or $Identity.nativeMachine -ne 0xaa64) {
        throw 'Native Windows ARM64 OS and an unemulated ARM64 PowerShell controller are required.'
    }
}

function Get-NativeBuildHost {
    if(-not [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) {
        throw 'This source build requires actual Windows ARM64 hardware.'
    }
    if(-not ('NativeEngineHost' -as [type])) {
        Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NativeEngineHost {
 [DllImport("kernel32.dll")] public static extern IntPtr GetCurrentProcess();
 [DllImport("kernel32.dll",SetLastError=true)] public static extern bool IsWow64Process2(IntPtr process,out ushort processMachine,out ushort nativeMachine);
}
'@
    }
    [ushort]$processMachine=0;[ushort]$nativeMachine=0
    if(-not [NativeEngineHost]::IsWow64Process2([NativeEngineHost]::GetCurrentProcess(),[ref]$processMachine,[ref]$nativeMachine)) {
        throw 'IsWow64Process2 could not establish the real controller/OS architecture.'
    }
    $identity=[ordered]@{isWindows=$true;processMachine=[int]$processMachine;nativeMachine=[int]$nativeMachine;controllerPid=$PID;osDescription=[Runtime.InteropServices.RuntimeInformation]::OSDescription}
    Assert-NativeBuildHost ([pscustomobject]$identity)
    return $identity
}

function Assert-UnlinkedPath([string]$Path) {
    $current=[IO.Path]::GetFullPath($Path)
    while($current) {
        if(Test-Path -LiteralPath $current) {
            $item=Get-Item -LiteralPath $current -Force
            if($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {throw "Linked build/evidence path is forbidden: $current"}
        }
        $parent=[IO.Path]::GetDirectoryName($current)
        if($parent -eq $current) {break}
        $current=$parent
    }
}

function New-BuildDirectories([string]$WorkDirectory,[string]$OutputDirectory) {
    foreach($path in @($WorkDirectory,$OutputDirectory)) {
        if([string]::IsNullOrWhiteSpace($path) -or $path.StartsWith('\\') -or $path.StartsWith('//')) {throw 'Fresh local build/evidence paths are required.'}
        Assert-UnlinkedPath $path
    }
    $work=[IO.Path]::GetFullPath($WorkDirectory);$output=[IO.Path]::GetFullPath($OutputDirectory)
    $separator=[IO.Path]::DirectorySeparatorChar
    if($work.Equals($output,[StringComparison]::OrdinalIgnoreCase) -or $work.StartsWith($output.TrimEnd($separator)+$separator,[StringComparison]::OrdinalIgnoreCase) -or $output.StartsWith($work.TrimEnd($separator)+$separator,[StringComparison]::OrdinalIgnoreCase)) {throw 'Build and evidence directories must be separate.'}
    if((Test-Path -LiteralPath $work) -or (Test-Path -LiteralPath $output)) {throw 'Build/evidence directory already exists; preserve it and choose fresh paths.'}
    New-Item -ItemType Directory -Path $output -ErrorAction Stop|Out-Null
    New-Item -ItemType Directory -Path $work -ErrorAction Stop|Out-Null
    return [pscustomobject]@{work=$work;output=$output}
}

function Get-SourcePin([string]$LockPath) {
    $lock=Get-Content -LiteralPath $LockPath -Raw|ConvertFrom-Json
    $url='https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-26.8.1.1.tar.xz'
    $sha='296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785'
    if($lock.schemaVersion -ne 1 -or $lock.runtime.version -ne '26.8.1.1' -or $lock.runtime.sourceUrl -ne $url -or $lock.runtime.sourceSha256 -ne $sha) {throw 'The authenticated official LibreOffice26.8.1.1 source lock is required.'}
    return [ordered]@{url=$lock.runtime.sourceUrl;size=302435508;sha256=$sha;version='26.8.1.1'}
}

function Get-SourceRunBinding([string]$RepoRoot,[string]$DriverPath,[string]$ManifestPath,[string]$LogDirectory) {
    $git=(Get-Command git -ErrorAction Stop).Source
    $headResult=Invoke-LoggedCommand $git @('rev-parse','HEAD') $RepoRoot (Join-Path $LogDirectory 'source-head')
    $treeResult=Invoke-LoggedCommand $git @('rev-parse','HEAD^{tree}') $RepoRoot (Join-Path $LogDirectory 'source-tree')
    $head=(Get-Content -LiteralPath $headResult.stdout -Raw).Trim()
    $tree=(Get-Content -LiteralPath $treeResult.stdout -Raw).Trim()
    if($head -cnotmatch '^[0-9a-f]{40}$' -or $tree -cnotmatch '^[0-9a-f]{40}$') {throw 'Actual Git source commit/tree identity is invalid.'}
    if($env:GITHUB_SHA -and $env:GITHUB_SHA -cne $head) {throw 'Actual Git HEAD differs from the GitHub workflow source SHA.'}
    $paths=@([IO.Path]::GetRelativePath($RepoRoot,$DriverPath).Replace('\','/'),[IO.Path]::GetRelativePath($RepoRoot,$ManifestPath).Replace('\','/'))
    foreach($path in $paths) {if($path.StartsWith('../') -or [IO.Path]::IsPathRooted($path)) {throw 'Source binding files must belong to this repository.'}}
    Invoke-LoggedCommand $git (@('ls-files','--error-unmatch','--')+$paths) $RepoRoot (Join-Path $LogDirectory 'source-tracked-files')|Out-Null
    Invoke-LoggedCommand $git @('diff','--quiet','HEAD','--') $RepoRoot (Join-Path $LogDirectory 'source-clean')|Out-Null
    $run=$null;$attempt=$null
    if($env:GITHUB_RUN_ID) {
        [long]$parsed=0
        if(-not [long]::TryParse($env:GITHUB_RUN_ID,[ref]$parsed) -or $parsed -le 0) {throw 'GitHub source run ID must be a positive integer.'}
        $run=$parsed
    }
    if($env:GITHUB_RUN_ATTEMPT) {
        [long]$parsedAttempt=0
        if(-not [long]::TryParse($env:GITHUB_RUN_ATTEMPT,[ref]$parsedAttempt) -or $parsedAttempt -le 0) {throw 'GitHub source run attempt must be a positive integer.'}
        $attempt=$parsedAttempt
    }
    if($env:GITHUB_ACTIONS -eq 'true' -and (-not $env:GITHUB_SHA -or $null -eq $run -or $null -eq $attempt)) {throw 'CI source receipt requires actual workflow SHA, run and attempt.'}
    return [ordered]@{sourceCommit=$head;sourceTree=$tree;sourceRun=$run;runAttempt=$attempt;
        sourcePortManifestSha256=(Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant();
        driverSha256=(Get-FileHash -LiteralPath $DriverPath -Algorithm SHA256).Hash.ToLowerInvariant()}
}

function Confirm-FileIdentity([string]$Path,[long]$Size,[ValidateSet('SHA256','SHA512')][string]$Algorithm,[string]$Hash) {
    $file=Get-Item -LiteralPath $Path
    if($Size -gt 0 -and $file.Length -ne $Size) {throw "Authenticated input size mismatch: $Path"}
    $actual=(Get-FileHash -LiteralPath $Path -Algorithm $Algorithm).Hash.ToLowerInvariant()
    if($actual -ne $Hash.ToLowerInvariant()) {throw "Authenticated input $Algorithm mismatch: $Path"}
    return [ordered]@{path=$file.FullName;size=$file.Length;algorithm=$Algorithm;hash=$actual}
}

function Get-AuthenticatedDownload([string]$Url,[string]$Destination,[long]$Size,[string]$Algorithm,[string]$Hash,[string]$ReceiptPath) {
    if(Test-Path -LiteralPath $Destination) {throw 'Download target already exists.'}
    $receipt=[ordered]@{url=$Url;status='downloading';expectedSize=$Size;expectedHash=$Hash;algorithm=$Algorithm;path=$Destination}
    Write-BuildJson $ReceiptPath $receipt
    Write-Host "Downloading authenticated input: $Url"
    $client=[Net.Http.HttpClient]::new();$client.Timeout=[TimeSpan]::FromMinutes(30)
    $stream=$null;$file=$null
    try {
        $response=$client.GetAsync($Url,[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        $response.EnsureSuccessStatusCode()|Out-Null
        $receipt.finalUrl=$response.RequestMessage.RequestUri.AbsoluteUri
        $stream=$response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $file=[IO.File]::Open($Destination,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        $buffer=[byte[]]::new(1048576);[long]$count=0;[long]$reported=0
        while(($read=$stream.Read($buffer,0,$buffer.Length)) -gt 0) {
            $file.Write($buffer,0,$read);$count+=$read
            if($Size -gt 0 -and $count -gt $Size) {throw 'Download exceeded its authenticated size.'}
            if($count-$reported -ge 16777216) {Write-Host "Downloaded $count bytes: $([IO.Path]::GetFileName($Destination))";$reported=$count}
        }
        $file.Dispose();$file=$null
        $receipt.identity=Confirm-FileIdentity $Destination $Size $Algorithm $Hash
        $receipt.status='authenticated'
        Write-Host "Authenticated $count bytes: $([IO.Path]::GetFileName($Destination))"
    } catch {$receipt.status='failed';$receipt.error=$_.Exception.Message;throw}
    finally {if($file){$file.Dispose()};if($stream){$stream.Dispose()};$client.Dispose();Write-BuildJson $ReceiptPath $receipt}
    return $receipt.identity
}

function Invoke-LoggedCommand([string]$FilePath,[string[]]$Arguments,[string]$WorkingDirectory,[string]$LogPrefix,[int]$TimeoutMinutes=350) {
    $receipt=[ordered]@{file=$FilePath;arguments=@($Arguments);workingDirectory=$WorkingDirectory;startedUtc=[DateTime]::UtcNow.ToString('o');passed=$false;exitCode=$null}
    $stdout=$LogPrefix+'.stdout.log';$stderr=$LogPrefix+'.stderr.log'
    foreach($path in @($stdout,$stderr,$LogPrefix+'.command.json')) {if(Test-Path -LiteralPath $path){throw 'Command evidence already exists.'}}
    $outStream=$null;$errStream=$null;$process=$null;$watch=[Diagnostics.Stopwatch]::StartNew()
    Write-Host ('Starting: '+[IO.Path]::GetFileName($FilePath)+' '+($Arguments -join ' '))
    try {
        $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$FilePath;$info.WorkingDirectory=$WorkingDirectory
        $info.UseShellExecute=$false;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
        foreach($argument in $Arguments) {$info.ArgumentList.Add($argument)}
        $process=[Diagnostics.Process]::new();$process.StartInfo=$info
        $outStream=[IO.File]::Open($stdout,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
        $errStream=[IO.File]::Open($stderr,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
        if(-not $process.Start()) {throw 'Command process did not start.'}
        $receipt.pid=$process.Id
        $outTask=$process.StandardOutput.BaseStream.CopyToAsync($outStream)
        $errTask=$process.StandardError.BaseStream.CopyToAsync($errStream)
        while(-not $process.WaitForExit(15000)) {
            Write-Host ("Still running {0}: {1}s; stdout={2} bytes stderr={3} bytes" -f [IO.Path]::GetFileName($FilePath),[int]$watch.Elapsed.TotalSeconds,$outStream.Length,$errStream.Length)
            if($watch.Elapsed.TotalMinutes -gt $TimeoutMinutes) {$process.Kill($true);$process.WaitForExit();throw 'Owned command exceeded its bounded time budget.'}
        }
        $outTask.GetAwaiter().GetResult();$errTask.GetAwaiter().GetResult()
        $receipt.exitCode=$process.ExitCode
        if($process.ExitCode -ne 0) {throw "Command failed with exit $($process.ExitCode); inspect $stdout and $stderr"}
        $receipt.passed=$true
    } catch {$receipt.error=$_.Exception.Message;throw}
    finally {
        if($outStream){$outStream.Dispose()};if($errStream){$errStream.Dispose()};if($process){$process.Dispose()}
        $receipt.elapsedSeconds=[Math]::Round($watch.Elapsed.TotalSeconds,3)
        Write-BuildJson ($LogPrefix+'.command.json') $receipt
    }
    return [pscustomobject]@{stdout=$stdout;stderr=$stderr;receipt=$LogPrefix+'.command.json';exitCode=$receipt.exitCode}
}

function Get-ExtraSourcePins {
    $base='https://download.documentfoundation.org/libreoffice/src/26.8.1/'
    # Published .sha256 files and archive sizes, fetched from the official
    # version-pinned source distribution. Upstream fetches these unchecked.
    foreach($pin in @(
        @('libreoffice-help-26.8.1.1.tar.xz',53513324,'f1de4054194e8718f699ddf2b269165613c8dd07c10c55b32968c977f0c6234f'),
        @('libreoffice-dictionaries-26.8.1.1.tar.xz',62319860,'ce366c50178f5bdf6df1c6df4a0146899cf27a0017734190d00d90f0c5acac61'),
        @('libreoffice-translations-26.8.1.1.tar.xz',236160656,'789519befa409d7eec24043cea41ddd318d9f1212f555d8b28d4982e35693bfc')
    )) { [ordered]@{filename=$pin[0];url=$base+$pin[0];size=$pin[1];sha256=$pin[2];checksumUrl=$base+$pin[0]+'.sha256'} }
}

function Get-ConfigureArguments([string]$ExternalTar='') {
    '--with-distro=LibreOfficeWinArm64','--build=aarch64-pc-cygwin','--host=aarch64-pc-cygwin',
    '--with-visual-studio=2026','--enable-firebird-sdbc','--enable-database-connectivity',
    '--without-system-firebird','--without-system-libatomic_ops','--without-system-libtommath','--without-system-icu','--with-lang=en-US ko'
    if($ExternalTar) {'--with-external-tar='+$ExternalTar}
}

function Get-BuildTargets([ValidateSet('Firebird','Full')][string]$Phase) {
    'ExternalProject_firebird';'firebird'
    if($Phase -eq 'Full') {'build'}
}

function Assert-GeneratedConfiguration([string]$Path) {
    $values=@{}
    foreach($line in Get-Content -LiteralPath $Path) {
        if($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?::|\?)?=\s*(.*?)\s*$') {$values[$Matches[1]]=$Matches[2]}
    }
    $required=@{OS='WNT';COM='MSC';CPUNAME='AARCH64';HOST_PLATFORM='aarch64-pc-cygwin';BUILD_PLATFORM='aarch64-pc-cygwin';ENABLE_FIREBIRD_SDBC='TRUE'}
    foreach($key in $required.Keys) {if($values[$key] -cne $required[$key]){throw "Generated configuration rejects native Firebird: $key=$($values[$key])"}}
    if(-not $values.ContainsKey('CROSS_COMPILING') -or $values.CROSS_COMPILING -ne '' -or $values.SYSTEM_FIREBIRD -ne '') {throw 'Cross-compiling or system Firebird is forbidden.'}
    foreach($token in @('FIREBIRD','LIBATOMIC_OPS','LIBTOMMATH')) {if($values.BUILD_TYPE -notmatch ('(^|\s)'+$token+'(\s|$)')) {throw "Required internal build dependency is absent: $token"}}
    return $values
}

function Get-PinnedPythonTemplates {
    # Exact nonexecuted launcher templates from authenticated official ARM64 MSI
    # SHA256 97c2173752325af1da3d8731f41c8e09a7c4ad491cf55d9b1069fadb5668e6d7.
    # A new source build must independently match every admitted byte/hash.
    $prefix='program/python-core-3.13.15/lib/'
    foreach($pin in @(
        @('pip/_vendor/distlib/t32.exe',332,'6b4195e640a85ac32eb6f9628822a622057df1e459df7c17a12f97aeabc9415b'),
        @('pip/_vendor/distlib/t64.exe',34404,'81a618f21cb87db9076134e70388b6e9cb7c2106739011b6a51772d22cae06b7'),
        @('pip/_vendor/distlib/w32.exe',332,'47872cc77f8e18cf642f868f23340a468e537e64521d9a3a416c8b84384d064b'),
        @('pip/_vendor/distlib/w64.exe',34404,'7a319ffaba23a017d7b1e18ba726ba6c54c53d6446db55f92af53c279894f8ad'),
        @('setuptools/cli-32.exe',332,'32acc1bc543116cbe2cff10cb867772df2f254ff2634c870aef0b46c4b696fdb'),
        @('setuptools/cli-64.exe',34404,'bbb3de5707629e6a60a0c238cd477b28f07f0066982fda953fa6fcec39073a4a'),
        @('setuptools/cli.exe',332,'32acc1bc543116cbe2cff10cb867772df2f254ff2634c870aef0b46c4b696fdb'),
        @('setuptools/gui-32.exe',332,'85dae1e95d77845f2cb59bcac3d4afe74bbe4c91a9bcc5bf4a71cd43104dbe7c'),
        @('setuptools/gui-64.exe',34404,'3471b6140eadc6412277dbbefe3fef8c345a0f1a59776086b80a3618c3a83e3b'),
        @('setuptools/gui.exe',332,'85dae1e95d77845f2cb59bcac3d4afe74bbe4c91a9bcc5bf4a71cd43104dbe7c')
    )) {[ordered]@{path=$prefix+$pin[0];machine=$pin[1];sha256=$pin[2];role='pythonLauncherTemplate'}}
}

function Assert-PythonTemplateAdmission([string]$RelativePath,[int]$Machine,[string]$Hash) {
    $pins=@(Get-PinnedPythonTemplates|Where-Object {$_.path -ceq $RelativePath})
    if($pins.Count -ne 1 -or $pins[0].machine -ne $Machine -or $pins[0].sha256 -cne $Hash) {throw "Unknown path/machine/hash for nonnative product code: $RelativePath"}
    return $pins[0]
}

function Get-ProductPeIdentity([string]$Path,[string]$RuntimeRoot='') {
    $data=[IO.File]::ReadAllBytes($Path)
    if($data.Length -lt 64 -or $data[0] -ne 77 -or $data[1] -ne 90) {throw "Invalid PE: $Path"}
    $offset=[BitConverter]::ToUInt32($data,60)
    if($offset -lt 64 -or $offset -gt 1048576 -or $offset+26 -gt $data.Length -or [BitConverter]::ToUInt32($data,[int]$offset) -ne 17744) {throw "Invalid PE headers: $Path"}
    $machine=[BitConverter]::ToUInt16($data,[int]$offset+4)
    $magic=[BitConverter]::ToUInt16($data,[int]$offset+24)
    $hash=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    $role='nativeArm64'
    if($machine -ne 0xaa64 -or $magic -ne 0x20b) {
        $role=''
        $optional=[int]$offset+24;$optionalSize=[BitConverter]::ToUInt16($data,[int]$offset+20)
        $characteristics=[BitConverter]::ToUInt16($data,[int]$offset+22)
        if($machine -eq 0x14c -and $magic -eq 0x10b -and [IO.Path]::GetExtension($Path) -ieq '.dll' -and ($characteristics -band 0x2000) -and $optionalSize -ge 216 -and $optional+$optionalSize -le $data.Length -and [BitConverter]::ToUInt32($data,$optional+92) -ge 15) {
            $sections=[BitConverter]::ToUInt16($data,[int]$offset+6)
            $sectionTable=$optional+$optionalSize
            if($sections -lt 1 -or $sections -gt 96 -or $sectionTable+$sections*40 -gt $data.Length) {throw 'Invalid managed PE sections.'}
            $mapRva={param([uint32]$Rva,[uint32]$Length)
                for($i=0;$i -lt $sections;$i++) {
                    $entry=$sectionTable+$i*40;$start=[BitConverter]::ToUInt32($data,$entry+12);$rawSize=[BitConverter]::ToUInt32($data,$entry+16);$raw=[BitConverter]::ToUInt32($data,$entry+20)
                    if($Rva -ge $start -and [long]$Rva+$Length -le [long]$start+$rawSize -and [long]$raw+$rawSize -le $data.Length) {return [byte[]]$data[([int]($raw+$Rva-$start))..([int]($raw+$Rva-$start+$Length-1))]}
                }
                throw 'Managed PE RVA is outside its actual section data.'
            }
            $clrRva=[BitConverter]::ToUInt32($data,$optional+208);$clrSize=[BitConverter]::ToUInt32($data,$optional+212)
            if($clrRva -eq 0 -or $clrSize -lt 72) {throw 'x86 DLL is not an IL-only AnyCPU assembly.'}
            [byte[]]$clr=&$mapRva $clrRva 72
            $cb=[BitConverter]::ToUInt32($clr,0);$flags=[BitConverter]::ToUInt32($clr,16);$metadataSize=[BitConverter]::ToUInt32($clr,12)
            if($cb -lt 72 -or $cb -gt $clrSize -or -not($flags -band 1) -or ($flags -band (2 -bor 16 -bor 0x20000)) -or $metadataSize -lt 16) {throw 'Managed DLL requires a foreign native architecture.'}
            if(@($clr[40..71]|Where-Object {$_ -ne 0}).Count -ne 0) {throw 'Managed DLL contains native-bearing CLR directories.'}
            [byte[]]$metadata=&$mapRva ([BitConverter]::ToUInt32($clr,8)) $metadataSize
            if([BitConverter]::ToUInt32($metadata,0) -ne 0x424a5342) {throw 'Managed assembly metadata signature is invalid.'}
            $role='managedAnyCpu'
        }
        if(-not $role -and $RuntimeRoot) {
            $relative=[IO.Path]::GetRelativePath($RuntimeRoot,$Path).Replace('\','/')
            $pin=Assert-PythonTemplateAdmission $relative $machine $hash
            if(($machine -eq 0x14c -and $magic -ne 0x10b) -or ($machine -eq 0x8664 -and $magic -ne 0x20b)) {throw 'Pinned template optional-header architecture changed.'}
            $role=$pin.role
        }
        if(-not $role) {throw "Product PE is not native ARM64 or verified AnyCPU: $Path (machine $machine)"}
    }
    return [ordered]@{path=$Path;machine=[int]$machine;role=$role;sha256=$hash;size=$data.Length}
}

function Quote-Bash([string]$Value) {return "'"+$Value.Replace("'","'\''")+"'"}

function Write-BashScript([string]$Path,[string[]]$Lines) {
    $text=($Lines -join "`n").Replace("`r`n","`n").Replace("`r","`n").TrimEnd("`n")+"`n"
    [IO.File]::WriteAllText($Path,$text,[Text.UTF8Encoding]::new($false))
}

function Invoke-CygwinScript($Bash,$Cygpath,[string]$Script,[string]$WorkingDirectory,[string]$LogPrefix) {
    $converted=Invoke-LoggedCommand $Cygpath @('-u',$Script) $WorkingDirectory ($LogPrefix+'-path')
    $unix=(Get-Content -LiteralPath $converted.stdout -Raw).Trim()
    return Invoke-LoggedCommand $Bash @('--noprofile','--norc',$unix) $WorkingDirectory $LogPrefix
}

function Get-IsqlSql([string]$DatabasePath) {
    if($DatabasePath.Contains("'") -or $DatabasePath -match '[\r\n]') {throw 'SQL proof database must have a literal owned path.'}
    $create=@"
CREATE DATABASE '$DatabasePath' USER 'SYSDBA' PASSWORD 'masterkey';
CREATE TABLE OPENGEUL_ARM64_PROBE (ID INTEGER NOT NULL PRIMARY KEY, AMOUNT INTEGER);
INSERT INTO OPENGEUL_ARM64_PROBE VALUES (1,42);
INSERT INTO OPENGEUL_ARM64_PROBE VALUES (2,9);
COMMIT;
UPDATE OPENGEUL_ARM64_PROBE SET AMOUNT=55 WHERE ID=1;
DELETE FROM OPENGEUL_ARM64_PROBE WHERE ID=2;
INSERT INTO OPENGEUL_ARM64_PROBE VALUES (3,13);
COMMIT;
UPDATE OPENGEUL_ARM64_PROBE SET AMOUNT=999 WHERE ID=1;
DELETE FROM OPENGEUL_ARM64_PROBE WHERE ID=3;
INSERT INTO OPENGEUL_ARM64_PROBE VALUES (4,99);
ROLLBACK;
QUIT;
"@
    $verify=@'
SET LIST ON;
SELECT COUNT(*) AS ROW_COUNT, SUM(AMOUNT) AS TOTAL,
SUM(CASE WHEN ID=1 AND AMOUNT=55 THEN 1 ELSE 0 END) AS ROW_ONE,
SUM(CASE WHEN ID=3 AND AMOUNT=13 THEN 1 ELSE 0 END) AS ROW_THREE
FROM OPENGEUL_ARM64_PROBE;
QUIT;
'@
    return [ordered]@{create=$create;verify=$verify}
}

function Assert-IsqlOutput([string]$Path) {
    $text=Get-Content -LiteralPath $Path -Raw
    foreach($pair in @(@('ROW_COUNT',2),@('TOTAL',68),@('ROW_ONE',1),@('ROW_THREE',1))) {
        $matches=[regex]::Matches($text,'(?m)^\s*'+$pair[0]+'\s+(-?\d+)\s*$')
        if($matches.Count -ne 1 -or [int]$matches[0].Groups[1].Value -ne $pair[1]) {throw "Persisted Firebird CRUD/rollback proof is wrong: $($pair[0])"}
    }
}

function Assert-BaseProof([string]$Path) {
    $proof=Get-Content -LiteralPath $Path -Raw|ConvertFrom-Json
    if($proof.schemaVersion -ne 1 -or $proof.passed -ne $true -or $proof.guiVerified -ne $false -or $proof.independentReopenVerified -ne $true -or @($proof.nativeProcesses).Count -ne 3) {throw 'Actual native Python/Office independent Base proof is incomplete.'}
    foreach($identity in $proof.nativeProcesses) {Assert-NativeBuildHost ([pscustomobject]@{isWindows=$true;processMachine=$identity.processMachine;nativeMachine=$identity.nativeMachine})}
    if($proof.nativeProcesses[0].role -ne 'uno-python') {throw 'Native proof did not observe the actual UNO Python process.'}
    for($i=1;$i -lt 3;$i++) {
        if($proof.nativeProcesses[$i].role -ne 'uno-host' -or $proof.nativeProcesses[$i].jobOwned -ne $true -or $proof.nativeProcesses[$i].phase -ne @('create','reopen')[$i-1]) {throw 'Native proof must observe owned soffice.bin hosts, not launcher processes.'}
    }
    $rows=@($proof.rows)
    if($rows.Count -ne 1 -or $rows[0].id -ne 1 -or $rows[0].text -cne 'Engine-OpenGeul-base 한글' -or $rows[0].amount -ne 42) {throw 'Native Base persisted row differs.'}
    return $proof
}

function Write-ExternalSourceInventory([string]$CacheDirectory,[string]$PinLog,[string]$OutputPath,[hashtable]$KnownPins=@{},[string]$PythonTree='',[switch]$RequirePython) {
    $pins=@{}
    foreach($line in Get-Content -LiteralPath $PinLog) {
        if($line -match '^PIN\|([^|]+)\|([^|]+)\|([0-9a-fA-F]{64})$') {
            $variable=$Matches[1];$name=$Matches[2];$hash=$Matches[3].ToLowerInvariant()
            if($name -match '[/\\]' -or $name -in @('.','..')) {throw 'External source filename escaped its cache.'}
            if($pins.ContainsKey($name) -and $pins[$name].sha256 -ne $hash) {throw 'Conflicting authenticated download.lst pins.'}
            $pins[$name]=@{variable=$variable;sha256=$hash}
        }
    }
    foreach($name in $KnownPins.Keys) {$pins[$name]=@{variable='independently-authenticated-source';sha256=$KnownPins[$name]}}
    $archives=@();$pythonVerified=$false
    foreach($file in Get-ChildItem -LiteralPath $CacheDirectory -File) {
        if($pins.ContainsKey($file.Name)) {
            $actual=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            if($actual -cne $pins[$file.Name].sha256) {throw "External source archive fails authenticated download.lst hash: $($file.Name)"}
            $archives+=@{filename=$file.Name;size=$file.Length;sha256=$actual;pinVariable=$pins[$file.Name].variable}
            if($pins[$file.Name].variable -eq 'PYTHON_TARBALL') {$pythonVerified=$true}
        } elseif($file.Name -match '\.(tar(?:\..+)?|tgz|xz|gz|bz2|zip|7z|whl|nupkg|crate)$') {
            throw "Unpinned source archive found in build cache: $($file.Name)"
        }
    }
    if($RequirePython -and -not $pythonVerified) {throw 'Source-built Python archive is absent or unverified.'}
    $wheels=@()
    if($PythonTree -and (Test-Path -LiteralPath $PythonTree)) {
        foreach($file in Get-ChildItem -LiteralPath $PythonTree -File -Filter '*.whl' -Recurse) {
            $wheels+=@{path=[IO.Path]::GetRelativePath($PythonTree,$file.FullName).Replace('\','/');size=$file.Length;sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant();provenance='unpacked authenticated Python source plus source-controlled patches'}
        }
    }
    $result=[ordered]@{schemaVersion=1;archives=@($archives);pythonSourceVerified=$pythonVerified;embeddedPythonWheels=@($wheels)}
    Write-BuildJson $OutputPath $result
    return $result
}

function Get-CrtNames {
    'concrt140.dll','msvcp140.dll','msvcp140_1.dll','msvcp140_2.dll','msvcp140_atomic_wait.dll',
    'msvcp140_codecvt_ids.dll','vcruntime140.dll','vcruntime140_1.dll','vcruntime140_threads.dll'
}

function Get-CrtSigningIdentity([string]$Path) {
    $signature=Get-AuthenticodeSignature -LiteralPath $Path -ErrorAction Stop
    $version=[Diagnostics.FileVersionInfo]::GetVersionInfo($Path)
    return [ordered]@{status=[string]$signature.Status;signerSubject=$signature.SignerCertificate.Subject;
        signerThumbprint=$signature.SignerCertificate.Thumbprint;signerIssuer=$signature.SignerCertificate.Issuer;
        fileVersion=$version.FileVersion;productVersion=$version.ProductVersion;
        fileVersionParts=@($version.FileMajorPart,$version.FileMinorPart,$version.FileBuildPart,$version.FilePrivatePart);
        productVersionParts=@($version.ProductMajorPart,$version.ProductMinorPart,$version.ProductBuildPart,$version.ProductPrivatePart);
        companyName=$version.CompanyName;originalFilename=$version.OriginalFilename}
}

function Assert-CrtFile([string]$Path,[string]$MinimumVersion) {
    Assert-UnlinkedPath $Path
    $name=[IO.Path]::GetFileName($Path)
    if($name -cnotin @(Get-CrtNames)) {throw "Unexpected app-local CRT filename: $name"}
    $pe=Get-ProductPeIdentity $Path
    if($pe.role -ne 'nativeArm64') {throw "App-local CRT must be native ARM64: $Path"}
    $identity=Get-CrtSigningIdentity $Path
    if($identity.status -ne 'Valid' -or $identity.signerSubject -notmatch '(?:^|,\s*)O=Microsoft Corporation(?:,|$)' -or $identity.signerThumbprint -notmatch '^[0-9a-fA-F]{40}$' -or $identity.companyName -ne 'Microsoft Corporation' -or $identity.originalFilename -ine $name) {throw "CRT Microsoft signature/resource identity rejected: $Path"}
    foreach($parts in @($identity.fileVersionParts,$identity.productVersionParts)) {
        if(@($parts).Count -ne 4) {throw 'CRT version resource is incomplete.'}
        $version=[Version]::new([int]$parts[0],[int]$parts[1],[int]$parts[2],[int]$parts[3])
        if($version.Major -ne 14 -or $version -lt [Version]$MinimumVersion) {throw "CRT runtime is older than selected MSVC build tools: $Path ($version < $MinimumVersion)"}
    }
    return [ordered]@{name=$name;sourcePath=[IO.Path]::GetFullPath($Path);machine=$pe.machine;size=$pe.size;sha256=$pe.sha256;signature=$identity}
}

function Get-AppLocalCrtPlan([string]$CompilerRoot,[string]$Toolset) {
    if($Toolset -cne 'v145') {throw 'App-local runtime discovery requires the configured VS2026 v145 toolset.'}
    Assert-UnlinkedPath $CompilerRoot
    $compiler=[IO.Path]::GetFullPath($CompilerRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $versionText=Split-Path $compiler -Leaf
    if($versionText -notmatch '^14\.\d+\.\d+(?:\.\d+)?$' -or (Split-Path (Split-Path $compiler -Parent) -Leaf) -ine 'MSVC') {throw 'Configured COMPATH must identify the actual VC/Tools/MSVC version directory.'}
    $version=[Version]$versionText
    $minimum=[Version]::new($version.Major,$version.Minor,$version.Build,[Math]::Max(0,$version.Revision))
    $vc=Split-Path (Split-Path (Split-Path $compiler -Parent) -Parent) -Parent
    if((Split-Path $vc -Leaf) -ine 'VC' -or (Split-Path (Split-Path $compiler -Parent) -Parent|Split-Path -Leaf) -ine 'Tools' -or -not(Test-Path -LiteralPath $compiler -PathType Container)) {throw 'Configured compiler root is outside the selected VS VC toolchain.'}
    $redistRoot=Join-Path $vc 'Redist/MSVC';Assert-UnlinkedPath $redistRoot
    $candidates=@()
    foreach($directory in Get-ChildItem -LiteralPath $redistRoot -Directory) {
        if($directory.Name -match '^v?(14\.\d+\.\d+(?:\.\d+)?)$') {$candidateVersion=[Version]$Matches[1]}
        elseif($directory.Name -ceq 'v145') {$candidateVersion=$minimum}
        else {continue}
        $candidateVersion=[Version]::new($candidateVersion.Major,$candidateVersion.Minor,$candidateVersion.Build,[Math]::Max(0,$candidateVersion.Revision))
        if($candidateVersion -lt $minimum) {continue}
        foreach($family in @('Microsoft.VC145.CRT','Microsoft.VC143.CRT')) {
            $path=Join-Path $directory.FullName ('arm64/'+$family)
            if(Test-Path -LiteralPath $path -PathType Container) {$candidates+=@{path=$path;family=$family;version=$candidateVersion;directory=$directory.Name}}
        }
    }
    if($candidates.Count -eq 0) {throw "No ARM64 VC redist from the selected VS installation is at least MSVC $minimum under $redistRoot"}
    $selected=@($candidates|Sort-Object -Property @{Expression={$_.version};Descending=$true},@{Expression={$_.family};Descending=$true})[0]
    Assert-UnlinkedPath $selected.path
    $files=@(foreach($name in Get-CrtNames) {Assert-CrtFile (Join-Path $selected.path $name) ([string]$minimum)})
    return [ordered]@{schemaVersion=1;toolset=$Toolset;compilerRoot=$compiler;compilerToolsVersion=$versionText;minimumRuntimeVersion=[string]$minimum;
        redistRoot=$redistRoot;sourceDirectory=$selected.path;redistVersionDirectory=$selected.directory;redistFamily=$selected.family;
        selection='selected VS installation; highest installed v14 ARM64 CRT not older than configured build tools; each DLL signature/version verified';files=$files}
}

function Save-VcRedistributionTerms([string]$OutputPath) {
    if(Test-Path -LiteralPath $OutputPath) {throw 'CRT redistribution terms snapshot already exists.'}
    $url='https://learn.microsoft.com/en-us/visualstudio/releases/2026/redistribution'
    $client=[Net.Http.HttpClient]::new();$client.Timeout=[TimeSpan]::FromMinutes(2)
    try {
        $response=$client.GetAsync($url).GetAwaiter().GetResult();$response.EnsureSuccessStatusCode()|Out-Null
        if($response.RequestMessage.RequestUri.Scheme -ne 'https' -or $response.RequestMessage.RequestUri.Host -ne 'learn.microsoft.com') {throw 'Microsoft redistribution terms left their official HTTPS origin.'}
        $bytes=$response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        $text=[Text.Encoding]::UTF8.GetString($bytes)
        if($bytes.Length -gt 2097152 -or $text -notmatch 'Visual Studio 2026' -or $text -notmatch 'REDIST.TXT' -or $text -notmatch 'VC\\redist') {throw 'Official VS2026 redistribution terms did not contain the expected redist grant.'}
        [IO.File]::WriteAllBytes($OutputPath,$bytes)
        return [ordered]@{url=$url;path=$OutputPath;size=$bytes.Length;sha256=(Get-FileHash $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()}
    } finally {$client.Dispose()}
}

function Install-AppLocalCrt($Plan,[string]$ProgramDirectory,[string]$TermsPath) {
    Assert-UnlinkedPath $ProgramDirectory;Assert-UnlinkedPath $TermsPath
    if(-not(Test-Path -LiteralPath $ProgramDirectory -PathType Container) -or -not(Test-Path -LiteralPath $TermsPath -PathType Leaf) -or @($Plan.files).Count -ne 9) {throw 'App-local CRT requires the complete preflight plan, program directory and preserved terms.'}
    $names=@($Plan.files|ForEach-Object {$_.name})
    if((Compare-Object -CaseSensitive $names @(Get-CrtNames))) {throw 'CRT preflight plan changed its exact nine-file family.'}
    $readme=Join-Path (Split-Path $ProgramDirectory -Parent) 'share/readme'
    $termsTarget=Join-Path $readme 'Microsoft-VC145-redistribution.html'
    Assert-UnlinkedPath $readme;Assert-UnlinkedPath $termsTarget
    $termsHash=(Get-FileHash $TermsPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if((Test-Path $termsTarget) -and (Get-FileHash $termsTarget -Algorithm SHA256).Hash.ToLowerInvariant() -cne $termsHash) {throw 'CRT redistribution terms destination collision.'}
    $checked=@()
    # Finish all source/collision checks before copying the first DLL.
    foreach($file in $Plan.files) {
        $expected=Join-Path $Plan.sourceDirectory $file.name
        if($file.sourcePath -cne [IO.Path]::GetFullPath($expected)) {throw 'CRT source escaped the configured VS redist directory.'}
        $actual=Assert-CrtFile $expected $Plan.minimumRuntimeVersion
        if($actual.sha256 -cne $file.sha256) {throw 'Authenticated CRT source changed after preflight.'}
        $destination=Join-Path $ProgramDirectory $file.name;Assert-UnlinkedPath $destination
        if((Test-Path -LiteralPath $destination) -and (Get-FileHash $destination -Algorithm SHA256).Hash.ToLowerInvariant() -cne $file.sha256) {throw "App-local CRT destination collision: $destination"}
        $checked+=@{source=$actual;destination=$destination;alreadyIdentical=(Test-Path -LiteralPath $destination)}
    }
    foreach($file in $checked) {
        if(-not $file.alreadyIdentical) {Copy-Item -LiteralPath $file.source.sourcePath -Destination $file.destination -ErrorAction Stop}
        $copied=Assert-CrtFile $file.destination $Plan.minimumRuntimeVersion
        if($copied.sha256 -cne $file.source.sha256) {throw 'Copied app-local CRT bytes differ from authenticated source.'}
        $file.copiedSha256=$copied.sha256
    }
    New-Item -ItemType Directory -Path $readme -Force|Out-Null
    if(-not(Test-Path $termsTarget)) {Copy-Item -LiteralPath $TermsPath -Destination $termsTarget}
    return [ordered]@{schemaVersion=1;toolset=$Plan.toolset;sourceDirectory=$Plan.sourceDirectory;programDirectory=$ProgramDirectory;files=$checked;redistributionTerms=@{path=$termsTarget;sha256=$termsHash}}
}

function Write-BaseProofScript([string]$Path) {
@'
import ctypes, hashlib, json, os, pathlib, sys, traceback
repo,runtime,output,work=map(pathlib.Path,sys.argv[1:])
sys.path.insert(0,str(repo/'suite/e2e'))
import engine_smoke as smoke
if not __debug__: raise RuntimeError('Native source-build qualification requires Python assertions enabled')

def native(pid, retained_handle=None):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=(ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32)
    kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.IsWow64Process2.argtypes=(ctypes.c_void_p,ctypes.POINTER(ctypes.c_ushort),ctypes.POINTER(ctypes.c_ushort))
    kernel.CloseHandle.argtypes=(ctypes.c_void_p,)
    handle=retained_handle or kernel.OpenProcess(0x1000,False,pid)
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    try:
        process_machine,native_machine=ctypes.c_ushort(),ctypes.c_ushort()
        if not kernel.IsWow64Process2(handle,ctypes.byref(process_machine),ctypes.byref(native_machine)): raise ctypes.WinError(ctypes.get_last_error())
        assert process_machine.value==0 and native_machine.value==0xaa64,'Observed Python/Office process is emulated or OS is not ARM64'
        return dict(pid=pid,processMachine=process_machine.value,nativeMachine=native_machine.value)
    finally:
        if retained_handle is None: kernel.CloseHandle(handle)

record=dict(schemaVersion=1,passed=False,guiVerified=False,independentReopenVerified=False,nativeProcesses=[])
path=work/'native-firebird-proof.odb'
try:
    assert not work.exists(),'Proof work directory must be fresh'
    work.mkdir()
    record['nativeProcesses'].append(dict(native(os.getpid()),role='uno-python'))
    for phase in ('create','reopen'):
        engine=smoke.Engine(repo/'suite');engine.runtime=runtime
        document=None
        try:
            engine.start()
            witnesses=engine.process.open_diagnostic_witnesses()
            try:
                matches=[item for item in witnesses.snapshot() if not item.get('error') and item.get('alive') and pathlib.Path(item['image']).resolve()==(runtime/'program/soffice.bin').resolve()]
                assert len(matches)==1,'The owned private job must contain exactly one actual soffice.bin host'
                member=matches[0]
                handle,identity=witnesses.members[member['pid']]
                record['nativeProcesses'].append(dict(native(member['pid'],handle),role='uno-host',jobOwned=True,phase=phase,image=identity['image'],creationTime=identity['creationTime']))
            finally: witnesses.close()
            driver=engine.service('com.sun.star.sdbc.DriverManager').getDriverByURL('sdbc:embedded:firebird')
            assert driver is not None,'Native Firebird SDBC driver is not registered'
            assert driver.getImplementationName()=='com.sun.star.comp.sdbc.firebird.Driver','Unexpected registered Firebird driver'
            if phase=='create':
                document=engine.service('com.sun.star.sdb.OfficeDatabaseDocument');document.initNew()
                document.DataSource.setPropertyValue('URL','sdbc:embedded:firebird')
                engine.store_new(document,path,'StarOffice XML (Base)')
                smoke.populate(engine,'base',document);document.store()
            else: document=engine.load(path.as_uri())
            observed=smoke.observe('base',document);smoke.verify_content('base',observed)
            record['rows']=observed['rows']
            if phase=='reopen': record['independentReopenVerified']=True
        finally:
            try: engine.close_document(document)
            finally: engine.cleanup()
            assert not engine.cleanup_errors,'Owned engine cleanup failed: '+repr(engine.cleanup_errors)
    record.update(passed=True,odb=str(path),odbSha256=hashlib.sha256(path.read_bytes()).hexdigest())
except BaseException as exc:
    record.update(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
finally:
    output.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
sys.exit(0 if record['passed'] else 1)
'@|Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Invoke-NativeEngineBuild([string]$Phase,[string]$WorkDirectory,[string]$OutputDirectory,[string]$SourceLockPath,[int]$Jobs) {
    $paths=New-BuildDirectories $WorkDirectory $OutputDirectory
    $work=$paths.work;$evidence=$paths.output
    $source=''
    $repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $receipt=[ordered]@{schemaVersion=1;kind='native-office-engine-source-build';phase=$Phase;architecture='arm64';status='failed';passed=$false;fullEngineQualified=$false;guiVerified=$false;startedUtc=[DateTime]::UtcNow.ToString('o');stage='native-host';firebirdSourcePortChecksExecuted=$false;libreOfficeCheckTargetExecuted=$false}
    try {
        $receipt.host=Get-NativeBuildHost
        $receipt.stage='bind-actual-source-run'
        $binding=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'build-native-engine.ps1') (Join-Path $repo 'suite/engine-build/source-build.json') $evidence
        foreach($key in $binding.Keys) {$receipt[$key]=$binding[$key]}
        if(-not $SourceLockPath) {$SourceLockPath=Join-Path $repo 'suite/config/runtime.lock.json'}
        $pin=Get-SourcePin $SourceLockPath;$receipt.sourcePin=$pin
        Copy-Item -LiteralPath $SourceLockPath -Destination (Join-Path $evidence 'input-runtime.lock.json')
        $downloads=Join-Path $work 'downloads';New-Item -ItemType Directory $downloads|Out-Null
        $receipt.stage='authenticated-downloads'
        $archive=Join-Path $downloads 'libreoffice-26.8.1.1.tar.xz'
        $receipt.sourceArchive=Get-AuthenticatedDownload $pin.url $archive $pin.size SHA256 $pin.sha256 (Join-Path $evidence 'libreoffice-download.json')
        $receipt.extraSourceArchives=@()
        foreach($extra in Get-ExtraSourcePins) {
            $identity=Get-AuthenticatedDownload $extra.url (Join-Path $downloads $extra.filename) $extra.size SHA256 $extra.sha256 (Join-Path $evidence ($extra.filename+'.download.json'))
            $receipt.extraSourceArchives+=@{pin=$extra;identity=$identity}
        }
        $setup=Join-Path $downloads 'setup-x86_64.exe'
        $setupHash='6acea47c59781c9e7f544a18d53935d59df6e44d5d52ac95ee165671b8e388820455eebf30ccc7d254b00c3d0eb694269a0f8dc84b17944c1f355dac9c5aafcc'
        $receipt.cygwinSetup=Get-AuthenticatedDownload 'https://cygwin.com/setup-x86_64.exe' $setup 0 SHA512 $setupHash (Join-Path $evidence 'cygwin-download.json')
        $manifestPath=Join-Path $repo 'suite/engine-build/source-build.json'
        $manifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
        Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $evidence 'input-source-build.json')
        $fb=Join-Path $downloads 'Firebird-3.0.13.33818-0.tar.bz2'
        if($manifest.firebird.url -ne 'https://github.com/FirebirdSQL/firebird/releases/download/v3.0.13/Firebird-3.0.13.33818-0.tar.bz2' -or $manifest.firebird.sha256 -ne 'bd263c4f685fb8fc3f1dcb8be8a411033cc31c5404d1dfce5d3849aa3f63a64d') {throw 'Pinned Firebird source manifest changed.'}
        $receipt.firebirdArchive=Get-AuthenticatedDownload $manifest.firebird.url $fb 13343760 SHA256 $manifest.firebird.sha256 (Join-Path $evidence 'firebird-download.json')
        $cygwin=Join-Path $work 'cygwin';$cache=Join-Path $work 'cygwin-cache'
        $packages='autoconf,automake,make,perl,python3,patch,bison,flex,gperf,unzip,zip,libtool,curl,git,diffutils,which,pkg-config,gcc-g++,gettext-devel'
        $receipt.stage='cygwin-build-tools'
        Invoke-LoggedCommand $setup @('--quiet-mode','--no-admin','--no-shortcuts','--no-startmenu','--no-desktop','--root',$cygwin,'--local-package-dir',$cache,'--site','https://mirrors.kernel.org/sourceware/cygwin/','--packages',$packages) $work (Join-Path $evidence 'cygwin-setup')|Out-Null
        $bash=Join-Path $cygwin 'bin/bash.exe';$cygpath=Join-Path $cygwin 'bin/cygpath.exe'
        if(-not(Test-Path -LiteralPath $bash) -or -not(Test-Path -LiteralPath $cygpath)) {throw 'Authenticated setup did not produce the required Cygwin build tools.'}
        $commands=Join-Path $work 'commands';New-Item -ItemType Directory $commands|Out-Null
        $convert={param($path,$name) $r=Invoke-LoggedCommand $cygpath @('-u',$path) $work (Join-Path $evidence ('cygpath-'+$name));(Get-Content -LiteralPath $r.stdout -Raw).Trim()}
        $unixWork=&$convert $work 'work';$unixArchive=&$convert $archive 'archive';$unixRepo=&$convert $repo 'repo';$unixFb=&$convert $fb 'firebird';$unixDownloads=&$convert $downloads 'downloads'
        $source=Join-Path $work 'libreoffice-26.8.1.1';$unixSource=$unixWork+'/libreoffice-26.8.1.1'
        $extract=Join-Path $commands 'extract.sh'
        Write-BashScript $extract @('set -euo pipefail',"cd $(Quote-Bash $unixWork)","/usr/bin/tar -xf $(Quote-Bash $unixArchive)")
        $receipt.stage='extract-authenticated-source'
        Invoke-CygwinScript $bash $cygpath $extract $work (Join-Path $evidence 'extract-source')|Out-Null
        if(-not(Test-Path -LiteralPath (Join-Path $source 'configure.ac'))) {throw 'Pinned source root was not extracted.'}
        Copy-Item (Join-Path $source 'configure.ac') (Join-Path $evidence 'configure-pristine.ac')
        $sourceGate=Join-Path $commands 'source-gate.sh'
        Write-BashScript $sourceGate @("set -euo pipefail","export PATH=/usr/local/bin:/usr/bin:/bin:`$PATH","cd $(Quote-Bash $unixRepo)","export OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE=1","export OPENGEUL_FIREBIRD_SOURCE_ARCHIVE=$(Quote-Bash $unixFb)","export OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES=$(Quote-Bash ($unixSource+'/external/firebird'))",'/usr/bin/python3 -m unittest suite.tests.test_firebird_arm64_port -v')
        $receipt.stage='real-source-port-tests'
        Invoke-CygwinScript $bash $cygpath $sourceGate $work (Join-Path $evidence 'source-port-tests')|Out-Null
        $receipt.firebirdSourcePortChecksExecuted=$true
        $receipt.stage='install-authenticated-source-hooks'
        $python=(Get-Command python -ErrorAction Stop).Source
        Invoke-LoggedCommand $python @((Join-Path $repo 'suite/engine-build/enable_firebird_arm64.py'),'--libreoffice-source',$source) $repo (Join-Path $evidence 'source-hooks')|Out-Null
        Write-BashScript (Join-Path $source 'autogen.input') @(Get-ConfigureArguments $unixDownloads)
        Copy-Item (Join-Path $source 'autogen.input') (Join-Path $evidence 'autogen.input')
        $configure=Join-Path $commands 'configure.sh'
        Write-BashScript $configure @('set -euo pipefail','export PATH=/usr/local/bin:/usr/bin:/bin:$PATH',"cd $(Quote-Bash $unixSource)",'./autogen.sh')
        $receipt.stage='native-configure'
        Invoke-CygwinScript $bash $cygpath $configure $work (Join-Path $evidence 'configure')|Out-Null
        $config=Join-Path $source 'config_host.mk'
        Copy-Item $config (Join-Path $evidence 'config_host.mk')
        $receipt.configuration=Assert-GeneratedConfiguration $config
        if(Test-Path (Join-Path $source 'config.log')) {Copy-Item (Join-Path $source 'config.log') (Join-Path $evidence 'config.log')}
        # Fail before any expensive compilation if this configured VS install
        # cannot supply a signed native runtime at least as new as its tools.
        $receipt.stage='selected-toolchain-app-local-crt-preflight'
        $compilerPath=Invoke-LoggedCommand $cygpath @('-w',$receipt.configuration.COMPATH) $work (Join-Path $evidence 'configured-msvc-root')
        $nativeCompilerRoot=(Get-Content -LiteralPath $compilerPath.stdout -Raw).Trim()
        $receipt.crtPreflight=Get-AppLocalCrtPlan $nativeCompilerRoot $receipt.configuration.VCTOOLSET
        Write-BuildJson (Join-Path $evidence 'app-local-crt-preflight.json') $receipt.crtPreflight
        $crtTerms=Join-Path $evidence 'Microsoft-VC145-redistribution.html'
        $receipt.crtRedistributionTerms=Save-VcRedistributionTerms $crtTerms
        # Resolve the exact source download.lst variables with GNU make rather
        # than guessing version substitutions in Python/pip/bootstrap filenames.
        $makePins=Join-Path $commands 'source-inputs.mk'
        Write-BashScript $makePins @('include download.lst','$(foreach name,$(filter %_TARBALL,$(.VARIABLES)),$(info PIN|$(name)|$($(name))|$($(patsubst %_TARBALL,%_SHA256SUM,$(name)))))','pins:',"`t@true")
        $unixMakePins=&$convert $makePins 'source-input-makefile'
        $pinScript=Join-Path $commands 'source-input-pins.sh'
        Write-BashScript $pinScript @('set -euo pipefail',"cd $(Quote-Bash $unixSource)","make --no-print-directory -f $(Quote-Bash $unixMakePins) pins")
        $pinOutput=Invoke-CygwinScript $bash $cygpath $pinScript $work (Join-Path $evidence 'external-source-pins')
        $knownPins=@{([IO.Path]::GetFileName($archive))=$pin.sha256;([IO.Path]::GetFileName($fb))=$manifest.firebird.sha256}
        foreach($extra in Get-ExtraSourcePins) {$knownPins[$extra.filename]=$extra.sha256}
        foreach($target in Get-BuildTargets $Phase) {
            $receipt.stage='make-'+$target
            $script=Join-Path $commands ($target+'.sh')
            Write-BashScript $script @('set -euo pipefail','export PATH=/usr/local/bin:/usr/bin:/bin:$PATH',"cd $(Quote-Bash $unixSource)","make -j$Jobs $target")
            Invoke-CygwinScript $bash $cygpath $script $work (Join-Path $evidence ('make-'+$target))|Out-Null
            if($target -eq 'firebird') {
                $fbOutput=Join-Path $source 'workdir/UnpackedTarball/firebird/gen/Release/firebird'
                $receipt.firebirdPe=@('bin/ifbclient.dll','plugins/Engine12.dll','intl/fbintl.dll')|ForEach-Object {
                    $pe=Get-ProductPeIdentity (Join-Path $fbOutput $_)
                    if($pe.role -ne 'nativeArm64') {throw 'Firebird engine/client/intl DLLs must be native ARM64.'}
                    $pe
                }
                $isql=Join-Path $fbOutput 'bin/isql.exe'
                $receipt.isql=[ordered]@{available=(Test-Path $isql);verified=$false}
                if(Test-Path $isql) {
                    $receipt.firebirdAppLocalCrt=Install-AppLocalCrt $receipt.crtPreflight (Join-Path $fbOutput 'bin') $crtTerms
                    $receipt.isql.pe=Get-ProductPeIdentity $isql
                    $sql=Get-IsqlSql (Join-Path $work 'isql-proof.fdb')
                    $createSql=Join-Path $work 'isql-create.sql';$verifySql=Join-Path $work 'isql-verify.sql'
                    $sql.create|Set-Content $createSql -Encoding ascii;$sql.verify|Set-Content $verifySql -Encoding ascii
                    $oldFirebird=$env:FIREBIRD
                    try {
                        $env:FIREBIRD=$fbOutput
                        Invoke-LoggedCommand $isql @('-b','-q','-i',$createSql) $fbOutput (Join-Path $evidence 'isql-create')|Out-Null
                        $query=Invoke-LoggedCommand $isql @('-b','-q','-user','SYSDBA','-password','masterkey','-i',$verifySql,(Join-Path $work 'isql-proof.fdb')) $fbOutput (Join-Path $evidence 'isql-reopen')
                        Assert-IsqlOutput $query.stdout;$receipt.isql.verified=$true
                    } finally {$env:FIREBIRD=$oldFirebird}
                }
            }
        }
        if($Phase -eq 'Full') {
            $receipt.stage='authenticate-all-downloaded-source-archives'
            $receipt.externalSources=Write-ExternalSourceInventory $downloads $pinOutput.stdout (Join-Path $evidence 'external-source-inventory.json') $knownPins (Join-Path $source 'workdir/UnpackedTarball/python3') -RequirePython
            Copy-Item (Join-Path $source 'download.lst') (Join-Path $evidence 'authenticated-download.lst')
            $receipt.stage='stage-authenticated-native-app-local-crt'
            $instdir=Join-Path $source 'instdir'
            $receipt.appLocalCrt=Install-AppLocalCrt $receipt.crtPreflight (Join-Path $instdir 'program') $crtTerms
            Write-BuildJson (Join-Path $evidence 'app-local-crt-installed.json') $receipt.appLocalCrt
            $receipt.stage='native-product-pe-audit'
            foreach($relative in @('program/soffice.bin','program/python.exe','program/pyuno.pyd','program/ifbclient.dll','program/Engine12.dll','program/intl/fbintl.dll')) {
                $critical=Get-ProductPeIdentity (Join-Path $instdir $relative)
                if($critical.role -ne 'nativeArm64') {throw "Required native runtime output has wrong architecture: $relative"}
            }
            $inventory=@()
            foreach($file in Get-ChildItem -LiteralPath $instdir -File -Recurse) {
                $stream=$file.OpenRead();try {$first=$stream.ReadByte();$second=$stream.ReadByte()} finally {$stream.Dispose()}
                if(($first -eq 77 -and $second -eq 90) -or $file.Extension -in @('.exe','.dll','.pyd') -or $file.Name -eq 'soffice.bin') {$inventory+=Get-ProductPeIdentity $file.FullName $instdir}
            }
            if($inventory.Count -eq 0) {throw 'Native PE inventory is empty.'}
            Write-BuildJson (Join-Path $evidence 'native-pe-inventory.json') $inventory
            $receipt.productPeCount=$inventory.Count
            $receipt.nativePeCount=@($inventory|Where-Object {$_.role -eq 'nativeArm64'}).Count
            $receipt.managedAnyCpuCount=@($inventory|Where-Object {$_.role -eq 'managedAnyCpu'}).Count
            $receipt.pinnedTemplateCount=@($inventory|Where-Object {$_.role -eq 'pythonLauncherTemplate'}).Count
            $receipt.stage='actual-native-uno-base-persistence'
            $probe=Join-Path $evidence 'native-base-proof.py';Write-BaseProofScript $probe
            $proof=Join-Path $evidence 'native-base-proof.json'
            Invoke-LoggedCommand (Join-Path $instdir 'program/python.exe') @($probe,$repo,$instdir,$proof,(Join-Path $work 'base-proof')) $instdir (Join-Path $evidence 'native-base-proof')|Out-Null
            $receipt.baseProof=Assert-BaseProof $proof
            $receipt.stage='package-qualified-source-build'
            $zip=Join-Path $evidence 'OpenGeul-Office-engine-arm64.zip'
            if(Test-Path $zip) {throw 'Engine artifact already exists.'}
            [IO.Compression.ZipFile]::CreateFromDirectory($instdir,$zip,[IO.Compression.CompressionLevel]::Fastest,$false)
            $receipt.artifact=[ordered]@{path=$zip;size=(Get-Item $zip).Length;sha256=(Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()}
            $receipt.fullEngineQualified=$true
        }
        $receipt.status=if($Phase -eq 'Full'){'native-engine-source-build-qualified'}else{'native-firebird-pe-built-full-engine-unqualified'}
        $receipt.passed=$true;$receipt.stage='complete'
    } catch {$receipt.error=$_.Exception.ToString();throw}
    finally {
        if($source -and (Test-Path -LiteralPath $source)) {
            foreach($name in @('config_host.mk','config.log','autogen.input')) {
                $candidate=Join-Path $source $name
                if(Test-Path -LiteralPath $candidate) {Copy-Item -LiteralPath $candidate -Destination (Join-Path $evidence $name) -Force}
            }
            $fbLog=Join-Path $source 'workdir/UnpackedTarball/firebird/build.log'
            if(Test-Path -LiteralPath $fbLog) {Copy-Item -LiteralPath $fbLog -Destination (Join-Path $evidence 'firebird-build.log')}
        }
        $receipt.finishedUtc=[DateTime]::UtcNow.ToString('o')
        Write-BuildJson (Join-Path $evidence 'source-build-receipt.json') $receipt
    }
}

if($MyInvocation.InvocationName -ne '.') {
    Invoke-NativeEngineBuild $Phase $WorkDirectory $OutputDirectory $SourceLockPath $Jobs
}
