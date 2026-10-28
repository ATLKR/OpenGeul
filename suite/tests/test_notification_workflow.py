"""Caller diagnosis keeps first-attempt source and matched-symbol admission."""
import unittest
from suite.tests.test_calc_matrix_workflow import workflow_steps,field,run_code
from suite.tests.test_navigation_diagnostic_workflow import condition
from suite.tests.test_com_wait_workflow import evaluate

class NotificationWorkflowTests(unittest.TestCase):
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
