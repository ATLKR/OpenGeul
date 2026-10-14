"""Offline native information-message ownership and public recent-menu flow."""
import copy
import importlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'e2e'))
import native_controls


class Probe:
    def __init__(self):
        self.dialog = {'hwnd': 10, 'root': 10, 'pid': 202, 'tid': 91, 'cls': '#32770',
                       'visible': True, 'enabled': True, 'owners': [20]}
        self.button = {**self.dialog, 'hwnd': 11, 'cls': 'Button'}
        self.foreground_hwnd = 10; self.hit_hwnd = 11; self.reads = 0; self.change = None
    def verify_process(self, pid, record):
        if pid != 202 or record != {'creation': 123, 'session': 1}:
            raise AssertionError('Held process changed')
    def window(self, hwnd):
        if hwnd == 10:
            self.reads += 1
            if self.reads == 2 and self.change: self.dialog.update(self.change)
            return copy.deepcopy(self.dialog)
        if hwnd == 11: return copy.deepcopy(self.button)
        raise AssertionError('Unowned HWND')
    def hit(self, point): return self.hit_hwnd
    def foreground(self): return self.foreground_hwnd


class Control:
    def __init__(self, text='최근 문서가 없습니다.', hwnd=10, pid=202):
        self.handle = hwnd; self.pid = pid; self.text = text
        self.visible = True; self.enabled = True; self.id = 1
    def process_id(self): return self.pid
    def class_name(self): return 'Button' if self.handle == 11 else '#32770'
    def is_visible(self): return self.visible
    def is_enabled(self): return self.enabled
    def window_text(self): return self.text
    def control_id(self): return self.id
    def rectangle(self): return SimpleNamespace(left=20, top=40, right=80, bottom=80)


class NativeInformationTests(unittest.TestCase):
    def acknowledge(self, *, probe=None, message=None, button=None, accessible_pid=202):
        self.inputs = []; probe = probe or Probe(); dialog = Control(); accessible = Control(pid=accessible_pid)
        message = message or Control(); button = button or Control('OK', 11)
        dialog.descendants = lambda **kwargs: [button]
        accessible.descendants = lambda **kwargs: [message]
        helper = getattr(native_controls, 'acknowledge_information_dialog', None)
        self.assertIsNotNone(helper, 'Actual native information handler is required')
        return helper(probe, dialog, accessible, 202, {'creation': 123, 'session': 1},
                      '최근 문서가 없습니다.', self.inputs.append)

    def test_wrong_text_owner_or_ambiguous_message_never_confirms(self):
        message = Control(pid=999)
        with self.assertRaises(AssertionError): self.acknowledge(message=message)
        self.assertEqual(self.inputs, [])
        probe = Probe(); dialog = Control(); accessible = Control(); button = Control('OK', 11)
        dialog.descendants = lambda **kwargs: [button]
        accessible.descendants = lambda **kwargs: [Control(), Control()]
        inputs = []
        with self.assertRaises(AssertionError):
            native_controls.acknowledge_information_dialog(probe, dialog, accessible, 202,
                {'creation': 123, 'session': 1}, '최근 문서가 없습니다.', inputs.append)
        self.assertEqual(inputs, [])

    def session_acknowledge(self, *, replaced_after_click=False):
        import driver
        probe = Probe(); probe.closed = False; dialog = Control(); accessible = Control(); button = Control('OK', 11)
        dialog.descendants = lambda **kwargs: [button]
        accessible.descendants = lambda **kwargs: [Control()]
        dialog.wait = Mock(); dialog.wrapper_object = lambda: dialog
        accessible.wrapper_object = lambda: accessible
        dialog.set_focus = lambda: None
        state = {'exists': True}; self.physical_inputs = []
        def click(*, coords):
            self.physical_inputs.append(coords)
            if replaced_after_click: probe.dialog['tid'] = 92
            else: state['exists'] = False
        probe.user = SimpleNamespace(IsWindow=lambda hwnd: state['exists'])
        probe.close = lambda: setattr(probe, 'closed', True)
        with tempfile.TemporaryDirectory() as folder:
            session = driver.Session.__new__(driver.Session)
            session.mode = 'native'; session.folder = Path(folder); session.proc = SimpleNamespace(pid=202, _handle=1)
            (session.folder/'runtime.json').write_text('{}')
            modules = {'pywinauto': SimpleNamespace(Desktop=lambda **kwargs: SimpleNamespace(
                window=lambda **filters: dialog if kwargs['backend'] == 'win32' else accessible),
                mouse=SimpleNamespace(click=click)),
                'print_focus': SimpleNamespace(WindowsFocusProbe=lambda: probe,
                    _bind_native_print_processes=lambda *args: ({202: {'creation': 123, 'session': 1}}, None))}
            with patch.dict(sys.modules, modules), patch.object(driver, 'os', SimpleNamespace(name='nt')):
                try: return session.acknowledge_native_information('최근 문서가 없습니다.')
                finally:
                    self.assertTrue(probe.closed)
                    if replaced_after_click:
                        self.assertFalse((session.folder/'native-information-1.json').exists())

    def test_session_confirms_once_and_records_same_owned_dialog_closure(self):
        record = self.session_acknowledge()
        self.assertEqual(self.physical_inputs, [(50, 60)])
        self.assertTrue(record['actualPhysicalConfirmation'])
        self.assertTrue(record['sameOwnedDialogClosed'])

    def test_session_does_not_accept_same_hwnd_thread_replacement_as_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            self.session_acknowledge(replaced_after_click=True)
        self.assertEqual(self.physical_inputs, [(50, 60)])

    def test_exact_native_message_has_two_bindings_then_one_physical_confirmation(self):
        probe = Probe(); record = self.acknowledge(probe=probe)
        self.assertEqual(self.inputs, [(50, 60)])
        self.assertEqual(probe.reads, 2)
        self.assertEqual(record['message'], '최근 문서가 없습니다.')
        self.assertEqual(record['button']['hwnd'], 11)

    def test_wrong_or_normalized_message_never_confirms(self):
        for text in ('최근 문서가 있습니다.', '최근 문서가 없습니다', ' 최근 문서가 없습니다.', '최근\n문서가 없습니다.'):
            with self.subTest(text=text), self.assertRaises(AssertionError):
                self.acknowledge(message=Control(text))
            self.assertEqual(self.inputs, [])

    def test_wrong_process_window_thread_or_accessible_owner_never_confirms(self):
        for key, value in (('pid', 999), ('root', 20), ('tid', 0), ('cls', 'Tauri Window'),
                           ('visible', False), ('enabled', False)):
            probe = Probe(); probe.dialog[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): self.acknowledge(probe=probe)
            self.assertEqual(self.inputs, [])
        with self.assertRaises(AssertionError): self.acknowledge(accessible_pid=999)
        self.assertEqual(self.inputs, [])

    def test_wrong_button_id_owner_readiness_hit_or_foreground_never_confirms(self):
        for key, value in (('id', 2), ('pid', 999), ('visible', False), ('enabled', False)):
            button = Control('OK', 11); setattr(button, key, value)
            with self.subTest(key=key), self.assertRaises(AssertionError): self.acknowledge(button=button)
            self.assertEqual(self.inputs, [])
        for key, value in (('hit_hwnd', 20), ('foreground_hwnd', 20)):
            probe = Probe(); setattr(probe, key, value)
            with self.subTest(key=key), self.assertRaises(AssertionError): self.acknowledge(probe=probe)
            self.assertEqual(self.inputs, [])

    def test_same_hwnd_thread_substitution_before_confirmation_fails(self):
        probe = Probe(); probe.change = {'tid': 92}
        with self.assertRaises(AssertionError): self.acknowledge(probe=probe)
        self.assertEqual(self.inputs, [])

    def recent(self, *, native_error=None):
        # Import this mixin only; no setUp, native process or product is started.
        with patch.dict(os.environ, {'E2E_FIXTURES': str(ROOT), 'E2E_OUTPUT': str(ROOT)}):
            module = importlib.import_module('test_supported_features')
        case = SimpleNamespace(recent_guard=Mock(), assertEqual=self.assertEqual)
        case.session = SimpleNamespace(dialogs=[],
            acknowledge_native_information=Mock(side_effect=native_error))
        dialog = Mock(); dialog.is_visible.return_value = False; dialog.count.return_value = 0
        status = Mock(); status.inner_text.return_value = '최근 문서가 없습니다'
        case.page = SimpleNamespace(locator=lambda selector: dialog if selector == '.recent-documents-dialog' else status)
        with patch.object(module, 'menu') as public_menu, patch.object(module, 'until', side_effect=lambda predicate, **kwargs: predicate()):
            result = module.SupportedNativeTests.recent_paths(case)
        public_menu.assert_called_once_with(case.page, 'file:open-recent')
        case.session.acknowledge_native_information.assert_called_once_with('최근 문서가 없습니다.')
        return result

    def test_empty_recent_uses_actual_native_confirmation_without_browser_alert_event(self):
        self.assertEqual(self.recent(), (None, []))

    def test_native_confirmation_failure_cannot_be_reported_as_empty_recent(self):
        with self.assertRaisesRegex(AssertionError, 'native ownership'):
            self.recent(native_error=AssertionError('native ownership'))
