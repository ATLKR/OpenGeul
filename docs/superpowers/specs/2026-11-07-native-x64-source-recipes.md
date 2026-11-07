# Source recipe inventory for native x64 qualification

This is a read-only source-policy inventory of `ATLKR/OpenGeul` at
`2921b110a3b9059c6a7c7a0ed222d750dfd59286`, branch
`work/opengeul-office-native-engine`. The checkout was clean before and after the
reads. Every upstream source reference is pinned to LibreOffice core
`bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1`. No engine, CI, lock, checkout,
credential or network setting was changed. No tests or builds were run.

The smallest justified x64 source policy is **the existing module bootstrap
correction plus the existing common Windows WinAcc correction**. The present
ARM64 installer additionally rewrites 13 recipe/source targets behind explicit
ARM conditions. Their need or safety when enabled for x64 is **unknown**; their
names or architecture-neutral underlying symptoms do not establish common scope.
A common source correction is not a native x64 compiler/runtime or GUI proof.

## Actual caller and receipt path

1. `.github/workflows/office-native-engine.yml:33` selects `windows-11-arm`, ARM64
   Python and the existing ARM producer. `suite/scripts/build-native-engine.ps1`
   bottom-level invocation enters `Invoke-NativeEngineBuild`; its source/run
   binding authenticates the tracked driver and `source-build.json`. The source
   archive pin is LibreOffice 26.8.1.1, 302,435,508 bytes, SHA256
   `296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785`.
2. Driver lines 1312–1325 extract the authenticated pristine source and run
   `Write-NativeSourceGate`. That generated gate runs the real-source Firebird,
   Python, ATL, Meson and WinAcc checks with explicit source inputs. Its current
   selection is ARM policy; it must not become a nominal x64 qualification gate
   merely by changing the architecture field.
3. Driver line 1328 executes `enable_firebird_arm64.py` CLI. Its `main` calls
   `install` with **all hooks**; no bootstrap-only CLI exists. `install` plans and
   authenticates inputs, calls `install_module_bootstrap` at line 431, writes the
   ARM recipe changes and three source payloads, and returns `sourceHooks` with
   `architecture=arm64`, `nativeBuildVerified=false`,
   `basePersistenceVerified=false`. This is installation evidence, not a build.
   Installation is intended for a fresh owned tree and rejects repeat application;
   do not infer transactional rollback after an I/O failure.
4. Driver line 1331 separately runs `apply_winacc_focus_order.py` with the pinned
   core. The driver validates the complete three-file/source/evidence receipt in
   `Assert-WinAccFocusSourcePatchReceipt` (line 1220), retaining false native/GUI
   qualification and false current-CI-root-cause flags.
5. Only `CalcDispatchDiagnostic` enters lines 1334–1346: a different source lock,
   two modified Calc/Sfx files and three headers are installed for exact
   `windows-arm64`, always ineligible. Keep this outside normal x64 source input.
6. Driver line 1347 writes ARM configure arguments, then native configuration,
   configured toolchain/CRT, Firebird, full build, PE/import/runtime and independent
   Base gates determine qualification. `stage_installed_runtime.py` at the later
   packaging stage assembles installed output; it does not make source patches or
   supply source-build proof.
7. `suite/scripts/fetch-source-engine.ps1:145` and
   `suite/prepare.py:128` consume external locked runtime/receipt/archive identity.
   The current consumer validates ARM64 host/configuration and the exact
   source-manifest hash. The fetcher also requires the whole producer run to have
   concluded success. These consumers are not independent per-hook source replay;
   a new x64 contract must authenticate its own policy, driver and native proof.
   `suite/config/runtime.arm64.lock.json` and `runtime.lock.json` were not changed.

## Common source corrections

### Module bootstrap

`enable_firebird_arm64.py:309` (`install_module_bootstrap`) changes exactly one
`-type d -path` occurrence to `-type d ! -path` in `bin/unpack-sources`.
The pinned source comment says to ignore git-hooks, while the original positive
predicate selects only git-hooks. Module directories consequently are not linked
into the source root. The source code has **no CPU/OS branch**. Existing exact
source-tar fixture metadata binds this helper to the same authenticated archive
and core; the common transformation was recomputed in memory and matched both
locked hashes. This establishes an architecture-independent source correction;
actual Cygwin x64 linking still needs its own native execution.

Before `912e88972e7fc7f61eb0b373187d80d2f2ab6e7462378dce979254fa31792715`.
After `5fbba07a0945cff9a3ce5ae56208c9e5ad7c713701d6ae32cf08950fef0ee6d4`.
Existing regressions: `test_native_source_module_links.py` covers original missing
modules, exact repair, all three module links, git-hooks exclusion, source drift,
linked inputs and evidence collisions. These tests were read, not rerun here.

### WinAcc focus call order

`apply_winacc_focus_order.py:38` authenticates three complete pinned source files,
exact lengths and hashes, and a one-call-move unified patch. It moves the new
object's `setFocus()` after the different old object's `unsetFocus()` in
`AccObjectWinManager::UpdateAccFocus`; no architecture predicate is added or
removed. Both versions remain 33,670 bytes. The moved call preserves the existing
same-object check and lazy-seeding behavior. Existing Windows WinAcc sources and
fixture metadata establish common Windows scope, not an x64 build result or the
cause of observed UIA timeouts.

Before `ab5ed31cac9b262461b1d7e45fbe4a5758fef852a0f51c08c0c6f8e25d1c9be0`.
After `5e5f42a6b448c0d9c70a05bf762e86951565b5a96decaf050399f577dd38332b`.
Patch `968379ba427ac952c5c7df7f0c37ceabb495310acc224ee5380d51f523fb3ed7`.
The unchanged dependency source hashes are recorded in the numeric receipt.
The in-memory transformation and exact unified patch bytes matched their locks.
Existing `test_winacc_focus_order.py` covers source/patch drift, hardlinks/reparse
paths, evidence collisions, repeat/wrong-core rejection and exact-method source
regression. No synthetic results from another commit are claimed for a new build.

## ARM-only installed recipe policy

All rows below are the **currently implemented policy**, not candidates silently
promoted to x64. Before hashes are the pristine pinned LO source. After hashes
come from `source-build.json`, except `sourceHook`, whose exact appended hook was
recomputed from the authenticated pinned public source and is emitted by the
installer's receipt. A recipe can be rewritten on disk while its added make
branch remains inactive for x64; that does not justify invoking the full ARM
installer in an x64 producer.

| Manifest key / source target | Exact effective condition | Before SHA256 | After SHA256 |
| --- | --- | --- | --- |
| `configureSource` / `configure.ac` | `Within Windows case, host_cpu == aarch64; remove only enable_firebird_sdbc=no` | `412040c7a2e84ab8305613b902dc5f0485f11d745e51a77969332aa058d6f31c` | `315a82e341c15eb115d41d4041ae6c7ca1eaea26d3950c5ec2efffaeb3b507de` |
| `sourceHook` / `external/firebird/UnpackedTarball_firebird.mk` | `OS_CPUNAME == WNT_AARCH64` | `6f0563296f3e00241e1339cce5fcc92f3eba427ed27bd0f72cf1808f2800a7a5` | `c4cbb6e973ccbc4ec0a0dc8329b93f1c8746a1eee5a056e4187a1e099d4dff15` |
| `icuBuildPath` / `external/firebird/ExternalProject_firebird.mk` | `OS_CPUNAME == WNT_AARCH64` | `6ee6f3bf95f7f1c6f9cad6b7127809b095d5aabf752bca768bccfc63a6af40e9` | `c92eabab77eb0693ed93dcbd459608717c61935994bfe6c814c341237e86c742` |
| `zstdSourceLinks` / `external/zstd/UnpackedTarball_zstd.mk` | `OS_CPUNAME == WNT_AARCH64; exact ZSTD_TARBALL UnpackedTarget` | `3d7f5ddeccdbebdd72cf34e6122e0c1d33093374d27b7779d6a6f81f76d55909` | `6e2dc4deb222a3bc5385153d51778701fce4eb9f45d7e5cf4c0b3ceea75766d8` |
| `mddsEquality` / `external/mdds/UnpackedTarball_mdds.mk` | `OS_CPUNAME == WNT_AARCH64` | `f315da733c95aeeae29656318289fae9a90bff2eab46478972a9d8472a10208a` | `8b2c09e41163c700a87f18681df2d5f2543716448657f8e7850c8d63b50a936a` |
| `pythonNativeHost` / `external/python3/ExternalProject_python3.mk` | `OS_CPUNAME == WNT_AARCH64; targets additionally Platform == ARM64` | `b31e4d779484a4d153155b025daf8b03678e1984abde4fe5c6c038ccb7d43445` | `cb6c9996e5ee7be941a23bcce9884e5a4c6458b6a9ce06860d4e2e2a793c93de` |
| `atlNativePaths` / `extensions/Library_so_activex.mk` | `OS_CPUNAME == WNT_AARCH64 AND MAKE_HOST matches %-cygwin` | `7da1d1e5798d99aa895c170e0c419a4b4d3595e38d177f754ddf8fd5b1b7a89c` | `454fd02b85c851f035d41731d2e889da03293e67c4e6bcdecb15aeba74caf9d8` |
| `atlConsumerNativePaths` / `embedserv/Library_emser.mk` | `OS_CPUNAME_COM == WNT_AARCH64_MSC AND MAKE_HOST matches %-cygwin; emser merged forwarding additionally gb_LinkTarget__is_merged(emser) is nonempty` | `00a83fb08008ccd00fb95d16c9bd3c682145393ebfc53a79883f51da6d8b46ef` | `b26faf7c9a4bc1141eb59af6690d76cfb14fd5ec11f80aa9814a0518d530abe2` |
| `atlConsumerNativePaths` / `extensions/Library_oleautobridge.mk` | `OS_CPUNAME_COM == WNT_AARCH64_MSC AND MAKE_HOST matches %-cygwin; emser merged forwarding additionally gb_LinkTarget__is_merged(emser) is nonempty` | `815234d7d766cc2953f7daa5e22cdd1852dfbf55a8793dc3ae1fb9d65532dbc8` | `b369233d2eec07295ca7adeb3e91b9bde2498ed7be96cb296e95e6d27a3b26ed` |
| `atlConsumerNativePaths` / `winaccessibility/Library_uacccom.mk` | `OS_CPUNAME_COM == WNT_AARCH64_MSC AND MAKE_HOST matches %-cygwin; emser merged forwarding additionally gb_LinkTarget__is_merged(emser) is nonempty` | `d5175bb77d4df08e02c358d958bb027e753b1aca737f641e05d4cfbf577f7062` | `7ec1fed59fad36368739d5917f46bd74f6560d33460bc73ea9438592356de815` |
| `atlConsumerNativePaths` / `winaccessibility/Library_winaccessibility.mk` | `OS_CPUNAME_COM == WNT_AARCH64_MSC AND MAKE_HOST matches %-cygwin; emser merged forwarding additionally gb_LinkTarget__is_merged(emser) is nonempty` | `0d488882bdd0bc4732ebd587c04d5a1199dc787740339a367b50a68b992961e4` | `c99e623c082accaa84efebf254876ee083effc071a1bd8de63ee10bcf6f45e6d` |
| `atlConsumerNativePaths` / `winaccessibility/WinResTarget_uacccom.mk` | `OS_CPUNAME_COM == WNT_AARCH64_MSC AND MAKE_HOST matches %-cygwin; emser merged forwarding additionally gb_LinkTarget__is_merged(emser) is nonempty` | `9e0b37d170ea2a47072abf4b2e107189cb0f81b14a7ab0ba2454b383c80d6c00` | `58637ccbabc74afb3a84f27526a26b47ffdce1bfa2c814e5d369b84f2b2aca5c` |
| `harfbuzzNativeMesonPaths` / `external/harfbuzz/ExternalProject_harfbuzz.mk` | `OS_CPUNAME_COM_OS_FOR_BUILD == WNT_AARCH64_MSC_WNT AND MAKE_HOST matches %-cygwin AND BUILD_PLATFORM == HOST_PLATFORM AND stripped WSL+PYTHON_FOR_BUILD+SYSTEM_PYTHON empty AND BUILD_TYPE contains MESON` | `2e85211865e09766b1bc8b0664aa152a2e98277a0af572150902786b3ceefc50` | `f959b6f564baf45777f531b588932b2e969bdfbf21ffdb41630874838415cfcb` |

The two narrow public upstream reads were `configure.ac` and
`external/firebird/UnpackedTarball_firebird.mk` at the pinned core; both returned
HTTP 200 and matched the existing manifest. Configure line 1092 is explicitly
`if test "$host_cpu" = "aarch64"`; only its nested Firebird-disable assignment is
removed. The source installer authenticates the configure patch but performs the
exact replacement itself. The Firebird recipe keeps all 25 existing upstream
Windows patches and appends the local patch only under `WNT_AARCH64`.

Additional payload and nested-patch boundaries:

- **Firebird ARM patch**: `firebird-windows-arm64.patch`, SHA256
  `dccca2b44bbb12ce06b75c227fa9a8fb530e5d6607904484d9f75732ae4cd58e`.
  The outer make condition is ARM-only. Its seven files add `_M_ARM64`/`ARM64`
  CPU identity, reuse the existing `_controlfp` path for ARM64, add the fixed
  MSVC platform branch, add `WIN_NT && ARM64` remote identity 44, advance the
  protocol enum sentinel, and select the librarian only for
  `$(PLATFORM)_$(CpuType) == win32_aarch64`. The name `commonArchiveRecipe`
  means Firebird's common-object library, **not cross-architecture common policy**.
  Exact locked before/after header/remote/archive states are in the JSON receipt.
  The manifest does not independently pin before/after whole-file hashes for
  `builds/make.new/config/config.h.in`, `src/common/common.h` or `FpeControl.h`;
  their full per-file state is therefore not independently re-proved by this
  inventory. Patch/source validation and actual builds remain required.
- **MDDS**: outer `WNT_AARCH64` only; the local patch moves the equality body into
  its class and removes the old out-of-line body after the existing GCC12 patch.
  The patch has no inner architecture guard, making the outer recipe condition
  essential. Hash `8bddef54230e818dadee067de53f0ab4971bf5c47764fdd2a05951144c92e8e3`.
  Two header before/after hashes and the unchanged node header stage remain
  manifest-bound. This inventory does not establish a need on x64.
- **Python**: the late import is `WNT_AARCH64` only and its targets file further
  requires MSBuild `Platform == ARM64`. It changes `CLToolPath`/`LinkToolPath` to
  `Hostarm64/arm64`; the authentic x64 freeze-helper mapping is explicitly left
  alone. Payload hash `3f993bc582b10890ffdd4ec9bf1ab0d50de064c0889f57687d1f6b4b63fd1e22`.
- **ATL**: ActiveX plus the five enumerated production consumers use local
  variables with original defaults outside ARM conditions. The emser merged
  forwarding is inside that same ARM/Cygwin branch and additionally requires
  actual merged membership. Do not extend native-path quoting or merged link
  forwarding to x64 without a new source/command-boundary case.
- **HarfBuzz**: the long condition in the table is conjunctive. The original
  pkg-config expression remains the default; no global compiler or make state
  is changed. It is not a general Meson or native-x64 override.
- **ICU loader path**: README/source evidence describes an underlying Windows
  helper-expression bug independent of CPU, but this implemented fix is
  deliberately ARM-conditioned. Original x64 expression remains selected.
  Whether x64 needs a separately justified correction is **unknown** here.
- **Zstd**: `CYGWIN=winsymlinks:sys` is exported only for that exact ARM unpack
  target. It is not permission to relax native module/DLL link policy globally.

## Driver child-process boundaries that must stay explicit

`Write-Make`-equivalent target scripts at driver line 1386 export
`TAR_OPTIONS=--force-local` only to owned make children, replacing inherited tar
options. The pinned helper invokes GNU tar with native `C:/...` archive paths;
colon syntax is a Cygwin/path issue rather than an ARM instruction-set issue.
This is a reasonable shared Windows/Cygwin bootstrap primitive, but still needs
the future x64 host's actual source/archive/link execution. It is not a source
file patch. `Invoke-CygwinScript -NativeLinks` (820) similarly selects
`CYGWIN=winsymlinks:nativestrict` before the owned Bash starts; strict native
module/DLL links must stay strict and pass the x64 host's access probe.

Conversely, `Get-NativeLibrarianPlan` (1006) selects and verifies
`COMPATH/bin/Hostarm64/arm64/lib.exe`, and the target script exports its literal
path as `OPENGEUL_FIREBIRD_LIB`. Both belong to ARM-only policy. The x64 producer
must not run that ARM tool preflight or substitute a PATH librarian. Configure
`LibreOfficeWinArm64/aarch64/VS2026`, native host `AA64`, generated `AARCH64`,
VS145 ARM64 CRT, PE and independent native Base process checks are also ARM
qualification gates, not reusable x64 assertions with renamed receipt fields.
The script-scoped deadline owner is unchanged by this inventory.

## Minimum source-policy implementation implications

Preserve the existing ARM call sequence exactly: the full ARM installer already
includes bootstrap, followed by the separate WinAcc installer. **Do not call
bootstrap first and then the existing full installer**, which would double apply
and fail its pristine-source hash. For x64, expose or import only the authenticated
bootstrap operation, then run the existing common WinAcc operation with the same
pinned source/evidence guards. Do not relabel the full installer's ARM receipt.
There is no evidence here to enable the other hooks for x64.

The narrow affected source-policy files are
`enable_firebird_arm64.py` (only if a stable common-only CLI is chosen),
`build-native-engine.ps1` (explicit target dispatch, no duplicate bootstrap),
and the architecture policy/manifest binding selected by the parent design.
`apply_winacc_focus_order.py` and the existing hashes need no content change
merely to execute on x64. Architecture-specific workflow/ref, native compiler,
PE/CRT/Base proof and consumer admission are separate necessary implementation
boundaries covered by the two design packages; this inventory does not waive
those gates or alter current locks.

The smallest new regression must prove x64 source dispatch selects exactly
bootstrap+WinAcc, never calls full ARM/diagnostic install or ARM librarian,
preserves the existing ARM sequence/receipt, rejects wrong core/source/policy,
and does not mutate non-selected recipes. Existing bootstrap and WinAcc drift,
repeat/evidence and exact-source tests remain applicable. ARM recipe tests must
retain their actual conditions and x64-negative selections. Actual native x64
compilation and product GUI acceptance are still pending and cannot be inferred
from these read-only checks.

## Evidence scope

`source-recipe-inventory.json` contains 14 matching existing source-fixture
hashes, 5 matching local payload/patch hashes, 2 common in-memory before/after
recomputations, the 13 ARM source targets and all 25 inherited upstream Windows
patch pins. Only the two necessary pinned upstream files were fetched. No
existing CI was queried, no retained remote artifact was downloaded, and no new
qualification receipt was produced. This private inventory is not a native build
receipt. Unknowns are x64 toolchain/build/runtime behavior, x64 need for any
currently ARM-only fix, and whole-file nested Firebird states not independently
pinned in the current manifest. There is no denied or pending operation in this
read-only slice.
