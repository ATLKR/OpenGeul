# Unified Office Menu Implementation Plan

> **For agentic workers:** Use subagent-driven-development or executing-plans task by task. Preserve the assigned checkout; do not create worktrees.

**Goal:** One native Office menu surface with required integration and explicit session failure.

**Architecture:** Prepare the retained native frame's real menubar, including
packaged native OpenGeul Home/HWP launcher entries. Remove the host File strip entirely;
keep shell-owned document transactions behind native commands.

**Tech Stack:** Python/PyUNO, C# .NET8 WinForms/Core, existing Windows E2E.

**Spec:** docs/superpowers/specs/2026-11-06-unified-office-menu-design.md

## Global Constraints

- Native full menus and Tabbed formatting remain; there is no shell-menu fallback.
- Preserve Calc pending input, Base temporary ODB, peer names, strict ownership and retained cleanup.
- Native preparation is required before accepting attachment or editable display.
- Preserve unsaved data and cancel vetoes during runtime-failure safe close.
- Unsupported semantic aliases are disabled, not relabeled wrong behavior.
- No external publication, access expansion, input replay or weakened admission.

## Review Focus

- A valid HWND without a usable native menu rejects only its owned session.
- Menu failure must not mask successful disk save or prevent close-status reads.
- Home/current Close/application Exit have distinct cancel-safe scopes.
- HWP is explicitly accessible but excluded from UNO attachment and Office shutdown.
- Native UI proof and six new process generations do not reuse legacy evidence.

### Task1: Native menu and command integration

**Files:** worker/native_menu.py, worker/native.py, worker/dispatch.py,
worker/session.py, runtime_branding.py and their Python tests.

**Interface:** attach requires nativeMenuReady=true with existing module and
parent/child handles; idle status validates menu; close/save use original document
status independently. Native events add home/exit and exact new/hwp permission.

- [x] Observe failing readiness, ownership, UI configuration, unsupported alias,
  routing and failure-after-edit tests against real worker/dispatcher code.
- [x] Prepare the native menubar once, validate the actual frame/resource/File
  command set and branded Home/HWP defaults, then observe passively.
- [x] Set four Tabbed HasMenubar flags; retain other modes and all formatting.
- [x] Preserve close/save/Calc/Base transactions and run targeted tests/review.

### Task2: Host lifecycle and dialog ownership

**Files:** shell/OfficeDocumentForm.cs, shell/HomeForm.cs,
shell/Core/DocumentMenuSurface.cs, shell/Core/WorkerClient.cs,
shell-tests/DocumentMenuSurfaceTests.cs and Program registration.

- [x] Write bound-ready/failure tests first; execute C# checks when the compiler
  is available and clearly report any unexecuted platform-dependent checks.
- [x] Remove the File strip, require the native status and export a numeric
  native-menu selection property as a hint only, not UI proof.
- [x] Reject failed attachment with owned release/error/form close. Use original
  cancel-safe close for runtime loss, never discard to force termination.
- [x] Connect document-owned Open and Home/Exit callbacks without introducing
  document Form ownership or fake keyboard focus restoration.
- [x] Verify Core behavior on Windows x64/ARM64 (121/121 at68bc25a).
- [x] Add an explicit guarded initial focus request after loading completes and
  before native-menu readiness; keep it separate from user Ctrl+F6.
- [x] Verify the shared focus core's 32 local cases, including 14 additional
  pending/activation/lifetime cases after the first 18-case implementation;
  keep native adapter compilation and host syntax checks separate from Windows UI.
- [x] Preserve pending initial focus when the foreground belongs to another app.
  Retry only from the pending document's activation, through one queued callback
  with fresh ownership/focus checks. Complete before the first native focus call;
  cancel on another owned control, changed attachment, disposal or successful
  explicit Ctrl+F6. Do not retry from resize or status polling.
- [x] Wake that same pending queue after the original form's positive
  WM_ACTIVATEAPP base processing, preserving owner/HWND fences and coalescing.
  Verify the 34 Core/source cases and 20 extracted-method synthetic cases;
  actual Windows activation still needs separate proof.
- [ ] Verify Windows-targeted WinForms compilation and UI; report actual limits.

### Task3: Native UI and final integration

**Files:** e2e/owned_native_menu.py, e2e/native_menu_smoke.py,
windows_smoke.py, home_routing_smoke.py, lifecycle_smoke.py,
related tests, office-suite.yml and suite/README.md.

- [x] Observe failing recipient tests, then implement a separate strict native
  menu/popup/DPI/hit/input-count proof with the original finite deadline.
- [x] Replace product menu triggers with native-only actions. Reuse shell picker
  and disk/cancel outcomes only after proving the new physical trigger.
- [ ] Check six modules, Escape/outside/repeat/keyboard/focus, Save As cancel,
  Base first save, Calc pending input, HWP/Home access and Exit cancellation.
- [ ] Keep six menu generations in a separate diagnostics root with complete
  original-engine exit/cleanup proof; do not exempt the existing83 gate.
- [ ] Run final Python/Core/static/compile checks and independent diff review;
  rerun affected checks after review fixes before a final authorized Windows run.
- [ ] Report exact-source run outcomes/screenshots or the exact blocker, keeping
  old RC failures and unintegrated proposals out of new success claims.

## Review follow-up after the first Windows run

- Preserve baseline6a6695f and its actual Windows fixture failure separately.
- Use absolute, owned temporary test roots on Windows.
- Preserve C# execution and explicit menu-not-executed failure evidence even if
  Python prerequisites fail; neither failure may qualify delivery.
- Allow normal same-owned-frame controller changes and native display modes.
  Keep foreign ownership, model, resource and dispatcher failures fatal.
- Brand the six default menu XML resources so normal native wrapper recreation
  retains Home/HWP without polling-time writes or lost native functionality.
- Verify complete live menu observations across a bounded view/resource change;
  do not turn a legitimately disposed old wrapper into a permanent failure.
- Actual preview/full-screen round-trip UI behavior still needs Windows evidence.
- [x] Add source-bound physical Writer/Calc preview and full-screen round-trip
  checks, keeping old display-mode settling inside the original input budget.
- [x] Require the new two-view-case plan in the independent archive consumer;
  preserve the original83-generation verifier and all process-exit guards.
- [x] Connect each view hold to a completed status request started after its
  first matching sample, using the existing diagnostics mode and numbers only.
- [x] Record passive focus observations around harness maximize/activation and
  await only the exact original idle host during the first editor check, inside
  its unchanged five-second deadline. Preserve later focus checks and input plans.
- [ ] Run those view cases on Windows after the final reviewed source is pushed.
- [x] Label the existing HWP launcher **OpenGeul 한글 시작**, keeping its internal
  new-hwp URL and no-argument launch. Direct blank-document creation is unsupported;
  the pinned HWP app starts at its own Home and provides its own New action.
- [x] Add a physical native HWP launcher scenario and a shared runner/archive
  validator. Require a fresh exact HWP process, retained live binding, visible
  owned main window, one normal close and same-handle exit0/release. Reject old
  reports without this proof and suppress tree-force cleanup while HWP is unretired.
- [ ] Execute the HWP launcher scenario on Windows. A visible main window is
  not a certified HWP Home UI or a newly created document.
- [x] Add a separate failure-only Writer root IA2 capability diagnostic with
  numeric ownership, HRESULT and reference cleanup evidence inside the original
  time budget. Preserve the original OS focus observations and decisions.
- [ ] Execute the root diagnostic on Windows. Fresh later bridge access cannot
  establish the provider identity or focus-cache state of the earlier failure.
- [x] Defer the private UIA client until its first use, preserving the original
  timeout and identity checks. Keep initial Win32 readiness independent of UIA.
- [x] Join the return128 retained-shell wait to the menu cohort's cleanup gate.
  Preserve unknown/late outcomes and the separate engine exit phase.
- [ ] Verify these startup, cleanup and diagnostic changes on Windows; local
  regression results do not qualify the remaining native menu or OS focus gates.
