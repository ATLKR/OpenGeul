# One Writer navigation boundary investigation

Retained ARM64 Writer evidence from run40212924531 proves four inserted Ctrl+End
inputs followed by forty stable body-cursor reads away from body end. It contains
no navigation trace. The scan plan already marks End extended; shell source only
intercepts Ctrl+F6. Pinned VCL source can consume keys in tracking, accelerators,
pre-notify or internal focus routing before Writer's KeyInput. OS focus alone
cannot distinguish these paths. Calc's initiating IME reset remains separate.

Reuse the existing NavigationTrace unchanged, enabling the existing diagnostic
CLI for Writer as well as Impress. The fixed workflow selects Writer, one case
per architecture. Start after original editor readiness and before the single
original Ctrl+End. Keep original60-second setup and all subordinate deadlines,
source/owner/first-attempt/privacy admission, inputs, semantic assertions and
cleanup. Stop after semantic PRE, before ASCII/IME/save. Keep normal acceptance
and unsaved-session closure guards. No console work, engine rebuild, new hooks,
new telemetry fields, extra input, focus retry or blanket timing change.

Approaches: reusing existing queue/entry/return tracing can distinguish pre-window
routing from later VCL routing without new instrumentation. More general logging
adds no decision value. Direct internal-handler tracing would need unavailable
matching internal symbols or engine instrumentation, so is not selected now.
This choice is the implementer's within the user's authorized CI investigation.

Decision/stop: inspect complete publication, overflow/rejected/cleanup states and
join Ctrl/End records to the original action and retained target. Queue removal
proves only that the owned queue observation occurred. The sent-message hooks do
not guarantee observation of posted-message handler execution; absent entry/return
rows cannot identify pretranslation, loss or a skipped handler. Explicit observed
entry/return still does not prove Writer's semantic handler executed. Missing,
partial, overflow or rejected trace, no reproduced failure, or failed prerequisite
is inconclusive; no unchanged rerun. A green step is never paired acceptance.

Control finding from run40237954954: x64 produced four complete queue-removal
rows and no entry/return rows, yet its first semantic read was at body end. This
invalidates using absent sent-message hooks to classify the failing path.
Microsoft's hook overview distinguishes queued-message and sent-message hooks:
https://learn.microsoft.com/en-us/windows/win32/winmsg/about-hooks
ARM64 failed Writer/Calc engine fixture prerequisites before this observation.
Diagnostic mode did not retain those generated exception reports; preserve only
the existing closed engine-failure-summary.json on fixture failure across every
validated diagnostic mode. Never retain engine-*.json, raw exception reports or
fixture content through this shared step. Its stage/category values are closed,
cleanup flags typed, and rows bounded. Successful or skipped fixtures do not
trigger the shared upload; missing summary remains an explicit upload failure,
with no raw-report fallback. Acceptance gates and per-mode prerequisites stay
unchanged. No unchanged native rerun is authorized by this retention repair.

### Removal-flag coverage correction after run40241619571

At9f40e65, x64 inserted the original Ctrl+End once (4/4), but all49
semantic observations retained bodyEndComparison1. Its complete zero-row trace
cannot exclude retrieval: HookGet admitted only flags1, omitting flags3 despite
the removal bit being present. Prior retained native evidence contains flags3.
The correction admits the removal bit exactly as the existing capture observer
does; flags0/2 remain excluded. No input, window scope, deadlines, protocol,
privacy gate, or semantic acceptance changes. This repairs observation coverage,
not Writer navigation or proof of which flags caused this failure.

The next corrected first-attempt diagnostic asks whether a failing original
Ctrl+End has owned queue-removal rows after closing this blind spot. Complete
rows plus unchanged cursor narrow the failure beyond queue removal; zero rows
remain insufficient to identify routing or a handler. Semantic success is
nonreproduction, not a product fix. Partial/overflow/rejected evidence is
inconclusive. Do not repeat unchanged or infer handler delivery from hook rows.
