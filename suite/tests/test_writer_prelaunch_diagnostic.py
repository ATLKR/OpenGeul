"""Closed diagnostic metadata; synthetic ports do not prove Windows readiness."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from test_writer_server_observer_runner_composition import setup, runner, BASE
from writer_server_observer_lifecycle import DiagnosticFailure, FailureCode as LifecycleCode
from writer_server_observer_win32 import NativeCallError, FailureCode as NativeCode
from writer_server_observer_msaa import WatchdogError, Code as WatchdogCode
from writer_server_observer_capture import CaptureError, Code as CaptureCode


FIELDS = ('prelaunchStepCode', 'prelaunchExceptionKindCode',
          'prelaunchExceptionSourceCode', 'prelaunchExceptionLine')


class Projection(unittest.TestCase):
    def projector(self):
        function = getattr(runner, '_prelaunch_failure', None)
        self.assertTrue(callable(function))
        return function

    @staticmethod
    def raised(path, line, error):
        try:
            exec(compile('\n' * (line - 1) + 'raise error\n', str(path), 'exec'), {'error': error})
        except BaseException as captured:
            return captured
        raise AssertionError('Synthetic raise did not execute')

    def test_closed_fields_start_unknown_and_reject_bool_overflow_or_extra(self):
        report = runner.empty_report()
        self.assertTrue(all(key in report['preparation'] for key in FIELDS))
        self.assertTrue(all(report['preparation'][key] is None for key in FIELDS))
        maxima = (14, 17, 5, 20000)
        for key, maximum in zip(FIELDS, maxima):
            for value in (True, -1, maximum + 1, 1.25, 'SYNTHETIC_PRIVATE'):
                corrupt = runner.empty_report()
                corrupt['preparation'][key] = value
                with self.subTest(field=FIELDS.index(key), category=type(value).__name__):
                    with self.assertRaises(runner.RunnerFailure):
                        runner.validate_public_report(corrupt)
        corrupt = runner.empty_report()
        corrupt['preparation']['prelaunchPrivate'] = 1
        with self.assertRaises(runner.RunnerFailure):
            runner.validate_public_report(corrupt)

    def test_exact_builtin_kind_and_deepest_fixed_coordinate_without_private_reads(self):
        project = self.projector()
        touched = []
        class Poison:
            def reject(self): touched.append(1); raise AssertionError()
            __str__ = __repr__ = reject
        error = self.raised(BASE / 'suite/e2e/writer_server_observer_lifecycle.py', 61, ValueError(Poison()))
        error = self.raised(BASE / 'suite/e2e/writer_server_observer_runner.py', 62, error)
        self.assertEqual(project(error), (5, 2, 61))
        self.assertEqual(touched, [])

    def test_exact_reviewed_domain_types_are_known_without_reading_their_code_or_args(self):
        project = self.projector()
        cases = ((runner.RunnerFailure(runner.Code.INPUT), 13, 1),
                 (DiagnosticFailure(LifecycleCode.ENVIRONMENT), 14, 2),
                 (WatchdogError(WatchdogCode.PREPARE), 15, 3),
                 (NativeCallError(NativeCode.CONTROLLER_IDENTITY), 16, 4),
                 (CaptureError(CaptureCode.DESCRIPTOR), 17, 5))
        names = ('runner', 'lifecycle', 'msaa', 'win32', 'capture')
        for (error, kind, source), name in zip(cases, names):
            path = BASE / ('suite/e2e/writer_server_observer_' + name + '.py')
            with self.subTest(kind=kind):
                self.assertEqual(project(self.raised(path, 71, error)), (kind, source, 71))

    def test_unknown_types_paths_and_overlong_trace_do_not_supply_a_coordinate(self):
        project = self.projector()
        path = BASE / 'suite/e2e/writer_server_observer_runner.py'
        class Derived(ValueError): pass
        self.assertEqual(project(self.raised(path, 61, Derived())), (0, 0, None))
        self.assertEqual(project(None), (0, 0, None))
        for bad in (path.with_suffix('.py.extra'), BASE / 'suite/e2e/other.py'):
            self.assertEqual(project(self.raised(bad, 61, ValueError())), (5, 0, None))
        for line in (20001, 65536):
            self.assertEqual(project(self.raised(path, line, ValueError())), (5, 0, None))
        code = 'def recur(n):\n if n: return recur(n-1)\n raise ValueError()\nrecur(70)\n'
        try:
            exec(compile(code, str(path), 'exec'), {})
        except ValueError as error:
            self.assertEqual(project(error), (5, 0, None))

    def test_projection_never_reads_ambient_environment_or_exception_custom_attributes(self):
        project = self.projector()
        reads = []
        class Unreadable:
            def reject(self, *args, **kwargs): reads.append(1); raise AssertionError()
            __getitem__ = get = __iter__ = keys = items = values = copy = __len__ = reject
        error = self.raised(BASE / 'suite/e2e/writer_server_observer_runner.py', 61, AssertionError())
        with patch.object(runner.os, 'environ', Unreadable()):
            self.assertEqual(project(error), (1, 1, 61))
        self.assertEqual(reads, [])

    def test_projection_failure_cannot_replace_the_original_exception(self):
        project = self.projector()
        import builtins
        original = builtins.__import__
        def denied(name, *args, **kwargs):
            if name == 'writer_server_observer_lifecycle': raise ImportError()
            return original(name, *args, **kwargs)
        with patch.object(builtins, '__import__', denied):
            self.assertEqual(project(ValueError()), (0, 0, None))

    def test_numeric_fields_do_not_admit_an_unbound_or_successful_failure_coordinate(self):
        cases = (({'prelaunchStepCode': 0},),
                 ({'prelaunchStepCode': 1},),
                 ({'prelaunchExceptionKindCode': 0, 'prelaunchExceptionSourceCode': 1,
                   'prelaunchExceptionLine': 1},),
                 ({'prelaunchExceptionKindCode': 1, 'prelaunchExceptionSourceCode': 0,
                   'prelaunchExceptionLine': 1},),
                 ({'prelaunchExceptionSourceCode': 1, 'prelaunchExceptionLine': 1},))
        for index, (values,) in enumerate(cases):
            report = runner.empty_report()
            report['preparation'].update(values)
            with self.subTest(case=index):
                with self.assertRaises(runner.RunnerFailure):
                    runner.validate_public_report(report)


class Composed(unittest.TestCase):
    def setUp(self):
        runner._PENDING_CASES.clear()
        runner._CASE_STARTED = False

    def tearDown(self):
        runner._PENDING_CASES.clear()
        runner._CASE_STARTED = False

    def assert_prelaunch_failure(self, report, native, step, code=13):
        self.assertEqual(report['failureCode'], code)
        self.assertTrue('prelaunchStepCode' in report['preparation'])
        self.assertEqual(report['preparation']['prelaunchStepCode'], step)
        self.assertIsNone(report['preparation']['launchAttempted'])
        self.assertNotIn('office-launch', native.calls)
        self.assertNotIn('helper-launch', native.calls)
        self.assertEqual(report['preparation']['inputCount'], 0)
        self.assertTrue(report['preparation']['cleanupComplete'])
        self.assertTrue(report['captureIncomplete'])
        self.assertFalse(report['normalAcceptance'])
        self.assertFalse(report['fullEngineQualified'])
        self.assertFalse(report['guiVerified'])
        self.assertFalse(report['acceptanceEligible'])

    def test_success_marks_environment_ready_without_a_failure_projection(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            report = obj.execute(inputs)
            self.assertEqual(report['failureCode'], 0)
            self.assertTrue('prelaunchStepCode' in report['preparation'])
            self.assertEqual(report['preparation']['prelaunchStepCode'], 14)
            self.assertTrue(all(report['preparation'][key] is None for key in FIELDS[1:]))
            self.assertTrue(report['runtime']['armed'])

    def test_existing_work_is_a_guard_failure_before_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            inputs.work_root.mkdir()
            report = obj.execute(inputs)
            self.assert_prelaunch_failure(report, c.api, 1, code=1)
            self.assertEqual(c.api.calls, [])

    def test_mkdir_denial_preserves_internal_failure_and_no_controller(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            with patch.object(Path, 'mkdir', side_effect=PermissionError()):
                report = obj.execute(inputs)
            self.assert_prelaunch_failure(report, c.api, 4)
            self.assertEqual(report['preparation']['prelaunchExceptionKindCode'], 4)
            self.assertEqual(c.api.calls, [])

    def test_layout_and_host_runtime_faults_identify_distinct_real_composition_boundaries(self):
        for attribute, step, error in (('Layout', 5, DiagnosticFailure(LifecycleCode.ENVIRONMENT)),
                                       ('HostRuntime', 6, WatchdogError(WatchdogCode.PREPARE))):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as folder:
                runner._CASE_STARTED = False
                obj, inputs, c, _ = setup(folder)
                def fail(*args, **kwargs): raise error
                setattr(c, attribute, SimpleNamespace(validated=fail))
                report = obj.execute(inputs)
                self.assert_prelaunch_failure(report, c.api, step)
                self.assertEqual(c.api.calls, [])

    def test_individual_image_resolve_failures_preserve_exact_original_role(self):
        names = ('OpenGeul.Office.exe', 'Office/program/python-core-3.13.17/bin/python.exe',
                 'Office/program/soffice.bin', 'Office/program/soffice.exe')
        for index, name in enumerate(names):
            with self.subTest(role=index), tempfile.TemporaryDirectory() as folder:
                runner._CASE_STARTED = False
                obj, inputs, c, _ = setup(folder)
                # The real Layout checks worker Python first, so remove each
                # selected file only after that original validation returns.
                original = c.HostRuntime.validated
                def remove_after_layout(*args):
                    value = original(*args)
                    (inputs.output / name).unlink()
                    return value
                c.HostRuntime = SimpleNamespace(validated=remove_after_layout)
                report = obj.execute(inputs)
                self.assert_prelaunch_failure(report, c.api, 7 + index)
                self.assertEqual(report['preparation']['prelaunchExceptionKindCode'], 3)
                self.assertEqual(c.api.calls, [])

    def test_controller_error_does_not_claim_creation_or_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            def fail(): raise NativeCallError(NativeCode.CONTROLLER_IDENTITY)
            c.api.retain_current_controller = fail
            report = obj.execute(inputs)
            self.assert_prelaunch_failure(report, c.api, 11)
            self.assertEqual(report['preparation']['prelaunchExceptionKindCode'], 16)

    def test_returned_late_controller_is_closed_once_before_failure_reporting(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            original = c.api.retain_current_controller
            def late():
                result = original()
                c.clock.value += 55000
                return result
            c.api.retain_current_controller = late
            report = obj.execute(inputs)
            self.assert_prelaunch_failure(report, c.api, 11, code=3)
            self.assertEqual(c.api.calls.count('close-700'), 1)
            self.assertEqual(report['pendingRetainedCount'], 0)

    def test_descriptor_and_environment_faults_close_the_original_controller_once(self):
        for attribute, step, error in (('Descriptor', 12, CaptureError(CaptureCode.DESCRIPTOR)),
                                       ('environment', 13, ValueError())):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as folder:
                runner._CASE_STARTED = False
                obj, inputs, c, _ = setup(folder)
                def fail(*args, **kwargs): raise error
                setattr(c, attribute, fail)
                report = obj.execute(inputs)
                self.assert_prelaunch_failure(report, c.api, step)
                self.assertEqual(c.api.calls.count('close-700'), 1)
                self.assertEqual(report['pendingRetainedCount'], 0)

    def test_admission_failure_leaves_every_new_field_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            def fail(**kwargs): raise runner.RunnerFailure(runner.Code.ADMISSION)
            c.require_stage = fail
            report = obj.execute(inputs)
            self.assertEqual(report['failureCode'], 4)
            self.assertTrue(all(key in report['preparation'] for key in FIELDS))
            self.assertTrue(all(report['preparation'][key] is None for key in FIELDS))
            self.assertEqual(c.api.calls, [])


if __name__ == '__main__':
    unittest.main()
