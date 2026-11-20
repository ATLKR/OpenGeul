# Bounded Calc IME mode diagnosis

The user selected continued Windows CI diagnosis. Keep the existing runners,
owner-push and first-attempt privacy admission, original deadlines, ownership
checks, input programs, semantic assertions and acceptance gates.

Run 40142400497 at c15ee05 provided a concrete Calc failure on ARM64: command 3
acknowledged typed Korean mode, but subsequent owned-target observations showed
IMM open state zero before the first physical `g`. The document showed literal
`g`, and no composition events appeared. The acknowledged mode is insufficient
to explain the later state. This does not identify the code that changed it.

The next experiment asks whether the existing thread-local TSF open compartment
also becomes zero or whether IMM disagrees with TSF. Run only the original Calc
IME case on each native architecture, using x64 as a comparison. Correlate bounded
read-only TSF snapshots with the existing owned-thread message observations.
Reuse existing-compartment enumeration and typed reads; never create a manager,
create a missing compartment, write mode, resend input, or extend a deadline.
Record errors, missing observations, overflow, reentrancy and reference cleanup.
IMM and TSF reads are sequential, not one atomic state snapshot. An unavailable
or untyped read must not be interpreted as a closed state.
The observer can affect timing, so a successful run does not prove the earlier
failure resolved. These observations cannot identify a caller or prove context
lifetime merely from equal handle values.

Use an explicit nonacceptance workflow mode and CLI. Preserve the original Calc
input, composition, restoration and saved-content checks. The case executes
once; evidence is uploaded separately, and a deliberate terminal failure blocks
package qualification. Every normal final acceptance gate remains required on
both architectures after a supported corrective change.

Two independently reviewed local boundary corrections accompany this work:

- Geometry acquisition measures disagreement between independent native reads
  before allowing bounded re-observation under retained ownership. Stable invalid
  geometry remains fatal; no pointer or click is repeated.
- The general GUI pre-ASCII boundary uses the retained keyboard session's existing
  owned-capture settlement and original deadline. Later ASCII guards remain
  strict. This does not claim to identify the capture owner inside Office.

The same acceptance run also exposed persistent Impress capture followed by
foreign Windows Terminal foreground, and a Writer lifecycle semantic mismatch.
Those are separate unresolved observations, not waived by this experiment or by
earlier successful runs.

## Experiment 40145703918 at 3ed78f8

The x64 original Calc case passed. Its 50 correlated mode rows were within the
original deadline with balanced references. Two early reads were untyped; all
41 rows after activation acknowledgment 3 showed typed TSF and IMM open/native
mode 1/1. This establishes a passing control, not an ARM64 repair.

ARM64 failed before installing the IME observer. One original click and Ctrl+F6
completed, but capture stayed on the owned editor during 93 subsequent samples
until the original five-second focus deadline expired. Foreground stayed owned.
The intended ARM64 mode-reset hypothesis was therefore not tested. Repeating the
unchanged mode experiment is not justified.

## Initial capture experiment: owned capture ordering

Use an explicitly nonacceptance focus-only mode with three fresh, sequential
Calc instances. Each retains its original one click, one Ctrl+F6, five-second
entry deadline and ownership guards. No repeated input or capture release is
allowed. Observe before the original click so the trace can distinguish:

- Whether mouse-up removal from the owned queue is observed.
- Capture acquired after mouse-up queue removal.
- Capture still present without an observed release by the entry deadline.

Queue removal does not prove handler execution. Missing, truncated or overflowed
observations remain inconclusive. The diagnostic cannot establish the internal
Office caller from a handle value or message alone.

Reuse the prepared native observer with a separate bounded capture ring and
passive admission to the original owned child. Keep normal ASCII admission and
input guards unchanged. Native recording ends at the original QPC deadline.
On an expected focus timeout, a bounded local shared-memory copy may retain
already recorded evidence: no new target queries, control messages, inputs or
deadline renewal. Mandatory unhook/handle cleanup still runs. Preserve the
primary failure and label this post-failure evidence separately.

Stop a successful diagnostic immediately after original focus readiness, before
the normal keyboard session proceeds to navigation, semantic setup, IME or save.
Retain its intentionally incomplete keyboard receipt and verify resource release.
Each case has a unique owned output and process; the cohort is not an input retry.
The same owner-push/first-attempt privacy prerequisites and deliberate terminal
nonacceptance failure apply. Every full native acceptance gate remains required.

## Experiment 40149245104 at 4a0e81a

Both architectures passed all three focus cases. The preceding run 40148534048
stopped in unit tests because the portable extraction fixture redefined the
Windows compiler's export macro. A six-line fixture-only correction reproduced
and fixed that compilation failure without changing production declarations or
warnings-as-errors. Both native lanes then passed 2,345 unit tests, with 36 skips.

Verified x64 snapshots contain 16/3/3 rows and ARM64 snapshots contain 4/16/16.
All six report complete publication at snapshot time, with matching reserved and
published counts, no overflow, no rejected rows and no expiry. Exact original
process generations, target identities, five-second deadlines and retained-engine
exit checks match. This is focus-only evidence, not IME or delivery acceptance.

The x64 second and third cases ended observation after mouse-down and focus
messages, before any mouse-up row was retained. Other cases observed mouse-up
removal and SAL capture/release cycles. Missing later rows in a stopped observer
are censored observations, not evidence of lost input. ARM64 persistent capture
did not reproduce. Hook installation and observations can perturb scheduling;
nonreproduction does not establish a repair. The ARM64 TSF/IMM hypothesis remains
untested.

## Follow-up: remaining original focus window

Test the specific hypothesis that capture or mouse-up processing can occur after
the readiness sample. Keep the same three fresh cases and original input and
five-second deadline. After readiness returns, mark a bracket from the same QPC
clock as the native ring, including its committed boundary. This is a
post-readiness marker, not the timestamp of the original readiness decision.
Rows after its upper boundary are later than readiness; earlier or overlapping
rows cannot be ordered against that decision from this marker alone.

Immediately close the keyboard session using a separate strict diagnostic-stop
contract while the independently admitted passive observer remains active. Do not
relax the existing normal stop contract. Preserve original target generation,
ownership and native architecture admission. No navigation, ASCII, IME, repeated
input, mode mutation, capture release or new deadline is permitted.

Retain passive observation only through the remainder of the original window.
At expiry, copy bounded local evidence and release hooks/handles without new
target queries or control messages. Preserve errors and publication quality;
record early termination, partial publication, rejection and overflow explicitly.
Do not send document/Home close input after the watch. Use the existing owned
test-process teardown and retained engine exit check before another fresh case.
Forced cleanup is not graceful shutdown or acceptance evidence.

The x64 case in run 40151873961 retained 17 valid published rows, all before its
post-readiness marker, and reached the original Python deadline. It then stopped
the cohort because the shell's forced teardown completed but the retained engine
handle was not signaled at its single zero-wait check. This proves unconfirmed
exit at that instant, not a permanent orphan. Share only the unused remainder of
the existing five-second post-taskkill shell-exit allowance with one retained
engine wait; never grant another five seconds, reopen a PID or request new rights.
Absent or exhausted allowance keeps the original zero-wait behavior. Timeout,
wait error or failed release must still prevent the next case.

Static review identifies an additional teardown gap: `OwnedOfficeProcess` assigns
the launcher to a private job, but deliberately has no kill-on-worker-exit policy.
Its `close()` releases handles; `terminate()` explicitly terminates the job through
normal worker cleanup. Forced shell teardown can bypass that cleanup. Therefore
waiting alone is not a complete remedy for the diagnostic's forced-only path.
Reuse the existing retained-identity, exact-PID taskkill pattern for this focus
diagnostic only: one invocation targets the original live shell and original live
engine after validating their retained identities. Include identity work within
the existing 15-second command allowance, then share the existing five-second
exit phase. Do not reopen PIDs, enumerate unrelated processes, request new access
rights, change job policy or add observation/input time. Numeric-PID taskkill is
not an atomic handle-based operation; preserve its errors and require retained
exit evidence rather than claiming termination from command return alone.

The same trace lacked a terminal QPC sample. Record local QPC brackets around the
final local copy to distinguish native-clock cutoff coverage from a truncated or
unknown interval. Do not wait longer to close a clock gap. A cutoff crossed only
after the copy began does not prove coverage at its beginning. Clock coverage
also does not prove final event counts: a callback may publish after its final
valid clock check. Keep publication quality and callback-quiescence limitations
explicit; missing events cannot establish handler completion.

Later capture rows may demonstrate capture after readiness in this observed
window. Later mouse-up rows may establish that the initial short trace ended too
early. No later rows cannot prove handler completion, absence of every capture
call, or resolution of the original failure. Full native acceptance remains
required after an independently supported behavior correction.

## Preparation failure in 40151873961

ARM64 stopped before the first focus case at the existing observer preparation
work deadline. Discovery took 4.672 seconds; the interval from discovery exit
to compiler launch took 14.531 seconds, leaving 7.765 seconds for compilation
and subsequent validation. The compiler job was terminated and its handles
released. No native focus or TSF/IMM conclusion follows from this failure.

The prior successful ARM64 run 40149245104 used identical observer source and
native compiler hashes and completed preparation in 6.750 seconds. Its discovery,
inter-stage interval and compilation took 0.281, 2.329 and 3.609 seconds. Slowdown
therefore spans multiple operations; the receipts do not isolate hashing, file
I/O, scheduling or compiler work as the cause. Do not claim a deterministic
preparation regression or remove validation based on this comparison.

Compilation already precedes editor observation, but remains part of its own
required 30-second preparation gate, including the three-second cleanup reserve.
Moving compilation outside that gate or reusing an unqualified binary would
conceal a prerequisite. Keep this gate unchanged. A fresh native check of the
reviewed retained-engine cleanup correction tests that correction and the
remaining-window experiment; it does not establish an ARM64 preparation repair.

## Integrated-engine mode experiment after 40212924531

Acceptance at `1238a1c9953d2dcd3db63823366c3a8d892c95b0` reached the
original Calc composition gate on ARM64. Its retained IME artifact
`12607765891` has SHA-256
`a99c4f45eb63e27cc1b50c34db22770540f9bf66298b79609b10c334ae923960`.
ACK3 and the first physical G keydown observed IMM open/native mode 1/1.
About 212 milliseconds later, notifications observed open state zero, with
the same numeric context handle and no recorded focus/context transition.
No composition events were retained. Equal handles do not prove context
lifetime; the current trace does not identify the writer or TSF state.

The earlier mode experiment stopped at focus admission on the older engine.
The integrated engine now reaches the relevant first-key boundary, justifying
one use of the existing mode diagnostic on each native architecture, with
x64 as a control. Wait for the current acceptance run to become terminal
before pushing the diagnostic selection. Do not rebuild the pinned engine.

The finite question is whether typed TSF open state also closes, or remains
open while IMM closes. Joint closure supports a joint reset, not a caller.
Disagreement supports divergence at sequential observations, not an atomic
comparison. Missing, untyped, partial, overflowed or uncorrelated snapshots
are inconclusive. Nonreproduction remains subject to observer effects.
Keep the original one-case input, ownership, preparation and execution
deadlines, restoration, privacy admission and deliberate nonacceptance exit.
This experiment cannot qualify package delivery or repair Writer navigation
or the independently observed lifecycle missing-character failure.

Writer had forty successful semantic observations with a stable collapsed
body cursor away from the body end. CTRL_END insertion was acknowledged,
but delivery and handling are unproved. Lifecycle's second append omitted
M while its character message was observed removed from the queue. Neither
observation authorizes repeated input, longer deadlines or weaker semantic
assertions. Preserve these separate hypotheses for evidence-led diagnosis.

## Mode result 40216984895 and owned context-handler interval

At `6ff740408848e85825d67b2c6dfa09319d73a288`, x64 passed the actual
Calc diagnostic: 50 complete correlated rows, with 41 typed post-ACK3
observations showing TSF and IMM open/conversion 1/1. The deliberate
nonacceptance guard remained active. ARM64 reached the original composition
case and failed. Its verified artifact `12609082024` has SHA-256
`4fc77877ce9005ebe22d97eaf6e21f964e7f5284253de1e425a2b331bf061311`.
All twelve rows are complete and correlated. Rows 1–6 contain untyped or
partial TSF values; rows 7–12 are valid typed observations. Both TSF and IMM
show open zero in notifications before the observed first G keydown. This
supports joint closure, not IMM-only divergence, but identifies no setter.
ARM64's required engine retirement did not prove success; acknowledged
restoration is not graceful retirement. No acceptance claim follows.

Pinned core `bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1`,
`vcl/win/window/salframe.cxx`, has no explicit ImmSetOpenStatus call. Its
ImplSalFrameSetInputContext associates the default context or detaches it
when text input is disabled. The frame handles this through
SAL_MSG_SETINPUTCONTEXT, defined as WM_USER+144 in vcl/inc/win/saldata.hxx.
The previous observer did not include this private message.

The next finite question is whether the joint closure is observed across
this exact owned handler interval. In the existing opt-in mode experiment,
record only its entry and return using the original thread hook mechanism,
original target identity and original QPC deadline. Do not dereference or
retain either payload parameter. Install the return hook only in diagnostic
mode; installation failure must release prior hooks and the mapping.
Normal composition ABI fields, acceptance paths, input and mode writes stay
unchanged. Append only bounded expiration/rejection counters.

Pair same-owned-thread entries and returns in bounded LIFO order, using
the published sequence as interval identity. Mark nested, pending, orphaned,
expired, rejected, untyped, reentrant or partially published observations
inconclusive. Sequential IMM/TSF readings and handler reentrancy prevent
causal attribution even for a complete interval containing closure. No
observed interval does not prove that TSF independently initiated closure.
A repeated plain mode comparison, mode resend or deadline extension is not
an acceptable substitute. Full native paired acceptance remains required.

## Failed-case engine cleanup

The failed ARM64 composition in run 40216984895 retained only retirement
admission and CloseHandle, followed by forced shell exit. The failure path
released both engine-proof handles before shell teardown, so shell exit could
not prove the original engine exited. Keep the already admitted retirement
handle until mandatory failure teardown and exit observation complete.

Validate original retained shell and engine identities within the existing
fifteen-second command allowance. Use one taskkill command for the live
original targets; do not reopen a process, request new rights or retry. Share
the existing five-second exit phase between shell and engine observations,
then always release the retained handle. Preserve the identical primary
exception and record cleanup errors separately. Nonzero command status, late
waits, identity mismatch or unconfirmed exit remain failures. This forced
cleanup receipt never establishes graceful retirement or IME acceptance.

The context-interval run 40221302894 at `feed368` stopped in both native
unit suites before GUI execution: the synthetic compiler fixture's command-line
`-D__declspec(...)` collided with Windows' predefined macro before its source
guard was processed. Normalize that fixture with `-U__declspec` immediately
before its synthetic definition, retaining warnings-as-errors and a negative
compile proving the source guard is necessary. This fixture repair is not an
IME behavior correction, and that run provides no context-interval result.
