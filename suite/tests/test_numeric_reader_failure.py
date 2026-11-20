"""Current reader exceptions retain optional numeric metadata across real file RPC."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'e2e/writer_model_reader.py'
sys.path.insert(0, str(SOURCE.parent))
import numeric_notice


def environment():
    return dict(OPENGEUL_SUITE_NUMERIC_NOTICE='1', OPENGEUL_SUITE_NOTICE_SCOPE='5', GITHUB_ACTIONS='true',
        GITHUB_REPOSITORY='ATLKR/OpenGeul', GITHUB_JOB='windows-suite',
        GITHUB_EVENT_NAME='push', GITHUB_REF='refs/heads/work/opengeul-office-arm64',
        GITHUB_ACTOR='ATLKR', GITHUB_ACTOR_ID='65988341', GITHUB_RUN_ID='123',
        GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='a'*40, GITHUB_WORKFLOW_SHA='a'*40, RUNNER_ARCH='ARM64')


class NumericReaderFailureTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('numeric_tested_reader', SOURCE)
        self.reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.reader)

    def run_helper(self, additions):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self.reader._atomic_json(output/'configuration.json', dict(readerClockKind=1))
            self.reader._atomic_json(output/'request-000.json', dict(sequence=7, action='start'))
            self.reader._atomic_json(output/'request-001.json', dict(sequence=1, action='release'))
            child_environment = dict(os.environ)
            child_environment.pop('OPENGEUL_SUITE_NUMERIC_NOTICE', None)
            child_environment.update(additions)
            child_environment.update(GH_TOKEN='synthetic-reader-fixture-token', GITHUB_TOKEN='synthetic-reader-fixture-token')
            process = subprocess.run([sys.executable, str(SOURCE), '--helper', str(output)],
                env=child_environment, capture_output=True, text=True, timeout=10, shell=False)
            self.assertEqual(0, process.returncode, process.stderr)
            failed = self.reader._read_json(output/'reply-000.json')
            released = self.reader._read_json(output/'reply-001.json')
            self.assertIs(failed['ok'], False)
            self.assertEqual('AssertionError', failed['error']['type'])
            self.assertEqual('', failed['error']['message'])
            self.assertIn('traceback', failed['error'])
            self.assertIs(released['ok'], True)
            self.assertIs(released['proxiesReleased'], True)
            return failed

    def assert_owned_failure(self, failure, function, exception_code):
        self.assertEqual({'captured','exceptionCode','fileCode','line'}, set(failure))
        self.assertTrue(all(type(value) is int for value in failure.values()))
        self.assertEqual(1, failure['captured'])
        self.assertEqual(exception_code, failure['exceptionCode'])
        self.assertEqual(8, failure['fileCode'])
        self.assertIn(failure['line'], {line for _, _, line in function.__code__.co_lines() if line})
        self.assertEqual(failure, numeric_notice.validate_failure_code(failure))

    def test_actual_child_failure_keeps_original_reply_and_numeric_metadata_through_wrapper(self):
        original = self.run_helper({})
        failed = self.run_helper(environment())
        self.assertEqual(original['error'], {
            key:value for key,value in failed['error'].items() if key != 'numericFailure'})
        failure = failed['error']['numericFailure']
        self.assert_owned_failure(failure, self.reader._helper, 1)
        with self.assertRaises(self.reader.ReaderBackendError) as caught:
            self.reader._require_reply(failed, 0, 'start')
        self.assertIs(failed, caught.exception.raw)
        self.assertEqual(failure, numeric_notice.capture_failure_code(caught.exception))

    def test_actual_focused_view_leaf_survives_child_file_rpc_wrapper_and_final_notice(self):
        import writer_style_smoke as style
        from test_impress_focused_view import FocusedReaderTests,FocusWorld
        import impress_focused_view as focus
        fixture=FocusedReaderTests();world=FocusWorld();world.focus.focused=1
        editing=fixture.reader(world)
        env=environment()|{'OPENGEUL_SUITE_NOTICE_SCOPE':'3'}
        try:
            with patch.dict(os.environ,env,clear=True):
                try:editing.read()
                except AssertionError as exc:
                    direct=numeric_notice.capture_failure_code(exc)
                    self.assertEqual(direct['fileCode'],26)
                    self.assertIn(direct['line'],{line for _,_,line in focus.FocusedViewReader._lookup.__code__.co_lines() if line})
                    self.assertEqual(numeric_notice.capture_failure_frames(exc)[-1],[26,direct['line']])
                else:self.fail('Malformed focus must retain its actual focused-view assertion')
                with tempfile.TemporaryDirectory() as directory:
                    output=Path(directory)
                    self.reader._atomic_json(output/'configuration.json',dict(suite='/synthetic-suite',
                        readerClockKind=1,
                        expected_service='com.sun.star.presentation.PresentationDocument',
                        getter_contract='impress-focused-view-edit-context-v2'))
                    self.reader._atomic_json(output/'request-000.json',dict(sequence=0,action='start'))
                    self.reader._atomic_json(output/'request-001.json',dict(sequence=1,action='release'))
                    anchor=type('Anchor',(),dict(profile=None,snapshot=lambda self:{},close=lambda self:[]))()
                    with patch.object(style,'observe_packaged_python',return_value={}), \
                         patch.object(style,'require_packaged_python',return_value={}), \
                         patch.object(self.reader,'_native_anchor',return_value=anchor), \
                         patch.object(self.reader,'_UnoReader',return_value=editing), \
                         patch.object(self.reader,'_qpc',return_value=(1,1)):
                        self.assertEqual(self.reader._helper(output,explicit_model=True),0)
                    failed=self.reader._read_json(output/'reply-000.json')
                    released=self.reader._read_json(output/'reply-001.json')
                    self.assertIs(failed['ok'],False)
                    self.assertIs(released['ok'],True)
                    self.assertEqual(failed['error']['numericFailure'],direct)
                    with self.assertRaises(self.reader.ReaderBackendError) as caught:
                        self.reader._require_reply(failed,0,'start')
                    retained=numeric_notice.capture_failure_code(caught.exception)
                    self.assertEqual(retained,direct)
                    stream=io.StringIO();emitter=numeric_notice.NoticeEmitter(environ=env,stream=stream)
                    self.assertTrue(emitter.emit_case_notice('ime-impress',dict(success=False,
                        stage='verify-pre-prefix-editing-context',numericFailure=retained)))
                    message=stream.getvalue().strip().split('::',2)[2]
                    self.assertLessEqual(len(message.encode()),2048)
                    decoded=numeric_notice.decode_notice(message,'a'*40,123,expected_scope=3)
                    self.assertEqual((decoded['schemaVersion'],decoded['fileCode'],decoded['line']),
                        (1,26,direct['line']))
                    self.assertEqual(world.now,1.)
        finally:fixture.doCleanups()

    def test_disabled_or_invalid_context_adds_no_helper_metadata(self):
        for additions in ({}, {**environment(), 'GITHUB_RUN_ATTEMPT':'2'},
                          {**environment(), 'GITHUB_WORKFLOW_SHA':'b'*40},
                          {**environment(), 'OPENGEUL_SUITE_NOTICE_SCOPE':'0'}):
            with self.subTest(additions=additions):
                self.assertNotIn('numericFailure', self.run_helper(additions)['error'])

    def test_actual_failed_start_keeps_primary_exception_and_existing_controller_evidence(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, environment()):
            output = Path(directory)
            reader = self.reader.OwnedWriterReader(Path('/synthetic-suite'), output,
                shell_pid=77, expected_shell_creation=111, suite_hwnd=11, parent_hwnd=12,
                child_hwnd=22, office_pid=88, expected_url='', clock=lambda:1.)
            with patch.object(self.reader, '_native_anchor') as anchor, \
                    patch.object(self.reader,'_controller_reader_clock_kind',return_value=1):
                with self.assertRaises(FileExistsError) as caught: reader.start(12.)
                anchor.assert_not_called()
            self.assertIs(type(caught.exception), FileExistsError)
            self.assertTrue(reader.failed)
            self.assertEqual(12., reader.deadline)
            self.assertIsNone(reader.process)
            self.assertEqual('FileExistsError', reader.first_error['type'])
            self.assertEqual(str(caught.exception), reader.first_error['message'])
            self.assertIn('traceback', reader.first_error)
            self.assert_owned_failure(reader.first_error['numericFailure'], self.reader.OwnedWriterReader.start, 5)
            self.assertEqual(reader.first_error, self.reader._read_json(output/'failure.json'))

    def test_optional_metadata_failure_cannot_replace_actual_failed_start(self):
        for method in ('notices_enabled','capture_failure_code','validate_failure_code'):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as directory, \
                    patch.dict(os.environ, environment()), patch.object(numeric_notice, method,
                        side_effect=RuntimeError('synthetic metadata unavailable')):
                reader = self.reader.OwnedWriterReader(Path('/synthetic-suite'), Path(directory),
                    shell_pid=77, expected_shell_creation=111, suite_hwnd=11, parent_hwnd=12,
                    child_hwnd=22, office_pid=88, expected_url='', clock=lambda:1.)
                with patch.object(self.reader,'_controller_reader_clock_kind',return_value=1):
                    with self.assertRaises(FileExistsError) as caught: reader.start(12.)
                self.assertEqual(str(caught.exception), reader.first_error['message'])
                self.assertNotIn('numericFailure', reader.first_error)
                self.assertEqual(12., reader.deadline)

    def test_controller_captures_before_formatting_and_unknown_files_remain_zero(self):
        events = []
        class ObservedError(ValueError):
            def __str__(self):
                events.append('formatted')
                return 'synthetic original error'
        capture = numeric_notice.capture_failure_code
        def observed_capture(exc):
            events.append('captured')
            return capture(exc)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, environment()), \
                patch.object(numeric_notice, 'capture_failure_code', side_effect=observed_capture):
            reader = self.reader.OwnedWriterReader(Path('/synthetic-suite'), Path(directory),
                shell_pid=77, expected_shell_creation=111, suite_hwnd=11, parent_hwnd=12,
                child_hwnd=22, office_pid=88, expected_url='', clock=lambda:1.)
            try:
                raise ObservedError()
            except ObservedError as exc:
                reader._record_failure(exc)
            self.assertEqual('captured', events[0])
            self.assertIn('formatted', events[1:])
            self.assertEqual(dict(captured=1,exceptionCode=0,fileCode=0,line=0), reader.first_error['numericFailure'])
            self.assertEqual('synthetic original error', reader.first_error['message'])
