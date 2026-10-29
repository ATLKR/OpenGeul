# One owned Writer compartment callback

Run 40252077899 at 6dc1ea4 passed both Base cases and both complete GUI passes
on each architecture, but did not qualify paired delivery. ARM64 Writer again
failed first composition: its complete 14-event trace showed open1 on the first
keydown, then open0 approximately 197.6 ms later. Calc's successful composition
and unsuccessful save are a different observation, not the same proven cause.

Question: does the first post-ACK3 OPENCLOSE callback contain a matched product
setter callsite? OnChange is a post-change notification; its stack is not
guaranteed to contain that setter. Internal notification frames alone are
inconclusive. This is one Writer case, not a cohort or retry.

The retained failing Writer case had an empty original TSF origin. Require that
same origin before installing the sink; a different origin stops the experiment.
This reuses the existing empty-origin engine-retirement proof and its original
budget, rather than adding a new post-shutdown allowance to another path.

Install one sink on the already enumerated owned-thread OPENCLOSE compartment
inside command3's original lease, after typed open1 and before ACK3. Obtain its
ITfSource, pin the callback DLL by its own address before Advise, and revalidate
typed open1. Keep diagnostic references and receipts separate from mode receipts.
Do not create a manager, select a global compartment, set any value, add input,
retry focus, inspect unrelated windows, or change any original deadline.

Claim the first eligible post-ACK3 callback before getters. Require immutable
original PID/TID/HWND/process generation, original QPC deadline, no active command
and no reentrancy. Read only this compartment, require VT_I4 zero and successful
VariantClear, and capture at most the existing 16 whitelist module/RVA frames.
Publish last. Failure is inconclusive, never replaced by a later callback.
Return S_OK on diagnostic rejection; do not unsubscribe inside the callback.

At command4 entry disable capture and unsubscribe on the owning thread before
profile restoration, using its existing one-attempt, at-most-five-second budget.
Require S_OK, no active callback and balanced owned reference release. Unknown
disconnect must fail restoration. If command4 cannot run or disconnect is
unproved, retain disabled sink/source/native mapping and callback code until
the existing retained engine's confirmed exit. Record termination separately
from unsubscribe; unproved exit remains a teardown failure. Controller unmapping
does not invalidate the target's separately mapped view. The module pin is a
diagnostic process-lifetime lease, not persistent access or a product change.

Use the existing exact ARM64 plugin DLL/PDB pair, existing function whitelist,
owner-push admission, first-attempt privacy gate and sanitized failure retention.
No engine rebuild, console probe, debugger or new credentials. A complete matched
setter callsite plus pinned source evidence is needed before a behavior edit.
Missing transition, partial/rejected trace, reentrancy, expiry, frame cap,
unmatched origin, different failure, nonreproduction or unproved cleanup ends
this experiment without an unchanged rerun.

Implementation order: reproduce lifetime failures with portable fault injection;
implement the lease and actual Windows adapter; test ABI/publication/controller
retirement and all selected workflow prerequisites; obtain independent review;
run frozen validation; only then one targeted native diagnostic. Existing full
acceptance remains mandatory for a final corrective commit and paired delivery.

## Numeric retention for a new execution

Run 40743213587 at `15d4b351d9604607ac94c3a7662c208c4c1bfc7d`
passed every x64 acceptance gate. ARM64 Writer and Calc failed their first
composition. Their retained IMM summaries contain closed samples and end with
open0/native1. Counts do not recover the complete sample order, current TSF
values, full conversion mask or the code that changed the state. Earlier
joint-close experiments are not measurements of this execution.

Keep the original one-Writer case, sink lease, setters, input and deadlines.
Transfer its final case record in memory after the original teardown. Run the
existing strict first-key/callback/retirement selector unchanged, then the
existing file-only symbol resolver once in the controller. Do not persist the
full case, formatted traceback, keyboard sidecars or screenshots. The existing
generated-fixture semantic-reader IPC remains outside the retention allowlist.

Retain only a closed numeric callback report. Bind its public source/run to the
first owner push and native ARM64, and keep absence distinct from measured zero.
Allow bounded lease/API receipts, original generation and clock joins, coded
failure locations, whitelisted module/RVA frames and pinned public DLL/PDB
identity. Exclude key values, input text, message payloads, paths and arbitrary
symbols. Callback publication and symbol resolution remain separate from setter
attribution and process retirement; no diagnostic report qualifies acceptance.

An explicit opt-in may publish one bounded numeric check notice, at most 32 KiB.
Failure to project or publish must preserve the original case result and
cleanup. The workflow uploads the numeric JSON only. It must not retain the
private directory or replay previously denied artifact/log data through notices.

Contracts: [OnChange](https://learn.microsoft.com/en-us/windows/win32/api/msctf/nf-msctf-itfcompartmenteventsink-onchange),
[UnadviseSink](https://learn.microsoft.com/en-us/windows/win32/api/msctf/nf-msctf-itfsource-unadvisesink),
[module pinning](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulehandleexa).

## Bounded follow-up after the first callback filled 16 frames

Run `40820145615`, source `07e752f`, reproduced the original Writer first-input
composition failure after the normal ARM64 prefix. Its first claimed callback
read typed zero and unsubscribed with five references acquired/released and no
active callback. The 16-frame buffer was full, so the existing decoder correctly
kept it inconclusive. An unknown frame is not itself a completeness rejection.
Plugin status1 verifies the separately loaded plugin's file origin; it does not
establish a product frame or setter. No product frame in this capacity-limited
sample proves no absence. The symbol worker did not run.

The next observation raises only the compartment record to 64 frames. Config
version2 and the controller/native StateSize check bind its 784-byte layout.
The shared capture helper accepts only 16- or 64-slot row types; caller/ASCII
records retain 16 slots. Capture the same first eligible callback once, with
no skipped frames, extra callback, recapture or retry. A count of 64 remains
inconclusive. Microsoft documents this count within the modern
[CaptureStackBackTrace API limit](https://learn.microsoft.com/en-us/windows/win32/debug/capturestackbacktrace).

Closed numeric schema2 retains the fixed 64-frame capacity and at most 63
selected/resolved product RVAs. A separate fixed compartment resolution profile
uses the existing file-only worker; ordinary resolution retains its 32-RVA
limit. DLL/PDB identity, ordered RVA joins, whitelist tags, cleanup, watchdog and
remaining budgets remain mandatory. Legacy closed schema1 keeps its original
16-frame boundary. The public notice/JSON remains limited to 32 KiB.

The old closed record did not expose command1's original typed state, and the
selector returned for the capped callback before checking first-key IMM state
and QPC order. Schema2 therefore projects the already retained command1 typed
receipt and first-key open/native/owner/QPC values even for an unselected case.
It adds no target getter and retains no key value, message payload or input text.
Missing data stays distinct from measured zero. Selection still requires the
original EMPTY state, original input signature, one owned first key with open1
and native1 after ACK3, and that key before the first eligible callback's zero.

Writer's callback deadline remains the QPC translation of its original 60-second
setup budget. The observed baseline-to-deadline interval was 50.7941848 seconds;
the callback began 0.3569066 seconds after baseline. Command3/4 retain their
existing maximum-five-second budgets. Save/Calc-dispatch 30-second budgets and
the file-only worker's 30-second budget are separate phases; this first-input
failure never entered save. It is not evidence of a whole-case 30-second bound.

No product engine binary or pinned normal engine/PDB input changes. This observer
source change requires no additional native engine source build. Capped or
otherwise incomplete evidence still ends the experiment without an unchanged
rerun, and every report keeps caller attribution and acceptance false.
