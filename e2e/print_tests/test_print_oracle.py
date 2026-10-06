"""Use synthetic PDF drawing operations, not customer documents or font binaries."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from reportlab.pdfgen.canvas import Canvas

ORACLE = Path(__file__).resolve().parents[1] / 'print_oracle.py'

class PrintOracleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assertTrue(ORACLE.is_file(), 'Missing independent printed-PDF oracle')
        spec = importlib.util.spec_from_file_location('print_oracle', ORACLE)
        self.oracle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.oracle)

    def pdf(self, kind='good'):
        path = self.root / (kind + '.pdf')
        c = Canvas(str(path), pagesize=(595.28, 841.89))
        c.setFont('Helvetica', 16)
        c.drawString(72, 750, 'ROW0 Hg 0123456789')
        if kind != 'missing':
            c.saveState()
            if kind == 'clipped':
                clip = c.beginPath(); clip.rect(70, 102, 400, 40)
                c.clipPath(clip, stroke=0)
            if kind == 'invisible':
                t = c.beginText(72, 100); t.setTextRenderMode(3)
                t.textOut('ROW4 Hg 0123456789'); c.drawText(t)
            else:
                c.drawString(72, 100 if kind != 'outside' else -20, 'ROW4 Hg 0123456789')
            c.restoreState()
        if kind == 'extra': c.showPage(); c.drawString(72, 750, 'UNEXPECTED PAGE')
        c.save()
        return path

    def check(self, path, **kwargs):
        args = dict(pages=[{'size_pt':[595.28,841.89],
                    'markers':['ROW0 Hg 0123456789','ROW4 Hg 0123456789'],
                    'ink_pairs':[['ROW0 Hg','ROW4 Hg']]}])
        args.update(kwargs)
        return self.oracle.inspect_pdf(path, args, self.root/'renders')

    def test_valid_print_is_visible_and_keeps_descenders(self):
        result = self.check(self.pdf())
        self.assertEqual(result['pages'], 1)
        self.assertTrue((self.root/'renders/page-1.png').is_file())
    def test_missing_last_line_fails(self):
        with self.assertRaisesRegex(ValueError, 'marker'): self.check(self.pdf('missing'))
    def test_extraction_alone_cannot_pass_invisible_text(self):
        with self.assertRaisesRegex(ValueError, 'ink|visible'): self.check(self.pdf('invisible'))
    def test_partial_clipping_is_detected_from_raster(self):
        with self.assertRaisesRegex(ValueError, 'ink|clipp'): self.check(self.pdf('clipped'))
    def test_extra_blank_or_unexpected_page_fails(self):
        with self.assertRaisesRegex(ValueError, 'page'): self.check(self.pdf('extra'))
    def test_off_page_output_fails(self):
        with self.assertRaisesRegex(ValueError, 'bounds|marker'): self.check(self.pdf('outside'))
    def test_non_pdf_fails(self):
        path=self.root/'fake.pdf'; path.write_bytes(b'not a PDF')
        with self.assertRaises(ValueError): self.check(path)
    def test_invalid_expected_page_dimensions_fail_closed(self):
        for sizes in ([float('nan'),841.89], [float('inf'),841.89]):
            with self.assertRaises(ValueError):
                self.check(self.pdf(), pages=[{'size_pt':sizes,'markers':['ROW0 Hg']}])
    def test_empty_expectation_cannot_pass(self):
        with self.assertRaises(ValueError): self.check(self.pdf(), pages=[])

if __name__=='__main__': unittest.main()
