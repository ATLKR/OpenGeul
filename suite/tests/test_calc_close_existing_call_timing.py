"""Portable preservation tests; these do not run Office or a native helper."""
import ast
import copy
import hashlib
import inspect
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
import calc_close_existing_call_timing as timing


ROOT = Path(__file__).resolve().parents[2]


def function(path, name, globals_):
    source = (ROOT / path).read_text(encoding='utf-8')
    tree = ast.parse(source)
    parts = name.split('.')
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == parts[0])
    if len(parts) == 2:
        node = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == parts[1])
    node = copy.deepcopy(node)
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / path), 'exec'), globals_, namespace)
    return namespace[node.name], node


class Clock:
    def __init__(self): self.value = 0
    def __call__(self): self.value += 10; return self.value


class TimingTests(unittest.TestCase):
    def collector(self, **kwargs):
        return timing.TimingCollector(clock=Clock(), **kwargs)

    def test_original_return_arguments_and_exactly_once(self):
        c = self.collector(); calls = []; value = object()
        def original(*args, **kwargs): calls.append((args, kwargs)); return value
        self.assertIs(c.invoke(0, original, 7, token=value), value)
        self.assertEqual(calls, [((7,), {'token': value})])
        c.finish(); self.assertTrue(c.snapshot()['complete'])

    def test_original_base_exception_identity_and_traceback(self):
        c = self.collector(); failure = KeyboardInterrupt('primary')
        def original(): raise failure
        with self.assertRaises(KeyboardInterrupt) as raised:
            c.invoke(0, original)
        self.assertIs(raised.exception, failure)
        c.finish(); self.assertEqual(c.snapshot()['events'][0]['raised'], True)

    def test_clock_failure_does_not_skip_original(self):
        def bad_clock(): raise RuntimeError('timer failed')
        c = timing.TimingCollector(clock=bad_clock); seen = []
        self.assertEqual(c.invoke(0, lambda: seen.append(1) or 29), 29)
        self.assertEqual(seen, [1]); c.finish()
        self.assertFalse(c.snapshot()['complete'])

    def test_end_clock_failure_keeps_primary_and_unwinds_stack(self):
        values = iter([10])
        c = timing.TimingCollector(clock=lambda: next(values))
        failure = ValueError('original')
        with self.assertRaises(ValueError) as raised:
            c.invoke(0, lambda: (_ for _ in ()).throw(failure))
        self.assertIs(raised.exception, failure)
        self.assertEqual(c.depth, 0); c.finish(); self.assertFalse(c.snapshot()['complete'])

    def test_end_clock_fault_retains_known_original_outcome(self):
        values = iter([10]); c = timing.TimingCollector(clock=lambda: next(values))
        primary = ValueError('original')
        with self.assertRaises(ValueError) as raised:
            c.invoke(0, lambda: (_ for _ in ()).throw(primary))
        self.assertIs(raised.exception, primary); c.finish()
        event = c.snapshot()['events'][0]
        self.assertFalse(event['finished']); self.assertIs(event['raised'], True)

    def test_unrecorded_outcome_is_null_instead_of_false(self):
        c = self.collector()
        def end(*args): raise RuntimeError('outcome recorder unavailable')
        c.end = end
        self.assertEqual(c.invoke(0, lambda: 31), 31); c.finish()
        event = c.snapshot()['events'][0]
        self.assertFalse(event['finished']); self.assertIsNone(event['raised'])

    def test_unexpected_begin_and_end_faults_are_secondary(self):
        for method in ('begin', 'end'):
            for fails in (False, True):
                with self.subTest(method=method, fails=fails):
                    c = self.collector(); seen = []; primary = ValueError('production')
                    def broken(*args): raise RuntimeError('collector')
                    setattr(c, method, broken)
                    def original():
                        seen.append(1)
                        if fails: raise primary
                        return 37
                    if fails:
                        with self.assertRaises(ValueError) as raised: c.invoke(0, original)
                        self.assertIs(raised.exception, primary)
                    else:
                        self.assertEqual(c.invoke(0, original), 37)
                    self.assertEqual(seen, [1]); self.assertNotEqual(c.flags, 0)

    def test_parent_id_survives_a_hot_aggregate_ancestor(self):
        c = self.collector(); c.case, c.phase, c.sequence = 0, 1, 0
        c.invoke(3, lambda: c.invoke(5, lambda: c.invoke(7, lambda: None)))
        c.finish(); rows = c.snapshot()['events']
        self.assertEqual(rows[1]['parentId'], rows[0]['id'])

    def test_finite_outer_overflow_does_not_hide_return_or_failure(self):
        c = self.collector(event_limit=1); seen = []
        self.assertEqual(c.invoke(0, lambda: 1), 1)
        self.assertEqual(c.invoke(0, lambda: seen.append('second') or 2), 2)
        failure = AssertionError('third')
        with self.assertRaises(AssertionError) as raised:
            c.invoke(0, lambda: (_ for _ in ()).throw(failure))
        self.assertIs(raised.exception, failure); self.assertEqual(seen, ['second'])
        c.finish(); snap = c.snapshot()
        self.assertFalse(snap['complete']); self.assertEqual(len(snap['events']), 1)

    def test_nested_events_are_inclusive_and_have_parent_ids(self):
        c = self.collector()
        c.invoke(0, lambda: c.invoke(1, lambda: 3))
        c.finish(); rows = c.snapshot()['events']
        self.assertEqual(rows[1]['parentId'], rows[0]['id'])
        self.assertGreater(rows[0]['elapsedNs'], rows[1]['elapsedNs'])
        self.assertIn('inclusive', c.snapshot()['durationBasis'])

    def test_hot_calls_aggregate_without_one_row_per_poll(self):
        c = self.collector(); c.case, c.phase, c.sequence = 1, 1, 0
        for _ in range(1000): self.assertEqual(c.invoke(4, lambda: 4), 4)
        c.finish(); snap = c.snapshot()
        self.assertEqual(snap['events'], [])
        self.assertEqual(snap['hotAggregates'][0]['count'], 1000)
        self.assertEqual(len(c.hot), 2232)

    def test_no_live_object_or_exception_retention(self):
        c = self.collector(); value = object()
        self.assertIs(c.invoke(0, lambda: value), value)
        self.assertTrue(all(type(v) is int for row in c.events for v in row))
        self.assertTrue(all(type(v) is int for row in c.hot for v in row))

    def test_snapshot_is_forbidden_until_original_unwind(self):
        c = self.collector()
        with self.assertRaises(AssertionError): c.snapshot()
        c.finish(); self.assertIsInstance(c.snapshot(), dict)

    def test_stack_bound_never_interrupts_original_leaf(self):
        c = self.collector(); leaves = []
        def nested(depth):
            if depth: return c.invoke(0, nested, depth-1)
            leaves.append(1); return 47
        self.assertEqual(c.invoke(0, nested, timing.MAX_STACK+5), 47)
        self.assertEqual(leaves, [1]); self.assertEqual(c.depth, 0)
        c.finish(); self.assertFalse(c.snapshot()['complete'])
        self.assertEqual(len(c.stack), timing.MAX_STACK)

    def test_collector_and_wrappers_contain_no_io_or_target_getter_calls(self):
        source = (ROOT / 'suite/e2e/calc_close_existing_call_timing.py').read_text()
        tree = ast.parse(source)
        nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TimingCollector']
        nodes += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'wrap_call']
        for root in nodes:
            for call in (n for n in ast.walk(root) if isinstance(n, ast.Call)):
                name = ast.unparse(call.func)
                self.assertFalse(name.startswith(('json.', 'os.', 'Path', 'subprocess.', 'native.')), name)
                self.assertNotIn(name.rsplit('.', 1)[-1], ('open', 'read_bytes', 'write_bytes', 'flush', 'fsync', 'print', 'repr', 'str'))


class TransformTests(unittest.TestCase):
    def original(self, which, globals_):
        path = 'suite/e2e/writer_model_reader.py' if which == 'atomic' else 'suite/e2e/counted_editor_shortcuts.py'
        name = '_atomic_json' if which == 'atomic' else 'CountedEditorShortcuts._retain'
        return function(path, name, globals_)

    def transformed(self, which, globals_, c):
        original, node = self.original(which, globals_)
        actual = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        transformed, proof = timing.transform_io(original, node, which, actual)
        globals_[timing.PRIVATE_INVOKE] = c.invoke
        return original, transformed, proof

    def test_two_real_function_ast_inverses_and_exact_call_counts(self):
        for which, count in [('atomic', 7), ('shortcut', 6)]:
            with self.subTest(which=which):
                c = timing.TimingCollector(clock=Clock())
                old, new, proof = self.transformed(which, {}, c)
                self.assertEqual(proof['callCount'], count)
                self.assertEqual(proof['originalAstSha256'], proof['inverseAstSha256'])
                self.assertEqual(old.__defaults__, new.__defaults__)
                self.assertEqual(old.__kwdefaults__, new.__kwdefaults__)
                self.assertEqual(old.__code__.co_varnames[:old.__code__.co_argcount], new.__code__.co_varnames[:new.__code__.co_argcount])

    def test_wrong_ast_pin_rejected_before_binding(self):
        old, node = self.original('atomic', {})
        with self.assertRaises(AssertionError): timing.transform_io(old, node, 'atomic', '0' * 64)

    def test_missing_or_extra_io_anchor_is_rejected(self):
        old, node = self.original('atomic', {})
        for extra in [False, True]:
            edited = copy.deepcopy(node)
            body = next(n for n in ast.walk(edited) if isinstance(n, ast.With)).body
            if len(body) == 3:
                if extra: body.append(copy.deepcopy(body[-1]))
                else: body.pop()
            else: self.fail('Unexpected production I/O statements')
            digest = hashlib.sha256(ast.dump(edited, include_attributes=False).encode()).hexdigest()
            with self.assertRaises(AssertionError): timing.transform_io(old, edited, 'atomic', digest)

    def test_changed_signature_is_rejected(self):
        old, node = self.original('atomic', {})
        node.args.args.append(ast.arg(arg='added'))
        digest = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        with self.assertRaises(AssertionError): timing.transform_io(old, node, 'atomic', digest)

    def test_real_atomic_bytes_and_durable_order_are_identical(self):
        for instrumented in [False, True]:
            with self.subTest(instrumented=instrumented), tempfile.TemporaryDirectory() as tmp:
                calls = []
                import os
                class OS:
                    @staticmethod
                    def fsync(fd): calls.append('fsync'); return os.fsync(fd)
                    @staticmethod
                    def replace(a, b): calls.append('replace'); return os.replace(a, b)
                globals_ = {'Path': Path, '_safe_file': lambda *a: calls.append('safe'), 'json': json, 'MAX_JSON_BYTES': 2 * 1024 * 1024, 'os': OS}
                c = timing.TimingCollector(clock=Clock())
                old, new, _ = self.transformed('atomic', globals_, c)
                fn = new if instrumented else old
                target = Path(tmp) / 'record.json'; value = {'pidBirth': 134372209461180553, 'text': '한글'}
                fn(target, value)
                self.assertEqual(target.read_bytes(), json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'))
                self.assertEqual(calls, ['safe', 'safe', 'fsync', 'replace'])
                self.assertFalse(target.with_name(target.name + '.tmp').exists())

    def test_real_retain_bytes_and_durability_precede_following_code(self):
        for instrumented in [False, True]:
            with self.subTest(instrumented=instrumented), tempfile.TemporaryDirectory() as tmp:
                calls = []
                class OS:
                    @staticmethod
                    def fsync(fd): calls.append('fsync')
                globals_ = {'json': json, 'os': OS, 'MAX_RECEIPT_BYTES': 128 * 1024}
                c = timing.TimingCollector(clock=Clock())
                old, new, _ = self.transformed('shortcut', globals_, c)
                owner = types.SimpleNamespace(output=Path(tmp), stem='case-000', receipt={'actions': [{'insertedInputs': 6}], 'birth': 134372209461180553})
                (new if instrumented else old)(owner, 'input-result'); calls.append('following-code')
                raw = (Path(tmp) / 'case-000-00-input-result.json').read_bytes()
                self.assertEqual(raw, (json.dumps(owner.receipt, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8'))
                self.assertEqual(calls, ['fsync', 'following-code'])

    def test_original_io_exception_identity_and_no_following_code(self):
        failure = OSError('original fsync'); calls = []
        class OS:
            @staticmethod
            def fsync(fd): calls.append('fsync'); raise failure
        with tempfile.TemporaryDirectory() as tmp:
            c = timing.TimingCollector(clock=Clock())
            old, new, _ = self.transformed('shortcut', {'json': json, 'os': OS, 'MAX_RECEIPT_BYTES': 128 * 1024}, c)
            owner = types.SimpleNamespace(output=Path(tmp), stem='case', receipt={'actions': []})
            with self.assertRaises(OSError) as raised: new(owner, 'admission')
            self.assertIs(raised.exception, failure); self.assertEqual(calls, ['fsync'])

    def fake_io(self, failing=None):
        calls = []; failure = OSError('original-' + str(failing))
        def called(name):
            calls.append(name)
            if name == failing: raise failure
        class Encoded:
            def encode(self, encoding): called('encode'); self_encoding.append(encoding); return b'payload'
        self_encoding = []
        class JSON:
            @staticmethod
            def dumps(value, **kwargs): called('serialize'); return Encoded()
        class Stream:
            def __enter__(self): called('enter'); return self
            def __exit__(self, *args): called('close'); return False
            def write(self, raw): called('write'); self_raw.append(raw)
            def flush(self): called('flush')
            def fileno(self): called('fileno'); return 91
        self_raw = []
        class Target:
            name = 'target.json'
            def with_name(self, name): return self
            def exists(self): return False
            def open(self, mode): called('open'); self_mode.append(mode); return Stream()
        self_mode = []
        class OS:
            @staticmethod
            def fsync(fd): called('fsync'); self_fd.append(fd)
            @staticmethod
            def replace(a, b): called('replace')
        self_fd = []
        globals_ = dict(Path=lambda p: p, _safe_file=lambda *args: None, json=JSON, os=OS, MAX_JSON_BYTES=2048)
        return globals_, Target(), calls, failure, [self_encoding, self_raw, self_mode, self_fd]

    def test_all_existing_io_calls_order_and_arguments_match_original(self):
        results = []
        for instrumented in (False, True):
            globals_, target, calls, _, arguments = self.fake_io()
            c = timing.TimingCollector(clock=Clock()); old, new, _ = self.transformed('atomic', globals_, c)
            (new if instrumented else old)(target, {'receipt': 1})
            results.append((calls, arguments))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1][0], ['serialize', 'encode', 'open', 'enter', 'write', 'flush', 'fileno', 'fsync', 'close', 'replace'])
        self.assertEqual(results[1][1], [['utf-8'], [b'payload'], ['xb'], [91]])

    def test_each_io_stage_fault_propagates_identically_and_never_retries(self):
        for failing in ('serialize', 'encode', 'open', 'enter', 'write', 'flush', 'fileno', 'fsync', 'close', 'replace'):
            observations = []
            for instrumented in (False, True):
                with self.subTest(failing=failing, instrumented=instrumented):
                    globals_, target, calls, failure, _ = self.fake_io(failing)
                    c = timing.TimingCollector(clock=Clock()); old, new, _ = self.transformed('atomic', globals_, c)
                    with self.assertRaises(OSError) as raised: (new if instrumented else old)(target, {})
                    self.assertIs(raised.exception, failure); self.assertEqual(calls.count(failing), 1)
                    observations.append(calls)
            self.assertEqual(observations[0], observations[1])

    def test_original_byte_cap_still_rejects_before_open(self):
        globals_, target, calls, _, _ = self.fake_io()
        globals_['MAX_JSON_BYTES'] = 6
        c = timing.TimingCollector(clock=Clock()); _, new, _ = self.transformed('atomic', globals_, c)
        with self.assertRaises(AssertionError): new(target, {})
        self.assertEqual(calls, ['serialize', 'encode'])


class BindingAndUnwindTests(unittest.TestCase):
    def test_existing_class_alias_and_inherited_method_restored(self):
        class Base:
            def call(self): return 'old'
        class Child(Base): pass
        alias = Base; old = Base.__dict__['call']
        new = lambda self: 'new'
        c = timing.TimingCollector(clock=Clock())
        with timing.Bindings([(Base, 'call', new)], [], c):
            self.assertEqual(alias().call(), 'new'); self.assertEqual(Child().call(), 'new')
        self.assertIs(Base.__dict__['call'], old)

    def test_restore_after_main_finally_before_timing_persist(self):
        module = types.ModuleType('owned'); module.fn = lambda: 'old'; old = module.fn
        c = timing.TimingCollector(clock=Clock()); order = []
        bindings = timing.Bindings([(module, 'fn', lambda: 'new')], [], c)
        failure = KeyboardInterrupt('primary')
        def main():
            try:
                order.append('main'); self.assertEqual(module.fn(), 'new'); raise failure
            finally:
                self.assertEqual(module.fn(), 'new'); order.append('original-cleanup')
        def persist(report):
            self.assertIs(module.fn, old); self.assertFalse(c.active); order.append('persist')
            self.assertEqual(report['originalInvocation']['exceptionType'], 'KeyboardInterrupt')
        with self.assertRaises(KeyboardInterrupt) as raised:
            timing.execute_original(main, bindings, c, ['original', '--output', 'fresh'], persist)
        self.assertIs(raised.exception, failure)
        self.assertEqual(order, ['main', 'original-cleanup', 'persist'])

    def test_persistence_failure_is_secondary_to_original(self):
        c = timing.TimingCollector(clock=Clock()); failure = ValueError('original')
        def main(): raise failure
        def persist(report): raise OSError('timing storage')
        with self.assertRaises(ValueError) as raised:
            timing.execute_original(main, timing.Bindings([], [], c), c, ['original'], persist)
        self.assertIs(raised.exception, failure)

    def test_finish_failure_is_secondary_to_original(self):
        c = timing.TimingCollector(clock=Clock()); failure = ValueError('original')
        def finish(): raise RuntimeError('collector finish')
        c.finish = finish
        with self.assertRaises(ValueError) as raised:
            timing.execute_original(lambda: (_ for _ in ()).throw(failure), timing.Bindings([], [], c), c, ['original'], lambda report: None)
        self.assertIs(raised.exception, failure)

    def test_private_globals_and_alias_restore_on_main_failure(self):
        module = types.ModuleType('owned'); module.fn = lambda: 'old'; original = module.fn
        c = timing.TimingCollector(clock=Clock()); private = {}
        bindings = timing.Bindings([(module, 'fn', lambda: 'instrumented')], [private], c)
        failure = RuntimeError('main')
        with self.assertRaises(RuntimeError) as raised:
            with bindings:
                self.assertIn(timing.PRIVATE_INVOKE, private); raise failure
        self.assertIs(raised.exception, failure)
        self.assertIs(module.fn, original); self.assertNotIn(timing.PRIVATE_INVOKE, private)

    def test_existing_private_global_rejected_before_installation(self):
        c = timing.TimingCollector(clock=Clock()); sentinel = object()
        private = {timing.PRIVATE_INVOKE: sentinel}
        with self.assertRaises(AssertionError): timing.Bindings([], [private], c)
        self.assertIs(private[timing.PRIVATE_INVOKE], sentinel)

    def test_rejected_binding_does_not_overwrite_foreign_change(self):
        module = types.ModuleType('owned'); module.first = lambda: 1; module.second = lambda: 2
        first = module.first; foreign = lambda: 99; private = {}
        c = timing.TimingCollector(clock=Clock())
        bindings = timing.Bindings([(module, 'first', lambda: 11), (module, 'second', lambda: 22)], [private], c)
        module.second = foreign
        with self.assertRaises(AssertionError):
            with bindings: self.fail('Original main must never be entered after a changed binding')
        self.assertIs(module.first, first); self.assertIs(module.second, foreign)
        self.assertNotIn(timing.PRIVATE_INVOKE, private)

    def test_hook_install_error_is_not_an_original_main_exception(self):
        module = types.ModuleType('owned'); module.fn = lambda: 1
        c = timing.TimingCollector(clock=Clock()); reports = []; calls = []
        bindings = timing.Bindings([(module, 'fn', lambda: 2)], [], c)
        module.fn = lambda: 3
        with self.assertRaises(AssertionError):
            timing.execute_original(lambda: calls.append(1), bindings, c, ['original'], reports.append)
        self.assertEqual(calls, [])
        self.assertIs(reports[0]['originalInvocation']['called'], False)
        self.assertIsNone(reports[0]['originalInvocation']['exceptionType'])
        self.assertEqual(reports[0]['instrumentationFailure']['phase'], 'hook-install')

    def test_hook_restore_error_preserves_normal_original_outcome(self):
        class BrokenRestore:
            def __enter__(self): return self
            def __exit__(self, *args): raise RuntimeError('restore')
        c = timing.TimingCollector(clock=Clock()); reports = []
        with self.assertRaises(RuntimeError):
            timing.execute_original(lambda: 0, BrokenRestore(), c, ['original'], reports.append)
        original = reports[0]['originalInvocation']
        self.assertTrue(original['called']); self.assertTrue(original['returned'])
        self.assertEqual(original['returnCode'], 0); self.assertIsNone(original['exceptionType'])
        self.assertEqual(reports[0]['instrumentationFailure']['phase'], 'hook-restore')

    def test_persistence_failure_after_return_is_not_a_false_success(self):
        c = timing.TimingCollector(clock=Clock())
        with self.assertRaises(OSError):
            timing.execute_original(lambda: 0, timing.Bindings([], [], c), c, ['original'], lambda report: (_ for _ in ()).throw(OSError('storage')))

    def test_original_main_called_once_argv_restored_and_all_false_qualification(self):
        c = timing.TimingCollector(clock=Clock()); calls = []; reports = []; argv = sys.argv
        def main(): calls.append(tuple(sys.argv)); return 1
        code = timing.execute_original(main, timing.Bindings([], [], c), c, ['original', '--output', 'fresh'], reports.append)
        self.assertEqual(code, 1); self.assertEqual(calls, [('original', '--output', 'fresh')]); self.assertIs(sys.argv, argv)
        self.assertEqual(reports[0]['originalInvocation']['returnCode'], 1)
        for key in ['success', 'productQualified', 'hostReadyQualified', 'officeReplacementCertified']:
            self.assertIs(reports[0][key], False)
        self.assertEqual(reports[0]['cases']['entered'], [0, 0, 0])

    def test_case_early_failure_does_not_invent_three_completed_cases(self):
        c = timing.TimingCollector(clock=Clock()); failure = AssertionError('first case')
        owner = types.SimpleNamespace(choice='save')
        def run(self): raise failure
        wrapped = timing.wrap_call(run, 0, c, context='case')
        with self.assertRaises(AssertionError) as raised: wrapped(owner)
        self.assertIs(raised.exception, failure)
        c.finish(); snap = c.snapshot()
        self.assertEqual(snap['cases']['entered'], [1, 0, 0]); self.assertEqual(snap['cases']['returned'], [0, 0, 0])
        self.assertEqual(snap['cases']['raised'], [1, 0, 0]); self.assertEqual(c.case, -1)


class SourceContractTests(unittest.TestCase):
    def test_real_private_bindings_compile_install_and_restore_without_running_cases(self):
        c = timing.TimingCollector(clock=Clock())
        original_main, bindings, proofs = timing.build_bindings(ROOT, c)
        self.assertEqual(original_main.__name__, 'main')
        self.assertEqual(len(bindings.changes), 13)
        self.assertEqual([p['callCount'] for p in proofs], [7, 6])
        with bindings:
            for owner, name, original, replacement in bindings.changes:
                self.assertIs(inspect.getattr_static(owner, name), replacement)
            for g in bindings.globals: self.assertIn(timing.PRIVATE_INVOKE, g)
        for owner, name, original, replacement in bindings.changes:
            self.assertIs(inspect.getattr_static(owner, name), original)
        for g in bindings.globals: self.assertNotIn(timing.PRIVATE_INVOKE, g)

    def test_all_production_source_pins_and_frozen_three_cases_are_current(self):
        proof = timing.verify_source_files(ROOT)
        self.assertEqual(len(proof), 11)
        for row in proof: self.assertIn('sha256', row)
        source = (ROOT / 'suite/e2e/calc_close_probe.py').read_text()
        self.assertIn("CHOICES=('save','discard','cancel')", source)
        self.assertIn('self.deadline=time.monotonic()+calc_model_barrier.MAX_SECONDS', source)
        self.assertIn("pause=.04,deadline=self.deadline", source)

    def test_changed_source_bytes_are_rejected_before_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in timing.SOURCE_PINS:
                p = root / relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes((ROOT / relative).read_bytes())
            target = root / 'suite/e2e/writer_model_reader.py'; target.write_bytes(target.read_bytes() + b'\n')
            with self.assertRaises(AssertionError): timing.verify_source_files(root)

    def test_exact_crlf_representation_allowed_mixed_representation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in timing.SOURCE_PINS:
                p = root / relative; p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes((ROOT / relative).read_bytes().replace(b'\n', b'\r\n'))
            rows = timing.verify_source_files(root)
            self.assertTrue(all(row['newlineRepresentation'] == 'CRLF' for row in rows))
            target = root / 'suite/e2e/calc_close_probe.py'
            target.write_bytes(target.read_bytes().replace(b'\r\n', b'\n', 1))
            with self.assertRaises(AssertionError): timing.verify_source_files(root)

    def binding_fixture(self, root, *, head='1'*40, tree='2'*40, dirty=False, changed_blob=None):
        for relative in timing.SOURCE_PINS:
            p = root / relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes((ROOT / relative).read_bytes())
        own = 'suite/e2e/calc_close_existing_call_timing.py'
        (root / own).write_bytes((ROOT / own).read_bytes())
        def git(root, *args):
            if args == ('rev-parse', 'HEAD'): return (head+'\n').encode()
            if args == ('rev-parse', 'HEAD^{tree}'): return (tree+'\n').encode()
            if args[0] == 'status': return b' M changed.py\n' if dirty else b''
            if args[0] == 'show':
                relative = args[1].split(':', 1)[1]
                raw = (root / relative).read_bytes()
                return raw+b'\n' if relative == changed_blob else raw
            self.fail('Unexpected local Git request: '+str(args))
        return git

    def test_source_head_and_actual_context_are_bound_without_environment_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); git = self.binding_fixture(root)
            environment = dict(GITHUB_ACTIONS='true', GITHUB_SHA='1'*40, GITHUB_WORKFLOW_SHA='1'*40,
                GITHUB_REF='refs/heads/synthetic-fixture', GITHUB_WORKFLOW_REF='synthetic-workflow')
            before = dict(environment)
            with patch.object(timing, '_git', git), patch.object(timing, 'os', types.SimpleNamespace(environ=environment)):
                bound = timing.source_binding(root)
            self.assertEqual(environment, before); self.assertEqual(bound['head'], '1'*40)
            self.assertFalse(bound['githubEnvironmentModified']); self.assertFalse(bound['mainNativePrivacySetupPerformed'])

    def test_wrong_missing_and_zero_actual_source_context_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); git = self.binding_fixture(root)
            for overrides in ({'GITHUB_SHA':'3'*40}, {'GITHUB_WORKFLOW_SHA':'0'*40}, {'GITHUB_SHA':None}, {'GITHUB_WORKFLOW_SHA':None}):
                with self.subTest(overrides=overrides):
                    environment = dict(GITHUB_ACTIONS='true', GITHUB_SHA='1'*40, GITHUB_WORKFLOW_SHA='1'*40)
                    environment.update(overrides)
                    with patch.object(timing, '_git', git), patch.object(timing, 'os', types.SimpleNamespace(environ=environment)):
                        with self.assertRaises(AssertionError): timing.source_binding(root)

    def test_dirty_zero_or_changed_committed_source_is_rejected(self):
        own = 'suite/e2e/calc_close_existing_call_timing.py'
        for options in ({'dirty':True}, {'head':'0'*40}, {'tree':'0'*40},
                {'changed_blob':'suite/e2e/writer_model_reader.py'}, {'changed_blob':own}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); git = self.binding_fixture(root, **options)
                with patch.object(timing, '_git', git), patch.object(timing, 'os', types.SimpleNamespace(environ={})):
                    with self.assertRaises(AssertionError): timing.source_binding(root)


if __name__ == '__main__': unittest.main()
