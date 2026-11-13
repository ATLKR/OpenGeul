"""Bounded cleanup/primary-error contract around the real print-call shape."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'paired_print_diagnostic.py'
api = None
if FILE.is_file():
    sys.path.insert(0, str(FILE.parent))
    spec = importlib.util.spec_from_file_location('paired_print_adapter_candidate', FILE)
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)


class Lease:
    def __init__(self):
        self.waits = 0
        self.closes = 0
        self.failure = None
        self.root_exited = True

    def wait_retired(self):
        self.waits += 1
        if self.failure is not None:
            raise self.failure
        return {'retainedRootExited': self.root_exited, 'retainedWebviewCount': 2,
                'retainedWebviewsExited': True}

    def close(self):
        self.closes += 1


class AttemptTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(api, 'paired print-call adapter is absent')
        self.lease = Lease()
        self.session = object()
        self.oracle = ValueError()

    def invoke(self, printer, factory=None):
        return api.invoke_print(printer, Path('editor'), Path('fixture'), {'name': 'table--300'},
                                Path('fresh-case'), factory or (lambda session, folder: self.lease),
                                lambda error: error is self.oracle)

    def printer(self, *args, admission):
        admission(self.session, args[3])
        return {'syntheticReport': True}

    def test_success_waits_for_original_handles_and_releases_once(self):
        report, error, retirement = self.invoke(self.printer)
        self.assertIsNone(error)
        self.assertTrue(report['syntheticReport'])
        self.assertTrue(retirement['retainedRootExited'])
        self.assertEqual((self.lease.waits, self.lease.closes), (1, 1))

    def test_original_oracle_object_is_retained_after_cleanup(self):
        def printer(*args, admission):
            admission(self.session, args[3])
            raise self.oracle
        report, error, retirement = self.invoke(printer)
        self.assertIsNone(report)
        self.assertIs(error, self.oracle)
        self.assertTrue(retirement['retainedWebviewsExited'])
        self.assertEqual((self.lease.waits, self.lease.closes), (1, 1))

    def test_constructor_failure_has_unknown_retirement_and_propagates(self):
        primary = RuntimeError()
        def printer(*args, admission):
            raise primary
        with self.assertRaises(RuntimeError) as caught:
            self.invoke(printer)
        self.assertIs(caught.exception, primary)
        self.assertEqual((self.lease.waits, self.lease.closes), (0, 0))

    def test_missing_admission_cannot_be_a_completed_observation(self):
        with self.assertRaises(api.Rejected):
            self.invoke(lambda *args, admission: {})

    def test_admission_rejection_propagates_before_print_input(self):
        primary = api.Rejected(2)
        reached = []
        def factory(session, folder):
            raise primary
        def printer(*args, admission):
            admission(self.session, args[3])
            reached.append('physical-print')
        with self.assertRaises(api.Rejected) as caught:
            self.invoke(printer, factory)
        self.assertIs(caught.exception, primary)
        self.assertEqual(reached, [])

    def test_cancellation_keeps_identity_after_owned_cleanup(self):
        primary = KeyboardInterrupt()
        def printer(*args, admission):
            admission(self.session, args[3])
            raise primary
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.invoke(printer)
        self.assertIs(caught.exception, primary)
        self.assertEqual((self.lease.waits, self.lease.closes), (1, 1))

    def test_cleanup_cancellation_does_not_replace_an_original_oracle(self):
        self.lease.failure = KeyboardInterrupt()
        def printer(*args, admission):
            admission(self.session, args[3])
            raise self.oracle
        with self.assertRaises(ValueError) as caught:
            self.invoke(printer)
        self.assertIs(caught.exception, self.oracle)
        self.assertEqual(self.lease.closes, 1)

    def test_unknown_retirement_prevents_a_return_even_after_raster_failure(self):
        self.lease.root_exited = False
        def printer(*args, admission):
            admission(self.session, args[3])
            raise self.oracle
        with self.assertRaises(ValueError) as caught:
            self.invoke(printer)
        self.assertIs(caught.exception, self.oracle)

    def test_cleanup_failure_after_success_remains_a_failure(self):
        primary = OSError()
        self.lease.failure = primary
        with self.assertRaises(OSError) as caught:
            self.invoke(self.printer)
        self.assertIs(caught.exception, primary)
        self.assertEqual(self.lease.closes, 1)

    def test_duplicate_admission_does_not_replace_the_first_lease(self):
        def printer(*args, admission):
            admission(self.session, args[3])
            admission(self.session, args[3])
        with self.assertRaises(api.Rejected):
            self.invoke(printer)
        self.assertEqual((self.lease.waits, self.lease.closes), (1, 1))
