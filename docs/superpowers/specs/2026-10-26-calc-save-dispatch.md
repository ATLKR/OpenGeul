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

Interpret the numeric trace alongside the original input/save oracle and
confirmed process-exit evidence. Validate native nesting, generation/deadline
rejection, event publication, ABI, cleanup failures, and artifact isolation
locally, independently review the change, then compile and run it on the
existing Windows ARM64 runner. Product corrections need causal evidence and
fresh full x64 and ARM64 acceptance on the final corrective commit.
