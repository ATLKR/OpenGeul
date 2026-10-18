param(
    [string]$WorkDirectory='.work/native-meson-receiver',
    [string]$OutputDirectory='.work/native-meson-receiver-evidence',
    [string]$DeadlineUtc=''
)
$ErrorActionPreference='Stop'
# The production driver's real InvocationName guard makes this import inert.
. (Join-Path $PSScriptRoot 'build-native-engine.ps1') -WorkDirectory $WorkDirectory -OutputDirectory $OutputDirectory -DeadlineUtc $DeadlineUtc

function Assert-MesonCompletion($Receipt,[int[]]$AllowedExitCodes=@(0)) {
    if($Receipt.pipeDrainComplete -ne $true -or $Receipt.forcedTermination -ne $false -or
       $Receipt.directProcessDeathVerified -ne $true -or $Receipt.processTreeCleanup -cne 'not-requested' -or
       @($Receipt.cleanupErrors).Count -ne 0 -or $null -eq $Receipt.exitCode -or
       $Receipt.exitCode -notin $AllowedExitCodes -or ($Receipt.exitCode -eq 0 -and $Receipt.passed -ne $true)) {
        throw 'Receiver observation requires a normal, drained, unforced owned command with an explicitly allowed exit code.'
    }
    return [ordered]@{succeeded=($Receipt.exitCode -eq 0);exitCode=$Receipt.exitCode;pid=$Receipt.pid;command=$Receipt}
}

function Invoke-MesonObservation([string]$File,[string[]]$Arguments,[string]$Work,[string]$Prefix,
                                [int[]]$AllowedExitCodes=@(0),[double]$Minutes=3) {
    try {Invoke-LoggedCommand $File $Arguments $Work $Prefix -TimeoutMinutes $Minutes|Out-Null}
    catch {if(-not(Test-Path -LiteralPath ($Prefix+'.command.json') -PathType Leaf)){throw}}
    $result=Assert-MesonCompletion (Get-Content -LiteralPath ($Prefix+'.command.json') -Raw|ConvertFrom-Json) $AllowedExitCodes
    $result.receipt=$Prefix+'.command.json';$result.stdout=$Prefix+'.stdout.log';$result.stderr=$Prefix+'.stderr.log'
    return $result
}

function Assert-MesonOriginalFailure([string]$Log,[string]$Compiler) {
    if($Compiler -cnotmatch '^/cygdrive/[a-z]/[^\s`]+/cl\.exe$') {throw 'Original compiler is not the demonstrated Cygwin executable.'}
    $text=[IO.File]::ReadAllText($Log);$escaped=[regex]::Escape($Compiler)
    if($text -notmatch ('ERROR: Unknown compiler\(s\):[^\r\n]*'+$escaped) -or
       $text -notmatch ('Running `'+$escaped+' /\?` gave "\[WinError 2\] [^\r\n]*"') -or
       $text -match 'access violation|stack overflow|internal compiler error|fatal error C1001') {
        throw 'Original failure is unrelated or ambiguous; compiler-path RED is inconclusive.'
    }
    return [ordered]@{classification='observed-original-compiler-path-winerror2';log=$Log;compiler=$Compiler}
}

function Assert-MesonNativeIdentity($Identity) {
    if($Identity.processMachine -ne 0 -or $Identity.nativeMachine -ne 0xaa64 -or
       $Identity.pid -le 0 -or $Identity.creationTimeRawTicks -isnot [string] -or
       $Identity.creationTimeRawTicks -cnotmatch '^[1-9][0-9]{15,19}$') {
        throw 'Actual native Python/target PID, raw64-bit creation ticks and IsWow64Process2(0,AA64) are required.'
    }
    [uint64]$ticks=0
    if(-not [uint64]::TryParse($Identity.creationTimeRawTicks,[ref]$ticks) -or $ticks -eq 0) {throw 'Raw process creation FILETIME is invalid.'}
    return $Identity
}

function Assert-MesonFixtureQueries($Queries,[string]$Dependencies) {
    $root=$Dependencies.Replace('\','/').TrimEnd('/')
    $versions=@($Queries.versions.stdout.Trim() -split '\r?\n')
    $paths=@($Queries.paths.stdout.Trim() -split '\r?\n'|ForEach-Object {$_.Replace('\','/')})
    $expected=@(($root+'/graphite/graphite2-uninstalled.pc'),($root+'/icu/icu-uc-uninstalled.pc'))
    if($Queries.'tool-version'.stdout.Trim() -cne '2.4.3' -or
       $versions.Count -ne 2 -or $versions[0] -cne '1.3.15' -or $versions[1] -cne '78.3' -or
       $paths.Count -ne 2 -or $paths[0] -ine $expected[0] -or $paths[1] -ine $expected[1] -or
       $Queries.'graphite-sentinel'.stdout.Trim() -cne 'graphite' -or $Queries.'icu-sentinel'.stdout.Trim() -cne 'icu' -or
       $Queries.'prefix-path'.stdout.Trim().Replace('\','/') -ine ($root+'/prefix pc/prefix-control.pc') -or
       [string]::IsNullOrWhiteSpace($Queries.cflags.stdout) -or [string]::IsNullOrWhiteSpace($Queries.libs.stdout)) {
        throw 'Candidate pkgconf did not select the exact nonempty samefixture Graphite/ICU/prefix entries.'
    }
    return [ordered]@{passed=$true;pkgconfVersion='2.4.3';selectedPaths=$paths;versions=$versions;prefixPreserved=$true}
}

function Get-MesonFileIdentity([string]$Path) {
    Assert-UnlinkedPath $Path
    $data=[IO.File]::ReadAllBytes($Path)
    if($data.Length -lt 64 -or $data[0] -ne 77 -or $data[1] -ne 90){throw 'Build helper is not PE.'}
    [long]$pe=[BitConverter]::ToUInt32($data,60)
    if($pe -lt 64 -or $pe+26 -gt $data.Length -or [BitConverter]::ToUInt32($data,[int]$pe) -ne 17744){throw 'Build helper PE header is invalid.'}
    return [ordered]@{path=[IO.Path]::GetFullPath($Path);size=$data.Length;sha256=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant();
        machine=[int][BitConverter]::ToUInt16($data,[int]$pe+4);role='build helper, not product payload';fileVersion=(Get-Item -LiteralPath $Path).VersionInfo.FileVersion}
}

function Convert-MesonPath([string]$Cygpath,[string]$Path,[string]$Mode,[string]$Work,[string]$Evidence,[string]$Name) {
    $r=Invoke-MesonObservation $Cygpath @($Mode,$Path) $Work (Join-Path $Evidence ('path-'+$Name))
    $value=([IO.File]::ReadAllText($r.stdout)).Trim()
    if(-not $value -or $value -match '[\r\n]'){throw 'Cygpath did not return one nonempty path.'}
    return $value
}

function Invoke-MesonMake([string]$Makefile,[string]$Bash,[string]$Cygpath,[string]$Work,[string]$Evidence,[string]$Name,[int[]]$Allowed=@(0)) {
    $unix=Convert-MesonPath $Cygpath $Makefile '-u' $Work $Evidence ($Name+'-makefile')
    $script=Join-Path $Evidence ($Name+'.sh')
    Write-BashScript $script @('set -euo pipefail','export PATH=/usr/local/bin:/usr/bin:/bin:$PATH',
        ('/usr/bin/make --no-print-directory --no-builtin-rules --no-builtin-variables -f '+(Quote-Bash $unix)))
    $unixScript=Convert-MesonPath $Cygpath $script '-u' $Work $Evidence ($Name+'-script')
    return Invoke-MesonObservation (Join-Path (Split-Path $Bash -Parent) 'env.exe') @('CYGWIN=winsymlinks:nativestrict',$Bash,'--noprofile','--norc',$unixScript) $Work (Join-Path $Evidence $Name) $Allowed
}

function Get-MesonPkgFixturePlan([string]$Dependencies,[string]$Work,[string]$Macro,$Flags) {
    # GNU make's file function stops its filename at the first whitespace.
    # Only its output operands are staged; the authentic macro and PC values
    # retain the same physical native paths, including spaces.
    $files=@(
        @{staged=(Join-Path $Work 'pc-stage-graphite.pc');destination=(Join-Path $Dependencies 'graphite/graphite2-uninstalled.pc')},
        @{staged=(Join-Path $Work 'pc-stage-icu.pc');destination=(Join-Path $Dependencies 'icu/icu-uc-uninstalled.pc')},
        @{staged=(Join-Path $Work 'pc-stage-prefix.pc');destination=(Join-Path $Dependencies 'prefix pc/prefix-control.pc')})
    $body=$Macro+"`n"+'$(file >pc-stage-graphite.pc,$('+'call gb_pkgconfig_file,graphite2,1.3.15,'+$Flags.graphite[0]+','+$Flags.graphite[1]+',fixture_control=graphite))'+"`n"+
        '$(file >pc-stage-icu.pc,$('+'call gb_pkgconfig_file,icu-uc,78.3,'+$Flags.icu[0]+','+$Flags.icu[1]+',fixture_control=icu))'+"`n"+
        '$(file >pc-stage-prefix.pc,$('+'call gb_pkgconfig_file,prefix-control,1.0,-DPREFIX_CONTROL, -L"'+$Dependencies.Replace('\','/')+'",fixture_control=prefix))'+"`nall:`n`t@true`n"
    return [ordered]@{makeText=$body;files=$files;makeCwd=$Work}
}

function Assert-MesonFreshFile([string]$Path) {
    Assert-UnlinkedPath $Path
    if($null -ne (Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue)) {throw ('Fresh fixture output required: '+$Path)}
}

function Install-MesonPcStage([string]$Stage,[string]$Destination) {
    Assert-UnlinkedPath $Stage
    $item=Get-Item -LiteralPath $Stage -Force
    if($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -le 0 -or $item.Length -gt 65536) {
        throw 'A nonempty bounded unlinked staged PC file is required.'
    }
    $partial=$Destination+'.control-partial'
    Assert-MesonFreshFile $Destination;Assert-MesonFreshFile $partial
    $bytes=[IO.File]::ReadAllBytes($Stage)
    $stream=[IO.File]::Open($partial,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {$stream.Write($bytes,0,$bytes.Length);$stream.Flush()} finally {$stream.Dispose()}
    # Same-directory rename without overwrite; retain a partial file on failure.
    [IO.File]::Move($partial,$Destination,$false)
    $placed=[IO.File]::ReadAllBytes($Destination)
    if([Convert]::ToHexString($bytes) -cne [Convert]::ToHexString($placed)) {throw 'Atomic PC placement changed staged bytes.'}
    return [ordered]@{path=$Destination;stagedPath=$Stage;bytes=$placed.Length;
        stagedSha256=(Get-FileHash -LiteralPath $Stage -Algorithm SHA256).Hash.ToLowerInvariant();
        sha256=(Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant();
        freshDestination=$true;unlinked=$true;byteIdentical=$true;atomicPlacement=$true}
}

function Save-MesonCrossFile([string]$Expected,[string]$Unexpected,[string]$Evidence,[string]$Name) {
    $record=[ordered]@{passed=$false;makeOutput='authentic full recipe cross-file';intended=$null;unexpected=$null}
    foreach($entry in @(@('intended',$Expected),@('unexpected',$Unexpected))) {
        $key=$entry[0];$path=$entry[1];$part=[ordered]@{path=$path;present=$false;valid=$false}
        try {
            $item=Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            if($null -ne $item) {
                $part.present=$true;Assert-UnlinkedPath $path
                if($item.PSIsContainer -or $item.Length -gt 65536) {throw 'Unexpected cross-file output type/size.'}
                $part.snapshot=Join-Path $Evidence ($Name+'-cross-file-'+$key+'.txt')
                Assert-MesonFreshFile $part.snapshot
                $bytes=[IO.File]::ReadAllBytes($path)
                [IO.File]::WriteAllBytes($part.snapshot,$bytes)
                $part.bytes=$bytes.Length;$part.sha256=(Get-FileHash -LiteralPath $part.snapshot -Algorithm SHA256).Hash.ToLowerInvariant()
                $part.valid=($bytes.Length -gt 0)
            }
        } catch {$part.error=$_.Exception.ToString()}
        $record[$key]=$part
    }
    $record.passed=($record.intended.present -and $record.intended.valid -and -not $record.unexpected.present -and -not $record.unexpected.error)
    Write-BuildJson (Join-Path $Evidence ($Name+'-cross-file.json')) $record
    return $record
}

function Invoke-MesonRecipeMake($Observation,[string]$Bash,[string]$Cygpath,[string]$Evidence,[string]$Name,[int[]]$Allowed,$PriorCrossFile) {
    # All observations use the same authentic cross-file target. Retain it
    # after each make, then verify that snapshot before removing our prior
    # generated file so the next observation must create its own output.
    if($null -ne (Get-Item -LiteralPath $Observation.crossFile -Force -ErrorAction SilentlyContinue)) {
        if($null -eq $PriorCrossFile -or $PriorCrossFile.passed -ne $true) {
            Save-MesonCrossFile $Observation.crossFile $Observation.unexpectedSibling $Evidence ($Name+'-preexisting')|Out-Null
            throw 'An unaccounted cross-file precedes this observation.'
        }
        Assert-UnlinkedPath $Observation.crossFile
        Confirm-FileIdentity $Observation.crossFile $PriorCrossFile.intended.bytes SHA256 $PriorCrossFile.intended.sha256|Out-Null
        Remove-Item -LiteralPath $Observation.crossFile -ErrorAction Stop
    }
    if($null -ne (Get-Item -LiteralPath $Observation.unexpectedSibling -Force -ErrorAction SilentlyContinue)) {
        Save-MesonCrossFile $Observation.crossFile $Observation.unexpectedSibling $Evidence ($Name+'-preexisting')|Out-Null
        throw 'An unexpected sibling output precedes this observation.'
    }
    $commandError=$null;$result=$null
    try {$result=Invoke-MesonMake $Observation.makefile $Bash $Cygpath $Observation.directory $Evidence $Name $Allowed}
    catch {$commandError=$_}
    $cross=Save-MesonCrossFile $Observation.crossFile $Observation.unexpectedSibling $Evidence $Name
    if($null -ne $commandError) {throw $commandError}
    if(-not $cross.passed) {throw 'The authentic cross-file output is missing, invalid or misplaced; observation is inconclusive.'}
    $result.crossFile=$cross
    return $result
}

function New-MesonDependencyFixtures([string]$Dependencies,[string]$Compiler,[string]$Librarian,[string]$VsBatch,[string]$Work,[string]$Evidence,[string]$Bash,[string]$Cygpath) {
    $libraries=@();$flags=@{}
    foreach($item in @(@('graphite',17,'receiver_graphite_fixture','graphite-fixture.h'),@('icu',19,'receiver_icu_fixture','icu-fixture.h'))) {
        $name=$item[0];$directory=Join-Path $Dependencies $name
        foreach($part in @('include space','source/i18n space','source/common space','source/lib space')) {New-Item -ItemType Directory -Force (Join-Path $directory $part)|Out-Null}
        $include=if($name -eq 'graphite'){Join-Path $directory 'include space'}else{Join-Path $directory 'source/common space'}
        @('#ifdef __cplusplus','extern "C" {','#endif',('int '+$item[2]+'(void);'),'#ifdef __cplusplus','}','#endif')|Set-Content -LiteralPath (Join-Path $include $item[3]) -Encoding utf8NoBOM
        $source=Join-Path $directory 'fixture.c';('int '+$item[2]+'(void) { return '+$item[1]+'; }')|Set-Content -LiteralPath $source -Encoding utf8NoBOM
        $object=Join-Path $directory 'fixture.obj';$library=Join-Path $directory ('source/lib space/receiver-'+$name+'.lib')
        $batch=Join-Path $Evidence ($name+'-fixture.cmd')
        @('@echo off',('call "'+$VsBatch+'" >nul'), 'if errorlevel 1 exit /b 1',
          ('"'+$Compiler+'" /nologo /MD /c "'+$source+'" /Fo"'+$object+'"'), 'if errorlevel 1 exit /b 1',
          ('"'+$Librarian+'" /nologo /machine:arm64 /out:"'+$library+'" "'+$object+'"'), 'exit /b %errorlevel%')|Set-Content -LiteralPath $batch -Encoding ascii
        Invoke-MesonObservation (Join-Path $env:SystemRoot 'System32/cmd.exe') @('/d','/c',$batch) $Work (Join-Path $Evidence ($name+'-fixture-build'))|Out-Null
        $libraries+=Get-Arm64ImportLibrary $library
        $forward=$include.Replace('\','/');$libForward=$library.Replace('\','/')
        $flags[$name]=if($name -eq 'graphite'){@(('-I"'+$forward+'" -DGRAPHITE2_STATIC'),('"'+$libForward+'"'))}else{@(('-I"'+(Join-Path $directory 'source/i18n space').Replace('\','/')+'" -I"'+$forward+'"'),('-L"'+(Split-Path $library -Parent).Replace('\','/')+'" -lreceiver-icu'))}
    }
    $macro=[IO.File]::ReadAllText((Join-Path $Evidence 'gb-pkgconfig-file.mk'))
    $make=Join-Path $Evidence 'pkg-fixtures.mk'
    $plan=Get-MesonPkgFixturePlan $Dependencies $Work $macro $flags
    Write-BuildJson (Join-Path $Evidence 'pkg-fixtures-plan.json') $plan
    foreach($file in $plan.files) {Assert-MesonFreshFile $file.staged;Assert-MesonFreshFile $file.destination;Assert-MesonFreshFile ($file.destination+'.control-partial')}
    [IO.File]::WriteAllText($make,$plan.makeText,[Text.UTF8Encoding]::new($false))
    Invoke-MesonMake $make $Bash $Cygpath $Work $Evidence 'pkg-fixtures'|Out-Null
    $placed=@($plan.files|ForEach-Object {Install-MesonPcStage $_.staged $_.destination})
    return [ordered]@{scope='explicit ARM64 dependency fixtures, not actual Graphite/ICU qualification';libraries=$libraries;
        pcFiles=$placed;plan=(Join-Path $Evidence 'pkg-fixtures-plan.json')}
}

function Invoke-NativeMesonReceiverControl([string]$WorkDirectory,[string]$OutputDirectory,[string]$DeadlineUtc) {
    $paths=New-BuildDirectories $WorkDirectory $OutputDirectory;$work=$paths.work;$evidence=$paths.output
    $repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'));$previousBudget=$script:NativeEngineBuildBudget
    $fixture=Join-Path $repo 'suite/diagnostics/native-meson-receiver';$preparation=$null
    $receipt=[ordered]@{schemaVersion=1;scope='component-receiver-feasibility-only';status='failed';classification='inconclusive';stage='budget';passed=$false;
        componentReceiverFeasible=$false;native23ExactRuntimeEquivalent=$false;fullHarfBuzzOptionsExecuted=$false;
        harfbuzzSetupProven=$false;harfbuzzCompileProven=$false;fullNative24Required=$true;engineQualified=$false;startedUtc=[DateTime]::UtcNow.ToString('o');retentionErrors=@()}
    try {
        if(-not $DeadlineUtc){throw 'The first workflow step must supply the shared 18-minute deadline.'}
        $script:NativeEngineBuildBudget=New-NativeBuildBudget $DeadlineUtc 18;$receipt.budget=$script:NativeEngineBuildBudget.record
        if($env:OPENGEUL_MESON_CONTROL_BUDGET_RECEIPT){Copy-Item -LiteralPath $env:OPENGEUL_MESON_CONTROL_BUDGET_RECEIPT -Destination (Join-Path $evidence 'job-budget.json')}
        $receipt.stage='native-controller';$receipt.host=Get-NativeBuildHost
        $receipt.stage='immutable-source-binding'
        $receipt.source=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'probe-native-meson-receiver.ps1') (Join-Path $fixture 'source-inputs.json') $evidence
        $base=(Get-Content -LiteralPath (Join-Path $fixture 'source-inputs.json') -Raw|ConvertFrom-Json).productionBaseCommit
        if($base -cnotmatch '^[0-9a-f]{40}$'){throw 'An approved immutable production base is required.'}
        Invoke-MesonObservation (Get-Command git).Source @('merge-base','--is-ancestor',$base,'HEAD') $repo (Join-Path $evidence 'approved-production-base')|Out-Null
        $receipt.productionBaseCommit=$base
        $python=(Get-Command python -ErrorAction Stop).Source;$receipt.python=Get-ProductPeIdentity $python
        $receipt.python.provenance='setup-python native ARM64 3.12 substitution; not Native23 bundled Python equivalence'
        $downloads=Join-Path $work 'downloads';New-Item -ItemType Directory $downloads|Out-Null
        $receipt.stage='authenticated-meson-pkgconf'
        $archive=Join-Path $downloads 'meson-1.8.3.tar.gz'
        $receipt.meson=Get-AuthenticatedDownload 'https://files.pythonhosted.org/packages/source/m/meson/meson-1.8.3.tar.gz' $archive 2335924 SHA256 'f118aa910fc0a137cc2dd0122232dbf82153d9a12fb5b0f5bb64896f6a157abf' (Join-Path $evidence 'meson-download.json')
        $tar=(Get-Command tar -ErrorAction Stop).Source
        Invoke-MesonObservation $tar @('-xzf',$archive,'-C',$downloads) $work (Join-Path $evidence 'extract-meson')|Out-Null
        $meson=Join-Path $downloads 'meson-1.8.3/meson.py'
        $pin=Get-WindowsPkgconfPin;$pkgconf=Join-Path $downloads $pin.filename
        $receipt.pkgconf=Get-AuthenticatedDownload $pin.url $pkgconf $pin.size SHA256 $pin.sha256 (Join-Path $evidence 'pkgconf-download.json')
        $receipt.pkgconf.pe=Get-WindowsBuildToolPeIdentity $pkgconf
        $receipt.stage='selected-vs-build-helpers'
        $vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
        $vs=Invoke-MesonObservation $vswhere @('-all','-products','*','-format','json') $work (Join-Path $evidence 'vs-instances')
        $instances=@(Get-Content -LiteralPath $vs.stdout -Raw|ConvertFrom-Json|Where-Object {$_.isComplete -eq $true -and $_.isPrerelease -eq $false -and $_.installationVersion -match '^18\.'})
        if($instances.Count -ne 1){throw 'Exactly one complete stable VS18 installation is required.'}
        $vsRoot=$instances[0].installationPath;$versionFile=Join-Path $vsRoot 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'
        $toolVersion=([IO.File]::ReadAllText($versionFile)).Trim();$tools=Join-Path $vsRoot ('VC/Tools/MSVC/'+$toolVersion+'/bin/Hostarm64/arm64')
        $compiler=Join-Path $tools 'cl.exe';$librarian=Join-Path $tools 'lib.exe';$vsBatch=Join-Path $vsRoot 'VC/Auxiliary/Build/vcvarsarm64.bat'
        $receipt.selectedToolchain=@{root=$vsRoot;installationVersion=$instances[0].installationVersion;toolVersion=$toolVersion;versionFileSha256=(Get-FileHash -LiteralPath $versionFile -Algorithm SHA256).Hash.ToLowerInvariant()}
        $receipt.buildHelpers=@('cl.exe','link.exe','lib.exe')|ForEach-Object {Get-MesonFileIdentity (Join-Path $tools $_)}
        $receipt.stage='authenticated-cygwin-make'
        $setup=Join-Path $downloads 'setup-x86_64.exe'
        $receipt.cygwinSetup=Get-AuthenticatedDownload 'https://cygwin.com/setup-x86_64.exe' $setup 0 SHA512 '6acea47c59781c9e7f544a18d53935d59df6e44d5d52ac95ee165671b8e388820455eebf30ccc7d254b00c3d0eb694269a0f8dc84b17944c1f355dac9c5aafcc' (Join-Path $evidence 'cygwin-download.json')
        $cygwin=Join-Path $work 'cygwin'
        Invoke-MesonObservation $setup @('--quiet-mode','--no-admin','--no-shortcuts','--no-startmenu','--no-desktop','--root',$cygwin,'--local-package-dir',(Join-Path $work 'cygwin-cache'),'--site','https://mirrors.kernel.org/sourceware/cygwin/','--packages','bash,make') $work (Join-Path $evidence 'cygwin-setup') @(0) 6|Out-Null
        $bash=Join-Path $cygwin 'bin/bash.exe';$cygpath=Join-Path $cygwin 'bin/cygpath.exe'
        $commands=Join-Path $work 'commands';New-Item -ItemType Directory $commands|Out-Null
        $receipt.cygwinIdentity=Get-CygwinIdentity $bash $cygpath $commands $work $evidence
        if($receipt.cygwinIdentity.operatingSystem -cne 'Cygwin'){throw 'Actual Cygwin helpers are required.'}
        $receipt.cygwinFiles=@('bash.exe','cygpath.exe','make.exe','env.exe','cygwin1.dll')|ForEach-Object {Get-MesonFileIdentity (Join-Path $cygwin ('bin/'+$_))}
        # Same two conversions as authentic win_short_path_for_make's Cygwin
        # branch; -s is only supported with native output, not POSIX -u.
        $dosCompiler=Convert-MesonPath $cygpath $compiler '-d' $work $evidence 'short-native-compiler'
        $configured=Convert-MesonPath $cygpath $dosCompiler '-u' $work $evidence 'configured-compiler'
        $long=Convert-MesonPath $cygpath $configured '-lm' $work $evidence 'native-long-compiler'
        if($long -notmatch ' ' -or [IO.Path]::GetFullPath($long) -ine [IO.Path]::GetFullPath($compiler)){throw 'Actual same compiler long path with spaces was not established.'}
        $pythonUnix=Convert-MesonPath $cygpath (Split-Path $python -Parent) '-u' $work $evidence 'python-directory'
        $systemUnix=Convert-MesonPath $cygpath (Join-Path $env:SystemRoot 'System32') '-u' $work $evidence 'system-directory'
        $receipt.stage='production-planner-output-control-local-write'
        Invoke-MesonObservation $python @((Join-Path $fixture 'prepare.py'),'--repo',$repo,'--work',$work,'--evidence',$evidence,'--python',$python,'--meson',$meson,'--pkgconf',$pkgconf,'--cc',$configured,'--python-search-path',($pythonUnix+':'+$systemUnix)) $work (Join-Path $evidence 'prepare-source')|Out-Null
        $preparation=Get-Content -LiteralPath (Join-Path $evidence 'source-preparation.json') -Raw|ConvertFrom-Json
        $receipt.sourcePreparation=$preparation
        $receipt.stage='explicit-dependency-fixtures'
        $receipt.dependencyFixtures=New-MesonDependencyFixtures $preparation.dependencies $compiler $librarian $vsBatch $work $evidence $bash $cygpath
        $receipt.stage='authentic-source-recipe-capture'
        $receipt.observations=@();$priorCrossFile=$null
        foreach($observation in @($preparation.observations|Where-Object mode -eq 'capture')) {
            Confirm-FileIdentity $observation.makefile 0 SHA256 $observation.makefileSha256|Out-Null
            $result=Invoke-MesonRecipeMake $observation $bash $cygpath $evidence ($observation.arm+'-capture') @(0) $priorCrossFile
            $priorCrossFile=$result.crossFile
            $makeHost=([IO.File]::ReadAllText((Join-Path $observation.directory 'builtin-make-host.txt'))).Trim()
            if($makeHost -notmatch '-cygwin$'){throw 'Real built-in Cygwin MAKE_HOST was not observed.'}
            $receipt.observations+=@{arm=$observation.arm;mode='capture';makeHost=$makeHost;command=$result}
        }
        Invoke-MesonObservation $python @((Join-Path $fixture 'receiver.py'),'compare','--original',$evidence,'--candidate',$evidence,'--output',(Join-Path $evidence 'recipe-parity.json')) $work (Join-Path $evidence 'recipe-parity')|Out-Null
        $receipt.stage='independent-samefixture-pkgconf-list-arms';$receipt.pkgQueries=@()
        $queries=@(@('tool-version','--version'),@('exists','--exists','graphite2','icu-uc'),@('versions','--modversion','graphite2','icu-uc'),@('paths','--path','graphite2','icu-uc'),@('cflags','--cflags','graphite2','icu-uc'),@('libs','--libs','graphite2','icu-uc'),@('graphite-sentinel','--variable=fixture_control','graphite2'),@('icu-sentinel','--variable=fixture_control','icu-uc'),@('prefix-path','--path','prefix-control'))
        foreach($arm in @('original','candidate')) {
            $armQueries=@{}
            foreach($query in $queries) {
                $queryArguments=@((Join-Path $fixture 'receiver.py'),'pkg-query','--capture',(Join-Path $evidence ($arm+'.capture.setup.json')),'--evidence',$evidence,'--arm',$arm,'--name',$query[0],'--')+@($query[1..($query.Count-1)])
                $r=Invoke-MesonObservation $python $queryArguments $work (Join-Path $evidence ($arm+'-pkg-'+$query[0])) @(0,1)
                $q=Get-Content -LiteralPath (Join-Path $evidence ($arm+'.pkg.'+$query[0]+'.json')) -Raw|ConvertFrom-Json
                Assert-MesonNativeIdentity $q.identity|Out-Null
                if($arm -eq 'candidate' -and -not $r.succeeded){throw 'Candidate exact pkgconf did not resolve the intended samefixture entries.'}
                $armQueries[$query[0]]=$q
                $receipt.pkgQueries+=@{arm=$arm;name=$query[0];result=$q;command=$r}
            }
            if($arm -eq 'candidate'){$receipt.sameFixtureSelection=Assert-MesonFixtureQueries $armQueries $preparation.dependencies}
        }
        $receipt.stage='actual-native-compiler-receiver-arms'
        foreach($observation in @($preparation.observations|Where-Object mode -eq 'recipe')) {
            Confirm-FileIdentity $observation.makefile 0 SHA256 $observation.makefileSha256|Out-Null
            $allowed=if($observation.arm -eq 'original'){@(0,2)}else{@(0)}
            $result=Invoke-MesonRecipeMake $observation $bash $cygpath $evidence ($observation.arm+'-recipe') $allowed $priorCrossFile
            $priorCrossFile=$result.crossFile
            $record=Get-Content -LiteralPath (Join-Path $evidence ($observation.arm+'.recipe.setup.json')) -Raw|ConvertFrom-Json
            Assert-MesonNativeIdentity $record.identity|Out-Null
            $capture=Get-Content -LiteralPath (Join-Path $evidence ($observation.arm+'.capture.setup.json')) -Raw|ConvertFrom-Json
            foreach($key in @('CC','CXX','PKG_CONFIG','PKG_CONFIG_PATH','PATH')) {
                if($record.environment.$key -cne $capture.environment.$key){throw 'Actual receiver environment differs from complete recipe parity capture.'}
            }
            if($observation.arm -eq 'original') {
                if($result.exitCode -ne 2 -or $record.mesonReturncode -ne 1 -or $record.originalCompilerRed -ne $true){throw 'Baseline must reproduce exact WinError2 and ordinary make2; alternate result is inconclusive.'}
                $receipt.originalRed=Assert-MesonOriginalFailure (Join-Path $observation.directory 'builddir/meson-logs/meson-log.txt') $configured
            } else {
                $build=Join-Path $observation.directory 'builddir'
                $receipt.candidateCommand=$result
                $receipt.candidateCompilers=Get-Content -LiteralPath (Join-Path $build 'meson-info/intro-compilers.json') -Raw|ConvertFrom-Json
                foreach($language in @('c','cpp')) {
                    $entry=$receipt.candidateCompilers.host.$language
                    if(@($entry.exelist).Count -ne 1 -or [IO.Path]::GetFullPath($entry.exelist[0]) -ine [IO.Path]::GetFullPath($compiler)){throw 'Meson compiler array did not retain the single selected native compiler.'}
                }
                $receipt.candidateDependencies=Get-Content -LiteralPath (Join-Path $build 'meson-info/intro-dependencies.json') -Raw|ConvertFrom-Json
                $receipt.reachedBuildHelpers=Get-Content -LiteralPath (Join-Path $build 'reached-tools.json') -Raw|ConvertFrom-Json
                foreach($tool in @('link.exe','lib.exe')) {
                    $reached=$receipt.reachedBuildHelpers.tools.$tool
                    if([IO.Path]::GetFullPath($reached.path) -ine [IO.Path]::GetFullPath((Join-Path $tools $tool))){throw 'Meson activated a different linker/librarian toolchain.'}
                    Confirm-FileIdentity $reached.path $reached.size SHA256 $reached.sha256|Out-Null
                }
                if(-not $receipt.reachedBuildHelpers.tools.'ninja.exe'){throw 'Actual native Meson Ninja resolution was not captured.'}
                $probe=Join-Path $build 'receiver-probe.exe';$receipt.probePe=Get-ProductPeIdentity $probe
                $receipt.staticLibrary=Get-Arm64ImportLibrary (Join-Path $build 'receiver-parts.lib')
                $receipt.stage='actual-native-tiny-executable'
                $run=Invoke-MesonObservation $probe @() $build (Join-Path $evidence 'receiver-probe')
                $identity=Get-Content -LiteralPath $run.stdout -Raw|ConvertFrom-Json
                Assert-MesonNativeIdentity $identity|Out-Null
                if($identity.pid -ne $run.pid -or $identity.functionCheck -ne $true -or $identity.value -ne 54){throw 'Owned actual native executable did not prove both languages and fixture libraries.'}
                $receipt.probeProcess=@{identity=$identity;command=$run}
            }
        }
        $receipt.stage='verify-all-native-python-identities'
        foreach($path in Get-ChildItem -LiteralPath $evidence -Filter '*.capture.*.json') {Assert-MesonNativeIdentity (Get-Content -LiteralPath $path.FullName -Raw|ConvertFrom-Json).identity|Out-Null}
        Assert-NativeBuildTimeRemaining
        $receipt.status='component-receiver-feasible';$receipt.classification='component-receiver-feasible';$receipt.componentReceiverFeasible=$true;$receipt.passed=$true;$receipt.stage='complete'
    } catch {$receipt.error=$_.Exception.ToString();$receipt.failedStage=$receipt.stage;throw}
    finally {
        # Retain partial preparation too. Failure before source-preparation.json
        # must not erase the exact installed recipe or partially reached build.
        foreach($name in @('production-source','Dependency Fixtures','Dependency','pc-stage-graphite.pc','pc-stage-icu.pc','pc-stage-prefix.pc')) {
            $path=Join-Path $work $name
            if(Test-Path -LiteralPath $path) {
                try {Assert-UnlinkedPath $path;Copy-Item -LiteralPath $path -Destination (Join-Path $evidence $name) -Recurse -ErrorAction Stop}
                catch {$receipt.retentionErrors+=$_.Exception.ToString()}
            }
        }
        foreach($name in @('meson-1.8.3.tar.gz','pkgconf-2.4.3.exe','setup-x86_64.exe')) {
            $path=Join-Path $work ('downloads/'+$name)
            if(Test-Path -LiteralPath $path) {
                try {Copy-Item -LiteralPath $path -Destination (Join-Path $evidence $name) -ErrorAction Stop}
                catch {$receipt.retentionErrors+=$_.Exception.ToString()}
            }
        }
        try {
            Copy-Item -LiteralPath $fixture -Destination (Join-Path $evidence 'control-source') -Recurse -ErrorAction Stop
            foreach($name in @('enable_firebird_arm64.py','source-build.json')) {Copy-Item -LiteralPath (Join-Path $repo ('suite/engine-build/'+$name)) -Destination (Join-Path $evidence ('production-'+$name)) -ErrorAction Stop}
            foreach($name in @('probe-native-meson-receiver.ps1','build-native-engine.ps1')) {Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $evidence $name) -ErrorAction Stop}
            Copy-Item -LiteralPath (Join-Path $repo '.github/workflows/office-native-meson-receiver-control.yml') -Destination (Join-Path $evidence 'office-native-meson-receiver-control.yml') -ErrorAction Stop
        } catch {$receipt.retentionErrors+=$_.Exception.ToString()}
        if($receipt.retentionErrors.Count){$receipt.passed=$false;$receipt.componentReceiverFeasible=$false;$receipt.status='retention-incomplete';$receipt.classification='inconclusive-retention'}
        $receipt.finishedUtc=[DateTime]::UtcNow.ToString('o')
        if($script:NativeEngineBuildBudget){$receipt.elapsedSeconds=$script:NativeEngineBuildBudget.clock.Elapsed.TotalSeconds}
        Write-BuildJson (Join-Path $evidence 'receiver-control-receipt.json') $receipt
        $script:NativeEngineBuildBudget=$previousBudget
    }
    if(-not $receipt.passed){throw 'Native receiver control is incomplete; inspect original retained evidence.'}
}

if($MyInvocation.InvocationName -ne '.') {Invoke-NativeMesonReceiverControl $WorkDirectory $OutputDirectory $DeadlineUtc}
