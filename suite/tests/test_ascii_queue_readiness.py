"""Initial target-thread input readiness, never application or semantic proof."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_ascii_message_observer as observers
import test_ascii_message_progress as progress
from test_ascii_editor_input import FakeWindows, keyboard

SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'ascii_queue_readiness.py'
MASK = 0x1c07


def sample(request=1):
    return dict(request=request, requestAfter=request, ack=request, ackAfter=request, status=0,
        queueFlags=MASK, queueStatus=0, keyboardSucceeded=1, keyboardError=0,
        callbackDepth=1, pid=88, tid=99, hwnd=progress.TARGET['hwnd'],
        engineCreationTime=200, layout=progress.TARGET['layout'],
        tickStarted=1000+request, tickFinished=1000+request, keyboardState=[0]*256)


class QueueProbe(observers.Probe):
    def __init__(self, samples=None, batches=None):
        super().__init__(batches); self.samples=list(samples or [sample()]); self.requests=0
    def query_initial_readiness(self):
        self.calls.append('queue-query'); self.requests+=1
        value=copy.deepcopy(self.samples.pop(0) if len(self.samples)>1 else self.samples[0])
        value.update(request=self.requests,requestAfter=self.requests,ack=self.requests,ackAfter=self.requests,
                     tickStarted=1000+self.requests,tickFinished=1000+self.requests)
        return value


class InitialQueueReadinessTests(unittest.TestCase):
    def module(self):
        self.assertTrue(SOURCE.is_file(), 'Mandatory target-thread readiness policy missing')
        spec=importlib.util.spec_from_file_location('tested_ascii_queue_readiness',SOURCE)
        value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
    def test_current_high_word_not_newness_or_non_toggle_low_bits_defines_pending(self):
        m=self.module(); value=sample();value['queueStatus']=MASK
        value['keyboardState'][0x11]=1;value['keyboardState'][0x90]=1
        self.assertTrue(m.require_initial_queue_sample(value,progress.TARGET,200,request=1))
        value['queueStatus']=1<<16
        self.assertFalse(m.require_initial_queue_sample(value,progress.TARGET,200,request=1))
        value['queueStatus']=0;value['keyboardState'][0xa2]=128
        self.assertFalse(m.require_initial_queue_sample(value,progress.TARGET,200,request=1))
        value['keyboardState'][0xa2]=0;value['callbackDepth']=2
        self.assertFalse(m.require_initial_queue_sample(value,progress.TARGET,200,request=1))
    def test_failed_keyboard_identity_stale_ack_unknown_mask_and_lock_states_are_fatal(self):
        m=self.module()
        mutations=[lambda r:r.update(keyboardSucceeded=0,keyboardError=5),lambda r:r.update(status=-2),
            lambda r:r.update(pid=89),lambda r:r.update(tid=100),lambda r:r.update(hwnd=3),
            lambda r:r.update(engineCreationTime=201),lambda r:r.update(layout=1),
            lambda r:r.update(ack=0),lambda r:r.update(ackAfter=2),lambda r:r.update(queueFlags=1),
            lambda r:r.update(requestAfter=2),lambda r:r.update(queueStatus=0x80000000),
            lambda r:r.update(tickFinished=0),lambda r:r.update(callbackDepth=0),
            lambda r:r['keyboardState'].__setitem__(0x14,1),lambda r:r['keyboardState'].__setitem__(0x91,1),
            lambda r:r['keyboardState'].__setitem__(0,True)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                value=sample();mutate(value)
                with self.assertRaises((AssertionError,OSError)):
                    m.require_initial_queue_sample(value,progress.TARGET,200,request=1)
    def setup_observer(self, probe):
        fixture=observers.AsciiMessageObserverTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.binding.update(officeCreationTime=200,suiteHwnd=11)
        observer,_=fixture.observer(probe);return fixture,observer
    def test_old_f2_control_end_pending_despite_async_neutral_waits_before_one_original_U(self):
        first=sample();first['queueStatus']=1<<16
        second=sample();second['keyboardState'][0x11]=128
        third=sample();third['keyboardState'][0x23]=128
        action=keyboard.ascii_actions('U')[0];rows=[]
        for event in action['events']:
            scan=event['scan'];up=bool(event['flags']&2);vk=16 if scan==42 else 85
            rows.append(progress.row(len(rows)+1,257 if up else 256,vk,scan))
            if not up and scan!=42:rows.append(progress.row(len(rows)+1,258,85,scan))
        probe=QueueProbe([first,second,third,sample()],batches=[rows]);fixture,observer=self.setup_observer(probe)
        api=FakeWindows();api.focus=progress.TARGET['hwnd'];api.user.GetWindowThreadProcessId=lambda *args:99
        fixture.binding['childHwnd']=api.focus
        with patch.object(keyboard,'_observer',return_value=observer),patch.object(keyboard.time,'sleep',side_effect=fixture.clock.pause):
            result=keyboard.type_ascii(api,11,api.focus,'U',fixture.record,pause=.04,deadline=101.,
                original_popen=fixture.process,native_binding=fixture.binding,prepared_library={},clock=fixture.clock)
        self.assertEqual(probe.requests,4,'Old preparation queue was not checked before ASCII')
        self.assertLess(probe.calls.index('queue-query'),probe.calls.index(('arm',0)))
        self.assertEqual(len(api.sent),1);self.assertEqual(api.sent[0][0],4)
        self.assertTrue(result['success']);self.assertEqual(observer.receipt['initialQueueReadiness']['pollCount'],4)
        self.assertFalse(observer.receipt['semanticInsertionProved'])
    def test_persistent_pending_expires_original_budget_without_arm_or_input(self):
        pending=sample();pending['queueStatus']=1<<16;probe=QueueProbe([pending]);fixture,observer=self.setup_observer(probe)
        observer.deadline=100.025;api=FakeWindows();api.focus=progress.TARGET['hwnd']
        fixture.binding['childHwnd']=api.focus
        with patch.object(keyboard,'_observer',return_value=observer),patch.object(keyboard.time,'sleep',side_effect=fixture.clock.pause):
            with self.assertRaisesRegex(AssertionError,'deadline'):
                keyboard.type_ascii(api,11,api.focus,'U',fixture.record,pause=.04,deadline=100.025,
                    original_popen=fixture.process,native_binding=fixture.binding,prepared_library={},clock=fixture.clock)
        self.assertEqual(api.sent,[]);self.assertNotIn(('arm',0),probe.calls)
        self.assertEqual(probe.calls.count('close'),1);self.assertFalse(observer.receipt['success'])
    def test_old_extra_F2_after_ready_still_fails_original_strict_order(self):
        old=progress.row(1,257,113,60);probe=QueueProbe(batches=[[old]]);fixture,observer=self.setup_observer(probe)
        with self.assertRaisesRegex(AssertionError,'order'):
            with observer:
                observer.arm(progress.action());observer.await_progress(progress.action())
        self.assertEqual(probe.requests,1)
        self.assertFalse(observer.receipt['actions'][0]['complete']);self.assertEqual(probe.calls.count('close'),1)
    def test_raw_failed_sample_retained_before_validation(self):
        invalid=sample();invalid['keyboardSucceeded']=0;invalid['keyboardError']=5
        fixture,observer=self.setup_observer(QueueProbe([invalid]))
        with self.assertRaises((AssertionError,OSError)):observer.__enter__()
        self.assertEqual(observer.receipt['initialQueueReadiness']['first'][0]['keyboardError'],5)
        self.assertEqual(observer.receipt['cleanup']['unhookAttempts'],2)
    def test_deadline_reached_during_validation_does_not_label_readiness_ready(self):
        fixture,observer=self.setup_observer(QueueProbe());original=fixture.module.require_initial_queue_sample
        def expired(*args,**kwargs):
            result=original(*args,**kwargs);fixture.clock.value=observer.deadline;return result
        with patch.object(fixture.module,'require_initial_queue_sample',side_effect=expired):
            with self.assertRaisesRegex(AssertionError,'deadline'):observer.__enter__()
        self.assertFalse(observer.receipt['initialQueueReadiness']['ready'])
        self.assertFalse(observer.active)
    def test_observation_cap_fails_without_arm_even_when_clock_does_not_advance(self):
        pending=sample();pending['queueStatus']=1<<16
        probe=QueueProbe([pending]);fixture,observer=self.setup_observer(probe)
        self.assertEqual(fixture.module.MAX_QUERIES,8192)
        with patch.object(fixture.module,'MAX_QUERIES',3),patch.object(observer,'pause'):
            with self.assertRaisesRegex(AssertionError,'bound'):observer.__enter__()
        self.assertEqual(probe.requests,3);self.assertNotIn(('arm',0),probe.calls)
        self.assertEqual(probe.calls.count('close'),1);self.assertFalse(observer.active)
    def test_bounded_raw_retention_preserves_first_sixteen_and_latest_forty_eight(self):
        m=self.module();ledger=dict(pollCount=0,first=[],last=[])
        for index in range(100):
            row=dict(index=index,keys=[index]);m.retain_sample(ledger,row);row['keys'][0]=-1
        self.assertEqual(ledger['pollCount'],100)
        self.assertEqual([x['index'] for x in ledger['first']],list(range(16)))
        self.assertEqual([x['index'] for x in ledger['last']],list(range(52,100)))
        self.assertEqual(ledger['first'][0]['keys'],[0]);self.assertEqual(ledger['last'][-1]['keys'],[99])


if __name__=='__main__':unittest.main()
