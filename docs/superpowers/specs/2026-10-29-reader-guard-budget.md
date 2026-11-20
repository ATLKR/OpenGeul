# Existing reader guard failure observations

The paired Windows run 40838303359 at source 26620d5 passed unit/shell checks
but failed Calc cancel before Ctrl+W and Writer PRE semantic admission before
the observer or first key. Both failures concern the original 12-second reader
deadline. The same capture helper leaf can mean no observation yet or expiry
after waiting on positive owned capture; Writer can expire inside validation.
The budget consumer is not established by the existing notice.

Preserve original guards, budgets, owner/generation checks, native calls, clock
call counts, input, cleanup and primary exception. Project existing observations
only. Increasing a deadline or repeating unchanged Windows input would not
identify the cause. Do not read/copy document bytes, body, prefix, paths, URLs,
error text or inventory contents into this observation.

Add kind-1 schema 8 only for scope1/calc-close-cancel/type-without-enter and
scope3/ime-writer/verify-pre-prefix-editing-context. Keep schemas1..7 and the
compartment file models1/2 and carrier3/codec2 unchanged. The in-memory Writer
diagnostic may emit one qualified numeric failure case; it must not write its
raw record or replace the original failure if optional publication fails.

`readerGuard` is exactly 20 integers:

```
[context, mask, phase, observed, validated, pending, captureRelation,
 inventoryPresent, readerStartAttempted, observationCount,
 cleanupPresentAtFailure, semanticFinishedPresentAtFailure,
 remainingFirstCheckMs, remainingLastCheckMs, remainingFailureMs,
 remainingSessionStartMs, remainingEngineAdmissionMs,
 remainingLastRequestOrCalcReadStartMs,
 remainingLastReceiveOrCalcReadFinishMs, readerBudgetMs]
```

Context1 is Calc and context2 is Writer. Mask bit(i-2) means slot i, 2..19,
was observed; unknown slots are zero. Time slots12..18 are signed int32
floor(1000*(deadline-at)). Writer budget slot19 is the measured original
readerDeadline-startedAt, at most12000ms; Calc leaves it unknown rather than
turning the code constant into a measurement. Capture relation compares only
handles: zero, child1, focus2, parent3, Suite4, other nonzero5. It is not a
capture lifetime proof.

Writer phase0 denotes expiry inside the validator with observed1/validated0/
pending0 and its IME budget leaf. Helper timeout leaves in that same Writer
context use phases1..5; a helper phase cannot label an inner IME budget leaf.
Calc phase1 supports first-check expiry or an observed, validated,
positive-capture wait. Do not relabel phase0 as one of the helper's phases1..5.
Snapshot Writer phase flags before semantic finally; later cleanup must not be
mistaken for cleanup preceding the failure, even within one Windows clock tick.

Use a private bounded ledger of at most32 live associations. Join the exact
record, original exception, session, context, current capture invocation and
current observation objects. Preserve immutable integer snapshots and reject
cloned/stale/foreign or changed failure associations. Decode must use only pure
validation; producer imports and new target queries are forbidden.

First-check time may retain the value of the existing helper clock read in its
private invocation. The IME budget may name its existing single clock result
as a local for failure-frame projection. Neither operation adds a clock read or
changes a public bounded native receipt. Phase flags narrow the consumption
segment, not every repeated semantic polling call site.
