"""Failure-only provenance: the first rejected row survives later cleanup guards."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'ascii_message_windows.py'


class AsciiRejectedValidationTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(SOURCE.parent))
        self.addCleanup(lambda: sys.path.remove(str(SOURCE.parent)))
        spec = importlib.util.spec_from_file_location('rejected_validation_windows', SOURCE)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.native = self.m.NativeAsciiProbe.__new__(self.m.NativeAsciiProbe)
        self.native.receipt = {}

    def row(self):
        return {'shell': {'pid': 2180, 'creationTime': 134372214435591757,
                         'handleValue': 0xffffffffffffffff, 'waitResult': 258,
                         'image': 'C:\\한글\\OpenGeul.Office.exe'},
                'engine': {'pid': 3624, 'creationTime': 134372214491063275},
                'scope': {'before': {'foreground': {'hwnd': 67482, 'pid': 3488}},
                          'after': {'foreground': {'hwnd': 67482, 'pid': 3488}},
                          'focusWithinEditor': False, 'caretRect': [-2147483648, 0, 0, 2147483647]},
                'keyboard': {'keysDown': [], 'capsLockOn': False},
                'optional': None, 'finite': -0.0}

    def reject(self, row, primary=None):
        if primary is None:
            primary = AssertionError('original strict foreground rejection')
        original = Mock(side_effect=primary)
        with patch.object(self.m.CountedEditorShortcuts, '_validate_guard', original):
            try:
                self.native._validate_guard(row)
            except BaseException as actual:
                self.assertIs(actual, primary)
            else:
                self.fail('Original validation rejection was suppressed')
        original.assert_called_once_with(self.native, row)
        return self.native.receipt['firstRejectedValidation']

    def test_success_delegates_once_returns_unchanged_and_creates_no_failure_fields(self):
        row = self.row()
        expected = object()
        with patch.object(self.m.CountedEditorShortcuts, '_validate_guard', return_value=expected) as original:
            with patch.object(self.m, '_copy_rejected_validation_row', create=True,
                              side_effect=AssertionError('copy on success')):
                self.assertIs(self.native._validate_guard(row), expected)
        original.assert_called_once_with(self.native, row)
        self.assertEqual({}, self.native.receipt)
        self.assertFalse(hasattr(self.native, '_first_rejected_validation_attempted'))

    def test_first_exact_native_row_detaches_and_later_cleanup_cannot_overwrite_it(self):
        row = self.row()
        expected = copy.deepcopy(row)
        captured = self.reject(row)
        self.assertTrue(captured['rowRetained'])
        self.assertEqual(expected, captured['row'])
        self.assertIsNot(row, captured['row'])
        self.assertIsNot(row['scope'], captured['row']['scope'])
        row['scope']['before']['foreground']['pid'] = 9999
        row['scope']['caretRect'].append(9)
        self.native.receipt['lastGuardObservation'] = {'cleanup': True}
        with patch.object(self.m, '_copy_rejected_validation_row', side_effect=AssertionError('second copy')):
            again = self.reject({'different': 'cleanup rejected scope'})
        self.assertIs(captured, again)
        self.assertEqual(expected, captured['row'])
        self.assertNotIn('primaryFailure', captured)
        self.assertIn('may-be-cleanup-after-earlier-error', captured['provenance'])

    def test_original_baseexceptions_identity_and_unprintable_errors_survive(self):
        class Unprintable(BaseException):
            def __str__(self): raise AssertionError('must not format primary')
        for primary in [AssertionError('strict'), KeyboardInterrupt(), SystemExit(9), Unprintable()]:
            with self.subTest(kind=type(primary).__name__):
                self.native = self.m.NativeAsciiProbe.__new__(self.m.NativeAsciiProbe)
                self.native.receipt = {}
                self.assertTrue(self.reject(self.row(), primary)['rowRetained'])

    def test_copy_baseexception_marks_once_and_never_replaces_original_error(self):
        with patch.object(self.m, '_copy_rejected_validation_row', create=True,
                          side_effect=KeyboardInterrupt()) as copier:
            captured = self.reject(self.row())
            again = self.reject({'later': 'cleanup'})
        self.assertIs(captured, again)
        self.assertFalse(captured['rowRetained'])
        self.assertNotIn('row', captured)
        self.assertEqual('bounded-primitive-copy-unavailable', captured['unretainedReason'])
        self.assertEqual(1, copier.call_count)
        self.assertTrue(self.native._first_rejected_validation_attempted)

    def test_receipt_write_failure_preserves_primary_and_attempt_sentinel(self):
        class BrokenReceipt(dict):
            def __setitem__(self, key, value): raise SystemExit(17)
        self.native.receipt = BrokenReceipt()
        primary = KeyboardInterrupt()
        original = Mock(side_effect=primary)
        with patch.object(self.m.CountedEditorShortcuts, '_validate_guard', original):
            with patch.object(self.m, '_copy_rejected_validation_row', create=True) as copier:
                for _ in range(2):
                    try: self.native._validate_guard(self.row())
                    except BaseException as actual: self.assertIs(actual, primary)
                    else: self.fail('Lost primary exception')
        self.assertEqual(2, original.call_count)
        self.assertEqual(0, copier.call_count)
        self.assertTrue(self.native._first_rejected_validation_attempted)

    def test_first_rejection_during_real_observer_cleanup_is_not_labelled_primary(self):
        from ascii_message_observer import OwnedAsciiObserver
        primary = ValueError('earlier non-guard error')
        observer = OwnedAsciiObserver(None, None, {}, {}, {}, 10., clock=lambda: 1.)
        self.native.receipt = observer.receipt
        observer.target = {'pid': 3624, 'tid': 4012, 'hwnd': 2884650, 'layout': 0x04090409}
        def guard():
            self.native._validate_guard(self.row())
            return dict(observer.target)
        close = Mock(return_value={'controllerResourcesReleased': True, 'engineHandleReleased': True})
        observer.probe = SimpleNamespace(can_stop=lambda: True, guard=guard, close=close,
                                         stop=Mock(side_effect=AssertionError('must not stop after reject')))
        observer.active = True
        with patch.object(self.m.CountedEditorShortcuts, '_validate_guard', side_effect=AssertionError('cleanup reject')):
            observer._close(primary)
        self.assertEqual('ValueError: earlier non-guard error', observer.receipt['error'])
        self.assertEqual(['AssertionError: cleanup reject'], observer.receipt['cleanupErrors'])
        self.assertTrue(observer.receipt['firstRejectedValidation']['rowRetained'])
        self.assertIn('may-be-cleanup-after-earlier-error', observer.receipt['firstRejectedValidation']['provenance'])
        self.assertNotIn('primaryFailure', observer.receipt['firstRejectedValidation'])
        close.assert_called_once_with()
        observer.probe.stop.assert_not_called()

    def test_bad_types_cycles_and_huge_rows_fail_bounded_without_magic_or_truncation(self):
        calls = []
        class Hostile:
            def __repr__(self): calls.append('repr'); raise KeyboardInterrupt()
            def __str__(self): calls.append('str'); raise KeyboardInterrupt()
            def __iter__(self): calls.append('iter'); raise KeyboardInterrupt()
            def __deepcopy__(self, memo): calls.append('deepcopy'); raise KeyboardInterrupt()
        class ListSubclass(list):
            def __iter__(self): calls.append('subclass-iter'); raise KeyboardInterrupt()
        class HostileMeta(type):
            def __eq__(self, other): calls.append('metaclass-equality'); raise KeyboardInterrupt()
        class MetaclassValue(metaclass=HostileMeta): pass
        cycle = {}; cycle['self'] = cycle
        deep = {}; cursor = deep
        for _ in range(30): cursor['next'] = {}; cursor = cursor['next']
        huge = {'image': 'x' * (1024 * 1024)}
        for row in [{'value': Hostile()}, {'value': ListSubclass()}, {'value': MetaclassValue()}, cycle, deep, huge,
                    {'big': 1 << 8192}, {'badFloat': float('nan')}, {'badFloat': float('inf')},
                    {'items': [None] * 10000}, {1: 'nonstr-key'}, {'value': b'bytes'},
                    {'value': (1, 2)}, {'value': '\ud800'}]:
            self.native = self.m.NativeAsciiProbe.__new__(self.m.NativeAsciiProbe)
            self.native.receipt = {}
            captured = self.reject(row)
            self.assertFalse(captured['rowRetained'])
            self.assertNotIn('row', captured)
            self.assertEqual('bounded-primitive-copy-unavailable', captured['unretainedReason'])
        self.assertEqual([], calls)

    def test_copy_limits_cover_structure_native_width_and_encoded_extent(self):
        row = {'keys': [None, True, False, -9223372036854775808, 18446744073709551615,
                        -1.7976931348623157e308, 1.7976931348623157e308, -0.0],
               'image': 'C:\\한글\\x\n\t"' + chr(0) * 40}
        copied = self.m._copy_rejected_validation_row(row)
        self.assertEqual(row, copied)
        self.assertEqual(type(row['keys']), type(copied['keys']))
        self.assertLessEqual(len(json.dumps(copied, ensure_ascii=False, separators=(',', ':')).encode()),
                             self.m.REJECTED_VALIDATION_MAX_BYTES)
        for row in [{'many': ['x'] * self.m.REJECTED_VALIDATION_MAX_NODES},
                    {'escaped': chr(0) * self.m.REJECTED_VALIDATION_MAX_BYTES},
                    {'nonascii': '한' * self.m.REJECTED_VALIDATION_MAX_BYTES}]:
            with self.assertRaises(ValueError): self.m._copy_rejected_validation_row(row)

    def test_original_real_validator_native_call_sequence_is_unchanged(self):
        shell = {'pid': 5}; engine = {'pid': 7}
        suite = {'hwnd': 10, 'isWindow': True, 'pid': 5, 'threadId': 3, 'rootHwnd': 10}
        editor = {'hwnd': 12, 'isWindow': True, 'pid': 7, 'threadId': 9, 'rootHwnd': 10}
        row = {'shell': shell, 'engine': engine,
               'scope': {'before': {'suite': suite, 'editor': editor, 'foreground': suite, 'editorWithinSuite': True},
                         'after': {'suite': suite, 'editor': editor, 'foreground': suite, 'editorWithinSuite': True},
                         'queriedThreadId': 9, 'cbSize': 72, 'queryAttempted': True,
                         'querySucceeded': True, 'lastError': 0, 'focus': editor,
                         'focusWithinEditor': True, 'capture': {'hwnd': 0},
                         'parent': {'hwnd': 11, 'pid': 5, 'rootHwnd': 10, 'isWindow': True},
                         **dict.fromkeys(['suiteOwnsParent','parentOwnsChild','parentVisible','parentEnabled',
                                          'childVisible','childEnabled'], True)},
               'keyboard': {'targetLayout': 0x04090409, 'currentThreadLayout': 0x04090409,
                            'keysDown': [], 'capsLockOn': False, 'scrollLockOn': False, 'numLockOn': False}}
        def target():
            probe = self.m.NativeAsciiProbe.__new__(self.m.NativeAsciiProbe)
            probe.receipt = {}; probe.original_shell = shell; probe.original_engine = engine
            probe.binding = dict(suiteHwnd=10, childHwnd=12, parentHwnd=11, shellPid=5, officePid=7)
            probe.thread = probe.lock_state = None
            calls = []
            probe._budget = lambda: calls.append('original-budget')
            probe.api = SimpleNamespace(require_foreground=lambda hwnd: calls.append(('original-foreground', hwnd)))
            return probe, calls
        baseline, baseline_calls = target()
        wrapped, wrapped_calls = target()
        self.m.CountedEditorShortcuts._validate_guard(baseline, row)
        with patch.object(self.m, '_copy_rejected_validation_row', create=True,
                          side_effect=AssertionError('unexpected success-path copy')):
            wrapped._validate_guard(row)
        self.assertEqual(baseline_calls, wrapped_calls)
        self.assertEqual(['original-budget', ('original-foreground', 10), 'original-budget'], wrapped_calls)
        self.assertEqual(baseline.thread, wrapped.thread)
        self.assertEqual(baseline.lock_state, wrapped.lock_state)
        self.assertEqual({}, wrapped.receipt)


if __name__ == '__main__': unittest.main()
