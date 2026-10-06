from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class PrintIntegrationTests(unittest.TestCase):
    def test_full_build_calls_printer_gate(self):
        text=(ROOT/'.github/workflows/msix.yml').read_text()
        self.assertIn('uses: ./.github/workflows/printing.yml',text)
        self.assertIn('build-sha: ${{ github.sha }}',text)
    def test_release_requires_printer_gate(self):
        text=(ROOT/'.github/workflows/msix.yml').read_text().split('  release:\n')[1]
        self.assertIn('printer-e2e',text.splitlines()[0])
    def test_no_bypass_print_or_skipping(self):
        text=(ROOT/'e2e/printing/ui.py').read_text()
        self.assertIn("menu(session.page, 'file:print')",text)
        for banned in ('Page.printToPDF','page.pdf(', 'file:export-pdf', 'skipTest(', 'continue-on-error'):
            self.assertNotIn(banned,text)
    def test_probe_pins_candidate_and_full_gate_has_no_fixed_run(self):
        self.assertIn("build-run: '37404480348'",(ROOT/'.github/workflows/printer-probe.yml').read_text())
        self.assertNotIn('37404480348',(ROOT/'.github/workflows/msix.yml').read_text())
