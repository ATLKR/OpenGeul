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

For x64, the runtime floor is the selected MSVC **package** version, explicitly
correcting the former maximum-of-tool-resource-builds rule. The compiler plan
records `runtimeFloorBasis='selected-msvc-package-v1'` and
`toolsetMetadata={path,size,sha256,version}` from the same selected VS
`VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt`. Require a regular,
unlinked file of 1–4096 bytes whose numeric version equals the selected compiler
directory; normalize that package version to four parts for
`minimumRuntimeVersion`. Preserve each tool's independently measured PE/hash,
resource family and native `_MSC_FULL_VER` witness. Recheck the original
metadata descriptor at configured-toolchain admission and final qualification.
Preserve the matching raw metadata bytes as
`native-selected-toolset-version.txt` in diagnostic evidence only; the runtime
artifact's exact two members do not change.

The x64 CRT directory label is path identity, not a DLL-version proxy. Within
that same VS installation, only the fixed native VC143 family and the existing
nine filenames are eligible. Every file and product resource version must meet
the package floor, with all existing Microsoft signature/company, PE, size and
hash guards. Incomplete or actually old sets are ineligible; a complete
version-eligible set with a signature/PE/structural error fails rather than
triggering fallback. Rank valid sets by their actual minimum file version,
descending, then directory name in ascending ordinal order. Record
`selectionBasis='actual-signed-crt-files-v1'` and `selectedFileVersionFloor`
from the actual nine signed file records. ARM v1 retains its existing floor,
folder selection and receipt behavior. Package metadata is provenance, not a
Microsoft signature; unsigned observations do not qualify a runtime. Consumers
replay the recorded path/version/hash joins and authenticated receipt; root's
independent adoption check can additionally hash the separate raw evidence.

The x64 recipe is exactly `moduleBootstrap`, `firebirdLoaderPath`,
`zstdSourceLinks`, then `winAccFocusOrder`. The loader hook reclassifies only
`external/firebird/ExternalProject_firebird.mk` after a real x64 examples/isql
loader failure and an authenticated nested GNU make reproduction exposed two
concatenated complete PATH assignments and the wrong Windows DLL directory.
This establishes the source-expression defect, not that every loader failure
has the same cause. The correction uses one existing helper for ICU/source/lib
and Firebird/bin, guarded specifically by WNT_X86_64. It adds no driver PATH
workaround or feature skip to the x64 build.

The zstd hook separately reclassifies only
`external/zstd/UnpackedTarball_zstd.mk`. Actual run `42336380144` failed while
creating `tests/cli-tests/bin/unzstd` as a symlink to `zstd`; this was a tar
symlink-creation failure, not proof of a missing zstd executable. The x64 recipe
had left this source file unchanged under global `winsymlinks:nativestrict`,
whereas the established ARM helper already confines a `winsymlinks:sys`
exception to the exact zstd unpack target. The new x64 hook adds that same
target-specific policy only under `WNT_X86_64`, using
`$(call gb_UnpackedTarget_get_target,$(ZSTD_TARBALL))`. It does not alter global
CYGWIN, other unpack targets, Linux, or the existing ARM helper. No package,
privilege, SDK or ABI change is part of this correction. The original archive
was unavailable for this investigation, so member ordering, the full link chain
and the exact Cygwin failure cause remain unverified. The policy difference is
consistent with the observed failure; actual native unpack, Full/Base and GUI
gates still have to verify the correction.

`windowsFirebirdLoaderPath` and `windowsZstdSourceLinks` in the fixed source
manifest pin their exact paths, conditions, before/after byte counts and SHA256
values. The original ARM helper, twenty-one ARM output files, ARM recipe hash
and thirteen-row ARM guarded plan remain unchanged. The x64 plan retains
seventeen authenticated source inputs: six common rows and exactly eleven
unchanged ARM-only source guards. The zstd archive provenance stays bound by
the existing manifest entry; its ARM descriptor is unchanged.
Future unknown hooks, source-pin changes or recipe-membership drift fail closed.
Source-only installation never proves actual native build/runtime behavior.

The x64 `sourceHooks` record contains `firebirdLoaderPath` and
`zstdSourceLinks`. Each thirteen-field hook receipt has schemaVersion=1, its
fixed kind/path/condition, beforeBytes/afterBytes, beforeSha256/afterSha256,
original/effective evidence paths, and typed false
nativeBuildVerified/fullEngineQualified/acceptanceEligible/guiVerified flags.
The zstd kind is `windows-zstd-source-links-source-hook`.
`sourceRecipeProof` retains its existing keys; hookOrder has
the four entries above and armGuardedSources contains the eleven exact
unchanged ARM-only path/hash rows. ARM retains its two hooks and thirteen rows.
The driver checks both x64 descriptors and actual retained evidence bytes against
the manifest, rather than using diagnostic success as engine qualification.
The runtime artifact still has exactly its original two members.

The POSIX nested-make regression exercises both installed recipes and preserves
the ARM helper's old x64 behavior independently of the new x64 dispatcher route.
That POSIX-only replay explicitly skips on native Windows;
its local success cannot replace a real Firebird target, native Full/Base,
process-retirement or later Suite acceptance result.

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

Initial source classification (the loader and zstd reclassifications above supersede their x64 exclusions): [reviewed inventory](2026-11-07-native-x64-source-recipes.md).
