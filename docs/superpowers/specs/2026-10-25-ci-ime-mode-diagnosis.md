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

## Next experiment: owned capture ordering

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
