"""The six native menu cases add a gate without replacing full acceptance."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from suite.tests.test_calc_matrix_workflow import WORKFLOW, workflow_steps, field, run_code, ROOTS
from suite.tests import test_full_acceptance_restore
from suite.tests.test_com_wait_workflow import step

PREREQUISITES = ('suite-unit-shell', 'build', 'worker-runtime', 'readiness',
                 'native31-privacy-prepare', 'fixtures')
DIAGNOSTIC_MODES = ('navigation-diagnostic', 'ime-mode-diagnostic', 'focus-diagnostic',
    'sal-offset-mapping', 'com-wait-diagnostic', 'mutex-function-mapping',
    'matched-plugin-caller', 'reader-console-diagnostic', 'calc-dispatch-diagnostic')


class NativeMenuWorkflowTests(unittest.TestCase):
    def setUp(self):
        # Reuse the actual expression evaluator used by the full acceptance
        # boundary tests; the workflow expressions are executed, not rewritten.
        self.workflow = test_full_acceptance_restore.FullAcceptanceRestoreTests()
        self.workflow.setUp()
        self.selected = self.workflow.selected

    def test_configured_mode_runs_full_acceptance_on_both_architectures(self):
        self.assertEqual(self.workflow.mode, 'acceptance')
        self.assertEqual(self.workflow.architectures, ['x64', 'arm64'])
        ui = step('native-menu-ui')
        for architecture in self.workflow.architectures:
            self.assertTrue(self.selected(ui, architecture, mode=self.workflow.mode))
            self.assertFalse(self.selected(step('ime-mode-not-acceptance'), architecture,
                                           mode=self.workflow.mode))
        code = run_code(step('suite-unit-shell'))
        self.assertIn('dotnet run --project suite/shell-tests/OpenGeul.Office.Tests.csproj -c Release', code)

    def test_menu_requires_original_prerequisites_but_not_unrelated_rc_outcomes(self):
        ui = step('native-menu-ui')
        for architecture in self.workflow.architectures:
            for prerequisite in PREREQUISITES:
                for outcome in ('failure', 'skipped', 'cancelled'):
                    with self.subTest(architecture=architecture, prerequisite=prerequisite, outcome=outcome):
                        self.assertFalse(self.selected(ui, architecture,
                            outcomes={prerequisite: outcome}, success=False))
            self.assertFalse(self.selected(ui, architecture, cancelled=True))
            for outcome in ('failure', 'skipped'):
                self.assertTrue(self.selected(ui, architecture, success=False,
                    outcomes={'calc-save': outcome, 'ime-mode-diagnostic': outcome}))
        steps = workflow_steps()
        self.assertLess(steps.index(step('fixtures')), steps.index(ui))
        self.assertLess(steps.index(ui), steps.index(step('calc-save')))

    def test_diagnostic_modes_never_run_or_relabel_the_native_menu_gate(self):
        for architecture in self.workflow.architectures:
            for mode in (*DIAGNOSTIC_MODES, 'unknown', ''):
                for name in ('native-menu-ui', 'native-menu-archive-integrity', 'native-menu-evidence'):
                    with self.subTest(architecture=architecture, mode=mode, name=name):
                        self.assertFalse(self.selected(step(name), architecture, mode=mode))

    def test_fixed_six_case_ui_uses_only_the_isolated_root_and_checks_exit(self):
        ui = step('native-menu-ui')
        code = run_code(ui)
        self.assertIn('python suite/e2e/native_menu_smoke.py --suite "$env:SUITE_PACKAGE" --fixtures .work/suite-engine/fixtures --output .work/suite-native-menu', code)
        self.assertIn('if ($LASTEXITCODE -ne 0)', code)
        self.assertIn('OPENGEUL_SUITE_DIAGNOSTICS: ${{ github.workspace }}/.work/suite-native-menu/worker-diagnostics', ui)
        self.assertNotRegex(code, r'--(?:modules|diagnose-[\w-]+|verify-one|probe-only)\b')
        self.assertIn('python suite/scripts/verify-suite.py $env:SUITE_PACKAGE', code)
        # The original five-root/83-generation gate remains independent.
        integrity = self.workflow.command('def check_all_native_archives(')
        self.assertIn("verify_native_archive_completeness(Path.cwd()", run_code(integrity))
        self.assertNotIn('.work/suite-native-menu', run_code(integrity))
        self.assertEqual(len(ROOTS), 5)

    def test_archive_integrity_remains_required_after_ui_failure_or_skip(self):
        archive = step('native-menu-archive-integrity')
        for architecture in self.workflow.architectures:
            for outcome in ('success', 'failure', 'skipped'):
                self.assertTrue(self.selected(archive, architecture, success=False,
                    outcomes={'native-menu-ui': outcome}))
            self.assertFalse(self.selected(archive, architecture, cancelled=True))
        code = run_code(archive)
        self.assertIn('python suite/e2e/native_menu_archive_completeness.py --workspace . --suite "$env:SUITE_PACKAGE" --output .work/suite-native-menu-archive-integrity.json', code)
        self.assertIn('if ($LASTEXITCODE -ne 0)', code)
        self.assertIn("'${{ steps.native-menu-ui.outcome }}' -cne 'success'", code)
        self.assertIn("throw 'Native menu UI verification did not pass.'", code)
        self.assertLess(workflow_steps().index(step('native-menu-ui')), workflow_steps().index(archive))
        # Neither a failed new menu gate nor its archive can reach delivery.
        for architecture in self.workflow.architectures:
            for gate in ('native-menu-ui', 'native-menu-archive-integrity'):
                for candidate in (step('final-zip-proof'), workflow_steps()[-1]):
                    self.assertFalse(self.selected(candidate, architecture, success=False,
                        outcomes={gate: 'failure'}))

    def test_failure_evidence_is_filtered_and_bound_to_source_run_architecture(self):
        upload = step('native-menu-evidence')
        for architecture in self.workflow.architectures:
            for outcome in ('success', 'failure'):
                self.assertTrue(self.selected(upload, architecture, success=False, cancelled=True,
                    outcomes={'native-menu-ui': outcome}))
            self.assertTrue(self.selected(upload, architecture, success=False,
                outcomes={'native-menu-ui': 'skipped', 'native-menu-archive-integrity': 'failure'}))
            self.assertFalse(self.selected(upload, architecture,
                outcomes={'native-menu-ui': 'skipped', 'native-menu-archive-integrity': 'skipped'}))
        self.assertIn('uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02', upload)
        self.assertIn('name: opengeul-suite-native-menu-${{ matrix.architecture }}-${{ github.run_id }}-${{ github.run_attempt }}', upload)
        self.assertIn('retention-days: 1', upload)
        self.assertIn('include-hidden-files: true', upload)
        self.assertIn('if-no-files-found: error', upload)
        allowed = ('.work/suite-native-menu/results.json', '.work/suite-native-menu/*-chrome.png',
            '.work/suite-native-menu/worker-diagnostics/*/manifest.json',
            '.work/suite-native-menu/worker-diagnostics/*/events.jsonl',
            '.work/suite-native-menu/worker-diagnostics/*/shutdown.json',
            '.work/suite-native-menu/worker-diagnostics/worker-save-*.jsonl',
            '.work/suite-native-menu-archive-integrity.json')
        paths = re.search(r'^        path: \|\n((?:          .*\n)+)', upload, re.M)
        self.assertIsNotNone(paths)
        self.assertEqual(tuple(line.strip() for line in paths.group(1).splitlines()), allowed)
        self.assertNotIn('continue-on-error', step('native-menu-ui') + step('native-menu-archive-integrity'))


class NativeMenuWorkflowExecutionTests(unittest.TestCase):
    """Execute the original PowerShell blocks at fake external tool boundaries."""
    def setUp(self):
        self.pwsh = shutil.which('pwsh')
        self.assertIsNotNone(self.pwsh, 'Actual PowerShell is required for workflow regression checks')
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='native-menu-workflow-')))
        self.calls = self.root / 'calls.jsonl'
        self.fake = self.root / 'fake.py'
        self.fake.write_text(
            'import json,os,pathlib,sys\n'
            'tool,args=sys.argv[1],sys.argv[2:]\n'
            'with pathlib.Path(os.environ["FAKE_CALLS"]).open("a") as out:\n'
            ' out.write(json.dumps(dict(tool=tool,args=args))+"\\n")\n'
            'if tool=="dotnet":\n'
            ' sys.exit(int(os.environ["SHELL_EXIT"]))\n'
            'if args[:2]==["-m","suite.scripts.run_unit_checks"]:\n'
            ' sys.exit(int(os.environ["UNIT_EXIT"]))\n'
            'if args and args[0]=="suite/e2e/native_menu_archive_completeness.py":\n'
            ' target=pathlib.Path(args[args.index("--output")+1]);target.parent.mkdir(exist_ok=True)\n'
            ' with target.open("x") as out:json.dump(dict(success=os.environ["ARCHIVE_EXIT"]=="0",nativeMenuExecuted=True),out)\n'
            ' sys.exit(int(os.environ["ARCHIVE_EXIT"]))\n'
            'sys.exit(int(os.environ["CAPABILITY_EXIT"]))\n', encoding='utf-8')

    def invoke(self, name, *, outcome='success', package='synthetic-package',
               unit_exit=0, shell_exit=0, archive_exit=0, capability_exit=0,
               unit_throw=False, shell_throw=False):
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"
        code = run_code(step(name))
        code = code.replace('${{ steps.native-menu-ui.outcome }}', outcome)
        code = code.replace('${{ matrix.architecture }}', 'arm64')
        self.assertNotIn('${{', code)
        environment = dict(os.environ, FAKE_CALLS=str(self.calls), UNIT_EXIT=str(unit_exit),
            SHELL_EXIT=str(shell_exit), ARCHIVE_EXIT=str(archive_exit), CAPABILITY_EXIT=str(capability_exit),
            GITHUB_SHA='a' * 40, GITHUB_RUN_ID='1234567', GITHUB_RUN_ATTEMPT='1',
            FAKE_UNIT_THROW='1' if unit_throw else '0', FAKE_SHELL_THROW='1' if shell_throw else '0')
        if package is None:
            environment.pop('SUITE_PACKAGE', None)
        else:
            environment['SUITE_PACKAGE'] = package
        script = self.root / 'case.ps1'
        wrappers = (
            "function python { if ($env:FAKE_UNIT_THROW -ceq '1' -and $args[0] -ceq '-m') { "
            "throw 'Original synthetic unit invocation failure.' }; & " + quote(sys.executable) +
            ' ' + quote(self.fake) + " 'python' @args }\n" +
            "function dotnet { if ($env:FAKE_SHELL_THROW -ceq '1') { "
            "throw 'Original synthetic shell invocation failure.' }; & " + quote(sys.executable) +
            ' ' + quote(self.fake) + " 'dotnet' @args }\n")
        script.write_text("$ErrorActionPreference='Stop'\n" + wrappers + "try {\n" + code +
            "\n} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }\n", encoding='utf-8')
        result = subprocess.run([self.pwsh, '-NoLogo', '-NoProfile', '-File', str(script)],
            cwd=self.root, env=environment, capture_output=True, text=True, timeout=20)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []
        return result, calls

    def archive_receipt(self):
        return self.root / '.work/suite-native-menu-archive-integrity.json'

    def test_skipped_ui_without_package_records_non_execution_without_python(self):
        result, calls = self.invoke('native-menu-archive-integrity', outcome='skipped', package=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [], 'Unexecuted UI must not invoke the archive CLI with an empty package')
        receipt = json.loads(self.archive_receipt().read_bytes())
        self.assertEqual(receipt, dict(schemaVersion=1, kind='native-menu-not-executed', success=False,
            acceptanceEligible=False, nativeMenuExecuted=False, prerequisiteCode=1,
            sourceCommit='a' * 40, runId=1234567, runAttempt=1, architecture='arm64'))
        self.assertIn('Native menu UI not executed: prerequisites unavailable.', result.stderr)
        self.assertNotIn('original generation or graceful shutdown archive is incomplete', result.stderr)

    def test_skipped_ui_never_overwrites_an_existing_receipt(self):
        self.archive_receipt().parent.mkdir()
        original = b'{"preserved":true}\n'
        self.archive_receipt().write_bytes(original)
        result, calls = self.invoke('native-menu-archive-integrity', outcome='skipped', package=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertEqual(self.archive_receipt().read_bytes(), original)

    def test_executed_ui_keeps_original_archive_invocation_and_failure(self):
        result, calls = self.invoke('native-menu-archive-integrity')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(calls, [dict(tool='python', args=[
            'suite/e2e/native_menu_archive_completeness.py', '--workspace', '.', '--suite',
            'synthetic-package', '--output', '.work/suite-native-menu-archive-integrity.json'])])
        self.assertTrue(json.loads(self.archive_receipt().read_bytes())['nativeMenuExecuted'])

    def test_archive_failure_after_executed_ui_remains_failure(self):
        result, calls = self.invoke('native-menu-archive-integrity', archive_exit=7)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn('original generation or graceful shutdown archive is incomplete', result.stderr)
        self.assertFalse(json.loads(self.archive_receipt().read_bytes())['success'])

    def test_failed_executed_ui_remains_failure_after_valid_archive(self):
        result, calls = self.invoke('native-menu-archive-integrity', outcome='failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn('Native menu UI verification did not pass.', result.stderr)

    def test_python_unit_failure_still_executes_one_shell_check_and_fails(self):
        result, calls = self.invoke('suite-unit-shell', unit_exit=7)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call['tool'] for call in calls], ['python', 'python', 'python', 'dotnet'])
        self.assertEqual(sum(call['tool'] == 'dotnet' for call in calls), 1)
        self.assertIn('Suite unit tests failed.', result.stderr)

    def test_python_invocation_failure_still_runs_shell_and_preserves_original_error(self):
        result, calls = self.invoke('suite-unit-shell', unit_throw=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call['tool'] for call in calls], ['python', 'python', 'dotnet'])
        self.assertIn('Original synthetic unit invocation failure.', result.stderr)

    def test_shell_invocation_failure_preserves_original_error(self):
        result, calls = self.invoke('suite-unit-shell', shell_throw=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call['tool'] for call in calls], ['python', 'python', 'python'])
        self.assertIn('Original synthetic shell invocation failure.', result.stderr)

    def test_shell_failure_after_passing_python_tests_remains_failure(self):
        result, calls = self.invoke('suite-unit-shell', shell_exit=9)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sum(call['tool'] == 'dotnet' for call in calls), 1)
        self.assertIn('Suite shell tests failed.', result.stderr)

    def test_passing_python_and_shell_checks_pass_the_original_step(self):
        result, calls = self.invoke('suite-unit-shell')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call['tool'] for call in calls], ['python', 'python', 'python', 'dotnet'])

    def test_capability_failure_still_fails_after_python_and_shell_checks(self):
        result, calls = self.invoke('suite-unit-shell', capability_exit=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sum(call['tool'] == 'dotnet' for call in calls), 1)
        self.assertIn('Suite unit capability receipts failed.', result.stderr)


if __name__ == '__main__':
    unittest.main()
