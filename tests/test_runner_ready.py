"""읽기 전용 ARM 러너 관찰의 실행 경계·상한·무입력을 검증한다."""
import importlib.util
import ctypes
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
    # Two legacy phase-diagnostic tests supply only a bounded snapshot and stop
    # before process binding. Adapt that owned fixture to the now-mandatory
    # native collector; a truncated snapshot supplies no completion capability.
    actual_wait = value.WindowsProbe.wait_startup_foreground
    def wait_with_snapshot_fixture(probe, owned, result):
        if hasattr(probe, 'user'): return actual_wait(probe, owned, result)
        original = probe.windows; last_error = [0]
        def snapshot():
            observed = original()
            if not observed['truncated']:
                rows = {row['hwnd']:row for row in observed['windows']}
                class NativeSnapshot:
                    def GetForegroundWindow(self): return observed['foregroundHwnd']
                    def EnumWindows(self, callback, _):
                        return all(callback(hwnd, 0) for hwnd in rows)
                    def IsWindow(self, hwnd): return hwnd in rows
                    def GetWindowThreadProcessId(self, hwnd, owner): owner._obj.value = rows[hwnd]['processId']; return rows[hwnd]['threadId']
                    def GetWindowTextLengthW(self, hwnd): return len(rows[hwnd]['title'].encode('utf-16-le'))//2
                    def GetWindowTextW(self, hwnd, buffer, _): buffer.value = rows[hwnd]['title']; return len(buffer.value.encode('utf-16-le'))//2
                    def GetClassNameW(self, hwnd, buffer, _): buffer.value = rows[hwnd]['className']; return len(buffer.value.encode('utf-16-le'))//2
                    def GetWindowRect(self, hwnd, rect):
                        rect._obj.left, rect._obj.top, rect._obj.right, rect._obj.bottom = rows[hwnd]['rectangle']; return 1
                    def IsWindowVisible(self, hwnd): return rows[hwnd]['visible']
                    def IsWindowEnabled(self, hwnd): return rows[hwnd]['enabled']
                probe.user = NativeSnapshot(); probe.callback = lambda callback: callback
            return observed
        probe.windows = snapshot
        try:
            with patch.object(value.ctypes, 'set_last_error', lambda number: last_error.__setitem__(0, number), create=True), \
                 patch.object(value.ctypes, 'get_last_error', lambda: last_error[0], create=True):
                return actual_wait(probe, owned, result)
        finally: probe.windows = original
    value.WindowsProbe.wait_startup_foreground = wait_with_snapshot_fixture
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
        self.fore = 20; self.probe_exists = False; self.calls = []; self.shows = []; self.closed = []; self.opened = []; self.signature_timeouts = []
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
            CreateWindowExW=api(self.create), ShowWindow=api(self.show), SetForegroundWindow=api(self.set_foreground),
            DestroyWindow=api(self.destroy), PeekMessageW=api(lambda *a: 0),
            TranslateMessage=api(lambda *a: 1), DispatchMessageW=api(lambda *a: 0),
            GetWindowThreadProcessId=api(self.owner), IsWindow=api(self.exists),
            GetForegroundWindow=api(self.foreground), GetWindowTextW=api(self.title),
            GetClassNameW=api(self.class_name), IsWindowVisible=api(self.exists), IsWindowEnabled=api(lambda h: 1))
        self._enum_active = False; self._enum_rows = {}
        self.user.EnumWindows = api(self.enum_windows)
        self.user.GetWindowTextLengthW = api(self.title_length)
        self.user.GetWindowRect = api(self.rectangle)
        self.user.IsWindowVisible = api(lambda hwnd: self._enum_rows[hwnd]['visible'] if self._enum_active else self.exists(hwnd))
        self.user.IsWindowEnabled = api(lambda hwnd: self._enum_rows[hwnd]['enabled'] if self._enum_active else True)
        self.kernel = SimpleNamespace(GetModuleHandleW=api(lambda *a: 1), GetCurrentProcessId=api(lambda: 100),
            OpenProcess=api(lambda *a: self.opened.append(a) or 11), CloseHandle=api(lambda h: self.closed.append(h) or 1),
            GetProcessTimes=api(self.times), IsWow64Process2=api(self.native), GetExitCodeProcess=api(self.exit_code),
            ProcessIdToSessionId=api(self.session))
        self.probe = value.WindowsProbe.__new__(value.WindowsProbe); self.probe.user = self.user; self.probe.kernel = self.kernel
        self.probe.host = lambda: {'processId': 100, 'processMachine': 0, 'nativeMachine': 0xAA64}
        self.probe.windows_directory = lambda: 'C:\\Windows'; self.probe.session_id = lambda: 1
        self.probe.windows = self.windows; self.probe.processes = self.processes
        self.probe.callback = lambda callback: callback
    def enum_windows(self, callback, _):
        observation = self.probe.windows(); self._enum_rows = {row['hwnd']:row for row in observation['windows']}
        self._enum_active = True
        try: return all(callback(hwnd, 0) for hwnd in self._enum_rows) and not observation['truncated']
        finally: self._enum_active = False
    def title_length(self, hwnd):
        buffer = ctypes.create_unicode_buffer(257); self.title(hwnd, buffer, 257)
        return len(buffer.value.encode('utf-16-le'))//2
    def rectangle(self, hwnd, rect):
        row = self._enum_rows.get(hwnd, self.desktop if hwnd == 20 and hasattr(self, 'desktop') else self.window)
        rect._obj.left, rect._obj.top, rect._obj.right, rect._obj.bottom = row['rectangle']; return True
    def create(self, *args): self.probe_exists = True; self.fore = 12; return 500
    def show(self, hwnd, command): self.shows.append((hwnd, command, self.clock)); return 0
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
    def processes(self, pids, *, deadline=None):
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
    def file_for_path(self, path):
        return self.file if str(path) == self.process['imagePath'] else Path(path)
    def run(self):
        import ctypes
        last_error = [0]
        try:
            with patch.object(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE, create=True), \
                 patch.object(self.value.time, 'monotonic', lambda: self.clock), \
                 patch.object(self.value.time, 'sleep', self.sleep), \
                 patch.object(self.value.ctypes, 'set_last_error', lambda number: last_error.__setitem__(0, number), create=True), \
                 patch.object(self.value.ctypes, 'get_last_error', lambda: last_error[0], create=True), \
                 patch.object(self.value, 'Path', self.file_for_path), \
                 patch.object(self.value.subprocess, 'run', self.signature):
                return self.probe.focus_probe()
        finally: self.directory.cleanup()


class MaskedStartupFixture(StartupFixture):
    """실제 visible CreateWindow 자동 활성화와 preexisting Progman/WSL을 재현한다."""
    def __init__(self, value, *, baseline=False, change=None, expires=1):
        super().__init__(value, expires=expires, change=change)
        self.fore = 20 if baseline else 12; self.baseline = baseline; self.styles = []; self.all_signature_timeouts = []
        self.explorer_file = Path(self.directory.name) / 'synthetic-explorer.exe'
        self.explorer_file.write_bytes(self.file.read_bytes())
        self.explorer = {**copy.deepcopy(self.process), 'processId': 300,
                         'imagePath': 'C:\\Windows\\explorer.exe', 'createdFileTime': 200000}
        self.desktop = {**copy.deepcopy(self.window), 'hwnd': 20, 'processId': 300, 'threadId': 301,
                        'title': 'Program Manager', 'className': 'Progman'}
        self.kernel.OpenProcess = ApiCall(lambda *a: self.opened.append(a) or (22 if a[2] == 300 else 11))
    def create(self, *args):
        self.probe_exists = True; self.styles.append(args[3])
        if args[3] & 0x10000000: self.fore = 500
        return 500
    def windows(self):
        rows = [copy.deepcopy(self.window)]
        if self.baseline: rows.append(copy.deepcopy(self.desktop))
        if self.change == 'multiple': rows.append({**copy.deepcopy(self.window), 'hwnd': 13})
        if self.change == 'hidden': rows[0]['visible'] = False
        if self.change == 'disabled': rows[0]['enabled'] = False
        return {'foregroundHwnd': self.foreground(), 'windows': rows, 'truncated': self.change == 'truncated'}
    def exists(self, hwnd):
        if hwnd == 20: return self.change != 'baselineGone' or self.clock == 0
        return super().exists(hwnd)
    def owner(self, hwnd, pid):
        if hwnd == 20:
            pid._obj.value = 999 if self.change == 'baselinePid' and self.clock else 300
            return 999 if self.change == 'baselineThread' and self.clock else 301
        return super().owner(hwnd, pid)
    def title(self, hwnd, buffer, count):
        if hwnd == 20:
            buffer.value = 'Other desktop' if self.change == 'baselineTitle' and self.clock else self.desktop['title']
            return len(buffer.value)
        return super().title(hwnd, buffer, count)
    def class_name(self, hwnd, buffer, count):
        if hwnd == 20:
            buffer.value = 'OtherClass' if self.change == 'baselineClass' and self.clock else self.desktop['className']
            return len(buffer.value)
        return super().class_name(hwnd, buffer, count)
    def times(self, handle, created, *rest):
        if handle == 22:
            changed = self.change == 'baselineCreation' and self.clock or self.change == 'baselineRetirementCreation' and self.clock >= self.expires
            created._obj.dwLowDateTime = 199999 if changed else 200000
            return 1
        return super().times(handle, created, *rest)
    def native(self, handle, process, native):
        if handle == 22:
            native._obj.value = 0x8664 if self.change == 'baselineNative' and self.clock else 0xAA64
            return 1
        return super().native(handle, process, native)
    def session(self, pid, session):
        if pid == 300:
            session._obj.value = 2 if self.change == 'baselineSession' and self.clock else 1
            return 1
        return super().session(pid, session)
    def exit_code(self, handle, code):
        if handle == 22: code._obj.value = 259; return 1
        return super().exit_code(handle, code)
    def processes(self, pids, *, deadline=None):
        if pids == [300]:
            result = copy.deepcopy(self.explorer)
            if self.change == 'baselineInitialSignature': result['signature']['status'] = 'NotSigned'
            if self.change == 'baselineWrongPath': result['imagePath'] = 'C:\\Other\\explorer.exe'
            if self.change == 'baselineInitialNative': result['nativeMachine'] = 0x8664
            if self.change == 'baselineInitialSession': result['sessionId'] = 2
            return [result]
        return super().processes(pids, deadline=deadline)
    def sleep(self, duration):
        super().sleep(duration)
        if self.change == 'baselineHash':
            data = bytearray(self.explorer_file.read_bytes()); data[-1] = 1; self.explorer_file.write_bytes(data)
    def signature(self, args, **kwargs):
        self.all_signature_timeouts.append(kwargs['timeout'])
        if self.explorer_file.name in kwargs['input'].decode():
            result = copy.deepcopy(self.explorer['signature']); result.pop('publisherMicrosoft')
            if self.change == 'baselinePostSignature' and self.clock: result['status'] = 'NotSigned'
            return SimpleNamespace(returncode=0, stdout=json.dumps(result).encode())
        return super().signature(args, **kwargs)
    def file_for_path(self, path):
        if str(path) == self.explorer['imagePath']: return self.explorer_file
        return super().file_for_path(path)


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

    def test_visible_create_cannot_mask_preexisting_wsl_before_read_only_wait(self):
        fixture = MaskedStartupFixture(module())
        result = fixture.run()
        self.assertIn('startupWait', result)
        self.assertTrue(result['startupWait']['naturalProcessExitObserved'])
        self.assertFalse(fixture.styles[0] & 0x10000000)
        self.assertEqual(fixture.shows, [(500, 4, 1)])
        self.assertEqual(fixture.calls, [('SetForegroundWindow', 500, 1)])
        self.assertTrue(result['foregroundMatched']); self.assertTrue(result['ownedWindowRemoved'])

    def test_visible_wsl_not_foreground_waits_with_only_bound_progman_baseline(self):
        fixture = MaskedStartupFixture(module(), baseline=True)
        result = fixture.run()
        self.assertIn('startupWait', result)
        self.assertTrue(result['startupWait']['naturalProcessExitObserved'])
        self.assertEqual(result['startupWait']['boundBaselineWindow']['hwnd'], 20)
        self.assertEqual(fixture.shows, [(500, 4, 1)])
        self.assertEqual(fixture.calls, [('SetForegroundWindow', 500, 1)])
        self.assertCountEqual(fixture.closed, [11, 22])

    def test_visible_wsl_selection_is_complete_unique_and_foreground_fail_closed(self):
        for change in ('multiple', 'truncated', 'foreignForeground', 'foreignRetirement'):
            fixture = MaskedStartupFixture(module(), baseline=True, change=change)
            with self.subTest(change=change):
                with self.assertRaises(ValueError): fixture.run()
                self.assertEqual(fixture.calls, []); self.assertEqual(fixture.shows, [])
                self.assertFalse(fixture.probe_exists)

    def test_hidden_disabled_lookalikes_do_not_displace_the_single_visible_wsl(self):
        for field in ('visible', 'enabled'):
            fixture = MaskedStartupFixture(module())
            original = fixture.probe.windows
            def windows():
                observed = original()
                observed['windows'].append({**copy.deepcopy(fixture.window), 'hwnd': 99,
                    'processId': 999, 'threadId': 998, field: False})
                return observed
            fixture.probe.windows = windows
            with self.subTest(field=field):
                result = fixture.run()
                self.assertEqual(result['startupWait']['boundWindow']['hwnd'], 12)
                self.assertEqual(fixture.opened, [(0x1000, False, 200)])
                self.assertEqual(fixture.shows, [(500, 4, 1)])

    def test_unbound_initial_foreground_does_not_show_or_activate_owned_probe(self):
        fixture = MaskedStartupFixture(module()); fixture.fore = 777
        with self.assertRaises(ValueError): fixture.run()
        self.assertEqual(fixture.shows, []); self.assertEqual(fixture.calls, [])
        self.assertFalse(fixture.probe_exists)

    def test_progman_images_share_the_original_65_second_deadline(self):
        fixture = MaskedStartupFixture(module(), baseline=True, expires=64.75)
        result = fixture.run()
        self.assertTrue(result['startupWait']['naturalProcessExitObserved'])
        self.assertEqual(fixture.all_signature_timeouts, [20, 20, 0.25, 0.25])
        self.assertEqual(fixture.shows, [(500, 4, 64.75)])
        self.assertEqual(fixture.calls, [('SetForegroundWindow', 500, 64.75)])

    def test_progman_signature_cannot_extend_deadline_before_show_or_activation(self):
        for phase in ('live', 'retired'):
            fixture = MaskedStartupFixture(module(), baseline=True)
            original = fixture.signature
            def signature(args, **kwargs):
                response = original(args, **kwargs)
                if fixture.explorer_file.name in kwargs['input'].decode() and ((phase == 'live') == (fixture.clock == 0)):
                    fixture.clock = 65.01
                return response
            fixture.signature = signature
            with self.subTest(phase=phase):
                with self.assertRaises(ValueError): fixture.run()
                self.assertEqual(fixture.shows, []); self.assertEqual(fixture.calls, [])
                self.assertCountEqual(fixture.closed, [11, 22]); self.assertFalse(fixture.probe_exists)

    def test_actual_process_metadata_signature_obeys_startup_remaining_budget(self):
        fixture = StartupFixture(module()); fixture.clock = 64.75
        def image(handle, flags, buffer, size): buffer.value = fixture.process['imagePath']; return 1
        fixture.kernel.QueryFullProcessImageNameW = ApiCall(image)
        try:
            with patch.object(fixture.value, 'Path', fixture.file_for_path), \
                 patch.object(fixture.value.time, 'monotonic', lambda: fixture.clock), \
                 patch.object(fixture.value.subprocess, 'run', fixture.signature):
                try: rows = fixture.value.WindowsProbe.processes(fixture.probe, [200], deadline=65)
                except TypeError: self.fail('실제 process metadata 조회도 시작 deadline을 받아야 합니다')
            self.assertEqual(fixture.signature_timeouts, [0.25])
            self.assertEqual(rows[0]['signature']['status'], 'Valid')
            self.assertEqual(fixture.closed, [11])
        finally: fixture.directory.cleanup()

    def test_expired_or_overrun_actual_process_metadata_never_proves_signature(self):
        for expired in (True, False):
            fixture = StartupFixture(module()); fixture.clock = 65 if expired else 64.75
            def image(handle, flags, buffer, size): buffer.value = fixture.process['imagePath']; return 1
            fixture.kernel.QueryFullProcessImageNameW = ApiCall(image)
            original = fixture.signature
            def signature(args, **kwargs):
                response = original(args, **kwargs); fixture.clock = 65.01; return response
            try:
                with self.subTest(expired=expired), patch.object(fixture.value, 'Path', fixture.file_for_path), \
                     patch.object(fixture.value.time, 'monotonic', lambda: fixture.clock), \
                     patch.object(fixture.value.subprocess, 'run', signature):
                    try:
                        with self.assertRaises(ValueError): fixture.value.WindowsProbe.processes(fixture.probe, [200], deadline=65)
                    except TypeError: self.fail('실제 process metadata deadline 검증이 필요합니다')
                    self.assertEqual(fixture.signature_timeouts, [] if expired else [0.25])
                    self.assertEqual(fixture.shows, []); self.assertEqual(fixture.calls, [])
            finally: fixture.directory.cleanup()

    def test_progman_binding_rejects_identity_signature_and_generation_changes(self):
        for change in ('baselineInitialSignature', 'baselineWrongPath', 'baselinePid', 'baselineThread',
                       'baselineClass', 'baselineTitle', 'baselineCreation', 'baselineNative',
                       'baselineSession', 'baselineGone', 'baselinePostSignature', 'baselineInitialNative',
                       'baselineInitialSession', 'baselineHash', 'baselineRetirementCreation'):
            fixture = MaskedStartupFixture(module(), baseline=True, change=change)
            with self.subTest(change=change):
                with self.assertRaises(ValueError): fixture.run()
                self.assertEqual(fixture.calls, []); self.assertEqual(fixture.shows, [])
                self.assertFalse(fixture.probe_exists)

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




class StartupSelectionDiagnosticTests(unittest.TestCase):
    # Exact retained Source115 native ARM AFTER snapshot, not the unretained
    # interior snapshot. Replaying a guard against it cannot prove that cause.
    ORIGINAL_AFTER_SNAPSHOT = json.loads('{"foregroundHwnd":393304,"windows":[{"hwnd":393304,"processId":7624,"threadId":7628,"title":"Program Manager","className":"Progman","visible":true,"enabled":true,"rectangle":[0,0,1024,768]},{"hwnd":65966,"processId":7624,"threadId":8768,"title":"","className":"ForegroundStaging","visible":false,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":131438,"processId":7624,"threadId":8420,"title":"","className":"ForegroundStaging","visible":false,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":131840,"processId":7624,"threadId":10896,"title":"Battery Meter","className":"SystemTray_Main","visible":false,"enabled":true,"rectangle":[0,0,14,14]},{"hwnd":131814,"processId":7624,"threadId":7876,"title":"","className":"ATL:00007FFE802580E0","visible":false,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":131362,"processId":7624,"threadId":3412,"title":"","className":"tooltips_class32","visible":false,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":65854,"processId":7624,"threadId":3412,"title":"","className":"Shell_TrayWnd","visible":true,"enabled":true,"rectangle":[0,720,1024,768]},{"hwnd":197274,"processId":10160,"threadId":8384,"title":"","className":"WindowsDashboard","visible":false,"enabled":true,"rectangle":[0,0,1024,720]},{"hwnd":131388,"processId":7624,"threadId":7628,"title":"","className":"tooltips_class32","visible":false,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":197490,"processId":5788,"threadId":1700,"title":"","className":"RunDLL","visible":false,"enabled":true,"rectangle":[26,26,42,42]},{"hwnd":590370,"processId":9376,"threadId":4348,"title":"","className":"WorkerW","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":262778,"processId":7624,"threadId":7876,"title":"BluetoothNotificationAreaIconWindowClass","className":"BluetoothNotificationAreaIconWindowClass","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":131828,"processId":7624,"threadId":3412,"title":"MiracastConnectionWindow","className":"MiracastConnectionWindow","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":262566,"processId":7624,"threadId":3176,"title":"MS_WebcheckMonitor","className":"MS_WebcheckMonitor","visible":false,"enabled":true,"rectangle":[130,130,898,649]},{"hwnd":131820,"processId":7624,"threadId":3176,"title":"","className":"WorkerW","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":197382,"processId":7624,"threadId":10896,"title":"","className":"WorkerW","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":327984,"processId":10160,"threadId":8384,"title":"","className":"MessageWindowClass","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":131260,"processId":5040,"threadId":3748,"title":"","className":"Chrome_WidgetWin_0","visible":false,"enabled":false,"rectangle":[0,0,0,0]},{"hwnd":393888,"processId":4360,"threadId":7028,"title":"","className":"Chrome_WidgetWin_0","visible":false,"enabled":false,"rectangle":[0,0,0,0]},{"hwnd":131754,"processId":5040,"threadId":3748,"title":"","className":"Chrome_WidgetWin_0","visible":false,"enabled":true,"rectangle":[104,104,872,623]},{"hwnd":131750,"processId":5040,"threadId":3748,"title":"","className":"Base_PowerMessageWindow","visible":false,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":131730,"processId":7712,"threadId":1068,"title":"","className":"crashpad_SessionEndWatcher","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":197254,"processId":10160,"threadId":8384,"title":"","className":"MessageWindowClass","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":197086,"processId":5028,"threadId":6312,"title":"Task Host Window","className":"COMTASKSWINDOWCLASS","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":197308,"processId":10760,"threadId":1720,"title":"C:\\\\ProgramData\\\\GitHub\\\\HostedComputeAgent\\\\hosted-compute-agent","className":"ConsoleWindowClass","visible":true,"enabled":true,"rectangle":[31,156,1024,675]},{"hwnd":65872,"processId":7624,"threadId":7628,"title":"","className":"WorkerW","visible":false,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":65768,"processId":7700,"threadId":7704,"title":"System Properties","className":"#32770","visible":true,"enabled":true,"rectangle":[311,319,731,511]},{"hwnd":65728,"processId":7700,"threadId":7704,"title":"Performance Options","className":"#32770","visible":false,"enabled":false,"rectangle":[52,52,485,578]},{"hwnd":65888,"processId":7624,"threadId":8420,"title":"","className":"ApplicationManager_DesktopShellWindow","visible":false,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":65880,"processId":7624,"threadId":8420,"title":"","className":"WorkerW","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":131378,"processId":7624,"threadId":3412,"title":"","className":"WorkerW","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":65704,"processId":7700,"threadId":7704,"title":"","className":"StubWindow32","visible":false,"enabled":false,"rectangle":[52,52,188,91]},{"hwnd":65810,"processId":7624,"threadId":2180,"title":"","className":"WorkerW","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":65808,"processId":7624,"threadId":7628,"title":"","className":"WorkerW","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":131150,"processId":7828,"threadId":4604,"title":"CrossDeviceResumeWindow","className":"CrossDeviceResumeWindowClass","visible":false,"enabled":true,"rectangle":[104,104,872,662]},{"hwnd":65804,"processId":7276,"threadId":7524,"title":"Task Host Window","className":"COMTASKSWINDOWCLASS","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":65782,"processId":7676,"threadId":7696,"title":"DesktopWindowXamlSource","className":"Windows.UI.Core.CoreWindow","visible":false,"enabled":true,"rectangle":[0,0,1,1]},{"hwnd":65716,"processId":7624,"threadId":7628,"title":"","className":"DDEMLEvent","visible":false,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":65712,"processId":7624,"threadId":7628,"title":"","className":"DDEMLMom","visible":false,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":131100,"processId":7244,"threadId":7428,"title":"Windows Push Notifications Platform","className":"PushNotificationsPowerManagement","visible":false,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":65592,"processId":5428,"threadId":4480,"title":"DWM Notification Window","className":"Dwm","visible":false,"enabled":true,"rectangle":[0,740,160,768]},{"hwnd":131182,"processId":5840,"threadId":5616,"title":"","className":"CicLoaderWndClass","visible":false,"enabled":false,"rectangle":[0,0,136,39]},{"hwnd":66172,"processId":1480,"threadId":9296,"title":"","className":"WorkerW","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":65930,"processId":7624,"threadId":8420,"title":"","className":"Postures Broadcast Listener Class","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":65954,"processId":7624,"threadId":8420,"title":"","className":"TabletModeCoverWindow","visible":false,"enabled":true,"rectangle":[0,0,1024,720]},{"hwnd":66062,"processId":7624,"threadId":8420,"title":"","className":"WorkerW","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":66064,"processId":7624,"threadId":8420,"title":"","className":"WorkerW","visible":false,"enabled":true,"rectangle":[0,0,136,39]},{"hwnd":65956,"processId":7624,"threadId":8420,"title":"","className":"DummyDWMListenerWindow","visible":true,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":65948,"processId":7624,"threadId":8420,"title":"","className":"EdgeUiInputTopWndClass","visible":true,"enabled":true,"rectangle":[15,0,1024,4]},{"hwnd":65912,"processId":7624,"threadId":8420,"title":"","className":"DummyDWMListenerWindow","visible":true,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":65910,"processId":7624,"threadId":8420,"title":"","className":"DummyDWMListenerWindow","visible":true,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":65908,"processId":7624,"threadId":8420,"title":"","className":"DummyDWMListenerWindow","visible":true,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":65906,"processId":7624,"threadId":8420,"title":"","className":"DummyDWMListenerWindow","visible":true,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":65904,"processId":7624,"threadId":8420,"title":"","className":"GamingFallbackWindow","visible":false,"enabled":true,"rectangle":[0,0,0,0]},{"hwnd":131764,"processId":5040,"threadId":3748,"title":"Widgets","className":"Chrome_WidgetWin_1","visible":false,"enabled":true,"rectangle":[0,720,0,720]},{"hwnd":65968,"processId":7624,"threadId":8768,"title":"Default IME","className":"IME","visible":false,"enabled":false,"rectangle":[0,0,0,0]},{"hwnd":131812,"processId":7624,"threadId":7876,"title":"Default IME","className":"IME","visible":false,"enabled":false,"rectangle":[0,0,0,0]},{"hwnd":131374,"processId":7624,"threadId":3412,"title":"MSCTFIME UI","className":"MSCTFIME UI","visible":false,"enabled":false,"rectangle":[0,0,0,0]},{"hwnd":65856,"processId":7624,"threadId":3412,"title":"Default IME","className":"IME","visible":false,"enabled":false,"rectangle":[0,0,0,0]},{"hwnd":262192,"processId":5788,"threadId":1700,"title":"Default IME","className":"IME","visible":false,"enabled":false,"rectangle":[0,0,0,0]},{"hwnd":131624,"processId":9376,"threadId":4348,"title":"Default IME","className":"IME","visible":false,"enabled":false,"rectangle":[0,0,0,0]},{"hwnd":131810,"processId":7624,"threadId":3176,"title":"Default IME","className":"IME","visible":false,"enabled":false,"rectangle":[0,0,0,0]},{"hwnd":197078,"processId":7624,"threadId":10896,"title":"Default IME","className":"IME","visible":false,"enabled":false,"rectangle":[0,0,0,0]},{"hwnd":131724,"processId":4360,"threadId":7028,"title":"Default IME","className":"IME","visible":false,"enabled":false,"rectangle":[0,0,0,0]}],"truncated":true}')

    def test_actual_startup_guard_retains_observed_truncated_selection_before_failure(self):
        value = module(); probe = value.WindowsProbe.__new__(value.WindowsProbe)
        snapshot = copy.deepcopy(self.ORIGINAL_AFTER_SNAPSHOT)
        calls = []
        probe.windows = lambda: calls.append('windows') or snapshot
        probe.windows_directory = lambda: calls.append('directory') or 'C:\\Windows'
        probe.startup_bound_process = lambda *args, **kwargs: calls.append('binding')
        result = {}
        with self.assertRaisesRegex(ValueError, '전체 관찰이 잘렸습니다'):
            probe.wait_startup_foreground(721776, result)
        self.assertEqual(calls, ['windows'])
        self.assertEqual(result.get('startupSelection'), {
            'readOnly': True, 'stage': 'completeWindowObservation',
            'windowCount': 64, 'truncated': True, 'foregroundHwnd': 393304})
        self.assertNotIn('startupWait', result)
        self.assertNotIn('setForegroundReturned', result)
        self.assertNotIn('naturalProcessExitObserved', result)

    def test_actual_startup_binding_failure_retains_phase_without_permission(self):
        value = module(); probe = value.WindowsProbe.__new__(value.WindowsProbe)
        calls = []
        snapshot = {'foregroundHwnd': 12, 'truncated': False, 'windows': [{
            'hwnd': 12, 'processId': 200, 'threadId': 201,
            'title': 'C:\\Windows\\System32\\wsl.exe', 'className': 'ConsoleWindowClass',
            'visible': True, 'enabled': True, 'rectangle': [31, 104, 1024, 623]}]}
        probe.windows = lambda: calls.append('windows') or snapshot
        probe.windows_directory = lambda: calls.append('directory') or 'C:\\Windows'
        def fail_binding(*args, **kwargs):
            calls.append('binding'); raise ValueError('selected process binding rejected')
        probe.startup_bound_process = fail_binding
        result = {}
        with self.assertRaisesRegex(ValueError, 'selected process binding rejected'):
            probe.wait_startup_foreground(500, result)
        self.assertEqual(calls, ['windows', 'directory', 'binding'])
        self.assertEqual(result.get('startupSelection'), {
            'readOnly': True, 'stage': 'candidateBinding',
            'windowCount': 1, 'truncated': False, 'foregroundHwnd': 12})
        self.assertNotIn('startupWait', result)
        self.assertNotIn('setForegroundReturned', result)
        self.assertNotIn('naturalProcessExitObserved', result)


class ScopedStartupEnumerationTests(unittest.TestCase):
    def stream(self, *, changes=(), foreground=9000, candidates=(9001,), hidden=100, candidate_title='C:\\Windows\\System32\\wsl.exe'):
        value = module(); probe = value.WindowsProbe.__new__(value.WindowsProbe)
        clock = [0.0]; errors = [0]; visits = []
        rows = {hwnd: {'hwnd': hwnd, 'processId': hwnd+100, 'threadId': hwnd+200,
                       'title': '', 'className': 'IME', 'visible': False, 'enabled': False,
                       'rectangle': [0, 0, 0, 0]} for hwnd in range(1, hidden+1)}
        rows[9000] = {'hwnd': 9000, 'processId': 300, 'threadId': 301,
                      'title': 'Program Manager', 'className': 'Progman',
                      'visible': True, 'enabled': True, 'rectangle': [0, 0, 1024, 768]}
        for hwnd in candidates:
            rows[hwnd] = {'hwnd': hwnd, 'processId': 200, 'threadId': 201,
                          'title': candidate_title, 'className': 'ConsoleWindowClass',
                          'visible': True, 'enabled': True, 'rectangle': [31, 104, 1024, 623]}
        class User:
            def GetForegroundWindow(self):
                return 9999 if 'foregroundHwnd' in changes and visits else foreground
            def EnumWindows(self, callback, _):
                for hwnd in [*range(1, hidden+1), *candidates]:
                    visits.append(hwnd)
                    if 'expired' in changes: clock[0] = 66
                    if not callback(hwnd, 0): return 0
                return 0 if 'nativeFailure' in changes else 1
            def IsWindow(self, hwnd): return hwnd in rows and not ('missing' in changes and hwnd in candidates)
            def IsWindowVisible(self, hwnd): return rows[hwnd]['visible']
            def IsWindowEnabled(self, hwnd): return rows[hwnd]['enabled']
            def GetWindowThreadProcessId(self, hwnd, pid):
                if 'ownerRace' in changes and visits and hwnd == foreground: pid._obj.value = 999; return 998
                pid._obj.value = rows[hwnd]['processId']; return rows[hwnd]['threadId']
            def GetWindowTextLengthW(self, hwnd): return len(rows[hwnd]['title'].encode('utf-16-le'))//2
            def GetWindowTextW(self, hwnd, buffer, _):
                if 'titleError' in changes and hwnd in candidates: errors[0] = 5; return 0
                buffer.value = rows[hwnd]['title']; return len(buffer.value.encode('utf-16-le'))//2
            def GetClassNameW(self, hwnd, buffer, _):
                if 'callbackError' in changes and hwnd in candidates: raise OSError('controlled callback read failure')
                buffer.value = rows[hwnd]['className']; return len(buffer.value)
            def GetWindowRect(self, hwnd, rect):
                if 'rectangleError' in changes and hwnd in candidates: return 0
                rect._obj.left, rect._obj.top, rect._obj.right, rect._obj.bottom = rows[hwnd]['rectangle']; return 1
        probe.user = User(); probe.callback = lambda callback: callback
        if 'hiddenRace' in changes:
            original = probe.user.IsWindowVisible; count = [0]
            def hidden_race(hwnd):
                result = original(hwnd)
                if hwnd == 1:
                    count[0] += 1
                    if count[0] == 1: rows[hwnd]['visible'] = True; rows[hwnd]['enabled'] = True
                return result
            probe.user.IsWindowVisible = hidden_race
        if 'classRace' in changes:
            rows[1].update(visible=True, enabled=True, className='OtherClass')
            original = probe.user.GetClassNameW; count = [0]
            def class_race(hwnd, buffer, size):
                result = original(hwnd, buffer, size)
                if hwnd == 1:
                    count[0] += 1
                    if count[0] == 1: rows[hwnd]['className'] = 'ConsoleWindowClass'; rows[hwnd]['title'] = candidate_title
                return result
            probe.user.GetClassNameW = class_race
        if 'eligibleOwnerRace' in changes:
            original = probe.user.GetWindowThreadProcessId; count = [0]
            def eligible_owner_race(hwnd, pid):
                result = original(hwnd, pid)
                if hwnd in candidates:
                    count[0] += 1
                    if count[0] == 1: rows[hwnd]['processId'] = 999; rows[hwnd]['threadId'] = 998
                return result
            probe.user.GetWindowThreadProcessId = eligible_owner_race
        return value, probe, clock, errors, visits

    def collect(self, fixture, expected_path='C:\\Windows\\System32\\wsl.exe'):
        value, probe, clock, errors, visits = fixture
        collector = getattr(probe, 'startup_candidates', None)
        self.assertTrue(callable(collector), 'Separate complete bounded startup-predicate collector is missing')
        observed = {}
        with patch.object(value.time, 'monotonic', lambda: clock[0]), \
             patch.object(value.ctypes, 'set_last_error', lambda number: errors.__setitem__(0, number), create=True), \
             patch.object(value.ctypes, 'get_last_error', lambda: errors[0], create=True):
            collector(expected_path, deadline=65, observation=observed)
        return observed

    def test_actual_stream_observes_late_wsl_after_more_than64_hidden_windows(self):
        fixture = self.stream(); observed = self.collect(fixture)
        self.assertTrue(observed['enumerationComplete'])
        self.assertEqual(observed['scope'], 'visible-enabled-exact-wsl-startup-candidates')
        self.assertGreater(observed['visits'], 64)
        self.assertEqual([row['hwnd'] for row in observed['candidates']], [9001])
        self.assertEqual(observed['foreground']['hwnd'], 9000)
        self.assertEqual(fixture[0].MAX_WINDOWS, 64)

    def test_actual_startup_selects_late_candidate_without_changing_general_truncation(self):
        value, probe, clock, errors, visits = self.stream()
        selected = []; probe.windows_directory = lambda: 'C:\\Windows'
        def binding(window, path, *, deadline):
            selected.append(window['hwnd']); raise ValueError('controlled stop after actual candidate selection')
        probe.startup_bound_process = binding
        with patch.object(value.time, 'monotonic', lambda: clock[0]), \
             patch.object(value.ctypes, 'set_last_error', lambda number: errors.__setitem__(0, number), create=True), \
             patch.object(value.ctypes, 'get_last_error', lambda: errors[0], create=True):
            diagnostic = probe.windows()
            self.assertTrue(diagnostic['truncated']); self.assertEqual(len(diagnostic['windows']), 64)
            self.assertNotIn(9001, [row['hwnd'] for row in diagnostic['windows']])
            try: probe.wait_startup_foreground(500, {})
            except ValueError: pass
        self.assertEqual(selected, [9001])

    def test_actual_stream_rejects_multiple_late_candidates(self):
        fixture = self.stream(candidates=(9001, 9002))
        with self.assertRaises(ValueError): self.collect(fixture)

    def test_actual_stream_rejects_native_callback_and_eligible_row_failures(self):
        for change in ('nativeFailure', 'callbackError', 'titleError', 'rectangleError', 'missing'):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.collect(self.stream(changes=(change,)))

    def test_actual_stream_rejects_cap_and_original_deadline_expiry(self):
        fixture = self.stream(hidden=4097)
        with self.assertRaises(ValueError): self.collect(fixture)
        self.assertLessEqual(len(fixture[4]), 4097)
        with self.assertRaises(ValueError): self.collect(self.stream(changes=('expired',)))

    def test_actual_stream_rejects_foreground_handle_and_owner_races(self):
        for change in ('foregroundHwnd', 'ownerRace'):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.collect(self.stream(changes=(change,)))

    def test_no_candidate_unknown_foreground_never_activates_owned_probe(self):
        fixture = MaskedStartupFixture(module()); fixture.fore = 777
        fixture.probe.windows = lambda: {'foregroundHwnd': 777, 'windows': [], 'truncated': False}
        with self.assertRaises(ValueError): fixture.run()
        self.assertEqual(fixture.shows, []); self.assertEqual(fixture.calls, [])
        self.assertFalse(fixture.probe_exists)

    def test_native_false_sub64_inventory_never_reaches_binding(self):
        for candidates in ((), (9001,)):
            value, probe, clock, errors, visits = self.stream(hidden=3, candidates=candidates, changes=('nativeFailure',))
            selected = []; probe.windows_directory = lambda: 'C:\\Windows'
            probe.startup_bound_process = lambda *args, **kwargs: selected.append(True)
            with patch.object(value.time, 'monotonic', lambda: clock[0]), \
                 patch.object(value.ctypes, 'set_last_error', lambda number: errors.__setitem__(0, number), create=True), \
                 patch.object(value.ctypes, 'get_last_error', lambda: errors[0], create=True):
                try: probe.wait_startup_foreground(500, {})
                except (ValueError, AttributeError): pass
            with self.subTest(candidates=candidates): self.assertEqual(selected, [])

    def test_zero_candidate_foreground_native_overrun_rejects(self):
        value, probe, clock, errors, visits = self.stream(foreground=0, candidates=())
        def slow_foreground(): clock[0] = 66; return 0
        probe.user.GetForegroundWindow = slow_foreground
        with patch.object(value.time, 'monotonic', lambda: clock[0]), self.assertRaises(ValueError):
            probe.startup_no_candidate_foreground({'foregroundHwnd':0, 'windows':[]}, 500, deadline=65, selection={})

    def test_native_utf16_title_units_support_nonbmp_windows_path(self):
        expected = 'C:\\Windows-😀\\System32\\wsl.exe'
        try: observed = self.collect(self.stream(candidate_title=expected), expected_path=expected)
        except ValueError: observed = None
        self.assertIsNotNone(observed, 'Valid native UTF16 title was rejected')
        self.assertTrue(observed['enumerationComplete'])
        self.assertEqual(observed['candidates'][0]['title'], expected)

    def test_omitted_hidden_and_nonconsole_native_races_reject(self):
        for change in ('hiddenRace', 'classRace'):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.collect(self.stream(changes=(change,)))

    def test_zero_candidate_verified_progman_and_identity_rejections(self):
        for change in (None, 'baselineInitialSignature', 'baselineInitialNative', 'baselineInitialSession', 'baselineWrongPath'):
            fixture = MaskedStartupFixture(module(), baseline=True, change=change, expires=0)
            fixture.probe.windows = lambda: {'foregroundHwnd':20, 'windows':[copy.deepcopy(fixture.desktop)], 'truncated':False}
            with self.subTest(change=change):
                if change is None:
                    result = fixture.run()
                    self.assertTrue(result['foregroundMatched']); self.assertEqual(len(fixture.calls), 1)
                    self.assertIn('noCandidateBaseline', result['startupSelection'])
                    self.assertEqual(fixture.closed, [22])
                else:
                    with self.assertRaises(ValueError): fixture.run()
                    self.assertEqual(fixture.shows, []); self.assertEqual(fixture.calls, [])

    def test_zero_candidate_final_progman_foreground_overrun_rejects_and_closes_handle(self):
        fixture = MaskedStartupFixture(module(), baseline=True)
        fixture.probe.windows = lambda: {'foregroundHwnd':20, 'windows':[copy.deepcopy(fixture.desktop)], 'truncated':False}
        original = fixture.signature
        def signature(args, **kwargs):
            result = original(args, **kwargs)
            def slow_foreground(): fixture.clock = 66; return 20
            fixture.user.GetForegroundWindow = ApiCall(slow_foreground)
            return result
        fixture.signature = signature
        with self.assertRaises(ValueError): fixture.run()
        self.assertEqual(fixture.shows, []); self.assertEqual(fixture.calls, [])
        self.assertEqual(fixture.closed, [22])

    def test_foreign_foreground_after_nocandidate_verification_never_activates(self):
        fixture = MaskedStartupFixture(module(), baseline=True, expires=0)
        fixture.probe.windows = lambda: {'foregroundHwnd':20, 'windows':[copy.deepcopy(fixture.desktop)], 'truncated':False}
        original = fixture.user.GetWindowThreadProcessId; owned_reads = [0]
        def owner(hwnd, pid):
            result = original(hwnd, pid)
            if hwnd == 500:
                owned_reads[0] += 1
                if owned_reads[0] == 2: fixture.fore = 777
            return result
        fixture.user.GetWindowThreadProcessId = ApiCall(owner)
        with self.assertRaises(ValueError): fixture.run()
        self.assertEqual(fixture.shows, []); self.assertEqual(fixture.calls, [])
        self.assertEqual(fixture.closed, [22])

    def test_baseline_creation_after_nocandidate_verification_never_activates(self):
        fixture = MaskedStartupFixture(module(), baseline=True, expires=0, change='baselineCreation')
        fixture.probe.windows = lambda: {'foregroundHwnd':20, 'windows':[copy.deepcopy(fixture.desktop)], 'truncated':False}
        original = fixture.user.GetWindowThreadProcessId; owned_reads = [0]
        def owner(hwnd, pid):
            result = original(hwnd, pid)
            if hwnd == 500:
                owned_reads[0] += 1
                if owned_reads[0] == 2: fixture.clock = .25
            return result
        fixture.user.GetWindowThreadProcessId = ApiCall(owner)
        with self.assertRaises(ValueError): fixture.run()
        self.assertEqual(fixture.shows, []); self.assertEqual(fixture.calls, [])
        self.assertEqual(fixture.closed, [22])

    def test_post_show_foreground_and_deadline_changes_never_call_setter(self):
        for change in ('foreground', 'showDeadline', 'foregroundReadDeadline'):
            fixture = MaskedStartupFixture(module(), baseline=True, expires=0)
            fixture.probe.windows = lambda: {'foregroundHwnd':20, 'windows':[copy.deepcopy(fixture.desktop)], 'truncated':False}
            original_show = fixture.show; original_foreground = fixture.foreground
            def show(hwnd, command):
                result = original_show(hwnd, command)
                if change == 'foreground': fixture.fore = 777
                if change == 'showDeadline': fixture.clock = 66
                return result
            def foreground():
                if change == 'foregroundReadDeadline' and fixture.shows: fixture.clock = 66
                return original_foreground()
            fixture.user.ShowWindow = ApiCall(show); fixture.user.GetForegroundWindow = ApiCall(foreground)
            with self.subTest(change=change):
                with self.assertRaises(ValueError): fixture.run()
                self.assertEqual(len(fixture.shows), 1); self.assertEqual(fixture.calls, [])
                self.assertEqual(fixture.closed, [22])

    def test_eligible_callback_owner_generation_change_rejects(self):
        with self.assertRaises(ValueError): self.collect(self.stream(changes=('eligibleOwnerRace',)))

    def test_one_setter_returning_after_startup_deadline_fails_and_cleans_up(self):
        fixture = MaskedStartupFixture(module(), baseline=True, expires=0)
        fixture.probe.windows = lambda: {'foregroundHwnd':20, 'windows':[copy.deepcopy(fixture.desktop)], 'truncated':False}
        original = fixture.set_foreground
        def slow_setter(hwnd):
            result = original(hwnd); fixture.clock = 66; return result
        fixture.user.SetForegroundWindow = ApiCall(slow_setter)
        with self.assertRaises(ValueError): fixture.run()
        self.assertEqual(len(fixture.shows), 1); self.assertEqual(len(fixture.calls), 1)
        self.assertFalse(fixture.probe_exists); self.assertEqual(fixture.closed, [22])


class InitialHeldDiagnosticTests(unittest.TestCase):
    APIS = ('GetProcessTimes', 'IsWow64Process2', 'GetExitCodeProcess', 'ProcessIdToSessionId')

    def test_actual_startup_retains_initial_tuple_without_observing_later_queries(self):
        fixture = StartupFixture(module(), expires=1)
        result = fixture.run()
        trace = result['startupWait']
        self.assertIn('initialHeldObservation', trace,
                      'The actual initial WSL held tuple must survive before the first wait sample')
        observed = trace['initialHeldObservation']
        self.assertEqual(observed['state'], {'createdFileTime': 100000, 'processMachine': 0,
                         'nativeMachine': 0xAA64, 'sessionId': 1, 'exitCode': 259})
        self.assertEqual(observed['apiCalls'], [
            {'api': name, 'succeeded': True, 'lastError': None} for name in self.APIS])
        self.assertEqual(observed['validation'], {'createdFileTime': True, 'processMachine': True,
                         'nativeMachine': True, 'sessionId': True, 'live': True})
        self.assertIsNone(observed['failureCode'])
        self.assertTrue(trace['naturalProcessExitObserved'])
        self.assertTrue(result['ownedWindowRemoved'])
        self.assertLess(len(json.dumps(observed).encode()), 4096)

    def test_each_failed_initial_api_stops_queries_and_retains_only_finite_error(self):
        for failed_index, failed_api in enumerate(self.APIS):
            with self.subTest(api=failed_api):
                fixture = StartupFixture(module()); calls = []
                for name in self.APIS:
                    original = getattr(fixture.kernel, name)
                    def call(*args, name=name, original=original):
                        calls.append(name)
                        if name == failed_api:
                            fixture.value.ctypes.set_last_error(87)
                            return False
                        return original(*args)
                    setattr(fixture.kernel, name, ApiCall(call))
                with self.assertRaises(ValueError): fixture.run()
                result = fixture.probe.last_focus_probe_result
                observed = result['startupWait'].get('initialHeldObservation')
                self.assertIsNotNone(observed, 'Initial API rejection must retain its finite observation')
                self.assertEqual(calls, list(self.APIS[:failed_index+1]))
                self.assertEqual(observed['apiCalls'], [
                    {'api': name, 'succeeded': index != failed_index,
                     'lastError': 87 if index == failed_index else None}
                    for index, name in enumerate(self.APIS[:failed_index+1])])
                self.assertEqual(observed['failureCode'], failed_api + '_failed')
                self.assertIsNone(observed['state']); self.assertEqual(observed['validation'], {})
                self.assertEqual(result['startupWait']['samples'], [])
                self.assertTrue(result['ownedWindowRemoved']); self.assertFalse(fixture.probe_exists)
                self.assertEqual(fixture.calls, []); self.assertEqual(fixture.shows, [])
                self.assertEqual(fixture.closed, [11])

    def test_successful_initial_api_query_does_not_read_stale_last_error(self):
        fixture = StartupFixture(module()); observed = {}
        try:
            with patch.object(fixture.value.ctypes, 'get_last_error',
                              side_effect=AssertionError('No successful API last-error read'), create=True):
                state = fixture.probe.startup_process_state(11, 200, observation=observed)
            self.assertEqual(observed['state'], state)
            self.assertEqual([row['api'] for row in observed['apiCalls']], list(self.APIS))
            self.assertTrue(all(row['succeeded'] and row['lastError'] is None for row in observed['apiCalls']))
        finally: fixture.directory.cleanup()

    def test_each_initial_api_exception_retains_attempt_without_reading_last_error(self):
        for failed_index, failed_api in enumerate(self.APIS):
            with self.subTest(api=failed_api):
                fixture = StartupFixture(module()); observed = {}; calls = []
                failure = ValueError('private native argument/path ' * 500)
                for name in self.APIS:
                    original = getattr(fixture.kernel, name)
                    def call(*args, name=name, original=original):
                        calls.append(name)
                        if name == failed_api: raise failure
                        return original(*args)
                    setattr(fixture.kernel, name, ApiCall(call))
                try:
                    with patch.object(fixture.value.ctypes, 'get_last_error',
                                      side_effect=AssertionError('No last-error query for exception'), create=True):
                        with self.assertRaises(ValueError) as raised:
                            fixture.probe.startup_process_state(11, 200, observation=observed)
                    self.assertIs(raised.exception, failure)
                    self.assertEqual(calls, list(self.APIS[:failed_index+1]))
                    self.assertEqual(observed['apiCalls'], [
                        {'api': name, 'succeeded': True, 'lastError': None}
                        for name in self.APIS[:failed_index]] + [
                        {'api': failed_api, 'succeeded': None, 'lastError': None, 'callException': True}])
                    self.assertEqual(observed['failureCode'], failed_api + '_exception')
                    self.assertIsNone(observed['state']); self.assertEqual(observed['validation'], {})
                    self.assertNotIn('private', json.dumps(observed))
                    self.assertLessEqual(len(observed['apiCalls']), 4)
                    self.assertLess(len(json.dumps(observed).encode()), 4096)
                finally: fixture.directory.cleanup()

    def test_unavailable_or_non_dword_last_error_is_null_without_raw_exception(self):
        for error in (None, -1, 2**32, True):
            with self.subTest(error=error):
                fixture = StartupFixture(module()); observed = {}
                fixture.kernel.GetProcessTimes = ApiCall(lambda *args: False)
                try:
                    with patch.object(fixture.value.ctypes, 'get_last_error', create=True,
                                      side_effect=OSError('private path/environment ' * 500) if error is None else None,
                                      return_value=error):
                        with self.assertRaises(ValueError):
                            fixture.probe.startup_process_state(11, 200, observation=observed)
                    self.assertEqual(observed['apiCalls'], [
                        {'api': 'GetProcessTimes', 'succeeded': False, 'lastError': None}])
                    self.assertIsNone(observed['state'])
                    self.assertNotIn('private', json.dumps(observed))
                    self.assertLess(len(json.dumps(observed).encode()), 4096)
                finally: fixture.directory.cleanup()

    def test_initial_identity_rejection_records_first_failed_predicate(self):
        changes = (
            ('createdFileTime', 'created_file_time_mismatch', 'GetProcessTimes',
             lambda handle, created, *rest: setattr(created._obj, 'dwLowDateTime', 99999) or 1),
            ('processMachine', 'process_machine_mismatch', 'IsWow64Process2',
             lambda handle, process, native: (setattr(process._obj, 'value', 0x8664),
                                               setattr(native._obj, 'value', 0xAA64), 1)[-1]),
            ('nativeMachine', 'native_machine_mismatch', 'IsWow64Process2',
             lambda handle, process, native: setattr(native._obj, 'value', 0x8664) or 1),
            ('sessionId', 'session_mismatch', 'ProcessIdToSessionId',
             lambda pid, session: setattr(session._obj, 'value', 2) or 1),
            ('live', 'process_not_live', 'GetExitCodeProcess',
             lambda handle, code: setattr(code._obj, 'value', 0) or 1))
        order = ('createdFileTime', 'processMachine', 'nativeMachine', 'sessionId', 'live')
        for field, failure, api, callback in changes:
            with self.subTest(field=field):
                fixture = StartupFixture(module()); setattr(fixture.kernel, api, ApiCall(callback))
                with self.assertRaises(ValueError): fixture.run()
                result = fixture.probe.last_focus_probe_result
                observed = result['startupWait'].get('initialHeldObservation')
                self.assertIsNotNone(observed, 'The rejecting initial predicate must retain its observed tuple')
                self.assertEqual(observed['failureCode'], failure)
                self.assertEqual(observed['validation'], {
                    key: key != field for key in order[:order.index(field)+1]})
                self.assertEqual(len(observed['apiCalls']), 4)
                self.assertEqual(result['firstFailure']['failureCode'], failure)
                self.assertIsNotNone(observed['state']); self.assertTrue(result['ownedWindowRemoved'])
                self.assertEqual(fixture.calls, []); self.assertEqual(fixture.shows, [])
                self.assertNotIn('foregroundAtActivation', result)
                self.assertEqual(result['startupWait']['samples'], [])

    def test_actual_focus_probe_preserves_first_failure_when_unregister_also_fails(self):
        fixture = StartupFixture(module())
        fixture.kernel.GetExitCodeProcess = ApiCall(lambda *args: False)
        fixture.user.UnregisterClassW = ApiCall(lambda *args: False)
        with self.assertRaisesRegex(ValueError, '소유 focus probe class 제거 실패'): fixture.run()
        result = fixture.probe.last_focus_probe_result
        self.assertIn('firstFailure', result, 'A cleanup exception must not erase the first failure receipt')
        self.assertEqual(result['firstFailure'], {'errorType': 'ValueError',
                         'failureCode': 'GetExitCodeProcess_failed'})
        self.assertEqual(result['cleanupFailure'], {'errorType': 'ValueError', 'stage': 'unregisterClass'})
        self.assertTrue(result['ownedWindowRemoved']); self.assertFalse(fixture.probe_exists)
        self.assertEqual(fixture.calls, []); self.assertEqual(fixture.shows, [])
        self.assertEqual(fixture.closed, [11])
        self.assertLess(len(json.dumps(result).encode()), fixture.value.MAX_JSON)

    def test_existing_controller_session_query_failure_has_finite_initial_reason(self):
        fixture = StartupFixture(module()); queried = [False]
        original = fixture.kernel.GetProcessTimes
        def times(*args):
            queried[0] = True
            return original(*args)
        def session_id():
            if queried[0]: raise ValueError('private controller query detail')
            return 1
        fixture.kernel.GetProcessTimes = ApiCall(times); fixture.probe.session_id = session_id
        with self.assertRaises(ValueError): fixture.run()
        result = fixture.probe.last_focus_probe_result
        observed = result['startupWait']['initialHeldObservation']
        self.assertEqual(observed['failureCode'], 'controller_session_query_failed')
        self.assertEqual(len(observed['apiCalls']), 4)
        self.assertEqual(observed['validation'], {'createdFileTime': True,
                         'processMachine': True, 'nativeMachine': True})
        self.assertNotIn('private', json.dumps(result))
        self.assertTrue(result['ownedWindowRemoved']); self.assertEqual(fixture.calls, [])

    def test_unregister_failure_keeps_its_stage_after_baseline_handle_release(self):
        fixture = MaskedStartupFixture(module(), baseline=True)
        fixture.user.UnregisterClassW = ApiCall(lambda *args: False)
        with self.assertRaisesRegex(ValueError, '소유 focus probe class 제거 실패'): fixture.run()
        result = fixture.probe.last_focus_probe_result
        self.assertIsNone(result['firstFailure'])
        self.assertEqual(result['cleanupFailure'], {'errorType': 'ValueError', 'stage': 'unregisterClass'})
        self.assertTrue(result['ownedWindowRemoved']); self.assertFalse(fixture.probe_exists)
        self.assertCountEqual(fixture.closed, [11, 22])


if __name__ == '__main__': unittest.main()
