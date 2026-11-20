import ast
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

TARGET_E2E = Path(__file__).resolve().parents[1]
KEY = 'SYNTHETIC_TARGET_KEY'
OTHER = 'SYNTHETIC_OTHER_KEY'


class Poison(Exception):
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


class EnvironmentSentinel:
    def __getattribute__(self, name):
        raise AssertionError()


def load_policy():
    tree = ast.parse((TARGET_E2E / 'native_document_policy.py').read_bytes())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('require_focus_map', 'double_checked_action', 'focus_map_failure_observation')]
    module = types.ModuleType('_focus_policy_under_test')
    module.copy = copy
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<synthetic-policy>', 'exec'), module.__dict__)
    return module


def sample(target=False, other=True):
    return [{'pageKey': KEY, 'focused': target}, {'pageKey': OTHER, 'focused': other}]


def exercise(sequence, *, helper_failure=False, writer_failure=False):
    policy = load_policy()
    tree = ast.parse((TARGET_E2E / 'native_document_windows.py').read_bytes())
    method = next(x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef) and x.name == 'prepare')
    primary = Poison('synthetic-secret')
    calls, records, seen_rows = [], [], []
    index = 0

    def focus_rows():
        nonlocal index
        calls.append('query')
        value = sequence[index]
        index += 1
        if isinstance(value, Exception):
            raise value
        return value

    def guarded(key, rows):
        calls.append('guard')
        seen_rows.append(rows)
        return policy.require_focus_map(key, rows)

    def until(predicate, *, timeout, pump):
        if timeout != 10:
            raise AssertionError()
        for number in range(len(sequence)):
            try:
                value = predicate()
            except Exception:
                if number + 1 < len(sequence):
                    pump(0.05)
                    continue
                raise primary
            if value:
                return value
        raise primary

    def record(operation, value):
        calls.append('record')
        if operation == 'focus-map-failure-numeric' and writer_failure:
            raise KeyboardInterrupt()
        records.append((operation, value))

    def point():
        calls.append('point')
        return {'point': [1, 2]}

    def ready():
        calls.append('ready')
        return 123

    wrapper = types.SimpleNamespace(set_focus=lambda: calls.append('set-focus'))
    desktop = types.SimpleNamespace(window=lambda **unused: types.SimpleNamespace(wrapper_object=lambda: wrapper))
    owner = types.SimpleNamespace(desktop=desktop, _focus_rows=focus_rows, _record=record)
    bound = types.SimpleNamespace(owner=owner, key=KEY, hwnd=12, page=types.SimpleNamespace(wait_for_timeout=lambda value: calls.append('pump')), _editor=lambda: calls.append('editor'), _point_observation=point, _ready=ready)
    mouse = types.SimpleNamespace(click=lambda **unused: calls.append('click'))
    driver = types.ModuleType('driver');driver.until = until
    pywinauto = types.ModuleType('pywinauto');pywinauto.mouse = mouse
    namespace = {'double_checked_action': policy.double_checked_action, 'require_focus_map': guarded}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<synthetic-prepare>', 'exec'), namespace)
    error = result = None
    helper_calls = []
    original_helper = getattr(policy, 'focus_map_failure_observation', None)

    def observed(*args):
        helper_calls.append(1)
        if helper_failure:
            raise KeyboardInterrupt()
        return original_helper(*args)

    output = io.StringIO()
    with mock.patch.object(os, 'environ', EnvironmentSentinel()), mock.patch.dict(sys.modules, {'driver': driver, 'pywinauto': pywinauto, 'native_document_policy': policy}), mock.patch.object(policy, 'focus_map_failure_observation', observed, create=True), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        try:
            result = namespace['prepare'](bound)
        except BaseException as caught:
            error = caught
    return types.SimpleNamespace(primary=primary, error=error, result=result, calls=calls, records=records, seen_rows=seen_rows, helper_calls=helper_calls, output=output.getvalue())


class FocusEntryTests(unittest.TestCase):
    def setUp(self):
        Poison.reads = []

    def diagnostic(self, result):
        records = [value for operation, value in result.records if operation == 'focus-map-failure-numeric']
        self.assertEqual(len(records), 1)
        value = records[0]
        self.assertEqual(set(value), {'schemaVersion', 'diagnosticOnly', 'acceptanceEligible', 'readCount', 'evaluationCompleted', 'countsKnown', 'unknown', 'unknownCode', 'targetFocused', 'otherFocusedCount', 'focusedCount'})
        self.assertEqual((value['schemaVersion'], value['diagnosticOnly'], value['acceptanceEligible']), (1, 1, 0))
        serialized = json.dumps(value)
        self.assertNotIn(KEY, serialized)
        self.assertNotIn(OTHER, serialized)
        self.assertNotIn('synthetic-secret', serialized)
        return value

    def test_negative_retains_final_snapshot_and_original_primary(self):
        result = exercise([sample(True, True), sample(False, True)])
        self.assertIs(result.error, result.primary)
        value = self.diagnostic(result)
        self.assertEqual((value['readCount'], value['evaluationCompleted'], value['countsKnown']), (2, True, True))
        self.assertEqual((value['targetFocused'], value['otherFocusedCount'], value['focusedCount']), (False, 1, 1))
        self.assertEqual(Poison.reads, [])
        self.assertEqual(result.output, '')

    def test_success_adds_no_observer_or_write_or_query(self):
        rows = sample(True, False)
        result = exercise([rows])
        self.assertIsNone(result.error)
        self.assertEqual(result.result, 123)
        self.assertEqual(result.helper_calls, [])
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.calls.count('query'), 1)
        self.assertEqual(result.calls.count('guard'), 1)
        self.assertEqual(result.calls.count('click'), 1)
        self.assertEqual(result.calls.count('point'), 2)

    def test_final_producer_failure_cannot_report_stale_rows(self):
        result = exercise([sample(False, True), RuntimeError()])
        self.assertIs(result.error, result.primary)
        value = self.diagnostic(result)
        self.assertEqual((value['readCount'], value['evaluationCompleted'], value['countsKnown'], value['unknownCode']), (2, False, False, 1))
        self.assertEqual((value['targetFocused'], value['otherFocusedCount'], value['focusedCount']), (None, None, None))

    def test_invalid_current_snapshot_is_unknown(self):
        result = exercise([[{'pageKey': KEY, 'focused': Poison('synthetic-secret')} ]])
        self.assertIs(result.error, result.primary)
        value = self.diagnostic(result)
        self.assertEqual((value['evaluationCompleted'], value['countsKnown'], value['unknownCode']), (True, False, 2))
        self.assertIsNone(value['targetFocused'])
        self.assertEqual(Poison.reads, [])

    def test_helper_or_writer_baseexception_cannot_mask_primary(self):
        for helper_failure, writer_failure in [(True, False), (False, True)]:
            with self.subTest(helper=helper_failure):
                result = exercise([sample()], helper_failure=helper_failure, writer_failure=writer_failure)
                self.assertIs(result.error, result.primary)
                self.assertEqual(result.helper_calls, [1])
                self.assertEqual(result.output, '')
        self.assertEqual(Poison.reads, [])

    def test_original_guard_order_and_rows_identity(self):
        first, last = sample(True, True), sample(False, True)
        result = exercise([first, last])
        self.diagnostic(result)
        self.assertIs(result.seen_rows[0], first)
        self.assertIs(result.seen_rows[1], last)
        self.assertEqual(result.calls, ['editor', 'set-focus', 'point', 'point', 'click', 'record', 'query', 'guard', 'pump', 'query', 'guard', 'record'])


class FocusNumericTests(unittest.TestCase):
    def setUp(self):
        self.function = load_policy().focus_map_failure_observation

    def observe(self, key=KEY, rows=None, count=1, complete=True):
        with mock.patch.object(os, 'environ', EnvironmentSentinel()):
            return self.function(key, sample() if rows is None else rows, count, complete)

    def test_positive_and_negative_counts(self):
        for target, other in [(True, False), (False, False), (False, True), (True, True)]:
            value = self.observe(rows=sample(target, other))
            self.assertEqual((value['targetFocused'], value['otherFocusedCount'], value['focusedCount']), (target, int(other), int(target) + int(other)))
            self.assertEqual((value['countsKnown'], value['unknown']), (True, 0))

    def test_invalid_shapes_are_null_and_bounded(self):
        for rows in [[], sample() * 17, [{'pageKey': KEY, 'focused': 1}], [{'pageKey': KEY, 'focused': False, 'document': Poison()}], [{'pageKey': OTHER, 'focused': True}], sample() + [sample()[0]]]:
            value = self.observe(rows=rows)
            self.assertFalse(value['countsKnown'])
            self.assertEqual((value['targetFocused'], value['otherFocusedCount'], value['focusedCount']), (None, None, None))

    def test_exact_builtin_types_avoid_custom_hash_repr(self):
        class KeyPoison:
            blocked = False
            def __hash__(self):
                if self.blocked:
                    raise AssertionError()
                return 1
            def __repr__(self):
                raise AssertionError()
        key = KeyPoison();rows = [{key: False, 'focused': True}];key.blocked = True
        self.assertFalse(self.observe(rows=rows)['countsKnown'])
        class StringPoison(str):
            def __eq__(self, other):
                raise AssertionError()
            def __hash__(self):
                raise AssertionError()
            def __repr__(self):
                raise AssertionError()
        self.assertFalse(self.observe(key=StringPoison(KEY))['countsKnown'])
        self.assertFalse(self.observe(rows=[{'pageKey': StringPoison(KEY), 'focused': True}])['countsKnown'])

    def test_incomplete_evaluation_is_never_stale(self):
        value = self.observe(rows=sample(True, False), count=2, complete=False)
        self.assertEqual((value['evaluationCompleted'], value['unknownCode']), (False, 1))
        self.assertIsNone(value['targetFocused'])

    def test_read_count_is_closed_numeric(self):
        for count in [Poison(), True, -1, 2147483648]:
            value = self.observe(count=count)
            self.assertEqual((value['readCount'], value['countsKnown'], value['unknownCode']), (0, False, 4))
        self.assertEqual(self.observe(count=2147483647)['readCount'], 2147483647)

    def test_does_not_mutate_rows_or_persist_strings(self):
        rows = sample(True, True)
        expected = sample(True, True)
        value = self.observe(rows=rows)
        self.assertEqual(rows, expected)
        self.assertTrue(all(item is None or type(item) in (int, bool) for item in value.values()))
        self.assertNotIn(KEY, json.dumps(value))

    def test_helper_has_no_io_environment_or_repr_calls(self):
        tree = ast.parse((TARGET_E2E / 'native_document_policy.py').read_bytes())
        function = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == 'focus_map_failure_observation')
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {'repr', 'str', 'hash', 'vars', 'locals', 'globals', 'open', 'getattr', 'print'})
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {'environ', 'argv', 'args', 'f_locals', 'co_filename'})


if __name__ == '__main__':
    unittest.main()
