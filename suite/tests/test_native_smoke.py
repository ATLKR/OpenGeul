"""Platform-neutral checks for the actual-Windows smoke harness helpers."""
import importlib.util
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'windows_smoke.py'
SPEC = importlib.util.spec_from_file_location('suite_windows_smoke', SOURCE)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class NativeSmokeTests(unittest.TestCase):
    def test_suite_launch_captures_child_stderr_after_parent_stream_is_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            command = [sys.executable, '-c', 'import sys; sys.stderr.buffer.write(b"worker traceback retained\\n")']
            with patch.object(smoke.subprocess, 'Popen', wraps=smoke.subprocess.Popen) as launched:
                process = smoke.launch_suite(command, output, output, 'calc')
            self.assertTrue(launched.call_args.kwargs['stderr'].closed)
            self.assertFalse(launched.call_args.kwargs['shell'])
            self.assertEqual(launched.call_args.args[0], command)
            self.assertEqual(process.wait(timeout=10), 0)
            self.assertEqual((output / 'calc-stderr.log').read_bytes(), b'worker traceback retained\n')

    def test_owned_startup_error_requires_exact_native_dialog_identity(self):
        self.assertTrue(smoke.is_owned_startup_error(31, 31, 31, 'OpenGeul Office', '#32770'))
        for observed in ((99, 31, 31, 'OpenGeul Office', '#32770'),
                         (31, 31, 99, 'OpenGeul Office', '#32770'),
                         (31, 31, 31, 'OpenGeul Calc', '#32770'),
                         (31, 31, 31, 'OpenGeul Office', 'WinForms')):
            self.assertFalse(smoke.is_owned_startup_error(*observed))

    def test_attachment_detects_owned_startup_error_before_reading_child_properties(self):
        api = object.__new__(smoke.Windows)
        api.windows = lambda pid: [44]
        api.pid = lambda hwnd: 31
        api.title = lambda hwnd: 'OpenGeul Office'
        api.class_name = lambda hwnd: '#32770'
        api.user = SimpleNamespace(GetWindow=lambda hwnd, flag: 55, IsWindow=lambda hwnd: True,
            GetAncestor=lambda hwnd, flag: hwnd, GetPropW=Mock(side_effect=AssertionError('properties must not be polled')))
        with self.assertRaisesRegex(AssertionError, 'startup-error dialog'):
            api.attached(SimpleNamespace(pid=31, poll=lambda: None))
        api.user.GetPropW.assert_not_called()

    def test_taskkill_not_found_is_secondary_exit_race_only_after_verified_exit_zero(self):
        process = SimpleNamespace(pid=123, poll=Mock(side_effect=[None, 0]))
        record = {'success': False, 'error': 'original close timeout'}
        error = smoke.subprocess.CalledProcessError(128, ['taskkill.exe'])
        with patch.object(smoke.subprocess, 'run', side_effect=error):
            smoke.stop_owned_test_process(process, record)
        self.assertTrue(record['cleanupExitRaceVerified'])
        self.assertEqual(record['cleanupProcessExitCode'], 0)
        self.assertNotIn('cleanupError', record)
        self.assertFalse(record['success'])
        self.assertEqual(record['error'], 'original close timeout')

    def test_taskkill_not_found_still_fails_if_owned_process_has_not_exited(self):
        process = SimpleNamespace(pid=123, poll=Mock(side_effect=[None, None]))
        record = {'success': True}
        error = smoke.subprocess.CalledProcessError(128, ['taskkill.exe'])
        with patch.object(smoke.subprocess, 'run', side_effect=error):
            smoke.stop_owned_test_process(process, record)
        self.assertFalse(record['success'])
        self.assertIn('CalledProcessError', record['cleanupError'])
        self.assertNotIn('cleanupExitRaceVerified', record)

    def test_owned_close_posts_once_and_refuses_foreign_or_child_windows(self):
        calls = []
        api = object.__new__(smoke.Windows)
        api.user = SimpleNamespace(IsWindow=lambda hwnd: True, GetAncestor=lambda hwnd, flag: hwnd,
            PostMessageW=lambda *args: calls.append(args) or True)
        api.pid = lambda hwnd: 123
        api.request_close(456, 123)
        self.assertEqual(calls, [(456, 0x0010, 0, 0)])
        api.pid = lambda hwnd: 999
        with self.assertRaises(AssertionError):
            api.request_close(456, 123)
        api.pid = lambda hwnd: 123
        api.user.GetAncestor = lambda hwnd, flag: 789
        with self.assertRaises(AssertionError):
            api.request_close(456, 123)
        self.assertEqual(len(calls), 1)

    def test_close_waits_for_teardown_longer_than_wrapper_two_second_timeout(self):
        elapsed = [0]
        calls = []
        api = SimpleNamespace(request_close=lambda hwnd, pid: calls.append((hwnd, pid)),
            user=SimpleNamespace(IsWindow=lambda hwnd: elapsed[0] < (3 if hwnd == 456 else 2.5)))
        record = {}
        with patch.object(smoke.time, 'monotonic', side_effect=lambda: elapsed[0]), \
                patch.object(smoke.time, 'sleep', side_effect=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)):
            smoke.close_document(api, SimpleNamespace(pid=123), 456, 789, record)
        self.assertEqual(calls, [(456, 123)])
        self.assertGreaterEqual(elapsed[0], 3)
        self.assertEqual(record['stage'], 'wait-editor-close')

    def test_failure_preserves_stage_and_full_python_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            record = {'stage': 'wait-document-close'}
            try:
                raise RuntimeError('teardown failure')
            except RuntimeError as exc:
                smoke.capture_failure(Path(directory), 'draw', record, exc)
            self.assertFalse(record['success'])
            self.assertEqual(record['stage'], 'wait-document-close')
            self.assertIn('RuntimeError: teardown failure', record['traceback'])
            self.assertIn('test_failure_preserves_stage', record['traceback'])

    def test_collector_continues_and_preserves_failed_case_record_and_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            calls = []
            def fails():
                calls.append('writer')
                smoke.write_result(output, 'writer', {'module': 'writer', 'success': False,
                    'childHwnd': 1234, 'error': 'native marker failed'})
                raise RuntimeError('case exception')
            def passes():
                calls.append('calc')
                return {'module': 'calc', 'success': True}
            with redirect_stdout(io.StringIO()):
                records = smoke.collect_cases([('writer', fails), ('calc', passes)], output)
            self.assertEqual(calls, ['writer', 'calc'])
            self.assertFalse(records[0]['success'])
            self.assertEqual(records[0]['childHwnd'], 1234)
            self.assertEqual(records[0]['error'], 'native marker failed')
            self.assertIn('RuntimeError: case exception', records[0]['caseException'])
            self.assertIn('RuntimeError: case exception', records[0]['caseTraceback'])
            self.assertEqual(records[0]['case'], 'writer')
            self.assertTrue(records[1]['success'])

    def test_collector_keeps_returned_cleanup_failure_as_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(io.StringIO()):
                records = smoke.collect_cases([
                    ('home', lambda: {'success': False, 'cleanupError': 'worker remained alive'}),
                    ('writer', lambda: {'success': True})], Path(directory))
            self.assertFalse(records[0]['success'])
            self.assertEqual(records[0]['cleanupError'], 'worker remained alive')
            self.assertTrue(records[1]['success'])

    def case_record(self, name):
        module = name.removeprefix('new-')
        return {'case': name, 'module': module, 'success': True,
                'kind': 'home' if name == 'home' else 'new-document' if name.startswith('new-') else 'keyboard-edit' if name in ('writer', 'calc', 'impress') else 'native-attach',
                'nativeParentVerified': name != 'home', 'newDocumentVerified': name.startswith('new-'),
                'keyboardInputVerified': name in ('writer', 'calc', 'impress'),
                'contentMutationVerified': name in ('writer', 'calc', 'impress')}

    def case_names(self):
        modules = ('writer', 'calc', 'impress', 'draw', 'math', 'base')
        return ('home',) + modules + tuple('new-' + module for module in modules)

    def test_aggregate_exit_and_module_claims_require_thirteen_passing_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            cases = [(name, lambda name=name: self.case_record(name)) for name in self.case_names()]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(smoke.run_cases(cases, output), 0)
            report = json.loads((output / 'results.json').read_text(encoding='utf-8'))
            self.assertTrue(report['success'])
            self.assertEqual(report['passedCaseCount'], 13)
            self.assertEqual(len(report['newDocumentModules']), 6)
            def failure():
                return {**self.case_record('writer'), 'success': False, 'error': 'marker missing'}
            cases[1] = ('writer', failure)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(smoke.run_cases(cases, output), 1)
            report = json.loads((output / 'results.json').read_text(encoding='utf-8'))
            self.assertFalse(report['success'])
            self.assertEqual(report['passedCaseCount'], 12)
            self.assertEqual(report['failedCases'], ['writer'])
            self.assertNotIn('writer', report['physicalInputModules'])
            self.assertNotIn('writer', report['nativeAttachmentModules'])
            self.assertEqual(len(report['tests']), 13)

    def test_aggregate_rejects_missing_or_duplicate_case_coverage(self):
        complete = [self.case_record(name) for name in self.case_names()]
        missing = smoke.suite_report(complete[:-1])
        self.assertFalse(missing['success'])
        self.assertEqual(missing['missingCases'], ['new-base'])
        duplicate = smoke.suite_report(complete + [complete[1]])
        self.assertFalse(duplicate['success'])
        self.assertEqual(duplicate['duplicateCases'], ['writer'])

    def test_new_base_target_is_fresh_and_distinct_from_engine_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            fixtures = Path(directory) / 'fixtures'
            fixtures.mkdir()
            target = smoke.new_base_target(fixtures)
            self.assertEqual(target.name, 'New-OpenGeul-base.odb')
            self.assertEqual(target.parent, fixtures.resolve())
            self.assertFalse(target.exists())
            target.write_bytes(b'keep existing bytes')
            with self.assertRaises(AssertionError):
                smoke.new_base_target(fixtures)
            self.assertEqual(target.read_bytes(), b'keep existing bytes')

    def test_saved_base_requires_real_database_zip_and_firebird_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'New-OpenGeul-base.odb'
            for url, accepted in (('sdbc:embedded:firebird', True), ('jdbc:', False)):
                with zipfile.ZipFile(target, 'w') as archive:
                    archive.writestr('mimetype', 'application/vnd.oasis.opendocument.base')
                    archive.writestr('content.xml', '<database xmlns:xlink="http://www.w3.org/1999/xlink"><connection xlink:href="' + url + '"/></database>')
                if accepted:
                    evidence = smoke.saved_base_evidence(target)
                    self.assertEqual(evidence['connection'], url)
                    self.assertEqual(evidence['sha256'], hashlib.sha256(target.read_bytes()).hexdigest())
                    self.assertGreater(evidence['bytes'], 0)
                else:
                    with self.assertRaises(AssertionError):
                        smoke.saved_base_evidence(target)
            with zipfile.ZipFile(target, 'w') as archive:
                archive.writestr('content.xml', '<database/>')
            with self.assertRaises((AssertionError, KeyError)):
                smoke.saved_base_evidence(target)

    def test_saved_base_rejects_other_odf_mime_even_with_firebird_url(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'wrong-type.odb'
            with zipfile.ZipFile(target, 'w') as archive:
                archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
                archive.writestr('content.xml', '<database xmlns:xlink="http://www.w3.org/1999/xlink"><connection xlink:href="sdbc:embedded:firebird"/></database>')
            with self.assertRaises(AssertionError):
                smoke.saved_base_evidence(target)

    def test_base_byte_rewrite_requires_semantic_verification_and_reports_actual_immutability(self):
        self.assertEqual(smoke.attach_only_content_status('base', 'before', 'after'),
                         {'fixtureUnchanged': False, 'contentVerificationRequired': True})
        self.assertEqual(smoke.attach_only_content_status('base', 'same', 'same'),
                         {'fixtureUnchanged': True, 'contentVerificationRequired': True})
        for module in ('draw', 'math'):
            with self.assertRaises(AssertionError):
                smoke.attach_only_content_status(module, 'before', 'after')
            self.assertEqual(smoke.attach_only_content_status(module, 'same', 'same'),
                             {'fixtureUnchanged': True, 'contentVerificationRequired': False})

    def test_physical_path_keys_escape_key_syntax_as_literal_text(self):
        self.assertEqual(smoke.literal_keys('a+^%~(){}'), 'a{+}{^}{%}{~}{(}{)}{{}{}}')
        self.assertEqual(smoke.literal_keys('C:\\생성 문서\\new.odb'), 'C:\\생성 문서\\new.odb')

    def test_save_and_explicit_discard_dialog_identity_rejects_foreign_or_wrong_prompts(self):
        valid = (31, 31, 400, 400, 'OpenGeul Base', 'OpenGeul Base', '#32770')
        smoke.require_dialog_identity(*valid)
        for index, wrong in ((0, 99), (2, 999), (4, '다른 대화 상자'), (6, 'OtherWindow')):
            observed = list(valid)
            observed[index] = wrong
            with self.assertRaises(AssertionError):
                smoke.require_dialog_identity(*observed)

    def test_new_document_launch_opens_exact_six_modules_without_a_file_argument(self):
        suite = Path('generated-suite')
        for module in ('writer', 'calc', 'impress', 'draw', 'math', 'base'):
            self.assertEqual(smoke.new_document_command(suite, module),
                             [str(suite / 'OpenGeul.Office.exe'), '--module', module])

    def test_new_document_launch_rejects_unowned_modules(self):
        for module in ('hwp', 'unknown', '../writer'):
            with self.assertRaises(AssertionError):
                smoke.new_document_command(Path('generated-suite'), module)

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
