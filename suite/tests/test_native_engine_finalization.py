"""Exercise the real source-build catch/finally without compiling an engine."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE=Path(__file__).resolve().parents[1]/'scripts/build-native-engine.ps1'
PWSH=shutil.which('pwsh')
PRIVATE='SYNTHETIC-PRIVATE-PATH-OR-MESSAGE'
NAMES=('config_host.mk','config.log','autogen.input','workdir/UnpackedTarball/firebird/build.log')


def quote(value):return "'"+str(value).replace("'","''")+"'"


@unittest.skipUnless(PWSH,'PowerShell is required for the real finalization boundary')
class NativeEngineFinalizationTests(unittest.TestCase):
    def execute(self,*,primary=False,copy_failures=(),write_failure=False,diagnostic=True):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve(strict=True)
            source=root/'source';source.mkdir()
            for name in NAMES:
                path=source/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(('synthetic '+name).encode())
            evidence=root/'evidence';work=root/'work';script=root/'case.ps1'
            success="$receipt.passed=$true;$receipt.status=$mode.status;$receipt.stage='complete';$receipt.fullEngineQualified=$mode.fullEngineQualified;$receipt.acceptanceEligible=$mode.acceptanceEligible"
            outcome="throw $script:primary" if primary else success
            body=fr"""
$ErrorActionPreference='Stop'
. {quote(SOURCE)}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(SOURCE)},[ref]$tokens,[ref]$errors)
if($errors.Count){{throw 'Source parse failed'}}
$build=$ast.Find({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Invoke-NativeEngineBuild'}},$true)
$outer=$build.Body.Find({{param($n) $n -is [Management.Automation.Language.TryStatementAst] -and $n.Finally -and $n.Finally.Extent.Text.Contains('$receipt.finishedUtc')}},$false)
if(-not $outer){{throw 'Original build finalization missing'}}
# Substitute only compilation. Execute the actual catch/finally source text.
$driver=@'
try {{$source={quote(source)};{outcome}}}
'@
$driver+=' '+($outer.CatchClauses|ForEach-Object {{$_.Extent.Text}})+' finally '+$outer.Finally.Extent.Text
$script:copyFailures=@({','.join(str(code) for code in copy_failures)})
$script:copyAttempts=0;$script:writeAttempts=0
$script:primary=[InvalidOperationException]::new('synthetic original build failure')
$script:previousBudget=[pscustomobject]@{{marker=123}}
$previousBudget=$script:previousBudget
$script:NativeEngineBuildBudget=New-NativeBuildBudget
$mode=Get-NativeEngineBuildMode Full -CalcDispatchDiagnostic:${str(diagnostic).lower()}
$paths=New-BuildDirectories {quote(work)} {quote(evidence)}
$work=$paths.work;$evidence=$paths.output;$source='';$manifest=$null;$buildFailure=$null
$receipt=[ordered]@{{schemaVersion=1;kind=$mode.kind;phase='Full';architecture='arm64';status='failed';stage='synthetic-build';passed=$false;fullEngineQualified=$false;acceptanceEligible=$false;guiVerified=$false;buildBudget=$script:NativeEngineBuildBudget.record}}
function Copy-Item {{
 param([string]$LiteralPath,[string]$Destination,[switch]$Force)
 $script:copyAttempts++
 if($script:copyFailures -contains $script:copyAttempts){{throw [IO.IOException]::new('{PRIVATE}')}}
 Microsoft.PowerShell.Management\Copy-Item @PSBoundParameters
}}
$script:writeFailure=${str(write_failure).lower()}
function Write-BuildJson {{
 param($Path,$Value)
 $script:writeAttempts++
 if($script:writeFailure){{throw [IO.IOException]::new('{PRIVATE}')}}
 $Value|ConvertTo-Json -Depth 30|Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}}
$failed=$false;$primaryPreserved=$false
try{{& ([scriptblock]::Create($driver))}}
catch{{$failed=$true;$primaryPreserved=[Object]::ReferenceEquals($_.Exception,$script:primary)}}
[ordered]@{{failed=$failed;primaryPreserved=$primaryPreserved;copyAttempts=$script:copyAttempts;writeAttempts=$script:writeAttempts;budgetRestored=[Object]::ReferenceEquals($script:NativeEngineBuildBudget,$script:previousBudget)}}|ConvertTo-Json -Compress
"""
            script.write_text(body,encoding='utf-8')
            env=dict(os.environ,GH_TOKEN='synthetic-finalization-fixture-token',GITHUB_TOKEN='synthetic-finalization-fixture-token')
            process=subprocess.run([PWSH,'-NoLogo','-NoProfile','-NonInteractive','-File',str(script)],
                env=env,capture_output=True,text=True,encoding='utf-8',timeout=15,shell=False)
            self.assertEqual(process.returncode,0,process.stdout+process.stderr)
            result=json.loads(process.stdout)
            receipt_path=evidence/('calc-dispatch-source-build-receipt.json' if diagnostic else 'source-build-receipt.json')
            receipt=json.loads(receipt_path.read_text(encoding='utf-8-sig')) if receipt_path.exists() else None
            copied={name:(evidence/('firebird-build.log' if code==4 else name)).read_bytes()
                    for code,name in enumerate(NAMES,1) if (evidence/('firebird-build.log' if code==4 else name)).is_file()}
            return result,receipt,copied

    def test_primary_build_error_survives_copy_failure_and_receipt_is_retained(self):
        result,receipt,copied=self.execute(primary=True,copy_failures=(1,))
        self.assertTrue(result['primaryPreserved'],'Diagnostic copy failure replaced the original build exception')
        self.assertEqual(result['writeAttempts'],1)
        self.assertTrue(result['budgetRestored'])
        self.assertIsNotNone(receipt,'The final receipt must still be attempted after a copy failure')
        self.assertFalse(receipt['passed']);self.assertFalse(receipt['fullEngineQualified']);self.assertFalse(receipt['acceptanceEligible'])
        self.assertIn('synthetic original build failure',receipt['error'])
        retained=receipt['diagnosticRetention']
        self.assertEqual(retained,dict(schemaVersion=1,status='incomplete',attemptedCopies=4,retainedCopies=3,errorCodes=[1]))
        self.assertNotIn(PRIVATE,json.dumps(retained))
        self.assertEqual(len(copied),3)

    def test_successful_build_copy_failure_stays_failed_and_does_not_qualify(self):
        for diagnostic in (True,False):
            with self.subTest(diagnostic=diagnostic):
                result,receipt,_=self.execute(copy_failures=(2,4),diagnostic=diagnostic)
                self.assertTrue(result['failed']);self.assertTrue(result['budgetRestored'])
                self.assertIsNotNone(receipt)
                self.assertFalse(receipt['passed']);self.assertFalse(receipt['fullEngineQualified']);self.assertFalse(receipt['acceptanceEligible'])
                self.assertEqual(receipt['status'],'failed')
                self.assertEqual(receipt['diagnosticRetention']['errorCodes'],[2,4])
                self.assertNotIn(PRIVATE,json.dumps(receipt))

    def test_all_copy_failures_continue_to_the_single_final_receipt_attempt(self):
        result,receipt,copied=self.execute(primary=True,copy_failures=(1,2,3,4))
        self.assertTrue(result['primaryPreserved'])
        self.assertEqual((result['copyAttempts'],result['writeAttempts']),(4,1))
        self.assertEqual(receipt['diagnosticRetention']['errorCodes'],[1,2,3,4])
        self.assertEqual(receipt['diagnosticRetention']['retainedCopies'],0)
        self.assertEqual(copied,{})

    def test_receipt_write_failure_cannot_replace_an_original_build_failure(self):
        result,receipt,_=self.execute(primary=True,copy_failures=(1,),write_failure=True)
        self.assertTrue(result['primaryPreserved'])
        self.assertEqual(result['writeAttempts'],1)
        self.assertTrue(result['budgetRestored'])
        self.assertIsNone(receipt)

    def test_receipt_write_failure_after_success_still_fails(self):
        result,receipt,_=self.execute(write_failure=True)
        self.assertTrue(result['failed'])
        self.assertEqual(result['writeAttempts'],1)
        self.assertTrue(result['budgetRestored'])
        self.assertIsNone(receipt)

    def test_success_preserves_mode_qualification_and_owned_diagnostic_bytes(self):
        for diagnostic in (True,False):
            with self.subTest(diagnostic=diagnostic):
                result,receipt,copied=self.execute(diagnostic=diagnostic)
                self.assertFalse(result['failed'])
                self.assertTrue(result['budgetRestored'])
                self.assertTrue(receipt['passed'])
                self.assertEqual(receipt['fullEngineQualified'],not diagnostic)
                self.assertEqual(receipt['acceptanceEligible'],not diagnostic)
                self.assertEqual(receipt['diagnosticRetention'],dict(schemaVersion=1,status='complete',attemptedCopies=4,retainedCopies=4,errorCodes=[]))
                self.assertEqual(copied,{name:('synthetic '+name).encode() for name in NAMES})


if __name__=='__main__':unittest.main()
