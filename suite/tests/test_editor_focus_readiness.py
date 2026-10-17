"""Bounded focus observation must never replay input or accept foreign focus."""
import ctypes
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'windows_smoke.py'
spec = importlib.util.spec_from_file_location('suite_focus_native_smoke', SOURCE)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativeFocusFrames:
    """An external Win32 boundary with real GUIThreadInfo pointer writes."""
    def __init__(self, focuses, captures=(0,)):
        self.focuses = iter(focuses)
        self.captures = iter(captures)
        self.focus = 0
        self.capture = 0
        self.foreground = 11
        # hwnd: (PID, TID, GA_ROOT, native class)
        self.windows = {11: (100, 10, 11, 'Suite'), 22: (100, 10, 11, 'Panel'),
                        33: (200, 20, 11, 'SALFRAME'), 34: (200, 20, 11, 'SALSUBFRAME'),
                        35: (200, 20, 11, 'SAL-toolbar'), 44: (300, 30, 44, 'Foreign')}
        self.queries = []
        self.query_ok = True

    def IsWindow(self, hwnd): return hwnd in self.windows
    def GetAncestor(self, hwnd, flag): return self.windows.get(hwnd, (0, 0, 0, ''))[2]
    def GetForegroundWindow(self): return self.foreground
    def GetWindowThreadProcessId(self, hwnd, pointer):
        pid, tid, _, _ = self.windows.get(hwnd, (0, 0, 0, ''))
        if pointer is not None: pointer._obj.value = pid
        return tid
    def IsChild(self, parent, child):
        return (parent == 11 and child in (22, 33, 34, 35)) or (parent == 33 and child == 34)
    def GetGUIThreadInfo(self, tid, pointer):
        self.queries.append(tid)
        self.focus = next(self.focuses, self.focus)
        self.capture = next(self.captures, self.capture)
        if not self.query_ok: return False
        info = pointer._obj
        info.flags, info.hwndActive, info.hwndFocus = 1, 33, self.focus
        info.hwndCapture = self.capture
        info.hwndCaret, info.hwndMenuOwner = 34, 35
        info.rcCaret.left, info.rcCaret.top, info.rcCaret.right, info.rcCaret.bottom = 1, 2, 3, 4
        return True


class EditorFocusReadinessTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(native, 'prepare_editor_focus', None)),
                        'Single-input bounded editor focus readiness is missing')
        self.clock = 0
        self.record, self.inputs = {}, []

    def api(self, focuses, captures=(0,)):
        user = NativeFocusFrames(focuses, captures)
        api = object.__new__(native.Windows)
        api.user = user
        api.class_name = lambda hwnd: user.windows.get(hwnd, (0, 0, 0, ''))[3]
        return api

    def advance(self, seconds): self.clock += seconds

    def prepare(self, api, click=None, enter=None, seconds=.2):
        with mock.patch.object(native.time, 'monotonic', side_effect=lambda: self.clock), \
                mock.patch.object(native.time, 'sleep', side_effect=self.advance):
            return native.prepare_editor_focus(api, 11, 33, 100, 200, self.record,
                click or (lambda: self.inputs.append('click')),
                enter or (lambda: self.inputs.append('CTRL+F6')), seconds=seconds)

    def test_null_focus_transition_reaches_real_editor_without_repeating_input(self):
        api = self.api([0, 0, 0, 0, 34, 34])
        self.assertEqual(self.prepare(api), 34)
        self.assertEqual(self.inputs, ['click', 'CTRL+F6'])
        evidence = self.record['editorFocusReadiness']
        self.assertTrue(evidence['ready'])
        self.assertEqual(evidence['focusHwnd'], 34)
        self.assertEqual([row['phase'] for row in evidence['snapshots'][:3]],
                         ['before-click', 'after-click', 'after-control-f6'])
        self.assertEqual(evidence['snapshots'][0]['focus']['hwnd'], 0)
        last = evidence['snapshots'][-1]
        self.assertEqual(last['focus']['pid'], 200)
        self.assertEqual(last['focus']['threadId'], 20)
        self.assertEqual(last['focus']['className'], 'SALSUBFRAME')
        self.assertEqual(last['caretRect'], [1, 2, 3, 4])
        self.assertEqual(last['flags'], 1)
        self.assertEqual(last['cbSize'], ctypes.sizeof(native.GuiThreadInfo))
        self.assertEqual(last['caret']['hwnd'], 34)
        self.assertEqual(last['menuOwner']['hwnd'], 35)
        self.assertTrue(all(tid == 20 for tid in api.user.queries))

    def test_owned_setup_focus_is_pending_until_child_focus_exists(self):
        api = self.api([11, 35, 35, 33, 33])
        self.assertEqual(self.prepare(api), 33)
        self.assertEqual(self.inputs, ['click', 'CTRL+F6'])

    def test_editor_focus_with_mouse_capture_waits_without_repeating_input(self):
        api = self.api([0, 34, 34, 34, 34, 34], captures=[0, 33, 33, 33, 0, 0])
        self.assertEqual(self.prepare(api), 34)
        self.assertEqual(self.inputs, ['click', 'CTRL+F6'])
        evidence = self.record['editorFocusReadiness']
        self.assertEqual([row['capture']['hwnd'] for row in evidence['snapshots']], [0, 33, 33, 33, 0])
        self.assertEqual([row['phase'] for row in evidence['snapshots'][3:]], ['wait', 'wait'])
        self.assertEqual(evidence['deadlineSeconds'], .2)
        self.assertGreater(self.clock, 0)
        self.assertLessEqual(self.clock, .2)
        self.assertIs(native.require_editor_focus_readiness(evidence, 11, 33, 100, 200), evidence)

    def test_persistent_mouse_capture_times_out_with_editor_focus_and_original_input_count(self):
        api = self.api([34], captures=[33])
        with self.assertRaisesRegex(AssertionError, 'ready'):
            self.prepare(api)
        self.assertGreaterEqual(self.clock, .2)
        self.assertLessEqual(self.clock, .25)
        self.assertEqual(self.inputs, ['click', 'CTRL+F6'])
        evidence = self.record['editorFocusReadiness']
        self.assertFalse(evidence['ready'])
        self.assertTrue(all(row['focus']['hwnd'] == 34 and row['capture']['hwnd'] == 33
                            for row in evidence['snapshots']))

    def test_strict_before_input_guard_rejects_capture_reappearing_after_ready_snapshot(self):
        api = self.api([34], captures=[0, 0, 0, 33])
        with self.assertRaisesRegex(AssertionError, 'capture'):
            self.prepare(api)
        self.assertEqual(self.clock, 0)
        self.assertEqual(self.inputs, ['click', 'CTRL+F6'])
        self.assertFalse(self.record['editorFocusReadiness']['ready'])
        self.assertEqual(self.record['editorFocusReadiness']['snapshots'][-1]['capture']['hwnd'], 0)

    def test_foreign_focus_fails_immediately_without_more_input(self):
        api = self.api([0, 44, 34])
        with self.assertRaisesRegex(AssertionError, 'foreign.*focus'):
            self.prepare(api)
        self.assertEqual(self.inputs, ['click'])
        self.assertFalse(self.record['editorFocusReadiness']['ready'])
        self.assertEqual(self.record['editorFocusReadiness']['snapshots'][-1]['focus']['className'], 'Foreign')

    def test_foreign_foreground_after_one_key_is_not_polled_until_recovery(self):
        api = self.api([0, 0, 34])
        def enter():
            self.inputs.append('CTRL+F6')
            api.user.foreground = 44
        with self.assertRaisesRegex(AssertionError, 'foreground'):
            self.prepare(api, enter=enter)
        self.assertEqual(self.inputs, ['click', 'CTRL+F6'])
        self.assertEqual(self.clock, 0)

    def test_child_process_replacement_is_not_a_pending_focus_transition(self):
        api = self.api([0, 0])
        def click():
            self.inputs.append('click')
            api.user.windows[33] = (999, 20, 11, 'Recycled')
        with self.assertRaisesRegex(AssertionError, 'editor.*identity'):
            self.prepare(api, click=click)
        self.assertEqual(self.inputs, ['click'])
        self.assertEqual(api.user.queries, [20], 'A recycled foreign child must not be queried')

    def test_focus_descendant_in_another_process_is_rejected(self):
        api = self.api([0, 0, 34])
        api.user.windows[34] = (999, 20, 11, 'Foreign-embedded')
        with self.assertRaisesRegex(AssertionError, 'foreign.*focus'):
            self.prepare(api)

    def test_focus_descendant_in_another_thread_is_not_editor_readiness(self):
        api = self.api([0, 0, 34])
        api.user.windows[34] = (200, 21, 11, 'Other-office-thread')
        with self.assertRaisesRegex(AssertionError, 'focus.*thread'):
            self.prepare(api)

    def test_win64_gui_thread_info_layout_is_identical_on_replay_hosts(self):
        self.assertEqual(ctypes.sizeof(native.GuiThreadInfo), 72)
        self.assertEqual(native.GuiThreadInfo.hwndActive.offset, 8)
        self.assertEqual(native.GuiThreadInfo.rcCaret.offset, 56)

    def test_failed_native_query_clears_stale_error_before_observation(self):
        api = self.api([0])
        error = [123]
        def query(tid, pointer):
            self.assertEqual(error[0], 0, 'Stale binding error was not cleared before native query')
            error[0] = 5
            return False
        api.user.GetGUIThreadInfo = query
        with mock.patch.object(native.ctypes, 'get_last_error', side_effect=lambda: error[0], create=True), \
                mock.patch.object(native.ctypes, 'set_last_error', side_effect=lambda value: error.__setitem__(0, value), create=True):
            with self.assertRaisesRegex(OSError, 'GetGUIThreadInfo'):
                self.prepare(api)
        self.assertEqual(self.record['editorFocusReadiness']['snapshots'][0]['lastError'], 5)

    def test_receipt_replay_rejects_foreign_threads_query_errors_and_repeated_input(self):
        self.assertTrue(callable(getattr(native, 'require_editor_focus_readiness', None)),
                        'Same-source pure focus receipt validator is missing')
        self.prepare(self.api([0, 0, 34, 34]))
        evidence = self.record['editorFocusReadiness']
        self.assertIs(native.require_editor_focus_readiness(evidence, 11, 33, 100, 200), evidence)
        mutations = [lambda e: e.update(clickAttempts=2), lambda e: e.update(controlF6Attempts=2),
                     lambda e: e.update(clickAttempts=True),
                     lambda e: e.update(controlF6Completed=False), lambda e: e.update(editorThreadId=99),
                     lambda e: e.update(deadlineSeconds=100), lambda e: e.update(ready=False),
                     lambda e: e['snapshots'][0].update(elapsedSeconds=-.5),
                     lambda e: e.update(pollStartedSeconds=999),
                     lambda e: e['snapshots'][-1].update(cbSize=96),
                     lambda e: e['snapshots'][-1].update(queriedThreadId=99),
                     lambda e: e['snapshots'][-1].update(querySucceeded=False),
                     lambda e: e['snapshots'][-1].update(lastError=5),
                     lambda e: e['snapshots'][-1]['capture'].update(hwnd=33),
                     lambda e: e['snapshots'][-1]['capture'].update(hwnd=False),
                     lambda e: e['snapshots'][-1]['focus'].update(threadId=99),
                     lambda e: e['snapshots'][-1]['focus'].update(pid=999),
                     lambda e: e['snapshots'][-1]['after']['foreground'].update(rootHwnd=44)]
        for mutate in mutations:
            changed = copy.deepcopy(evidence)
            mutate(changed)
            with self.subTest(mutation=mutate), self.assertRaises((AssertionError, OSError)):
                native.require_editor_focus_readiness(changed, 11, 33, 100, 200)

    def test_owned_editor_detached_from_suite_is_rejected(self):
        api = self.api([0])
        api.user.windows[33] = (200, 20, 33, 'SALFRAME')
        with self.assertRaisesRegex(AssertionError, 'editor.*identity'):
            self.prepare(api)
        self.assertEqual(self.inputs, [])

    def test_dead_child_is_rejected_before_any_input(self):
        api = self.api([0])
        del api.user.windows[33]
        with self.assertRaisesRegex(AssertionError, 'editor.*identity'):
            self.prepare(api)
        self.assertEqual(api.user.queries, [])
        self.assertEqual(self.inputs, [])

    def test_zero_child_thread_never_queries_implicit_foreground_thread(self):
        api = self.api([0])
        api.user.windows[33] = (200, 0, 11, 'SALFRAME')
        with self.assertRaisesRegex(AssertionError, 'editor.*identity'):
            self.prepare(api)
        self.assertEqual(api.user.queries, [])

    def test_final_strict_guard_also_refuses_implicit_thread_zero(self):
        api = self.api([34])
        api.user.windows[33] = (200, 0, 11, 'SALFRAME')
        with self.assertRaisesRegex(AssertionError, 'thread'):
            api.require_editor_focus(11, 33)
        self.assertEqual(api.user.queries, [])

    def test_gui_thread_query_error_retains_error_and_does_not_retry(self):
        api = self.api([0])
        api.user.query_ok = False
        with mock.patch.object(native.ctypes, 'get_last_error', return_value=5, create=True):
            with self.assertRaisesRegex(OSError, 'GetGUIThreadInfo'):
                self.prepare(api)
        snapshot = self.record['editorFocusReadiness']['snapshots'][-1]
        self.assertFalse(snapshot['querySucceeded'])
        self.assertEqual(snapshot['lastError'], 5)
        self.assertEqual(self.inputs, [])
        self.assertEqual(api.user.queries, [20])

    def test_foreground_change_during_query_fails_with_both_observations(self):
        api = self.api([0])
        query = api.user.GetGUIThreadInfo
        def change(tid, pointer):
            result = query(tid, pointer)
            api.user.foreground = 44
            return result
        api.user.GetGUIThreadInfo = change
        with self.assertRaisesRegex(AssertionError, 'foreground'):
            self.prepare(api)
        snapshot = self.record['editorFocusReadiness']['snapshots'][-1]
        self.assertEqual(snapshot['before']['foreground']['hwnd'], 11)
        self.assertEqual(snapshot['after']['foreground']['hwnd'], 44)
        self.assertEqual(self.inputs, [])

    def test_timeout_preserves_pending_observations_and_never_replays_inputs(self):
        api = self.api([0])
        with self.assertRaisesRegex(AssertionError, 'focus.*ready'):
            self.prepare(api)
        self.assertGreaterEqual(self.clock, .2)
        self.assertLessEqual(self.clock, .25)
        self.assertEqual(self.inputs, ['click', 'CTRL+F6'])
        evidence = self.record['editorFocusReadiness']
        self.assertFalse(evidence['ready'])
        self.assertGreater(len(evidence['snapshots']), 3)
        self.assertTrue(all(row['focus']['hwnd'] == 0 for row in evidence['snapshots']))


if __name__ == '__main__': unittest.main()
