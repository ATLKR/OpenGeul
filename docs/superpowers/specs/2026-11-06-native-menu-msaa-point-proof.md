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
Require class/style and rectangle containment on every live observation. These
are exposure conditions; they do not establish Save identity.

## Verification

Start with failing tests for MTA and ABI rejection, wrong File/child ID, failed
round trip, target/negative mismatches, HRESULT plus non-null output cleanup,
VARIANT cleanup, DPI restoration, late completion and unresolved callback exit.
Exercise the real native thread startup/wait boundary on Windows without UI
input. Keep synthetic and actual provider results separate. The original six
menu cases, view round trips and complete Suite acceptance gates remain required.

## Source-qualified IA2 mode

Mode 4 has a separate source admission and numeric proof. The backend,
source-selected launch, menu callers and separate archive verifier are implemented.
Actual Windows qualification of this path remains pending. The existing global UIA, canonical IUnknown and
read-only diagnostic results keep their original meanings. In particular, a
canonical comparison that returned FALSE remains FALSE.

Source admission uses the architecture's tracked external runtime lock, an
authenticated normal Full source-build receipt and the exact engine ZIP. Join
the bundled provenance and complete payload inventory to that lock. Then join
both `program/UAccCOM.dll` and `program/winaccessibility.dll` in the authenticated
engine ZIP to the actual Office files and verified inventory. Require the pinned
core and reviewed accessibility source outputs. An MSI version string, a caller
Boolean, a diagnostic engine or an arbitrary replacement lock cannot qualify.
Keep the resulting immutable admission object alive through each measurement;
its bounded summary and digest identify the proof without exporting COM pointers.

The identity argument is limited to that admitted provider implementation and
the current owned process generation. Compare IA2 window/unique-ID tuples for
retained and independently discovered File and target objects, and the File
`accHitTest` result. Preserve all UIA role positives and negatives and the raw
global Pane comparison. Require File/target distinction, the original child
window domain, nonzero IDs, both post-call anchor getters returning `S_OK`, and
stable tuples while the references overlap. Negative signed IDs are valid.
Destruction and ID reuse remain possible; equal tuples from unrelated processes,
generations, source inputs or non-overlapping lifetimes are insufficient.

The worker records a candidate only. Controller admission additionally requires
the original popup exposure, physical point, attachment, retained process HANDLE
generations, source admission digest, all reference/VARIANT cleanup, native
thread exit and post-call ownership checks. The original canonical
`localIdentityKnown` and `localIdentityMatch` fields are not promoted. A signed
32-bit UIA HWND is normalized only after strict type/range checks; retain its raw
value and require the normalized value to equal the independently owned popup.

Every required observation uses fresh discovery and a separate retired capsule.
Each proof expires 1.5 seconds after its own capture and must be consumed before
expiry, inside the original five-second action deadline. These are per-action
and per-measurement limits; they do not establish a shared cohort deadline. Do
not renew a deadline, retry a failed measurement, reuse an expired proof for later
input or accept a partial set of pointer observations. Keep one
pending capsule at most, its duplicated HANDLEs and borrowed-reference keepalive,
and the existing controller exit fence. A pending or unknown outcome prohibits
the next action, activation or launch.

The caller seam is explicit and defaults off. A selected launch carries the
actual sealed admission through its original Popen and each later document/action
binding. Source preparation has its own bounded prelaunch budget; each later
measurement retains its original document/action deadline. Runtime metadata drift or changed provider bytes fails
without automatic re-admission. Archive verification uses a separate closed
mode-4 branch and fresh authenticated source admission; historical receipt time
checks cannot reuse a live proof as authority for new input. Neither a source
build nor a completed identity diagnostic proves a menu gesture or Suite
acceptance.


The x64 source recipe additionally requires six pinned native ATL consumer
transformations and twelve original/effective evidence members. Its normal Full
build receipt must retain verified inputs from the selected compiler's ATL header
and library, with bounded sizes, file generations and hashes. This prerequisite
is source-build evidence; it does not attest which DLL a live process loaded or
qualify a Suite UI gesture. The existing qualified ARM64 source receipt remains a
separate supported input.

Initial editor focus counters distinguish a live status prefix from the final
disposal snapshot. Prefix counters cannot prove that no later activation or
queued attempt occurred. Only a final snapshot joined to the retained original
process/window generation and independently confirmed retirement can establish a
complete zero count. If forced termination leaves no valid final snapshot, or
only a prefix is recovered, the outcome remains unknown. Collection reuses the
bounded numeric trace read; it adds no
focus, input, timer, native query or RPC.
