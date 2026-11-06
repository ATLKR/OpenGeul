"""Synthetic scenario boundaries; no actual Windows UI is exercised here."""
import contextlib
import copy
import ctypes
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))


def load_smoke():
    path = E2E / 'native_menu_smoke.py'
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location('native_menu_scenario_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def status_sample(at, started, completed, *, target=True, preview=True, menu_visible=True):
    """Synthetic numeric publisher evidence, never a Windows status RPC."""
    return dict(observedAt=at, targetMatched=target,
        state=dict(statusSequenceRaw=(1 << 56) | (started << 28) | completed,
            nativeMenuBarCount=int(menu_visible if target else not menu_visible),
            previewIndicatorCount=int(preview)),
        statusSequence=dict(version=1, started=started, completed=completed))


class Session:
    """External Windows boundary double, deliberately never native evidence."""
    actual_windows = False

    def __init__(self, *, ready=True, fail=None, cleanup=True, initial_error=None):
        self.readiness, self.fail, self.cleanup_result = ready, fail, cleanup
        self.initial_error = initial_error
        self.calls = []

    def open(self, record):
        self.calls.append('open')

    def ready(self):
        self.calls.append('ready')
        return self.readiness

    def gesture(self, name, record):
        self.calls.append(name)
        if self.fail == name:
            raise AssertionError('synthetic menu recipient rejection')
        return dict(gesture=name, success=True, kind='owned-native-menu-inspection')

    def screenshot(self, record, *, initial=False):
        self.calls.append('initial-screenshot' if initial else 'screenshot')
        if initial and self.initial_error:
            record['initialScreenshotErrorType'] = self.initial_error
            return None
        record['initialScreenshotScope' if initial else 'screenshotScope'] = 'owned-fresh-blank-form-top-240-pixels'
        return record['case'] + ('-initial-chrome.png' if initial else '-chrome.png')

    def view_roundtrip(self, record):
        self.calls.append('view-roundtrip')
        return dict(kind='native-view-roundtrip', success=True, module=record['module'])

    def hwp_launcher(self, record):
        self.calls.append('hwp-launcher')
        return dict(kind='owned-native-hwp-launcher', success=True)

    def finish(self, record):
        self.calls.append('finish')
        return True

    def cleanup(self, record):
        self.calls.append('cleanup')
        if self.cleanup_result == 'raise':
            raise RuntimeError('synthetic cleanup failure')
        return self.cleanup_result


class NativeMenuSmokeTests(unittest.TestCase):
    def setUp(self):
        self.smoke = load_smoke()
        self.assertIsNotNone(self.smoke, 'The fixed six-module native menu runner is missing')

    def run_case(self, session, module='writer'):
        return self.smoke.run_case(Path('/synthetic/suite'), Path('/synthetic/fixtures'),
            Path('/synthetic/output'), module, session_factory=lambda *args: session)

    def test_writer_requires_native_hwp_launcher_before_finish_without_certifying_synthetic_input(self):
        session=Session();record=self.run_case(session)
        self.assertIn('hwp-launcher',session.calls)
        self.assertLess(session.calls.index('hwp-launcher'),session.calls.index('finish'))
        self.assertTrue(record['hwpLauncherCompleted'])
        self.assertFalse(record['nativeHwpMenuLaunchExecuted'])
        session=Session();session.hwp_launcher=lambda record:dict(kind='owned-native-hwp-launcher',success=False)
        record=self.run_case(session)
        self.assertFalse(record['success']);self.assertNotIn('finish',session.calls)
        self.assertEqual(record['stage'],'native-hwp-launcher')

    def test_actual_adapter_rejects_hwp_success_flags_without_shared_receipt_proof(self):
        boundary=Session();session=self.smoke.WindowsSession(Path('/synthetic/suite'),
            Path('/synthetic/fixtures'),Path('/synthetic/output'),'writer')
        for name in ('open','ready','gesture','screenshot','view_roundtrip','hwp_launcher','finish','cleanup'):
            setattr(session,name,getattr(boundary,name))
        record=self.smoke.run_case(session.suite,session.fixtures,session.output,'writer',session_factory=lambda *args:session)
        self.assertFalse(record['success']);self.assertEqual(record['errorType'],'ValueError')
        self.assertEqual(record['stage'],'native-hwp-launcher');self.assertNotIn('finish',boundary.calls)

    def hwp_session(self, *, damage=None, pending=False, exit_code=0):
        import lifecycle_smoke as lifecycle
        folder=Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        executable=folder/'HWP/OpenGeul.exe';executable.parent.mkdir();executable.write_bytes(b'synthetic')
        session=self.smoke.WindowsSession(folder,folder,folder,'writer')
        session.hwnd,session.parent,session.child,session.office_pid,session.home_hwnd=11,55,56,88,99
        session.process=SimpleNamespace(pid=77,_handle=10,poll=lambda:None)
        state=SimpleNamespace(live=True,launched=False);calls=[]
        session.engine=SimpleNamespace(handle=30,exited=lambda seconds:False,close_handle=lambda handle:calls.append(('engine-release',handle)) or True)
        class Function:
            def __init__(self,call):self.call=call
            def __call__(self,*args):return self.call(*args)
        def image(handle,flags,buffer,size):
            text=str(folder/'OpenGeul.Office.exe' if handle==10 else executable)
            buffer.value=text;ctypes.cast(size,ctypes.POINTER(lifecycle.wintypes.DWORD)).contents.value=len(text)
            return 1
        def times(handle,created,*unused):
            value=ctypes.cast(created,ctypes.POINTER(lifecycle.wintypes.FILETIME)).contents
            value.dwLowDateTime=(101 if damage=='shell-generation' and state.launched else 100) if handle==10 else 300
            value.dwHighDateTime=0
            if handle==20 and not state.live:
                exited=ctypes.cast(unused[0],ctypes.POINTER(lifecycle.wintypes.FILETIME)).contents
                exited.dwLowDateTime=301;exited.dwHighDateTime=0
            return 1
        def code(handle,value):
            ctypes.cast(value,ctypes.POINTER(lifecycle.wintypes.DWORD)).contents.value=259 if handle==10 else exit_code
            return 1
        def open_process(access,inherit,pid):
            self.assertEqual((access,inherit,pid),(0x100000|0x1000,False,123));calls.append(('bind',pid));return 20
        kernel=SimpleNamespace(GetProcessId=Function(lambda handle:77 if handle==10 else 123),
            QueryFullProcessImageNameW=Function(image),GetProcessTimes=Function(times),GetExitCodeProcess=Function(code),
            WaitForSingleObject=Function(lambda handle,timeout:258 if handle==10 or state.live else 0),
            OpenProcess=Function(open_process),CloseHandle=Function(lambda handle:calls.append(('handle-release',handle)) or 1))
        self.enterContext(patch.object(lifecycle,'hwp_kernel',return_value=kernel))
        def census(pid,path,*,shell_creation,evidence):
            self.assertEqual((pid,path,shell_creation),(77,executable,100))
            matched=state.launched or damage=='existing'
            created=150 if damage=='stale' else 300
            match=dict(pid=123,parentPid=77,executable=str(executable),creationFileTime=created) if matched else None
            if damage=='foreign' and matched:match['parentPid']=90
            clock=400 if matched else 200
            def stamp(value):return dict(low=value,high=0,fileTime=value)
            candidate=dict(pid=123,parentPid=match['parentPid'],snapshotExeName='OpenGeul.exe',parentMatches=True,nameMatches=True,
                queryAttempted=True,handleOpened=True,handleClosed=True,matched=True,nativeImage=str(executable),nativeImageLength=len(str(executable)),
                image=str(executable),nativeCreation=stamp(created),creationFileTime=created,imageMatches=True,generationWithinSnapshot=True) if matched else None
            candidates=[candidate] if matched else []
            if damage=='unrelated':
                candidates.insert(0,dict(pid=999,parentPid=90,snapshotExeName='OpenGeul.exe',parentMatches=False,nameMatches=True,
                    queryAttempted=False,handleOpened=False,handleClosed=False,matched=False))
            evidence.update(schemaVersion=1,kind='native-hwp-child-census',clockApi='GetSystemTimePreciseAsFileTime',shellPid=77,
                shellCreationFileTime=100,expectedExecutable=str(executable),snapshotClock=stamp(clock),snapshotStartedFileTime=clock,
                snapshotHandleCreated=True,snapshotClosed=True,enumerationComplete=True,candidates=candidates,match=match,success=True)
            return match
        self.enterContext(patch.object(lifecycle,'_hwp_child_process',side_effect=census))
        from test_owned_native_menu import OwnedNativeMenuTests, Probe, Clock
        menu=OwnedNativeMenuTests().feature();clock=Clock();probe=Probe(folder,clock)
        probe.shell['handleValue']=10
        session.process.opengeul_suite_root=folder
        session.process.opengeul_evidence_output=folder
        session.process.opengeul_evidence_case='native-menu-writer'
        session.process.args=[str(folder/'OpenGeul.Office.exe')]
        menu_api=SimpleNamespace(attachment=lambda document:(55,56,88),user=SimpleNamespace(GetPropW=lambda hwnd,name:1))
        def command(name,record):
            self.assertEqual(name,'new-hwp');calls.append(('menu',name))
            result=menu.click_native_menu_action(menu_api,session.process,11,record,name,probe=probe,clock=clock)
            state.launched=True;return result
        session._native_command=command;session._owned_blank=lambda:calls.append(('writer-live',))
        session._home_ready=lambda **options:True
        def close(hwnd,pid):
            self.assertEqual((hwnd,pid),(500,123));calls.append(('close',hwnd,pid))
            if not pending:state.live=False
        session.api=SimpleNamespace(windows=lambda pid:[500] if state.live else [],class_name=lambda hwnd:'Tauri Window',pid=lambda hwnd:123,
            attachment=lambda document:(55,56,88),
            request_close=close,require_foreground=lambda hwnd:None,
            user=SimpleNamespace(IsWindow=lambda hwnd:state.live,IsWindowVisible=lambda hwnd:True,IsWindowEnabled=lambda hwnd:True,GetAncestor=lambda hwnd,flags:hwnd))
        browser=SimpleNamespace(handle=501,class_name=lambda:'Chrome_RenderWidgetHostHWND')
        session.desktop=lambda **options:SimpleNamespace(window=lambda **options:SimpleNamespace(wrapper_object=lambda:SimpleNamespace(descendants=lambda:[browser])))
        def wait(function,seconds=0):
            value=function()
            if not value:raise AssertionError('Synthetic bounded observation incomplete')
            return value
        session.native=SimpleNamespace(wait_for=wait,activate_owned_suite=lambda *args:calls.append(('activate-writer',)),
            stop_owned_test_process=lambda *args:calls.append(('forbidden-tree-cleanup',)))
        return session,calls,state

    def test_native_hwp_launcher_uses_real_retained_binding_exit_and_releases_only_its_handle(self):
        for damage in (None,'unrelated'):
            with self.subTest(damage=damage):
                session,calls,_=self.hwp_session(damage=damage)
                self.assertTrue(callable(getattr(session,'hwp_launcher',None)))
                record=dict(module='writer',case='native-menu-writer',shellPid=77,windowHwnd=11,parentHwnd=55,childHwnd=56,
                    officePid=88,officeCreationTime=200,originalHomeHwnd=99,
                    nativeArchiveGeneration=dict(pid=88,creationTime=200,image=str(session.suite/'Office/program/soffice.bin')),
                    windowActivations=[dict(suiteHwnd=11,originalProcess=dict(pid=77,handleValue=10,creationTime=100,
                        image=str(session.suite/'OpenGeul.Office.exe'),waitResult=258))])
                result=session.hwp_launcher(record)
                self.assertIs(self.smoke.require_hwp_launcher_receipt(result,record,session.suite),result)
                self.assertTrue(result['success']);self.assertEqual(result['kind'],'owned-native-hwp-launcher')
                self.assertEqual(result['exit']['exitCode'],0)
                self.assertEqual(result['liveBinding']['handleValue'],result['exit']['handleValue'])
                self.assertTrue(result['handleReleased']);self.assertFalse(session.hwp_unretired)
                self.assertEqual([row for row in calls if row[0] in ('menu','bind','close','handle-release')],
                    [('menu','new-hwp'),('bind',123),('close',500,123),('handle-release',20)])

    def test_hwp_existing_foreign_or_stale_generation_never_closes_a_process(self):
        for damage in ('existing','foreign','stale','shell-generation'):
            with self.subTest(damage=damage):
                session,calls,_=self.hwp_session(damage=damage)
                self.assertTrue(callable(getattr(session,'hwp_launcher',None)))
                with self.assertRaises(AssertionError):session.hwp_launcher({})
                self.assertFalse(any(row[0] in ('bind','close','handle-release') for row in calls))
                if damage=='existing':self.assertFalse(any(row[0]=='menu' for row in calls))

    def test_hwp_nonzero_exit_preserves_failure_and_releases_the_same_handle(self):
        session,calls,_=self.hwp_session(exit_code=7);record={}
        self.assertTrue(callable(getattr(session,'hwp_launcher',None)))
        with self.assertRaises(AssertionError):session.hwp_launcher(record)
        self.assertEqual(record['nativeHwpLauncher']['exit']['exitCode'],7)
        self.assertFalse(record['nativeHwpLauncher']['success']);self.assertIn(('handle-release',20),calls)

    def test_hwp_pending_normal_close_suppresses_shell_tree_cleanup_and_fails_the_gate(self):
        session,calls,_=self.hwp_session(pending=True);record={}
        self.assertTrue(callable(getattr(session,'hwp_launcher',None)))
        with self.assertRaises(AssertionError):session.hwp_launcher(record)
        self.assertTrue(session.hwp_unretired);self.assertIn(('handle-release',20),calls)
        self.assertFalse(session.cleanup(record));self.assertTrue(record['shellCleanupSuppressedForHwp'])
        self.assertFalse(any(row[0]=='forbidden-tree-cleanup' for row in calls))

    def test_fixed_six_modules_and_four_distinct_gestures_include_repeat_open(self):
        self.assertEqual(self.smoke.MODULES,
            ('writer', 'calc', 'impress', 'draw', 'math', 'base'))
        for module in self.smoke.MODULES:
            with self.subTest(module=module):
                session = Session()
                record = self.run_case(session, module)
                view = ['view-roundtrip'] if module in ('writer', 'calc') else []
                self.assertEqual(session.calls, ['open', 'ready', 'initial-screenshot', 'open-escape',
                    'open-outside', 'keyboard-escape', 'open-escape',
                    *view, 'screenshot', *(['hwp-launcher'] if module=='writer' else []), 'finish', 'cleanup'])
                self.assertTrue(record['success'])
                self.assertTrue(record['scenarioCompleted'])
                self.assertFalse(record['actualWindowsExecuted'])
                self.assertFalse(record['nativeMenuVerified'])
                self.assertIs(record.get('viewRoundtripCompleted'), module in ('writer', 'calc'))
                self.assertIs(record.get('viewPhysicalVerified'), False)
                self.assertEqual([r['gesture'] for r in record['gestures']],
                    list(self.smoke.GESTURES))

    def test_missing_or_malformed_readiness_never_sends_menu_input(self):
        for ready in (False, None, 1, 'ready'):
            with self.subTest(ready=ready):
                session = Session(ready=ready)
                record = self.run_case(session)
                self.assertFalse(record['success'])
                self.assertEqual(record['errorType'], 'AssertionError')
                self.assertEqual(session.calls, ['open', 'ready', 'cleanup'])

    def test_initial_chrome_precedes_a_first_gesture_failure_without_qualifying_success(self):
        for error in (None, 'OSError'):
            with self.subTest(initialError=error):
                session = Session(fail='open-escape', initial_error=error)
                record = self.run_case(session)
                self.assertEqual(session.calls, ['open', 'ready', 'initial-screenshot', 'open-escape', 'cleanup'])
                self.assertEqual(record['errorType'], 'AssertionError')
                self.assertFalse(record['success']); self.assertFalse(record['scenarioCompleted'])
                self.assertFalse(record['nativeMenuVerified']); self.assertFalse(record['viewPhysicalVerified'])
                self.assertEqual(record['gestures'], [])
                self.assertNotIn('screenshot', record)
                if error:
                    self.assertEqual(record['initialScreenshotErrorType'], 'OSError')
                    self.assertNotIn('initialScreenshot', record)
                else:
                    self.assertEqual(record['initialScreenshot'], 'native-menu-writer-initial-chrome.png')
                    self.assertEqual(record['initialScreenshotScope'], 'owned-fresh-blank-form-top-240-pixels')

    def capture_session(self, height=600, *, capture_error=False, lose_owner=False):
        from PIL import Image
        from test_windows_attachment import native as windows, User32
        folder = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        session = self.smoke.WindowsSession(folder, folder, folder, 'writer')
        session.hwnd, session.parent, session.child, session.office_pid = 11, 55, 56, 88
        session.process = SimpleNamespace(pid=77, poll=lambda: None)
        witnesses, captures = [], []
        session.engine = SimpleNamespace(exited=lambda seconds: witnesses.append(seconds) or False)
        session.api = object.__new__(windows.Windows); session.api.user = User32()
        session.api.user.GetForegroundWindow = lambda: 11
        def capture():
            captures.append(11)
            self.assertEqual(session.api.user.counts[('GetPropW', 11, 'OpenGeul.Office.ParentHwnd')], len(captures)*2-1)
            if lose_owner: session.api.user.pids[55] = 99
            if capture_error: raise OSError('Synthetic private capture detail must not be retained')
            return Image.new('RGB', (640, height), 'white')
        def desktop(*, backend):
            self.assertEqual(backend, 'win32')
            def window(*, handle):
                self.assertEqual(handle, 11)
                return SimpleNamespace(wrapper_object=lambda: SimpleNamespace(capture_as_image=capture))
            return SimpleNamespace(window=window)
        session.desktop = desktop
        return session, captures, witnesses

    def capture(self, session, record, *, initial):
        try: return session.screenshot(record, initial=initial)
        except TypeError:
            self.fail('The real Windows screenshot adapter must support a distinct initial capture')

    def test_actual_initial_and_final_chrome_are_guarded_cropped_and_never_overwritten(self):
        from PIL import Image
        for height in (120, 600):
            with self.subTest(height=height):
                session, captures, witnesses = self.capture_session(height)
                record = dict(case='native-menu-writer')
                initial = self.capture(session, record, initial=True)
                final = self.capture(session, record, initial=False)
                self.assertEqual(initial, 'native-menu-writer-initial-chrome.png')
                self.assertEqual(final, 'native-menu-writer-chrome.png')
                self.assertEqual(captures, [11,11]); self.assertEqual(witnesses, [0,0,0,0])
                for name in (initial, final):
                    with Image.open(session.output/name) as image:
                        self.assertEqual(image.size, (640, min(height,240)))
                before = {name:(session.output/name).read_bytes() for name in (initial,final)}
                duplicate = dict(case='native-menu-writer')
                self.assertIsNone(self.capture(session, duplicate, initial=True))
                self.assertEqual(duplicate, dict(case='native-menu-writer', initialScreenshotErrorType='FileExistsError'))
                with self.assertRaises(FileExistsError): self.capture(session, record, initial=False)
                self.assertEqual({name:(session.output/name).read_bytes() for name in (initial,final)}, before)

    def test_actual_capture_failure_is_content_free_and_keeps_both_owner_checks(self):
        session, captures, witnesses = self.capture_session(capture_error=True)
        record = dict(case='native-menu-writer')
        self.assertIsNone(self.capture(session, record, initial=True))
        self.assertEqual(record, dict(case='native-menu-writer', initialScreenshotErrorType='OSError'))
        self.assertEqual(captures,[11]); self.assertEqual(witnesses,[0,0])
        self.assertEqual(list(session.output.iterdir()), [])

    def test_foreign_owner_is_fatal_before_or_after_capture_without_retaining_an_image(self):
        for after in (False,True):
            with self.subTest(afterCapture=after):
                session, captures, witnesses = self.capture_session(lose_owner=after)
                if not after: session.api.user.pids[55] = 99
                record = dict(case='native-menu-writer')
                with self.assertRaises(AssertionError): self.capture(session, record, initial=True)
                self.assertEqual(captures, [11] if after else [])
                self.assertEqual(record, dict(case='native-menu-writer'))
                self.assertEqual(list(session.output.iterdir()), [])

    def opening_focus_session(self):
        from test_windows_attachment import native as windows, User32
        class FocusUser(User32):
            def __init__(self):
                super().__init__();self.focus=11;self.on_query=None
            def GetForegroundWindow(self):return 11
            def GetGUIThreadInfo(self,thread,pointer):
                self.call('GetGUIThreadInfo',thread)
                if self.on_query:self.on_query()
                value=pointer._obj;value.hwndActive=11;value.hwndFocus=self.focus
                value.hwndCapture=value.hwndMenuOwner=value.flags=0
                return 1
        session=self.smoke.WindowsSession(Path('/suite'),Path('/fixtures'),Path('/output'),'writer')
        session.hwnd,session.parent,session.child,session.office_pid=11,55,56,88
        session.native=windows;session.api=object.__new__(windows.Windows);session.api.user=FocusUser()
        session.process=SimpleNamespace(pid=77,_handle=8,poll=lambda:None)
        session.engine=SimpleNamespace(handle=9,creation_time=200,exited=lambda seconds:False)
        record=dict(nativeArchiveGeneration=dict(pid=88,creationTime=200,image='/suite/Office/program/soffice.bin'))
        return session,record

    def test_opening_focus_observation_uses_actual_windows_api_and_records_only_numbers(self):
        session,record=self.opening_focus_session();user=session.api.user
        user.properties[11,'OpenGeul.Office.NativeMenuReady']=0
        observer=getattr(session,'_observe_open_focus',None)
        self.assertTrue(callable(observer),'Initial host focus needs an actual read-only adapter')
        observer(record,1)
        user.properties[11,'OpenGeul.Office.NativeMenuReady']=1
        observer(record,2);observer(record,3)
        rows=record['openingFocusObservations']
        self.assertEqual([row['phaseCode'] for row in rows],[1,2,3])
        self.assertEqual([row['nativeReadyHint'] for row in rows],[0,1,1])
        self.assertEqual([row['attachReadyObserved'] for row in rows],[0,1,1])
        for row in rows:
            self.assertEqual((row['hostGui']['focusHwnd'],row['engineGui']['focusHwnd']),(11,11))
            self.assertEqual(row['foreground'],dict(hwnd=11,pid=77,rootHwnd=11))
            def numeric(value):
                if type(value) is dict:
                    for child in value.values():numeric(child)
                else:self.assertIs(type(value),int)
            numeric(row)
        self.assertEqual([call for call in user.calls if call[0]=='GetGUIThreadInfo'],
            [('GetGUIThreadInfo',7),('GetGUIThreadInfo',9)]*3)
        self.assertNotIn('GetWindowTextW',{call[0] for call in user.calls})
        with self.assertRaises(AssertionError):observer(record,3)
        self.assertEqual(len(rows),3)

    def test_opening_focus_observation_rejects_owner_or_retained_handle_change_before_retention(self):
        for change in ('before-parent','after-parent','engine-handle','shell-handle','engine-generation'):
            with self.subTest(change=change):
                session,record=self.opening_focus_session();user=session.api.user
                observer=getattr(session,'_observe_open_focus',None)
                self.assertTrue(callable(observer),'Initial ownership must be checked by the actual adapter')
                if change=='before-parent':user.pids[55]=99
                elif change=='after-parent':user.on_query=lambda:user.pids.update({55:99})
                elif change=='engine-handle':user.on_query=lambda:setattr(session.engine,'handle',10)
                elif change=='shell-handle':user.on_query=lambda:setattr(session.process,'_handle',10)
                else:session.engine.creation_time=201
                with self.assertRaises(AssertionError):observer(record,1)
                self.assertNotIn('openingFocusObservations',record)
                if change in ('before-parent','engine-generation'):
                    self.assertFalse(any(call[0]=='GetGUIThreadInfo' for call in user.calls))

    def test_actual_open_samples_focus_before_and_after_maximize_and_existing_activation(self):
        import startup_smoke
        import windows_smoke
        import owned_native_menu
        session,record=self.opening_focus_session();events=[];user=session.api.user
        record['case']='native-menu-writer';api=session.api;process=session.process;engine=session.engine
        observer=getattr(session,'_observe_open_focus',None)
        self.assertTrue(callable(observer),'The real open path must emit the three numeric phases')
        def sample(value,phase):events.append(('observe',phase));return observer(value,phase)
        session._observe_open_focus=sample
        def maximize():events.append('maximize')
        def desktop(*,backend):
            self.assertEqual(backend,'win32')
            return SimpleNamespace(window=lambda *,handle:SimpleNamespace(wrapper_object=lambda:SimpleNamespace(maximize=maximize)))
        def activate(*args):events.append('activate')
        with patch.object(self.smoke.os,'name','nt'), \
             patch.dict(sys.modules,{'pywinauto':SimpleNamespace(Desktop=desktop)}), \
             patch.object(windows_smoke,'launch_suite',return_value=process), \
             patch.object(windows_smoke,'new_document_command',return_value=['synthetic-launch']), \
             patch.object(windows_smoke,'Windows',return_value=api), \
             patch.object(windows_smoke,'verified_attachment',return_value=(11,55,56,88)), \
             patch.object(windows_smoke,'capture_native_archive_generation',return_value=record['nativeArchiveGeneration']), \
             patch.object(startup_smoke,'EngineProcessWitness',return_value=engine), \
             patch.object(windows_smoke,'activate_owned_suite',side_effect=activate), \
             patch.object(api,'home',return_value=22), \
             patch.object(session,'_home_ready',return_value=True):
            session.open(record)
        self.assertEqual(events,[('observe',1),'maximize',('observe',2),'activate',('observe',3)])
        self.assertEqual(len(record['openingFocusObservations']),3)
        self.assertFalse(record.get('nativeMenuVerified',False))

    def test_failed_gesture_is_not_retried_and_later_input_is_not_sent(self):
        session = Session(fail='open-outside')
        record = self.run_case(session)
        self.assertFalse(record['success'])
        self.assertEqual(session.calls,
            ['open', 'ready', 'initial-screenshot', 'open-escape', 'open-outside', 'cleanup'])
        self.assertEqual(len(record['gestures']), 1)
        self.assertEqual(record['errorType'], 'AssertionError')

    def test_cleanup_failure_cannot_turn_a_completed_scenario_into_success(self):
        for outcome in (False, 'raise'):
            with self.subTest(outcome=outcome):
                record = self.run_case(Session(cleanup=outcome))
                self.assertTrue(record['scenarioCompleted'])
                self.assertFalse(record['success'])
                self.assertFalse(record['cleanupConfirmed'])
                self.assertFalse(record['nativeMenuVerified'])

    def test_primary_gesture_failure_survives_cleanup_failure(self):
        record = self.run_case(Session(fail='open-escape', cleanup='raise'))
        self.assertEqual(record['errorType'], 'AssertionError')
        self.assertEqual(record['cleanupErrorType'], 'RuntimeError')

    def test_unknown_module_is_rejected_before_constructing_a_session(self):
        calls = []
        with self.assertRaises(ValueError):
            self.smoke.run_case(Path('/suite'), Path('/fixtures'), Path('/output'),
                'unknown', session_factory=lambda *args: calls.append(args))
        self.assertEqual(calls, [])

    def test_synthetic_six_case_success_never_claims_actual_ui_acceptance(self):
        with tempfile.TemporaryDirectory() as folder:
            with contextlib.redirect_stdout(io.StringIO()):
                report = self.smoke.run_modules(Path('/suite'), Path('/fixtures'), Path(folder),
                    session_factory=lambda *args: Session())
            self.assertTrue(report['scenarioSuccess'])
            self.assertFalse(report['success'])
            self.assertFalse(report['actualWindowsExecuted'])
            self.assertFalse(report['nativeMenuVerified'])
            self.assertIs(report.get('viewPhysicalVerified'), False)
            self.assertEqual(report.get('viewPhysicalExpectedCaseCount'), 2)
            self.assertEqual(report.get('viewPhysicalVerifiedCaseCount'), 0)
            self.assertFalse(report['acceptanceEligible'])
            self.assertIs(report.get('nativeHwpMenuLaunchExecuted'), False)
            self.assertIs(report.get('disabledCommandsPhysicalVerified'), False)
            self.assertEqual(report['expectedCaseCount'], 6)
            self.assertEqual(report['completedCaseCount'], 6)
            self.assertIn('save-as-cancel', report['externalAcceptanceGates'])

    def test_unconfirmed_cleanup_stops_cohort_before_another_engine_is_launched(self):
        calls = []
        def factory(*args):
            calls.append(args[-1])
            return Session(cleanup=False)
        with tempfile.TemporaryDirectory() as folder:
            with contextlib.redirect_stdout(io.StringIO()):
                report = self.smoke.run_modules(Path('/suite'), Path('/fixtures'), Path(folder),
                    session_factory=factory)
        self.assertEqual(calls, ['writer'])
        self.assertFalse(report['success'])
        self.assertEqual(report['missingModules'], ['calc', 'impress', 'draw', 'math', 'base'])

    def test_synthetic_session_cannot_claim_physical_views_by_claiming_windows(self):
        class Impostor(Session):
            actual_windows = True
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(self.smoke, 'os', SimpleNamespace(name='nt')), \
                contextlib.redirect_stdout(io.StringIO()):
            report = self.smoke.run_modules(Path('/suite'), Path('/fixtures'), Path(folder),
                session_factory=lambda *args: Impostor())
        self.assertTrue(report['scenarioSuccess'])
        self.assertFalse(report['success'])
        self.assertIs(report['viewPhysicalVerified'], False)
        self.assertEqual(report['viewPhysicalVerifiedCaseCount'], 0)
        self.assertTrue(all(row['viewPhysicalVerified'] is False for row in report['tests']))

    def test_failed_roundtrip_returns_to_cleanup_without_screenshot_or_finish_input(self):
        session = Session()
        def fail(record):
            session.calls.append('view-roundtrip')
            raise AssertionError('synthetic failed first view observation')
        session.view_roundtrip = fail
        record = self.run_case(session, 'calc')
        self.assertFalse(record['success'])
        self.assertIs(record['viewRoundtripCompleted'], False)
        self.assertIs(record['viewPhysicalVerified'], False)
        self.assertEqual(session.calls, ['open', 'ready', 'initial-screenshot', 'open-escape', 'open-outside',
            'keyboard-escape', 'open-escape', 'view-roundtrip', 'cleanup'])

    def test_cli_cannot_select_a_subset_and_relabel_it_as_the_complete_matrix(self):
        parser = self.smoke.argument_parser()
        args = parser.parse_args(['--suite', '/suite', '--fixtures', '/fixtures', '--output', '/output'])
        self.assertEqual(args.suite, Path('/suite'))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(['--suite', '/suite', '--fixtures', '/fixtures',
                '--output', '/output', '--modules', 'writer'])

    def test_native_unready_is_one_passive_check_without_a_wait_or_fallback(self):
        session = self.smoke.WindowsSession(Path('/suite'), Path('/fixtures'), Path('/output'), 'writer')
        calls, waits = [], []
        session.api = session.process = object()
        session.hwnd = 11
        session.menu = SimpleNamespace(native_menu_active=lambda *args: calls.append(args) or False)
        session.native = SimpleNamespace(wait_for=lambda check, seconds: waits.append(seconds) or check())
        self.assertIs(session.ready(), False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(waits, [])

    def test_engine_handle_release_result_is_required_for_cleanup_confirmation(self):
        for released in (True, False):
            with self.subTest(released=released):
                session = self.smoke.WindowsSession(Path('/suite'), Path('/fixtures'), Path('/output'), 'writer')
                calls = []
                session.process = SimpleNamespace(poll=lambda: 0)
                session.native = SimpleNamespace(stop_owned_test_process=lambda *args: None)
                session.engine = SimpleNamespace(handle=123, exited=lambda seconds: True,
                    close_handle=lambda handle: calls.append(handle) or released, close=lambda: None)
                record = {}
                self.assertIs(session.cleanup(record), released)
                self.assertEqual(calls, [123])
                self.assertIs(record['engineHandleReleased'], released)
                self.assertEqual(session.engine.handle, None if released else 123)

    def test_launched_process_without_retained_engine_witness_cannot_confirm_cleanup(self):
        session = self.smoke.WindowsSession(Path('/suite'), Path('/fixtures'), Path('/output'), 'writer')
        session.process = SimpleNamespace(poll=lambda: 0)
        session.native = SimpleNamespace(stop_owned_test_process=lambda *args: None)
        self.assertIs(session.cleanup({}), False)

    def test_actual_helper_gesture_receipt_is_preserved_and_bound_to_its_command(self):
        session = self.smoke.WindowsSession(Path('/suite'), Path('/fixtures'), Path('/output'), 'writer')
        session.api = session.process = object()
        session.hwnd = 11
        receipt = dict(kind='owned-native-menu-action', command='open-escape', gesture=True, success=True)
        session.menu = SimpleNamespace(inspect_native_menu=lambda *args: receipt)
        result = session.gesture('open-escape', {})
        self.assertEqual(result['gesture'], 'open-escape')
        self.assertIs(result['receipt'], receipt)
        for change in ({'gesture': False}, {'command': 'open-outside'},
                       {'kind': 'owned-shell-control-action'}, {'success': False}):
            bad = receipt | change
            session.menu = SimpleNamespace(inspect_native_menu=lambda *args: bad)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                session.gesture('open-escape', {})

    def test_default_session_on_linux_cannot_claim_actual_windows_execution(self):
        with patch.object(self.smoke, 'os', SimpleNamespace(name='posix')):
            record = self.smoke.run_case(Path('/suite'), Path('/fixtures'), Path('/output'), 'writer')
        self.assertFalse(record['success'])
        self.assertFalse(record['actualWindowsExecuted'])
        self.assertEqual(record['errorType'], 'AssertionError')

    def finish_session(self, module):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        suite, fixtures, output = (folder / name for name in ('Suite 한글', 'fixtures', 'output'))
        for path in (suite, fixtures, output):
            path.mkdir()
        session = self.smoke.WindowsSession(suite, fixtures, output, module)
        calls, live = [], {9, 11, 13}
        session.hwnd, session.parent, session.child, session.office_pid, session.home_hwnd = 11, 12, 13, 88, 9
        session.process = SimpleNamespace(pid=77, returncode=None)
        session.process.poll = lambda: session.process.returncode
        def waited(timeout):
            calls.append(('wait-shell', timeout))
            assert session.process.returncode == 0
        session.process.wait = waited
        session.engine = SimpleNamespace(exited=lambda seconds: 13 not in live, code=lambda: 0)
        def command(*args):
            name = args[-1]; calls.append(('menu', name))
            if name in ('home', 'close') or name == 'exit' and module != 'calc':
                live.discard(11); live.discard(13)
            if name == 'exit' and module != 'calc':
                live.discard(9); session.process.returncode = 0
            return dict(kind='owned-native-menu-action', success=True, gesture=False, command=name)
        def close_document(*args, **kwargs):
            calls.append(('qualified-close', kwargs.get('calc_close_proof')))
            live.discard(11); live.discard(13)
        def close_home(*args):
            calls.append(('close-home',)); live.discard(9); session.process.returncode = 0
        def saved(*args):
            calls.append(('base-save',))
            args[-1]['baseSaveMenuAction'] = dict(kind='owned-native-menu-action')
            return Path(folder) / 'blank.odb'
        def wait_for(check, seconds):
            value = check(); assert value, 'synthetic condition not satisfied'
            return value
        session.native = SimpleNamespace(close_document=close_document, close_home=close_home,
            wait_for=wait_for, save_new_base=saved, saved_base_evidence=lambda p: {'sha256': 'a' * 64})
        session.menu = SimpleNamespace(click_native_menu_action=command,
            native_menu_active=lambda *args: 11 in live,
            inspect_native_menu=lambda *args: calls.append(('inspect', args[-1])) or dict(
                kind='owned-native-menu-action', success=True, gesture=True, command=args[-1]))
        session.api = SimpleNamespace(home=lambda p: 9 if 9 in live else None,
            pid=lambda h: 88 if h == 13 else 77, title=lambda h: 'OpenGeul Office',
            require_foreground=lambda h: h in live,
            user=SimpleNamespace(IsWindow=lambda h: h in live or h == 12,
                IsWindowVisible=lambda h: h in live, GetAncestor=lambda h, f: h if h in (9, 11) else 11,
                GetForegroundWindow=lambda: 9 if 11 not in live else 11,
                IsChild=lambda p, c: (p, c) in ((11, 12), (12, 13), (11, 13)),
                GetPropW=lambda h, name: (12 if name.endswith('ParentHwnd') else 13) if h == 11 else 0))
        session._cancel_calc_exit = lambda record, **kwargs: calls.append(('cancel-exit',)) or True
        return session, calls

    def view_boundaries(self, session, calls, *, bad_observation=None, bad_fullscreen=None):
        """Synthetic external input/provider boundaries around the real runner."""
        shell = dict(pid=77, creationTime=1000, image=str(session.suite/'OpenGeul.Office.exe'),
            handleValue=777, waitResult=258)
        engine = dict(pid=88, creationTime=1001, image=str(session.suite/'Office/program/soffice.bin'),
            handleValue=888, waitResult=258)
        binding = dict(document=11, parent=12, child=13, officePid=88,
            officeCreationTime=1001, expectedImage=engine['image'])
        session.process._handle = 777
        common = dict(schemaVersion=1, startedAt=0, deadline=5, finishedAt=1,
            binding=binding, originalProcess=shell, originalEngine=engine,
            engineHandleReleased=True, providerClientReleased=True,
            dpiScope=dict(verified=True, restored=True), focusReturned=True)
        original_command = session.menu.click_native_menu_action
        session.menu.click_native_menu_action = lambda *args: common | original_command(*args)
        observation_index = [0]
        def observe(*args, **kwargs):
            self.assertEqual(args[:3], (session.api, session.process, session.hwnd))
            self.assertEqual(kwargs, dict(module=session.module, preview=kwargs['preview'],
                menu_visible=kwargs['menu_visible'], hold_seconds=3, seconds=5))
            calls.append(('observe', kwargs['preview'], kwargs['menu_visible']))
            baseline, start = 10 + 2 * observation_index[0], 4 * observation_index[0]
            observation_index[0] += 1
            row = dict(schemaVersion=1, kind='owned-native-view-observation', success=True,
                module=session.module, preview=kwargs['preview'], menuVisible=kwargs['menu_visible'],
                holdSeconds=3, startedAt=start, deadline=start+5, finishedAt=start+3.1, observedSeconds=(start+3.1)-start,
                samples=[status_sample(start,baseline,baseline-1,preview=kwargs['preview'],menu_visible=kwargs['menu_visible']),
                    status_sample(start+3.1,baseline+1,baseline+1,preview=kwargs['preview'],menu_visible=kwargs['menu_visible'])],
                settledAt=start,statusSequenceVersion=1,firstTargetStartedSequence=baseline,lastTargetCompletedSequence=baseline+1,
                binding=binding, originalProcess=shell, originalEngine=engine,
                engineHandleReleased=True, providerClientReleased=True,
                dpiScope=dict(verified=True, restored=True), statusRpcProved=True, inputCallAttempts=0)
            change = bad_observation(row) if callable(bad_observation) else bad_observation
            return row | (change or {})
        def inspect(*args):
            self.assertEqual(args[:3], (session.api, session.process, session.hwnd))
            calls.append(('inspect', args[-1]))
            return common | dict(kind='owned-native-menu-action', success=True, gesture=True,
                command=args[-1], coreCommandsVerified=True, coreCommands=[
                    'new-hwp', 'home', 'new', 'open', 'save', 'saveAs', 'close'],
                coreSnapshots=[{} for _ in range(7)], focusReturned=True)
        def toggle(*args, **kwargs):
            self.assertEqual(args[:3], (session.api, session.process, session.hwnd))
            self.assertEqual(kwargs, dict(module=session.module, seconds=5))
            calls.append(('fullscreen',))
            row = common | dict(schemaVersion=1, kind='owned-native-fullscreen-toggle', success=True,
                module=session.module, inputCallAttempts=1, requestedInputs=6, insertedInputs=6,
                startedAt=0, deadline=5, finishedAt=1, binding=binding,
                originalProcess=shell, originalEngine=engine, engineHandleReleased=True,
                providerClientReleased=True, dpiScope=dict(verified=True, restored=True))
            return row | (bad_fullscreen or {})
        session.menu.observe_native_view, session.menu.inspect_native_menu = observe, inspect
        self.enterContext(patch.dict(sys.modules, {'owned_fullscreen': SimpleNamespace(
            toggle_native_fullscreen=toggle)}))
        return dict(pid=engine['pid'], creationTime=engine['creationTime'], image=engine['image'])

    def test_real_session_view_roundtrip_keeps_original_recipient_and_exact_action_order(self):
        for module in ('writer', 'calc'):
            with self.subTest(module=module):
                session, calls = self.finish_session(module)
                generation = self.view_boundaries(session, calls)
                function = getattr(session, 'view_roundtrip', None)
                self.assertTrue(callable(function), 'The real WindowsSession view runner is missing')
                record = dict(module=module, keyboardInputVerified=False, contentMutationVerified=False,
                    nativeArchiveGeneration=generation)
                result = function(record)
                self.assertTrue(result['success'])
                self.assertEqual((result['kind'], result['module']), ('native-view-roundtrip', module))
                self.assertEqual(calls, [('menu', 'printPreview'), ('observe', True, True),
                    ('menu', 'printPreview'), ('observe', False, True), ('inspect', 'core-commands'),
                    ('fullscreen',), ('observe', False, False), ('fullscreen',),
                    ('observe', False, True), ('inspect', 'core-commands')])
                self.assertIs(record['keyboardInputVerified'], False)
                self.assertIs(record['contentMutationVerified'], False)

    def test_failed_view_observation_stops_before_another_preview_or_fullscreen_input(self):
        session, calls = self.finish_session('writer')
        generation = self.view_boundaries(session, calls, bad_observation={'success': False})
        function = getattr(session, 'view_roundtrip', None)
        self.assertTrue(callable(function), 'The real WindowsSession view runner is missing')
        with self.assertRaises(AssertionError):
            function(dict(module='writer', nativeArchiveGeneration=generation))
        self.assertEqual(calls, [('menu', 'printPreview'), ('observe', True, True)])

    def test_view_roundtrip_cannot_pass_after_original_home_disappears(self):
        session, calls = self.finish_session('writer')
        generation = self.view_boundaries(session, calls)
        session.api.home = lambda process: None
        with self.assertRaises(AssertionError):
            session.view_roundtrip(dict(module='writer', nativeArchiveGeneration=generation))
        self.assertEqual(calls[-1], ('inspect', 'core-commands'))

    def test_partial_fullscreen_insertion_stops_without_a_retry_or_inverse_input(self):
        session, calls = self.finish_session('calc')
        generation = self.view_boundaries(session, calls, bad_fullscreen={'insertedInputs': 5})
        function = getattr(session, 'view_roundtrip', None)
        self.assertTrue(callable(function), 'The real WindowsSession view runner is missing')
        with self.assertRaises(AssertionError):
            function(dict(module='calc', nativeArchiveGeneration=generation))
        self.assertEqual(calls, [('menu', 'printPreview'), ('observe', True, True),
            ('menu', 'printPreview'), ('observe', False, True), ('inspect', 'core-commands'),
            ('fullscreen',)])

    def test_view_observation_rejects_wrong_state_generation_cleanup_or_budget_before_more_input(self):
        changes = ({'kind': 'owned-native-menu-action'}, {'module': 'calc'}, {'preview': False},
            {'menuVisible': False}, {'holdSeconds': 2}, {'observedSeconds': 2.9},
            {'observedSeconds': 5}, {'observedSeconds': 4},
            {'samples': []}, {'samples': [{} for _ in range(65)]},
            {'inputCallAttempts': True}, {'statusRpcProved': False}, {'finishedAt': 5},
            {'engineHandleReleased': False}, {'providerClientReleased': False},
            {'dpiScope': {'verified': True, 'restored': False}},
            {'binding': dict(document=11, parent=12, child=99, officePid=88)})
        for change in changes:
            with self.subTest(change=change):
                session, calls = self.finish_session('writer')
                generation = self.view_boundaries(session, calls, bad_observation=change)
                with self.assertRaises(AssertionError):
                    session.view_roundtrip(dict(module='writer', nativeArchiveGeneration=generation))
                self.assertEqual(calls, [('menu', 'printPreview'), ('observe', True, True)])

    def test_status_completion_requires_fresh_numeric_samples_after_the_final_target_baseline(self):
        def samples(edit):
            values = [status_sample(0,10,9), status_sample(3.1,11,11)]
            edit(values)
            return {'samples': values}
        changes = [
            {'statusSequenceVersion': None}, {'statusSequenceVersion': True},
            {'firstTargetStartedSequence': None}, {'firstTargetStartedSequence': True},
            {'firstTargetStartedSequence': -1}, {'firstTargetStartedSequence': 1 << 28},
            {'lastTargetCompletedSequence': None}, {'lastTargetCompletedSequence': True},
            {'lastTargetCompletedSequence': 10}, {'lastTargetCompletedSequence': 1 << 28},
            {'firstTargetStartedSequence': 9}, {'lastTargetCompletedSequence': 12},
            samples(lambda rows: rows[0].pop('statusSequence')),
            samples(lambda rows: rows[0]['state'].pop('statusSequenceRaw')),
            samples(lambda rows: rows[0]['state'].update(statusSequenceRaw=True)),
            samples(lambda rows: rows[0]['state'].update(statusSequenceRaw=(2 << 56) | (10 << 28) | 9)),
            samples(lambda rows: rows[0]['statusSequence'].update(version=True)),
            samples(lambda rows: rows[0]['statusSequence'].update(started=10.0)),
            samples(lambda rows: rows[0]['statusSequence'].update(completed=10)),
            {'samples': [status_sample(0,10,9),status_sample(1,12,11),status_sample(3.1,11,11)]},
            {'samples': [status_sample(0,10,9),status_sample(1,12,12),status_sample(3.1,12,11)]},
            {'samples': [status_sample(0,10,10),status_sample(3.1,10,10)]},
            {'samples': [status_sample(0,10,9),status_sample(3.1,11,10)]},
            samples(lambda rows: rows[0].update(targetMatched=1)),
            samples(lambda rows: rows[0].update(observedAt=True)),
            samples(lambda rows: rows[0].update(observedAt=float('nan'))),
            samples(lambda rows: rows[0].update(observedAt=-1)),
            samples(lambda rows: rows[-1].update(observedAt=5)),
            {'samples': [status_sample(0,10,9),status_sample(3.1,11,11,target=False)]},
            {'samples': [status_sample(0,10,9),status_sample(1,11,11,target=False),
                status_sample(1.1,11,11),status_sample(3.1,12,12)],'lastTargetCompletedSequence':12},
            {'samples': [status_sample(0,10,9),status_sample(.5,11,11,target=False),
                status_sample(1,11,11),status_sample(4,11,11)],'finishedAt':4,
                'settledAt':1,'observedSeconds':3},
            {'settledAt': True}, {'settledAt': .1},
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index, change=change):
                session, calls = self.finish_session('writer')
                generation = self.view_boundaries(session, calls, bad_observation=change)
                with self.assertRaises((AssertionError, KeyError)):
                    session.view_roundtrip(dict(module='writer', nativeArchiveGeneration=generation))
                self.assertEqual(calls, [('menu','printPreview'),('observe',True,True)])

    def test_status_baseline_resets_after_settling_without_reusing_an_earlier_completion(self):
        session, calls = self.finish_session('writer')
        def settled(row):
            at, baseline = row['startedAt'], row['firstTargetStartedSequence']
            flags = dict(preview=row['preview'], menu_visible=row['menuVisible'])
            return dict(samples=[status_sample(at,baseline-1,baseline-1,target=False,**flags),
                status_sample(at+.1,baseline,baseline-1,**flags),
                status_sample(at+3.1,baseline+1,baseline+1,**flags)], settledAt=at+.1,
                observedSeconds=(at+3.1)-(at+.1))
        generation = self.view_boundaries(session, calls, bad_observation=settled)
        self.assertTrue(session.view_roundtrip(dict(module='writer',nativeArchiveGeneration=generation))['success'])

    def test_status_samples_cannot_roll_back_or_replay_between_the_four_observations(self):
        for reason in ('sequence','clock'):
            session, calls = self.finish_session('writer')
            prior = []
            def replay(row):
                if not prior:
                    prior.append(copy.deepcopy(row)); return {}
                if reason=='clock':
                    shift=row['startedAt']
                    changed=copy.deepcopy(row)
                    for key in ('startedAt','deadline','finishedAt','settledAt'):changed[key]-=shift
                    for sample in changed['samples']:sample['observedAt']-=shift
                    return changed
                changed=copy.deepcopy(prior[0])
                changed.update(preview=row['preview'],menuVisible=row['menuVisible'])
                for sample in changed['samples']:
                    sample['state']['previewIndicatorCount']=int(row['preview'])
                    sample['state']['nativeMenuBarCount']=int(row['menuVisible'])
                return changed
            generation=self.view_boundaries(session,calls,bad_observation=replay)
            with self.subTest(reason=reason), self.assertRaises(AssertionError):
                session.view_roundtrip(dict(module='writer',nativeArchiveGeneration=generation))
            self.assertEqual(calls,[('menu','printPreview'),('observe',True,True),
                ('menu','printPreview'),('observe',False,True)])

    def test_finish_fixture_roots_are_absolute_resolved_owned_siblings(self):
        session, _ = self.finish_session('calc')
        for path in (session.suite, session.fixtures, session.output):
            self.assertTrue(path.is_absolute(), 'Real freeze boundary requires a drive-qualified absolute fixture')
            self.assertEqual(path, path.resolve())
            self.assertTrue(path.is_dir())
            self.assertEqual(path.parent, session.output.parent,
                'Suite, fixtures and output must belong to the same temporary test root')
        self.assertEqual(len({session.suite, session.fixtures, session.output}), 3)

    def test_writer_home_command_closes_only_original_document_then_same_home_is_closed(self):
        session, calls = self.finish_session('writer'); record = {}
        self.assertIs(session.finish(record), True)
        self.assertEqual([c for c in calls if c[0] == 'menu'], [('menu', 'home')])
        self.assertNotIn(('qualified-close', None), calls)
        self.assertTrue(record['nativeHomeVerified'])

    def test_draw_and_math_close_use_the_native_menu_without_a_second_close_input(self):
        for module in ('draw', 'math'):
            with self.subTest(module=module):
                session, calls = self.finish_session(module); record = {}
                self.assertIs(session.finish(record), True)
                self.assertEqual([c for c in calls if c[0] == 'menu'], [('menu', 'close')])
                self.assertFalse(any(c[0] == 'qualified-close' for c in calls))
                self.assertTrue(record['nativeCloseVerified'])

    def test_saved_base_native_exit_retires_shell_without_another_document_or_home_close(self):
        session, calls = self.finish_session('base'); record = {}
        self.assertIs(session.finish(record), True)
        self.assertIn(('menu', 'exit'), calls)
        self.assertLess(calls.index(('base-save',)), calls.index(('menu', 'exit')))
        self.assertFalse(any(c[0] in ('qualified-close', 'close-home') for c in calls))
        self.assertTrue(record['nativeExitVerified'])

    def test_calc_exit_cancel_precedes_first_blank_token_and_qualified_close(self):
        session, calls = self.finish_session('calc'); token = object(); record = {}
        with patch('generated_calc_close.freeze_generated_blank_calc',
                side_effect=lambda *args: calls.append(('freeze',)) or token):
            self.assertIs(session.finish(record), True)
        self.assertEqual([c[0] for c in calls if c[0] in
            ('menu', 'cancel-exit', 'inspect', 'freeze', 'qualified-close')],
            ['menu', 'cancel-exit', 'inspect', 'freeze', 'qualified-close'])
        self.assertIn(('menu', 'exit'), calls)
        self.assertIn(('qualified-close', token), calls)
        self.assertTrue(record['nativeExitCancelVerified'])

    def test_calc_real_freeze_accepts_the_runner_record_without_relabeling_its_case(self):
        import generated_calc_close as generated
        import lifecycle_smoke as lifecycle
        session, calls = self.finish_session('calc')
        session.actual_windows = False
        session.process.args = [str(session.suite/'OpenGeul.Office.exe'), '--module', 'calc']
        session.process._handle, session.process.opengeul_evidence_case = 777, 'native-menu-calc'
        retained = []
        class Bound:
            def __init__(self, pid, image):
                self.pid, self.handle, self.creation, self.kernel = pid, pid, 1000 if pid == 77 else 1001, None
                retained.append(self)
            def live(self):
                return session.process.poll() is None if self.pid == 77 else session.api.user.IsWindow(13)
            def close(self):
                self.handle = None
        def identity(kernel, handle):
            return (session.suite/'OpenGeul.Office.exe', 1000) if handle in (77, 777) else (
                session.suite/'Office/program/soffice.bin', 1001)
        session.open = lambda record: record.update(shellPid=77, windowHwnd=11, childHwnd=13,
            officePid=88, officeCreationTime=1001, nativeArchiveGeneration=dict(pid=88,
                creationTime=1001, image=str(session.suite/'Office/program/soffice.bin')))
        session.screenshot = lambda record, *, initial=False: record['case'] + (
            '-initial-chrome.png' if initial else '-chrome.png')
        session.cleanup = lambda record: True
        close = session.native.close_document
        def qualified(*args, **kwargs):
            proof = kwargs['calc_close_proof']
            self.assertIsInstance(proof, generated.GeneratedBlankCalc)
            generated.verify_generated_blank_calc(args[0], args[1], args[2], args[3], args[4], proof)
            close(*args, **kwargs)
            proof.engine.close(); proof.shell.close()
        session.native.close_document = qualified
        self.view_boundaries(session, calls)
        with patch.object(lifecycle, 'BoundHwpProcess', Bound), \
                patch.object(lifecycle, 'process_identity', side_effect=identity):
            record = self.smoke.run_case(session.suite, session.fixtures, session.output, 'calc',
                session_factory=lambda *args: session)
        self.assertTrue(record['success'], record.get('errorType'))
        self.assertEqual((record['kind'], record['case'], record['module']),
            ('native-menu-gesture-case', 'native-menu-calc', 'calc'))
        self.assertFalse(record['actualWindowsExecuted'])
        self.assertEqual(len(retained), 2)
        self.assertTrue(all(item.handle is None for item in retained))

    def test_calc_cancel_deadline_starts_before_native_exit_and_is_not_restarted(self):
        session, calls = self.finish_session('calc'); now, observed = [7], []
        original = session._native_command
        def command(name, record):
            result = original(name, record); now[0] += 4
            return result
        session._native_command = command
        session._cancel_calc_exit = lambda record, **kwargs: observed.append(kwargs.get('deadline')) or True
        with patch.object(self.smoke.time, 'monotonic', side_effect=lambda: now[0]), \
                patch('generated_calc_close.freeze_generated_blank_calc', return_value=object()):
            self.assertIs(session.finish({}), True)
        self.assertEqual(observed, [27])

    def cancel_session(self):
        session = self.smoke.WindowsSession(Path('/suite'), Path('/fixtures'), Path('/output'), 'calc')
        live = {21}; calls = []
        session.hwnd, session.process = 11, SimpleNamespace(pid=77)
        session.api = SimpleNamespace(windows=lambda pid: [21], pid=lambda h: 77,
            title=lambda h: 'OpenGeul Calc', class_name=lambda h: '#32770',
            require_foreground=lambda h: calls.append(('foreground', h)),
            user=SimpleNamespace(GetWindow=lambda h, f: 11, IsWindow=lambda h: h in live))
        session.native = SimpleNamespace(wait_for=lambda check, **kwargs: check(),
            require_dialog_identity=lambda *args: calls.append(('identity', args)))
        session.desktop = lambda **kwargs: self.fail('Unbounded UIA discovery must not be used')
        return session, live, calls

    def test_calc_cancel_uses_only_bounded_helper_schema_proof_and_original_remaining(self):
        session, live, calls = self.cancel_session(); observed = []
        receipt = dict(success=True, kind='owned-shell-menu-cancel',
            snapshots=[dict(promptSchemaVerified=True) for _ in range(3)])
        def cancel(*args, **kwargs):
            observed.append((args, kwargs)); live.remove(21)
            return receipt
        record = {}
        with patch.object(self.smoke.time, 'monotonic', return_value=18), \
                patch('owned_menu_cancel.cancel_native_menu_prompt', side_effect=cancel):
            self.assertIs(session._cancel_calc_exit(record, deadline=20), True)
        self.assertEqual(observed[0][0], (session.api, session.process, 11, record, 21, 'OpenGeul Calc'))
        self.assertEqual(observed[0][1], {'seconds': 2})
        self.assertIs(record['nativeExitCancelAction'], receipt)

    def test_calc_cancel_rejects_missing_or_unverified_prompt_schema_receipt(self):
        for snapshots in (None, [], [dict(promptSchemaVerified=False)], [{}]):
            with self.subTest(snapshots=snapshots):
                session, live, calls = self.cancel_session()
                result = dict(success=True, kind='owned-shell-menu-cancel', snapshots=snapshots)
                def cancel(*args, **kwargs):
                    live.remove(21); return result
                with patch.object(self.smoke.time, 'monotonic', return_value=18), \
                        patch('owned_menu_cancel.cancel_native_menu_prompt', side_effect=cancel), \
                        self.assertRaises(AssertionError):
                    session._cancel_calc_exit({}, deadline=20)


class InitialFocusStderrTests(unittest.TestCase):
    """Synthetic C# serializer shapes; no native query, focus or real log reads."""
    def setUp(self):
        self.smoke = load_smoke()
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.session = self.smoke.WindowsSession(self.folder/'suite', self.folder, self.folder, 'writer')
        self.session.hwnd, self.session.parent, self.session.child, self.session.office_pid = 11, 12, 13, 88
        self.session.process = SimpleNamespace(pid=77, _handle=777, opengeul_evidence_output=self.folder,
            opengeul_evidence_case='native-menu-writer', opengeul_suite_root=self.folder/'suite')
        self.session.engine = SimpleNamespace(handle=888, creation_time=200)
        self.session._opening_focus_identity = (77,777,888,200,11,12,13,88)
        self.record = dict(case='native-menu-writer',module='writer',shellPid=77,windowHwnd=11,
            parentHwnd=12,childHwnd=13,officePid=88,officeCreationTime=200,
            nativeArchiveGeneration=dict(pid=88,creationTime=200,
                image=str(self.folder/'suite/Office/program/soffice.bin')),
            windowActivations=[dict(suiteHwnd=11,shellPid=77,originalProcess=dict(pid=77,handleValue=777,creationTime=100,
                image=str(self.folder/'suite/OpenGeul.Office.exe'),waitResult=258))],
            openingFocusObservations=[dict(phaseCode=1,hostGui=dict(threadId=9),engineGui=dict(threadId=10))])
        self.path = self.folder/'native-menu-writer-stderr.log'

    def snapshot(self):
        def window(hwnd, pid, thread, parent):
            return dict(Hwnd=hwnd,Pid=pid,ThreadId=thread,Root=11 if hwnd else 0,Parent=parent,
                Exists=bool(hwnd),Visible=bool(hwnd),Enabled=bool(hwnd),ClassName='synthetic class, never exported')
        zero = window(0,0,0,0)
        return dict(Shell=dict(Pid=77,CreationTime=100,Image=str(self.folder/'suite/OpenGeul.Office.exe'),Alive=True),
            Engine=dict(Pid=88,CreationTime=200,Image=str(self.folder/'suite/Office/program/soffice.bin'),Alive=True),
            Form=window(11,77,9,0),Panel=window(12,77,9,11),Child=window(13,88,10,12),
            Foreground=window(11,77,9,0),Focus=window(11,77,9,0),EditorFocus=window(11,77,9,0),
            Capture=dict(zero),EditorCapture=dict(zero),CurrentThread=9,GuiQueriesSucceeded=True,GuiFlags=0,
            FormOwnsPanel=True,PanelOwnsChild=True,FocusWithinEditor=False,EditorFocusWithinEditor=False,
            RegisteredPanel=12,RegisteredChild=13,HostMenuOwner=0,EditorMenuOwner=0)

    def event(self, stage='initial', sequence=1, *, reason='initialPending', before=True):
        result = dict(Verified=False,Attempted=False,Reason=reason,Before=self.snapshot() if before else None,
            After=None,PreviousFocus=0,NativeError=0)
        details = dict(available=False,pending=True,result=result) if stage=='initial' else (
            dict(queued=True,pending=True) if stage=='initial.queued' else dict(pending=True,result=result))
        return dict(event='suite.editorFocus',component='host',stage=stage,sequence=sequence,
            utc='2026-11-06T00:00:00+00:00',processId=77,managedThreadId=1,
            workerProcessId=99,traceId='a'*32,details=details)

    def write(self, rows, *, suffix=b''):
        self.path.write_bytes(b''.join((json.dumps(row,separators=(',',':'))+'\r\n').encode()
            for row in rows)+suffix)

    def capture(self):
        method=getattr(self.smoke,'capture_initial_focus_trace',None)
        self.assertTrue(callable(method),'Bounded numeric initial-focus trace capture is missing')
        return method(self.session,self.record)

    def assert_unknown(self, value):
        self.assertIs(value['known'],False)
        self.assertEqual(value['rows'],[])
        self.assertIs(type(value['errorCode']),int)
        self.assertGreater(value['errorCode'],0)

    def test_pascal_case_snapshots_and_lower_case_envelope_are_numeric_only(self):
        self.write([self.event(),self.event('initial.queued',2),self.event('initial.activation',3)])
        value=self.capture()
        self.assertTrue(value['known']);self.assertEqual(value['errorCode'],0)
        self.assertEqual([row['stageCode'] for row in value['rows']],[1,2,3])
        self.assertEqual(value['rows'][0]['reasonCode'],4)
        self.assertFalse(value['rows'][0]['contextInherited'])
        self.assertTrue(value['rows'][1]['contextInherited'])
        self.assertEqual(value['rows'][0]['before']['Shell'],dict(Pid=77,CreationTime=100,Alive=True))
        def numeric(item):
            if type(item) is dict: return all(numeric(child) for child in item.values())
            if type(item) is list: return all(numeric(child) for child in item)
            return type(item) in (int,bool)
        self.assertTrue(numeric(value),'Trace output must contain only fixed keys and numbers/booleans')
        exported=json.dumps(value)
        for forbidden in ('initialPending','suite.editorFocus','synthetic class',str(self.folder),'a'*32):
            self.assertNotIn(forbidden,exported)

    def test_before_missing_queue_does_not_establish_a_new_context(self):
        self.write([self.event('initial.queued')]);self.assert_unknown(self.capture())

    def test_foreign_or_recycled_snapshot_generations_are_not_admitted(self):
        for component,key in (('Shell','Pid'),('Shell','CreationTime'),('Engine','Pid'),('Engine','CreationTime'),
                              ('Form','Hwnd'),('Panel','Parent'),('Child','ThreadId')):
            with self.subTest(component=component,key=key):
                row=self.event();row['details']['result']['Before'][component][key]+=1
                self.write([row]);self.assert_unknown(self.capture())

    def test_after_snapshot_is_joined_to_the_same_original_binding(self):
        row=self.event(reason='editorFocused');row['details']['result'].update(Verified=True,Attempted=True,After=self.snapshot())
        self.write([row]);self.assertTrue(self.capture()['known'])
        row['details']['result']['After']['Engine']['CreationTime']+=1
        self.write([row]);self.assert_unknown(self.capture())

    def test_queue_worker_trace_and_physical_sequence_cannot_change(self):
        for key,change in (('workerProcessId',100),('traceId','b'*32),('processId',78),('sequence',1),('sequence',0)):
            with self.subTest(key=key,change=change):
                queue=self.event('initial.queued',2);queue[key]=change
                self.write([self.event(),queue]);self.assert_unknown(self.capture())

    def test_failed_csharp_writes_may_leave_gaps_in_increasing_sequences(self):
        self.write([self.event(sequence=2),self.event('initial.queued',5)])
        value=self.capture();self.assertTrue(value['known'])
        self.assertEqual([row['sequence'] for row in value['rows']],[2,5])
        self.assertTrue(value.get('gapObserved',False),'Dropped C# writes must stay explicit')
        self.assertEqual(value['gapCount'],3)
        self.assertTrue(value['eventCompletenessUnknown'])
        self.assertFalse(value['acceptanceEligible'])

    def test_snapshot_visibility_and_readiness_changes_do_not_change_its_identity(self):
        first=self.event();later=self.event('initial.activation',2)
        later['details']['result']['Before']['Panel']['Enabled']=False
        later['details']['result']['Before']['Form']['Visible']=False
        self.write([first,later]);value=self.capture();self.assertTrue(value['known'])
        self.assertFalse(value['rows'][1]['before']['Panel']['Enabled'])

    def test_append_during_parsing_returns_unknown_instead_of_a_partial_success(self):
        self.write([self.event()]);decode=self.smoke.json.loads
        def append(raw,**kwargs):
            result=decode(raw,**kwargs)
            with self.path.open('ab') as stream: stream.write(b'synthetic concurrent append\n')
            return result
        with patch.object(self.smoke.json,'loads',side_effect=append):
            self.assert_unknown(self.capture())

    def test_other_case_or_original_popen_handle_is_unknown(self):
        self.write([self.event()])
        self.session.process.opengeul_evidence_case='native-menu-calc';self.assert_unknown(self.capture())
        self.session.process.opengeul_evidence_case='native-menu-writer'
        self.session.process._handle=778;self.assert_unknown(self.capture())

    def test_unknown_stage_reason_extra_field_and_noninteger_number_are_not_exported(self):
        changes=(lambda row:row.update(stage='synthetic unknown stage'),
            lambda row:row['details']['result'].update(Reason='synthetic unknown reason'),
            lambda row:row.update(body='synthetic forbidden body'),
            lambda row:row.update(sequence=True),
            lambda row:row['details']['result']['Before'].update(GuiFlags=1.5))
        for change in changes:
            row=self.event();change(row);self.write([row]);self.assert_unknown(self.capture())

    def test_partial_duplicate_json_and_nonfinite_numbers_are_unknown(self):
        valid=json.dumps(self.event(),separators=(',',':')).encode()
        for raw in (valid[:-1]+b'\n',valid,valid.replace(b'"sequence":1',b'"sequence":1,"sequence":1')+b'\n',
                    valid.replace(b'"GuiFlags":0',b'"GuiFlags":NaN')+b'\n'):
            self.path.write_bytes(raw);self.assert_unknown(self.capture())

    def test_only_the_exact_serializer_prefix_is_parsed(self):
        row=self.event();valid=json.dumps(row,separators=(',',':')).encode()+b'\n'
        self.path.write_bytes(b'synthetic unstructured line\n '+valid)
        self.assert_unknown(self.capture())
        self.path.write_bytes(b'synthetic unstructured line\n'+valid)
        self.assertTrue(self.capture()['known'])

    def test_regular_file_without_hardlinks_symlinks_or_parent_alias_is_required(self):
        self.write([self.event()]);other=self.folder/'synthetic-original.log';self.path.rename(other)
        try: self.path.symlink_to(other)
        except (OSError,NotImplementedError): self.skipTest('Filesystem symlinks unavailable')
        self.assert_unknown(self.capture());self.path.unlink()
        try: os.link(other,self.path)
        except OSError: self.skipTest('Filesystem hardlinks unavailable')
        self.assert_unknown(self.capture())

    def test_size_line_row_and_budget_bounds_return_unknown(self):
        self.path.write_bytes(b'x'*(2*1024*1024+1));self.assert_unknown(self.capture())
        self.path.write_bytes(b'x'*(64*1024+1)+b'\n');self.assert_unknown(self.capture())
        self.write([self.event(sequence=i+1) for i in range(129)]);self.assert_unknown(self.capture())
        self.write([self.event()])
        with patch.object(self.smoke.time,'monotonic',side_effect=[0.,2.]):
            self.assert_unknown(self.capture())

    def test_finally_captures_once_before_cleanup_without_replacing_primary_failure(self):
        boundary=Session(fail='open-escape');calls=[]
        def capture(session,record):
            calls.append('capture');raise RuntimeError('synthetic private capture failure')
        cleanup=boundary.cleanup
        boundary.cleanup=lambda record:calls.append('cleanup') or cleanup(record)
        with patch.object(self.smoke,'capture_initial_focus_trace',capture,create=True):
            record=self.smoke.run_case(self.folder,self.folder,self.folder,'writer',session_factory=lambda *args:boundary)
        self.assertEqual(calls,['capture','cleanup'])
        self.assertEqual(record['errorType'],'AssertionError');self.assertEqual(record['stage'],'open-escape')
        self.assertTrue(record['cleanupConfirmed']);self.assertFalse(record['success'])
        self.assert_unknown(record['initialFocusTrace'])
