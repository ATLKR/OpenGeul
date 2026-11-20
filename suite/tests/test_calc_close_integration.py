"""GUI cleanup requires explicit generated-Calc authorization before close."""
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))


class CalcCloseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.native=importlib.import_module('windows_smoke')
        self.generated=importlib.import_module('generated_calc_close')

    def test_calc_without_explicit_proof_fails_before_posting_any_close(self):
        closes=[]
        api=NS(request_close=lambda *args:closes.append(args),user=NS(IsWindow=lambda h:False))
        with self.assertRaises(AssertionError):
            self.native.close_document(api,NS(pid=7),10,20,dict(module='calc'))
        self.assertEqual([],closes)

    def test_calc_routes_only_the_supplied_saved_or_blank_token_and_never_posts_second_close(self):
        for blank in (False,True):
            proof=(self.generated.GeneratedBlankCalc(Path('/suite'),object(),10,20,None,None,1,2,()) if blank
                   else self.generated.SavedCalcCopy(Path('/suite'),Path('/owned'),Path('/owned/OpenGeul-calc.xlsx'),'a'*64,()))
            routed=[];closes=[]
            api=NS(request_close=lambda *args:closes.append(args))
            process=NS(pid=7);record=dict(module='calc')
            with patch.object(self.generated,'close_generated_blank_calc',side_effect=lambda *args:routed.append(('blank',args))), \
                 patch.object(self.generated,'close_saved_calc_copy',side_effect=lambda *args:routed.append(('saved',args))):
                self.native.close_document(api,process,10,20,record,calc_close_proof=proof)
            self.assertEqual(['blank' if blank else 'saved'],[row[0] for row in routed])
            self.assertIs(proof,routed[0][1][-1]);self.assertEqual([],closes)

    def test_non_calc_cannot_receive_a_calc_discard_token(self):
        with self.assertRaises(AssertionError):
            self.native.close_document(NS(),NS(),10,20,dict(module='writer'),calc_close_proof=object())


if __name__=='__main__':unittest.main()
