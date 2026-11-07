"""Real File-header geometry without an unused retained HWND query."""
import copy
import inspect
from pathlib import Path
import sys
import unittest

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
import test_native_menu_graph as graphs


class FileGeometryTests(unittest.TestCase):
    def fixture(self):
        owner = graphs.NativeMenuGraphTests(methodName='runTest')
        self.addCleanup(owner.doCleanups)
        return owner.fixture()

    def optional(self, probe, element):
        self.assertIn('include_native_hwnd', inspect.signature(probe._chrome).parameters,
            'File-only geometry must omit the unused HWND query explicitly')
        return probe._chrome(element, False)

    def trace(self, probe):
        calls = []
        original = probe._uia_call
        def query(code, function, *args):
            calls.append(code)
            return original(code, function, *args)
        probe._uia_call = query
        return calls

    def test_physical_header_does_not_read_the_retained_file_hwnd(self):
        module, probe, boundary, clock, binding, calls = self.fixture()
        retained = probe._identity_refs['file']
        original = boundary.Node.CurrentNativeWindowHandle.fget
        seen = []
        primary = RuntimeError('Synthetic unused retained File HWND access')
        def hwnd(node):
            seen.append(node)
            if node is retained:
                raise primary
            return original(node)
        boundary.Node.CurrentNativeWindowHandle = property(hwnd)
        try:
            fresh = probe._physical_base()
        except RuntimeError as error:
            if error is primary:
                self.fail('The unused retained File HWND query still ran')
            raise
        self.assertEqual(set(fresh), {'file', 'bar', 'peer', 'contrast-edit'})
        self.assertFalse(any(node is retained for node in seen))
        self.assertEqual([node.key for node in seen], ['file', 'bar', 'peer'])
        self.assertEqual(boundary.native.calls, [])
        proof = probe.interop['graphRefresh']
        self.assertTrue(proof['fileEqualsRetained'])
        self.assertTrue(proof['ownershipBefore'] and proof['ownershipAfter'])
        self.assertEqual(proof['physicalHit'], dict(hwnd=56, pid=88, threadId=9, rootHwnd=11))
        self.assertTrue(all(value is False for value in proof['differentFrom'].values()))

    def test_full_chrome_keeps_exact_query_order_and_result_keys(self):
        module, probe, boundary, clock, binding, calls = self.fixture()
        queries = self.trace(probe)
        row = probe._chrome(probe._identity_refs['file'])
        self.assertEqual(queries, [7, 3, 5, 5, 5, 5, 10, 9, 8, 11, 12])
        self.assertEqual(list(row), ['runtimeId', 'runtimeIdAvailable', 'runtimeObservation',
            'pid', 'nativeHwnd', 'controlType', 'visible', 'enabled', 'rectangle', 'identity'])
        self.assertEqual(row['nativeHwnd'], 0)

    def test_optional_geometry_omits_only_hwnd_call_and_key(self):
        module, probe, boundary, clock, binding, calls = self.fixture()
        queries = self.trace(probe)
        element = probe._identity_refs['file']
        full = probe._chrome(element)
        original_queries = list(queries)
        queries.clear()
        geometry = self.optional(probe, element)
        self.assertEqual(queries, original_queries[1:])
        self.assertNotIn('nativeHwnd', geometry)
        self.assertEqual(geometry, {key: value for key, value in full.items() if key != 'nativeHwnd'})

    def test_full_chrome_preserves_none_and_signed32_handle_values(self):
        for raw, expected in ((None, 0), (0, 0), (-1, 0xffffffff), (-2**31, 2**31), (2**32-1, 2**32-1)):
            with self.subTest(rawKind=type(raw).__name__, expected=expected):
                module, probe, boundary, clock, binding, calls = self.fixture()
                reads = []
                boundary.Node.CurrentNativeWindowHandle = property(lambda node: reads.append(1) or raw)
                row = probe._chrome(probe._identity_refs['file'])
                self.assertEqual((row['nativeHwnd'], len(reads)), (expected, 1))

    def test_full_chrome_still_rejects_invalid_handle_shapes_before_later_queries(self):
        for raw in (True, 'invalid', 1.5, -2**31-1, 2**32):
            with self.subTest(rawKind=type(raw).__name__):
                module, probe, boundary, clock, binding, calls = self.fixture()
                boundary.Node.CurrentNativeWindowHandle = property(lambda node: raw)
                queries = self.trace(probe)
                with self.assertRaises(AssertionError):
                    probe._chrome(probe._identity_refs['file'])
                self.assertEqual(queries, [7])

    def test_full_chrome_propagates_the_original_hwnd_exception_once(self):
        module, probe, boundary, clock, binding, calls = self.fixture()
        primary = KeyboardInterrupt()
        reads = []
        def hwnd(node):
            reads.append(1)
            raise primary
        boundary.Node.CurrentNativeWindowHandle = property(hwnd)
        with self.assertRaises(KeyboardInterrupt) as caught:
            probe._chrome(probe._identity_refs['file'])
        self.assertTrue(caught.exception is primary)
        self.assertEqual(reads, [1])

    def test_optional_geometry_preserves_runtime_and_role_rejections(self):
        for damage in ('runtime', 'scope', 'metadata', 'role'):
            with self.subTest(damage=damage):
                module, probe, boundary, clock, binding, calls = self.fixture()
                element = probe._identity_refs['file']
                if damage == 'runtime':
                    boundary.Node.GetRuntimeId = lambda node: [True]
                elif damage == 'scope':
                    probe._identity_scope = None
                elif damage == 'metadata':
                    boundary.interface._methods_[0].paramflags = ((2, 'runtimeId'),)
                else:
                    probe.uia.iuia.CompareElements = lambda left, right: False
                self.assertIn('include_native_hwnd', inspect.signature(probe._chrome).parameters)
                with self.assertRaises(AssertionError):
                    probe._chrome(element, False)

    def test_physical_header_still_rejects_pid_type_visibility_enabled_and_geometry(self):
        for damage in ('pid', 'type', 'offscreen', 'disabled', 'empty'):
            with self.subTest(damage=damage):
                module, probe, boundary, clock, binding, calls = self.fixture()
                retained = probe._identity_refs['file']
                property_name = {'pid': 'CurrentProcessId', 'type': 'CurrentControlType',
                    'offscreen': 'CurrentIsOffscreen', 'disabled': 'CurrentIsEnabled',
                    'empty': 'CurrentBoundingRectangle'}[damage]
                original = getattr(boundary.Node, property_name).fget
                def value(node):
                    result = original(node)
                    if node is not retained:
                        return result
                    if damage == 'empty':
                        result.right = result.left
                        return result
                    return {'pid': 999, 'type': 50010, 'offscreen': True, 'disabled': False}[damage]
                setattr(boundary.Node, property_name, property(value))
                reached = []
                probe.uia.iuia.ElementFromPoint = lambda point: reached.append(1) or boundary.Node('file')
                with self.assertRaises(AssertionError):
                    probe._physical_base()
                self.assertEqual(reached, [])

    def test_fresh_file_mismatch_and_role_alias_remain_rejected(self):
        for damage in ('fresh-file', 'alias'):
            with self.subTest(damage=damage):
                module, probe, boundary, clock, binding, calls = self.fixture()
                if damage == 'fresh-file':
                    probe.uia.iuia.ElementFromPoint = lambda point: boundary.Node('edit')
                else:
                    retained = probe._identity_refs['file']
                    compare = boundary.compare
                    probe.uia.iuia.CompareElements = lambda left, right: (
                        True if left is not retained and left.key == 'file' and right.key == 'edit'
                        else compare(left, right))
                with self.assertRaises(AssertionError):
                    probe._physical_base()

    def test_live_bar_peer_and_peer_hwnd_checks_remain_required(self):
        for damage in ('bar', 'peer', 'peer-hwnd'):
            with self.subTest(damage=damage):
                module, probe, boundary, clock, binding, calls = self.fixture()
                parent = boundary.parent
                if damage == 'bar':
                    probe.uia.iuia.ControlViewWalker.GetParentElement = lambda node: (
                        boundary.Node('edit') if node.key == 'file' else parent(node))
                elif damage == 'peer':
                    probe.uia.iuia.ControlViewWalker.GetParentElement = lambda node: (
                        boundary.Node('host') if node.key == 'bar' else parent(node))
                else:
                    original = boundary.Node.CurrentNativeWindowHandle.fget
                    boundary.Node.CurrentNativeWindowHandle = property(lambda node: 57 if node.key == 'peer' else original(node))
                with self.assertRaises(AssertionError):
                    probe._physical_base()

    def test_intermediate_ancestor_still_requires_zero_hwnd(self):
        for handle in (0, 95):
            with self.subTest(handle=handle):
                module, probe, boundary, clock, binding, calls = self.fixture()
                parent = boundary.parent
                probe.uia.iuia.ControlViewWalker.GetParentElement = lambda node: (
                    boundary.Node('bridge') if node.key == 'bar' else boundary.Node('peer')
                    if node.key == 'bridge' else parent(node))
                kind = boundary.Node.CurrentControlType.fget
                hwnd = boundary.Node.CurrentNativeWindowHandle.fget
                boundary.Node.CurrentControlType = property(lambda node: 50033 if node.key == 'bridge' else kind(node))
                boundary.Node.CurrentNativeWindowHandle = property(lambda node: handle if node.key == 'bridge' else hwnd(node))
                if handle:
                    with self.assertRaises(AssertionError):
                        probe._physical_base()
                else:
                    self.assertEqual(set(probe._physical_base()), {'file', 'bar', 'peer', 'contrast-edit'})

    def test_scope_foreground_and_original_deadline_changes_still_block(self):
        for damage in ('attachment', 'foreground', 'late'):
            with self.subTest(damage=damage):
                module, probe, boundary, clock, binding, calls = self.fixture()
                if damage == 'attachment':
                    probe.attachment_snapshot = lambda binding: dict(valid=False)
                elif damage == 'foreground':
                    probe.foreground = lambda: 99
                else:
                    point = probe.uia.iuia.ElementFromPoint
                    probe.uia.iuia.ElementFromPoint = lambda value: setattr(clock, 'now', 6.) or point(value)
                with self.assertRaises(AssertionError):
                    probe._physical_base()
                self.assertEqual(boundary.native.calls, [])

    def test_full_snapshot_hwnd_still_changes_the_eight_part_stability_binding(self):
        module, probe, boundary, clock, binding, calls = self.fixture()
        snapshot = boundary.native.snapshot(binding, 'save')
        first = module._validate(snapshot, binding, 77, 'save')
        self.assertEqual((len(first), first[1]), (8, 99))
        changed = copy.deepcopy(snapshot)
        changed['control']['nativeHwnd'] = 100
        second = module._validate(changed, binding, 77, 'save')
        self.assertNotEqual(first, second)
        changed = copy.deepcopy(snapshot)
        changed['ancestry'][-1]['nativeHwnd'] = 57
        with self.assertRaises(AssertionError):
            module._validate(changed, binding, 77, 'save')


if __name__ == '__main__':
    unittest.main()
