param(
    [string]$WorkDirectory='.work/native-atl-control',
    [string]$OutputDirectory='.work/native-atl-evidence'
)
$ErrorActionPreference='Stop'
# The reviewed driver has a real InvocationName guard: dot-sourcing defines
# ownership/download/PE helpers without starting an engine build.
. (Join-Path $PSScriptRoot 'build-native-engine.ps1') -WorkDirectory $WorkDirectory -OutputDirectory $OutputDirectory

function Get-AtlToolchainPlan($Instances) {
    $selected=@($Instances|Where-Object {
        $_.isComplete -eq $true -and $_.isPrerelease -eq $false -and
        $_.installationVersion -match '^18\.' -and $_.productId -ceq 'Microsoft.VisualStudio.Product.Enterprise'
    })
    if($selected.Count -ne 1) {throw 'Exactly one complete stable VS18 installation is required; no other VS fallback.'}
    $instance=$selected[0];$root=[IO.Path]::GetFullPath($instance.installationPath)
    Assert-UnlinkedPath $root
    $default=Join-Path $root 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'
    Assert-UnlinkedPath $default
    $version=([IO.File]::ReadAllText($default)).Trim()
    if($version -cne '14.51.36231' -or $instance.installationVersion -cne '18.10.12224.181') {throw 'This native22 control is pinned to VS18.10.12224.181 / v145 14.51.36231; changed runner tools require review.'}
    $compilerRoot=Join-Path $root ('VC/Tools/MSVC/'+$version)
    Assert-UnlinkedPath $compilerRoot
    if(-not(Test-Path -LiteralPath $compilerRoot -PathType Container)) {throw 'Selected default MSVC toolset directory is missing.'}
    return [ordered]@{instanceId=$instance.instanceId;installationRoot=$root;installationVersion=$instance.installationVersion;
        compilerRoot=$compilerRoot;compilerVersion=$version;toolset='v145';defaultVersionFile=$default;
        defaultVersionSha256=(Get-FileHash -LiteralPath $default -Algorithm SHA256).Hash.ToLowerInvariant()}
}

function Get-AtlFile([string]$Path,[switch]$Library) {
    $record=[ordered]@{path=[IO.Path]::GetFullPath($Path);status='missing';bytes=$null;sha256=$null;machines=$null;error=$null}
    try {
        Assert-UnlinkedPath $Path
        if(-not(Test-Path -LiteralPath $Path)) {return $record}
        $file=Get-Item -LiteralPath $Path -Force
        $limit=if($Library){67108864}else{1048576}
        if($file.PSIsContainer -or $file.Length -le 0 -or $file.Length -gt $limit) {throw 'ATL census requires a bounded nonempty regular file.'}
        $record.bytes=$file.Length
        $record.sha256=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        if($Library) {$record.machines=@((Get-Arm64ImportLibrary $Path).machines)}
        $record.status='verified'
    } catch {$record.status='rejected';$record.error=$_.Exception.Message}
    return $record
}

function Get-AtlCensus([string]$CompilerRoot) {
    Assert-UnlinkedPath $CompilerRoot
    $include=Join-Path $CompilerRoot 'atlmfc/include'
    $headers=@('atlbase.h','atlcom.h','atlctl.h')|ForEach-Object {Get-AtlFile (Join-Path $include $_)}
    $regular=Get-AtlFile (Join-Path $CompilerRoot 'atlmfc/lib/arm64/atls.lib') -Library
    $spectre=Get-AtlFile (Join-Path $CompilerRoot 'atlmfc/lib/spectre/arm64/atls.lib') -Library
    # Match the authenticated configure.ac parent-directory selection exactly.
    $spectreParent=Join-Path $CompilerRoot 'atlmfc/lib/spectre'
    Assert-UnlinkedPath $spectreParent
    $selectSpectre=Test-Path -LiteralPath $spectreParent -PathType Container
    $selected=if($selectSpectre){$spectre}else{$regular}
    return [ordered]@{includeDirectory=$include;headers=@($headers);libraries=@($regular,$spectre);
        spectreParentExists=$selectSpectre;selectedLibrary=$selected;
        ready=(@($headers|Where-Object status -ne 'verified').Count -eq 0 -and $selected.status -eq 'verified')}
}

function Assert-AtlCommandCompletion($Receipt) {
    if($Receipt.pipeDrainComplete -ne $true -or $Receipt.forcedTermination -ne $false -or
        $Receipt.directProcessDeathVerified -ne $true -or $Receipt.processTreeCleanup -cne 'not-requested' -or
        @($Receipt.cleanupErrors).Count -ne 0 -or $null -eq $Receipt.exitCode) {
        throw 'ATL diagnostic requires normal, drained, unforced owned-command completion.'
    }
    # These observations own the direct Cygwin make invocation. Only GNU
    # make's expected failure exit 2 may proceed to the baseline text oracle.
    if($Receipt.exitCode -ne 0 -and $Receipt.exitCode -ne 2) {throw 'Direct make exit is neither successful zero nor expected diagnostic 2; ATL path handling is inconclusive.'}
    $succeeded=($Receipt.exitCode -eq 0 -and $Receipt.passed -eq $true)
    if($Receipt.exitCode -eq 0 -and -not $succeeded) {throw 'Zero exit code without a successful command receipt is unproved.'}
    return [ordered]@{succeeded=$succeeded;exitCode=$Receipt.exitCode}
}

function Invoke-AtlObservation([string]$File,[string[]]$Arguments,[string]$Work,[string]$Prefix,[double]$Minutes=2) {
    try {Invoke-LoggedCommand $File $Arguments $Work $Prefix -TimeoutMinutes $Minutes|Out-Null}
    catch {
        if(-not(Test-Path -LiteralPath ($Prefix+'.command.json') -PathType Leaf)) {throw}
    }
    $completion=Assert-AtlCommandCompletion (Get-Content -LiteralPath ($Prefix+'.command.json') -Raw|ConvertFrom-Json)
    $completion.commandReceipt=$Prefix+'.command.json';$completion.stdout=$Prefix+'.stdout.log';$completion.stderr=$Prefix+'.stderr.log'
    return $completion
}

function Assert-AtlArchiveExtraction([string]$Log,[string]$Library) {
    $expected=([IO.Path]::GetFullPath($Library)).Replace('\','/').ToLowerInvariant()
    foreach($line in [IO.File]::ReadAllLines($Log)) {
        if($line -match '^\s*Loaded\s+(.+?atls\.lib)\(([^)]+)\)\s*$') {
            $actual=$Matches[1].Trim().Replace('\','/').ToLowerInvariant();$member=$Matches[2]
            if($actual -ceq $expected) {return [ordered]@{library=$Library;member=$member;line=$line;log=$Log}}
        }
    }
    throw 'Linker output does not prove extraction from the selected ARM64 atls.lib.'
}

function Get-AtlControlConclusion([bool]$BaselineHeader,[bool]$CandidateHeader,[bool]$BaselineLink,[bool]$CandidateLink) {
    $finding='candidate-unproved'
    if($CandidateHeader -and $CandidateLink) {
        if(-not $BaselineHeader -and -not $BaselineLink) {$finding='configured-header-and-library-paths-unusable'}
        elseif(-not $BaselineHeader) {$finding='configured-header-path-unusable'}
        elseif(-not $BaselineLink) {$finding='configured-library-path-unusable'}
        else {$finding='atl-prerequisite-reproduced-no-path-failure'}
    }
    return [ordered]@{finding=$finding;fullEngineQualified=$false;guiVerified=$false;runtimeExecuted=$false}
}

function Assert-AtlExpectedFailure([string[]]$Logs,[ValidateSet('Header','Library')][string]$Kind) {
    $pattern=if($Kind -eq 'Header') {
        'atl-control\.cpp\(\d+\): fatal error C1083: Cannot open include file: [''"]atlbase\.h[''"]:'
    } else {'fatal error LNK(?:1104|1181): cannot open (?:input )?file [''"][^''"\r\n]*atls\.lib[''"]'}
    $found=@();$bad=@()
    foreach($log in $Logs) {
        foreach($line in [IO.File]::ReadAllLines($log)) {
            if($line -match $pattern) {$found+=@{kind=$Kind;line=$line;log=$log}}
            if($line -match 'access violation|stack overflow|internal compiler error|fatal error C1001') {$bad+=,$line}
        }
    }
    if($found.Count -ne 1 -or $bad.Count) {
        throw 'Baseline failed for an unrelated or ambiguous reason; ATL path handling is inconclusive.'
    }
    return $found[0]
}

function Assert-AtlHeaderInclusion([string]$Log,[string]$Header) {
    $expected=([IO.Path]::GetFullPath($Header)).Replace('\','/').ToLowerInvariant()
    foreach($line in [IO.File]::ReadAllLines($Log)) {
        if($line -match '^Note: including file:\s*(.+?)\s*$' -and $Matches[1].Replace('\','/').ToLowerInvariant() -ceq $expected) {
            return [ordered]@{header=$Header;line=$line;log=$Log}
        }
    }
    throw 'Compiler /showIncludes did not witness the selected ATL census header.'
}

function Get-AtlCompileArguments([string[]]$IncludeDirectories,[string]$AtlInclude,[string]$Source,[string]$Object,[string]$Pdb) {
    @('-nologo','-O2','-GL','-MD','-EHsc','-std:c++20','-permissive-','-Zc:__cplusplus,preprocessor','-showIncludes')+
        @($IncludeDirectories|ForEach-Object {'-I'+$_.Replace('\','/')})+
        @(('-I'+$AtlInclude),'-c',$Source,('-Fo'+$Object),('-Fd'+$Pdb))
}

function Get-AtlLinkArguments([string[]]$LibraryDirectories,[string]$AtlLib,[string]$Object,[string]$Output,[string]$Map) {
    @('-nologo','-LTCG','-MACHINE:ARM64','-SUBSYSTEM:CONSOLE','-VERBOSE:LIB',('-OUT:'+$Output),('-MAP:'+$Map))+
        @($LibraryDirectories|ForEach-Object {'-LIBPATH:'+ $_.Replace('\','/')})+
        @(('-LIBPATH:'+$AtlLib),$Object,($AtlLib+'/atls.lib'),'advapi32.lib','gdi32.lib','ole32.lib','oleaut32.lib','shlwapi.lib','urlmon.lib','uuid.lib','user32.lib','kernel32.lib')
}

function Convert-AtlPath([string]$Cygpath,[string]$Path,[string]$Mode,[string]$Work,[string]$Evidence,[string]$Name) {
    $r=Invoke-LoggedCommand $Cygpath @($Mode,$Path) $Work (Join-Path $Evidence ('path-'+$Name)) -TimeoutMinutes 1
    $value=(Get-Content -LiteralPath $r.stdout -Raw).Trim()
    if(-not $value -or $value -match '[\r\n]') {throw 'Cygwin path conversion returned an invalid single path.'}
    return $value
}

function Write-AtlMakeControl([string]$Name,[string[]]$Arguments,[string]$Tool,[string]$Work,[string]$Evidence,
        [string]$Bash,[string]$Cygpath,[string]$UnixWork) {
    $makefile=Join-Path $Evidence ($Name+'.mk')
    # Every native argument is retained separately and shell-quoted once. No
    # MSYS shell or inherited INCLUDE/LIB participates in either comparison.
    Write-BuildJson (Join-Path $Evidence ($Name+'.argv.json')) ([ordered]@{tool=$Tool;arguments=@($Arguments);shell='authenticated Cygwin Bash and GNU make';unset=@('INCLUDE','LIB','CL','_CL_','LINK','_LINK_');set=@{VSLANG='1033'}})
    $native=((@($Tool)+$Arguments|ForEach-Object {Quote-Bash $_}) -join ' ')
    Write-BashScript $makefile @('.PHONY: all','all:',("`tunset INCLUDE LIB CL _CL_ LINK _LINK_ && VSLANG=1033 "+$native.Replace('$','$$')))
    $unixMake=Convert-AtlPath $Cygpath $makefile '-u' $Work $Evidence ($Name+'-makefile')
    $script=Join-Path $Evidence ($Name+'.sh')
    Write-BashScript $script @('set -euo pipefail','export PATH=/usr/local/bin:/usr/bin:/bin:$PATH',
        ('cd '+(Quote-Bash $UnixWork)),('/usr/bin/make --no-builtin-rules --no-builtin-variables -f '+(Quote-Bash $unixMake)+' all'))
    $unixScript=Convert-AtlPath $Cygpath $script '-u' $Work $Evidence ($Name+'-script')
    $envExe=Join-Path (Split-Path $Bash -Parent) 'env.exe'
    return Invoke-AtlObservation $envExe @('CYGWIN=winsymlinks:nativestrict',$Bash,'--noprofile','--norc',$unixScript) $Work (Join-Path $Evidence $Name)
}

function Invoke-NativeAtlControl([string]$WorkDirectory,[string]$OutputDirectory) {
    $paths=New-BuildDirectories $WorkDirectory $OutputDirectory;$work=$paths.work;$evidence=$paths.output
    $repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'));$previous=$script:NativeEngineBuildBudget
    $cygwin='';$failure=$null;$retentionFailure=$null
    $receipt=[ordered]@{schemaVersion=1;kind='native-arm64-atl-prerequisite-control';diagnosticOnly=$true;causalCorrectionProven=$false;completed=$false;status='failed';stage='native-host';
        startedUtc=[DateTime]::UtcNow.ToString('o');fullEngineQualified=$false;guiVerified=$false;runtimeExecuted=$false;
        installsVsAtlOrProduct=$false;configuredPaths=$null;candidatePaths=$null;baselineHeader=$null;candidateHeader=$null;baselineLink=$null;candidateLink=$null;retentionErrors=@()}
    try {
        $script:NativeEngineBuildBudget=New-NativeBuildBudget '' 12;$receipt.budget=$script:NativeEngineBuildBudget.record
        $receipt.host=Get-NativeBuildHost
        $receipt.stage='actual-source-binding'
        $binding=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'probe-native-atl.ps1') (Join-Path $repo 'suite/diagnostics/native-atl-source/source.json') $evidence
        foreach($key in $binding.Keys) {$receipt[$key]=$binding[$key]}
        $sourcePin=Get-Content -LiteralPath (Join-Path $repo 'suite/diagnostics/native-atl-source/source.json') -Raw|ConvertFrom-Json
        $receipt.sourceEvidence=@()
        foreach($pin in $sourcePin.files) {
            $from=Join-Path $repo ('suite/diagnostics/native-atl-source/'+$pin.name)
            Assert-UnlinkedPath $from;Confirm-FileIdentity $from $pin.bytes SHA256 $pin.sha256|Out-Null
            $to=Join-Path $evidence $pin.name;Copy-Item -LiteralPath $from -Destination $to
            $receipt.sourceEvidence+=@{file=$pin.name;sha256=$pin.sha256;bytes=$pin.bytes}
        }
        Copy-Item -LiteralPath (Join-Path $repo 'suite/diagnostics/native-atl-source/source.json') -Destination (Join-Path $evidence 'source.json')
        $receipt.stage='selected-vs18-toolchain'
        $vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
        Assert-UnlinkedPath $vswhere
        $vs=Invoke-LoggedCommand $vswhere @('-all','-products','*','-format','json') $work (Join-Path $evidence 'vs-instances') -TimeoutMinutes 1
        $receipt.toolchain=Get-AtlToolchainPlan @(Get-Content -LiteralPath $vs.stdout -Raw|ConvertFrom-Json)
        $tools=$receipt.toolchain.compilerRoot;$native=Join-Path $tools 'bin/Hostarm64/arm64'
        $receipt.nativeTools=@()
        foreach($name in @('cl.exe','link.exe','lib.exe','dumpbin.exe')) {
            $file=Join-Path $native $name;$identity=Get-ProductPeIdentity $file
            if($identity.role -cne 'nativeArm64') {throw 'The actual compiler and linker must be native ARM64.'}
            $identity.fileVersion=(Get-Item -LiteralPath $file).VersionInfo.FileVersion
            $identity.productVersion=(Get-Item -LiteralPath $file).VersionInfo.ProductVersion
            $receipt.nativeTools+=,$identity
        }
        $receipt.components=@()
        foreach($id in @('Microsoft.VisualStudio.Component.VC.ATL.ARM64','Microsoft.VisualStudio.Component.VC.ATL.ARM64.Spectre')) {
            $label=if($id.EndsWith('.Spectre')){'spectre'}else{'regular'}
            $r=Invoke-LoggedCommand $vswhere @('-all','-products','*','-version','[18.0,19.0)','-requires',$id,'-property','instanceId') $work (Join-Path $evidence ('component-'+$label)) -TimeoutMinutes 1
            $ids=@(Get-Content -LiteralPath $r.stdout|ForEach-Object {$_.Trim()}|Where-Object {$_})
            $receipt.components+=@{id=$id;selectedInstanceContains=($receipt.toolchain.instanceId -cin $ids);commandReceipt=$r.receipt}
        }
        $receipt.stage='strict-atl-census';$receipt.census=Get-AtlCensus $tools
        Write-BuildJson (Join-Path $evidence 'atl-census.json') $receipt.census
        if(-not $receipt.census.ready) {$receipt.status='missing-or-rejected-atl-prerequisites';throw 'Selected ATL header/library census failed; install nothing and retain the exact missing/rejected observations.'}
        $receipt.stage='selected-arm64-windows-sdk'
        $sdk=(Get-ItemProperty 'HKLM:/SOFTWARE/Microsoft/Windows Kits/Installed Roots' -Name KitsRoot10).KitsRoot10
        Assert-UnlinkedPath $sdk
        $versions=@(Get-ChildItem -LiteralPath (Join-Path $sdk 'Include') -Directory|Where-Object {$_.Name -match '^10\.0\.\d+\.0$'}|Sort-Object {[Version]$_.Name} -Descending)
        if(-not $versions.Count) {throw 'No selected Windows SDK version is installed.'}
        $sdkVersion=$versions[0].Name
        $includeDirs=@((Join-Path $tools 'include'))+@('ucrt','um','shared'|ForEach-Object {Join-Path $sdk ('Include/'+$sdkVersion+'/'+$_)})
        $libDirs=@((Join-Path $tools 'lib/arm64'))+@('ucrt','um'|ForEach-Object {Join-Path $sdk ('Lib/'+$sdkVersion+'/'+$_+'/arm64')})
        foreach($dir in $includeDirs+$libDirs) {Assert-UnlinkedPath $dir;if(-not(Test-Path -LiteralPath $dir -PathType Container)) {throw 'Selected ARM64 SDK/compiler include or library directory is missing.'}}
        $receipt.sdk=[ordered]@{root=$sdk;version=$sdkVersion;includeDirectories=$includeDirs;libraryDirectories=$libDirs}
        $receipt.stage='authenticated-cygwin-build-helpers'
        $downloads=Join-Path $work 'downloads';New-Item -ItemType Directory $downloads|Out-Null
        $setup=Join-Path $downloads 'setup-x86_64.exe'
        $setupHash='6acea47c59781c9e7f544a18d53935d59df6e44d5d52ac95ee165671b8e388820455eebf30ccc7d254b00c3d0eb694269a0f8dc84b17944c1f355dac9c5aafcc'
        $receipt.cygwinSetup=Get-AuthenticatedDownload 'https://cygwin.com/setup-x86_64.exe' $setup 0 SHA512 $setupHash (Join-Path $evidence 'cygwin-download.json')
        $cygwin=Join-Path $work 'cygwin';$cache=Join-Path $work 'cygwin-cache'
        $receipt.cygwinSetupCommand=Invoke-LoggedCommand $setup @('--quiet-mode','--no-admin','--no-shortcuts','--no-startmenu','--no-desktop','--root',$cygwin,'--local-package-dir',$cache,'--site','https://mirrors.kernel.org/sourceware/cygwin/','--packages','bash,make') $work (Join-Path $evidence 'cygwin-setup') -TimeoutMinutes 5
        $bash=Join-Path $cygwin 'bin/bash.exe';$cygpath=Join-Path $cygwin 'bin/cygpath.exe'
        $receipt.cygwinFiles=@()
        foreach($name in @('bash.exe','cygpath.exe','make.exe','env.exe','cygwin1.dll')) {
            $file=Join-Path $cygwin ('bin/'+$name);Assert-UnlinkedPath $file
            $receipt.cygwinFiles+=@{path=$file;bytes=(Get-Item -LiteralPath $file).Length;sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant();role='x64 build helper, not product payload'}
        }
        $commands=Join-Path $work 'commands';New-Item -ItemType Directory $commands|Out-Null
        $receipt.cygwinIdentity=Get-CygwinIdentity $bash $cygpath $commands $work $evidence
        if($receipt.cygwinIdentity.operatingSystem -cne 'Cygwin' -or $receipt.cygwinIdentity.machine -cne 'x86_64') {throw 'Actual reviewed x64 Cygwin build-helper identity is required; MSYS substitution is forbidden.'}
        $receipt.cygwinPackages=Invoke-LoggedCommand (Join-Path $cygwin 'bin/cygcheck.exe') @('-c','-d','bash','make') $work (Join-Path $evidence 'cygwin-packages') -TimeoutMinutes 1
        $unixWork=Convert-AtlPath $cygpath $work '-u' $work $evidence 'work'
        $unixCompiler=Convert-AtlPath $cygpath $tools '-u' $work $evidence 'compiler-unix'
        $mixedCompiler=Convert-AtlPath $cygpath $tools '-sm' $work $evidence 'compiler-mixed'
        $selection=Join-Path $evidence 'atl-path-selection.sh'
        $prefix=@('set -euo pipefail','export PATH=/usr/local/bin:/usr/bin:/bin:$PATH',"COMPATH=$(Quote-Bash $mixedCompiler)","COMPATH_unix=$(Quote-Bash $unixCompiler)",'WIN_HOST_ARCH=arm64','build_os=cygwin','GNUMAKE_WIN_NATIVE=','WSL_ONLY_AS_HELPER=')
        $sourceLines=[IO.File]::ReadAllLines((Join-Path $evidence 'configure-atl-selection.sh'))
        Write-BashScript $selection ($prefix+$sourceLines+@('CXX=$(win_short_path_for_make "$COMPATH/bin/Hostarm64/arm64/cl.exe")',
            'LINK=$(win_short_path_for_make "$COMPATH/bin/Hostarm64/arm64/link.exe")',
            'printf ''ATL_INCLUDE=%s\nATL_LIB=%s\nCXX=%s\nLINK=%s\n'' "$ATL_INCLUDE" "$ATL_LIB" "$CXX" "$LINK"','/usr/bin/make --version'))
        $selected=Invoke-CygwinScript $bash $cygpath $selection $work (Join-Path $evidence 'atl-path-selection')
        if((Get-Content -LiteralPath $selected.stdout -Raw) -cnotmatch 'Built for x86_64-pc-cygwin') {throw 'Actual Cygwin GNU make build identity is required.'}
        $values=@{}
        foreach($line in Get-Content -LiteralPath $selected.stdout) {if($line -match '^(ATL_INCLUDE|ATL_LIB|CXX|LINK)=(.+)$') {$values[$Matches[1]]=$Matches[2]}}
        if($values.Count -ne 4 -or $values.ATL_INCLUDE -cnotmatch '^/cygdrive/[a-z]/' -or $values.ATL_LIB -cnotmatch '^/cygdrive/[a-z]/' -or
            $values.CXX -cnotmatch '^/cygdrive/[a-z]/' -or $values.LINK -cnotmatch '^/cygdrive/[a-z]/') {throw 'Authentic configure selection did not yield the expected Cygwin GNU make path form.'}
        $receipt.configuredPaths=@{ATL_INCLUDE=$values.ATL_INCLUDE;ATL_LIB=$values.ATL_LIB}
        $receipt.nativeInvocationPaths=@{CXX=$values.CXX;LINK=$values.LINK;compilerSelection='source win_short_path_for_make; absolute selected Hostarm64/arm64; same binary in both arms'}
        $frozen=Get-Content -LiteralPath (Join-Path $evidence 'failure-context.json') -Raw|ConvertFrom-Json
        if($values.ATL_INCLUDE -cne $frozen.ATL_INCLUDE -or $values.ATL_LIB -cne $frozen.ATL_LIB -or $values.CXX -cne $frozen.CXX) {throw 'Actual configure-derived ATL/compiler spellings differ from native22; retain the changed layout for review.'}
        foreach($pair in @(@('CXX','cl.exe'),@('LINK','link.exe'))) {
            $translatedTool=Convert-AtlPath $cygpath $values[$pair[0]] '-lm' $work $evidence ('invoked-'+$pair[0].ToLowerInvariant())
            $identity=$receipt.nativeTools|Where-Object {[IO.Path]::GetFileName($_.path) -ieq $pair[1]}
            if([IO.Path]::GetFullPath($translatedTool) -ine [IO.Path]::GetFullPath($identity.path)) {throw 'Cygwin native invocation path differs from the selected native tool identity.'}
            Confirm-FileIdentity $translatedTool $identity.size SHA256 $identity.sha256|Out-Null
        }
        $windowsInclude=Convert-AtlPath $cygpath $values.ATL_INCLUDE '-lm' $work $evidence 'candidate-include'
        $windowsLib=Convert-AtlPath $cygpath $values.ATL_LIB '-lm' $work $evidence 'candidate-lib'
        if([IO.Path]::GetFullPath($windowsInclude) -ine [IO.Path]::GetFullPath($receipt.census.includeDirectory) -or
            [IO.Path]::GetFullPath($windowsLib+'/atls.lib') -ine [IO.Path]::GetFullPath($receipt.census.selectedLibrary.path)) {throw 'Translated ATL paths do not identify the exact selected toolset census files.'}
        $receipt.candidatePaths=@{ATL_INCLUDE=$windowsInclude;ATL_LIB=$windowsLib;translationOnly=$true}
        $receipt.stage='native-atl-header-controls'
        $cpp=Join-Path $evidence 'atl-control.cpp'
        @'
#define STRICT
#define _ATL_APARTMENT_THREADED
#define _ATL_STATIC_REGISTRY
#include <atlbase.h>
extern ATL::CComModule _Module;
#include <atlcom.h>
#include <atlctl.h>
ATL::CComModule _Module;
int main() { return static_cast<int>(_Module.RegisterServer(FALSE)); }
'@|Set-Content -LiteralPath $cpp -Encoding utf8NoBOM
        $receipt.cppSha256=(Get-FileHash -LiteralPath $cpp -Algorithm SHA256).Hash.ToLowerInvariant()
        $cl=$values.CXX;$link=$values.LINK
        $objects=@{}
        foreach($mode in @('baseline','candidate')) {
            $inc=if($mode -eq 'baseline'){$values.ATL_INCLUDE}else{$windowsInclude}
            $obj=(Join-Path $evidence ($mode+'.obj')).Replace('\','/');$objects[$mode]=$obj
            $arguments=@(Get-AtlCompileArguments $includeDirs $inc $cpp.Replace('\','/') $obj (Join-Path $evidence ($mode+'.pdb')).Replace('\','/'))
            $toolIdentity=$receipt.nativeTools|Where-Object {[IO.Path]::GetFileName($_.path) -ieq 'cl.exe'}
            Confirm-FileIdentity $toolIdentity.path $toolIdentity.size SHA256 $toolIdentity.sha256|Out-Null
            $result=Write-AtlMakeControl ($mode+'-header') $arguments $cl $work $evidence $bash $cygpath $unixWork
            $receipt[$mode+'Header']=$result
            if($result.succeeded) {
                $result.includes=@()
                foreach($header in $receipt.census.headers) {
                    Confirm-FileIdentity $header.path $header.bytes SHA256 $header.sha256|Out-Null
                    $result.includes+=Assert-AtlHeaderInclusion $result.stdout $header.path
                }
            }
        }
        if(-not $receipt.candidateHeader.succeeded) {throw 'Windows-path ATL header candidate did not compile; path cause remains unproved.'}
        $receipt.candidateObject=Get-AtlFile $objects.candidate
        $receipt.stage='native-atl-library-controls'
        foreach($mode in @('baseline','candidate')) {
            $lib=if($mode -eq 'baseline'){$values.ATL_LIB}else{$windowsLib}
            $exe=(Join-Path $evidence ($mode+'-atl.exe')).Replace('\','/')
            $arguments=@(Get-AtlLinkArguments $libDirs $lib $objects.candidate $exe (Join-Path $evidence ($mode+'-atl.map')).Replace('\','/'))
            $toolIdentity=$receipt.nativeTools|Where-Object {[IO.Path]::GetFileName($_.path) -ieq 'link.exe'}
            Confirm-FileIdentity $toolIdentity.path $toolIdentity.size SHA256 $toolIdentity.sha256|Out-Null
            Confirm-FileIdentity $receipt.census.selectedLibrary.path $receipt.census.selectedLibrary.bytes SHA256 $receipt.census.selectedLibrary.sha256|Out-Null
            $result=Write-AtlMakeControl ($mode+'-link') $arguments $link $work $evidence $bash $cygpath $unixWork
            $receipt[$mode+'Link']=$result
            if($result.succeeded) {
                $result.outputPe=Get-ProductPeIdentity $exe
                if($result.outputPe.role -cne 'nativeArm64') {throw 'ATL control output is not native ARM64.'}
                $result.archiveExtraction=Assert-AtlArchiveExtraction $result.stdout $receipt.census.selectedLibrary.path
            }
        }
        if(-not $receipt.candidateLink.succeeded) {throw 'Windows-path ATL library candidate did not link; library path cause remains unproved.'}
        if(-not $receipt.baselineHeader.succeeded) {$receipt.baselineHeader.expectedFailure=Assert-AtlExpectedFailure @($receipt.baselineHeader.stdout,$receipt.baselineHeader.stderr) Header}
        if(-not $receipt.baselineLink.succeeded) {$receipt.baselineLink.expectedFailure=Assert-AtlExpectedFailure @($receipt.baselineLink.stdout,$receipt.baselineLink.stderr) Library}
        $receipt.conclusion=Get-AtlControlConclusion $receipt.baselineHeader.succeeded $receipt.candidateHeader.succeeded $receipt.baselineLink.succeeded $receipt.candidateLink.succeeded
        $receipt.completed=$true;$receipt.status='diagnostic-complete';$receipt.stage='complete'
    } catch {$failure=$_;$receipt.error=$_.Exception.ToString()}
    finally {
        if($cygwin) {
            foreach($name in @('setup.log','setup.log.full')) {
                try {
                    $log=Join-Path $cygwin ('var/log/'+$name)
                    if(Test-Path -LiteralPath $log -PathType Leaf) {Copy-Item -LiteralPath $log -Destination (Join-Path $evidence ('cygwin-'+$name))}
                } catch {$receipt.retentionErrors+=$_.Exception.Message;$receipt.completed=$false}
            }
        }
        $receipt.finishedUtc=[DateTime]::UtcNow.ToString('o')
        $script:NativeEngineBuildBudget=$previous
        try {Write-BuildJson (Join-Path $evidence 'atl-control-receipt.json') $receipt}
        catch {$retentionFailure=$_;Write-Host ('ATL receipt retention failed: '+$_.Exception.Message)}
    }
    if($failure) {throw $failure}
    if($retentionFailure) {throw $retentionFailure}
    if($receipt.retentionErrors.Count) {throw 'ATL evidence retention failed; see retained original observations and retentionErrors.'}
}

if($MyInvocation.InvocationName -ne '.') {Invoke-NativeAtlControl $WorkDirectory $OutputDirectory}
