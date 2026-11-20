"""Diagnostic fixture metadata stays bounded; Calc selects only its numeric artifact."""
import ast
import json
import re
import tempfile
from pathlib import Path
from contextlib import redirect_stdout
import io
from unittest.mock import patch
import unittest
from suite.tests.test_calc_matrix_workflow import WORKFLOW,workflow_steps,field,run_code
from suite.tests.test_navigation_diagnostic_workflow import condition
from suite.tests.test_com_wait_workflow import evaluate
from suite.tests.test_engine_smoke import smoke


def configured_modes():
    steps={field(s,'id'):s for s in workflow_steps() if field(s,'id')}
    values=re.search(r'-cnotin @\(([^)]+)\)',run_code(steps['run-mode'])).group(1)
    return ast.literal_eval('('+values+',)'),steps


class DiagnosticFixtureRetentionTests(unittest.TestCase):
    def test_all_validated_modes_share_failure_only_exact_safe_artifact(self):
        modes,steps=configured_modes();stage=steps['diagnostic-fixture-failure-evidence']
        self.assertEqual(re.search(r'^        path: (.+)$',stage,re.M).group(1),'.work/suite-engine/engine-failure-summary.json')
        self.assertEqual(re.search(r'^        retention-days: (.+)$',stage,re.M).group(1),'1')
        self.assertEqual(re.search(r'^        if-no-files-found: (.+)$',stage,re.M).group(1),'error')
        expression=condition(stage).replace('always()','True')
        for mode in (*modes,'unknown',''):
            for admitted in ('success','failure','skipped'):
                for outcome in ('success','failure','cancelled','skipped'):
                    if mode not in modes and admitted=='success':continue  # Unreachable after actual validator.
                    with self.subTest(mode=mode,admitted=admitted,outcome=outcome):
                        actual=evaluate(expression,mode,outcomes={'run-mode':admitted,'fixtures':outcome})
                        self.assertEqual(actual,admitted=='success' and mode not in ('acceptance','calc-dispatch-diagnostic','ime-mode-diagnostic') and outcome=='failure')
        # Unknown modes cannot reach the successful validation outcome.
        self.assertNotIn('unknown',modes);self.assertNotIn('',modes)
        self.assertIn("throw 'Unknown Suite run mode.'",run_code(steps['run-mode']))
        self.assertEqual(sum('.work/suite-engine/engine-failure-summary.json' in s for s in workflow_steps()),1)
        for s in workflow_steps():
            if field(s,'id')=='diagnostic-fixture-failure-evidence':
                for raw in ('engine-*.json','engine-smoke.json','engine-writer.json','fixtures/'):
                    self.assertNotIn(raw,s)

    def test_actual_build_and_fixture_prerequisites_do_not_force_synthetic_modes(self):
        modes,steps=configured_modes()
        selected=re.search(r'OPENGEUL_SUITE_RUN_MODE: (\S+)',WORKFLOW.read_text()).group(1)
        self.assertIn(selected,modes)
        all_pass={name:'success' for name in ('suite-unit-shell','sal-offset-admission','source-engine','matched-symbol-qualification')}
        for mode in modes:
            for arch in ('x64','arm64'):
                built=evaluate(condition(steps['build']),mode,arch,all_pass)
                fixtures=evaluate(condition(steps['fixtures']).replace('!cancelled()','True'),mode,arch,{'build':'success' if built else 'skipped'})
                if mode in ('com-wait-diagnostic','sal-offset-mapping','mutex-function-mapping','reader-console-diagnostic'):
                    self.assertFalse(fixtures,(mode,arch))
                captured=evaluate(condition(steps['diagnostic-fixture-failure-evidence']).replace('always()','True'),mode,arch,
                    {'run-mode':'success','fixtures':'failure' if fixtures else 'skipped'})
                self.assertEqual(captured,fixtures and mode not in ('acceptance','calc-dispatch-diagnostic','ime-mode-diagnostic'))
        stage=steps['navigation-diagnostic']
        for prerequisite in ('build','readiness','native31-privacy-prepare','fixtures'):
            self.assertIn('steps.'+prerequisite+".outcome == 'success'",condition(stage))
        self.assertIn('acceptance',condition(workflow_steps()[-1]))

    def test_each_mode_and_module_serializes_only_bounded_closed_failure_metadata(self):
        modes,_=configured_modes()
        for mode in modes:
            if mode=='acceptance':continue
            for module in smoke.FILES:
                with self.subTest(mode=mode,module=module):
                    rows=[dict(module=m,status='passed') for m in smoke.FILES]
                    row=next(r for r in rows if r['module']==module)
                    row.update(status='failed',failureStage='load-factory',
                        error={'type':'TimeoutError','message':'PRIVATE-TEXT','traceback':'PRIVATE-STACK'},
                        fixture='C:/PRIVATE-PATH/file',observed={'text':'PRIVATE-CONTENT'},
                        finalizationFailures=[{'stage':'engine-cleanup','type':'OSError','message':'PRIVATE'}]*20,
                        cleanupErrors=['PRIVATE']*23,
                        engineCleanup={'gracefulQualified':False,'forcedTermination':True,'jobEmptyVerified':True,
                            'launcherExitCode':0,'image':'C:/PRIVATE-IMAGE',
                            'errors':[{'stage':'PRIVATE-STAGE','type':'PRIVATE-CLASS','message':'PRIVATE-DETAIL'}]*100})
                    summary=smoke.failure_summary(rows);encoded=json.dumps(summary)
                    self.assertNotIn('PRIVATE',encoded);self.assertLess(len(encoded),10000)
                    self.assertEqual(set(summary),{'schemaVersion','kind','acceptanceEligible','passed','cases'})
                    self.assertEqual(len(summary['cases']),6)
                    result=next(r for r in summary['cases'] if r['module']==module)
                    self.assertEqual(set(result),{'module','status','failure','finalizationFailures','cleanupErrorCount','cleanup'})
                    self.assertEqual(result['failure'],{'stage':'load-factory','category':'TimeoutError'})
                    self.assertEqual(len(result['finalizationFailures']),2)
                    self.assertEqual(result['cleanupErrorCount'],23)
                    self.assertEqual(set(result['cleanup']),{'gracefulQualified','forcedTermination','jobEmptyVerified','launcherExitCode','errors','errorsTruncated'})
                    self.assertTrue(all(set(e)=={'stage','category'} for e in result['cleanup']['errors']))
                    self.assertEqual(len(result['cleanup']['errors']),16)
                    self.assertTrue(result['cleanup']['errorsTruncated'])
                    self.assertTrue(result['cleanup']['forcedTermination'])
                    self.assertTrue(result['cleanup']['jobEmptyVerified'])
                    self.assertFalse(summary['acceptanceEligible']);self.assertFalse(summary['passed'])

    def test_actual_fixture_command_produces_the_exact_uploaded_safe_summary(self):
        _,steps=configured_modes()
        self.assertIn('suite/e2e/engine_smoke.py --suite $package --output .work/suite-engine',run_code(steps['fixtures']))
        self.assertNotIn('--verify-ui',run_code(steps['fixtures']))
        for failed_module in smoke.FILES:
            with self.subTest(module=failed_module),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);suite=root/'suite';suite.mkdir();output=root/'evidence'
                modules={m:{'factory':factory} for m,factory in smoke.FACTORIES.items()}
                (suite/'suite-product.json').write_text(json.dumps({'schemaVersion':1,'modules':modules}))
                def case(suite,output,module,specification,verify_ui):
                    self.assertFalse(verify_ui)
                    if module==failed_module:raise PermissionError('PRIVATE-EXCEPTION C:/PRIVATE-PATH')
                    return dict(module=module,status='passed')
                with patch.object(smoke,'run_case',side_effect=case),redirect_stdout(io.StringIO()):
                    code=smoke.main(['--suite',str(suite),'--output',str(output)])
                self.assertEqual(code,1)
                safe=output/'engine-failure-summary.json';text=safe.read_text();receipt=json.loads(text)
                self.assertNotIn('PRIVATE',text);self.assertNotIn(str(root),text)
                row=next(r for r in receipt['cases'] if r['module']==failed_module)
                self.assertEqual(row['failure'],{'stage':'case-setup','category':'PermissionError'})
                self.assertFalse(receipt['passed'])
