"""Read-only capture settlement never changes the target or the input program."""
import copy
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'e2e/capture_readiness.py'
capture = None
if SOURCE.is_file():
    spec = importlib.util.spec_from_file_location('capture_readiness_tested', SOURCE)
    capture = importlib.util.module_from_spec(spec); spec.loader.exec_module(capture)


class CaptureReadinessTests(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(capture, 'Missing bounded read-only owned-capture gate')
    def fixture(self, values):
        self.now = 1.; self.reads = self.validations = 0; self.pauses = []; self.receipt = {}
        self.binding = dict(suiteHwnd=11, shellPid=77, officePid=88)
        self.values = list(values)
        def observe():
            self.reads += 1
            value = self.values.pop(0) if len(self.values) > 1 else self.values[0]
            return dict(scope=dict(capture=copy.deepcopy(value), before=dict(suite=dict(threadId=45),editor=dict(threadId=44))), marker=self.reads)
        def validate(row):
            self.validations += 1
            self.assertIs(self.receipt['lastGuardObservation'], row)
        def pause(seconds): self.pauses.append(seconds); self.now += seconds
        self.observe, self.validate, self.pause = observe, validate, pause
    def window(self, hwnd=12, pid=77, thread=45, root=11, exists=True):
        return dict(hwnd=hwnd,pid=pid,threadId=thread,rootHwnd=root,isWindow=exists)
    def settle(self, deadline=2.):
        return capture.settle_owned_capture(self.observe,self.validate,self.receipt,self.binding,deadline,clock=lambda:self.now,pause=self.pause)
    def test_zero_capture_observes_once_without_wait_or_action(self):
        self.fixture([dict(hwnd=0)]); row=self.settle()
        self.assertEqual((self.reads,self.validations,self.pauses),(1,1,[]))
        self.assertIs(row,self.receipt['lastGuardObservation'])
    def test_live_host_or_engine_capture_settles_read_only_under_same_deadline(self):
        for window in (self.window(),self.window(22,88,44)):
            self.fixture([window,window,dict(hwnd=0)]); row=self.settle()
            self.assertEqual((self.reads,self.validations),(3,3));self.assertEqual(self.pauses,[.05,.05])
            summary=self.receipt['captureReadiness'];self.assertEqual(summary['pollCount'],2)
            self.assertEqual(summary['first']['scope']['capture'],window)
            self.assertEqual(summary['last']['scope']['capture'],dict(hwnd=0))
            self.assertEqual(row['scope']['capture']['hwnd'],0)
    def test_unknown_foreign_dead_or_different_thread_capture_is_immediate_failure(self):
        for value in (dict(hwnd=12),self.window(pid=99),self.window(root=99),self.window(exists=False),self.window(thread=99)):
            self.fixture([value,dict(hwnd=0)])
            with self.assertRaisesRegex(AssertionError,'capture'):self.settle()
            self.assertEqual(self.pauses,[]);self.assertEqual(self.reads,1)
            self.assertEqual(self.receipt['lastGuardObservation']['scope']['capture'],value)
    def test_context_validation_failure_is_not_retried_or_swallowed(self):
        self.fixture([self.window(),dict(hwnd=0)])
        error=AssertionError('generation changed')
        def reject(row):raise error
        self.validate=reject
        with self.assertRaises(AssertionError) as result:self.settle()
        self.assertIs(result.exception,error);self.assertEqual(self.pauses,[])
        self.assertIn('scope',self.receipt['lastGuardObservation'])
    def test_owned_capture_expiry_preserves_last_observation_without_renewal(self):
        self.fixture([self.window()])
        with self.assertRaisesRegex(AssertionError,'deadline'):self.settle(1.12)
        self.assertEqual(self.now,1.12);self.assertEqual(len(self.pauses),3)
        self.assertEqual(self.receipt['lastGuardObservation']['scope']['capture']['hwnd'],12)
        self.assertLessEqual(len(self.receipt['captureReadiness']),8)
    def test_late_zero_observation_does_not_pass_expired_deadline(self):
        self.fixture([dict(hwnd=0)]);original=self.observe
        def late():row=original();self.now=2.;return row
        self.observe=late
        with self.assertRaisesRegex(AssertionError,'deadline'):self.settle()
        self.assertEqual(self.receipt['lastGuardObservation']['scope']['capture']['hwnd'],0)
    def test_zero_settlement_clock_must_still_precede_original_deadline(self):
        self.fixture([self.window(),dict(hwnd=0)]);original=self.validate;reads=[]
        def validate(row):
            original(row)
            if row['scope']['capture']['hwnd']==0:self.now=1.999;reads.append(0)
        def clock():
            if reads:
                reads[0]+=1
                if reads[0]>=3:return 2.
            return self.now
        self.validate=validate
        with self.assertRaisesRegex(AssertionError,'deadline'):
            capture.settle_owned_capture(self.observe,self.validate,self.receipt,self.binding,2.,clock=clock,pause=self.pause)
        self.assertGreaterEqual(self.receipt['captureReadiness']['settledAt'],2.)


if __name__ == '__main__': unittest.main()
