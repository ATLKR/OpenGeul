"""Numeric-only diagnostics at the real native menu failure boundaries."""
import copy
import ctypes as C
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT, ROOT/'suite/tests', ROOT/'suite/e2e'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
import test_owned_native_menu as original_tests


class NativeBoundary:
    """Only the already-declared User32 boundary is synthetic."""
    def __init__(self, probe, clock):
        self.probe, self.clock = probe, clock
        self.calls = []
        self.after_deadline = 0
        self.expire_at = self.fail_at = self.pending_at = None
        self.foreground = 99
        self.owner_mode = 'owned'
        self.drift = self.foreground_changed = False
        self.gui_seen = False
        self.primary = OSError(5, 'Synthetic native diagnostic failure')

    def called(self, name):
        if self.clock() >= self.probe.deadline:
            self.after_deadline += 1
        self.calls.append(name)
        if len(self.calls) == self.pending_at:
            self.probe._msaa_lease = NS(pending=True)
        if len(self.calls) == self.expire_at:
            self.clock.now = self.probe.deadline
        if len(self.calls) == self.fail_at:
            raise self.primary

    def IsWindow(self, hwnd):
        self.called('IsWindow')
        return int(hwnd != 0)

    def GetWindowThreadProcessId(self, hwnd, output):
        self.called('GetWindowThreadProcessId')
        if not isinstance(output._obj, C.c_uint32):
            raise AssertionError('The real DWORD out parameter is required')
        shell = hwnd in (11, 55)
        output._obj.value = 77 if shell else 88
        if self.owner_mode == 'foreign' and hwnd == 100:
            output._obj.value = 999
        if self.drift and self.gui_seen and hwnd == 56:
            output._obj.value = 999
        return 7 if shell else 9

    def GetAncestor(self, hwnd, flag):
        self.called('GetAncestor')
        if flag != 2:
            raise AssertionError('Only the existing GA_ROOT declaration is used')
        return 11 if hwnd in (11, 55, 56) else hwnd

    def GetWindow(self, hwnd, flag):
        self.called('GetWindow')
        if flag != 4:
            raise AssertionError('Only the existing GW_OWNER declaration is used')
        if self.owner_mode == 'zero':
            return 0
        if self.owner_mode == 'cycle':
            return 100 if hwnd == 99 else 99
        if self.owner_mode == 'bound':
            return hwnd + 1
        return 100 if hwnd == 99 else 56

    def GetForegroundWindow(self):
        self.called('GetForegroundWindow')
        return 11 if self.foreground_changed and self.gui_seen else self.foreground

    def GetGUIThreadInfo(self, thread, output):
        self.called('GetGUIThreadInfo')
        if thread != 9 or output._obj.cbSize != C.sizeof(output._obj):
            raise AssertionError('The original engine GUI thread/layout is required')
        state = output._obj
        state.active = state.capture = state.menuOwner = 99
        state.focus = 56
        state.flags = 0x10
        self.gui_seen = True
        return 1

    def GetPropW(self, hwnd, name):
        self.called('GetPropW')
        if hwnd != 11 or name not in ('OpenGeul.Office.ParentHwnd', 'OpenGeul.Office.ChildHwnd'):
            raise AssertionError('Only the original numeric attachment exports are read')
        return 55 if name.endswith('ParentHwnd') else 56

    def IsChild(self, parent, child):
        self.called('IsChild')
        return int((parent, child) in ((11, 55), (55, 56)))


class FocusBoundaryDiagnosticTests(unittest.TestCase):
    def fixture(self):
        owner = original_tests.OwnedNativeMenuTests(methodName='test_root_com_failure_retains_numeric_hresult_without_exception_text')
        self.addCleanup(owner.doCleanups)
        m, api, process, record, clock, boundary = owner.real_chrome_fixture()
        probe = boundary.probe
        binding = dict(document=11, parent=55, child=56, officePid=88)
        probe.begin_identity_scope(binding, boundary.native.shell, boundary.native.engine,
            clock(), probe.deadline, 'keyboard-escape', True)
        probe._identity_refs = {'file': boundary.Node('file'), 'bar': boundary.Node('bar'),
            'peer': boundary.Node('peer'), 'contrast-edit': boundary.Node('edit'),
            'target:save': boundary.Node('save')}
        probe.file_element = probe._identity_refs['file']
        probe.menu_bar_element = probe._identity_refs['bar']
        probe._uses_comparison = True
        attachment = dict(valid=True, binding=dict(binding), exported=[55, 56], windows={
            role: dict(hwnd=hwnd, pid=pid, threadId=tid, rootHwnd=11)
            for role, hwnd, pid, tid in (('document', 11, 77, 7), ('parent', 55, 77, 7), ('child', 56, 88, 9))})
        probe.attachment_snapshot = lambda value: copy.deepcopy(attachment)
        probe.bind_menu_classification(m._menu_scope(binding, boundary.native.shell,
            boundary.native.engine, clock(), probe.deadline), lambda: None)
        native = NativeBoundary(probe, clock)
        for name in ('IsWindow', 'GetWindowThreadProcessId', 'GetAncestor', 'GetWindow',
                'GetForegroundWindow', 'GetGUIThreadInfo', 'GetPropW', 'IsChild'):
            setattr(probe.user, name, getattr(native, name))
        return m, probe, boundary, clock, binding, attachment, native

    def collect(self, probe, binding, attachment, native, foreground=99):
        helper = getattr(probe, '_observe_physical_foreground_mismatch', None)
        self.assertTrue(callable(helper), 'The original mismatch lacks a bounded numeric observation')
        observation = {}
        helper(binding, attachment, attachment['windows']['child'], foreground, observation)
        self.assertIn('foregroundMismatch', observation)
        return observation['foregroundMismatch']

    def test_post_refresh_mismatch_keeps_assertion_and_primary_while_recording_native_owner(self):
        m, p, b, clock, binding, attachment, native = self.fixture()
        calls = []
        marker = {}
        class NoProviderAccess:
            def __getattribute__(self, name):
                raise AssertionError('A native diagnostic must not enter the UIA provider')
        def foreground():
            calls.append(1)
            if len(calls) == 1:
                return 11
            marker['last'] = p.interop.get('lastCall')
            marker['exception'] = getattr(p, '_last_call_exception', None)
            p.provider_client = NoProviderAccess()
            return 99
        p.foreground = foreground
        with self.assertRaisesRegex(AssertionError, 'Physical File header requires its original foreground document'):
            p._physical_base()
        self.assertIn('foregroundMismatch', p.interop['graphRefresh'])
        row = p.interop['graphRefresh']['foregroundMismatch']
        self.assertEqual((row['statusCode'], row['bindingBefore'], row['bindingAfter'], row['foregroundSame']), (2, 1, 1, 1))
        self.assertEqual(row['ownerStopCode'], 2)
        self.assertEqual([item['hwnd'] for item in row['owners']], [99, 100])
        self.assertEqual((row['engineGui']['flags'], row['engineGui']['captureHwnd'], row['engineGui']['menuOwnerHwnd']), (16, 99, 99))
        self.assertEqual(row['popupQualified'], 0)
        self.assertIs(p.interop['lastCall'], marker['last'])
        self.assertIs(getattr(p, '_last_call_exception', None), marker['exception'])
        self.assertEqual(native.after_deadline, 0)

    def test_normal_physical_refresh_adds_no_native_diagnostic_calls(self):
        m, p, b, clock, binding, attachment, native = self.fixture()
        p.foreground = lambda: 11
        result = p._physical_base()
        self.assertIn('file', result)
        self.assertNotIn('foregroundMismatch', p.interop['graphRefresh'])
        # Existing physical hit PID/root calls are not new diagnostic calls.
        self.assertEqual(native.calls, ['GetWindowThreadProcessId', 'GetAncestor'])

    def test_owner_zero_cycle_foreign_and_cap_remain_partial_never_popup_permission(self):
        for mode, stop, count in (('zero', 1, 1), ('cycle', 3, 2), ('foreign', 5, 2), ('bound', 4, 16)):
            with self.subTest(mode=mode):
                _, p, _, _, binding, attachment, native = self.fixture()
                native.owner_mode = mode
                row = self.collect(p, binding, attachment, native)
                self.assertEqual((row['ownerStopCode'], len(row['owners'])), (stop, count))
                self.assertEqual((row['knownPartial'], row['popupQualified']), (1, 0))

    def test_binding_change_and_foreground_change_cannot_certify_same_observation(self):
        for mode in ('binding', 'foreground'):
            with self.subTest(mode=mode):
                _, p, _, _, binding, attachment, native = self.fixture()
                native.drift = mode == 'binding'
                native.foreground_changed = mode == 'foreground'
                row = self.collect(p, binding, attachment, native)
                self.assertNotEqual(row['statusCode'], 2)
                self.assertEqual((row['knownPartial'], row['popupQualified']), (1, 0))

    def test_pending_or_expiry_blocks_every_following_native_call(self):
        _, p, _, clock, binding, attachment, native = self.fixture()
        row = self.collect(p, binding, attachment, native)
        total = len(native.calls)
        self.assertGreater(total, 0)
        for mode in ('expired-before', 'pending-before'):
            with self.subTest(mode=mode):
                _, p, _, clock, binding, attachment, native = self.fixture()
                if mode == 'expired-before': clock.now = p.deadline
                else: p._msaa_lease = NS(pending=True)
                row = self.collect(p, binding, attachment, native)
                self.assertEqual(native.calls, [])
                self.assertEqual(row['statusCode'], 1)
        for index in range(1, total + 1):
            for mode in ('late', 'pending'):
                with self.subTest(boundary=index, mode=mode):
                    _, p, _, _, binding, attachment, native = self.fixture()
                    if mode == 'late': native.expire_at = index
                    else: native.pending_at = index
                    row = self.collect(p, binding, attachment, native)
                    self.assertEqual(len(native.calls), index)
                    self.assertEqual(native.after_deadline, 0)
                    self.assertEqual(row['statusCode'], 1)
                    self.assertEqual((row['knownPartial'], row['popupQualified']), (1, 0))

    def test_native_failure_is_partial_without_overwriting_any_uia_call_record(self):
        _, p, _, _, binding, attachment, native = self.fixture()
        marker = dict(apiCode=7, hresult=-2146233083)
        original = RuntimeError()
        p.interop['lastCall'] = marker
        p.interop['primaryFailureCall'] = marker
        p._last_call_exception = original
        native.fail_at = 3
        row = self.collect(p, binding, attachment, native)
        self.assertEqual(len(native.calls), 3)
        self.assertEqual((row['statusCode'], row['knownPartial'], row['popupQualified']), (3, 1, 0))
        self.assertIs(p.interop['lastCall'], marker)
        self.assertIs(p.interop['primaryFailureCall'], marker)
        self.assertIs(p._last_call_exception, original)

    def test_original_file_com_error_never_enters_native_mismatch_diagnostic(self):
        _, p, b, _, _, _, native = self.fixture()
        p.foreground = lambda: 11
        class COMError(Exception):
            hresult = -2146233083
            def __str__(self): raise AssertionError('Exception text must not be read')
        primary = COMError()
        original = b.Node.CurrentNativeWindowHandle.fget
        attempts = []
        def handle(node):
            if node.key == 'file': attempts.append(1); raise primary
            return original(node)
        b.Node.CurrentNativeWindowHandle = property(handle)
        with self.assertRaises(COMError) as caught: p._physical_base()
        self.assertIs(caught.exception, primary)
        self.assertEqual(attempts, [1])
        self.assertEqual(native.calls, ['GetWindowThreadProcessId', 'GetAncestor'])
        self.assertNotIn('foregroundMismatch', p.interop['graphRefresh'])

    def test_new_records_contain_only_numbers_and_fixed_structure(self):
        _, p, _, _, binding, attachment, native = self.fixture()
        row = self.collect(p, binding, attachment, native)
        def numeric(value):
            if type(value) is dict:
                return all(type(key) is str and numeric(item) for key, item in value.items())
            if type(value) is list: return all(numeric(item) for item in value)
            return type(value) is int
        self.assertTrue(numeric(row))
        self.assertLess(len(json.dumps(row).encode()), 8192)

    def walk(self, *, ancestor=False, com_failure=False):
        m, p, b, clock, binding, attachment, native = self.fixture()
        initial = 'save' if ancestor else 'blank'
        p.uia.iuia.GetFocusedElement = lambda: b.Node(initial)
        parent = p.uia.iuia.ControlViewWalker.GetParentElement
        p.uia.iuia.ControlViewWalker.GetParentElement = lambda node: b.Node('blank') if node.key == 'save' else parent(node)
        primary = None
        if com_failure:
            class COMError(Exception):
                hresult = -2146233083
                def __str__(self): raise AssertionError('Exception text must not be read')
            primary = COMError()
            getter = b.Node.CurrentNativeWindowHandle.fget
            def handle(node):
                if node.key == 'blank': raise primary
                return getter(node)
            b.Node.CurrentNativeWindowHandle = property(handle)
        return m, p, b, clock, native, primary

    def test_first_failed_focus_reference_is_depth_zero_with_unobserved_properties(self):
        _, p, _, _, native, _ = self.walk()
        with self.assertRaises(AssertionError): p._focused_menu([{'runtimeId': []}, {'runtimeId': []}], 0, 1)
        self.assertIn('focusedWalk', p.interop)
        row = p.interop['focusedWalk']
        self.assertEqual((row['failed'], row['rows'][-1]['depth'], row['rows'][-1]['referencePhaseCode']), (1, 0, 1))
        self.assertEqual(row['rows'][-1]['observedMask'], 0)
        self.assertEqual(native.calls, [])

    def test_ancestor_failure_preserves_already_returned_first_cursor_properties(self):
        _, p, _, _, _, _ = self.walk(ancestor=True)
        with self.assertRaises(AssertionError): p._focused_menu([{'runtimeId': []}, {'runtimeId': []}], 0, 1)
        self.assertIn('focusedWalk', p.interop)
        rows = p.interop['focusedWalk']['rows']
        self.assertEqual([(r['depth'], r['referencePhaseCode']) for r in rows], [(0, 1), (1, 2)])
        self.assertEqual((rows[0]['observedMask'], rows[0]['pid'], rows[0]['kindCode'], rows[0]['visible'], rows[0]['enabled']), (15, 88, 50011, 1, 1))
        self.assertEqual(rows[1]['observedMask'], 0)

    def test_focused_walk_keeps_original_query_and_clock_sequence_and_com_exception(self):
        _, p, _, _, native, primary = self.walk(ancestor=True, com_failure=True)
        calls, ticks = [], [0]
        original_call, original_clock = p._uia_call, p.clock
        def observed(code, method, *args):
            calls.append(code)
            return original_call(code, method, *args)
        def counted(): ticks[0] += 1; return original_clock()
        p._uia_call, p.clock = observed, counted
        with self.assertRaises(type(primary)) as caught:
            p._focused_menu([{'runtimeId': []}, {'runtimeId': []}], 0, 1)
        self.assertIs(caught.exception, primary)
        # GetFocused, complete Save chrome, its two role tests, then the failing
        # ancestor HWND getter. No query may follow that original COM error.
        self.assertEqual(calls, [15, 7, 3, 5, 5, 5, 5, 5, 10, 9, 8, 11, 12, 5, 5, 7])
        # Sixteen UIA calls plus one parent call; the failed call has no post-clock.
        self.assertEqual(ticks[0], 33)
        self.assertEqual(native.calls, [])

    def test_failed_diagnostic_storage_cannot_replace_original_focus_com_error(self):
        _, p, _, _, native, primary = self.walk(ancestor=True, com_failure=True)
        class DiagnosticStore(dict):
            def __setitem__(self, key, value):
                if key == 'focusedWalk': raise KeyboardInterrupt()
                return super().__setitem__(key, value)
        p.interop = DiagnosticStore(p.interop)
        with self.assertRaises(type(primary)) as caught:
            p._focused_menu([{'runtimeId': []}, {'runtimeId': []}], 0, 1)
        self.assertIs(caught.exception, primary)
        self.assertEqual(native.calls, [])


if __name__ == '__main__':
    unittest.main()
