param([Parameter(Mandatory)][string]$ExecutablePath,
      [Parameter(Mandatory)][string]$OutputDirectory,
      [ValidatePattern('^[a-zA-Z0-9-]{1,32}$')][string]$Label='installed')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Use the observed SDK interop signatures, never a guessed COM interface/vtable or Tests.dll.
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$outputPath = Join-Path $OutputDirectory ('wack-binaryinfo-' + $Label + '.json')
if (Test-Path -LiteralPath $outputPath) { throw 'Refusing to reuse a BinaryInfo observation.' }
$kit = [IO.Path]::GetFullPath((Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/App Certification Kit'))
$expectedInterop = '61e0ea014840c16e827319dc8272a488dd4d8bdbdbc4ce1ccd30062cda8a6e3d'
$expectedEngine = 'b991f5c98d16d0e7b12bf0a19dd55d361c79967bd280014748e2ab9d39afcac3'
$expectedEditors = @('94b6290903c11a333546c8faff45808febf07021378e66d76b5ff1d89e4cb9f3',
                     'e282955c8e460cb66270949e51e492162bce7cebb75ae62562043c05885f8490')
$stages = [Collections.Generic.List[object]]::new()
$registrations = [Collections.Generic.List[object]]::new()
$result = [ordered]@{scope='diagnostic SDK BinaryInfo COM calls on a hash-verified editor; no SDK test DLL execution or gate exemption';
                     label=$Label;complete=$false;host=@{is64BitProcess=[Environment]::Is64BitProcess;
                     pointerBytes=[IntPtr]::Size;sessionId=(Get-Process -Id $PID).SessionId;
                     powershellVersion=[string]$PSVersionTable.PSVersion;clrVersion=[string][Environment]::Version;
                     registryView=if([Environment]::Is64BitProcess){'Registry64'}else{'Registry32'}};
                     editor=$null;interop=$null;coclass=$null;registrations=$registrations;stages=$stages}
$comObject=$null; $loaded=$false; $unloadAttempted=$false; $before=$null; $stage='editor-identity'

function FailureRecord([Exception]$ErrorObject, [string]$Name) {
    $base = $ErrorObject.GetBaseException()
    $bits = [BitConverter]::ToUInt32([BitConverter]::GetBytes([int]$base.HResult), 0)
    $message = [string]$base.Message
    $truncated = $message.Length -gt 4096
    if ($truncated) { $message = $message.Substring(0, 4096) }
    return @{stage=$Name;success=$false;exceptionType=$base.GetType().FullName;
             hresult=('0x{0:X8}' -f $bits);message=$message;messageTruncated=$truncated}
}

function FileIdentity([string]$Path) {
    $item = Get-Item -LiteralPath $Path
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -gt 256MB) {
        throw 'Identity input must be a bounded regular file.'
    }
    return @{name=$item.Name;bytes=$item.Length;sha256=(Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash;
             fileVersion=([string]$item.VersionInfo.FileVersion);machine=(PeMachine $item.FullName)}
}

function PeMachine([string]$Path) {
    $stream=[IO.File]::OpenRead($Path)
    $reader=[IO.BinaryReader]::new($stream)
    try {
        if ($reader.ReadUInt16() -ne 0x5A4D -or $stream.Length -lt 64) { throw 'Invalid PE DOS header.' }
        $stream.Position=0x3C; $offset=$reader.ReadUInt32()
        if ($offset -gt $stream.Length - 6) { throw 'Invalid PE offset.' }
        $stream.Position=$offset
        if ($reader.ReadUInt32() -ne 0x4550) { throw 'Invalid PE signature.' }
        return ('0x{0:X4}' -f $reader.ReadUInt16())
    } finally { $reader.Dispose() }
}

function VerifyKitFile([string]$Path, [string]$ExpectedHash) {
    $full=[IO.Path]::GetFullPath($Path)
    $prefix=$kit.TrimEnd([char[]]'\/') + [IO.Path]::DirectorySeparatorChar
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'COM file is outside the installed kit.' }
    $cursor=Get-Item -LiteralPath $full
    while ($null -ne $cursor) {
        if ($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse points are forbidden in the COM file path.' }
        if ($cursor.FullName.Equals($kit, [StringComparison]::OrdinalIgnoreCase)) { break }
        $cursor=Get-Item -LiteralPath (Split-Path -Parent $cursor.FullName)
    }
    if ((Get-Item -LiteralPath $full).Length -gt 16MB) { throw 'Installed COM file exceeds the hash input budget.' }
    $identity=FileIdentity $full
    if ($identity.bytes -gt 16MB -or $identity.sha256 -ine $ExpectedHash) { throw 'Installed COM file differs from the Run43 hash.' }
    $signature=Get-AuthenticodeSignature -LiteralPath $full
    $identity.signatureStatus=[string]$signature.Status
    $identity.signerSubject=if($signature.SignerCertificate){$signature.SignerCertificate.Subject}else{$null}
    $identity.signerThumbprint=if($signature.SignerCertificate){$signature.SignerCertificate.Thumbprint}else{$null}
    if ($signature.Status -ne [Management.Automation.SignatureStatus]::Valid -or
        -not $signature.SignerCertificate -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation(?:,|$)') {
        throw 'Installed COM file does not have a valid Microsoft Authenticode signature.'
    }
    $identity.path=$full
    return $identity
}

try {
    if ($env:GITHUB_ACTIONS -ne 'true') { throw 'BinaryInfo diagnostics are restricted to disposable GitHub Actions runners.' }
    $fullEditor=[IO.Path]::GetFullPath($ExecutablePath)
    $editor=FileIdentity $fullEditor
    if ($editor.sha256.ToLowerInvariant() -notin $expectedEditors) { throw 'Editor differs from the two exact source/diagnostic hashes.' }
    $before=$editor.sha256; $result.editor=$editor
    $stages.Add(@{stage=$stage;success=$true})
    $stage='interop-identity'
    $interopPath=Join-Path $kit 'microsoft.windows.softwarelogo.binaryinfo.interop.dll'
    $result.interop=VerifyKitFile $interopPath $expectedInterop
    $stages.Add(@{stage=$stage;success=$true})
    $stage='interop-metadata'
    $assembly=[Reflection.Assembly]::LoadFrom($interopPath)
    $type=$assembly.GetType('Microsoft.Windows.SoftwareLogo.BinaryInfo.Interop.BinaryInfoClass', $true)
    if (-not $type.IsImport -or -not $type.IsClass -or $type.GUID -eq [Guid]::Empty) { throw 'Observed BinaryInfo coclass metadata is invalid.' }
    $methods=@{}
    $signatures=[Collections.Generic.List[object]]::new()
    foreach ($name in @('LoadBinary','IsPerMonitorV2DPIAwarenessSet','UnloadBinary')) {
        $matches=@($type.GetMethods() | Where-Object { $_.Name -eq $name })
        if ($matches.Count -ne 1) { throw 'Observed BinaryInfo method has an ambiguous signature.' }
        $method=$matches[0]; $parameters=@($method.GetParameters())
        $parametersMatch=if($name -eq 'LoadBinary'){
            $parameters.Count -eq 1 -and $parameters[0].ParameterType -eq [string]
        }else{$parameters.Count -eq 0}
        $returnMatch=if($name -eq 'IsPerMonitorV2DPIAwarenessSet'){$method.ReturnType -eq [bool]}else{$method.ReturnType -eq [void]}
        if (-not $parametersMatch -or -not $returnMatch) { throw 'BinaryInfo signature differs from the exact Run44 call sites.' }
        $methods[$name]=$method
        $signatures.Add(@{name=$name;returnType=$method.ReturnType.FullName;
                         parameterTypes=@($parameters | ForEach-Object { $_.ParameterType.FullName })})
    }
    $result.coclass=@{fullName=$type.FullName;guid=$type.GUID.ToString();assemblyName=$assembly.FullName;
                     isComImport=$type.IsImport;methods=$signatures}
    $stages.Add(@{stage=$stage;success=$true})
    $stage='com-registration'
    $currentView=if([Environment]::Is64BitProcess){'Registry64'}else{'Registry32'}
    $selected=$null
    foreach ($viewName in @('Registry32','Registry64')) {
        $view=[Microsoft.Win32.RegistryView]::$viewName
        $baseKey=[Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::ClassesRoot, $view)
        $key=$null; $classKey=$null
        try {
            $classKey=$baseKey.OpenSubKey(('CLSID\{' + $type.GUID.ToString() + '}'), $false)
            $key=$baseKey.OpenSubKey(('CLSID\{' + $type.GUID.ToString() + '}\InprocServer32'), $false)
            $record=@{view=$viewName;registered=($null -ne $key);selected=($viewName -eq $currentView)}
            $record.activationRedirectKeys=@()
            $record.hasAppId=$false
            if ($classKey) {
                $record.activationRedirectKeys=@($classKey.GetSubKeyNames() | Where-Object { $_ -in @('TreatAs','AutoTreatAs','LocalServer32') })
                $record.hasAppId=-not [string]::IsNullOrWhiteSpace([string]$classKey.GetValue('AppID'))
            }
            if ($key) {
                $raw=[string]$key.GetValue('', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
                $enginePath=[Environment]::ExpandEnvironmentVariables($raw).Trim().Trim([char]'"')
                $record.threadingModel=[string]$key.GetValue('ThreadingModel')
                try {
                    if ($record.activationRedirectKeys.Count -gt 0) { throw 'COM registration has activation redirect keys.' }
                    if ($record.hasAppId) { throw 'COM registration has an AppID activation mapping.' }
                    if (-not [IO.Path]::IsPathRooted($enginePath)) { throw 'COM engine path is not absolute.' }
                    $record.engine=VerifyKitFile $enginePath $expectedEngine
                    $record.verified=$true
                    if ($viewName -eq $currentView) { $selected=$record }
                } catch { $record.verified=$false; $record.failure=FailureRecord $_.Exception 'registration-engine-verification' }
            }
            $registrations.Add($record)
        } finally { if($key){$key.Dispose()}; if($classKey){$classKey.Dispose()}; $baseKey.Dispose() }
    }
    if (-not $selected) { throw 'Current process registry view has no verified SDK BinaryInfo engine.' }
    $expectedMachine=if([Environment]::Is64BitProcess){'0x8664'}else{'0x014C'}
    if ($selected.engine.machine -ne $expectedMachine) { throw 'Registered engine machine differs from this probe process.' }
    $stages.Add(@{stage=$stage;success=$true;engineMachine=$selected.engine.machine})
    $stage='BinaryInfoClass-construction'
    $comObject=[Activator]::CreateInstance($type)
    if (-not [Runtime.InteropServices.Marshal]::IsComObject($comObject)) { throw 'Observed coclass did not produce a COM object.' }
    $stages.Add(@{stage=$stage;success=$true})
    $stage='LoadBinary'
    $null=$methods.LoadBinary.Invoke($comObject, [object[]]@($fullEditor))
    $loaded=$true; $stages.Add(@{stage=$stage;success=$true})
    $stage='IsPerMonitorV2DPIAwarenessSet'
    $value=$methods.IsPerMonitorV2DPIAwarenessSet.Invoke($comObject, [object[]]@())
    $stages.Add(@{stage=$stage;success=$true;value=[bool]$value})
    $stage='UnloadBinary'; $unloadAttempted=$true
    $null=$methods.UnloadBinary.Invoke($comObject, [object[]]@())
    $loaded=$false; $stages.Add(@{stage=$stage;success=$true})
    $result.complete=$true
} catch {
    $stages.Add((FailureRecord $_.Exception $stage))
} finally {
    if ($comObject) {
        if ($loaded -and -not $unloadAttempted) {
            try {
                $null=$methods.UnloadBinary.Invoke($comObject, [object[]]@())
                $stages.Add(@{stage='UnloadBinary-cleanup';success=$true})
            } catch { $result.complete=$false; $stages.Add((FailureRecord $_.Exception 'UnloadBinary-cleanup')) }
        }
        try {
            $remaining=[Runtime.InteropServices.Marshal]::FinalReleaseComObject($comObject)
            $stages.Add(@{stage='FinalReleaseComObject';success=$true;remainingReferences=$remaining})
        } catch { $result.complete=$false; $stages.Add((FailureRecord $_.Exception 'FinalReleaseComObject')) }
    }
    if ($before) {
        try {
            $after=(Get-FileHash -LiteralPath $fullEditor -Algorithm SHA256).Hash
            $result.editor.sha256After=$after; $result.editor.unchanged=($after -eq $before)
            if ($after -ne $before) { $result.complete=$false }
        } catch { $result.complete=$false; $stages.Add((FailureRecord $_.Exception 'editor-unchanged-check')) }
    }
    $json=$result | ConvertTo-Json -Depth 12 -Compress
    if ([Text.Encoding]::UTF8.GetByteCount($json) -gt 64KB) {
        foreach ($entry in $stages) { if($entry.ContainsKey('message')){$entry.message=$entry.message.Substring(0,[Math]::Min(256,$entry.message.Length));$entry.messageTruncated=$true} }
        $result.complete=$false; $result.outputTruncated=$true
        $json=$result | ConvertTo-Json -Depth 12 -Compress
        if ([Text.Encoding]::UTF8.GetByteCount($json) -gt 64KB) { throw 'BinaryInfo observation exceeds its JSON budget.' }
    }
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($outputPath), $json, [Text.UTF8Encoding]::new($false))
}
# A diagnosed SDK exception is evidence. The caller must still execute the normal WACK gate.
Write-Output ('BinaryInfo diagnostic written: ' + $Label + '; complete=' + $result.complete)
