"""Diagnostic workflow routing preserves baseline gates and uploads only selected JSON."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from suite import payload
from suite.tests import test_calc_dispatch_integration as integration
from suite.tests.test_calc_matrix_workflow import WORKFLOW, field, run_code, workflow_steps
from suite.tests.test_com_wait_workflow import evaluate
from suite.tests.test_navigation_diagnostic_workflow import condition


MODE = 'calc-dispatch-diagnostic'
MODES = ('acceptance', 'navigation-diagnostic', 'ime-mode-diagnostic', 'focus-diagnostic',
         'sal-offset-mapping', 'com-wait-diagnostic', 'mutex-function-mapping',
         'matched-plugin-caller', 'reader-console-diagnostic', MODE, 'unknown', '')
GATES = ('suite-unit-shell', 'sal-offset-admission', 'source-engine', 'build',
         'readiness', 'native31-privacy-prepare', 'fixtures')
ROOT = Path(__file__).resolve().parents[2]


def steps_by_id():
    return {field(step, 'id'): step for step in workflow_steps() if field(step, 'id')}


def selected(step, mode, architecture, outcomes, cancelled=False):
    expression = (condition(step) or 'success()').replace('!cancelled()', repr(not cancelled))
    expression = expression.replace('always()', 'True').replace('success()', 'True')
    expression = expression.replace('github.ref', repr('refs/heads/work/opengeul-office-arm64'))
    return evaluate(expression, mode, architecture, outcomes)


class CalcDispatchWorkflowTests(unittest.TestCase):
    def test_original_gates_are_all_required_before_fetch_stage_and_one_calc_case(self):
        steps = steps_by_id()
        self.assertIn('calc-dispatch-inputs', steps.keys(), 'Locked Calc dispatch workflow route is missing')
        self.assertIn('calc-dispatch-diagnostic', steps.keys())
        outcomes = {name: 'success' for name in steps}
        for architecture in ('x64', 'arm64'):
            for stage, gates in (('calc-dispatch-inputs', GATES),
                                 ('calc-dispatch-diagnostic', (*GATES, 'calc-dispatch-inputs'))):
                for failed in (None, *gates):
                    for status in ('failure', 'skipped'):
                        actual = outcomes | ({failed: status} if failed else {})
                        with self.subTest(stage=stage, architecture=architecture, failed=failed, status=status):
                            self.assertEqual(selected(steps[stage], MODE, architecture, actual),
                                             architecture == 'arm64' and failed is None)
                self.assertFalse(selected(steps[stage], MODE, architecture, outcomes, cancelled=True))
            for mode in MODES:
                if mode != MODE:
                    for name in ('calc-dispatch-inputs', 'calc-dispatch-diagnostic', 'calc-dispatch-evidence', 'calc-dispatch-not-acceptance'):
                        self.assertFalse(selected(steps[name], mode, architecture, outcomes))
        for architecture in ('x64', 'arm64'):
            for failed in (None, 'suite-unit-shell', 'sal-offset-admission', 'source-engine'):
                actual = outcomes | ({failed: 'failure'} if failed else {})
                self.assertEqual(selected(steps['build'], MODE, architecture, actual),
                                 architecture == 'arm64' and failed is None)
                self.assertEqual(selected(steps['source-engine'], MODE, architecture, actual),
                                 architecture == 'arm64' and failed not in ('suite-unit-shell', 'sal-offset-admission'))
        self.assertTrue(selected(steps['sal-offset-admission'], MODE, 'arm64', outcomes))
        self.assertIn("Assert-Native31Context '${{ matrix.architecture }}'", run_code(steps['sal-offset-admission']))
        self.assertRegex(WORKFLOW.read_text(encoding='utf-8'), r'(?m)^  OPENGEUL_SUITE_RUN_MODE: (?:acceptance|calc-dispatch-diagnostic)$')
        self.assertNotIn('SUITE_PACKAGE=', run_code(steps['calc-dispatch-inputs']))

    def test_every_upload_in_calc_mode_is_limited_to_the_selected_numeric_artifact(self):
        steps = steps_by_id()
        self.assertIn('calc-dispatch-evidence', steps.keys())
        uploads = [step for step in workflow_steps() if 'uses: actions/upload-artifact@' in step]
        scenarios = [{name: status for name in steps} for status in ('success', 'failure', 'skipped', 'cancelled')]
        scenarios += [{name: ('failure' if name == failed else 'success') for name in steps} for failed in steps]
        for mode in MODES:
            for architecture in ('x64', 'arm64'):
                for outcomes in scenarios:
                    for cancelled in (False, True):
                        active = [field(step, 'id') or step.splitlines()[0] for step in uploads
                                  if selected(step, mode, architecture, outcomes, cancelled)]
                        if mode == MODE:
                            expected = ['calc-dispatch-evidence'] if architecture == 'arm64' and outcomes['calc-dispatch-inputs'] != 'skipped' else []
                            self.assertEqual(active, expected)
                        else:
                            self.assertNotIn('calc-dispatch-evidence', active)

    def test_evidence_has_five_exact_json_paths_and_terminal_rejects_delivery(self):
        steps = steps_by_id()
        self.assertIn('calc-dispatch-evidence', steps.keys())
        upload = steps['calc-dispatch-evidence']
        match = re.search(r'^        path: \|\n((?:          .*\n)+)', upload, re.M)
        self.assertIsNotNone(match)
        self.assertEqual([line.strip() for line in match.group(1).splitlines()], [
            '.work/suite-calc-dispatch/results.json',
            '.work/suite-calc-dispatch/calc-dispatch-diagnostic.json',
            '.work/suite-calc-dispatch-input/artifact-server-metadata.json',
            '.work/suite-calc-dispatch-input/calc-dispatch-download.json',
            '.work/suite-calc-dispatch-package/calc-dispatch-diagnostic.json'])
        self.assertIn('include-hidden-files: true', upload)
        self.assertIn('always()', condition(upload))
        self.assertIn('package delivery is prohibited', run_code(steps['calc-dispatch-not-acceptance']))
        self.assertIn('always()', condition(steps['calc-dispatch-not-acceptance']))
        for architecture in ('x64', 'arm64'):
            self.assertFalse(selected(workflow_steps()[-1], MODE, architecture, {name: 'success' for name in steps}))


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required for the real workflow command boundary')
class CalcDispatchWorkflowBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = integration.ArtifactTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.checkout = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve(strict=True) / '검증 checkout'
        scripts = self.checkout / 'suite/scripts'; scripts.mkdir(parents=True)
        (self.checkout / '.work').mkdir()
        config = self.checkout / 'suite/config'; config.mkdir()
        shutil.copy2(ROOT / 'suite/scripts/stage-calc-dispatch.py', scripts / 'stage-calc-dispatch.py')
        # HTTP authentication and extraction have their own real-client fixture.
        # This boundary supplies its already authenticated synthetic inputs.
        (scripts / 'fetch-calc-dispatch.ps1').write_text(
            "param($DiagnosticLockPath,$Output)\n"
            "if ($DiagnosticLockPath -cne 'suite/config/calc-dispatch.arm64.lock.json') { throw 'Wrong diagnostic lock route.' }\n"
            "if ($env:WORKFLOW_FETCH_FAILURE -eq '1') { throw 'Synthetic fetch failed.' }\n"
            "New-Item -ItemType Directory -Path $Output -ErrorAction Stop | Out-Null\n"
            "Copy-Item -LiteralPath $env:WORKFLOW_ARCHIVE -Destination (Join-Path $Output 'OpenGeul-Office-engine-arm64-calc-dispatch.zip')\n"
            "Copy-Item -LiteralPath $env:WORKFLOW_RECEIPT -Destination (Join-Path $Output 'calc-dispatch-source-build-receipt.json')\n"
            "Copy-Item -LiteralPath $env:WORKFLOW_AUDIT -Destination (Join-Path $Output 'calc-dispatch-download.json')\n",
            encoding='utf-8')
        self.lock = dict(schemaVersion=1, kind='calc-dispatch-diagnostic-input', architecture='arm64',
                         repository='ATLKR/OpenGeul', repositoryId=1405493151, sourceCommit='b'*40,
                         runId=123, runAttempt=1, artifactId=456, artifactSha256='d'*64, artifactSize=100,
                         sourceLockSha256='c'*64, coreCommit='bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1')
        (config / 'calc-dispatch.arm64.lock.json').write_text(json.dumps(self.lock), encoding='utf-8')
        self.audit = dict(schemaVersion=1, kind='authenticated-calc-dispatch-download', passed=True,
                          **{name: self.lock[name] for name in ('sourceCommit','sourceLockSha256','coreCommit',
                             'artifactSha256','artifactSize','artifactId','runId','runAttempt')},
                          engineSha256=integration.sha(self.fixture.archive), receiptSha256=integration.sha(self.fixture.receipt))
        self.audit_file = self.checkout / 'authenticated-audit.json'
        self.env_file = self.checkout / 'github-env'; self.env_file.touch()
        self.environment = dict(os.environ, GH_TOKEN='synthetic-unused-workflow-token',
                                GITHUB_TOKEN='synthetic-unused-workflow-token',
                                SUITE_PACKAGE=str(self.fixture.f.root), GITHUB_SHA='a'*40,
                                GITHUB_ENV=str(self.env_file), PYTHONPATH=str(ROOT),
                                WORKFLOW_PYTHON=sys.executable, WORKFLOW_ARCHIVE=str(self.fixture.archive),
                                WORKFLOW_RECEIPT=str(self.fixture.receipt), WORKFLOW_AUDIT=str(self.audit_file))
        self.environment.pop('SUITE_CALC_DISPATCH_PACKAGE', None)
        self.environment.pop('OPENGEUL_SUITE_DIAGNOSTICS', None)

    def execute(self, name, *, header='', environment=None):
        step = steps_by_id().get(name)
        self.assertIsNotNone(step, 'Missing actual workflow command boundary: ' + name)
        script = self.checkout / (name + '.ps1')
        script.write_text("$ErrorActionPreference = 'Stop'\n" + header + run_code(step), encoding='utf-8')
        actual_environment = dict(environment or self.environment)
        step_env = re.search(r'^      env:\n((?:        .*\n)+)', step, re.M)
        if step_env:
            for line in step_env.group(1).splitlines():
                key, value = line.strip().split(': ', 1)
                actual_environment[key] = value.replace('${{ github.workspace }}', str(self.checkout)).replace(
                    '${{ github.token }}', 'synthetic-unused-workflow-token')
        return subprocess.run([shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(script)],
                              cwd=self.checkout, env=actual_environment,
                              capture_output=True, text=True, encoding='utf-8', timeout=30)

    def stage(self, *, changes=None, fetch_failure=False):
        self.audit_file.write_text(json.dumps(self.audit | (changes or {})), encoding='utf-8')
        return self.execute('calc-dispatch-inputs',
                            header='function python { & $env:WORKFLOW_PYTHON @args }\n',
                            environment=self.environment | {'WORKFLOW_FETCH_FAILURE': str(int(fetch_failure))})

    def baseline_bytes(self):
        return {path.relative_to(self.fixture.f.root).as_posix(): path.read_bytes()
                for path in self.fixture.f.root.rglob('*') if path.is_file()}

    def test_actual_block_stages_producer_b_on_consumer_a_and_preserves_baseline(self):
        before = self.baseline_bytes()
        process = self.stage()
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        published = dict(line.split('=', 1) for line in self.env_file.read_text(encoding='utf-8-sig').splitlines())
        self.assertEqual(set(published), {'SUITE_CALC_DISPATCH_PACKAGE'})
        package = Path(published['SUITE_CALC_DISPATCH_PACKAGE'])
        self.assertEqual(package, self.checkout / '.work/suite-calc-dispatch-package')
        inventory = json.loads((package / payload.INVENTORY).read_text())
        overlay = integration.ime.require_calc_dispatch_suite(package, inventory, expected_engine_source_commit='b'*40)
        self.assertEqual(overlay['engineSourceCommit'], 'b'*40)
        self.assertEqual(overlay['admittedSuiteSourceCommit'], 'a'*40)
        self.assertEqual(overlay['inputs']['archiveSha256'], self.audit['engineSha256'])
        self.assertEqual(overlay['inputs']['receiptSha256'], self.audit['receiptSha256'])
        self.assertEqual(self.baseline_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'Diagnostic engine cannot qualify'):
            payload.verify_payload(package, inventory)

    def test_actual_block_rejects_failed_download_receipt_without_publishing_package(self):
        before = self.baseline_bytes()
        process = self.stage(changes={'passed': False})
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(self.env_file.read_text(), '')
        self.assertEqual(self.baseline_bytes(), before)

    def test_actual_block_rejects_changed_inner_digest_without_publishing_package(self):
        process = self.stage(changes={'engineSha256': 'f'*64})
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(self.env_file.read_text(), '')

    def test_actual_block_stops_after_fetch_failure(self):
        process = self.stage(fetch_failure=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(self.env_file.read_text(), '')

    def test_actual_run_block_invokes_the_one_calc_cli_and_propagates_failure(self):
        header = ("function python {\n"
                  "  [IO.File]::AppendAllText($env:WORKFLOW_CLI_LOG, (ConvertTo-Json -InputObject @($args) -Compress) + \"`n\")\n"
                  "  $global:LASTEXITCODE = [int]$env:WORKFLOW_CLI_EXIT\n}\n")
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code):
                log = self.checkout / ('cli-' + str(exit_code) + '.jsonl')
                package = self.checkout / '.work/suite-calc-dispatch-package'
                environment = self.environment | {'SUITE_CALC_DISPATCH_PACKAGE': str(package),
                              'WORKFLOW_CLI_LOG': str(log), 'WORKFLOW_CLI_EXIT': str(exit_code)}
                process = self.execute('calc-dispatch-diagnostic', header=header, environment=environment)
                self.assertEqual(process.returncode == 0, exit_code == 0, process.stdout + process.stderr)
                calls = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertEqual(calls, [['suite/e2e/korean_ime_smoke.py', '--suite', str(package),
                    '--fixtures', '.work/suite-engine/fixtures', '--readiness', '.work/suite-korean-readiness/readiness.json',
                    '--output', '.work/suite-calc-dispatch', '--diagnose-calc-dispatch',
                    '--expected-engine-source-commit', 'b'*40]])

    def test_actual_run_step_binds_the_owned_worker_diagnostics_environment(self):
        expected = self.checkout / '.work/suite-calc-dispatch-worker-diagnostics'
        header = ("if ([IO.Path]::GetFullPath($env:OPENGEUL_SUITE_DIAGNOSTICS) -cne [IO.Path]::GetFullPath($env:WORKFLOW_EXPECTED_DIAGNOSTICS)) { throw 'Owned worker diagnostics root is missing.' }\n"
                  "function python { $global:LASTEXITCODE = 0 }\n")
        process = self.execute('calc-dispatch-diagnostic', header=header,
                               environment=self.environment | {'WORKFLOW_EXPECTED_DIAGNOSTICS': str(expected)})
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)


if __name__ == '__main__':
    unittest.main()
