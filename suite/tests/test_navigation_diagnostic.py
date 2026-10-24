"""Diagnostic observation cannot turn input delivery into semantic acceptance."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
from navigation_diagnostic import NavigationTrace

class Probe:
    def __init__(self): self.calls=[];self.target={'hwnd':51};self.fail=False
    def admit(self):self.calls.append('admit');return self.target
    def guard(self):self.calls.append('guard');return self.target
    def start(self):self.calls.append('start')
    def read_navigation_trace(self):
        self.calls.append('read')
        if self.fail:raise RuntimeError('snapshot unavailable')
        return {'status':'complete','events':[], 'semanticHandlerProved':False}
    def can_stop(self):return True
    def stop(self):self.calls.append('stop')
    def close(self):self.calls.append('close');return {'controllerResourcesReleased':True}

class NavigationTraceTests(unittest.TestCase):
    def trace(self):
        self.now=1.;self.record={};self.probe=Probe()
        return NavigationTrace(None,None,{},None,self.record,10.,clock=lambda:self.now,probe=self.probe)
    def test_no_inputs_waits_or_semantic_claims(self):
        trace=self.trace();trace.start();trace.close()
        self.assertEqual(self.probe.calls,['admit','guard','start','guard','read','stop','close'])
        row=self.record['navigationDiagnostic']
        self.assertFalse(row['acceptanceEligible']);self.assertFalse(row['semanticHandlerProved'])
        self.assertEqual(row['deadline'],10.)
    def test_primary_failure_preserved_and_snapshot_precedes_unhook(self):
        trace=self.trace();trace.start();self.probe.fail=True
        primary=RuntimeError('semantic failure');trace.close(primary)
        self.assertIn('snapshot unavailable',self.record['navigationDiagnostic']['snapshotError'])
        self.assertEqual(self.probe.calls[-3:],['read','stop','close'])
    def test_expired_budget_does_not_renew_or_send_stop_message(self):
        trace=self.trace();trace.start();self.now=10.
        trace.close(RuntimeError('deadline failure'))
        self.assertEqual(self.probe.calls[-1],'close')
        self.assertNotIn('read',self.probe.calls);self.assertNotIn('stop',self.probe.calls)
        self.assertEqual(self.record['navigationDiagnostic']['snapshot']['status'],'unavailable')
    def test_snapshot_failure_is_not_success_without_primary(self):
        trace=self.trace();trace.start();self.probe.fail=True
        with self.assertRaisesRegex(RuntimeError,'snapshot unavailable'):trace.close()
        self.assertEqual(self.probe.calls[-1],'close')
    def test_idempotent_close_preserves_first_receipt(self):
        trace=self.trace();trace.start();trace.close();before=list(self.probe.calls);trace.close()
        self.assertEqual(before,self.probe.calls)

class NavigationAdmissionTests(unittest.TestCase):
    def test_wrong_owner_context_is_rejected_before_output_or_compilation(self):
        import json,os,tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        from suite.tests.test_korean_ime_smoke import ime
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);suite=root/'suite';suite.mkdir();fixtures=root/'fixtures';fixtures.mkdir()
            output=root/'diagnostic';event=root/'event.json';event.write_text('{}')
            (suite/'suite-inventory.json').write_text(json.dumps({'schemaVersion':1,'architecture':'x64'}))
            with patch.object(ime,'os',SimpleNamespace(name='nt',environ={})), patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(event)}), \
                 patch.object(ime.native_arch,'observe_native_architecture'), patch.object(ime.native_arch,'validate_native_architecture'), \
                 patch.object(ime.ascii_input,'prepare_observer') as prepare:
                with self.assertRaisesRegex(ValueError,'owner-push context'):
                    ime.main(['--suite',str(suite),'--fixtures',str(fixtures),'--readiness',str(root/'readiness.json'),
                        '--output',str(output),'--diagnose-navigation','impress'])
                prepare.assert_not_called();self.assertFalse(output.exists())

if __name__=='__main__':unittest.main()
