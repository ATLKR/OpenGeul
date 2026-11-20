"""Finite synthetic DUMPBIN records, never execution or physical-input evidence."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/mutex_call_classification.py'
BASE=0x180000000

def listing(rows):
    return 'Dump of file private.dll\nFile Type: DLL\n'+''.join(f'  {BASE+0x1000+4*i:016X}: {s}\n' for i,s in enumerate(rows))

class CallClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('call_classifier',SCRIPT)
        cls.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.m)
    def run_rows(self,rows,**kw):
        return self.m.parse_and_classify(listing(rows),image_base=BASE,function_range={'beginRva':0x1000,'endRvaExclusive':0x1000+4*len(rows)},**kw)
    def test_fixture_requires_one_known_direct_call(self):
        r=self.run_rows(['stp x29,x30,[sp,#-0x10]!','bl 0000000180001200','ret'],fixture_target=0x1200)
        self.assertTrue(r['fixtureValidated']);self.assertEqual(r['calls'][0]['targetRva'],0x1200)
        for rows in (['ret'],['bl 0000000180001204'],['bl 0000000180001200','bl 0000000180001200']):
            with self.assertRaises(self.m.ClassificationError):self.run_rows(rows,fixture_target=0x1200)
    def test_adjacent_known_import_and_nonadjacent_unproved(self):
        rows=['adrp x8,0000000180002000','ldr x8,[x8,#0x400]','blr x8']
        r=self.run_rows(rows,condition_iat=0x2400)
        self.assertEqual(r['calls'][0]['flow'],'adjacent-known-condition-import')
        for altered in (rows[:2]+['mov x8,x9',rows[2]],rows[:1]+['nop']+rows[1:],['adrp xzr,0000000180002000','ldr x8,[sp,#0x400]','blr x8']):
            self.assertEqual(self.run_rows(altered,condition_iat=0x2400)['calls'][0]['flow'],'unproved-register-flow')
    def test_calls_clear_no_targets_followed_and_zero_explicit(self):
        r=self.run_rows(['bl 0000000180009000','blr x9','ret'])
        self.assertFalse(r['attributionProved']);self.assertEqual(r['callCount'],2)
        self.assertFalse(r['calls'][0]['targetWithinRange']);self.assertEqual(self.run_rows(['ret'])['callCount'],0)
        self.assertNotIn('1800',str(r));self.assertNotIn('private',str(r))
    def test_complete_rows_and_bounded_format(self):
        good=listing(['nop','ret']);kw=dict(image_base=BASE,function_range={'beginRva':0x1000,'endRvaExclusive':0x1008})
        for text in (good.replace('0000000180001004','0000000180001000'),good.replace('0000000180001004','0000000180001008'),good.splitlines()[0],good+'UNKNOWN HEADER\n','x'*262145,good.replace('nop','frobnicate')):
            with self.assertRaises(self.m.ClassificationError):self.m.parse_and_classify(text,**kw)
        with self.assertRaises(self.m.ClassificationError):self.run_rows(['nop']*26)
        with self.assertRaises(self.m.ClassificationError):self.run_rows(['blr x8']*9)
    def test_unknown_call_syntax_and_branch_breaks_import_flow(self):
        for operand in ('x31','sp','xzr','x8, x9'):
            with self.assertRaises(self.m.ClassificationError):self.run_rows(['blr '+operand])
        r=self.run_rows(['adrp x8,0000000180002000','b 000000018000100C','ldr x8,[x8,#0x400]','blr x8'],condition_iat=0x2400)
        self.assertEqual(r['calls'][0]['flow'],'unproved-control-flow')
    def test_incoming_branch_keeps_adjacent_import_match_unproved(self):
        r=self.run_rows(['b 0000000180001008','adrp x8,0000000180002000','ldr x8,[x8,#0x400]','blr x8'],condition_iat=0x2400)
        self.assertEqual(r['calls'][0]['flow'],'unproved-control-flow')
    def test_fixture_and_production_receipts_never_emit_input_text(self):
        r=self.run_rows(['bl 0000000180001200','ret'],fixture_target=0x1200)
        text=str(r)
        for forbidden in ('private.dll','000000018','bl ','ret','x8'):
            self.assertNotIn(forbidden,text.replace('returnRva',''))
    def test_errors_expose_only_closed_reason_codes(self):
        with self.assertRaises(self.m.ClassificationError) as caught:
            self.m.parse_and_classify('private/path malformed raw input',image_base=BASE,function_range={'beginRva':0x1000,'endRvaExclusive':0x1004})
        self.assertEqual(caught.exception.reason_code,'unsupported-output-line')
        forged=self.m.ClassificationError('private/path arbitrary error')
        self.assertEqual(forged.reason_code,'classification-failure')
        self.assertNotIn('private',str(forged))
