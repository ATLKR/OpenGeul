import unittest
from suite.tests.test_calc_matrix_workflow import workflow_steps,field,run_code
from suite.tests.test_navigation_diagnostic_workflow import condition
from suite.tests.test_com_wait_workflow import evaluate

class ReaderConsoleWorkflowTests(unittest.TestCase):
    def test_one_arm_probe_requires_unit_source_build_and_original_privacy(self):
        steps={field(s,'id'):s for s in workflow_steps() if field(s,'id')}
        self.assertIn('reader-console-diagnostic',steps)
        stage=steps['reader-console-diagnostic'];gates=('suite-unit-shell','sal-offset-admission','source-engine','build','native31-privacy-prepare')
        for arch in ('x64','arm64'):
            for failed in (None,*gates):
                outcomes={g:'failure' if g==failed else 'success' for g in gates}
                exp=condition(stage).replace('!cancelled()','True')
                self.assertEqual(evaluate(exp,'reader-console-diagnostic',arch,outcomes),arch=='arm64' and failed is None)
        self.assertEqual(run_code(stage).count('reader_console_diagnostic.py'),1)
        self.assertIn('./suite/scripts/prepare-native31.ps1',run_code(steps['native31-privacy-prepare']))
    def test_only_receipt_uploaded_and_normal_acceptance_gates_remain_required(self):
        steps={field(s,'id'):s for s in workflow_steps() if field(s,'id')}
        self.assertIn('reader-console-evidence',steps)
        upload=steps['reader-console-evidence'];self.assertIn('path: .work/suite-reader-console/receipt.json',upload)
        self.assertNotIn('path: .work/suite-reader-console/',upload.replace('path: .work/suite-reader-console/receipt.json',''))
        self.assertIn('always()',condition(upload));self.assertIn('throw ',run_code(steps['reader-console-not-acceptance']))
        for mode in ('acceptance','ime-mode-diagnostic','focus-diagnostic','navigation-diagnostic'):
            for name in ('readiness','fixtures'):
                exp=condition(steps[name]).replace('!cancelled()','True')
                self.assertTrue(evaluate(exp,mode,'arm64',{'build':'success'}))
                self.assertFalse(evaluate(exp,'reader-console-diagnostic','arm64',{'build':'success'}))
    def test_probe_build_requires_exact_admission_and_privacy_never_skips(self):
        from itertools import product
        steps={field(s,'id'):s for s in workflow_steps() if field(s,'id')}
        for arch in ('x64','arm64'):
            for values in product(('success','failure','skipped'),repeat=3):
                outcomes=dict(zip(('suite-unit-shell','sal-offset-admission','source-engine'),values))
                self.assertEqual(evaluate(condition(steps['build']),'reader-console-diagnostic',arch,outcomes),arch=='arm64' and all(v=='success' for v in values))
        privacy=condition(steps['native31-privacy-prepare']).replace('!cancelled()','True').replace("github.ref == 'refs/heads/work/opengeul-office-arm64'",'True')
        for mode in ('acceptance','ime-mode-diagnostic','reader-console-diagnostic'):
            for ready in ('success','failure','skipped'):
                self.assertEqual(evaluate(privacy,mode,'arm64',{'build':'success','readiness':ready,'sal-offset-admission':'success'}),ready=='success' or mode=='reader-console-diagnostic')

    def test_console_mode_installs_privacy_dependency_before_guard(self):
        steps={field(s,'id'):s for s in workflow_steps() if field(s,'id')}
        code=run_code(steps['native31-privacy-prepare'])
        self.assertIn("if ($env:OPENGEUL_SUITE_RUN_MODE -ceq 'reader-console-diagnostic')",code)
        self.assertIn('python -m pip install pywinauto==0.6.9',code)
        self.assertLess(code.index('python -m pip install pywinauto==0.6.9'),code.index('./suite/scripts/prepare-native31.ps1'))
        self.assertIn("if ($LASTEXITCODE -ne 0) { throw 'Native UI test prerequisites failed.' }",code)
        self.assertEqual(field(steps['native31-privacy-prepare'],'timeout-minutes'),'3')
