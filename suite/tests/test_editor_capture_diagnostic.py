"""Passive focus diagnostics cannot authorize input or extend entry time."""
import copy
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import test_ime_keyboard_session as fixtures


class CaptureDiagnosticTests(unittest.TestCase):
    def fixture(self):
        owner=fixtures.IMEKeyboardSessionTests();owner.setUp();self.addCleanup(owner.doCleanups)
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        session,*_=owner.fixture(directory.name,module='calc');session.start()
        session.record.update(kind='native-focus-diagnostic',acceptanceEligible=False,imeVerified=False)
        session.record['editorFocusReadiness']=dict(deadline=6.,startedAt=1.,deadlineSeconds=5.,
            deadlineScope='editor-setup-and-focus',ready=False,clickAttempts=1,clickCompleted=False)
        return session
    def probe(self):
        calls=[]
        def read(**kw):calls.append(('read',kw));return dict(status='complete',events=[{'sequence':1}])
        return NS(admit=lambda:calls.append('admit'),start=lambda:calls.append('start'),
            read_capture_trace=read,can_stop=lambda:True,stop=lambda:calls.append('stop'),
            close=lambda:(calls.append('close') or dict(engineHandleReleased=True,controllerResourcesReleased=True)),calls=calls)
    def test_expiry_retains_local_rows_without_target_or_stop_calls(self):
        from editor_capture_diagnostic import EditorCaptureDiagnostic
        keyboard=self.fixture();probe=self.probe();trace=EditorCaptureDiagnostic(keyboard,{},6.,probe=probe)
        trace.start();keyboard.clock.now=6.;primary=RuntimeError('original focus deadline')
        trace.close(primary)
        self.assertEqual(probe.calls,['admit','start',('read',{'local_only':True}),'close'])
        self.assertEqual(trace.receipt['snapshot']['events'],[{'sequence':1}])
        trace.close(primary);self.assertEqual(probe.calls.count('close'),1)
        self.assertFalse(trace.receipt['acceptanceEligible'])
    def test_copy_and_cleanup_errors_preserve_primary(self):
        from editor_capture_diagnostic import EditorCaptureDiagnostic
        keyboard=self.fixture();probe=self.probe();trace=EditorCaptureDiagnostic(keyboard,{},6.,probe=probe)
        trace.start();keyboard.clock.now=6.
        def fail(**kw):raise OSError('local copy failed')
        probe.read_capture_trace=fail
        trace.close(RuntimeError('primary'))
        self.assertIn('local copy failed',trace.receipt['snapshotError']);self.assertIn('close',probe.calls)
    def test_original_deadline_and_phase_are_mandatory(self):
        from editor_capture_diagnostic import EditorCaptureDiagnostic
        keyboard=self.fixture()
        with self.assertRaises(AssertionError):EditorCaptureDiagnostic(keyboard,{},7.,probe=self.probe())
        keyboard.phase='focused'
        with self.assertRaises(AssertionError):EditorCaptureDiagnostic(keyboard,{},6.,probe=self.probe())
    def test_passive_scope_allows_only_original_owned_focus_and_capture(self):
        from editor_capture_diagnostic import validate_passive_scope
        keyboard=self.fixture();scope=keyboard.probe.scope_snapshot(keyboard.api,keyboard.binding)
        scope['capture']=dict(hwnd=0,isWindow=False,pid=0,threadId=0,rootHwnd=0)
        for target in ('suite','parent','editor'):
            row=copy.deepcopy(scope);row['focus']=copy.deepcopy(row['parent'] if target=='parent' else row['before'][target])
            validate_passive_scope(row,keyboard.binding,keyboard.tid)
        for mutate in (lambda r:r['focus'].update(hwnd=999),lambda r:r['before']['foreground'].update(pid=999),
                       lambda r:r['capture'].update(hwnd=999,isWindow=True,pid=88,threadId=44,rootHwnd=11),
                       lambda r:r.update(parentOwnsChild=False),lambda r:r['before']['editor'].update(threadId=99)):
            row=copy.deepcopy(scope);mutate(row)
            with self.assertRaises(AssertionError):validate_passive_scope(row,keyboard.binding,keyboard.tid)
    def test_focus_case_stops_before_navigation_or_ime(self):
        import korean_ime_smoke as ime
        import test_ime_case_phases as phases
        import editor_capture_diagnostic as diagnostic
        original=phases.ime.case;events=[]
        class Trace:
            def __init__(self,keyboard,prepared,deadline):
                self.keyboard=keyboard;self.closed=False;events.append('construct')
                self.cohort_lease=NS(finish=lambda:None)
            def start(self):events.append('trace-start')
            def close(self,primary=None):
                if not self.closed:events.append('trace-close');self.closed=True
        def case(*args,**kwargs):return original(*args,**kwargs,diagnose_focus=True,diagnostic_suffix='focus-01')
        with patch.object(phases.ime,'case',side_effect=case),patch.object(diagnostic,'EditorCaptureDiagnostic',Trace),patch.object(diagnostic,'cohort_cleanup_confirmed',return_value=True), \
                patch.object(diagnostic,'stop_focus_keyboard',side_effect=lambda k:k.close(RuntimeError('focus stop'))), \
                patch('generated_calc_close.freeze_saved_calc_copy',return_value=object()), \
                patch('calc_save_smoke.read_cells',return_value={}):
            owner=phases.IMECasePhaseTests();self.addCleanup(owner.doCleanups)
            calls,record,result,error=owner.run_case('calc')
        self.assertIsNone(error,repr(error));self.assertTrue(result['success'])
        self.assertEqual(events,['construct','trace-start','trace-close'])
        self.assertEqual(calls.count('CTRL_F6'),1);self.assertNotIn('ready',calls)
        self.assertNotIn(('navigate','calc'),calls);self.assertNotIn('ascii-forward',calls)
        self.assertNotIn('CTRL_S',calls);self.assertNotIn(('command',1),calls)
        self.assertFalse(result['imeVerified']);self.assertFalse(result['acceptanceEligible'])
        self.assertEqual(result['case'],'ime-calc-focus-01')

    def test_cohort_lease_joins_then_observes_once_without_new_target_lookup(self):
        from editor_capture_diagnostic import CohortEngineLease,cohort_cleanup_confirmed
        k=self.fixture();calls=[];receipt={}
        probe=NS(open_engine=lambda pid:(calls.append(('open',pid)) or 909),
            engine_snapshot=lambda h:(calls.append(('identity',h)) or dict(k.engine,handleValue=h)),
            kernel=NS(WaitForSingleObject=lambda h,ms:(calls.append(('wait',h,ms)) or 0)),
            close_engine=lambda h:(calls.append(('close',h)) or True))
        lease=CohortEngineLease(k,receipt)
        with patch('editor_capture_diagnostic.join_shortcut_generation',return_value=k.shared_admission):lease.admit(probe,6.)
        k.clock.now=100.;lease.finish();lease.finish()
        self.assertEqual(calls,[('open',k.binding['officePid']),('identity',909),('wait',909,0),('close',909)])
        record=dict(focusCohortEngineCleanup=receipt,testProcessCleanup=dict(shellExitCode=0,disposition='already-exited'))
        self.assertTrue(cohort_cleanup_confirmed(record))
        for key in ('admitted','engineExitConfirmed','handleReleased'):
            modified=copy.deepcopy(record);modified['focusCohortEngineCleanup'][key]=False
            self.assertFalse(cohort_cleanup_confirmed(modified))
    def test_cohort_lease_rejects_changed_generation_and_releases_without_wait(self):
        from editor_capture_diagnostic import CohortEngineLease
        k=self.fixture();calls=[];receipt={}
        probe=NS(open_engine=lambda pid:909,engine_snapshot=lambda h:dict(k.engine,handleValue=h,creationTime=99),
            kernel=NS(WaitForSingleObject=lambda *args:self.fail('unadmitted lease waited')),
            close_engine=lambda h:(calls.append(h) or True))
        lease=CohortEngineLease(k,receipt)
        with self.assertRaises(AssertionError):lease.admit(probe,6.)
        lease.finish();self.assertEqual(calls,[909]);self.assertFalse(receipt['engineExitConfirmed'])
    def test_cohort_persistent_engine_and_failed_release_stop_next_case(self):
        from editor_capture_diagnostic import CohortEngineLease,cohort_cleanup_confirmed
        for wait,release in ((258,True),(0,False)):
            k=self.fixture();receipt={};calls=[]
            probe=NS(open_engine=lambda pid:909,engine_snapshot=lambda h:dict(k.engine,handleValue=h),
                kernel=NS(WaitForSingleObject=lambda h,ms:(calls.append(ms) or wait)),close_engine=lambda h:release)
            lease=CohortEngineLease(k,receipt)
            with patch('editor_capture_diagnostic.join_shortcut_generation',return_value=k.shared_admission):lease.admit(probe,6.)
            k.clock.now=100.;lease.finish();self.assertEqual(calls,[0])
            self.assertFalse(cohort_cleanup_confirmed(dict(focusCohortEngineCleanup=receipt,
                testProcessCleanup=dict(shellExitCode=0,disposition='already-exited'))))
    def stopped_keyboard(self):
        k=self.fixture();k.focus_editor(6.)
        with patch.object(k,'editor_ready'):
            fixtures.IMEKeyboardSessionTests().ready(k)
        k.record['focusCaptureDiagnostic']=dict(deadline=6.,cleanupErrors=[],cleanup=dict(
            engineHandleReleased=True,controllerResourcesReleased=True))
        return k
    def test_real_keyboard_stop_retains_incomplete_session_and_releases_handle(self):
        from editor_capture_diagnostic import stop_focus_keyboard
        import json
        k=self.stopped_keyboard();stop_focus_keyboard(k)
        self.assertTrue(k.finished);self.assertFalse(k.receipt['success']);self.assertTrue(k.receipt['engineHandleReleased'])
        self.assertEqual(k.phase,'awaiting-editor-readiness')
        persisted=json.loads((k.output/(k.stem+'-session-result.json')).read_text())
        self.assertFalse(persisted['success']);self.assertIn('FocusDiagnosticStop',persisted['error'])
    def test_focus_stop_cannot_hide_release_retention_or_deadline_failure(self):
        from editor_capture_diagnostic import stop_focus_keyboard
        for operation in ('release','retain','late'):
            k=self.stopped_keyboard();original=k.probe.close_engine
            def late(handle):
                result=original(handle);k.clock.now=6.;return result
            target=k if operation=='retain' else k.probe
            method='_retain' if operation=='retain' else 'close_engine'
            effect=late if operation=='late' else OSError('synthetic cleanup failure')
            with patch.object(target,method,side_effect=effect):
                with self.assertRaises(AssertionError):stop_focus_keyboard(k)
            self.assertFalse(k.receipt['success'])
    def test_focus_cli_wrong_owner_rejected_before_output_or_prepare(self):
        import json,os
        from pathlib import Path
        import korean_ime_smoke as ime
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);suite=root/'suite';suite.mkdir();baseline=root/'fixtures';baseline.mkdir()
            event=root/'event.json';event.write_text('{}');output=root/'output'
            (suite/'suite-inventory.json').write_text(json.dumps(dict(schemaVersion=1,architecture='x64')))
            with patch.object(ime,'os',NS(name='nt',environ={})),patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(event)}), \
                    patch.object(ime.native_arch,'observe_native_architecture'),patch.object(ime.native_arch,'validate_native_architecture'), \
                    patch.object(ime.ascii_input,'prepare_observer') as prepare:
                with self.assertRaisesRegex(ValueError,'owner-push context'):
                    ime.main(['--suite',str(suite),'--fixtures',str(baseline),'--readiness',str(root/'readiness.json'),
                        '--output',str(output),'--diagnose-focus','calc'])
                prepare.assert_not_called();self.assertFalse(output.exists())
    def test_passive_identity_revalidates_original_generation_thread_and_session(self):
        from editor_capture_diagnostic import PassiveCaptureProbe
        k=self.fixture();scope=copy.deepcopy(k.receipt['admissionSnapshot']['scope'])
        scope['capture']=dict(hwnd=0,isWindow=False,pid=0,threadId=0,rootHwnd=0)
        scope['focus']=copy.deepcopy(scope['before']['editor'])
        probe=PassiveCaptureProbe(k,{}, {},6.)
        probe.handle=909;probe.original_shell=k.shell;probe.original_engine=dict(k.engine,handleValue=909)
        probe.controller_pid=1;probe.sessions=dict(controller=2,shell=2,engine=2)
        probe.probe=NS(process_snapshot=lambda p:k.shell,engine_snapshot=lambda h:probe.original_engine,
            scope_snapshot=lambda *args:scope,keyboard_snapshot=lambda tid:dict(targetLayout=0x04090409))
        probe._session=lambda pid:2
        probe._identity()
        scope['before']['suite']['threadId']+=1;scope['after']['suite']['threadId']+=1
        scope['before']['foreground']['threadId']+=1;scope['after']['foreground']['threadId']+=1
        scope['parent']['threadId']+=1
        with self.assertRaises(AssertionError):probe._identity()
        k.clock.now=6.
        probe.probe.process_snapshot=lambda p:self.fail('target query after deadline')
        with self.assertRaisesRegex(AssertionError,'deadline expired'):probe._identity()
    def test_focus_cli_three_independent_paths_and_abort_on_unconfirmed_exit(self):
        import importlib.util,json
        from pathlib import Path
        import korean_ime_smoke as ime
        for fail_exit in (False,True):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);suite=root/'suite';suite.mkdir();baseline=root/'fixtures';baseline.mkdir()
                output=root/'output';readiness=root/'readiness.json';readiness.write_text('{}')
                (suite/'suite-inventory.json').write_text(json.dumps(dict(schemaVersion=1,architecture='x64')))
                def execute(*args,**kw):
                    return dict(case='ime-calc-'+kw['diagnostic_suffix'],success=True,
                        testProcessCleanup=dict(shellExitCode=0,disposition='already-exited'),
                        focusCohortEngineCleanup=dict(admitted=True,engineExitConfirmed=not fail_exit,handleReleased=True))
                loader=NS(exec_module=lambda module:None)
                admission=NS(validate_context=lambda *args:dict(source='synthetic-bound-owner-push'),read_event=lambda:{})
                with patch.object(ime,'os',NS(name='nt',environ={})), \
                        patch.object(ime.native_arch,'observe_native_architecture'),patch.object(ime.native_arch,'validate_native_architecture'), \
                        patch.object(ime,'require_readiness',return_value={}),patch.object(ime.ascii_input,'prepare_observer',return_value={}), \
                        patch.object(importlib.util,'spec_from_file_location',return_value=NS(loader=loader)), \
                        patch.object(importlib.util,'module_from_spec',return_value=admission),patch.object(ime,'case',side_effect=execute) as cases:
                    result=ime.main(['--suite',str(suite),'--fixtures',str(baseline),'--readiness',str(readiness),
                        '--output',str(output),'--diagnose-focus','calc'])
                report=json.loads((output/'results.json').read_text());count=1 if fail_exit else 3
                self.assertEqual(cases.call_count,count);self.assertEqual(result,1 if fail_exit else 0)
                self.assertEqual([c.kwargs['diagnostic_suffix'] for c in cases.call_args_list],[f'focus-{i:02d}' for i in range(1,count+1)])
                self.assertEqual(report['completedCaseCount'],count);self.assertFalse(report['acceptanceEligible']);self.assertFalse(report['imeVerified'])
                self.assertEqual(report['runBinding'],dict(source='synthetic-bound-owner-push'))

    def test_focus_failure_preserves_primary_without_fresh_native_diagnostics(self):
        import test_ime_case_phases as phases
        import editor_capture_diagnostic as diagnostic
        original=phases.ime.case;events=[]
        class Trace:
            def __init__(self,*args):self.cohort_lease=NS(finish=lambda:events.append('lease-finish'));self.closed=False
            def start(self):raise RuntimeError('original focus failure')
            def close(self,primary=None):
                if not self.closed:events.append(('close',str(primary)));self.closed=True
        def case(*args,**kw):return original(*args,**kw,diagnose_focus=True,diagnostic_suffix='focus-01')
        with patch.object(phases.ime,'case',side_effect=case),patch.object(diagnostic,'EditorCaptureDiagnostic',Trace),                 patch.object(phases.ime,'retain_ime_focus_failure_diagnostics',side_effect=AssertionError('fresh target call')):
            owner=phases.IMECasePhaseTests();self.addCleanup(owner.doCleanups)
            calls,record,result,error=owner.run_case('calc')
        self.assertIsInstance(error,RuntimeError);self.assertEqual(str(error),'original focus failure')
        self.assertEqual(record['error'],'RuntimeError: original focus failure')
        self.assertEqual(record['failureScreenshotSkipped'],'focus-diagnostic-local-only-after-failure')
        self.assertEqual(events,[('close','original focus failure'),'lease-finish'])
        self.assertNotIn('CTRL_F6',calls);self.assertNotIn('ready',calls)
