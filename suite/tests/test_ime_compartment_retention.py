"""One original compartment case keeps raw evidence in memory through cleanup."""
import copy
import importlib.util
import inspect
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'e2e')]
import korean_ime_smoke as ime


class CompartmentRetentionTests(unittest.TestCase):
    def original_case(self, *, failure=False, sink_error=False):
        import test_ime_case_phases as phases
        original=ime.case;captured=[];observed=[];self.sink_states=[]
        harness=phases.IMECasePhaseTests();self.addCleanup(harness.doCleanups)
        def case(*args,**kw):
            readiness=args[3];readiness['nativeMachine']=0xaa64
            readiness['profile']['component']['machine']=0xaa64
            readiness['source']['architecture']='arm64'
            observer=ime.CompositionObserver;keyboard=ime.IMEKeyboardSession
            retirement=sys.modules['ime_engine_retirement'];admit=retirement.admit_ime_retirement
            class Observer(observer):
                def __init__(inner,*a,**k):
                    super().__init__(*a,**k)
                    inner.diagnose_ime_mode=True
                    inner.native_architecture.update(nativeMachine=0xaa64,nativeArchitecture='arm64',processArchitecture='arm64')
                    inner.target_architecture=dict(inner.native_architecture)
                def pending(inner,*a):return not failure
                def diagnostics(inner):return dict(status='complete',events=[])
                def mode_diagnostics(inner):return dict(status='complete',events=[])
                def compartment_diagnostics(inner):return dict(status='not-triggered',cleanupStatus='unsubscribed')
            def owned_keyboard(*a,**k):
                value=keyboard(*a,**k);observed.append(value)
                return value
            def admitted(**k):
                value=admit(**k)
                value.verify_after_close_home=lambda **k:None
                return value
            def sink(record):
                captured.append(record)
                self.sink_states.append(observed[0].closed)
                if sink_error:raise ValueError('synthetic sink failure')
            window=sys.modules['pywinauto'].Desktop().window(handle=11).wrapper_object()
            with patch.object(ime,'CompositionObserver',Observer),patch.object(ime,'IMEKeyboardSession',side_effect=owned_keyboard), \
                 patch.object(retirement,'admit_ime_retirement',side_effect=admitted), \
                 patch.object(ime,'validate_ime_evidence',return_value=dict(imeVerified=True)), \
                 patch.object(window,'capture_as_image',side_effect=AssertionError('No raw screen retention')), \
                 patch.object(ime,'capture_failure',side_effect=AssertionError('No raw failure sidecar')), \
                 patch.object(ime,'write_result',side_effect=AssertionError('No raw case JSON')):
                return original(*args,**kw,diagnose_ime_mode=True,capture_ime_compartment=True,
                    plugin_origin=dict(verified=True),compartment_sink=sink)
        with patch.object(ime,'case',side_effect=case):
            calls,record,result,error=harness.run_case('writer',empty_retirement_failure=True,
                fail_semantic='pre' if failure=='semantic' else None)
        return calls,record,result,error,captured,observed

    def test_original_success_has_one_same_record_sink_after_cleanup_without_raw_sidecars(self):
        self.assertIn('compartment_sink',inspect.signature(ime.case).parameters)
        calls,record,result,error,captured,observed=self.original_case()
        self.assertIsNone(error,repr(error));self.assertIs(result,record)
        self.assertTrue(record['success']);self.assertEqual(self.sink_states,[True])
        self.assertEqual(len(captured),1);self.assertIs(captured[0],record)
        self.assertFalse(observed[0].retain_evidence)
        self.assertEqual(calls.count('CTRL_S'),1)
        self.assertEqual([x for x in calls if isinstance(x,tuple) and x[0]=='command'],
            [('command',1),('command',2),('command',3),('command',4)])
        self.assertIn('final-stop',calls)

    def test_original_failure_keeps_primary_and_sink_after_one_teardown(self):
        self.assertIn('compartment_sink',inspect.signature(ime.case).parameters)
        calls,record,result,error,captured,observed=self.original_case(failure=True)
        self.assertIsInstance(error,AssertionError)
        self.assertIn('Unexpected false boundary predicate',str(error))
        self.assertIsNone(result);self.assertEqual(len(captured),1);self.assertIs(captured[0],record)
        self.assertEqual(self.sink_states,[True])
        self.assertFalse(observed[0].retain_evidence)
        failures=[v for v in calls if isinstance(v,tuple) and v[0]=='failure-teardown']
        self.assertEqual(len(failures),1);self.assertIs(failures[0][1],error)
        self.assertNotIn('CTRL_S',calls)
        self.assertEqual([v for v in calls if isinstance(v,tuple) and v[0]=='physical'],[('physical','g')])

    def test_early_partial_case_and_sink_error_do_not_mask_the_original_failure(self):
        calls,record,result,error,captured,observed=self.original_case(failure='semantic',sink_error=True)
        self.assertIsInstance(error,RuntimeError);self.assertEqual(str(error),'semantic pre rejected')
        self.assertEqual(len(captured),1);self.assertIs(captured[0],record)
        self.assertEqual(self.sink_states,[True]);self.assertEqual(record['compartmentSinkErrorType'],'ValueError')
        self.assertFalse(record['success']);self.assertIsNone(result)
        self.assertNotIn('observer-installed',calls);self.assertNotIn('CTRL_S',calls)
        self.assertFalse(any(isinstance(row,tuple) and row[0]=='physical' for row in calls))

    def test_in_memory_resolution_runs_original_selector_then_one_file_only_worker(self):
        from test_compartment_selection import CompartmentSelectionTests
        fixture=CompartmentSelectionTests();fixture.setUp();module=fixture.m
        function=getattr(module,'resolve_compartment_in_memory',None)
        self.assertTrue(callable(function),'In-memory compartment resolution is required')
        report=fixture.compartment_report();before=copy.deepcopy(report);calls=[]
        def worker(pair,*,mode,rvas):
            calls.append((pair,mode,rvas))
            return dict(success=True,resolution=dict(dllSha256=report['pluginFileOrigin']['dllSha256'],
                identity=report['pluginFileOrigin']['matchedIdentity'],frames=[dict(returnRva=100,tag='frame-input-context')]))
        selected,resolved=function(report,Path('/synthetic/pair'),report['runBinding'],worker_run=worker)
        self.assertEqual(selected['status'],'selected');self.assertTrue(resolved['success'])
        self.assertEqual(calls,[(Path('/synthetic/pair'),'resolve',[100])]);self.assertEqual(report,before)
        report['tests'][0]['keyTokens']=['g','k']
        selected,resolved=function(report,Path('/synthetic/pair'),report['runBinding'],worker_run=worker)
        self.assertEqual(selected['status'],'inconclusive-case');self.assertIsNone(resolved)
        self.assertEqual(len(calls),1)
        report=fixture.compartment_report();report['tests'][0]['imeFailureCleanup']['engineExitConfirmed']=False
        with self.assertRaises(AssertionError):function(report,Path('/synthetic/pair'),report['runBinding'],worker_run=worker)
        self.assertEqual(len(calls),1)

    def test_single_controller_keeps_raw_case_in_memory_and_only_persists_closed_numeric_receipt(self):
        from suite.scripts import matched_plugin_diagnostic as resolution
        for failure in ('none','case','prepare','release','resolve'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);events=[];seen=[];primary=RuntimeError('SYNTHETIC PRIVATE '+failure)
                binding=dict(sourceCommit='a'*40,runId='7',runAttempt='1',architecture='arm64',
                    repository='ATLKR/OpenGeul',job='windows-suite')
                context=dict(sourceCommit='a'*40,runId=7,runAttempt=1,architecture=0xaa64)
                receipt=dict(verified=True,released=False)
                record=dict(case='ime-writer',success=failure!='case',private='SYNTHETIC PRIVATE',cleanupComplete=True)
                def close():
                    events.append('lease-close')
                    if failure=='release':raise primary
                    receipt['released']=True
                lease=NS(binding=lambda:dict(verified=True),receipt=receipt,close=close)
                def prepare(*a,**k):
                    events.append('prepare')
                    if failure=='prepare':raise primary
                    return object()
                def one_case(*a,**k):
                    events.append('case');self.assertEqual(a[4],'writer')
                    self.assertFalse(receipt['released']);self.assertTrue(k['capture_ime_compartment'])
                    k['compartment_sink'](record)
                    if failure=='case':raise primary
                    return record
                def resolve(report,pair,actual):
                    events.append('resolve');self.assertEqual(actual,binding)
                    if failure!='prepare':self.assertIs(report['tests'][0],record)
                    self.assertEqual(events.count('case'),int(failure!='prepare'))
                    self.assertIn('lease-close',events)
                    if failure=='resolve':raise primary
                    return dict(status='inconclusive-case'),None
                def project(report,selection=None,resolution=None,*,context):
                    seen.append(report);self.assertNotIn('SYNTHETIC PRIVATE',json.dumps(context))
                    return dict(schemaVersion=1,kind=4,scopeCode=11,sourceCommit=context['sourceCommit'],
                        runId=context['runId'],runAttempt=1,architecture=0xaa64,status=0)
                publisher=NS(project=project,encode_notice=lambda value:json.dumps(value),emit_value=lambda value:events.append('notice') or True)
                with patch.dict(sys.modules,{'ime_compartment_report':publisher}), \
                     patch.object(ime,'_open_plugin_proof',return_value=lease), \
                     patch.object(ime.ascii_input,'prepare_observer',side_effect=prepare), \
                     patch.object(ime,'case',side_effect=one_case), \
                     patch.object(ime,'collect_cases',side_effect=AssertionError('No collector replay or sidecars')), \
                     patch.object(resolution,'resolve_compartment_in_memory',side_effect=resolve), \
                     patch.object(ime.numeric_notice,'public_context',return_value=context):
                    if failure in ('case','prepare','resolve'):
                        with self.assertRaises(RuntimeError) as raised:
                            ime.run_mode_diagnostic(root,root,root,{},'arm64',binding,root/'pair/receipt.json',capture_compartment=True)
                        self.assertIs(raised.exception,primary)
                    else:
                        code=ime.run_mode_diagnostic(root,root,root,{},'arm64',binding,root/'pair/receipt.json',capture_compartment=True)
                        self.assertEqual(code,0 if failure=='none' else 1)
                self.assertEqual([p.name for p in root.iterdir()],['callback-numeric.json'])
                raw=(root/'callback-numeric.json').read_text()
                self.assertNotIn('SYNTHETIC PRIVATE',raw);self.assertEqual(json.loads(raw)['kind'],4)
                self.assertEqual(events.count('notice'),1);self.assertEqual(events.count('lease-close'),1)
                self.assertEqual(len(seen),1)

    def controller_roundtrip(self, *, resolver_failure=False):
        from test_compartment_selection import CompartmentSelectionTests
        from test_ime_compartment_report import CompartmentReportTests,environment
        from test_ime_mode_receipts import ThreadModeReceiptTests
        from ime_thread_mode import require_typed_mode_receipt
        from suite.scripts import matched_plugin_diagnostic as resolver
        import ime_compartment_report as publisher
        fixture=CompartmentSelectionTests();fixture.setUp();raw=fixture.compartment_report()
        projection=CompartmentReportTests();projection.setUp();_,_,worker=projection.fixture()
        raw['runBinding'].update(ref='refs/heads/work/opengeul-office-arm64',event='push',
            workflowRef='ATLKR/OpenGeul/.github/workflows/office-suite.yml@refs/heads/work/opengeul-office-arm64')
        record=raw['tests'][0];record['imeEngineRetirement']['close']=dict(result=True)
        # The selector's smaller protocol fixture predates the setter's client
        # interface; this end-to-end fixture must carry the actual typed ABI.
        mode=ThreadModeReceiptTests().receipt(3)
        mode.update(beforeConversion=0,requestedConversion=1,afterConversion=1)
        self.assertEqual(require_typed_mode_receipt(mode,3,
            original=((1,0,None),(1,0,None)),allow_empty=True),((0,3,1),(0,3,1)))
        self.assertEqual((mode['referencesAcquired'],mode['referencesReleased']),(6,6))
        record['imeCommands'][0]['threadMode']=mode
        record['traceback']='SYNTHETIC PRIVATE INPUT AND TRACEBACK'
        identity=raw['pluginFileOrigin'];worker['resolution'].update(dllSha256=identity['dllSha256'],identity=identity['matchedIdentity'])
        env=environment();env.update(GITHUB_SHA='a'*40,GITHUB_WORKFLOW_SHA='a'*40,GITHUB_RUN_ID='7')
        original=resolver.resolve_compartment_in_memory;calls=[]
        def resolved(report,pair,context):
            self.assertIs(report['tests'][0],record)
            if resolver_failure:raise RuntimeError('SYNTHETIC PRIVATE worker failure')
            def file_worker(actual,*,mode,rvas):
                calls.append((mode,rvas));return worker
            return original(report,pair,context,worker_run=file_worker)
        primary=AssertionError('Native UI condition did not become true: False')
        def case(*args,**kw):kw['compartment_sink'](record);raise primary
        proof=dict(identity,released=False)
        lease=NS(binding=lambda:dict(verified=True),receipt=proof,close=lambda:proof.update(released=True))
        with tempfile.TemporaryDirectory() as directory,patch.dict(ime.os.environ,env), \
             patch.object(publisher,'_attempted',False), \
             patch.object(ime,'_open_plugin_proof',return_value=lease), \
             patch.object(ime.ascii_input,'prepare_observer',return_value=object()), \
             patch.object(ime,'case',side_effect=case), \
             patch.object(resolver,'resolve_compartment_in_memory',side_effect=resolved),redirect_stdout(io.StringIO()) as stream:
            root=Path(directory)
            with self.assertRaises(AssertionError) as raised:
                ime.run_mode_diagnostic(root,root,root,{},'arm64',raw['runBinding'],root/'pair/receipt.json',capture_compartment=True)
            self.assertIs(raised.exception,primary)
            files=list(root.iterdir());self.assertEqual([p.name for p in files],['callback-numeric.json'])
            message=files[0].read_text()
            closed=publisher.decode_notice(message,'a'*40,7)
            self.assertEqual(json.loads(message)['schemaVersion'],2)
            self.assertEqual(closed['statusCode'],1 if resolver_failure else 3)
            self.assertFalse(closed['runtimeCallerProved']);self.assertFalse(closed['acceptanceEligible'])
            self.assertNotIn('SYNTHETIC PRIVATE',message)
            self.assertEqual(stream.getvalue().count('::notice '),1)
            annotation=stream.getvalue().strip().split('::',2)[2]
            self.assertLessEqual(len(annotation.encode('utf-8')),4096)
            self.assertEqual(json.loads(annotation)['schemaVersion'],3)
            self.assertEqual(publisher.decode_notice(annotation,'a'*40,7),closed)
            self.assertEqual(calls,[] if resolver_failure else [('resolve',[100])])
            self.assertTrue(proof['released'])
            self.assertTrue(record['imeFailureCleanup']['engineExitConfirmed'])
            self.assertEqual(closed['callback']['statusCode'],3)
            if resolver_failure:
                self.assertIsNone(closed['selection']['statusCode'])
                self.assertIsNone(closed['resolution'])

    def test_controller_original_selector_real_numeric_projection_and_resolution_roundtrip(self):
        self.controller_roundtrip()

    def test_resolver_failure_preserves_original_primary_cleanup_and_one_closed_receipt(self):
        self.controller_roundtrip(resolver_failure=True)


if __name__=='__main__':unittest.main()
