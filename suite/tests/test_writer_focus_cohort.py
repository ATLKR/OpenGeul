"""One Writer ordering case must not expand the existing Calc cohort or input."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import korean_ime_smoke as ime

class WriterFocusCohortTests(unittest.TestCase):
    def test_one_writer_case_and_original_cleanup_required(self):
        for cleaned in (True,False):
            with self.subTest(cleaned=cleaned),tempfile.TemporaryDirectory() as directory:
                output=Path(directory);calls=[]
                def run(*args,**kwargs):
                    calls.append((args,kwargs))
                    return dict(success=True,testProcessCleanup=dict(shellExitCode=0,disposition='already-exited'),
                        focusCohortEngineCleanup=dict(admitted=True,engineExitConfirmed=cleaned,handleReleased=True))
                with patch.object(ime.ascii_input,'prepare_observer',return_value={}),patch.object(ime,'case',side_effect=run):
                    code=ime.run_focus_cohort(output,output,output,{},'arm64',{},module='writer')
                self.assertEqual(len(calls),1)
                args,kwargs=calls[0]
                self.assertEqual(args[4:6],('writer',dict(ime.INPUT_CASES)['writer']))
                self.assertTrue(kwargs['diagnose_focus'])
                self.assertEqual(kwargs['diagnostic_suffix'],'focus-01')
                self.assertNotIn('plugin_origin',kwargs)
                report=json.loads((output/'results.json').read_text())
                self.assertEqual(report['expectedCaseCount'],1)
                self.assertEqual(report['completedCaseCount'],1)
                self.assertEqual(report['success'],cleaned)
                self.assertEqual(code,0 if cleaned else 1)
                self.assertFalse(report['acceptanceEligible']);self.assertFalse(report['imeVerified'])

    def test_real_writer_case_stops_before_navigation_and_ime(self):
        from types import SimpleNamespace as NS
        import test_ime_case_phases as phases
        import editor_capture_diagnostic as diagnostic
        original=ime.case;events=[]
        class Trace:
            def __init__(self,keyboard,prepared,deadline):
                self.keyboard=keyboard;self.closed=False;self.cohort_lease=NS(finish=lambda:None)
            def start(self):events.append('start')
            def watch_remaining(self):events.append('watch');self.close()
            def close(self,primary=None):
                if not self.closed:events.append('close');self.closed=True
        def real_case(*args,**kwargs):
            args=list(args);args[3]=dict(args[3],nativeMachine=0xaa64)
            return original(*args,**kwargs,diagnose_focus=True,diagnostic_suffix='focus-01')
        owner=phases.IMECasePhaseTests();self.addCleanup(owner.doCleanups)
        with patch.object(ime,'case',side_effect=real_case),patch.object(diagnostic,'EditorCaptureDiagnostic',Trace), \
                patch.object(diagnostic,'cohort_cleanup_confirmed',return_value=True), \
                patch.object(diagnostic,'stop_focus_keyboard_before_passive_watch',side_effect=lambda k,t:k.close(RuntimeError('focus stop'))):
            calls,record,result,error=owner.run_case('writer')
        self.assertIsNone(error,repr(error));self.assertTrue(result['success'])
        self.assertEqual(result['case'],'ime-writer-focus-01');self.assertEqual(result['architecture'],'arm64')
        self.assertEqual(events,['start','watch','close']);self.assertEqual(calls.count('CTRL_F6'),1)
        for forbidden in ('ready',('navigate','writer'),'ascii-forward','CTRL_S',('command',1)):
            self.assertNotIn(forbidden,calls)
        self.assertFalse(result['imeVerified']);self.assertFalse(result['acceptanceEligible'])

    def test_real_case_rejects_writer_scope_expansion_before_filesystem(self):
        import sys
        from types import SimpleNamespace as NS
        for changes in ({'machine':0x8664},{'diagnostic_suffix':'focus-02'},
                        {'plugin_origin':{}},{'diagnose_navigation':True},{'diagnose_ime_mode':True}):
            options=dict(prepared_library={},diagnose_focus=True,diagnostic_suffix='focus-01');options.update(changes)
            machine=options.pop('machine',0xaa64)
            with self.subTest(changes=changes),patch.dict(sys.modules,{'pywinauto':NS(Desktop=object)}):
                with self.assertRaises(AssertionError):
                    ime.case(None,None,None,{'nativeMachine':machine},'writer','odt',**options)

    def test_writer_rejects_other_architecture_or_matched_cohort_before_preparation(self):
        for architecture,proof,module in [('x64',None,'writer'),('arm64',Path('proof'),'writer'),('arm64',None,'impress')]:
            with self.subTest(architecture=architecture,proof=proof,module=module),patch.object(ime.ascii_input,'prepare_observer') as prepare:
                with self.assertRaises(AssertionError):
                    ime.run_focus_cohort(Path('.'),Path('.'),Path('.'),{},architecture,{},proof,module=module)
                prepare.assert_not_called()


class WriterFocusWorkflowTests(unittest.TestCase):
    def test_only_arm64_after_all_existing_prerequisites(self):
        from suite.tests.test_calc_matrix_workflow import workflow_steps,field,run_code
        from suite.tests.test_navigation_diagnostic_workflow import condition
        from suite.tests.test_com_wait_workflow import evaluate
        steps={field(s,'id'):s for s in workflow_steps() if field(s,'id')}
        gates=('suite-unit-shell','sal-offset-admission','source-engine')
        for architecture in ('arm64','x64'):
            for failed in (None,*gates):
                outcomes={name:'failure' if name==failed else 'success' for name in gates}
                self.assertEqual(evaluate(condition(steps['build']),'focus-diagnostic',architecture,outcomes),architecture=='arm64' and failed is None)
            for failed in (None,'build','readiness','native31-privacy-prepare','fixtures'):
                outcomes={name:'failure' if name==failed else 'success' for name in ('build','readiness','native31-privacy-prepare','fixtures')}
                self.assertEqual(evaluate(condition(steps['focus-diagnostic']).replace('!cancelled()','True'),'focus-diagnostic',architecture,outcomes),architecture=='arm64' and failed is None)
        self.assertIn('--diagnose-focus writer',run_code(steps['focus-diagnostic']))
        self.assertNotIn('--matched-plugin-proof',run_code(steps['focus-diagnostic']))
        self.assertIn('always()',condition(steps['focus-diagnostic-evidence']))
        self.assertIn('throw ',run_code(steps['focus-not-acceptance']))

if __name__=='__main__':unittest.main()
