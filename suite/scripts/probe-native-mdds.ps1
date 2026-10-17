param([string]$Output='', [string]$WorkRoot='', [string]$Deadline='')
$ErrorActionPreference='Stop'
# The pinned producer has an invocation-name guard, no FunctionsOnly parameter.
. (Join-Path $PSScriptRoot 'build-native-engine.ps1')

function Get-MddsToolchainEnvironment([string]$Dev,[string]$Cmd,[string]$Work,[string]$Out) {
    # PATH retains inherited host entries. Transfer it only through fresh owned
    # work storage, which the workflow never uploads, and remove it on failure.
    $private=Join-Path $Work 'selected-path.private.txt';Assert-UnlinkedPath $private
    if(Test-Path -LiteralPath $private){throw 'Preserve existing private environment snapshot.'}
    $batch=Join-Path $Out 'toolchain-environment.cmd'
    @('@echo off',('call "'+$Dev+'" -no_logo -arch=arm64 -host_arch=arm64'),'if errorlevel 1 exit /b %errorlevel%',
      'set CL=','set _CL_=','set LINK=','set _LINK_=','set PATH > "%~1"','if errorlevel 1 exit /b %errorlevel%',
      'set INCLUDE','set LIB','set LIBPATH','set WindowsSdk','set VCTools','exit /b 0')|Set-Content $batch -Encoding ascii
    try {
        Invoke-LoggedCommand $Cmd @('/d','/c',$batch,$private) $Work (Join-Path $Out 'toolchain-environment') -TimeoutMinutes 1|Out-Null
        $environment=@{}
        foreach($line in Get-Content (Join-Path $Out 'toolchain-environment.stdout.log')) {
            if($line -match '^(INCLUDE|LIB|LIBPATH|WindowsSdk[^=]*|VCTools[^=]*)=(.*)$'){$environment[$Matches[1]]=$Matches[2]}
        }
        $paths=@(Get-Content -LiteralPath $private|Where-Object {$_ -match '^PATH='})
        if($paths.Count -ne 1){throw 'Exactly one private selected PATH required.'}
        $environment['PATH']=$paths[0].Substring(5)
        if(-not $environment['PATH'] -or -not $environment['INCLUDE'] -or -not $environment['LIB'] -or -not $environment['WindowsSdkDir']){throw 'Incomplete actual native SDK environment.'}
        $digest=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($environment['PATH']))).ToLowerInvariant()
        Write-BuildJson (Join-Path $Out 'path-environment.json') ([ordered]@{schemaVersion=1;pathSha256=$digest;rawPathRetainedInEvidence=$false})
        return $environment
    } finally {
        if(Test-Path -LiteralPath $private){Assert-UnlinkedPath $private;Remove-Item -LiteralPath $private -ErrorAction Stop}
    }
}

function Invoke-NativeMddsProbe([string]$Output,[string]$WorkRoot,[string]$Deadline) {
    foreach($path in @($Output,$WorkRoot)) {
        if(-not $path){throw 'Explicit owned evidence/work paths required.'}
        $parent=[IO.Path]::GetFullPath($path)
        while($parent){if(Test-Path -LiteralPath (Join-Path $parent '.git')){throw 'Diagnostic paths must be outside Git.'};$parent=[IO.Path]::GetDirectoryName($parent)}
    }
    $paths=New-BuildDirectories $WorkRoot $Output;$work=$paths.work;$out=$paths.output
    $oldBudget=$script:NativeEngineBuildBudget
    $receipt=[ordered]@{schemaVersion=1;kind='native-arm64-mdds-equality-ab-diagnostic';passed=$false;engineQualified=$false;productQualified=$false;baseQualified=$false;
        productionHookInstalled=$false;originalTwoGnumericObjectsRebuilt=$false;
        scope='Header A/B only: original failing TUs/PCH/argv not retained. Full Native21 is later proof.';stage='native-host';startedUtc=[DateTime]::UtcNow.ToString('o')}
    try {
        $script:NativeEngineBuildBudget=New-NativeBuildBudget -DeadlineUtc $Deadline -MaximumMinutes 20
        $receipt.budget=$script:NativeEngineBuildBudget.record;$receipt.host=Get-NativeBuildHost
        $repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'));$manifest=Join-Path $repo 'suite/engine-build/source-build.json'
        $receipt.source=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'probe-native-mdds.ps1') $manifest $out
        $receipt.files=@(foreach($relative in @('.github/workflows/office-native-mdds-probe.yml','suite/scripts/probe-native-mdds.ps1','suite/scripts/native_mdds_probe.py','suite/scripts/mdds-equality-probe.cpp','suite/tests/test_native_mdds_probe.py','suite/scripts/build-native-engine.ps1')) {
            $path=Join-Path $repo $relative;[ordered]@{path=$relative;bytes=(Get-Item $path).Length;sha256=(Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()}
        })
        Copy-Item $manifest (Join-Path $out 'input-source-build.json')
        if($env:OPENGEUL_MDDS_BUDGET_RECEIPT){Copy-Item $env:OPENGEUL_MDDS_BUDGET_RECEIPT (Join-Path $out 'job-budget.json')}
        $python=(Get-Command python -ErrorAction Stop).Source;$controller=(Get-Process -Id $PID).Path
        $receipt.python=Get-ProductPeIdentity $python;$receipt.controller=Get-ProductPeIdentity $controller
        if($receipt.python.role -cne 'nativeArm64' -or $receipt.controller.role -cne 'nativeArm64'){throw 'Native ARM64 Python/PowerShell required.'}
        $helper=Join-Path $PSScriptRoot 'native_mdds_probe.py';Copy-Item $helper (Join-Path $out 'native_mdds_probe.py')
        $receipt.stage='selected-native-toolchain'
        $vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
        Invoke-LoggedCommand $vswhere @('-latest','-products','*','-version','[18.0,19.0)','-format','json') $work (Join-Path $out 'vswhere') -TimeoutMinutes 1|Out-Null
        $instances=@(Get-Content (Join-Path $out 'vswhere.stdout.log') -Raw|ConvertFrom-Json)
        if($instances.Count -ne 1){throw 'Exactly one selected VS18 installation required.'}
        $vs=$instances[0].installationPath;$version=(Get-Content (Join-Path $vs 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt') -Raw).Trim()
        if($version -cne '14.51.36231'){throw 'Exact Native20 selected toolset 14.51.36231 required.'}
        $tools=Join-Path $vs ('VC/Tools/MSVC/'+$version);$bin=Join-Path $tools 'bin/Hostarm64/arm64';$cl=Join-Path $bin 'cl.exe';$dumpbin=Join-Path $bin 'dumpbin.exe'
        $receipt.compiler=@(foreach($name in @('cl.exe','c1xx.dll','c2.dll','link.exe','dumpbin.exe')) {
            $id=Get-ProductPeIdentity (Join-Path $bin $name)
            if($id.role -cne 'nativeArm64'){throw 'Selected compiler components must be native ARM64.'};$id
        })
        $receipt.crtPlan=Get-AppLocalCrtPlan $tools 'v145'
        $receipt.stage='authenticated-complete-sources'
        $lo=Join-Path $work 'libreoffice.tar.xz';$mdds=Join-Path $work 'mdds-3.2.1.tar.xz';$boost=Join-Path $work 'boost_1_91_0.tar.xz'
        $pin=Get-SourcePin (Join-Path $repo 'suite/config/runtime.arm64.lock.json')
        if($pin.size -ne 302435508 -or $pin.sha256 -cne '296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785'){throw 'Exact LO source pin differs.'}
        $receipt.libreoffice=Get-AuthenticatedDownload $pin.url $lo $pin.size SHA256 $pin.sha256 (Join-Path $out 'libreoffice-download.json')
        $receipt.mdds=Get-AuthenticatedDownload 'https://dev-www.libreoffice.org/src/mdds-3.2.1.tar.xz' $mdds 648256 SHA256 '673f5bb94612dbba581fc92b99b5e5dd1a53e29496a5dbc936432f6b0687c112' (Join-Path $out 'mdds-download.json')
        $receipt.boost=Get-AuthenticatedDownload 'https://dev-www.libreoffice.org/src/boost_1_91_0.tar.xz' $boost 21664068 SHA256 '2f975c10da79511c2f218189fc8a12eef1a92e3bd18206e9841d406296d065eb' (Join-Path $out 'boost-download.json')
        $receipt.stage='exact-scratch-transform'
        Invoke-LoggedCommand $python @($helper,'prepare',$mdds,$lo,$boost,$work,$out,(Join-Path $PSScriptRoot 'mdds-equality-probe.cpp')) $work (Join-Path $out 'prepare') -TimeoutMinutes 5|Out-Null
        $plan=Get-Content (Join-Path $out 'source-plan.json') -Raw|ConvertFrom-Json;$receipt.sourcePlan=$plan
        # Wrapper's quoted include resolves the unchanged retained diagnostic TU.
        Copy-Item (Join-Path $PSScriptRoot 'mdds-equality-probe.cpp') (Join-Path $work 'mdds-equality-probe.cpp')
        $program=Join-Path $out 'program';New-Item -ItemType Directory $program|Out-Null
        $receipt.terms=Save-VcRedistributionTerms (Join-Path $out 'Microsoft-VC145-redistribution.html')
        $receipt.crtInstall=Install-AppLocalCrt $receipt.crtPlan $program $receipt.terms.path
        Write-BuildJson (Join-Path $out 'crt-install.json') $receipt.crtInstall
        $dev=Join-Path $vs 'Common7/Tools/VsDevCmd.bat';Assert-UnlinkedPath $dev
        # Capture once for both cases; evidence retains selected SDK fields and PATH digest only.
        $environment=Get-MddsToolchainEnvironment $dev (Join-Path ([Environment]::SystemDirectory) 'cmd.exe') $work $out
        $receipt.pathEnvironment=Get-Content (Join-Path $out 'path-environment.json') -Raw|ConvertFrom-Json
        # Supply the captured identical environment directly to cl. Never rely on PATH cl.
        $previous=@{};foreach($name in $environment.Keys){$previous[$name]=[Environment]::GetEnvironmentVariable($name);[Environment]::SetEnvironmentVariable($name,$environment[$name])}
        $previousCL=$env:CL;$previous_CL=$env:_CL_;$previousLINK=$env:LINK;$previous_LINK=$env:_LINK_;$env:CL='';$env:_CL_='';$env:LINK='';$env:_LINK_=''
        try {
            $exe=Join-Path $program 'probe.exe';$obj=Join-Path $program 'probe.obj'
            $common=@('/nologo','/Bv','/showIncludes','/std:c++20','/permissive-','/Zc:__cplusplus,preprocessor','/EHs','/D_ARM64_=1','/MD','/utf-8','/Gd','/GR','/Gs','/GS','/Gy','/bigobj','/Zc:inline',('/I'+$plan.boostInclude),('/Fe'+$exe),('/Fo'+$obj),$plan.wrapper,'/link','/MACHINE:ARM64','/INCREMENTAL:NO')
            $receipt.commonCompilerArguments=$common;$receipt.compilerPath=$cl
            foreach($case in $plan.cases) {
                $receipt.stage=$case.name+'-compile'
                $arguments=@(('/I'+$case.include))+$common
                Write-BuildJson (Join-Path $out ($case.name+'-argv.json')) ([ordered]@{file=$cl;arguments=$arguments;include=$environment['INCLUDE'];lib=$environment['LIB'];libpath=$environment['LIBPATH'];sdk=$environment['WindowsSdkDir'];clEnvironment='';underscoreClEnvironment='';linkEnvironment='';underscoreLinkEnvironment=''})
                if($case.name -ceq 'original') {
                    try {Invoke-LoggedCommand $cl $arguments $work (Join-Path $out 'original-compile') -TimeoutMinutes 2|Out-Null}
                    catch {if(-not(Test-Path (Join-Path $out 'original-compile.command.json'))){throw}}
                    # Admission is Python-only, preserving 64-bit Windows receipt ticks.
                    Invoke-LoggedCommand $python @($helper,'admit-original',$out) $work (Join-Path $out 'original-admission') -TimeoutMinutes 1|Out-Null
                    if((Test-Path $exe) -or (Test-Path $obj)){throw 'Failed original emitted output; preserve it and stop.'}
                } else {
                    Invoke-LoggedCommand $cl $arguments $work (Join-Path $out 'candidate-compile') -TimeoutMinutes 2|Out-Null
                }
                $versionLog=(Get-Content (Join-Path $out ($case.name+'-compile.stdout.log')) -Raw)+(Get-Content (Join-Path $out ($case.name+'-compile.stderr.log')) -Raw)
                if($versionLog -cnotmatch '19\.51\.36260' -or $versionLog -cnotmatch '(?i)ARM64'){throw 'Exact actual Native20 MSVC19.51.36260 ARM64 identity missing.'}
            }
        } finally {
            foreach($name in $environment.Keys){[Environment]::SetEnvironmentVariable($name,$previous[$name])};$env:CL=$previousCL;$env:_CL_=$previous_CL;$env:LINK=$previousLINK;$env:_LINK_=$previous_LINK
        }
        $receipt.stage='candidate-native-headers-imports'
        $receipt.executable=Get-ProductPeIdentity $exe
        if($receipt.executable.role -cne 'nativeArm64'){throw 'Candidate executable must be native ARM64.'}
        foreach($target in @($obj,$exe)) {
            $dumpArguments=@('/nologo','/headers');if($target -ceq $exe){$dumpArguments+=@('/imports','/loadconfig')};$dumpArguments+=@($target)
            Invoke-LoggedCommand $dumpbin $dumpArguments $work (Join-Path $out ('dump-'+[IO.Path]::GetFileName($target))) -TimeoutMinutes 1|Out-Null
        }
        $receipt.stage='candidate-native-runtime'
        Invoke-LoggedCommand $exe @() $program (Join-Path $out 'candidate-runtime') -TimeoutMinutes 0.5|Out-Null
        $receipt.stage='paired-evidence-admission'
        Invoke-LoggedCommand $python @($helper,'admit',$out) $work (Join-Path $out 'paired-admission') -TimeoutMinutes 1|Out-Null
        $receipt.admission=Get-Content (Join-Path $out 'admission.json') -Raw|ConvertFrom-Json
        Assert-NativeBuildTimeRemaining;$receipt.passed=$true;$receipt.stage='complete'
    } catch {$receipt.error=$_.Exception.ToString();throw}
    finally {
        $receipt.finishedUtc=[DateTime]::UtcNow.ToString('o')
        if($receipt.budget){$receipt.budget.elapsedSeconds=$script:NativeEngineBuildBudget.clock.Elapsed.TotalSeconds}
        $script:NativeEngineBuildBudget=$oldBudget
        Write-BuildJson (Join-Path $out 'diagnostic.json') $receipt
    }
}
if($MyInvocation.InvocationName -ne '.') {Invoke-NativeMddsProbe $Output $WorkRoot $Deadline}
