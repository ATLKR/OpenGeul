# Opt-in paired Windows print diagnostic

This additive tool compares locked HWP 1.1.4 with the current same-run package
on two fixed, already generated synthetic inputs. It is always nonqualifying.
The ordinary eight print cases, exact golden masks, source-preservation checks,
normal result and success-only PDF collector remain unchanged.

The roles are `locked-hwp114` (source131ccbf3, rhwp0.8.7) and `current`
(independently expected checkout/run/attempt, rhwp0.9.0). HWP1.1.4 is **not** the
exact golden756 producer. The current native helper's source/run fields bind the
harness and are separate from the old binary's compile provenance.

## Portable checks

From the repository root, using the existing print-test dependencies:

```sh
python -m unittest discover -s e2e/print_tests -v
```

The paired tests replace external Windows ports only. They exercise the actual
print function and retained binder bodies, plus pure admission, cleanup,
original-exception and evidence predicates. Passing these tests is not Windows,
printing, loaded-WASM or release-qualification evidence.

## Future owned Windows job integration

Run only in the existing owned standard x64 virtual-print job, after normal
package/WASM selection and the original once-only synthetic fixture generation.
Use the job's independently established checkout SHA, run ID and attempt. Keep
its PR test-merge binding separate from the event head. Select the package from
that same run and pin its provenance SHA before invoking this tool. The tool
does not discover remote artifacts or grant CI authority to an input receipt.

Example argument shape (placeholders require genuine values):

```text
python e2e/paired_print_run.py --run-paired-print
  --harness-source <exact-checkout-SHA> --run-id <run> --run-attempt <attempt>
  --current-provenance-sha256 <independent-provenance-SHA256>
  --package package --wasm wasm-input --inputs inputs/e2e-fixtures
  --fixtures print-fixtures --legacy-cache paired-locked-inputs
  --legacy-runtime paired-legacy-runtime --current-runtime paired-current-runtime
  --work paired-private-attempts --output paired-print-evidence
```

The legacy cache requires `legacy-portable.zip` and `legacy-provenance.json`.
Without them the default refuses, before transport or printing. Only a
separately authorized `--acquire-legacy` uses Suite's existing fixed canonical
v1.1.4 URL/size/SHA route, with no latest or alternate fallback. Authentication
and permission denials must not be bypassed. No download was performed while
developing this candidate.

`prepare_payload` verifies the current complete MSIX/portable parity. Exact
external source/run/attempt, same-run editor component, actual editor bytes,
actual MSIX hash, source-bound six WASM inputs and authentic historical pins are
checked separately. A new runtime directory is required for each role.

All eight original case descriptors are validated before selecting table--300
and basic-hwpx. Their bytes are hashed once, reused for both roles, and checked
before/after every print. There is no per-role document regeneration. The print
path retains its original Session, native UI/foreground/DPI guards, owned queue,
spooler completion, paper geometry and exact reviewed ink oracle.

Admission captures the original Popen root handle and original known WebView
generations. Separate SYNCHRONIZE handles provide the exit barrier. A complete
pre-cleanup census, sampled shutdown census and those original handles are
required; new descendants, stale identities or an incomplete census block the
next case/role. This proves the **captured cohort's** exit, not that every
possible transient descendant was observed. Existing owned cleanup may force
termination; it is not a normal-close or servicing proof.

Only the unchanged oracle's final ink-mismatch source frame is comparable.
Other failures and unknown retirement stop the sequence. The original ink
exception is retained in memory, the bounded comparison evidence is exported,
then that original exception is rethrown. The command still exits nonzero.
No tolerance, reference or success-only normal collector is changed.

## Evidence and limits

Upload only `paired-print-evidence/` from the deliberately enabled diagnostic
step, preserving the original print job's result. Never upload the private work
tree through this new collector. It exports only four synthetic PDFs, four
single-page rasters and a numeric JSON manifest, capped at 8 MiB/file and
48 MiB total. Exported bytes must match observation-time hashes. Inputs,
screenshots, traces, console/error strings, URLs, environment, command lines and
font bodies are not copied.

The manifest retains original oracle failures and separately records:

- actual binary/hash and sampled native process identities;
- requested profile filesystem identity, `actualSelectedProfileKnown=false`;
- sampled Arial/Malgun installed file hashes, not actual selected glyph fonts;
- build WASM provenance, `actualLoadedWasmIdentityKnown=false`;
- `qualification=false`, `acceptanceEligible=false`, `sourceQualified=false`.

The requested profile is not evidence of effective isolation. Font sampling is
not proof of every font used. The comparison does not establish pure SVG,
Skia, WASM or profile causality. Historical golden PDF/PNG, fixture hashes and
selected font identities are missing. Effective profile/module observation, if
needed, requires a separate reviewed follow-up; no raw command-line query is
added here.

The current regular-file sampler requires one link. The actual Windows font
files' link counts have not been observed; legitimate system hardlinks would
therefore make this candidate refuse before printing. That OS compatibility
limit is unverified, and no broad link acceptance is added speculatively.

## Workflow and bounded failure context

The additive workflow steps run only after input preparation and a completed
normal print attempt, on windows-2025 in a public, same-repository draft pull
request whose exact head branch is `work/opengeul-office-arm64`. No job, runner,
input, permission, timeout, release or Store condition is added or broadened.
The normal print step, success-only normal PDF collector and normal evidence
path keep their original behavior. The new diagnostic's nonzero exit does not
erase an earlier normal failure.

The paired upload uses `always()` only after a separate admission step succeeds.
That step rebinds the expected source/run/attempt, authentic canonical old
assets, actual current package checksums/renderer/WASM, the two unchanged
generated fixtures, original report/retirement/profile contract, nine-file
allowlist and 48 MiB cap. It independently replays the unchanged PDF oracle and
PNG fingerprint and rejects metadata/font/input drift during verification.
An ink mismatch may produce admitted **nonqualifying evidence** while retaining
the original failed oracle and failed job. An incomplete pair is not uploaded.

Failures print closed numeric JSON only. Stage codes are 1 preflight, 2 locked
legacy input, 3 current preparation, 4 current admission, 5 fixture binding,
6 installed font sampling, 7 print comparison, and 8 collection/admission.
File/function codes map only to the known source functions listed in
`paired_print_run._SOURCE_FUNCTIONS`; line numbers are bounded to 1..20000.
At most 12 known frames are emitted while inspecting at most 64 traceback links.
Unknown source is counted without emitting its filename or function name.

`knownRole` is 1 locked-hwp114, 2 current, or 0 unknown. `fontCode` is 1 Arial,
2 Malgun, or 0 unknown. Existing stat size (0..512 MiB) and link count
(0..65535) are retained only when already observed and exactly typed; otherwise
their Known flags are false. Projection performs no new file/process query and
reads no exception text, args, repr, locals, environment or command line. A
diagnostic cancellation cannot replace the existing failure or weaken a guard.

Failure stdout uses `paired-print-failure-numeric` schema 2, with the original
numeric fields and nullable `censusObservation`; historical schema 1 has no such
field. The optional schema-1 census record contains only the already-observed
root PID/original creation time, sealed/live-root-check flags, snapshot/known/
guard-unexpected counts and up to 64 PID-sorted `{pid,parentPid,executableRoleCode}`
rows. Codes 1/2/3 mean exact `msedgewebview2.exe`/`conhost.exe`/`werfault.exe` names
after ASCII-only case normalization; all other names or shapes are 0. Raw names
and paths are never emitted. The
guard expands from all retained PIDs; its unexpected count is separate from the
rows whose snapshot parent chain reaches the root PID. That chain is neither
current ownership nor process-generation proof. The record is diagnostic only,
never acceptance eligible, and absent/invalid observation remains unknown while
the original rejection and cleanup priority are retained. No new process query,
handle, late adoption, input or collector permission is introduced.

Actual Windows execution, legacy transport, CI submission, installation and
publication remain unperformed until the owning task integrates this candidate.
