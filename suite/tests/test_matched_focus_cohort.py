"""The private plugin lease spans preparation and all original cohort cleanup."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import korean_ime_smoke as ime
import plugin_file_origin
import ascii_message_preparation as preparation

class MatchedFocusCohortTests(unittest.TestCase):
    def test_remote_proof_rejected_before_any_filesystem_query(self):
        api=NS(preflight=lambda path:(_ for _ in ()).throw(ValueError('remote-drive')))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            with patch.object(plugin_file_origin,'FileApi',return_value=api),patch.object(Path,'lstat',side_effect=AssertionError('filesystem query before admission')),patch.object(Path,'open',side_effect=AssertionError('open before admission')):
                with self.assertRaisesRegex(ValueError,'remote-drive'):
                    ime.run_focus_cohort(root,root,root,{},'arm64',{},root/'proof.json')
    def test_lease_covers_compile_and_cases_and_releases_on_failure(self):
        for mode in ('success','unconfirmed','prepare-failure','close-failure','both-fail'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                output=Path(directory);proof=output/'proof.json';proof.write_text('{}')
                events=[];private={'path':'private-only'};receipt=dict(verified=True,released=False)
                def close():
                    events.append('close')
                    if mode in ('close-failure','both-fail'):raise ValueError('synthetic')
                    receipt['released']=True
                lease=NS(binding=lambda:private,receipt=receipt,close=close)
                lease_budgets=[]
                def make_lease(path,proof,budget,**kw):lease_budgets.append(budget);return lease
                def prepare(folder,*,architecture,budget):
                    events.append('prepare');self.assertIs(budget,lease_budgets[0])
                    if mode in ('prepare-failure','both-fail'):raise ValueError('synthetic preparation')
                    return {}
                def case(*args,**kw):
                    self.assertIs(kw['plugin_origin'],private);self.assertFalse(receipt['released']);events.append('case')
                    return dict(success=True,testProcessCleanup=dict(shellExitCode=0,disposition='already-exited'),
                        focusCohortEngineCleanup=dict(admitted=True,engineExitConfirmed=mode!='unconfirmed',handleReleased=True))
                self.assertTrue(hasattr(ime,'run_focus_cohort'),'bounded cohort integration absent')
                with patch.object(plugin_file_origin,'PluginFileLease',side_effect=make_lease),patch.object(plugin_file_origin,'FileApi',return_value=NS(preflight=lambda path:None)), \
                        patch.object(preparation,'prepare_observer',side_effect=prepare),patch.object(ime,'case',side_effect=case):
                    if mode in ('prepare-failure','both-fail'):
                        with self.assertRaisesRegex(ValueError,'preparation') as caught:
                            ime.run_focus_cohort(output,output,output,{},'arm64',{},proof)
                        self.assertEqual(caught.exception.pluginOriginReceipt['released'],mode!='both-fail')
                        if mode=='both-fail':self.assertEqual(caught.exception.pluginOriginCleanupErrorType,'ValueError')
                        retained=json.loads((output/'plugin-origin-failure.json').read_text())
                        self.assertEqual(retained['pluginFileOrigin']['released'],mode!='both-fail')
                        self.assertNotIn('private-only',json.dumps(retained))
                    else:
                        code=ime.run_focus_cohort(output,output,output,{},'arm64',{},proof)
                        report=json.loads((output/'results.json').read_text())
                        self.assertEqual(code,0 if mode=='success' else 1)
                        self.assertNotIn('private-only',json.dumps(report));self.assertFalse(report['acceptanceEligible'])
                        self.assertEqual(events.count('case'),1 if mode=='unconfirmed' else 3)
                self.assertEqual(events[-1],'close');self.assertEqual(events.count('close'),1)

if __name__=='__main__':unittest.main()
