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

Add OpenGeul Home and HWP launcher actions to the six packaged native File menu XML
definitions during verified runtime branding. Preserve the original XML bytes,
including prolog, DOCTYPE, comments and existing menu order. New native menu
wrappers created by normal view transitions inherit the same default commands.
The worker validates current live commands and dispatch ownership without
writing frame settings, document UI storage or external user profiles. Do not
copy formatting menus into host controls or insert unbound XMenu items.

## Commands and lifecycle

- Native New/Open/Save/Save As/Close use the existing shell transactions.
  Cover AddDirect, OpenFromWriter and OpenFromCalc from the actual six menus.
- Display the HWP launcher as **OpenGeul 한글 시작**, distinct from Office Home's
  **OpenGeul 시작 화면**. Keep the exact allowlisted URL
  vnd.opengeul.office:new-hwp and the existing no-argument HWP launch for compatibility.
  This starts the existing HWP app; it does not create a blank document directly.
  A fresh instance of the pinned HWP app shows its own Home without a document
  path and has no new-document CLI flag. Its existing-instance callback returns
  for empty arguments without requesting a new document or window. See the
  [pinned argument handling](https://github.com/golbin/hop/blob/34bd15c97e0851627cb7f055042c5340198aeb7f/apps/desktop/src-tauri/src/lib.rs#L51-L55)
  and [HWP Home action](https://github.com/golbin/hop/blob/34bd15c97e0851627cb7f055042c5340198aeb7f/apps/studio-host/src/ui/home-screen.ts#L47-L83).
  A user creates a document inside that app.
  Do not add HWP to the six UNO document factories or alter the standalone engine.
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

After successful attachment, the UI thread clears loading and checks a pending
initial focus handoff before publishing native-menu readiness. Share the existing
owned focus checks with the user Ctrl+F6 route without synthesizing that route.
Only the original foreground document with agreeing Form/Panel focus, retained
process/window identities and no menu, capture, modal or close activity may hand
focus to its native child. A foreign foreground leaves the handoff pending without
changing focus. While pending, document activation or the original form's
WM_ACTIVATEAPP(true) may queue one UI callback after base message processing;
the callback must recheck all conditions after WinForms focus restoration. Mark
the handoff complete before its first native SetFocus call, including reentrant
callbacks. An already focused editor completes it without input. A different
owned control chosen by the user, changed attachment, disposal or successful
explicit Ctrl+F6 ends the pending handoff. Never accumulate callbacks or retry
from resize or status polling, and never activate a foreign or background window.

The menu harness records numeric focus observations before and after its own
maximize and after activation. At its first editor check, only the exact idle
owned host may await natural focus inside the original five-second action
deadline. Input still requires the original editor postcondition; foreign or
changed ownership, modal/menu state and ambiguous focus fail immediately. Later
editor checks keep their original immediate requirements. These observations
and initial screenshots do not prove that the chrome is unobstructed. Initial
Win32 focus observation creates no UIA client; create the private client once
at its first UIA use inside the same action deadline. Failed or closed clients
cannot be initialized again.

If taskkill returns 128 while the original retained shell is still pending,
observe that same Popen inside the existing five-second exit phase. Preserve
the original case failure and the forced-cleanup classification. Join the
cleanup receipt's PID, exit code and completed deadline to the actual retained
process observation; late or unconfirmed cleanup stops the cohort even if a
later poll sees an exit. The existing engine exit phase remains separate.

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

Standalone compiler prerequisites use a necessary nonsecret environment allowlist;
mock boundaries use synthetic environments. Keep failure receipts to fixed
stages and process/exit metadata, without environment maps, full commands or raw
diagnostic streams. Observe retained direct-child state before cleanup. Compiler
capture and cleanup waits share the original deadline with a cleanup reserve;
incomplete reader or handle cleanup remains an explicit failure rather than
qualification. This does not promise a hard real-time wall-clock bound on native
process creation or operating-system scheduling.

The new menu observer uses a private
[CUIAutomation8 client](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/legacy/hh448746(v=vs.85)).
Set and verify its connection and transaction timeouts from the remaining
original action budget before provider queries, then release the client along
with retained handles and restore DPI. Do not change pywinauto's shared client
or treat a clock check after an unbounded provider call as a timeout mechanism.
The documented provider timeout and post-call rejection are not a hard real-time
operating-system scheduling guarantee.

Keep the raw count of visible shell-owned UIA MenuBar nodes. A standard Windows
system menu may be excluded from the client-menu admission decision only through
live independent OS evidence: the original HWND's OBJID_SYSMENU geometry, an
exact original-window physical hit with HTSYSMENU, and a fresh UIA point element
that compares equal to the counted bar. Require distinct engine-bar and shell-root
elements, bounded non-client ancestry and unchanged process/window/attachment
identities before and after the observation. Record verified-system, client and
unknown counts separately; a client or unknown bar still blocks input. Neither a
caption ancestor, a label, an empty runtime ID nor a corrected count proves a
system menu. Unsupported APIs, unavailable negative anchors or ambiguous/stale
comparisons fail closed. These native queries keep the original action budget
and post-call rejection; they add no hard real-time scheduling guarantee.

Writer and Calc must each keep the original document through Print Preview on
and off, then full screen on and off. Use the real native File command and one
counted native shortcut per transition. Observe fixed chrome without document
content or additional input: allow the old display mode to settle inside the
original five-second deadline, then require three continuous seconds in the
requested mode. Ownership, generation, foreground, readiness and ambiguous UI
fail immediately. The survival interval alone does not prove a completed status
RPC. In the existing diagnostics mode, the owned shell exports one positive
64-bit property containing version1 and two 28-bit started/completed sequences.
Publish the start before the actual status request and completion only after its
native-menu reply passes the original checks. Require a completion greater than
the first matching view sample's started sequence, alongside the continuous
three-second hold. This excludes an already in-flight request and adds no RPC
or input. Missing, invalid, decreasing or failed-publication evidence cannot
qualify the view. After restoring the view, check Home/HWP and the core native
File items and retain the existing
Home/save/cancel/close outcomes. The archive consumer must require both physical
view cases rather than accepting an earlier six-menu-only success report.

The HWP entry reuses the shipped HWP launcher. Menu availability and its routed
command do not prove that HWP created a new document. A physical HWP launch test
needs a new exact process generation, retained handles and graceful shutdown;
it must not fall through to the Office shell's tree-force cleanup. Preserve the
standalone HWP distribution and report unexecuted HWP outcomes explicitly.
The runner and independent archive consumer share the same source-bound launcher
proof. Join its native menu action to the original Writer/shell/Office generation,
an empty pre-launch child census, the exact new HWP executable/creation time and
one retained HANDLE through normal exit0 and release. Missing or boolean-only
summaries cannot replace this proof. An unretired HWP process stops the cohort
and suppresses shell tree cleanup; other modules are then unexecuted. This adds
no Office engine generation and leaves the original83 gate unchanged.

After the existing native accessibility diagnostic restores the retained VCL
focus window and confirms selection preservation, it may record only an
allowlisted Writer edit-window type code and fresh equality result. Do not read
that window's state/text or create accessible document objects for this optional
diagnostic. Unknown types and query errors remain numeric observations and do
not replace the independent OS accessibility gate or establish its failure cause.

If the original Writer OS focus observation fails, a separate child may later
query a fresh root through AccessibleObjectFromWindow, IServiceProvider and the
documented IAccessible2 QueryService. Preserve both original MSAA observations
before this optional diagnostic. Record only closed numeric outcomes, original
HWND/process generation checks and reference cleanup; successful bridge access
does not identify the earlier COM object, its DLL or a working focus cache.
Keep the original 45-second budget and at most eight seconds for this child,
including a cleanup reserve. Use a bounded file and timed process waits rather
than pipe-reader joins. Late, unretired or cleanup-failed results remain unknown;
retain at most one pending child/file pair and block further diagnostic launches.
Synchronous OS calls cannot be forcibly preempted. This diagnostic never changes
the original accessibility decision or qualifies acceptance.
