"""Platform-neutral checks for the actual-Windows smoke harness helpers."""
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'windows_smoke.py'
SPEC = importlib.util.spec_from_file_location('suite_windows_smoke', SOURCE)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class NativeSmokeTests(unittest.TestCase):
    def test_missing_file_does_not_satisfy_save_wait(self):
        check = Mock(side_effect=[FileNotFoundError('still writing'), False, True])
        with patch.object(smoke.time, 'monotonic', side_effect=[0, 0.1, 0.2, 0.3]), \
                patch.object(smoke.time, 'sleep') as sleep:
            self.assertIs(smoke.wait_for(check, seconds=1), True)
        self.assertEqual(check.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_half_written_zip_does_not_satisfy_save_wait(self):
        check = Mock(side_effect=[zipfile.BadZipFile('incomplete archive'), False, 'saved'])
        with patch.object(smoke.time, 'monotonic', side_effect=[0, 0.1, 0.2, 0.3]), \
                patch.object(smoke.time, 'sleep') as sleep:
            self.assertEqual(smoke.wait_for(check, seconds=1), 'saved')
        self.assertEqual(check.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_transient_save_failure_still_times_out(self):
        check = Mock(side_effect=FileNotFoundError('still writing'))
        with patch.object(smoke.time, 'monotonic', side_effect=[0, 0.1, 2]), \
                patch.object(smoke.time, 'sleep'):
            with self.assertRaises(AssertionError):
                smoke.wait_for(check, seconds=1)

    def test_home_requires_exact_seven_module_accessibility_labels(self):
        labels = ['파일 열기…'] + ['OpenGeul ' + name for name in ('HWP', 'Writer', 'Calc', 'Impress', 'Draw', 'Math', 'Base')]
        self.assertEqual(len(smoke.require_home_labels(labels)), 7)
        with self.assertRaises(AssertionError):
            smoke.require_home_labels(labels[:-1])
        with self.assertRaises(AssertionError):
            smoke.require_home_labels(labels + ['OpenGeul Writer'])
        with self.assertRaises(AssertionError):
            smoke.require_home_labels(labels[:-1] + ['OpenGeul base'])

    def fixture(self, directory):
        fixtures = Path(directory) / 'fixtures'
        fixtures.mkdir()
        source = fixtures / 'OpenGeul-writer.docx'
        source.write_bytes(b'generated fixture bytes')
        baseline = {'schemaVersion': 1, 'kind': 'engine', 'passed': True, 'cases': [{
            'module': 'writer', 'status': 'passed', 'fixture': str(source.resolve()),
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]}
        (fixtures.parent / 'engine-smoke.json').write_text(json.dumps(baseline), encoding='utf-8')
        return fixtures, source

    def test_fixture_must_match_passed_engine_baseline_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            fixtures, source = self.fixture(directory)
            self.assertEqual(smoke.require_engine_fixture(fixtures, 'writer', 'docx'), source.resolve())
            source.write_bytes(b'different document')
            with self.assertRaises(AssertionError):
                smoke.require_engine_fixture(fixtures, 'writer', 'docx')

    def test_failed_engine_baseline_cannot_authorize_gui_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            fixtures, _ = self.fixture(directory)
            report = fixtures.parent / 'engine-smoke.json'
            baseline = json.loads(report.read_text(encoding='utf-8'))
            baseline['passed'] = False
            report.write_text(json.dumps(baseline), encoding='utf-8')
            with self.assertRaises(AssertionError):
                smoke.require_engine_fixture(fixtures, 'writer', 'docx')

    def test_package_marker_scan_reads_actual_docx_xlsx_pptx_xml(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'fixture.zip'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('word/document.xml', '<p><t>Engine-</t><t>OpenGeul-writer</t></p>')
                archive.writestr('xl/worksheets/sheet1.xml', '<s><t>UI-OpenGeul-calc</t></s>')
                archive.writestr('ppt/slides/slide1.xml', '<s><t>UI-OpenGeul-impress</t></s>')
                archive.writestr('metadata.xml', '<t>should not count</t>')
            text = smoke.package_text(source)
            for marker in ('Engine-OpenGeul-writer', 'UI-OpenGeul-calc', 'UI-OpenGeul-impress'):
                self.assertIn(marker, text)
            self.assertNotIn('should not count', text)


if __name__ == '__main__':
    unittest.main()
