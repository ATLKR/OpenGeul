"""Exercise Calc's durable-file predicate with real workbook bytes."""
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
import calc_save_smoke as calc
from test_calc_model_barrier import workbook


class CalcSavedBytePollingTests(unittest.TestCase):
    def poll(self, values, *, late=False):
        baseline=calc.read_cells(workbook());expected=baseline['a1Text']+calc.MARKER
        clock=[0.];receipt={};reads=[];sequence=iter(values)
        def read(path):
            reads.append(clock[0]);value=next(sequence)
            if late:clock[0]=.31
            if isinstance(value,Exception):raise value
            return value
        with patch.object(Path,'read_bytes',read),patch.object(calc.time,'monotonic',side_effect=lambda:clock[0]), \
                patch.object(calc.time,'sleep',side_effect=lambda n:clock.__setitem__(0,clock[0]+n)):
            try:
                value=calc.wait_for(lambda:calc.saving_workbook_snapshot(Path('owned.xlsx'),baseline,expected,.3,receipt),.3)
                error=None
            except Exception as exc:value,error=None,exc
        return value,error,receipt,reads

    def test_denied_then_original_then_exact_workbook_keeps_grid_and_snapshot_hash(self):
        raw=workbook(a1=calc.read_cells(workbook())['a1Text']+calc.MARKER)
        value,error,receipt,reads=self.poll([PermissionError(13,'denied'),workbook(),raw])
        self.assertIsNone(error);self.assertEqual(value['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(value['bytes'],len(raw));self.assertEqual(len(reads),3)
        self.assertEqual(receipt['transientCount'],1)

    def test_persistent_denial_and_late_valid_bytes_cannot_pass(self):
        valid=workbook(a1=calc.read_cells(workbook())['a1Text']+calc.MARKER)
        for values,late in (([PermissionError(13,'denied')]*10,False),([valid],True)):
            with self.subTest(late=late):
                value,error,receipt,reads=self.poll(values,late=late)
                self.assertIsNone(value);self.assertIsInstance(error,AssertionError)
                self.assertTrue(all(t<.3 for t in reads))

    def test_partial_zip_can_recover_but_parser_overrun_cannot_pass(self):
        valid=workbook(a1=calc.read_cells(workbook())['a1Text']+calc.MARKER)
        value,error,_,reads=self.poll([b'partial ZIP',valid])
        self.assertIsNone(error);self.assertEqual(value['sha256'],hashlib.sha256(valid).hexdigest())
        self.assertEqual(len(reads),2)
        baseline=calc.read_cells(workbook());receipt={};clock=[0.]
        original=calc.read_cells
        def late_parse(raw):
            result=original(raw);clock[0]=.31;return result
        with patch.object(Path,'read_bytes',return_value=valid),patch.object(calc,'read_cells',side_effect=late_parse), \
                patch.object(calc.time,'monotonic',side_effect=lambda:clock[0]):
            with self.assertRaisesRegex(AssertionError,'save deadline'):
                calc.saving_workbook_snapshot(Path('owned.xlsx'),baseline,baseline['a1Text']+calc.MARKER,.3,receipt)

    def test_wrong_edit_neighbor_or_formula_remains_fatal_without_retry(self):
        expected=calc.read_cells(workbook())['a1Text']+calc.MARKER
        for raw in (workbook(a1=expected+'duplicate'),workbook(a1=expected,b1='18'),
                    workbook(a1=expected,formula='SUM(B1:B1)')):
            value,error,_,reads=self.poll([raw])
            self.assertIsNone(value);self.assertIsInstance(error,AssertionError)
            self.assertEqual(len(reads),1)

    def test_parser_permission_error_is_fatal(self):
        original=calc.read_cells
        def parser(raw):
            if raw==b'parse-me':raise PermissionError(13,'parser')
            return original(raw)
        with patch.object(calc,'read_cells',side_effect=parser):
            _,error,receipt,reads=self.poll([b'parse-me'])
        self.assertIsInstance(error,PermissionError);self.assertEqual(len(reads),1)
        self.assertEqual(receipt['transientCount'],0)
