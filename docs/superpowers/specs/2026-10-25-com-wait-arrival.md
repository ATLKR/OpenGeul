# One controlled during-wait arrival experiment

Run 40162807902 at 7793ee8693ef7ce859ea634f949fcacfdb20cab6 completed
with native unit tests 2404/2404 (36 skips) and shell tests 93/93 on x64 and
ARM64. Only the deliberate nonacceptance guard failed. The platform-analyzer
correction is verified. All six synthetic cases have valid QPC ordering, no
overflow/reentrancy/callback errors, and successful native cleanup.

Both ordinary controls delivered once. Both pinned flags 8 and counterfactual
flags 24 retained the prequeued posted mouse-up through CoWait and delivered
it only during the subsequent ordinary drain. This contradicts suppression
of this prequeued posted stimulus and gives no evidence for changing production
dispatch flags. It does not reproduce hardware-input classification, the actual
Office caller/filter, or its capture failure.

## Finite next discriminator

Run ONE additional fixed timing experiment: enqueue the same single synthetic
mouse-up from an exact-owned rendezvous callback while the synchronous wait is
active. The original physical down/up pair may itself already have queued its
up before CoWait, so neither result establishes timing as the Office cause.
If this newly enqueued item is also deferred, close timing alone as an
explanation for the tested posted-message behavior and stop posted-message
variants. Physical queue, caller and filter questions require different evidence.

Posting from a producer after a SendMessage acknowledgement races the wait's
return. Instead, the receiving WndProc posts the sole mouse-up BEFORE returning
the acknowledgement, only inside the active ordinary or COM arm. This is an
intentional controlled intervention, not passive logging. There is no physical
input, capture/foreground operation, Office hook or observation of other windows.

## Protocol and bounds

Retain three fresh children: ordinary dispatch, pinned CoWait8, counterfactual
CoWait24. Reuse the existing architecture, owner/source admission, hidden owned
window, one-second COM timeout, five-second child deadline, ten-second retained
parent watchdog, and at most two seconds exit-only cleanup. Do not add CoWait's
INPUTAVAILABLE flag, renew a deadline, sleep, retry, or post an extra mouse-up.

One producer waits on a separate start event, then sends one exact-owned tagged
WM_APP using SendMessageTimeout with BLOCK, ABORTIFHUNG and ERRORONEXIT, bounded
by the smaller of one second and remaining child time. No broadcast or
NOTIMEOUTIFNOTHUNG. The receiver posts exactly once inside the acknowledged
callback, with thread identity, phase and QPC checks. Duplicate, expired or
late-drain callbacks cannot post. The message hook still observes only the
tagged mouse-up and its real WndProc delivery; rendezvous metadata is separate.

Set active phase and release the producer immediately before entering the arm,
with no intervening message pump. The ordinary control must handle an initially
empty queue: use a bounded message-aware wait and PeekMessage/DispatchMessage,
one fixed arm deadline of at most one second, and the existing 256-iteration
cap. Recompute remaining time without resetting the deadline. Sent messages
can be processed by PeekMessage even when it returns no posted item.

After COM returns, disable rendezvous posting before the labelled immediate
drain. A late callback with no qualifying during-call post is inconclusive,
not proof of lost input. Receiver callback chronology establishes the enqueue
inside the synchronous call interval; a producer timestamp or precall marker
alone does not. Keep the one-event CoWait handle unsignaled, and require the
same RPC_S_CALLPENDING result.

## Lifetime and interpretation

The producer publishes all results before its final done-event signal and
performs no further native/window/handle/shared-receipt access afterward. A
bounded non-pumping wait on that event proves resource quiescence, not thread
termination. Retain its Thread and delegates until this barrier. Do not close
start/done events or destroy the window before quiescence. If the barrier is
unconfirmed, skip unsafe disposal, fail the child, and use the existing retained
process boundary; never report successful cleanup or launch another arm. No
OpenThread, PID reopening, new process rights or security-policy changes.

Returning from the STA would itself destroy its windows. Therefore an
unconfirmed producer barrier must not return normally: emit a bounded,
identified failure receipt with cleanup/quiescence false and terminate only
this spawned child with exit code 1. The parent still verifies its retained
process exit and stops the series. This is whole-child containment, not
successful native cleanup. A blocked failure write remains contained by the
existing parent watchdog; no new observation or timeout allowance is added.

The ordinary control requires one acknowledged post, one removal and one real
delivery. A COM comparison requires a qualifying phase-2 callback/post, bounded
producer completion, valid receipt ordering and native cleanup. No qualifying
callback is inconclusive. API, identity, duplicate, deadline or lifetime errors
are fixture failures. Suppression, nested delivery and deferred delivery remain
synthetic observations only. No production dispatch policy changes follow from
this experiment alone.

Add explicit stimulus/version metadata so these receipts cannot be confused
with the earlier prequeued experiment. Test the executable state/receipt
contracts, including late no-post, duplicate, malformed phase order, initial
empty control queue and pending-producer cleanup. Independently review, freeze,
run local validation, then one first-attempt native diagnostic on both existing
architectures. All Office GUI/privacy/ownership/semantic gates remain unchanged;
these diagnostics cannot qualify a package.

Primary references: [SendMessageTimeout](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendmessagetimeoutw),
[PeekMessage](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-peekmessagew),
[MsgWaitForMultipleObjectsEx](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-msgwaitformultipleobjectsex).
