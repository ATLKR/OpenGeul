# Own diagnostic boundary; shared production command helper remains unchanged.
function Invoke-PythonControlBuildCommand([string]$FilePath,[string[]]$Arguments,[string]$WorkingDirectory,[string]$LogPrefix,[ValidateRange(0.000001,350)][double]$TimeoutMinutes=350,[hashtable]$ChildEnvironment=@{}) {
    $receipt=[ordered]@{file=$FilePath;arguments=@($Arguments);workingDirectory=$WorkingDirectory;startedUtc=[DateTime]::UtcNow.ToString('o');passed=$false;exitCode=$null;
        timeoutMinutes=$TimeoutMinutes;pipeDrainComplete=$false;forcedTermination=$false;directProcessDeathVerified=$false;processTreeCleanup='not-requested';cleanupErrors=@()}
    $stdout=$LogPrefix+'.stdout.log';$stderr=$LogPrefix+'.stderr.log'
    foreach($path in @($stdout,$stderr,$LogPrefix+'.command.json')) {if(Test-Path -LiteralPath $path){throw 'Command evidence already exists.'}}
    $outStream=$null;$errStream=$null;$process=$null;$started=$false;$failure=$null
    $cancel=[Threading.CancellationTokenSource]::new();$watch=[Diagnostics.Stopwatch]::StartNew()
    Write-Host ('Starting: '+[IO.Path]::GetFileName($FilePath)+' '+($Arguments -join ' '))
    try {
        $timeoutMilliseconds=Get-NativeBuildRemaining ([int][Math]::Floor($TimeoutMinutes*60000))
        $receipt.effectiveTimeoutMilliseconds=$timeoutMilliseconds
        $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$FilePath;$info.WorkingDirectory=$WorkingDirectory
        $info.UseShellExecute=$false;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
        foreach($argument in $Arguments) {$info.ArgumentList.Add($argument)}
        # Clear the child dictionary without enumerating inherited variable values.
        $info.Environment.Clear()
        foreach($name in $ChildEnvironment.Keys){$info.Environment[$name]=$ChildEnvironment[$name]}
        $receipt.childEnvironmentNames=@($ChildEnvironment.Keys|Sort-Object)
        if($ChildEnvironment.ContainsKey('PATH')) {
            $receipt.pathSha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($ChildEnvironment.PATH))).ToLowerInvariant()
        }
        $process=[Diagnostics.Process]::new();$process.StartInfo=$info
        $outStream=[IO.File]::Open($stdout,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
        $errStream=[IO.File]::Open($stderr,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
        if(-not $process.Start()) {throw 'Command process did not start.'}
        $started=$true;$receipt.pid=$process.Id
        $creation=Get-CommandCreationIdentity $process
        foreach($key in $creation.Keys) {$receipt[$key]=$creation[$key]}
        $outTask=$process.StandardOutput.BaseStream.CopyToAsync($outStream,81920,$cancel.Token)
        $errTask=$process.StandardError.BaseStream.CopyToAsync($errStream,81920,$cancel.Token)
        while($true) {
            $remaining=[int][Math]::Floor($timeoutMilliseconds-$watch.Elapsed.TotalMilliseconds)
            if($remaining -le 0) {throw 'Owned command exceeded its original time budget.'}
            if($process.WaitForExit([Math]::Min(15000,$remaining))) {break}
            Write-Host ("Still running {0}: {1}s; stdout={2} bytes stderr={3} bytes" -f [IO.Path]::GetFileName($FilePath),[int]$watch.Elapsed.TotalSeconds,$outStream.Length,$errStream.Length)
        }
        $receipt.exitCode=$process.ExitCode;$receipt.directProcessDeathVerified=$true
        # Descendants can retain inherited output handles after the direct
        # command exits. EOF must fit this same deadline, not a fresh budget.
        $remaining=[int][Math]::Floor($timeoutMilliseconds-$watch.Elapsed.TotalMilliseconds)
        if($remaining -le 0 -or -not [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($outTask,$errTask),$remaining)) {
            throw 'Owned command output pipes exceeded the original time budget.'
        }
        $outTask.GetAwaiter().GetResult()|Out-Null;$errTask.GetAwaiter().GetResult()|Out-Null
        $receipt.pipeDrainComplete=$true
        if($process.ExitCode -ne 0) {
            $outStream.Flush();$errStream.Flush()
            try {Write-CommandFailureTail $stdout 'stdout';Write-CommandFailureTail $stderr 'stderr'}
            catch {Write-Host ('Owned failure tail unavailable: '+$_.Exception.Message)}
            throw "Command failed with exit $($process.ExitCode); inspect $stdout and $stderr"
        }
        $receipt.passed=$true
    } catch {$failure=$_;$receipt.error=$_.Exception.Message}
    finally {
        if($started) {
            try {
                if(-not $process.HasExited) {
                    $receipt.forcedTermination=$true;$receipt.processTreeCleanup='entire-process-tree-kill-requested'
                    $process.Kill($true)
                    if(-not $process.WaitForExit(5000)) {throw 'Owned direct command death remains unproved after termination.'}
                }
                $receipt.directProcessDeathVerified=$process.HasExited
                if($process.HasExited) {$receipt.exitCode=$process.ExitCode}
            } catch {$receipt.cleanupErrors+=('process: '+$_.Exception.Message)}
            if(-not $receipt.pipeDrainComplete) {
                # Kill(true) cannot establish descendant ownership once the
                # root exited. Record the limitation and cancel our own reads.
                if($receipt.directProcessDeathVerified -and -not $receipt.forcedTermination) {$receipt.processTreeCleanup='unproved-after-direct-process-exit'}
                $cancel.Cancel()
                foreach($reader in @($process.StandardOutput,$process.StandardError)) {
                    try {$reader.Dispose()} catch {$receipt.cleanupErrors+=('pipe: '+$_.Exception.Message)}
                }
            }
        }
        foreach($resource in @($outStream,$errStream,$process,$cancel)) {
            if($resource) {try {$resource.Dispose()} catch {$receipt.cleanupErrors+=('dispose: '+$_.Exception.Message)}}
        }
        if($receipt.cleanupErrors.Count -gt 0) {$receipt.passed=$false;if(-not $receipt.error){$receipt.error='Owned command resource cleanup failed.'}}
        $receipt.elapsedSeconds=[Math]::Round($watch.Elapsed.TotalSeconds,3)
        $receipt.finishedUtc=[DateTime]::UtcNow.ToString('o')
        Write-BuildJson ($LogPrefix+'.command.json') $receipt
    }
    if($failure) {throw $failure}
    if(-not $receipt.passed) {throw $receipt.error}
    return [pscustomobject]@{stdout=$stdout;stderr=$stderr;receipt=$LogPrefix+'.command.json';exitCode=$receipt.exitCode}
}
