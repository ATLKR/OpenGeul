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


class Clock:
    def __init__(self):
        self.now = 100.
        self.pauses = []

    def __call__(self): return self.now

    def pause(self, seconds):
        self.pauses.append(seconds)
        self.now += seconds


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

    def timed_probe(self):
        clock = Clock()
        # Explicit dependency injection leaves every real receipt/guard active.
        self.probe.clock, self.probe.pause = clock, clock.pause
        return clock

    def readbacks(self, points):
        values = iter(points)
        last = [12, 34]
        def observe(pointer):
            last[:] = next(values, last)
            pointer._obj.x, pointer._obj.y = last
            return 1
        self.user.GetPhysicalCursorPos.action = observe
        self.user.SetPhysicalCursorPos.action = lambda x, y: 1

    def test_delayed_native_readback_requires_observed_exact_acknowledgment_after_one_move(self):
        clock = self.timed_probe()
        # The actual failure's shape: success from Set, first read still old.
        self.readbacks([[12, 34], [12, 34], [960, 1079], [960, 1079]])
        receipt = {}
        self.probe.park_pointer(receipt)
        self.assertEqual([960, 1079], receipt['readbackPhysicalPoint'])
        samples = receipt['physicalReadbacks']
        self.assertEqual(['acknowledgment', 'acknowledgment', 'final-confirmation'],
                         [row['phase'] for row in samples])
        self.assertEqual([[12, 34], [960, 1079], [960, 1079]], [row['point'] for row in samples])
        self.assertTrue(all(row['nativeReturn'] == 1 and row['lastError'] == 0 for row in samples))
        self.assertEqual(1, receipt['pointerMoveAttempts'])
        self.assertEqual(1, receipt['pointerMove']['nativeReturn'])
        self.assertEqual(0, receipt['pointerMove']['lastError'])
        self.assertLess(receipt['finishedAt'], receipt['readbackDeadline'])
        self.assertEqual([.01], clock.pauses)
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))
        self.assertEqual(self.previous, self.context[0])
        for name in ('SetCursorPos', 'ClipCursor', 'SetForegroundWindow', 'SendInput', 'mouse_event', 'SetCapture'):
            self.assertNotIn(name, vars(self.user))

    def test_never_matching_readback_is_bounded_fatal_and_restores_dpi_without_another_move(self):
        clock = self.timed_probe(); self.readbacks([[12, 34]])
        receipt = {}
        with self.assertRaisesRegex(AssertionError, 'physical cursor'):
            self.probe.park_pointer(receipt)
        self.assertLessEqual(len(receipt['physicalReadbacks']), 26)
        self.assertGreater(len(receipt['physicalReadbacks']), 1)
        self.assertLessEqual(clock.now, receipt['readbackDeadline'])
        self.assertTrue(all(0 < value <= .01 for value in clock.pauses))
        self.assertNotIn('actualPointHwnd', receipt)
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def test_exact_readback_returned_after_the_deadline_is_still_fatal(self):
        clock = self.timed_probe(); calls = [0]
        def observe(pointer):
            calls[0] += 1
            pointer._obj.x, pointer._obj.y = [12, 34] if calls[0] == 1 else [960, 1079]
            if calls[0] > 1: clock.now += .251
            return 1
        self.user.GetPhysicalCursorPos.action = observe
        receipt = {}
        with self.assertRaisesRegex(AssertionError, 'deadline'):
            self.probe.park_pointer(receipt)
        self.assertEqual([960, 1079], receipt['physicalReadbacks'][-1]['point'])
        self.assertGreater(receipt['physicalReadbacks'][-1]['finishedAt'], receipt['readbackDeadline'])
        self.assertNotIn('actualPointHwnd', receipt)
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def test_final_readback_drift_after_taskbar_queries_fails_without_reparking(self):
        self.timed_probe(); self.readbacks([[12, 34], [960, 1079], [14, 36]])
        receipt = {}
        with self.assertRaisesRegex(AssertionError, 'physical cursor'):
            self.probe.park_pointer(receipt)
        self.assertEqual('final-confirmation', receipt['physicalReadbacks'][-1]['phase'])
        self.assertEqual([14, 36], receipt['readbackPhysicalPoint'])
        self.assertEqual(self.taskbar, receipt['actualRootHwnd'])
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def test_earlier_absolute_deadline_caps_the_same_acknowledgment_budget(self):
        clock = self.timed_probe(); self.readbacks([[12, 34]])
        receipt = {}
        with self.assertRaises(AssertionError):
            self.probe.park_pointer(receipt, deadline=100.015)
        self.assertEqual(100.015, receipt['readbackDeadline'])
        self.assertLessEqual(clock.now, 100.015)
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def test_invalid_or_expired_deadline_never_moves_the_pointer(self):
        for deadline in (True, float('nan'), float('inf'), 100., 99.):
            with self.subTest(deadline=deadline):
                self.timed_probe()
                with self.assertRaises(AssertionError): self.probe.park_pointer({}, deadline=deadline)
        self.assertEqual([], self.user.SetPhysicalCursorPos.calls)

    def test_prelaunch_wrapper_forwards_earlier_deadline_and_retains_the_failed_acknowledgment(self):
        self.timed_probe(); self.readbacks([[12, 34]])
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(self.module, 'NativeWindowProbe', return_value=self.probe):
                with self.assertRaises(AssertionError):
                    self.module.prepare_launch_pointer(Path(directory), 'bounded-pointer', deadline=100.015)
            receipt = json.loads((Path(directory) / 'bounded-pointer-pointer.json').read_text())
        self.assertFalse(receipt['success'])
        self.assertEqual(100.015, receipt['callerDeadline'])
        self.assertEqual(100.015, receipt['readbackDeadline'])
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(1, receipt['pointerMoveAttempts'])
        self.assertLessEqual(len(receipt['physicalReadbacks']), 26)

    def test_native_read_query_error_retains_raw_return_and_restores_dpi(self):
        self.timed_probe(); calls = [0]
        def observe(pointer):
            calls[0] += 1
            pointer._obj.x, pointer._obj.y = [12, 34]
            return int(calls[0] == 1)
        self.user.GetPhysicalCursorPos.action = observe
        receipt = {}
        with self.assertRaises(OSError): self.probe.park_pointer(receipt)
        self.assertEqual(0, receipt['physicalReadbacks'][-1]['nativeReturn'])
        self.assertIsNone(receipt['physicalReadbacks'][-1]['point'])
        self.assertIn('error', receipt['physicalReadbacks'][-1])
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def test_same_taskbar_pid_with_a_changed_thread_is_not_the_retained_owner(self):
        self.timed_probe(); identities = [0]
        def identity(hwnd, pointer):
            identities[0] += 1; pointer._obj.value = 88
            return 99 if identities[0] == 1 else 100
        self.user.GetWindowThreadProcessId.action = identity
        receipt = {}
        with self.assertRaisesRegex(AssertionError, 'taskbar'):
            self.probe.park_pointer(receipt)
        self.assertEqual(100, receipt['freshTaskbar']['tid'])
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def test_replaced_primary_taskbar_after_acknowledgment_is_not_accepted(self):
        self.timed_probe(); finds = [0]
        def find(*args):
            finds[0] += 1
            return self.taskbar if finds[0] == 1 else self.taskbar + 1
        self.user.FindWindowW.action = find
        receipt = {}
        with self.assertRaisesRegex(AssertionError, 'taskbar'):
            self.probe.park_pointer(receipt)
        self.assertEqual(self.taskbar + 1, receipt['freshTaskbar']['hwnd'])
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def test_move_failure_retains_native_zero_and_never_samples_an_acknowledgment(self):
        self.timed_probe(); self.user.SetPhysicalCursorPos.action = lambda x, y: 0
        receipt = {}
        with self.assertRaises(OSError): self.probe.park_pointer(receipt)
        self.assertEqual(0, receipt['pointerMove']['nativeReturn'])
        self.assertEqual([], receipt['physicalReadbacks'])
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def test_native_query_exception_retains_unknown_return_and_preserves_cleanup(self):
        self.timed_probe(); calls = [0]
        def observe(pointer):
            calls[0] += 1
            if calls[0] > 1: raise OSError('native query exception')
            pointer._obj.x, pointer._obj.y = [12, 34]
            return 1
        self.user.GetPhysicalCursorPos.action = observe
        receipt = {}
        with self.assertRaisesRegex(OSError, 'native query exception'):
            self.probe.park_pointer(receipt)
        row = receipt['physicalReadbacks'][-1]
        self.assertIsNone(row['nativeReturn'])
        self.assertIn('native query exception', row['error'])
        self.assertLessEqual(row['startedAt'], row['finishedAt'])
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def test_dpi_restore_failure_stays_fatal_even_after_exact_pointer_confirmation(self):
        self.timed_probe(); original = self.user.SetThreadDpiAwarenessContext.action
        def context(value):
            if len(self.user.SetThreadDpiAwarenessContext.calls) == 2: return 0
            return original(value)
        self.user.SetThreadDpiAwarenessContext.action = context
        receipt = {}
        with self.assertRaises(OSError): self.probe.park_pointer(receipt)
        self.assertEqual([960, 1079], receipt['readbackPhysicalPoint'])
        self.assertFalse(receipt['dpiContextRestored'])
        self.assertEqual(0, receipt['dpiRestore']['nativeReturn'])
        self.assertLessEqual(receipt['dpiRestore']['startedAt'], receipt['dpiRestore']['finishedAt'])
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def test_late_dpi_restore_is_attempted_once_and_cannot_certify_success(self):
        clock = self.timed_probe(); original = self.user.SetThreadDpiAwarenessContext.action
        def context(value):
            result = original(value)
            if len(self.user.SetThreadDpiAwarenessContext.calls) == 2: clock.now += .251
            return result
        self.user.SetThreadDpiAwarenessContext.action = context
        receipt = {}
        with self.assertRaisesRegex(AssertionError, 'deadline'): self.probe.park_pointer(receipt)
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertGreater(receipt['finishedAt'], receipt['readbackDeadline'])
        self.assertEqual(2, len(self.user.SetThreadDpiAwarenessContext.calls))
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def transient_restore_clock_fault(self, receipt, fault):
        clock = self.timed_probe()
        injected = []
        def observe():
            if 'dpiRestore' in receipt and not injected:
                injected.append(True)
                if isinstance(fault, BaseException): raise fault
                return fault
            return clock()
        self.probe.clock = observe

    def assert_restore_clock_failure(self, fault, exception, message):
        receipt = {}
        self.transient_restore_clock_fault(receipt, fault)
        with self.assertRaisesRegex(exception, message): self.probe.park_pointer(receipt)
        self.assertIn(message, receipt['dpiRestore']['clockError'])
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertIsNone(receipt['dpiRestore']['startedAt'])
        self.assertEqual(100., receipt['dpiRestore']['finishedAt'])
        self.assertEqual(self.previous, self.context[0])
        self.assertEqual(2, len(self.user.SetThreadDpiAwarenessContext.calls))
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

    def test_transient_restore_start_clock_regression_stays_fatal_after_recovery(self):
        self.assert_restore_clock_failure(99., AssertionError, 'Pointer clock changed')

    def test_transient_restore_start_clock_nan_stays_fatal_after_recovery(self):
        self.assert_restore_clock_failure(float('nan'), AssertionError, 'Pointer clock changed')

    def test_transient_restore_start_clock_exception_stays_fatal_after_recovery(self):
        self.assert_restore_clock_failure(RuntimeError('clock unavailable'), RuntimeError, 'clock unavailable')

    def test_restore_start_clock_fault_preserves_an_existing_native_move_failure(self):
        receipt = {}
        self.transient_restore_clock_fault(receipt, RuntimeError('clock unavailable'))
        self.user.SetPhysicalCursorPos.action = lambda x, y: 0
        with self.assertRaisesRegex(OSError, 'SetPhysicalCursorPos failed'):
            self.probe.park_pointer(receipt)
        self.assertIn('SetPhysicalCursorPos failed', receipt['operationError'])
        self.assertIn('clock unavailable', receipt['dpiRestore']['clockError'])
        self.assertTrue(receipt['dpiContextRestored'])
        self.assertEqual(100., receipt['dpiRestore']['finishedAt'])
        self.assertEqual(self.previous, self.context[0])
        self.assertEqual(2, len(self.user.SetThreadDpiAwarenessContext.calls))
        self.assertEqual(1, len(self.user.SetPhysicalCursorPos.calls))

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
