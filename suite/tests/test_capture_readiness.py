"""Read-only capture settlement never changes the target or the input program."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

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

    def test_current_invocation_binds_original_timeout_and_replaces_old_episode(self):
        self.fixture([self.window()])
        with self.assertRaises(AssertionError) as caught:self.settle(1.12)
        current=capture.current_capture_invocation(self.receipt)
        self.assertIsNotNone(current,'Current invocation diagnostic is absent')
        self.assertIs(caught.exception.opengeul_capture_invocation,current)
        self.assertEqual((current['timeoutPhase'],current['observationPresent'],
            current['validationReturned'],current['ownedPositiveCapturePending']),(1,True,True,True))
        self.assertIs(caught.exception.opengeul_capture_observation,self.receipt['lastGuardObservation'])
        first=self.receipt['captureReadiness']['first'];started=self.receipt['captureReadiness']['startedAt']
        self.now=3.
        with self.assertRaises(AssertionError) as next_error:self.settle(3.)
        new=capture.current_capture_invocation(self.receipt)
        self.assertIsNot(new,current)
        self.assertIs(next_error.exception.opengeul_capture_invocation,new)
        self.assertEqual((new['timeoutPhase'],new['observationPresent'],new['validationReturned'],
            new['ownedPositiveCapturePending']),(1,False,False,False))
        self.assertIsNone(next_error.exception.opengeul_capture_observation)
        self.assertIs(self.receipt['captureReadiness']['first'],first)
        self.assertEqual(self.receipt['captureReadiness']['startedAt'],started)

    def test_current_invocation_distinguishes_native_and_validation_expiry(self):
        for phase in (2,3):
            self.fixture([dict(hwnd=0)])
            if phase==2:
                original=self.observe
                def late():row=original();self.now=2.;return row
                self.observe=late
            else:
                original=self.validate
                def late(row):original(row);self.now=2.
                self.validate=late
            with self.subTest(phase=phase),self.assertRaises(AssertionError) as caught:self.settle()
            current=capture.current_capture_invocation(self.receipt)
            self.assertIs(caught.exception.opengeul_capture_invocation,current)
            self.assertEqual(current['timeoutPhase'],phase)
            self.assertEqual(current['validationReturned'],phase==3)
            self.assertFalse(current['ownedPositiveCapturePending'])

    def test_next_observation_clears_previous_rows_validated_pending_flags(self):
        self.fixture([self.window(),dict(hwnd=0)]);original=self.observe
        def late_second():
            row=original()
            if self.reads==2:self.now=2.
            return row
        self.observe=late_second
        with self.assertRaises(AssertionError) as caught:self.settle()
        current=capture.current_capture_invocation(self.receipt)
        self.assertEqual((current['timeoutPhase'],current['observationPresent'],current['validationReturned'],
            current['ownedPositiveCapturePending']),(2,True,False,False))
        self.assertEqual(caught.exception.opengeul_capture_observation['scope']['capture']['hwnd'],0)

    def test_diagnostic_preserves_declared_clock_and_native_call_trace(self):
        for outcome in ('zero','observe-error','validation-error'):
            for operation in (capture.settle_owned_capture,):
                trace=[];now=[1.];count=[0];receipt={};primary=AssertionError('original synthetic failure')
                def clock():trace.append(('clock',now[0]));return now[0]
                def observe():
                    trace.append(('observe',));count[0]+=1
                    if outcome=='observe-error':raise primary
                    value=self.window() if outcome in ('pending','timeout') and count[0]<3 else dict(hwnd=0)
                    return dict(scope=dict(capture=value,before=dict(suite=dict(threadId=45),editor=dict(threadId=44))))
                def validate(row):
                    trace.append(('validate',))
                    if outcome=='validation-error':raise primary
                def pause(seconds):trace.append(('pause',seconds));now[0]+=seconds
                try:operation(observe,validate,receipt,dict(suiteHwnd=11,shellPid=77,officePid=88),
                    1.02 if outcome=='timeout' else 2.,clock=clock,pause=pause)
                except BaseException as exc:
                    trace.append(('error',type(exc).__name__,str(exc)))
                    if outcome.endswith('error'):self.assertIs(exc,primary)
                kinds=[row[0] for row in trace]
                expected={'zero':['clock','observe','clock','validate','clock','clock'],
                    'observe-error':['clock','observe','error'],
                    'validation-error':['clock','observe','clock','validate','error']}[outcome]
                with self.subTest(outcome=outcome):self.assertEqual(kinds,expected)

    def test_diagnostic_slot_failure_cannot_replace_original_result_or_failure(self):
        class RejectRegistry(list):
            def append(self,value):raise KeyboardInterrupt('Synthetic diagnostic failure')
        self.fixture([dict(hwnd=0)])
        with mock.patch.object(capture,'_CAPTURE_INVOCATIONS',RejectRegistry()):
            self.assertEqual(self.settle()['scope']['capture']['hwnd'],0)
            self.now=2.
            with self.assertRaisesRegex(AssertionError,'^Owned capture readiness deadline expired$'):self.settle()

    def test_diagnostic_update_failure_cannot_replace_original_result(self):
        class RejectUpdate(dict):
            def update(self,*args,**kwargs):raise KeyboardInterrupt('Synthetic metadata update failure')
        def start(receipt,deadline):
            current=RejectUpdate();capture._CAPTURE_INVOCATIONS.append((receipt,current));return current
        self.fixture([dict(hwnd=0)])
        with mock.patch.object(capture,'_diagnostic_start',start):
            self.assertEqual(self.settle()['scope']['capture']['hwnd'],0)
        self.assertEqual((self.reads,self.validations,self.pauses),(1,1,[]))

    def test_invocation_association_is_bounded_and_adds_no_receipt_json_fields(self):
        import json
        self.fixture([dict(hwnd=0)])
        for unused in range(33):self.settle()
        self.assertEqual(len(capture._CAPTURE_INVOCATIONS),32)
        self.assertNotIn('captureInvocation',self.receipt)
        raw=json.dumps(self.receipt)
        self.assertNotIn('lastCheckedAt',raw)
        self.assertNotIn('timeoutPhase',raw)


if __name__ == '__main__': unittest.main()
