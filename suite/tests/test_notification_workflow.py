"""Caller diagnosis keeps first-attempt source and matched-symbol admission."""
import unittest
from suite.tests.test_calc_matrix_workflow import workflow_steps,field,run_code
from suite.tests.test_navigation_diagnostic_workflow import condition
from suite.tests.test_com_wait_workflow import evaluate


COMPARTMENT_STEPS = ('ime-mode-diagnostic', 'ime-notification-resolution',
                     'ime-mode-diagnostic-evidence', 'ime-mode-not-acceptance')


def sequenced_prefix_steps(steps):
    """The original document operations before the first normal Writer case."""
    by_id = {field(s, 'id'): s for s in steps if field(s, 'id')}
    result = []
    for name in ('calc-save', 'calc-close'):
        original = by_id[name]
        result.extend((original, steps[steps.index(original) + 1]))
    result.extend(by_id[name] for name in ('office-features', 'home-fixtures', 'home-routes'))
    result.append(next(s for s in steps if 'suite/e2e/pdf_export_smoke.py --produce' in s))
    return result


class NotificationWorkflowTests(unittest.TestCase):
    def selected(self, candidate, mode, architecture, *, outcomes=None, success=True, cancelled=False):
        defaults = {field(s, 'id'): 'success' for s in workflow_steps() if field(s, 'id')}
        expression = condition(candidate).replace('!cancelled()', repr(not cancelled))
        expression = expression.replace('always()', 'True').replace('success()', repr(success))
        return evaluate(expression, mode, architecture, defaults | (outcomes or {}))

    def test_one_writer_callback_follows_original_prefix_before_normal_ime(self):
        steps = workflow_steps()
        by_id = {field(s, 'id'): s for s in steps if field(s, 'id')}
        normal = next(s for s in steps if '--output .work/suite-korean-ime\n' in s)
        ordered = [by_id[name] for name in ('native31-privacy-prepare', 'fixtures')]
        ordered += sequenced_prefix_steps(steps)
        ordered += [by_id[name] for name in COMPARTMENT_STEPS] + [normal]
        positions = [steps.index(s) for s in ordered]
        self.assertEqual(positions, sorted(positions), 'Writer diagnosis must follow the original document prefix')
        first = steps.index(by_id[COMPARTMENT_STEPS[0]])
        self.assertEqual([field(s, 'id') for s in steps[first:first + 4]], list(COMPARTMENT_STEPS))
        self.assertEqual(steps[first + 4], normal)
        self.assertEqual(sum('--diagnose-ime-mode writer' in s for s in steps), 1)

    def test_prefix_keeps_original_dependencies_after_earlier_failures_only_on_arm_diagnostic(self):
        steps = workflow_steps()
        prefix = sequenced_prefix_steps(steps)
        dependencies = [('fixtures',)] * 4 + [('build',)] * 2 + [('office-features', 'home-fixtures'), ('build',)]
        modes = ('acceptance', 'ime-mode-diagnostic', 'focus-diagnostic', 'navigation-diagnostic',
                 'calc-dispatch-diagnostic', 'matched-plugin-caller', 'reader-console-diagnostic',
                 'sal-offset-mapping', 'com-wait-diagnostic', 'mutex-function-mapping', 'unknown', '')
        for architecture in ('x64', 'arm64'):
            for mode in modes:
                expected = mode == 'acceptance' or mode == 'ime-mode-diagnostic' and architecture == 'arm64'
                for candidate, required in zip(prefix, dependencies):
                    for failed in (None, *required):
                        outcomes = {'calc-save': 'failure', 'calc-close': 'failure'}
                        if failed is not None:
                            outcomes[failed] = 'failure'
                        with self.subTest(mode=mode, architecture=architecture, step=candidate.splitlines()[0], failed=failed):
                            self.assertEqual(self.selected(candidate, mode, architecture, outcomes=outcomes,
                                                           success=False), expected and failed is None)
                            self.assertFalse(self.selected(candidate, mode, architecture, cancelled=True))
        probe = next(s for s in steps if field(s, 'id') == 'ime-mode-diagnostic')
        self.assertTrue(self.selected(probe, 'ime-mode-diagnostic', 'arm64', success=False,
                                      outcomes={'calc-save': 'failure', 'calc-close': 'failure'}))

    def test_sequenced_diagnostic_cannot_select_normal_suffix_or_raw_artifacts(self):
        steps = workflow_steps()
        allowed = sequenced_prefix_steps(steps)
        allowed += [s for s in steps if field(s, 'id') in COMPARTMENT_STEPS]
        start = steps.index(next(s for s in steps if field(s, 'id') == 'calc-save'))
        for candidate in steps[start:]:
            for architecture in ('x64', 'arm64'):
                expected = (candidate in allowed and architecture == 'arm64'
                            or field(candidate, 'id') == 'ime-mode-not-acceptance')
                with self.subTest(step=candidate.splitlines()[0], architecture=architecture):
                    self.assertEqual(self.selected(candidate, 'ime-mode-diagnostic', architecture), expected)
                    if 'uses: actions/upload-artifact@' in candidate and expected:
                        self.assertEqual(field(candidate, 'id'), 'ime-mode-diagnostic-evidence')

    def test_mode_build_and_symbols_require_original_admission(self):
        steps={field(s,'id'):s for s in workflow_steps() if field(s,'id')}
        self.assertTrue(evaluate(condition(steps['sal-offset-admission']),'ime-mode-diagnostic','arm64',{}))
        for architecture in ('x64','arm64'):
            for admission in ('success','failure','skipped'):
                for qualified in ('success','failure','skipped'):
                    outcomes={'sal-offset-admission':admission,'matched-symbol-qualification':qualified}
                    expected=admission=='success' and architecture=='arm64' and qualified=='success'
                    self.assertEqual(evaluate(condition(steps['build']),'ime-mode-diagnostic',architecture,outcomes),expected)
                    self.assertEqual(evaluate(condition(steps['source-engine']),'ime-mode-diagnostic',architecture,outcomes),architecture=='arm64' and admission=='success')
                    for gate in ('build','readiness','native31-privacy-prepare','fixtures'):
                        for status in ('success','failure','skipped'):
                            native={name:'success' for name in ('build','readiness','native31-privacy-prepare','fixtures')}
                            native.update(outcomes);native[gate]=status
                            expression=condition(steps['ime-mode-diagnostic']).replace('!cancelled()','True')
                            allowed=status=='success' and architecture=='arm64' and qualified=='success'
                            self.assertEqual(evaluate(expression,'ime-mode-diagnostic',architecture,native),allowed)

    def test_original_controller_resolves_once_and_workflow_only_verifies_numeric_receipt(self):
        steps={field(s,'id'):s for s in workflow_steps() if field(s,'id')}
        self.assertIn('ime-notification-resolution',steps,'bounded notification resolution missing')
        diagnostic=run_code(steps['ime-mode-diagnostic'])
        self.assertIn('--capture-ime-compartment',diagnostic);self.assertIn('--diagnose-ime-mode writer',diagnostic);self.assertIn('--matched-plugin-proof',diagnostic)
        resolver=steps['ime-notification-resolution']
        self.assertIn('!cancelled()',condition(resolver));self.assertIn("steps.ime-mode-diagnostic.outcome != 'skipped'",condition(resolver))
        self.assertIn("steps.matched-symbol-qualification.outcome == 'success'",condition(resolver))
        self.assertIn('ime_compartment_report.py --verify .work/suite-ime-mode-diagnostic/callback-numeric.json',run_code(resolver))
        self.assertNotIn('matched_plugin_diagnostic.py',run_code(resolver))
        self.assertIn("OPENGEUL_SUITE_IME_COMPARTMENT_NOTICE: '1'",steps['ime-mode-diagnostic'])
        self.assertIn("OPENGEUL_SUITE_NOTICE_SCOPE: '3'",steps['ime-mode-diagnostic'])
        artifact=steps['ime-mode-diagnostic-evidence']
        self.assertIn('path: .work/suite-ime-mode-diagnostic/callback-numeric.json',artifact)
        self.assertNotIn('path: |',artifact)
        for forbidden in ('qualification.json','plugin-symbol-download.json','artifact-server-metadata.json','include-hidden-files'):
            self.assertNotIn(forbidden,artifact)
        self.assertIn('always()',condition(steps['ime-mode-not-acceptance']))
        self.assertIn('throw ',run_code(steps['ime-mode-not-acceptance']))

    def test_compartment_mode_excludes_raw_prerequisite_artifact_uploads(self):
        names=('한국어 입력 환경의 준비·실패 기록 즉시 보존','Suite native31 setup and control originals',
               'Preserve bounded diagnostic prerequisite failure summary')
        for name in names:
            step=next(s for s in workflow_steps() if name in s.splitlines()[0])
            self.assertIn("env.OPENGEUL_SUITE_RUN_MODE != 'ime-mode-diagnostic'",condition(step))
