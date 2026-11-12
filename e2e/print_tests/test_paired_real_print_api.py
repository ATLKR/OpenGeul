"""Execute the actual candidate function with only external Windows ports replaced."""
import ast
from contextlib import ExitStack
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'virtual_print.py'
RESULTS = ROOT / 'print_results.py'


class ActualPrintApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.fixture = self.folder / 'synthetic.hwpx'
        self.fixture.write_bytes(b'SYNTHETIC_OWNED_FIXTURE')
        self.events = []
        owner = self
        class Queue:
            name = 'owned-synthetic-queue'
            def __enter__(self): return self
            def __exit__(self, *args): owner.events.append('queue-closed')
            def jobs(self): return []
        class Page:
            def title(self): return '\u2022 synthetic'
        class Process:
            pid = 17
            _handle = 19
        class Session:
            page = Page()
            proc = Process()
            def __init__(self, *args, **kwargs):
                owner.events.append('session')
            def close(self): owner.events.append('session-closed')
        class Button:
            def click_input(self): owner.events.append('cancel-input')
        spec = importlib.util.spec_from_file_location('actual_print_results', RESULTS)
        results = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(results)
        self.namespace = {
            'Path': Path, 'json': json, 'shutil': shutil, 'ExitStack': ExitStack,
            'VirtualQueue': Queue, 'Session': Session,
            'digest': lambda path: hashlib.sha256(path.read_bytes()).hexdigest(),
            'stop_session': lambda session: session.close(),
            'capture_failure': lambda *args: False,
            'system_dialog': lambda *args: self.events.append('first-print-input'),
            'configure_media': lambda *args, **kwargs: None,
            'snapshot': lambda *args: None,
            'control': lambda *args: Button(),
            'visible_dialog': lambda *args: None,
            'wait': lambda check, *args: check(),
            'edit': lambda *args: None,
            'validate_cases': results.validate_cases,
        }
        tree = ast.parse(SOURCE.read_bytes())
        self.functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    def function(self, name):
        self.assertIn(name, self.functions, 'requested print function is absent')
        module = ast.Module(body=[self.functions[name]], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(SOURCE), 'exec'), self.namespace)
        return self.namespace[name]

    def print_call(self, *, admission=None, supply=False):
        call = self.function('print_document')
        args = (Path('editor'), self.fixture, {'name': 'cancel', 'cancel': True}, self.folder / 'fresh-case')
        if supply:
            try:
                return call(*args, admission=admission)
            except TypeError:
                self.fail('the actual print API has no admission keyword')
        return call(*args)

    def test_default_print_path_still_cancels_and_preserves_its_source(self):
        result = self.print_call()
        self.assertTrue(result['cancelled'])
        self.assertEqual(self.events, ['session', 'first-print-input', 'cancel-input', 'session-closed', 'queue-closed'])
        preserved = json.loads((self.folder / 'fresh-case/source-preservation.json').read_bytes())
        self.assertTrue(preserved['unchanged'])

    def test_admission_is_before_the_first_real_print_call(self):
        def admit(session, folder): self.events.append('admission')
        self.print_call(admission=admit, supply=True)
        self.assertEqual(self.events[:3], ['session', 'admission', 'first-print-input'])

    def test_admission_failure_keeps_original_exception_and_owned_cleanup(self):
        primary = ValueError()
        def admit(session, folder): raise primary
        with self.assertRaises(ValueError) as caught:
            self.print_call(admission=admit, supply=True)
        self.assertIs(caught.exception, primary)
        self.assertEqual(self.events, ['session', 'session-closed', 'queue-closed'])
        self.assertTrue(json.loads((self.folder / 'fresh-case/source-preservation.json').read_bytes())['unchanged'])

    def test_constructor_failure_never_supplies_an_owned_admission(self):
        primary = RuntimeError()
        def session(*args, **kwargs): raise primary
        self.namespace['Session'] = session
        with self.assertRaises(RuntimeError) as caught:
            self.print_call(admission=lambda *args: self.events.append('admission'), supply=True)
        self.assertIs(caught.exception, primary)
        self.assertEqual(self.events, ['queue-closed'])

    def test_retirement_checkpoint_is_after_capture_and_before_original_stop(self):
        events = self.events
        class Observer:
            def __exit__(self, error_type, error, traceback):
                events.append('sealed')
                return False
        self.namespace['capture_failure'] = lambda *args: events.append('capture') is not None
        self.print_call(admission=lambda *args: Observer(), supply=True)
        self.assertEqual(events[-4:], ['capture', 'sealed', 'session-closed', 'queue-closed'])

    def test_retirement_observer_receives_the_original_operation_error(self):
        primary = ValueError()
        observed = []
        class Observer:
            def __exit__(self, error_type, error, traceback):
                observed.append(error)
                return False
        def fail(*args): raise primary
        self.namespace['system_dialog'] = fail
        with self.assertRaises(ValueError) as caught:
            self.print_call(admission=lambda *args: Observer(), supply=True)
        self.assertIs(caught.exception, primary)
        self.assertEqual(observed, [primary])

    def test_one_case_builder_produces_all_eight_before_diagnostic_selection(self):
        fixtures = self.folder / 'fixtures'
        fixtures.mkdir()
        rows = [
            {'name': 'table--300', 'file': 't1.hwpx', 'pages': [{}]},
            {'name': 'table-0', 'file': 't2.hwpx', 'pages': [{}]},
            {'name': 'table-600', 'file': 't3.hwpx', 'pages': [{}]},
            {'name': 'multipage', 'file': 'multi.hwpx', 'pages': [{}, {}]},
        ]
        (fixtures / 'print-cases.json').write_text(json.dumps(rows))
        actual = self.function('build_cases')(self.folder / 'inputs', fixtures)
        self.assertEqual([row['name'] for row in actual],
                         ['table--300', 'table-0', 'table-600', 'multipage', 'basic-hwp', 'basic-hwpx', 'page-range', 'cancel'])
        self.assertEqual(actual[6]['pages'], [{}])

    def check_original_operation_error_after_cleanup_replacement(self, where):
        import paired_print_diagnostic
        primary, cleanup, retired = ValueError(), RuntimeError(), []
        class Lease:
            operation_error = None
            def remember_primary(self, error):
                if self.operation_error is None:self.operation_error=error
            def __exit__(self, error_type, error, traceback):
                self.remember_primary(error)
                return False
            def wait_retired(self):
                retired.append('wait')
                return {'retainedRootExited': True, 'retainedWebviewCount': 1,
                        'retainedWebviewsExited': True}
            def close(self): retired.append('close')
        lease = Lease()
        def fail(*args): raise primary
        self.namespace['system_dialog'] = fail
        if where == 'session':
            def stop(*args): raise cleanup
            self.namespace['stop_session'] = stop
        elif where == 'queue':
            original = self.namespace['VirtualQueue']
            class BadQueue(original):
                def __exit__(self, *args):
                    super().__exit__(*args)
                    raise cleanup
            self.namespace['VirtualQueue'] = BadQueue
        elif where == 'source-finally':
            original, calls = self.namespace['digest'], []
            def digest(path):
                calls.append(1)
                if len(calls) == 2: raise cleanup
                return original(path)
            self.namespace['digest'] = digest
        elif where == 'capture':
            def capture(*args): raise KeyboardInterrupt()
            self.namespace['capture_failure'] = capture
        printer = self.function('print_document')
        with self.assertRaises(ValueError) as caught:
            paired_print_diagnostic.invoke_print(printer, Path('editor'), self.fixture,
                {'name': 'cancel', 'cancel': True}, self.folder / 'actual-owned-case',
                lambda *args: lease, lambda error: error is primary)
        self.assertIs(caught.exception, primary)
        self.assertEqual(retired, ['wait', 'close'])

    def test_actual_session_cleanup_replacement_cannot_hide_original_operation(self):
        self.check_original_operation_error_after_cleanup_replacement('session')

    def test_actual_queue_cleanup_replacement_cannot_hide_original_operation(self):
        self.check_original_operation_error_after_cleanup_replacement('queue')

    def test_actual_source_finally_replacement_cannot_hide_original_operation(self):
        self.check_original_operation_error_after_cleanup_replacement('source-finally')

    def test_diagnostic_capture_cancellation_cannot_replace_original_operation(self):
        self.check_original_operation_error_after_cleanup_replacement('capture')


if __name__ == '__main__':
    unittest.main()
