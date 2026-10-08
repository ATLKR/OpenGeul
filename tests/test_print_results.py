"""Reject incomplete, foreign or incorrectly configured virtual-printer jobs."""
import importlib.util
from pathlib import Path
import unittest
PATH=Path(__file__).resolve().parents[1]/'e2e/print_results.py'
class PrintResultTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PATH.exists(),'Missing terminal spooler-result validation')
        spec=importlib.util.spec_from_file_location('print_results',PATH)
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        self.queue='OpenGeul-CI-'+'a'*32
        self.job={'JobId':2,'pPrinterName':self.queue,'pDocument':'basic.hwpx - HOP','Status':128,'TotalPages':2,'PagesPrinted':2}
        self.media={'PaperSize':9,'PaperLength':2970,'PaperWidth':2100,'Orientation':1}
    def check(self,job=None,media=None):
        return self.m.completed_job([self.job if job is None else job],self.queue,'basic.hwpx',2,self.media if media is None else media)
    def test_printed_job_is_accepted(self):self.assertEqual(self.check()['JobId'],2)
    def test_pending_job_is_not_success(self):self.assertIsNone(self.check({**self.job,'Status':8}))
    def test_printing_job_is_not_success(self):self.assertIsNone(self.check({**self.job,'Status':16}))
    def test_no_job_is_not_success(self):self.assertIsNone(self.m.completed_job([],self.queue,'basic.hwpx',2,self.media))
    def test_error_even_alongside_printed_bit_fails(self):
        for flag in (1,2,4,32,64,256,512,1024):
            with self.assertRaises(ValueError):self.check({**self.job,'Status':128|flag})
    def test_unknown_or_missing_status_cannot_pass(self):
        for status in (None,-1,True,'128'):
            with self.assertRaises(ValueError):self.check({**self.job,'Status':status})
    def test_textual_error_takes_priority_over_printed_bit(self):
        with self.assertRaisesRegex(ValueError,'textual'):
            self.check({**self.job,'pStatus':'Paper jam'})
    def test_explicit_printed_text_is_accepted(self):
        self.assertEqual(self.check({**self.job,'pStatus':'Printed'})['JobId'],2)
    def test_other_queue_fails(self):
        with self.assertRaises(ValueError):self.check({**self.job,'pPrinterName':'physical-printer'})
    def test_another_document_fails(self):
        with self.assertRaises(ValueError):self.check({**self.job,'pDocument':'unrelated.hwpx - HOP'})
    def test_duplicate_print_job_fails(self):
        with self.assertRaises(ValueError):self.m.completed_job([self.job,self.job],self.queue,'basic.hwpx',2,self.media)
    def test_missing_or_extra_page_fails(self):
        for key in ('TotalPages','PagesPrinted'):
            for pages in (0,1,3,None,True):
                with self.assertRaises(ValueError):self.check({**self.job,key:pages})
    def test_wrong_media_or_orientation_fails(self):
        for key,value in [('PaperSize',1),('PaperLength',2794),('PaperWidth',2159),('Orientation',2)]:
            with self.assertRaises(ValueError):self.check(media={**self.media,key:value})
    def test_page_range_uses_printed_count_not_source_total(self):
        job={**self.job,'TotalPages':1,'PagesPrinted':1}
        self.assertEqual(self.m.completed_job([job],self.queue,'basic.hwpx',1,self.media)['TotalPages'],1)
    def test_expected_scenario_set_cannot_be_replaced_by_duplicates(self):
        good=[{'name':n} for n in self.m.REQUIRED_CASES];self.m.validate_cases(good)
        bad=good[:-1]+[good[0]]
        with self.assertRaises(ValueError):self.m.validate_cases(bad)
    def test_missing_case_and_unknown_case_fail(self):
        good=[{'name':n} for n in self.m.REQUIRED_CASES]
        with self.assertRaises(ValueError):self.m.validate_cases(good[:-1])
        with self.assertRaises(ValueError):self.m.validate_cases(good+[{'name':'new-unreviewed'}])
if __name__=='__main__':unittest.main()
