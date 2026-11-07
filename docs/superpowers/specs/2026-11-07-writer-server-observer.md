# Writer server observation for an owned diagnostic session

This is the implementation contract. Portable checks do not establish actual
Windows compilation, capture, process retirement or Suite acceptance.

The observed failure is a numeric MSAA result: Writer can report no focused
accessible descendant while the original owned editor HWND has Win32 focus.
This diagnostic records the existing server branches. It must not seed a focus
cache, change event order, substitute another root, or make an acceptance gate
pass. A source build and a successful capture are separate results from a
working, distributable Suite.

## Build and distribution boundary

The family is `writer-server-observer-diagnostic`. It has its own source lock,
patch, receipt, engine archive, artifact name and runtime markers. The existing
ARM64 source workflow selects it only on
`work/opengeul-office-native-writer-observer`, for the first exact owner push.
It uses the existing runner and deadlines. Calc diagnostics and symbol mode
cannot be combined with this mode.

Both `UAccCOM` and `winaccessibility` must be rebuilt against the same private
sink ABI. The private sink ABI is version 2; the numeric shared-memory IPC is
version 1. Their versions are independent. Source inputs, patch results and
header payloads are authenticated before applying the patch.

The engine root and `program` directory carry Writer diagnostic markers that
bind the source, lock, wire schema and both DLL hashes. A staged Suite also has
a root marker. Normal payload verification and ordinary GUI test entry points
reject this family. No diagnostic receipt can set `fullEngineQualified`,
`acceptanceEligible` or `guiVerified` to true. Staging preserves the verified
normal baseline and its HWP, shell and worker bytes.

## Source and lifetime boundary

The service forwards a private atomic callback through its existing manager
relationship. It does not add a public COM interface, a reverse DLL import or a
new query on a protected getter. The getter entry records only its canonical
interface pointer and atomic facts before its original SolarMutex guard.
Protected values are read only after that original guard.

Setup runs outside the original map lock and has one resident-image winner.
Competitors return unknown without waiting. A failed setup never becomes an
earlier successful observation. Before Ready publication the actual sink image
is pinned for the diagnostic process lifetime. Before that pin, the existing
normal service-to-UAccCOM import is the bootstrap lifetime dependency; portable
source checks are not proof of the emitted Windows import table.

Binding uses the original map lookup, original AddRef and canonical accessible
interface. A claimed root is published once. Object, map and manager
invalidation take effect before recording admission checks. Invalidation cannot
read an unpublished root tuple. A different or invalidated root cannot be
silently rebound.

The recorder observes the existing getter branch and output tag, existing focus
assignments and parent propagation. HRESULTs, AddRef/Release ownership,
old-focus-unset-before-new-focus-set order and original control flow remain
unchanged. Observer code cannot replace an original exception or return value.

## Runtime and ownership boundary

Preparation has its own explicit bound and precedes runtime start S. This does
not claim that complete application startup takes 30 seconds. Immediately
before creating and arming the observation mapping, the controller captures S
once. Runtime deadline D is S + 30 seconds; observation cutoff is D - 5 seconds.
No later stage starts another 30-second budget.

The controller launches only a generated blank Writer session in a job assigned
at process creation. Only explicit NUL stdio handles are inherited. A fresh
child environment contains the required non-secret bootstrap values and the
private descriptor. The controller admits the original host, worker and engine
generations from that owned job, retains their HANDLEs, and validates the exact
original HWND, process, thread and attachment relationships before arming.

The original numeric MSAA observation runs in a separate creation-owned helper
job under the same runtime budget. Its existing read-only owner admission may
open the expected engine PID and check birth, image and HWND ownership. That
helper handle has no retirement authority. Cleanup and remote-retirement proof
use the controller's original retained engine HANDLE only.

A valid negative MSAA result can be a completed observation. It remains a
failed accessibility result. A timeout, partial result, malformed result or
unconfirmed helper exit cannot count as completed. The helper watchdog never
uses an unbounded pipe drain or thread join. Synchronous native calls themselves
are not claimed to be forcibly preemptible.

## Numeric completeness and cleanup

Rows contain closed event codes, artificial scope/thread ordinals, counts and
QPC samples. PID, birth, HWND, TID and nonce belong only to private ownership
bindings and mapping headers. No document text, input, accessibility Name,
Value, title, opaque COM address or raw exception is exported.

Reservation and active-admission retries are bounded. Contention loss,
overflow, reentry, invalidation and partial publication remain durable incomplete
facts. Each row commits last and is never reused. A decoder scans the entire
reserved range, including entries after holes. Scope stacks and QPC ordering are
checked within each non-reused artificial thread; reservation order does not
imply chronological order between threads.

Cleanup independently attempts admission closure, gate closure, snapshot,
owned-job disposal, retained engine exit observation, local unmapping and each
HANDLE release under the original D. Closed admission, active count zero,
local unmapping, job emptiness and a kill request do not prove remote retirement.
Only matching original retained identity, a signaled HANDLE and observed exit
within D establish that fact. Forced diagnostic disposal is not normal UI close.

Pre-arm, pre-bind and pre-Ready intervals remain unknown. Later Ready cannot
reconstruct earlier coverage. Other clients may also query the server, so a
captured server event is not attributed to the original helper merely because
it lies in the same time interval. Whole-original-interval coverage, original
client attribution and full Suite acceptance are never inferred from a
synthetic test or a complete numeric record.
