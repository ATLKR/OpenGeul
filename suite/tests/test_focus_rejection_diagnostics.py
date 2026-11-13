"""Raw capture rejection evidence must not change the strict native guard."""
import ctypes
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_editor_focus_readiness as focus_tests

native = focus_tests.native
E2E = Path(__file__).resolve().parents[1] / 'e2e'
CAPTURE = 2**48 + 73
MESSAGE = 'Owned editor mouse capture is still active before physical input'


class QueryBoundary(focus_tests.NativeFocusFrames):
    def __init__(self, captures):
        super().__init__([33], captures)
        self.calls = []
    def GetForegroundWindow(self):
        self.calls.append('foreground'); return super().GetForegroundWindow()
    def GetAncestor(self, hwnd, flag):
        self.calls.append('root'); return super().GetAncestor(hwnd, flag)
    def GetWindowThreadProcessId(self, hwnd, pointer):
        self.calls.append('thread'); return super().GetWindowThreadProcessId(hwnd, pointer)
    def GetGUIThreadInfo(self, tid, pointer):
        self.calls.append('gui'); result = super().GetGUIThreadInfo(tid, pointer)
        info = pointer._obj
        info.hwndActive = 2**45 + 1; info.hwndMenuOwner = 2**45 + 2
        info.hwndMoveSize = 2**45 + 3; info.hwndCaret = 2**45 + 4
        info.rcCaret.left, info.rcCaret.top = -100, -20
        return result


class RawCaptureRejectionTests(unittest.TestCase):
    def api(self, folder, captures=(CAPTURE, 0)):
        api = object.__new__(native.Windows); api.user = QueryBoundary(captures)
        api.evidence_output = Path(folder).resolve(); api.evidence_case = 'owned-case'
        return api

    def reject(self, api):
        with self.assertRaisesRegex(AssertionError, MESSAGE) as caught:
            api.require_editor_focus(11, 33)
        return caught.exception

    def module(self):
        path = E2E / 'focus_rejection_diagnostics.py'
        self.assertTrue(path.is_file(), 'Raw capture rejection retention is missing')
        spec = importlib.util.spec_from_file_location('focus_rejection_diagnostics', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_exact_failing_gui_values_survive_without_second_query(self):
        with tempfile.TemporaryDirectory() as folder:
            api = self.api(folder); error = self.reject(api)
            self.assertEqual(ctypes.sizeof(native.GuiThreadInfo), 72)
            self.assertTrue(hasattr(error, 'opengeul_focus_rejection'), 'Same-call raw GUI evidence missing')
            row = error.opengeul_focus_rejection
            self.assertEqual(api.user.queries, [20])
            self.assertEqual(api.user.calls, ['foreground', 'root', 'thread', 'gui'])
            self.assertEqual(row['queriedThreadId'], 20)
            self.assertEqual(row['suiteHwnd'], 11); self.assertEqual(row['childHwnd'], 33)
            self.assertTrue(row['querySucceeded'])
            info = row['rawGuiThreadInfo']
            self.assertEqual(info['cbSize'], 72); self.assertEqual(info['flags'], 1)
            self.assertEqual(info['hwndCapture'], CAPTURE)
            self.assertEqual(info['hwndFocus'], 33)
            for key, value in [('hwndActive', 1), ('hwndMenuOwner', 2), ('hwndMoveSize', 3), ('hwndCaret', 4)]:
                self.assertEqual(info[key], 2**45 + value)
            self.assertEqual(info['caretRect'], [-100, -20, 3, 4])
            self.assertEqual(len(bytes.fromhex(row['rawGuiThreadInfoHex'])), 72)
            self.assertTrue(all(type(info[key]) is int for key in info if key != 'caretRect'))
            files = list(Path(folder).glob('owned-case-strict-editor-focus-rejection-*.json'))
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_bytes()), row)
            self.assertLessEqual(files[0].stat().st_size, 16384)
            self.assertNotIn('captureOwner', row); self.assertNotIn('creationTime', row)

    def test_same_primary_object_survives_secondary_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            api = self.api(folder); seen = []
            def broken(api, hwnd, child, thread, info, primary):
                seen.append(primary); raise OSError('secondary write failure')
            with mock.patch.dict(sys.modules, {'focus_rejection_diagnostics': NS(retain_capture_rejection=broken)}):
                error = self.reject(api)
            self.assertEqual(len(seen), 1)
            self.assertIs(error, seen[0]); self.assertEqual(str(error), MESSAGE)
            self.assertEqual(api.user.queries, [20])

    def test_capture_free_success_has_no_diagnostic_io_or_native_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            api = self.api(folder, captures=(0,)); calls = []
            with mock.patch.dict(sys.modules, {'focus_rejection_diagnostics': NS(retain_capture_rejection=lambda *args:calls.append(args))}), \
                    mock.patch.object(Path, 'open', side_effect=AssertionError('success performed I/O')):
                self.assertEqual(api.require_editor_focus(11, 33), 33)
            self.assertEqual(calls, []); self.assertEqual(list(Path(folder).iterdir()), [])
            self.assertEqual(api.user.calls, ['foreground', 'root', 'thread', 'gui'])
            self.assertEqual(api.user.queries, [20])

    def test_invalid_case_and_relative_output_preserve_raw_primary(self):
        for field, value in [('evidence_case', '../foreign'), ('evidence_case', 'x'*101),
                             ('evidence_output', Path('relative')), ('evidence_output', None)]:
            with self.subTest(field=field, value=str(value)), tempfile.TemporaryDirectory() as folder:
                api = self.api(folder); setattr(api, field, value); error = self.reject(api)
                self.assertTrue(hasattr(error, 'opengeul_focus_rejection'))
                self.assertEqual(error.opengeul_focus_rejection['rawGuiThreadInfo']['hwndCapture'], CAPTURE)
                self.assertEqual(list(Path(folder).iterdir()), []); self.assertEqual(api.user.queries, [20])

    def test_existing_exclusive_receipt_is_not_overwritten_or_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'owned-case-strict-editor-focus-rejection-000.json'
            target.write_bytes(b'original receipt')
            api = self.api(folder); error = self.reject(api)
            self.assertTrue(hasattr(error, 'opengeul_focus_rejection'))
            self.assertEqual(target.read_bytes(), b'original receipt')
            self.assertEqual(len(list(Path(folder).iterdir())), 1); self.assertEqual(api.user.queries, [20])

    def test_write_and_serialization_failures_never_replace_primary(self):
        module = self.module()
        for operation in ['write', 'json', 'copy']:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as folder:
                api = self.api(folder)
                if operation == 'write': patcher = mock.patch.object(Path, 'open', side_effect=OSError('write unavailable'))
                elif operation == 'json': patcher = mock.patch.object(module.json, 'dumps', side_effect=ValueError('encode unavailable'))
                else: patcher = mock.patch.object(module, 'copy_gui_thread_info', side_effect=RuntimeError('copy unavailable'))
                with mock.patch.dict(sys.modules, {'focus_rejection_diagnostics': module}), patcher:
                    error = self.reject(api)
                self.assertEqual(str(error), MESSAGE); self.assertEqual(api.user.queries, [20])
                if operation != 'copy': self.assertTrue(hasattr(error, 'opengeul_focus_rejection'))

    def test_sixty_four_receipts_are_finite_and_later_rejection_still_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            api = self.api(folder, captures=(CAPTURE,))
            for _ in range(65):
                error = self.reject(api)
                self.assertTrue(hasattr(error, 'opengeul_focus_rejection'))
                self.assertEqual(error.opengeul_focus_rejection['rawGuiThreadInfo']['hwndCapture'], CAPTURE)
            self.assertEqual(len(list(Path(folder).glob('*.json'))), 64)
            self.assertEqual(len(api.user.queries), 65)
            self.assertTrue(all(p.stat().st_size <= 16384 for p in Path(folder).glob('*.json')))

    def test_linked_output_does_not_write_into_another_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            api = self.api(folder); original = Path.is_symlink
            def linked(path):
                return path == api.evidence_output or original(path)
            with mock.patch.object(Path, 'is_symlink', linked):
                error = self.reject(api)
            self.assertTrue(hasattr(error, 'opengeul_focus_rejection'))
            self.assertEqual(error.opengeul_focus_rejection_error, 'AssertionError')
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == '__main__': unittest.main()
