"""Actual virtual-printer E2E. No PDF-export, Page.printToPDF or spooler mocks."""
import copy,json,os,shutil,unittest
from pathlib import Path
from driver import Session,digest,edit
from virtual_printer import VirtualPrinter
from controls import PrintControls
from pdf_oracle import inspect_printed_pdf

ROOT=Path(os.environ['PRINT_OUTPUT']).resolve()
FIXTURES=Path(os.environ['PRINT_FIXTURES']).resolve()
EXE=Path(os.environ['E2E_EXE']).resolve()

class PrintingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.printer=VirtualPrinter(ROOT/'queue')
        cls.printer.__enter__()
        cls.addClassCleanup(cls.printer.close)
        cls.manifest=json.loads((FIXTURES/'print-manifest.json').read_text(encoding='utf-8'))
    def setUp(self):
        self.folder=ROOT/self._testMethodName;self.folder.mkdir(parents=True,exist_ok=True)
        self.session=None;self.controls=None
        self.addCleanup(self.close)
    def close(self):
        try:
            if self.controls:self.controls.capture()
        finally:
            if self.session:self.session.close()
    def open(self,name='print-basic',extension='hwpx'):
        self.document=self.folder/f'{name}.{extension}'
        shutil.copy2(FIXTURES/self.document.name,self.document)
        self.original=digest(self.document)
        self.expected=copy.deepcopy(self.manifest[name])
        self.session=Session('native',self.folder/'app',self.document,executable=EXE,accessibility=True)
        self.controls=PrintControls(self.session,self.folder)
    def output(self,pages=None):
        output=self.folder/'printed.pdf'
        job=self.controls.open().print(self.printer,output,pages=pages)
        report=inspect_printed_pdf(output,self.expected,self.folder/'pdf')
        self.assertEqual(digest(self.document),self.original,'Printing changed the original document')
        if job['TotalPages']:
            self.assertEqual(job['TotalPages'],report['page_count'],'Spooler and PDF page counts disagree')
        return report
    def test_hwpx_basic(self):self.open();self.output()
    def test_hwp_basic(self):self.open(extension='hwp');self.output()
    def test_unsaved_edit_is_printed_without_saving(self):
        self.open();edit(self.session.page,' UNSAVED-PRINT')
        self.expected['pages'][0].append('UNSAVED-PRINT');self.output()
        self.assertTrue(self.session.page.title().startswith('• '),'Printing cleared dirty state')
    def test_three_pages_in_order(self):self.open('print-three');self.output()
    def test_selected_second_page_only(self):
        self.open('print-three')
        all_pages=self.expected['pages']
        self.expected['pages']=[all_pages[1]]
        self.expected['forbidden']=all_pages[0]+all_pages[2]
        self.output(pages=2)
    def test_cancel_sends_nothing_and_editor_remains_usable(self):
        self.open();before=self.printer.ids();self.controls.open().cancel()
        self.assertEqual(self.printer.ids(),before)
        self.assertFalse((self.folder/'printed.pdf').exists())
        edit(self.session.page,' AFTER-CANCEL');self.expected['pages'][0].append('AFTER-CANCEL')
        self.output()
    def test_hwpx_table_first_and_last_lines(self):self.open('print-table');self.output()
    def test_hwp_table_first_and_last_lines(self):self.open('print-table','hwp');self.output()
