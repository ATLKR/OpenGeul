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
existing engine-*.json reports on future navigation prerequisite failures, without
changing any gate or launching an unchanged rerun to collect broader logs.
