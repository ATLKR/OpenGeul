"""읽기 전용 ARM 러너 관찰의 실행 경계·상한·무입력을 검증한다."""
import importlib.util
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
                 'sessionId': 1, 'signature': {'status': 'Valid', 'subject': 'CN=Microsoft Windows, O=Microsoft Corporation',
                 'issuer': 'CN=Microsoft Windows Production PCA', 'thumbprint': 'C' * 40,
                 'publisherMicrosoft': True}} for n in pids]

    def uia(self, hwnd):
        return {'hwnd': hwnd, 'nodes': [{'name': 'Next', 'controlType': 50000, 'automationId': 'Next',
                 'className': 'Button', 'processId': 200, 'enabled': True, 'offscreen': False}],
                'truncated': False}

    def screen(self, path):
        path.write_bytes(b'\x89PNG\r\n\x1a\nsynthetic-OS-observer-image')
        return {'width': 1200, 'height': 900}


class RunnerReadyTests(unittest.TestCase):
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
