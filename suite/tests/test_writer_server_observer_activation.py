"""Real typed caption port with synthetic Win32 calls; never Windows proof."""
import copy
import ctypes as C
import importlib
import contextlib
import io
from unittest import mock
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
import test_writer_server_observer_prepare_native as typed
import test_writer_server_observer_runner_composition as composed
import suite_window_activation as physical


class Function:
    def __init__(self, action): self.action, self.calls = action, []
    def __call__(self, *args): self.calls.append(args); return self.action(*args)


class NativeFixture(typed.System):
    def __init__(self, components):
        super().__init__()
        self.c = components
        self.host, self.thread, self.host_pid, self.birth, self.host_tid = 201, 203, 101, 111, 501
        self.engine_pid, self.engine_tid = 401, 611
        self.home, self.document, self.panel, self.child, self.descendant = 500, 600, 610, 601, 602
        self.windows = [self.home, self.document]
        self.facts = {self.home:(101,501,0,500),self.document:(101,501,0,600),
            self.panel:(101,501,600,600),self.child:(401,611,610,600),self.descendant:(401,611,601,600)}
        self.props = {(600,'OpenGeul.Office.ParentHwnd'):610,(600,'OpenGeul.Office.ChildHwnd'):601}
        self.foreground, self.focus, self.host_focus = 999, 0, 600
        self.capture = self.menu = self.flags = 0
        self.host_capture = self.host_menu = self.host_flags = 0
        self.hidden, self.disabled = set(), set()
        self.covered = self.iconic = self.cloaked = self.swapped = False
        self.hit_test, self.context, self.cursor = 2, 123, [512, 400]
        self.caption_state = 0
        self.held_key = None; self.down = False; self.inserts = [2]
        self.after_move = self.after_send = self.after_dpi = None
        self.fail_restore = False
        self.after_restore = None
        self.user.GetGUIThreadInfo = Function(self.gui)
        self.kernel.QueryFullProcessImageNameW = Function(self.process_image)
        self.kernel.GetProcessId = Function(lambda handle:components.api.identity(typed.number(handle))[0])
        self.kernel.GetProcessTimes = Function(lambda *args:1)
        extra = {'IsWindowVisible':lambda hwnd:int(typed.number(hwnd) not in self.hidden),
            'IsWindowEnabled':lambda hwnd:int(typed.number(hwnd) not in self.disabled),
            'IsIconic':lambda hwnd:int(self.iconic), 'GetWindowRect':self.rectangle,
            'GetTitleBarInfo':self.caption, 'WindowFromPhysicalPoint':lambda point:888 if self.covered else self.document,
            'SetPhysicalCursorPos':self.move, 'GetPhysicalCursorPos':self.position,
            'SetThreadDpiAwarenessContext':self.set_context,'GetThreadDpiAwarenessContext':lambda:self.context,
            'AreDpiAwarenessContextsEqual':lambda a,b:a==b,'SendMessageTimeoutW':self.hit,
            'GetAsyncKeyState':lambda key:0x8000 if key==self.held_key or self.down and key==(2 if self.swapped else 1) else 0,
            'GetSystemMetrics':lambda key:int(self.swapped), 'SendInput':self.send}
        for name, fn in extra.items(): setattr(self.user,name,Function(fn))
        self.dwm=NS(DwmGetWindowAttribute=Function(self.dwm_attribute))
        self.prep=typed.M.PreparationNativeApi(components.api,kernel=self.kernel,user=self.user)
        components.prep=self.prep

    def gui(self, thread, output):
        tid=typed.number(thread); assert tid in (self.host_tid,self.engine_tid)
        info=C.cast(output,C.POINTER(typed.M.GuiThreadInfo)).contents
        assert info.size==72
        host=tid==self.host_tid
        info.active=self.document if self.foreground==self.document else 0
        info.focus=self.host_focus if host else self.focus
        info.capture=self.host_capture if host else self.capture
        info.menu=self.host_menu if host else self.menu
        info.flags=self.host_flags if host else self.flags
        return 1

    def process_image(self, handle, flags, output, length):
        raw=str(self.c.api.images[typed.number(handle)]).encode('utf-16-le')
        array=C.cast(output,C.POINTER(C.c_uint16))
        for i in range(len(raw)//2):array[i]=int.from_bytes(raw[2*i:2*i+2],'little')
        C.cast(length,C.POINTER(C.c_uint32))[0]=len(raw)//2
        return 1

    def rectangle(self, hwnd, output):
        assert typed.number(hwnd)==self.document
        output._obj.left,output._obj.top,output._obj.right,output._obj.bottom=0,0,1024,720
        return 1
    def caption(self, hwnd, output):
        assert typed.number(hwnd)==self.document
        output._obj.rectangle=physical.Rect(8,8,1016,32)
        output._obj.states[0]=self.caption_state
        return 1
    def dwm_attribute(self, hwnd, attribute, output, size):
        assert typed.number(hwnd)==self.document and attribute==14
        C.cast(output,C.POINTER(C.c_uint32))[0]=int(self.cloaked)
        return 0
    def hit(self, hwnd, message, wparam, lparam, flags, milliseconds, output):
        assert typed.number(hwnd)==self.document and message==0x84 and 0<milliseconds<=200
        output._obj.value=self.hit_test
        return 1
    def move(self, x, y):
        self.cursor=[x,y]
        if self.after_move:self.after_move()
        return 1
    def position(self, output):output._obj.x,output._obj.y=self.cursor;return 1
    def set_context(self, context):
        if context==123 and self.fail_restore:return 0
        previous,self.context=self.context,context
        if context==-4 and self.after_dpi:self.after_dpi()
        if context==123 and self.after_restore:self.after_restore()
        return previous
    def send(self, count, payload, size):
        assert size==40 and count in (1,2)
        primary=(8,16) if self.swapped else (2,4)
        self.c.api.calls.append('caption-send-'+str(count))
        assert [payload[i].data.mouse.flags for i in range(count)]==list(primary if count==2 else primary[1:])
        result=self.inserts.pop(0) if self.inserts else count
        if isinstance(result,BaseException):raise result
        if count==2 and result==1:self.down=True
        elif result==count:
            self.down=False;self.foreground=self.document;self.focus=self.host_focus=self.child
        if self.after_send:self.after_send(count,result)
        return result


class CaptionPreparationTests(unittest.TestCase):
    def setUp(self): composed.runner._CASE_STARTED=False;composed.runner._PENDING_CASES.clear()
    def tearDown(self): composed.runner._CASE_STARTED=False;composed.runner._PENDING_CASES.clear()
    def module(self):
        try:return importlib.import_module('writer_server_observer_activation')
        except ModuleNotFoundError:self.fail('Writer owned-caption profile is absent')
    def fixture(self, folder):
        module=self.module();old,inputs,c,_=composed.setup(folder);system=NativeFixture(c)
        def factory(budget):return module.NativeCaptionProbe(budget,prep=c.prep,user=system.user,kernel=system.kernel,dwm=system.dwm)
        profile=module.OwnedCaptionPreparation(probe_factory=factory)
        obj=composed.runner.DedicatedWriterRunner(c,read_value=old.read_value,pause=old.pause,nonce=71,
            admission_profile='owned-peer-before-first-admission-v1',activation_profile=profile)
        return obj,inputs,c,system,profile
    def run_case(self, change=None):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,system,profile=self.fixture(folder)
            if change:change(c,system)
            report=obj.execute(inputs)
        return report,c,system,profile

    def test_real_typed_adapter_one_click_and_original_runtime_intervals(self):
        report,c,system,_=self.run_case();a=report['captionActivation']
        self.assertEqual(report['failureCode'],0)
        self.assertEqual(c.api.calls.count('caption-send-2'),1)
        self.assertEqual(a['inputCalls'],1);self.assertEqual(a['requestedInputs'],2);self.assertEqual(a['insertedInputs'],2)
        self.assertEqual(report['preparation']['inputCount'],2);self.assertEqual(report['preparation']['activationCount'],1)
        self.assertTrue(a['eligible']);self.assertTrue(a['dpiRestored']);self.assertTrue(a['cleanupComplete'])
        self.assertEqual(system.context,123)
        self.assertFalse({'SetForegroundWindow','SetFocus','AttachThreadInput'} & system.user.__dict__.keys())
        self.assertTrue(report['runtime']['remote_retired']);self.assertFalse(report['normalAcceptance'])
        self.assertEqual(report['preparation']['cutoffQpc']-report['preparation']['startQpc'],55000)
        self.assertEqual(report['preparation']['deadlineQpc']-report['preparation']['startQpc'],60000)

    def test_ready_or_already_foreground_performs_no_pointer_effect(self):
        for ready in (False,True):
            composed.runner._CASE_STARTED=False
            def change(c,s):
                s.foreground=s.document
                s.focus=s.host_focus=s.child if ready else s.document
            report,c,s,_=self.run_case(change)
            a=report['captionActivation'];self.assertEqual(a['inputCalls'],0);self.assertEqual(a['pointerMoves'],0)
            self.assertEqual(report['preparation']['inputCount'],0);self.assertEqual(s.user.SendInput.calls,[])
            self.assertEqual(a['reasonCode'],1 if ready else 2)

    def test_unavailable_or_foreign_hit_is_zero_input(self):
        for name in ('covered','iconic','cloaked'):
            composed.runner._CASE_STARTED=False
            report,c,s,_=self.run_case(lambda c,s:setattr(s,name,True))
            self.assertNotEqual(report['failureCode'],0);self.assertEqual(s.user.SendInput.calls,[])
            self.assertEqual(report['preparation']['inputCount'],0)

    def test_disabled_hidden_or_modal_peer_is_zero_input(self):
        for collection in ('hidden','disabled'):
            for hwnd in (600,610,601):
                composed.runner._CASE_STARTED=False
                report,c,s,_=self.run_case(lambda c,s:getattr(s,collection).add(hwnd))
                self.assertNotEqual(report['failureCode'],0);self.assertEqual(s.user.SendInput.calls,[])

    def test_both_gui_threads_menu_capture_and_flags_block(self):
        for name in ('capture','menu','flags','host_capture','host_menu','host_flags'):
            composed.runner._CASE_STARTED=False
            report,c,s,_=self.run_case(lambda c,s:setattr(s,name,1))
            self.assertNotEqual(report['failureCode'],0);self.assertEqual(s.user.SendInput.calls,[])

    def test_other_owned_control_selection_is_not_forced(self):
        def change(c,s):s.facts[777]=(s.host_pid,s.host_tid,s.document,s.document);s.host_focus=777
        report,c,s,_=self.run_case(change)
        self.assertNotEqual(report['failureCode'],0);self.assertEqual(s.user.SendInput.calls,[])

    def test_geometry_or_hit_change_after_move_prevents_input(self):
        for covered in (True,False):
            composed.runner._CASE_STARTED=False
            def change(c,s):
                s.after_move=lambda:setattr(s,'covered',True) if covered else setattr(s,'hit_test',1)
            report,c,s,_=self.run_case(change)
            self.assertNotEqual(report['failureCode'],0);self.assertEqual(s.user.SendInput.calls,[])
            self.assertTrue(report['captionActivation']['dpiRestored'])

    def test_held_button_or_modifier_prevents_input(self):
        for key in (1,2,4,5,6,0x10,0x11,0x12,0x5b,0x5c):
            composed.runner._CASE_STARTED=False
            report,c,s,_=self.run_case(lambda c,s:setattr(s,'held_key',key))
            self.assertNotEqual(report['failureCode'],0);self.assertEqual(s.user.SendInput.calls,[])

    def test_swapped_primary_uses_exact_matching_down_up(self):
        report,c,s,_=self.run_case(lambda c,s:setattr(s,'swapped',True))
        self.assertEqual(report['failureCode'],0);self.assertEqual(c.api.calls.count('caption-send-2'),1)

    def test_known_partial_prefix_has_only_one_guarded_release(self):
        report,c,s,_=self.run_case(lambda c,s:setattr(s,'inserts',[1,1]))
        self.assertNotEqual(report['failureCode'],0);a=report['captionActivation']
        self.assertEqual([call[0] for call in s.user.SendInput.calls],[2,1]);self.assertEqual(a['insertedInputs'],1)
        self.assertEqual(a['releaseCalls'],1);self.assertEqual(a['releaseInsertedInputs'],1)
        self.assertEqual(report['preparation']['inputCount'],2);self.assertEqual(a['pendingInputPrefix'],0)

    def test_unknown_native_return_is_never_zero_or_replayed(self):
        report,c,s,_=self.run_case(lambda c,s:setattr(s,'inserts',[OSError()]))
        a=report['captionActivation'];self.assertEqual(len(s.user.SendInput.calls),1)
        self.assertIsNone(a['insertedInputs']);self.assertIsNone(report['preparation']['inputCount'])
        self.assertFalse(a['cleanupComplete']);self.assertGreater(report['pendingRetainedCount'],0)

    def test_release_guard_loss_keeps_pending_prefix_without_foreign_input(self):
        def change(c,s):
            s.inserts=[1,1];s.after_send=lambda count,result:setattr(s,'covered',True) if count==2 else None
        report,c,s,_=self.run_case(change);a=report['captionActivation']
        self.assertEqual([call[0] for call in s.user.SendInput.calls],[2]);self.assertEqual(a['pendingInputPrefix'],1)
        self.assertFalse(a['cleanupComplete']);self.assertGreater(report['pendingRetainedCount'],0)

    def test_late_partial_return_never_sends_after_work_cutoff(self):
        def change(c,s):
            s.inserts=[1,1];s.after_send=lambda count,result:setattr(c.clock,'value',c.clock.value+56000)
        report,c,s,_=self.run_case(change);a=report['captionActivation']
        self.assertEqual([call[0] for call in s.user.SendInput.calls],[2]);self.assertEqual(a['pendingInputPrefix'],1)
        self.assertEqual(a['releaseCalls'],0);self.assertFalse(a['cleanupComplete'])
        self.assertFalse(report['preparation']['runtimeEntered'] is True)

    def test_late_dpi_entry_retains_and_restores_original_context(self):
        def change(c,s):s.after_dpi=lambda:setattr(c.clock,'value',c.clock.value+56000)
        report,c,s,_=self.run_case(change);a=report['captionActivation']
        self.assertEqual(s.context,123);self.assertTrue(a['dpiEntered']);self.assertTrue(a['dpiRestored'])
        self.assertEqual(s.user.SendInput.calls,[]);self.assertEqual(a['pendingDpiContext'],0)

    def test_failed_dpi_restore_is_not_clean_or_forgotten(self):
        report,c,s,_=self.run_case(lambda c,s:setattr(s,'fail_restore',True));a=report['captionActivation']
        self.assertFalse(a['dpiRestored']);self.assertEqual(a['pendingDpiContext'],1)
        self.assertFalse(report['preparation']['cleanupComplete']);self.assertGreater(report['pendingRetainedCount'],0)

    def test_original_attachment_change_before_input_is_zero_input(self):
        def change(c,s):s.after_move=lambda:setattr(s,'changed_exports',True)
        report,c,s,_=self.run_case(change)
        self.assertNotEqual(report['failureCode'],0);self.assertEqual(s.user.SendInput.calls,[])

    def test_existing_default_strict_profile_does_not_change_or_invent_activation(self):
        self.module()
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=composed.setup(folder);report=obj.execute(inputs)
        self.assertEqual(report['failureCode'],0);self.assertTrue(all(v is None for v in report['captionActivation'].values()))
        self.assertEqual(report['preparation']['activationCount'],0);self.assertEqual(report['preparation']['inputCount'],0)

    def test_new_source_coordinate_is_fixed_and_unknown_focus_stays_null(self):
        def change(c,s):
            def fail(*args,**kwargs):raise typed.M.PreparationError(typed.M.PreparationCode.NATIVE)
            c.prep.focus_snapshot=fail
        report,c,s,_=self.run_case(change)
        self.assertIsNone(report['captionActivation']['foregroundBefore'])
        self.assertIsNone(report['captionActivation']['readyBefore'])
        self.assertEqual(s.user.SendInput.calls,[])
        composed.runner._CASE_STARTED=False;composed.runner._PENDING_CASES.clear()
        report,c,s,_=self.run_case(lambda c,s:setattr(s,'covered',True))
        self.assertEqual(report['preparation']['preparationFailureSourceCode'],8)
        altered=copy.deepcopy(report);altered['captionActivation']={key:None for key in altered['captionActivation']}
        with self.assertRaises(composed.runner.RunnerFailure):composed.runner.validate_public_report(altered)

    def test_probe_does_not_rebind_or_query_original_process_image_port(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,s,profile=self.fixture(folder)
            signature=c.prep._image.argtypes
            report=obj.execute(inputs)
            self.assertIs(c.prep._image.argtypes,signature)
        self.assertEqual(report['failureCode'],0)
        self.assertEqual(s.kernel.GetProcessId.calls,[])
        self.assertEqual(s.kernel.GetProcessTimes.calls,[])

    def test_release_unknown_or_zero_retains_pending_and_truthful_input_count(self):
        for value in (0,OSError()):
            composed.runner._CASE_STARTED=False;composed.runner._PENDING_CASES.clear()
            report,c,s,_=self.run_case(lambda c,s:setattr(s,'inserts',[1,value]))
            a=report['captionActivation']
            self.assertEqual([call[0] for call in s.user.SendInput.calls],[2,1])
            self.assertEqual(a['pendingInputPrefix'],1);self.assertFalse(a['cleanupComplete'])
            self.assertEqual(report['preparation']['inputCount'],1 if type(value) is int else None)

    def test_successful_send_returned_late_is_recorded_without_further_input(self):
        def change(c,s):s.after_send=lambda count,result:setattr(c.clock,'value',c.clock.value+56000)
        report,c,s,_=self.run_case(change)
        self.assertEqual(report['captionActivation']['insertedInputs'],2)
        self.assertEqual(report['preparation']['inputCount'],2)
        self.assertEqual([call[0] for call in s.user.SendInput.calls],[2])
        self.assertFalse(report['preparation']['runtimeEntered'] is True)

    def test_primary_and_release_guards_recheck_original_retained_generation(self):
        for partial in (False,True):
            composed.runner._CASE_STARTED=False;composed.runner._PENDING_CASES.clear()
            def change(c,s):
                native=c.api.identity
                def stale():c.api.identity=lambda h:(native(h)[0],native(h)[1]+1) if h==301 else native(h)
                if partial:
                    s.inserts=[1,1];s.after_send=lambda count,result:stale() if count==2 else None
                else:s.after_move=stale
            report,c,s,_=self.run_case(change)
            self.assertEqual([call[0] for call in s.user.SendInput.calls],[2] if partial else [])
            self.assertNotEqual(report['failureCode'],0)

    def test_exact_profile_type_and_cli_opt_in_are_explicit(self):
        module=self.module();runner=composed.runner
        for value in (True,1,'one-owned-caption-v1',object()):
            with self.assertRaises(runner.RunnerFailure):runner.DedicatedWriterRunner(object(),activation_profile=value)
        for enabled in (False,True):
            runner._CASE_STARTED=False;runner._PENDING_CASES.clear()
            with tempfile.TemporaryDirectory() as folder:
                obj,inputs,c,s,profile=self.fixture(folder)
                prepared=Path(folder)/'prepared.json';prepared.write_text('{}')
                flags={'output':inputs.output,'baseline':inputs.baseline,'artifact':inputs.artifact,
                    'diagnostic-lock':inputs.diagnostic_lock,'source-lock':inputs.source_lock,
                    'expected-suite-source-commit':inputs.expected_suite_source_commit,'prepared-library':prepared,
                    'host-python':inputs.host_python,'helper-script':inputs.helper_script,'windows':inputs.windows,
                    'work-root':inputs.work_root,'report':Path(folder)/'report.numeric.json'}
                args=[v for key,value in flags.items() for v in ('--'+key,str(value))]
                args+=['--admission-profile','owned-peer-before-first-admission-v1']
                if enabled:args+=['--activation-profile',module.PROFILE]
                else:s.foreground=s.document;s.focus=s.host_focus=s.child
                c.ConsoleProfile=lambda:None
                synthetic={key:obj.read_value(key) for key in ('SystemRoot','WINDIR','USERPROFILE','APPDATA','LOCALAPPDATA')}
                out=io.StringIO()
                # Keep the exact class while replacing only its probe factory default.
                original=module.OwnedCaptionPreparation.__init__
                def init(self):original(self,probe_factory=profile._factory)
                with mock.patch.object(runner,'NativeComponents',lambda:c),mock.patch.object(runner.os,'environ',synthetic), \
                        mock.patch.object(runner.secrets,'randbelow',lambda n:70), \
                        mock.patch.object(module.OwnedCaptionPreparation,'__init__',init),contextlib.redirect_stdout(out):
                    code=runner.main(args)
                result=json.loads(out.getvalue());self.assertEqual(code,0)
                self.assertEqual(result['captionActivation']['enabled'],True if enabled else None)
                self.assertEqual(len(s.user.SendInput.calls),int(enabled))

    def test_caption_availability_matches_the_existing_guarded_leaf_mask(self):
        for state in (0,0x100000,1,0x8000,0x10000):
            composed.runner._CASE_STARTED=False;composed.runner._PENDING_CASES.clear()
            report,c,s,_=self.run_case(lambda c,s:setattr(s,'caption_state',state))
            self.assertEqual(len(s.user.SendInput.calls),0 if state & (1|0x8000|0x10000) else 1)

    def test_native_error_content_is_never_read_or_serialized(self):
        class Poison(OSError):
            def __str__(self):raise AssertionError()
            def __repr__(self):raise AssertionError()
            def __getattribute__(self,name):
                if name in ('args','__cause__','__context__'):raise AssertionError()
                return super().__getattribute__(name)
        report,c,s,_=self.run_case(lambda c,s:setattr(s,'inserts',[Poison('SYNTHETIC_PRIVATE')]))
        self.assertNotIn('SYNTHETIC_PRIVATE',json.dumps(report))
        self.assertIsNone(report['preparation']['inputCount'])
        self.assertGreater(report['pendingRetainedCount'],0)

    def test_late_restore_return_does_not_start_queries_after_cleanup_deadline(self):
        def change(c,s):s.after_restore=lambda:setattr(c.clock,'value',c.clock.value+61000)
        report,c,s,_=self.run_case(change);a=report['captionActivation']
        self.assertEqual(len(s.user.GetThreadDpiAwarenessContext.calls),1)
        self.assertEqual(report['preparation']['preparationFailureCode'],int(typed.M.PreparationCode.BUDGET))
        self.assertEqual(s.context,123);self.assertEqual(a['pendingDpiContext'],1)
        self.assertFalse(a['cleanupComplete']);self.assertGreater(report['pendingRetainedCount'],0)

    def test_unknown_dpi_entry_return_is_pending_without_guessing_original_context(self):
        def change(c,s):
            def fail(context):raise OSError()
            s.user.SetThreadDpiAwarenessContext.action=fail
        report,c,s,_=self.run_case(change);a=report['captionActivation']
        self.assertEqual(len(s.user.SetThreadDpiAwarenessContext.calls),1)
        self.assertFalse(a['dpiEntered']);self.assertEqual(a['pendingDpiContext'],1)
        self.assertEqual(s.user.SendInput.calls,[]);self.assertFalse(a['cleanupComplete'])
        self.assertGreater(report['pendingRetainedCount'],0)

    def test_final_dpi_comparison_uses_original_deadline_and_preserves_primary(self):
        cases=((False,False,False),(True,True,False),(True,False,False),(True,True,True))
        for late,restored,primary in cases:
            composed.runner._CASE_STARTED=False;composed.runner._PENDING_CASES.clear()
            def change(c,s):
                calls=0
                def equal(a,b):
                    nonlocal calls
                    calls+=1
                    if calls==2:
                        if late:c.clock.value+=61000
                        return restored
                    return a==b
                s.user.AreDpiAwarenessContextsEqual.action=equal
                if primary:s.inserts=[0]
            report,c,s,_=self.run_case(change);a=report['captionActivation']
            expected=typed.M.PreparationCode.BUDGET if late and not primary else typed.M.PreparationCode.NATIVE
            with self.subTest(late=late,restored=restored,primary=primary):
                self.assertEqual(report['preparation']['preparationFailureCode'],int(expected))
                self.assertEqual(a['dpiRestored'],restored)
                self.assertEqual(a['pendingDpiContext'],int(not restored))
                self.assertFalse(a['cleanupComplete']);self.assertFalse(report['preparation']['cleanupComplete'])
                self.assertGreater(report['pendingRetainedCount'],0)
                self.assertEqual([call[0] for call in s.user.SendInput.calls],[2])
                self.assertEqual(report['preparation']['inputCount'],0 if primary else 2)
                self.assertEqual(len(s.user.SetThreadDpiAwarenessContext.calls),2)
                self.assertEqual(len(s.user.GetThreadDpiAwarenessContext.calls),2)
                self.assertEqual(len(s.user.AreDpiAwarenessContextsEqual.calls),2)

    def test_expired_dpi_cleanup_does_not_start_a_restore_or_input(self):
        def change(c,s):s.after_dpi=lambda:setattr(c.clock,'value',c.clock.value+61000)
        report,c,s,_=self.run_case(change);a=report['captionActivation']
        self.assertEqual([call[0] for call in s.user.SetThreadDpiAwarenessContext.calls],[-4])
        self.assertEqual(s.user.SendInput.calls,[])
        self.assertFalse(a['dpiRestored']);self.assertEqual(a['pendingDpiContext'],1)
        self.assertFalse(a['cleanupComplete']);self.assertGreater(report['pendingRetainedCount'],0)

    def test_unknown_cli_profile_fails_before_native_port_bootstrap(self):
        self.module();runner=composed.runner;calls=[]
        with tempfile.TemporaryDirectory() as folder:
            report=Path(folder)/'result.json'
            names=('output','baseline','artifact','diagnostic-lock','source-lock','expected-suite-source-commit',
                'prepared-library','host-python','helper-script','windows','work-root')
            args=[v for name in names for v in ('--'+name,'SYNTHETIC')]+['--report',str(report),
                '--activation-profile','unknown']
            out=io.StringIO()
            with mock.patch.object(runner,'NativeComponents',lambda:calls.append(1)),contextlib.redirect_stdout(out):
                code=runner.main(args)
        self.assertEqual(code,1);self.assertEqual(calls,[])
        self.assertTrue(all(v is None for v in json.loads(out.getvalue())['captionActivation'].values()))

    def test_report_requires_actual_pending_and_release_correlations(self):
        report,c,s,_=self.run_case(lambda c,s:setattr(s,'inserts',[1,1]))
        for changes in ({'releaseCalls':0}, {'pendingInputPrefix':1},
                {'dpiRestored':False}, {'stageCode':0}, {'reasonCode':1}):
            changed=copy.deepcopy(report);changed['captionActivation'].update(changes)
            with self.assertRaises(composed.runner.RunnerFailure):composed.runner.validate_public_report(changed)
        composed.runner._CASE_STARTED=False;composed.runner._PENDING_CASES.clear()
        report,c,s,_=self.run_case(lambda c,s:setattr(s,'inserts',[OSError()]))
        changed=copy.deepcopy(report);changed['captionActivation']['pendingInputPrefix']=0
        with self.assertRaises(composed.runner.RunnerFailure):composed.runner.validate_public_report(changed)

    def test_actual_report_rejects_unknown_bool_overflow_and_impossible_input_accounting(self):
        report,c,s,_=self.run_case()
        mutations=(('inputCalls',True),('insertedInputs',3),('releaseCalls',2),('pendingInputPrefix',-1),('extra',0))
        for field,value in mutations:
            altered=copy.deepcopy(report);altered['captionActivation'][field]=value
            with self.assertRaises(composed.runner.RunnerFailure):composed.runner.validate_public_report(altered)
        altered=copy.deepcopy(report);altered['preparation']['inputCount']=0
        with self.assertRaises(composed.runner.RunnerFailure):composed.runner.validate_public_report(altered)
        altered=copy.deepcopy(report);altered['captionActivation']['cleanupComplete']=False
        with self.assertRaises(composed.runner.RunnerFailure):composed.runner.validate_public_report(altered)


if __name__=='__main__':unittest.main()
