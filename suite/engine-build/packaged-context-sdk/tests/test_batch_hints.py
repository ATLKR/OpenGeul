"""Synthetic B-mode contracts. Actual CMD/SDK evidence is separate."""
import copy
import hashlib
import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import run_sdk_gate as gate
import ci_entry as entry
import test_ci_wiring as fixtures

MODE='source-assert'
INPUTS='369bfbf3caaf51867e9dc5b330ad0f8206fa1c04e4f7378575c6922d055bbb04'
FLAGS=dict(originalSdkGateExecuted=False,acceptanceEligible=False,qualification=False,canService=False)

def binding():return entry.require_context(fixtures.environment(),'x64')
def controller():
    return dict(schemaVersion=4,kind='sdk-source-assert-controller',mode=MODE,binding=binding(),
      approvedCodeManifestSha256='1'*64,expectedSourceInputsSha256=INPUTS,originalSdkReportSha256=None,
      instrumentedStage=3,failureCode=5,helperFailureCode=10,cancelled=False,instrumentedChecksPassed=False,
      sourceInputsVerified=True,envelopeKnown=True,envelopeCompleted=False,envelopeCleanupProved=True,
      envelopeForcedCleanup=False,envelopeExitCode=2,helperPhaseResults=[],helperPreCleanup=[],
      failureObservation=None,**FLAGS)
def private():
    return dict(schemaVersion=4,kind='sdk-source-assert-private',mode=MODE,architectureCode=0x8664,
      approvedCodeManifestSha256='1'*64,expectedSourceInputsSha256=INPUTS,
      canary=dict(statusCode=0,reasonCode=1,returns=None),phases=[],compilerDiagnostics=None,childWritable=True,
      authority=False,compilerInvocationProved=False,**FLAGS)
def sidecar(raw):
    return dict(schemaVersion=4,kind='sdk-source-assert-sidecar',mode=MODE,binding=binding(),
      approvedCodeManifestSha256='1'*64,expectedSourceInputsSha256=INPUTS,originalSdkReportSha256=None,
      controllerReceiptSha256=hashlib.sha256(raw).hexdigest(),unavailableReasonCode=0,
      observation=private(),childWritable=True,authority=False,compilerInvocationProved=False,**FLAGS)

class BatchCodecTests(unittest.TestCase):
    def function(self,name):
        self.assertTrue(hasattr(gate,name),'Explicit B codec required')
        return getattr(gate,name)
    def test_canary_records_observed_status_after_the_marker(self):
        fn=self.function('decode_batch_canary')
        self.assertEqual(fn(b'1 0\r\n2 2\r\n3 5\r\n',b'0\r\n2\r\n5\r\n'),dict(statusCode=1,reasonCode=0,returns=[0,2,5]))
    def test_canary_constants_cannot_stand_in_for_restored_status(self):
        fn=self.function('decode_batch_canary')
        for observed in(b'0\r\n0\r\n5\r\n',b'0\r\n2\r\n',b'0\r\n2\r\n5\r\n0\r\n'):
            with self.subTest(case=len(observed)),self.assertRaises(gate.GateFailure):fn(b'1 0\r\n2 2\r\n3 5\r\n',observed)
    def test_canary_unknown_type_path_duplicate_and_oversize_reject(self):
        fn=self.function('decode_batch_canary')
        for raw in(True,'SYNTHETIC',b'',b'C:\\foreign\r\n',b'1 0\r\n1 2\r\n3 5\r\n',b'0'*65):
            with self.subTest(case=type(raw).__name__),self.assertRaises(gate.GateFailure):fn(raw,b'0\r\n2\r\n5\r\n')
    def test_closed_full_trace_and_original_vs_error_stop(self):
        fn=self.function('decode_batch_trace')
        self.assertEqual(fn(b'1 0\r\n2 0\r\n3 0\r\n4 2\r\n'),dict(statusCode=1,reasonCode=0,rows=[[1,0],[2,0],[3,0],[4,2]]))
        self.assertEqual(fn(b'1 0\r\n2 2\r\n'),dict(statusCode=2,reasonCode=0,rows=[[1,0],[2,2]]))
    def test_partial_or_impossible_trace_cannot_be_completed_proof(self):
        fn=self.function('decode_batch_trace')
        for raw in(b'1 0\r\n',b'1 0\r\n2 0\r\n',b'1 0\r\n2 0\r\n3 0\r\n',b'1 0\r\n2 2\r\n3 0\r\n4 2\r\n',b'1 0\r\n3 0\r\n',b'1 00\r\n2 2\r\n'):
            with self.subTest(case=len(raw)),self.assertRaises(gate.GateFailure):fn(raw)
    def test_canonical_signed_and_u32_codes_do_not_weaken_vs_guard(self):
        fn=self.function('decode_batch_trace')
        self.assertEqual(fn(b'1 0\r\n2 -1\r\n3 0\r\n4 4294967295\r\n')['rows'][-1],[4,4294967295])
        for raw in(b'1 0\r\n2 4294967296\r\n',b'1 0\r\n2 -2147483649\r\n',b'1 0\r\n2 +2\r\n',b'1 0\r\n2 -0\r\n'):
            with self.assertRaises(gate.GateFailure):fn(raw)
    def test_canary_template_restores_discovery_exit_and_observes_return(self):
        text=self.function('batch_discovery_template')(r'C:\VS\vswhere.exe')
        self.assertIn('set "OPENGEUL_SDK_DISCOVERY_RC=%errorlevel%"',text)
        self.assertIn('exit /b %OPENGEUL_SDK_DISCOVERY_RC%',text)
        for code in(0,2,5):self.assertIn('call :sdk_canary_return '+str(code),text)
        self.assertEqual(text.count('echo %errorlevel%'),3)
        self.assertIn('exit /b %2',text)
    def test_marked_template_preserves_original_guard_and_compiler_command(self):
        fn=self.function('batch_compile_template')
        base='@echo off\ncall "C:\\VS\\VsDevCmd.bat" -no_logo\nif errorlevel 1 exit /b %errorlevel%\nset "CL="\n"C:\\VS\\cl.exe" /W4 /WX /c "C:\\owned\\context.cpp"\nexit /b %errorlevel%\n'
        value=fn(base,3)
        self.assertIn('if errorlevel 1 exit /b %errorlevel%',value)
        self.assertIn('"C:\\VS\\cl.exe" /W4 /WX /c "C:\\owned\\context.cpp"',value)
        self.assertEqual(value.count('call :serializer_phase'),4)
        self.assertIn('exit /b %2',value)

class BatchSchemaTests(unittest.TestCase):
    def function(self,name):
        self.assertTrue(hasattr(entry,name),'Separate strict B contract required')
        return getattr(entry,name)
    def test_controller_cannot_be_normal_sdk_report(self):
        fn=self.function('validate_batch_controller');value=controller()
        self.assertEqual(fn(value,binding(),'1'*64),value)
        for delta in({'kind':'packaged-context-sdk-ci'},{'mode':'normal'},{'originalSdkGateExecuted':True},
          {'originalSdkReportSha256':'a'*64},{'qualification':True},{'sdkGatePassed':True}):
            with self.subTest(case=list(delta)),self.assertRaises(entry.CiFailure):fn({**value,**delta},binding(),'1'*64)
    def test_controller_source_attempt_arch_and_hash_are_external(self):
        fn=self.function('validate_batch_controller')
        for key,value in(('sourceCommit','b'*40),('runAttempt',2),('architectureCode',0xaa64),('runId',124)):
            changed=controller();changed['binding'][key]=value
            with self.assertRaises(entry.CiFailure):fn(changed,binding(),'1'*64)
        with self.assertRaises(entry.CiFailure):fn(controller(),binding(),'2'*64)
    def test_missing_unknown_bool_partial_and_normal_fields_reject(self):
        fn=self.function('validate_batch_controller');base=controller()
        cases=[{k:v for k,v in base.items()if k!='cancelled'},{**base,'unproved':0},{**base,'failureCode':True},
          {**base,'helperPhaseResults':[{}]},{**base,'mode':False},{**base,'expectedSourceInputsSha256':'f'*64}]
        for value in cases:
            with self.assertRaises(entry.CiFailure):fn(value,binding(),'1'*64)
    def test_sidecar_joins_actual_b_bytes_without_faking_original_sha(self):
        fn=self.function('validate_batch_sidecar');raw=json.dumps(controller(),separators=(',',':')).encode()
        value=sidecar(raw);self.assertEqual(fn(value,raw,binding(),'1'*64),value)
        for delta in({'controllerReceiptSha256':'f'*64},{'originalSdkReportSha256':'a'*64},{'authority':True},
          {'compilerInvocationProved':True},{'childWritable':False},{'kind':'packaged-context-sdk-ci'}):
            with self.assertRaises(entry.CiFailure):fn({**value,**delta},raw,binding(),'1'*64)

    def test_private_canary_boolean_partial_and_path_data_reject(self):
        fn=self.function('validate_batch_private');base=private()
        for delta in({'architectureCode':True},{'canary':{'statusCode':1,'reasonCode':0,'returns':[0,False,5]}},
          {'canary':{'statusCode':1,'reasonCode':0,'returns':[0,2]}},{'path':r'C:\foreign'},
          {'phases':[{'phaseCode':3,'enabled':False,'statusCode':0,'reasonCode':1,'rows':None}]}):
            with self.assertRaises(entry.CiFailure):fn({**base,**delta},controller(),'1'*64)
    def test_explicit_unavailable_is_not_partial_schema_acceptance(self):
        fn=self.function('validate_batch_sidecar');raw=json.dumps(controller(),separators=(',',':')).encode();value=sidecar(raw)
        value.update(observation=None,unavailableReasonCode=7);self.assertEqual(fn(value,raw,binding(),'1'*64),value)
        for delta in({'unavailableReasonCode':0},{'observation':{}},{'unavailableReasonCode':True}):
            with self.assertRaises(entry.CiFailure):fn({**value,**delta},raw,binding(),'1'*64)

    def test_positive_compile_trace_requires_matching_retired_phase_row(self):
        fn=self.function('validate_batch_private');value=private();value['canary']=dict(statusCode=1,reasonCode=0,returns=[0,2,5])
        value['phases']=[dict(phaseCode=3,enabled=True,statusCode=1,reasonCode=0,rows=[[1,0],[2,0],[3,0],[4,2]])]
        c=controller();rows=fixtures.success_fixture()['phaseResults'][:2]
        rows[1].update(completed=False,forcedCleanup=True,exitCode=2,failureCode=10)
        c['helperPhaseResults']=entry.project_helper_phases(rows);c['helperPreCleanup']=[None,None]
        self.assertEqual(fn(value,c,'1'*64),value)
        for key,bad in(('cleanupProved',False),('rootExitObserved',False),('jobEmptyObserved',False),('identityRechecked',False),('handlesClosed',3)):
            changed=copy.deepcopy(c);changed['helperPhaseResults'][1][key]=bad
            with self.subTest(field=key),self.assertRaises(entry.CiFailure):fn(value,changed,'1'*64)

    def test_positive_hints_cannot_contradict_outer_cleanup_or_cancellation(self):
        fn=self.function('validate_batch_private');value=private();value['canary']=dict(statusCode=1,reasonCode=0,returns=[0,2,5])
        value['phases']=[dict(phaseCode=3,enabled=True,statusCode=1,reasonCode=0,rows=[[1,0],[2,0],[3,0],[4,2]])]
        c=controller();c['helperPhaseResults']=entry.project_helper_phases(fixtures.success_fixture()['phaseResults'][:2]);c['helperPreCleanup']=[None,None]
        self.assertEqual(fn(value,c,'1'*64),value)
        for key,bad in(('envelopeKnown',False),('envelopeCleanupProved',False),('cancelled',True)):
            changed={**c,key:bad}
            with self.subTest(field=key),self.assertRaises(entry.CiFailure):fn(value,changed,'1'*64)


class BatchRetirementTests(unittest.TestCase):
    def tracker(self,root):
        self.assertTrue(hasattr(gate,'BatchObservation'),'Explicit instrumented tracker required')
        return gate.BatchObservation(Path(root),0x8664,'1'*64,100.,clock=lambda:1.)
    def row(self,*,complete=True):
        return dict(completed=complete,cleanupProved=True,forcedCleanup=not complete,rootExitObserved=True,
          jobEmptyObserved=True,identityRechecked=True,handlesClosed=4,exitCode=0 if complete else 2)
    def reader(self,path,limit):
        self.assertEqual(limit,64)
        if path.name=='sdk-canary.phase':return b'1 0\r\n2 2\r\n3 5\r\n'
        if path.name=='sdk-canary.return':return b'0\r\n2\r\n5\r\n'
        if path.name=='sdk-port.phase':return b'1 0\r\n2 0\r\n3 0\r\n4 2\r\n'
        raise AssertionError('Unexpected fixed leaf')
    def test_failed_but_retired_compile_still_collects_untrusted_trace(self):
        with tempfile.TemporaryDirectory()as temporary:
            tracker=self.tracker(temporary)
            with mock.patch.object(gate.tools,'read',side_effect=self.reader):
                tracker.collect(1,self.row())
                base='@echo off\ncall "C:\\VS\\dev.cmd"\nif errorlevel 1 exit /b %errorlevel%\n"C:\\VS\\cl.exe" /c fixed.cpp\nexit /b %errorlevel%\n'
                self.assertNotEqual(tracker.template(base,3),base)
                tracker.collect(3,self.row(complete=False))
            self.assertEqual(tracker.value['phases'][0]['rows'][-1],[4,2])
            self.assertFalse(tracker.value['authority']);self.assertFalse(tracker.value['compilerInvocationProved'])
    def test_uncertain_retirement_performs_no_hint_io(self):
        with tempfile.TemporaryDirectory()as temporary:
            tracker=self.tracker(temporary);row=self.row();row['cleanupProved']=False
            with mock.patch.object(gate.tools,'read',side_effect=AssertionError('No read'))as read:
                tracker.collect(1,row)
            self.assertEqual(read.call_count,0);self.assertEqual(tracker.value['canary']['statusCode'],2)
    def test_canary_mismatch_keeps_original_template(self):
        with tempfile.TemporaryDirectory()as temporary:
            tracker=self.tracker(temporary)
            with mock.patch.object(gate.tools,'read',return_value=b'0\r\n0\r\n0\r\n'):
                tracker.collect(1,self.row())
            base='SYNTHETIC-UNCHANGED';self.assertEqual(tracker.template(base,3),base)
    def test_deadline_exhausted_prevents_new_io(self):
        with tempfile.TemporaryDirectory()as temporary:
            tracker=self.tracker(temporary);tracker.clock=lambda:100.
            with mock.patch.object(gate.tools,'read')as read:tracker.collect(1,self.row())
            self.assertEqual(read.call_count,0);self.assertEqual(tracker.value['canary']['reasonCode'],5)
    def test_ordinary_read_fault_does_not_replace_pending_primary(self):
        with tempfile.TemporaryDirectory()as temporary:
            tracker=self.tracker(temporary);primary=gate.GateFailure(10)
            try:
                try:raise primary
                finally:
                    with mock.patch.object(gate.tools,'read',side_effect=PermissionError()):tracker.collect(1,self.row())
            except gate.GateFailure as observed:self.assertIs(observed,primary)
            self.assertFalse(tracker.cancelled)
    def test_cancellation_during_diagnostic_preserves_primary_and_stops_io(self):
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with tempfile.TemporaryDirectory()as temporary:
                tracker=self.tracker(temporary);primary=gate.GateFailure(10)
                with mock.patch.object(gate.tools,'read',side_effect=cancel)as read:
                    try:
                        try:raise primary
                        finally:tracker.collect(1,self.row())
                    except gate.GateFailure as observed:self.assertIs(observed,primary)
                    count=read.call_count;tracker.collect(1,self.row());self.assertEqual(read.call_count,count)
                self.assertTrue(tracker.cancelled)
    def test_cancellation_without_primary_propagates_same_object(self):
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with tempfile.TemporaryDirectory()as temporary:
                tracker=self.tracker(temporary)
                with mock.patch.object(gate.tools,'read',side_effect=cancel):
                    try:tracker.collect(1,self.row())
                    except BaseException as observed:self.assertIs(observed,cancel)
                    else:self.fail('Cancellation must propagate')
                self.assertTrue(tracker.cancelled)
    def test_parser_and_storage_faults_do_not_replace_primary(self):
        class Failing(list):
            def append(self,item):raise MemoryError()
        with tempfile.TemporaryDirectory()as temporary:
            tracker=self.tracker(temporary)
            with mock.patch.object(gate.tools,'read',side_effect=self.reader):tracker.collect(1,self.row())
            tracker.value['phases']=Failing();tracker.template('SYNTHETIC',3);primary=gate.GateFailure(10)
            try:
                try:raise primary
                finally:
                    with mock.patch.object(gate.tools,'read',side_effect=self.reader):tracker.collect(3,self.row(complete=False))
            except gate.GateFailure as observed:self.assertIs(observed,primary)
            self.assertIsNone(tracker.value)

class InstrumentedDriverTests(unittest.TestCase):
    def helper(self,**changes):
        self.assertTrue(hasattr(gate,'execute_instrumented'),'Separate B driver required')
        import test_command_lease_wiring as wiring
        import approved_launch as launch
        with mock.patch.object(launch,'require_batch_admission',lambda context,root:launch.require_admission(context,root)),mock.patch.object(gate,'execute',gate.execute_instrumented):
            return wiring.CommandLeaseWiringTests().helper(**changes)
    def test_unavailable_canary_stays_instrumented_without_normal_success_label(self):
        events,lease,result=self.helper()
        self.assertEqual(result['kind'],'sdk-source-assert-helper')
        self.assertEqual(result['mode'],MODE);self.assertFalse(result['originalSdkGateExecuted'])
        self.assertNotIn('sdkGatePassed',result);self.assertNotIn('nativeSdkCompiled',result)
        self.assertTrue(result['instrumentedChecksPassed']);self.assertFalse(result['qualification'])
        self.assertEqual(lease.close_count,1);self.assertEqual(len([e for e in events if e[0]=='run']),5)
        self.assertTrue(all(not row['enabled']for row in result['batchObservation']['phases']))
    def test_instrumented_deadlines_do_not_extend_original_windows(self):
        events,lease,result=self.helper()
        rows=[e[1]for e in events if e[0]=='run'];self.assertEqual(len(rows),5)
        self.assertTrue(all(end<=result['deadline']for end in rows))
        self.assertEqual(result['deadline']-result['startedAt'],180.)
    def test_diagnostic_failure_keeps_original_instrumented_outcome(self):
        self.assertTrue(hasattr(gate,'execute_instrumented'),'Separate B driver required')
        with mock.patch.object(gate.BatchObservation,'collect',side_effect=MemoryError()):events,lease,result=self.helper()
        self.assertTrue(result['instrumentedChecksPassed']);self.assertIsNone(result['batchObservation'])
        self.assertEqual(lease.close_count,1)
    def test_cancellation_stops_before_next_child_and_closes_once(self):
        self.assertTrue(hasattr(gate,'execute_instrumented'),'Separate B driver required')
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with mock.patch.object(gate.BatchObservation,'collect',side_effect=cancel):events,lease,result=self.helper()
            self.assertTrue(result['cancelled']);self.assertFalse(result['instrumentedChecksPassed'])
            self.assertEqual(len([e for e in events if e[0]=='run']),1);self.assertEqual(lease.close_count,1)

    def test_diagnostic_cancellation_cannot_replace_pending_lease_primary(self):
        self.assertTrue(hasattr(gate,'execute_instrumented'),'Separate B driver required')
        import test_command_lease_wiring as wiring
        original=wiring.Lease.verify
        def verify(lease,*,deadline=None):
            if any(e[0]=='run'for e in lease.events):raise gate.GateFailure(10)
            return original(lease,deadline=deadline)
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with mock.patch.object(wiring.Lease,'verify',verify),mock.patch.object(gate.BatchObservation,'collect',side_effect=cancel):events,lease,result=self.helper()
            self.assertEqual(result['failureCode'],10);self.assertTrue(result['cancelled'])
            self.assertEqual(len([e for e in events if e[0]=='run']),1);self.assertEqual(lease.close_count,1)

    def test_final_diagnostic_copy_cancellation_cannot_skip_original_close(self):
        import test_command_lease_wiring as wiring
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            class Tracker:
                cancelled=False;reason=0
                def __init__(self,*args,**kwargs):self.capture=__import__('types').SimpleNamespace(cleanup_unknown=False,bind_sdk=lambda sdk,architecture:None)
                def template(self,original,phase):return original
                def collect(self,phase,row):pass
                @property
                def value(self):raise cancel
            original=wiring.Lease.close;closes=[]
            def close(lease):closes.append(1);return original(lease)
            with mock.patch.object(gate,'BatchObservation',Tracker),mock.patch.object(wiring.Lease,'close',close):
                try:events,lease,result=self.helper()
                except BaseException:self.fail('Diagnostic finalization must pass through owned cleanup')
            self.assertEqual(len(closes),1);self.assertEqual(len([e for e in events if e[0]=='run']),5);self.assertTrue(result['cancelled']);self.assertIsNone(result['batchObservation'])

    def test_explicit_runner_cancellation_stops_all_five_phases_even_with_exit1(self):
        for phase in range(1,6):
            with self.subTest(phase=phase):
                events,lease,result=self.helper(cancel_row_phase=phase)
                self.assertTrue(result['cancelled']);self.assertFalse(result['instrumentedChecksPassed'])
                self.assertEqual(len([e for e in events if e[0]=='run']),phase);self.assertEqual(lease.close_count,1)


class BatchPublicationTests(unittest.TestCase):
    def api(self,name):self.assertTrue(hasattr(entry,name),'Explicit B publication/verification required');return getattr(entry,name)
    def test_fixed_two_files_join_actual_controller_bytes(self):
        publish=self.api('batch_publish');verify=self.api('verify_batch_files')
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);value=controller();self.assertTrue(publish(root,value,private(),deadline=10.,clock=lambda:1.))
            out=verify(root,binding(),'1'*64);self.assertTrue(out['admitted'])
            self.assertEqual(out['controllerSha256'],hashlib.sha256((root/'controller.numeric.json').read_bytes()).hexdigest())
            self.assertEqual({p.name for p in root.iterdir()},{'controller.numeric.json','source-assertion.json'})
    def test_corrupt_private_data_is_explicit_unavailable_not_completed_proof(self):
        publish=self.api('batch_publish');verify=self.api('verify_batch_files')
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);self.assertTrue(publish(root,controller(),{'unproved':True},deadline=10.,clock=lambda:1.))
            value=json.loads((root/'source-assertion.json').read_bytes());self.assertIsNone(value['observation'])
            self.assertEqual(value['unavailableReasonCode'],4);self.assertTrue(verify(root,binding(),'1'*64)['admitted'])
    def test_manual_missing_partial_duplicate_or_wrong_join_is_rejected(self):
        publish=self.api('batch_publish');verify=self.api('verify_batch_files')
        for mode in('missing','partial','duplicate','hash','bool'):
            with tempfile.TemporaryDirectory()as temporary:
                root=Path(temporary);publish(root,controller(),private(),deadline=10.,clock=lambda:1.);p=root/'source-assertion.json';v=json.loads(p.read_bytes())
                if mode=='missing':p.unlink()
                elif mode=='partial':p.write_bytes(b'{')
                elif mode=='duplicate':p.write_bytes(b'{"schemaVersion":1,'+p.read_bytes()[1:])
                else:
                    v['controllerReceiptSha256']='f'*64 if mode=='hash'else v['controllerReceiptSha256']
                    if mode=='bool':v['unavailableReasonCode']=False
                    p.write_text(json.dumps(v))
                with self.assertRaises((entry.CiFailure,FileNotFoundError)):verify(root,binding(),'1'*64)
    def test_publication_cancellation_preserves_pending_primary_and_stops(self):
        publish=self.api('batch_publish');self.api('_batch_write')
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with tempfile.TemporaryDirectory()as temporary:
                value=controller();value['failureCode']=10;primary=gate.GateFailure(10)
                with mock.patch.object(entry,'_batch_write',side_effect=cancel)as write:
                    try:
                        try:raise primary
                        finally:publish(Path(temporary),value,private(),deadline=10.,clock=lambda:1.)
                    except gate.GateFailure as observed:self.assertIs(observed,primary)
                self.assertEqual(write.call_count,1);self.assertTrue(value['cancelled']);self.assertEqual(value['failureCode'],10)
    def test_unhandled_publication_cancellation_propagates_same_object(self):
        publish=self.api('batch_publish');self.api('_batch_write')
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with tempfile.TemporaryDirectory()as temporary,mock.patch.object(entry,'_batch_write',side_effect=cancel)as write:
                try:publish(Path(temporary),controller(),private(),deadline=10.,clock=lambda:1.)
                except BaseException as observed:self.assertIs(observed,cancel)
                else:self.fail('Cancellation must not be swallowed')
                self.assertEqual(write.call_count,1)


    def test_expired_publication_performs_no_new_write_and_preserves_pending_primary(self):
        publish=self.api('batch_publish');primary=gate.GateFailure(10)
        with tempfile.TemporaryDirectory()as temporary,mock.patch.object(entry,'_batch_write')as write:
            self.assertFalse(publish(Path(temporary),controller(),private(),deadline=1.,clock=lambda:1.))
            try:
                try:raise primary
                finally:publish(Path(temporary),controller(),private(),deadline=1.,clock=lambda:1.)
            except gate.GateFailure as observed:self.assertIs(observed,primary)
        self.assertEqual(write.call_count,0)
    def test_deadline_between_files_prevents_second_write(self):
        publish=self.api('batch_publish');now=[1.]
        def write(*args,**kwargs):now[0]=10.
        with tempfile.TemporaryDirectory()as temporary,mock.patch.object(entry,'_batch_write',side_effect=write)as written:
            self.assertFalse(publish(Path(temporary),controller(),private(),deadline=10.,clock=lambda:now[0]))
        self.assertEqual(written.call_count,1)
    def test_expired_fixed_writer_does_not_begin_path_io(self):
        write=self.api('_batch_write')
        with mock.patch.object(entry,'_regular')as regular:
            with self.assertRaises(entry.CiFailure):write(Path('controller.numeric.json'),b'{}',deadline=1.,clock=lambda:1.)
        self.assertEqual(regular.call_count,0)
class BatchBootstrapTests(unittest.TestCase):
    def test_admitted_prefix_dispatches_b_without_calling_normal_main(self):
        import approved_launch as launch
        self.assertTrue(hasattr(gate,'batch_main'),'Explicit B helper entry required')
        fake=__import__('types').SimpleNamespace(main=mock.Mock(side_effect=AssertionError('Normal must not run')),batch_main=mock.Mock(return_value=130))
        fake_sys=__import__('types').SimpleNamespace(flags=__import__('types').SimpleNamespace(isolated=True),dont_write_bytecode=True,modules=sys.modules,path=[])
        with mock.patch.object(launch,'sys',fake_sys),mock.patch.object(launch,'admit_code',return_value=object()),mock.patch.object(launch,'admit_batch_code',return_value=object(),create=True),mock.patch.object(launch.importlib,'import_module',return_value=fake):
            # Avoid preloaded gate-module rejection without reading environment.
            removed={k:sys.modules.pop(k)for k in('run_sdk_gate','supervisor','toolchain','owned_job_win32')if k in sys.modules}
            try:code=launch.main(['--approved-manifest',str(ROOT/'approved-sdk-code.json'),'--expected-approved-manifest-sha256','1'*64,'--source-assert','--architecture','x64'])
            finally:sys.modules.update(removed)
        self.assertEqual(code,130);self.assertEqual(fake.main.call_count,0);self.assertEqual(fake.batch_main.call_count,1)

    def test_batch_admission_propagates_cancel_and_normal_admission_remains_closed(self):
        import approved_launch as launch
        self.assertTrue(hasattr(launch,'admit_batch_code'),'B admission must preserve cancellation')
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with mock.patch.object(launch,'_verify',side_effect=cancel):
                try:launch.admit_batch_code(ROOT,ROOT/'approved-sdk-code.json','1'*64)
                except BaseException as observed:self.assertIs(observed,cancel)
                else:self.fail('Cancellation must propagate')
                with self.assertRaises(launch.ApprovalFailure):launch.admit_code(ROOT,ROOT/'approved-sdk-code.json','1'*64)
    def test_batch_bootstrap_admission_cancel_returns130_before_import(self):
        import approved_launch as launch
        self.assertTrue(hasattr(launch,'admit_batch_code'),'B admission required')
        fake_sys=__import__('types').SimpleNamespace(flags=__import__('types').SimpleNamespace(isolated=True),dont_write_bytecode=True,modules=sys.modules,path=[])
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with mock.patch.object(launch,'sys',fake_sys),mock.patch.object(launch,'admit_batch_code',side_effect=cancel),mock.patch.object(launch.importlib,'import_module')as imported:
                code=launch.main(['--approved-manifest',str(ROOT/'approved-sdk-code.json'),'--expected-approved-manifest-sha256','1'*64,'--source-assert'])
            self.assertEqual(code,130);self.assertEqual(imported.call_count,0)
    def test_batch_require_admission_preserves_cancel_and_exact_context_type(self):
        import approved_launch as launch
        self.assertTrue(hasattr(launch,'require_batch_admission'),'B admission validation required')
        with self.assertRaises(launch.ApprovalFailure):launch.require_batch_admission(object(),ROOT)
        context=object.__new__(launch.CodeAdmission)
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with mock.patch.object(launch.CodeAdmission,'require_root',side_effect=cancel):
                try:launch.require_batch_admission(context,ROOT)
                except BaseException as observed:self.assertIs(observed,cancel)
                else:self.fail('Cancellation must propagate')

    def test_b_helper_admission_cancel_is_not_downgraded_to_approval_failure(self):
        import approved_launch as launch
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with mock.patch.object(launch,'require_batch_admission',side_effect=cancel),mock.patch.object(gate.tools,'verify_bundle')as bundle:
                code=gate.batch_main(['--architecture','x64','--source-bundle',str(ROOT/'frozen-v2'),'--work-root',str(ROOT/'uncreated'),'--output',str(ROOT/'uncreated/sdk-batch.numeric.json')])
            self.assertEqual(code,130);self.assertEqual(bundle.call_count,0)

def helper_receipt():
    value=fixtures.success_fixture()
    value.update(schemaVersion=4,kind='sdk-source-assert-helper',mode=MODE,originalSdkGateExecuted=False,
      acceptanceEligible=False,sourceInputsVerified=True,batchObservation=None,batchUnavailableReasonCode=7)
    for old,new in(('sdkGatePassed','instrumentedChecksPassed'),('nativeSdkCompiled','instrumentedPortObjectVerified'),
      ('nativeLinked','instrumentedLinkVerified'),('negativeSmokePassed','instrumentedNegativeSmokePassed')):value[new]=value.pop(old)
    return value

class BatchControllerTests(unittest.TestCase):
    def api(self,name):self.assertTrue(hasattr(entry,name),'Explicit B controller required');return getattr(entry,name)
    def test_b_helper_can_use_shared_structural_checks_but_not_normal_kind(self):
        fn=self.api('validate_batch_helper');raw=helper_receipt()
        self.assertIs(fn(raw,'x64','1'*64,180.,raw['compileInputs']),raw)
        for delta in({'kind':'packaged-context-sdk-negative-gate'},{'originalSdkGateExecuted':True},
          {'instrumentedChecksPassed':True,'instrumentedPortObjectVerified':False},{'mode':'normal'}):
            with self.assertRaises(entry.CiFailure):fn({**raw,**delta},'x64','1'*64,180.,raw['compileInputs'])
    def test_controller_success_still_has_no_original_sdk_execution(self):
        fn=self.api('batch_controller');raw=helper_receipt();outer=dict(completed=True,cleanupProved=True,forcedCleanup=False,exitCode=0)
        value=fn(binding(),outer,raw,'1'*64)
        entry.validate_batch_controller(value,binding(),'1'*64)
        self.assertTrue(value['instrumentedChecksPassed']);self.assertFalse(value['originalSdkGateExecuted'])
        self.assertIsNone(value['originalSdkReportSha256']);self.assertNotIn('sdkGatePassed',value)
    def test_outer_failure_never_overrides_helper_failure_with_success(self):
        fn=self.api('batch_controller');raw=helper_receipt();raw.update(instrumentedChecksPassed=False,failureCode=10,stage=3)
        value=fn(binding(),dict(completed=False,cleanupProved=True,forcedCleanup=False,exitCode=2),raw,'1'*64,failure=5)
        self.assertEqual(value['failureCode'],5);self.assertEqual(value['helperFailureCode'],10)
        self.assertFalse(value['instrumentedChecksPassed'])
    def test_cancellation_gets_reserved_control_exit_without_normal_sdk_call(self):
        fn=self.api('batch_main');self.api('_batch_context')
        with mock.patch.object(entry,'_batch_context',side_effect=KeyboardInterrupt()),mock.patch.object(entry,'main',side_effect=AssertionError('Normal must not run'))as normal:
            self.assertEqual(fn([]),130)
        self.assertEqual(normal.call_count,0)
    def test_verifier_cli_malformed_or_untrusted_context_is_closed(self):
        fn=self.api('batch_verify_main');self.api('_batch_context')
        for error in(entry.CiFailure(3),FileNotFoundError()):
            with mock.patch.object(entry,'_batch_context',side_effect=error),mock.patch('builtins.print')as emitted:
                self.assertEqual(fn([]),1)
            args=emitted.call_args.args;self.assertEqual(len(args),1);data=json.loads(args[0])
            self.assertEqual(set(data),{'schemaVersion','admitted','controllerSha256','sidecarSha256','reasonCode'})
            self.assertFalse(data['admitted']);self.assertIsNone(data['controllerSha256']);self.assertIsNone(data['sidecarSha256'])
    def test_invalid_helper_packet_does_not_replace_its_validation_failure(self):
        fn=self.api('batch_main')
        import toolchain,owned_job_win32,supervisor,contextlib,types
        import test_command_lease_wiring as wiring
        events=[];lease=wiring.Lease(events)
        args=types.SimpleNamespace(architecture='x64',expected_approved_manifest_sha256='1'*64)
        class Admission:
            def read_approved(self,name):return(ROOT/name).read_bytes()
            def require_root(self,root):return True
        class Envelope:
            def run(self,command,cwd,environment,deadline):
                out=Path(command[command.index('--output')+1]);out.parent.mkdir();out.write_bytes(b'{"unproved":true}')
                return dict(completed=False,cleanupProved=True,forcedCleanup=False,exitCode=2,rootExitObserved=True,jobEmptyObserved=True,identityRechecked=True,handlesClosed=4)
        with tempfile.TemporaryDirectory()as temporary,contextlib.ExitStack()as stack:
            temp=Path(temporary);repo=temp/'repo';repo.mkdir();runtime=temp/'runtime';runtime.mkdir()
            locations={'system':r'C:\Windows','programFiles':r'C:\Program Files','programFilesX86':r'C:\Program Files (x86)','commandLease':lease}
            for obj,name,value in ((entry,'_batch_context',lambda argv:(args,ROOT,repo,binding(),Admission())),
              (entry.os,'environ',{'RUNNER_TEMP':str(runtime)}),(toolchain,'system_locations',lambda *a,**kw:locations),
              (owned_job_win32,'NativeApi',lambda:object()),(supervisor,'child_environment',lambda *a:{}),(entry,'EnvelopeRunner',lambda api:Envelope())):stack.enter_context(mock.patch.object(obj,name,value))
            publish=stack.enter_context(mock.patch.object(entry,'batch_publish',return_value=True))
            try:code=fn([])
            except Exception:self.fail('Malformed helper must retain its original closed validation failure')
        self.assertEqual(code,1);self.assertEqual(publish.call_args.args[1]['failureCode'],4)
        self.assertIsNone(publish.call_args.args[1]['helperFailureCode']);self.assertEqual(lease.close_count,1)
    def test_verifier_close_cancellation_returns130_without_public_output(self):
        fn=self.api('batch_verify_main')
        import toolchain,types
        args=types.SimpleNamespace(architecture='x64',expected_approved_manifest_sha256='1'*64)
        admission=types.SimpleNamespace(require_root=lambda root:None)
        lease=types.SimpleNamespace(close=mock.Mock(side_effect=KeyboardInterrupt()))
        with mock.patch.object(entry,'_batch_context',return_value=(args,ROOT,ROOT.parents[2],binding(),admission)), \
          mock.patch.object(toolchain,'system_locations',return_value={'commandLease':lease}), \
          mock.patch.object(entry,'verify_batch_files',return_value=dict(schemaVersion=1,admitted=True,controllerSha256='a'*64,sidecarSha256='b'*64,reasonCode=0)), \
          mock.patch.object(entry,'check_checkout',return_value=True),mock.patch('builtins.print')as emitted:
            try:code=fn([])
            except BaseException:self.fail('Verifier cancellation requires a reserved control exit')
        self.assertEqual(code,130);self.assertEqual(emitted.call_count,0)

    def test_verifier_replays_source13_before_native_setup_and_after_pair_validation(self):
        import toolchain,types
        args=types.SimpleNamespace(architecture='x64',expected_approved_manifest_sha256='1'*64)
        admission=types.SimpleNamespace(require_root=lambda root:None)
        for failure_call in(1,2):
            calls=[];lease=types.SimpleNamespace(close=mock.Mock(return_value=True))
            def verify(path):
                calls.append(1)
                if len(calls)==failure_call:raise gate.GateFailure(3)
                return True
            with mock.patch.object(entry,'_batch_context',return_value=(args,ROOT,ROOT.parents[2],binding(),admission)), \
              mock.patch.object(toolchain,'verify_bundle',side_effect=verify),mock.patch.object(toolchain,'system_locations',return_value={'commandLease':lease})as locations, \
              mock.patch.object(entry,'verify_batch_files',return_value=dict(schemaVersion=1,admitted=True,controllerSha256='a'*64,sidecarSha256='b'*64,reasonCode=0))as files, \
              mock.patch.object(entry,'check_checkout',return_value=True),mock.patch('builtins.print')as emitted:
                code=entry.batch_verify_main([])
            self.assertEqual(code,1);self.assertFalse(json.loads(emitted.call_args.args[0])['admitted'])
            self.assertEqual(len(calls),failure_call);self.assertEqual(files.call_count,failure_call-1)
            self.assertEqual(locations.call_count,failure_call-1);self.assertEqual(lease.close.call_count,failure_call-1)

class BatchContextTests(unittest.TestCase):
    def context(self,change=None,pins=None):
        import types
        values={**fixtures.environment(),'GITHUB_WORKSPACE':str(ROOT.parents[2])};values.update(change or{})
        class LiteralMapping:
            def __getitem__(self,key):return values[key]
            def get(self,key,default=None):
                return values.get(key,default)
            def copy(self):raise AssertionError('Environment copy forbidden')
            def __iter__(self):raise AssertionError('Environment iteration forbidden')
        expected=[hashlib.sha256((ROOT/'ci_entry.py').read_bytes()).hexdigest(),'2'*64,'3'*64]
        if pins is not None:expected=pins
        argv=['--architecture','x64']
        for name,value in zip(('entry','bootstrap','approved-manifest'),expected):argv.extend(['--expected-'+name+'-sha256',value])
        fake_sys=types.SimpleNamespace(flags=types.SimpleNamespace(isolated=True),dont_write_bytecode=True,platform='win32',version_info=(3,12))
        return LiteralMapping(),fake_sys,argv
    def test_b_external_pins_and_literal_context_are_bound_before_admission(self):
        env,system,argv=self.context();admission=object()
        with mock.patch.object(entry.os,'environ',env),mock.patch.object(entry,'sys',system),mock.patch.object(entry,'check_checkout')as checkout,mock.patch.object(entry,'_batch_code',return_value=admission)as code:
            result=entry._batch_context(argv)
        self.assertIs(result[-1],admission);self.assertEqual(result[3],binding())
        self.assertEqual(code.call_args.args,(ROOT,'2'*64,'3'*64));self.assertEqual(checkout.call_args.args,(ROOT.parents[2],binding()))
    def test_wrong_entry_pin_or_context_is_rejected_before_code_execution(self):
        cases=[self.context(pins=['0'*64,'2'*64,'3'*64]),self.context(change={'GITHUB_RUN_ATTEMPT':'2'}),self.context(change={'GITHUB_SHA':'b'*40})]
        for env,system,argv in cases:
            with mock.patch.object(entry.os,'environ',env),mock.patch.object(entry,'sys',system),mock.patch.object(entry,'check_checkout'),mock.patch.object(entry,'_batch_code')as code:
                with self.assertRaises(entry.CiFailure):entry._batch_context(argv)
            self.assertEqual(code.call_count,0)

class BatchControllerIntegrationTests(unittest.TestCase):
    def run_controller(self,*,cancel=False,uncertain=None,expired=False,cancel_code=130):
        import contextlib,types,toolchain,supervisor,owned_job_win32
        import test_command_lease_wiring as wiring
        now=[1.];lease=wiring.Lease([]);args=types.SimpleNamespace(architecture='x64',expected_approved_manifest_sha256='1'*64)
        class Admission:
            def read_approved(self,name):return(ROOT/name).read_bytes()
            def require_root(self,root):return True
        class Envelope:
            def run(self,command,cwd,environment,deadline):
                if cancel:
                    result=dict(completed=False,cleanupProved=True,forcedCleanup=True,exitCode=cancel_code,cancelled=True,rootExitObserved=True,jobEmptyObserved=True,identityRechecked=True,handlesClosed=4)
                    if uncertain is not None:result[uncertain]=3 if uncertain=='handlesClosed'else False
                    return result
                raw=helper_receipt();raw['compileInputs']=[]
                for index,name in enumerate(('context_observer.hpp','context_observer_windows.cpp','sdk_smoke.hpp','windows_sdk_smoke.cpp'),1):
                    data=(ROOT/('frozen-v2'if index<=2 else'')/name).read_bytes()
                    raw['compileInputs'].append(dict(slot=index,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
                out=Path(command[command.index('--output')+1]);out.parent.mkdir();out.write_text(json.dumps(raw))
                result=dict(completed=True,cleanupProved=True,forcedCleanup=False,exitCode=0,rootExitObserved=True,jobEmptyObserved=True,identityRechecked=True,handlesClosed=4)
                if uncertain is not None:result[uncertain]=3 if uncertain=='handlesClosed'else False
                if expired:now[0]=181.
                return result
        with tempfile.TemporaryDirectory()as temporary,contextlib.ExitStack()as stack:
            temp=Path(temporary);repo=temp/'repo';repo.mkdir();runtime=temp/'runtime';runtime.mkdir()
            locations={'system':r'C:\Windows','programFiles':r'C:\Program Files','programFilesX86':r'C:\Program Files (x86)','commandLease':lease}
            for obj,name,value in((entry,'_batch_context',lambda argv:(args,ROOT,repo,binding(),Admission())),(entry.os,'environ',{'RUNNER_TEMP':str(runtime)}),
              (toolchain,'system_locations',lambda *a,**kw:locations),(supervisor,'child_environment',lambda *a:{}),(owned_job_win32,'NativeApi',lambda:object()),
              (entry,'EnvelopeRunner',lambda api:Envelope()),(entry,'check_checkout',lambda *a:True),(entry.time,'monotonic',lambda:now[0])):
                stack.enter_context(mock.patch.object(obj,name,value))
            reader=stack.enter_context(mock.patch.object(entry,'_read',wraps=entry._read));code=entry.batch_main([])
            public=repo/'.work/packaged-context-sdk-batch-public/windows-2025'
            names=sorted(p.name for p in public.iterdir())
            packets=None if cancel or expired else(json.loads((public/'controller.numeric.json').read_bytes()),json.loads((public/'source-assertion.json').read_bytes()))
            helper_reads=sum(Path(call.args[0]).name=='sdk-batch.numeric.json'for call in reader.call_args_list)
            return code,names,packets,lease.close_count,helper_reads
    def test_successful_instrumentation_publishes_only_separate_nonacceptance_pair(self):
        code,names,packets,closed,reads=self.run_controller()
        self.assertEqual(code,0);self.assertEqual(names,['controller.numeric.json','source-assertion.json']);self.assertEqual(closed,1)
        for packet in packets:
            self.assertFalse(packet['originalSdkGateExecuted']);self.assertFalse(packet['qualification']);self.assertFalse(packet['acceptanceEligible'])
            self.assertIsNone(packet['originalSdkReportSha256'])
        self.assertTrue(packets[0]['instrumentedChecksPassed']);self.assertFalse(packets[1]['authority'])
    def test_child_cancellation_closes_without_helper_read_or_publication(self):
        code,names,packets,closed,reads=self.run_controller(cancel=True)
        self.assertEqual(code,130);self.assertEqual(names,[]);self.assertIsNone(packets);self.assertEqual(closed,1);self.assertEqual(reads,0)

    def test_uncertain_outer_retirement_never_reads_child_writable_helper(self):
        for key in('cleanupProved','rootExitObserved','jobEmptyObserved','identityRechecked','handlesClosed'):
            with self.subTest(field=key):
                code,names,packets,closed,reads=self.run_controller(uncertain=key)
                self.assertEqual(code,1);self.assertEqual(reads,0);self.assertEqual(closed,1)
                self.assertEqual(packets[0]['failureCode'],5);self.assertIsNone(packets[0]['helperPhaseResults'])
                self.assertIsNone(packets[1]['observation']);self.assertFalse(packets[0]['instrumentedChecksPassed'])

    def test_expired_overall_does_not_read_helper_or_publish_new_files(self):
        code,names,packets,closed,reads=self.run_controller(expired=True)
        self.assertEqual(code,1);self.assertEqual(names,[]);self.assertIsNone(packets);self.assertEqual(closed,1);self.assertEqual(reads,0)

    def test_outer_cancelled_flag_has_priority_over_exit1_and_uncertain_cleanup(self):
        for uncertain in(None,'cleanupProved','rootExitObserved','jobEmptyObserved','identityRechecked','handlesClosed'):
            with self.subTest(field=uncertain):
                code,names,packets,closed,reads=self.run_controller(cancel=True,cancel_code=1,uncertain=uncertain)
                self.assertEqual(code,130);self.assertEqual(names,[]);self.assertIsNone(packets);self.assertEqual(closed,1);self.assertEqual(reads,0)

class PortCompilerDiagnosticsTests(unittest.TestCase):
    def capture(self,root,*,now=None):
        self.assertTrue(hasattr(gate,'PortCompilerCapture'),'B2 fixed port capture required')
        return gate.PortCompilerCapture(Path(root),100.,clock=(lambda:1.)if now is None else now)
    def row(self,**changes):
        return dict(completed=False,cleanupProved=True,forcedCleanup=True,rootExitObserved=True,
          jobEmptyObserved=True,identityRechecked=True,handlesClosed=4,cancelled=False,**changes)
    def test_new_profile_and_old_wire_cannot_be_confused(self):
        self.assertEqual(gate.empty_batch_receipt()['schemaVersion'],4)
        self.assertEqual(gate.empty_batch_receipt()['mode'],'source-assert')
        self.assertNotEqual(gate.empty_batch_receipt()['kind'],'sdk-batch-instrumented-helper')
    def test_pure_parser_ast_is_exact_except_function_and_fixed_files_symbol(self):
        import ast
        self.assertTrue(hasattr(gate,'project_compiler_diagnostics'),'Pure parser required')
        source=ROOT.parents[2]/'suite/scripts/ime-finalization-compiler-observation/observe-ime-finalization-compile.py'
        original=next(n for n in ast.parse(source.read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name=='project_diagnostics')
        actual=next(n for n in ast.parse((ROOT/'run_sdk_gate.py').read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name=='project_compiler_diagnostics')
        actual.name=original.name
        for node in ast.walk(actual):
            if isinstance(node,ast.Name)and node.id=='SDK_COMPILER_FILES':node.id='FILES'
        self.assertEqual(ast.dump(actual,include_attributes=False),ast.dump(original,include_attributes=False))
        self.assertEqual(gate.SDK_COMPILER_FILES,('context_observer.hpp','context_observer_windows.cpp','sdk_smoke.hpp','windows_sdk_smoke.cpp'))
    def test_parser_limits_and_unknown_roles_remain_numeric(self):
        self.assertTrue(hasattr(gate,'project_compiler_diagnostics'),'Pure parser required')
        value=gate.project_compiler_diagnostics('context_observer_windows.cpp(7): fatal error C1083: synthetic\nforeign.cpp(8): error C2222: synthetic','cl : command line error D9002: synthetic',Path('C:/owned'))
        self.assertEqual(value['diagnostics'],[dict(streamCode=1,severity=3,kind=1,number=1083,fileCode=2,line=7),dict(streamCode=1,severity=2,kind=1,number=2222,fileCode=0,line=0),dict(streamCode=2,severity=2,kind=2,number=9002,fileCode=0,line=0)])
        value=gate.project_compiler_diagnostics(('error C1001: synthetic\n'*40),'x'*65537,Path('C:/owned'))
        self.assertEqual(len(value['diagnostics']),32);self.assertEqual(value['droppedCount'],8);self.assertEqual(value['scanComplete'],0)
    def test_precreate_is_exclusive_fixed_pair_and_all_fds_are_closed(self):
        with tempfile.TemporaryDirectory()as temp:
            capture=self.capture(temp);self.assertTrue(capture.prepare())
            self.assertEqual(sorted(p.name for p in Path(temp).iterdir()),['sdk-port.stderr','sdk-port.stdout'])
            # An empty ordinary file is distinguishable from no output file.
            result=capture.observe(self.row());self.assertEqual(result['streamStatus'],[1,1]);self.assertEqual(result['streamBytes'],[0,0])
            self.assertEqual(result['projection']['diagnostics'],[])
            for name in('sdk-port.stdout','sdk-port.stderr'):
                with(Path(temp)/name).open('ab')as stream:stream.write(b'x')
    def test_preexisting_file_is_preserved_and_capture_stays_unavailable(self):
        with tempfile.TemporaryDirectory()as temp:
            p=Path(temp)/'sdk-port.stdout';p.write_bytes(b'synthetic-preserved')
            capture=self.capture(temp);self.assertFalse(capture.prepare());self.assertEqual(p.read_bytes(),b'synthetic-preserved')
            self.assertNotIn('1>',capture.redirect('"C:\\VS\\cl.exe" /c fixed.cpp'))
    def test_redirect_only_appends_two_literal_leaves_after_successful_prepare(self):
        with tempfile.TemporaryDirectory()as temp:
            capture=self.capture(temp);self.assertTrue(capture.prepare());command='"C:\\VS\\cl.exe" /c fixed.cpp'
            self.assertEqual(capture.redirect(command),command+' 1>"sdk-port.stdout" 2>"sdk-port.stderr"')
    def test_original_file_id_swap_is_unavailable(self):
        with tempfile.TemporaryDirectory()as temp:
            capture=self.capture(temp);self.assertTrue(capture.prepare())
            p=Path(temp)/'sdk-port.stdout';p.rename(Path(temp)/'retained-original');p.write_bytes(b'error C1001: synthetic')
            value=capture.observe(self.row());self.assertEqual(value['streamStatus'][0],6);self.assertIsNone(value['projection'])
    def test_missing_oversize_utf8_alias_and_changed_links_are_distinct(self):
        for kind,status in(('missing',3),('oversize',4),('encoding',5),('symlink',6),('hardlink',6)):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory()as temp:
                capture=self.capture(temp);self.assertTrue(capture.prepare());p=Path(temp)/'sdk-port.stdout'
                if kind=='missing':p.unlink()
                elif kind=='oversize':p.write_bytes(b'x'*65537)
                elif kind=='encoding':p.write_bytes(b'\xff')
                elif kind=='symlink':p.rename(Path(temp)/'original');p.symlink_to(Path(temp)/'original')
                else:__import__('os').link(p,Path(temp)/'extra-link')
                value=capture.observe(self.row());self.assertEqual(value['streamStatus'][0],status);self.assertIsNone(value['projection'])
    def test_uncertain_retirement_or_cancel_does_not_open_capture(self):
        with tempfile.TemporaryDirectory()as temp:
            capture=self.capture(temp);self.assertTrue(capture.prepare())
            for key in('cleanupProved','rootExitObserved','jobEmptyObserved','identityRechecked'):
                row=self.row();row[key]=False
                with mock.patch.object(gate.os,'open',side_effect=AssertionError('No read'))as opened:
                    value=capture.observe(row)
                self.assertEqual(opened.call_count,0);self.assertEqual(value['streamStatus'],[7,7])
            row=self.row();row['cancelled']=True
            with mock.patch.object(gate.os,'open')as opened:capture.observe(row)
            self.assertEqual(opened.call_count,0)
    def test_deadline_prevents_prepare_and_new_read(self):
        with tempfile.TemporaryDirectory()as temp:
            now=[100.];capture=self.capture(temp,now=lambda:now[0]);self.assertFalse(capture.prepare());self.assertEqual(list(Path(temp).iterdir()),[])
            now[0]=1.;capture=self.capture(temp,now=lambda:now[0]);self.assertTrue(capture.prepare());now[0]=100.
            with mock.patch.object(gate.os,'open')as opened:value=capture.observe(self.row())
            self.assertEqual(opened.call_count,0);self.assertEqual(value['streamStatus'],[8,8])
    def test_capture_cancellation_preserves_pending_primary_and_stops_second_read(self):
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with tempfile.TemporaryDirectory()as temp:
                capture=self.capture(temp);self.assertTrue(capture.prepare());primary=gate.GateFailure(10)
                with mock.patch.object(gate.os,'open',side_effect=cancel)as opened:
                    try:
                        try:raise primary
                        finally:capture.observe(self.row())
                    except gate.GateFailure as observed:self.assertIs(observed,primary)
                self.assertEqual(opened.call_count,1);self.assertTrue(capture.cancelled)
    def test_public_reader_requires_new_capture_key_and_rejects_old_wire(self):
        value=private();value.pop('compilerDiagnostics',None)
        with self.assertRaises(entry.CiFailure):entry.validate_batch_private(value,controller(),'1'*64)
        old=controller();old.update(schemaVersion=1,kind='sdk-batch-instrumented-controller',mode='instrumented-batch-hints')
        with self.assertRaises(entry.CiFailure):entry.validate_batch_controller(old,binding(),'1'*64)

    def diagnostic_pair(self):
        c=controller();rows=fixtures.success_fixture()['phaseResults'][:2]
        rows[1].update(completed=False,forcedCleanup=True,exitCode=2,failureCode=10)
        c['helperPhaseResults']=entry.project_helper_phases(rows);c['helperPreCleanup']=[None,None]
        v=private();v['canary']=dict(statusCode=1,reasonCode=0,returns=[0,2,5]);v['phases']=[dict(phaseCode=3,enabled=True,statusCode=1,reasonCode=0,rows=[[1,0],[2,0],[3,0],[4,2]])]
        v['compilerDiagnostics']=dict(phaseCode=3,prepared=True,streamStatus=[2,1],streamBytes=[40,0],firstC2338Detail=None,firstC2338SourceAssertion=None,projection=dict(scanComplete=1,droppedCount=0,diagnostics=[dict(streamCode=1,severity=3,kind=1,number=1083,fileCode=2,line=7)]))
        return c,v
    def test_capture_packet_is_ordinal_retired_numeric_only_and_bounded(self):
        c,v=self.diagnostic_pair();entry.validate_batch_private(v,c,'1'*64)
        cases=[]
        for key,value in(('phaseCode',4),('prepared',1),('streamStatus',[True,1]),('streamBytes',[65537,0]),('projection',{'raw':'SYNTHETIC'}),('rawOutput','SYNTHETIC')):
            changed=copy.deepcopy(v);changed['compilerDiagnostics'][key]=value;cases.append(changed)
        for field,value in(('scanComplete',True),('droppedCount',True),('diagnostics',[v['compilerDiagnostics']['projection']['diagnostics'][0]]*33)):
            changed=copy.deepcopy(v);changed['compilerDiagnostics']['projection'][field]=value;cases.append(changed)
        changed=copy.deepcopy(v);changed['compilerDiagnostics']['projection']['diagnostics'][0].update(fileCode=0,line=7);cases.append(changed)
        for changed in cases:
            with self.assertRaises(entry.CiFailure):entry.validate_batch_private(changed,c,'1'*64)
        for key in('cleanupProved','rootExitObserved','jobEmptyObserved','identityRechecked'):
            changed=copy.deepcopy(c);changed['helperPhaseResults'][1][key]=False
            with self.assertRaises(entry.CiFailure):entry.validate_batch_private(v,changed,'1'*64)
    def test_unavailable_and_empty_are_not_synthesized_into_success(self):
        c,v=self.diagnostic_pair();d=v['compilerDiagnostics'];d.update(streamStatus=[1,3],streamBytes=[0,None],projection=None)
        entry.validate_batch_private(v,c,'1'*64)
        changed=copy.deepcopy(v);changed['compilerDiagnostics']['projection']=dict(scanComplete=1,droppedCount=0,diagnostics=[])
        with self.assertRaises(entry.CiFailure):entry.validate_batch_private(changed,c,'1'*64)
        changed=copy.deepcopy(v);changed['compilerDiagnostics']['prepared']=False
        with self.assertRaises(entry.CiFailure):entry.validate_batch_private(changed,c,'1'*64)

    def test_precreate_descriptors_are_closed_before_return(self):
        with tempfile.TemporaryDirectory()as temp:
            capture=self.capture(temp);opened=[];closed=[];real_open=gate.os.open;real_close=gate.os.close
            def open_owned(*args,**kwargs):
                fd=real_open(*args,**kwargs);opened.append(fd);return fd
            def close_owned(fd):closed.append(fd);return real_close(fd)
            with mock.patch.object(gate.os,'open',side_effect=open_owned),mock.patch.object(gate.os,'close',side_effect=close_owned):self.assertTrue(capture.prepare())
            self.assertEqual(closed,opened);self.assertEqual(len(opened),2)
            for fd in opened:
                with self.assertRaises(OSError):gate.os.fstat(fd)
    def test_read_close_uncertainty_stops_before_second_file(self):
        with tempfile.TemporaryDirectory()as temp:
            capture=self.capture(temp);self.assertTrue(capture.prepare());real_close=gate.os.close
            def close(fd):real_close(fd);raise PermissionError()
            with mock.patch.object(gate.os,'close',side_effect=close)as closed:value=capture.observe(self.row())
            self.assertEqual(closed.call_count,1);self.assertTrue(capture.cleanup_unknown);self.assertIsNone(value['projection'])
    def test_precreate_close_uncertainty_cannot_return_an_executable_template(self):
        with tempfile.TemporaryDirectory()as temp:
            tracker=gate.BatchObservation(Path(temp),0x8664,'1'*64,100.,clock=lambda:1.);tracker.value['canary']=dict(statusCode=1,reasonCode=0,returns=[0,2,5])
            real_close=gate.os.close
            def close(fd):real_close(fd);raise PermissionError()
            base='@echo off\ncall "C:\\VS\\dev.cmd"\nif errorlevel 1 exit /b %errorlevel%\n"C:\\VS\\cl.exe" /c fixed.cpp\nexit /b %errorlevel%\n'
            with mock.patch.object(gate.os,'close',side_effect=close):
                with self.assertRaises(gate.GateFailure):tracker.template(base,3)
    def test_port_only_template_and_collection_match_actual_adapter(self):
        with tempfile.TemporaryDirectory()as temp:
            tracker=gate.BatchObservation(Path(temp),0x8664,'1'*64,100.,clock=lambda:1.);tracker.value['canary']=dict(statusCode=1,reasonCode=0,returns=[0,2,5])
            base='@echo off\ncall "C:\\VS\\dev.cmd"\nif errorlevel 1 exit /b %errorlevel%\n"C:\\VS\\cl.exe" /c fixed.cpp\nexit /b %errorlevel%\n'
            text=tracker.template(base,3);self.assertEqual(text.count('1>"sdk-port.stdout"'),1)
            (Path(temp)/'sdk-port.stdout').write_bytes(b'context_observer_windows.cpp(7): fatal error C1083: synthetic')
            with mock.patch.object(gate.tools,'read',return_value=b'1 0\r\n2 0\r\n3 0\r\n4 2\r\n'):tracker.collect(3,self.row())
            self.assertEqual(tracker.value['compilerDiagnostics']['projection']['diagnostics'][0]['number'],1083)
            self.assertNotIn('1>"sdk-port.stdout"',tracker.template(base,4));self.assertNotIn('1>"sdk-port.stdout"',tracker.template(base,5))
    def test_capture_swap_between_path_and_handle_is_unavailable(self):
        with tempfile.TemporaryDirectory()as temp:
            capture=self.capture(temp);self.assertTrue(capture.prepare());real_open=gate.os.open;seen=[]
            def swap(path,*args,**kwargs):
                if Path(path).name=='sdk-port.stdout'and not seen:
                    seen.append(1);Path(path).rename(Path(temp)/'original');Path(path).write_bytes(b'error C1001: synthetic')
                return real_open(path,*args,**kwargs)
            with mock.patch.object(gate.os,'open',side_effect=swap):value=capture.observe(self.row())
            self.assertEqual(value['streamStatus'][0],6);self.assertIsNone(value['projection'])
    def test_worst_bounded_numeric_packet_stays_inside_existing_public_cap(self):
        c,v=self.diagnostic_pair();rows=fixtures.success_fixture()['phaseResults'];c['helperPhaseResults']=entry.project_helper_phases(rows);c['helperPreCleanup']=[None]*5
        v['phases']=[dict(phaseCode=i,enabled=True,statusCode=1,reasonCode=0,rows=[[1,0],[2,0],[3,0],[4,4294967295]])for i in(3,4,5)]
        d=v['compilerDiagnostics'];d.update(streamStatus=[2,2],streamBytes=[65536,65536],projection=dict(scanComplete=0,droppedCount=992,diagnostics=[dict(streamCode=2,severity=3,kind=3,number=9999,fileCode=4,line=9999999)]*32))
        with tempfile.TemporaryDirectory()as temp:
            self.assertTrue(entry.batch_publish(Path(temp),c,v,deadline=10.,clock=lambda:1.))
            self.assertLessEqual((Path(temp)/'controller.numeric.json').stat().st_size,8192);self.assertLessEqual((Path(temp)/'source-assertion.json').stat().st_size,8192)

    def test_mixed_successful_stream_still_requires_exact_retired_phase(self):
        c,v=self.diagnostic_pair();v['phases'][0].update(statusCode=0,reasonCode=4,rows=None)
        v['compilerDiagnostics'].update(streamStatus=[2,3],streamBytes=[40,None],projection=None)
        entry.validate_batch_private(v,c,'1'*64)
        for key,bad in(('cleanupProved',False),('rootExitObserved',False),('jobEmptyObserved',False),('identityRechecked',False),('handlesClosed',3),('cancelled',True)):
            changed=copy.deepcopy(c);changed['helperPhaseResults'][1][key]=bad
            with self.subTest(field=key),self.assertRaises(entry.CiFailure):entry.validate_batch_private(v,changed,'1'*64)
    def test_mixed_empty_read_requires_verified_canary_and_outer_context(self):
        c,v=self.diagnostic_pair();v['compilerDiagnostics'].update(streamStatus=[1,5],streamBytes=[0,None],projection=None)
        canary=v['canary'];packet=v['compilerDiagnostics']
        for key,bad in(('envelopeKnown',False),('envelopeCleanupProved',False),('cancelled',True)):
            changed={**c,key:bad}
            with self.assertRaises(entry.CiFailure):entry.validate_compiler_diagnostics(packet,changed,canary)
        with self.assertRaises(entry.CiFailure):entry.validate_compiler_diagnostics(packet,c,dict(statusCode=0,reasonCode=1,returns=None))

class FirstC2338DetailTests(unittest.TestCase):
    """Synthetic public literals only; no SDK header contents are read."""
    SDK={8:r'C:\SDK\Include\10.0.26100.0\cppwinrt\winrt\base.h',
      9:r'C:\SDK\Include\10.0.26100.0\cppwinrt\winrt\Windows.Storage.h'}
    def project(self,stdout,stderr=''):
        self.assertTrue(hasattr(gate,'project_first_c2338_detail'),'B3 numeric detail required')
        projection=gate.project_compiler_diagnostics(stdout,stderr,Path('C:/owned'))
        return gate.project_first_c2338_detail(stdout,stderr,projection,self.SDK)
    def pair(self):
        self.assertEqual(gate.empty_batch_receipt()['schemaVersion'],4)
        c,v=PortCompilerDiagnosticsTests().diagnostic_pair()
        v['compilerDiagnostics']['projection']['diagnostics'][0].update(number=2338,fileCode=0,line=0)
        v['compilerDiagnostics']['firstC2338Detail']=dict(diagnosticOrdinal=1,streamCode=1,sdkSlot=8,line=123,assertionClass=1)
        v['compilerDiagnostics']['firstC2338SourceAssertion']=dict(diagnosticOrdinal=1,streamCode=1,statusCode=8,text=None)
        return c,v
    def test_schema_three_rejects_historical_b2_even_with_current_detail(self):
        self.assertEqual(gate.empty_batch_receipt()['schemaVersion'],4)
        c,v=self.pair()
        for packet in(c,v):
            packet['schemaVersion']=2
        with self.assertRaises(entry.CiFailure):entry.validate_batch_controller(c,binding(),'1'*64)
        with self.assertRaises(entry.CiFailure):entry.validate_batch_private(v,c,'1'*64)
        raw=helper_receipt();raw['schemaVersion']=2
        with self.assertRaises(entry.CiFailure):entry.validate_batch_helper(raw,'x64','1'*64,180.,raw['compileInputs'])
    def test_first_descriptor_ordinal_and_stream_span_both_inputs(self):
        text=self.SDK[9]+'(257): error C2338: Mismatched C++/WinRT headers.'
        value=self.project('cl : command line warning D9002: synthetic',text+'\n'+self.SDK[8]+'(9): error C2338: Not an awaitable type.')
        self.assertEqual(value,dict(diagnosticOrdinal=2,streamCode=2,sdkSlot=9,line=257,assertionClass=1))
    def test_sdk_roles_require_exact_verified_full_path_not_basename_suffix_or_alias(self):
        for path in('base.h','winrt/base.h',r'C:\foreign\base.h',r'C:\attacker'+self.SDK[8],self.SDK[8].replace('cppwinrt','cppwinrt\\..\\cppwinrt')):
            with self.subTest(case=path==self.SDK[8]):
                value=self.project(path+'(123): error C2338: Not an awaitable type.')
                self.assertEqual((value['sdkSlot'],value['line']),(0,0))
        self.assertEqual(self.project(self.SDK[8].lower().replace('\\','/')+'(123): error C2338: synthetic')['sdkSlot'],8)
    def test_only_four_exact_public_assertion_literals_are_classified(self):
        literals=('Mismatched C++/WinRT headers.','Not an awaitable type.',
          'Only native x64/ARM64 observers are supported','T must be WinRT type.')
        for code,literal in enumerate(literals,1):
            self.assertEqual(self.project(self.SDK[8]+'(3): error C2338: '+literal)['assertionClass'],code)
        for tail in('synthetic','mismatched C++/WinRT headers.',literals[0]+' '+literals[1]):
            self.assertEqual(self.project(self.SDK[8]+'(3): error C2338: '+tail)['assertionClass'],0)
    def test_no_c2338_or_dropped_c2338_cannot_create_detail(self):
        self.assertIsNone(self.project('error C1083: synthetic'))
        self.assertIsNone(self.project('error C1001: synthetic\n'*32+self.SDK[8]+'(1): error C2338: synthetic'))
        self.assertEqual(self.project('error C2338: synthetic'),dict(diagnosticOrdinal=1,streamCode=1,sdkSlot=0,line=0,assertionClass=0))
    def test_reader_binds_detail_to_first_actual_c2338_and_exact_numeric_shape(self):
        c,v=self.pair();entry.validate_batch_private(v,c,'1'*64)
        for key,bad in(('diagnosticOrdinal',2),('diagnosticOrdinal',True),('streamCode',2),('sdkSlot',True),('sdkSlot',1),('line',0),('line',True),('assertionClass',5),('assertionClass',True),('message','synthetic')):
            changed=copy.deepcopy(v);changed['compilerDiagnostics']['firstC2338Detail'][key]=bad
            with self.subTest(field=key),self.assertRaises(entry.CiFailure):entry.validate_batch_private(changed,c,'1'*64)
        for change in('missing','null','not-c2338','later-c2338','unknown-line'):
            changed=copy.deepcopy(v);d=changed['compilerDiagnostics']
            if change=='missing':del d['firstC2338Detail']
            elif change=='null':d['firstC2338Detail']=None
            elif change=='not-c2338':d['projection']['diagnostics'][0]['number']=1083
            elif change=='later-c2338':d['projection']['diagnostics']*=2;d['firstC2338Detail']['diagnosticOrdinal']=2
            else:d['firstC2338Detail']['sdkSlot']=0
            with self.subTest(case=change),self.assertRaises(entry.CiFailure):entry.validate_batch_private(changed,c,'1'*64)
    def test_detail_does_not_bypass_retirement_cancel_or_unavailable_projection(self):
        c,v=self.pair()
        for key,bad in(('cleanupProved',False),('handlesClosed',3),('cancelled',True)):
            changed=copy.deepcopy(c);changed['helperPhaseResults'][1][key]=bad
            with self.assertRaises(entry.CiFailure):entry.validate_batch_private(v,changed,'1'*64)
        v['compilerDiagnostics'].update(streamStatus=[2,3],streamBytes=[40,None],projection=None)
        with self.assertRaises(entry.CiFailure):entry.validate_batch_private(v,c,'1'*64)
    def test_sdk_slot_cannot_contradict_an_existing_local_source_role(self):
        c,v=self.pair();v['compilerDiagnostics']['projection']['diagnostics'][0].update(fileCode=2,line=26)
        with self.assertRaises(entry.CiFailure):entry.validate_batch_private(v,c,'1'*64)
    def test_capture_reuses_already_read_pair_and_verified_sdk_records(self):
        with tempfile.TemporaryDirectory()as temp:
            capture=gate.PortCompilerCapture(Path(temp),100.,clock=lambda:1.)
            self.assertTrue(hasattr(capture,'bind_sdk'),'Existing authenticated SDK result binding required')
            sdk=dict(root=r'C:\SDK',version='10.0.26100.0',files=[dict(slot=i,bytes=1,sha256='a'*64)for i in range(1,17)])
            with mock.patch.object(gate.tools,'read',side_effect=AssertionError('No header read')):capture.bind_sdk(sdk,'x64')
            self.assertTrue(capture.prepare())
            (Path(temp)/'sdk-port.stdout').write_bytes((self.SDK[8]+'(123): error C2338: Mismatched C++/WinRT headers.').encode())
            real=capture._read
            with mock.patch.object(capture,'_read',wraps=real)as reads:value=capture.observe(PortCompilerDiagnosticsTests().row())
            self.assertEqual(reads.call_count,2)
            self.assertEqual(value['firstC2338Detail'],dict(diagnosticOrdinal=1,streamCode=1,sdkSlot=8,line=123,assertionClass=1))
            self.assertEqual(value['projection']['diagnostics'][0]['fileCode'],0)
    def test_optional_detail_fault_preserves_existing_diagnostic_projection(self):
        with tempfile.TemporaryDirectory()as temp:
            capture=gate.PortCompilerCapture(Path(temp),100.,clock=lambda:1.);self.assertTrue(capture.prepare())
            (Path(temp)/'sdk-port.stdout').write_bytes(b'error C2338: synthetic')
            self.assertTrue(hasattr(gate,'project_first_c2338_detail'),'B3 detail projector required')
            with mock.patch.object(gate,'project_first_c2338_detail',side_effect=MemoryError()):value=capture.observe(PortCompilerDiagnosticsTests().row())
            self.assertEqual(value['projection']['diagnostics'][0]['number'],2338)
            self.assertEqual(value['firstC2338Detail'],dict(diagnosticOrdinal=1,streamCode=1,sdkSlot=0,line=0,assertionClass=0))
    def test_detail_cancellation_keeps_exact_primary_or_original_cancel(self):
        self.assertTrue(hasattr(gate,'project_first_c2338_detail'),'B3 detail projector required')
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with tempfile.TemporaryDirectory()as temp:
                capture=gate.PortCompilerCapture(Path(temp),100.,clock=lambda:1.);self.assertTrue(capture.prepare())
                primary=gate.GateFailure(10)
                with mock.patch.object(gate,'project_first_c2338_detail',side_effect=cancel):
                    try:
                        try:raise primary
                        finally:capture.observe(PortCompilerDiagnosticsTests().row())
                    except gate.GateFailure as observed:self.assertIs(observed,primary)
                self.assertTrue(capture.cancelled)
            with tempfile.TemporaryDirectory()as temp:
                capture=gate.PortCompilerCapture(Path(temp),100.,clock=lambda:1.);self.assertTrue(capture.prepare())
                with mock.patch.object(gate,'project_first_c2338_detail',side_effect=cancel):
                    try:capture.observe(PortCompilerDiagnosticsTests().row())
                    except BaseException as observed:self.assertIs(observed,cancel)
                    else:self.fail('Original cancellation required')
    def test_32_descriptors_plus_single_detail_stays_under_8192(self):
        c,v=self.pair();rows=fixtures.success_fixture()['phaseResults'];c['helperPhaseResults']=entry.project_helper_phases(rows);c['helperPreCleanup']=[None]*5
        v['phases']=[dict(phaseCode=i,enabled=True,statusCode=1,reasonCode=0,rows=[[1,0],[2,0],[3,0],[4,4294967295]])for i in(3,4,5)]
        d=v['compilerDiagnostics'];d.update(streamStatus=[2,2],streamBytes=[65536,65536])
        d['projection']['diagnostics']=[dict(streamCode=1,severity=3,kind=1,number=2338 if i==31 else 1001,fileCode=0,line=0)for i in range(32)]
        d['projection'].update(scanComplete=0,droppedCount=992);d['firstC2338Detail'].update(diagnosticOrdinal=32,line=9999999,assertionClass=4)
        d['firstC2338SourceAssertion']['diagnosticOrdinal']=32
        with tempfile.TemporaryDirectory()as temp:
            self.assertTrue(entry.batch_publish(Path(temp),c,v,deadline=10.,clock=lambda:1.))
            self.assertLessEqual((Path(temp)/'source-assertion.json').stat().st_size,8192)

class SourceAssertionTests(unittest.TestCase):
    """Only synthetic assertion strings; never runtime/user error collection."""
    def status(self,text):
        self.assertTrue(hasattr(entry,'source_assertion_status'),'Source-only text predicate required')
        return entry.source_assertion_status(text)
    def project(self,stdout,stderr=''):
        self.assertTrue(hasattr(gate,'project_source_assertion'),'Source-only assertion projector required')
        return gate.project_source_assertion(stdout,stderr,gate.project_compiler_diagnostics(stdout,stderr,Path('C:/owned')))
    def pair(self):
        self.assertEqual(gate.empty_batch_receipt()['schemaVersion'],4)
        c,v=FirstC2338DetailTests().pair()
        v['compilerDiagnostics']['firstC2338SourceAssertion']=dict(diagnosticOrdinal=1,streamCode=1,statusCode=1,text=' static_assert failed: synthetic public assertion')
        return c,v
    def test_source_only_kind_and_historical_schema_are_separate(self):
        self.assertEqual(gate.empty_batch_receipt()['schemaVersion'],4)
        self.assertEqual(gate.empty_batch_receipt()['kind'],'sdk-source-assert-helper')
        self.assertEqual(gate.empty_batch_receipt()['mode'],'source-assert')
        c,v=self.pair();c.update(schemaVersion=3,kind='sdk-batch-compiler-controller',mode='instrumented-batch-codes')
        with self.assertRaises(entry.CiFailure):entry.validate_batch_controller(c,binding(),'1'*64)
    def test_exact_first_c2338_prefix_is_removed_without_changing_the_body(self):
        text=' static_assert failed: a public invariant.'
        value=self.project('error C1001: synthetic',r'C:\SDK\private-prefix.h(72): error C2338:'+text+'\nerror C2338: later')
        self.assertEqual(value,dict(diagnosticOrdinal=2,streamCode=2,statusCode=1,text=text))
        self.assertNotIn('private-prefix',value['text'])
    def test_utf8_512_byte_boundary_is_not_character_count_or_truncation(self):
        self.assertEqual(self.status('x '*256),1)
        self.assertEqual(self.status('x'*513),3)
        self.assertEqual(self.status('\u03a9'*256),4)
        self.assertEqual(self.status('\u03a9'*257),4)
        value=self.project('error C2338: '+'x'*513)
        self.assertEqual(value['statusCode'],3);self.assertIsNone(value['text'])
    def test_control_format_multiline_and_surrogate_text_fail_closed(self):
        for code in(0,9,10,13,27,127,0x85,0x2028,0x2029,0x202e,0xd800):
            with self.subTest(code=code):self.assertEqual(self.status('public'+chr(code)+'assertion'),4)
    def test_non_crlf_line_controls_cannot_be_silently_split_from_the_body(self):
        for code in(11,12,0x85,0x2028,0x2029):
            value=self.project('error C2338: public'+chr(code)+'suffix')
            with self.subTest(code=code):self.assertEqual(value['statusCode'],4);self.assertIsNone(value['text'])
    def test_ambiguous_line_contract_cannot_attach_a_later_body_to_first_c2338(self):
        for code in(11,12,13,28,29,30,0x85,0x2028,0x2029):
            text='error C1000: synthetic'+chr(code)+'error C2338: first assertion\nerror C2338: second assertion'
            numeric=gate.project_compiler_diagnostics(text,'',Path('C:/owned'));self.assertEqual(len(numeric['diagnostics']),3)
            value=self.project(text)
            with self.subTest(code=code):
                self.assertEqual(value,dict(diagnosticOrdinal=2,streamCode=1,statusCode=4,text=None))
            self.assertEqual([r['number']for r in numeric['diagnostics']],[1000,2338,2338])
    def test_paths_urls_and_nonpublic_slash_tokens_fail_closed(self):
        for text in(r'C:\owned\source.cpp','C:/owned/source.cpp','../header.h','/tmp/header.h','https://synthetic.invalid/a','www.synthetic.invalid','file.cpp','header.h','.env','data:,synthetic','foreign/type','xC++/WinRT','C++/WinRT/suffix','C++/WinRT.h','x64/ARM64.log','.C++/WinRT','C++/WinRT-debug'):
            with self.subTest(case=text.startswith('C')):self.assertEqual(self.status(text),5)
        for text in('Mismatched C++/WinRT headers.','Only native x64/ARM64 observers are supported','winrt::impl::is_class_v<T> must hold.','static_assert failed: public invariant.','C++/WinRT.','(C++/WinRT)'):
            self.assertEqual(self.status(text),1)
        self.assertEqual(self.status('한글.h'),4);self.assertEqual(self.status('Ω 조건이 필요합니다.'),4)
    def test_secret_references_credentials_pem_and_opaque_tokens_are_not_published(self):
        for text in('pass'+':/'+'/synthetic','Bearer synthetic','Basic synthetic','password=synthetic','api_key=synthetic','api key=synthetic','AccessKey=synthetic','-----BEGIN PRIVATE KEY-----','gh'+'p_'+'SYNTHETIC'*4,'a'*32):
            self.assertEqual(self.status(text),6)
    def test_rejected_body_preserves_all_original_numeric_codes(self):
        for body in('https://synthetic.invalid/private','header.h','한글.h','.env','data:,synthetic'):
            text='error C2338: '+body+'\nerror C1083: synthetic'
            original=gate.project_compiler_diagnostics(text,'',Path('C:/owned'));value=self.project(text)
            with self.subTest(case=len(body)):
                self.assertEqual(value,dict(diagnosticOrdinal=1,streamCode=1,statusCode=4 if not body.isascii()else 5,text=None))
                self.assertEqual([r['number']for r in original['diagnostics']],[2338,1083])
    def test_optional_body_failure_preserves_c2338_projection_and_unknown_detail(self):
        self.assertTrue(hasattr(gate,'project_source_assertion'),'Source-only assertion projector required')
        with tempfile.TemporaryDirectory()as temp:
            capture=gate.PortCompilerCapture(Path(temp),100.,clock=lambda:1.);self.assertTrue(capture.prepare())
            (Path(temp)/'sdk-port.stdout').write_bytes(b'error C2338: synthetic')
            with mock.patch.object(gate,'project_source_assertion',side_effect=MemoryError()):value=capture.observe(PortCompilerDiagnosticsTests().row())
            self.assertEqual(value['projection']['diagnostics'][0]['number'],2338)
            self.assertEqual(value['firstC2338SourceAssertion'],dict(diagnosticOrdinal=1,streamCode=1,statusCode=8,text=None))
    def test_reader_replays_text_types_status_and_first_descriptor_binding(self):
        c,v=self.pair();entry.validate_batch_private(v,c,'1'*64)
        for key,bad in(('diagnosticOrdinal',2),('streamCode',2),('statusCode',True),('statusCode',2),('text','https://synthetic.invalid/a'),('text','header.h'),('text','한글.h'),('text','.env'),('text','data:,synthetic'),('text','x'*513),('extra',0)):
            changed=copy.deepcopy(v);changed['compilerDiagnostics']['firstC2338SourceAssertion'][key]=bad
            with self.subTest(field=key),self.assertRaises(entry.CiFailure):entry.validate_batch_private(changed,c,'1'*64)
        changed=copy.deepcopy(v);del changed['compilerDiagnostics']['firstC2338SourceAssertion']
        with self.assertRaises(entry.CiFailure):entry.validate_batch_private(changed,c,'1'*64)
    def test_source_flag_and_retirement_are_required_for_body_but_not_failure_codes(self):
        c,v=self.pair();c['sourceInputsVerified']=False
        with self.assertRaises(entry.CiFailure):entry.validate_batch_private(v,c,'1'*64)
        v['compilerDiagnostics']['firstC2338SourceAssertion'].update(statusCode=8,text=None)
        entry.validate_batch_private(v,c,'1'*64)
        c['helperPhaseResults'][1]['cleanupProved']=False
        with self.assertRaises(entry.CiFailure):entry.validate_batch_private(v,c,'1'*64)
    def test_no_published_c2338_cannot_create_body(self):
        self.assertIsNone(self.project('error C1083: synthetic'))
        self.assertIsNone(self.project('error C1001: synthetic\n'*32+'error C2338: synthetic'))
    def test_publisher_loses_only_unsafe_optional_body_not_valid_numeric_projection(self):
        c,v=self.pair();v['compilerDiagnostics']['firstC2338SourceAssertion']['text']='https://synthetic.invalid/private'
        with tempfile.TemporaryDirectory()as temp:
            self.assertTrue(entry.batch_publish(Path(temp),c,v,deadline=10.,clock=lambda:1.))
            data=(Path(temp)/'source-assertion.json').read_bytes();packet=json.loads(data)
            self.assertIsNotNone(packet['observation']);observed=packet['observation']['compilerDiagnostics']
            self.assertEqual(observed['projection'],v['compilerDiagnostics']['projection'])
            self.assertEqual(observed['firstC2338SourceAssertion'],dict(diagnosticOrdinal=1,streamCode=1,statusCode=8,text=None))
            self.assertNotIn(b'synthetic.invalid',data)
    def test_full_wire_cap_drops_only_body_and_never_truncates_numeric_codes(self):
        c,v=self.pair();encode=entry.json.dumps
        def enlarged(value,*args,**kwargs):
            result=encode(value,*args,**kwargs)
            if(type(value)is dict and value.get('kind')=='sdk-source-assert-sidecar'
              and value['observation']['compilerDiagnostics']['firstC2338SourceAssertion']['text']is not None):result+=' '*8192
            return result
        with tempfile.TemporaryDirectory()as temp,mock.patch.object(entry.json,'dumps',side_effect=enlarged):
            self.assertTrue(entry.batch_publish(Path(temp),c,v,deadline=10.,clock=lambda:1.))
            data=(Path(temp)/'source-assertion.json').read_bytes();self.assertLessEqual(len(data),8192)
            observed=json.loads(data)['observation']['compilerDiagnostics']
            self.assertEqual(observed['projection'],v['compilerDiagnostics']['projection'])
            self.assertEqual(observed['firstC2338SourceAssertion'],dict(diagnosticOrdinal=1,streamCode=1,statusCode=9,text=None))
    def test_body_cancellation_preserves_primary_or_original_cancel(self):
        self.assertTrue(hasattr(gate,'project_source_assertion'),'Source-only assertion projector required')
        for cancel in(KeyboardInterrupt(),SystemExit(130)):
            with tempfile.TemporaryDirectory()as temp:
                capture=gate.PortCompilerCapture(Path(temp),100.,clock=lambda:1.);self.assertTrue(capture.prepare())
                (Path(temp)/'sdk-port.stdout').write_bytes(b'error C2338: synthetic')
                primary=gate.GateFailure(10)
                with mock.patch.object(gate,'project_source_assertion',side_effect=cancel):
                    try:
                        try:raise primary
                        finally:capture.observe(PortCompilerDiagnosticsTests().row())
                    except gate.GateFailure as observed:self.assertIs(observed,primary)
                self.assertTrue(capture.cancelled)
    def test_maximum_numeric_records_and_escaped_body_fit_without_code_loss(self):
        c,v=self.pair();rows=fixtures.success_fixture()['phaseResults'];c['helperPhaseResults']=entry.project_helper_phases(rows);c['helperPreCleanup']=[None]*5
        v['phases']=[dict(phaseCode=i,enabled=True,statusCode=1,reasonCode=0,rows=[[1,0],[2,0],[3,0],[4,4294967295]])for i in(3,4,5)]
        d=v['compilerDiagnostics'];d.update(streamStatus=[2,2],streamBytes=[65536,65536]);d['projection'].update(scanComplete=0,droppedCount=992)
        d['projection']['diagnostics']=[dict(streamCode=1,severity=3,kind=1,number=2338 if i==31 else 1001,fileCode=0,line=0)for i in range(32)]
        d['firstC2338Detail'].update(diagnosticOrdinal=32,line=9999999,assertionClass=4)
        d['firstC2338SourceAssertion']['diagnosticOrdinal']=32
        d['firstC2338SourceAssertion'].update(diagnosticOrdinal=32,text='\"'*512)
        with tempfile.TemporaryDirectory()as temp:
            self.assertTrue(entry.batch_publish(Path(temp),c,v,deadline=10.,clock=lambda:1.))
            data=(Path(temp)/'source-assertion.json').read_bytes();self.assertLessEqual(len(data),8192)
            observed=json.loads(data)['observation']['compilerDiagnostics'];self.assertEqual(len(observed['projection']['diagnostics']),32)
            self.assertEqual(observed['firstC2338SourceAssertion']['text'],'\"'*512)

if __name__=='__main__':unittest.main()
