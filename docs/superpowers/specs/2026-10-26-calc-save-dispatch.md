# Bounded Calc save dispatch diagnosis

This is a new implementation reconstructed from accessible source and original
run 40252077899. The previous environment's uncommitted candidate was not
recovered. Its code and tests supply no verification for this implementation.

The ordinary active-cell ASCII save passed on x64 and ARM64. The original ARM64
IME Calc report reaches `save-ctrl-s`, uses a 30-second absolute save budget,
then fails its durable-file oracle. Its 295 file reads have no transient errors.
The original engine's forced termination is confirmed separately; it is not a
graceful-close proof. Writer composition and Impress focus are separate failures.

## Scope and choice

Use a separately built diagnostic engine with source probes in the existing
Calc save path. An external debugger would add privileges and timing changes;
an observer of queued keys cannot locate an internal save boundary. Source
probes are the selected implementation choice under the user's existing grant.
Do not add a save, commit key, setter, activation, retry, or model reader.

Authenticate pinned LibreOffice source files before changing them. Probe
`ScTabViewShell::ExecuteSave`, its existing `InputEnterHandler` and `ExecuteSlot`
calls, and `SfxObjectShell` save and medium-commit boundaries. A returned input
handler call is not proof of committed input. Preserve nested calls and record
numeric operation, phase, invocation, parent, depth, outcome, and QPC only.

## Ownership, deadline, and lifetime

The fixed protocol contains no input bytes, document text, paths, URLs, key
tokens, or arbitrary strings. Bind the original engine PID, creation time,
thread and HWND, controller PID and creation time, and unpredictable nonce.
Use a fixed capacity of 128 events and a maximum depth of eight. Publish each
complete row last with a Windows Interlocked operation. Invalid ownership,
generation, nesting, saturation, changed immutable fields, or incomplete rows
make the evidence inconclusive.

Set one monotonic deadline at admission, no later than 30 seconds after its
start. It covers arming, the original save, recording, disabling, target disposal
when needed, retained-HANDLE termination observation, and local handle cleanup.
Reserve cleanup inside that deadline. Never renew it after a timeout. Missing
return events prove only an incomplete observation. Verify process termination
with the retained original HANDLE, generation, signaled wait, and exit code;
report closure separately. A controller unmap does not retire the target view.

## Build and evidence isolation

The diagnostic runtime has a distinct artifact name and receipt with
`fullEngineQualified=false` and `acceptanceEligible=false`. Do not change either
normal runtime lock to point at it. Ordinary packaging must reject it. No main
merge, release, Store publication, customer deployment, new runner class,
credentials, or permission changes are included.

Pin the producer run, artifact ID, outer archive size and SHA-256 separately
from the current Suite commit. Authenticate the outer archive before deriving
its inner engine and receipt digests. The overlay records both the historical
engine source and the admitted Suite source; neither replaces the other's
provenance. Join the Suite source to the current CI event and Korean readiness.

Retain only the numeric diagnostic reports and explicit provenance receipts.
Calc diagnosis skips composing screenshots, raw case/exception reports and
keyboard sidecars. The existing generated-fixture setup and model-reader IPC
continue to verify the original behavior; they are outside the retained
diagnostic artifact allowlist. Never supply user documents to this case.

For new executions, an explicit product-step opt-in may also publish a closed
numeric observation as a GitHub check annotation. This creates new telemetry;
it never reads or republishes denied artifact or log data. Use static titles,
validated public source/run provenance, numeric case/stage/exception and owned
source-file IDs, line numbers, and selected existing observations. Presence bits
distinguish missing values from measured zero. Do not include messages, paths,
formatted tracebacks, keyboard data or document values. Limit case messages to
2 KiB, validated Calc traces to 32 KiB, two changed case projections and eight
notices per controller. Telemetry failures preserve the original result and
cleanup. Unit-test steps do not enable the opt-in. A failed annotation read
stops that read boundary without another credential or anonymous fallback.

The unit step uses a separate opt-in and emits one result summary only after
ordinary unittest discovery finishes. Product notices stay disabled inside the
unit process. Record standard run/error/failure/skip counts and at most eight
actual failure locations, captured before error formatting. Public source-file
IDs come from a sorted, bounded set of top-level Python source files and are
bound to the exact source commit. Omit test names and parameter reprs. The
collector does not inspect exception messages, traceback text, locals or skip
reasons. Preserve standard
unittest discovery, logs and exit codes, including an empty-run exit of five.

GitHub documents the [notice command](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#setting-a-notice-message)
and [annotation read API](https://docs.github.com/en/rest/checks/runs#list-check-run-annotations).
The existing credential verified the new notice round trip on Windows.
Run 40724862643 at
`b0e15e666a90e75ba60ec4f55ae4475c37dde1e9` produced closed unit, case and
Calc-trace notices whose complete annotation counts matched the finished job.
That run attached Calc but failed the existing foreground-ownership guard
before save; it supplies no native save or retained-engine-exit proof.
Run 40734133781 at `dfc633b09ec39f0e3d0f2736e9aad372e924548e` reproduced
the same guard before the Calc navigation reader started. Both Windows unit
and shell checks passed; the native save probes still did not execute. These
results do not establish a model-reader cause for the foreground change.

When such a guard fails, keep the original owned source-frame locations and a
bounded numeric projection of its already captured before/after foreground
ownership and semantic-reader progress. An attempted reader start is not a
process-start proof; a returned observation or cleanup field is not evidence
that the reader changed foreground. Do not query the target again or weaken
the guard to obtain a later dispatch trace.
Initial setup can fail before a semantic-reader context exists. Its numeric
projection must distinguish that unobserved context from a measured empty
observation list, and join the failed shared guard to the original admitted
processes and editor thread. Keep the same ownership and time-limit checks.

Run 40765655839 at `6176ae673b0e405999437d14d93ce0da872661ba`
passed both Windows unit/shell checks and all diagnostic prerequisites. Calc
failed its first navigation admission after the original Ctrl+F6, before its
navigation reader, Korean composition/save dispatch or transport admission.
Its source-bound foreground vector is `[5,5,0,121,0]`: each surrounding
snapshot contains a live foreign PID. This does not identify the window,
establish equality of those PID values, or prove which action changed focus.
Local resources and handles were released; there is no retained-engine-exit
proof. The native trace and original save oracle remain unobserved.

For one subsequent Calc diagnostic, explicitly opt in to a new closed case
notice version. Project only finite class codes from the existing foreground
`className` fields and equality of the existing positive PID values. Do not
emit class strings, titles, paths, raw foreign PIDs or input. Unknown class
strings map to a fixed unknown code; absent fields remain unobserved. PID
value equality does not establish process identity or a shared generation.
Reuse the current guard's existing ownership/generation/clock binding before
projecting. Do not issue another window/process query, create a helper, add
input or retry focus. Keep all earlier notice versions and the two-notice
Calc budget, at most 2 KiB per case notice, unchanged. The opt-in applies
only to the ARM64 Calc diagnostic scope, and numeric artifact isolation and
all non-acceptance flags remain mandatory.

Interpret the numeric trace alongside the original input/save oracle and
confirmed process-exit evidence. Validate native nesting, generation/deadline
rejection, event publication, ABI, cleanup failures, and artifact isolation
locally, independently review the change, then compile and run it on the
existing Windows ARM64 runner. Product corrections need causal evidence and
fresh full x64 and ARM64 acceptance on the final corrective commit.

Run 40774909254 at `39f43753db153dfa8068471493bcbf05a83f23af`
passed 2,999 real Windows unit tests on each architecture (38 skipped) and
all Calc diagnostic prerequisites. Its initial navigation guard again failed
before reader/input/save admission. The new vector `[2,2,1]` categorizes both
foreign foreground snapshots as `CASCADIA_HOSTING_WINDOW_CLASS` and compares
their PID values equal. This is not a process-generation or activation-cause
witness. The native save trace, oracle and retained-engine exit remain unobserved.

The pinned LibreOffice console launcher `pyuno/zipcore/python.cxx` creates its
core interpreter with `CREATE_UNICODE_ENVIRONMENT` only and a fresh STARTUPINFO.
This does not establish a visible-console defect: a child can inherit its
parent's windowless console without repeating `CREATE_NO_WINDOW`, and console
inheritance is separate from ordinary handle inheritance. See the
[CPython console inheritance discussion](https://github.com/python/cpython/issues/85785)
and [Win32 inheritance documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/inheritance).
The earlier inference that these creation flags proved a console gap was too
strong. The previous Terminal association and activation cause remain unknown.

The direct-core WorkerLaunch path selects the exact packaged Python 3.13.15
interpreter for explicit bootstrap and a same-PID retained query-HANDLE check.
It matches the launcher's process-local bootstrap environment and preserves
structured arguments, UTF-8, original worker ownership and cleanup. Its passing
probe establishes the new path's behavior, without proving that the old launcher
caused the foreground failure. Keep the packaged launcher and runtime manifest
for existing tools, and keep the original focus and input guards.

Before the original GUI scenario, execute a bounded Windows bootstrap probe
through the actual WorkerLaunch/WorkerClient path. It may substitute only a
constant synthetic Python program in the arguments. Verify native architecture,
packaged interpreter and UNO origins, local UNO bootstrap, absent console and
synthetic Korean UTF-8 roundtrip. Join its internal PID and creation-time reply
to one retained query-only process HANDLE, observe that same generation's
zero-code exit before client disposal, and release the HANDLE even on failure.
Publish only fixed booleans/numeric summaries, without environment values or
paths. This separate probe cannot prove original Calc engine retirement or
the earlier Terminal association. Keep all original focus guards and one input
attempt; a new Windows run must establish whether the original failure changes.

Run 40782731241 at `13fbd5eb22684c4069d480b64ebde003b1e4e10a`
passed both Windows unit/shell checks (2,999 tests, 38 skipped per architecture).
The ARM64 package and native worker bootstrap probe passed, including console
absence and same-generation normal exit. IME readiness and standalone engine
fixtures passed. Privacy preparation failed before diagnostic input staging;
the original Calc case, native dispatch and save oracle were not executed.
The fresh job log retained only the outer entry failure. Its detailed child
failure remained in local receipts, so the exact cause is unknown.

For the next original preparation, opt in to one source-bound numeric CaseV2
notice after the existing cleanup. Preserve actual owned traceback locations
when the error is captured, prefer the original observer failure over a later
controller wrapper, and retain unknown fields as unobserved. Use append-only
source IDs and scope 12. The observer records locations without emitting;
only the validated Suite controller emits once. A failure before the final
receipt must preserve the same raised exception after supplemental reporting.
The caller forwards only the bounded closed numeric payload, never other
stdout, stderr, exception text, UIA data, titles, paths or screenshots. Keep
all original source/ownership/privacy guards, the one original close/pointer
attempt, and the 120-second controller, 125-second containment and 15-second
staging limits. A successful preparation remains a prerequisite for Calc.

Run 40791429654 at `af55e795e2de38032d186c492ef04af970a01724`
passed ARM64 unit/shell checks (3,018 tests, 38 skipped), package/bootstrap,
IME readiness, privacy preparation and diagnostic input admission. The earlier
privacy failure did not recur; its cause remains unknown. The original Calc
case reached physical composition and the one Ctrl+S attempt, observed its saved
marker, and preserved the baseline fixture. The stable native trace contains
13 events with three balanced save invocations at maximum depth three,
without rejection, overflow, expiry or open invocations. The owner identity
joins the original case and its retained HANDLE exit inside the absolute
30-second budget. The exit code is 1, consistent with the diagnostic's explicit
forced teardown; it is not graceful exit 0 qualification. The diagnostic still
declares `imeVerified=false` and `acceptanceEligible=false`, and does not provide
the normal reopen or lifecycle acceptance proof.

The same run's x64 unit check failed one subsecond shared-build-budget test.
The corrected test consumes the original shared Stopwatch before later command
attempts, requires rejection before process creation, and retains separate
running-command forced-termination coverage. Production build deadlines are
unchanged. Restore normal acceptance on both architectures for the next current
source, including full IME/focus/accessibility, document reopen, portable-package
checks and all 83 original engine generations' graceful shutdown gates.

Final normal acceptance also needs the identity of the actual product ZIP.
Immediately before its existing candidate upload, under the same successful
normal-acceptance condition, recheck the current portable receipt's source,
architecture, file-check flags and archive path. Hash that same original ZIP
again through one read-only stream, require its hash to match the pre-GUI
portable receipt, and record its current byte length. Emit only the closed
seven-field proof: schema version, source commit, run ID, run attempt,
architecture, SHA-256 and bytes. The proof contains no paths or document data.
It is independent of the GitHub outer artifact digest and cannot qualify a
candidate without the same run's successful final job and uploaded artifact.
Diagnostic modes must not emit this proof or deliver a candidate ZIP.
