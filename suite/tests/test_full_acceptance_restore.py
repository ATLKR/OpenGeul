"""Fixed modes keep paired full acceptance and isolated diagnosis separate."""
import re
import unittest

from suite.tests.test_calc_matrix_workflow import WORKFLOW, workflow_steps, field, run_code
from suite.tests.test_com_wait_workflow import evaluate, step
from suite.tests.test_navigation_diagnostic_workflow import condition


class FullAcceptanceRestoreTests(unittest.TestCase):
    def setUp(self):
        self.steps = workflow_steps()
        source = WORKFLOW.read_text(encoding='utf-8')
        self.mode = re.search(r'^  OPENGEUL_SUITE_RUN_MODE: (\S+)$', source, re.M).group(1)
        self.architectures = re.findall(r'^        - architecture: (\S+)$', source, re.M)
        self.outcomes = {field(s, 'id'): 'success' for s in self.steps if field(s, 'id')}

    def selected(self, candidate, architecture, *, outcomes=None, success=True, cancelled=False, mode='acceptance'):
        expression = (condition(candidate) or 'success()').replace('!cancelled()', repr(not cancelled))
        expression = expression.replace('always()', 'True').replace('success()', repr(success))
        expression = expression.replace('github.ref', repr('refs/heads/work/opengeul-office-arm64'))
        return evaluate(expression, mode, architecture, self.outcomes | (outcomes or {}))

    def command(self, fragment):
        matches = [s for s in self.steps if field(s, 'run') == '|' and fragment in run_code(s)]
        self.assertEqual(len(matches), 1, fragment)
        return matches[0]

    def test_acceptance_mode_selects_full_gates_on_both_native_architectures(self):
        self.assertEqual(self.architectures, ['x64', 'arm64'])
        start = self.steps.index(step('calc-save'))
        gates = [step(name) for name in ('suite-unit-shell', 'build', 'readiness',
                                        'native31-privacy-prepare', 'fixtures')]
        gates += self.steps[start:]
        # Require the complete commands, so a targeted diagnostic cannot stand in
        # for the full IME, UI, document lifecycle, or either independent GUI run.
        for fragment in (
            '--output .work/suite-korean-ime\n', 'korean_ui_smoke.py --suite',
            'writer_style_smoke.py --suite', 'lifecycle_smoke.py --suite',
            '--output .work/suite-startup --attempts 40\n',
            '--output .work/suite-native\n', '--output .work/suite-native-2\n',
            'def check_all_native_archives(',
        ):
            candidate = self.command(fragment)
            self.assertIn(candidate, gates)
            self.assertNotRegex(run_code(candidate), r'--(?:diagnose-[\w-]+|verify-one|modules|probe-only)\b')
        for architecture in self.architectures:
            for gate in gates:
                with self.subTest(architecture=architecture, gate=gate.splitlines()[0]):
                    self.assertTrue(self.selected(gate, architecture))
            self.assertEqual(self.selected(step('source-engine'), architecture), architecture == 'arm64')

    def test_acceptance_mode_leaves_every_optional_diagnostic_unselected(self):
        diagnostics = (
            'sal-offset-admission', 'sal-offset-mapping', 'sal-offset-evidence', 'sal-offset-not-acceptance',
            'com-wait-diagnostic', 'com-wait-evidence', 'com-wait-not-acceptance',
            'mutex-layout-fixture', 'mutex-function-mapping', 'mutex-function-evidence', 'mutex-function-not-acceptance',
            'matched-symbol-inputs', 'matched-symbol-qualification', 'matched-plugin-focus',
            'matched-plugin-resolution', 'matched-plugin-evidence', 'matched-plugin-not-acceptance',
            'diagnostic-fixture-failure-evidence', 'reader-console-diagnostic', 'reader-console-evidence',
            'reader-console-not-acceptance', 'navigation-diagnostic', 'navigation-diagnostic-evidence',
            'diagnostic-not-acceptance', 'ime-mode-diagnostic', 'ime-notification-resolution',
            'ime-mode-diagnostic-evidence', 'ime-mode-not-acceptance', 'focus-diagnostic',
            'focus-diagnostic-evidence', 'focus-not-acceptance',
            'calc-dispatch-inputs', 'calc-dispatch-diagnostic', 'calc-dispatch-evidence',
            'calc-dispatch-not-acceptance',
        )
        for architecture in self.architectures:
            for name in diagnostics:
                with self.subTest(architecture=architecture, diagnostic=name):
                    self.assertFalse(self.selected(step(name), architecture))

    def test_configured_mode_selects_exactly_one_proven_route(self):
        self.assertIn(self.mode, ('acceptance', 'calc-dispatch-diagnostic'))
        for architecture in self.architectures:
            for name in ('calc-dispatch-inputs', 'calc-dispatch-diagnostic', 'calc-dispatch-evidence'):
                self.assertEqual(self.selected(step(name), architecture, mode=self.mode),
                                 self.mode == 'calc-dispatch-diagnostic' and architecture == 'arm64')
            self.assertEqual(self.selected(step('calc-dispatch-not-acceptance'), architecture, mode=self.mode),
                             self.mode == 'calc-dispatch-diagnostic')
            for gate in self.steps[self.steps.index(step('calc-save')):]:
                self.assertEqual(self.selected(gate, architecture, mode=self.mode), self.mode == 'acceptance')

    def test_acceptance_prerequisites_and_package_handoff_still_fail_closed(self):
        ime = self.command('--output .work/suite-korean-ime\n')
        integrity = self.command('def check_all_native_archives(')
        delivery = self.steps[-1]
        for architecture in self.architectures:
            for status in ('failure', 'skipped'):
                self.assertFalse(self.selected(step('readiness'), architecture, outcomes={'build': status}))
                for prerequisite in ('fixtures', 'readiness'):
                    self.assertFalse(self.selected(ime, architecture, outcomes={prerequisite: status}))
                for prerequisite in ('office-features', 'home-fixtures'):
                    self.assertFalse(self.selected(step('home-routes'), architecture, outcomes={prerequisite: status}))
                self.assertFalse(self.selected(delivery, architecture, outcomes={'home-routes': status}))
            self.assertFalse(self.selected(delivery, architecture, success=False))
            self.assertFalse(self.selected(ime, architecture, cancelled=True))
            self.assertTrue(self.selected(integrity, architecture, success=False))
            self.assertTrue(self.selected(self.steps[-2], architecture, success=False, cancelled=True))
