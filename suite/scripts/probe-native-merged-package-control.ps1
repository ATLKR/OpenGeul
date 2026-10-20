param([string]$WorkDirectory='.work/native29-merged-work',[string]$OutputDirectory='.work/native29-merged-evidence',[string]$DeadlineUtc='')
$ErrorActionPreference='Stop'
$driver=Join-Path $PSScriptRoot 'build-native-engine.ps1'
$driverSha='e243851c5be121a057aa9b126482106a8e0d8dd6fb7d5cc9f2e8fc9b7d10ec69'
if((Get-FileHash -LiteralPath $driver -Algorithm SHA256).Hash.ToLowerInvariant() -cne $driverSha){throw 'Reviewed original driver changed.'}
. $driver -WorkDirectory $WorkDirectory -OutputDirectory $OutputDirectory -DeadlineUtc $DeadlineUtc

function Assert-ControlCommandReceipt($Receipt){
    if($Receipt.passed -ne $true -or $Receipt.exitCode -ne 0 -or $Receipt.pid -le 0 -or
       $Receipt.creationUtcTicks -le 0 -or $Receipt.pipeDrainComplete -ne $true -or
       $Receipt.forcedTermination -ne $false -or $Receipt.directProcessDeathVerified -ne $true -or
       $Receipt.processTreeCleanup -cne 'not-requested' -or @($Receipt.cleanupErrors).Count){throw 'Control requires normal owned drained unforced zero-exit completion.'}
}

function Observe-ControlPeRejection([string]$Path){
    try{Get-ProductPeIdentity $Path|Out-Null}catch{
        if($_.Exception.Message -cne ('Invalid PE: '+$Path)){throw}
        return [ordered]@{path=$Path;rejected=$true;error=$_.Exception.Message;predicate='Unchanged Get-ProductPeIdentity from pinned production driver'}
    }
    throw 'Control unexpectedly accepted a non-PE fixture.'
}

function Get-ControlFile([string]$Path,[int]$MaximumBytes=33554432,[switch]$RetainHex){
    Assert-UnlinkedPath $Path;$item=Get-Item -LiteralPath $Path -Force
    if($item.PSIsContainer -or $item.Length -gt $MaximumBytes){throw 'Controlled file exceeds finite bounds.'}
    $raw=[IO.File]::ReadAllBytes($Path)
    $record=[ordered]@{path=$item.FullName;bytes=$raw.Length;sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($raw)).ToLowerInvariant();
        attributes=[string]$item.Attributes;reparsePoint=(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)}
    if($RetainHex){$record.hex=[Convert]::ToHexString($raw).ToLowerInvariant()}
    if($raw.Length -ge 64 -and $raw[0] -eq 77 -and $raw[1] -eq 90){
        $offset=[BitConverter]::ToUInt32($raw,60)
        if($offset -ge 64 -and $offset+6 -le $raw.Length -and [BitConverter]::ToUInt32($raw,[int]$offset) -eq 17744){$record.observedPeMachine=[int][BitConverter]::ToUInt16($raw,[int]$offset+4)}
    }
    return $record
}

function Invoke-NativeMergedPackageControl([string]$WorkDirectory,[string]$OutputDirectory,[string]$DeadlineUtc){
    $paths=New-BuildDirectories $WorkDirectory $OutputDirectory;$work=$paths.work;$evidence=$paths.output
    $repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'));$data=Join-Path $repo 'suite/diagnostics/native-merged-package'
    $previous=$script:NativeEngineBuildBudget
    $receipt=[ordered]@{schemaVersion=1;kind='native29-authentic-merged-placeholder-and-install-selection-control';diagnosticOnly=$true;
        status='inconclusive';completed=$false;native28DllCauseProven=$false;native28DllBytesAvailable=$false;
        fullEngineQualified=$false;baseQualified=$false;runtimeExecuted=$false;payloadExecuted=$false;stage='budget';startedUtc=[DateTime]::UtcNow.ToString('o')}
    try{
        if(-not $DeadlineUtc -or -not $env:OPENGEUL_MERGED_CONTROL_BUDGET_RECEIPT){throw 'Original first-step deadline and budget receipt are mandatory.'}
        $script:NativeEngineBuildBudget=New-NativeBuildBudget $DeadlineUtc 15;$receipt.budget=$script:NativeEngineBuildBudget.record
        Copy-Item -LiteralPath $env:OPENGEUL_MERGED_CONTROL_BUDGET_RECEIPT -Destination (Join-Path $evidence 'job-budget.json') -ErrorAction Stop
        $receipt.host=Get-NativeBuildHost
        $controller=Get-Process -Id $PID;$receipt.controller=Get-ProductPeIdentity $controller.Path
        if($receipt.controller.role -cne 'nativeArm64'){throw 'Actual controller PE must also be native ARM64.'}
        $receipt.controllerCreation=Get-CommandCreationIdentity $controller
        $receipt.stage='source-binding'
        $receipt.source=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'probe-native-merged-package-control.ps1') (Join-Path $data 'source.json') $evidence
        $receipt.productionDriverSha256=$driverSha
        foreach($name in @('Invoke-LoggedCommand','Get-ProductPeIdentity')){
            [IO.File]::WriteAllText((Join-Path $evidence ($name+'.original-definition.ps1')),(Get-Command $name).Definition)
        }
        foreach($file in Get-ChildItem -LiteralPath $data -File){Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $evidence ('input-'+$file.Name)) -ErrorAction Stop}
        $pythonTool=(Get-Command python -ErrorAction Stop).Source;$receipt.pythonHelper=Get-ControlFile $pythonTool
        $receipt.helperArchitecturePolicy='Python, Cygwin, setup and GNU make are build helpers and may be foreign architecture. Product code is never executed or admitted.'
        Invoke-LoggedCommand $pythonTool @('--version') $work (Join-Path $evidence 'python-version') -TimeoutMinutes 1|Out-Null
        $receipt.stage='installed-runtime-stage-unit-tests'
        $receipt.productionStageInputs=@()
        foreach($relative in @('suite/engine-build/stage_installed_runtime.py','suite/tests/test_installed_runtime_stage.py')){
            $path=Join-Path $repo $relative;$receipt.productionStageInputs+=,(Get-ControlFile $path)
            Copy-Item -LiteralPath $path -Destination (Join-Path $evidence ('input-'+[IO.Path]::GetFileName($path))) -ErrorAction Stop
        }
        $stageUnits=Invoke-LoggedCommand $pythonTool @('-m','unittest','suite.tests.test_installed_runtime_stage','-v') $repo (Join-Path $evidence 'installed-runtime-stage-unit-tests') -TimeoutMinutes 2
        $unitText=[IO.File]::ReadAllText($stageUnits.stderr)
        $unitCases=@([IO.File]::ReadAllLines($stageUnits.stderr)|Where-Object {$_ -cmatch '^test_.* \.\.\. ok$'})
        if($unitCases.Count -ne 14 -or $unitText -cnotmatch '(?m)^Ran 14 tests in [0-9.]+s\r?$' -or $unitText -cnotmatch '(?m)^OK\r?$'){
            throw 'Installed-runtime-stage fixtures require exactly14 ordinary passed cases without skips.'
        }
        $receipt.installedRuntimeStageUnitTests=[ordered]@{module='suite.tests.test_installed_runtime_stage';commandReceipt=$stageUnits.receipt;
            passedCaseCount=$unitCases.Count;skippedCaseCount=0;caseLines=$unitCases;fixturesOnly=$true;runtimeExecuted=$false}
        $receipt.stage='minimal-cygwin'
        $setup=Join-Path $work 'setup-x86_64.exe'
        $receipt.cygwinSetup=Get-AuthenticatedDownload 'https://cygwin.com/setup-x86_64.exe' $setup 1574328 SHA512 '6acea47c59781c9e7f544a18d53935d59df6e44d5d52ac95ee165671b8e388820455eebf30ccc7d254b00c3d0eb694269a0f8dc84b17944c1f355dac9c5aafcc' (Join-Path $evidence 'cygwin-download.json')
        $cygwin=Join-Path $work 'cygwin'
        Invoke-LoggedCommand $setup @('--quiet-mode','--no-admin','--no-shortcuts','--no-startmenu','--no-desktop','--root',$cygwin,'--local-package-dir',(Join-Path $work 'cygwin-cache'),'--site','https://mirrors.kernel.org/sourceware/cygwin/','--packages','bash,coreutils,make') $work (Join-Path $evidence 'cygwin-setup') -TimeoutMinutes 8|Out-Null
        $bash=Join-Path $cygwin 'bin/bash.exe';$cygpath=Join-Path $cygwin 'bin/cygpath.exe'
        $receipt.cygwinHelpers=@(Get-ControlFile $bash;Get-ControlFile (Join-Path $cygwin 'bin/make.exe');Get-ControlFile $cygpath)
        $commands=Join-Path $work 'commands';New-Item -ItemType Directory $commands|Out-Null
        $receipt.cygwinIdentity=Get-CygwinIdentity $bash $cygpath $commands $work $evidence
        $converted=@{}
        foreach($entry in @(@('data',$data),@('evidence',$evidence))){
            $result=Invoke-LoggedCommand $cygpath @('-u',$entry[1]) $work (Join-Path $evidence ('cygpath-'+$entry[0])) -TimeoutMinutes 1
            $converted[$entry[0]]=(Get-Content -LiteralPath $result.stdout -Raw).Trim()
        }
        $receipt.stage='authentic-gnu-make-replay'
        Invoke-LoggedCommand $pythonTool @((Join-Path $data 'render_control.py'),'--data',$data,'--output',$evidence,'--unix-data',$converted.data,'--unix-output',$converted.evidence) $repo (Join-Path $evidence 'render-authentic-control') -TimeoutMinutes 1|Out-Null
        $script=Join-Path $commands 'merged-control.sh'
        Write-BashScript $script @('set -euo pipefail',"cd $(Quote-Bash $converted.evidence)",'/usr/bin/make --version',"/usr/bin/make --no-builtin-rules --no-builtin-variables --no-print-directory -f $(Quote-Bash ($converted.evidence+'/control.mk'))","/usr/bin/stat -c 'type=%F bytes=%s mode=%a' instdir/program/avmedialo.dll")
        Invoke-CygwinScript $bash $cygpath $script $work (Join-Path $evidence 'authentic-merged-make') -NativeLinks|Out-Null
        Copy-Item -LiteralPath $script -Destination (Join-Path $evidence 'merged-control.sh') -ErrorAction Stop
        $marker=Join-Path $evidence 'instdir/program/avmedialo.dll'
        $receipt.marker=Get-ControlFile $marker -MaximumBytes 64 -RetainHex
        $expected=[Text.Encoding]::ASCII.GetBytes("invalid - merged lib`n")
        if($receipt.marker.bytes -ne 21 -or $receipt.marker.hex -cne [Convert]::ToHexString($expected).ToLowerInvariant()){throw 'Authentic merged macro produced unexpected bytes.'}
        $selection=[IO.File]::ReadAllLines((Join-Path $evidence 'installation-selection.txt'))
        if($selection.Count -ne 2 -or $selection[0] -cne 'avmedia merged standalone' -or $selection[1] -cne 'merged standalone'){throw 'Authentic upstream install selection differs.'}
        $receipt.installSelection=[ordered]@{registered=@('avmedia','merged','standalone');selected=@('merged','standalone');avmediaExcluded=$true;authority='Original Helper.mk register_libraries_for_install and full pre_MergedLibsList.mk'}
        $receipt.peRejections=@(Observe-ControlPeRejection $marker)
        foreach($item in @(@('changed.dll',"invalid - merged lib!`n"),@('empty.dll',''),@('same-marker.txt',"invalid - merged lib`n"))){
            $path=Join-Path $evidence $item[0];[IO.File]::WriteAllBytes($path,[Text.Encoding]::ASCII.GetBytes($item[1]))
            $receipt.peRejections+=,(Observe-ControlPeRejection $path)
        }
        $receipt.stage='raw-instdir-zip-boundary'
        $archive=Join-Path $evidence 'fixture-developer-instdir.zip'
        Write-NativeEngineArchive (Join-Path $evidence 'instdir') $archive $evidence
        $zip=[IO.Compression.ZipFile]::OpenRead($archive)
        try{
            if($zip.Entries.Count -ne 1 -or $zip.Entries[0].FullName -cne 'program/avmedialo.dll'){throw 'Controlled raw instdir ZIP member identity differs.'}
            $stream=$zip.Entries[0].Open();$buffer=[IO.MemoryStream]::new()
            try{$stream.CopyTo($buffer);$raw=$buffer.ToArray()}finally{$stream.Dispose();$buffer.Dispose()}
            $hash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($raw)).ToLowerInvariant()
            if($raw.Length -ne 21 -or $hash -cne $receipt.marker.sha256){throw 'Raw instdir ZIP changed the controlled sentinel bytes.'}
            $receipt.rawInstdirZip=[ordered]@{file=(Get-ControlFile $archive);member='program/avmedialo.dll';memberBytes=$raw.Length;memberSha256=$hash;memberMatchesSentinel=$true;qualifiedEngineArchive=$false}
        }finally{$zip.Dispose()}
        $receipt.stage='verify-owned-command-lifetimes';$commands=@(Get-ChildItem -LiteralPath $evidence -Filter '*.command.json' -File)
        if($commands.Count -lt 10){throw 'Control command census is incomplete.'}
        foreach($file in $commands){Assert-ControlCommandReceipt (Get-Content -LiteralPath $file.FullName -Raw|ConvertFrom-Json)}
        $receipt.commandCount=$commands.Count
        Assert-NativeBuildTimeRemaining
        $receipt.status='controlled-upstream-marker-and-install-filter-observed';$receipt.completed=$true;$receipt.stage='complete'
    }catch{$receipt.error=$_.Exception.ToString();throw}
    finally{
        $receipt.finishedUtc=[DateTime]::UtcNow.ToString('o');$script:NativeEngineBuildBudget=$previous
        Write-BuildJson (Join-Path $evidence 'merged-package-control-receipt.json') $receipt
    }
}

if($MyInvocation.InvocationName -ne '.'){
    Invoke-NativeMergedPackageControl $WorkDirectory $OutputDirectory $DeadlineUtc
}
