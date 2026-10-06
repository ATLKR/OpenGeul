"""Real Windows Print to PDF scenarios. A virtual driver is not physical-printer certification."""
import json
import os
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from driver import Session, digest, edit
from run import EvidenceResult
from fixtures import make_fixture, FIRST, LAST
from oracle import inspect_pdf, compare_terminal_ink
from spooler import VirtualPrinter, require_host
from ui import print_document


class PrinterTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(os.environ['PRINT_EVIDENCE']) / self._testMethodName
        self.folder.mkdir(parents=True, exist_ok=True)
        self.inputs = Path(os.environ['E2E_FIXTURES'])
        self.exe = Path(os.environ['E2E_EXE'])
        self.reports = []

    def exercise(self, *, pages=1, landscape=False, table_spacing=None, legacy=False, changed=False, cancel=False):
        suffix = str(table_spacing) if table_spacing is not None else 'document'
        folder = self.folder / suffix; folder.mkdir()
        source = folder / 'print-input.hwpx'
        base = self.inputs / (f'table-spacing-{table_spacing}.hwpx' if table_spacing is not None else 'basic.hwpx')
        expected = make_fixture(base, source, pages=pages, landscape=landscape, table=table_spacing is not None)
        with VirtualPrinter(landscape=landscape) as printer:
            session = Session('native', folder / 'session', source, executable=self.exe)
            try:
                if legacy:
                    target = folder / 'print-input.hwp'
                    session.save(source, target, save_as=True)
                    session.close(); session = Session('native', folder / 'legacy-session', target, executable=self.exe)
                    source = target
                original = digest(source)
                if changed:
                    edit(session.page, ' PRINT-UNSAVED-456')
                    expected['pages'][-1].append('PRINT-UNSAVED-456')
                title = session.page.title()
                output = folder / 'printer-output.pdf'
                jobs = print_document(session, printer, output, cancel=cancel)
                self.assertEqual(digest(source), original, 'Printing modified the source file')
                self.assertEqual(session.page.title(), title, 'Printing changed dirty-state/title')
                report = None if cancel else inspect_pdf(output, expected, folder / 'rendered')
                record = {'printer': printer.name, 'driver': 'Microsoft Print To PDF', 'jobs': jobs,
                          'sourceSha256': original, 'cancelled': cancel, 'pdf': report}
                (folder / 'print-result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
                self.reports.append(record)
                return report
            finally: session.close()

    def test_hwpx_a4_actual_spooler_output(self): self.exercise()
    def test_hwp_actual_spooler_output(self): self.exercise(legacy=True)
    def test_three_pages_no_extra_blank_page(self): self.exercise(pages=3)
    def test_landscape_paper(self): self.exercise(landscape=True)
    def test_unsaved_edits_print_without_saving(self): self.exercise(changed=True)
    def test_cancel_preserves_unsaved_document_and_submits_no_job(self): self.exercise(changed=True, cancel=True)
    def test_compressed_table_terminal_glyph_matches_control(self):
        control = self.exercise(table_spacing=0)
        compressed = self.exercise(table_spacing=-300)
        ratio = compare_terminal_ink(compressed['pages'][0]['markers'][LAST]['inkPixels'],
                                     control['pages'][0]['markers'][LAST]['inkPixels'])
        (self.folder / 'terminal-ink.json').write_text(json.dumps({'compressedOverControl': ratio}))


def main():
    require_host(os.environ)
    output = Path(os.environ['PRINT_EVIDENCE']); output.mkdir(parents=True, exist_ok=True)
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(PrinterTests))
    success = result.wasSuccessful() and not result.skipped and result.testsRun == 7
    payload = {'success': success, 'expectedTests': 7, 'testsRun': result.testsRun, 'tests': result.records,
               'head': os.environ.get('GITHUB_SHA'), 'run': os.environ.get('GITHUB_RUN_ID'),
               'buildSource': os.environ.get('PRINT_BUILD_SHA', os.environ.get('GITHUB_SHA')),
               'scope': 'Microsoft PDF virtual driver, real app Print UI and spooler; not physical printer certification'}
    (output / 'results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    root = ET.Element('testsuite', name='OpenGeul virtual printer', tests=str(result.testsRun), failures=str(len(result.failures)), errors=str(len(result.errors)))
    for record in result.records:
        child = ET.SubElement(root, 'testcase', name=record['test'], time=str(record['seconds']))
        if record['status'] != 'passed': ET.SubElement(child, 'failure').text = record['message']
    ET.ElementTree(root).write(output / 'junit.xml', encoding='utf-8', xml_declaration=True)
    return 0 if success else 1

if __name__ == '__main__': sys.exit(main())
