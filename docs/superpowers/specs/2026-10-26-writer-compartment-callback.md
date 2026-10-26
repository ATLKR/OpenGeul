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

Contracts: [OnChange](https://learn.microsoft.com/en-us/windows/win32/api/msctf/nf-msctf-itfcompartmenteventsink-onchange),
[UnadviseSink](https://learn.microsoft.com/en-us/windows/win32/api/msctf/nf-msctf-itfsource-unadvisesink),
[module pinning](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulehandleexa).
