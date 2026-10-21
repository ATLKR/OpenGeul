"""Typed controller/mapping fakes exercise the real versioned queue transaction."""
import copy
import ctypes as C
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_ascii_message_windows as windows
from test_ascii_queue_readiness import sample


class InitialQueueTransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture=windows.AsciiMessageWindowsTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.responses=[dict(sample(),engineCreationTime=123456)];self.fail_control=False;self.stale=False
        f.user.RegisterWindowMessageW=windows.Fn(lambda name:0xc001 if 'Start' in name else 0xc003 if 'Readiness' in name else 0xc002)
        f.dll.ReadinessSampleSize=windows.Fn(lambda:C.sizeof(f.m.QueueSample))
        f.dll.ReadinessOffset=windows.Fn(lambda:f.State.readiness.offset)
        old=f.user.SendMessageTimeoutW
        def send(hwnd,message,wp,lp,flags,timeout,result):
            if message!=0xc003:return old(hwnd,message,wp,lp,flags,timeout,result)
            f.calls.append(('query-control',hwnd,message,flags,timeout))
            state=f.State.from_address(C.addressof(f.raw));response=copy.deepcopy(self.responses.pop(0) if len(self.responses)>1 else self.responses[0])
            for key,value in response.items():
                if key in ('request','requestAfter','ack','ackAfter'):continue
                if key=='keyboardState':
                    for i,b in enumerate(value):state.readiness.sample.keyboard[i]=b
                else:setattr(state.readiness.sample,key,value)
            state.readiness.ack=0 if self.stale else state.readiness.request
            return not self.fail_control
        f.user.SendMessageTimeoutW=windows.Fn(send)
    def transport(self):
        t=self.fixture.transport();self.addCleanup(t.close);t.start()
        self.assertTrue(callable(getattr(t,'query_initial_readiness',None)),'Native initial readiness transaction missing')
        return t
    def test_ready_ack_acquired_on_both_sides_of_exact_sample_copy_before_first_arm(self):
        t=self.transport();f=self.fixture
        state=f.State.from_address(C.addressof(f.raw))
        with self.assertRaisesRegex(AssertionError,'readiness'):t.arm(0)
        original=C.string_at
        def copied(address,size):f.calls.append('snapshot-copy');return original(address,size)
        with patch.object(C,'string_at',side_effect=copied):row=t.query_initial_readiness()
        ack=C.addressof(f.raw)+f.State.readiness.offset+type(state.readiness).ack.offset
        index=f.calls.index('snapshot-copy')
        self.assertEqual(f.calls[index-1],('acquire',ack));self.assertEqual(f.calls[index+1],('acquire',ack))
        self.assertEqual((row['request'],row['ack'],row['ackAfter']),(1,1,1))
        self.assertEqual(t.arm(0),0);self.assertEqual(state.armedEpoch,1)
        self.assertEqual(f.record['transport']['readinessControls']['pollCount'],1)
    def test_pending_then_ready_has_distinct_requests_without_resetting_or_restarting(self):
        pending=dict(sample(),engineCreationTime=123456);pending['queueStatus']=1<<16
        self.responses=[pending,dict(sample(),engineCreationTime=123456)]
        t=self.transport();f=self.fixture;r1=t.query_initial_readiness()
        self.assertEqual(r1['queueStatus'],1<<16)
        with self.assertRaisesRegex(AssertionError,'readiness'):t.arm(0)
        r2=t.query_initial_readiness();self.assertEqual(r2['request'],2)
        t.arm(0)
        controls=[c for c in f.calls if isinstance(c,tuple) and c[0]=='message']
        self.assertEqual(len(controls),1);self.assertEqual(controls[0][2],0xc001)
        self.assertEqual(len([c for c in f.calls if isinstance(c,tuple) and c[0]=='query-control']),2)
    def test_stale_ack_or_bad_identity_is_retained_and_fatal_without_reuse(self):
        for failure in ['stale','identity','keyboard']:
            with self.subTest(failure=failure):
                self.setUp();self.stale=failure=='stale'
                if failure=='identity':self.responses[0]['engineCreationTime']=123457
                if failure=='keyboard':self.responses[0]['keyboardSucceeded']=0;self.responses[0]['keyboardError']=5
                t=self.transport()
                with self.assertRaises((AssertionError,OSError)):t.query_initial_readiness()
                self.assertIn('lastInitialQueueObservation',self.fixture.record['transport'])
                prior=len(self.fixture.calls)
                with self.assertRaisesRegex(AssertionError,'failed'):t.query_initial_readiness()
                self.assertEqual(len(self.fixture.calls),prior)
    def test_control_timeout_is_sticky_and_retains_untrusted_raw_ack(self):
        t=self.transport();self.fail_control=True
        with self.assertRaisesRegex(AssertionError,'control'):t.query_initial_readiness()
        self.assertIn('lastInitialQueueObservation',self.fixture.record['transport'])
        self.assertEqual(self.fixture.State.from_address(C.addressof(self.fixture.raw)).armedEpoch,0)
        with self.assertRaisesRegex(AssertionError,'failed'):t.query_initial_readiness()
    def test_post_control_deadline_never_qualifies_ack_or_arms(self):
        t=self.transport();f=self.fixture;original=f.user.SendMessageTimeoutW
        def late(*args):value=original(*args);f.now=101.;return value
        f.user.SendMessageTimeoutW=windows.Fn(late)
        with self.assertRaisesRegex(AssertionError,'deadline'):t.query_initial_readiness()
        self.assertIn('lastInitialQueueObservation',f.record['transport'])
        self.assertEqual(f.State.from_address(C.addressof(f.raw)).armedEpoch,0)
    def test_torn_ack_during_copy_never_qualifies_or_reuses_query(self):
        t=self.transport();f=self.fixture;original=C.string_at
        def changed(address,size):
            value=original(address,size);f.State.from_address(C.addressof(f.raw)).readiness.ack+=1;return value
        with patch.object(C,'string_at',side_effect=changed):
            with self.assertRaisesRegex(AssertionError,'ACK'):t.query_initial_readiness()
        row=f.record['transport']['lastInitialQueueObservation']
        self.assertEqual((row['ack'],row['ackAfter']),(1,2));self.assertFalse(t.initial_queue_ready)
    def test_count_epoch_command_or_recording_change_after_native_query_is_fatal(self):
        for field,value in [('count',1),('armedEpoch',1),('command',2),('recording',0)]:
            with self.subTest(field=field):
                self.setUp();t=self.transport();f=self.fixture;original=f.user.SendMessageTimeoutW
                def changed(*args):
                    result=original(*args);setattr(f.State.from_address(C.addressof(f.raw)),field,value);return result
                f.user.SendMessageTimeoutW=windows.Fn(changed)
                with self.assertRaises(AssertionError):t.query_initial_readiness()
                self.assertFalse(t.initial_queue_ready)
    def test_first_arm_does_not_reset_an_unexpected_existing_epoch(self):
        t=self.transport();f=self.fixture;t.query_initial_readiness()
        state=f.State.from_address(C.addressof(f.raw));state.armedEpoch=77
        with self.assertRaisesRegex(AssertionError,'epoch'):t.arm(0)
        self.assertEqual(state.armedEpoch,77)


if __name__=='__main__':unittest.main()
