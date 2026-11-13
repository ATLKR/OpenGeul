"""Closed reader-budget diagnostics from original guards, with no new sampling."""
import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
import capture_readiness as capture
import ime_keyboard_session as keyboard
import counted_editor_shortcuts as counted
import numeric_notice as codec
import test_counted_editor_shortcuts as fixtures


class Clock:
    def __init__(self, now=1.):
        self.now, self.calls = now, 0

    def __call__(self):
        self.calls += 1
        return self.now


class ExistingReaderGuardObservationsTests(unittest.TestCase):
    def test_capture_invocation_keeps_the_first_existing_clock_read(self):
        clock, receipt = Clock(), {}
        row = dict(scope=dict(capture=dict(hwnd=0)))
        result = capture.settle_owned_capture(lambda: row, lambda value: None,
            receipt, {}, 10., clock=clock)
        self.assertIs(result, row)
        self.assertEqual(clock.calls, 4)
        current = capture.current_capture_invocation(receipt)
        self.assertEqual(current.get('firstCheckedAt'), 1.)

    def test_ime_budget_trace_keeps_its_one_original_clock_value(self):
        session = keyboard.IMEKeyboardSession.__new__(keyboard.IMEKeyboardSession)
        session.clock, session.deadline = Clock(12.), 12.
        try:
            session._budget()
        except AssertionError as primary:
            frame = primary.__traceback__
            while frame.tb_frame.f_code is not keyboard.IMEKeyboardSession._budget.__code__:
                frame = frame.tb_next
            self.assertIs(frame.tb_frame.f_locals['self'], session)
            self.assertEqual(frame.tb_frame.f_locals.get('checked_at'), 12.)
        else:
            self.fail('The original expired budget must still reject')
        self.assertEqual(session.clock.calls, 1)


class ReaderGuardSummaryTests(unittest.TestCase):
    def helper(self):
        self.assertTrue((E2E / 'reader_guard_summary.py').is_file(),
                        'The closed reader guard projection is required')
        return importlib.import_module('reader_guard_summary')

    @staticmethod
    def retain_failure(record, primary):
        record['numericFailure'] = codec.capture_failure_code(primary)
        record['numericFailureFrames'] = codec.capture_failure_frames(primary)

    def calc(self, directory, *, pending=False):
        process, binding, api, clock, probe, record = fixtures.CountedEditorShortcutsTests().fixture(directory)
        record.update(case='calc-close-cancel', choice='cancel', module='calc',
            kind='physical-calc-uncommitted-close', stage='type-without-enter', success=False,
            shellPid=77, officePid=88, windowHwnd=11, parentHwnd=12, childHwnd=22,
            beforeInput=dict(bindingBefore=dict(binding), readStartedAt=.2, readFinishedAt=.5),
            closeShortcutCount=0)
        session = counted.CountedEditorShortcuts(api, process, binding, record, 10.,
            clock=clock, probe=probe)
        original_engine, original_scope = probe.engine_snapshot, probe.scope_snapshot
        if pending:
            def scope(*args):
                value = original_scope(*args)
                value['capture'].update(hwnd=22, pid=88, threadId=44, rootHwnd=11, isWindow=True)
                return value
            probe.scope_snapshot = scope
        else:
            def engine(*args):
                value = original_engine(*args)
                clock.now = 10.
                return value
            probe.engine_snapshot = engine
        primary = None
        with patch.object(capture.time, 'sleep', side_effect=lambda seconds: setattr(clock, 'now', 10.)):
            try:
                with session:
                    self.fail('Original admission must reject before input')
            except AssertionError as exc:
                primary = exc
        self.assertIsNotNone(primary)
        self.assertEqual(probe.sent, [])
        return record, primary, session, clock, probe

    def writer(self, directory, *, stage_flags=None, freeze=True, kind='native-ime-mode-diagnostic'):
        process, binding, api, clock, probe, record = fixtures.CountedEditorShortcutsTests().fixture(directory)
        clock = Clock(); probe.clock = clock
        record.update(case='ime-writer', module='writer', kind=kind,
            stage='verify-pre-prefix-editing-context', success=False, architecture='arm64',
            shellPid=77, officePid=88, windowHwnd=11, parentHwnd=12, childHwnd=22)
        session = keyboard.IMEKeyboardSession(api, process, 11, 12, 22, 88, 'writer',
            record, 30., probe=probe, clock=clock, retain_evidence=False)
        session.start(); session.phase = 'navigated'; clock.now = 2.
        context = dict(schemaVersion=1, kind='ime-semantic-editing-context', module='writer',
            phase='pre', startedAt=2., readerDeadline=14., setupDeadline=30.,
            expectedNative=dict(session.binding), observations=[], sampleTimings=[])
        if stage_flags:
            context.update(stage_flags)
        record['imeSemanticContext'] = context
        record['imeSemanticContexts'] = [context]
        original_join = keyboard.join_shortcut_generation
        def join(*args):
            value = original_join(*args); clock.now = 14.
            return value
        helper = self.helper(); original_freeze = helper.freeze_writer
        def frozen(*args):
            before = clock.calls, list(probe.calls)
            if freeze: original_freeze(*args)
            self.assertEqual((clock.calls, probe.calls), before)
        primary = None
        with patch.object(keyboard, 'join_shortcut_generation', side_effect=join), \
                patch.object(helper, 'freeze_writer', side_effect=frozen):
            try:
                session.require_context_target('imeSemanticContext')
            except AssertionError as exc:
                primary = exc
        self.assertIsNotNone(primary)
        self.assertEqual(session.deadline, 30.)
        self.assertEqual(probe.sent, [])
        return record, primary, session, context, clock, probe

    def test_identical_calc_leaf_distinguishes_no_observation_and_owned_capture_wait(self):
        values = []
        for pending in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                record, primary, session, clock, probe = self.calc(directory, pending=pending)
                helper = self.helper(); before = list(probe.calls)
                helper.bind(record, primary)
                self.retain_failure(record, primary)
                value = helper.project(record)
                self.assertIsNotNone(value)
                self.assertTrue(helper.valid(value))
                self.assertEqual(value[0], 1)
                self.assertEqual(value[2:6], [1, int(pending), int(pending), int(pending)])
                self.assertEqual(probe.calls, before)
                self.assertEqual(value[14], 0)
                values.append(value)
        self.assertEqual(values[0][12], 0)
        self.assertEqual(values[1][12], 9000)

    def test_writer_freezes_phase_zero_before_later_same_tick_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            record, primary, session, context, clock, probe = self.writer(directory)
            helper = self.helper(); calls, reads = list(probe.calls), clock.calls
            context.update(cleanup=dict(startedAt=14., finishedAt=14.), finishedAt=14.)
            helper.bind(record, primary); self.retain_failure(record, primary)
            value = helper.project(record)
            self.assertIsNotNone(value)
            self.assertEqual(value[0], 2)
            self.assertEqual(value[2:6], [0, 1, 0, 0])
            self.assertEqual(value[10:12], [0, 0])
            self.assertEqual(value[12:15], [12000, 12000, 0])
            self.assertEqual(value[19], 12000)
            self.assertEqual(clock.calls, reads)
            self.assertEqual(probe.calls, calls)

    def test_writer_requires_early_freeze_not_late_cleanup_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            record, primary, session, context, clock, probe = self.writer(directory, freeze=False)
            helper = self.helper(); helper.bind(record, primary); self.retain_failure(record, primary)
            self.assertIsNone(helper.project(record))

    def test_equal_cloned_context_is_not_the_original_require_context_target_local(self):
        helper = self.helper(); original_freeze = helper.freeze_writer
        def swap(record, primary, session, context):
            cloned = dict(context)
            record['imeSemanticContext'] = cloned
            original_freeze(record, primary, session, cloned)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(helper, 'freeze_writer', side_effect=swap):
            record, primary, session, context, clock, probe = self.writer(directory)
        helper.bind(record, primary); self.retain_failure(record, primary)
        self.assertIsNone(helper.project(record))

    def test_actual_keyboard_close_preserves_the_frozen_original_failure(self):
        for close_result in (True, False):
            with self.subTest(close_result=close_result), tempfile.TemporaryDirectory() as directory:
                record, primary, session, context, clock, probe = self.writer(directory)
                helper = self.helper(); helper.bind(record, primary); self.retain_failure(record, primary)
                expected = helper.project(record); self.assertIsNotNone(expected)
                original_trace, original_args = primary.__traceback__, primary.args
                probe.close_result = close_result
                session.close(primary); session.close(primary)
                after = clock.calls, list(probe.calls)
                self.assertEqual(helper.project(record), expected)
                self.assertEqual((clock.calls, probe.calls), after)
                self.assertIs(primary.__traceback__, original_trace)
                self.assertEqual(primary.args, original_args)
                self.assertEqual(probe.calls.count(('close', 2**41)), 1)
                self.assertEqual(bool(session.receipt['cleanupErrors']), not close_result)

    def test_writer_progress_flags_only_read_existing_scalar_metadata(self):
        class Unreadable:
            def __str__(self): raise AssertionError('Raw data must not be read')
            def __repr__(self): raise AssertionError('Raw data must not be read')
            def __len__(self): raise AssertionError('Raw data must not be read')
            def __bool__(self): raise AssertionError('Raw data must not be read')
            def __eq__(self, other): raise AssertionError('Raw data must not be read')
        for kind in ('native-korean-ime', 'native-ime-mode-diagnostic'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                flags = dict(inventoryEvidence=Unreadable(), inventorySha256=Unreadable(),
                    readerStartAttempted=True, observations=[Unreadable()],
                    sampleTimings=[dict(requestedAt=2., receivedAt=2.)],
                    cleanup=dict(startedAt=2., finishedAt=2.), finishedAt=2.,
                    sourceBytesHex=Unreadable(), expectedPrefix=Unreadable(),
                    sourcePath=Unreadable(), expectedUrl=Unreadable())
                record, primary, session, context, clock, probe = self.writer(directory, stage_flags=flags, kind=kind)
                helper = self.helper(); helper.bind(record, primary); self.retain_failure(record, primary)
                value = helper.project(record)
                self.assertIsNotNone(value)
                self.assertEqual(value[7:12], [1, 1, 1, 1, 1])

    def test_cloned_primary_record_and_stale_current_invocation_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            record, primary, session, clock, probe = self.calc(directory)
            helper = self.helper(); helper.bind(record, primary); self.retain_failure(record, primary)
            self.assertIsNotNone(helper.project(record))
            self.assertIsNone(helper.project(dict(record)))
            helper.bind(record, AssertionError('foreign'))
            self.assertIsNotNone(helper.project(record))
            capture.settle_owned_capture(lambda: dict(scope=dict(capture=dict(hwnd=0))),
                lambda row: None, session.receipt, {}, 20., clock=lambda: 11.)
            self.assertIsNone(helper.project(record))

    def test_projection_is_immutable_and_rejects_mutated_owner_or_failure_metadata(self):
        for target in ('failure', 'frames', 'owner', 'binding', 'kind'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                record, primary, session, clock, probe = self.calc(directory)
                helper = self.helper(); helper.bind(record, primary); self.retain_failure(record, primary)
                expected = helper.project(record); self.assertIsNotNone(expected)
                changed = helper.project(record); changed[2] = 5
                self.assertEqual(helper.project(record), expected)
                if target == 'failure': record['numericFailure']['line'] += 1
                elif target == 'frames': record['numericFailureFrames'][-1][1] += 1
                elif target == 'owner': session.receipt['originalEngine']['creationTime'] += 1
                elif target == 'binding': session.receipt['expectedBinding'] = dict(session.receipt['expectedBinding'])
                else: record['kind'] = 'native-korean-ime'
                self.assertIsNone(helper.project(record))

    def test_consistently_relabelled_metadata_cannot_replace_the_actual_guard_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            record, primary, session, clock, probe = self.calc(directory)
            self.assertEqual(session.binding['officePid'], 88)
            record['officePid'] = 999
            record['beforeInput']['bindingBefore']['officePid'] = 999
            session.receipt['expectedBinding']['officePid'] = 999
            session.receipt['originalEngine']['pid'] = 999
            helper = self.helper(); helper.bind(record, primary); self.retain_failure(record, primary)
            self.assertIsNone(helper.project(record))

    def test_cloned_observation_in_both_metadata_slots_is_not_the_actual_guard_row(self):
        with tempfile.TemporaryDirectory() as directory:
            record, primary, session, clock, probe = self.calc(directory, pending=True)
            cloned = dict(primary.opengeul_capture_observation)
            primary.opengeul_capture_observation = cloned
            session.receipt['lastGuardObservation'] = cloned
            helper = self.helper(); helper.bind(record, primary); self.retain_failure(record, primary)
            self.assertIsNone(helper.project(record))

    def test_frozen_numeric_context_and_baseline_metadata_cannot_be_relabelled_later(self):
        for target in ('writer-native', 'calc-baseline', 'calc-timing'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                if target == 'writer-native':
                    record, primary, session, context, clock, probe = self.writer(directory)
                else:
                    record, primary, session, clock, probe = self.calc(directory)
                helper = self.helper(); helper.bind(record, primary); self.retain_failure(record, primary)
                self.assertIsNotNone(helper.project(record))
                if target == 'writer-native': context['expectedNative']['officePid'] = 999
                elif target == 'calc-baseline': record['beforeInput']['bindingBefore']['officePid'] = 999
                else: record['beforeInput']['readFinishedAt'] = .6
                self.assertIsNone(helper.project(record))

    def test_replaced_traceback_with_identical_owned_locations_is_not_the_original_failure(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            record, primary, session, clock, probe = self.calc(one)
            other, second, other_session, other_clock, other_probe = self.calc(two)
            helper = self.helper(); helper.bind(record, primary); self.retain_failure(record, primary)
            self.assertIsNotNone(helper.project(record))
            primary.__traceback__ = second.__traceback__
            self.assertIsNone(helper.project(record))

    def test_bound_failure_can_gain_outer_reraise_frames_without_changing_the_primary(self):
        with tempfile.TemporaryDirectory() as directory:
            record, primary, session, clock, probe = self.calc(directory)
            helper = self.helper(); helper.bind(record, primary); self.retain_failure(record, primary)
            original = helper.project(record); self.assertIsNotNone(original)
            try:
                exec(compile('raise original', str(E2E / 'calc_close_probe.py'), 'exec'), {'original': primary})
            except AssertionError as later:
                self.assertIs(later, primary)
            self.assertEqual(helper.project(record), original)

    def test_decoder_is_pure_and_vector_validation_is_closed(self):
        helper = self.helper()
        sample = [1, 7183, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, -1, -1, -1, 0, 0, 0, 0, 0]
        self.assertTrue(helper.valid(sample))
        for index, replacement in ((0, True), (1, 2**18), (2, 0), (2, 6), (3, True),
                                    (6, 1), (12, -(2**31)-1), (13, 2**31), (14, 1), (19, 1)):
            value = list(sample); value[index] = replacement
            with self.subTest(index=index, replacement=replacement): self.assertFalse(helper.valid(value))
        script = '''
import sys
sys.path.insert(0, sys.argv[1])
import reader_guard_summary as helper
assert not any(name in sys.modules for name in ('numeric_notice', 'windows_smoke',
    'capture_readiness', 'ime_keyboard_session', 'counted_editor_shortcuts', 'uno', 'pywinauto'))
assert helper.valid([1,7183,1,0,0,0,0,0,0,0,0,0,-1,-1,-1,0,0,0,0,0])
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(E2E)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unknown_invocation_fields_and_changed_native_rows_cannot_become_evidence(self):
        for target in ('invocation', 'row', 'context', 'focus-owner', 'parent-owner'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                record, primary, session, context, clock, probe = self.writer(directory)
                helper = self.helper(); helper.bind(record, primary); self.retain_failure(record, primary)
                self.assertIsNotNone(helper.project(record))
                if target == 'invocation':
                    primary.opengeul_capture_invocation['timeoutPhase'] = 1
                elif target == 'row':
                    primary.opengeul_capture_observation['scope']['capture']['hwnd'] = 99
                elif target == 'focus-owner':
                    primary.opengeul_capture_observation['scope']['focus']['pid'] = 99
                elif target == 'parent-owner':
                    primary.opengeul_capture_observation['scope']['parent']['pid'] = 99
                else:
                    record['imeSemanticContext'] = dict(context)
                self.assertIsNone(helper.project(record))

    def test_helper_does_not_read_clock_paths_document_data_or_exception_text(self):
        class Unreadable:
            def __str__(self): raise AssertionError('No raw data conversion')
            def __repr__(self): raise AssertionError('No raw data conversion')
            def __len__(self): raise AssertionError('No raw data conversion')
            def __bool__(self): raise AssertionError('No raw data conversion')
            def __eq__(self, other): raise AssertionError('No raw data comparison')
        with tempfile.TemporaryDirectory() as directory:
            record, primary, session, clock, probe = self.calc(directory)
            primary.args = (Unreadable(),)
            session.receipt['expectedBinding']['expectedImage'] = Unreadable()
            session.receipt['originalEngine']['image'] = Unreadable()
            session.receipt['originalShell']['image'] = Unreadable()
            record['beforeInput']['text'] = Unreadable()
            helper = self.helper(); before = list(probe.calls)
            with patch.object(type(clock), '__call__', side_effect=AssertionError('No new clock sample')):
                helper.bind(record, primary); self.retain_failure(record, primary)
                self.assertIsNotNone(helper.project(record))
            self.assertEqual(probe.calls, before)

    def test_source_records_cannot_supply_an_unbound_public_snapshot(self):
        helper = self.helper()
        record = dict(case='calc-close-cancel', kind='physical-calc-uncommitted-close', module='calc',
            stage='type-without-enter', success=False,
            numericReaderGuardSnapshot=[1,7183,1,0,0,0,0,0,0,0,0,0,-1,-1,-1,0,0,0,0,0])
        self.assertIsNone(helper.project(record))

    def test_private_original_failure_bindings_are_bounded(self):
        helper = self.helper(); records = []
        with tempfile.TemporaryDirectory() as root:
            for index in range(33):
                directory = Path(root) / str(index); directory.mkdir()
                record, primary, session, clock, probe = self.calc(directory)
                helper.bind(record, primary); self.retain_failure(record, primary)
                records.append(record)
        self.assertEqual(len(helper._BOUND), 32)
        self.assertIsNone(helper.project(records[0]))
        self.assertIsNotNone(helper.project(records[-1]))

    def test_writer_freezes_and_calc_bindings_share_one_total_association_bound(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as root:
            for index in range(32):
                directory = Path(root) / ('w' + str(index)); directory.mkdir()
                record, primary, session, context, clock, probe = self.writer(directory)
                helper.bind(record, primary); self.retain_failure(record, primary)
            for index in range(32):
                directory = Path(root) / ('c' + str(index)); directory.mkdir()
                record, primary, session, clock, probe = self.calc(directory)
                helper.bind(record, primary); self.retain_failure(record, primary)
        self.assertLessEqual(len({id(entry[0]) for entry in helper._FROZEN + helper._BOUND}), 32)


if __name__ == '__main__':
    unittest.main()
