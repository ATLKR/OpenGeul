"""Targeted navigation evidence cannot qualify or deliver a Suite package."""
import unittest
from suite.tests.test_calc_matrix_workflow import WORKFLOW, workflow_steps, field, run_code

MODE = "env.OPENGEUL_SUITE_RUN_MODE == 'acceptance'"
DIAGNOSTIC = "env.OPENGEUL_SUITE_RUN_MODE == 'navigation-diagnostic'"

def condition(step):
    value=field(step,'if')
    if value and value.startswith("'"):return value[1:-1].replace("''", "'")
    if value and value.startswith('"'):return value[1:-1]
    return value

class NavigationDiagnosticWorkflowTests(unittest.TestCase):
    def test_fixed_mode_and_validation_reject_unknown_values(self):
        self.assertIn("OPENGEUL_SUITE_RUN_MODE: sal-offset-mapping",WORKFLOW.read_text())
        step=next(s for s in workflow_steps() if field(s,'id')=='run-mode')
        code=run_code(step)
        self.assertIn("-cnotin @('acceptance', 'navigation-diagnostic', 'ime-mode-diagnostic', 'focus-diagnostic', 'sal-offset-mapping')",code)
        self.assertIn("throw 'Unknown Suite run mode.'",code)

    def test_diagnostic_requires_every_original_prerequisite(self):
        steps=workflow_steps();step=next(s for s in steps if field(s,'id')=='navigation-diagnostic')
        value=condition(step)
        self.assertEqual(value, "!cancelled() && "+DIAGNOSTIC+" && steps.build.outcome == 'success' && steps.readiness.outcome == 'success' && steps.native31-privacy-prepare.outcome == 'success' && steps.fixtures.outcome == 'success'")
        prerequisites=('build','readiness','native31-privacy-prepare','fixtures')
        for mode in ('acceptance','navigation-diagnostic','ime-mode-diagnostic','focus-diagnostic','sal-offset-mapping','unknown',''):
            for failed in (None,*prerequisites):
                expression=value.replace('!cancelled()','True').replace('env.OPENGEUL_SUITE_RUN_MODE',repr(mode)).replace('&&','and')
                for prerequisite in prerequisites:
                    expression=expression.replace('steps.'+prerequisite+'.outcome',repr('skipped' if failed==prerequisite else 'success'))
                self.assertEqual(eval(expression,{'__builtins__':{}}),mode=='navigation-diagnostic' and failed is None)
        code=run_code(step)
        self.assertIn('python suite/e2e/korean_ime_smoke.py --suite $env:SUITE_PACKAGE --fixtures .work/suite-engine/fixtures --readiness .work/suite-korean-readiness/readiness.json --output .work/suite-navigation-diagnostic --diagnose-navigation impress',code)
        self.assertIn('if ($LASTEXITCODE -ne 0)',code)
        self.assertLess(next(i for i,s in enumerate(steps) if field(s,'id')=='fixtures'),steps.index(step))

    def test_all_acceptance_steps_keep_original_conditions_and_require_acceptance(self):
        steps=workflow_steps();start=next(i for i,s in enumerate(steps) if field(s,'id')=='calc-save')
        originals={"!cancelled() && steps.fixtures.outcome == 'success'",
            "!cancelled() && steps.build.outcome == 'success'",
            "!cancelled() && steps.office-features.outcome == 'success' && steps.home-fixtures.outcome == 'success'",
            "!cancelled() && steps.fixtures.outcome == 'success' && steps.readiness.outcome == 'success'",
            'always()',"success() && steps.home-routes.outcome == 'success'"}
        for step in steps[start:]:
            with self.subTest(step=step.splitlines()[0]):
                value=condition(step)
                self.assertTrue(value.startswith(MODE+' && ('),value)
                self.assertTrue(value.endswith(')'),value)
                self.assertIn(value[len(MODE+' && ('):-1],originals)
        delivery=condition(steps[-1])
        for mode in ('acceptance','navigation-diagnostic','ime-mode-diagnostic','focus-diagnostic','sal-offset-mapping','unknown',''):
            for success in (True,False):
                for home in ('success','failure','skipped'):
                    expression=delivery.replace('env.OPENGEUL_SUITE_RUN_MODE',repr(mode)).replace('success()',str(success)).replace('steps.home-routes.outcome',repr(home)).replace('&&','and')
                    self.assertEqual(eval(expression,{'__builtins__':{}}),mode=='acceptance' and success and home=='success')

    def test_evidence_is_separate_and_diagnostic_terminal_is_deliberate_failure(self):
        steps=workflow_steps()
        upload=next(s for s in steps if field(s,'id')=='navigation-diagnostic-evidence')
        terminal=next(s for s in steps if field(s,'id')=='diagnostic-not-acceptance')
        self.assertEqual(condition(upload),'always() && '+DIAGNOSTIC)
        self.assertIn('path: .work/suite-navigation-diagnostic/',upload)
        self.assertIn('opengeul-suite-navigation-diagnostic-${{ matrix.architecture }}-${{ github.run_id }}-${{ github.run_attempt }}',upload)
        self.assertEqual(condition(terminal),'always() && '+DIAGNOSTIC)
        self.assertIn("throw 'Navigation diagnostic only: full Suite acceptance was not run; package delivery is prohibited.'",run_code(terminal))
        self.assertLess(steps.index(upload),steps.index(terminal))
        self.assertIn(MODE,condition(steps[-1]))

    def test_scoped_experiments_keep_prerequisites_and_cannot_qualify(self):
        steps=workflow_steps()
        for name,flag,title in (('ime-mode','ime-mode','IME mode'),('focus','focus','Focus')):
            with self.subTest(experiment=name):
                step=next(s for s in steps if field(s,'id')==name+'-diagnostic')
                mode="env.OPENGEUL_SUITE_RUN_MODE == '"+name+"-diagnostic'"
                prerequisites=('build','readiness','native31-privacy-prepare','fixtures')
                expected="!cancelled() && "+mode+"".join(" && steps."+p+".outcome == 'success'" for p in prerequisites)
                self.assertEqual(condition(step),expected)
                for run_mode in ('acceptance','navigation-diagnostic','ime-mode-diagnostic','focus-diagnostic','sal-offset-mapping','unknown',''):
                    for failed in (None,*prerequisites):
                        expression=condition(step).replace('!cancelled()','True').replace('env.OPENGEUL_SUITE_RUN_MODE',repr(run_mode)).replace('&&','and')
                        for p in prerequisites:
                            expression=expression.replace('steps.'+p+'.outcome',repr('failure' if failed==p else 'success'))
                        self.assertEqual(eval(expression,{'__builtins__':{}}),run_mode==name+'-diagnostic' and failed is None)
                self.assertIn('--output .work/suite-'+name+'-diagnostic --diagnose-'+flag+' calc',run_code(step))
                self.assertIn('if ($LASTEXITCODE -ne 0)',run_code(step))
                upload=next(s for s in steps if field(s,'id')==name+'-diagnostic-evidence')
                terminal=next(s for s in steps if field(s,'id')==name+'-not-acceptance')
                self.assertEqual(condition(upload),'always() && '+mode)
                self.assertEqual(condition(terminal),'always() && '+mode)
                self.assertIn('path: .work/suite-'+name+'-diagnostic/',upload)
                self.assertIn('opengeul-suite-'+name+'-diagnostic-${{ matrix.architecture }}-${{ github.run_id }}-${{ github.run_attempt }}',upload)
                self.assertIn("throw '"+title+" diagnostic only: full Suite acceptance was not run; package delivery is prohibited.'",run_code(terminal))
                self.assertLess(steps.index(step),steps.index(upload))
                self.assertLess(steps.index(upload),steps.index(terminal))

    def test_shared_preparation_is_not_conditioned_on_diagnostic_mode(self):
        for step in workflow_steps():
            if field(step,'id') in ('readiness','native31-privacy-prepare','fixtures'):
                self.assertNotIn('OPENGEUL_SUITE_RUN_MODE',condition(step) or '')
