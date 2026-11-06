# Unified Office document menus

## Required experience

LibreOffice's complete native menubar is the single document menu surface.
Remove the separate OpenGeul File strip; do not restore it on any failure.
Keep the native Notebookbar formatting UI, including its native File tab.
A failed connection or menu integration is an explicit session error.

Copying native menus into WinForms would duplicate dynamic module commands and
accessibility state. Using only Notebookbar File tabs would require separate
paths for the four Tabbed modules and Math/Base. The selected native menubar
uses the existing WorkWindow/SystemWindow peer and native menu manager.

## Native integration

Before accepting attachment, prepare the same retained frame's actual menubar,
require showElement success, verify the UI element's frame/resource/type and
real File popup with module-specific New/Open/Save/Save As/Close commands.
HWND attachment alone is insufficient. Preserve the exact peer name,
controller/model ownership, parent/child validation and retained process cleanup.
Set HasMenubar for the product's four default Tabbed modes during runtime
branding; do not change Math/Base mode or an external LibreOffice profile.
After preparation, status observes passively rather than resetting open menus.
A normal native controller/view replacement is allowed only while the original
frame, peer, document model and interceptor remain owned. Full Screen and user
menu visibility changes do not themselves indicate lost integration.

Add OpenGeul Home and New HWP actions to the six packaged native File menu XML
definitions during verified runtime branding. Preserve the original XML bytes,
including prolog, DOCTYPE, comments and existing menu order. New native menu
wrappers created by normal view transitions inherit the same default commands.
The worker validates current live commands and dispatch ownership without
writing frame settings, document UI storage or external user profiles. Do not
copy formatting menus into host controls or insert unbound XMenu items.

## Commands and lifecycle

- Native New/Open/Save/Save As/Close use the existing shell transactions.
  Cover AddDirect, OpenFromWriter and OpenFromCalc from the actual six menus.
- vnd.opengeul.office:new-hwp is an exact allowlisted action launching the
  existing HWP editor. Do not add HWP to the six UNO document factories.
- StartModule returns to the existing Home only after the current document's
  normal asynchronous close succeeds. Cancellation keeps the document.
- Quit/Exit request Home's existing sequential Office-document/application close,
  with Save/Discard/Cancel protection, rather than closing only the current form.
  Standalone HWP processes remain outside this Office shutdown/save scope.
- Unsupported commands must not pretend to perform another action. Disable or
  omit SaveAll/SaveACopy and any retained semantic aliases that are not actually
  implemented; disclose the precise supported scope.
- Document Open/picker/error ownership belongs to the invoking document, while
  Home remains the central document/window coordinator. Do not assign WinForms
  owners to document forms or change Calc pending input and Base temporary ODB.

## Failure and focus

A menu-preparation failure rejects attachment, clearly reports the error and
releases only the failed owned session before closing its form. Do not expose an
editable document before this required integration succeeds. Never recover by
restoring a shell menu. Keep original files, other documents and other apps safe.

Runtime integration loss reports an error once and invokes the original safe
close transaction. Preserve document status/save results independently from the
broken menu so saving and close preparation remain possible. If saving fails or
the user vetoes closing, do not discard unsaved data or kill the process; retain
an explicitly failed session and its resources without a substitute menu.

Escape, outside click, repeated opening and keyboard navigation must return to
the original native editor naturally. No synthesized Ctrl+F6, foreign activation
or weakened foreground/capture/engine-generation guard is allowed.

## Validation and scope

Write behavioral tests before product changes, distinguishing executed Python
RED/GREEN, C# tests/compilation and actual Windows UI. The native menu requires a
separate engine-owned recipient/popup proof; old WinForms menu evidence does not
qualify it. Verify six modules, menu save/pickers/cancel/close/Home/HWP access,
module/document switching, application Exit cancellation, keyboard focus and
screenshots. Isolate six new menu-smoke generations from the existing83 gate and
verify their original process lifetimes separately. Earlier RC failures remain
separate from this change. No main merge, release/Store/customer distribution,
paid runner, credential replacement/access expansion or stopped artifact retry.

The new menu observer uses a private
[CUIAutomation8 client](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/legacy/hh448746(v=vs.85)).
Set and verify its connection and transaction timeouts from the remaining
original action budget before provider queries, then release the client along
with retained handles and restore DPI. Do not change pywinauto's shared client
or treat a clock check after an unbounded provider call as a timeout mechanism.
The documented provider timeout and post-call rejection are not a hard real-time
operating-system scheduling guarantee.
