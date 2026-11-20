"""Exercise Calc's durable-file predicate with real workbook bytes."""
import hashlib
import zipfile
from pathlib import Path
import unittest
from unittest.mock import patch
import calc_save_smoke as calc
from test_calc_model_barrier import workbook


class CalcSavedBytePollingTests(unittest.TestCase):
    def poll(self, values, *, late=False, seconds=.3):
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
                value=calc.wait_for(lambda:calc.saving_workbook_snapshot(Path('owned.xlsx'),baseline,expected,seconds,receipt),seconds)
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
        self.assertEqual(receipt.get('outcomeCounts'),[0]*5);self.assertEqual(receipt.get('lastOutcomeCode'),0)

    def test_wrong_edit_neighbor_or_formula_remains_fatal_without_retry(self):
        expected=calc.read_cells(workbook())['a1Text']+calc.MARKER
        for raw in (workbook(a1=expected+'duplicate'),workbook(a1=expected,b1='18'),
                    workbook(a1=expected,formula='SUM(B1:B1)')):
            value,error,receipt,reads=self.poll([raw])
            self.assertIsNone(value);self.assertIsInstance(error,AssertionError)
            self.assertEqual(len(reads),1)
            self.assertEqual(receipt.get('outcomeCounts'),[0]*5);self.assertEqual(receipt.get('lastOutcomeCode'),0)

    def test_parser_permission_error_is_fatal(self):
        original=calc.read_cells
        def parser(raw):
            if raw==b'parse-me':raise PermissionError(13,'parser')
            return original(raw)
        with patch.object(calc,'read_cells',side_effect=parser):
            _,error,receipt,reads=self.poll([b'parse-me'])
        self.assertIsInstance(error,PermissionError);self.assertEqual(len(reads),1)
        self.assertEqual(receipt['transientCount'],0)
        self.assertEqual(receipt.get('outcomeCounts'),[0]*5);self.assertEqual(receipt.get('lastOutcomeCode'),0)


    def test_all_five_outcomes_are_numeric_and_do_not_change_retry_counts(self):
        valid=workbook(a1=calc.read_cells(workbook())['a1Text']+calc.MARKER)
        value,error,receipt,reads=self.poll([FileNotFoundError(2,'opaque'),PermissionError(13,'opaque'),b'partial ZIP',workbook(),valid],seconds=.6)
        self.assertIsNone(error);self.assertEqual(value['bytes'],len(valid))
        self.assertEqual(receipt.get('outcomeCounts'),[1,1,1,1,1]);self.assertEqual(receipt.get('lastOutcomeCode'),5)
        self.assertEqual(receipt['attempts'],5);self.assertEqual(receipt['transientCount'],2)
        self.assertEqual(len(reads),5);self.assertEqual(receipt['deadline'],.6)

    def test_persistent_classified_outcomes_still_fail_the_original_wait(self):
        for code,payload in ((1,FileNotFoundError(2,'opaque')),(2,PermissionError(13,'opaque')),(3,b'partial ZIP'),(4,workbook())):
            with self.subTest(code=code):
                value,error,receipt,reads=self.poll([payload]*10)
                self.assertIsNone(value);self.assertIsInstance(error,AssertionError)
                expected=[0]*5;expected[code-1]=len(reads)
                self.assertEqual(receipt.get('outcomeCounts'),expected);self.assertEqual(receipt.get('lastOutcomeCode'),code)
                self.assertEqual(receipt['attempts'],len(reads));self.assertTrue(all(t<.3 for t in reads))

    def test_bad_zip_recording_preserves_the_exact_exception_and_clock_calls(self):
        class OpaqueZip(zipfile.BadZipFile):
            def __str__(self):raise AssertionError('diagnostic string conversion forbidden')
            def __repr__(self):raise AssertionError('diagnostic repr forbidden')
        failure=OpaqueZip('opaque');receipt={};baseline=calc.read_cells(workbook())
        with patch.object(Path,'read_bytes',return_value=b'parse'),patch.object(calc,'read_cells',side_effect=failure),patch.object(calc.time,'monotonic',return_value=0.) as clock:
            with self.assertRaises(OpaqueZip) as caught:calc.saving_workbook_snapshot(Path('owned.xlsx'),baseline,baseline['a1Text']+calc.MARKER,1.,receipt)
        self.assertIs(caught.exception,failure);self.assertEqual(clock.call_count,2)
        self.assertEqual(receipt.get('outcomeCounts'),[0,0,1,0,0]);self.assertEqual(receipt.get('lastOutcomeCode'),3)
        self.assertEqual(receipt['attempts'],1);self.assertEqual(receipt['transientCount'],0)

    def test_outcome_bookkeeping_adds_no_reads_or_clock_observations(self):
        baseline=calc.read_cells(workbook());valid=workbook(a1=baseline['a1Text']+calc.MARKER)
        for code,payload,calls in ((1,FileNotFoundError(2,'opaque'),3),(2,PermissionError(13,'opaque'),3),(3,b'partial ZIP',2),(4,workbook(),3),(5,valid,4)):
            with self.subTest(code=code):
                receipt={}
                effect={'side_effect':payload} if isinstance(payload,Exception) else {'return_value':payload}
                with patch.object(Path,'read_bytes',**effect) as read,patch.object(calc.time,'monotonic',return_value=0.) as clock:
                    if code==3:
                        with self.assertRaises(zipfile.BadZipFile):calc.saving_workbook_snapshot(Path('owned.xlsx'),baseline,baseline['a1Text']+calc.MARKER,1.,receipt)
                    else:calc.saving_workbook_snapshot(Path('owned.xlsx'),baseline,baseline['a1Text']+calc.MARKER,1.,receipt)
                self.assertEqual(read.call_count,1);self.assertEqual(clock.call_count,calls)
                self.assertEqual(receipt.get('lastOutcomeCode'),code)

    def test_unknown_transient_and_invalid_diagnostic_state_cannot_change_behavior(self):
        class OpaqueDenied(PermissionError):
            def __str__(self):raise AssertionError('diagnostic string conversion forbidden')
            def __repr__(self):raise AssertionError('diagnostic repr forbidden')
        baseline=calc.read_cells(workbook());expected=baseline['a1Text']+calc.MARKER;receipt={}
        with patch.object(Path,'read_bytes',side_effect=OpaqueDenied(13,'opaque')),patch.object(calc.time,'monotonic',return_value=0.):
            self.assertIs(calc.saving_workbook_snapshot(Path('owned.xlsx'),baseline,expected,1.,receipt),False)
        self.assertEqual(receipt.get('outcomeCounts'),[0]*5);self.assertEqual(receipt.get('lastOutcomeCode'),0)
        self.assertEqual(receipt['attempts'],1);self.assertEqual(receipt['transientCount'],1)
        class Opaque:
            def __str__(self):raise AssertionError('diagnostic string conversion forbidden')
            def __repr__(self):raise AssertionError('diagnostic repr forbidden')
        poison=Opaque();receipt={'outcomeCounts':poison};valid=workbook(a1=expected)
        with patch.object(Path,'read_bytes',return_value=valid),patch.object(calc.time,'monotonic',return_value=0.):
            result=calc.saving_workbook_snapshot(Path('owned.xlsx'),baseline,expected,1.,receipt)
        self.assertEqual(result['bytes'],len(valid));self.assertIs(receipt.get('outcomeCounts'),poison)

    def test_stale_transient_cannot_classify_a_later_unknown_none(self):
        baseline=calc.read_cells(workbook());expected=baseline['a1Text']+calc.MARKER
        for mode in ('unchanged','attempt-only','same-transient-object'):
            with self.subTest(mode=mode):
                receipt={}
                with patch.object(Path,'read_bytes',side_effect=PermissionError(13,'opaque')),patch.object(calc.time,'monotonic',return_value=0.):
                    self.assertIs(calc.saving_workbook_snapshot(Path('owned.xlsx'),baseline,expected,1.,receipt),False)
                self.assertEqual(receipt.get('outcomeCounts'),[0,1,0,0,0])
                def unknown(*_):
                    if mode!='unchanged':receipt['attempts']+=1
                    if mode=='same-transient-object':receipt['transientCount']+=1
                    return None
                with patch.object(calc.native,'read_saving_document',side_effect=unknown):
                    self.assertIs(calc.saving_workbook_snapshot(Path('owned.xlsx'),baseline,expected,1.,receipt),False)
                self.assertEqual(receipt.get('outcomeCounts'),[0,1,0,0,0])
                self.assertEqual(receipt.get('lastOutcomeCode'),0)
