"""Original single-array insertion/pacing around the new read-only barrier."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace as NS
from test_ascii_editor_input import FakeWindows
from ascii_observer_boundary import AsciiObserverBoundary


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'ascii_editor_input.py'
spec = importlib.util.spec_from_file_location('ascii_observer_wiring_input', SOURCE)
ascii_input = importlib.util.module_from_spec(spec); spec.loader.exec_module(ascii_input)


class AsciiObserverWiringTests(unittest.TestCase):
    def setUp(self):
        self.api, self.record, self.events = FakeWindows(), {}, []
        self.process=NS(pid=77)
        self.binding=dict(suiteHwnd=11,childHwnd=22)
        self.prepared={'kind':'test-only-boundary'}
    def call(self,text='aA'):
        return ascii_input.type_ascii(self.api,11,22,text,self.record,pause=.025,
            original_popen=self.process,native_binding=self.binding,prepared_library=self.prepared,
            deadline=101.,clock=lambda:100.)
    def boundary(self,*args,**kwargs):
        self.assertIs(args[1],self.process); self.assertEqual(args[2],self.binding)
        self.assertIs(args[3],self.prepared); self.assertEqual(args[5],101.)
        outer=self
        class Boundary(AsciiObserverBoundary):
            def __enter__(self): outer.events.append('start'); return super().__enter__()
            def arm(self,a): outer.events.append(('arm',a['index'])); super().arm(a)
            def await_progress(self,a): outer.events.append(('progress',a['index'])); return super().await_progress(a)
            def finish(self,n): outer.events.append(('finish',n)); super().finish(n)
            def __exit__(self,*args): outer.events.append('stop'); return super().__exit__(*args)
        return Boundary(*args,**kwargs)
    def test_one_original_buffer_and_pause_precede_progress_before_next_character(self):
        original=self.api.send
        self.api.send=lambda count,payload,size:(self.events.append(('send',count)),original(count,payload,size))[1]
        with patch.object(ascii_input,'_observer',side_effect=self.boundary), \
             patch.object(ascii_input.time,'sleep',side_effect=lambda n:self.events.append(('pause',n))):
            result=self.call()
        self.assertEqual(['start',('arm',0),('send',2),('pause',.025),('progress',0),
            ('arm',1),('send',4),('pause',.025),('progress',1),('finish',2),'stop'],self.events)
        self.assertTrue(result['success']); self.assertEqual(0,result['queueObserverIndex'])
    def test_missing_or_mismatched_original_authority_never_sends_input(self):
        with self.assertRaises((TypeError,AssertionError)):
            ascii_input.type_ascii(self.api,11,22,'a',self.record,pause=.025)
        self.binding['childHwnd']=23
        with self.assertRaises(AssertionError): self.call()
        self.assertEqual([],self.api.sent)
    def test_queue_failure_stops_next_character_without_retry_and_closes_observer(self):
        def factory(*args,**kwargs):
            result=self.boundary(*args,**kwargs)
            result.await_progress=lambda a:(_ for _ in ()).throw(AssertionError('missing consumed character'))
            return result
        with patch.object(ascii_input,'_observer',side_effect=factory),patch.object(ascii_input.time,'sleep'):
            with self.assertRaisesRegex(AssertionError,'consumed'): self.call()
        self.assertEqual(1,len(self.api.sent)); self.assertEqual('stop',self.events[-1])
        self.assertFalse(self.record['asciiEditorInputs'][0]['success'])
    def test_observer_start_failure_never_enters_sendinput(self):
        with patch.object(ascii_input,'_observer',side_effect=OSError('hook unavailable')):
            with self.assertRaises(OSError): self.call()
        self.assertEqual([],self.api.sent)
    def test_stop_failure_cannot_publish_ascii_success(self):
        def factory(*args,**kwargs):
            result=self.boundary(*args,**kwargs)
            class StopFailure(type(result)):
                def __exit__(self,*args): super().__exit__(*args); raise OSError('stop failed')
            result.__class__=StopFailure
            return result
        with patch.object(ascii_input,'_observer',side_effect=factory),patch.object(ascii_input.time,'sleep'):
            with self.assertRaisesRegex(OSError,'stop'): self.call('a')
        self.assertFalse(self.record['asciiEditorInputs'][0]['success'])
    def test_whole_observer_boundary_requires_initial_phase_and_marks_no_native_observation(self):
        boundary=AsciiObserverBoundary(self.api,self.process,self.binding,self.prepared,self.record,101.)
        with self.assertRaisesRegex(AssertionError,'initial'):
            boundary.arm(ascii_input.ascii_actions('U')[0])
        self.assertEqual(boundary.receipt['actions'],[])
        with boundary:
            boundary.arm(ascii_input.ascii_actions('U')[0]);boundary.finish(1)
        phase=boundary.receipt['initialQueueReadiness']
        self.assertFalse(phase['observedNative']);self.assertEqual(phase['deadline'],101.)
        self.assertEqual(phase['kind'],'test-only-initial-queue-phase')


if __name__=='__main__': unittest.main()
