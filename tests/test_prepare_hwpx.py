"""Cancellation must finish in the application before the native driver continues."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_driver():
    api = types.SimpleNamespace(sync_playwright=Mock(), expect=Mock())
    spec = importlib.util.spec_from_file_location('cancel_save_driver', ROOT/'e2e/driver.py')
    driver = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'playwright': types.ModuleType('playwright'), 'playwright.sync_api': api}), \
            patch.object(sys, 'path', [str(ROOT/'e2e'), *sys.path]):
        spec.loader.exec_module(driver)
    return driver


class CancelledSaveAsDriverTests(unittest.TestCase):
    def setUp(self):
        self.driver = load_driver()
        self.events = []
        self.session = self.driver.Session.__new__(self.driver.Session)
        self.session.mode = 'native'
        self.session.page = Mock()
        self.session.native_dialog = Mock(side_effect=lambda target: self.events.append(('dialog-closed', target)))
        self.driver.menu = Mock(side_effect=lambda page, command: self.events.append(('menu', command)))
        self.driver.expect = Mock(return_value=types.SimpleNamespace(to_have_text=self.wait_for_completion))

    def wait_for_completion(self, message, *, timeout):
        self.events.append(('completion', message, timeout))

    def test_cancel_waits_for_exact_application_completion_before_returning(self):
        result = self.session.save(Path('original.hwpx'), Path('must-not-exist.hwpx'), save_as=True, cancel=True)
        self.events.append(('returned', result))
        self.assertEqual(self.events, [
            ('menu', 'file:save-as'), ('dialog-closed', None),
            ('completion', '다른 이름으로 저장 취소', 30000), ('returned', None),
        ])
        self.session.page.locator.assert_called_once_with('#sb-message')
        self.session.page.wait_for_function.assert_not_called()

    def test_missing_cancellation_completion_fails_without_retrying(self):
        def incomplete(message, *, timeout):
            self.wait_for_completion(message, timeout=timeout)
            raise AssertionError('application cancellation did not complete')
        self.driver.expect.return_value.to_have_text = incomplete
        with self.assertRaisesRegex(AssertionError, 'application cancellation did not complete'):
            self.session.save(Path('original.hwpx'), Path('must-not-exist.hwpx'), save_as=True, cancel=True)
        self.driver.menu.assert_called_once_with(self.session.page, 'file:save-as')
        self.session.native_dialog.assert_called_once_with(None)
        self.driver.expect.assert_called_once()


class NativePickerReadinessTests(unittest.TestCase):
    def setUp(self):
        self.driver = load_driver()
        self.session = self.driver.Session.__new__(self.driver.Session)
        self.session.proc = types.SimpleNamespace(pid=123)
        self.session.page = Mock()
        self.filename = Mock()
        self.filename.class_name.return_value = 'Edit'
        self.filename.parent.return_value.class_name.return_value = 'ComboBox'
        self.filename.is_visible.return_value = True
        self.filename.is_enabled.return_value = True
        self.button = Mock()
        self.button.control_id.return_value = 1
        self.button.is_visible.return_value = True
        self.button.is_enabled.return_value = True
        self.dialog = Mock(handle=456)
        self.dialog.process_id.return_value = 123
        self.dialog.class_name.return_value = '#32770'
        self.spec = Mock()
        self.spec.wrapper_object.return_value = self.dialog
        self.desktop = Mock()
        self.desktop.window.return_value = self.spec
        self.api = patch.dict(sys.modules, {'pywinauto': types.SimpleNamespace(Desktop=lambda **kw: self.desktop)})
        self.api.start()
        self.addCleanup(self.api.stop)
        self.driver.ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(
            user32=types.SimpleNamespace(IsWindow=lambda hwnd: False, IsWindowVisible=lambda hwnd: False)))
        self.driver.until = Mock(side_effect=self.poll)

    def poll(self, check, timeout=25, **kwargs):
        # Model bounded polling without sleeping or performing any dialog action.
        for _ in range(3):
            try:
                value = check()
                if value:
                    return value
            except ValueError:
                pass
        raise AssertionError('native picker filename never became ready')

    def test_waits_for_initially_missing_filename_then_acts_once(self):
        self.dialog.descendants.side_effect = [[], [self.filename], [self.button]]
        target = Path('selected.hwpx')
        self.session.native_dialog(target)
        self.desktop.window.assert_called_once_with(class_name='#32770', process=123)
        self.filename.set_edit_text.assert_called_once_with(str(target))
        self.button.click_input.assert_called_once()
        self.assertEqual(self.dialog.descendants.call_count, 3)

    def test_never_ready_picker_fails_before_setting_or_clicking(self):
        self.dialog.descendants.return_value = []
        with self.assertRaisesRegex(AssertionError, 'filename never became ready'):
            self.session.native_dialog(Path('selected.hwpx'))
        self.filename.set_edit_text.assert_not_called()
        self.button.click_input.assert_not_called()

    def test_wrong_owner_is_rejected_before_enumerating_controls(self):
        self.dialog.process_id.return_value = 999
        self.dialog.descendants.side_effect = lambda **kw: [self.button] if kw else [self.filename]
        with self.assertRaisesRegex(AssertionError, 'ownership'):
            self.session.native_dialog(Path('selected.hwpx'))
        self.dialog.descendants.assert_not_called()
        self.button.click_input.assert_not_called()


if __name__ == '__main__':
    unittest.main()
