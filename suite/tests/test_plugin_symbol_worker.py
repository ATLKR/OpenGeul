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
