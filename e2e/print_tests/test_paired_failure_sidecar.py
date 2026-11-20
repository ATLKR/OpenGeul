import ast
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import paired_print_run as runner
import paired_print_diagnostic as diagnostic
from paired_print_contract import Rejected

FILE = ROOT / 'paired_print_failure_sidecar.py'
if FILE.exists():
    spec = importlib.util.spec_from_file_location('paired_print_failure_sidecar', FILE)
    sidecar = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = sidecar
    spec.loader.exec_module(sidecar)
else:
    sidecar = None

SOURCE = '32493df98348dc3d713a5edd6ce3b8a910ab2748'
PROTECTED_LOGICAL_SHA256 = {'virtual_print.py': '4f77494bcaffb19a97bcdf44a0b7870eaad6aea06712195c4ade709668edc4dd', 'paired_print_collect.py': '1d4e5bf38c9a819a2624166f736b182cdc064e499776fa2c3fda7a9da7c8756e', 'paired_print_contract.py': 'c454a42d0eaad72da51783301f429cfbc1089618ca189de65f910a118345439b', 'print_raster.py': 'f9d90ac4550f57d1ab0707fd475a99a8f4c1b5a0e009218de7a1382f10cf40a4', 'print_results.py': 'b2ecbc38408971872b903b3282d9a8e1f45d3f1d59b733d89afb4363e241ef9f'}
LEASE_AST_SHA256 = '5cf7047126f2fd9482e5b1f5fd125c38ae7b53c81203922c37dc658dd0248c33'
WINDOWS_AST_SHA256 = '1693476af14552b0c86437546e8525840c44963b34c72c0566b324d1e038d65a'


class FailureSidecarTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(sidecar, 'fixed numeric failure sidecar is absent')
        self.error = Rejected(15)
        self.error.pairedRole = 1
        self.error.pairedFailureCase = 1
        self.error.pairedFailureBinding = (SOURCE, 777, 1)
        self.error.pairedFailureProgress = {
            'phaseCode': 3, 'printerCallAttempted': True, 'printerCallReturned': True,
            'originalOracleAttempted': None, 'originalOracleReturned': None,
            'rootIdentityKnown': True, 'originalRootPid': 17,
            'originalRootCreationFileTime': 134395509194324477,
        }

    def packet(self):
        return sidecar.build_sidecar(self.error, runner.project_failure(self.error))

    def test_fixed_numeric_packet_retains_case_root_and_unknown_oracle(self):
        value = self.packet()
        self.assertEqual((value['roleCode'], value['caseCode']), (1, 1))
        self.assertEqual(value['progress']['originalRootCreationFileTime'], 134395509194324477)
        self.assertIsNone(value['progress']['originalOracleAttempted'])
        self.assertIsNone(value['progress']['originalOracleReturned'])
        self.assertIs(value['progress']['printerCallReturned'], True)
        self.assertFalse(value['qualification'])
        self.assertFalse(value['acceptanceEligible'])
        def walk(x):
            if type(x) is dict:
                for y in x.values(): walk(y)
            elif type(x) is list:
                for y in x: walk(y)
            else:
                self.assertTrue(x is None or type(x) in (int, bool))
        walk(value)

    def test_independent_binding_rejects_source_run_or_attempt_mismatch(self):
        raw = sidecar.encode_sidecar(self.packet())
        self.assertEqual(sidecar.validate_sidecar(raw, SOURCE, 777, 1)['caseCode'], 1)
        for source, run, attempt in [('0' * 40, 777, 1), (SOURCE, 778, 1), (SOURCE, 777, 2)]:
            with self.subTest(caseNumber=attempt + run), self.assertRaises(ValueError):
                sidecar.validate_sidecar(raw, source, run, attempt)

    def test_no_binding_remains_unknown_and_cannot_be_upload_admitted(self):
        del self.error.pairedFailureBinding
        value = self.packet()
        self.assertFalse(value['sourceBindingKnown'])
        with self.assertRaises(ValueError):
            sidecar.validate_sidecar(sidecar.encode_sidecar(value), SOURCE, 777, 1)

    def test_closed_shape_caps_unknown_strings_duplicates_and_boolean_ids(self):
        raw = sidecar.encode_sidecar(self.packet())
        bad = [raw + b' ', raw.replace(b'"caseCode":1', b'"caseCode":true'),
               raw.replace(b'"caseCode":1', b'"caseCode":0'),
               raw.replace(b'"caseCode":1', b'"caseCode":1,"caseCode":1'),
               raw.replace(b'"caseCode":1', b'"caseCode":"SYNTHETIC-OPAQUE"'),
               raw + b'x' * 8193]
        for code, data in enumerate(bad):
            with self.subTest(caseNumber=code), self.assertRaises(ValueError):
                sidecar.validate_sidecar(data, SOURCE, 777, 1)

    def test_optional_write_is_exclusive_bounded_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'paired-print-failure.numeric.json'
            sidecar.write_sidecar(self.error, runner.project_failure(self.error), path=path)
            before = path.read_bytes()
            self.assertLessEqual(len(before), 8192)
            with self.assertRaises(FileExistsError):
                sidecar.write_sidecar(self.error, runner.project_failure(self.error), path=path)
            self.assertEqual(path.read_bytes(), before)

    def test_args_repr_and_unrelated_environment_are_not_read(self):
        class Error(RuntimeError):
            def __getattribute__(self, name):
                if name in ('args', '__str__', '__repr__', 'private'):
                    raise AssertionError('SYNTHETIC-DO-NOT-READ')
                return super().__getattribute__(name)
        error = Error('SYNTHETIC-DO-NOT-OUTPUT')
        error.private = object()
        raw = sidecar.encode_sidecar(sidecar.build_sidecar(error, runner.project_failure(error)))
        self.assertNotIn(b'SYNTHETIC', raw)
        self.assertNotIn(b'paired-print-failure-numeric', raw)

    def test_cached_census_root_conflict_rejects_sidecar_only(self):
        projected = runner.project_failure(self.error)
        projected['censusObservation'] = {
            'schemaVersion': 1, 'diagnosticOnly': True, 'acceptanceEligible': False,
            'rootPid': 19, 'originalRootCreationFileTime': 134395509194324477,
            'sealed': True, 'requireLiveRoot': True, 'snapshotCount': 10,
            'knownCount': 7, 'guardUnexpectedCount': 1, 'rootSnapshotReachableCount': 1,
            'rows': [{'pid': 23, 'parentPid': 17, 'executableRoleCode': 1}],
        }
        with self.assertRaises(ValueError): sidecar.build_sidecar(self.error, projected)

    def test_optional_build_leaves_original_failure_projection_unchanged(self):
        projected = runner.project_failure(self.error)
        before = json.dumps(projected, sort_keys=True)
        sidecar.encode_sidecar(sidecar.build_sidecar(self.error, projected))
        self.assertEqual(json.dumps(projected, sort_keys=True), before)

    def test_cli_reuses_local_file_guard_and_independent_expected_binding(self):
        import paired_print_windows as windows
        raw = sidecar.encode_sidecar(self.packet())
        args = ['paired_print_failure_sidecar.py', '--expected-source', SOURCE,
                '--expected-run', '777', '--expected-attempt', '1']
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', args), \
             mock.patch.object(windows, 'read_regular', return_value=(raw, {})) as reader, \
             contextlib.redirect_stdout(out):
            self.assertEqual(sidecar.main(), 0)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(reader.call_args.args, (sidecar.OUTPUT, 8192))
        self.assertEqual(json.loads(out.getvalue()), {'admitted': True, 'qualification': False, 'errorCode': 0})


class ActualAttemptProgressTests(unittest.TestCase):
    def invoke(self, *, printer_error=None, retirement_error=None, close_error=None, oracle=None):
        lease = diagnostic.RetainedLease.__new__(diagnostic.RetainedLease)
        lease.root_pid = 17
        lease.handles = {17: {'creation': 134395509194324477}}
        lease.operation_error = None
        events = []
        def retired():
            events.append(1)
            if retirement_error is not None: raise retirement_error
            return {'retainedRootExited': True, 'retainedWebviewCount': 2, 'retainedWebviewsExited': True}
        def close():
            events.append(2)
            if close_error is not None: raise close_error
        lease.wait_retired, lease.close = retired, close
        def printer(*args, admission):
            admission(object(), args[3])
            if printer_error is not None: raise printer_error
            return {'syntheticReport': True}
        result = diagnostic.invoke_print(printer, Path('editor'), Path('fixture'), {}, Path('owned'),
                                         lambda *args: lease, oracle or (lambda error: False))
        return result, events

    def test_actual_cleanup_failure_stamps_cached_root_without_oracle_claim(self):
        error = Rejected(15)
        with self.assertRaises(Rejected) as caught: self.invoke(retirement_error=error)
        self.assertIs(caught.exception, error)
        value = getattr(error, 'pairedFailureProgress', None)
        self.assertIsNotNone(value, 'actual invoke_print does not retain progress')
        self.assertEqual(value['phaseCode'], 3)
        self.assertTrue(value['printerCallReturned'])
        self.assertIsNone(value['originalOracleReturned'])
        self.assertEqual(value['originalRootCreationFileTime'], 134395509194324477)

    def test_primary_identity_and_original_cleanup_sequence_are_unchanged(self):
        primary, cleanup = KeyboardInterrupt(), Rejected(15)
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.invoke(printer_error=primary, retirement_error=cleanup)
        self.assertIs(caught.exception, primary)
        self.assertEqual(getattr(primary, 'pairedFailureProgress', {}).get('phaseCode'), 1)

    def test_existing_oracle_predicate_is_not_called_early_or_twice(self):
        primary, cleanup, calls = ValueError(), Rejected(15), []
        def oracle(error): calls.append(1); return True
        with self.assertRaises(ValueError):
            self.invoke(printer_error=primary, retirement_error=cleanup, oracle=oracle)
        self.assertEqual(calls, [])
        self.assertIsNone(getattr(primary, 'pairedFailureProgress', {}).get('originalOracleAttempted'))
        (report, error, retired), _ = self.invoke(printer_error=primary, oracle=oracle)
        self.assertIs(error, primary)
        self.assertEqual(calls, [1])
        self.assertTrue(primary.pairedFailureProgress['originalOracleAttempted'])
        self.assertFalse(primary.pairedFailureProgress['originalOracleReturned'])

    def test_optional_stamp_failure_does_not_replace_primary_or_cleanup(self):
        class Error(RuntimeError):
            def __setattr__(self, name, value): raise RuntimeError('SYNTHETIC-STAMP-FAILURE')
        error = Error()
        with self.assertRaises(Error) as caught: self.invoke(retirement_error=error)
        self.assertIs(caught.exception, error)

    def test_real_close_clears_handles_but_original_cached_root_survives(self):
        lease = diagnostic.RetainedLease.__new__(diagnostic.RetainedLease)
        lease.root_pid, lease.closed = 17, False
        lease.handles = {17: {'creation': 134395509194324477, 'own': False, 'handle': 19},
                         23: {'creation': 134395509194324478, 'own': True, 'handle': 29}}
        lease.operation_error = None
        events = []
        class Kernel:
            def CloseHandle(self, handle): events.append(('handle', handle)); return True
        class Probe:
            def close(self): events.append(('probe', 1))
        lease.kernel, lease.probe = Kernel(), Probe()
        primary = Rejected(15)
        def retired(): raise primary
        lease.wait_retired = retired
        def printer(*args, admission):
            admission(object(), args[3])
            return {'syntheticReport': True}
        with self.assertRaises(Rejected) as caught:
            diagnostic.invoke_print(printer, Path('editor'), Path('fixture'), {}, Path('owned'),
                                    lambda *args: lease, lambda error: False)
        self.assertIs(caught.exception, primary)
        self.assertEqual(lease.handles, {})
        self.assertEqual(events, [('handle', 29), ('probe', 1)])
        progress = primary.pairedFailureProgress
        self.assertEqual(progress['phaseCode'], 3)
        self.assertTrue(progress['rootIdentityKnown'])
        self.assertEqual((progress['originalRootPid'], progress['originalRootCreationFileTime']),
                         (17, 134395509194324477))

    def test_optional_root_cache_fault_keeps_original_success_and_failure(self):
        with mock.patch.object(diagnostic, '_cached_original_root', side_effect=KeyboardInterrupt()):
            (report, error, retired), events = self.invoke()
        self.assertTrue(report['syntheticReport'])
        self.assertIsNone(error)
        self.assertTrue(retired['retainedRootExited'])
        self.assertEqual(events, [1, 2])
        primary = Rejected(15)
        with mock.patch.object(diagnostic, '_cached_original_root', side_effect=OSError()), \
             self.assertRaises(Rejected) as caught:
            self.invoke(retirement_error=primary)
        self.assertIs(caught.exception, primary)
        self.assertFalse(primary.pairedFailureProgress['rootIdentityKnown'])

    def test_owned_guard_class_and_original_print_files_are_unchanged(self):
        for name, expected in PROTECTED_LOGICAL_SHA256.items():
            actual = hashlib.sha256((ROOT / name).read_text(encoding='utf-8').encode()).hexdigest()
            self.assertEqual(actual, expected)
        lease = next(x for x in ast.parse((ROOT / 'paired_print_diagnostic.py').read_bytes()).body
                     if isinstance(x, ast.ClassDef) and x.name == 'RetainedLease')
        self.assertEqual(hashlib.sha256(ast.dump(lease, include_attributes=False).encode()).hexdigest(), LEASE_AST_SHA256)
        candidate = ast.parse((ROOT / 'paired_print_windows.py').read_bytes())
        owner = self
        class StripCachedCase(ast.NodeTransformer):
            def visit_Assign(self, node):
                if any(isinstance(t, ast.Attribute) and t.attr == 'pairedFailureCase' for t in node.targets):
                    return None
                return node
            def visit_Try(self, node):
                invoke_wrapper = (len(node.body) == 1 and isinstance(node.body[0], ast.Assign)
                    and isinstance(node.body[0].value, ast.Call)
                    and isinstance(node.body[0].value.func, ast.Name)
                    and node.body[0].value.func.id == 'invoke_print')
                node = self.generic_visit(node)
                if invoke_wrapper:
                    owner.assertFalse(node.orelse or node.finalbody)
                    owner.assertEqual(len(node.handlers), 1)
                    handler = node.handlers[0]
                    owner.assertIsInstance(handler.type, ast.Name)
                    owner.assertEqual((handler.type.id, handler.name), ('BaseException', 'error'))
                    owner.assertEqual(len(handler.body), 1)
                    owner.assertIsInstance(handler.body[0], ast.Raise)
                    owner.assertIsNone(handler.body[0].exc)
                    owner.assertIsNone(handler.body[0].cause)
                    return node.body
                if not node.body:
                    owner.assertFalse(node.orelse or node.finalbody)
                    owner.assertEqual(len(node.handlers), 1)
                    owner.assertIsInstance(node.handlers[0].type, ast.Name)
                    owner.assertEqual(node.handlers[0].type.id, 'BaseException')
                    owner.assertEqual(len(node.handlers[0].body), 1)
                    owner.assertIsInstance(node.handlers[0].body[0], ast.Pass)
                    return None
                for handler in node.handlers:
                    if (handler.name == 'error' and len(handler.body) == 2
                            and isinstance(handler.body[0], ast.If)
                            and isinstance(handler.body[1], ast.Raise)
                            and not any(isinstance(n, ast.Name) and n.id == 'error'
                                        for statement in handler.body for n in ast.walk(statement))):
                        handler.name = None
                return node
        stripped = StripCachedCase().visit(candidate)
        self.assertEqual(hashlib.sha256(ast.dump(stripped, include_attributes=False).encode()).hexdigest(), WINDOWS_AST_SHA256)



class MainSidecarIsolationTests(unittest.TestCase):
    def arguments(self, optin):
        args = ['paired_print_run.py', '--run-paired-print']
        for name in ('legacy-cache', 'legacy-runtime', 'current-runtime', 'package', 'wasm',
                     'inputs', 'fixtures', 'work', 'output'):
            args.extend(['--' + name, 'synthetic-owned-path'])
        args.extend(['--current-provenance-sha256', '1' * 64, '--harness-source', SOURCE,
                     '--run-id', '777', '--run-attempt', '1'])
        if optin: args.append('--failure-numeric-sidecar')
        return args

    def test_disabled_sidecar_keeps_original_stdout_and_calls_no_writer(self):
        self.assertIsNotNone(sidecar)
        primary = Rejected(15)
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', self.arguments(False)), \
             mock.patch.object(runner, 'run', side_effect=primary), \
             mock.patch.object(sidecar, 'write_sidecar') as writer, contextlib.redirect_stdout(out):
            code = runner.main()
        self.assertEqual(code, 1)
        self.assertEqual(writer.call_count, 0)
        value = json.loads(out.getvalue())
        self.assertEqual((value['errorCode'], value['exceptionCode']), (15, 1))
        self.assertFalse(value['qualification'])

    def test_optional_writer_exception_keeps_original_stdout_and_exit_code(self):
        self.assertIsNotNone(sidecar)
        primary = Rejected(15)
        for number, error in enumerate((OSError(), KeyboardInterrupt())):
            with self.subTest(caseNumber=number):
                out = io.StringIO()
                with mock.patch.object(sys, 'argv', self.arguments(True)), \
                     mock.patch.object(runner, 'run', side_effect=primary), \
                     mock.patch.object(sidecar, 'write_sidecar', side_effect=error) as writer, \
                     contextlib.redirect_stdout(out):
                    code = runner.main()
                self.assertEqual(code, 1)
                self.assertEqual(writer.call_count, 1)
                value = json.loads(out.getvalue())
                self.assertEqual((value['errorCode'], value['exceptionCode']), (15, 1))
                self.assertEqual(len(out.getvalue().splitlines()), 1)

    def test_actual_run_exception_handler_stamps_binding_without_inventing_case(self):
        tree = ast.parse((ROOT / 'paired_print_run.py').read_bytes())
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
        block = next(n for n in run.body if isinstance(n, ast.Try))
        primary = Rejected(15)
        class Port:
            attempts = [(1, 1)]
        namespace = {'primary': primary, 'port': Port(), 'BaseException': BaseException,
                     'expected_pair': {'harnessSourceCommit': SOURCE, 'harnessRunId': 777, 'harnessRunAttempt': 1}}
        outer = ast.Try(body=[ast.Raise(exc=ast.Name(id='primary', ctx=ast.Load()), cause=None)],
                        handlers=block.handlers, orelse=[], finalbody=[])
        program = ast.fix_missing_locations(ast.Module(body=[outer], type_ignores=[]))
        with self.assertRaises(Rejected) as caught:
            exec(compile(program, str(ROOT / 'paired_print_run.py'), 'exec'), namespace)
        self.assertIs(caught.exception, primary)
        self.assertFalse(hasattr(primary, 'pairedFailureCase'))
        self.assertEqual(primary.pairedRole, 1)
        self.assertEqual(primary.pairedFailureBinding, (SOURCE, 777, 1))

    def test_actual_print_case_boundary_preserves_active_case_on_invoke_failure(self):
        tree = ast.parse((ROOT / 'paired_print_windows.py').read_bytes())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'WindowsPort')
        function = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'print_case')
        boundary = next(n for n in function.body if isinstance(n, ast.Try)
            and len(n.body) == 1 and isinstance(n.body[0], ast.Assign)
            and isinstance(n.body[0].value, ast.Call)
            and isinstance(n.body[0].value.func, ast.Name) and n.body[0].value.func.id == 'invoke_print')
        run_tree = ast.parse((ROOT / 'paired_print_run.py').read_bytes())
        run = next(n for n in run_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
        run_block = next(n for n in run.body if isinstance(n, ast.Try))
        primary = Rejected(15)
        class Port:
            attempts = [(1, 1)]
            printer = None
            oracle_error = None
        def invoke(*args): raise primary
        namespace = {'invoke_print': invoke, 'self': Port(), 'port': Port(),
                     'exe': None, 'source': None, 'case': None, 'folder': None, 'admission': None,
                     'code': 1, 'BaseException': BaseException,
                     'expected_pair': {'harnessSourceCommit': SOURCE, 'harnessRunId': 777, 'harnessRunAttempt': 1}}
        outer = ast.Try(body=[boundary], handlers=run_block.handlers, orelse=[], finalbody=[])
        program = ast.fix_missing_locations(ast.Module(body=[outer], type_ignores=[]))
        with self.assertRaises(Rejected) as caught:
            exec(compile(program, str(ROOT / 'paired_print_windows.py'), 'exec'), namespace)
        self.assertIs(caught.exception, primary)
        value = sidecar.build_sidecar(primary, runner.project_failure(primary))
        self.assertEqual((value['roleCode'], value['caseCode']), (1, 1))

    def test_rethrown_first_oracle_keeps_its_case_after_all_four_attempts(self):
        tree = ast.parse((ROOT / 'paired_print_run.py').read_bytes())
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
        block = next(n for n in run.body if isinstance(n, ast.Try))
        primary = Rejected(15)
        primary.pairedRole, primary.pairedFailureCase = 1, 1
        class Port:
            attempts = [(1, 1), (1, 6), (2, 1), (2, 6)]
        namespace = {'primary': primary, 'port': Port(), 'BaseException': BaseException,
                     'expected_pair': {'harnessSourceCommit': SOURCE, 'harnessRunId': 777, 'harnessRunAttempt': 1}}
        outer = ast.Try(body=[ast.Raise(exc=ast.Name(id='primary', ctx=ast.Load()), cause=None)],
                        handlers=block.handlers, orelse=[], finalbody=[])
        program = ast.fix_missing_locations(ast.Module(body=[outer], type_ignores=[]))
        with self.assertRaises(Rejected):
            exec(compile(program, str(ROOT / 'paired_print_run.py'), 'exec'), namespace)
        self.assertEqual((primary.pairedRole, primary.pairedFailureCase), (1, 1))

    def test_actual_aggregate_collector_failure_keeps_case_unknown(self):
        tree = ast.parse((ROOT / 'paired_print_run.py').read_bytes())
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
        block = next(n for n in run.body if isinstance(n, ast.Try))
        primary = Rejected(26)
        class Port:
            attempts = [(1, 1), (1, 6), (2, 1), (2, 6)]
            profile_observations = []
            def raise_original_oracle(self): raise AssertionError('SYNTHETIC-UNREACHED')
        port = Port()
        def collector(*args): raise primary
        namespace = {'execute': lambda: runner.execute_pair({}, [], port, Path('private'), Path('allowlist'),
                     compare=lambda *args: {}, collector=collector), 'port': port, 'BaseException': BaseException,
                     'expected_pair': {'harnessSourceCommit': SOURCE, 'harnessRunId': 777, 'harnessRunAttempt': 1}}
        outer = ast.Try(body=[ast.Expr(value=ast.Call(func=ast.Name(id='execute', ctx=ast.Load()), args=[], keywords=[]))],
                        handlers=block.handlers, orelse=[], finalbody=[])
        program = ast.fix_missing_locations(ast.Module(body=[outer], type_ignores=[]))
        with self.assertRaises(Rejected) as caught:
            exec(compile(program, str(ROOT / 'paired_print_run.py'), 'exec'), namespace)
        self.assertIs(caught.exception, primary)
        value = sidecar.build_sidecar(primary, runner.project_failure(primary))
        self.assertEqual((value['roleCode'], value['caseCode']), (0, 0))


if __name__ == '__main__': unittest.main()
