"""Content-free save evidence, with no Office runtime or GUI proof."""
from contextlib import redirect_stderr, redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

WORKER = Path(__file__).resolve().parents[1] / 'worker'
sys.path.insert(0, str(WORKER))


class SaveBackend:
    def __init__(self):
        self.calls = []
        self.failure = None

    def save(self, path, filter_name):
        self.calls.append((path, filter_name))
        if self.failure is not None:
            raise self.failure

    def status(self):
        return {'modified': False, 'title': 'private document title'}


class SaveDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.worker = importlib.import_module('office_worker')
        self.session_module = importlib.import_module('session')
        self.dispatch_module = importlib.import_module('dispatch')
        # Isolate each process-local writer while exercising the real file sink.
        diagnostics = sys.modules.get('save_diagnostics')
        if diagnostics is not None:
            writer = patch.object(diagnostics, '_trace', diagnostics.SaveTrace())
            writer.start()
            self.addCleanup(writer.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.evidence = self.root / 'evidence'
        environment = patch.dict(os.environ, {'OPENGEUL_SUITE_DIAGNOSTICS': str(self.evidence)})
        environment.start()
        self.addCleanup(environment.stop)
        self.backend = SaveBackend()
        modules = {'calc': {'factory': 'private:factory/scalc',
                           'extensions': ['ods'], 'filters': {'ods': 'calc8'}}}
        self.session = self.session_module.DocumentSession(self.root, modules)
        self.session.backend = self.backend
        self.session.module, self.session.path, self.session.state = 'calc', self.root / 'private-book.ods', 'attached'

    def request(self, request_id=17, args=None):
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()) as output:
            result = self.worker.handle_request(self.session,
                {'id': request_id, 'command': 'save', 'args': {} if args is None else args})
        self.assertEqual('', output.getvalue(), 'diagnostics polluted the worker JSONL channel')
        return result

    def records(self):
        files = list(self.evidence.glob('worker-save-*.jsonl'))
        self.assertEqual(1, len(files), 'missing exclusive worker save trace')
        data = files[0].read_text(encoding='utf-8')
        for secret in ('private document title', 'private-book.ods', 'private-destination.ods',
                       'private exception message', 'private native query'):
            self.assertNotIn(secret, data)
        return [json.loads(line) for line in data.splitlines()]

    def test_save_records_exact_request_id_and_preserves_result(self):
        for request_id in (17, 'save-id\nwith-newline'):
            result = self.request(request_id)
            self.assertEqual({'id': request_id, 'ok': True, 'result': {
                'modified': False, 'title': 'private document title', 'module': 'calc',
                'path': str(self.session.path)}}, result)
        records = self.records()
        self.assertEqual(['request.begin', 'request.end'] * 2, [r['stage'] for r in records])
        self.assertEqual([17, 17, 'save-id\nwith-newline', 'save-id\nwith-newline'],
                         [r['details']['requestId'] for r in records])
        self.assertEqual([1, 2, 3, 4], [r['sequence'] for r in records])
        for record in records:
            self.assertEqual('suite.workerSave', record['event'])
            self.assertEqual('worker', record['component'])
            self.assertEqual(os.getpid(), record['workerPid'])
            self.assertEqual(threading.get_ident(), record['threadId'])
            self.assertIsInstance(record['utc'], str)
        self.assertTrue(records[1]['details']['ok'])
        self.assertEqual([(None, None)] * 2, self.backend.calls)

    def test_save_as_metadata_omits_target_filter_and_result_content(self):
        target = self.root / 'private-destination.ods'
        result = self.request('save-as', {'path': str(target), 'filter': 'calc8'})
        self.assertTrue(result['ok'])
        self.assertEqual(target, self.session.path)
        self.assertEqual([(target, 'calc8')], self.backend.calls)
        self.assertEqual(['request.begin', 'request.end'], [r['stage'] for r in self.records()])

    def test_save_failure_records_error_without_retry_or_exception_message(self):
        self.backend.failure = RuntimeError('private exception message')
        result = self.request('failed-save')
        self.assertEqual({'id': 'failed-save', 'ok': False, 'error': {
            'code': 'save_failed', 'message': '문서를 저장하지 못했습니다. 문서를 열어 둡니다.'}}, result)
        records = self.records()
        self.assertEqual(['request.begin', 'request.error'], [r['stage'] for r in records])
        self.assertEqual({'requestId': 'failed-save', 'ok': False, 'errorCode': 'save_failed',
                          'exceptionType': 'WorkerError'}, records[-1]['details'])
        self.assertEqual([(None, None)], self.backend.calls)
        self.assertEqual('attached', self.session.state)
        self.assertIs(self.backend, self.session.backend)

    def test_unexpected_save_error_keeps_generic_protocol_error(self):
        def fail(command, args):
            raise ValueError('private exception message')
        self.session.dispatch = fail
        result = self.request(19)
        self.assertEqual('engine_error', result['error']['code'])
        self.assertEqual({'requestId': 19, 'ok': False, 'errorCode': 'engine_error',
                          'exceptionType': 'ValueError'}, self.records()[-1]['details'])

    def test_native_save_receipts_precede_unchanged_command_forwarding(self):
        forwarded = []
        def receive(command):
            forwarded.append((command, self.records()[-1]))
        router = self.dispatch_module.DispatchRouter(receive)
        for name in ('.uno:Save', '.uno:SaveAs', '.uno:SaveAll'):
            router.dispatch(SimpleNamespace(Complete=name + '?private native query'), ())
        self.assertEqual(['save', 'saveAs', 'save'], [row[0] for row in forwarded])
        records = self.records()
        self.assertEqual([1, 2, 3], [r['details']['receiptSequence'] for r in records])
        self.assertEqual(['.uno:Save', '.uno:SaveAs', '.uno:SaveAll'],
                         [r['details']['nativeCommand'] for r in records])
        self.assertTrue(all(r['event'] == 'suite.nativeDispatch' and r['stage'] == 'received'
                            and r['component'] == 'worker' for r in records))

    def test_valid_host_trace_token_matches_worker_and_native_records(self):
        token = '0123456789abcdef0123456789abcdef'
        with patch.dict(os.environ, {'OPENGEUL_SUITE_SAVE_TRACE_ID': token}):
            self.assertTrue(self.request()['ok'])
            self.dispatch_module.DispatchRouter(lambda command: None).dispatch(
                SimpleNamespace(Complete='.uno:Save'), ())
        self.assertEqual([token] * 3, [row.get('traceId') for row in self.records()])

    def test_malformed_host_trace_tokens_never_enter_records(self):
        for token in ('private malformed token', 'A' * 32, 'a' * 31, 'a' * 33, 'a' * 32 + '\n'):
            with patch.dict(os.environ, {'OPENGEUL_SUITE_SAVE_TRACE_ID': token}):
                self.assertTrue(self.request()['ok'])
        records = self.records()
        self.assertTrue(all('traceId' in row and row['traceId'] is None for row in records))
        trace_bytes = next(self.evidence.glob('worker-save-*.jsonl')).read_text(encoding='utf-8')
        self.assertNotIn('private malformed token', trace_bytes)

    def test_host_trace_token_does_not_enable_disabled_diagnostics(self):
        with patch.dict(os.environ, {'OPENGEUL_SUITE_DIAGNOSTICS': '',
                                    'OPENGEUL_SUITE_SAVE_TRACE_ID': 'a' * 32}):
            self.assertTrue(self.request()['ok'])
        self.assertFalse(self.evidence.exists())

    def test_disabled_diagnostics_leave_no_files_and_forward_save_once(self):
        with patch.dict(os.environ, {'OPENGEUL_SUITE_DIAGNOSTICS': ''}):
            self.assertTrue(self.request()['ok'])
            forwarded = []
            self.dispatch_module.DispatchRouter(forwarded.append).dispatch(
                SimpleNamespace(Complete='.uno:Save'), ())
        self.assertFalse(self.evidence.exists())
        self.assertEqual([(None, None)], self.backend.calls)
        self.assertEqual(['save'], forwarded)

    def test_malformed_or_non_save_requests_do_not_write_save_records(self):
        with redirect_stderr(io.StringIO()):
            response = self.worker.handle_request(self.session,
                {'id': 5, 'command': 'save', 'args': []})
            self.worker.handle_request(self.session, {'id': 6, 'command': 'status', 'args': {}})
        self.assertEqual('invalid_request', response['error']['code'])
        self.dispatch_module.DispatchRouter(lambda command: None).dispatch(
            SimpleNamespace(Complete='file:///private-book.ods'), ())
        self.assertFalse(self.evidence.exists())

    def test_invalid_diagnostic_root_does_not_change_save_result(self):
        blocked = self.root / 'blocked'
        blocked.write_text('keep', encoding='utf-8')
        for root in ('relative-evidence', str(blocked)):
            with self.subTest(root=root), patch.dict(os.environ, {'OPENGEUL_SUITE_DIAGNOSTICS': root}):
                self.assertTrue(self.request()['ok'])
        self.assertEqual('keep', blocked.read_text(encoding='utf-8'))
        self.assertEqual([(None, None)] * 2, self.backend.calls)
        self.assertFalse(self.evidence.exists())

    def test_linked_diagnostic_root_is_failure_isolated_without_foreign_write(self):
        foreign = self.root / 'foreign'
        foreign.mkdir()
        linked = self.root / 'linked'
        # Exercise the rejected filesystem boundary on every platform, including
        # Windows accounts without symbolic-link privileges. The real link below
        # adds coverage when available; absence of that privilege never skips a test.
        diagnostics = importlib.import_module('save_diagnostics')
        with patch.object(diagnostics, 'plain_path', side_effect=ValueError('linked root rejected')), \
                patch.dict(os.environ, {'OPENGEUL_SUITE_DIAGNOSTICS': str(linked / 'evidence')}):
            self.assertTrue(self.request()['ok'])
        self.assertEqual([(None, None)], self.backend.calls)
        self.assertFalse(linked.exists())
        self.assertEqual([], list(foreign.iterdir()))
        try:
            linked.symlink_to(foreign, target_is_directory=True)
        except OSError:
            return
        with patch.dict(os.environ, {'OPENGEUL_SUITE_DIAGNOSTICS': str(linked / 'evidence')}):
            self.assertTrue(self.request()['ok'])
        self.assertEqual([(None, None)] * 2, self.backend.calls)
        self.assertEqual([], list(foreign.iterdir()))

    def test_trace_budget_bounds_records_and_skips_oversized_request_ids(self):
        self.assertTrue(self.request('x' * 20000)['ok'])
        for request_id in range(200):
            self.assertTrue(self.request(request_id)['ok'])
        records = self.records()
        self.assertLessEqual(len(records), 256)
        self.assertGreater(len(records), 0)
        self.assertTrue(all(len(json.dumps(r).encode('utf-8')) <= 4096 for r in records))
        self.assertTrue(all(type(r['details']['requestId']) is int for r in records))
        self.assertLessEqual(next(self.evidence.glob('worker-save-*.jsonl')).stat().st_size, 256 * 4096)
        self.assertEqual(201, len(self.backend.calls))


if __name__ == '__main__':
    unittest.main()
