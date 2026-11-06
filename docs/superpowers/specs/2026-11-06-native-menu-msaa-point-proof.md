# Native menu point proof for the owned VCL popup

Status: implementation in progress; actual Windows qualification pending.

The pinned VCL File submenu has a logical accessible tree while its physical
floating window can expose only a UIA Pane. Preserve the observed global Pane
and its failed comparison with Save. Neither a shared PID nor a bounding box is
enough to identify a menu command.

Add an explicit proof method only when both of these channels succeed:

1. The global point is exposed by the exact native popup window. Verify the
   allowlisted popup class, engine PID/thread/generation, window rectangle,
   original document owner chain, physical DPI context, foreground and live
   original attachment before and after the observation.
2. The native File accessible object's `accHitTest` identifies the intended
   retained and freshly discovered UIA target. Require native File child ID zero,
   a non-null native `IAccessible`, a File round trip through
   `ElementFromIAccessible`, target positives and every existing role negative.

Keep the original global-UIA proof unchanged for controls that support it. The
new result must name its own method and retain the original global FALSE; it
must never relabel a Pane as Save or synthesize a runtime ID.

## Same-apartment call lifetime

Measure explicit MTA membership for the controller and worker. Preserve the
private client's original apartment and borrowed File/target references for the
entire call. Use a worker-local typed binder and numeric record; do not mutate
the parent probe's call state or use its UIA client concurrently.

Use the current UCRT `_beginthreadex` ABI with a retained `WINFUNCTYPE` callback,
not `Thread.start` or an unbounded join. Register its capsule before startup and
bind the returned HANDLE/TID/creation time to this controller process. Wait for
the actual native thread exit within the original action deadline. Synchronous
CRT/OS calls cannot be forcibly preempted; any late outcome is unknown.

The worker verifies and restores its own physical DPI context. All new raw COM
out/QI references and VARIANTs are released or cleared in the worker before
`CoUninitialize`. Borrowed parent references are never manually released. Fence
every exception and return normally from the callback so ctypes and the CRT can
complete their unwind. No `ExitThread` or `_endthreadex` call is made by Python.

A completed signal alone is insufficient. Admission requires native thread
exit, reference/VARIANT/DPI/COM cleanup, HANDLE release and a final deadline check.
Recheck the original ownership, target and physical point before input.

## Pending calls

Retain at most one unresolved capsule and prohibit further input or new scopes.
Never accept a late proof. After owned engine shutdown, use only the existing
cleanup remainder to confirm callback exit and release its resources. Unknown
cleanup stops the cohort.

An unresolved foreign callback must not outlive normal Python teardown. The
implementation needs a source-verified finalization fence that preserves closed
failure records and abandons only its own E2E controller process with a fixed
nonzero status. It must not terminate customer apps or claim resource cleanup.
If that fence cannot be established, the new method cannot be enabled.

The dedicated native-menu CLI installs the explicit and atexit self-only fence
after the original pywinauto/comtypes apartment selection. It then enables the
helper once and runs an input-free native thread startup/exit preflight before
opening a document. The matrix retains that numeric preflight, and the archive
consumer requires it. A default helper import or another E2E caller stays
disabled. The self-only exit fence does not prove wall-clock termination: Windows
can wait for pending I/O, and the CRT fallback can execute DLL detach. The runner
does not currently retain a separate controller HANDLE exit receipt, so an exit
code from this fence remains a failed gate, never cleanup proof.

Creator MTA and thread membership are measured before the private UIA client is
created, then checked again before and after the worker. The immutable helper
scope's PID, creation, parent/child and point numbers are retained separately and
joined to the original action scope. The worker's processBefore/processAfter
numbers describe its duplicated process HANDLE guards. The controller proves
the full live popup, attachment and target before and after the worker.

For an already admitted menu, a fresh physical File-header endpoint can refresh
the live UIA graph. Require the physical header to hit the exact original child,
then a fresh global File element to compare TRUE with the retained File and
FALSE with every other role. Walk the fresh element's actual parents to the
original bar and peer. Keep the first child HWND admission and initial Edit
contrast binding; do not retry a timed-out child mapping or replace anchors.
An obscured or hidden header cannot pass this method.

The narrow popup class candidate is `SALTMPSUBFRAME`, with `WS_POPUP` and
`WS_EX_TOOLWINDOW` and without `WS_CHILD`, as defined by the
[pinned Windows frame source](https://github.com/LibreOffice/core/blob/bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/vcl/win/window/salframe.cxx#L420)
and [class constants](https://github.com/LibreOffice/core/blob/bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/vcl/inc/win/saldata.hxx#L158).
Actual class matching is still unverified. Class/style and rectangle containment
are exposure conditions; they do not establish Save identity.

## Verification

Start with failing tests for MTA and ABI rejection, wrong File/child ID, failed
round trip, target/negative mismatches, HRESULT plus non-null output cleanup,
VARIANT cleanup, DPI restoration, late completion and unresolved callback exit.
Exercise the real native thread startup/wait boundary on Windows without UI
input. Keep synthetic and actual provider results separate. The original six
menu cases, view round trips and complete Suite acceptance gates remain required.
