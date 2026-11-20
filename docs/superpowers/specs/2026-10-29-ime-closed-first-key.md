# Original first-key IME closed-mode diagnosis

Paired normal Windows execution reaches the first physical Korean key in ARM64
Writer and Calc, but composition does not begin. Existing numeric mode samples
show a final open value of zero with native conversion enabled. These values do
not identify the setter or prove which callback changed the state. The former
exact-US guard cascade was not observed in this execution.

## Chosen approach

Use the existing standard `ime-mode-diagnostic` mode for one original, owned ARM64
Writer case. Preserve the normal prefix evidence, pinned runtime/plugin/PDB
identity, first-key eligibility, single callback capture, finite work/watchdog
budgets, original input sequence and retained process-generation cleanup. Reuse
the already implemented closed carrier 3 and exact-source numeric consumer.
Do not replay input, renew a budget, repair focus/layout/IME state or manufacture
a callback when the capture is absent or capped.

The alternative of another normal run would not expose the first callback's
matched setter frames. Broad raw log/document collection is unnecessary. This
diagnostic deliberately cannot qualify acceptance or produce a deliverable ZIP;
x64 remains a unit/control boundary. Restore paired normal acceptance after
evidence-backed corrections, then validate all final gates on the final source.

## Independent API input correction

The Writer OS probe passes five fixed interface identifiers to comtypes.GUID.
Microsoft documents the CLSIDFromString representation with braces, and comtypes
forwards strings without adding them. Add braces to the five literals while
keeping their UUID bytes, native calls, service/target interface identities,
watchdog, reference/VARIANT cleanup and primary acceptance checks unchanged.

Strict synthetic GUID boundaries reproduce an early root failure and then pass
after normalization. The observed Windows root failure has zero acquired COM
references, but that shape does not uniquely establish this cause. A zero
preserved HRESULT at this stage is not evidence of a successful native call.
The correction still requires real Windows OS-gate verification in a later
normal run; the targeted IME mode does not exercise that gate.

Primary contracts:
- https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/nf-combaseapi-clsidfromstring
- https://raw.githubusercontent.com/enthought/comtypes/1.4.17/comtypes/GUID.py

The workflow pins pywinauto but leaves its comtypes dependency transitive. The
currently installed Windows comtypes version was not captured, so do not claim
that the linked source version is the runtime's measured version.

## Verification

Exercise actual RawComBackend root, canonical identity, both service interfaces
and the full observer with a strict synthetic GUID boundary. Require balanced
cleanup and no text reads. Run the configured Linux suite and diagnostic routing
checks, review exact staged bytes, check remote/active runs before push, and read
the terminal closed numeric evidence. Keep x64/ARM64 results and diagnostics
distinct from product acceptance, preserve all stop decisions for old artifacts,
and leave main, releases, deployment, costs and credentials unchanged.
