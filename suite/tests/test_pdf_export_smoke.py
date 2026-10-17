"""Portable PDF oracle regressions; these do not claim Windows engine success."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                           NameObject, NumberObject, TextStringObject)


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'pdf_export_smoke.py'
smoke = None
if SOURCE.exists():
    spec = importlib.util.spec_from_file_location('suite_pdf_export_smoke', SOURCE)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)


def write_pdf(path, pages, metadata=None):
    """Real, independently parsed PDFs with a Unicode text CMap, no Office mocks."""
    writer = PdfWriter()
    chars = sorted(set(''.join(pages)))
    cmap = DecodedStreamObject()
    cmap.set_data(('begincmap\n/CMapType 2 def\n1 begincodespacerange\n'
                   '<0000> <FFFF>\nendcodespacerange\n' + str(len(chars)) +
                   ' beginbfchar\n' + '\n'.join('<%04x> <%04x>' % (ord(c), ord(c)) for c in chars) +
                   '\nendbfchar\nendcmap').encode('ascii'))
    descendant = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/CIDFontType2'), NameObject('/BaseFont'): NameObject('/OracleFont'),
        NameObject('/CIDSystemInfo'): DictionaryObject({NameObject('/Registry'): TextStringObject('Adobe'),
            NameObject('/Ordering'): TextStringObject('Identity'), NameObject('/Supplement'): NumberObject(0)})})
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type0'), NameObject('/BaseFont'): NameObject('/OracleFont'),
        NameObject('/Encoding'): NameObject('/Identity-H'),
        NameObject('/DescendantFonts'): ArrayObject([writer._add_object(descendant)]),
        NameObject('/ToUnicode'): writer._add_object(cmap)})
    reference = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): reference})})
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 12 Tf 30 800 Td <' + text.encode('utf-16-be').hex() + '> Tj ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    if metadata:
        writer.add_metadata(metadata)
    with path.open('wb') as output:
        writer.write(output)


class PdfExportOracleTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(smoke, 'The independent PDF export verifier is not implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        (self.output / 'exports').mkdir()

    def production(self):
        records = []
        for case in smoke.case_specs():
            path = self.output / 'exports' / (case['module'] + '.pdf')
            write_pdf(path, [' '.join(markers) for markers in case['pageMarkers']])
            data = path.read_bytes()
            records.append(dict(module=case['module'], status='passed', filter=case['filter'],
                expected=case, relativePath='exports/' + path.name,
                sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
                ownedEngineClosed=True, guiVerified=False, physicalPrintingVerified=False))
        return dict(schemaVersion=1, kind='engine-pdf-export-production', passed=True,
            guiVerified=False, physicalPrintingVerified=False, cases=records)

    def replace_pdf(self, production, module, pages, metadata=None):
        record = next(row for row in production['cases'] if row['module'] == module)
        path = self.output / record['relativePath']
        write_pdf(path, pages, metadata)
        data = path.read_bytes()
        record.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))

    def test_real_unicode_pdf_pages_pass_and_text_is_recorded(self):
        report = smoke.verify_exports(self.output, self.production())
        self.assertTrue(report['passed'], report)
        self.assertEqual(len(report['cases']), 5)
        self.assertEqual([row['pageCount'] for row in report['cases']], [2, 1, 2, 1, 1])
        self.assertTrue(all('한글' in row['pageText'][0] for row in report['cases']))
        self.assertEqual(report['verifier']['version'], '6.21.0')
        self.assertIs(report['guiVerified'], False)
        self.assertIs(report['physicalPrintingVerified'], False)

    def test_pdf_header_and_metadata_cannot_substitute_for_page_text(self):
        production = self.production()
        wanted = production['cases'][1]['expected']['pageMarkers'][0]
        self.replace_pdf(production, 'calc', ['A different spreadsheet'], {'/Subject': ' '.join(wanted)})
        report = smoke.verify_exports(self.output, production)
        self.assertFalse(report['passed'])
        failure = next(row for row in report['cases'] if row['module'] == 'calc')
        self.assertEqual(failure['status'], 'failed')
        self.assertIn('marker', failure['error']['message'])

    def test_exact_page_count_and_each_pages_markers_are_required(self):
        for defect in ('extra-blank-page', 'missing-page', 'wrong-page'):
            with self.subTest(defect=defect):
                production = self.production()
                wanted = production['cases'][0]['expected']['pageMarkers']
                pages = [' '.join(markers) for markers in wanted]
                pages = pages + [''] if defect == 'extra-blank-page' else pages[:1] if defect == 'missing-page' else [pages[0], pages[0]]
                self.replace_pdf(production, 'writer', pages)
                self.assertFalse(smoke.verify_exports(self.output, production)['passed'])

    def test_duplicate_missing_or_unreviewed_cases_and_changed_expectations_fail_closed(self):
        production = self.production()
        variants = [production['cases'][:-1], production['cases'] + [production['cases'][0]],
                    production['cases'][1:] + [production['cases'][0]]]
        changed = copy.deepcopy(production['cases'])
        changed[0]['expected']['pageMarkers'][0] = ['A different document']
        variants.append(changed)
        for cases in variants:
            with self.subTest(cases=cases):
                self.assertFalse(smoke.verify_exports(self.output, dict(production, cases=cases))['passed'])

    def test_changed_bytes_empty_pdf_or_linked_export_cannot_pass(self):
        for defect in ('changed-bytes', 'empty', 'link'):
            with self.subTest(defect=defect):
                production = self.production()
                path = self.output / production['cases'][0]['relativePath']
                if defect == 'changed-bytes':
                    path.write_bytes(path.read_bytes() + b'changed after production')
                elif defect == 'empty':
                    path.write_bytes(b'')
                else:
                    target = self.output / 'outside.pdf'
                    path.replace(target)
                    path.symlink_to(target)
                self.assertFalse(smoke.verify_exports(self.output, production)['passed'])
                if path.is_symlink():
                    path.unlink()

    def test_verifier_failure_retains_json_log_exports_and_producer_hash_join(self):
        production = self.production()
        production['suite'] = str(self.output / 'suite')
        report_path = self.output / smoke.PRODUCTION_REPORT
        report_path.write_text(json.dumps(production), encoding='utf-8')
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            code = smoke.main(['--verify', '--suite', str(self.output / 'suite'), '--output', str(self.output)])
        self.assertEqual(code, 1)
        report = json.loads((self.output / smoke.VERIFICATION_REPORT).read_text())
        self.assertFalse(report['passed'])
        self.assertEqual(report['productionReportSha256'], hashlib.sha256(report_path.read_bytes()).hexdigest())
        self.assertEqual(len(report['cases']), 5, 'Identity failure must retain independent PDF diagnostics')
        self.assertTrue(all(row.get('pageText') for row in report['cases']))
        self.assertTrue((self.output / 'pdf-verification.log').is_file())
        self.assertEqual(len(list((self.output / 'exports').glob('*.pdf'))), 5)


class PdfProducerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.suite = self.root / 'suite'
        self.suite.mkdir()
        self.output = self.root / 'evidence'
        self.output.mkdir()
        (self.output / 'sources').mkdir()
        (self.output / 'exports').mkdir()

    def run_generated_case(self, cleanup_error=False, change_url=False):
        events = []
        path = self.output / 'exports' / 'writer.pdf'

        class Document:
            url = ''

            def storeToURL(self, url, props):
                events.append(('pdf-export', dict(props)))
                path.write_bytes(b'%PDF-1.7\nbefore engine cleanup')
                if change_url:
                    self.url = url

            def getURL(self):
                return self.url

        class Engine:
            def __init__(self, suite):
                self.cleanup_errors = []
                self.document = Document()
                member = dict(pid=99, creationTime=789, image=str(suite / 'Office/program/soffice.bin'), alive=True, exitCode=259)
                self.owned_job_evidence = dict(jobHandleValue=42, initial=[member],
                    final=[dict(member, alive=False, exitCode=0)], finalJobPids=[], jobEmptyVerified=True)

            def start(self):
                events.append('start-owned-engine')

            def load(self, url):
                events.append(('load', url))
                self.document.url = url
                return self.document

            def prop(self, name, value):
                return name, value

            def store_new(self, document, target, source_filter):
                events.append(('save-native', source_filter))
                target.write_bytes(b'generated native fixture')
                document.url = target.as_uri()

            def close_document(self, document):
                events.append('close-generated-model')

            def cleanup(self):
                events.append('cleanup-owned-engine')
                if path.exists():
                    path.write_bytes(b'%PDF-1.7\nfinal bytes after owned cleanup')
                if cleanup_error:
                    self.cleanup_errors.append('Owned process remained alive')

        self.assertTrue(hasattr(smoke, 'run_case'), 'The owned PDF producer is not implemented')
        with patch.object(smoke, 'Engine', Engine, create=True), \
                patch.object(smoke, '_populate', create=True), \
                patch.object(smoke, '_validate_model', create=True), \
                patch.object(smoke, '_require_font', create=True), \
                patch.object(smoke, '_interaction_handler', return_value=object(), create=True):
            record = smoke.run_case(self.suite, self.output, smoke.case_specs()[0])
        return record, events, path

    def test_producer_uses_pdf_filter_without_replacing_source_and_hashes_after_owned_cleanup(self):
        record, events, path = self.run_generated_case()
        self.assertEqual(record['status'], 'passed', record)
        export = next(event[1] for event in events if isinstance(event, tuple) and event[0] == 'pdf-export')
        self.assertEqual(export['FilterName'], 'writer_pdf_Export')
        self.assertIs(export['Overwrite'], False)
        self.assertNotIn('PageRange', export)
        self.assertEqual(record['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertIs(record['ownedEngineClosed'], True)
        self.assertEqual(sum(isinstance(event, tuple) and event[0] == 'load' for event in events), 2)
        self.assertEqual(events[-1], 'cleanup-owned-engine')

    def test_cleanup_failure_or_source_replacement_never_publishes_success_hash(self):
        for cleanup_error, change_url in ((True, False), (False, True)):
            with self.subTest(cleanup_error=cleanup_error, change_url=change_url):
                record, events, path = self.run_generated_case(cleanup_error, change_url)
                self.assertEqual(record['status'], 'failed', record)
                self.assertNotIn('sha256', record)
                self.assertTrue(path.is_file(), 'Failed exports must remain for diagnosis')
                path.unlink()
                (self.output / 'sources' / 'writer.odt').unlink()

    def test_production_refuses_existing_output_and_paths_inside_payload(self):
        sentinel = self.output / 'user-document.txt'
        sentinel.write_text('keep this user document')
        with redirect_stderr(io.StringIO()):
            self.assertEqual(smoke.main(['--produce', '--suite', str(self.suite), '--output', str(self.output)]), 2)
        self.assertEqual(sentinel.read_text(), 'keep this user document')
        target = self.suite / 'new-evidence'
        with redirect_stderr(io.StringIO()):
            self.assertEqual(smoke.main(['--produce', '--suite', str(self.suite), '--output', str(target)]), 2)
        self.assertFalse(target.exists())

    def test_draw_font_applies_to_existing_shape_text(self):
        class Cursor:
            selected = False

            def gotoEnd(self, expand):
                self.selected = expand

            def setPropertyValue(self, name, value):
                self.assert_selected = self.selected

        cursor = Cursor()

        class Shape:
            def getText(self):
                return self

            def createTextCursor(self):
                return cursor

        class Page:
            def getCount(self):
                return 0

            def setPropertyValue(self, name, value):
                pass

        class Pages:
            def getCount(self):
                return 1

            def getByIndex(self, index):
                return Page()

        class Document:
            def getDrawPages(self):
                return Pages()

        with patch.object(smoke.baseline, '_shape', return_value=Shape()):
            smoke._populate(object(), smoke.case_specs()[3], Document())
        self.assertTrue(cursor.assert_selected, 'Font must apply to rendered text, not only future insertion')

    def test_launcher_exit_does_not_close_job_or_remove_profile_with_live_engine_child(self):
        for terminate_fails in (False, True):
            with self.subTest(terminate_fails=terminate_fails):
                events = []

                class Api:
                    alive = True

                    def job_pids(self, job, **kwargs):
                        return [99] if self.alive else []

                    def state(self, handle):
                        return dict(alive=self.alive, exitCode=259 if self.alive else 0)

                    def wait_for(self, handle, timeout):
                        return 258 if self.alive else 0

                api = Api()

                class Witness:
                    members = {123: (456, dict(pid=99, image=str(self.suite / 'Office/program/soffice.bin'), creationTime=789))}

                    def __init__(self):
                        self.api = api

                    def snapshot(self):
                        return [dict(identity, **api.state(handle)) for handle, identity in self.members.values()]

                    def close(self):
                        events.append('close-witnesses')

                class Process:
                    job = 42

                    def wait(self, timeout):
                        return 0  # The launcher exited; its child is still alive.

                    def open_diagnostic_witnesses(self):
                        return Witness()

                    def terminate(self):
                        events.append('terminate-owned-job')
                        if terminate_fails:
                            raise OSError('private job termination failed')
                        api.alive = False

                    def close(self):
                        events.append('close-job')

                class Profile:
                    name = 'retained-private-profile'

                    def cleanup(self):
                        events.append('remove-profile')

                engine = smoke.Engine(self.suite)
                engine.process, engine.profile = Process(), Profile()
                engine.cleanup()
                self.assertIn('terminate-owned-job', events, 'Launcher exit alone must not prove owned job exit')
                if terminate_fails:
                    self.assertNotIn('close-job', events)
                    self.assertNotIn('remove-profile', events)
                    self.assertTrue(engine.cleanup_errors)
                else:
                    self.assertLess(events.index('terminate-owned-job'), events.index('close-job'))
                    self.assertLess(events.index('close-job'), events.index('remove-profile'))
                    self.assertEqual(engine.owned_job_evidence['finalJobPids'], [])
                    self.assertTrue(engine.owned_job_evidence['jobEmptyVerified'])

    def test_engine_identity_rejects_changed_binary_or_another_uno_server_image(self):
        self.assertTrue(hasattr(smoke, '_engine_identity'), 'Engine inventory identity is not implemented')
        files = {}
        for relative in ('Office/program/soffice.exe', 'Office/program/soffice.bin'):
            path = self.suite / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative.encode('ascii'))
            files[relative] = dict(size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        (self.suite / 'suite-inventory.json').write_text(json.dumps(dict(schemaVersion=1, files=files)))
        identity = smoke._engine_identity(self.suite)
        self.assertEqual(set(identity['files']), set(files))
        (self.suite / 'Office/program/soffice.bin').write_bytes(b'another engine')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            smoke._engine_identity(self.suite)
        initial = dict(pid=99, creationTime=789, image=str(self.suite / 'Office/program/soffice.bin'), alive=True, exitCode=259)
        evidence = dict(jobHandleValue=42, initial=[initial], final=[dict(initial, alive=False, exitCode=0)],
                        finalJobPids=[], jobEmptyVerified=True)
        smoke._validate_job_evidence(self.suite, evidence)
        evidence['initial'][0]['image'] = str(self.root / 'another-suite/Office/program/soffice.bin')
        with self.assertRaisesRegex(ValueError, 'engine image'):
            smoke._validate_job_evidence(self.suite, evidence)


if __name__ == '__main__':
    unittest.main()
