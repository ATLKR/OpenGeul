import ast
import builtins
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

E2E = Path(__file__).resolve().parents[1]
TARGET_E2E = E2E
ENTRIES = ((1, 'mcp_worker.py'), (2, 'structured_cli_mcp/valid_companion.py'))
MESSAGES = {
    1: '실제 MCP 작업자 검증에 실패했습니다. bounded 결과·기존 원본은 보존합니다.',
    2: 'Structured portable companion failed; no installed/full-feature success is claimed.',
}


class PoisonException(Exception):
    reads = []

    def __str__(self):
        type(self).reads.append(1)
        raise AssertionError()

    def __repr__(self):
        type(self).reads.append(2)
        raise AssertionError()

    def __getattribute__(self, name):
        if name in ('args', '__dict__'):
            type(self).reads.append(3)
            raise AssertionError()
        return BaseException.__getattribute__(self, name)


class PoisonEnvironment:
    def __getattribute__(self, name):
        raise AssertionError()


def load_helper():
    path = TARGET_E2E / 'bounded_failure_observer.py'
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location('_bounded_failure_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def namespace(primary, action=None):
    result = {'__name__': '__main__', 'PRIMARY': primary, 'sys': sys}
    names = ('require', 'private_runtime', 'password_inputs', 'current_binding', 'verify_executable', 'verify_host')
    for name in names:
        exec(compile('def ' + name + '():\n    raise PRIMARY\n', '<synthetic-public>', 'exec'), result)
    if action:
        body = '    ' + action + '()\n'
    else:
        body = '    raise PRIMARY\n'
    exec(compile('def main():\n' + body, '<synthetic-public>', 'exec'), result)
    return result


def run_entry(entry, primary, helper=None, action=None, success=False, import_failure=False):
    _, path = entry
    tree = ast.parse((TARGET_E2E / path).read_bytes())
    tail = tree.body[-1]
    code = compile(ast.Module(body=[tail], type_ignores=[]), '<synthetic-entry>', 'exec')
    ns = namespace(primary, action)
    if success:
        ns['main'] = lambda: None
    mcp, native = types.ModuleType('mcp_worker'), types.ModuleType('native_architecture')
    for name in ('private_runtime', 'password_inputs', 'current_binding'):
        setattr(mcp, name, ns[name])
    for name in ('verify_executable', 'verify_host'):
        setattr(native, name, ns[name])
    imports = []
    original_import = builtins.__import__

    def imported(name, *args, **kwargs):
        if name == 'bounded_failure_observer':
            imports.append(1)
            if import_failure or helper is None:
                raise ImportError()
            return helper
        return original_import(name, *args, **kwargs)

    output, stdout = io.StringIO(), io.StringIO()
    exit_value = None
    with mock.patch.object(os, 'environ', PoisonEnvironment()), mock.patch.dict(sys.modules, {'mcp_worker': mcp, 'native_architecture': native}), mock.patch.object(builtins, '__import__', imported), contextlib.redirect_stderr(output), contextlib.redirect_stdout(stdout):
        try:
            exec(code, ns)
        except SystemExit as error:
            exit_value = (error.code, error.__cause__, error.__suppress_context__)
    return output.getvalue(), stdout.getvalue(), exit_value, len(imports)


def decode_record(test, output):
    test.assertEqual(len(output.splitlines()), 1)
    test.assertLessEqual(len(output.encode('ascii')), 4096)
    record = json.loads(output)
    test.assertEqual(set(record), {'schemaVersion', 'entryCode', 'exceptionCode', 'diagnosticOnly', 'acceptanceEligible', 'unknownFrameCount', 'truncated', 'frames'})
    test.assertEqual(record['schemaVersion'], 1)
    test.assertEqual(record['diagnosticOnly'], 1)
    test.assertEqual(record['acceptanceEligible'], 0)
    for row in record['frames']:
        test.assertEqual(set(row), {'sourceFileCode', 'line'})
        test.assertIn(row['sourceFileCode'], (1, 2, 3))
        test.assertIs(type(row['line']), int)
    return record


class EntryFailureTests(unittest.TestCase):
    def setUp(self):
        PoisonException.reads = []

    def test_failure_emits_one_closed_record(self):
        helper = load_helper()
        for entry in ENTRIES:
            with self.subTest(entry=entry[0]):
                output, stdout, stopped, imports = run_entry(entry, PoisonException('synthetic-secret'), helper)
                record = decode_record(self, output)
                self.assertEqual(record['entryCode'], entry[0])
                self.assertEqual(record['exceptionCode'], 0)
                self.assertTrue(record['frames'])
                self.assertEqual(stdout, '')
                self.assertEqual(imports, 1)
                self.assertEqual(stopped, (MESSAGES[entry[0]], None, True))

    def test_poison_and_static_failure_are_preserved(self):
        for entry in ENTRIES:
            output, stdout, stopped, _ = run_entry(entry, PoisonException('synthetic-secret'), load_helper())
            self.assertEqual(stopped, (MESSAGES[entry[0]], None, True))
            self.assertEqual(stdout, '')
            self.assertNotIn('synthetic-secret', output)
        self.assertEqual(PoisonException.reads, [])

    def test_success_has_no_observer_import_or_call(self):
        def forbidden(*unused):
            raise AssertionError()
        helper = types.SimpleNamespace(emit_failure=forbidden)
        for entry in ENTRIES:
            output, stdout, stopped, imports = run_entry(entry, PoisonException(), helper, success=True)
            self.assertEqual((output, stdout, stopped, imports), ('', '', None, 0))

    def test_observer_baseexception_preserves_primary_and_static_exit(self):
        for entry in ENTRIES:
            with self.subTest(entry=entry[0]):
                observed = []
                primary = PoisonException('synthetic-secret')
                def broken(error, *unused):
                    observed.append((error, BaseException.__getattribute__(error, '__traceback__')))
                    raise KeyboardInterrupt()
                output, stdout, stopped, _ = run_entry(entry, primary, types.SimpleNamespace(emit_failure=broken))
                self.assertEqual(stopped, (MESSAGES[entry[0]], None, True))
                self.assertEqual((output, stdout), ('', ''))
                self.assertEqual(len(observed), 1)
                self.assertIs(observed[0][0], primary)
                self.assertIs(observed[0][1], BaseException.__getattribute__(primary, '__traceback__'))

    def test_import_failure_preserves_original_failure(self):
        for entry in ENTRIES:
            output, stdout, stopped, _ = run_entry(entry, PoisonException(), import_failure=True)
            self.assertEqual((output, stdout), ('', ''))
            self.assertEqual(stopped, (MESSAGES[entry[0]], None, True))

    def test_fixed_public_guard_functions_have_codes(self):
        helper = load_helper()
        cases = ((ENTRIES[0], 'private_runtime', 1), (ENTRIES[0], 'password_inputs', 1), (ENTRIES[0], 'current_binding', 1), (ENTRIES[0], 'verify_executable', 3), (ENTRIES[0], 'verify_host', 3), (ENTRIES[1], 'private_runtime', 1), (ENTRIES[1], 'verify_executable', 3), (ENTRIES[1], 'verify_host', 3))
        for entry, action, file_code in cases:
            with self.subTest(entry=entry[0], action=action):
                output, _, _, _ = run_entry(entry, PoisonException(), helper, action=action)
                record = decode_record(self, output)
                self.assertTrue(any(row['sourceFileCode'] == file_code for row in record['frames']))

    def test_main_tail_keeps_original_catch_and_static_raise(self):
        for entry, path in ENTRIES:
            tail = ast.parse((TARGET_E2E / path).read_bytes()).body[-1]
            guarded = tail.body[0]
            self.assertIsInstance(guarded, ast.Try)
            self.assertEqual(ast.dump(guarded.body[0]), ast.dump(ast.Expr(value=ast.Call(func=ast.Name(id='main', ctx=ast.Load()), args=[], keywords=[]))))
            handler = guarded.handlers[0]
            self.assertEqual(handler.type.id, 'Exception')
            raised = handler.body[-1]
            self.assertIsInstance(raised, ast.Raise)
            self.assertEqual(raised.exc.func.id, 'SystemExit')
            self.assertEqual(raised.exc.args[0].value, MESSAGES[entry])
            self.assertIsNone(raised.cause.value)


class FramePoison:
    def __init__(self, code):
        object.__setattr__(self, '_code', code)

    def __getattribute__(self, name):
        if name == 'f_code':
            return object.__getattribute__(self, '_code')
        raise AssertionError()


class TraceNode:
    def __init__(self, code, line, next_node=None, line_allowed=True):
        self.tb_frame = FramePoison(code)
        self._line, self.tb_next, self.line_allowed = line, next_node, line_allowed

    @property
    def tb_lineno(self):
        if not self.line_allowed:
            raise AssertionError()
        return self._line


def chain(count, code, line_allowed=True):
    node = None
    for i in reversed(range(count)):
        node = TraceNode(code, i + 1, node, line_allowed)
    return node


class HelperBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = load_helper()
        if cls.helper is None:
            raise AssertionError()

    def emit(self, error, registry=(), fake_trace=None, entry=1):
        output = io.StringIO()
        with mock.patch.object(os, 'environ', PoisonEnvironment()), contextlib.redirect_stderr(output):
            if fake_trace is None:
                value = self.helper.emit_failure(error, entry, registry)
            else:
                with mock.patch.object(self.helper, '_traceback', return_value=fake_trace):
                    value = self.helper.emit_failure(error, entry, registry)
        return value, output.getvalue()

    def test_poison_never_reads_args_repr_str_or_environment(self):
        PoisonException.reads = []
        value, output = self.emit(PoisonException('synthetic-secret'))
        self.assertTrue(value)
        decode_record(self, output)
        self.assertNotIn('synthetic-secret', output)
        self.assertEqual(PoisonException.reads, [])

    def test_traceback_slot_bypasses_custom_exception_property(self):
        class PoisonTraceback(PoisonException):
            reads = []
            @property
            def __traceback__(self):
                type(self).reads.append(4)
                raise AssertionError()
        value, output = self.emit(PoisonTraceback('synthetic-secret'))
        self.assertTrue(value)
        decode_record(self, output)
        self.assertEqual(PoisonTraceback.reads, [])

    def test_unknown_frame_never_reads_filename_locals_or_line(self):
        value, output = self.emit(PoisonException(), fake_trace=chain(3, object(), False))
        self.assertTrue(value)
        record = decode_record(self, output)
        self.assertEqual((record['unknownFrameCount'], record['frames'], record['truncated']), (3, [], 0))

    def test_known_code_identity_and_line(self):
        known = self.test_known_code_identity_and_line.__func__.__code__
        value, output = self.emit(PoisonException(), ((known, 2),), TraceNode(known, 123), entry=2)
        self.assertTrue(value)
        self.assertEqual(decode_record(self, output)['frames'], [{'sourceFileCode': 2, 'line': 123}])

    def test_scan_is_bounded_to_32(self):
        value, output = self.emit(PoisonException(), fake_trace=chain(33, object(), False))
        self.assertTrue(value)
        record = decode_record(self, output)
        self.assertEqual((record['unknownFrameCount'], record['truncated']), (32, 1))

    def test_32_is_not_truncated_without_more_frames(self):
        value, output = self.emit(PoisonException(), fake_trace=chain(32, object(), False))
        self.assertTrue(value)
        record = decode_record(self, output)
        self.assertEqual((record['unknownFrameCount'], record['truncated']), (32, 0))

    def test_known_rows_are_bounded_to_12(self):
        known = self.test_known_rows_are_bounded_to_12.__func__.__code__
        value, output = self.emit(PoisonException(), ((known, 1),), chain(13, known))
        self.assertTrue(value)
        record = decode_record(self, output)
        self.assertEqual((len(record['frames']), record['unknownFrameCount'], record['truncated']), (12, 0, 1))

    def test_12_rows_and_json_byte_limit(self):
        known = self.test_12_rows_and_json_byte_limit.__func__.__code__
        node = chain(12, known)
        root = node
        while node:
            node._line = 2147483647
            node = node.tb_next
        value, output = self.emit(PoisonException(), ((known, 1),), root)
        self.assertTrue(value)
        record = decode_record(self, output)
        self.assertEqual((len(record['frames']), record['truncated']), (12, 0))
        self.assertLessEqual(len(output.encode('ascii')), 4096)

    def test_cycle_stops_at_scan_limit(self):
        node = TraceNode(object(), 1, line_allowed=False)
        node.tb_next = node
        value, output = self.emit(PoisonException(), fake_trace=node)
        self.assertTrue(value)
        self.assertEqual(decode_record(self, output)['unknownFrameCount'], 32)

    def test_closed_exception_type_codes(self):
        for error, expected in ((ValueError(), 1), (AssertionError(), 2), (RuntimeError(), 3), (TimeoutError(), 4), (FileNotFoundError(), 5), (PermissionError(), 6), (OSError(), 7), (TypeError(), 8), (KeyError(), 9), (ImportError(), 10), (PoisonException(), 0)):
            with self.subTest(code=expected):
                value, output = self.emit(error)
                self.assertTrue(value)
                self.assertEqual(decode_record(self, output)['exceptionCode'], expected)

    def test_unknown_exception_metaclass_is_not_hashed(self):
        class Meta(type):
            def __hash__(cls):
                raise AssertionError()
        class Unknown(Exception, metaclass=Meta):
            pass
        value, output = self.emit(Unknown())
        self.assertTrue(value)
        self.assertEqual(decode_record(self, output)['exceptionCode'], 0)

    def test_serialization_baseexception_is_suppressed(self):
        with mock.patch.object(self.helper.json, 'dumps', side_effect=KeyboardInterrupt()):
            value, output = self.emit(PoisonException())
        self.assertFalse(value)
        self.assertEqual(output, '')

    def test_stderr_baseexception_is_suppressed(self):
        class Sink:
            calls = 0
            def write(self, value):
                self.calls += 1
                raise KeyboardInterrupt()
        sink = Sink()
        with mock.patch.object(sys, 'stderr', sink):
            self.assertFalse(self.helper.emit_failure(PoisonException(), 1, ()))
        self.assertEqual(sink.calls, 1)

    def test_invalid_entry_or_source_code_emits_nothing(self):
        known = self.test_invalid_entry_or_source_code_emits_nothing.__func__.__code__
        for entry, registry in ((0, ()), (True, ()), (1, ((known, 99),))):
            value, output = self.emit(PoisonException(), registry, entry=entry)
            self.assertEqual((value, output), (False, ''))

    def test_primary_traceback_identity_is_unchanged(self):
        try:
            raise PoisonException('synthetic-secret')
        except PoisonException as error:
            before = BaseException.__getattribute__(error, '__traceback__')
            value, output = self.emit(error)
            self.assertTrue(value)
            self.assertIs(before, BaseException.__getattribute__(error, '__traceback__'))

    def test_helper_ast_has_no_sensitive_reads_or_side_effects(self):
        tree = ast.parse((TARGET_E2E / 'bounded_failure_observer.py').read_bytes())
        forbidden_calls = {'str', 'repr', 'vars', 'locals', 'globals', 'open', 'getattr', 'print', 'eval', 'exec'}
        forbidden_attributes = {'args', 'f_locals', 'f_globals', 'co_filename', 'environ', 'argv', '__dict__', '__str__', '__repr__'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, forbidden_calls)
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, forbidden_attributes)
            if isinstance(node, ast.Import):
                self.assertTrue(all(alias.name in ('json', 'sys', 'types') for alias in node.names))


if __name__ == '__main__':
    unittest.main()
