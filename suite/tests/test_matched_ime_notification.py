"""One IME case holds the existing exact plugin proof through cleanup."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import korean_ime_smoke as ime
import plugin_file_origin as origin
import ascii_message_preparation as preparation

class MatchedNotificationTests(unittest.TestCase):
    def test_single_case_holds_file_through_failure_and_compilation(self):
        self.assertTrue(hasattr(ime,'run_mode_diagnostic'),'single matched mode integration missing')
        for failure in ('none','case','prepare','release'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as d:
                root=Path(d).resolve();proof=root/'proof.json';proof.write_text('{}')
                events=[];private={'path':'synthetic-private'};receipt={'verified':True,'released':False};budgets=[]
                def close():
                    events.append('close')
                    if failure=='release':raise ValueError('synthetic release')
                    receipt['released']=True
                lease=NS(binding=lambda:private,receipt=receipt,close=close)
                def opened(*a,**k):budgets.append(a[2]);return lease
                def prepared(*a,**k):
                    events.append('prepare');self.assertIs(k['budget'],budgets[0])
                    if failure=='prepare':raise ValueError('synthetic preparation')
                    return {}
                def case(*a,**k):
                    events.append('case');self.assertFalse(receipt['released'])
                    self.assertTrue(k['capture_ime_caller']);self.assertIs(k['plugin_origin'],private)
                    return {'success':failure!='case'}
                with patch.object(origin,'FileApi',return_value=NS(preflight=lambda p:None)),patch.object(origin,'PluginFileLease',side_effect=opened),patch.object(preparation,'prepare_observer',side_effect=prepared),patch.object(ime,'case',side_effect=case):
                    if failure=='prepare':
                        with self.assertRaisesRegex(ValueError,'preparation') as caught:
                            ime.run_mode_diagnostic(root,root,root,{},'arm64',{},proof,capture_caller=True)
                        self.assertTrue(caught.exception.pluginOriginReceipt['released'])
                    else:
                        code=ime.run_mode_diagnostic(root,root,root,{},'arm64',{},proof,capture_caller=True)
                        self.assertEqual(code,0 if failure=='none' else 1)
                        report=json.loads((root/'results.json').read_text())
                        self.assertEqual(report['expectedCaseCount'],1);self.assertEqual(events.count('case'),1)
                        self.assertFalse(report['acceptanceEligible']);self.assertNotIn('synthetic-private',json.dumps(report))
                self.assertEqual(events[-1],'close');self.assertEqual(events.count('close'),1)
