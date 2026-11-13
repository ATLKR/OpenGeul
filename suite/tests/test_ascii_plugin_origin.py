"""Opt-in origin sidecars cannot qualify unbound or partial plugin frames."""
import ctypes as C
import json
import unittest
import ascii_message_protocol as p
import test_ascii_message_windows as boundary

class PluginOriginTraceTests(unittest.TestCase):
    def transport(self):
        self.assertTrue(hasattr(p,'PluginBinding'),'plugin binding ABI absent')
        b=boundary.AsciiMessageWindowsTests();b.setUp();self.addCleanup(b.doCleanups)
        b.dll.HookReturn=C.c_void_p(13)
        origin=dict(path='C:\\owned\\Office\\program\\vclplug_winlo.dll',volume=7,
                    fileId=bytes(range(16)),size=1536,architecture='arm64')
        try:t=b.m.MessageTransport(b.user,b.kernel,b.dll,b.target,123456,b.record,101.,b.clock,b.identity,
            nonce=123,capture_diagnostic_mode=True,capture_deadline_counter=1000,capture_counter_frequency=100,plugin_origin=origin)
        except TypeError:self.fail('Transport cannot bind an opt-in plugin origin')
        t.start();return b,t
    def row(self):
        b,t=self.transport();s=t.state;s.captureCount=1;c=s.captureEvents[0]
        for k,v in dict(sequence=1,origin=1,message=0x202,removeFlags=3,pid=t.target['pid'],tid=t.target['tid'],hwnd=t.target['hwnd'],engineCreationTime=t.creation,counter=10,finishedCounter=11,frequency=100,lParam=123).items():setattr(c,k,v)
        s.retrievalClaimed=4;r=s.retrievalEvents[2]
        for k,v in dict(sequence=3,captureSequence=1,bucket=2,message=0x202,removeFlags=3,pid=t.target['pid'],tid=t.target['tid'],hwnd=t.target['hwnd'],engineCreationTime=t.creation,counter=12,finishedCounter=18,frequency=100,lParam=123,originSucceeded=1,stackRequested=1,frameCount=1).items():setattr(r,k,v)
        r.frames[0].moduleId=14;r.frames[0].rva=0x1104
        o=s.pluginOrigins[2]
        for k,v in dict(sequence=3,captureSequence=1,bucket=2,status=1,counter=13,finishedCounter=15).items():setattr(o,k,v)
        return b,t,r,o
    def test_bound_plugin_offsets_export_only_after_correlated_sidecar(self):
        b,t,r,o=self.row();b.now=102.;b.identity_ok=False
        result=t.read_capture_trace(local_only=True)['retrieval']
        self.assertEqual(result['status'],'complete');self.assertEqual(result['moduleMapVersion'],2)
        self.assertEqual(result['records'][0]['frames'],[dict(moduleId=14,rva=0x1104)])
        self.assertEqual(result['records'][0]['pluginOrigin']['status'],1)
        self.assertNotIn('C:',json.dumps(result));self.assertFalse(result['moduleLifetimeContinuityProved'])
    def test_missing_sidecar_is_partial_and_never_exports_plugin_offsets(self):
        b,t,r,o=self.row();o.sequence=0
        result=t.read_capture_trace(local_only=True)['retrieval']
        self.assertEqual(result['status'],'partial');self.assertEqual(result['records'],[])
    def test_mismatch_late_sidecar_and_private_header_mutation_reject(self):
        for change in (lambda t,o:setattr(o,'captureSequence',2),lambda t,o:setattr(o,'status',2),
                       lambda t,o:setattr(o,'finishedCounter',1000),lambda t,o:setattr(t.state.pluginBinding,'volume',8)):
            b,t,r,o=self.row();change(t,o)
            with self.assertRaises(AssertionError):t.read_capture_trace(local_only=True)
    def test_failed_origin_with_redacted_frame_remains_explicit_partial(self):
        b,t,r,o=self.row();o.status=2;r.frames[0].moduleId=0;r.frames[0].rva=0;r.unknownFrames=1
        result=t.read_capture_trace(local_only=True)['retrieval']
        self.assertEqual(result['status'],'partial');self.assertEqual(result['records'][0]['pluginOrigin']['status'],2)

if __name__=='__main__':unittest.main()
