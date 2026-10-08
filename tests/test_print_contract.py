"""Release and safety checks need no printer/PDF dependencies."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class PrintContractTests(unittest.TestCase):
    def test_required_print_jobs_gate_release(self):
        text=(ROOT/'.github/workflows/msix.yml').read_text()
        self.assertIn('  virtual-print:',text)
        release=text.split('  release:',1)[1]
        self.assertIn('virtual-print',release.split('    steps:',1)[0])
        self.assertNotIn('continue-on-error: true',text)
    def test_no_fallback_to_direct_pdf_or_test_bridge(self):
        path=ROOT/'e2e/virtual_print.py'
        self.assertTrue(path.is_file(),'Missing real virtual-printer test')
        text=path.read_text()
        for forbidden in ['Page.printToPDF','export_pdf','file:export-pdf','window.__wasm']:
            self.assertNotIn(forbidden,text)
        self.assertIn('spool',text.lower())
    def test_printing_tools_are_test_only_and_pinned(self):
        text=(ROOT/'e2e/print-requirements.txt').read_text()
        self.assertIn('pypdfium2==',text)
        self.assertIn('reportlab==',text)
        self.assertNotIn('pypdfium2',(ROOT/'scripts/build-msix.ps1').read_text())
    def test_ownership_is_limited_to_disposable_windows_runner(self):
        path=ROOT/'e2e/print_queue.py'
        self.assertTrue(path.is_file(),'Missing printer ownership guard')
        text=path.read_text()
        for required in ['github-hosted','GITHUB_ACTIONS','Microsoft Print To PDF','PORTPROMPT:']:
            self.assertIn(required,text)
