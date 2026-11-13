# Isolated SDK compile/selftest CI candidate — not Windows-qualified

This repository-relative proposal ports the reviewed scratch SDKv2 into an isolated diagnostic job. The existing product jobs keep their original bodies and old-ref behavior; only the new `refs/heads/work/opengeul-office-package-context-sdk` is excluded from normal Suite. That exact public owner push, first attempt, is the only new entry. No Main/native checkout, branch, workflow run, SDK installation or Store action has been changed by preparing this proposal.

The job reuses the existing static `matrix.os` runner policy (`windows-2025`, `windows-11-arm`) without changing permissions, runner allowlists or cost settings. It discovers only preinstalled native Python3.12 and installed VS/SDK; missing prerequisites fail the job. It does not call setup-python, pip, a package manager or an installer. Workflow literals pin `ci_entry.py`, the bootstrap and the approved eight-file code manifest before running the isolated interpreter. The CI entry independently requires the exact repository/id/owner/actor/ref/attempt/source/workflow SHA and detached checkout HEAD.

The CI entry uses the same typed private Job mechanism to enclose the bootstrap, with one original180-second window propagated to the child without renewal. Compiler phases still use the base30-second policy; the enclosing role alone has a fixed180-second cap. Both reserve the final second for cleanup and require actual root exit, empty Job and successful handle closure. Environments are new finite dictionaries; RUNNER_TEMP is the sole additional child field needed for the bootstrap's existing root-ownership guard. Stdio stays NUL. Real Windows nested-Job behavior and hard OS preemption remain unverified.

Only `.work/packaged-context-sdk-public/<fixed-runner>/report.numeric.json` is uploaded. It contains source/run binding, status, cleanup and validated PE/COFF/hash records, with no binary, object, private metadata, compiler output, environment or source tree. Unavailable reports remain unknown. Diagnostic failure is a job failure, with no `continue-on-error`; successful compilation/selftest grants no customer/UI/runtime/package/Update/Repair qualification.

Original observer runtime3 and its bundle SHA are unchanged. The historical13-file manifest is preserved; `frozen-v2/source-inputs.json` separately binds every original/effective pin. Its only transformation is the copied README's relative reproduction command. Historical59-test evidence is not reissued against changed documentation. Original pure40/lease6 and scratch SDK27/25 plus reviewed30/32 evidence remain separate and unchanged.

The original27-file/25-test candidate is preserved separately. Its P2 fix and independent re-review produced32 passing portable tests. The current CI proposal has47 portable tests, failures0/errors0/skipped0, plus five existing historical Writer/workflow compatibility checks. These include actual Linux g++ compilation/execution of the fixed negative entry against the frozen pure `collect` implementation and a getter seam. They do not compile or execute the Windows SDK port. The PowerShell workflow body was parsed only, not executed.

The implementation is narrower than the original plan: the Windows path compiles the actual frozen port and fixed smoke entry, links them, and runs only invalid/expired rejection. It does not rerun the old synthetic core cases, portable59, pure40, or lease6. All thirteen v2 original deliverables are copied byte-for-byte with the original manifest. Main/native/CI and the original helper files were not edited.

`supervisor.py` uses the original absolute per-phase deadline with a one-second cleanup reserve. It requires root exit0, empty private Job, retained-generation checks and successful local/handle cleanup; timeout/cancellation/uncertainty cannot pass. It terminates only the private Job, never a PID reopen or another process. `owned_job_win32.py` preserves the reviewed SDK adapter's entire NativeApi class byte-for-byte; only its environment validator changes to a complete finite compiler environment. Its atomic Job/handle attribute lists, suspended creation, NUL stdio, pre-resume identity checks and original HANDLE ownership are unchanged. The C++ entry has no request parser, path input or normal-observation switch. The child environment is a newly constructed dictionary; the parent environment is not copied or iterated. The sole CLI parent lookup is nonsecret `RUNNER_TEMP`.

## Files and proposed Windows invocation

- `approved_launch.py`: isolated, externally pinned bootstrap; validates the fixed eight-file code graph against the external expected manifest SHA before importing any candidate runtime module.
- `ci_entry.py`: exact public-owner/source admission, fixed private-Job bootstrap envelope, typed private-report validation and one closed numeric publication.
- `run_sdk_gate.py`: future Windows-only source/tool admission, private staging, compile/link/smoke phases, closed numeric receipt. Direct script invocation is rejected; a missing/forged code context is rejected before OS/tool setup. Header/entry staging rechecks their approved hashes.
- `toolchain.py`: canonical files, native PE/COFF machines, exact thirteen-file observer pins, installed VS/SDK inputs. No installer, download or authentication.
- `supervisor.py`, `owned_job_win32.py`: bounded private-Job process control.
- `sdk_smoke.hpp`, `windows_sdk_smoke.cpp`: two internally constructed negative requests. Pure validation/QPC rejection occurs before package, KnownFolder, WinRT or file getters.
- `tests/`, `run_portable_checks.py`: only the new portable contracts; no ordinary Windows test-discovery or workflow changes.

An authorized future standard-runner invocation would use existing Python/VS/SDK only, a new UUID root directly below that run's RUNNER_TEMP, and a receipt named `sdk-gate.numeric.json` inside it:

```text
python -I -B suite/engine-build/packaged-context-sdk/ci_entry.py --architecture x64 --expected-entry-sha256 <workflow-literal-SHA256> --expected-bootstrap-sha256 <workflow-literal-SHA256> --expected-approved-manifest-sha256 <workflow-literal-SHA256>
```

The ARM64 job changes only `--architecture arm64`. The proposed workflow verifies the reviewed entry/bootstrap/manifest SHA literals first; it never computes approval from current files. The CI entry creates the bootstrap's fresh explicit nonsecret environment. Its manifest includes the CI entry, bootstrap and six SDK files; external expected SHA avoids a hash cycle. The proposal has not been applied or run. Missing/mutated code, missing tools, SDK headers/import libraries, native compiler or clean process retirement are failures. No fallback install is supplied.

## Unresolved gates

The new CI proposal's independent review and actual Windows toolchain/SDK ABI/link/run are pending. Installed Python cache/SDK registration availability (including registry view), VsDevCmd and nested-Job behavior are still unobserved. The code root must be controlled by the trusted runner caller. Paths and code are checked before/after; no atomic protection against malicious concurrent namespace/code replacement is claimed. Each compiler child has at most30s (cleanup1s inside), with a shared180s enclosing monitor; the step4-minute and job6-minute limits are final platform bounds, not proof of cleanup within180s. Synchronous OS calls in the monitor itself cannot be preempted by its own before/after checks. All Windows/watchdog verification flags remain false until genuine observations exist.

This diagnostic supervisor is not the missing packaged-helper launcher/original HANDLE creator. Actual package-context getters/FileIDs, durable lease, UDF equivalence, side-effect-free OS initialization, Update, Repair and servicing authority all remain unverified/false. No package is installed, launched, changed or serviced by this candidate. No new runner, workflow, credentials, certificate, permissions or cost was introduced.


## Exact OS command-processor binding

The command processor uses a separate lease for the exact `cmd.exe` selected by `GetSystemDirectoryW`. It requires WRP protection classification, ordinary non-reparse paths, native PE bytes and stable retained/fresh file identity, final path, metadata and digest. The noninheritable read handle shares only read access and remains held through the relevant controller/helper phases. Other source, SDK and tool inputs keep their original single-link policy.

WRP is protection classification and this lease detects ordinary changes; neither establishes a Microsoft signature or cryptographic OS attestation. Generic canonical/read/PE guards, observer source pins and original Job budgets remain unchanged. Native calls check the original deadline individually; those checks do not make a synchronous OS call preemptible. Cleanup still attempts one close after expiry, and an uncertain close cannot pass.
## Fixed SDK header directory

SDK input slot3 is `Include/<version>/shared/sddl.h`. Microsoft's official
win32metadata source places this header at
[`generation/WinSDK/RecompiledIdlHeaders/shared/sddl.h`](https://github.com/microsoft/win32metadata/blob/15fc870a5e96df7c560877ff30136c0fb5a21e9b/generation/WinSDK/RecompiledIdlHeaders/shared/sddl.h),
blob `f7e67f5a941a2737cd4eca0711c232356fafc903`.
There is no alternate-directory search or `um/sddl.h` fallback. All16 member
positions and hashes, strict regular/single-link checks, architecture/version
selection, and30/180-second budgets remain unchanged.

The6d9 run43312663925 records the previous `um/sddl.h` request failing with
FILE_NOT_FOUND for x64 SDK10.0.26100.0 and ARM64 SDK10.0.26100.0/10.0.22621.0.
Those records are historical failures, not success evidence for this correction.
The new literal-layout tests use synthetic bytes only. Actual installed shared
header availability and Windows compile/link/negative-smoke success still need
the next owned diagnostic run; no servicing or product qualification is granted.

Raw helper protocol2 and public protocol6 add an ordinal-joined pre-cleanup
observation array. `helperPreCleanup` is null if diagnostic storage was unavailable;
this is unknown, not a completed phase observation. An array has exactly as many entries as the unchanged
15-field `helperPhaseResults`. Each entry is either null (diagnostic unavailable)
or has exactly `firstRootExitCodeBeforeCleanup` (null or uint32 except259),
`lastRootWaitBeforeCleanup` (null,0 or258), and
`lastJobMemberCountBeforeCleanup` (null or0..128). Three null fields mean no
validated active-loop sample. The loop uses its existing API results and clock
reads; cleanup snapshots never fill these fields. A first root exit does not prove
compiler creation, compilation, the cause of failure or the time of a child-side
batch checkpoint. These observations never participate in the original success
gate. Current readers reject old raw/public protocol labels and missing or
misjoined new packets instead of relabelling historical results.

The optional sink accepts only a fresh plain dictionary. A malformed/unavailable
diagnostic packet becomes null without replacing the original command result or
post-Runner lease check. Native stdio remains NUL and the NativeApi byte sequence,
source13, private Job,30/180-second deadlines and cleanup reserve are unchanged.
The normal SDK path has no batch checkpoints or compiler stdout capture.
Child-written markers in the separate opt-in path below are untrusted hints;
actual CMD return-code equivalence and Windows behavior remain unverified.


## Explicit B3 first-C2338 numeric detail

The exact SDK branch opts in with `[sdk-batch-codes]`. This replaces the current
B1 workflow route. B1 source2ac and B2 sourcebd2894, their approved manifests,
strict readers and actual ZIPs remain immutable historical evidence. Historical
receipts are not relabelled or selected from their own version fields. Without
the explicit marker the normal SDK
execution, public protocol6 and original one-file artifact retain their behavior.
B3 uses separate schema3 and `--instrumented-batch-codes`; its verifier is
`--verify-batch-codes-only` with the same architecture/three expected source-pin
options. The verifier's separate five-field response remains schema1.

B3 retains only two literal private leaves, `sdk-port.stdout` and `sdk-port.stderr`,
for the first port compile at phase3. The parent exclusively precreates ordinary
single-link files, records their original device/file IDs and closes both FDs
before CMD starts. Only then may the original tool command append redirections.
No smoke/link capture, extra canary, phase, runtime module or Job is added.
Compiler flags, ERRORLEVEL handling, Source13, finite environment,30/180 limits,
NativeApi and its outer NUL stdio remain unchanged. Successful precreation does
not prove Windows redirection sharing or truncation behavior; the next actual
run must observe it. A changed or unsupported identity is unavailable.

After the original postlease/command result and proved root exit, empty Job,
generation/cleanup and4handle closes, B3 may read the fixed pair within the same
original overall deadline. Forced cleanup does not prevent reading when that
retirement is proved. Each file is checked against its original dev/ino and
stable path/open-handle/final metadata, including single-link/no-reparse guards.
Normal zero bytes, missing, oversize, invalid UTF8 and unstable identity remain
distinct numeric statuses. FD-close uncertainty stops further I/O and children;
original operation failure and cancellation retain priority. Synchronous OS calls
are not made preemptible by before/after deadline checks.

Only the existing pure C/D/LNK projector is reused, with the fixed four SDK source
roles. Its AST differs only in function and FILES-symbol names. The old IME
three-case/nine-pin collector and its PIPE/60-second capture path are untouched.
B3 reads at most65536bytes per stream,128KiB total, decodes strict UTF8 and retains
at most32 numeric descriptors. The existing65536-character/512-line/4096-line-
length parser limits remain. No chcp, VSLANG or warning-policy change is made.
Read cap is not a disk-write quota. Raw files stay private, are never printed or
included in artifacts, and may remain in the owned temporary root until runner
cleanup. No paths, argv, environment, source text or error prose is published.

`firstC2338Detail` is null unless the published descriptors contain C2338. One
numeric row then binds the first C2338's one-based `diagnosticOrdinal` and
`streamCode`. `sdkSlot` is8 for the authenticated SDK16 base.h full path,9 for
Windows.Storage.h, or0 for unknown; an unknown slot has `line=0`. These two paths
are constructed from the existing authenticated SDK result, without any header
read. Basename, suffix and namespace aliases cannot acquire an SDK slot. The
original four source roles and their unknown-file/line rules stay unchanged.
`assertionClass` recognizes only exact public literals:1 Mismatched C++/WinRT
headers.;2 Not an awaitable type.;3 Only native x64/ARM64 observers are supported;
4 T must be WinRT type. Unknown or ambiguous text is0. No literal text is stored
in the receipt. A detail-only failure preserves the original descriptor and its
ordinal/stream with slot/line/class0; cancellation keeps its original priority.
This extra analysis reuses the already-read strings and adds no file I/O,
Native API, phase, capture pair, SDK metadata collection or time allowance.

`scanComplete` means only that the projector scanned the stable bytes that were
read. It does not prove complete compiler output, compiler creation, execution,
termination history or object generation. After forced cleanup some output may
be absent. Numeric codes, an empty diagnostic list, read success or a tool-command
return hint never change `compilerInvocationProved`, `originalSdkGateExecuted`,
`acceptanceEligible`, `qualification` or `canService` from false. The original SDK
report SHA stays null. COFF/link/negative checks and the intentional nonacceptance
terminal retain their independent conditions.

Only the two fixed B numeric JSON files are uploaded, each at most8192bytes.
The independent reader requires exact B3 keys/types, source/run/attempt/approval
binding, actual controller-byte SHA and matching retired phase for every successful
stream, including mixed success/unavailable packets. Missing/unknown fields,
bool-as-int, wrong versions, aliases, stale identities and forged authority reject.
Old B1/B2 and normal SDK schemas cannot pass as B3. Portable synthetic results are not
actual Windows, compiler, package-context or customer acceptance evidence.
