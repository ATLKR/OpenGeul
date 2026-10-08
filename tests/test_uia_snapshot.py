"""A native UI tree may disappear during a read; input actions are never retried."""
import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self): self.now = 0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Tree:
    def __init__(self, *observations):
        self.observations = list(observations)
        self.calls = []
    def descendants(self, **filters):
        self.calls.append(filters)
        value = self.observations.pop(0) if len(self.observations) > 1 else self.observations[0]
        if isinstance(value, BaseException): raise value
        return value


class SnapshotTests(unittest.TestCase):
    def module(self):
        path = ROOT / 'e2e/uia_snapshot.py'
        self.assertTrue(path.is_file(), 'Missing read-only stale UI snapshot boundary')
        spec = importlib.util.spec_from_file_location('snapshot_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.time = Clock()
        return module

    def test_observed_missing_wrapper_type_is_read_again_without_input(self):
        module = self.module(); expected = [object()]
        tree = Tree(KeyError(None), expected)
        self.assertIs(module.snapshot_descendants(tree), expected)
        self.assertEqual(len(tree.calls), 2)

    def test_other_keyerrors_are_not_swallowed(self):
        module = self.module()
        for key in ('ComboBox', 'None', 0):
            tree = Tree(KeyError(key), [])
            with self.assertRaises(KeyError): module.snapshot_descendants(tree)
            self.assertEqual(len(tree.calls), 1)

    def test_empty_tree_remains_empty_not_an_invented_control(self):
        module = self.module(); tree = Tree([])
        self.assertEqual(module.snapshot_descendants(tree), [])
        self.assertEqual(len(tree.calls), 1)

    def test_filters_remain_scoped_to_the_same_tree(self):
        module = self.module(); tree = Tree(KeyError(None), [])
        module.snapshot_descendants(tree, control_type='RadioButton')
        self.assertEqual(tree.calls, [{'control_type': 'RadioButton'}] * 2)

    def test_permanently_unavailable_tree_fails_with_original_cause(self):
        module = self.module(); tree = Tree(KeyError(None))
        with self.assertRaises(AssertionError) as caught: module.snapshot_descendants(tree)
        self.assertIsInstance(caught.exception.__cause__, KeyError)
        self.assertLessEqual(module.time.now, 5.2)

    def test_unrelated_runtime_failure_is_not_retried(self):
        module = self.module(); tree = Tree(PermissionError('Access denied'), [])
        with self.assertRaises(PermissionError): module.snapshot_descendants(tree)
        self.assertEqual(len(tree.calls), 1)

    def test_helper_cannot_dispatch_or_retry_actions(self):
        self.module()
        code = ast.parse((ROOT / 'e2e/uia_snapshot.py').read_text())
        names = {n.attr for n in ast.walk(code) if isinstance(n, ast.Attribute)}
        self.assertFalse(names & {'Invoke', 'Expand', 'Select', 'click_input', 'set_edit_text', 'send_keys'})

    def test_real_rows_path_recovers_observed_enumeration_failure(self):
        path = ROOT / 'e2e/preview_settings.py'
        spec = importlib.util.spec_from_file_location('rows_test', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'print_focus': types.SimpleNamespace(_node=lambda c: {'type': 'Button'})}), \
                patch.object(sys, 'path', [str(ROOT / 'e2e'), *sys.path]):
            spec.loader.exec_module(module)
            controls = [object()]; tree = Tree(KeyError(None), controls)
            observed, nodes = module.rows(tree)
        self.assertIs(observed, controls)
        self.assertEqual(nodes, [{'type': 'Button'}])
        self.assertEqual(len(tree.calls), 2)

    def test_preview_enumerations_all_use_the_read_boundary(self):
        for name in ('preview_settings.py',):
            path = ROOT / 'e2e' / name
            self.assertTrue(path.is_file())
            code = path.read_text()
            self.assertNotIn('preview.descendants(', code)
            self.assertNotIn("previews[0].descendants(", code)


if __name__ == '__main__': unittest.main()
