"""Select one actual capture timeout, without falling forward to a later case."""
import copy
import importlib.util
from pathlib import Path
import unittest
SCRIPT=Path(__file__).resolve().parents[1]/'scripts/matched_plugin_diagnostic.py'

class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(),'matched trace selection absent')
        s=importlib.util.spec_from_file_location('matched_selection_test',SCRIPT);self.m=importlib.util.module_from_spec(s);s.loader.exec_module(self.m)
    def report(self):
        target=dict(pid=8,tid=9,hwnd=10,engineCreationTime=11)
        capture=dict(sequence=1,origin=1,message=0x202,removeFlags=3,lParam=12,frequency=100,counter=10,finishedCounter=11,**target)
        origin=dict(sequence=3,captureSequence=1,bucket=2,status=1,counter=12,finishedCounter=13)
        row=dict(sequence=3,captureSequence=1,bucket=2,message=0x202,removeFlags=3,lParam=12,frequency=100,counter=12,finishedCounter=14,
            pluginOrigin=origin,frames=[dict(moduleId=14,rva=0x1104),dict(moduleId=0,rva=0)],frameCount=2,unknownFrames=1,frameCapReached=0,flags=0,**target)
        cleanup=dict(testProcessCleanup=dict(shellExitCode=0,disposition='already-exited'),focusCohortEngineCleanup=dict(admitted=True,engineExitConfirmed=True,handleReleased=True))
        scope=dict(capture=dict(hwnd=10,pid=8,threadId=9,rootHwnd=20,isWindow=True))
        case=dict(case='ime-calc-focus-01',success=False,kind='native-focus-diagnostic',stage='focus-editor',error='AssertionError: Owned capture readiness deadline expired',
            editorFocusReadiness=dict(deadline=6.,ready=False),imeKeyboardSession=dict(expectedNative=dict(suiteHwnd=20,childHwnd=10,officePid=8,officeCreationTime=11),originalEngine=dict(pid=8,creationTime=11),captureReadiness=dict(deadline=6.,settledAt=None,pollCount=95,first=dict(scope=scope),last=dict(scope=scope))),
            focusCaptureDiagnostic=dict(deadline=6.,cleanupErrors=[],snapshot=dict(status='complete',overflow=False,rejected=0,expired=True,reservedCount=1,events=[capture],deadlineCounter=100,counterFrequency=100,
                retrieval=dict(moduleMapVersion=2,status='complete',rejected=0,expired=False,pendingBuckets=[],records=[row]))),**cleanup)
        case['focusCaptureDiagnostic'].update(expectedNative=copy.deepcopy(case['imeKeyboardSession']['expectedNative']),originalEngine=dict(pid=8,creationTime=11),terminalCopyCoverage=dict(clockCoverage='truncated',errors=[],before=dict(counter=90,counterFrequency=100,nativeDeadlineCounter=100),after=dict(counter=95,counterFrequency=100,nativeDeadlineCounter=100)))
        return dict(kind='native-focus-diagnostic',architecture='arm64',acceptanceEligible=False,tests=[case],pluginFileOrigin=dict(verified=True,released=True,dllSha256='a'*64,matchedIdentity=dict(guid='a'*36,age=1)))
    def test_only_correlated_plugin_offsets_and_limits_are_returned(self):
        result=self.m.select(self.report())
        self.assertEqual(result['rvas'],[0x1104]);self.assertEqual(result['unknownFrames'],1)
        self.assertTrue(result['terminalClockTruncated']);self.assertFalse(result['runtimeCallerProved'])
    def test_generation_is_bound_to_original_admission(self):
        r=self.report();snapshot=r['tests'][0]['focusCaptureDiagnostic']['snapshot']
        snapshot['events'][0]['engineCreationTime']=999;snapshot['retrieval']['records'][0]['engineCreationTime']=999
        with self.assertRaises(AssertionError):self.m.select(r)
    def test_terminal_coverage_is_not_producer_expiry(self):
        r=self.report();r['tests'][0]['focusCaptureDiagnostic']['snapshot']['expired']=False
        result=self.m.select(r);self.assertTrue(result['terminalClockTruncated']);self.assertFalse(result['producerExpired'])
    def test_wrong_resolved_pair_and_unresolved_tags_cannot_succeed(self):
        selected=self.m.select(self.report())
        self.assertTrue(hasattr(self.m,'join_resolution'),'trace-pair join absent')
        worker=dict(success=True,resolution=dict(dllSha256='a'*64,identity=dict(guid='a'*36,age=1),frames=[dict(returnRva=0x1104,tag='mutex-acquire')]))
        self.assertTrue(self.m.join_resolution(selected,worker))
        worker['resolution']['frames'][0]['tag']='unresolved';self.assertFalse(self.m.join_resolution(selected,worker))
        worker['resolution']['dllSha256']='b'*64
        with self.assertRaises(AssertionError):self.m.join_resolution(selected,worker)
    def test_partial_rejected_or_mutated_first_failure_never_falls_forward(self):
        for mutate in (lambda c:c['focusCaptureDiagnostic']['snapshot'].update(overflow=True),
            lambda c:c['focusCaptureDiagnostic']['snapshot']['retrieval'].update(pendingBuckets=[1]),
            lambda c:c['focusCaptureDiagnostic']['snapshot']['retrieval']['records'][0]['pluginOrigin'].update(status=2),
            lambda c:c['focusCaptureDiagnostic']['snapshot']['retrieval']['records'][0].update(pid=77),
            lambda c:c['focusCaptureDiagnostic']['snapshot']['retrieval']['records'][0]['pluginOrigin'].update(finishedCounter=101)):
            r=self.report();later=copy.deepcopy(r['tests'][0]);later['case']='ime-calc-focus-02';r['tests'].append(later);mutate(r['tests'][0])
            with self.assertRaises(AssertionError):self.m.select(r)
    def test_nonreproduction_is_explicit_and_not_a_caller_claim(self):
        r=self.report();r['tests'][0].update(success=True,error=None)
        r['tests']=[dict(copy.deepcopy(r['tests'][0]),case=f'ime-calc-focus-{i:02d}') for i in range(1,4)]
        result=self.m.select(r);self.assertEqual(result['status'],'not-reproduced');self.assertEqual(result['rvas'],[])

if __name__=='__main__':unittest.main()
