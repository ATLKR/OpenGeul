"""The original authenticated focus patch must precede the observer's5e5 baseline."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
ENGINE=ROOT/'suite/engine-build'
BASELINE=ROOT.parent/'baseline'
BACKEND=ENGINE/'writer-server-observer-diagnostic' if (ENGINE/'writer-server-observer-diagnostic').is_dir() else BASELINE/'writer-backend'
SOURCE_PLAN=ENGINE/'source-build.json' if (ENGINE/'source-build.json').is_file() else BASELINE/'source-build.json'


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class AuthenticatedBaseline(unittest.TestCase):
    def test_raw_source_is_rejected_until_exact_normal_patch_is_installed(self):
        pin=json.loads((SOURCE_PLAN).read_text())['winAccFocusOrder']
        backend=load(BACKEND/'install.py','baseline_observer')
        with tempfile.TemporaryDirectory() as temporary:
            temp=Path(temporary);source=temp/'source';shutil.copytree(BACKEND/'tests/upstream',source);(source/'include').mkdir()
            manager=source/pin['path'];effective=manager.read_bytes();moved=b'        pAccObjNew->setFocus();\n';anchor=b'        oldFocus = newFocus;\n'
            self.assertEqual((effective.count(moved),effective.count(anchor)),(1,1))
            raw=effective.replace(moved,b'',1).replace(anchor,anchor+moved,1)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),pin['sha256']);manager.write_bytes(raw)
            with self.assertRaises(ValueError):backend.install(source,'windows-arm64')
            self.assertEqual(manager.read_bytes(),raw);self.assertFalse((source/'include/opengeul_writer_observer').exists())
            self.assertTrue((ENGINE/'apply_winacc_focus_order.py').is_file(),'Exact normal focus installer has not been wired')
            package=temp/'normal';package.mkdir();shutil.copyfile(ENGINE/'apply_winacc_focus_order.py',package/'apply_winacc_focus_order.py');shutil.copyfile(ENGINE/'winacc-focus-order.patch',package/'winacc-focus-order.patch');shutil.copyfile(SOURCE_PLAN,package/'source-build.json')
            normal=load(package/'apply_winacc_focus_order.py','baseline_normal');evidence=temp/'evidence';evidence.mkdir()
            proof=normal.install(source,evidence,backend.CORE)
            self.assertEqual(manager.read_bytes(),effective);self.assertEqual(proof['afterSha256'],pin['afterSha256']);self.assertFalse(proof['nativeBuildVerified']);self.assertFalse(proof['guiVerified'])
            observed=backend.install(source,'windows-arm64')
            self.assertFalse(observed['acceptanceEligible']);self.assertFalse(observed['fullEngineQualified'])
            expected=json.loads((BACKEND/'source-lock.json').read_text())['sources'][1]['after']['sha256']
            self.assertEqual(hashlib.sha256(manager.read_bytes()).hexdigest(),expected)


class DriverScope(unittest.TestCase):
    def test_only_writer_branch_gets_the_focus_precondition_call(self):
        fixture=ROOT/'suite/tests/fixtures/writer-focus-baseline';pin=json.loads((fixture/'pins.json').read_text());changed=(ROOT/'suite/scripts/build-native-engine.ps1').read_text()
        added=(fixture/'added-function.ps1').read_text()+'\n'
        call="            $receipt.writerServerObserverFocusBaseline=Install-WriterServerObserverFocusBaseline $source $repo $python $evidence $pin\n"
        self.assertEqual(changed.count(added),1);self.assertEqual(changed.count(call),1)
        logging=json.loads((fixture/'logging-only-projection.json').read_text())
        self.assertEqual(logging['scope'],'Invoke-LoggedCommand closed ChildEnvironment logging only; null mode original statements retained')
        for side in ('before','after'):
            self.assertEqual(hashlib.sha256(logging[side].encode()).hexdigest(),logging[side+'Sha256'])
        self.assertEqual(changed.count(logging['after']),1)
        original=changed.replace(added,'',1).replace(call,'',1).replace(logging['after'],logging['before'],1)
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),pin['baselineDriverSha256'])
        branch=changed.index('        if($WriterServerObserverDiagnostic) {',changed.index("$receipt.stage='install-authenticated-source-hooks'"))
        end=changed.index('        Write-BashScript',branch)
        selected=changed[branch:end]
        self.assertLess(selected.index('Install-WriterServerObserverFocusBaseline'),selected.index('Install-WriterServerObserverSource $source'))
        self.assertIn("$receipt.stage='install-authenticated-writer-server-observer-diagnostic'",selected)

    def test_focus_child_environment_uses_the_existing_closed_allowlist(self):
        changed=(ROOT/'suite/scripts/build-native-engine.ps1').read_text()
        focus=changed.split('function Install-WriterServerObserverFocusBaseline(',1)[1].split('\nfunction ',1)[0]
        observer=changed.split('function Install-WriterServerObserverSource(',1)[1].split('\nfunction ',1)[0]
        block="""    if($null -eq $ChildEnvironment) {
        $ChildEnvironment=@{PYTHONUTF8='1';PYTHONDONTWRITEBYTECODE='1'}
        foreach($key in @('PATH','SystemRoot','WINDIR','TEMP','TMP')) {
            $value=[Environment]::GetEnvironmentVariable($key)
            if($null -ne $value) {$ChildEnvironment[$key]=$value}
        }
    }
"""
        self.assertIn(block,observer)
        self.assertIn(block,focus,'Focus helper must restrict its child map before process start')
        self.assertIn('-ChildEnvironment $ChildEnvironment',focus)
        self.assertNotIn('GetEnvironmentVariables(',focus)

    def test_closed_command_receipt_and_console_use_a_separate_projection(self):
        changed=(ROOT/'suite/scripts/build-native-engine.ps1').read_text()
        command=changed.split('function Invoke-LoggedCommand(',1)[1].split('\nfunction ',1)[0]
        self.assertIn('$closedSource=($null -ne $ChildEnvironment)',command)
        self.assertIn('if(-not $closedSource) {',command)
        self.assertIn('argumentCount=@($Arguments).Count',command)
        self.assertIn('cleanupErrorCount=@($receipt.cleanupErrors).Count',command)
        self.assertIn("Write-BuildJson ($LogPrefix+'.command.json') $closedReceipt",command)
        self.assertIn('if(-not $closedSource) {Write-CommandFailureTail',command)

    def test_closed_receipt_write_failure_is_a_fixed_error(self):
        changed=(ROOT/'suite/scripts/build-native-engine.ps1').read_text()
        command=changed.split('function Invoke-LoggedCommand(',1)[1].split('\nfunction ',1)[0]
        self.assertIn("try {Write-BuildJson ($LogPrefix+'.command.json') $closedReceipt}",command)
        self.assertIn("catch {throw 'Closed source command receipt write failed.'}",command)

    def test_focus_log_prefix_does_not_alias_its_existing_proof_directory(self):
        changed=(ROOT/'suite/scripts/build-native-engine.ps1').read_text()
        focus=changed.split('function Install-WriterServerObserverFocusBaseline(',1)[1].split('\nfunction ',1)[0]
        self.assertIn("$proofDirectory=Join-Path $EvidenceDirectory 'writer-focus-baseline'",focus)
        self.assertIn("$Repo (Join-Path $EvidenceDirectory 'writer-focus-baseline-source-hooks') -ChildEnvironment $ChildEnvironment",focus)

    def test_closed_preflight_io_error_is_fixed_and_null_mode_stays_original(self):
        changed=(ROOT/'suite/scripts/build-native-engine.ps1').read_text()
        command=changed.split('function Invoke-LoggedCommand(',1)[1].split('\nfunction ',1)[0]
        closed="""    if($closedSource) {
        try {
            foreach($path in @($stdout,$stderr,$LogPrefix+'.command.json')) {if(Test-Path -LiteralPath $path -ErrorAction Stop){throw 'Command evidence already exists.'}}
        } catch {throw 'Closed source command preflight failed.'}
    } else {
        foreach($path in @($stdout,$stderr,$LogPrefix+'.command.json')) {if(Test-Path -LiteralPath $path){throw 'Command evidence already exists.'}}
    }
"""
        self.assertIn(closed,command)

    def test_normal_helper_and_patch_are_exact_copies(self):
        pins=json.loads((ROOT/'suite/tests/fixtures/writer-focus-baseline/pins.json').read_text())['copiedNormalHelperHashes']
        for name,digest in pins.items():self.assertEqual(hashlib.sha256((ENGINE/name).read_bytes()).hexdigest(),digest)


if __name__=='__main__':unittest.main()
