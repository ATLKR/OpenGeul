"""Native symbol support is qualified before the single ARM64 GUI experiment."""
import unittest
from suite.tests.test_calc_matrix_workflow import workflow_steps,field,run_code,WORKFLOW
from suite.tests.test_navigation_diagnostic_workflow import condition

class MatchedWorkflowTests(unittest.TestCase):
    def test_matched_build_requires_arm64_and_successful_qualification(self):
        from suite.tests.test_com_wait_workflow import evaluate
        steps={field(s,'id'):s for s in workflow_steps() if field(s,'id')}
        for architecture in ('x64','arm64'):
            for outcome in ('success','failure','skipped'):
                self.assertEqual(evaluate(condition(steps['build']),'matched-plugin-caller',architecture,
                    {'matched-symbol-qualification':outcome}),architecture=='arm64' and outcome=='success')
                self.assertEqual(evaluate(condition(steps['source-engine']),'matched-plugin-caller',architecture,
                    {'sal-offset-admission':outcome}),architecture=='arm64' and outcome=='success')

    def test_qualification_precedes_arm_only_build_and_retains_first_attempt_admission(self):
        steps=workflow_steps();byid={field(s,'id'):s for s in steps if field(s,'id')}
        self.assertIn('matched-symbol-qualification',byid)
        qual=byid['matched-symbol-qualification'];build=byid['build'];focus=byid['matched-plugin-focus']
        self.assertLess(steps.index(qual),steps.index(build));self.assertIn("matrix.architecture == 'arm64'",condition(qual))
        self.assertIn("steps.sal-offset-admission.outcome == 'success'",condition(qual))
        self.assertIn("steps.matched-symbol-qualification.outcome == 'success'",condition(build))
        self.assertIn("matrix.architecture == 'arm64'",condition(build))
        for gate in ('build','readiness','native31-privacy-prepare','fixtures','matched-symbol-qualification'):
            self.assertIn('steps.'+gate+".outcome == 'success'",condition(focus))
        self.assertIn('--matched-plugin-proof',run_code(focus))
        resolve=byid['matched-plugin-resolution'];self.assertIn('!cancelled()',condition(resolve))
        self.assertIn("steps.matched-plugin-focus.outcome != 'skipped'",condition(resolve))
        self.assertIn('--mode resolve',run_code(resolve))
        terminal=byid['matched-plugin-not-acceptance'];self.assertIn('always()',condition(terminal));self.assertIn('throw ',run_code(terminal))
        self.assertIsNone(condition(byid['suite-unit-shell']))

if __name__=='__main__':unittest.main()
