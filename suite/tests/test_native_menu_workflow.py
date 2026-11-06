"""The six native menu cases add a gate without replacing full acceptance."""
import re
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
            self.assertFalse(self.selected(upload, architecture,
                outcomes={'native-menu-ui': 'skipped'}))
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


if __name__ == '__main__':
    unittest.main()
