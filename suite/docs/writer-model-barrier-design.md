# Strict read-only Writer completion in the acceptance harness

This local branch implements an E2E-only synchronization correction from Suite
`299c9e4cc244b47b0e11d8b96040395a1ac76220`. It changes no shell, worker, document
engine, input producer or pacing. Publication and actual Windows qualification
require root and independent review; local synthetic tests are not Windows proof.

## Established problem and historical limits

Original `Case.edit` sent one physical marker and then waited for a dirty title.
The original Cancel action preserves the first edit's dirty title, so the second
check could return before any second-marker body change. The first edit can also
set the title after only an initial character. Three corrected RED regressions
execute the actual original `Case.edit` and `dirty_cancel_save`: an unchanged
second body, a partial first body, and the original Save boundary. Suite299 failed
all three with `AssertionError not raised`. The required correction rejects the
incomplete body; it must never repair it. Physical-call/pause and raw scan-buffer
preservation tests passed against the original source and remain green.

The unchanged fixed20 diagnostic `38975228858` completed all20 trials. All10
observed trials had exact model/XML/independent UNO text. Controls passed8/10;
trial10 lost L in the first `-LIFECYCLE-CANCE-SAVE-`, and trial12 lost C in the
second `-AFTER-CANEL-`. XML matched independent UNO in all20, including the two
incorrect bodies. Therefore stale completion is not the full loss explanation.
A model observer changes scheduling. This is a new acceptance synchronization
policy; the historical physical-loss cause and a product fix remain unproved.
The original diagnostic raw and failures are preserved and are not backfilled.

## Exact per-frame expectation

`Case` freezes the independent original DOCX full body before launching the
editor. Known blank and Home factory documents have baseline `''` and URL `''`.
Each exact attachment has its own ledger, including Home's second edited frame;
the clean first Home frame cannot satisfy that frame's completion. Before every
unchanged physical edit, a fresh observer verifies the actual prior body equals
baseline plus that frame's ordered completed markers. Only final successful
cleanup commits the next marker. Failed contexts cannot retry.

Only CRLF and CR normalize to LF. No spaces, punctuation, case or other text is
normalized. A prior body or monotonically growing exact append prefix may be
pending; full-body equality is complete. Changed baseline, dropped interior
characters, reordering, duplication, extra text, prefix regression, foreign
ownership and native/getter/cleanup errors fail. A permanently unchanged prior
or stalled prefix times out. There is no input retry, focus repair, extra sleep,
model mutation, dispatch, reopen/reload, save, selection or cursor capability.

## API and immutable evidence

`writer_model_barrier.py` is pure: no file reads, native calls, UNO or input.

```python
freeze_expectation(binding, baseline_body, completed_markers, next_marker,
                   before_input, *, suite_root, original_shell, inventory,
                   inventory_sha256, started_at, timeout_seconds=12.0)
validate_observation(plan, observation, previous_body)  # pending | complete
await_completion(plan, reader, *, clock, pause, record, max_reads=120)
finalize_completion(plan, record, cleanup, finished_at)
replay_completion(receipt, *, suite_root, inventory, inventory_sha256,
                  binding, baseline_body, completed_markers, next_marker)
replay_case_completions(record, *, suite_root, inventory, inventory_sha256,
                        baseline_body, expected_urls)
```

`Expectation` uses frozen JSON snapshots for binding, before-input raw data,
original launched Popen HANDLE, inventory and independent text. Every receipt
retains full expected/prior/observed text, original deadline, wrapper/read times,
raw ownership/Python/UNO observations, decisions and errors. Every attempted read
is appended before validation. Startup and original input failures also retain
case evidence and owned-reader cleanup; first failures are preserved separately
from later cleanup/persistence errors. Portable replay recomputes all decisions
and exact coverage rather than trusting `success`, `verified` or summaries.

`expected_urls` contains only source-derived edited `(Suite HWND, child HWND)`
pairs: attachment0 for ordinary Writer cases and attachment1 for Home. The helper
independently derives URLs from original fixture constructor paths; new/Home URLs
are explicitly empty. Whole-case replay derives marker counts/order from source
`ASCII_EDITOR_MARKERS`, joins original readiness and exact ASCII receipts at
`.025`, validates per-frame cumulative bodies, exact edited-frame coverage and
nonoverlapping ordered edit intervals. It returns honest
`originalPhysicalAsciiLossCauseEstablished=false` and `productFixEstablished=false`.

## Original generation, frame and packaged Python

The original `Case.process._handle` is queried with typed native APIs before
input. Its actual PID, image, raw FILETIME low/high, liveness and still-active
exit status are retained. It is borrowed, never closed by the observer. Reader
startup must match that original creation time before opening Office or making
UNO calls; a recycled numeric PID with the same image is insufficient.

Controller and helper each retain their own original shell/Office HANDLEs.
Raw before/after snapshots bind PID, FILETIME creation, packaged image, HWND
parent/root/exported properties and the original Office command line. A unique
private pipe and UserInstallation profile derive from that same actual argv.
The helper retains the existing frame/controller/model objects, records their
actual PyUNO representations, enumerates the unique original native container
and checks actual object equality and controller/model links before and after
`Text.getString` and `isModified`. An empty model URL remains exact-frame bound.

Every read keeps the same frozen original controller/helper HANDLEs and actual
observer PID/creation/image/HANDLE/private-job identity. Seven packaged Python
roles are checked with `writer_style_smoke`'s native process-image, version,
DLL/module-origin and inventory path policy. Runtime regenerates actual seven
file hashes/nonlinked-path evidence independently on helper and controller.
Portable replay uses explicit trusted inventory and its SHA without accessing
recorded Windows paths or calling `Path.resolve` on Ubuntu. The external delivery
helper independently rehashes those roles in the verified local payload.

Existing native archives contain no argv or pipe field. Returned frame summaries
include actual reader-observed Office argv/profile. The external helper joins
embedded Office PID/FILETIME/image to an archive after-ui-bootstrap event and
the decoded unique UserInstallation URL to `manifest.ownedProfile`. It does not
invent an archive pipe field or confuse launcher/worker PID with embedded Office.
All original archive/hash/no-dump and saved-file gates remain mandatory.

## One deadline and cleanup before Save

One controller-monotonic twelve-second budget starts before original HANDLE and
before-input capture. Startup, UNO resolution, unchanged physical typing, getters,
validation and helper cleanup cannot reset that deadline. Every blocking UNO
operation runs in the unchanged suspended-to-private-job-to-resume launcher.
Expiry may terminate only that observation job, never the live document. Such
forced cleanup remains a failure. Reads are capped at120 and pending pauses at
0.1 seconds clipped to remaining time. Helper QPC ticks/frequency stay raw and
are never compared to controller seconds or nanoseconds.

Per-read `readCallCleanupSucceeded` and `readerStillRetained` describe a completed
RPC with a persistent helper, not final process cleanup. Full model equality is
only state `model-complete`. Final `complete` requires actual release ACK for
that same observer, normal exit0 of retained private-job members, an empty job,
actual HANDLE-close receipts and unchanged original native generations. Continuity
joins frozen reader PID/creation/image/HANDLE/job and controller HANDLEs to final
cleanup. Chronology is strict:
`modelEqualityAt <= cleanup.startedAt <= cleanup.finishedAt <= finishedAt <= deadline`.
Only then may original Cancel/Save/Discard/failed-Save-As actions proceed. The
original dirty-title check remains after this stricter completion procedure.

## Verification and review

RED provenance remains under `work/writer-model-barrier-tdd/`: the corrected
three original-source regressions and absent-module policy contracts. New
cleanup-identity/time regressions first produced10 meaningful failing subcases,
then passed after exact cross-read/final joins. Current focused tests also cover
portable raw-Windows whole-case replay without filesystem access, real production
context integration with only native-reader boundaries replaced, independent
baseline/URL/frame coverage, time bounds and original physical-input invariants.
Backend fakes test native ownership, typed failures, read-only getters, owned
transport/job cleanup and recycled original-shell rejection. None is a live
Windows positive. Final source hashes, complete local suite and independent code
review must be recorded before root chooses a new source-bound Windows run.
