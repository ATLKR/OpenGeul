# One owned IME-close notification caller

## Evidence and decision

Run 40222649458 at 5452c543922d595e182d0041294a5e92ec8bef94 reached the
original composition case. ARM64 artifact 12611171727 (SHA-256
8188241af6135732c10de391f715b980726018af8ca2cfff10aee5915e3c5e48)
contains twelve complete correlated rows. Typed joint closure appears in
notifications 10/11 before first keydown 12. No owned 0x490 interval appears;
this is absence within coverage, not proof against every context path.
Forced cleanup now confirms original engine exit and handle release, while
graceful retirement and composition remain false. x64's four eligible 0x490
intervals remain open at both boundaries and its actual diagnostic passes.

The authorized CI diagnosis needs a concrete caller, not another general
trace. Use one stack at the existing first typed joint-close notification.
This is an implementation choice within the user's continuing CI diagnosis
authorization; it is not a product behavior correction.

## Approaches

1. Reuse the existing owned WH_CALLWNDPROC callback and bounded matched-module
   stack machinery. This avoids new callback lifetimes and samples the actual
   failing notification. Selected, subject to implementation review.
2. Subscribe to ITfCompartmentEventSink. Notifications do not guarantee that
   the setter remains on the stack; subscription adds unadvise/unload risks.
   Do not add it for this experiment.
3. Attach a native debugger at a setter. No existing verified CI debugger
   workflow is present. DbgHelp's isolated file-only resolver is not one.
   Do not install or expose a debugging service as part of this change.

## Bounded contract

Normal acceptance remains unchanged. In the existing opt-in Calc mode case,
arm only after command 3 successfully proves typed TSF and IMM open=1. Claim
at most one record: the first fully correlated owned WM_IME_NOTIFY entry
after ACK3 showing typed TSF open=0 and IMM open=0. Getter failures, partial
publication, reentrancy, foreign ownership, or expiry cannot qualify it.
Keep the original QPC deadline and original process-generation admission.

Append the record after the existing ABI prefix. Join it to the published
message and mode sequence. Retain only at most sixteen fixed-whitelist
module IDs/RVAs; redact unknown frames and erase temporary raw addresses.
Reuse the existing held plugin file identity and exact DLL/PDB qualification
for private plugin attribution. No symbol queries occur inside the hook.
Reuse the existing isolated thirty-second symbol worker outside the editor.
Do not expand its qualification fallback or export arbitrary symbol names.

Record one Boolean from HookCall's own wParam: whether Windows reports that
the current thread sent this message. This is not CWPSTRUCT.wParam. A true
value permits inspecting a synchronous delivery stack; it does not establish
that a visible frame changed the compartment. False cannot recover another
thread's sender stack. No extra input, mode writes, sleeps, retries, rights,
or process attachments are permitted.

## Interpretation and stopping rule

A qualified product callsite whose pinned source changes the relevant
context/mode can support a narrow behavior correction after independent
review. A mutex/pump frame identifies delivery context only. A system-only,
deferred, capped, unknown, expired or nonreproduced result is inconclusive
about the setter. Close this hypothesis after the one original case; do not
repeat it unchanged or broaden passive logging to compensate.

Both native architectures still require final-code full acceptance and the
paired unpublished delivery. This diagnostic can qualify neither.

Primary API contract: https://learn.microsoft.com/en-us/windows/win32/winmsg/callwndproc
