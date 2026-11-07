function Install-WriterServerObserverFocusBaseline([string]$SourceRoot,[string]$Repo,[string]$Python,[string]$EvidenceDirectory,$Pin,[hashtable]$ChildEnvironment=$null) {
    $plan=Get-Content -LiteralPath (Join-Path $Repo 'suite/engine-build/source-build.json') -Raw|ConvertFrom-Json
    $focus=$plan.winAccFocusOrder
    if($Pin.coreCommit -cne 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1' -or $focus.coreCommit -cne $Pin.coreCommit -or
       $focus.path -cne 'winaccessibility/source/service/AccObjectWinManager.cxx' -or @($focus.sources).Count -ne 3) {throw 'Writer focus baseline input differs.'}
    $proofDirectory=Join-Path $EvidenceDirectory 'writer-focus-baseline'
    New-Item -ItemType Directory -Path $proofDirectory -ErrorAction Stop|Out-Null
    if($null -eq $ChildEnvironment) {
        $ChildEnvironment=@{PYTHONUTF8='1';PYTHONDONTWRITEBYTECODE='1'}
        foreach($key in @('PATH','SystemRoot','WINDIR','TEMP','TMP')) {
            $value=[Environment]::GetEnvironmentVariable($key)
            if($null -ne $value) {$ChildEnvironment[$key]=$value}
        }
    }
    $result=Invoke-LoggedCommand $Python @((Join-Path $Repo 'suite/engine-build/apply_winacc_focus_order.py'),'--libreoffice-source',$SourceRoot,'--evidence-directory',$proofDirectory,'--core-commit',$Pin.coreCommit) $Repo (Join-Path $EvidenceDirectory 'writer-focus-baseline-source-hooks') -ChildEnvironment $ChildEnvironment
    $proof=Get-Content -LiteralPath $result.stdout -Raw|ConvertFrom-Json
    if($proof.passed -isnot [bool] -or -not $proof.passed -or $proof.schemaVersion -ne 1 -or $proof.kind -cne 'winacc-focus-order-source-patch' -or
       $proof.coreCommit -cne $Pin.coreCommit -or $proof.path -cne $focus.path -or
       $proof.beforeSha256 -cne $focus.sha256 -or $proof.afterSha256 -cne $focus.afterSha256 -or $proof.patchSha256 -cne $focus.patch.sha256 -or
       $proof.nativeBuildVerified -isnot [bool] -or $proof.nativeBuildVerified -or $proof.guiVerified -isnot [bool] -or $proof.guiVerified -or
       $proof.currentCiRootCauseConfirmed -isnot [bool] -or $proof.currentCiRootCauseConfirmed -or @($proof.sourceFiles).Count -ne 3) {throw 'Writer focus baseline receipt differs.'}
    $seen=@{}
    foreach($expected in @($focus.sources)) {
        $rows=@($proof.sourceFiles|Where-Object {$_.path -ceq $expected.path})
        if($rows.Count -ne 1 -or $seen.ContainsKey($expected.path)) {throw 'Writer focus baseline source set differs.'}
        $seen[$expected.path]=$true;$row=$rows[0]
        $after=if($expected.path -ceq $focus.path){$focus.afterSha256}else{$expected.sha256}
        $afterBytes=if($expected.path -ceq $focus.path){$focus.afterBytes}else{$expected.size}
        if($row.beforeBytes -ne $expected.size -or $row.afterBytes -ne $afterBytes -or $row.beforeSha256 -cne $expected.sha256 -or $row.afterSha256 -cne $after) {throw 'Writer focus baseline source receipt differs.'}
        $file=Join-Path $SourceRoot $expected.path;Assert-UnlinkedPath $file
        if((Get-Item -LiteralPath $file).Length -ne $afterBytes -or (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -cne $after) {throw 'Writer focus baseline effective source differs.'}
    }
    return $proof
}
