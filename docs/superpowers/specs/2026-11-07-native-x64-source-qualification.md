# Native x64 source qualification: selected specification

Status: selected design; the minimal x64 source subset has passed source-policy
review. Implementation and native Windows qualification remain to be completed.

## Outcome and boundaries

Add a real native x64 source producer for the pinned LibreOffice core
`bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1`, including the reviewed WinAcc focus
correction. Use one target-aware build implementation and two independently
qualified producer workflows. Preserve existing ARM64 defaults and the exact
legacy ARM v1 consumer contract.

The recorded ARM Full run `42304325191` at `2921b110a3b9059c6a7c7a0ed222d750dfd59286`
and Suite run `42309580135` at `39e5a49a8cf73bf2bb8e1132c9db4c596d817d47` are
outside this change: never cancel or duplicate them. Their states have not been
requeried by this design pass. A 2921 success qualifies only that original
producer; it cannot validate a later shared-driver refactor.

No new runner, permission, credential, SDK fallback, toolchain auto-install,
deadline extension, release, main merge or customer distribution is included.
Actual x64 tool availability, native execution of the approved source recipe and
330-minute feasibility remain unproven. The WinAcc source defect is not a proven cause of the separate
UIA timeout or IME failures.

## Public interface and invariant owners

The sole new producer option is
`build-native-engine.ps1 -Architecture {arm64,x64}`, default `arm64`. Existing
omitted-architecture invocations retain their original meaning. Normal Full,
diagnostic builds, and symbols remain distinct; diagnostic artifacts are never
acceptance inputs. The initial x64 mode supports normal Full only, without symbols or Calc dispatch diagnostics. Unsupported architecture/mode combinations fail before build.

| File | Responsibility and interface |
|---|---|
| `suite/engine-build/native-targets.json` (new) | Fixed tracked policy, exactly `arm64` and `x64` rows: native host/product machine, compiler profile, configure expectations, source-recipe key, proof version, fixed workflow/ref/job and artifact identities. No observed-success flags. |
| `suite/engine-build/source-build.json` | Existing source/patch pins plus the policy digest and exact reviewed recipe membership/before-and-after hashes. Existing ARM patch outputs remain pinned. |
| `suite/engine-build/apply_native_source.py` (new) | `apply_native_source(source_root: Path, evidence_directory: Path, *, architecture: str) -> dict`; CLI accepts the same finite architecture and two filesystem paths. Reads only the fixed tracked manifests. Applies an authenticated exact recipe; unknown/unclassified hooks fail closed. |
| `suite/scripts/build-native-engine.ps1` | One lifecycle: admission, native preflight, source acquisition/recipe, configure, compile, stage, PE/CRT/import checks, native Base proof, cleanup and archive/receipt. Target-sensitive helpers accept explicit finite `Architecture`, never arbitrary caller maps. |
| `.github/workflows/office-native-engine-x64.yml` (new) | Fixed x64 job `native-firebird-and-office-x64`, runner `windows-2022`, producer branch `work/opengeul-office-native-engine-x64`; invokes the shared driver with explicit `x64`. |
| `.github/workflows/office-native-engine.yml` | Established ARM workflow/ref/runner stay unchanged during initial producer-only rollout. Later reviewed shared-driver ARM validation uses a separate Full run. |
| `suite/crt.py` and existing producer `Get-CrtNames` | Preserve the existing exact nine/eight-file families and their conformance test; reuse existing PE/import primitives. Add no new filename list. |
| `suite/scripts/fetch-source-engine.ps1` | Select fixed trusted policy from independently selected lock architecture; authenticate the whole producer run, artifact and exact two-member archive. |
| `suite/prepare.py` | Strict legacy ARM v1 or explicit x64 v2 proof validation, chosen by expected architecture. |
| `suite/package.py`, `suite/payload.py` | Propagate independently selected architecture through final runtime and packaged-payload replay; preserve provenance. |
| `.github/workflows/office-suite.yml` | Choose acquisition by validated lock format; pass source ZIP/receipt for either architecture. An acquisition/validation error is fatal. |

`Get-NativeEngineTarget([ValidateSet('arm64','x64')] [string]$Architecture='arm64')`
is an internal fixed-path resolver. It verifies tracked policy bytes against the
manifest digest, exact row set/fields and architecture consistency. Public APIs
and helpers take architecture, not a caller-constructed target map. Tests mutate
synthetic policy files through a private seam; production callers cannot choose
another path or inject resolved policy.

Consumer signatures are
`validate_source_build_lock(runtime: dict, *, architecture: str) -> dict`,
`validate_source_build_receipt(runtime: dict, receipt: Path, *, architecture: str) -> dict`,
and `validate_source_build_runtime(runtime_root: Path, proof: dict, *, architecture='arm64', branding=None) -> None`.
All internal callers pass architecture explicitly. The compatibility default
rejects x64 proof. Receipts never select their own validation policy.

## Architecture and source contracts

| Fact | ARM64, preserved | New x64 |
|---|---|---|
| Native OS/product PE | `AA64`, native controller | `8664`, native controller |
| Process architecture probe | `IsWow64Process2.processMachine=0` | `IsWow64Process2.processMachine=0` |
| Configure CPU/triples | `AARCH64`, `aarch64-pc-cygwin` | `X86_64`, `x86_64-pc-cygwin` |
| Distro | `LibreOfficeWinArm64` | `LibreOfficeWin64` |
| Explicit compiler | VS2026 / v145 / native ARM tools | VS2022 / v143 / `Hostx64/x64` |
| Required external build types | Existing exact ARM requirements | `FIREBIRD`, `LIBTOMMATH`; no ARM-only `LIBATOMIC_OPS` requirement |
| CRT | Existing exact eight files and v1 terms/floor checks | `crt_names('x64')`: exact nine files, signed native runtime at least the actual configured compiler version, VS2022 redistribution terms |
| Receipt | Existing strict v1 | Explicit v2, `architecture='x64'` |
| Inner engine ZIP | `OpenGeul-Office-engine-arm64.zip` | `OpenGeul-Office-engine-x64.zip` |

Before large downloads, native preflight must prove actual OS/controller,
selected VS/cl/link/lib machine and version, JDK/JNI, required installed SDK,
matching signed CRT and a native compile/link capability. Published runner
inventory is insufficient. Missing the fixed profile stops with bounded,
secret-free evidence; no alternative SDK or compiler is selected automatically.
Pinned tooling exceptions (for example authenticated helper executables) retain
their existing exact roles/hashes, not a wholesale replacement of PE constants.

The x64 workflow explicitly uses the standard `windows-2022` runner. Its
[official image inventory](https://raw.githubusercontent.com/actions/runner-images/main/images/windows/Windows2022-Readme.md)
(version `20261101.353.1`, checked 2026-11-07) lists VS2022, native C++ components
and JDK21. This is a host choice, not proof of installed capability: the same
fixed VS2022/v143 preflight must pass on the actual allocated runner. The first
`windows-2025` run passed its 25 Windows unit checks but returned zero instances
from the filtered VS2022/native-component query and stopped before compilation
or source acquisition. This does not establish that all VS2022 installations
were absent; the
[Windows 2025 inventory](https://raw.githubusercontent.com/actions/runner-images/main/images/windows/Windows2025-Readme.md)
also lists VS2022. Zero or ambiguous filtered selections retain a read-only
unfiltered instance diagnostic under the same deadline and still fail closed.
There is no automatic runner/profile fallback or tool installation.

The reviewed source-policy inventory approves exactly `moduleBootstrap` then
`winAccFocusOrder` for x64. Both are common exact-hash corrections whose
before/after transformations were independently recomputed. Exclude the 13
existing ARM-guarded source/recipe targets; their need or safety on x64 is
unknown. Future unknown hooks or recipe-membership drift fail closed. This
source-only approval does not prove actual x64 build/runtime behavior.

Preserve the ARM sequence: the full existing ARM installer, which already
includes bootstrap, then the separate WinAcc installer. Never prepend bootstrap
to that sequence or invoke the entire ARM installer as x64. Preserve established
ARM recipe outputs. Configure explicitly requests archive packaging and existing
OEM-service exclusions after distro defaults; generated configuration is checked.

The fixed x64 target row selects the official VS2022 redistribution URL
`https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution`;
`Save-VcRedistributionTerms` snapshots and hashes that page and joins it to the
selected compiler profile. Preserve the existing ARM VS2026 terms URL/checks.
Actual availability of all nine signed x64 CRT files remains a fresh-host gate;
missing files stop without an SDK/runtime installer or alternate-profile fallback.

## Admission, time and qualification

Normal Full always enforces owner, first-push event, first attempt, exact source
HEAD/tree, repository, workflow/ref/job and workflow-source binding, independently
of `-MutexSymbols`. Symbols retain their additional requirements. The shared
driver owns one absolute 330-minute deadline within a 360-minute job, including
preflight through cleanup/proof. Preserve `$script:NativeEngineBuildBudget` in
the same script scope; target loading or helper imports cannot reset it.

The fixed x64 artifact prefix is `opengeul-native-x64-engine-<run>-<attempt>`.
ARM retains its existing workflow, ref, job, prefix and inner filename. Trigger
tests cover branch/path/shared-dependency filters and concurrency: an x64 push
must neither start nor cancel an ARM run. No combined matrix qualifies inputs.
The fetcher still requires the entire selected run to be `completed/success`;
a successful artifact-producing job inside a failed run is insufficient.

The x64 v2 proof joins actual source/run/attempt/workflow identity, driver and
policy/recipe digests, exact applied patch receipts, generated configuration,
native installed product inventory, CRT/legal proof and normal/delay-import
closure. It explicitly includes native `program/winaccessibility.dll` size/hash
and import closure tied to the applied WinAcc recipe. Require actual native
Base creation, a separate independent reopen preserving the fixed synthetic
Korean row, and original owned-process retirement. Emit qualification flags only
after all producer gates pass; `guiVerified` remains false.

## Staged adoption and acceptance

First land producer support on the fixed x64 branch after root review. Keep the
existing ARM producer branch and all consumer runtime input locks untouched.
Implement consumer changes against the current Suite checkout on
`work/opengeul-office-arm64`, preserving its newer files. Selectively integrate
only reviewed target policy and necessary source metadata; never copy the old
producer checkout's `prepare.py`, `package.py`, `payload.py` or ARM runtime lock
over those files. Consumers may gain strict support without changing selected
inputs. The existing x64 lock is `suite/config/runtime.lock.json`, as selected by
`build-suite.ps1`; there is no `runtime.x64.lock.json`. The main
checkout's qualified ARM `6714099caea00c800c900272574ae1c6b6144225` / run
`42203789086` pin remains until separately qualified adoption. The producer
checkout's stale ARM lock must never be copied into the main checkout. No
successful x64 source lock or receipt is fabricated as scaffolding.

After actual x64 Full qualification and exact outer/inner/receipt hash and
provenance verification, a separately reviewed lock change can select it. The
Suite must then compile and run the actual x64 menu, focus, accessibility,
Korean input, create/save/reopen, document/module transition, lifetime and
applicable install/update/repair gates. A later changed-driver ARM Full and ARM
Suite are separate required regression evidence before adopting that ARM output.
Failures remain failures; no cross-architecture relabelling or MSI fallback.

Source recipe classification: [reviewed inventory](2026-11-07-native-x64-source-recipes.md).
