"""Portable source/PowerShell contracts; no Windows compiler or Full execution."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import shutil
import unittest

import test_source_companion_capture as capture_fixture

ROOT=Path(__file__).resolve().parents[2]
DRIVER=ROOT/'suite/scripts/build-native-engine.ps1'
PWSH=Path(shutil.which('pwsh') or '/workspace/toolcache/opengeul-validation/powershell/pwsh')
def quote(p):return "'"+str(p).replace("'","''")+"'"

class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def ps(self,body):
        script=self.root/'case.ps1';script.write_text("$ErrorActionPreference='Stop'\n. "+quote(DRIVER)+'\n'+body)
        env={'PATH':str(PWSH.parent)+':/usr/bin:/bin','PYTHONUTF8':'1'}
        if os.name=='nt':env={'PATH':str(PWSH.parent),'SystemRoot':os.environ.get('SystemRoot',r'C:\Windows'),'PYTHONUTF8':'1'}
        return subprocess.run([str(PWSH),'-NoLogo','-NoProfile','-File',str(script)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env,timeout=20).returncode
    def test_numeric_command_discards_streams_arguments_and_exception_text(self):
        child=self.root/'synthetic.py';child.write_text("import sys\nprint('SYNTHETIC-STDOUT')\nprint('SYNTHETIC-STDERR',file=sys.stderr)\nraise SystemExit(2)\n")
        prefix=self.root/'observed'
        code=self.ps("if(-not (Get-Command Invoke-LoggedCommand).Parameters.ContainsKey('NumericOnly')){exit 7}\n"+
            "$rejected=$false;try{Invoke-LoggedCommand "+quote(sys.executable)+" @('-I','-B',"+quote(child)+") "+quote(self.root)+" "+quote(prefix)+" -TimeoutMinutes 0.1 -NumericOnly|Out-Null}catch{$rejected=$true};if(-not $rejected){exit 8}")
        self.assertEqual(code,0)
        value=json.loads(prefix.with_suffix('.command.json').read_text(encoding='utf-8-sig'))
        for forbidden in ('file','arguments','workingDirectory','error','cleanupErrors'):self.assertNotIn(forbidden,value)
        self.assertEqual(value['exitCode'],2);self.assertIs(value['passed'],False)
        self.assertFalse(prefix.with_suffix('.stdout.log').exists());self.assertFalse(prefix.with_suffix('.stderr.log').exists())
    def test_component_binder_requires_current_context_and_generic_native_gate_stays_closed(self):
        fixture=capture_fixture.CaptureTests('test_exact_source_and_owned_partial_component_capture');fixture.setUp();self.addCleanup(fixture.doCleanups)
        paths=fixture.fixture('ps');self.assertEqual(fixture.run_capture(paths),0)
        proof=paths[-1]/'source-companion-proof.json';body="$p=Get-Content "+quote(proof)+" -Raw|ConvertFrom-Json\n"
        body+="$r=[pscustomobject]@{sourcePin=[pscustomobject]@{coreCommit='9dea406ab7695df6325b11b0e19fdca8db4b7276'};architecture='x64';sourceCommit=$p.buildBinding.sourceCommit;sourceTree=$p.buildBinding.sourceTree;sourceRun=$p.buildBinding.sourceRun;runAttempt=$p.buildBinding.runAttempt;sourceRecipeProof=[pscustomobject]@{recipeSha256=$p.buildBinding.recipeSha256};sourceCompanionProof=$p}\n"
        body+="$row=Get-OwnedSourceCompanionProduct $r "+quote(paths[1])+' '+quote(paths[-1])+";if($row.role -cne 'x86CompatibilityHelper'){exit 9}\n"
        body+="$rejected=$false;try{Get-AuditedProductPeIdentity "+quote(paths[1]/'program/spsupp_x86.dll')+' '+quote(paths[1])+' '+quote(paths[-1])+" x64 -RequireNative|Out-Null}catch{$rejected=$true};if(-not $rejected){exit 10}\n"
        body+="$r.sourceRun=124;$rejected=$false;try{Get-OwnedSourceCompanionProduct $r "+quote(paths[1])+' '+quote(paths[-1])+"|Out-Null}catch{$rejected=$true};if(-not $rejected){exit 11}\n"
        self.assertEqual(self.ps(body),0)
    def test_full_capture_revalidation_and_separate_inventory_role_are_mandatory(self):
        source=DRIVER.read_text()
        self.assertIn("$receipt.stage='source-companion-audit'",source)
        self.assertIn("$receipt.stage='revalidate-source-companion'",source)
        self.assertIn("$receipt.companionPeCount=",source)
        def body(text):return text[text.index('function Get-ProductPeIdentity('):text.index('function Save-ProductPeFailure(')]
        self.assertEqual(hashlib.sha256(body(source).encode()).hexdigest(),'03a16d71f4cddf8cf24997d5e3f2c0655b449abdc4a2d0e82b2fd83f962c500d')
    def test_component_object_cannot_differ_from_current_owned_proof_file(self):
        fixture=capture_fixture.CaptureTests('test_exact_source_and_owned_partial_component_capture');fixture.setUp();self.addCleanup(fixture.doCleanups)
        paths=fixture.fixture('object-boundary');self.assertEqual(fixture.run_capture(paths),0)
        proof=paths[-1]/'source-companion-proof.json';body="$p=Get-Content "+quote(proof)+" -Raw|ConvertFrom-Json\n"
        body+="$r=[pscustomobject]@{sourcePin=[pscustomobject]@{coreCommit='9dea406ab7695df6325b11b0e19fdca8db4b7276'};architecture='x64';sourceCommit=$p.buildBinding.sourceCommit;sourceTree=$p.buildBinding.sourceTree;sourceRun=$p.buildBinding.sourceRun;runAttempt=$p.buildBinding.runAttempt;sourceRecipeProof=[pscustomobject]@{recipeSha256=$p.buildBinding.recipeSha256};sourceCompanionProof=$p}\n"
        body+="$p.sourceProofs[0].sha256=('0'*64);$rejected=$false;try{Get-OwnedSourceCompanionProduct $r "+quote(paths[1])+' '+quote(paths[-1])+"|Out-Null}catch{$rejected=$true};if(-not $rejected){exit 12}\n"
        self.assertEqual(self.ps(body),0)
