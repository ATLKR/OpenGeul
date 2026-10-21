"""Diagnostic entry uses the real shared click policy; native operations are fakes."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from contextlib import ExitStack

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'e2e'))
sys.path.insert(0, str(HERE))
import editor_click_readiness as click
import generated_calc_close as generated
import tsf_profile_diagnostic as diag
from test_editor_click_readiness import Probe


def focus_row():
    def window(hwnd, pid, tid):
        return dict(hwnd=hwnd, pid=pid, threadId=tid, rootHwnd=11, isWindow=True)
    frame = dict(suite=window(11,77,10), editor=window(33,88,20),
                 foreground=window(11,77,10), editorWithinSuite=True)
    return dict(before=copy.deepcopy(frame), after=copy.deepcopy(frame),
        queriedThreadId=20, cbSize=72, queryAttempted=True, querySucceeded=True,
        lastError=0, flags=0, focus=window(34,88,20), focusWithinEditor=True,
        capture=dict(hwnd=0))


class DiagnosticClickEntryTests(unittest.TestCase):
    def fixture(self, directory):
        output=Path(directory).resolve();suite=output/'Suite';suite.mkdir()
        process=NS(pid=77,_handle=2**40,args=[str(suite/'OpenGeul.Office.exe')],
            opengeul_suite_root=suite,opengeul_evidence_output=output,
            opengeul_evidence_case='diagnostic-entry')
        probe=Probe(process,time.monotonic)
        process.opengeul_activation_binding=tuple(probe.shell[k] for k in
            ('pid','handleValue','image','creationTime','waitResult'))
        rows=[]
        def observe(*args):
            rows.append(focus_row());return rows[-1]
        def foreground(hwnd): self.assertEqual(probe.foreground_root,hwnd)
        api=NS(require_foreground=foreground,editor_focus_snapshot=observe)
        return process,probe,api,rows

    def entry(self, api, process, record, setup_deadline):
        method=getattr(diag,'prepare_diagnostic_editor_focus',None)
        self.assertTrue(callable(method), 'Diagnostic must supply the real click pending context before native.click_owned_editor')
        return method(api,process,11,22,33,88,record,setup_deadline)

    def test_real_transitive_click_then_pure_focus_share_original_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            process,probe,api,rows=self.fixture(directory);record={}
            with patch.object(click,'NativeEditorClickProbe',return_value=probe):
                self.assertEqual(self.entry(api,process,record,time.monotonic()+60),34)
            pending=record['editorFocusReadiness'];passive=record['diagnosticFocusReadiness']
            measured=record['editorClicks'][0]
            self.assertEqual((probe.calls.count('move'),probe.calls.count('click')),(1,1))
            self.assertEqual((pending['clickAttempts'],pending['clickCompleted']),(1,True))
            self.assertEqual((pending['controlF6Attempts'],pending['controlF6Completed'],pending['ready']),(0,False,False))
            self.assertEqual((passive['keyboardInputs'],passive['ready']),(0,True))
            self.assertEqual((pending['startedAt'],pending['deadline']),(passive['startedAt'],passive['deadline']))
            self.assertEqual(measured['deadline'],pending['deadline'])
            self.assertLessEqual(pending['deadlineSeconds'],5)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['capture']['hwnd'],0)
            self.assertTrue(measured['engineHandleReleased']);self.assertTrue(measured['dpiScope']['restored'])
            with self.assertRaises(AssertionError):diag.native.require_editor_focus_readiness(pending,11,33,77,88)

    def test_setup_clip_is_the_click_and_passive_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            process,probe,api,rows=self.fixture(directory);record={};deadline=time.monotonic()+1
            with patch.object(click,'NativeEditorClickProbe',return_value=probe):
                self.entry(api,process,record,deadline)
            self.assertEqual(record['editorFocusReadiness']['deadline'],deadline)
            self.assertEqual(record['diagnosticFocusReadiness']['deadline'],deadline)

    def test_foreign_foreground_prevents_buttons_and_keeps_native_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            process,probe,api,rows=self.fixture(directory);probe.foreground_root=99;record={}
            with patch.object(click,'NativeEditorClickProbe',return_value=probe):
                with self.assertRaises(AssertionError):self.entry(api,process,record,time.monotonic()+5)
            self.assertNotIn('move',probe.calls);self.assertNotIn('click',probe.calls)
            self.assertEqual(rows,[]);self.assertFalse(record['editorFocusReadiness']['clickCompleted'])
            self.assertTrue(record['editorClicks'][0]['engineHandleReleased'])
            self.assertTrue(record['editorClicks'][0]['dpiScope']['restored'])

    def test_expiry_during_real_click_does_not_start_a_new_passive_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            process,probe,api,rows=self.fixture(directory);record={}
            clock=NS(now=time.monotonic())
            probe.after_click=lambda:setattr(clock,'now',clock.now+5)
            # The real click function holds its default clock; only the diagnostic
            # clock advances to the original expiry when that one click returns.
            with patch.object(click,'NativeEditorClickProbe',return_value=probe),patch.object(diag.time,'monotonic',side_effect=lambda:clock.now):
                with self.assertRaisesRegex(AssertionError,'deadline'):self.entry(api,process,record,clock.now+60)
            self.assertEqual((probe.calls.count('move'),probe.calls.count('click')),(1,1))
            self.assertEqual(rows,[]);self.assertNotIn('diagnosticFocusReadiness',record)
            self.assertTrue(record['editorClicks'][0]['engineHandleReleased'])
            self.assertFalse(record['editorFocusReadiness']['ready'])

    def test_passive_query_late_return_cannot_become_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            process,probe,api,rows=self.fixture(directory);record={};clock=NS(now=time.monotonic())
            observe=api.editor_focus_snapshot
            def late(*args):
                row=observe(*args);clock.now+=5;return row
            api.editor_focus_snapshot=late
            with patch.object(click,'NativeEditorClickProbe',return_value=probe),patch.object(diag.time,'monotonic',side_effect=lambda:clock.now):
                with self.assertRaisesRegex(AssertionError,'deadline'):self.entry(api,process,record,clock.now+60)
            self.assertEqual(len(rows),1);self.assertFalse(record['diagnosticFocusReadiness']['ready'])
            self.assertEqual((probe.calls.count('move'),probe.calls.count('click')),(1,1))

    def test_passive_foreign_focus_remains_fatal_after_the_one_click(self):
        with tempfile.TemporaryDirectory() as directory:
            process,probe,api,rows=self.fixture(directory);record={}
            observe=api.editor_focus_snapshot
            def foreign(*args):
                row=observe(*args);row['focus']['pid']=999;return row
            api.editor_focus_snapshot=foreign
            with patch.object(click,'NativeEditorClickProbe',return_value=probe):
                with self.assertRaisesRegex(AssertionError,'foreign'):self.entry(api,process,record,time.monotonic()+5)
            self.assertFalse(record['diagnosticFocusReadiness']['ready'])
            self.assertEqual((probe.calls.count('move'),probe.calls.count('click')),(1,1))

    def test_expired_setup_never_calls_the_native_click(self):
        with tempfile.TemporaryDirectory() as directory:
            process,probe,api,rows=self.fixture(directory)
            with patch.object(click,'NativeEditorClickProbe',return_value=probe):
                with self.assertRaisesRegex(AssertionError,'deadline'):self.entry(api,process,{},time.monotonic()-1)
            self.assertEqual(probe.calls,[]);self.assertEqual(rows,[])


class GeneratedDiagnosticCloseTests(unittest.TestCase):
    def fixture(self, directory):
        folder=Path(directory);proof=generated.SavedCalcCopy(folder/'Suite',folder,folder/'OpenGeul-calc.xlsx','a'*64,())
        process=NS(pid=77);shell=dict(pid=77,handleValue=101,creationTime=2**58+1)
        engine=dict(pid=88,handleValue=102,creationTime=2**58+3)
        probe=NS(process_snapshot=lambda p:copy.deepcopy(shell),engine_snapshot=lambda h:copy.deepcopy(engine))
        lease=NS(handle=102,shell=shell,engine=engine,probe=probe,deadline=time.monotonic()+180)
        record=dict(module='calc',windowHwnd=11,childHwnd=33,shellPid=77,officePid=88,cleanupErrors=[])
        return process,lease,record,proof

    def close(self, api, process, record, proof, lease):
        method=getattr(diag,'close_generated_diagnostic_copy',None)
        self.assertTrue(callable(method),'Diagnostic must delegate the explicitly owned generated-copy cleanup')
        return method(api,process,11,33,record,proof,lease)

    def test_exact_saved_copy_delegates_through_unchanged_native_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            process,lease,record,proof=self.fixture(directory);api=object()
            with patch.object(generated,'close_saved_calc_copy') as leaf:
                result=self.close(api,process,record,proof,lease)
            leaf.assert_called_once_with(api,process,11,33,record,proof)
            self.assertTrue(result['complete']);self.assertFalse(result['cleanDirectCloseSupported'])
            self.assertEqual(result['phaseLimitsSeconds'],dict(promptReadinessFocus=20,dialogGone=20,rootGone=20,childGone=10))
            self.assertEqual(result['maximumSequentialDeclaredSeconds'],70)
            self.assertEqual(result['deadline'],lease.deadline);self.assertEqual(lease.handle,102)

    def test_changed_generation_prevents_any_delegate(self):
        for key in ('shell','engine'):
            with self.subTest(key=key),tempfile.TemporaryDirectory() as directory:
                process,lease,record,proof=self.fixture(directory)
                original=getattr(lease,key).copy();original['creationTime']+=1
                if key=='shell':lease.probe.process_snapshot=lambda p:original
                else:lease.probe.engine_snapshot=lambda h:original
                with patch.object(generated,'close_saved_calc_copy') as leaf:
                    with self.assertRaisesRegex(AssertionError,'generation'):self.close(object(),process,record,proof,lease)
                leaf.assert_not_called();self.assertFalse(record['diagnosticDocumentClose']['complete'])

    def test_expired_lease_prevents_queries_and_delegate(self):
        with tempfile.TemporaryDirectory() as directory:
            process,lease,record,proof=self.fixture(directory);lease.deadline=time.monotonic()-1
            with patch.object(lease.probe,'process_snapshot') as query,patch.object(generated,'close_saved_calc_copy') as leaf:
                with self.assertRaisesRegex(AssertionError,'deadline'):self.close(object(),process,record,proof,lease)
            query.assert_not_called();leaf.assert_not_called()

    def test_delegate_failure_is_retained_and_never_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            process,lease,record,proof=self.fixture(directory);error=OSError('owned prompt failed')
            with patch.object(generated,'close_saved_calc_copy',side_effect=error) as leaf:
                with self.assertRaises(OSError) as raised:self.close(object(),process,record,proof,lease)
            self.assertIs(raised.exception,error);self.assertEqual(leaf.call_count,1)
            self.assertFalse(record['diagnosticDocumentClose']['complete'])
            self.assertIn('owned prompt failed',record['diagnosticDocumentClose']['error'])

    def test_late_delegate_success_cannot_qualify_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            process,lease,record,proof=self.fixture(directory);now=time.monotonic();lease.deadline=now+180
            clock=NS(now=now)
            def late(*args):clock.now=lease.deadline
            with patch.object(generated,'close_saved_calc_copy',side_effect=late),patch.object(diag.time,'monotonic',side_effect=lambda:clock.now):
                with self.assertRaisesRegex(AssertionError,'deadline'):self.close(object(),process,record,proof,lease)
            self.assertFalse(record['diagnosticDocumentClose']['complete'])

    def test_case_keeps_observer_primary_over_owned_generated_copy_cleanup_failure(self):
        import calc_model_barrier
        import home_routing_smoke
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'evidence';output.mkdir()
            process,probe,api,rows=DiagnosticClickEntryTests().fixture(output)
            process.poll=lambda:None
            fixture=Path(directory)/'fixtures'/'OpenGeul-calc.xlsx';fixture.parent.mkdir();fixture.write_bytes(b'owned fixture')
            suite=process.opengeul_suite_root
            proof=generated.SavedCalcCopy(suite,output/'tsf-profile-calc',output/'tsf-profile-calc'/fixture.name,
                hashlib.sha256(fixture.read_bytes()).hexdigest(),())
            api.user=NS(IsWindow=lambda hwnd:True,GetWindowThreadProcessId=lambda hwnd,out:20)
            lease=NS(handle=probe.engine['handleValue'],shell=copy.deepcopy(probe.shell),engine=copy.deepcopy(probe.engine),
                probe=probe,deadline=time.monotonic()+180,tid=20,record=dict(handleClosed=False))
            lease.close=lambda:lease.record.update(handleClosed=True)
            primary=OSError('observer admission failed');secondary=OSError('owned generated prompt failed')
            desktop=NS(window=lambda **kw:NS(wrapper_object=lambda:NS(maximize=lambda:None)))
            with ExitStack() as stack:
                stack.enter_context(patch.dict(sys.modules,{'pywinauto':NS(Desktop=lambda **kw:desktop)}))
                for owner,name,value in ((diag.native,'require_engine_fixture',lambda *a:fixture),
                    (diag.native,'_verified_saved_calc_close_proof',lambda *a,**kw:proof),
                    (diag.native,'launch_suite',lambda *a:process),(diag.native,'Windows',lambda:api),
                    (diag.native,'verified_attachment',lambda *a:(11,22,33,88)),
                    (diag.native,'activate_owned_suite',lambda *a:None),(diag,'EngineLease',lambda *a:lease),
                    (calc_model_barrier,'baseline_from_ooxml',lambda raw:()),
                    (click,'NativeEditorClickProbe',lambda *a:probe)):
                    stack.enter_context(patch.object(owner,name,new=value))
                observer=stack.enter_context(patch.object(diag,'ProfileObserver',side_effect=primary))
                discard=stack.enter_context(patch.object(generated,'close_saved_calc_copy',side_effect=secondary))
                obsolete=stack.enter_context(patch.object(diag,'close_clean_diagnostic_copy',side_effect=AssertionError('obsolete clean-only close')))
                archive=stack.enter_context(patch.object(home_routing_smoke,'verify_native_archives'))
                with self.assertRaises(OSError) as raised:diag.case(suite,fixture.parent,output,dict(profile={}))
            self.assertIs(raised.exception,primary);self.assertEqual(observer.call_count,1)
            self.assertEqual(discard.call_count,1);self.assertIs(discard.call_args.args[-1],proof)
            obsolete.assert_not_called();archive.assert_not_called()
            record=json.loads((output/'result.json').read_bytes())
            self.assertEqual(record['error'],'OSError: observer admission failed')
            self.assertEqual(record['cleanupErrors'],['OSError: owned generated prompt failed'])
            self.assertFalse(record['success']);self.assertNotIn('naturalRetirementVerified',record)
            self.assertTrue(record['retainedEngine']['handleClosed']);self.assertFalse(record['diagnosticDocumentClose']['complete'])
            self.assertEqual((probe.calls.count('move'),probe.calls.count('click')),(1,1));self.assertEqual(len(rows),1)


if __name__=='__main__':unittest.main()
