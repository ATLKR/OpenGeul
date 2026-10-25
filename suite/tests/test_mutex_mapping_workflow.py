"""Static attribution cannot reach Office input or package delivery."""
import unittest
from itertools import product
from suite.tests.test_com_wait_workflow import step, evaluate
from suite.tests.test_calc_matrix_workflow import workflow_steps, run_code, WORKFLOW
from suite.tests.test_navigation_diagnostic_workflow import condition

MODE = 'mutex-function-mapping'
MODES = ('acceptance', 'navigation-diagnostic', 'ime-mode-diagnostic',
         'focus-diagnostic', 'sal-offset-mapping', 'com-wait-diagnostic', MODE, 'unknown', '')


class MutexMappingWorkflowTests(unittest.TestCase):
    def test_compile_and_mapping_require_native_source_admission(self):
        self.assertIn('OPENGEUL_SUITE_RUN_MODE: reader-console-diagnostic', WORKFLOW.read_text())
        compile_step=step('mutex-layout-fixture'); mapping=step('mutex-function-mapping')
        for arch in ('x64','arm64'):
            for mode in MODES:
                for results in product(('success','failure','skipped'), repeat=4):
                    outcomes=dict(zip(('suite-unit-shell','sal-offset-admission',
                                       'source-engine','mutex-layout-fixture'),results))
                    admitted=arch=='arm64' and mode==MODE
                    self.assertEqual(evaluate(condition(compile_step),mode,arch,outcomes),
                                     admitted and all(x=='success' for x in results[:3]))
                    self.assertEqual(evaluate(condition(mapping),mode,arch,outcomes),
                                     admitted and all(x=='success' for x in results))
        self.assertLess(workflow_steps().index(step('sal-offset-admission')),workflow_steps().index(compile_step))
        self.assertLess(workflow_steps().index(compile_step),workflow_steps().index(mapping))
        self.assertIn('--fixture .work/suite-mutex-layout-fixture/mutex-layout-fixture.dll',run_code(mapping))
        self.assertIn('--inspect-calls',run_code(mapping))

    def test_static_mode_cannot_build_or_enter_office(self):
        self.assertFalse(evaluate(condition(step('build')),MODE))
        for name in ('readiness','native31-privacy-prepare','fixtures'):
            self.assertIn("steps.build.outcome == 'success'",condition(step(name)))
        self.assertIn("env.OPENGEUL_SUITE_RUN_MODE == 'acceptance'",condition(workflow_steps()[-1]))
        for arch in ('x64','arm64'):
            for result in ('success','failure','skipped'):
                self.assertEqual(evaluate(condition(step('source-engine')),MODE,arch,
                    {'sal-offset-admission':result}),arch=='arm64' and result=='success')

    def test_upload_is_only_receipts_and_always_nonacceptance(self):
        upload=step('mutex-function-evidence'); end=step('mutex-function-not-acceptance')
        self.assertIn('always()',condition(upload))
        self.assertIn('path: |',upload)
        self.assertIn('.work/suite-mutex-function-mapping/receipt.json',upload)
        self.assertIn('.work/suite-mutex-layout-fixture/receipt.json',upload)
        self.assertNotIn('*.dll',upload)
        self.assertNotIn('**',upload)
        self.assertEqual(condition(end),"always() && env.OPENGEUL_SUITE_RUN_MODE == 'mutex-function-mapping'")
        self.assertIn('package delivery is prohibited',run_code(end))
        self.assertLess(workflow_steps().index(upload),workflow_steps().index(end))
        self.assertLess(workflow_steps().index(end),workflow_steps().index(step('build')))
