# Suite engine and GUI content verification

Run the real engine harness with the packaged UNO Python on Windows:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
& "$suite\Office\program\python.exe" "$repo\suite\e2e\engine_smoke.py" --suite $suite --output $evidence
```

Evidence must be outside the payload. The evidence directory may exist, but its
`fixtures` directory and engine report must be absent. No user document is read,
overwritten or discarded. Each case owns a headless process/job, profile and
random local named pipe using the packaged worker's native process helpers.
Macros and automatic document updates are disabled. Every case writes a JSON
record and the aggregate `engine-smoke.json`; failures remain failures even when
the other modules pass. Exit codes: 0 all cases passed; 1 case failure; 2 setup
or evidence-path failure. A missing native engine/pyuno/Firebird is not skipped.

Generated files are `fixtures/OpenGeul-writer.docx`, `OpenGeul-calc.xlsx`,
`OpenGeul-impress.pptx`, `OpenGeul-draw.odg`, `OpenGeul-math.odf`, and
`OpenGeul-base.odb`. Saved files are closed and reopened through UNO, then their
text, spreadsheet formula/result, drawing geometry, math expression or embedded
Firebird row is compared. Base uses the OfficeDatabaseDocument service and native
embedded Firebird, avoiding the interactive database wizard and external Java.

Run the separate real GUI harness with the normal workflow Python and its pinned
`pywinauto`/Pillow dependencies:

```powershell
python "$repo\suite\e2e\windows_smoke.py" --suite $suite --fixtures "$evidence\fixtures" --output $nativeEvidence
```

Use a fresh native evidence directory outside the Suite payload and fixtures.
The harness first starts the Suite without arguments, checks the exact seven
module accessibility labels and writes `home.png` and `home-result.json`.
It then opens all six engine-generated Office fixtures, requiring each file to
match its passing `engine-smoke.json` baseline path and SHA256 before launch.
Every module must report a live child HWND beneath the Suite-owned native panel,
an OpenGeul document title and no visible top-level Office process window. Each
document and its remaining Suite home must close cleanly.

Only the first three modules receive actual physical clicks and keyboard input:

- Writer: append `UI-OpenGeul-writer` and save.
- Calc: append `UI-OpenGeul-calc` to A1, preserving the original marker, and save.
  D1 must retain `=SUM(B1:C1)` with result 42.
- Impress: append `UI-OpenGeul-impress` to a first-slide text shape and save.
  The only generated text shape starts at (2500,2500), size (20000,6000), in
  hundredths of a millimetre. A new text shape on that slide is also accepted.

Keyboard input requires the Suite foreground window and focus inside its
embedded editor. Saved OOXML must contain the new suffix, its bytes must change,
and the marker must remain after close. Missing or partially written ZIP files
keep the save wait pending; they cannot satisfy the predicate. There is no UNO,
clipboard, DOM or programmatic document-mutation fallback in this GUI harness.

Draw, Math and Base are **attach-only GUI checks**. They write
`draw-attached.png`, `math-attached.png`, `base-attached.png` and corresponding
`*-result.json`. Draw and Math must leave generated fixture bytes unchanged.
Base may commit an embedded Firebird backup into its ODB when the model closes;
its record reports the actual `fixtureUnchanged` value and
`contentVerificationRequired=true`, preserving both SHA256 values. Base is not
allowed to claim byte immutability when those hashes differ. The mandatory
post-GUI `--verify-ui` engine gate reopens all six fixtures and checks their
original semantics, including Base's persisted SQL row. These
records explicitly keep `keyboardInputVerified` and `contentMutationVerified`
false; they do not establish keyboard editing, a Base connection or Java/driver
readiness. `results.json` records all six native attachments separately from the
three physical-input cases. No case establishes IME composition, and Linux helper
tests do not establish actual Windows GUI success. Failure screenshots/records
remain failure evidence even if earlier cases passed.

The GUI harness attempts all 13 independent cases (home, six existing documents,
six blank documents), preserving each case's strict checks and owned cleanup.
A failed case does not stop later processes/fixtures from being observed.
`results.json` retains the failed function's evidence and exception, lists failed,
missing or duplicate cases, and reports successful module claims only for passing
cases. Any failure or incomplete coverage produces `success=false` and process
exit 1; the validated-package gate is unchanged.

After existing-document checks, all six Office modules also launch with
`--module MODULE` and no file argument. Each blank document must attach under the
Suite panel, retain its OpenGeul title, avoid external Office windows, produce
`new-MODULE-attached.png` / `new-MODULE-result.json`, and close along with its home
with process exit 0. The first five cases perform no typing or saving and claim
no content mutation. All six successful cases are listed separately as
`newDocumentModules` in the aggregate report.

New Base additionally proves the database survives its private profile cleanup.
The harness physically focuses the unique shell-owned Korean File menu and sends
Ctrl+S. It requires the exact `OpenGeul Base — 다른 이름으로 저장` native dialog,
launched shell PID, document HWND owner, unique filename Edit automation ID `1001`
and Save button ID `1`. It physically types the fresh
`fixtures/New-OpenGeul-base.odb` path and clicks Save; existing fixtures are never
overwritten. The saved ZIP must have the pinned database mimetype
`application/vnd.oasis.opendocument.base` (see
[LibreOffice 26.8.1.1's database constant](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/include/comphelper/documentconstants.hxx#L51)), valid `content.xml`
and the embedded Firebird connection. After normal close and process/profile
cleanup, the same file must still exist and pass validation. Evidence includes
`new-base-save-as.png`, `new-base-saved.png`, saved-file SHA256/size and
`newBaseSaveAsVerified=true` / `savedFileSurvivedCleanup=true` only after success.

The explicit-discard helper remains independently guarded by exact dialog
identity, heading and Korean button text. It is never a fallback in the New Base
Save As case: a save failure, unexpected selector/dialog or subsequent discard
prompt fails that case. The harness does not clear modified state, auto-dismiss
arbitrary dialogs, or claim Base SQL/keyboard-content editing from this save test.

After the GUI has saved and closed each document, run:

```powershell
& "$suite\Office\program\python.exe" "$repo\suite\e2e\engine_smoke.py" --suite $suite --output $evidence --verify-ui
```

This writes `ui-engine-{module}.json` and `ui-engine-verification.json`. Both the
original marker and expected suffix must persist. `guiVerified` remains false in
these engine reports: child-HWND ownership, physical input, focus and the actual
save action must be established separately by the GUI harness. The supplied Linux
headless runtime has no pyuno and does not establish packaged Windows engine or
GUI success.

`korean_ui_smoke.py` validates the four actual Tabbed native editors separately.
It retains a screenshot and the Windows UIA tree, then reads the instantiated VCL
accessibility objects through that exact Office process's existing private pipe.
The E2E-only reader verifies the retained PID's image, creation time and editor
HWND before and after collection; no product worker API is added. The pipe is
obtained from a bounded native query of only that retained process, passed to the
packaged Python through stdin, and recorded only as a SHA256 fingerprint.
The harness establishes the owned Suite foreground and physically focuses its
verified editor before observing native focus events. It sends no document text
or save command, and both fixture copies and their originals must remain intact.

The authoritative `*-accessibility.json` records UNO `AccessibleRole.PAGE_TAB`
(38) children of one real `PAGE_TAB_LIST` (39), live parent/object equality,
actual child-index round trips, VISIBLE/SHOWING state and positive rendered bounds
inside the verified Office HWND. Required Korean Home/Insert tabs must have
distinct actual child indices. Native window bounds use a scoped per-monitor-v2
DPI context on the collector thread, with verified restoration. Document/table
subtrees are not enumerated.
`*-os-accessibility.json` is a diagnostic snapshot and does not establish OS
screen-reader support. A `--probe-only` run never claims Korean UI verification.

This distinction addresses the pinned upstream Windows bridge's notebookbar
hierarchy: [the notebookbar is a border-window child](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/vcl/source/window/brdwin.cxx#L1948),
while [WorkWindow grafts only its menubar into accessible children](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/vcl/source/window/accessibility.cxx#L196).
The E2E reader uses the existing
[XVclWindowPeer XAccessible test property](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/toolkit/source/awt/vclxwindow.cxx#L1938)
on the actual notebookbar peer. For undecorated system-child windows the owned
WorkWindow's accessible parent may be null. The reader obtains the real
`TabControlUIObject` with `XUITest.getWindow(verifiedPeer).getChild`, then uses a
passive public focus listener to retain `FocusEvent.NextFocus`. `XUIObject.equals`
verifies that this next peer wraps the same underlying native VCL tab control.
The original focus is restored and verified, and the selected tab is required
to remain unchanged; no document content is edited. That peer's `XAccessible` supplies the actual native roles,
parents, child indices and rendered tab names. These are native UNO roles, not
MSAA role numbers; passing this UI gate does not certify that the upstream OS
accessibility bridge exposes the notebookbar.
