# Bounded diagnostic: execute the pinned production SDK block on Source 81's
# already-signed bytes. Original source proof and the real diagnostic CI differ.
param([Parameter(Mandatory)][string]$PackageDirectory,
      [Parameter(Mandatory)][string]$NativeDirectory,
      [Parameter(Mandatory)][string]$OutputDirectory)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$true

function Get-SameSignedEnvironmentDigest {
 $variables=[Environment]::GetEnvironmentVariables('Process')
 $names=[string[]]@($variables.Keys);[Array]::Sort($names,[StringComparer]::Ordinal)
 $all=[ordered]@{};$github=[ordered]@{}
 foreach ($name in $names) {
  $all[$name]=[string]$variables[$name]
  if ($name.StartsWith('GITHUB_',[StringComparison]::Ordinal)) { $github[$name]=[string]$variables[$name] }
 }
 # Hash in memory; environment values, including credentials, are never saved.
 $encoding=[Text.UTF8Encoding]::new($false)
 return @{sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($encoding.GetBytes(($all | ConvertTo-Json -Compress)))).ToLowerInvariant();
  githubSha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($encoding.GetBytes(($github | ConvertTo-Json -Compress)))).ToLowerInvariant()}
}

function Get-SameSignedProductionAst {
 param([Parameter(Mandatory)][string]$Path)
 $expected='327ee797d69c11eb1cf1c87116897061e9299754afa73586155662413a5b9f74'
 $raw=[IO.File]::ReadAllBytes($Path)
 $hash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($raw)).ToLowerInvariant()
 if ($hash -cne $expected) { throw 'Pinned production importer bytes differ.' }
 $encoding=[Text.UTF8Encoding]::new($false,$true);$source=$encoding.GetString($raw)
 $tokens=$null;$errors=$null
 $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
 if ($errors.Count) { throw 'Production importer has parse errors.' }
 $records=@()
 foreach ($name in @('Assert-OpenGeulSelectedUnsignedPackage','ConvertTo-OpenGeulUtcSecond','Get-OpenGeulNativePublicCertificate')) {
  $matches=@($ast.EndBlock.Statements | Where-Object { $_ -is [Management.Automation.Language.FunctionDefinitionAst] -and $_.Name -ceq $name })
  if ($matches.Count -ne 1) { throw 'Exact original top-level function required.' }
  $extent=$matches[0].Extent;$text=$extent.Text
  if ($text -cne $source.Substring($extent.StartOffset,$extent.EndOffset-$extent.StartOffset)) { throw 'Original function extent differs.' }
  $bytes=$encoding.GetBytes($text)
  $records+=@{name=$name;text=$text;sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant();
   bytes=$bytes.Length;startOffset=$extent.StartOffset;endOffset=$extent.EndOffset;startLine=$extent.StartLineNumber;endLine=$extent.EndLineNumber}
 }
 $statements=@($ast.EndBlock.Statements);$indices=@()
 for ($i=0;$i -lt $statements.Count;$i++) {
  if ($statements[$i].Extent.Text.StartsWith('$certificate=Get-OpenGeulNativePublicCertificate ',[StringComparison]::Ordinal)) { $indices+=$i }
 }
 if ($indices.Count -ne 1) { throw 'Exact original certificate assignment required.' }
 $start=$indices[0]
 if ($start+3 -ge $statements.Count -or
     $statements[$start+1].Extent.Text -cne '$copy=Join-Path $NativeDirectory ''test-only.msix''' -or
     $statements[$start+2].Extent.Text -cne '$trusted=$null' -or
     $statements[$start+3] -isnot [Management.Automation.Language.TryStatementAst] -or
     -not $statements[$start+3].Finally) { throw 'Original contiguous SDK try/finally block required.' }
 $begin=$statements[$start].Extent.StartOffset;$end=$statements[$start+3].Extent.EndOffset
 $text=$source.Substring($begin,$end-$begin)
 $sliceTokens=$null;$sliceErrors=$null
 $sliceAst=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$sliceTokens,[ref]$sliceErrors)
 if ($sliceErrors.Count -or $sliceAst.EndBlock.Statements.Count -ne 4 -or
     $text -match '(?m)^\s*python \$helper\b') { throw 'SDK slice includes a forbidden producer/finalizer path.' }
 $bytes=$encoding.GetBytes($text)
 return @{productionSha256=$hash;productionBytes=$raw.Length;functions=$records;
  slice=@{text=$text;sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant();
   bytes=$bytes.Length;startOffset=$begin;endOffset=$end;startLine=$statements[$start].Extent.StartLineNumber;endLine=$statements[$start+3].Extent.EndLineNumber}}
}

function Write-SameSignedFreshJson {
 param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)]$Value)
 $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Value | ConvertTo-Json -Depth 15)+"`n")
 $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
 try { $stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
}

$sourceBinding=@{repository='ATLKR/OpenGeul';commit='a785d3d33537ecedef325043346dc81425001dae';runId='38265944818';runAttempt='1'}
$diagnosticBinding=@{repository=$env:GITHUB_REPOSITORY;commit=$env:GITHUB_SHA;runId=$env:GITHUB_RUN_ID;runAttempt=$env:GITHUB_RUN_ATTEMPT}
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
    $diagnosticBinding.repository -cne 'ATLKR/OpenGeul' -or $diagnosticBinding.commit -cnotmatch '^[0-9a-f]{40}$' -or
    $diagnosticBinding.runId -cnotmatch '^[1-9][0-9]{0,19}$' -or $diagnosticBinding.runAttempt -cne '1' -or
    $diagnosticBinding.commit -ceq $sourceBinding.commit -or $diagnosticBinding.runId -ceq $sourceBinding.runId -or
    $env:GITHUB_JOB -cne 'msix-install-arm64' -or $env:GITHUB_EVENT_NAME -cne 'workflow_dispatch' -or
    $env:GITHUB_REF -cne 'refs/heads/diagnostic/same-signed-arm-sdk-source81') {
 throw 'Real, separate public hosted diagnostic CI binding required.'
}
$PackageDirectory=(Resolve-Path -LiteralPath $PackageDirectory).Path
$NativeDirectory=(Resolve-Path -LiteralPath $NativeDirectory).Path
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
foreach ($name in @('install.json','same-signed-sdk-diagnostic.json','importer-ast-slice.json','importer-sdk-slice.ps1.txt',
 'host-architecture.json','sdk-tool-process.json','sdk-controller.json','wack.xml','wack.json','wack-context.json','wack-reset.log','wack-stdout.log','wack-stderr.log')) {
 if (Test-Path -LiteralPath (Join-Path $OutputDirectory $name)) { throw 'Fresh diagnostic SDK outputs required.' }
}
$pendingPath=Join-Path $OutputDirectory 'pending-native.json'
$pendingSha=(Get-FileHash -LiteralPath $pendingPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($pendingSha -cne '17e44ee6c0ef1ca72f9c873b14f10b405744d26158e96466de5bb50741c4e696') { throw 'Original Source 81 pending JSON changed.' }
$pending=Get-Content -LiteralPath $pendingPath -Raw | ConvertFrom-Json
foreach ($name in @('repository','commit','runId','runAttempt')) {
 if ($pending.native.binding.$name -cne $sourceBinding[$name]) { throw 'Original native source binding differs.' }
}
$signedSha='e477c40740196bbced7cb123e57ab25c4edd0314dc6c9a0a5f933686a7f8f985'
$cerSha='ae780af23ac64716a2a8bc346e6079e5d9d7e163801baef718fac47366e9f4e2'
$thumbprint='7CFE4B4DDA1673B57FC63EC167CCBF48C1A27DB8'
if ($pending.signedSha256 -cne $signedSha -or $pending.native.installation.signedTestPackageSha256.ToLowerInvariant() -cne $signedSha -or
    (Get-FileHash -LiteralPath (Join-Path $NativeDirectory 'test-only.msix') -Algorithm SHA256).Hash.ToLowerInvariant() -cne $signedSha -or
    (Get-FileHash -LiteralPath (Join-Path $NativeDirectory 'test.cer') -Algorithm SHA256).Hash.ToLowerInvariant() -cne $cerSha -or
    $pending.native.certificate.sha256 -cne $cerSha -or $pending.native.certificate.thumbprint -cne $thumbprint) { throw 'Exact original signed input/CER required.' }
$inputEvidence=@{}
foreach ($name in @('installed-launch.json','installed-cli.json')) {
 $hash=(Get-FileHash -LiteralPath (Join-Path $OutputDirectory $name) -Algorithm SHA256).Hash.ToLowerInvariant()
 if ($hash -cne $pending.native.originalEvidence.$name.sha256) { throw 'Original installed CLI/GUI bytes differ.' }
 $inputEvidence[$name]=$hash
}
$original=Get-SameSignedProductionAst -Path (Join-Path $PSScriptRoot 'msix-wack-import.ps1')
$encoding=[Text.UTF8Encoding]::new($false)
$functionProof=@()
foreach ($function in $original.functions) {
 $path=Join-Path $OutputDirectory ('importer-fn-'+$function.name+'.ps1.txt')
 if (Test-Path -LiteralPath $path) { throw 'Fresh original function extent output required.' }
 [IO.File]::WriteAllBytes($path,$encoding.GetBytes($function.text))
 $functionProof+=@{name=$function.name;sha256=$function.sha256;bytes=$function.bytes;startOffset=$function.startOffset;endOffset=$function.endOffset;startLine=$function.startLine;endLine=$function.endLine}
 Invoke-Expression -Command $function.text
}
Assert-OpenGeulSelectedUnsignedPackage -PackageDirectory $PackageDirectory -ExpectedSha256 $pending.unsignedSha256
[IO.File]::WriteAllBytes((Join-Path $OutputDirectory 'importer-sdk-slice.ps1.txt'),$encoding.GetBytes($original.slice.text))
$proof=@{productionPath='e2e/msix-wack-import.ps1';productionSha256=$original.productionSha256;productionBytes=$original.productionBytes;
 functions=$functionProof;slice=@{sha256=$original.slice.sha256;bytes=$original.slice.bytes;startOffset=$original.slice.startOffset;endOffset=$original.slice.endOffset;
 startLine=$original.slice.startLine;endLine=$original.slice.endLine};slicePreservedVerbatim=$true;productionRoleGuardExecuted=$false;validateInputExecuted=$false;finalizeExecuted=$false}
Write-SameSignedFreshJson -Path (Join-Path $OutputDirectory 'importer-ast-slice.json') -Value $proof
$beforeEnvironment=Get-SameSignedEnvironmentDigest
$receipt=[ordered]@{formatVersion=1;success=$false;scope='Exact previously native-installed signed ARM64 bytes inspected by the unmodified stock x64 SDK block; diagnostic only';
 originalSourceBinding=$sourceBinding;diagnosticBinding=$diagnosticBinding;actualDiagnosticJob=$env:GITHUB_JOB;
 productionImporterSha256=$original.productionSha256;executedSliceSha256=$original.slice.sha256;exactSignedInputSha256=$signedSha;
 certificateSha256=$cerSha;certificateThumbprint=$thumbprint;unsignedOriginalSha256=$pending.unsignedSha256;originalPendingSha256=$pendingSha;
 processEnvironmentBeforeSha256=$beforeEnvironment.sha256;githubEnvironmentBeforeSha256=$beforeEnvironment.githubSha256;
 sourceBindingDiffersFromDiagnostic=$true;qualificationFinalized=$false;wholeSourceQualified=$false;storeCertified=$false}
try {
 # The pinned original assignments, SDK calls and try/finally execute verbatim.
 # This wrapper is also in e2e/, preserving the original PSScriptRoot resolution.
 Invoke-Expression -Command $original.slice.text
 $receipt.success=$true
} catch { $receipt.error=$_.Exception.Message;throw }
finally {
 $afterEnvironment=Get-SameSignedEnvironmentDigest
 $receipt.processEnvironmentAfterSha256=$afterEnvironment.sha256
 $receipt.githubEnvironmentAfterSha256=$afterEnvironment.githubSha256
 $receipt.processEnvironmentUnchanged=($beforeEnvironment.sha256 -ceq $afterEnvironment.sha256)
 $receipt.githubEnvironmentUnchanged=($beforeEnvironment.githubSha256 -ceq $afterEnvironment.githubSha256)
 $receipt.signedInputUnchanged=((Get-FileHash -LiteralPath (Join-Path $NativeDirectory 'test-only.msix') -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $signedSha)
 $receipt.publicCertificateUnchanged=((Get-FileHash -LiteralPath (Join-Path $NativeDirectory 'test.cer') -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $cerSha)
 $receipt.originalPendingUnchanged=((Get-FileHash -LiteralPath $pendingPath -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $pendingSha)
 $receipt.trustedCertificateAbsent=(-not (Test-Path -LiteralPath ('Cert:\LocalMachine\TrustedPeople\'+$thumbprint)))
 $receipt.originalInstalledEvidenceUnchanged=$true
 foreach ($name in $inputEvidence.Keys) {
  if ((Get-FileHash -LiteralPath (Join-Path $OutputDirectory $name) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $inputEvidence[$name]) { $receipt.originalInstalledEvidenceUnchanged=$false }
 }
 $receipt.installJsonAbsent=(-not (Test-Path -LiteralPath (Join-Path $OutputDirectory 'install.json')))
 Assert-OpenGeulSelectedUnsignedPackage -PackageDirectory $PackageDirectory -ExpectedSha256 $pending.unsignedSha256
 $receipt.unsignedOriginalUnchanged=$true
 foreach ($name in @('unsignedOriginalUnchanged','processEnvironmentUnchanged','githubEnvironmentUnchanged','signedInputUnchanged','publicCertificateUnchanged','originalPendingUnchanged','trustedCertificateAbsent','originalInstalledEvidenceUnchanged','installJsonAbsent')) {
  if ($receipt[$name] -ne $true) { $receipt.success=$false }
 }
 Write-SameSignedFreshJson -Path (Join-Path $OutputDirectory 'same-signed-sdk-diagnostic.json') -Value $receipt
 if (-not $receipt.success) { throw 'Same-signed SDK diagnostic did not pass all original-input/environment/cleanup checks; see its receipt.' }
}
