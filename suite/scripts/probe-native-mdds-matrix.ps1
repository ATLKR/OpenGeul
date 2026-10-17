param([string]$MatrixOutput='', [string]$MatrixWorkRoot='', [string]$MatrixDeadline='')
$ErrorActionPreference='Stop'
# Distinct caller names survive the old driver's dot-sourced param defaults.
# Its invocation guard imports unchanged ownership/budget/private-PATH helpers only.
. (Join-Path $PSScriptRoot 'probe-native-mdds.ps1')

function Invoke-NativeMddsMatrixObservation([string]$Output,[string]$WorkRoot,[string]$Deadline) {
    foreach($path in @($Output,$WorkRoot)) {
        if(-not $path){throw 'Explicit owned evidence/work paths required.'}
        $parent=[IO.Path]::GetFullPath($path)
        while($parent){if(Test-Path -LiteralPath (Join-Path $parent '.git')){throw 'Diagnostic paths must be outside Git.'};$parent=[IO.Path]::GetDirectoryName($parent)}
    }
    $paths=New-BuildDirectories $WorkRoot $Output;$work=$paths.work;$out=$paths.output
    $oldBudget=$script:NativeEngineBuildBudget
    $receipt=[ordered]@{schemaVersion=1;kind='native-arm64-original-mdds-matrix-parse-observation';observationAdmitted=$false;runtimeTested=$false;oldFlatCompiled=$false;candidateCompiled=$false;engineQualified=$false;productQualified=$false;baseQualified=$false;
        productionHookInstalled=$false;originalTwoGnumericObjectsRebuilt=$false;
        scope='Original matrix parsing and builtin-traits compile-only; no actual Office custom specialization or Native21 result.';stage='native-host';startedUtc=[DateTime]::UtcNow.ToString('o')}
    try {
        $script:NativeEngineBuildBudget=New-NativeBuildBudget -DeadlineUtc $Deadline -MaximumMinutes 20
        $receipt.budget=$script:NativeEngineBuildBudget.record;$receipt.host=Get-NativeBuildHost
        $repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'));$manifest=Join-Path $repo 'suite/engine-build/source-build.json'
        $receipt.source=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'probe-native-mdds-matrix.ps1') $manifest $out
        $receipt.files=@(foreach($relative in @('.github/workflows/office-native-mdds-matrix-probe.yml','suite/scripts/probe-native-mdds-matrix.ps1','suite/scripts/native_mdds_matrix_observation.py','suite/scripts/matrix-include.cpp','suite/scripts/matrix-builtin-equality.cpp','suite/tests/test_native_mdds_matrix_observation.py','suite/scripts/probe-native-mdds.ps1','suite/scripts/native_mdds_probe.py','suite/scripts/mdds-equality-probe.cpp','suite/scripts/build-native-engine.ps1')) {
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
        $receipt.stage='authenticated-complete-sources'
        $lo=Join-Path $work 'libreoffice.tar.xz';$mdds=Join-Path $work 'mdds-3.2.1.tar.xz';$boost=Join-Path $work 'boost_1_91_0.tar.xz'
        $pin=Get-SourcePin (Join-Path $repo 'suite/config/runtime.arm64.lock.json')
        if($pin.size -ne 302435508 -or $pin.sha256 -cne '296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785'){throw 'Exact LO source pin differs.'}
        $receipt.libreoffice=Get-AuthenticatedDownload $pin.url $lo $pin.size SHA256 $pin.sha256 (Join-Path $out 'libreoffice-download.json')
        $receipt.mdds=Get-AuthenticatedDownload 'https://dev-www.libreoffice.org/src/mdds-3.2.1.tar.xz' $mdds 648256 SHA256 '673f5bb94612dbba581fc92b99b5e5dd1a53e29496a5dbc936432f6b0687c112' (Join-Path $out 'mdds-download.json')
        $receipt.boost=Get-AuthenticatedDownload 'https://dev-www.libreoffice.org/src/boost_1_91_0.tar.xz' $boost 21664068 SHA256 '2f975c10da79511c2f218189fc8a12eef1a92e3bd18206e9841d406296d065eb' (Join-Path $out 'boost-download.json')
        $receipt.stage='reused-authenticated-source-preparation'
        Invoke-LoggedCommand $python @($helper,'prepare',$mdds,$lo,$boost,$work,$out,(Join-Path $PSScriptRoot 'mdds-equality-probe.cpp')) $work (Join-Path $out 'prepare') -TimeoutMinutes 5|Out-Null
        $plan=Get-Content (Join-Path $out 'source-plan.json') -Raw|ConvertFrom-Json;$receipt.sourcePlan=$plan
        # Source preparation may retain the old flat candidate scratch, but this
        # companion compiles only the unchanged original matrix include tree.
        $matrixHelper=Join-Path $PSScriptRoot 'native_mdds_matrix_observation.py'
        Copy-Item $matrixHelper (Join-Path $out 'native_mdds_matrix_observation.py')
        Invoke-LoggedCommand $python @($matrixHelper,'prepare',$out,$work,$PSScriptRoot) $work (Join-Path $out 'matrix-prepare') -TimeoutMinutes 1|Out-Null
        $matrixPlan=Get-Content (Join-Path $out 'matrix-plan.json') -Raw|ConvertFrom-Json;$receipt.matrixPlan=$matrixPlan
        $dev=Join-Path $vs 'Common7/Tools/VsDevCmd.bat';Assert-UnlinkedPath $dev
        $environment=Get-MddsToolchainEnvironment $dev (Join-Path ([Environment]::SystemDirectory) 'cmd.exe') $work $out
        $receipt.pathEnvironment=Get-Content (Join-Path $out 'path-environment.json') -Raw|ConvertFrom-Json
        $previous=@{};foreach($name in $environment.Keys){$previous[$name]=[Environment]::GetEnvironmentVariable($name);[Environment]::SetEnvironmentVariable($name,$environment[$name])}
        $previousCL=$env:CL;$previous_CL=$env:_CL_;$previousLINK=$env:LINK;$previous_LINK=$env:_LINK_;$env:CL='';$env:_CL_='';$env:LINK='';$env:_LINK_=''
        try {
            $common=@('/nologo','/Bv','/showIncludes','/std:c++20','/permissive-','/Zc:__cplusplus,preprocessor','/EHs','/D_ARM64_=1','/MD','/utf-8','/Gd','/GR','/Gs','/GS','/Gy','/bigobj','/Zc:inline','/c',('/I'+$matrixPlan.boostInclude))
            $receipt.commonCompilerArguments=$common;$receipt.compilerPath=$cl
            foreach($case in $matrixPlan.cases) {
                $receipt.stage=$case.name+'-compile'
                $arguments=@(('/I'+$case.include))+$common+@(('/Fo'+$case.object),$case.translationUnit)
                Write-BuildJson (Join-Path $out ($case.name+'-argv.json')) ([ordered]@{file=$cl;arguments=$arguments;include=$environment['INCLUDE'];lib=$environment['LIB'];libpath=$environment['LIBPATH'];sdk=$environment['WindowsSdkDir'];clEnvironment='';underscoreClEnvironment='';linkEnvironment='';underscoreLinkEnvironment=''})
                try {Invoke-LoggedCommand $cl $arguments $work (Join-Path $out $case.name) -TimeoutMinutes 2|Out-Null}
                catch {if(-not(Test-Path (Join-Path $out ($case.name+'.command.json')))){throw}}
                # Normal cl exit 2 is an observation; abnormal exits/death/drain reject.
                Invoke-LoggedCommand $python @($matrixHelper,'admit-case',$out,$case.name) $work (Join-Path $out ($case.name+'-admission')) -TimeoutMinutes 1|Out-Null
                $observed=Get-Content (Join-Path $out ($case.name+'-admission.json')) -Raw|ConvertFrom-Json
                if($observed.cases[0].classification -ceq 'compile-success') {
                    Invoke-LoggedCommand $dumpbin @('/nologo','/headers',$case.object) $work (Join-Path $out ($case.name+'-object-headers')) -TimeoutMinutes 1|Out-Null
                }
            }
        } finally {
            foreach($name in $environment.Keys){[Environment]::SetEnvironmentVariable($name,$previous[$name])};$env:CL=$previousCL;$env:_CL_=$previous_CL;$env:LINK=$previousLINK;$env:_LINK_=$previous_LINK
        }
        $receipt.stage='matrix-observation-admission'
        Invoke-LoggedCommand $python @($matrixHelper,'admit',$out) $work (Join-Path $out 'matrix-admission') -TimeoutMinutes 1|Out-Null
        $receipt.admission=Get-Content (Join-Path $out 'matrix-admission.json') -Raw|ConvertFrom-Json
        Assert-NativeBuildTimeRemaining;$receipt.observationAdmitted=$true;$receipt.stage='complete'
    } catch {$receipt.error=$_.Exception.ToString();throw}
    finally {
        $receipt.finishedUtc=[DateTime]::UtcNow.ToString('o')
        if($receipt.budget){$receipt.budget.elapsedSeconds=$script:NativeEngineBuildBudget.clock.Elapsed.TotalSeconds}
        $script:NativeEngineBuildBudget=$oldBudget
        Write-BuildJson (Join-Path $out 'diagnostic.json') $receipt
    }
}
if($MyInvocation.InvocationName -ne '.') {Invoke-NativeMddsMatrixObservation $MatrixOutput $MatrixWorkRoot $MatrixDeadline}
