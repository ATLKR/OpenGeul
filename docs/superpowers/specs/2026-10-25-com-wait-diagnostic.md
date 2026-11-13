# Bounded synthetic STA dispatch experiment

Run 40160669513 at 001cdd73e234000b94ea6320b54734ce440623a6 mapped the
two failing ARM64 traces' SAL return RVA 406484 to exact export
`osl_waitCondition`, range [406400,406556), with a preceding call at 406480.
The archive size/hash match runtime.arm64.lock.json. Both native unit suites
passed 2397 tests (36 skips), and both shell suites passed 92/92. Only the
intentional nonacceptance guard failed. The mapping receipt archive is 586 bytes,
SHA256 2eade3735b1e0938d3732b02ee88de7c74e35f6c40866c35cd738933d1047a8f.

Pinned source bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1 calls
`CoWaitForMultipleHandles(COWAIT_DISPATCH_CALLS, timeout, 1, handles, &index)`
through the SAL helper. This identifies a function, not the actual apartment,
message filter, caller, or cause of capture remaining owned.

## Finite hypothesis ledger

| Proposition | Evidence / remaining discriminator |
|---|---|
| Mouse-up was never retrieved, or preceded recapture | Contradicted by the owned event sequence in both failing ARM64 cases. |
| Coordinate delta alone explains capture failure | Contradicted by a passing x64 case with the same client-coordinate delta. |
| The failed retrieval occurred through the SAL condition wait | Exact export/unwind mapping confirms the function. Its caller and runtime COM context remain unknown. |
| The pinned wait can remove an owned queued mouse-up without WndProc delivery | Test below; currently unverified. Posted-message behavior cannot prove physical-input equivalence. |
| Broader window dispatch changes that synthetic behavior | Fixed counterfactual below; currently unverified. A result does not establish safe LibreOffice reentrancy. |

## Experiment

Use the existing net8.0 shell-test executable in explicit diagnostic mode,
after existing owner-push, first-attempt and exact-source admission. Ordinary
shell tests run pure receipt/ordering/classification contracts only.

Run exactly three fresh child processes: ordinary PeekMessage/DispatchMessage,
the pinned COM flags 8, and test-only flags 24 (8 plus
COWAIT_DISPATCH_WINDOW_MESSAGES). Each child owns one dedicated STA thread,
one hidden never-shown window, and one unsignaled event. Explicitly initialize
COM, verify apartment, and balance initialization. No custom message filter.
Post exactly one tagged WM_LBUTTONUP to that window before entering its arm.
No sleeps, retries, extra posts, physical input, foreground/capture APIs,
window enumeration, screenshots, Office hooks, or desktop configuration.

A thread-local WH_GETMESSAGE hook records only that exact owned message.
The real WndProc independently records delivery. Record flags including
PM_REMOVE|PM_NOYIELD, QPC phase ordering, and bounded counters. No mutation,
filtering, callback pumping or exceptions across unmanaged boundaries.
Root delegates, guard reentrancy, and cap observations at 32 rows.

Each child has one five-second deadline for setup, experiment and immediate
post-wait drain. COM receives at most 1000 milliseconds from the remaining
budget; its sole event is never signaled, so only RPC_S_CALLPENDING is expected.
Unexpected S_OK or other HRESULT invalidates the fixture. The ordinary pump
and labelled post-wait drain each have at most 256 retrievals. A call-phase
marker alone does not prove API entry; matching same-thread callbacks during
the synchronous call interval show nested callback execution.

Unhook, destroy the window on its owning STA, unregister its class, close the
event, and uninitialize COM even after failure. The outer parent retains each
exact Process object, enforces one ten-second watchdog including startup and
bounded live output reads (16 KiB), and terminates only that child on failure.
At most two additional seconds are for exit confirmation only. An unconfirmed
exit stops the series. No PID reopening, broad process termination or changes
to existing Office cleanup. These are separate fixture budgets; all original
Office preparation and editor deadlines remain unchanged.

## Interpretation and implementation boundary

The ordinary control must record exactly one removal and one real delivery.
A COM arm with removal during its wait and no delivery through the bounded
drain supports only removal without observed delivery in this synthetic test.
Delivery during the wait or later drain is a valid alternative result, not a
failed product regression. Do not encode expected COM suppression as an
acceptance assertion. Instrumentation, identity, bounds, deadline or cleanup
failure is a fixture failure and cannot support a mechanism conclusion.

This experiment contains no outgoing RPC or physical mouse queue behavior.
It cannot resolve the original capture/IME failure by itself. Broader dispatch
may introduce reentrancy, while removing COM dispatch may deadlock callers.
No production wait flag or input admission changes are included. A behavior
correction requires a demonstrated defect and review of those consequences.
No identical rerun follows an inconclusive result.

Retain only the bounded JSON receipt. The explicit diagnostic workflow skips
engine/package/Office desktop work, preserves every existing GUI mode's guards,
and deliberately prevents package qualification. Native x64 and ARM64 run the
same final source. Local PowerShell Add-Type checks standalone C# syntax and
pure contracts on .NET 9; it is not Win32 execution or net8 project validation.

## Primary references

- [Pinned SAL helper](https://github.com/LibreOffice/core/blob/bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/include/systools/win32/wait_for_multiple_objects.hxx)
- [COM wait semantics](https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/nf-combaseapi-cowaitformultiplehandles)
- [COM wait flags](https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/ne-combaseapi-cowait_flags)
- [MessagePending limitations](https://learn.microsoft.com/en-us/windows/win32/api/objidl/nf-objidl-imessagefilter-messagepending)
