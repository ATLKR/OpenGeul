param([string]$PythonControlOutput='', [string]$PythonControlWorkRoot='', [string]$PythonControlDeadline='')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'build-native-engine.ps1')
. (Join-Path $PSScriptRoot 'native-python-command.ps1')

function Get-PythonControlChildEnvironment([hashtable]$Selected) {
    # Read only explicit system/build fields. Never enumerate or save inherited values.
    $allowed=@('SystemRoot','WINDIR','COMSPEC','OS','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','ProgramFiles','ProgramFiles(x86)','ProgramW6432','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','ProgramData','ALLUSERSPROFILE','SystemDrive','HOMEDRIVE','HOMEPATH')
    $child=@{}
    foreach($name in $allowed) {
        $value=[Environment]::GetEnvironmentVariable($name)
        if($null -ne $value){$child[$name]=$value}
    }
    foreach($name in $Selected.Keys) {
        if($name -cnotin @('CL','_CL_','LINK','_LINK_','INCLUDE','LIB','LIBPATH','PATH','MAKEFLAGS')){throw 'Unexpected selected build environment field.'}
        $child[$name]=$Selected[$name]
    }
    return $child
}

function Get-PythonControlPropertyCases {
    @(
        [ordered]@{requested='default';evidenceName='preferred-00-default'},
        [ordered]@{requested='x86';evidenceName='preferred-01-x86'},
        [ordered]@{requested='ARM64';evidenceName='preferred-02-uppercase-arm64'},
        [ordered]@{requested='arm64';evidenceName='preferred-03-lowercase-arm64'}
    )
}

function New-PythonControlMeasurementPaths([string]$Out,$Case) {
    $prefix=Join-Path $Out $Case.evidenceName
    $propertyFile=$prefix+'.properties.txt'
    foreach($path in @($propertyFile,($prefix+'.command.json'),($prefix+'.stdout.log'),($prefix+'.stderr.log'))) {
        if(Test-Path -LiteralPath $path){throw 'Preserve prior property measurement evidence; never reuse an old invocation receipt.'}
    }
    return [ordered]@{prefix=$prefix;properties=$propertyFile}
}

function Complete-PythonControlResult($Receipt,$Baseline,$Candidate,$Runtime) {
    $Receipt.passed=$false;$Receipt.causalCorrectionProven=$false
    $Receipt.candidateFeasible=$Candidate.status -ceq 'passed' -and $Runtime.testsPassed -eq $true
    if($Baseline.status -cne 'reproduced' -or -not $Receipt.candidateFeasible) {
        $Receipt.stage='non-reproduction-or-incomplete-pair'
        throw 'Overall success requires exact baseline reproduction and native candidate build/KAT.'
    }
    $Receipt.causalCorrectionProven=$true;$Receipt.passed=$true;$Receipt.stage='complete'
}

function Get-PythonToolIdentity([string]$Path,[int]$ExpectedMachine) {
    Assert-UnlinkedPath $Path;$bytes=[IO.File]::ReadAllBytes($Path)
    if($bytes.Length -lt 64 -or $bytes[0] -ne 77 -or $bytes[1] -ne 90){throw 'Invalid host tool PE.'}
    $offset=[BitConverter]::ToUInt32($bytes,60)
    if($offset -gt $bytes.Length-26 -or [BitConverter]::ToUInt32($bytes,[int]$offset) -ne 17744){throw 'Invalid host tool PE headers.'}
    $machine=[BitConverter]::ToUInt16($bytes,[int]$offset+4)
    if(($ExpectedMachine -ne 0 -and $machine -ne $ExpectedMachine) -or $machine -notin @(0x14c,0x8664,0xAA64)){throw 'Selected host tool architecture differs.'}
    $resource=(Get-Item $Path).VersionInfo
    return [ordered]@{path=$Path;machine=[int]$machine;size=$bytes.Length;sha256=(Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant();fileVersion=$resource.FileVersion;productVersion=$resource.ProductVersion;role='diagnostic build-host tool'}
}

function Get-PythonControlEnvironment([string]$Dev,[string]$Cmd,[string]$Work,[string]$Out) {
    $private=Join-Path $Work 'selected-path.private.txt';Assert-UnlinkedPath $private
    if(Test-Path $private){throw 'Preserve existing private environment.'}
    $batch=Join-Path $Out 'toolchain-environment.cmd'
    @('@echo off',('call "'+$Dev+'" -no_logo -arch=arm64 -host_arch=arm64'),'if errorlevel 1 exit /b %errorlevel%',
      'set CL=-D_SILENCE_EXPERIMENTAL_COROUTINE_DEPRECATION_WARNINGS','set _CL_=','set LINK=','set _LINK_=',
      'set PATH > "%~1"','if errorlevel 1 exit /b %errorlevel%','set INCLUDE','set LIB','set LIBPATH','exit /b 0')|Set-Content $batch -Encoding ascii
    try {
        Invoke-LoggedCommand $Cmd @('/d','/c',$batch,$private) $Work (Join-Path $Out 'toolchain-environment') -TimeoutMinutes 2|Out-Null
        $environment=@{CL='-D_SILENCE_EXPERIMENTAL_COROUTINE_DEPRECATION_WARNINGS';_CL_='';LINK='';_LINK_='';MAKEFLAGS=''}
        foreach($line in Get-Content (Join-Path $Out 'toolchain-environment.stdout.log')) {
            if($line -match '^(INCLUDE|LIB|LIBPATH)=(.*)$'){$environment[$Matches[1]]=$Matches[2]}
        }
        $pathLines=@(Get-Content $private|Where-Object {$_ -match '^PATH='})
        if($pathLines.Count -ne 1 -or -not $environment.INCLUDE -or -not $environment.LIB){throw 'Incomplete selected environment.'}
        # Only known VS/SDK/Windows/Git entries survive. Raw inherited PATH never enters evidence.
        $allowed=@($pathLines[0].Substring(5).Split(';')|Where-Object {$_ -match '(?i)Microsoft Visual Studio|Windows Kits|\\Windows(?:\\|$)|\\Git\\' }|Select-Object -Unique)
        $environment.PATH=$allowed -join ';'
        $digest=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($environment.PATH))).ToLowerInvariant()
        Write-BuildJson (Join-Path $Out 'selected-environment.json') ([ordered]@{CL=$environment.CL;_CL_='';LINK='';_LINK_='';INCLUDE=$environment.INCLUDE;LIB=$environment.LIB;LIBPATH=$environment.LIBPATH;pathSha256=$digest;pathEntries=$allowed.Count;rawInheritedPathRetained=$false;sanitizedKnownToolPathMayAppearInMsbuild=$true})
        return $environment
    } finally {if(Test-Path $private){Assert-UnlinkedPath $private;Remove-Item -LiteralPath $private -ErrorAction Stop}}
}

function Invoke-PythonControl([string]$ControlOutput,[string]$ControlWork,[string]$ControlDeadline) {
    foreach($path in @($ControlOutput,$ControlWork)) {
        if(-not $path){throw 'Explicit exclusive diagnostic paths required.'}
        $parent=[IO.Path]::GetFullPath($path)
        while($parent){if(Test-Path (Join-Path $parent '.git')){throw 'Evidence/work must be outside Git.'};$parent=[IO.Path]::GetDirectoryName($parent)}
    }
    $paths=New-BuildDirectories $ControlWork $ControlOutput;$work=$paths.work;$out=$paths.output
    $oldBudget=$script:NativeEngineBuildBudget
    $r=[ordered]@{schemaVersion=1;kind='native-cpython-host-ab';passed=$false;causalCorrectionProven=$false;engineQualified=$false;fullExtensionCoverage=$false;stage='native-host';startedUtc=[DateTime]::UtcNow.ToString('o');scopeDifferences=@('Minimal pcbuild.sln pythoncore target, then unchanged python.vcxproj Build interpreter target; surrounding make-j4 Office workload absent.','Original effective generated sources and objects not retained: source-pinned reconstruction.','x64 _freeze_module solution mapping remains authentic build-host helper; no x64 product fallback.');propertySupport=$null}
    try {
        $script:NativeEngineBuildBudget=New-NativeBuildBudget -DeadlineUtc $ControlDeadline -MaximumMinutes 80
        $r.budget=$script:NativeEngineBuildBudget.record;$r.host=Get-NativeBuildHost
        $repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'));$data=Join-Path $repo 'suite/diagnostics/native-python'
        $helper=Join-Path $PSScriptRoot 'native_python_control.py';$python=(Get-Command python -ErrorAction Stop).Source
        $r.source=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'probe-native-python.ps1') (Join-Path $repo 'suite/engine-build/source-build.json') $out
        foreach($tool in @($python,(Get-Process -Id $PID).Path)){if((Get-ProductPeIdentity $tool).role -cne 'nativeArm64'){throw 'Native ARM64 controller required.'}}
        Copy-Item $data (Join-Path $out 'diagnostic-source') -Recurse
        if($env:OPENGEUL_PYTHON_BUDGET_RECEIPT){Copy-Item $env:OPENGEUL_PYTHON_BUDGET_RECEIPT (Join-Path $out 'job-budget.json')}
        $vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
        Invoke-LoggedCommand $vswhere @('-latest','-products','*','-version','[18.0,19.0)','-format','json') $work (Join-Path $out 'vswhere') -TimeoutMinutes 1|Out-Null
        $instances=@(Get-Content (Join-Path $out 'vswhere.stdout.log') -Raw|ConvertFrom-Json)
        if($instances.Count -ne 1){throw 'Exactly one VS18 required.'};$vs=$instances[0].installationPath
        $version=(Get-Content (Join-Path $vs 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt') -Raw).Trim()
        if($version -cne '14.51.36231'){throw 'Exact actual Native21 toolset required.'}
        $tools=Join-Path $vs ('VC/Tools/MSVC/'+$version);$native=Join-Path $tools 'bin/Hostarm64/arm64'
        $r.tools=@(foreach($hostName in @('HostX86','Hostarm64')){foreach($name in @('cl.exe','link.exe','c2.dll')){
            $expected=if($hostName -ceq 'Hostarm64'){0xAA64}else{0x14c}
            Get-PythonToolIdentity (Join-Path $tools ('bin/'+$hostName+'/arm64/'+$name)) $expected
        }})
        # Original configure selected MSBuild/Current/Bin, without an arm64 suffix.
        $msbuild=Join-Path $vs 'MSBuild/Current/Bin/MSBuild.exe';$r.msbuild=Get-PythonToolIdentity $msbuild 0
        $git=(Get-Command git -ErrorAction Stop).Source;$gitRoot=[IO.Path]::GetDirectoryName([IO.Path]::GetDirectoryName($git));$patch=Join-Path $gitRoot 'usr/bin/patch.exe'
        if(-not(Test-Path $patch)){$patch=Join-Path ([IO.Path]::GetDirectoryName($gitRoot)) 'usr/bin/patch.exe'}
        if(-not(Test-Path $patch)){throw 'Authentic GNU patch required; no substitute transformation.'}
        Invoke-LoggedCommand $patch @('--version') $work (Join-Path $out 'patch-version') -TimeoutMinutes 1|Out-Null
        $r.stage='source-downloads';$cache=Join-Path $work 'downloads';New-Item -ItemType Directory $cache|Out-Null
        $pins=Get-Content (Join-Path $data 'source-pins.json') -Raw|ConvertFrom-Json
        foreach($key in @('python','zlib','bootstrap')) {
            $p=$pins.$key
            Get-AuthenticatedDownload ('https://dev-www.libreoffice.org/src/'+$p.filename) (Join-Path $cache $p.filename) $p.bytes SHA256 $p.sha256 (Join-Path $out ($key+'-download.json'))|Out-Null
        }
        $r.stage='authentic-source-reconstruction'
        Invoke-LoggedCommand $python @($helper,'prepare',$data,$cache,$work,$out,$patch) $work (Join-Path $out 'prepare') -TimeoutMinutes 10|Out-Null
        $r.sourcePlan=Get-Content (Join-Path $out 'source-plan.json') -Raw|ConvertFrom-Json
        $environment=Get-PythonControlEnvironment (Join-Path $vs 'Common7/Tools/VsDevCmd.bat') (Join-Path ([Environment]::SystemDirectory) 'cmd.exe') $work $out
        $childEnvironment=Get-PythonControlChildEnvironment $environment
        & {
            $r.stage='selected-child-common-appdata-preflight'
            $preflight=Join-Path $out 'command-environment.properties.txt'
            if(Test-Path -LiteralPath $preflight){throw 'Preserve prior environment preflight evidence.'}
            $probeProject=Join-Path $data 'command-environment.proj'
            Invoke-PythonControlBuildCommand $msbuild @($probeProject,'/t:Probe','/nodeReuse:false',('/p:PythonControlEnvironmentOutput='+$preflight)) $work (Join-Path $out 'command-environment') -ChildEnvironment $childEnvironment -TimeoutMinutes 2|Out-Null
            $r.commandEnvironmentPreflight=Get-Content -LiteralPath $preflight
            $observer=Join-Path $data 'observe-tools.targets'
            $common=@('/p:Configuration=Release','/p:Platform=ARM64','/maxcpucount','/p:PlatformToolset=v145','/p:VisualStudioVersion=18.0','/ToolsVersion:Current','/p:WindowsTargetPlatformVersion=10.0.26100.0',('/p:zlibDir='+$work+'/zlib'),('/p:ForceImportAfterCppTargets='+$observer),'/nodeReuse:false')
            # Measure installed property evaluation before using any assumed spelling/value.
            $r.stage='installed-property-measurement';$measurements=@()
            foreach($propertyCase in @(Get-PythonControlPropertyCases)) {
                $value=$propertyCase.requested
                $measurementPaths=New-PythonControlMeasurementPaths $out $propertyCase
                $propertyFile=$measurementPaths.properties;$prefix=$measurementPaths.prefix
                $argv=@((Join-Path $work 'candidate/PCbuild/pythoncore.vcxproj'),'/t:PythonControlEvaluate',('/p:PythonControlProperties='+$propertyFile))+$common
                if($value -cne 'default'){$argv+=@('/p:PreferredToolArchitecture='+$value)}
                try {Invoke-PythonControlBuildCommand $msbuild $argv $work $prefix -ChildEnvironment $childEnvironment -TimeoutMinutes 2|Out-Null}
                catch {if(-not(Test-Path -LiteralPath ($prefix+'.command.json'))){throw}}
                # Paths were exclusively absent before this invocation, so this receipt is current.
                $command=Get-Content -LiteralPath ($prefix+'.command.json') -Raw|ConvertFrom-Json
                if($command.file -cne $msbuild -or ($command.arguments -join [char]0) -cne ($argv -join [char]0)){throw 'Property measurement receipt does not bind current invocation.'}
                $measurements+=@{requested=$value;evidenceName=$propertyCase.evidenceName;commandReceipt=$prefix+'.command.json';commandPassed=$command.passed;exitCode=$command.exitCode;properties=if(Test-Path $propertyFile){Get-Content $propertyFile}else{$null}}
            }
            $candidateSelection=@('/p:PythonControlHost=Hostarm64');$mechanism='explicit conditional CLToolPath/LinkToolPath fallback; Preferred property unsupported/unresolved'
            foreach($measurement in $measurements) {
                if($measurement.commandPassed -eq $true -and $measurement.requested -cin @('ARM64','arm64') -and @($measurement.properties|Where-Object {$_ -match '^(CLToolPath|VC_ExecutablePath_ARM64)=.*(?i:Hostarm64)[\\/]arm64[\\/]'}).Count -gt 0) {
                    $candidateSelection=@('/p:PreferredToolArchitecture='+$measurement.requested);$mechanism='PreferredToolArchitecture='+$measurement.requested;break
                }
            }
            $r.candidateSelection=$mechanism
            $r.propertySupport=@{measurements=$measurements;selection=$mechanism;baseline='Unchanged default selection required to emit HostX86 compiler/linker; no host override.';actualCommandProofRequired=$true}
            Write-BuildJson (Join-Path $out 'property-support.json') $r.propertySupport
            foreach($case in @('baseline','candidate')) {
                $r.stage=$case+'-MSBuild'
                $caseRoot=Join-Path $work $case;$selection=if($case -ceq 'baseline'){@()}else{$candidateSelection}
                $argv=@((Join-Path $caseRoot 'PCbuild/pcbuild.sln'),'/t:pythoncore',('/bl:'+ (Join-Path $out ($case+'.binlog'))),'/v:diagnostic')+$common+$selection
                # /MP and original unbounded /maxcpucount remain identical across arms.
                Get-CimInstance Win32_OperatingSystem|Select-Object TotalVisibleMemorySize,FreePhysicalMemory,TotalVirtualMemorySize,FreeVirtualMemory|ConvertTo-Json|Set-Content (Join-Path $out ($case+'-memory-before.json'))
                try {Invoke-PythonControlBuildCommand $msbuild $argv $caseRoot (Join-Path $out ($case+'-build')) -ChildEnvironment $childEnvironment -TimeoutMinutes 22|Out-Null}
                catch {if(-not(Test-Path (Join-Path $out ($case+'-build.command.json')))){throw}}
                finally {
                    $observed=@(foreach($tool in $r.tools){Get-PythonToolIdentity $tool.path $tool.machine})
                    Write-BuildJson (Join-Path $out ($case+'-tool-inventory.json')) ([ordered]@{toolsRoot=$tools;toolsetVersion=$version;tools=$r.tools;observedTools=$observed})
                    Invoke-LoggedCommand $python @($helper,'collect',$work,$out,$case) $work (Join-Path $out ($case+'-collect')) -TimeoutMinutes 5|Out-Null
                }
                Invoke-LoggedCommand $python @($helper,'admit',$data,$work,$out,$case) $work (Join-Path $out ($case+'-admit')) -TimeoutMinutes 1|Out-Null
            }
            $r.stage='candidate-interpreter'
            $argv=@((Join-Path $work 'candidate/PCbuild/python.vcxproj'),'/t:Build',('/bl:'+ (Join-Path $out 'interpreter.binlog')),'/v:diagnostic')+$common+$candidateSelection
            Invoke-PythonControlBuildCommand $msbuild $argv (Join-Path $work 'candidate') (Join-Path $out 'interpreter-build') -ChildEnvironment $childEnvironment -TimeoutMinutes 8|Out-Null
        }
        $runtime=Join-Path $out 'runtime';$program=Join-Path $runtime 'program';New-Item -ItemType Directory $program -Force|Out-Null
        foreach($name in @('python.exe','python313.dll')){Copy-Item (Join-Path $work ('candidate/PCbuild/arm64/'+$name)) (Join-Path $program $name)}
        # Python needs its authentic pure-Python stdlib; no extension or DLL substitutes.
        Copy-Item (Join-Path $work 'candidate/Lib') (Join-Path $program 'Lib') -Recurse
        $r.crtPlan=Get-AppLocalCrtPlan $tools 'v145';$terms=Save-VcRedistributionTerms (Join-Path $out 'Microsoft-VC145-redistribution.html')
        $r.crtInstall=Install-AppLocalCrt $r.crtPlan $program $terms.path
        $r.images=@(foreach($name in @('python.exe','python313.dll')){
            $image=Join-Path $program $name;$id=Get-ProductPeIdentity $image;if($id.role -cne 'nativeArm64'){throw 'Product image must be native ARM64.'}
            Invoke-LoggedCommand (Join-Path $native 'dumpbin.exe') @('/headers','/imports','/loadconfig',$image) $work (Join-Path $out ('dump-'+$name)) -TimeoutMinutes 1|Out-Null;$id
        })
        $r.crtClosure=Invoke-CrtImportAudit $python $repo $runtime $out
        $r.stage='native-builtin-sha2-KAT'
        Invoke-LoggedCommand $python @((Join-Path $PSScriptRoot 'native_python_runtime.py'),(Join-Path $program 'python.exe'),(Join-Path $program 'python313.dll'),(Join-Path $PSScriptRoot 'native_python_kat.py'),(Join-Path $data 'sha2-kat-vectors.json'),$out) $work (Join-Path $out 'runtime-observer') -TimeoutMinutes 3|Out-Null
        $r.baseline=Get-Content (Join-Path $out 'baseline-admission.json') -Raw|ConvertFrom-Json
        $r.candidate=Get-Content (Join-Path $out 'candidate-admission.json') -Raw|ConvertFrom-Json
        Complete-PythonControlResult $r $r.baseline $r.candidate (Get-Content (Join-Path $out 'native-runtime-identity.json') -Raw|ConvertFrom-Json)
        $r.extensionsPending='Full authentic solution requires built LO OpenSSL, libffi, bzip2, SQLite, lzma and other external artifacts. No modules removed/stubbed; full extension/full engine coverage pending.'
    } catch {$r.error=$_.Exception.ToString();throw}
    finally {
        foreach($case in @('baseline','candidate')){if(Test-Path (Join-Path $out ($case+'-admission.json'))){$r[$case]=Get-Content (Join-Path $out ($case+'-admission.json')) -Raw|ConvertFrom-Json}}
        $r.finishedUtc=[DateTime]::UtcNow.ToString('o')
        if($r.budget){$r.budget.elapsedSeconds=$script:NativeEngineBuildBudget.clock.Elapsed.TotalSeconds}
        $script:NativeEngineBuildBudget=$oldBudget;Write-BuildJson (Join-Path $out 'diagnostic.json') $r
    }
}
if($MyInvocation.InvocationName -ne '.') {Invoke-PythonControl $PythonControlOutput $PythonControlWorkRoot $PythonControlDeadline}
