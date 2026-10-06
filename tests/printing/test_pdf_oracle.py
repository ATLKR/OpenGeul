"""Negative controls for the independent printed-output oracle (synthetic PDFs only)."""
import sys
import tempfile
import unittest
from pathlib import Path
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'e2e' / 'printing'))
from pdf_oracle import inspect_printed_pdf


class PrintedPDFTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'printed.pdf'
        self.expected = {'pages': [['PRINT-FIRST', 'PRINT-LAST']], 'size_pt': [595.276, 841.89]}

    def pdf(self, mode='normal', pages=1):
        c = canvas.Canvas(str(self.path), pagesize=tuple(self.expected['size_pt']))
        for i in range(pages):
            if mode != 'blank':
                c.drawString(50, 780, 'PRINT-FIRST')
                if mode != 'missing':
                    if mode == 'invisible':
                        t = c.beginText(50, 100); t.setTextRenderMode(3); t.textOut('PRINT-LAST'); c.drawText(t)
                    else:
                        c.drawString(50, -20 if mode == 'outside' else 100, 'PRINT-LAST')
                    if mode == 'covered':
                        c.setFillColorRGB(1, 1, 1); c.rect(45, 90, 150, 35, fill=1, stroke=0)
            c.showPage()
        c.save()
        return self.path

    def inspect(self):
        return inspect_printed_pdf(self.path, self.expected, self.root / 'evidence')

    def test_accepts_visible_markers_and_emits_rendered_evidence(self):
        self.pdf(); result = self.inspect()
        self.assertEqual(result['page_count'], 1)
        self.assertTrue((self.root / 'evidence/page-1.png').is_file())
        self.assertEqual(len(result['sha256']), 64)

    def test_rejects_missing_last_line(self):
        self.pdf('missing')
        with self.assertRaises(AssertionError): self.inspect()

    def test_rejects_blank_page(self):
        self.pdf('blank')
        with self.assertRaises(AssertionError): self.inspect()

    def test_rejects_extra_page(self):
        self.pdf(pages=2)
        with self.assertRaises(AssertionError): self.inspect()

    def test_rejects_text_outside_page(self):
        self.pdf('outside')
        with self.assertRaises(AssertionError): self.inspect()

    def test_rejects_invisible_but_extractable_text(self):
        self.pdf('invisible')
        self.assertIn('PRINT-LAST', PdfReader(self.path).pages[0].extract_text())
        with self.assertRaises(AssertionError): self.inspect()

    def test_rejects_white_occluded_text(self):
        self.pdf('covered')
        self.assertIn('PRINT-LAST', PdfReader(self.path).pages[0].extract_text())
        with self.assertRaises(AssertionError): self.inspect()

    def test_rejects_wrong_paper_size(self):
        self.pdf(); self.expected['size_pt'] = [612, 792]
        with self.assertRaises(AssertionError): self.inspect()

    def test_rejects_encrypted_pdf(self):
        self.pdf(); writer = PdfWriter(clone_from=self.path); writer.encrypt('secret')
        with self.path.open('wb') as f: writer.write(f)
        with self.assertRaises(AssertionError): self.inspect()

    def test_rejects_non_pdf(self):
        self.path.write_bytes(b'not a PDF')
        with self.assertRaises(AssertionError): self.inspect()

    def test_rejects_empty_expectations(self):
        self.pdf(); self.expected['pages'] = [[]]
        with self.assertRaises(AssertionError): self.inspect()

    def test_page_order_and_forbidden_markers(self):
        self.pdf(); self.expected['forbidden'] = ['PRINT-FIRST']
        with self.assertRaises(AssertionError): self.inspect()
