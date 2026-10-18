param([string]$WorkDirectory='.work/native28-atl-work',[string]$OutputDirectory='.work/native28-atl-evidence',[string]$DeadlineUtc='')
$ErrorActionPreference='Stop'
$driver=Join-Path $PSScriptRoot 'build-native-engine.ps1'
$driverSha='501680337e44e33e4c58cfdfbdd4d39cc4d4925cf91f458ec93800b663c9a7b4'
if((Get-FileHash -LiteralPath $driver -Algorithm SHA256).Hash.ToLowerInvariant() -cne $driverSha){throw 'Reviewed owned-command driver changed.'}
. $driver -WorkDirectory $WorkDirectory -OutputDirectory $OutputDirectory -DeadlineUtc $DeadlineUtc
$inputRoot=Join-Path $PSScriptRoot '../diagnostics/native-atl-source'
$inputManifest=Get-Content -LiteralPath (Join-Path $inputRoot 'path-control-source.json') -Raw|ConvertFrom-Json
foreach($pin in $inputManifest.reusedInputs){
    $path=Join-Path (Join-Path $PSScriptRoot '../..') $pin.repositoryPath
    Assert-UnlinkedPath $path;Confirm-FileIdentity $path $pin.bytes SHA256 $pin.sha256|Out-Null
}
. (Join-Path $inputRoot 'atl-static-archive.ps1')

function Initialize-AtlPathOwnedCommand {
    $original=(Get-Command Invoke-LoggedCommand -CommandType Function).Definition
    $old="if(`$name -cnotin @('PATH','FIREBIRD')"
    $new="if(`$name -cnotin @('PATH','FIREBIRD','LIB','INCLUDE','CL','_CL_','LINK','_LINK_','VSLANG')"
    if([regex]::Matches($original,[regex]::Escape($old)).Count -ne 1){throw 'Owned command environment seam differs from pinned source.'}
    $adapted=$original.Replace($old,$new)
    if($adapted.Replace($new,$old) -cne $original){throw 'Owned command adapter changed more than its finite environment list.'}
    Set-Item -Path Function:script:Invoke-AtlPathOwnedCommand -Value ([ScriptBlock]::Create($adapted))
    return [ordered]@{driverSha256=$driverSha;originalDefinitionSha256=(Get-AtlPayloadHash ([Text.Encoding]::UTF8.GetBytes($original)) 0 ([Text.Encoding]::UTF8.GetByteCount($original)));
        adaptedDefinitionSha256=(Get-AtlPayloadHash ([Text.Encoding]::UTF8.GetBytes($adapted)) 0 ([Text.Encoding]::UTF8.GetByteCount($adapted)));
        originalBodyRestoredExactly=$true;allowedEnvironmentNames=@('PATH','FIREBIRD','LIB','INCLUDE','CL','_CL_','LINK','_LINK_','VSLANG');
        onlyDifference='Seven child-environment names added; every other source character/body/ownership field unchanged';directOwnerPreserved=$true}
}

function Assert-AtlPathCommandReceipt($Receipt,[ValidateSet('Baseline','Candidate')][string]$Arm){
    if($Receipt.pipeDrainComplete -ne $true -or $Receipt.forcedTermination -ne $false -or
       $Receipt.directProcessDeathVerified -ne $true -or $Receipt.processTreeCleanup -cne 'not-requested' -or @($Receipt.cleanupErrors).Count){throw 'Path control requires normal drained unforced direct death.'}
    if($Arm -ceq 'Baseline'){
        if($Receipt.exitCode -notin @(1104,1181) -or $Receipt.passed -ne $false){throw 'Baseline direct LINK must have its exact expected native failure exit.'}
    }elseif($Receipt.exitCode -ne 0 -or $Receipt.passed -ne $true){throw 'Candidate direct tool must have normal successful zero exit.'}
}

function Assert-AtlPathMissingLibrary([string[]]$Logs,[int]$ExitCode){
    $found=@();$other=@()
    foreach($path in $Logs){foreach($line in [IO.File]::ReadAllLines($path)){
        if($line -match '^\s*LINK : fatal error LNK(1104|1181): cannot open (?:input )?file [''"]atls\.lib[''"]\s*$'){
            $found+=,[ordered]@{line=$line;log=$path;code=[int]$Matches[1]}
        }elseif($line -match '(?i)\berror\b|\bfatal\b|\bLNK\d{4}\b|access violation|stack overflow|exception'){ $other+=,$line }
    }}
    if($found.Count -ne 1 -or $other.Count -or $found[0].code -ne $ExitCode){throw 'Baseline failure is not solely the exact missing bare atls.lib diagnostic; inconclusive.'}
    return $found[0]
}

function Get-AtlPathLinkArms([string[]]$LibraryDirectories,[string]$AtlLib,[string]$Object,[string]$Output){
    $common=@('-nologo','-MACHINE:ARM64','-SUBSYSTEM:CONSOLE','-INCREMENTAL:NO','-VERBOSE:LIB')+
        @($LibraryDirectories|ForEach-Object{'-LIBPATH:'+ $_.Replace('\','/')})+@($Object)
    $systems=@('advapi32.lib','gdi32.lib','ole32.lib','oleaut32.lib','shlwapi.lib','urlmon.lib','uuid.lib','user32.lib','kernel32.lib')
    return [ordered]@{baseline=@($common)+@(('-OUT:'+($Output+'/baseline.exe')),('-MAP:'+($Output+'/baseline.map')),'atls.lib')+$systems;
        candidate=@($common)+@(('-OUT:'+($Output+'/candidate.exe')),('-MAP:'+($Output+'/candidate.map')),('-LIBPATH:'+$AtlLib),($AtlLib+'/atls.lib'))+$systems}
}

function Write-AtlPathFixture([string]$Path){
    if(Test-Path -LiteralPath $Path){throw 'Preserve original authored fixture.'}
    @'
#define STRICT
#define _ATL_APARTMENT_THREADED
#define _ATL_STATIC_REGISTRY
#include <atlbase.h>
extern ATL::CComModule _Module;
#include <atlcom.h>
#include <atlctl.h>
ATL::CComModule _Module;
int main() { return _Module.GetModuleInstance() == nullptr ? 0 : 1; }
'@|Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Get-AtlPathParentEnvironment {
    $result=[ordered]@{}
    foreach($name in @('PATH','LIB','INCLUDE','CL','_CL_','LINK','_LINK_','VSLANG')){
        $value=[Environment]::GetEnvironmentVariable($name,'Process')
        $result[$name]=[ordered]@{present=($null -ne $value);value=$(if($name -cne 'PATH'){$value}else{$null});
            sha256=$(if($null -ne $value){Get-AtlPayloadHash ([Text.Encoding]::UTF8.GetBytes($value)) 0 ([Text.Encoding]::UTF8.GetByteCount($value))}else{$null})}
    }
    return $result
}

function Get-AtlPathObject([string]$Path){
    Assert-UnlinkedPath $Path;$file=Get-Item -LiteralPath $Path
    if($file.PSIsContainer -or $file.Length -lt 20 -or $file.Length -gt 67108864){throw 'Owned COFF object has invalid bounds.'}
    $data=[IO.File]::ReadAllBytes($Path);$machine=[int][BitConverter]::ToUInt16($data,0)
    if($machine -ne 0xaa64 -or [BitConverter]::ToUInt16($data,16) -ne 0){throw 'Owned fixture object must be ordinary native ARM64 COFF.'}
    return [ordered]@{path=[IO.Path]::GetFullPath($Path);bytes=$data.Length;sha256=(Get-AtlPayloadHash $data 0 $data.Length);machine=$machine}
}

function Invoke-AtlPathObserved([string]$File,[string[]]$Arguments,[string]$Work,[string]$Prefix,[hashtable]$Environment){
    Write-BuildJson ($Prefix+'.argv.json') ([ordered]@{file=$File;arguments=@($Arguments);workingDirectory=$Work;
        childOverrides=$Environment;policy='CONTROLLED trusted non-ATL LIB and explicit native includes; not an exact Native27 environment replay';otherEnvironmentEntries='Inherited unchanged; full environment/credentials are not dumped'})
    try{Invoke-AtlPathOwnedCommand $File $Arguments $Work $Prefix -TimeoutMinutes 2 -EnvironmentOverrides $Environment|Out-Null}
    catch{if(-not(Test-Path -LiteralPath ($Prefix+'.command.json') -PathType Leaf)){throw}}
    return [ordered]@{commandReceipt=$Prefix+'.command.json';stdout=$Prefix+'.stdout.log';stderr=$Prefix+'.stderr.log';
        raw=(Get-Content -LiteralPath ($Prefix+'.command.json') -Raw|ConvertFrom-Json)}
}
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

function Get-AtlFile([string]$Path) {
    $record=[ordered]@{path=[IO.Path]::GetFullPath($Path);status='missing';bytes=$null;sha256=$null;machines=$null;error=$null}
    try {
        Assert-UnlinkedPath $Path
        if(-not(Test-Path -LiteralPath $Path)) {return $record}
        $file=Get-Item -LiteralPath $Path -Force
        if($file.PSIsContainer -or $file.Length -le 0 -or $file.Length -gt 1048576) {throw 'ATL census requires a bounded nonempty regular file.'}
        $record.bytes=$file.Length
        $record.sha256=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        $record.status='verified'
    } catch {$record.status='rejected';$record.error=$_.Exception.Message}
    return $record
}

function Get-AtlCensus([string]$CompilerRoot,[object[]]$Profiles=@()) {
    Assert-UnlinkedPath $CompilerRoot
    if(-not $Profiles.Count) {$Profiles=(Get-Content -LiteralPath (Join-Path $PSScriptRoot '../diagnostics/native-atl-source/atl-static-profiles.json') -Raw|ConvertFrom-Json).profiles}
    $regularPin=@($Profiles|Where-Object kind -eq 'regular');$spectrePin=@($Profiles|Where-Object kind -eq 'spectre')
    if($Profiles.Count -ne 2 -or $regularPin.Count -ne 1 -or $spectrePin.Count -ne 1) {throw 'Exactly the regular and Spectre ATL static profiles are required.'}
    $include=Join-Path $CompilerRoot 'atlmfc/include'
    $headers=@('atlbase.h','atlcom.h','atlctl.h')|ForEach-Object {Get-AtlFile (Join-Path $include $_)}
    $regular=Get-AtlStaticLibrary (Join-Path $CompilerRoot 'atlmfc/lib/arm64/atls.lib') $regularPin[0]
    $spectre=Get-AtlStaticLibrary (Join-Path $CompilerRoot 'atlmfc/lib/spectre/arm64/atls.lib') $spectrePin[0]
    # Match the authenticated configure.ac parent-directory selection exactly.
    $spectreParent=Join-Path $CompilerRoot 'atlmfc/lib/spectre'
    Assert-UnlinkedPath $spectreParent
    $selectSpectre=Test-Path -LiteralPath $spectreParent -PathType Container
    $selected=if($selectSpectre){$spectre}else{$regular}
    return [ordered]@{includeDirectory=$include;headers=@($headers);libraries=@($regular,$spectre);
        spectreParentExists=$selectSpectre;selectedLibrary=$selected;
        readyForNativeLinkMeasurement=(@($headers|Where-Object status -ne 'verified').Count -eq 0 -and $selected.readyForNativeLinkMeasurement -eq $true);
        nativeConsumedOnlyVerified=$null}
}

function Invoke-NativeAtlPathControl([string]$WorkDirectory,[string]$OutputDirectory,[string]$DeadlineUtc){
    $paths=New-BuildDirectories $WorkDirectory $OutputDirectory;$work=$paths.work;$evidence=$paths.output
    $repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'));$previous=$script:NativeEngineBuildBudget
    $failure=$null;$parent=Get-AtlPathParentEnvironment
    $receipt=[ordered]@{schemaVersion=1;kind='native28-atl-library-path-receiver-control';diagnosticOnly=$true;stage='budget';
        status='inconclusive';completed=$false;pathReceiverMeasured=$false;nativeConsumedOnlyVerified=$null;
        fullEngineQualified=$false;runtimeExecuted=$false;baseQualified=$false;causalCorrectionProven=$false;
        inheritedRelevantEnvironment=$parent;controlledEnvironmentReplay='Not exact Native27 replay';startedUtc=[DateTime]::UtcNow.ToString('o');retentionErrors=@()}
    try{
        $script:NativeEngineBuildBudget=New-NativeBuildBudget $DeadlineUtc 15;$receipt.budget=$script:NativeEngineBuildBudget.record
        if(-not $DeadlineUtc){throw 'A first-user-step external deadline is mandatory.'}
        if(-not $env:OPENGEUL_ATL_PATH_BUDGET_RECEIPT){throw 'Original first-step job budget receipt is mandatory.'}
        Copy-Item -LiteralPath $env:OPENGEUL_ATL_PATH_BUDGET_RECEIPT -Destination (Join-Path $evidence 'job-budget.json') -ErrorAction Stop
        $receipt.host=Get-NativeBuildHost
        $controller=Get-Process -Id $PID;$receipt.controller=Get-ProductPeIdentity $controller.Path
        if($receipt.controller.role -cne 'nativeArm64'){throw 'Actual controller image must also be native ARM64.'}
        $receipt.controllerDateTimeIdentity=Get-CommandCreationIdentity $controller
        $receipt.stage='source-binding'
        $receipt.source=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'probe-native-atl-path-control.ps1') (Join-Path $inputRoot 'path-control-source.json') $evidence
        $receipt.adapter=Initialize-AtlPathOwnedCommand
        [IO.File]::WriteAllText((Join-Path $evidence 'owned-command-original.ps1'),(Get-Command Invoke-LoggedCommand).Definition)
        [IO.File]::WriteAllText((Join-Path $evidence 'owned-command-adapted.ps1'),(Get-Command Invoke-AtlPathOwnedCommand).Definition)
        Copy-Item -LiteralPath (Join-Path $inputRoot 'path-control-source.json') -Destination (Join-Path $evidence 'path-control-source.json')
        Copy-Item -LiteralPath (Join-Path $inputRoot 'atl-static-profiles.json') -Destination (Join-Path $evidence 'atl-static-profiles.json')
        $receipt.stage='native-toolchain-and-atl-inventory'
        $vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe';Assert-UnlinkedPath $vswhere
        $vs=Invoke-LoggedCommand $vswhere @('-all','-products','*','-format','json') $work (Join-Path $evidence 'vs-instances') -TimeoutMinutes 1
        $receipt.toolchain=Get-AtlToolchainPlan @(Get-Content -LiteralPath $vs.stdout -Raw|ConvertFrom-Json)
        $tools=$receipt.toolchain.compilerRoot;$native=Join-Path $tools 'bin/Hostarm64/arm64';$receipt.nativeTools=@()
        foreach($name in @('cl.exe','link.exe')){
            $identity=Get-ProductPeIdentity (Join-Path $native $name)
            if($identity.role -cne 'nativeArm64'){throw 'Selected direct compiler/linker must be native ARM64.'};$receipt.nativeTools+=,$identity
        }
        $receipt.census=Get-AtlCensus $tools;Write-BuildJson (Join-Path $evidence 'atl-census.json') $receipt.census
        if(-not $receipt.census.readyForNativeLinkMeasurement){throw 'Selected ATL input missing or not exact typed profile; no installation or fallback.'}
        $sdk=(Get-ItemProperty 'HKLM:/SOFTWARE/Microsoft/Windows Kits/Installed Roots' -Name KitsRoot10).KitsRoot10;Assert-UnlinkedPath $sdk
        $versions=@(Get-ChildItem -LiteralPath (Join-Path $sdk 'Include') -Directory|Where-Object{$_.Name -match '^10\.0\.\d+\.0$'}|Sort-Object{[Version]$_.Name} -Descending)
        if(-not $versions.Count){throw 'Installed Windows SDK selection unavailable.'};$version=$versions[0].Name
        $includes=@((Join-Path $tools 'include'))+@('ucrt','um','shared'|ForEach-Object{Join-Path $sdk ('Include/'+$version+'/'+$_)})
        $libraries=@((Join-Path $tools 'lib/arm64'))+@('ucrt','um'|ForEach-Object{Join-Path $sdk ('Lib/'+$version+'/'+$_+'/arm64')})
        foreach($dir in $includes+$libraries){Assert-UnlinkedPath $dir;if(-not(Test-Path -LiteralPath $dir -PathType Container)){throw 'Selected native SDK/compiler directory missing.'}}
        foreach($dir in $libraries){if(Test-Path -LiteralPath (Join-Path $dir 'atls.lib')){throw 'Controlled non-ATL LIB unexpectedly contains atls.lib.'}}
        $atl=([IO.Path]::GetDirectoryName($receipt.census.selectedLibrary.path)).Replace('\','/')
        $receipt.sdk=[ordered]@{root=$sdk;version=$version;includeDirectories=$includes;nonAtlLibraryDirectories=$libraries}
        $receipt.nativeAtlLib=$atl
        $child=@{LIB=($libraries -join ';');INCLUDE='';CL='';_CL_='';LINK='';_LINK_='';VSLANG='1033';PATH=($native+';'+(Join-Path $env:SystemRoot 'System32')+';'+$env:SystemRoot)}
        $receipt.controlledChildEnvironment=$child
        $receipt.stage='one-owned-native-compile'
        $cpp=Join-Path $evidence 'atl-path-owned.cpp';Write-AtlPathFixture $cpp
        $obj=(Join-Path $evidence 'atl-path-owned.obj').Replace('\','/')
        $cl=Join-Path $native 'cl.exe';$link=Join-Path $native 'link.exe'
        $compile=@('-nologo','-O2','-MD','-EHsc','-std:c++20','-permissive-','-Zc:__cplusplus,preprocessor','-showIncludes')+
            @($includes|ForEach-Object{'-I'+$_.Replace('\','/')})+@(('-I'+$receipt.census.includeDirectory.Replace('\','/')),'-c',$cpp.Replace('\','/'),('-Fo'+$obj))
        $receipt.compile=Invoke-AtlPathObserved $cl $compile $work (Join-Path $evidence 'compile') $child
        Assert-AtlPathCommandReceipt $receipt.compile.raw Candidate
        $object=Get-AtlPathObject $obj;$receipt.initialObject=$object
        $arms=Get-AtlPathLinkArms $libraries $atl $obj $evidence.Replace('\','/');$receipt.arms=[ordered]@{}
        foreach($mode in @('baseline','candidate')){
            Assert-NativeBuildTimeRemaining
            Confirm-FileIdentity $obj $object.bytes SHA256 $object.sha256|Out-Null
            foreach($tool in $receipt.nativeTools){Confirm-FileIdentity $tool.path $tool.size SHA256 $tool.sha256|Out-Null}
            $lib=$receipt.census.selectedLibrary;Confirm-FileIdentity $lib.path $lib.bytes SHA256 $lib.sha256|Out-Null
            $arm=Invoke-AtlPathObserved $link $arms[$mode] $work (Join-Path $evidence $mode) $child
            $arm.sameObjectBefore=$object;$arm.sameObjectAfter=Get-AtlPathObject $obj
            if(($arm.sameObjectAfter|ConvertTo-Json -Compress) -cne ($object|ConvertTo-Json -Compress)){throw 'The one object changed across link arms.'}
            $receipt.arms[$mode]=$arm
        }
        Assert-AtlPathCommandReceipt $receipt.arms.baseline.raw Baseline
        $receipt.baselineMissingLibrary=Assert-AtlPathMissingLibrary @($receipt.arms.baseline.stdout,$receipt.arms.baseline.stderr) $receipt.arms.baseline.raw.exitCode
        Assert-AtlPathCommandReceipt $receipt.arms.candidate.raw Candidate
        $exe=Join-Path $evidence 'candidate.exe';$receipt.candidateOutput=Get-ProductPeIdentity $exe
        if($receipt.candidateOutput.role -cne 'nativeArm64'){throw 'Candidate output must be native ARM64; output is never executed.'}
        $receipt.stage='strict-selected-archive-consumption'
        try{
            $receipt.nativeConsumption=Assert-AtlNativeConsumption @($receipt.arms.candidate.stdout,$receipt.arms.candidate.stderr) (Join-Path $evidence 'candidate.map') $receipt.census.selectedLibrary
            $receipt.nativeConsumedOnlyVerified=$true
        }catch{$receipt.nativeConsumedOnlyVerified=$false;$receipt.nativeConsumptionError=$_.Exception.Message}
        $receipt.pathReceiverMeasured=$true;$receipt.completed=$true
        $receipt.status=if($receipt.nativeConsumedOnlyVerified){'path-measured-native-members-proved-diagnostic-only'}else{'path-measured-native-consumption-inconclusive'}
        $receipt.stage='complete'
    }catch{$failure=$_;$receipt.error=$_.Exception.ToString()}
    finally{
        $receipt.parentEnvironmentAfter=Get-AtlPathParentEnvironment
        $receipt.parentEnvironmentUnchanged=(($parent|ConvertTo-Json -Depth 8 -Compress) -ceq ($receipt.parentEnvironmentAfter|ConvertTo-Json -Depth 8 -Compress))
        if(-not $receipt.parentEnvironmentUnchanged){$receipt.completed=$false;$receipt.retentionErrors+=,'Parent environment changed.'}
        $receipt.finishedUtc=[DateTime]::UtcNow.ToString('o')
        if($script:NativeEngineBuildBudget){$receipt.elapsedSeconds=$script:NativeEngineBuildBudget.clock.Elapsed.TotalSeconds}
        $script:NativeEngineBuildBudget=$previous
        Write-BuildJson (Join-Path $evidence 'atl-path-control-receipt.json') $receipt
    }
    if($failure){throw $failure};if(-not $receipt.completed -or $receipt.retentionErrors.Count){throw 'ATL path measurement incomplete; original evidence retained.'}
}

if($MyInvocation.InvocationName -ne '.') {Invoke-NativeAtlPathControl $WorkDirectory $OutputDirectory $DeadlineUtc}
