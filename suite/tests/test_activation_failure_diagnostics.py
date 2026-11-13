"""Failure-time observations never certify historical routing or change input."""
import copy
import ctypes as C
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_suite_window_activation as activation_tests
Clock, Library = activation_tests.Clock, activation_tests.Library


class FakeDiagnosticProbe:
    def __init__(self, clock):
        self.clock = clock; self.calls = []; self.closed = []; self.current = (98, 99)
        self.fail = None; self.late = None; self.racy = False; self.reads = {}
    def event(self, name):
        self.calls.append(name)
        if self.late == name: self.clock.now += .6
        if self.fail == name: raise OSError('diagnostic unavailable')
    def foreground(self): self.event('foreground'); return dict(rawHwnd=self.current[0], rootHwnd=self.current[1])
    def identity(self, hwnd):
        self.event('identity'); self.reads[hwnd] = self.reads.get(hwnd, 0) + 1
        return dict(hwnd=hwnd, rootHwnd=hwnd, pid=99 if self.racy and self.reads[hwnd] > 1 else hwnd + 100,
                    threadId=hwnd + 1000, isWindow=True)
    def caption(self, hwnd): self.event('caption'); return dict(className='ForeignWindow', title='Foreign caption')
    def gui_thread(self, tid):
        self.event('gui'); return dict(threadId=tid, flags=0x14, hwndActive=99, hwndFocus=98,
            hwndCapture=97, hwndMenuOwner=96, hwndMoveSize=0, hwndCaret=0)
    def open_process(self, pid): self.event('open'); return pid + 2**40
    def process(self, handle):
        self.event('process'); return dict(pid=handle - 2**40, handleValue=handle, creationTime=123456,
            image='C:/foreign.exe', waitResult=258)
    def close_process(self, handle): self.closed.append(handle); return True


class FailureDiagnosticPolicy(unittest.TestCase):
    def load(self):
        path = E2E / 'activation_failure_diagnostics.py'
        self.assertTrue(path.is_file(), 'failure-only diagnostic collector is missing')
        spec = importlib.util.spec_from_file_location('activation_failure_diagnostics_tested', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module
    def collect(self, probe, clock, last=88):
        return self.load().collect_failure_diagnostics(11, 77, 9, last, probe=probe, clock=clock)
    def test_two_distinct_foreign_roots_three_gui_rows_and_failure_time_only_generations(self):
        clock = Clock(); probe = FakeDiagnosticProbe(clock); result = self.collect(probe, clock)
        self.assertEqual([r['hwnd'] for r in result['foreignWindows']], [99, 88])
        self.assertEqual(len(result['guiThreads']), 3); self.assertEqual(len(probe.closed), 2)
        self.assertTrue(all(r['process']['released'] for r in result['foreignWindows']))
        self.assertIn('historical', result['identityLimit'])
        self.assertEqual(result['deadline'] - result['startedAt'], .5)
        self.assertEqual(result['guiThreads'][0]['hwndCapture'], 97)
    def test_same_foreign_root_is_deduplicated_and_owned_root_is_never_foreign(self):
        for current, last, expected in [((98,99),99,[99]),((11,11),11,[]),((0,0),88,[88])]:
            with self.subTest(current=current):
                c = Clock(); p = FakeDiagnosticProbe(c); p.current = current
                r = self.collect(p,c,last)
                self.assertEqual([v['hwnd'] for v in r['foreignWindows']],expected)
                self.assertLessEqual(len(p.closed),2); self.assertLessEqual(len(r['guiThreads']),3)
    def test_deadline_stops_further_queries_and_opened_handle_is_closed(self):
        c=Clock();p=FakeDiagnosticProbe(c);p.late='open';r=self.collect(p,c)
        self.assertTrue(r['deadlineExpired']);self.assertEqual(p.calls[-1],'open')
        self.assertEqual(len(p.closed),1);self.assertGreater(r['finishedAt'],r['deadline'])
        self.assertFalse(r['withinBudget'])
        self.assertTrue(r['foreignWindows'][0]['process']['released'])
    def test_native_timeout_at_exact_deadline_is_expired_even_before_policy_recheck(self):
        c=Clock();p=FakeDiagnosticProbe(c)
        def expired():
            c.now=1.5;raise TimeoutError('native diagnostic reached deadline')
        p.foreground=expired;r=self.collect(p,c)
        self.assertTrue(r['deadlineExpired']);self.assertFalse(r['withinBudget'])
        self.assertEqual(p.calls,[])
    def test_handle_release_at_exact_deadline_is_expired_and_never_within_budget(self):
        c=Clock();p=FakeDiagnosticProbe(c);closed=p.close_process
        def close(handle):
            result=closed(handle);c.now=1.5;return result
        p.close_process=close;r=self.collect(p,c)
        self.assertEqual(len(p.closed),2)
        self.assertTrue(r['deadlineExpired']);self.assertFalse(r['withinBudget'])
        self.assertTrue(all(v['process']['released'] for v in r['foreignWindows']))
    def test_unavailable_identity_remains_unknown_without_process_admission(self):
        c=Clock();p=FakeDiagnosticProbe(c);p.fail='identity';r=self.collect(p,c)
        self.assertEqual(p.closed,[]);self.assertTrue(r['errors'])
        self.assertTrue(all(row['status']=='unavailable' for row in r['foreignWindows']))
    def test_changed_native_identity_is_racy_and_not_a_historical_binding(self):
        c=Clock();p=FakeDiagnosticProbe(c);p.racy=True;r=self.collect(p,c)
        self.assertTrue(all(v['status']=='racy' for v in r['foreignWindows']))
        self.assertTrue(all(v['processAssociation']=='unknown' for v in r['foreignWindows']))
    def test_dead_process_and_pid_mismatch_do_not_qualify_process_association(self):
        for change in ({'waitResult':0},{'pid':987}):
            with self.subTest(change=change):
                c=Clock();p=FakeDiagnosticProbe(c);original=p.process
                def process(handle):
                    row=original(handle);row.update(change);return row
                p.process=process;r=self.collect(p,c)
                self.assertTrue(all(v['processAssociation']=='unknown' for v in r['foreignWindows']))
                self.assertEqual(len(p.closed),2)
    def test_query_failure_after_admission_closes_every_handle(self):
        c=Clock();p=FakeDiagnosticProbe(c);p.fail='process';r=self.collect(p,c)
        self.assertEqual(len(p.closed),2);self.assertTrue(r['errors'])
    def test_receipt_and_all_strings_are_bounded_with_nonascii_values(self):
        c=Clock();p=FakeDiagnosticProbe(c);p.caption=lambda hwnd:dict(className='한'*10000,title='글'*10000)
        original=p.process
        def process(handle):
            value=original(handle);value['image']='가'*10000;return value
        p.process=process;r=self.collect(p,c)
        self.assertLessEqual(len(json.dumps(r,ensure_ascii=False).encode()),16384)
        self.assertTrue(all(len(v['title'])<=256 and len(v['className'])<=128 for v in r['foreignWindows']))
        self.assertTrue(all(len(v['process']['image'])<=512 for v in r['foreignWindows']))


class FailureOnlyHook(unittest.TestCase):
    def test_original_exception_object_action_finish_and_effects_survive_diagnostic_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture=activation_tests.OwnedActivationPolicy();fixture.setUpClass();p,c,probe,record=fixture.fixture(directory)
            original=OSError('original action failure')
            def broken(process): raise original
            probe.process_snapshot=broken;seen=[]
            def collect(*args,**kwargs):
                seen.append(copy.deepcopy(record['windowActivations'][0]));c.now+=.6
                raise RuntimeError('secondary diagnostic error')
            with patch.dict(sys.modules,{'activation_failure_diagnostics':NS(collect_failure_diagnostics=collect)}):
                with self.assertRaises(OSError) as caught:
                    fixture.run_activation(p,c,probe,record)
            self.assertIs(caught.exception,original);self.assertEqual(len(seen),1)
            value=record['windowActivations'][0]
            self.assertEqual(value['finishedAt'],seen[0]['finishedAt'])
            self.assertEqual(value['error'],'OSError: original action failure')
            self.assertFalse(value['ready']);self.assertEqual(value['inputCallAttempts'],0)
            self.assertIn('secondary diagnostic',value['failureDiagnosticsError'])
    def test_unprintable_diagnostic_exception_cannot_replace_original_exception(self):
        class Unprintable(Exception):
            def __str__(self):raise LookupError('diagnostic formatting failed')
        with tempfile.TemporaryDirectory() as directory:
            fixture=activation_tests.OwnedActivationPolicy();fixture.setUpClass();p,c,probe,record=fixture.fixture(directory)
            original=OSError('original input failure')
            def broken(process):raise original
            def collect(*args,**kwargs):raise Unprintable()
            probe.process_snapshot=broken;seen=None
            with patch.dict(sys.modules,{'activation_failure_diagnostics':NS(collect_failure_diagnostics=collect)}):
                try:fixture.run_activation(p,c,probe,record)
                except BaseException as exc:seen=exc
            self.assertIs(seen,original)
            self.assertIn('Unprintable',record['windowActivations'][0]['failureDiagnosticsError'])
            self.assertEqual(len(list(Path(directory).glob('*-result.json'))),1)
    def test_pass_path_never_collects_and_preserves_one_click_two_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture=activation_tests.OwnedActivationPolicy();fixture.setUpClass();p,c,probe,record=fixture.fixture(directory);calls=[]
            with patch.dict(sys.modules,{'activation_failure_diagnostics':NS(collect_failure_diagnostics=lambda *a,**k:calls.append(a))}):
                result=fixture.run_activation(p,c,probe,record)
            self.assertEqual(calls,[]);self.assertEqual(probe.calls.count('click'),1)
            self.assertEqual(result['insertedInputs'],2);self.assertNotIn('failureDiagnostics',result)
    def test_postdeadline_diagnostics_do_not_renew_action_or_change_original_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture=activation_tests.OwnedActivationPolicy();fixture.setUpClass();p,c,probe,record=fixture.fixture(directory)
            probe.after_click=lambda:setattr(probe,'foreground_root',99)
            def collect(*args,**kwargs):
                value=record['windowActivations'][0]
                self.assertFalse(value['ready']);self.assertEqual(value['finishedAt'],c())
                self.assertGreaterEqual(c(),value['deadline']);c.now+=.5
                return {'kind':'diagnostic-test','ready':False}
            with patch.dict(sys.modules,{'activation_failure_diagnostics':NS(collect_failure_diagnostics=collect)}):
                with self.assertRaisesRegex(AssertionError,'foreground'):
                    fixture.run_activation(p,c,probe,record)
            result=record['windowActivations'][0]
            self.assertEqual(result['finishedAt'],result['deadline'])
            self.assertEqual(result['clickAttempts'],1);self.assertIn('failureDiagnostics',result)


class ExistingNativeValueRetention(unittest.TestCase):
    def boundary(self):
        boundary=activation_tests.NativeActivationBoundary();boundary.setUp()
        boundary.user.GetPhysicalCursorPos.action=lambda output:setattr(output._obj,'x',20) or setattr(output._obj,'y',10) or 1
        boundary.user.GetSystemMetrics.action=lambda key:0
        boundary.user.SendInput.action=lambda count,payload,size:count
        return boundary
    def test_five_clear_button_reads_and_existing_values_are_retained_without_extra_native_calls(self):
        b=self.boundary();b.user.GetAsyncKeyState.action=lambda key:0;receipt={'chosenPhysicalPoint':[20,10]}
        b.probe.click(receipt)
        self.assertEqual([v[0] for v in b.user.GetAsyncKeyState.calls],[1,2,4,5,6])
        self.assertEqual(receipt['physicalButtonStateSamples'],[{'virtualKey':k,'rawState':0} for k in (1,2,4,5,6)])
        self.assertEqual(receipt['beforeClickCursorReadback'],[20,10]);self.assertFalse(receipt['swappedPrimary'])
        self.assertEqual(len(b.user.SendInput.calls),1)
        self.assertEqual(receipt['inputStartedAt'],1.);self.assertEqual(receipt['inputFinishedAt'],1.)
    def test_held_button_short_circuit_retains_only_the_existing_prefix(self):
        for held in (1,2,4,5,6):
            with self.subTest(held=held):
                b=self.boundary();b.user.GetAsyncKeyState.action=lambda key:0x8000 if key==held else 0
                receipt={'chosenPhysicalPoint':[20,10]}
                with self.assertRaisesRegex(AssertionError,'held'):b.probe.click(receipt)
                expected=list((1,2,4,5,6));expected=expected[:expected.index(held)+1]
                self.assertEqual([v[0] for v in b.user.GetAsyncKeyState.calls],expected)
                self.assertEqual([v['virtualKey'] for v in receipt['physicalButtonStateSamples']],expected)
                self.assertEqual(b.user.SendInput.calls,[])
    def test_raw_foreground_handle_is_retained_using_the_existing_two_queries(self):
        b=self.boundary();b.user.GetForegroundWindow.action=lambda:2**40;b.user.GetAncestor.action=lambda hwnd,kind:2**41
        self.assertEqual(b.probe.foreground(),2**41)
        self.assertEqual(b.probe.last_foreground_snapshot,{'rawHwnd':2**40,'rootHwnd':2**41})
        self.assertEqual(len(b.user.GetForegroundWindow.calls),1);self.assertEqual(len(b.user.GetAncestor.calls),1)


class NativeFailureBoundary(unittest.TestCase):
    def load(self): return FailureDiagnosticPolicy().load()
    def test_64bit_gui_layout_query_only_rights_and_native_handle_cleanup(self):
        m=self.load();self.assertEqual(C.sizeof(m.GuiThreadInfo),72)
        self.assertEqual(m.GuiThreadInfo.hwndCapture.offset,24)
        user,kernel=Library(),Library();c=Clock();probe=m.NativeFailureProbe(1.5,c,user=user,kernel=kernel)
        handle=2**48;kernel.OpenProcess.action=lambda rights,inherit,pid:handle
        self.assertEqual(probe.open_process(55),handle)
        self.assertEqual(kernel.OpenProcess.calls,[(0x00101000,False,55)])
        self.assertIs(kernel.OpenProcess.restype,C.c_void_p)
        self.assertIs(user.GetGUIThreadInfo.argtypes[1]._type_,m.GuiThreadInfo)
        self.assertTrue(probe.close_process(handle));self.assertEqual(kernel.CloseHandle.calls,[(handle,)])
        self.assertFalse({'SetForegroundWindow','SetFocus','AttachThreadInput','SendMessageW','SendInput','TerminateProcess'} & (user.__dict__.keys()|kernel.__dict__.keys()))
    def test_native_gui_preserves_high_handles_flags_and_api_failure(self):
        m=self.load();user,kernel=Library(),Library();c=Clock();probe=m.NativeFailureProbe(1.5,c,user=user,kernel=kernel)
        def gui(tid,value):
            value._obj.flags=20;value._obj.hwndCapture=2**48;return 1
        user.GetGUIThreadInfo.action=gui;row=probe.gui_thread(9)
        self.assertEqual(row['hwndCapture'],2**48);self.assertEqual(row['flags'],20)
        user.GetGUIThreadInfo.action=lambda *args:0
        with self.assertRaises(OSError):probe.gui_thread(9)
    def test_native_retained_handle_measures_pid_filetime_image_and_live_wait(self):
        m=self.load();user,kernel=Library(),Library();c=Clock();probe=m.NativeFailureProbe(1.5,c,user=user,kernel=kernel)
        handle=2**48;kernel.GetProcessId.action=lambda h:55;kernel.WaitForSingleObject.action=lambda h,t:258
        def times(h,created,*rest):
            created._obj.high=123;created._obj.low=456;return 1
        kernel.GetProcessTimes.action=times
        def image(h,flags,buffer,size):
            self.assertEqual(size._obj.value,4096);buffer.value='C:/foreign.exe';size._obj.value=14;return 1
        kernel.QueryFullProcessImageNameW.action=image;row=probe.process(handle)
        self.assertEqual(row,dict(pid=55,handleValue=handle,creationTime=(123<<32)|456,image='C:/foreign.exe',waitResult=258))
        self.assertEqual(kernel.WaitForSingleObject.calls,[(handle,0)])
        self.assertTrue(all(v[0]==handle for fn in (kernel.GetProcessId,kernel.GetProcessTimes,kernel.QueryFullProcessImageNameW) for v in fn.calls))
    def test_native_timeout_prevents_further_calls_and_is_reported_at_exact_boundary(self):
        m=self.load();user,kernel=Library(),Library();c=Clock();probe=m.NativeFailureProbe(1.5,c,user=user,kernel=kernel)
        def late():c.now=1.5;return 99
        user.GetForegroundWindow.action=late
        row=m.collect_failure_diagnostics(11,77,9,99,clock=c,probe=probe)
        self.assertTrue(row['deadlineExpired']);self.assertFalse(row['withinBudget'])
        self.assertEqual(user.GetAncestor.calls,[]);self.assertEqual(kernel.OpenProcess.calls,[])
    def test_same_python_process_title_is_skipped_without_message_path(self):
        import os
        m=self.load();user,kernel=Library(),Library();c=Clock();probe=m.NativeFailureProbe(1.5,c,user=user,kernel=kernel)
        user.GetWindowThreadProcessId.action=lambda hwnd,pid:setattr(pid._obj,'value',os.getpid()) or 9
        result=probe.caption(11)
        self.assertEqual(result['titleState'],'skipped-same-observer-process')
        self.assertEqual(user.GetWindowTextW.calls,[])

if __name__=='__main__':unittest.main()
