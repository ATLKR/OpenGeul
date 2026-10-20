"""Platform-neutral checks for the actual-Windows smoke harness helpers."""
import importlib.util
from contextlib import ExitStack, redirect_stdout
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
    def test_harness_can_load_by_sibling_path_in_an_isolated_interpreter(self):
        code = ('import importlib.util,sys; '
                'spec=importlib.util.spec_from_file_location("owned_windows_smoke",sys.argv[1]); '
                'module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)')
        result = smoke.subprocess.run([sys.executable, '-I', '-c', code, str(SOURCE)],
                                      capture_output=True, text=True, timeout=10, shell=False)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_suite_launch_captures_child_stderr_after_parent_stream_is_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            command = [sys.executable, '-c', 'import sys; sys.stderr.buffer.write(b"worker traceback retained\\n")']
            with patch.object(smoke, 'prepare_launch_pointer', create=True), \
                    patch.object(smoke.subprocess, 'Popen', wraps=smoke.subprocess.Popen) as launched:
                process = smoke.launch_suite(command, output, output, 'calc')
            self.assertTrue(launched.call_args.kwargs['stderr'].closed)
            self.assertFalse(launched.call_args.kwargs['shell'])
            self.assertEqual(launched.call_args.args[0], command)
            self.assertEqual(process.wait(timeout=10), 0)
            self.assertEqual((output / 'calc-stderr.log').read_bytes(), b'worker traceback retained\n')

    def test_pointer_precondition_is_completed_once_before_suite_process_launch(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            process = SimpleNamespace()
            with patch.object(smoke, 'prepare_launch_pointer', side_effect=lambda *a: calls.append('pointer'), create=True), \
                    patch.object(smoke.subprocess, 'Popen', side_effect=lambda *a, **kw: calls.append('launch') or process):
                smoke.launch_suite(['owned.exe'], output, output, 'owned')
        self.assertEqual(['pointer', 'launch'], calls)

    def test_pointer_precondition_failure_never_launches_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(smoke, 'prepare_launch_pointer', side_effect=RuntimeError('taskbar unavailable'), create=True), \
                    patch.object(smoke.subprocess, 'Popen') as launched:
                with self.assertRaisesRegex(RuntimeError, 'taskbar unavailable'):
                    smoke.launch_suite(['owned.exe'], output, output, 'owned')
            launched.assert_not_called()

    def test_external_window_gate_rejects_tooltip_like_popup_and_retains_snapshot(self):
        api = object.__new__(smoke.Windows)
        api.attached = lambda process: (11, 22, 33)
        api.pid = lambda hwnd: 88
        api.title = lambda hwnd: 'OpenGeul Writer'
        api.windows = lambda pid: [44]
        api._last_window_enumerations = {88: [44]}
        census = {'officePid': 88, 'windows': [{'hwnd': 44, 'className': 'SALTMPSUBFRAME',
                   'ownerHwnd': 11, 'style': 0x80000000, 'exStyle': 0x88, 'queryErrors': []}]}
        with tempfile.TemporaryDirectory() as directory:
            process = SimpleNamespace(pid=77, opengeul_evidence_output=Path(directory), opengeul_evidence_case='attempt-007')
            with patch.object(smoke, 'NativeWindowProbe', return_value=SimpleNamespace(window_census=lambda handles, pid: census), create=True):
                with self.assertRaises(AssertionError) as caught:
                    smoke.verified_attachment(api, process, 'writer')
            self.assertIn('SALTMPSUBFRAME', str(caught.exception))
            evidence = Path(directory) / 'attempt-007-offending-windows.json'
            self.assertTrue(evidence.is_file(), 'offending HWND census was not retained')
            self.assertEqual(census, json.loads(evidence.read_text()))

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


class CalcDocumentOrchestrationTests(unittest.TestCase):
    """Exercise document_case while replacing only its external GUI boundaries.

    Removing or moving the Calc begin/complete calls must fail these tests even
    when the fake keyboard produces a saved file containing the marker.
    """

    @staticmethod
    def _write_document(path, module, suffix=''):
        marker = 'Engine-OpenGeul-' + module + (' 한글' if module == 'calc' else '') + suffix
        with zipfile.ZipFile(path, 'w') as archive:
            if module == 'calc':
                archive.writestr('xl/workbook.xml',
                    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<sheets><sheet name="Sheet0" sheetId="1" r:id="rId1"/></sheets></workbook>')
                archive.writestr('xl/_rels/workbook.xml.rels',
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                    'Target="worksheets/sheet1.xml"/></Relationships>')
                archive.writestr('xl/worksheets/sheet1.xml',
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>' + marker + '</t></is></c>'
                    '<c r="B1"><v>17</v></c><c r="C1"><v>25</v></c>'
                    '<c r="D1"><f>SUM(B1:C1)</f><v>42</v></c></row></sheetData></worksheet>')
            else:
                member = 'word/document.xml' if module == 'writer' else 'ppt/slides/slide1.xml'
                archive.writestr(member, '<document><text>' + marker + '</text></document>')

    def _run_document(self, module='calc', *, failure=None, abort_raises=False,
                      replace_source_on_launch=False, physical_input=True):
        events, state = [], {}
        first_error = RuntimeError({
            'begin': 'before-input model rejected',
            'complete': 'model completion rejected',
            'cleanup': 'observer cleanup rejected',
            'input': 'physical input failed',
            'save': 'saved marker verification failed',
        }.get(failure, 'unused failure'))
        plan = object()
        extension = dict(smoke.INPUT_CASES + smoke.ATTACH_CASES)[module]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite, fixtures, output = (root / name for name in ('suite', 'fixtures', 'output'))
            for path in (suite, fixtures, output): path.mkdir()
            source = fixtures / ('OpenGeul-' + module + '.' + extension)
            self._write_document(source, module)
            original = source.read_bytes()
            (root / 'engine-smoke.json').write_text(json.dumps({
                'schemaVersion': 1, 'kind': 'engine', 'passed': True, 'cases': [{
                    'module': module, 'status': 'passed', 'fixture': str(source.resolve()),
                    'sha256': hashlib.sha256(original).hexdigest()}]}), encoding='utf-8')
            process = SimpleNamespace(pid=100, poll=lambda: None)

            class FakeWindow:
                def __init__(self, handle): self.handle = handle
                def maximize(self): events.append('maximize')
                def set_focus(self): events.append('window-focus')
                def click_input(self): events.append('editor-click')
                def capture_as_image(self): return self
                def save(self, path): events.append(('screenshot', path.name))

            class FakeDesktop:
                def __init__(self, **kwargs): pass
                def window(self, *, handle):
                    return SimpleNamespace(wrapper_object=lambda: FakeWindow(handle))

            def editor_focus(hwnd, child):
                events.append('editor-focus-verified')
                return child

            api = SimpleNamespace(
                user=SimpleNamespace(GetForegroundWindow=lambda: 11, GetAncestor=lambda hwnd, flag: 11),
                title=lambda hwnd: 'OpenGeul ' + module.title(),
                require_foreground=lambda hwnd: None,
                require_editor_focus=editor_focus,
                windows=lambda pid: [], external_window_message=lambda *args: 'foreign window')

            def launch(*args):
                events.append('launch')
                baseline = output / 'calc-model-baseline.xlsx'
                state['baselineAtLaunch'] = baseline.read_bytes() if baseline.exists() else None
                if replace_source_on_launch:
                    self._write_document(source, module, '-changed-after-launch')
                return process

            def send_keys(keys, *, pause):
                events.append(('keys', keys, pause))
                if keys == '^s' and failure != 'save':
                    self._write_document(source, module, smoke.EDITOR_MARKERS[module])

            real_wait_for = smoke.wait_for
            def wait_for(check, seconds=10):
                if failure == 'save' and seconds == 30:
                    self.assertFalse(check(), 'The original save XML gate must really observe a missing marker')
                    events.append('saved-xml-check-failed')
                    raise first_error
                return real_wait_for(check, seconds)

            def prepare_focus(api, hwnd, child, shell_pid, office_pid, record, click, enter):
                click()
                enter()
                events.append('focus-ready')

            def type_ascii(api, hwnd, child, marker, record, *, pause):
                events.append(('type', marker, pause))
                if failure == 'input': raise first_error

            class FakeCalcContext:
                def __init__(self, actual_suite, actual_source, actual_output, actual_process,
                             attachment, record, baseline):
                    events.append('model-context')
                    state['contextArguments'] = (actual_suite, actual_source, actual_output,
                                                  actual_process, attachment, record)
                    state['contextBaseline'] = baseline
                    self.record = record

                def begin(self, marker):
                    events.append(('model-begin', marker))
                    self.record['calcModelCompletion'] = dict(state='pending', success=False)
                    if failure == 'begin': raise first_error
                    return plan

                def complete(self, actual_plan):
                    if actual_plan is not plan:
                        raise AssertionError('The original Calc plan was not retained')
                    events.append('model-completion-observed')
                    if failure == 'complete': raise first_error
                    events.append('reader-normal-close')
                    if failure == 'cleanup': raise first_error
                    events.append('reader-cleanup-validated')
                    self.record['calcModelCompletion'].update(state='complete', success=True,
                        cleanup={'normalExit': True, 'emptyJob': True, 'handlesClosed': True})
                    self.record['calcModelCompletionVerified'] = True
                    state['sealedCompletion'] = json.loads(json.dumps(self.record['calcModelCompletion']))

                def abort(self, exc):
                    events.append('model-abort')
                    state['abortError'] = exc
                    self.record['calcModelCompletion'].update(state='failed', success=False)
                    if abort_raises: raise RuntimeError('secondary abort cleanup failure')

            def capture_failure(output, name, record, exc):
                events.append('failure-recorded')
                record.update(success=False, error=type(exc).__name__ + ': ' + str(exc))

            modules = {
                'pywinauto': SimpleNamespace(Desktop=FakeDesktop),
                'pywinauto.keyboard': SimpleNamespace(send_keys=send_keys),
            }
            error = None
            with ExitStack() as stack:
                stack.enter_context(patch.dict(sys.modules, modules))
                for name, replacement in (
                        ('launch_suite', launch), ('Windows', lambda: api),
                        ('verified_attachment', lambda *args: (11, 22, 33, 200)),
                        ('prepare_editor_focus', prepare_focus),
                        ('wait_for', wait_for),
                        ('CalcModelContext', FakeCalcContext), ('capture_failure', capture_failure),
                        ('close_document', lambda *args, **kwargs: (state.update(closeProof=kwargs.get('calc_close_proof')), events.append('document-close'))),
                        ('close_home', lambda *args: events.append('home-close')),
                        ('stop_owned_test_process', lambda *args: events.append('process-cleanup'))):
                    stack.enter_context(patch.object(smoke, name, replacement, create=True))
                stack.enter_context(patch.object(smoke.ascii_input, 'type_ascii', type_ascii))
                try:
                    smoke.document_case(suite, fixtures, output, module, extension, physical_input)
                except Exception as exc:
                    error = exc
            state.update(events=events, error=error, firstError=first_error, original=original,
                         record=json.loads((output / (module + '-result.json')).read_text(encoding='utf-8')),
                         snapshot=(output / 'calc-model-baseline.xlsx').read_bytes()
                         if (output / 'calc-model-baseline.xlsx').exists() else None)
            return state

    def test_calc_requires_model_completion_and_normal_cleanup_before_single_original_save(self):
        run = self._run_document()
        self.assertIsNone(run['error'])
        events = run['events']
        marker = smoke.EDITOR_MARKERS['calc']
        self.assertIn(('model-begin', marker), events,
                      'Calc physical input bypassed the owned before-input model gate')
        ordered = ['focus-ready', 'model-context', ('model-begin', marker),
                   ('keys', '^{HOME}{F2}^{END}', 0.1), ('type', marker, 0.04),
                   ('keys', '{ENTER}', 0.1), 'model-completion-observed',
                   'reader-normal-close', 'reader-cleanup-validated', ('keys', '^s', 0.1),
                   'document-close', 'home-close']
        self.assertEqual(sorted(events.index(event) for event in ordered),
                         [events.index(event) for event in ordered])
        self.assertEqual([event for event in events if isinstance(event, tuple) and event[0] == 'keys'],
                         [('keys', '^{F6}', 0.1), ('keys', '^{HOME}{F2}^{END}', 0.1),
                          ('keys', '{ENTER}', 0.1), ('keys', '^s', 0.1)])
        self.assertEqual([event for event in events if isinstance(event, tuple) and event[0] == 'type'],
                         [('type', marker, 0.04)])
        self.assertNotIn('model-abort', events)
        self.assertTrue(run['record']['success'])
        self.assertEqual(run['contextBaseline']['a1Text']+marker,dict(run['closeProof'].cells)['a1Text'])

    def test_calc_freezes_exact_ooxml_bytes_before_launch_and_passes_that_independent_baseline(self):
        run = self._run_document(replace_source_on_launch=True)
        self.assertIsNone(run['error'])
        self.assertEqual(run['original'], run['baselineAtLaunch'],
                         'The independent Calc snapshot must exist before Suite launch')
        self.assertEqual(run['original'], run['snapshot'])
        self.assertEqual(smoke.calc_model_barrier.baseline_from_ooxml(run['original']),
                         run['contextBaseline'])
        arguments = run['contextArguments']
        self.assertEqual({'hwnd': 11, 'parent': 22, 'child': 33, 'officePid': 200}, arguments[4])
        self.assertEqual('calc', arguments[5]['module'])

    def test_calc_completion_failure_aborts_once_without_save_and_preserves_the_first_error(self):
        run = self._run_document(failure='complete', abort_raises=True)
        self.assertIs(run['error'], run['firstError'])
        self.assertIs(run.get('abortError'), run['firstError'])
        self.assertEqual(1, run['events'].count('model-abort'))
        self.assertNotIn(('keys', '^s', 0.1), run['events'])
        self.assertNotIn('document-close', run['events'])
        self.assertEqual('RuntimeError: model completion rejected', run['record']['error'])
        self.assertFalse(run['record']['success'])

    def test_calc_normal_reader_cleanup_failure_blocks_save(self):
        run = self._run_document(failure='cleanup')
        self.assertIs(run['error'], run['firstError'])
        self.assertIn('model-completion-observed', run['events'])
        self.assertIn('reader-normal-close', run['events'])
        self.assertNotIn('reader-cleanup-validated', run['events'])
        self.assertNotIn(('keys', '^s', 0.1), run['events'])
        self.assertEqual(1, run['events'].count('model-abort'))
        self.assertEqual('RuntimeError: observer cleanup rejected', run['record']['error'])

    def test_calc_before_input_failure_blocks_navigation_typing_enter_and_save(self):
        run = self._run_document(failure='begin')
        self.assertIs(run['error'], run['firstError'])
        self.assertEqual([('keys', '^{F6}', 0.1)],
                         [event for event in run['events'] if isinstance(event, tuple) and event[0] == 'keys'])
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'type' for event in run['events']))
        self.assertIs(run.get('abortError'), run['firstError'])

    def test_calc_input_failure_aborts_without_replacing_original_failure(self):
        run = self._run_document(failure='input', abort_raises=True)
        self.assertIs(run['error'], run['firstError'])
        self.assertIs(run.get('abortError'), run['firstError'])
        self.assertNotIn('model-completion-observed', run['events'])
        self.assertNotIn(('keys', '{ENTER}', 0.1), run['events'])
        self.assertNotIn(('keys', '^s', 0.1), run['events'])
        self.assertEqual('RuntimeError: physical input failed', run['record']['error'])

    def test_original_save_xml_failure_preserves_sealed_model_completion_without_second_cleanup(self):
        run = self._run_document(failure='save')
        self.assertIs(run['error'], run['firstError'])
        self.assertIn('reader-cleanup-validated', run['events'])
        self.assertIn('saved-xml-check-failed', run['events'])
        self.assertEqual(1, run['events'].count(('keys', '^s', 0.1)))
        self.assertNotIn('model-abort', run['events'],
                         'The completed and normally closed observer must not be aborted by a later save failure')
        self.assertEqual(run['sealedCompletion'], run['record']['calcModelCompletion'])
        self.assertTrue(run['record']['calcModelCompletionVerified'])
        self.assertFalse(run['record']['success'])
        self.assertEqual('RuntimeError: saved marker verification failed', run['record']['error'])
        self.assertNotIn('document-close', run['events'])

    def test_completed_real_calc_context_abort_preserves_sealed_proof_and_does_not_persist_again(self):
        context = object.__new__(smoke.CalcModelContext)
        context.reader = None
        context.failed = False
        context.receipt = dict(state='complete', success=True,
            cleanup={'normalExit': True, 'emptyJob': True, 'handlesClosed': True})
        sealed = json.loads(json.dumps(context.receipt))
        with patch.object(context, 'persist') as persist:
            context.abort(RuntimeError('later original save gate failed'))
        self.assertEqual(sealed, context.receipt,
                         'A later save failure must not falsify the completed model and cleanup proof')
        self.assertFalse(context.failed)
        persist.assert_not_called()

    def test_other_physical_modules_keep_original_navigation_and_do_not_start_calc_observer(self):
        for module, navigation in (('writer', '^{END}'), ('impress', '{TAB}{F2}^{END}')):
            with self.subTest(module=module):
                run = self._run_document(module)
                self.assertIsNone(run['error'])
                self.assertNotIn('model-context', run['events'])
                self.assertIsNone(run['snapshot'])
                self.assertEqual([('keys', '^{F6}', 0.1), ('keys', navigation, 0.1), ('keys', '^s', 0.1)],
                    [event for event in run['events'] if isinstance(event, tuple) and event[0] == 'keys'])
                self.assertTrue(run['record']['success'])

    def test_attach_only_modules_do_not_capture_calc_baseline_or_send_editor_input(self):
        for module in ('draw', 'math', 'base'):
            with self.subTest(module=module):
                run = self._run_document(module, physical_input=False)
                self.assertIsNone(run['error'])
                self.assertNotIn('model-context', run['events'])
                self.assertIsNone(run['snapshot'])
                self.assertFalse(any(isinstance(event, tuple) and event[0] in ('keys', 'type')
                                     for event in run['events']))
                self.assertTrue(run['record']['success'])


if __name__ == '__main__':
    unittest.main()
