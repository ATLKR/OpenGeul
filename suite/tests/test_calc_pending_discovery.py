"""Replay the observed formula-line defect with a synthetic owned document tree.

Only fixture fields are original Windows evidence. Missing ancestor/control
objects below are synthetic; these tests do not claim a captured native tree.
"""
import json
from pathlib import Path
import unittest

from suite.tests import test_calc_pending_input as fixtures

Accessible = fixtures.Accessible
ORIGINAL = Path(__file__).parent / 'fixtures/calc-formula-inputline-diagnostic.json'


class TargetDocumentDiscoveryTests(unittest.TestCase):
    setUp = fixtures.PendingInputTests.setUp
    reader = fixtures.PendingInputTests.reader
    present = fixtures.PendingInputTests.present

    def original_formula_tree(self):
        original = json.loads(ORIGINAL.read_text())
        failed = original['failedNode']
        described = failed['description']
        formula = Accessible(described['role'], described['name'], rectangle=tuple(described['rectangle']))
        self.root.role = original['root']['role']
        path = failed['indexPath']
        parent = self.root
        for depth, index in enumerate(path):
            children = [Accessible(40) for _ in range(index + 1)]
            children[index] = formula if depth == len(path) - 1 else Accessible(40)
            parent.set_children(children)
            parent = children[index]
        expected_parent = original['expectedParent']
        formula.parent.role = expected_parent['role']
        formula.parent.rectangle = tuple(expected_parent['rectangle'])
        self.root.set_children([Accessible(35), self.root.children[1], Accessible(40), self.document])
        formula.parent, formula.index = original['actualParent'], failed['observedIndexInParent']
        return formula

    def test_observed_null_parent_formula_inputline_is_not_a_document_or_edit_buffer(self):
        formula = self.original_formula_tree()
        for operation in ('getAccessibleParent', 'getAccessibleIndexInParent', 'getAccessibleChildCount',
                          'getAccessibleName', 'getText', 'getLocationOnScreen', 'getSize'):
            setattr(formula, operation, lambda op=operation: self.fail('Discovery touched unrelated formula-line ' + op))
        raw = self.reader().read()
        self.assertIsNone(raw['editor'])
        self.assertEqual(raw['document']['indexPath'], [3])
        self.assertLess(raw['traversal']['visitedCount'], 40, 'Menus/formula-line descendants must not consume the old667-node traversal')
        self.assertEqual(raw['traversal'].get('ownershipScope'), 'retained-root-to-calc-document-and-direct-edit-buffer')
        self.assertGreater(raw['traversal'].get('skippedNonDocumentBranchCount', 0), 0)

    def test_menu_and_toolbar_children_are_never_enumerated(self):
        for role in (34, 35, 36, 57, 63):
            with self.subTest(role=role):
                control = Accessible(role)
                control.getAccessibleChildCount = lambda: self.fail('Unrelated menu/toolbar/status descendants must not be enumerated')
                control.getAccessibleParent = lambda: self.fail('Unrelated controls are not target ancestry')
                self.root.set_children([control, self.document])
                self.api.require_pending_receipt(self.reader().read(), 456)

    def test_every_target_ancestor_still_requires_reciprocal_parent_index_and_readback(self):
        for field, value in (('parent', None), ('index', -1)):
            with self.subTest(field=field):
                container = Accessible(40, children=[self.document])
                self.root.set_children([container])
                setattr(container, field, value)
                with self.assertRaisesRegex(AssertionError, 'parent/index reciprocity'):
                    self.reader().read()

    def test_unique_target_document_and_exact_retained_editor_ancestry_are_mandatory(self):
        self.root.set_children([Accessible(40, children=[self.document]), Accessible(40, children=[Accessible(84)])])
        with self.assertRaisesRegex(AssertionError, 'Exactly one reachable Calc document'):
            self.reader().read()
        self.root.set_children([self.document])
        self.document.set_children([self.table, self.editor]); self.editor.parent = None
        with self.assertRaisesRegex(AssertionError, 'parent/index reciprocity'):
            self.reader().read()

    def test_source_target_editor_paragraph_null_parent_remains_rejected(self):
        self.document.set_children([self.table, self.editor]); self.paragraph.parent = None
        with self.assertRaisesRegex(AssertionError, 'parent/index reciprocity'):
            self.reader().read()

    def test_formula_bar_text_match_cannot_substitute_for_the_direct_a1_editor(self):
        formula = self.original_formula_tree()
        formula.name, formula.text = 'Cell A1', 'Existing A1'
        raw = self.reader().read()
        self.assertIsNone(raw['editor'])
        with self.assertRaisesRegex(AssertionError, 'in-cell edit buffer is absent'):
            self.api.require_pending_receipt(raw, 456, 'Existing A1', True)

    def test_replay_requires_every_claimed_target_node_to_have_been_validated(self):
        raw = self.present()
        raw['traversal']['validatedNodeCount'] = 1
        with self.assertRaisesRegex(AssertionError, 'target ancestry'):
            self.api.require_pending_receipt(raw, 456, 'Existing A1', True)

    def test_two_direct_editors_and_a_changed_retained_document_path_are_rejected(self):
        second = Accessible(61, 'Cell A1', children=[Accessible(41, text='Existing A1')])
        self.document.set_children([self.table, self.editor, second])
        with self.assertRaisesRegex(AssertionError, 'Multiple actual in-cell text editors'):
            self.reader().read()
        self.document.set_children([self.table])
        reader = self.reader(); reader.read()
        self.root.set_children([Accessible(40), self.document])
        with self.assertRaisesRegex(AssertionError, 'document path changed'):
            reader.read()


if __name__ == '__main__':
    unittest.main()
