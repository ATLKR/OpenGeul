"""Failure-only picker observations preserve the original failure and private text."""
import ctypes
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'e2e'))
import driver


class PickerClosureTests(unittest.TestCase):
    def observe(self, *, oversized=False, write_failure=False):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        session = driver.Session.__new__(driver.Session)
        session.folder = self.folder; session.proc = SimpleNamespace(pid=202)
        button = SimpleNamespace(handle=11, control_id=lambda: 2,
            is_visible=lambda: True, is_enabled=lambda: True,
            rectangle=lambda: SimpleNamespace(left=20, top=40, right=80, bottom=80),
            window_text=Mock(side_effect=AssertionError('Never read filenames or text')),
            click_input=Mock())
        dialog = SimpleNamespace(handle=10, process_id=lambda: 202, class_name=lambda: '#32770',
            descendants=lambda **kwargs: [button], set_focus=Mock(), wait=Mock())
        dialog.wrapper_object = lambda: dialog
        window = {'hwnd': 10, 'root': 10, 'pid': 202, 'tid': 91, 'cls': '#32770',
                  'visible': True, 'enabled': True, 'owners': []}
        if oversized: window['owners'] = list(range(10000))
        probe = SimpleNamespace(foreground=lambda: 10, hit=lambda point: 11,
            window=lambda hwnd: {**window, 'hwnd': hwnd}, close=Mock())
        modules = {'pywinauto': SimpleNamespace(Desktop=lambda **kwargs: SimpleNamespace(window=lambda **filters: dialog)),
            'pywinauto.controls.hwndwrapper': SimpleNamespace(InvalidWindowHandle=RuntimeError),
            'print_focus': SimpleNamespace(WindowsFocusProbe=lambda: probe)}
        original = AssertionError('exact picker closure timeout')
        with patch.dict(sys.modules, modules), patch.object(driver, 'until', side_effect=original), \
                patch.object(ctypes, 'windll', SimpleNamespace(user32=SimpleNamespace(
                    IsWindow=lambda hwnd: True, IsWindowVisible=lambda hwnd: True)), create=True):
            if write_failure:
                with patch.object(Path, 'write_bytes', side_effect=OSError('Cannot write evidence')):
                    with self.assertRaises(AssertionError) as captured: session.native_dialog(None)
            else:
                with self.assertRaises(AssertionError) as captured: session.native_dialog(None)
        self.assertIs(captured.exception, original)
        button.click_input.assert_called_once_with()
        button.window_text.assert_not_called()
        probe.close.assert_called_once_with()

    def test_closure_failure_records_only_bounded_owned_window_button_and_point_metadata(self):
        self.observe()
        data = (self.folder/'native-picker-closure.json').read_bytes()
        self.assertLessEqual(len(data), 16*1024)
        record = json.loads(data)
        self.assertEqual(record['expectedHwnd'], 10)
        self.assertEqual(record['expectedPid'], 202)
        self.assertEqual(record['buttonHwnd'], 11)
        self.assertEqual(record['buttonCenterObservedAfterFailure'], [50, 60])
        self.assertTrue(record['buttonClickReturned'])

    def test_oversize_metadata_is_not_written_and_original_error_is_preserved(self):
        self.observe(oversized=True)
        self.assertFalse((self.folder/'native-picker-closure.json').exists())

    def test_diagnostic_write_failure_cannot_replace_original_or_repeat_input(self):
        self.observe(write_failure=True)
        self.assertFalse((self.folder/'native-picker-closure.json').exists())
