"""One real-shaped observation is enough for the IME setup barrier.

Synthetic native fixtures exercise fail-closed policy; they are not Windows
input, UNO or Korean composition evidence.
"""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
from test_calc_model_barrier import observation, workbook
import test_calc_pending_input as pending_fixtures
from test_writer_model_barrier import (original_shell_fixture,
    retime_native_cleanup_fixture, synthetic_frame)
from test_writer_model_reader import cleanup_fixture
import calc_model_barrier
import writer_model_reader


SOURCE = Path(__file__).resolve().parents[1] / 'e2e/ime_calc_setup.py'


class ImeCalcSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = None
        if SOURCE.is_file():
            spec = importlib.util.spec_from_file_location('ime_calc_setup_under_test', SOURCE)
            cls.api = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.api)

    def setUp(self):
        self.assertIsNotNone(self.api, 'Missing one-observation Calc IME setup barrier')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.frame = synthetic_frame(Path(self.temp.name) / 'Suite', 'unused')
        self.source = self.frame.suite / 'OpenGeul-calc.xlsx'
        self.original = workbook()
        self.source.write_bytes(self.original)
        self.frame.binding['documentUrl'] = self.source.as_uri()
        self.baseline = calc_model_barrier.baseline_from_ooxml(self.original)
        self.prefix = ' ime-opengeul-calc:'
        pending = pending_fixtures.PendingInputTests()
        pending.setUp()
        self.addCleanup(pending.doCleanups)
        pending.paragraph.text = self.baseline['a1Text'] + self.prefix
        ui = pending.present()
        ui['childHwnd'] = self.frame.binding['childHwnd']
        self.row = observation(self.frame, self.baseline['a1Text'], 1., 1.1, False)
        self.row.update(kind='existing-owned-calc-pending-input',
            operations=list(writer_model_reader.CALC_PENDING_OPERATIONS),
            pendingInput=ui, calcSelection=dict(readOnly=True,
                source='retained-controller.getSelection', range=dict(sheet=0,
                    startColumn=0, startRow=0, endColumn=0, endRow=0)))
        self.native = {k: self.frame.binding[k] for k in (
            'shellPid', 'shellCreationTime', 'officePid', 'officeCreationTime',
            'expectedImage', 'suiteHwnd', 'parentHwnd', 'childHwnd', 'rootHwnd')}
        self.shell = original_shell_fixture(self.frame.binding, self.frame.suite)
        self.context = dict(suite=self.frame.suite, baseline=self.baseline,
            prefix=self.prefix, inventory=self.frame.inventory,
            inventory_sha256=self.frame.inventory_sha256, original_shell=self.shell,
            expected_native=self.native, expected_url=self.source.as_uri(),
            started_at=.5, deadline=10.)

    def validate(self, row=None, **changes):
        return self.api.validate_calc_setup(self.row if row is None else row,
            **dict(self.context, **changes))

    def cleanup(self):
        value = cleanup_fixture(self.frame.binding, str(self.frame.suite))
        value.update(kind='owned-calc-pending-reader-cleanup',
            startedAt=2., finishedAt=2.1, deadline=10.)
        retime_native_cleanup_fixture(value)
        return value

    def test_accepts_one_pending_a1_observation_without_inventing_earlier_history(self):
        value = self.validate()
        self.assertEqual(value, self.row)
        self.assertNotIn('beforeInput', value)
        self.assertNotIn('afterCtrlHome', value)
        self.assertFalse(value['isModified'])
        self.assertEqual(value['a1Text'], self.baseline['a1Text'])

    def test_wrong_a1_selection_or_edit_buffer_never_passes(self):
        changes = [lambda r: r['calcSelection']['range'].update(startRow=7, endRow=7),
            lambda r: r.update(pendingInput=dict(r['pendingInput'], editor=None)),
            lambda r: r['pendingInput']['editor'].update(name='Cell F8'),
            lambda r: r['pendingInput']['editor'].update(text='changed'),
            lambda r: r['pendingInput']['traversal'].update(truncated=True)]
        for change in changes:
            row = copy.deepcopy(self.row)
            change(row)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                self.validate(row)

    def test_model_must_remain_clean_with_exact_baseline_cells(self):
        for key, value in [('a1Text', self.baseline['a1Text'] + self.prefix),
                           ('isModified', True), ('b1Value', True),
                           ('c1Value', float('nan')), ('d1Value', 41),
                           ('d1Formula', '=42')]:
            row = copy.deepcopy(self.row)
            row[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                self.validate(row)

    def test_first_admission_generation_and_exact_document_url_are_required(self):
        for key, value in [('officeCreationTime', 999), ('shellCreationTime', True),
                           ('childHwnd', 1234), ('expectedImage', '/foreign/soffice.bin')]:
            native = dict(self.native, **{key: value})
            with self.subTest(key=key), self.assertRaises(AssertionError):
                self.validate(expected_native=native)
        with self.assertRaises(AssertionError):
            self.validate(expected_url='file:///C:/foreign.xlsx')

    def test_native_frame_profile_and_packaged_python_cannot_drift(self):
        paths = [(('bindingAfter', 'officeCreationTime'), 999),
                 (('nativeSnapshots', 'helperAfter', 'profileUrl'), 'file:///C:/other'),
                 (('unoSnapshots', 'after', 'documentUrl'), 'file:///C:/other.xlsx'),
                 (('pythonIdentity', 'files', 'uno', 'sha256'), '0' * 64)]
        for path, value in paths:
            row = copy.deepcopy(self.row)
            target = row
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(AssertionError):
                self.validate(row)

    def test_stale_or_out_of_deadline_observation_and_nonexact_prefix_are_rejected(self):
        for changes in ({'started_at': 1.05}, {'deadline': 1.05},
                        {'deadline': True}, {'prefix': ' ime-opengeul-calc:한글'},
                        {'prefix': self.prefix + ' '}):
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                self.validate(**changes)

    def run_reader(self, row=None, cleanup=None, start_failure=None,
                   close_failure=None, record=None, current_failure=None,
                   final_time=2.2):
        calls = []
        row = self.row if row is None else row
        cleanup = self.cleanup() if cleanup is None else cleanup
        def start(deadline):
            calls.append(('start', deadline))
            if start_failure is not None:
                raise start_failure
            return row
        def close(deadline):
            calls.append(('close', deadline))
            if close_failure is not None:
                raise close_failure
            return cleanup
        def factory(*args, **kwargs):
            calls.append(('construct', args, kwargs))
            return SimpleNamespace(start=start, close=close)
        def require_current():
            calls.append(('current',))
            if current_failure is not None:
                raise current_failure
        record = {} if record is None else record
        record.setdefault('asciiPrefix', self.prefix)
        ticks = iter((.5, .6, final_time))
        value = self.api.observe_calc_setup(self.frame.suite, self.source,
            self.original, record, 10., original_shell=self.shell,
            expected_native=self.native, require_current=require_current,
            reader_factory=factory, clock=lambda: next(ticks))
        return value, calls, record

    def test_reader_is_closed_and_validated_before_context_can_return(self):
        value, calls, record = self.run_reader()
        self.assertTrue(value['success'])
        self.assertEqual(value['observation'], self.row)
        self.assertEqual(value['cleanup'], self.cleanup())
        self.assertEqual([c[0] for c in calls],
            ['current', 'construct', 'start', 'close', 'current'])
        self.assertEqual([c[1] for c in calls if c[0] in ('start', 'close')], [10., 10.])
        self.assertEqual(calls[1][2]['getter_contract'], writer_model_reader.CALC_PENDING_GETTER_CONTRACT)
        self.assertEqual(record['calcSetupContext'], value)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_wrong_observation_still_closes_reader_once_and_retains_primary_failure(self):
        row = copy.deepcopy(self.row)
        row['isModified'] = True
        record = {}
        with self.assertRaisesRegex(AssertionError, 'accepted'):
            self.run_reader(row=row, record=record)
        self.assertFalse(record['calcSetupContext']['success'])
        self.assertIn('cleanup', record['calcSetupContext'])

    def test_start_failure_attempts_partial_cleanup_and_preserves_original_exception(self):
        primary = RuntimeError('original launch failed')
        record = {}
        with self.assertRaises(RuntimeError) as raised:
            self.run_reader(start_failure=primary, record=record)
        self.assertIs(raised.exception, primary)
        self.assertIn('cleanup', record['calcSetupContext'])
        self.assertFalse(record['calcSetupContext']['success'])

    def test_failed_nonnatural_or_unclosed_helper_never_allows_ime_context(self):
        for key, value in [('terminated', True), ('finalJobPids', [99]),
                           ('errors', [{'error': 'release failed'}])]:
            cleanup = self.cleanup()
            cleanup[key] = value
            record = {}
            with self.subTest(key=key), self.assertRaises(AssertionError):
                self.run_reader(cleanup=cleanup, record=record)
            self.assertFalse(record['calcSetupContext']['success'])

    def test_cleanup_failure_does_not_replace_an_existing_primary_exception(self):
        primary = RuntimeError('original launch failed')
        secondary = OSError('cleanup failed')
        record = {}
        with self.assertRaises(RuntimeError) as raised:
            self.run_reader(start_failure=primary, close_failure=secondary, record=record)
        self.assertIs(raised.exception, primary)
        self.assertIn('cleanup failed', record['calcSetupContext']['cleanupErrors'][0])

    def test_native_admission_rejection_prevents_reader_construction(self):
        record = {}
        primary = RuntimeError('retained generation changed')
        with self.assertRaises(RuntimeError) as raised:
            self.run_reader(record=record, current_failure=primary)
        self.assertIs(raised.exception, primary)
        self.assertNotIn('cleanup', record['calcSetupContext'])

    def test_cleanup_and_final_context_cannot_precede_the_single_read(self):
        cleanup = self.cleanup()
        cleanup.update(startedAt=.8, finishedAt=.9)
        retime_native_cleanup_fixture(cleanup)
        with self.assertRaisesRegex(AssertionError, 'order'):
            self.run_reader(cleanup=cleanup)
        with self.assertRaisesRegex(AssertionError, 'order'):
            self.run_reader(final_time=2.05)

    def test_reader_retains_explicit_source_and_popen_inputs_for_independent_replay(self):
        value, _, _ = self.run_reader()
        self.assertIn('originalShell', value)
        self.assertEqual(value['originalShell'], self.shell)
        self.assertEqual(value['expectedUrl'], self.source.as_uri())
        self.assertEqual(value['expectedPrefix'], self.prefix)
        self.assertEqual(value['expectedNative'], self.native)


if __name__ == '__main__':
    unittest.main()
