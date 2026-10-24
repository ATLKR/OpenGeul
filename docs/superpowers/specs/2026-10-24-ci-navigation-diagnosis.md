# Owned editor navigation diagnosis in CI

The user selected continued Windows CI diagnosis. Preserve local saved-read fix
`a3a1913` and all normal native acceptance gates. The first experiment concerns
the x64 Impress failure at `6d9b8e3`, run 40106900112: all four shortcut insertion
counts completed, but 43 semantic observations remained in object selection with
caret -1. These observations do not show whether the editor dequeued TAB/F2 or
whether a window procedure received them.

Use the already precompiled, generation-bound ASCII observer transport with a
separate bounded navigation ring. Attach only to the retained owned editor
thread after initial focus admission, before original TAB/F2/CTRL_END. Observe
queue removal, window-procedure entry and return, focus/capture handles and
native timestamps. Do not alter inputs or wait for diagnostic events. Retain the
existing UNO PRE reader and its original 12-second limit within the 60-second
setup deadline. Never invoke UNO from a hook. Diagnostic rows cannot satisfy an
ASCII, IME, editing or shutdown assertion.

Hypothesis outcomes: no dequeued F2 suggests delivery/queue progress; dequeued
F2 without window entry may mean accelerator/pretranslation consumption, not a
stuck queue; window entry/return without caret transition narrows the boundary
but does not prove a particular LibreOffice handler ran. Overflow, missing rows
and observer failures are inconclusive, never negative evidence of delivery.

Reuse avoids moving the expensive IME DLL compilation before navigation, which
would change the timing being investigated. A new remote access service or
interactive runner is outside scope. Intermediate UNO waits between shortcuts
would serialize the original sequence and are intentionally excluded.

CI diagnosis must retain exact owner-push, workflow/job identity and first-attempt
privacy admission. Targeted execution must be distinctly labeled non-acceptance
and cannot upload final packages. The final corrective source must run every
normal gate on both architectures. No unchanged reruns or empty commits.

Implementation: test the bounded native producer/ABI and controller cleanup;
integrate an opt-in navigation-only case using the original input and semantic
path; test workflow separation and non-delivery; obtain independent review;
run one targeted experiment and interpret its evidence before behavior changes.

## Experiment 40140460250, source 97b4eb2

Both native architectures produced complete eight-event queue traces for the
original TAB/F2/Ctrl+End sequence and reached caret 26 in the expected paragraph
under the unchanged PRE deadline. No window-procedure entry/return rows were
observed. Thus absence of those rows is compatible with successful editing
readiness and does not establish failure or a blocked queue. The earlier caret
failure was not reproduced; instrumentation can affect timing. No editor
behavior correction is claimed from this experiment.

The navigation-only case then incorrectly invoked normal saved-only keyboard
completion. Repair only that diagnostic disposal: retain the intentionally
incomplete keyboard receipt, verify handle release/retention/deadline, and keep
normal saved-only completion unchanged. Restore acceptance mode to validate the
independently supported shared saved-read repair on both native architectures.
The diagnostic evidence cannot replace any required acceptance gate.
