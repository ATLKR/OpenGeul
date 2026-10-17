"""E2E-only observation of the retained native Calc A1 edit buffer.

Pinned to LibreOffice 26.8.1.1. VCLXWindow's ``XAccessible`` property is an
explicitly removable Java-a11y TEST hook, not a production public contract:
toolkit/source/awt/vclxwindow.cxx. AccessibleDocument.cxx creates the temporary
ScAccessibleEditObject directly below DOCUMENT_SPREADSHEET on entering edit
mode; AccessibleEditObject.cxx gives it TEXT_FRAME and EditView output bounds.
Its PARAGRAPH XAccessibleText.getText reads the existing EditView through the
null-checked ScAccessibleEditObjectTextData::GetTextForwarder (AccessibleText.cxx).

These accessibility getters may allocate accessibility bookkeeping, install its
notify handler, and emit accessibility SetFocus notifications. This helper does
not send input, focus/select, accept edits, or create a Calc EditEngine. It never
uses UITest formula getState, whose null EditEngine path is unsafe. Absence of
the actual temporary editor is explicit; model-cell text is never substituted.
"""
from __future__ import annotations

import re
import time
import uuid

ROLE_NAMESPACE = 'com.sun.star.accessibility.AccessibleRole'
STATE_NAMESPACE = 'com.sun.star.accessibility.AccessibleStateType'
ROLE_CONSTANTS = dict(PARAGRAPH=41, TABLE=58, TABLE_CELL=59, TEXT_FRAME=61,
                      DOCUMENT_SPREADSHEET=84)
STATE_CONSTANTS = dict(DEFUNC=16, SHOWING=16777216, VISIBLE=536870912)
# STR_ACC_CELL_NAME: core/sc/inc/strings.hrc and translations/source/ko/sc/messages.po
# at tag libreoffice-26.8.1.1; GetCurrentCellName substitutes the exact address.
A1_EDITOR_NAMES = ('Cell A1', '셀 A1')
MAX_DEPTH, MAX_CHILDREN, MAX_NODES, MAX_PARAGRAPHS = 24, 256, 2048, 32
MAX_TEXT = 65536
MAX_DIAGNOSTIC_NODES, MAX_DIAGNOSTIC_NAME, MAX_DIAGNOSTIC_ERROR = 64, 256, 512
KIND = 'owned-calc-a1-accessible-pending-input'
WITNESSES = ('sameFramePeer', 'sameRoot', 'liveParentIndexReciprocity',
             'sameRetainedDocument', 'sameRetainedEditor')


def _inside(rectangle, outer):
    return (isinstance(rectangle, list) and len(rectangle) == 4
            and all(type(value) is int for value in rectangle)
            and rectangle[0] < rectangle[2] and rectangle[1] < rectangle[3]
            and outer[0] <= rectangle[0] < rectangle[2] <= outer[2]
            and outer[1] <= rectangle[1] < rectangle[3] <= outer[3])


def _rectangle(context):
    point, size = context.getLocationOnScreen(), context.getSize()
    values = (point.X, point.Y, size.Width, size.Height)
    assert all(type(value) is int for value in values), 'Accessible screen geometry is not integral'
    return [point.X, point.Y, point.X + size.Width, point.Y + size.Height]


def _path(value):
    return (isinstance(value, list) and len(value) <= MAX_DEPTH
            and all(type(index) is int and 0 <= index < MAX_CHILDREN for index in value))


def _identity(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{32}', value) is not None


def _visible(bits):
    return (type(bits) is int and not bits & STATE_CONSTANTS['DEFUNC']
            and bits & STATE_CONSTANTS['SHOWING'] and bits & STATE_CONSTANTS['VISIBLE'])


def require_pending_receipt(raw, child_hwnd, expected_text=None, require_editor=False, previous=None):
    """Replay structural and exact-text checks; live identity is witnessed by the reader.

    Identity strings are local labels assigned to retained UNO objects, not
    native addresses. ``previous`` binds consecutive observations to those same
    retained root/document/editor witnesses. This is not a cryptographic proof.
    """
    assert isinstance(raw, dict) and type(raw.get('schemaVersion')) is int and raw['schemaVersion'] == 1 and raw.get('kind') == KIND, 'Actual Calc accessible pending-input receipt is required'
    assert type(child_hwnd) is int and child_hwnd > 0 and type(raw.get('childHwnd')) is int and raw['childHwnd'] == child_hwnd, 'Pending-input receipt belongs to another owned editor HWND'
    assert raw.get('sourceTag') == 'libreoffice-26.8.1.1' and raw.get('testOnlyProperty') == 'XVclWindowPeer.XAccessible', 'Pending-input source/test-property binding differs'
    assert raw.get('roleConstants') == ROLE_CONSTANTS and raw.get('stateConstants') == STATE_CONSTANTS, 'Pending-input accessible constants differ from the pinned API'
    assert isinstance(raw.get('witness'), dict) and all(raw['witness'].get(name) is True for name in WITNESSES), 'Pending-input live ownership/reciprocity witness is incomplete'
    traversal = raw.get('traversal', {})
    assert traversal.get('truncated') is False, 'Pending-input traversal was truncated'
    assert type(traversal.get('visitedCount')) is int and 1 <= traversal['visitedCount'] <= MAX_NODES, 'Pending-input traversal exceeds its finite node bound'
    assert type(traversal.get('skippedTableCount')) is int and 0 <= traversal['skippedTableCount'] <= traversal['visitedCount'], 'Pending-input skipped-table count is invalid'
    root, document, editor = raw.get('root'), raw.get('document'), raw.get('editor')
    assert isinstance(root, dict) and _identity(root.get('identity')), 'Retained accessible root identity is missing'
    outer = root.get('rectangle')
    assert isinstance(outer, list) and _inside(outer, outer), 'Owned root screen bounds are invalid'
    assert isinstance(document, dict) and _identity(document.get('identity')) and document.get('role') == ROLE_CONSTANTS['DOCUMENT_SPREADSHEET'], 'Exactly one retained Calc document is required'
    assert _path(document.get('indexPath')) and _inside(document.get('rectangle'), outer) and _visible(document.get('stateBits')), 'Calc document path, visibility or owned geometry is invalid'
    if editor is None:
        assert not require_editor and expected_text is None, 'Actual A1 in-cell edit buffer is absent'
    else:
        assert isinstance(editor, dict) and _identity(editor.get('identity')), 'Retained A1 editor identity is missing'
        assert editor.get('role') == ROLE_CONSTANTS['TEXT_FRAME'] and editor.get('name') in A1_EDITOR_NAMES, 'Actual editor is not the exact source-named A1 TEXT_FRAME'
        path = editor.get('indexPath')
        assert _path(path) and len(path) == len(document['indexPath']) + 1 and editor.get('parentIndexPath') == document['indexPath'] and path[:-1] == document['indexPath'], 'A1 editor is not a direct child of the retained Calc document'
        assert _inside(editor.get('rectangle'), document['rectangle']) and _visible(editor.get('stateBits')), 'A1 editor visibility or document-bound geometry is invalid'
        paragraphs = editor.get('paragraphs')
        assert isinstance(paragraphs, list) and 1 <= len(paragraphs) <= MAX_PARAGRAPHS, 'A1 editor paragraph count is invalid'
        for index, paragraph in enumerate(paragraphs):
            assert isinstance(paragraph, dict) and paragraph.get('role') == ROLE_CONSTANTS['PARAGRAPH'], 'A1 editor text must come from actual accessible paragraphs'
            assert paragraph.get('indexPath') == path + [index] and paragraph.get('parentIndexPath') == path, 'A1 paragraph parent/index path is invalid'
            assert isinstance(paragraph.get('text'), str), 'A1 accessible paragraph returned null/non-string text'
            assert len(paragraph['text']) <= MAX_TEXT, 'A1 accessible paragraph exceeds its finite text bound'
        assert sum(len(paragraph['text']) for paragraph in paragraphs) + len(paragraphs) - 1 <= MAX_TEXT, 'A1 accessible paragraphs exceed their finite aggregate text bound'
        text = '\n'.join(paragraph['text'] for paragraph in paragraphs)
        assert editor.get('text') == text, 'A1 pending text differs from its complete accessible paragraphs'
        if expected_text is not None:
            assert isinstance(expected_text, str) and text == expected_text, 'Actual A1 pending buffer does not exactly match expected text'
    if previous is not None:
        require_pending_receipt(previous, child_hwnd)
        for key in ('root', 'document'):
            assert raw[key]['identity'] == previous[key]['identity'], 'Retained accessible ' + key + ' identity changed'
        assert document['indexPath'] == previous['document']['indexPath'], 'Retained Calc document path changed'
        if previous['editor'] is not None:
            assert editor is not None and editor['identity'] == previous['editor']['identity'] and editor['indexPath'] == previous['editor']['indexPath'], 'Retained A1 edit buffer disappeared or changed identity/path'
    return raw


class AccessiblePendingReader:
    """Retain only objects reachable from the verified frame's own native peer."""

    def __init__(self, frame, child_hwnd, *, deadline=None, clock=time.monotonic):
        import uno
        assert type(child_hwnd) is int and child_hwnd > 0, 'Owned native editor HWND is invalid'
        for namespace, constants in ((ROLE_NAMESPACE, ROLE_CONSTANTS), (STATE_NAMESPACE, STATE_CONSTANTS)):
            for name, expected in constants.items():
                assert int(uno.getConstantByName(namespace + '.' + name)) == expected, 'Accessible API differs from pinned source'
        self.frame, self.child_hwnd = frame, child_hwnd
        self.deadline, self.clock = deadline, clock
        self.peer = frame.getContainerWindow()
        assert self.peer is not None and int(self.peer.getWindowHandle((), 1)) == child_hwnd, 'Frame peer does not own the verified native editor'
        self.root = self.peer.getProperty('XAccessible')
        assert self.root is not None, 'Owned frame peer has no accessible test object'
        self.document = self.editor = None
        self.identities = dict(root=uuid.uuid4().hex, document=uuid.uuid4().hex, editor=uuid.uuid4().hex)
        self.previous = None
        self.last_diagnostic = None

    def release(self):
        """Drop local references only; never close/dispose any native object."""
        self.frame = self.peer = self.root = self.document = self.editor = None
        self.previous = None

    def _verify_peer(self):
        assert self.frame is not None and self.peer is not None, 'Pending-input reader has been released'
        assert self.frame.getContainerWindow() == self.peer and int(self.peer.getWindowHandle((), 1)) == self.child_hwnd, 'Verified frame peer/HWND changed during pending-input capture'
        assert self.peer.getProperty('XAccessible') == self.root, 'Retained native accessible root changed'

    def read(self):
        # Error evidence is separate from a qualified observation. Retain only
        # bounded JSON data; drop every temporary native proxy in the finally.
        self._trace, self._trace_count, self._current = [], 0, None
        self._contexts, self._phase = [], 'verify-peer'
        self.last_diagnostic = None
        try:
            return self._read()
        except BaseException as exc:
            try:
                diagnostic = self._failure_diagnostic(exc)
            except BaseException as diagnostic_error:
                diagnostic = dict(schemaVersion=1, kind=KIND + '-failure', qualified=False,
                    childHwnd=self.child_hwnd, phase=self._phase,
                    primaryError=dict(type=type(exc).__name__, message=str(exc)[:MAX_DIAGNOSTIC_ERROR]),
                    diagnosticError=dict(type=type(diagnostic_error).__name__,
                                         message=str(diagnostic_error)[:MAX_DIAGNOSTIC_ERROR]))
            self.last_diagnostic = diagnostic
            try:
                exc.pending_input_diagnostic = diagnostic
            except BaseException:
                pass  # The original exception, even if immutable, stays primary.
            raise
        finally:
            self._trace = self._contexts = self._current = None

    def _describe_failure_object(self, accessible, known_role=None, context=None, *, read_index=False):
        """At most one node and its two parents; no second tree traversal."""
        if accessible is None:
            return None
        known = [node for node in self._contexts if node[0] == accessible]
        record = dict(knownIndexPaths=[node[2] for node in known])
        errors = record['errors'] = []

        def get(operation, owner):
            # These optional getters cannot reset/extend the reader's budget.
            # An absent deadline gives no authorization for extra remote calls.
            if self.deadline is None or self.clock() >= self.deadline:
                record['deadlineExpired'] = True
                return None
            try:
                return getattr(owner, operation)()
            except BaseException as exc:
                errors.append(dict(operation=operation, type=type(exc).__name__,
                                   message=str(exc)[:MAX_DIAGNOSTIC_ERROR]))
                return None

        if context is None:
            context = known[0][1] if known else get('getAccessibleContext', accessible)
        if known_role is not None:
            record['role'] = known_role
        if context is None:
            return record
        if read_index:
            index = get('getAccessibleIndexInParent', context)
            if type(index) is int:
                record['indexInParent'] = index
        if known_role is None:
            role = get('getAccessibleRole', context)
            if type(role) is int:
                record['role'] = role
        name = get('getAccessibleName', context)
        if isinstance(name, str):
            record.update(name=name[:MAX_DIAGNOSTIC_NAME], nameTruncated=len(name) > MAX_DIAGNOSTIC_NAME)
        point = get('getLocationOnScreen', context)
        size = get('getSize', context)
        if point is not None and size is not None:
            values = point.X, point.Y, size.Width, size.Height
            if all(type(value) is int for value in values):
                record['rectangle'] = [point.X, point.Y, point.X + size.Width, point.Y + size.Height]
        return record

    def _failure_diagnostic(self, exc):
        diagnostic = dict(schemaVersion=1, kind=KIND + '-failure', sourceTag='libreoffice-26.8.1.1',
            qualified=False, childHwnd=self.child_hwnd, phase=self._phase,
            primaryError=dict(type=type(exc).__name__, message=str(exc)[:MAX_DIAGNOSTIC_ERROR]),
            observedNodeCount=self._trace_count, partialTreeTruncated=self._trace_count > len(self._trace),
            nodes=[dict(row) for row in self._trace])
        if self._current is not None:
            current = self._current
            row = dict(current['record'])
            row['description'] = self._describe_failure_object(current['accessible'], row.get('role'),
                current.get('context'), read_index='observedIndexInParent' not in row and bool(row['indexPath']))
            if row['description'] is not None and 'indexInParent' in row['description']:
                row['observedIndexInParent'] = row['description']['indexInParent']
            diagnostic['failedNode'] = row
            diagnostic['expectedParent'] = self._describe_failure_object(current['parent'])
            if current['actualParent'] is current['parent']:
                diagnostic['actualParent'] = diagnostic['expectedParent']
            else:
                diagnostic['actualParent'] = self._describe_failure_object(current['actualParent'])
        return diagnostic

    def _read(self):
        self._verify_peer()
        nodes, skipped = [], [0]
        self._contexts = nodes

        def reciprocity(context, parent, path, record, phase, *, final=False):
            self._phase = phase
            actual_parent = context.getAccessibleParent()
            self._current['actualParent'] = actual_parent
            parent_matches = actual_parent == parent
            record.update(observedParentMatchesExpected=parent_matches, expectedIndexInParent=path[-1])
            # Preserve the original short-circuit: if the parent is foreign,
            # its index is optional error evidence, never a new primary error.
            actual_index = int(context.getAccessibleIndexInParent()) if parent_matches else None
            if parent_matches:
                record['observedIndexInParent'] = actual_index
            assert parent_matches and actual_index == path[-1], ('Accessible identity/path changed during pending-input read'
                if final else 'Pending-input actual parent/index reciprocity failed')
            self._phase = phase + '-readback'
            readback_matches = parent.getAccessibleContext().getAccessibleChild(path[-1]) == self._current['accessible']
            record['parentChildReadbackMatches'] = readback_matches
            assert readback_matches, ('Accessible identity/path changed during pending-input read'
                if final else 'Pending-input parent child-index readback changed')

        def visit(accessible, path, parent=None):
            self._phase = 'visit-bound'
            row = dict(indexPath=path[:MAX_DEPTH + 1], parentIndexPath=path[:-1][:MAX_DEPTH + 1])
            self._trace_count += 1
            if len(self._trace) < MAX_DIAGNOSTIC_NODES:
                self._trace.append(row)
            self._current = dict(record=row, accessible=accessible, parent=parent, actualParent=None)
            assert accessible is not None and len(path) <= MAX_DEPTH and len(nodes) < MAX_NODES, 'Pending-input accessible traversal exceeded its finite bound or returned null'
            assert not any(accessible == earlier[0] for earlier in nodes), 'Pending-input accessible tree contains a cycle or duplicate live object'
            self._phase = 'get-context'
            context = accessible.getAccessibleContext()
            self._current['context'] = context
            assert context is not None, 'Pending-input accessible context is null'
            if parent is not None:
                reciprocity(context, parent, path, row, 'parent-index-reciprocity')
            self._phase = 'get-role'
            role = int(context.getAccessibleRole())
            row['role'] = role
            nodes.append((accessible, context, path, parent, role))
            if role in (ROLE_CONSTANTS['TABLE'], ROLE_CONSTANTS['TABLE_CELL']):
                skipped[0] += 1
                row['tableDescendantsSkipped'] = True
                return  # Never ask a spreadsheet table/cell for its descendants.
            self._phase = 'get-child-count'
            count = int(context.getAccessibleChildCount())
            row['childCount'] = count
            assert 0 <= count <= MAX_CHILDREN, 'Pending-input container has an excessive child count'
            for index in range(count):
                visit(context.getAccessibleChild(index), path + [index], accessible)

        visit(self.root, [])
        self._phase = 'select-document-editor'
        documents = [node for node in nodes if node[4] == ROLE_CONSTANTS['DOCUMENT_SPREADSHEET']]
        assert len(documents) == 1, 'Exactly one reachable Calc document is required; split/ambiguous panes are unsupported'
        document, document_context, document_path, _, _ = documents[0]
        if self.document is None:
            self.document = document
        assert document == self.document, 'Retained Calc document identity changed'
        root_context = self.root.getAccessibleContext()
        assert root_context is not None, 'Owned root context disappeared'
        document_record = dict(identity=self.identities['document'], role=ROLE_CONSTANTS['DOCUMENT_SPREADSHEET'],
                               indexPath=document_path, rectangle=_rectangle(document_context),
                               stateBits=int(document_context.getAccessibleStateSet()))
        candidates = [node for node in nodes if node[3] == document and node[4] == ROLE_CONSTANTS['TEXT_FRAME']]
        assert len(candidates) <= 1, 'Multiple actual in-cell text editors are ambiguous'
        editor_record = None
        if candidates:
            editor, context, path, _, _ = candidates[0]
            name = context.getAccessibleName()
            assert isinstance(name, str) and name in A1_EDITOR_NAMES, 'Actual in-cell editor is not source-named A1'
            if self.editor is None:
                self.editor = editor
            assert editor == self.editor, 'Retained A1 pending editor identity changed'
            paragraphs = [node for node in nodes if node[3] == editor]
            assert 1 <= len(paragraphs) <= MAX_PARAGRAPHS, 'Actual A1 edit buffer has an invalid paragraph count'
            records = []
            for index, (_, paragraph_context, paragraph_path, _, role) in enumerate(paragraphs):
                assert role == ROLE_CONSTANTS['PARAGRAPH'] and paragraph_path == path + [index], 'Actual A1 editor child is not a reciprocal accessible paragraph'
                text = paragraph_context.getText()
                assert isinstance(text, str), 'Actual A1 paragraph text is null/non-string'
                assert len(text) <= MAX_TEXT, 'Actual A1 accessible paragraph exceeds its finite text bound'
                records.append(dict(role=role, indexPath=paragraph_path, parentIndexPath=path, text=text))
            assert sum(len(record['text']) for record in records) + len(records) - 1 <= MAX_TEXT, 'Actual A1 accessible paragraphs exceed their finite aggregate text bound'
            editor_record = dict(identity=self.identities['editor'], role=ROLE_CONSTANTS['TEXT_FRAME'], name=name,
                                 indexPath=path, parentIndexPath=document_path, rectangle=_rectangle(context),
                                 stateBits=int(context.getAccessibleStateSet()), paragraphs=records,
                                 text='\n'.join(record['text'] for record in records))
        else:
            assert self.editor is None, 'Retained A1 pending editor disappeared'
        # Hold every captured proxy until the complete tree/text read is checked.
        for accessible, context, path, parent, role in nodes:
            if parent is not None:
                row = dict(indexPath=path, parentIndexPath=path[:-1], role=role)
                self._current = dict(record=row, accessible=accessible, context=context, parent=parent, actualParent=None)
                reciprocity(context, parent, path, row, 'final-parent-index-reciprocity', final=True)
        self._phase = 'verify-peer-after-read'
        self._verify_peer()
        self._phase = 'validate-pending-receipt'
        raw = dict(schemaVersion=1, kind=KIND, sourceTag='libreoffice-26.8.1.1',
                   testOnlyProperty='XVclWindowPeer.XAccessible', childHwnd=self.child_hwnd,
                   roleConstants=dict(ROLE_CONSTANTS), stateConstants=dict(STATE_CONSTANTS),
                   root=dict(identity=self.identities['root'], rectangle=_rectangle(root_context)),
                   document=document_record, editor=editor_record,
                   traversal=dict(visitedCount=len(nodes), skippedTableCount=skipped[0], truncated=False),
                   witness={name: True for name in WITNESSES})
        require_pending_receipt(raw, self.child_hwnd, previous=self.previous)
        self.previous = raw
        return raw
