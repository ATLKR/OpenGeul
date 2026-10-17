"""Portable boundary tests; they do not certify native Calc accessibility."""
from copy import deepcopy
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))

ROLES = dict(PARAGRAPH=41, TABLE=58, TABLE_CELL=59, TEXT_FRAME=61,
             DOCUMENT_SPREADSHEET=84)
STATES = dict(DEFUNC=16, SHOWING=16777216, VISIBLE=536870912)


class Accessible:
    def __init__(self, role, name='', children=(), rectangle=(10, 10, 90, 90), text=''):
        self.role, self.name, self.rectangle, self.text = role, name, rectangle, text
        self.state = STATES['SHOWING'] | STATES['VISIBLE']
        self.parent, self.index, self.children = None, -1, []
        self.set_children(children)

    def set_children(self, children):
        self.children = list(children)
        for index, child in enumerate(self.children):
            child.parent, child.index = self, index

    def getAccessibleContext(self): return self
    def getAccessibleRole(self): return self.role
    def getAccessibleStateSet(self): return self.state
    def getAccessibleName(self): return self.name
    def getAccessibleParent(self): return self.parent
    def getAccessibleIndexInParent(self): return self.index
    def getAccessibleChildCount(self): return len(self.children)
    def getAccessibleChild(self, index): return self.children[index]
    def getLocationOnScreen(self): return NS(X=self.rectangle[0], Y=self.rectangle[1])
    def getSize(self): return NS(Width=self.rectangle[2]-self.rectangle[0], Height=self.rectangle[3]-self.rectangle[1])
    def getText(self): return self.text


class PendingInputTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module('calc_pending_input')
        except ModuleNotFoundError:
            self.fail('The bounded accessibility pending-input reader is missing')
        self.paragraph = Accessible(41, rectangle=(20, 20, 65, 35), text='Existing A1')
        self.editor = Accessible(61, 'Cell A1', [self.paragraph], (20, 20, 70, 40))
        self.table = Accessible(58)
        self.table.getAccessibleChildCount = lambda: self.fail('Sheet cells must never be enumerated')
        self.document = Accessible(84, children=[self.table], rectangle=(10, 10, 95, 95))
        self.root = Accessible(40, children=[self.document], rectangle=(0, 0, 100, 100))
        self.peer = NS(getWindowHandle=lambda *args: 456,
                       getProperty=lambda name: self.root if name == 'XAccessible' else self.fail('Only the pinned test property is allowed'))
        self.frame = NS(getContainerWindow=lambda: self.peer)
        uno = NS(getConstantByName=lambda name: (STATES if '.AccessibleStateType.' in name else ROLES)[name.rsplit('.', 1)[-1]])
        self.patcher = patch.dict(sys.modules, uno=uno)
        self.patcher.start(); self.addCleanup(self.patcher.stop)

    def reader(self): return self.api.AccessiblePendingReader(self.frame, 456)

    def present(self, reader=None):
        self.document.set_children([self.table, self.editor])
        return (reader or self.reader()).read()

    def test_absence_before_f2_is_explicit_and_table_descendants_are_never_read(self):
        raw = self.reader().read()
        self.assertIsNone(raw['editor'])
        self.assertEqual(raw['traversal']['skippedTableCount'], 1)
        self.api.require_pending_receipt(raw, 456)
        with self.assertRaises(AssertionError):
            self.api.require_pending_receipt(raw, 456, require_editor=True)

    def test_actual_a1_editor_text_and_identity_are_retained_across_typing(self):
        reader = self.reader(); absent = reader.read(); baseline = self.present(reader)
        self.api.require_pending_receipt(baseline, 456, 'Existing A1', True, absent)
        self.paragraph.text += ' pending-marker'
        after = reader.read()
        self.api.require_pending_receipt(after, 456, 'Existing A1 pending-marker', True, baseline)
        self.assertEqual(baseline['editor']['identity'], after['editor']['identity'])
        self.assertEqual(after['editor']['indexPath'], [0, 1])
        self.assertEqual(after['editor']['paragraphs'][0]['text'], self.paragraph.text)

    def test_exact_korean_source_resource_name_is_supported(self):
        self.editor.name = '셀 A1'
        self.api.require_pending_receipt(self.present(), 456, 'Existing A1', True)

    def test_release_only_drops_local_references_and_prevents_future_reads(self):
        reader = self.reader(); self.present(reader)
        self.editor.dispose = lambda: self.fail('The reader must never dispose native objects')
        reader.release(); reader.release()
        with self.assertRaises(AssertionError): reader.read()

    def test_hidden_or_defunct_document_and_editor_are_rejected(self):
        for target in (self.document, self.editor):
            for state in (0, STATES['VISIBLE'], STATES['SHOWING'] | STATES['VISIBLE'] | STATES['DEFUNC']):
                with self.subTest(target=target, state=state):
                    original = target.state; target.state = state
                    with self.assertRaises(AssertionError): self.present()
                    target.state = original

    def test_wrong_hwnd_missing_peer_or_accessible_context_fail_closed(self):
        reader = self.reader()
        for change in (lambda: setattr(self.peer, 'getWindowHandle', lambda *a: 999),
                       lambda: setattr(self.frame, 'getContainerWindow', lambda: None),
                       lambda: setattr(self.root, 'getAccessibleContext', lambda: None)):
            with self.subTest(change=change):
                old_handle, old_peer, old_context = self.peer.getWindowHandle, self.frame.getContainerWindow, self.root.getAccessibleContext
                change()
                with self.assertRaises(AssertionError): reader.read()
                self.peer.getWindowHandle, self.frame.getContainerWindow, self.root.getAccessibleContext = old_handle, old_peer, old_context

    def test_changed_root_or_spreadsheet_document_is_rejected(self):
        reader = self.reader(); reader.read()
        original = self.root
        self.root = Accessible(40, children=[self.document], rectangle=(0, 0, 100, 100))
        with self.assertRaises(AssertionError): reader.read()
        self.root = original
        original.set_children([Accessible(84, children=[self.table])])
        with self.assertRaises(AssertionError): reader.read()

    def test_replaced_or_disappeared_editor_cannot_reuse_a_text_match(self):
        for replacement in ([], [Accessible(61, 'Cell A1', [Accessible(41, text='Existing A1')])]):
            with self.subTest(replacement=replacement):
                reader = self.reader(); self.present(reader)
                self.document.set_children([self.table, *replacement])
                with self.assertRaises(AssertionError): reader.read()

    def test_parent_index_and_index_readback_must_all_reciprocate(self):
        for field, value in (('parent', self.root), ('index', 0)):
            with self.subTest(field=field):
                self.document.set_children([self.table, self.editor])
                setattr(self.editor, field, value)
                with self.assertRaises(AssertionError): self.reader().read()
        self.document.set_children([self.table, self.editor])
        calls = [0]
        def unstable(index):
            if index == 1:
                calls[0] += 1
                return self.editor if calls[0] == 1 else self.paragraph
            return self.table
        self.document.getAccessibleChild = unstable
        with self.assertRaises(AssertionError): self.reader().read()

    def test_cycles_duplicate_children_and_multiple_documents_are_rejected(self):
        self.root.set_children([self.document, self.document])
        with self.assertRaises(AssertionError): self.reader().read()
        self.root.set_children([self.document, Accessible(84)])
        with self.assertRaises(AssertionError): self.reader().read()
        self.root.set_children([self.document]); self.document.set_children([self.root])
        with self.assertRaises(AssertionError): self.reader().read()

    def test_count_depth_and_total_node_bounds_fail_instead_of_truncating(self):
        self.document.getAccessibleChildCount = lambda: 1000000
        with self.assertRaises(AssertionError): self.reader().read()
        self.document.getAccessibleChildCount = lambda: len(self.document.children)
        nested = self.document
        for _ in range(40): nested = Accessible(40, children=[nested])
        self.root.set_children([nested])
        with self.assertRaises(AssertionError): self.reader().read()
        self.root.set_children([Accessible(40, children=[Accessible(40) for _ in range(100)]) for _ in range(30)])
        with self.assertRaises(AssertionError): self.reader().read()

    def test_only_direct_text_frame_with_exact_a1_resource_name_qualifies(self):
        for name in ('Cell A10', 'cell A1', 'A1', 'Cell A1 pending', '셀 A10'):
            with self.subTest(name=name):
                self.editor.name = name
                with self.assertRaises(AssertionError): self.present()
        self.editor.name = 'Cell A1'
        self.document.set_children([self.table, Accessible(40, children=[self.editor])])
        with self.assertRaises(AssertionError):
            self.api.require_pending_receipt(self.reader().read(), 456, require_editor=True)

    def test_editor_and_document_bounds_must_belong_to_owned_root(self):
        for target, rectangle in ((self.editor, (90, 20, 110, 40)),
                                  (self.editor, (20, 20, 20, 40)),
                                  (self.document, (-10, 10, 95, 95))):
            with self.subTest(rectangle=rectangle):
                original = target.rectangle; target.rectangle = rectangle
                with self.assertRaises(AssertionError): self.present()
                target.rectangle = original

    def test_null_text_or_context_and_nonparagraph_editor_children_are_rejected(self):
        for change in (lambda: setattr(self.paragraph, 'text', None),
                       lambda: setattr(self.paragraph, 'getAccessibleContext', lambda: None),
                       lambda: setattr(self.paragraph, 'role', 60)):
            with self.subTest(change=change):
                original = self.paragraph.text, self.paragraph.getAccessibleContext, self.paragraph.role
                change()
                with self.assertRaises(AssertionError): self.present()
                self.paragraph.text, self.paragraph.getAccessibleContext, self.paragraph.role = original

    def test_multiple_paragraph_text_is_exact_and_never_trimmed(self):
        self.editor.set_children([self.paragraph, Accessible(41, text='second  ')])
        raw = self.present()
        self.api.require_pending_receipt(raw, 456, 'Existing A1\nsecond  ', True)
        with self.assertRaises(AssertionError):
            self.api.require_pending_receipt(raw, 456, 'Existing A1\nsecond', True)

    def test_validator_rejects_forged_or_incomplete_ownership_and_traversal(self):
        raw = self.present()
        changes = [lambda r: r.update(childHwnd=999), lambda r: r.update(kind='model-cell'),
                   lambda r: r['witness'].update(sameFramePeer=False),
                   lambda r: r['witness'].update(liveParentIndexReciprocity=False),
                   lambda r: r['traversal'].update(truncated=True),
                   lambda r: r['traversal'].update(visitedCount=100000),
                   lambda r: r['roleConstants'].update(TEXT_FRAME=60),
                   lambda r: r['editor'].update(indexPath=[5, 1]),
                   lambda r: r['editor'].update(name='Cell A2'),
                   lambda r: r['editor'].update(text='Existing A1 suffix'),
                   lambda r: r['editor']['paragraphs'][0].update(indexPath=[0, 1, 9]),
                   lambda r: r['editor'].update(rectangle=[200, 20, 220, 40]),
                   lambda r: r['root'].update(identity='')]
        for change in changes:
            with self.subTest(change=change):
                forged = deepcopy(raw); change(forged)
                with self.assertRaises(AssertionError):
                    self.api.require_pending_receipt(forged, 456, 'Existing A1', True)

    def test_validator_requires_previous_retained_object_identity(self):
        raw = self.present()
        for target in ('root', 'document', 'editor'):
            with self.subTest(target=target):
                forged = deepcopy(raw); forged[target]['identity'] = 'different'
                with self.assertRaises(AssertionError):
                    self.api.require_pending_receipt(forged, 456, previous=raw)
        forged = deepcopy(raw); forged['editor'] = None
        with self.assertRaises(AssertionError):
            self.api.require_pending_receipt(forged, 456, previous=raw)

    def test_schema_version_requires_an_integer_not_boolean_or_float(self):
        raw = self.present()
        for value in (True, False, 1.0, '1'):
            with self.subTest(value=value):
                forged = deepcopy(raw); forged['schemaVersion'] = value
                with self.assertRaises(AssertionError):
                    self.api.require_pending_receipt(forged, 456)

    def test_oversized_paragraph_is_rejected_before_geometry_and_serialization(self):
        self.paragraph.text = 'x' * 65537
        self.editor.getLocationOnScreen = lambda: self.fail('Oversized text reached subsequent editor geometry/serialization')
        with self.assertRaisesRegex(AssertionError, 'paragraph.*bound'):
            self.present()
        self.editor.getLocationOnScreen = lambda: NS(X=20, Y=20)
        self.paragraph.text = 'Existing A1'
        raw = self.present()
        raw['editor']['paragraphs'][0]['text'] = 'x' * 65537
        with self.assertRaisesRegex(AssertionError, 'paragraph.*bound'):
            self.api.require_pending_receipt(raw, 456)


if __name__ == '__main__': unittest.main()
