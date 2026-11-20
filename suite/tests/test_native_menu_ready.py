"""Synthetic, read-only startup readiness; no Windows input or environment."""
import ctypes
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

E2E=Path(__file__).resolve().parents[1]/'e2e'
sys.path.insert(0,str(E2E))


def load_smoke():
    spec=importlib.util.spec_from_file_location('native_ready_under_test',E2E/'native_menu_smoke.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class Clock:
    def __init__(self):self.value=10.;self.pauses=[]
    def __call__(self):return self.value
    def pause(self,seconds):self.pauses.append(seconds);self.value+=seconds


class User:
    def __init__(self,clock):
        self.clock=clock;self.hints=[0,1];self.pids={11:7,55:7,56:8}
        self.threads={11:70,55:70,56:80};self.parents={11:0,55:11,56:55}
        self.visible=True;self.enabled=True;self.iconic=False;self.foreground=11
        self.active=11;self.capture=0;self.menu=0;self.flags=0;self.on_hint=None
        self.reads=0
    def IsWindow(self,hwnd):return hwnd in self.pids
    def IsWindowVisible(self,hwnd):return self.visible
    def IsWindowEnabled(self,hwnd):return self.enabled
    def IsIconic(self,hwnd):return self.iconic
    def GetAncestor(self,hwnd,mode):return 11 if mode==2 else self.parents[hwnd]
    def GetWindowThreadProcessId(self,hwnd,pointer):
        if pointer is not None:ctypes.cast(pointer,ctypes.POINTER(ctypes.c_uint32))[0]=self.pids[hwnd]
        return self.threads[hwnd]
    def GetForegroundWindow(self):return self.foreground
    def GetPropW(self,hwnd,name):
        if hwnd!=11 or name!='OpenGeul.Office.NativeMenuReady':raise AssertionError('Unexpected property')
        self.reads+=1
        value=self.hints.pop(0) if len(self.hints)>1 else self.hints[0]
        if self.on_hint:self.on_hint()
        return value


class Probe:
    def __init__(self,user,clock,deadline):
        self.user=user;self.clock=clock;self.deadline=deadline;self.on_snapshot=None
        self.shell=dict(pid=7,handleValue=17,creationTime=20,image='/suite/OpenGeul.Office.exe',waitResult=258)
        self.engine=dict(pid=8,handleValue=18,creationTime=30,image='/suite/Office/program/soffice.bin',waitResult=258)
    def _call(self,function,*args):
        if self.clock()>=self.deadline:raise AssertionError('Expired synthetic query')
        value=function(*args)
        if self.clock()>=self.deadline:raise AssertionError('Late synthetic query')
        return value
    def process_snapshot(self,process):
        if self.on_snapshot:self.on_snapshot()
        return dict(self.shell if process._handle==17 else self.engine)


class NativeMenuReadyTests(unittest.TestCase):
    def setUp(self):
        self.smoke=load_smoke();self.session=self.smoke.WindowsSession(Path('/suite'),Path('/fixtures'),Path('/output'),'base')
        self.clock=Clock();self.deadline=10.2;self.user=User(self.clock);self.probe=Probe(self.user,self.clock,self.deadline)
        self.session.process=NS(pid=7,_handle=17,poll=lambda:None)
        self.session.engine=NS(handle=18,creation_time=30,exited=lambda seconds:False)
        self.session.hwnd=11;self.session.parent=55;self.session.child=56;self.session.office_pid=8
        self.session.api=NS(user=self.user,attachment=lambda hwnd:(55,56,8),
            query_gui_thread_info=lambda thread:NS(hwndActive=self.user.active,hwndCapture=self.user.capture,
                hwndMenuOwner=self.user.menu,flags=self.user.flags))
        self.session._opening_focus_identity=(7,17,18,30,11,55,56,8)
        self.record=dict(windowActivations=[dict(originalProcess=dict(self.probe.shell))],
            nativeArchiveGeneration={key:self.probe.engine[key] for key in ('pid','creationTime','image')},
            openingFocusObservations=[dict(phaseCode=3,hostGui=dict(threadId=70),engineGui=dict(threadId=80))])
        self.method=getattr(self.session,'_await_native_menu_ready',None)
        self.assertTrue(callable(self.method),'Original startup deadline readiness gate is missing')
    def await_ready(self):
        return self.method(self.record,self.deadline,probe=self.probe,clock=self.clock,pause=self.clock.pause)

    def test_same_original_generation_can_become_ready_inside_remaining_budget(self):
        self.await_ready();result=self.record['nativeMenuReadiness']
        self.assertEqual(result['completed'],1);self.assertEqual(result['samples'],2)
        self.assertEqual(result['first']['readyHint'],0);self.assertEqual(result['last']['readyHint'],1)
        self.assertEqual(self.clock.pauses,[.05]);self.assertEqual(result['acceptanceEligible'],0)
    def test_ready_hint_is_not_editor_focus_or_native_menu_success(self):
        self.user.hints=[1];self.await_ready()
        self.assertFalse(self.record.get('nativeMenuVerified',False))
        self.assertNotIn('editorFocusReadiness',self.record)
    def test_no_remaining_budget_performs_no_query_and_cannot_restart150_seconds(self):
        self.clock.value=self.deadline
        with self.assertRaises(AssertionError):self.await_ready()
        self.assertEqual(self.user.reads,0);self.assertEqual(self.clock.pauses,[])
        self.assertEqual(self.record['nativeMenuReadiness']['completed'],0)
    def test_unready_at_deadline_is_failure_without_input_or_unbounded_polling(self):
        self.user.hints=[0]
        with self.assertRaises(AssertionError):self.await_ready()
        result=self.record['nativeMenuReadiness']
        self.assertEqual(result['completed'],0);self.assertLessEqual(result['samples'],3001)
        self.assertGreaterEqual(self.clock.value,self.deadline)
    def test_late_ready_one_is_not_accepted(self):
        self.user.hints=[1];self.user.on_hint=lambda:setattr(self.clock,'value',11.)
        with self.assertRaises(AssertionError):self.await_ready()
        self.assertEqual(self.record['nativeMenuReadiness']['completed'],0)
    def test_original_process_generation_image_and_handle_changes_are_fatal(self):
        for change in ('shell-birth','engine-birth','shell-image','engine-image','shell-handle','engine-handle'):
            with self.subTest(change=change):
                self.setUp();self.user.hints=[0,1]
                def change_after_hint():
                    if change=='shell-birth':self.probe.shell['creationTime']=21
                    elif change=='engine-birth':self.probe.engine['creationTime']=31
                    elif change=='shell-image':self.probe.shell['image']='/other.exe'
                    elif change=='engine-image':self.probe.engine['image']='/other.exe'
                    elif change=='shell-handle':self.session.process._handle=19
                    else:self.session.engine.handle=19
                self.user.on_hint=change_after_hint
                with self.assertRaises(AssertionError):self.await_ready()
                self.assertEqual(self.record['nativeMenuReadiness']['completed'],0)
    def test_original_exports_parent_pid_and_thread_changes_are_fatal(self):
        for change in ('exports','parent','pid','thread'):
            with self.subTest(change=change):
                self.setUp()
                def change_after_hint():
                    if change=='exports':self.session.api.attachment=lambda hwnd:(55,57,8)
                    elif change=='parent':self.user.parents[56]=11
                    elif change=='pid':self.user.pids[56]=9
                    else:self.user.threads[56]=81
                self.user.on_hint=change_after_hint
                with self.assertRaises(AssertionError):self.await_ready()
                self.assertEqual(self.record['nativeMenuReadiness']['completed'],0)

    def test_thread_change_since_last_opening_observation_is_fatal_on_first_sample(self):
        self.user.threads[56]=81
        with self.assertRaises(AssertionError):self.await_ready()
        self.assertEqual(self.user.reads,0)

    def test_stalled_clock_and_pause_still_stop_at_fixed_sample_cap(self):
        self.user.hints=[0]
        self.clock.pause=lambda seconds:None
        with self.assertRaises(AssertionError):self.await_ready()
        self.assertEqual(self.record['nativeMenuReadiness']['samples'],3001)
        self.assertEqual(self.record['nativeMenuReadiness']['stageCode'],6)
    def test_foreign_foreground_disabled_modal_capture_and_menu_are_not_waited_away(self):
        for change,value in (('foreground',99),('enabled',False),('active',99),('capture',99),('menu',99),('flags',4)):
            with self.subTest(change=change):
                self.setUp();setattr(self.user,change,value)
                with self.assertRaises(AssertionError):self.await_ready()
                self.assertEqual(self.user.reads,0);self.assertEqual(self.clock.pauses,[])
    def test_hint1_does_not_bypass_after_join_ownership_check(self):
        self.user.hints=[1];self.user.on_hint=lambda:setattr(self.user,'foreground',99)
        with self.assertRaises(AssertionError):self.await_ready()
        self.assertEqual(self.record['nativeMenuReadiness']['completed'],0)
    def test_caret_blink_flag_is_not_a_menu_or_modal_mode(self):
        self.user.flags=1;self.user.hints=[1];self.await_ready()
        self.assertEqual(self.record['nativeMenuReadiness']['completed'],1)
    def test_bad_ready_property_shape_is_fatal(self):
        for value in (True,2,'1'):
            with self.subTest(shape=type(value).__name__):
                self.setUp();self.user.hints=[value]
                with self.assertRaises(AssertionError):self.await_ready()
                self.assertEqual(self.record['nativeMenuReadiness']['completed'],0)
    def test_retained_result_contains_only_closed_numeric_summary_not_images(self):
        self.await_ready();result=self.record['nativeMenuReadiness']
        def numeric(value):
            if type(value) is dict:
                for child in value.values():numeric(child)
            else:self.assertIs(type(value),int)
        numeric(result)
        self.assertLess(len(str(result)),4096)


if __name__=='__main__':unittest.main()
