"""Real source verification failures retain closed numeric traceback locations."""
import ast
import importlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'suite/e2e'))
from suite.tests import test_native_menu_source_selection as fixtures


class Clock:
    def __init__(self):
        self.now, self.calls = 1000., 0

    def __call__(self):
        self.calls += 1
        return self.now


class NoPayloadRead:
    def __repr__(self):
        raise AssertionError('Exception payload representation was read')

    __str__ = __repr__


class SourceFailureFrameTests(unittest.TestCase):
    def setUp(self):
        self.codec = importlib.import_module('numeric_notice')
        self.selection = importlib.import_module('native_menu_source_selection')
        self.gate = self.selection.gate
        self.owned = importlib.import_module('owned_native_menu')

    def test_source_file_ids_append_without_changing_the_historical_ids(self):
        self.assertEqual(tuple(self.codec.SOURCE_FILES.items())[37:38],
            (('owned_native_menu.py', 38),))
        self.assertEqual(tuple(self.codec.SOURCE_FILES.items())[38:], (
            ('native_menu_source_selection.py', 39),
            ('native_menu_source_admission.py', 40)))
        for code in (39, 40):
            failure = dict(captured=1, exceptionCode=7, fileCode=code, line=1)
            self.assertEqual(self.codec.validate_failure_code(failure), failure)
            self.assertEqual(self.codec.validate_failure_frames([[code, 1]]), [[code, 1]])
        for invalid in ([[41, 1]], [[True, 1]], [[39, 0]], [[39, 1, 2]]):
            with self.subTest(shape='invalid'), self.assertRaises(ValueError):
                self.codec.validate_failure_frames(invalid)

    def source_case(self):
        fixture = fixtures.SourceMenuSelectionTests(
            methodName='test_first_probe_rechecks_inventory_executables_providers_and_pending')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        prepared = fixture.prepared()
        selected = fixture.selected(prepared)
        return fixture.launch(selected), selected

    def verify_epoch_lines(self):
        source = Path(self.selection.__file__).read_text(encoding='utf-8')
        function = next(node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == '_verify_runtime')
        return [node.lineno for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == '_unchanged_epochs']

    def source_failure(self, phase, *, capture_error=False):
        process, selected = self.source_case()
        clock, calls, originals, primary, capture_count = Clock(), [], {}, [], []
        record = {}
        payload_calls = 0
        for name in ('_payload_epoch',):
            originals[name] = getattr(self.selection, name)
        originals['_hash_file'] = self.gate._hash_file
        original_provider = self.gate.SourceMenuAdmission.verify_provider_files
        original_capture = self.codec.capture_failure_frames

        def expire(function, *args, **kwargs):
            clock.now = 1005.
            try:
                return function(*args, **kwargs)
            except ValueError as failure:
                failure.args = (NoPayloadRead(),)
                primary.append((failure, failure.args, failure.__traceback__))
                raise

        def payload(*args, **kwargs):
            nonlocal payload_calls
            payload_calls += 1
            calls.append(('payload', payload_calls))
            if (phase == 'first-payload' and payload_calls == 1
                    or phase == 'second-payload' and payload_calls == 2):
                return expire(originals['_payload_epoch'], *args, **kwargs)
            return originals['_payload_epoch'](*args, **kwargs)

        def hashed(*args, **kwargs):
            calls.append(('hash',))
            if phase == 'anchor':
                return expire(originals['_hash_file'], *args, **kwargs)
            return originals['_hash_file'](*args, **kwargs)

        def provider(admission, *args, **kwargs):
            calls.append(('provider',))
            if phase == 'provider':
                return expire(original_provider, admission, *args, **kwargs)
            return original_provider(admission, *args, **kwargs)

        def capture(failure):
            self.assertIs(failure, primary[0][0])
            before = (failure.__traceback__, failure.args, clock.calls, tuple(calls))
            capture_count.append(1)
            if capture_error:
                raise RuntimeError('Synthetic frame capture failure')
            result = original_capture(failure)
            self.assertIs(failure.__traceback__, before[0])
            self.assertIs(failure.args, before[1])
            self.assertEqual((clock.calls, tuple(calls)), before[2:])
            return result

        with patch.object(self.selection, '_payload_epoch', payload), \
                patch.object(self.gate, '_hash_file', hashed), \
                patch.object(self.gate.SourceMenuAdmission, 'verify_provider_files', provider), \
                patch.object(self.selection.time, 'monotonic', clock), \
                patch.object(os, 'environ', {'SOURCE_FRAME_TEST_ONLY': '1'}), \
                patch.object(self.codec, 'capture_failure_frames', capture), \
                patch.object(self.owned, 'NativeMenuProbe', side_effect=AssertionError(
                    'Failed source verification must precede probe construction')) as build:
            caught = None
            try:
                self.owned.inspect_native_menu(SimpleNamespace(), process, 11, record,
                    'open-escape', clock=clock)
            except ValueError as failure:
                caught = failure
            else:
                self.fail('Actual source deadline did not reject before probe construction')
        self.assertEqual(len(primary), 1)
        self.assertIs(caught, primary[0][0])
        self.assertIs(caught.args, primary[0][1])
        trace = caught.__traceback__
        while trace is not None and trace is not primary[0][2]:
            trace = trace.tb_next
        self.assertIs(trace, primary[0][2])
        build.assert_not_called()
        action, = record['nativeMenuActions']
        self.assertFalse(action['success'])
        self.assertEqual((action['startedAt'], action['deadline'], action['finishedAt']),
            (1000., 1005., 1005.))
        self.assertEqual((action['pointers'], action['keys'], action['dpiScope']), ([], [], {}))
        self.assertNotIn('uiaInterop', action)
        self.assertEqual(action['numericFailure']['exceptionCode'], 7)
        self.assertEqual(capture_count, [1])
        self.assertNotIn('SOURCE_FRAME_TEST_ONLY', json.dumps(action))
        if capture_error:
            self.assertNotIn('numericFailureFrames', action)
            self.assertEqual(action['numericFailureFramesCaptureFailed'], 1)
        else:
            self.assertIn('numericFailureFrames', action)
            frames = self.codec.validate_failure_frames(action['numericFailureFrames'])
            self.assertEqual(frames[-1], [action['numericFailure']['fileCode'],
                action['numericFailure']['line']])
            self.assertTrue(all(code in (38, 39, 40) for code, _ in frames))
        return action, calls

    def test_actual_first_payload_deadline_retains_its_first_epoch_chain(self):
        action, calls = self.source_failure('first-payload')
        self.assertIn([39, self.verify_epoch_lines()[0]], action['numericFailureFrames'])
        self.assertNotIn([39, self.verify_epoch_lines()[1]], action['numericFailureFrames'])
        self.assertEqual(calls, [('payload', 1)])

    def test_actual_anchor_deadline_retains_the_hash_chain(self):
        action, calls = self.source_failure('anchor')
        self.assertEqual(action['numericFailure']['fileCode'], 40)
        self.assertEqual(calls, [('payload', 1), ('hash',)])

    def test_actual_provider_deadline_is_distinct_from_an_anchor_hash(self):
        action, calls = self.source_failure('provider')
        self.assertEqual(action['numericFailure']['fileCode'], 40)
        self.assertEqual(calls, [('payload', 1)] + [('hash',)]*7 + [('provider',)])
        provider_line = self.gate.SourceMenuAdmission.verify_provider_files.__code__.co_firstlineno
        self.assertTrue(any(code == 40 and provider_line <= line < provider_line+13
            for code, line in action['numericFailureFrames']))

    def test_actual_second_payload_deadline_retains_its_second_epoch_chain(self):
        action, calls = self.source_failure('second-payload')
        self.assertIn([39, self.verify_epoch_lines()[1]], action['numericFailureFrames'])
        self.assertNotIn([39, self.verify_epoch_lines()[0]], action['numericFailureFrames'])
        self.assertEqual(calls, [('payload', 1)] + [('hash',)]*7 + [('provider',)]
            + [('hash',)]*2 + [('payload', 2)])

    def test_capture_failure_cannot_replace_the_actual_source_exception(self):
        self.source_failure('first-payload', capture_error=True)

    def test_numeric_capture_keeps_existing_limits_and_excludes_foreign_frames(self):
        source = Path(self.codec.__file__).with_name('native_menu_source_selection.py')
        scope = {'payload': NoPayloadRead()}
        exec(compile('def recurse(n):\n if n: return recurse(n-1)\n raise ValueError(payload)\n',
            str(source), 'exec'), scope)
        try:
            scope['recurse'](100)
        except ValueError as failure:
            frames = self.codec.capture_failure_frames(failure)
            self.assertEqual(frames, [[39, 2]]*8)
        else:
            self.fail('Synthetic owned recursion did not fail')
        foreign = {}
        exec(compile('def fail():\n raise ValueError()\n', 'FOREIGN_SYNTHETIC.py', 'exec'), foreign)
        try:
            foreign['fail']()
        except ValueError as failure:
            self.assertEqual(self.codec.capture_failure_frames(failure), [])
        else:
            self.fail('Synthetic foreign failure did not run')


if __name__ == '__main__':
    unittest.main()
