"""Owned child watchdog retains parent deadlines and sanitized terminal evidence."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace as NS
import test_ascii_message_preparation as fixture

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/plugin_symbol_worker.py'

class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(),'owned symbol worker absent')
        spec=importlib.util.spec_from_file_location('symbol_worker_test',SCRIPT)
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.clock=fixture.Clock();self.clock.value=100.
        self.addCleanup(patch.stopall)
        patch.object(self.m.shared.time,'monotonic',self.clock).start();patch.object(self.m.shared.time,'sleep',self.clock.sleep).start()
        patch.object(self.m.shared.native_arch,'observe_native_architecture',return_value={}).start()
        patch.object(self.m.shared.native_arch,'validate_native_architecture',return_value={}).start()
        patch.object(self.m,'FileApi',return_value=NS(preflight=lambda path:None),create=True).start()
    def runtime(self,mode):
        owner=NS(install=self.root,clock=self.clock);runtime=fixture.Runtime(owner)
        original=runtime.start
        def start(argv,folder):
            request=json.loads((folder/'request.json').read_text())
            self.assertEqual(request['startedAt'],100.);self.assertEqual(request['workDeadline'],127.);self.assertEqual(request['deadline'],130.)
            value=dict(schemaVersion=1,kind='local-plugin-symbol-resolution',complete=True,cleanupComplete=True,acceptance=False,runtimeCallerProved=False,frames=[],qualification=dict(roundTripMatched=True,tag='mutex-acquire',functionRva=4096,functionSize=16,functionAliasUniquenessProved=False))
            if mode=='bad-output':value['complete']=False
            if mode=='oversized-output':value['unexpected']='x'*65537
            if mode!='missing-output':(folder/'result.json').write_text(json.dumps(value))
            return original(argv,folder)
        runtime.start=start
        if mode=='nonzero':runtime.states=[[(0,0,1)]]
        if mode in ('hang','survivor'):runtime.states=[[(258 if mode=='hang' else 0,1,0)]];runtime.late=True
        if mode=='close-failure':runtime.close_error=True
        return runtime
    def test_success_and_failure_preserve_owned_cleanup_without_raw_command(self):
        for mode in ('success','nonzero','hang','survivor','close-failure','missing-output','bad-output','oversized-output'):
            with self.subTest(mode=mode):
                self.clock.value=100.;runtime=self.runtime(mode)
                if mode=='success':
                    result=self.m.run(self.root,mode='qualify',runtime=runtime)
                    self.assertTrue(result['success']);self.assertTrue(result['temporaryFilesRemoved'])
                    self.assertNotIn('resolutionProfile',result)
                else:
                    with self.assertRaises(Exception) as caught:self.m.run(self.root,mode='qualify',runtime=runtime)
                    result=caught.exception.symbolWorkerReceipt;self.assertFalse(result['success'])
                self.assertNotIn(str(self.root),json.dumps(result));self.assertNotIn('command',json.dumps(result))
                self.assertTrue(runtime.processes[0].closed)
                if mode in ('hang','survivor','nonzero'):self.assertTrue(runtime.processes[0].forced)
    def test_remote_pair_rejected_before_parent_stat(self):
        api=NS(preflight=lambda path:(_ for _ in ()).throw(ValueError('remote-drive')))
        with patch.object(self.m,'FileApi',return_value=api),patch.object(self.m.shared,'_absolute',side_effect=AssertionError('stat before local-drive admission')):
            with self.assertRaisesRegex(ValueError,'remote-drive'):self.m.run(self.root,mode='qualify')
    def test_compartment_only_worker_33_to64_keeps_original_mode_budget_and_cleanup(self):
        run=getattr(self.m,'run_compartment',None);self.assertTrue(callable(run))
        for count in (33,63,64):
            with self.subTest(count=count):
                self.clock.value=100.;runtime=self.runtime('success');start=runtime.start
                rvas=[0x1104+(index%3)*4 for index in range(count)]
                def profile_start(argv,folder):
                    request=json.loads((folder/'request.json').read_text())
                    self.assertEqual((request['mode'],request['resolutionProfile']),('resolve',2))
                    self.assertEqual(request['rvas'],rvas)
                    result=start(argv,folder)
                    output=folder/'result.json';value=json.loads(output.read_text())
                    value['resolutionProfile']=2;output.write_text(json.dumps(value))
                    return result
                runtime.start=profile_start
                value=run(self.root,mode='resolve',rvas=rvas,runtime=runtime)
                self.assertEqual((value['mode'],value['resolutionProfile']),('resolve',2))
                self.assertEqual(value['stages'][0]['stage'],'symbol-resolve')
                self.assertTrue(value['temporaryFilesRemoved'] and runtime.processes[0].closed)
                self.assertNotIn(str(self.root),json.dumps(value))
        with self.assertRaises(AssertionError):self.m.run(self.root,mode='resolve',rvas=[0x1104]*33)

    def test_compartment_invalid_inputs_and_unbound_child_profile_are_rejected(self):
        run=getattr(self.m,'run_compartment',None);self.assertTrue(callable(run))
        for kwargs in (dict(mode='qualify'),dict(mode=True),dict(rvas=[0x1104]*65),dict(rvas=[True]),dict(rvas=[])):
            with self.subTest(kwargs=kwargs),patch.object(self.m,'FileApi',side_effect=AssertionError('file query')) as file_api:
                with self.assertRaises(AssertionError):run(self.root,**dict(dict(rvas=[0x1104]),**kwargs))
                file_api.assert_not_called()
        for profile in (None,1,True):
            self.clock.value=100.;runtime=self.runtime('success');start=runtime.start
            def unbound(argv,folder):
                result=start(argv,folder);output=folder/'result.json';value=json.loads(output.read_text())
                if profile is not None:value['resolutionProfile']=profile
                output.write_text(json.dumps(value));return result
            runtime.start=unbound
            with self.subTest(profile=profile),self.assertRaises(AssertionError) as caught:
                run(self.root,rvas=[0x1104],runtime=runtime)
            self.assertTrue(caught.exception.symbolWorkerReceipt['temporaryFilesRemoved'])
            self.assertTrue(runtime.processes[0].closed)
        with self.assertRaises(TypeError):run(self.root,rvas=[0x1104],max_frames=65)

    def test_child_profile_is_closed_before_adapter_import(self):
        path=self.root/'profile-request.json'
        for profile,mode in (('missing','resolve'),(None,'resolve'),(True,'resolve'),(0,'resolve'),(3,'resolve'),('2','resolve'),(2,'qualify')):
            request=dict(startedAt=100.,workDeadline=127.,deadline=130.,resolutionProfile=profile,mode=mode)
            if profile=='missing':request.pop('resolutionProfile')
            path.write_text(json.dumps(request))
            with self.subTest(profile=profile,mode=mode),patch.object(self.m.importlib.util,
                    'spec_from_file_location',side_effect=AssertionError('adapter import')) as load:
                with self.assertRaises(AssertionError):self.m.child(path)
                load.assert_not_called()

    def test_actual_legacy_parent_rejects_any_present_compartment_profile_field(self):
        for mode in ('resolve','qualify'):
            for profile in (2,1,None,True):
                with self.subTest(mode=mode,profile=profile):
                    self.clock.value=100.;runtime=self.runtime('success');start=runtime.start
                    def cross_profile(argv,folder):
                        result=start(argv,folder);path=folder/'result.json';value=json.loads(path.read_text())
                        value['resolutionProfile']=profile;path.write_text(json.dumps(value));return result
                    runtime.start=cross_profile
                    with self.assertRaises(AssertionError) as caught:
                        self.m.run(self.root,mode=mode,rvas=[0x1104] if mode=='resolve' else None,runtime=runtime)
                    receipt=caught.exception.symbolWorkerReceipt
                    self.assertTrue(receipt['temporaryFilesRemoved'] and runtime.processes[0].closed)
                    self.assertNotIn('resolutionProfile',receipt)
                    self.assertNotIn('resolution',receipt)

    def test_child_dispatches_the_closed_profile_without_renewing_budget(self):
        calls=[]
        def resolved(name,args,profile=None):
            budget=args[-1]
            self.assertEqual((budget.started,budget.work_deadline,budget.deadline),(100.,127.,130.))
            calls.append((name,list(args[3]) if name!='qualify' else None))
            value=dict(kind='local-plugin-symbol-resolution',complete=True,cleanupComplete=True,
                acceptance=False,runtimeCallerProved=False,frames=[])
            if profile is not None:value['resolutionProfile']=profile
            return value
        runtime=NS(preflight_path=lambda path:None)
        adapter=NS(_path_syntax=Path,NativeRuntime=lambda budget:runtime,
            retention=NS(MAX_DLL=32*1024*1024,read_regular=lambda path,limit,budget:b'{}' if path.name=='receipt.json' else b'PE'),
            resolve=lambda *args,**kw:resolved('legacy',args),
            resolve_compartment=lambda *args,**kw:resolved('compartment',args,2),
            qualify=lambda *args,**kw:resolved('qualify',args))
        spec=NS(loader=NS(exec_module=lambda module:None))
        for profile,mode,count,name in ((1,'resolve',32,'legacy'),(2,'resolve',64,'compartment'),(1,'qualify',0,'qualify')):
            with self.subTest(profile=profile,mode=mode):
                directory=self.root/(str(profile)+mode);directory.mkdir()
                rvas=[0x1104]*count if mode=='resolve' else None
                request=dict(startedAt=100.,workDeadline=127.,deadline=130.,
                    resolutionProfile=profile,mode=mode,pair=str(self.root),rvas=rvas)
                path=directory/'request.json';path.write_text(json.dumps(request))
                with patch.object(self.m.importlib.util,'spec_from_file_location',return_value=spec), \
                     patch.object(self.m.importlib.util,'module_from_spec',return_value=adapter):
                    self.m.child(path)
                self.assertEqual(calls[-1],(name,rvas))
                result=json.loads((directory/'result.json').read_text())
                if profile==2:self.assertEqual(result['resolutionProfile'],2)
                else:self.assertNotIn('resolutionProfile',result)
    def test_failed_child_preserves_closed_failure_code_after_cleanup(self):
        # Previously every child error became exit 1 and its only detail was deleted.
        self.assertTrue(hasattr(self.m,'failure_exit_code'),'child failure classification absent')
        error=type('ResolutionError',(ValueError,),{})('symbol-load')
        code=self.m.failure_exit_code(error)
        runtime=self.runtime('nonzero');runtime.states=[[(0,0,code)]]
        with self.assertRaises(AssertionError) as caught:self.m.run(self.root,mode='qualify',runtime=runtime)
        receipt=caught.exception.symbolWorkerReceipt
        self.assertFalse(receipt['success']);self.assertTrue(receipt['temporaryFilesRemoved'])
        self.assertTrue(runtime.processes[0].closed)
        self.assertEqual(receipt['stages'][0]['childFailure'],{'category':'ResolutionError','code':'symbol-load'})
        self.assertNotIn(str(self.root),json.dumps(receipt))
    def test_failure_classification_never_exports_exception_text(self):
        self.assertTrue(hasattr(self.m,'failure_exit_code'),'child failure classification absent')
        error=type('ResolutionError',(ValueError,),{})('private-path-or-symbol')
        self.assertEqual(self.m.failure_exit_code(error),1)
        self.assertEqual(self.m.failure_exit_code(type('private-type',(Exception,),{})('private-message')),1)
        codes=[]
        for category,code in self.m.FAILURES:
            value=self.m.failure_exit_code(type(category,(Exception,),{})(code))
            self.assertGreater(value,65535);self.assertLess(value,2**31);codes.append(value)
        self.assertEqual(len(codes),len(set(codes)))
        self.assertNotIn('private',json.dumps(self.m.stages([{'cleanupLastSample':{'root':{'waitResult':0,'exitCode':1},'activeProcesses':0,'querySucceeded':True}}])))
    def test_identity_mismatch_exit_channel_preserves_all_failed_predicates(self):
        error_type=type('ModuleIdentityError',(ValueError,),{})
        for value in ((1|8|16|64,7),(127,9)):
            code=self.m.failure_exit_code(error_type(value))
            self.assertNotEqual(code,1,'metadata mismatch discarded')
            rows=self.m.stages([{'samples':[{'root':{'waitResult':0,'exitCode':code},'activeProcesses':0,'querySucceeded':True}]}])
            failure=rows[0]['childFailure']
            self.assertEqual(failure['mismatchMask'],value[0]);self.assertEqual(failure['symbolType'],value[1])
            self.assertEqual(failure['category'],'ModuleIdentityError')
        for bad in ((0,7),(128,7),(1,10),(True,7),(1,True),'private-text'):
            self.assertEqual(self.m.failure_exit_code(error_type(bad)),1)
    def test_isolated_child_exit_channel_has_no_stderr_or_stdout(self):
        request=self.root/'request.json'
        request.write_text(json.dumps(dict(startedAt=1,workDeadline=2,deadline=3)))
        result=subprocess.run([sys.executable,'-I',str(SCRIPT),'--child',str(request)],
            capture_output=True,timeout=10,cwd=self.root)
        expected=self.m.failure_exit_code(AssertionError())
        self.assertEqual(result.returncode,expected if os.name=='nt' else expected%256)
        self.assertEqual(result.stdout,b'');self.assertEqual(result.stderr,b'')
    @unittest.skipUnless(os.name=='nt','Windows cmd exit-code transport')
    def test_generated_cmd_preserves_full_child_exit_code(self):
        runtime=self.runtime('nonzero');original=runtime.start
        expected=self.m.failure_exit_code(AssertionError())
        def start(argv,folder):
            request=json.loads((folder/'request.json').read_text())
            request['workDeadline']-=1
            (folder/'request.json').write_text(json.dumps(request))
            result=subprocess.run(argv,cwd=folder,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,expected)
            self.assertEqual(result.stdout,b'');self.assertEqual(result.stderr,b'')
            self.assertEqual((folder/'stdout').read_bytes(),b'')
            self.assertEqual((folder/'stderr').read_bytes(),b'')
            request['workDeadline']+=1
            (folder/'request.json').write_text(json.dumps(request))
            runtime.states=[[(0,0,result.returncode)]]
            return original(argv,folder)
        runtime.start=start
        with self.assertRaises(AssertionError) as caught:self.m.run(self.root,mode='qualify',runtime=runtime)
        self.assertEqual(caught.exception.symbolWorkerReceipt['stages'][0]['childFailure'],
            {'category':'AssertionError','code':'unclassified'})
    def test_inherited_budget_never_renews(self):
        self.clock.value=127.
        with self.assertRaises(AssertionError):self.m.inherited_budget(dict(startedAt=100.,workDeadline=127.,deadline=130.))
        self.clock.value=105.
        budget=self.m.inherited_budget(dict(startedAt=100.,workDeadline=127.,deadline=130.))
        self.assertEqual(budget.started,100.);self.assertEqual(budget.now(),105.)
        with self.assertRaises(AssertionError):self.m.inherited_budget(dict(startedAt=100.,workDeadline=128.,deadline=131.))

if __name__=='__main__':unittest.main()
