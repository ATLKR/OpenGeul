"""읽기 전용 ARM 러너 관찰의 실행 경계·상한·무입력을 검증한다."""
import importlib.util
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module():
    path = ROOT / 'e2e/runner-ready.py'
    if not path.is_file():
        raise AssertionError('읽기 전용 runner-ready 관찰 도구가 필요합니다')
    spec = importlib.util.spec_from_file_location('runner_ready_tested', path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


ENV = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
       'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
       'GITHUB_REF': 'refs/heads/diagnostic/arm-runner-ready71', 'GITHUB_ACTOR': 'ATLKR',
       'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}


class Observer:
    """외부 Windows 관찰만 대체한다. 입력 동작은 구현하지 않는다."""
    def host(self):
        return {'processId': 100, 'processMachine': 0x8664, 'nativeMachine': 0xAA64}

    def windows(self):
        row = {'hwnd': 12, 'processId': 200, 'threadId': 201, 'title': 'Choose privacy settings for your device',
               'className': 'ApplicationFrameWindow', 'visible': True, 'enabled': True,
               'rectangle': [0, 0, 1200, 900]}
        return {'foregroundHwnd': 12, 'windows': [row], 'truncated': False}

    def processes(self, pids):
        return [{'processId': n, 'imagePath': 'C:\\Windows\\System32\\ApplicationFrameHost.exe',
                 'imageBytes': 1000, 'imageSha256': 'b' * 64, 'createdFileTime': 100000,
                 'sessionId': 1, 'processMachine': 0, 'nativeMachine': 0xAA64,
                 'signature': {'status': 'Valid', 'subject': 'CN=Microsoft Windows, O=Microsoft Corporation',
                 'issuer': 'CN=Microsoft Windows Production PCA', 'thumbprint': 'C' * 40,
                 'publisherMicrosoft': True}} for n in pids]

    def uia(self, hwnd):
        return {'hwnd': hwnd, 'nodes': [{'name': 'Next', 'controlType': 50000, 'automationId': 'Next',
                 'className': 'Button', 'processId': 200, 'enabled': True, 'offscreen': False}],
                'truncated': False}

    def screen(self, path):
        path.write_bytes(b'\x89PNG\r\n\x1a\nsynthetic-OS-observer-image')
        return {'width': 1200, 'height': 900}


class Kernel:
    def OpenProcess(self, *args): return 11
    def CloseHandle(self, handle): return True
    def GetProcessTimes(self, handle, created, *rest): created._obj.dwLowDateTime = 100000; return True
    def IsWow64Process2(self, handle, process, native): native._obj.value = 0xAA64; return True


class WindowUser:
    def IsWindow(self, hwnd): return True
    def GetForegroundWindow(self): return 12
    def GetWindowThreadProcessId(self, hwnd, pid): pid._obj.value = 200; return 201
    def GetWindowTextW(self, hwnd, text, count): text.value = 'Microsoft account'; return len(text.value)
    def GetClassNameW(self, hwnd, text, count): text.value = 'Windows.UI.Core.CoreWindow'; return len(text.value)
    def IsWindowVisible(self, hwnd): return True
    def IsWindowEnabled(self, hwnd): return True


class Dwm:
    def DwmGetWindowAttribute(self, hwnd, attribute, cloaked, size): return 0


class ApiCall:
    def __init__(self, callback): self.callback = callback
    def __call__(self, *args): return self.callback(*args)


class StartupFixture:
    """외부 WinAPI만 교체: own 창 생성 중 WSL fore 출현/자연 종료를 재현한다."""
    def __init__(self, value, *, expires=60, setter=True, change=None, exited_path_unavailable=False):
        self.value = value; self.clock = 0; self.expires = expires; self.setter = setter; self.change = change
        self.fore = 20; self.probe_exists = False; self.calls = []; self.closed = []; self.opened = []; self.signature_timeouts = []
        self.exited_path_unavailable = exited_path_unavailable
        self.directory = tempfile.TemporaryDirectory(); self.file = Path(self.directory.name) / 'synthetic-wsl.exe'
        data = bytearray(512); data[:2] = b'MZ'; data[60:64] = (128).to_bytes(4, 'little')
        data[128:132] = b'PE\x00\x00'; data[132:134] = (0xAA64).to_bytes(2, 'little'); self.file.write_bytes(data)
        self.process = Observer().processes([200])[0]
        self.process.update(imagePath='C:\\Windows\\System32\\wsl.exe', imageBytes=len(data), imageSha256=hashlib.sha256(data).hexdigest())
        self.window = {'hwnd': 12, 'processId': 200, 'threadId': 201,
            'title': self.process['imagePath'], 'className': 'ConsoleWindowClass',
            'visible': True, 'enabled': True, 'rectangle': [31, 104, 1024, 623]}
        def api(fn): return ApiCall(fn)
        self.user = SimpleNamespace(
            DefWindowProcW=api(lambda *a: 0), RegisterClassW=api(lambda *a: 1), UnregisterClassW=api(lambda *a: 1),
            CreateWindowExW=api(self.create), SetForegroundWindow=api(self.set_foreground),
            DestroyWindow=api(self.destroy), PeekMessageW=api(lambda *a: 0),
            TranslateMessage=api(lambda *a: 1), DispatchMessageW=api(lambda *a: 0),
            GetWindowThreadProcessId=api(self.owner), IsWindow=api(self.exists),
            GetForegroundWindow=api(self.foreground), GetWindowTextW=api(self.title),
            GetClassNameW=api(self.class_name), IsWindowVisible=api(self.exists), IsWindowEnabled=api(lambda h: 1))
        self.kernel = SimpleNamespace(GetModuleHandleW=api(lambda *a: 1), GetCurrentProcessId=api(lambda: 100),
            OpenProcess=api(lambda *a: self.opened.append(a) or 11), CloseHandle=api(lambda h: self.closed.append(h) or 1),
            GetProcessTimes=api(self.times), IsWow64Process2=api(self.native), GetExitCodeProcess=api(self.exit_code),
            ProcessIdToSessionId=api(self.session))
        self.probe = value.WindowsProbe.__new__(value.WindowsProbe); self.probe.user = self.user; self.probe.kernel = self.kernel
        self.probe.host = lambda: {'processId': 100, 'processMachine': 0, 'nativeMachine': 0xAA64}
        self.probe.windows_directory = lambda: 'C:\\Windows'; self.probe.session_id = lambda: 1
        self.probe.windows = self.windows; self.probe.processes = self.processes
    def create(self, *args): self.probe_exists = True; self.fore = 12; return 500
    def exists(self, hwnd): return self.probe_exists if hwnd == 500 else self.clock < self.expires
    def foreground(self):
        if self.change == 'foreignRetirement' and self.clock >= self.expires: return 777
        if self.fore == 12 and self.clock >= self.expires: return 0
        if self.change == 'foreignForeground' and self.clock > 0: return 777
        return self.fore
    def owner(self, hwnd, pid):
        pid._obj.value = 100 if hwnd == 500 else (999 if self.change == 'pid' and self.clock > 0 else 200)
        return 101 if hwnd == 500 else (999 if self.change == 'thread' and self.clock > 0 else 201)
    def title(self, hwnd, buffer, _): buffer.value = self.window['title']; return len(buffer.value)
    def class_name(self, hwnd, buffer, _): buffer.value = 'OtherClass' if self.change == 'class' and self.clock else self.window['className']; return len(buffer.value)
    def times(self, handle, created, *rest): created._obj.dwLowDateTime = 99999 if self.change == 'creation' and self.clock else 100000; return 1
    def native(self, handle, process, native): native._obj.value = 0x8664 if self.change == 'native' and self.clock else 0xAA64; return 1
    def session(self, pid, session): session._obj.value = 2 if self.change == 'session' and self.clock else 1; return 1
    def exit_code(self, handle, code): code._obj.value = 0 if self.clock >= self.expires else 259; return 1
    def set_foreground(self, hwnd):
        self.calls.append(('SetForegroundWindow', hwnd, self.clock))
        returned = self.setter and self.clock >= self.expires
        if returned: self.fore = 777 if self.change == 'afterActivation' else hwnd
        return returned
    def destroy(self, hwnd):
        if hwnd != 500: raise AssertionError('OS 창 종료 금지')
        self.probe_exists = False; return 1
    def windows(self):
        return {'foregroundHwnd': self.foreground(), 'windows': [copy.deepcopy(self.window)], 'truncated': False}
    def processes(self, pids):
        result = copy.deepcopy(self.process)
        if self.exited_path_unavailable and self.clock >= self.expires:
            result.update(imagePath='', imageBytes=0, imageSha256='', signature={
                'status': 'Unavailable', 'subject': '', 'issuer': '', 'thumbprint': '', 'publisherMicrosoft': False})
        if self.change == 'signature' and self.clock: result['signature']['status'] = 'NotSigned'
        if self.change == 'session' and self.clock: result['sessionId'] = 2
        if self.change == 'hash' and self.clock: result['imageSha256'] = 'c' * 64
        return [result]
    def sleep(self, duration):
        self.clock += duration
        if self.change == 'hash':
            data = bytearray(self.file.read_bytes()); data[-1] = 1; self.file.write_bytes(data)
        if self.change == 'pe':
            data = bytearray(self.file.read_bytes()); data[132:134] = (0x8664).to_bytes(2, 'little'); self.file.write_bytes(data)
        if self.change == 'missingFile' and self.file.exists(): self.file.unlink()
    def signature(self, args, **kwargs):
        if not self.opened: raise AssertionError('fresh file 서명 전에 동일 process handle 유지 필수')
        self.signature_timeouts.append(kwargs['timeout'])
        result = copy.deepcopy(self.process['signature']); result.pop('publisherMicrosoft')
        if self.change == 'initialSignature': result['status'] = 'NotSigned'
        if self.change == 'signature' and self.clock: result['status'] = 'NotSigned'
        return SimpleNamespace(returncode=0, stdout=json.dumps(result).encode())
    def run(self):
        import ctypes
        try:
            with patch.object(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE, create=True), \
                 patch.object(self.value.time, 'monotonic', lambda: self.clock), \
                 patch.object(self.value.time, 'sleep', self.sleep), \
                 patch.object(self.value, 'Path', lambda path: self.file if str(path) == self.process['imagePath'] else Path(path)), \
                 patch.object(self.value.subprocess, 'run', self.signature):
                return self.probe.focus_probe()
        finally: self.directory.cleanup()


class RunnerReadyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.event_path = Path(directory.name) / 'event.json'
        self.event = {'repository': {'full_name': 'ATLKR/OpenGeul', 'private': False, 'id': 1405493151},
                      'sender': {'login': 'ATLKR', 'id': 65988341, 'type': 'User'},
                      'ref': 'diagnostic/arm-runner-ready71'}
        self.event_path.write_text(json.dumps(self.event))
        context = patch.dict(ENV, {'GITHUB_EVENT_PATH': str(self.event_path), 'GITHUB_ACTOR_ID': '65988341',
                                  'GITHUB_JOB': 'observe',
                                  'GITHUB_WORKFLOW_REF': 'ATLKR/OpenGeul/.github/workflows/store-package.yml@refs/heads/diagnostic/arm-runner-ready71'})
        context.start()
        self.addCleanup(context.stop)

    def oobe(self):
        observed = {
            'foreground': {'hwnd': 12, 'processId': 200, 'threadId': 201, 'title': 'Microsoft account',
                           'className': 'Windows.UI.Core.CoreWindow', 'visible': True, 'enabled': True,
                           'rectangle': [0, 0, 1024, 768]},
            'processes': [{**Observer().processes([200])[0], 'imagePath': 'C:\\Windows\\System32\\WWAHost.exe'}],
            'uia': [{'hwnd': 12, 'truncated': False, 'nodes': [
                {'name': name, 'automationId': automation, 'controlType': kind, 'processId': 200,
                 'className': '', 'enabled': True, 'offscreen': False} for name, automation, kind in [
                    ('Choose privacy settings for your device', '', 50033), ('Windows Setup', '', 50006),
                    ('ms-appx-web://microsoft.windows.cloudexperiencehost/core/view/oobeLightFooterHost.html', '', 50033),
                    ('Next, tab through all privacy settings to continue', 'OobeSettingsAcceptButton', 50000)]]}]}
        return observed

    def test_known_signed_native_privacy_window_is_selected_without_accept_or_settings(self):
        candidate = module().privacy_candidate(self.oobe(), 1, 'C:\\Windows')
        self.assertEqual(candidate['hwnd'], 12)
        self.assertEqual(candidate['process']['imagePath'], 'C:\\Windows\\System32\\WWAHost.exe')
        self.assertEqual(candidate['operation'], 'WM_CLOSE')

    def search(self):
        observed = self.oobe(); observed['foreground']['title'] = 'Search'
        owner = observed['processes'][0]
        owner['imagePath'] = 'C:\\Windows\\SystemApps\\MicrosoftWindows.Client.CBS_cw5n1h2txyewy\\SearchHost.exe'
        nodes = [{'name': name, 'automationId': automation, 'controlType': kind, 'processId': pid,
                  'className': cls, 'enabled': True, 'offscreen': False}for name, automation, kind, pid, cls in [
                    ('Search', '', 50032, 200, 'Windows.UI.Core.CoreWindow'),
                    ('Search box', 'SearchTextBox', 50004, 200, 'RichEditBox'),
                    ('Search - Web content', '', 50033, 201, 'BrowserRootView'),
                    ('', '', 50033, 202, 'Intermediate D3D Window')]]
        observed['uia'][0]['nodes'] = nodes
        for pid in [201, 202]:
            child = copy.deepcopy(owner); child.update({'processId': pid, 'createdFileTime': 200000,
                'imagePath': 'C:\\Program Files (x86)\\Microsoft\\EdgeWebView\\Application\\154.0.4258.53\\msedgewebview2.exe'})
            child['signature']['subject'] = 'CN=Microsoft Corporation, O=Microsoft Corporation'
            observed['processes'].append(child)
        return observed

    def test_exact_signed_search_root_and_native_uia_children_are_selected_without_typing(self):
        candidate = module().search_candidate(self.search(), 1, 'C:\\Windows')
        self.assertEqual(candidate['kind'], 'SearchHost.exe'); self.assertEqual(candidate['operation'], 'WM_CLOSE')
        self.assertEqual([p['processId'] for p in candidate['boundUiaChildProcesses']], [201, 202])

    def test_readonly_timeline_observes_search_after_late_os_foreground_transition(self):
        value = module(); clock = [0.0]; reads = []
        class Delayed:
            def windows(self):
                reads.append(clock[0]); window = copy.deepcopy(self_outer.search()['foreground'])
                if clock[0] < 0.3: window.update({'hwnd': 20, 'title': 'Program Manager', 'className': 'Progman'})
                return {'foregroundHwnd': window['hwnd'], 'windows': [window], 'truncated': False}
        self_outer = self
        with patch.object(value.time, 'monotonic', lambda: clock[0]), patch.object(value.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            observed = value.foreground_transition(Delayed())
        self.assertEqual(observed['windowObservation']['foregroundHwnd'], 12)
        self.assertEqual(observed['samples'][0]['foreground']['title'], 'Program Manager')
        self.assertEqual(observed['samples'][-1]['foreground']['title'], 'Search')
        self.assertLessEqual(len(reads), 21); self.assertLessEqual(clock[0], 2.0)

    def test_search_root_textbox_and_child_identity_changes_are_rejected(self):
        for change in ('root', 'textbox', 'textbox-pid', 'child-pid', 'child-path', 'child-native', 'child-session', 'child-creation', 'child-signature'):
            observed = self.search(); tree = observed['uia'][0]; child = observed['processes'][1]
            if change == 'root': tree['nodes'][0]['processId'] = 999
            if change == 'textbox': tree['nodes'][1]['automationId'] = 'AnotherBox'
            if change == 'textbox-pid': tree['nodes'][1]['processId'] = 201
            if change == 'child-pid': child['processId'] = 999
            if change == 'child-path': child['imagePath'] = 'C:\\Other\\msedgewebview2.exe'
            if change == 'child-native': child['processMachine'] = 0x8664
            if change == 'child-session': child['sessionId'] = 2
            if change == 'child-creation': child['createdFileTime'] = 1
            if change == 'child-signature': child['signature']['status'] = 'NotSigned'
            with self.subTest(change=change), self.assertRaises(ValueError): module().search_candidate(observed, 1, 'C:\\Windows')

    def test_privacy_selection_rejects_changed_owner_native_session_signature_and_context(self):
        for change in ('pid', 'creation', 'path', 'signature', 'publisher', 'native', 'session',
                       'class', 'title', 'disabled', 'hidden', 'uia-owner', 'uia-error', 'uia-truncated', 'context', 'next-id'):
            observed = self.oobe(); window = observed['foreground']; process = observed['processes'][0]; tree = observed['uia'][0]
            if change == 'pid': process['processId'] = 999
            elif change == 'creation': process['createdFileTime'] = 0
            elif change == 'path': process['imagePath'] = 'C:\\attacker\\WWAHost.exe'
            elif change == 'signature': process['signature']['status'] = 'NotSigned'
            elif change == 'publisher': process['signature']['subject'] = 'CN=Other publisher'
            elif change == 'native': process['processMachine'] = 0x8664
            elif change == 'session': process['sessionId'] = 2
            elif change == 'class': window['className'] = '#32770'
            elif change == 'title': window['title'] = 'Another account'
            elif change == 'disabled': window['enabled'] = False
            elif change == 'hidden': window['visible'] = False
            elif change == 'uia-owner': tree['nodes'][0]['processId'] = 999
            elif change == 'uia-error': tree['error'] = {'type': 'COMError', 'hresult': '0x80070005'}
            elif change == 'uia-truncated': tree['truncated'] = True
            elif change == 'context': tree['nodes'][2]['name'] = 'Untrusted document'
            elif change == 'next-id': tree['nodes'][3]['automationId'] = 'UnknownNext'
            with self.subTest(change=change), self.assertRaises(ValueError):
                module().privacy_candidate(observed, 1, 'C:\\Windows')

    def test_actual_close_method_rechecks_bound_identity_before_one_normal_close(self):
        value = module(); observed = self.oobe(); candidate = value.privacy_candidate(observed, 1, 'C:\\Windows')
        probe = value.WindowsProbe.__new__(value.WindowsProbe); calls = []
        class User(WindowUser):
            def GetWindowThreadProcessId(self, hwnd, pid): pid._obj.value = 200; return 201
            def GetForegroundWindow(self): return 12
            def SendMessageTimeoutW(self, *args): calls.append(args[:4]); return 1
            def IsWindow(self, hwnd): return not calls
        probe.user = User(); probe.current = lambda hwnd: copy.deepcopy(observed)
        probe.kernel = Kernel()
        probe.dwm = Dwm()
        probe.session_id = lambda: 1; probe.windows_directory = lambda: 'C:\\Windows'
        result = probe.close_verified(candidate)
        self.assertEqual(calls, [(12, 0x0010, 0, 0)])
        self.assertTrue(result['messageDelivered']); self.assertTrue(result['windowDisappeared'])

    def test_post_send_destruction_race_is_success_and_error_or_reuse_keeps_request_receipt(self):
        value = module()
        for condition in ('destroyed', 'reused', 'error'):
            observed = self.oobe(); candidate = value.privacy_candidate(observed, 1, 'C:\\Windows'); calls = []
            class User(WindowUser):
                def GetForegroundWindow(self): return 12
                def GetWindowThreadProcessId(self, hwnd, pid):
                    pid._obj.value = 200 if not calls else (0 if condition == 'destroyed' else 999); return 201
                def SendMessageTimeoutW(self, *args): calls.append(args[:4]); return 1
                def IsWindow(self, hwnd):
                    if not calls: return True
                    if condition == 'error': raise OSError('external API observation failed')
                    self.checks = getattr(self, 'checks', 0) + 1
                    return condition == 'reused' or self.checks == 1
            probe = value.WindowsProbe.__new__(value.WindowsProbe)
            probe.user = User(); probe.kernel = Kernel(); probe.current = lambda hwnd: copy.deepcopy(observed)
            probe.dwm = Dwm()
            probe.session_id = lambda: 1; probe.windows_directory = lambda: 'C:\\Windows'
            result = probe.close_verified(candidate)
            with self.subTest(condition=condition):
                self.assertEqual(calls, [(12, 0x0010, 0, 0)])
                self.assertEqual(result['messageRequests'], 1)
                self.assertEqual(result['windowDisappeared'], condition == 'destroyed')
                self.assertEqual(result['ownershipChangedAfterSend'], condition == 'reused')
                self.assertEqual(result['postSendErrorType'], 'OSError' if condition == 'error' else None)

    def test_native_state_distinguishes_destroyed_hidden_cloaked_and_active_surface(self):
        value = module(); candidate = value.privacy_candidate(self.oobe(), 1, 'C:\\Windows')
        for condition in ('destroyed', 'hidden', 'cloaked', 'active'):
            probe = value.WindowsProbe.__new__(value.WindowsProbe); probe.user = WindowUser(); probe.kernel = Kernel(); probe.dwm = Dwm()
            if condition == 'destroyed': probe.user.IsWindow = lambda hwnd: False
            if condition in ('hidden', 'cloaked'): probe.user.GetForegroundWindow = lambda: 20
            if condition == 'hidden': probe.user.IsWindowVisible = lambda hwnd: False
            if condition == 'cloaked':
                def cloak(hwnd, attr, out, size): self.assertEqual(attr, 14); out._obj.value = 2; return 0
                probe.dwm.DwmGetWindowAttribute = cloak
            state = probe.window_state(candidate, 11)
            with self.subTest(condition=condition):
                self.assertEqual(state['dismissalKind'], 'unconfirmed' if condition == 'active' else condition)
                self.assertEqual(state['surfaceDismissed'], condition != 'active')
                self.assertEqual(state['windowExists'], condition != 'destroyed')

    def test_foreign_identity_active_cloak_or_unknown_dwm_cannot_prove_dismissal(self):
        value = module(); candidate = value.privacy_candidate(self.oobe(), 1, 'C:\\Windows')
        for condition in ('pid', 'title', 'class', 'creation', 'native', 'active-cloak', 'dwm-error'):
            probe = value.WindowsProbe.__new__(value.WindowsProbe); probe.user = WindowUser(); probe.kernel = Kernel(); probe.dwm = Dwm()
            probe.user.GetForegroundWindow = lambda: 20
            def cloak(hwnd, attr, out, size): out._obj.value = 2; return 0
            probe.dwm.DwmGetWindowAttribute = cloak
            if condition == 'pid': probe.user.GetWindowThreadProcessId = lambda *args: 0
            if condition == 'title': probe.user.GetWindowTextW = lambda *args: 0
            if condition == 'class': probe.user.GetClassNameW = lambda *args: 0
            if condition == 'creation': probe.kernel.GetProcessTimes = lambda *args: False
            if condition == 'native': probe.kernel.IsWow64Process2 = lambda *args: False
            if condition == 'active-cloak': probe.user.GetForegroundWindow = lambda: 12
            if condition == 'dwm-error': probe.dwm.DwmGetWindowAttribute = lambda *args: -2147024891
            with self.subTest(condition=condition): self.assertFalse(probe.window_state(candidate, 11)['surfaceDismissed'])

    def test_held_process_creation_native_or_final_hwnd_owner_change_never_sends_close(self):
        value = module()
        for condition in ('creation', 'native', 'pid', 'foreground'):
            observed = self.oobe(); candidate = value.privacy_candidate(observed, 1, 'C:\\Windows')
            kernel = Kernel()
            if condition == 'creation': kernel.GetProcessTimes = lambda *args: False
            if condition == 'native': kernel.IsWow64Process2 = lambda *args: False
            user = SimpleNamespace(GetWindowThreadProcessId=lambda *args: 0,
                                   SendMessageTimeoutW=lambda *args: self.fail('held owner 검증 실패 후 입력 금지'))
            if condition == 'foreground':
                def owner(hwnd, pid): pid._obj.value = 200; return 201
                user.GetWindowThreadProcessId = owner; user.GetForegroundWindow = lambda: 99
            probe = value.WindowsProbe.__new__(value.WindowsProbe)
            probe.user = user; probe.kernel = kernel; probe.current = lambda hwnd: copy.deepcopy(observed)
            probe.session_id = lambda: 1; probe.windows_directory = lambda: 'C:\\Windows'
            with self.subTest(condition=condition), self.assertRaises(ValueError): probe.close_verified(candidate)

    def test_close_recheck_changed_pid_creation_hash_or_window_never_sends_input(self):
        value = module()
        for change in ('pid', 'creation', 'hash', 'thread', 'class', 'signature'):
            observed = self.oobe(); candidate = value.privacy_candidate(observed, 1, 'C:\\Windows')
            fresh = copy.deepcopy(observed)
            if change == 'pid': fresh['processes'][0]['processId'] = 999
            elif change == 'creation': fresh['processes'][0]['createdFileTime'] += 1
            elif change == 'hash': fresh['processes'][0]['imageSha256'] = 'c' * 64
            elif change == 'thread': fresh['foreground']['threadId'] += 1
            elif change == 'class': fresh['foreground']['className'] = 'OtherClass'
            elif change == 'signature': fresh['processes'][0]['signature']['status'] = 'NotSigned'
            probe = value.WindowsProbe.__new__(value.WindowsProbe)
            probe.user = SimpleNamespace(SendMessageTimeoutW=lambda *args: self.fail('검증 실패 후 입력 금지'))
            probe.current = lambda hwnd: fresh; probe.session_id = lambda: 1; probe.windows_directory = lambda: 'C:\\Windows'
            with self.subTest(change=change), self.assertRaises(ValueError): probe.close_verified(candidate)

    def test_production_scope_requires_exact_source_workflow_push_main(self):
        value = module()
        self.event_path.write_text(json.dumps({**self.event, 'ref': 'refs/heads/main', 'deleted': False}))
        production = {**ENV, 'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'push',
                      'GITHUB_JOB': 'native-e2e-arm64',
                      'GITHUB_WORKFLOW_REF': 'ATLKR/OpenGeul/.github/workflows/msix.yml@refs/heads/main'}
        self.assertEqual(value.binding(production)['ref'], 'refs/heads/main')
        for workflow in ('', 'Other/repo/.github/workflows/msix.yml@refs/heads/main',
                         'ATLKR/OpenGeul/.github/workflows/store-package.yml@refs/heads/main'):
            with self.subTest(workflow=workflow), self.assertRaises(ValueError):
                value.binding({**production, 'GITHUB_WORKFLOW_REF': workflow})

    def test_prepare_retains_before_after_and_separates_normal_close_from_consent(self):
        value = module(); observation = self.oobe(); calls = []
        class Ready(Observer):
            def windows(self):
                window = copy.deepcopy(observation['foreground'])
                if calls: window.update({'hwnd': 20, 'title': 'Program Manager', 'className': 'Progman'})
                return {'foregroundHwnd': window['hwnd'], 'windows': [window], 'truncated': False}
            def processes(self, pids): return copy.deepcopy(observation['processes'])
            def uia(self, hwnd):
                if hwnd == 12: return copy.deepcopy(observation['uia'][0])
                return {'hwnd': hwnd, 'nodes': [], 'truncated': False}
            def session_id(self): return 1
            def windows_directory(self): return 'C:\\Windows'
            def close_verified(self, candidate):
                calls.append('WM_CLOSE')
                return {'messageRequests': 1, 'messageDelivered': True, 'windowDisappeared': True}
            def focus_probe(self):
                calls.append('owned-focus')
                return {'setForegroundReturned': True, 'foregroundMatched': True, 'ownedWindowRemoved': True}
        with tempfile.TemporaryDirectory() as d:
            result = value.prepare(Ready(), ENV, Path(d) / 'ready')
            self.assertEqual(calls, ['WM_CLOSE', 'owned-focus'])
            self.assertTrue(result['hostReadyQualified']); self.assertFalse(result['sourceQualified'])
            self.assertFalse(result['readOnly']); self.assertEqual(result['inputsPerformed'], 1)
            self.assertEqual(result['consentInputsPerformed'], 0); self.assertEqual(result['registryWrites'], 0)
            self.assertEqual(result['processTerminations'], 0)
            self.assertTrue((Path(d) / 'ready/before/observation.json').is_file())
            self.assertTrue((Path(d) / 'ready/after/observation.json').is_file())

    def test_failed_close_keeps_action_receipt_and_never_focuses_or_retries(self):
        value = module(); observation = self.oobe(); calls = []
        class Ready(Observer):
            def windows(self): return {'foregroundHwnd': 12, 'windows': [observation['foreground']], 'truncated': False}
            def processes(self, pids): return copy.deepcopy(observation['processes'])
            def uia(self, hwnd): return copy.deepcopy(observation['uia'][0])
            def session_id(self): return 1
            def windows_directory(self): return 'C:\\Windows'
            def close_verified(self, candidate):
                calls.append('WM_CLOSE'); return {'messageRequests': 1, 'messageDelivered': True, 'windowDisappeared': False}
            def focus_probe(self): self.fail('실패한 close 후 focus/retry 금지')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): value.prepare(Ready(), ENV, Path(d) / 'ready')
            result = json.loads((Path(d) / 'ready/preparation.json').read_text())
            self.assertEqual(calls, ['WM_CLOSE']); self.assertEqual(len(result['actions']), 1)
            self.assertEqual(result['inputsPerformed'], 1); self.assertFalse(result['hostReadyQualified'])
            self.assertFalse(result['sourceQualified']); self.assertTrue(result['afterObservationRetained'])

    def test_failed_focus_setter_never_qualifies_even_if_foreground_matches(self):
        value = module(); observer = Observer()
        observer.focus_probe = lambda: {'setForegroundReturned': False, 'foregroundMatched': True, 'ownedWindowRemoved': True}
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): value.prepare(observer, ENV, Path(d) / 'ready')
            result = json.loads((Path(d) / 'ready/preparation.json').read_text())
            self.assertFalse(result['hostReadyQualified']); self.assertFalse(result['sourceQualified'])
            self.assertEqual(result['stage'], 'ownedFocusProbe'); self.assertEqual(result['actions'], [])

    def test_actual_probe_waits_for_wsl_appearing_during_create_then_one_setter(self):
        fixture = StartupFixture(module())
        result = fixture.run()
        self.assertTrue(result['setForegroundReturned']); self.assertTrue(result['foregroundMatched'])
        self.assertTrue(result['ownedWindowRemoved'])
        self.assertEqual(len(fixture.calls), 1); self.assertEqual(fixture.calls[0][:2], ('SetForegroundWindow', 500))
        self.assertGreaterEqual(fixture.calls[0][2], 60)
        self.assertTrue(result['startupWait']['naturalProcessExitObserved'])
        self.assertEqual(result['startupWait']['timeoutSeconds'], 65)

    def test_actual_probe_wsl_deadline_performs_no_activation_or_os_input(self):
        fixture = StartupFixture(module(), expires=1000)
        with self.assertRaises(ValueError): fixture.run()
        self.assertEqual(fixture.calls, []); self.assertLessEqual(fixture.clock, 65)
        self.assertFalse(fixture.probe_exists); self.assertEqual(fixture.closed, [11])

    def test_actual_wait_rejects_owner_generation_native_signature_session_and_foreign_changes(self):
        for change in ('pid', 'thread', 'class', 'creation', 'native', 'signature', 'session', 'hash', 'foreignForeground'):
            fixture = StartupFixture(module(), change=change)
            with self.subTest(change=change), self.assertRaises(ValueError): fixture.run()
            self.assertEqual(fixture.calls, []); self.assertFalse(fixture.probe_exists)

    def test_false_setter_or_foreign_after_wait_still_cannot_match(self):
        for setter, change in ((False, None), (True, 'afterActivation')):
            fixture = StartupFixture(module(), expires=1, setter=setter, change=change)
            result = fixture.run()
            self.assertFalse(result['setForegroundReturned'] and result['foregroundMatched'])
            self.assertEqual(len(fixture.calls), 1); self.assertTrue(result['ownedWindowRemoved'])

    def test_unknown_foreground_at_natural_exit_never_activates_probe(self):
        fixture = StartupFixture(module(), expires=1, change='foreignRetirement')
        with self.assertRaises(ValueError): fixture.run()
        self.assertEqual(fixture.calls, []); self.assertFalse(fixture.probe_exists)

    def test_actual44_dead_process_blank_image_query_uses_separate_verified_disk_image(self):
        fixture = StartupFixture(module(), expires=1, exited_path_unavailable=True)
        result = fixture.run()
        self.assertTrue(result['foregroundMatched']); self.assertEqual(len(fixture.calls), 1)
        trace = result['startupWait']
        self.assertEqual(trace['liveBoundImage'], trace['postExitImage'])
        self.assertEqual(trace['postExitHeldIdentity']['sessionId'], 1)
        self.assertTrue(trace['naturalProcessExitObserved'])

    def test_separate_image_read_rejects_wrong_pe_missing_disk_and_blank_live_binding(self):
        for change in ('pe', 'missingFile', 'liveBlank'):
            fixture = StartupFixture(module(), expires=1, change=change, exited_path_unavailable=True)
            if change == 'liveBlank': fixture.process.update(imagePath='', imageBytes=0, imageSha256='')
            with self.subTest(change=change), self.assertRaises(ValueError): fixture.run()
            self.assertEqual(fixture.calls, []); self.assertFalse(fixture.probe_exists)

    def test_held_handle_precedes_fresh_image_and_is_closed_on_initial_image_rejection(self):
        fixture = StartupFixture(module(), expires=1, change='initialSignature')
        with self.assertRaises(ValueError): fixture.run()
        self.assertEqual(len(fixture.opened), 1); self.assertEqual(fixture.closed, [11])
        self.assertEqual(fixture.calls, []); self.assertFalse(fixture.probe_exists)

    def test_post_exit_signature_uses_only_remaining_startup_budget(self):
        fixture = StartupFixture(module(), expires=64.75, exited_path_unavailable=True)
        result = fixture.run()
        self.assertTrue(result['foregroundMatched'])
        self.assertEqual(fixture.signature_timeouts, [20, 0.25])
        self.assertLessEqual(fixture.calls[0][2], 65)

    def test_expired_bound_image_budget_never_starts_signature(self):
        fixture = StartupFixture(module())
        try:
            with patch.object(fixture.value.time, 'monotonic', lambda: 1), self.assertRaises(ValueError):
                fixture.probe.bound_image(fixture.process['imagePath'], deadline=1)
            self.assertEqual(fixture.signature_timeouts, [])
        finally: fixture.directory.cleanup()

    def test_actual_windows_reader_keeps_foreground_ahead_of_hidden_window_cap(self):
        value = module(); probe = value.WindowsProbe.__new__(value.WindowsProbe)
        class User:
            def GetForegroundWindow(self): return 1000
            def EnumWindows(self, callback, _):
                for hwnd in [*range(1, 100), 1000]:
                    if not callback(hwnd, 0): break
            def GetWindowThreadProcessId(self, hwnd, pid): pid._obj.value = hwnd + 100; return hwnd + 200
            def GetWindowTextW(self, hwnd, buffer, _): buffer.value = 'Privacy' if hwnd == 1000 else ''; return len(buffer.value)
            def GetClassNameW(self, hwnd, buffer, _): buffer.value = 'Windows.UI.Core.CoreWindow'; return len(buffer.value)
            def GetWindowRect(self, hwnd, rect): return True
            def IsWindowVisible(self, hwnd): return hwnd == 1000
            def IsWindowEnabled(self, hwnd): return True
        probe.user = User(); probe.callback = lambda callback: callback
        observed = probe.windows(); value.validate_windows(observed)
        self.assertEqual(len(observed['windows']), 64)
        self.assertTrue(observed['truncated'])
        self.assertEqual(observed['windows'][0]['hwnd'], 1000)
        self.assertEqual(observed['windows'][0]['processId'], 1100)

    def test_actual_uia_reader_uses_standard_control_view_walker_without_value_pattern(self):
        value = module(); probe = value.WindowsProbe.__new__(value.WindowsProbe)
        child = SimpleNamespace(CurrentName='Next', CurrentControlType=50000, CurrentAutomationId='Next',
                                CurrentClassName='Button', CurrentProcessId=200, CurrentIsEnabled=True, CurrentIsOffscreen=False)
        root = SimpleNamespace(CurrentName='Privacy', CurrentControlType=50032, CurrentAutomationId='',
                               CurrentClassName='Windows.UI.Core.CoreWindow', CurrentProcessId=200,
                               CurrentIsEnabled=True, CurrentIsOffscreen=False)
        walker = SimpleNamespace(GetFirstChildElement=lambda element: child if element is root else None,
                                 GetNextSiblingElement=lambda element: None)
        # IUIA owns the COM interface; ControlViewWalker is the standard UIAutomation property.
        api = SimpleNamespace(iuia=SimpleNamespace(ElementFromHandle=lambda hwnd: root, ControlViewWalker=walker))
        with patch.dict('sys.modules', {'pywinauto': SimpleNamespace(),
                        'pywinauto.uia_defines': SimpleNamespace(IUIA=lambda: api)}):
            observed = probe.uia(12)
        value.validate_uia(observed, 12)
        self.assertNotIn('error', observed)
        self.assertEqual([row['name'] for row in observed['nodes']], ['Privacy', 'Next'])
        self.assertEqual([row['processId'] for row in observed['nodes']], [200, 200])

    def test_emulated_controller_native_arm_host_is_observed_without_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'proof'
            value = module().observe(Observer(), ENV, out)
            self.assertEqual(value['controller']['processMachine'], 0x8664)
            self.assertEqual(value['controller']['nativeMachine'], 0xAA64)
            self.assertFalse(value['controller']['native'])
            self.assertEqual(value['foreground']['hwnd'], 12)
            self.assertEqual(value['uia'][0]['nodes'][0]['name'], 'Next')
            self.assertTrue(value['readOnly'])
            self.assertFalse(value['sourceQualified'])
            self.assertFalse(value['productExecuted'])
            self.assertEqual(value['inputsPerformed'], 0)
            self.assertEqual(json.loads((out / 'observation.json').read_bytes()), value)

    def test_foreign_context_or_attempt_never_creates_evidence(self):
        for key, val in [('GITHUB_ACTIONS', 'false'), ('RUNNER_ENVIRONMENT', 'self-hosted'),
                         ('GITHUB_REPOSITORY', 'other/repo'), ('GITHUB_REF', 'refs/heads/main'),
                         ('GITHUB_ACTOR', 'other'), ('GITHUB_EVENT_NAME', 'push'),
                         ('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_SHA', 'wrong')]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as d:
                out = Path(d) / 'proof'
                with self.assertRaises(ValueError): module().observe(Observer(), {**ENV, key: val}, out)
                self.assertFalse(out.exists())

    def test_x64_host_or_wrong_controller_machine_is_rejected(self):
        for pair in [(0, 0x8664), (0x14c, 0xAA64)]:
            observer = Observer()
            observer.host = lambda: {'processId': 100, 'processMachine': pair[0], 'nativeMachine': pair[1]}
            with self.subTest(pair=pair), tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError): module().observe(observer, ENV, Path(d) / 'proof')

    def test_no_raw_environment_arguments_or_uia_values_are_written(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'proof'
            module().observe(Observer(), {**ENV, 'SECRET': 'private-test-value'}, out)
            raw = (out / 'observation.json').read_text()
            self.assertNotIn('private-test-value', raw)
            self.assertNotIn('argv', raw)
            self.assertNotIn('environment', raw)
            observer = Observer()
            observer.uia = lambda h: {'hwnd': h, 'nodes': [{'Value': 'private-test-value'}], 'truncated': False}
            with self.assertRaises(ValueError): module().observe(observer, ENV, Path(d) / 'other')

    def test_metadata_bounds_and_duplicate_handles_are_rejected(self):
        for change in ('title', 'count', 'duplicate', 'uia'):
            observer = Observer()
            original = observer.windows()
            if change == 'title': original['windows'][0]['title'] = 'x' * 257
            if change == 'count': original['windows'] *= 65
            if change == 'duplicate': original['windows'] *= 2
            observer.windows = lambda: original
            if change == 'uia': observer.uia = lambda h: {'hwnd': h, 'nodes': [Observer().uia(h)['nodes'][0]] * 65, 'truncated': False}
            with self.subTest(change=change), tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError): module().observe(observer, ENV, Path(d) / 'proof')

    def test_existing_output_and_reparse_alias_are_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'proof'; out.mkdir(); keep = out / 'keep'; keep.write_bytes(b'prior')
            with self.assertRaises(ValueError): module().observe(Observer(), ENV, out)
            self.assertEqual(keep.read_bytes(), b'prior')
            link = Path(d) / 'alias'; link.symlink_to(out, target_is_directory=True)
            with self.assertRaises(ValueError): module().observe(Observer(), ENV, link / 'new')
            self.assertFalse((out / 'new').exists())


if __name__ == '__main__': unittest.main()
