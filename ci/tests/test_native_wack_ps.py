"""Native 증거는 정리 후에만 게시하고 SDK process proof는 실제 소유 PID를 검사한다."""
from pathlib import Path
import importlib.util
import json
import os
import subprocess
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PW = Path(shutil.which('pwsh') or '/workspace/OpenGeul-ci-build-progress/.work/powershell746/bin/pwsh')


class NativeTransportPowerShellTests(unittest.TestCase):
    @unittest.skipUnless(PW.is_file(), 'PowerShell runtime unavailable')
    def test_native_publication_is_atomic_and_rejects_every_failed_cleanup(self):
        # Removing a cleanup gate must make this real function execution fail.
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp)/'boundary.ps1'
            script.write_text(r'''
param([string]$Source,[string]$Root)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'parse failed' }
$function=$tree.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Write-OpenGeulNativeResult'},$true)
if (-not $function) { throw 'native publication function missing' }
Invoke-Expression $function.Extent.Text
$cleanupFields=@('candidateUninstalled','unsignedUnchanged','privateKeyRemoved','trustedCertificateRemoved','frameworksRemoved')
foreach ($failed in @('','nativeSuccess','oversize')+$cleanupFields) {
 $directory=Join-Path $Root $(if ($failed) {$failed} else {'success'})
 New-Item -ItemType Directory $directory | Out-Null
 [IO.File]::WriteAllBytes((Join-Path $directory 'test-only.msix'),[byte[]]@(1,2,3))
 [IO.File]::WriteAllBytes((Join-Path $directory 'test.cer'),[byte[]]@(4,5,6))
 $cleanup=[ordered]@{};foreach($key in $cleanupFields){$cleanup[$key]=$key -ne $failed}
 $native=[ordered]@{formatVersion=1;success=($failed -ne 'nativeSuccess');scope='native-arm64-install-only';binding=@{repository='ATLKR/OpenGeul';commit=('a'*40);runId='123';runAttempt='1'};
  installation=@{success=$true;architecture='arm64';uninstalled=$true;signedTestPackageSha256=(Get-FileHash (Join-Path $directory 'test-only.msix')).Hash.ToLowerInvariant()};
  launch=@{success=$true};cli=@{success=$true};cleanup=$cleanup;
  certificate=@{sha256=(Get-FileHash (Join-Path $directory 'test.cer')).Hash.ToLowerInvariant()}}
 if ($failed -eq 'oversize') {$native.launch.extra='a'*(513*1024)}
 $threw=$false
 try { Write-OpenGeulNativeResult -TransportDirectory $directory -Record $native } catch {$threw=$true}
 $written=Test-Path (Join-Path $directory 'native-install.json')
 if ($failed -and (-not $threw -or $written)) {throw "failed cleanup published: $failed"}
 if (-not $failed -and ($threw -or -not $written)) {throw 'complete cleanup did not publish'}
 if (-not $failed) {
  $record=Get-Content (Join-Path $directory 'native-install.json') -Raw | ConvertFrom-Json
  if ($record.scope -cne 'native-arm64-install-only') {throw 'wrong native scope'}
  try {Write-OpenGeulNativeResult -TransportDirectory $directory -Record $native;throw 'overwrite accepted'} catch {
   if ($_.Exception.Message -eq 'overwrite accepted') {throw}
  }
 }
}
''',encoding='utf-8')
            result = subprocess.run([str(PW),'-NoProfile','-File',str(script),
                                     '-Source',str(ROOT/'e2e/msix-install.ps1'),'-Root',tmp],
                                    capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(PW.is_file(), 'PowerShell runtime unavailable')
    def test_public_cer_der_and_eku_are_checked_against_real_certificate(self):
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'cert-boundary.ps1'
            script.write_text(r"""
param([string]$Source,[string]$Root)
$ErrorActionPreference='Stop'
$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
$f=$a.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-OpenGeulNativePublicCertificate'},$true)
if (-not $f) {throw 'certificate function missing'}
Invoke-Expression $f.Extent.Text
$rsa=[Security.Cryptography.RSA]::Create(2048)
$req=[Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=OpenGeul Development',$rsa,[Security.Cryptography.HashAlgorithmName]::SHA256,[Security.Cryptography.RSASignaturePadding]::Pkcs1)
$oids=[Security.Cryptography.OidCollection]::new();[void]$oids.Add([Security.Cryptography.Oid]::new('1.3.6.1.5.5.7.3.3'))
$req.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($oids,$false))
$now=[DateTimeOffset]::UtcNow;$cert=$req.CreateSelfSigned($now.AddMinutes(-5),$now.AddHours(23))
$der=$cert.Export([Security.Cryptography.X509Certificates.X509ContentType]::Cert)
$path=Join-Path $Root 'test.cer';[IO.File]::WriteAllBytes($path,$der)
$metadata=@{derBase64=[Convert]::ToBase64String($der);sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($der)).ToLowerInvariant();
 thumbprint=$cert.Thumbprint;signerThumbprint=$cert.Thumbprint;subject=$cert.Subject;
 notBefore=$cert.NotBefore.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss'Z'");notAfter=$cert.NotAfter.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss'Z'");
 codeSigning=$true;publicOnly=$true;signatureStatus='Valid'}
$parsed=Get-OpenGeulNativePublicCertificate -FilePath $path -Metadata $metadata -Publisher $cert.Subject
if ($parsed.HasPrivateKey -or $parsed.Thumbprint -cne $cert.Thumbprint) {throw 'public DER import mismatch'}
$parsed.Dispose()
foreach($field in @('derBase64','sha256','thumbprint','signerThumbprint','subject','notBefore','notAfter','codeSigning','publicOnly','signatureStatus')) {
 $bad=$metadata.Clone();$bad[$field]=if ($metadata[$field] -is [bool]) {$false} else {'mismatch'}
 $accepted=$false;try {$p=Get-OpenGeulNativePublicCertificate -FilePath $path -Metadata $bad -Publisher $cert.Subject;$p.Dispose();$accepted=$true} catch {}
 if ($accepted) {throw "certificate metadata mismatch accepted: $field"}
}
foreach ($kind in @('pfx','noeku','longlived','expired','future')) {
 if ($kind -eq 'pfx') {$bytes=$cert.Export([Security.Cryptography.X509Certificates.X509ContentType]::Pkcs12,'password')} else {
  $request=[Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=OpenGeul Development',$rsa,[Security.Cryptography.HashAlgorithmName]::SHA256,[Security.Cryptography.RSASignaturePadding]::Pkcs1)
  if ($kind -ne 'noeku') {$request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($oids,$false))}
  $from=if($kind -eq 'future'){$now.AddHours(1)}elseif($kind -eq 'expired'){$now.AddHours(-3)}else{$now.AddMinutes(-5)}
  $until=if($kind -eq 'longlived'){$now.AddDays(2)}elseif($kind -eq 'expired'){$now.AddHours(-1)}else{$now.AddHours(23)}
  $other=$request.CreateSelfSigned($from,$until);$bytes=$other.Export([Security.Cryptography.X509Certificates.X509ContentType]::Cert)
 }
 $caseMetadata=$metadata.Clone()
 if ($kind -ne 'pfx') {
  $caseMetadata.derBase64=[Convert]::ToBase64String($bytes);$caseMetadata.sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
  $caseMetadata.thumbprint=$other.Thumbprint;$caseMetadata.signerThumbprint=$other.Thumbprint
  $caseMetadata.notBefore=$other.NotBefore.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss'Z'");$caseMetadata.notAfter=$other.NotAfter.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss'Z'")
 }
 [IO.File]::WriteAllBytes($path,$bytes)
 $accepted=$false;try {$p=Get-OpenGeulNativePublicCertificate -FilePath $path -Metadata $caseMetadata -Publisher $cert.Subject;$p.Dispose();$accepted=$true} catch {}
 if ($accepted) {throw "invalid certificate accepted: $kind"}
 if ($kind -ne 'pfx') {$other.Dispose()}
}
$cert.Dispose();$rsa.Dispose()
""",encoding='utf-8')
            result=subprocess.run([str(PW),'-NoProfile','-File',str(script),'-Source',str(ROOT/'e2e/msix-wack-import.ps1'),'-Root',tmp],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(PW.is_file(), 'PowerShell runtime unavailable')
    def test_raw_launch_and_cli_evidence_preserves_every_original_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'original-evidence.ps1'
            script.write_text(r"""
param([string]$Source,[string]$Root)
$ErrorActionPreference='Stop'
$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
$f=$a.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-OpenGeulNativeOriginalEvidence'},$true)
if (-not $f) {throw 'original evidence collector missing'}
Invoke-Expression $f.Extent.Text
$raw1=[Text.UTF8Encoding]::new($false).GetBytes("{`r`n  `"success`": true, `"value`": `"한글`"`r`n}`r`n")
$raw2=[Text.UTF8Encoding]::new($false).GetBytes('{"success":true,"cli":"rhwp"}'+"`n")
[IO.File]::WriteAllBytes((Join-Path $Root 'installed-launch.json'),$raw1)
[IO.File]::WriteAllBytes((Join-Path $Root 'installed-cli.json'),$raw2)
$evidence=Get-OpenGeulNativeOriginalEvidence -OutputDirectory $Root
if ($evidence.Count -ne 2) {throw 'raw original count mismatch'}
foreach($name in @('installed-launch.json','installed-cli.json')) {
 $bytes=[IO.File]::ReadAllBytes((Join-Path $Root $name));$record=$evidence[$name]
 if($record.bytes -ne $bytes.Length -or $record.rawBase64 -cne [Convert]::ToBase64String($bytes) -or
    $record.sha256 -cne [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()) {throw 'raw original bytes/hash mismatch'}
}
""",encoding='utf-8')
            result=subprocess.run([str(PW),'-NoProfile','-File',str(script),'-Source',str(ROOT/'e2e/msix-install.ps1'),'-Root',tmp],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(PW.is_file(), 'PowerShell runtime unavailable')
    def test_native_role_and_architecture_are_rejected_before_any_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            environment=os.environ|{'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted',
                'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}
            for role,architecture in (('msix-install-arm64','arm64'),('msix-native-arm64','x64'),('store-wack','arm64')):
                env=environment|{'GITHUB_JOB':role}
                output=base/(role+'-'+architecture)
                transport=base/(role+'-'+architecture+'-transport')
                result=subprocess.run([str(PW),'-NoProfile','-File',str(ROOT/'e2e/msix-install.ps1'),
                    '-PackageDirectory',str(base/'missing-package'),'-OutputDirectory',str(output),
                    '-McpFixtureDirectory',str(base/'missing-fixture'),'-ExpectedCliSha256','a'*64,
                    '-Architecture',architecture,'-NativeOnly','-TransportDirectory',str(transport)],
                    env=env,capture_output=True,text=True)
                with self.subTest(role=role,architecture=architecture):
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('NativeOnly',result.stderr)
                    self.assertFalse(output.exists());self.assertFalse(transport.exists())

    def test_native_only_cannot_emit_wack_or_install_before_cleanup(self):
        source=(ROOT/'e2e/msix-install.ps1').read_text()
        self.assertIn('[switch]$NativeOnly',source)
        self.assertIn("'msix-native-arm64','store-native-arm64'",source)
        self.assertIn('if (-not $NativeOnly)',source)
        self.assertLess(source.index('finally {', source.index('$cert=$null')),source.rindex('Write-OpenGeulNativeResult -TransportDirectory'))
        self.assertIn('NotBefore',source)
        self.assertIn('AddHours(23)',source)
        self.assertEqual(source.count('AddSeconds(60)'),2)

    @unittest.skipUnless(PW.is_file(), 'PowerShell runtime unavailable')
    def test_store_selected_msix_is_bound_to_full_original_directory_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'selected-boundary.ps1'
            script.write_text(r"""
param([string]$Source,[string]$Root)
$ErrorActionPreference='Stop'
$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
$f=$a.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-OpenGeulSelectedUnsignedPackage'},$true)
if (-not $f) {throw 'selected package boundary missing'}
Invoke-Expression $f.Extent.Text
$selected=Join-Path $Root 'selected';$full=Join-Path $Root 'full';New-Item -ItemType Directory $selected,$full | Out-Null
[IO.File]::WriteAllBytes((Join-Path $selected 'OpenGeul_arm64.msix'),[byte[]]@(1,2,3))
[IO.File]::WriteAllBytes((Join-Path $full 'OpenGeul_arm64.msix'),[byte[]]@(1,2,3))
[IO.File]::WriteAllBytes((Join-Path $full 'OpenGeul_x64.msix'),[byte[]]@(4,5,6))
[IO.File]::WriteAllText((Join-Path $selected 'AppxManifest.xml'),'arm64')
$sha=(Get-FileHash (Join-Path $full 'OpenGeul_arm64.msix')).Hash.ToLowerInvariant()
Assert-OpenGeulSelectedUnsignedPackage -PackageDirectory $selected -ExpectedSha256 $sha
foreach($case in @('swapped','full-original','missing')) {
 if($case -eq 'swapped'){[IO.File]::WriteAllBytes((Join-Path $selected 'OpenGeul_arm64.msix'),[byte[]]@(4,5,6));$input=$selected}
 elseif($case -eq 'full-original'){$input=$full}else{$input=Join-Path $Root 'missing'}
 $accepted=$false;try{Assert-OpenGeulSelectedUnsignedPackage -PackageDirectory $input -ExpectedSha256 $sha;$accepted=$true}catch{}
 if($accepted){throw "unbound selected input accepted: $case"}
}
""",encoding='utf-8')
            result=subprocess.run([str(PW),'-NoProfile','-File',str(script),'-Source',str(ROOT/'e2e/msix-wack-import.ps1'),'-Root',tmp],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        source=(ROOT/'e2e/msix-wack-import.ps1').read_text()
        self.assertEqual(source.count('--package-directory $OriginalDirectory'),2)
        self.assertNotIn('--package-directory $PackageDirectory',source)
        self.assertGreaterEqual(source.count('Assert-OpenGeulSelectedUnsignedPackage -PackageDirectory $PackageDirectory'),2)

    def test_importer_validates_transport_before_trust_and_finalizes_after_wack(self):
        path=ROOT/'e2e/msix-wack-import.ps1'
        self.assertTrue(path.is_file(), 'native SDK importer missing')
        source=path.read_text()
        self.assertLess(source.index('validate-input'),source.index('Import-Certificate'))
        self.assertLess(source.index("'wack-controller.py'"),source.index("'wack.ps1'"))
        self.assertLess(source.index("'wack.ps1'"),source.index(' finalize '))
        self.assertIn('HasPrivateKey',source)
        self.assertIn('Get-AuthenticodeSignature',source)
        self.assertNotIn('Add-AppxPackage',source)
        self.assertNotIn('Export-PfxCertificate',source)
        self.assertIn('finally {',source)


if __name__=='__main__':unittest.main()
