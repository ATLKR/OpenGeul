# Owned Calc pending-input observation

This E2E helper observes the ordinary in-cell A1 buffer through the exact
LibreOffice 26.8.1.1 accessibility implementation. The retained frame's native
peer and removable `XAccessible` test property remain mandatory. This is a
finite acceptance contract for the generated workbook, not a general-purpose
screen reader or a production pending-edit API.

Windows diagnostic run `39018638813` stopped on the formula input line before
any navigation or typing. Its 667th visited object was `TEXT_FRAME`, named
`입력줄`, with parent `null` and index `-1`. The retained original subset is
`suite/tests/fixtures/calc-formula-inputline-diagnostic.json`; the portable test
uses synthetic surrounding objects and does not claim to replay a complete
captured Windows tree.

The null parent matches the pinned source:

- [The EditLine base constructor uses a null parent](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/sc/source/ui/Accessibility/AccessibleEditObject.cxx#L72).
- [The edit control constructor passes only its object type](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/sc/source/ui/inc/AccessibleEditObject.hxx#L186).
- [The formula input line explicitly calls `InitAcc(nullptr, ...)`](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/sc/source/ui/app/inputwin.cxx#L1590),
  also on its [other edit-view initialization path](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/sc/source/ui/app/inputwin.cxx#L2141).
- [The input window creates `ScAccessibleEditLineObject`](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/sc/source/ui/app/inputwin.cxx#L2224),
  using the [Input line resource](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/sc/inc/strings.hrc#L109).

Discovery follows the pinned `FRAME`, `PANEL`, `ROOT_PANE`, `SCROLL_PANE`,
`SPLIT_PANE`, `VIEW_PORT` and `WINDOW` roles from that retained root. It stops at
each `DOCUMENT_SPREADSHEET` and requires exactly one candidate. Other roles are
leaves for discovery: their parent, child count, name, geometry and text are not
queried. There is no special exception keyed to the formula line's name, path,
null parent or index. An unsupported target ancestor role produces no eligible
document on that branch; absent or split/ambiguous eligible document panes fail.

After discovery, every retained ancestor from root to the spreadsheet must
pass the original parent/index/child-readback checks. The helper reads only the
document's direct table and text-frame children; it requires at most one direct
in-cell text frame, the exact source A1 name, and actual direct paragraph text.
Table descendants are never enumerated. The qualified ancestry, table, editor
and paragraphs are checked again before returning. Retained identity/path,
positive contained geometry, visibility, text, encoding and model checks remain
strict. Formula-bar text and committed model-cell text cannot substitute for
an absent in-cell edit buffer.

`traversal.ownershipScope`, `discoveryContainerRoles`, skipped-branch counts and
the exact validated-node count describe this scope. The reciprocity witness
applies to the qualified document path and direct buffer objects. It makes no
reciprocity claim about unrelated frame controls. Existing depth, child, node,
paragraph and text bounds, the original shared twelve-second deadline, one
physical input sequence, and normal observer exit requirements are retained.

Portable tests preserve the original failing-control metadata and exercise
strict positive and negative cases. They do not establish the behavior, tree
size, latency or successful Save/Close results of a new Windows run.
