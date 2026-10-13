"""Owned native Print input; only the external Windows boundary is substituted."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Probe:
    def __init__(self):
        self.windows = {
            300: dict(hwnd=300, pid=20, tid=21, cls='#32770', root=300,
                      owners=[100], visible=True, enabled=True),
            301: dict(hwnd=301, pid=20, tid=21, cls='Button', root=300,
                      owners=[100], visible=True, enabled=True),
        }
        self.processes = {10: dict(pid=10, creation=100, session=2),
                          20: dict(pid=20, creation=200, session=2, parentProcessId=10)}
        self.foreground_hwnd = 999
        self.hit_hwnd = 301
        self.activations = []
        self.barriers = []
        self.closed = False
        self.activation_result = True
        self.barrier_result = True
    def bind_process(self, pid, expected, handle=None):
        return dict(self.processes[pid])
    def verify_process(self, pid, expected):
        if self.processes.get(pid) != expected:
            raise AssertionError('Changed held process')
    def window(self, hwnd):
        if hwnd not in self.windows:
            raise AssertionError('Closed native window')
        return dict(self.windows[hwnd])
    def foreground(self): return self.foreground_hwnd
    def set_foreground(self, hwnd):
        self.activations.append(hwnd)
        if self.activation_result: self.foreground_hwnd = hwnd
        return self.activation_result
    def sync_activation(self, hwnd, expected, report):
        self.barriers.append(hwnd)
        report.update(returned=self.barrier_result, timeoutMs=1000)
        return self.barrier_result
    def hit(self, point): return self.hit_hwnd
    def close(self): self.closed = True


class Button:
    handle = 301
    def __init__(self, probe):
        self.probe = probe
        self.inputs = []
        self.error = None
    def process_id(self): return 20
    def class_name(self): return 'Button'
    def control_id(self): return 1010
    def is_visible(self): return True
    def is_enabled(self): return True
    def rectangle(self):
        return types.SimpleNamespace(left=10, top=20, right=50, bottom=60)
    def click_input(self):
        self.inputs.append((self.handle, self.probe.foreground_hwnd))
        if self.error: raise self.error


class Dialog:
    handle = 300
    def __init__(self, button): self.button = button
    def process_id(self): return 20
    def class_name(self): return '#32770'
    def window_text(self): return 'Print'
    def descendants(self, **filters): return [self.button]


class PrintNativeInputTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('owned_native_print_test', ROOT/'e2e/print_focus.py')
        self.module = importlib.util.module_from_spec(spec)
        desktop = types.ModuleType('pywinauto'); desktop.Desktop = None
        with patch.dict(sys.modules, {'pywinauto': desktop}): spec.loader.exec_module(self.module)
        self.assertIsNotNone(getattr(self.module, 'click_owned_print_preferences', None),
                             'Missing owned native Preferences input boundary')
        self.probe = Probe(); self.button = Button(self.probe); self.dialog = Dialog(self.button)
        self.runtime = {'nativeArchitecture': {'processId': 10, 'architecture': 'arm64'},
                        'webview2Native': {'rootProcessId': 10, 'processes': [
                            {'processId': 20, 'parentProcessId': 10}]}}
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def call(self):
        fn = getattr(self.module, 'click_owned_print_preferences', None)
        self.assertIsNotNone(fn, 'Missing owned native Preferences input boundary')
        return fn(self.dialog, 10, self.runtime, app_handle=77,
                  evidence_dir=self.folder, probe=self.probe)

    def diagnostic(self):
        path = self.folder/'print-native-preferences-diagnostic.json'
        self.assertTrue(path.is_file())
        self.assertLessEqual(path.stat().st_size, 4096)
        return json.loads(path.read_bytes())

    def test_owned_dialog_activates_once_and_receives_one_physical_click(self):
        self.call()
        self.assertEqual(self.button.inputs, [(301, 300)])
        self.assertEqual(self.probe.activations, [300]); self.assertEqual(self.probe.barriers, [300])
        data = self.diagnostic(); self.assertTrue(data['passed']); self.assertEqual(data['hitHwnd'], 301)
        self.assertTrue(self.probe.closed)

    def test_exact_dialog_already_foreground_needs_no_activation(self):
        self.probe.foreground_hwnd = 300; self.call()
        self.assertEqual(self.button.inputs, [(301, 300)]); self.assertEqual(self.probe.activations, [])

    def test_foreign_overlay_at_preferences_center_receives_no_input(self):
        self.probe.hit_hwnd = 999
        with self.assertRaises(AssertionError): self.call()
        self.assertEqual(self.button.inputs, [])
        self.assertFalse(self.diagnostic()['passed']); self.assertEqual(self.diagnostic()['hitHwnd'], 999)

    def test_foreign_foreground_after_owned_barrier_receives_no_input(self):
        def barrier(hwnd, expected, report): self.probe.foreground_hwnd = 999; return True
        self.probe.sync_activation = barrier
        with self.assertRaises(AssertionError): self.call()
        self.assertEqual(self.button.inputs, []); self.assertEqual(self.probe.activations, [300])

    def test_hwnd_retargeted_during_hit_query_receives_no_input(self):
        def hit(point): self.probe.windows[301]['tid'] = 999; return 301
        self.probe.hit = hit
        with self.assertRaises(AssertionError): self.call()
        self.assertEqual(self.button.inputs, [])

    def test_changed_held_process_before_click_receives_no_input(self):
        def hit(point): self.probe.processes[20]['creation'] = 999; return 301
        self.probe.hit = hit
        with self.assertRaises(AssertionError): self.call()
        self.assertEqual(self.button.inputs, [])

    def test_closed_hidden_disabled_wrong_pid_or_root_receives_no_input(self):
        for row, change in ((300, {'pid': 99}), (301, {'root': 999}),
                            (301, {'visible': False}), (301, {'enabled': False})):
            with self.subTest(row=row, change=change):
                self.setUp(); self.probe.windows[row].update(change)
                with self.assertRaises(AssertionError): self.call()
                self.assertEqual(self.button.inputs, [])
        self.setUp(); del self.probe.windows[300]
        with self.assertRaises(AssertionError): self.call()
        self.assertEqual(self.button.inputs, [])

    def test_wrong_app_or_foreign_ancestry_rejects_before_activation(self):
        for kind in ('wrong-app', 'foreign-parent', 'cycle', 'duplicate'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'wrong-app': self.runtime['nativeArchitecture']['processId'] = 99
                elif kind == 'foreign-parent': self.runtime['webview2Native']['processes'][0]['parentProcessId'] = 99
                elif kind == 'cycle': self.runtime['webview2Native']['processes'][0]['parentProcessId'] = 20
                else: self.runtime['webview2Native']['processes'].append(dict(self.runtime['webview2Native']['processes'][0]))
                with self.assertRaises(AssertionError): self.call()
                self.assertEqual(self.button.inputs, []); self.assertEqual(self.probe.activations, [])

    def test_changed_rectangle_after_activation_receives_no_input(self):
        def barrier(hwnd, expected, report):
            self.button.rectangle = lambda: types.SimpleNamespace(left=20, top=20, right=60, bottom=60)
            return True
        self.probe.sync_activation = barrier
        with self.assertRaises(AssertionError): self.call()
        self.assertEqual(self.button.inputs, [])

    def test_successful_click_may_activate_preferences_modal(self):
        def click():
            self.button.inputs.append((301, self.probe.foreground_hwnd)); self.probe.foreground_hwnd = 400
        self.button.click_input = click; self.call()
        self.assertEqual(self.button.inputs, [(301, 300)])
        self.assertTrue(self.diagnostic()['passed']); self.assertEqual(self.diagnostic()['foregroundAfter'], 400)

    def test_rejected_activation_or_barrier_is_not_retried(self):
        for field in ('activation_result', 'barrier_result'):
            with self.subTest(field=field):
                self.setUp(); setattr(self.probe, field, False)
                with self.assertRaises(AssertionError): self.call()
                self.assertEqual(self.button.inputs, []); self.assertEqual(self.probe.activations, [300])

    def test_click_error_escapes_once_and_diagnostic_does_not_store_opaque_message(self):
        self.button.error = OSError('secret https://example.invalid/opaque?token=secret')
        with self.assertRaises(OSError): self.call()
        self.assertEqual(self.button.inputs, [(301, 300)])
        data = self.diagnostic(); self.assertFalse(data['passed']); self.assertEqual(data['errorType'], 'OSError')
        self.assertNotIn('secret', json.dumps(data)); self.assertTrue(self.probe.closed)

    def test_actual_configure_media_rejects_overlay_before_wait_or_unguarded_click(self):
        fn = getattr(self.module, 'click_owned_print_preferences', None)
        self.assertIsNotNone(fn, 'Missing owned native Preferences input boundary')
        (self.folder/'session').mkdir(); (self.folder/'session/runtime.json').write_text(json.dumps(self.runtime))
        source = ast.parse((ROOT/'e2e/virtual_print.py').read_text(encoding='utf8'))
        selected = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'configure_media')
        scope = {'json': json, 'control': lambda *args: self.button,
                 'click_owned_print_preferences': lambda *args, **kwargs: fn(*args, **kwargs, probe=self.probe),
                 'wait': lambda *args: self.fail('UI wait must not start after rejected input')}
        exec(compile(ast.Module(body=[selected], type_ignores=[]), 'actual-configure-media', 'exec'), scope)
        self.probe.hit_hwnd = 999
        with self.assertRaises(AssertionError):
            scope['configure_media'](self.dialog, 10, self.folder, app_handle=77)
        self.assertEqual(self.button.inputs, [])


if __name__ == '__main__': unittest.main()
