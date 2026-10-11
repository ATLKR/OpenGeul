"""Native close must target one real owned editor, never its IPC or dialog HWNDs."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('native_editor_close', ROOT / 'e2e/password/native.py')
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)

# Actual original-selector records from diagnostic run 38166248802, source61.
OWNED_PID = 1512
EDITOR = {'handle': 131516, 'pid': OWNED_PID, 'class_name': 'Tauri Window', 'title': 'OpenGeul'}
SINGLE_INSTANCE = {'handle': 524334, 'pid': OWNED_PID,
                   'class_name': 'org.allenlabs.opengeul-sic', 'title': 'org.allenlabs.opengeul-siw'}


class Window:
    def __init__(self, handle=10, pid=OWNED_PID, class_name='Tauri Window',
                 title='OpenGeul', visible=True, enabled=True):
        self.handle, self.pid, self.cls, self.title = handle, pid, class_name, title
        self.visible, self.enabled = visible, enabled
        self.inputs = []

    def process_id(self):
        return self.pid

    def class_name(self):
        return self.cls

    def window_text(self):
        return self.title

    def is_visible(self):
        return self.visible

    def is_enabled(self):
        return self.enabled

    def set_focus(self):
        self.inputs.append(('focus',))

    def type_keys(self, *args, **kwargs):
        self.inputs.append(('keys', args, kwargs))


class NativeEditorCloseTests(unittest.TestCase):
    def request(self, windows):
        desktop_calls = []

        class Desktop:
            def __init__(self, *, backend):
                desktop_calls.append(('backend', backend))

            def windows(self, *, process):
                desktop_calls.append(('process', process))
                # Return exactly the external boundary's records. The actual
                # ownership guard must also reject a mismatched returned PID.
                return windows

        session = SimpleNamespace(proc=SimpleNamespace(pid=OWNED_PID))
        probe = NATIVE.Qualification.__new__(NATIVE.Qualification)
        with patch.dict(sys.modules, {'pywinauto': SimpleNamespace(Desktop=Desktop)}):
            try:
                return probe.request_native_close(session)
            finally:
                self.assertEqual(desktop_calls, [('backend', 'win32'), ('process', OWNED_PID)])

    def assert_no_input_failure(self, windows, message='Expected one owned native editor window'):
        with self.assertRaisesRegex(AssertionError, message):
            self.request(windows)
        self.assertTrue(all(window.inputs == [] for window in windows))

    def assert_one_physical_close(self, window, observed):
        self.assertEqual(observed, {'hwnd': window.handle, 'processId': window.pid,
                                   'title': window.title, 'class': 'Tauri Window',
                                   'input': 'physical Alt+F4'})
        self.assertEqual(window.inputs, [('focus',), ('keys', ('%{F4}',), {'set_foreground': True})])

    def test_actual_source61_editor_and_single_instance_window_close_only_editor(self):
        editor, ipc = Window(**EDITOR), Window(**SINGLE_INSTANCE)
        observed = self.request([editor, ipc])
        self.assert_one_physical_close(editor, observed)
        self.assertEqual(ipc.inputs, [])

    def test_single_owned_editor_gets_one_physical_alt_f4(self):
        editor = Window(**EDITOR)
        self.assert_one_physical_close(editor, self.request([editor]))

    def test_empty_window_list_fails_without_input(self):
        self.assert_no_input_failure([])

    def test_actual_single_instance_window_alone_fails_without_input(self):
        self.assert_no_input_failure([Window(**SINGLE_INSTANCE)])

    def test_hidden_editor_fails_without_input(self):
        self.assert_no_input_failure([Window(visible=False)])

    def test_disabled_editor_fails_without_input(self):
        self.assert_no_input_failure([Window(enabled=False)])

    def test_titleless_editor_fails_without_input(self):
        self.assert_no_input_failure([Window(title='')])

    def test_other_window_classes_cannot_impersonate_editor(self):
        for class_name in ('Tauri Window ', 'tauri window', 'WorkerW', 'Tao Thread Event Target', '#32770'):
            with self.subTest(class_name=class_name):
                self.assert_no_input_failure([Window(class_name=class_name)])

    def test_two_real_editors_fail_without_input_to_either(self):
        self.assert_no_input_failure([Window(handle=10), Window(handle=11, title='Second document')])

    def test_duplicate_editor_handles_fail_without_input_to_either_wrapper(self):
        self.assert_no_input_failure([Window(handle=10), Window(handle=10)])

    def test_repeated_editor_record_fails_without_input(self):
        editor = Window()
        self.assert_no_input_failure([editor, editor])

    def test_mismatched_returned_owner_fails_before_focus_or_close(self):
        self.assert_no_input_failure([Window(pid=OWNED_PID + 1)], 'Native close window ownership differs')

    def test_foreign_and_owned_editors_are_not_resolved_by_picking_first(self):
        self.assert_no_input_failure([Window(pid=OWNED_PID + 1), Window(handle=11)])

    def test_native_dialog_and_tao_auxiliary_are_ignored_without_input(self):
        editor = Window(**EDITOR)
        dialog = Window(handle=12, class_name='#32770', title='저장 확인')
        auxiliary = Window(handle=13, class_name='Tao Thread Event Target', title='Auxiliary')
        self.assert_one_physical_close(editor, self.request([dialog, auxiliary, editor]))
        self.assertEqual(dialog.inputs, [])
        self.assertEqual(auxiliary.inputs, [])


if __name__ == '__main__':
    unittest.main()
