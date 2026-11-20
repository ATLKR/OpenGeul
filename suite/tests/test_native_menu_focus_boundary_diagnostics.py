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
        self.classes = {99: 'SALTMPSUBFRAME'}
        self.roots = {}
        self.class_count = 0
        self.class_mutation = self.kernel_mutation = None
        self.class_result = None
        self.engine_pid, self.engine_birth, self.engine_wait = 88, 200, 258
        self.times_succeeded = 1
        self.identity_drift = {}
        self.owner_drift = {}
        self.thread_drift = {}
        self.final_root_mutation = None
        self.final_root_pending = False

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
        if hwnd in self.identity_drift:
            output._obj.value = self.identity_drift[hwnd]
        return self.thread_drift.get(hwnd, 7 if shell else 9)

    def GetAncestor(self, hwnd, flag):
        self.called('GetAncestor')
        if flag != 2:
            raise AssertionError('Only the existing GA_ROOT declaration is used')
        result = self.roots.get(hwnd, 11 if hwnd in (11, 55, 56) else hwnd)
        if self.final_root_pending and hwnd == self.foreground:
            self.final_root_pending = False
            if self.final_root_mutation is not None: self.final_root_mutation()
        return result

    def GetWindow(self, hwnd, flag):
        self.called('GetWindow')
        if flag != 4:
            raise AssertionError('Only the existing GW_OWNER declaration is used')
        if hwnd in self.owner_drift:
            return self.owner_drift[hwnd]
        if self.owner_mode == 'zero':
            return 0
        if self.owner_mode == 'cycle':
            return 100 if hwnd == 99 else 99
        if self.owner_mode == 'bound':
            return hwnd + 1
        return 100 if hwnd == 99 else 56

    def GetForegroundWindow(self):
        self.called('GetForegroundWindow')
        if self.gui_seen: self.final_root_pending = True
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

    def GetClassNameW(self, hwnd, output, size):
        self.called('GetClassNameW')
        if not isinstance(output, C.Array) or output._type_ is not C.c_wchar or size != len(output):
            raise AssertionError('The existing WCHAR buffer declaration is required')
        self.class_count += 1
        output.value = self.classes.get(hwnd, 'SYNTHETIC-UNKNOWN')
        if self.class_mutation is not None:
            self.class_mutation(hwnd)
        return len(output.value) if self.class_result is None else self.class_result

    def GetProcessId(self, handle):
        self.called('GetProcessId')
        if handle != 9: raise AssertionError('Only the original borrowed engine HANDLE is permitted')
        if self.kernel_mutation is not None: self.kernel_mutation('GetProcessId')
        return self.engine_pid

    def GetProcessTimes(self, handle, *outputs):
        self.called('GetProcessTimes')
        from suite_window_activation import FileTime
        if handle != 9 or len(outputs) != 4 or any(type(p._obj) is not FileTime for p in outputs):
            raise AssertionError('The existing HANDLE and four FILETIME outputs are required')
        outputs[0]._obj.low = self.engine_birth & 0xffffffff
        outputs[0]._obj.high = self.engine_birth >> 32
        if self.kernel_mutation is not None: self.kernel_mutation('GetProcessTimes')
        return self.times_succeeded

    def WaitForSingleObject(self, handle, timeout):
        self.called('WaitForSingleObject')
        if (handle, timeout) != (9, 0):
            raise AssertionError('Only a zero-duration wait on the original engine HANDLE is permitted')
        if self.kernel_mutation is not None: self.kernel_mutation('WaitForSingleObject')
        return self.engine_wait


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
                'GetForegroundWindow', 'GetGUIThreadInfo', 'GetPropW', 'IsChild', 'GetClassNameW'):
            setattr(probe.user, name, getattr(native, name))
        probe.kernel = NS(**{name: getattr(native, name) for name in
            ('GetProcessId', 'GetProcessTimes', 'WaitForSingleObject')})
        return m, probe, boundary, clock, binding, attachment, native

    def source_fixture(self):
        values = self.fixture()
        m, p, b, clock, binding, attachment, native = values
        p.source_selection = p._source_bound_selection = object()
        p._native_point_profile_version = 4
        p._native_identity_diagnostic = 0
        p._source_generation_binding = m._source_generation(binding, b.native.shell, b.native.engine, 9)
        p._point_source = dict(shellHandle=8, engineHandle=9)
        return values

    def facts(self, row):
        self.assertIn('boundaryFacts', row)
        value = row['boundaryFacts']
        self.assertEqual(set(value), {'schemaVersion', 'diagnosticOnly', 'acceptanceEligible',
            'foregroundClassKnown', 'foregroundClassCode', 'rootClassKnown', 'rootClassCode',
            'sourceMatched', 'engineIdentityKnown', 'engineWaitKnown', 'engineWaitResult'})
        self.assertTrue(all(type(v) is int for v in value.values()))
        self.assertEqual((value['schemaVersion'], value['diagnosticOnly'], value['acceptanceEligible']), (1, 1, 0))
        return value

    def test_boundary_facts_classifies_only_exact_fixed_classes_and_reads_same_hwnd_once(self):
        names = ('SALFRAME', 'SALTMPSUBFRAME', '#32770', 'ConsoleWindowClass',
            'Windows.UI.Core.CoreWindow', 'ApplicationFrameWindow', 'Tauri Window')
        for code, name in enumerate(names, 1):
            with self.subTest(code=code):
                _, p, _, _, binding, attachment, native = self.source_fixture()
                native.classes[99] = name
                facts = self.facts(self.collect(p, binding, attachment, native))
                self.assertEqual((facts['foregroundClassKnown'], facts['foregroundClassCode']), (1, code))
                self.assertEqual((facts['rootClassKnown'], facts['rootClassCode']), (1, code))
                self.assertEqual(native.class_count, 1)
                self.assertEqual((facts['sourceMatched'], facts['engineIdentityKnown'],
                    facts['engineWaitKnown'], facts['engineWaitResult']), (1, 1, 1, 258))

    def test_raw_and_root_class_are_separate_and_hwnd_pid_namespace_is_not_mixed(self):
        _, p, _, _, binding, attachment, native = self.source_fixture()
        native.foreground = 91; native.roots[91] = 99
        native.classes.update({91: '#32770', 99: 'SALFRAME'})
        facts = self.facts(self.collect(p, binding, attachment, native))
        self.assertEqual((facts['foregroundClassCode'], facts['rootClassCode'], native.class_count), (3, 1, 2))
        _, p, _, _, binding, attachment, native = self.source_fixture()
        native.foreground = 88; native.classes[88] = 'SALTMPSUBFRAME'
        facts = self.facts(self.collect(p, binding, attachment, native, foreground=88))
        self.assertEqual((facts['foregroundClassKnown'], facts['rootClassCode'], facts['engineWaitKnown']), (1, 2, 1))

    def test_unknown_or_failed_class_is_never_retained_and_does_not_replace_original_owner_observation(self):
        for name, result in (('SALFRAME-extra', None), ('salframe', None), ('SYNTHETIC-PRIVATE-WINDOW', None),
                ('SALFRAME', 0), ('SALFRAME', 1), ('SALFRAME', 64), ('SALFRAME', True)):
            with self.subTest(caseCode=(name, result) != ('SALFRAME', 0)):
                _, p, _, _, binding, attachment, native = self.source_fixture()
                native.classes[99] = name; native.class_result = result
                row = self.collect(p, binding, attachment, native); facts = self.facts(row)
                self.assertEqual((facts['foregroundClassKnown'], facts['foregroundClassCode']), (0, 0))
                self.assertEqual((row['statusCode'], row['bindingAfter'], row['foregroundSame'], row['popupQualified']), (2, 1, 1, 0))
                self.assertNotIn(name, json.dumps(row))

    def test_class_identity_or_owner_change_leaves_only_unknown_numeric_class(self):
        for mode in ('pid', 'root', 'owner'):
            with self.subTest(mode=mode):
                _, p, _, _, binding, attachment, native = self.source_fixture()
                def change(hwnd):
                    if mode == 'pid': native.identity_drift[hwnd] = 999
                    elif mode == 'root': native.roots[hwnd] = 111
                    else: native.owner_drift[hwnd] = 0
                native.class_mutation = change
                facts = self.facts(self.collect(p, binding, attachment, native))
                self.assertEqual((facts['foregroundClassKnown'], facts['rootClassKnown']), (0, 0))

    def test_class_join_rejects_stable_new_metadata_that_disagrees_with_the_captured_root_owner(self):
        for mode in ('pid', 'thread', 'owner', 'raw-root', 'root-during-raw-class'):
            with self.subTest(mode=mode):
                _, p, _, _, binding, attachment, native = self.source_fixture()
                if mode in ('raw-root', 'root-during-raw-class'):
                    native.foreground = 91; native.roots[91] = 99; native.classes[91] = '#32770'
                def change():
                    if mode == 'pid': native.identity_drift[99] = 999
                    elif mode == 'thread': native.thread_drift[99] = 10
                    elif mode == 'owner': native.owner_drift[99] = 0
                    elif mode == 'raw-root': native.roots[91] = 111
                native.final_root_mutation = change
                if mode == 'root-during-raw-class':
                    def during_class(hwnd):
                        if hwnd == 91: native.identity_drift[99] = 999
                    native.class_mutation = during_class
                row = self.collect(p, binding, attachment, native); facts = self.facts(row)
                self.assertEqual((row['owners'][0]['pid'], row['owners'][0]['threadId'], row['owners'][0]['ownerHwnd']), (88, 9, 100))
                self.assertEqual((facts['foregroundClassKnown'], facts['foregroundClassCode']), (0, 0))
                self.assertEqual(facts['rootClassKnown'], int(mode == 'raw-root'))
                self.assertEqual(facts['engineWaitKnown'], 1)

    def test_engine_wait_zero_and_timeout_are_known_only_after_original_pid_and_birth_match(self):
        for wait, known in ((0, 1), (258, 1), (0xffffffff, 0), (1, 0), (True, 0)):
            with self.subTest(waitCode=int(wait)):
                _, p, _, _, binding, attachment, native = self.source_fixture()
                native.engine_wait = wait
                facts = self.facts(self.collect(p, binding, attachment, native))
                self.assertEqual((facts['engineIdentityKnown'], facts['engineWaitKnown']), (1, known))
                self.assertEqual(facts['engineWaitResult'], wait if known else 0)
        for field, value in (('engine_pid', 999), ('engine_pid', True), ('engine_birth', 201), ('times_succeeded', 0)):
            with self.subTest(field=field):
                _, p, _, _, binding, attachment, native = self.source_fixture(); setattr(native, field, value)
                facts = self.facts(self.collect(p, binding, attachment, native))
                self.assertEqual((facts['engineIdentityKnown'], facts['engineWaitKnown'], facts['engineWaitResult']), (0, 0, 0))
                self.assertNotIn('WaitForSingleObject', native.calls)

    def test_wrong_or_untyped_source_generation_never_queries_the_retained_engine_handle(self):
        changes = (lambda p: p._source_generation_binding.update(engineHandleValue=10),
            lambda p: p._source_generation_binding.update(officePid=True),
            lambda p: p._source_generation_binding.update(engineCreationTime=201),
            lambda p: p._source_generation_binding.update(document=12),
            lambda p: p._source_generation_binding.update(extra=1),
            lambda p: p._point_source.update(engineHandle=True),
            lambda p: p._point_source.update(shellHandle=10),
            lambda p: p._point_source.update(extra=1),
            lambda p: p._identity_scope.update(officeCreationTime=201),
            lambda p: setattr(p, '_source_bound_selection', object()),
            lambda p: setattr(p, 'source_selection', None),
            lambda p: setattr(p, '_native_point_profile_version', 3),
            lambda p: p._menu_classification_context[0].update(version=True),
            lambda p: p._identity_scope.update(startedAt=False))
        for index, change in enumerate(changes):
            with self.subTest(case=index):
                _, p, _, _, binding, attachment, native = self.source_fixture(); change(p)
                facts = self.facts(self.collect(p, binding, attachment, native))
                self.assertEqual((facts['sourceMatched'], facts['engineIdentityKnown'], facts['engineWaitKnown']), (0, 0, 0))
                self.assertFalse(set(native.calls) & {'GetProcessId', 'GetProcessTimes', 'WaitForSingleObject'})

    def test_source_change_at_each_borrowed_handle_return_stops_all_further_process_queries(self):
        order = ['GetProcessId', 'GetProcessTimes', 'WaitForSingleObject']
        for stop in order:
            with self.subTest(apiCode=order.index(stop)):
                _, p, _, _, binding, attachment, native = self.source_fixture()
                def change(name):
                    if name == stop: p._point_source = dict(p._point_source)
                native.kernel_mutation = change
                facts = self.facts(self.collect(p, binding, attachment, native))
                self.assertEqual((facts['sourceMatched'], facts['engineIdentityKnown'], facts['engineWaitKnown']), (0, 0, 0))
                self.assertEqual([name for name in native.calls if name in order], order[:order.index(stop) + 1])

    def test_new_fact_reads_share_original_budget_pending_and_native_only_boundary(self):
        _, p, _, _, binding, attachment, native = self.source_fixture()
        self.facts(self.collect(p, binding, attachment, native)); total = len(native.calls)
        for index in range(1, total + 1):
            for mode in ('late', 'pending'):
                with self.subTest(boundary=index, mode=mode):
                    _, p, _, _, binding, attachment, native = self.source_fixture()
                    if mode == 'late': native.expire_at = index
                    else: native.pending_at = index
                    row = self.collect(p, binding, attachment, native)
                    self.assertEqual(len(native.calls), index); self.assertEqual(native.after_deadline, 0)
                    self.assertEqual((row['statusCode'], row['popupQualified']), (1, 0))
                    self.assertEqual(self.facts(row)['engineWaitKnown'], 0)

    def test_new_native_fact_failures_and_cancellation_preserve_original_foreground_assertion(self):
        for target in ('GetClassNameW', 'GetProcessId', 'GetProcessTimes', 'WaitForSingleObject'):
            for error_type in (OSError, KeyboardInterrupt, SystemExit):
                with self.subTest(api=target, errorCode=(OSError, KeyboardInterrupt, SystemExit).index(error_type)):
                    _, p, _, _, _, _, native = self.source_fixture()
                    primary = error_type()
                    original_called = native.called
                    def called(name):
                        original_called(name)
                        if name == target: raise primary
                    native.called = called
                    calls = []; preserved = {}
                    def foreground():
                        calls.append(1)
                        if len(calls) == 1: return 11
                        preserved['last'] = p.interop.get('lastCall')
                        preserved['exception'] = getattr(p, '_last_call_exception', None)
                        return 99
                    p.foreground = foreground
                    marker = dict(apiCode=7); p.interop['lastCall'] = marker
                    original = RuntimeError(); p._last_call_exception = original
                    with self.assertRaisesRegex(AssertionError, 'Physical File header requires its original foreground document'):
                        p._physical_base()
                    row = p.interop['graphRefresh']['foregroundMismatch']; facts = self.facts(row)
                    self.assertEqual(row['popupQualified'], 0); self.assertEqual(facts['acceptanceEligible'], 0)
                    self.assertNotIn('error', facts); self.assertNotIn('exception', facts)
                    self.assertIs(p._last_call_exception, preserved['exception'])
                    self.assertIs(p.interop['lastCall'], preserved['last'])

    def test_borrowed_engine_filetime_keeps_high_bits_without_querying_an_image_or_exit_code(self):
        _, p, _, _, binding, attachment, native = self.source_fixture()
        birth = (1 << 40) + 200
        native.engine_birth = birth
        p._identity_scope['officeCreationTime'] = birth
        p._menu_classification_context[0]['officeCreationTime'] = birth
        p._source_generation_binding['engineCreationTime'] = birth
        facts = self.facts(self.collect(p, binding, attachment, native))
        self.assertEqual((facts['engineIdentityKnown'], facts['engineWaitKnown'], facts['engineWaitResult']), (1, 1, 258))
        self.assertEqual([name for name in native.calls if name in ('GetProcessId', 'GetProcessTimes', 'WaitForSingleObject')],
            ['GetProcessId', 'GetProcessTimes', 'WaitForSingleObject'])

    def test_unsupported_optional_native_apis_stay_unknown_without_losing_original_numeric_owner_result(self):
        for name in ('GetClassNameW', 'GetProcessId', 'GetProcessTimes', 'WaitForSingleObject'):
            with self.subTest(api=name):
                _, p, _, _, binding, attachment, native = self.source_fixture()
                delattr(p.user if name == 'GetClassNameW' else p.kernel, name)
                row = self.collect(p, binding, attachment, native); facts = self.facts(row)
                self.assertEqual((row['statusCode'], row['ownerStopCode'], row['bindingAfter'], row['foregroundSame']), (2, 2, 1, 1))
                self.assertEqual(row['popupQualified'], 0)
                if name == 'GetClassNameW':
                    self.assertEqual((facts['foregroundClassKnown'], facts['rootClassKnown']), (0, 0))
                    self.assertEqual(facts['engineWaitKnown'], 1)
                else:self.assertEqual(facts['engineWaitKnown'], 0)


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
