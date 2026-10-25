# Static mapping of the observed SAL wait offset

Run 40157695775 at c34b238 captured two failing ARM64 mouse-up retrievals with
the same combase.dll frames followed by sal3.dll return RVA 406484. The passing
case follows a different mergedlo.dll path. Retrieval publication and cleanup
are valid; stacks are capped and contain unknown frames. Origin observations
support a coordinate-conversion change but do not establish its cause. A passing
x64 case also has the client-coordinate difference, so that difference alone
does not imply capture failure.

Pinned source has a compatible candidate: osl_waitCondition calls the SAL helper
that invokes CoWaitForMultipleHandles(COWAIT_DISPATCH_CALLS). The offset has not
been mapped to a function. Do not change COM flags or suppress owned host work
on this correlation alone.

## Bounded next analysis

Use the existing authenticated CI engine fetch unchanged, then parse only the
locked archive's program/sal3.dll as data. No Office process, window, hook, input,
IME setup, memory inspection, symbol server or additional service is needed.
Do not download or upload the engine binary/archive through another route. The
previous local Forbidden remains a separate restriction. Output only bounded
static mapping metadata, hashes and provenance.

Verify archive size/SHA256 against runtime.arm64.lock.json through a held file;
require exactly one regular, unaliased program/sal3.dll member within a 32 MiB
decompression bound. Parse PE32+ ARM64 headers with checked RVA/file mappings,
bounded export tables and ARM64 exception/unwind function lengths. Map the return
RVA and its preceding four-byte call instruction to the same function range.
An export must start at that exact range to name the function conclusively;
nearest earlier export, forwarded export, fragment, missing or ambiguous range
is inconclusive. Do not guess from proximity. Retain malformed-input failures.
One 30-second analysis deadline covers hashing, decompression and parsing; no
renewal or retries. Native fetch retains its own existing authenticated deadline.

Add an explicit nonacceptance static mode to the existing workflow. Reuse
Assert-Native31Context for exact owner-push/first-attempt admission before fetch,
and require HEAD and tracked source bytes to match the event commit. Native unit
and shell checks remain. Skip package/desktop preparation only in this new
file-only mode; existing GUI modes retain every privacy/input/preparation gate.
Upload only the mapping receipt and deliberately prohibit package qualification.
No other acceptance conditions or existing modes change.

## Decision threshold

An exact exported function/range match can confirm or reject the SAL source
candidate without another GUI experiment. It does not prove COM apartment/filter
state or that altered dispatch flags are safe. A behavior correction additionally
requires a deterministic test of the identified wait/message-handling defect and
review of deadlock/reentrancy consequences. An inconclusive static map is reported
as such; no identical rerun follows automatically.
