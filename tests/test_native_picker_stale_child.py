"""A vanished shell child must not retarget the owned Save As dialog."""
import ctypes
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class InvalidWindowHandle(RuntimeError):
    # Exact pywinauto 0.6.9 exception API: it has no handle attribute.
    def __init__(self, hwnd):
        super().__init__(f'Handle {hwnd} is not a vaild window handle')


class WindowApi:
    def __init__(self):
        self.windows = {983592: dict(pid=8028, thread=91, cls='#32770', visible=True, enabled=True)}
    def IsWindow(self, hwnd):
        return hwnd in self.windows
    def IsWindowVisible(self, hwnd):
        return self.windows.get(hwnd, {}).get('visible', False)
    def IsWindowEnabled(self, hwnd):
        return self.windows.get(hwnd, {}).get('enabled', False)
    def GetWindowThreadProcessId(self, hwnd, pid):
        item = self.windows.get(hwnd, {})
        pid._obj.value = item.get('pid', 0)
        return item.get('thread', 0)
    def GetClassNameW(self, hwnd, text, count):
        text.value = self.windows.get(hwnd, {}).get('cls', '')[:count-1]
        return len(text.value)


class NativePickerStaleChildTests(unittest.TestCase):
    def setUp(self):
        api = types.SimpleNamespace(sync_playwright=Mock(), expect=Mock())
        spec = importlib.util.spec_from_file_location('stale_child_driver', ROOT/'e2e/driver.py')
        self.driver = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'playwright': types.ModuleType('playwright'), 'playwright.sync_api': api}), \
                patch.object(sys, 'path', [str(ROOT/'e2e'), *sys.path]):
            spec.loader.exec_module(self.driver)
        self.clock = 0
        self.sleeps = []
        def sleep(seconds):
            self.sleeps.append(seconds)
            self.clock += seconds
        self.driver.time = types.SimpleNamespace(monotonic=lambda: self.clock, sleep=sleep)
        self.user32 = WindowApi()
        self.driver.ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(user32=self.user32),
                                                   c_uint32=ctypes.c_uint32, byref=ctypes.byref,
                                                   create_unicode_buffer=ctypes.create_unicode_buffer)
        self.session = self.driver.Session.__new__(self.driver.Session)
        self.session.proc = types.SimpleNamespace(pid=8028)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session.folder = Path(self.temp.name)
        self.session._record_picker_readiness_failure = Mock()
        self.filename = Mock()
        self.filename.class_name.return_value = 'Edit'
        self.filename.parent.return_value.class_name.return_value = 'ComboBox'
        self.filename.is_visible.return_value = True
        self.filename.is_enabled.return_value = True
        self.button = Mock()
        self.button.control_id.return_value = 1
        self.button.is_visible.return_value = True
        self.button.is_enabled.return_value = True
        self.dialog = Mock(handle=983592)
        self.dialog.process_id.return_value = 8028
        self.dialog.class_name.return_value = '#32770'
        self.dialog.window_text.return_value = 'Save As'
        self.spec = Mock()
        self.spec.wrapper_object.return_value = self.dialog
        self.desktop = Mock()
        self.desktop.window.return_value = self.spec
        packages = {'pywinauto': types.SimpleNamespace(Desktop=lambda **kw: self.desktop),
                    'pywinauto.controls': types.ModuleType('pywinauto.controls'),
                    'pywinauto.controls.hwndwrapper': types.SimpleNamespace(InvalidWindowHandle=InvalidWindowHandle)}
        self.api = patch.dict(sys.modules, packages)
        self.api.start()
        self.addCleanup(self.api.stop)
        self.enum_count = 0
        self.failure = InvalidWindowHandle(197236)
        self.first_enumeration = lambda: (_ for _ in ()).throw(self.failure)
        def descendants(**kwargs):
            if kwargs:
                self.assertEqual(kwargs, {'class_name': 'Button'})
                return [self.button]
            self.enum_count += 1
            if self.enum_count == 1:
                return self.first_enumeration()
            return [self.filename]
        self.dialog.descendants.side_effect = descendants
        # Model the exact owned dialog disappearing after the physical Save click.
        self.button.click_input.side_effect = lambda: self.user32.windows.pop(983592, None)

    def fail_without_input(self, expected=InvalidWindowHandle):
        with self.assertRaises(expected) as error:
            self.session.native_dialog(Path('synthetic-output.hwp'))
        if expected is InvalidWindowHandle:
            self.assertIs(error.exception, self.failure)
        self.filename.set_edit_text.assert_not_called()
        self.dialog.set_focus.assert_not_called()
        self.button.click_input.assert_not_called()
        self.assertEqual(self.enum_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_actual_dead_child_then_ready_same_dialog_inputs_once(self):
        self.session.native_dialog(Path('synthetic-output.hwp'))
        self.assertEqual(self.enum_count, 2)
        self.assertEqual(self.sleeps, [.1])
        self.desktop.window.assert_called_once_with(class_name='#32770', process=8028)
        self.filename.set_edit_text.assert_called_once_with('synthetic-output.hwp')
        self.button.click_input.assert_called_once()
        self.session._record_picker_readiness_failure.assert_not_called()

    def test_parent_handle_invalid_exception_is_not_retried(self):
        self.failure = InvalidWindowHandle(983592)
        self.fail_without_input()

    def test_invalid_child_reused_and_live_is_not_retried(self):
        self.user32.windows[197236] = dict(pid=999, thread=33, cls='Edit', visible=True, enabled=True)
        self.fail_without_input()

    def test_parent_destroyed_during_enumeration_fails_without_input(self):
        def gone():
            self.user32.windows.pop(983592)
            raise self.failure
        self.first_enumeration = gone
        self.fail_without_input()

    def changed_parent(self, field, value):
        def changed():
            self.user32.windows[983592][field] = value
            raise self.failure
        self.first_enumeration = changed
        self.fail_without_input()

    def test_parent_owner_changed_fails_immediately(self):
        self.changed_parent('pid', 999)

    def test_parent_thread_changed_fails_immediately(self):
        self.changed_parent('thread', 92)

    def test_parent_class_changed_fails_immediately(self):
        self.changed_parent('cls', '#other')

    def test_parent_hidden_fails_immediately(self):
        self.changed_parent('visible', False)

    def test_parent_disabled_fails_immediately(self):
        self.changed_parent('enabled', False)

    def test_wrapper_retargets_during_enumeration_fails_without_input(self):
        def replaced():
            self.dialog.handle = 111
            raise self.failure
        self.first_enumeration = replaced
        self.fail_without_input()

    def test_unknown_invalid_handle_message_is_not_retried(self):
        self.failure.args = ('unexpected private error',)
        self.fail_without_input()

    def test_other_runtime_error_is_not_retried(self):
        self.failure = RuntimeError('original enumeration error')
        self.fail_without_input(RuntimeError)

    def test_selection_invalid_handle_is_not_retried(self):
        self.first_enumeration = lambda: [self.filename]
        self.filename.parent.side_effect = self.failure
        self.fail_without_input()

    def test_parent_changed_during_successful_enumeration_fails_without_input(self):
        def changed():
            self.user32.windows[983592]['pid'] = 999
            return [self.filename]
        self.first_enumeration = changed
        self.fail_without_input(RuntimeError)

    def test_parent_changed_during_candidate_selection_fails_without_input(self):
        self.first_enumeration = lambda: [self.filename]
        parent = self.filename.parent.return_value
        def changed():
            self.user32.windows[983592]['pid'] = 999
            return parent
        self.filename.parent.side_effect = changed
        self.fail_without_input(RuntimeError)

    def test_duplicate_filename_candidates_never_allow_input(self):
        self.dialog.descendants.side_effect = None
        self.dialog.descendants.return_value = [self.filename, self.filename]
        with self.assertRaisesRegex(AssertionError, '20s'):
            self.session.native_dialog(Path('synthetic-output.hwp'))
        self.filename.set_edit_text.assert_not_called()
        self.button.click_input.assert_not_called()

    def test_global_until_does_not_catch_invalid_window_handles(self):
        with self.assertRaises(InvalidWindowHandle) as error:
            self.driver.until(lambda: (_ for _ in ()).throw(self.failure), timeout=20)
        self.assertIs(error.exception, self.failure)
        self.assertEqual(self.sleeps, [])

    def test_dead_child_forever_obeys_original_20_second_deadline(self):
        self.dialog.descendants.side_effect = self.failure
        with self.assertRaisesRegex(AssertionError, '20s'):
            self.session.native_dialog(Path('synthetic-output.hwp'))
        self.assertGreaterEqual(self.clock, 20)
        self.assertLess(self.clock, 20.2)
        self.assertTrue(self.sleeps)
        self.assertEqual(set(self.sleeps), {.1})
        self.filename.set_edit_text.assert_not_called()
        self.button.click_input.assert_not_called()


if __name__ == '__main__':
    unittest.main()
