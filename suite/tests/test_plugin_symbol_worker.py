"""Owned child watchdog retains parent deadlines and sanitized terminal evidence."""
import importlib.util
import json
from pathlib import Path
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
    def test_inherited_budget_never_renews(self):
        self.clock.value=127.
        with self.assertRaises(AssertionError):self.m.inherited_budget(dict(startedAt=100.,workDeadline=127.,deadline=130.))
        self.clock.value=105.
        budget=self.m.inherited_budget(dict(startedAt=100.,workDeadline=127.,deadline=130.))
        self.assertEqual(budget.started,100.);self.assertEqual(budget.now(),105.)
        with self.assertRaises(AssertionError):self.m.inherited_budget(dict(startedAt=100.,workDeadline=128.,deadline=131.))

if __name__=='__main__':unittest.main()
