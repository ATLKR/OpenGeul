"""Diagnostic-only source replay: no product/runtime qualification."""
import importlib.util
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import json

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / 'suite/diagnostics/native-merged-package'
SCRIPT = ROOT / 'suite/scripts/probe-native-merged-package-control.ps1'
PWSH = shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'


class MergedPackageReplayTests(unittest.TestCase):
    def renderer(self):
        path = DATA / 'render_control.py'
        self.assertTrue(path.is_file(), 'authentic merged-package renderer is required')
        spec = importlib.util.spec_from_file_location('merged_package_control', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_authentic_make_rejects_merged_placeholder_from_install_selection(self):
        module = self.renderer()
        with tempfile.TemporaryDirectory(prefix='merged-package-') as temporary:
            root = pathlib.Path(temporary)
            result = module.prepare(DATA, root)
            process = subprocess.run([shutil.which('make'), '--no-builtin-rules', '--no-builtin-variables', '-f', str(root / 'control.mk')], cwd=root, capture_output=True, text=True)
            self.assertEqual(0, process.returncode, process.stderr)
            self.assertEqual(b'invalid - merged lib\n', (root/'instdir/program/avmedialo.dll').read_bytes())
            rows = (root/'installation-selection.txt').read_text().splitlines()
            self.assertEqual(['avmedia merged standalone', 'merged standalone'], rows)
            self.assertEqual('upstream-source-replay-only', result['scope'])
            self.assertEqual(False, result['native28DllCauseProven'])
            self.assertEqual(False, result['fullEngineQualified'])

    def test_modified_authentic_source_is_rejected_before_makefile_or_output(self):
        module = self.renderer()
        with tempfile.TemporaryDirectory(prefix='merged-package-') as temporary:
            root=pathlib.Path(temporary); altered=root/'altered';shutil.copytree(DATA, altered)
            pin=altered/'linktarget-command.mk';pin.write_bytes(pin.read_bytes().replace(b'echo invalid - merged lib',b'echo ignored - merged lib'))
            output=root/'output';output.mkdir()
            with self.assertRaisesRegex(ValueError, 'fixture identity'):
                module.prepare(altered, output)
            self.assertEqual([],list(output.iterdir()))

    def test_no_overwrite_of_previous_control_outputs(self):
        module = self.renderer()
        with tempfile.TemporaryDirectory(prefix='merged-package-') as temporary:
            root=pathlib.Path(temporary);module.prepare(DATA,root)
            original=(root/'control.mk').read_bytes()
            with self.assertRaises(FileExistsError):
                module.prepare(DATA,root)
            self.assertEqual(original,(root/'control.mk').read_bytes())

    def powershell(self, body):
        self.assertTrue(SCRIPT.is_file(), 'bounded package control controller is required')
        quote=lambda value: "'"+str(value).replace("'","''")+"'"
        process=subprocess.run([PWSH,'-NoProfile','-NonInteractive','-Command',"$ErrorActionPreference='Stop'; . "+quote(SCRIPT)+'; '+body],capture_output=True,text=True,timeout=25)
        self.assertEqual(0,process.returncode,process.stdout+process.stderr)
        return process.stdout

    def test_original_pe_auditor_rejects_both_exact_and_mutated_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=pathlib.Path(temporary);quote=lambda value:"'"+str(value).replace("'","''")+"'"
            for name,raw in [('original.dll',b'invalid - merged lib\n'),('changed.dll',b'other text\n'),('empty.dll',b'')]:
                path=root/name;path.write_bytes(raw)
                observed=json.loads(self.powershell('Observe-ControlPeRejection '+quote(path)+'|ConvertTo-Json -Compress'))
                self.assertTrue(observed['rejected']);self.assertEqual('Invalid PE: '+str(path),observed['error'])

    def test_receipt_requires_owned_normal_drained_zero_exit(self):
        self.powershell("$good=[pscustomobject]@{passed=$true;exitCode=0;pid=123;creationUtcTicks=638000000000000000;pipeDrainComplete=$true;forcedTermination=$false;directProcessDeathVerified=$true;processTreeCleanup='not-requested';cleanupErrors=@()};Assert-ControlCommandReceipt $good;foreach($field in @('passed','exitCode','pid','creationUtcTicks','pipeDrainComplete','forcedTermination','directProcessDeathVerified','processTreeCleanup','cleanupErrors')){$bad=$good.PSObject.Copy();switch($field){passed{$bad.passed=$false}exitCode{$bad.exitCode=1}pid{$bad.pid=0}creationUtcTicks{$bad.creationUtcTicks=0}pipeDrainComplete{$bad.pipeDrainComplete=$false}forcedTermination{$bad.forcedTermination=$true}directProcessDeathVerified{$bad.directProcessDeathVerified=$false}processTreeCleanup{$bad.processTreeCleanup='unproved'}cleanupErrors{$bad.cleanupErrors=@('bad')}};$rejected=$false;try{Assert-ControlCommandReceipt $bad}catch{$rejected=$true};if(-not $rejected){throw ('Accepted invalid receipt field '+$field)}}")

    def test_dot_sourcing_preserves_external_deadline(self):
        quote=lambda value:"'"+str(value).replace("'","''")+"'"
        self.powershell('. '+quote(SCRIPT)+" -DeadlineUtc '2030-01-01T00:00:00.0000000Z';if($DeadlineUtc -cne '2030-01-01T00:00:00.0000000Z'){throw 'External deadline changed'}")

    def test_workflow_preserves_bounded_control_and_original_evidence(self):
        workflow=ROOT/'.github/workflows/office-native-merged-package-control.yml'
        self.assertTrue(workflow.is_file(), 'isolated bounded workflow is required')
        text=workflow.read_text()
        self.assertIn('runs-on: windows-11-arm',text)
        self.assertIn('timeout-minutes: 20',text)
        self.assertLess(text.index("origin='first-user-step'"),text.index('actions/checkout@'))
        self.assertIn('AddMinutes(15)',text)
        self.assertIn('if: always()',text)
        self.assertIn('include-hidden-files: true',text)
        self.assertIn('contents: read',text)
        self.assertIn('ref: ${{ github.sha }}',text)
        self.assertIn('actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1',text)
        self.assertIn("python-version: '3.12'",text)
        self.assertIn('architecture: arm64',text)
        self.assertIn('branches: [work/opengeul-office-native29-combined-preflight]',text)
        for production_input in ('suite/scripts/build-native-engine.ps1','suite/engine-build/stage_installed_runtime.py','suite/tests/test_installed_runtime_stage.py'):
            self.assertIn('      - '+production_input+'\n',text)
        self.assertIn("github.ref == 'refs/heads/work/opengeul-office-native29-combined-preflight'",text)
        controller=SCRIPT.read_text()
        self.assertIn("@('-m','unittest','suite.tests.test_installed_runtime_stage','-v')",controller)
        self.assertLess(controller.index("(Join-Path $evidence 'python-version')"),controller.index("(Join-Path $evidence 'installed-runtime-stage-unit-tests')"))
        self.assertLess(controller.index("(Join-Path $evidence 'installed-runtime-stage-unit-tests')"),controller.index("$receipt.stage='minimal-cygwin'"))
        self.assertNotIn('contents: write',text)
        self.assertNotIn('build-native-engine.ps1 -Phase',text)
        self.assertNotIn('cancel-in-progress: true',text)


if __name__ == '__main__':
    unittest.main()
