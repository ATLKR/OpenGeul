"""Typed native boundaries only; these tests do not claim Windows GUI proof."""
import ctypes
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'native_window_evidence.py'


class Function:
    def __init__(self, action=lambda *args: 1):
        self.action, self.calls = action, []

    def __call__(self, *args):
        self.calls.append(args)
        return self.action(*args)


class Library:
    def __getattr__(self, name):
        value = Function()
        setattr(self, name, value)
        return value


class NativeWindowEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(), 'missing physical pointer/census native boundary')
        spec = importlib.util.spec_from_file_location('native_window_evidence_tested', SOURCE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.user, self.shell = Library(), Library()
        self.taskbar, self.hit = 0x123456789, 0x234567890
        self.previous = 0x345678901
        self.context, self.cursor = [self.previous], [12, 34]
        def set_context(value):
            value = getattr(value, 'value', value)
            previous, self.context[0] = self.context[0], value
            return previous
        self.user.SetThreadDpiAwarenessContext.action = set_context
        self.user.GetThreadDpiAwarenessContext.action = lambda: self.context[0]
        self.user.AreDpiAwarenessContextsEqual.action = lambda left, right: left == right
        self.user.FindWindowW.action = lambda *args: self.taskbar
        def appbar(message, data):
            data._obj.rc = self.module.Rect(0, 1040, 1920, 1080)
            return 1
        self.shell.SHAppBarMessage.action = appbar
        def rect(hwnd, value):
            value._obj.left, value._obj.top = 0, 1040
            value._obj.right, value._obj.bottom = 1920, 1080
            return 1
        self.user.GetWindowRect.action = rect
        def get_cursor(point):
            point._obj.x, point._obj.y = self.cursor
            return 1
        self.user.GetPhysicalCursorPos.action = get_cursor
        self.user.SetPhysicalCursorPos.action = lambda x, y: self.cursor.__setitem__(slice(None), [x, y]) or 1
        self.user.WindowFromPhysicalPoint.action = lambda point: self.hit
        self.user.GetAncestor.action = lambda hwnd, flag: self.taskbar if flag == 2 else 0
        self.user.GetWindow.action = lambda *args: 0
        def pid(hwnd, value):
            value._obj.value = 88
            return 99
        self.user.GetWindowThreadProcessId.action = pid
        self.user.GetClassNameW.action = lambda hwnd, buffer, size: setattr(buffer, 'value', 'Shell_TrayWnd') or 13
        self.user.GetWindowTextW.action = lambda hwnd, buffer, size: setattr(buffer, 'value', '') or 0
        self.user.GetWindowLongPtrW.action = lambda hwnd, offset: 0x80000008
        self.user.GetForegroundWindow.action = lambda: 0
        self.probe = self.module.NativeWindowProbe(user=self.user, shell=self.shell)

    def test_structures_and_signatures_preserve_windows_widths_and_full_handles(self):
        self.assertEqual(8, ctypes.sizeof(self.module.Point))
        self.assertEqual(16, ctypes.sizeof(self.module.Rect))
        self.assertEqual(48 if ctypes.sizeof(ctypes.c_void_p) == 8 else 36,
                         ctypes.sizeof(self.module.AppBarData))
        self.assertEqual((ctypes.c_uint32, ctypes.POINTER(self.module.AppBarData)), self.shell.SHAppBarMessage.argtypes)
        self.assertIs(ctypes.c_size_t, self.shell.SHAppBarMessage.restype)
        self.assertIs(ctypes.c_void_p, self.user.FindWindowW.restype)
        self.assertIs(ctypes.c_ssize_t, self.user.GetWindowLongPtrW.restype)
        self.assertEqual((self.module.Point,), self.user.WindowFromPhysicalPoint.argtypes)

    def test_parks_once_at_verified_physical_taskbar_edge_and_restores_dpi(self):
        receipt = {}
        self.probe.park_pointer(receipt)
        self.assertEqual([960, 1079], receipt['chosenPhysicalPoint'])
        self.assertEqual(receipt['chosenPhysicalPoint'], receipt['readbackPhysicalPoint'])
        self.assertEqual(self.taskbar, receipt['taskbarHwnd'])
        self.assertEqual(self.taskbar, receipt['actualRootHwnd'])
        self.assertEqual(self.previous, receipt['previousDpiContext'])
        self.assertEqual(self.previous, receipt['restoredDpiContext'])
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(self.previous, self.context[0])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))
        self.assertEqual(2, len(self.user.SetThreadDpiAwarenessContext.calls))

    def test_failed_readback_restores_dpi_without_retry_or_launch_and_retains_receipt(self):
        self.user.SetPhysicalCursorPos.action = lambda x, y: 1  # Clipped/no movement.
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(self.module, 'NativeWindowProbe', return_value=self.probe):
                with self.assertRaisesRegex(AssertionError, 'physical cursor'):
                    self.module.prepare_launch_pointer(Path(directory), 'attempt-007')
            receipt = json.loads((Path(directory) / 'attempt-007-pointer.json').read_text())
        self.assertFalse(receipt['success'])
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(self.previous, self.context[0])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))
        self.assertIn('error', receipt)

    def test_foreign_physical_hit_is_a_precondition_failure_not_a_fallback(self):
        self.user.GetAncestor.action = lambda hwnd, flag: 777
        receipt = {}
        with self.assertRaisesRegex(AssertionError, 'taskbar'):
            self.probe.park_pointer(receipt)
        self.assertEqual(777, receipt['actualRootHwnd'])
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def test_missing_taskbar_fails_explicitly_and_still_restores_dpi(self):
        self.user.FindWindowW.action = lambda *args: 0
        receipt = {}
        with self.assertRaisesRegex(AssertionError, 'taskbar'):
            self.probe.park_pointer(receipt)
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual([], self.user.SetPhysicalCursorPos.calls)

    def test_census_keeps_every_snapshot_handle_and_query_errors(self):
        self.user.GetClassNameW.action = lambda *args: (_ for _ in ()).throw(OSError('class query denied'))
        census = self.probe.window_census([44, 55], 88)
        self.assertEqual([44, 55], [row['hwnd'] for row in census['windows']])
        for row in census['windows']:
            self.assertEqual(88, row['pid'])
            self.assertEqual(0x80000008, row['style'])
            self.assertEqual(0, row['ownerHwnd'])
            self.assertIn('className', [error['field'] for error in row['queryErrors']])


if __name__ == '__main__':
    unittest.main()
