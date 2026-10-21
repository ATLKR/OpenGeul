"""Portable typed transport fakes; no actual Windows hooks or dispatch proof."""
import ctypes as C
import importlib.util
from pathlib import Path, PureWindowsPath
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'ascii_message_windows.py'


class Fn:
    def __init__(self, function): self.function = function
    def __call__(self, *args): return self.function(*args)


class AsciiMessageWindowsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(), 'Missing owned ASCII native controller transport')
        sys.path.insert(0, str(SOURCE.parent)); self.addCleanup(lambda: sys.path.remove(str(SOURCE.parent)))
        spec = importlib.util.spec_from_file_location('tested_ascii_message_windows', SOURCE)
        self.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.m)
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        from ascii_message_protocol import State, Event, MAGIC, VERSION, CAPACITY
        self.State, self.Event = State, Event
        self.raw = C.create_string_buffer(C.sizeof(State)); self.calls = []
        self.now = 100.; self.identity_ok = True; self.install_fail = None
        self.send_ok = True; self.ack = True; self.unhook_ok = True
        self.clock = lambda: self.now
        self.target = dict(pid=88, tid=99, hwnd=0x123456789, layout=0x04090409)
        self.record = {}; test = self
        class Kernel: pass
        class User: pass
        class Dll: _handle = 333
        self.kernel, self.user, self.dll = Kernel(), User(), Dll()
        self.kernel.CreateFileMappingW = Fn(lambda *a: self.note('create', 444))
        self.kernel.MapViewOfFile = Fn(lambda *a: self.note('map', C.addressof(self.raw)))
        self.kernel.UnmapViewOfFile = Fn(lambda *a: self.note('unmap', True))
        self.kernel.CloseHandle = Fn(lambda *a: self.note('close-map', True))
        self.kernel.FreeLibrary = Fn(lambda *a: self.note('free-library', True))
        self.kernel.GetCurrentProcessId = Fn(lambda: 77)
        self.kernel.GetCurrentThreadId = Fn(lambda: 66)
        self.user.RegisterWindowMessageW = Fn(lambda name: 0xc001 if 'Start' in name else 0xc002)
        def hook(kind, *args):
            self.calls.append(('install', kind))
            return 0 if self.install_fail == kind else 1000 + kind
        self.user.SetWindowsHookExW = Fn(hook)
        self.user.UnhookWindowsHookEx = Fn(lambda h: self.note(('unhook', h), self.unhook_ok))
        def send(hwnd, message, wp, lp, flags, timeout, result):
            self.calls.append(('message', hwnd, message, flags, timeout))
            state = self.State.from_address(C.addressof(self.raw))
            if self.ack:
                if message == 0xc001: state.recording = 1; state.ack = 1
                else: state.recording = 0; state.stopAck = 2
            return self.send_ok
        self.user.SendMessageTimeoutW = Fn(send)
        def read(pointer):
            address = C.cast(pointer, C.c_void_p).value
            self.calls.append(('acquire', address))
            return C.c_uint32.from_address(address).value
        def publish(pointer, value):
            address = C.cast(pointer, C.c_void_p).value
            self.calls.append(('publish', address, value))
            C.c_uint32.from_address(address).value = value
        self.dll.ReadWord, self.dll.PublishWord = Fn(read), Fn(publish)
        self.dll.StateSize = Fn(lambda: C.sizeof(State))
        self.dll.EventSize = Fn(lambda: C.sizeof(Event))
        self.dll.EventsOffset = Fn(lambda: State.events.offset)
        self.dll.HookCall, self.dll.HookGet = C.c_void_p(11), C.c_void_p(12)

    def note(self, value, result): self.calls.append(value); return result

    def identity(self):
        self.calls.append('identity')
        assert self.identity_ok, 'Original target generation changed'

    def transport(self):
        return self.m.MessageTransport(self.user, self.kernel, self.dll, self.target,
            123456, self.record, 101., self.clock, self.identity, nonce=123)

    def test_start_exact_thread_hooks_control_target_and_stop_disable_ack(self):
        t = self.transport(); t.start()
        state = self.State.from_address(C.addressof(self.raw))
        self.assertEqual(88, state.pid); self.assertEqual(99, state.tid)
        self.assertEqual(123456, state.engineCreationTime); self.assertEqual(1, state.command)
        self.assertEqual([('install', 4), ('install', 3)], [x for x in self.calls if isinstance(x, tuple) and x[0] == 'install'])
        self.assertEqual(0, t.arm(0)); self.assertEqual(1, state.armedEpoch)
        stop = t.stop(); self.assertTrue(stop['recordingStopped'])
        self.assertFalse(stop['remoteCallbackQuiescenceProved'])
        receipt = t.close(); self.assertEqual(2, receipt['unhookAttempts'])
        self.assertEqual(1, self.calls.count('unmap')); self.assertEqual(1, self.calls.count('free-library'))
        for row in [r for r in self.calls if isinstance(r, tuple) and r[0] == 'message']:
            self.assertEqual(self.target['hwnd'], row[1]); self.assertEqual(0x22, row[3]); self.assertLessEqual(row[4], 1000)

    def test_partial_hook_install_closes_only_admitted_hook_and_every_controller_resource(self):
        self.install_fail = 3; t = self.transport()
        with self.assertRaises(OSError): t.start()
        result = t.close()
        self.assertEqual(1, result['unhookAttempts'])
        self.assertEqual([('unhook', 1004)], [r for r in self.calls if isinstance(r, tuple) and r[0] == 'unhook'])
        self.assertTrue(result['controllerResourcesReleased'])

    def test_failed_or_unacknowledged_start_is_fatal_and_cleanup_once(self):
        for failure in ('send', 'ack'):
            with self.subTest(failure=failure):
                self.calls.clear(); self.send_ok = failure != 'send'; self.ack = failure != 'ack'
                t = self.transport()
                with self.assertRaises((OSError, AssertionError)): t.start()
                t.close(); t.close()
                self.assertEqual(2, len([r for r in self.calls if isinstance(r, tuple) and r[0] == 'unhook']))

    def test_generation_change_before_control_never_sends_inert_message(self):
        t = self.transport(); self.identity_ok = False
        with self.assertRaisesRegex(AssertionError, 'generation'): t.start()
        self.assertFalse(any(isinstance(r, tuple) and r[0] == 'message' for r in self.calls)); t.close()

    def test_expired_deadline_never_sends_start_or_stop_and_still_unhooks(self):
        t = self.transport(); t.start(); self.now = 101.
        with self.assertRaisesRegex(AssertionError, 'deadline'): t.stop()
        self.assertEqual(1, len([r for r in self.calls if isinstance(r, tuple) and r[0] == 'message']))
        self.assertEqual(2, t.close()['unhookAttempts'])

    def test_exact_fresh_control_timestamp_at_deadline_never_sends_control(self):
        t=self.transport(); t.start(); self.calls.clear()
        values=iter((100.,100.,100.,101.,101.,101.))
        t.clock=lambda:next(values,101.)
        with self.assertRaises(AssertionError): t._control(0xc002)
        self.assertFalse(any(isinstance(r,tuple) and r[0]=='message' for r in self.calls))
        t.close()

    def test_exact_hook_attempt_timestamp_at_deadline_never_installs_hook(self):
        t=self.transport()
        # Start has six earlier budget/identity reads before its first fresh
        # attempt timestamp; advancing exactly there must forbid acquisition.
        values=iter((100.,100.,100.,100.,100.,100.,101.,101.))
        t.clock=lambda:next(values,101.)
        with self.assertRaises(AssertionError): t.start()
        self.assertFalse(any(isinstance(r,tuple) and r[0]=='install' for r in self.calls))
        t.close()

    def test_late_registration_never_acquires_mapping_or_installs_hooks(self):
        t=self.transport()
        original=self.user.RegisterWindowMessageW
        def delayed(name):
            result=original(name); self.now=101.; return result
        self.user.RegisterWindowMessageW=Fn(delayed)
        with self.assertRaisesRegex(AssertionError,'deadline'):t.start()
        self.assertNotIn('create',self.calls)
        self.assertFalse(any(isinstance(r,tuple) and r[0]=='install' for r in self.calls))
        t.close()

    def test_each_committed_row_is_acquired_before_and_after_immutable_copy(self):
        t = self.transport(); t.start(); t.arm(0)
        state = self.State.from_address(C.addressof(self.raw)); state.count = 2
        state.events[0].sequence = 1; state.events[0].actionEpoch = 1
        state.events[1].sequence = 0
        rows = t.read_events(0); self.assertEqual([1], [r['sequence'] for r in rows])
        address = C.addressof(self.raw) + self.State.events.offset
        self.assertEqual(2, self.calls.count(('acquire', address)))
        state.events[0].actionEpoch = 77
        self.assertEqual(1, rows[0]['actionEpoch'])
        with self.assertRaisesRegex(AssertionError, 'baseline'): t.arm(1)
        t.close()

    def test_overflow_status_reserved_or_wrong_commit_fail_closed(self):
        for name in ('overflow', 'status', 'reserved', 'sequence'):
            with self.subTest(name=name):
                t = self.transport(); t.start(); t.arm(0)
                state = self.State.from_address(C.addressof(self.raw)); state.count = 1; state.events[0].sequence = 1
                if name in ('reserved', 'sequence'): setattr(state.events[0], name, 2)
                else: setattr(state, name, 1)
                with self.assertRaises(AssertionError): t.read_events(0)
                t.close()

    def test_stop_ack_is_sampled_recording_disable_without_quiescence_or_final_count(self):
        t = self.transport(); t.start()
        state = self.State.from_address(C.addressof(self.raw)); state.activeCallbacks = 3
        row = t.stop(); self.assertEqual(3, row['sampledActiveCallbacks'])
        self.assertFalse(row['remoteCallbackQuiescenceProved']); self.assertFalse(row['eventCountFinal'])
        t.close()

    def test_unhook_failure_still_releases_mapping_library_and_records_each_attempt(self):
        t = self.transport(); t.start(); self.unhook_ok = False
        with self.assertRaisesRegex(OSError, 'Unhook'): t.close()
        self.assertEqual(1, self.calls.count('unmap')); self.assertEqual(1, self.calls.count('close-map'))
        self.assertEqual(1, self.calls.count('free-library'))
        self.assertEqual(2, self.record['transportCleanup']['unhookAttempts'])

    def native(self, *, engine_creation=200):
        suite = (Path(self.directory.name) / 'owned' / 'opengeul').resolve()
        shell = dict(pid=77,handleValue=555,image=str(suite/'OpenGeul.Office.exe'),creationTime=100,waitResult=258)
        engine = dict(pid=88,handleValue=666,image=str(suite/'Office/program/soffice.bin'),creationTime=engine_creation,waitResult=258)
        process = NS(pid=77,_handle=555,args=[shell['image']],opengeul_suite_root=suite,
            opengeul_activation_binding=tuple(shell[k] for k in ('pid','handleValue','image','creationTime','waitResult')))
        binding = dict(shellPid=77,shellCreationTime=100,officePid=88,officeCreationTime=200,
            expectedImage=engine['image'],suiteHwnd=11,rootHwnd=11,parentHwnd=22,childHwnd=33)
        def session(pid, output): C.cast(output,C.POINTER(C.c_uint32)).contents.value=1; return True
        self.kernel.ProcessIdToSessionId = Fn(session)
        native = NS(kernel=self.kernel,user=self.user,
            process_snapshot=lambda p: dict(shell) if int(p._handle)==555 else dict(engine),
            open_engine=lambda pid:self.note('open-engine',666),engine_snapshot=lambda handle:dict(engine),
            close_engine=lambda handle:self.note('close-engine',True))
        window = dict(isWindow=True,hwnd=self.target['hwnd'],pid=88,threadId=99,rootHwnd=11)
        api = NS(_focus_window=lambda hwnd:dict(window))
        probe = self.m.NativeAsciiProbe(api,process,binding,{'architecture':'x64'},self.record,101.,self.clock)
        observed = dict(processMachine=0,nativeMachine=0x8664,processArchitecture='x64',nativeArchitecture='x64')
        self.enterContext(patch.object(self.m,'NativeShortcutProbe',return_value=native))
        self.enterContext(patch.object(self.m.NativeAsciiProbe,'_guard',side_effect=lambda: self.note('strict-native-guard',{'scope':{'focus':dict(window)}})))
        # The strict scope guard's own policy is reviewed/tested independently;
        # this fixture checks admission/identity and cleanup at its boundary.
        probe.thread=99
        import native_suite_architecture as architecture
        self.enterContext(patch.object(architecture,'observe_native_architecture',return_value=observed))
        self.enterContext(patch.dict(sys.modules,{'ascii_message_preparation':NS(require_prepared_library=lambda *a,**k:suite/'prepared/ascii-message-observer.dll')}))
        self.library_loader=self.enterContext(patch.object(C,'WinDLL',return_value=self.dll,create=True))
        return probe,native,engine,window

    def test_native_admission_joins_original_shell_engine_and_target_before_library_hooking(self):
        probe,native,engine,window = self.native()
        self.assertEqual(self.target,probe.admit())
        self.assertEqual(self.target,probe.guard())
        self.assertEqual(666,probe.handle)
        self.assertEqual({'controller':1,'shell':1,'engine':1},self.record['nativeSessions'])
        self.assertFalse(any(isinstance(r,tuple) and r[0]=='install' for r in self.calls))
        self.assertTrue(probe.close()['engineHandleReleased']); self.assertEqual(1,self.calls.count('close-engine'))

    def test_native_fixture_admits_with_drive_required_windows_path_semantics(self):
        # PureWindowsPath exposes Windows' rooted-without-drive distinction on
        # Linux too. Model the current drive in admission and its shared image
        # comparator without replacing any production admission/identity guard.
        class WindowsFixturePath(PureWindowsPath):
            def resolve(self, strict=False):
                if self.is_absolute(): return self
                if self.root: return type(self)('Z:' + str(self))
                return type(self)(r'Z:\fixture-current') / self
        import counted_editor_shortcuts
        with patch.dict(globals(), {'Path':WindowsFixturePath}), \
             patch.object(self.m,'Path',WindowsFixturePath), \
             patch.object(counted_editor_shortcuts,'Path',WindowsFixturePath):
            probe,native,engine,window = self.native()
            try:
                self.assertEqual(self.target,probe.admit())
                suite=probe.process.opengeul_suite_root
                self.assertTrue(suite.is_absolute());self.assertTrue(suite.drive)
                self.assertEqual(str(suite/'OpenGeul.Office.exe'),probe.process.args[0])
                self.assertEqual(str(suite/'Office/program/soffice.bin'),probe.binding['expectedImage'])
                loaded=WindowsFixturePath(self.library_loader.call_args.args[0])
                self.assertTrue(loaded.is_absolute());self.assertTrue(loaded.drive)
                self.assertEqual(suite/'prepared/ascii-message-observer.dll',loaded)
            finally:
                probe.close()

    def test_drive_less_root_remains_rejected_before_engine_or_library_admission(self):
        with patch.object(self.m,'Path',PureWindowsPath):
            probe,native,engine,window = self.native()
            probe.process.opengeul_suite_root=PureWindowsPath('/owned/opengeul')
            try:
                with self.assertRaises(AssertionError):probe.admit()
                self.assertNotIn('open-engine',self.calls)
                self.library_loader.assert_not_called()
            finally:
                probe.close()

    def test_native_wrong_generation_never_loads_or_installs_and_retained_handle_is_closed(self):
        probe,native,engine,window = self.native(engine_creation=201)
        with self.assertRaisesRegex(AssertionError,'generation'): probe.admit()
        probe.close(); self.assertEqual(1,self.calls.count('close-engine'))
        self.assertNotIn('free-library',self.calls)

    def test_native_focus_thread_or_target_generation_change_fails_before_control(self):
        probe,native,engine,window = self.native(); probe.admit()
        window['threadId']=100
        with self.assertRaisesRegex(AssertionError,'target'): probe.guard()
        probe.close()
        self.assertFalse(any(isinstance(r,tuple) and r[0]=='message' for r in self.calls))

    def test_native_unhook_error_still_closes_retained_engine_once(self):
        probe,native,engine,window = self.native(); probe.admit(); probe.start(); self.unhook_ok=False
        with self.assertRaises(OSError): probe.close()
        self.assertEqual(1,self.calls.count('close-engine'))
        self.assertTrue(self.record['nativeCleanup']['engineHandleReleased'])

    def test_partial_constructor_keeps_pointer_width_safe_library_cleanup(self):
        probe,native,engine,window = self.native()
        self.dll._handle=0x1234567887654321
        released=[]
        self.kernel.FreeLibrary=Fn(lambda handle:released.append(handle) or True)
        with patch.object(self.m,'MessageTransport',side_effect=AssertionError('early constructor failure')):
            with self.assertRaisesRegex(AssertionError,'constructor'): probe.admit()
        self.assertEqual((C.c_void_p,),getattr(self.kernel.FreeLibrary,'argtypes',None))
        self.assertIs(C.c_int32,self.kernel.FreeLibrary.restype)
        result=probe.close()
        self.assertEqual([0x1234567887654321],released)
        self.assertTrue(result['engineHandleReleased'])


if __name__ == '__main__': unittest.main()
