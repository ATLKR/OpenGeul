param(
    [string]$WorkDirectory='.work/native30-identity-work',
    [string]$OutputDirectory='.work/native30-identity-evidence',
    [string]$DeadlineUtc='',
    [string]$ExpectedSourceCommit='',
    [string]$ExpectedSourceTree=''
)
$ErrorActionPreference='Stop'
$driver=Join-Path $PSScriptRoot 'build-native-engine.ps1'
$driverSha='b91a49f1937eaa11ff364f107bdf532dfae1430f2cf72dbb772a328316b7df9c'
if((Get-FileHash -LiteralPath $driver -Algorithm SHA256).Hash.ToLowerInvariant() -cne $driverSha){throw 'Reviewed identity producer driver changed.'}
. $driver -WorkDirectory $WorkDirectory -OutputDirectory $OutputDirectory -DeadlineUtc $DeadlineUtc

function Assert-IdentityCommandReceipt($Receipt){
    if($Receipt.passed -ne $true -or $Receipt.exitCode -ne 0 -or $Receipt.pid -le 0 -or
       $Receipt.creationUtcTicks -isnot [long] -or $Receipt.creationUtcTicks -le 0 -or
       $Receipt.pipeDrainComplete -ne $true -or $Receipt.forcedTermination -ne $false -or
       $Receipt.directProcessDeathVerified -ne $true -or $Receipt.processTreeCleanup -cne 'not-requested' -or
       @($Receipt.cleanupErrors).Count){throw 'Identity control requires exact creation integer, normal zero, drained unforced direct death.'}
}

function Get-IdentityControlFile([string]$Path,[long]$MaximumBytes=33554432){
    Assert-UnlinkedPath $Path
    $item=Get-Item -LiteralPath $Path -Force
    if($item -isnot [IO.FileInfo] -or $item.Length -le 0 -or $item.Length -gt $MaximumBytes){throw 'Bounded regular diagnostic input required.'}
    return [ordered]@{path=$item.FullName;bytes=$item.Length;sha256=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
}

function Assert-NoInheritedGitRedirection {
    $names=@(Get-ChildItem Env:|Where-Object {$_.Name -match '^GIT_'}|ForEach-Object {$_.Name})
    if($names.Count){throw ('Inherited Git environment is forbidden for real no-Git placement: '+($names -join ','))}
}

function Assert-IdentitySourceInputs([string]$Commit,[string]$Tree,[string]$EventName){
    if($Commit -cnotmatch '^[0-9a-f]{40}$'){throw 'Exact diagnostic source commit input required.'}
    if($EventName -cnotin @('push','workflow_dispatch')){throw 'Identity control requires a bound push or explicit manual dispatch.'}
    if(($EventName -ceq 'workflow_dispatch' -or $Tree) -and $Tree -cnotmatch '^[0-9a-f]{40}$'){
        throw 'Manual dispatch requires an exact reviewed source tree; any supplied tree must be exact.'
    }
    return [ordered]@{eventName=$EventName;expectedSourceCommit=$Commit;expectedSourceTree=$Tree;
        explicitTreeInputRequired=($EventName -ceq 'workflow_dispatch');treeCryptographicallyBoundBySourceCommit=$true}
}

function New-IdentityNoGitSource([string]$Repo,[string]$Evidence){
    if(-not $env:RUNNER_TEMP -or $env:GITHUB_RUN_ID -cnotmatch '^[1-9][0-9]*$' -or $env:GITHUB_RUN_ATTEMPT -cnotmatch '^[1-9][0-9]*$'){
        throw 'Actual runner temp/run/attempt are required for a fresh owned no-Git source.'
    }
    Assert-NoInheritedGitRedirection
    Assert-UnlinkedPath $env:RUNNER_TEMP
    $temp=[IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $path=Join-Path $temp ('native30-identity-nogit-'+$env:GITHUB_RUN_ID+'-'+$env:GITHUB_RUN_ATTEMPT)
    if(Test-Path -LiteralPath $path){throw 'No-Git source namespace already exists; preserve it.'}
    $checkout=[IO.Path]::GetFullPath($Repo).TrimEnd([IO.Path]::DirectorySeparatorChar)
    if($path.StartsWith($checkout+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
        throw 'No-Git source must physically lie outside the checkout.'
    }
    $checks=@();$ancestor=$path
    while($ancestor){
        Assert-UnlinkedPath $ancestor
        $marker=Join-Path $ancestor '.git';$exists=Test-Path -LiteralPath $marker
        $checks+=,[ordered]@{ancestor=$ancestor;gitMarker=$marker;exists=$exists}
        if($exists){throw 'No-Git source has a Git marker in its ancestry.'}
        $next=[IO.Path]::GetDirectoryName($ancestor)
        if($next -ceq $ancestor){break};$ancestor=$next
    }
    New-Item -ItemType Directory -Path $path -ErrorAction Stop|Out-Null
    Write-BuildJson (Join-Path $Evidence 'no-git-placement.json') ([ordered]@{
        sourceDirectory=$path;runnerTemp=$temp;checkout=$checkout;freshOwned=$true;outsideCheckout=$true;
        ancestorChecks=$checks;inheritedGitEnvironmentNames=@();noRepositoryCreated=$true;diagnosticOnly=$true})
    return $path
}

function Invoke-IdentityFixture([string]$CaseRoot,[string]$Archive){
    Assert-NativeBuildTimeRemaining
    $spec=Get-Content -LiteralPath (Join-Path $CaseRoot 'case.json') -Raw|ConvertFrom-Json -AsHashtable
    $result=[ordered]@{case=$spec.case;accepted=$false;expectedAccepted=$spec.expectedAccepted;diagnosticOnly=$true;
        fixtureProvenance=$spec.fixtureProvenance;fullEngineQualified=$false;baseQualified=$false;runtimeExecuted=$false;officeReplacementCertified=$false}
    try{
        $proof=Set-RuntimeBuildIdentity $spec.runtimeRoot $Archive $spec.sourcePin $spec.sourceCommit $spec.evidenceDirectory $spec.configuration $spec.installedRuntimeStage
        $proof.finalVerification=Assert-RuntimeBuildIdentity $spec.runtimeRoot $spec.sourcePin $proof
        $outer=[ordered]@{sourcePin=$spec.sourcePin;sourceCommit=$spec.sourceCommit;configuration=$spec.configuration;
            installedRuntimeStage=$spec.installedRuntimeStage;runtimeBuildIdentity=$proof;
            diagnosticOnly=$true;fixtureProvenance=$spec.fixtureProvenance;fullEngineQualified=$false;baseQualified=$false;runtimeExecuted=$false;officeReplacementCertified=$false}
        $json=$outer|ConvertTo-Json -Depth 20
        Write-NewIdentityBytes (Join-Path $CaseRoot 'identity-control-proof.json') (([Text.UTF8Encoding]::new($false,$true)).GetBytes($json+"`n"))
        $result.accepted=$true;$result.identityMode=$proof.identityMode
    }catch{$result.error=$_.Exception.Message}
    finally{Write-BuildJson (Join-Path $CaseRoot 'producer-result.json') $result}
    if($result.accepted -ne $spec.expectedAccepted){throw ('Unexpected producer fixture outcome: '+$spec.case+'; '+$result.error)}
}

function Invoke-NativeIdentityControl([string]$WorkDirectory,[string]$OutputDirectory,[string]$DeadlineUtc,[string]$ExpectedSourceCommit,[string]$ExpectedSourceTree){
    $paths=New-BuildDirectories $WorkDirectory $OutputDirectory;$work=$paths.work;$evidence=$paths.output
    $repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'));$data=Join-Path $repo 'suite/diagnostics/native-runtime-identity'
    $previous=$script:NativeEngineBuildBudget
    $receipt=[ordered]@{schemaVersion=1;kind='native30-bounded-authentic-runtime-identity-control';diagnosticOnly=$true;
        completed=$false;status='inconclusive';stage='budget';startedUtc=[DateTime]::UtcNow.ToString('o');
        fullEngineQualified=$false;baseQualified=$false;runtimeExecuted=$false;officeReplacementCertified=$false;
        qualifiedInputArtifact=$null;historicalNative29OriginalIniBytesObserved=$false;upstreamCoreCheckoutManufactured=$false}
    try{
        if(-not $DeadlineUtc -or -not $env:OPENGEUL_IDENTITY_CONTROL_BUDGET_RECEIPT){throw 'Original first-step deadline/budget receipt required.'}
        $budget=Get-Content -LiteralPath $env:OPENGEUL_IDENTITY_CONTROL_BUDGET_RECEIPT -Raw|ConvertFrom-Json
        if($budget.origin -cne 'first-user-step' -or $budget.deadlineUtc -cne $DeadlineUtc -or $budget.controlMinutes -ne 15 -or $budget.jobTimeoutMinutes -ne 20 -or $budget.nominalReserveMinutes -ne 5){throw 'Original shared identity budget changed.'}
        $script:NativeEngineBuildBudget=New-NativeBuildBudget $DeadlineUtc 15;$receipt.budget=$script:NativeEngineBuildBudget.record
        Copy-Item -LiteralPath $env:OPENGEUL_IDENTITY_CONTROL_BUDGET_RECEIPT -Destination (Join-Path $evidence 'job-budget.json') -ErrorAction Stop
        $receipt.host=Get-NativeBuildHost
        $controller=Get-Process -Id $PID;$receipt.controller=Get-ProductPeIdentity $controller.Path
        if($receipt.controller.role -cne 'nativeArm64'){throw 'Actual PowerShell controller PE must be native ARM64.'}
        $receipt.controllerCreation=Get-CommandCreationIdentity $controller
        Assert-NoInheritedGitRedirection
        $receipt.stage='source-binding'
        $receipt.sourceInputs=Assert-IdentitySourceInputs $ExpectedSourceCommit $ExpectedSourceTree $env:GITHUB_EVENT_NAME
        $receipt.source=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'probe-native-identity-control.ps1') (Join-Path $data 'source.json') $evidence
        if($receipt.source.sourceCommit -cne $ExpectedSourceCommit -or ($ExpectedSourceTree -and $receipt.source.sourceTree -cne $ExpectedSourceTree)){throw 'Actual source differs from reviewed diagnostic commit/tree inputs.'}
        $receipt.productionDriver=Get-IdentityControlFile $driver
        $receipt.productionDriverSha256=$driverSha
        Copy-Item -LiteralPath $driver -Destination (Join-Path $evidence 'reviewed-build-native-engine.ps1') -ErrorAction Stop
        foreach($name in @('Invoke-LoggedCommand','Get-ProductPeIdentity','Set-RuntimeBuildIdentity','Assert-RuntimeBuildIdentity','Confirm-FileIdentity')){
            [IO.File]::WriteAllText((Join-Path $evidence ($name+'.reviewed-definition.ps1')),(Get-Command $name).Definition)
        }
        $receipt.inputs=@()
        foreach($file in Get-ChildItem -LiteralPath $data -File -Recurse|Where-Object {$_.Extension -ne '.pyc'}){
            $receipt.inputs+=,(Get-IdentityControlFile $file.FullName)
            $relative=[IO.Path]::GetRelativePath($data,$file.FullName);$copy=Join-Path (Join-Path $evidence 'inputs') $relative
            New-Item -ItemType Directory -Path (Split-Path $copy -Parent) -Force|Out-Null
            Copy-Item -LiteralPath $file.FullName -Destination $copy -ErrorAction Stop
        }
        $python=(Get-Command python -ErrorAction Stop).Source;$receipt.python=Get-ProductPeIdentity $python
        if($receipt.python.role -cne 'nativeArm64'){throw 'Diagnostic pure-consumer Python PE must be native ARM64.'}
        $helper=Join-Path $data 'control.py'
        Invoke-LoggedCommand $python @('-I','-B',$helper,'host','--output',(Join-Path $evidence 'python-native-host.json')) $repo (Join-Path $evidence 'python-native-host') -TimeoutMinutes 1|Out-Null
        $receipt.helperArchitecturePolicy='Cygwin setup/bash/git/perl/make are build helpers and may be foreign architecture; none is native product proof. Native Python/PowerShell identities are separately verified.'
        $receipt.stage='minimal-authenticated-cygwin'
        $setup=Join-Path $work 'setup-x86_64.exe'
        $receipt.cygwinSetup=Get-AuthenticatedDownload 'https://cygwin.com/setup-x86_64.exe' $setup 1574328 SHA512 '6acea47c59781c9e7f544a18d53935d59df6e44d5d52ac95ee165671b8e388820455eebf30ccc7d254b00c3d0eb694269a0f8dc84b17944c1f355dac9c5aafcc' (Join-Path $evidence 'cygwin-download.json')
        $cygwin=Join-Path $work 'cygwin'
        Invoke-LoggedCommand $setup @('--quiet-mode','--no-admin','--no-shortcuts','--no-startmenu','--no-desktop','--root',$cygwin,'--local-package-dir',(Join-Path $work 'cygwin-cache'),'--site','https://mirrors.kernel.org/sourceware/cygwin/','--packages','bash,coreutils,make,perl,git') $work (Join-Path $evidence 'cygwin-setup') -TimeoutMinutes 8|Out-Null
        $bash=Join-Path $cygwin 'bin/bash.exe';$cygpath=Join-Path $cygwin 'bin/cygpath.exe'
        $receipt.cygwinHelpers=@()
        foreach($name in @('bash','cygpath','env','git','perl','make')){$receipt.cygwinHelpers+=,(Get-IdentityControlFile (Join-Path $cygwin ('bin/'+$name+'.exe')))}
        $commands=Join-Path $work 'commands';New-Item -ItemType Directory -Path $commands|Out-Null
        $receipt.cygwinIdentity=Get-CygwinIdentity $bash $cygpath $commands $work $evidence
        $receipt.stage='real-no-git-source-placement'
        $sourceRoot=New-IdentityNoGitSource $repo $evidence
        $generated=Join-Path $evidence 'generated';$converted=@{}
        foreach($entry in @(@('source',$sourceRoot),@('parent',$repo),@('generated',$generated))){
            $result=Invoke-LoggedCommand $cygpath @('-u',$entry[1]) $work (Join-Path $evidence ('cygpath-'+$entry[0])) -TimeoutMinutes 1
            $unix=([IO.File]::ReadAllText($result.stdout)).Trim()
            $roundtrip=Invoke-LoggedCommand $cygpath @('-w',$unix) $work (Join-Path $evidence ('cygpath-'+$entry[0]+'-roundtrip')) -TimeoutMinutes 1
            $native=([IO.File]::ReadAllText($roundtrip.stdout)).Trim()
            if(-not [IO.Path]::GetFullPath($native).Equals([IO.Path]::GetFullPath($entry[1]),[StringComparison]::OrdinalIgnoreCase)){throw 'Native/POSIX path roundtrip differs.'}
            $converted[$entry[0]]=$unix
        }
        Write-BuildJson (Join-Path $evidence 'native-posix-roundtrip.json') $converted
        $receipt.stage='actual-source-archive-authentication'
        $pin=Get-SourcePin (Join-Path $repo 'suite/config/runtime.lock.json')
        $archive=Join-Path $work 'libreoffice-26.8.1.1.tar.xz'
        $receipt.sourceArchive=Get-AuthenticatedDownload $pin.url $archive $pin.size SHA256 $pin.sha256 (Join-Path $evidence 'source-download.json')
        $receipt.stage='authentic-fragment-generation'
        Invoke-LoggedCommand $python @('-I','-B',$helper,'render','--archive',$archive,'--source-root',$sourceRoot,'--output',$generated,'--unix-output',$converted.generated,'--unix-parent',$converted.parent,'--unix-source',$converted.source) $repo (Join-Path $evidence 'render-authentic-control') -TimeoutMinutes 3|Out-Null
        # The generated caller and complete original fragments exist in evidence BEFORE execution.
        Invoke-CygwinScript $bash $cygpath (Join-Path $generated 'generate-control.sh') $work (Join-Path $evidence 'authentic-generation') -NativeLinks|Out-Null
        $receipt.stage='fresh-fixture-producer-contract'
        $cases=Join-Path $evidence 'cases'
        Invoke-LoggedCommand $python @('-I','-B',$helper,'cases','--generated',$generated,'--output',$cases,'--parent',$receipt.source.sourceCommit) $repo (Join-Path $evidence 'prepare-finite-cases') -TimeoutMinutes 1|Out-Null
        $caseRoots=@(Get-ChildItem -LiteralPath $cases -Directory|Sort-Object Name)
        if($caseRoots.Count -ne 24){throw 'Finite identity case census changed.'}
        foreach($caseRoot in $caseRoots){Invoke-IdentityFixture $caseRoot.FullName $archive}
        $receipt.stage='independent-exact-consumer-snapshot-replay'
        Invoke-LoggedCommand $python @('-I','-B',$helper,'audit','--cases',$cases,'--output',(Join-Path $evidence 'identity-contract-replay.json')) $repo (Join-Path $evidence 'pure-consumer-replay') -TimeoutMinutes 2|Out-Null
        $receipt.replay=Get-IdentityControlFile (Join-Path $evidence 'identity-contract-replay.json')
        $receipt.stage='final-unchanged-source-binding'
        $git=(Get-Command git -ErrorAction Stop).Source
        foreach($binding in @(@('head','HEAD',$ExpectedSourceCommit),@('tree','HEAD^{tree}',$receipt.source.sourceTree))){
            $check=Invoke-LoggedCommand $git @('rev-parse',$binding[1]) $repo (Join-Path $evidence ('final-source-'+$binding[0])) -TimeoutMinutes 1
            if(([IO.File]::ReadAllText($check.stdout)).Trim() -cne $binding[2]){throw 'Diagnostic source changed during control.'}
        }
        Invoke-LoggedCommand $git @('diff','--quiet','HEAD','--') $repo (Join-Path $evidence 'final-source-clean') -TimeoutMinutes 1|Out-Null
        $receipt.stage='verify-owned-command-lifetimes'
        $owned=@(Get-ChildItem -LiteralPath $evidence -Filter '*.command.json' -File -Recurse)
        if($owned.Count -lt 18){throw 'Owned command census incomplete.'}
        foreach($file in $owned){Assert-IdentityCommandReceipt (Get-Content -LiteralPath $file.FullName -Raw|ConvertFrom-Json)}
        $receipt.commandCount=$owned.Count
        Assert-NativeBuildTimeRemaining
        $receipt.caseCount=$caseRoots.Count;$receipt.status='finite-authentic-identity-control-passed';$receipt.completed=$true;$receipt.stage='complete'
    }catch{$receipt.error=$_.Exception.ToString();throw}
    finally{
        $receipt.finishedUtc=[DateTime]::UtcNow.ToString('o');$script:NativeEngineBuildBudget=$previous
        Write-BuildJson (Join-Path $evidence 'identity-control-receipt.json') $receipt
    }
}

if($MyInvocation.InvocationName -ne '.'){
    Invoke-NativeIdentityControl $WorkDirectory $OutputDirectory $DeadlineUtc $ExpectedSourceCommit $ExpectedSourceTree
}
