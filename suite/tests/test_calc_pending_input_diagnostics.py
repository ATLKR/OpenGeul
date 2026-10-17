"""Partial native-accessibility failure evidence; no Windows execution is claimed."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from suite.tests import test_calc_pending_input as fixtures

Accessible = fixtures.Accessible


class PendingFailureDiagnosticsTests(unittest.TestCase):
    # Reuse only the synthetic UNO fixture; its oracle tests run separately.
    setUp = fixtures.PendingInputTests.setUp

    def reader(self):
        value = fixtures.PendingInputTests.reader(self)
        value.deadline, value.clock = 100.0, lambda: 1.0
        return value

    def broken_branch(self, depth=11, *, wrong_parent=True):
        leaf = Accessible(57, 'Notebook toolbar item', rectangle=(22, 23, 44, 45))
        node = leaf
        for _ in range(depth - 1):
            node = Accessible(40, children=[node])
        self.root.set_children([node])
        leaf.parent = self.root if wrong_parent else leaf.parent
        leaf.index = 99
        return leaf

    def fail_read(self, reader):
        with self.assertRaisesRegex(AssertionError, 'actual parent/index reciprocity failed') as raised:
            reader.read()
        diagnostic = getattr(raised.exception, 'pending_input_diagnostic', None)
        self.assertIsInstance(diagnostic, dict, 'The original failing read must retain partial accessibility evidence')
        self.assertIs(diagnostic, reader.last_diagnostic)
        self.assertFalse(diagnostic['qualified'])
        self.assertEqual(diagnostic['primaryError']['message'], str(raised.exception))
        return diagnostic

    def test_depth_eleven_failure_preserves_actual_node_parent_index_role_name_and_geometry(self):
        self.broken_branch()
        diagnostic = self.fail_read(self.reader())
        self.assertEqual(diagnostic['failedNode']['indexPath'], [0] * 11)
        self.assertEqual(diagnostic['failedNode']['parentIndexPath'], [0] * 10)
        self.assertFalse(diagnostic['failedNode']['observedParentMatchesExpected'])
        self.assertEqual(diagnostic['failedNode']['observedIndexInParent'], 99)
        self.assertEqual(diagnostic['failedNode']['expectedIndexInParent'], 0)
        self.assertEqual(diagnostic['failedNode']['description']['role'], 57)
        self.assertEqual(diagnostic['failedNode']['description']['name'], 'Notebook toolbar item')
        self.assertEqual(diagnostic['failedNode']['description']['rectangle'], [22, 23, 44, 45])
        self.assertEqual(diagnostic['actualParent']['knownIndexPaths'], [[]])
        self.assertEqual(len(diagnostic['nodes']), 12)
        json.dumps(diagnostic, allow_nan=False)

    def test_wrong_index_with_the_correct_parent_remains_an_original_failure(self):
        self.broken_branch(wrong_parent=False)
        diagnostic = self.fail_read(self.reader())
        self.assertTrue(diagnostic['failedNode']['observedParentMatchesExpected'])
        self.assertEqual(diagnostic['failedNode']['observedIndexInParent'], 99)
        self.assertEqual(diagnostic['phase'], 'parent-index-reciprocity')

    def test_optional_diagnostic_getter_error_cannot_replace_the_original_failure(self):
        leaf = self.broken_branch()
        leaf.getAccessibleName = lambda: (_ for _ in ()).throw(RuntimeError('diagnostic name unavailable'))
        diagnostic = self.fail_read(self.reader())
        self.assertEqual(diagnostic['failedNode']['description']['rectangle'], [22, 23, 44, 45])
        self.assertEqual(diagnostic['failedNode']['description']['errors'][0]['operation'], 'getAccessibleName')
        self.assertEqual(diagnostic['primaryError']['type'], 'AssertionError')

    def test_bad_parent_still_raises_original_assertion_if_optional_index_getter_throws(self):
        leaf = self.broken_branch()
        leaf.getAccessibleIndexInParent = lambda: (_ for _ in ()).throw(RuntimeError('optional index unavailable'))
        try:
            self.reader().read()
        except BaseException as exc:
            self.assertIsInstance(exc, AssertionError, 'Collecting the index must not replace the original bad-parent assertion')
            self.assertEqual(str(exc), 'Pending-input actual parent/index reciprocity failed')
            diagnostic = exc.pending_input_diagnostic
            self.assertEqual(diagnostic['failedNode']['description']['errors'][0]['operation'], 'getAccessibleIndexInParent')
        else:
            self.fail('A bad parent must remain rejected')

    def test_failed_node_uses_the_already_observed_context_without_refetching_it(self):
        leaf = self.broken_branch()
        calls = []
        def context():
            calls.append('context')
            if len(calls) > 1:
                raise RuntimeError('The original context must not be refetched')
            return leaf
        leaf.getAccessibleContext = context
        diagnostic = self.fail_read(self.reader())
        self.assertEqual(calls, ['context'])
        self.assertEqual(diagnostic['failedNode']['description']['name'], leaf.name)

    def test_final_reciprocity_failure_preserves_its_original_assertion(self):
        self.document.set_children([self.table, self.editor])
        calls = []
        def index():
            calls.append('index')
            return 1 if len(calls) == 1 else 99
        self.editor.getAccessibleIndexInParent = index
        with self.assertRaisesRegex(AssertionError, '^Accessible identity/path changed during pending-input read$'):
            self.reader().read()

    def test_expired_original_deadline_prevents_optional_remote_diagnostic_getters(self):
        leaf = self.broken_branch()
        leaf.getAccessibleName = lambda: self.fail('Expired diagnostics must not issue another name getter')
        leaf.getLocationOnScreen = lambda: self.fail('Expired diagnostics must not issue another geometry getter')
        reader = self.reader(); reader.clock = lambda: 100.0
        diagnostic = self.fail_read(reader)
        self.assertTrue(diagnostic['failedNode']['description']['deadlineExpired'])
        self.assertNotIn('name', diagnostic['failedNode']['description'])
        self.assertNotIn('rectangle', diagnostic['failedNode']['description'])

    def test_partial_tree_and_strings_remain_bounded_with_the_failing_node_retained(self):
        children = [Accessible(40) for _ in range(72)]
        self.root.set_children(children)
        children[-1].parent = None
        children[-1].name = 'x' * 10000
        diagnostic = self.fail_read(self.reader())
        self.assertLessEqual(len(diagnostic['nodes']), 64)
        self.assertTrue(diagnostic['partialTreeTruncated'])
        self.assertEqual(diagnostic['observedNodeCount'], 73)
        self.assertEqual(diagnostic['failedNode']['indexPath'], [71])
        description = diagnostic['failedNode']['description']
        self.assertEqual(len(description['name']), 256)
        self.assertTrue(description['nameTruncated'])
        self.assertLess(len(json.dumps(diagnostic).encode()), 65536)

    def test_successful_read_does_not_fetch_names_or_geometry_of_unrelated_controls(self):
        unrelated = Accessible(40)
        unrelated.getAccessibleName = lambda: self.fail('Success must not eagerly collect diagnostic names')
        unrelated.getLocationOnScreen = lambda: self.fail('Success must not eagerly collect diagnostic geometry')
        self.root.set_children([unrelated, self.document])
        self.api.require_pending_receipt(self.reader().read(), 456)

    def test_actual_helper_error_reply_retains_the_partial_accessibility_diagnostic(self):
        import writer_model_reader as helper
        import writer_style_smoke as style
        self.broken_branch()
        pending = self.reader()
        wrapped = NS(read=pending.read, release=pending.release, pending_input=pending)
        anchor = NS(snapshot=lambda: {}, close=lambda: [], profile=NS(snapshot=lambda: {}))
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / 'configuration.json').write_text(json.dumps(dict(suite=folder)))
            for sequence, action in enumerate(('start', 'release')):
                (output / f'request-{sequence:03d}.json').write_text(json.dumps(dict(sequence=sequence, action=action)))
            with patch.object(helper, '_native_anchor', return_value=anchor), \
                    patch.object(helper, '_UnoReader', return_value=wrapped), \
                    patch.object(helper, '_qpc', return_value=(1, 1)), \
                    patch.object(style, 'observe_packaged_python', return_value={}), \
                    patch.object(style, 'require_packaged_python', return_value={}):
                helper._helper(output)
            reply = json.loads((output / 'reply-000.json').read_text())
        self.assertFalse(reply['ok'])
        self.assertEqual(reply['error']['message'], 'Pending-input actual parent/index reciprocity failed')
        self.assertIsInstance(reply['error'].get('pendingInputDiagnostic'), dict,
                              'Real helper JSON producer must preserve the a11y failure evidence')
        self.assertEqual(reply['error']['pendingInputDiagnostic']['failedNode']['indexPath'], [0] * 11)


if __name__ == '__main__':
    unittest.main()
