# Bounded mouse-up retrieval diagnosis

Run 40154709197 at 88a9217 reproduced ARM64 capture remaining owned after a
mouse-up retrieval. Cases 1 and 2 retrieved mouse-up with flags 1 and then
recorded SAL release. Case 3 retrieved it with flags 3, recorded no subsequent
SAL release, and failed the original five-second guard before Ctrl+F6 insertion.
All three original engines exited under the repaired cleanup contract. Observer
preparation passed in 6.703 seconds with its unchanged gate.

The failing mouse-up client coordinates differ from mouse-down by one pixel on
each axis. The harness injected one button-only pair. A client-origin change is
possible; neither pointer movement nor the consuming caller is established.
The inspected pinned engine pump uses flags 1. Queue retrieval does not prove
handler execution. Final ARM snapshots were slightly before the native cutoff.

## Finite hypothesis ledger

| Alternative | Current evidence and status | Next discriminator / correction threshold |
|---|---|---|
| No owned mouse-up was retrieved | Disproved for the observed event: row 12 is owned mouse-up removal, after recapture. This does not uniquely attribute that event to the injected pair. | Do not add input or retry the click. |
| Mouse-up preceded the observed recapture | Disproved for this sequence: SAL capture returns in row 11 before mouse-up in row 12, with the same owned generation. | Do not repair by forcing capture release or changing input order. |
| Preparation or orphan cleanup prevented this case | Disproved for this run: preparation passed in 6.703 seconds; all three retained engines signaled and their handles were released. | Preserve the tested cleanup repair; no preparation-budget change. |
| Coordinate-origin movement explains the one-pixel difference | Open. Button-only injection contains no movement; the observed difference matches a possible origin shift, but the trace has no event screen point or per-event origin. | Same event screen point plus the corresponding origin shift supports this interpretation. Stable origin with changed event screen point weakens it. Neither alone proves why release was omitted. |
| An alternate retrieval path consumes mouse-up without normal handling | Open. Flags 3 and missing subsequent SAL release differ from flags 1 plus release in both controls. Inspected normal engine pump uses flags 1. No consumer identified. | An interpretable stack mapping to a pinned source path that removes this event without its required dispatch/release, together with a deterministic regression reproducing that path, can justify correcting that path. A different stack alone cannot. |

These alternatives are not mutually exclusive. An origin change could accompany
a different retrieval path. The next observation tests only the two open rows;
it does not identify either as the cause in advance. If the stack stops at the
Windows callback boundary, mappings are unknown, clocks expire, or no failure
reproduces, record the unresolved row rather than infer a cause or repeat the
same run. A later experiment needs a new evidence-based decision.

For an embedding/readiness behavior correction, additionally identify the exact
owned host/worker geometry transition and demonstrate in a regression that
input is admitted before that required transition completes. The sampled origin
correlation by itself does not meet this threshold. No current evidence meets
either behavior-correction threshold.

## Decision within the authorized CI diagnostic scope

Another unchanged run cannot identify the retrieval path. A window-procedure
replacement or remote debugger would change the experiment or exceed its scope.
Extend the existing passive observer with bounded retrieval metadata instead.

Retain event-associated MSG.pt and one sampled ClientToScreen(0,0) origin for the
first owned left-button down and the first owned left-button up for each removal
flag value 1 and 3. These are separate observations in the target thread's DPI
context, not atomic historical physical geometry. At most three records exist.

For the two possible up records only, capture at most 16 current-stack frames.
Classify them against a fixed whitelist of already-loaded engine and Windows
modules. Persist numeric module IDs and relative offsets only. Unknown frames
have ID and offset zero; no absolute stack address, path, arguments, stack bytes,
symbol lookup, module enumeration, loading, network or remote access is permitted.
Local raw addresses are cleared after classification. Module attribution remains
observational because borrowed module handles do not prove lifetime continuity.

Each record correlates to an already committed owned capture event. Keep the
original PID/TID/HWND/generation, QPC deadline, bounded append-only publication,
and reentrancy guards. Record failed APIs, partial publication, unknown modules,
frame-cap truncation and elapsed/overrun status. Never start another observation
after the original deadline; abandon remaining work on expiry without extending
the deadline. Native calls are not preemptible, so frame caps cannot guarantee
execution latency. All results remain nonacceptance evidence.

## What the experiment can decide

An observed engine frame above retrieval may distinguish the normal pump from
another path; a callback-only or unknown stack is inconclusive. Screen-coordinate
and sampled-origin evidence may distinguish an origin change from an unexplained
client-coordinate difference. Neither proves causality or normal handler return.
Observer effects remain possible. No product behavior fix is justified until
the resulting evidence supports one.

## Verification

Use executable portable native fixtures for correlation, caps, expiry, unknown
module redaction and publication, plus controller decoding tests for malformed,
partial and expired records. Preserve old protocol prefix/normal input behavior.
Run focused and full local tests, independent review, and only then one new
first-attempt native diagnostic on both existing architectures. Keep preparation,
privacy, ownership, input, cleanup and final acceptance gates unchanged.
