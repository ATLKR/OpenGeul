# Native ARM64 Firebird source-build candidate

The official LibreOffice 26.8.1.1 Windows ARM64 MSI is a baseline. It has no
embedded Firebird driver. It cannot qualify the current Suite Base contract.
This directory starts a source port; it does not establish a working native Base
runtime or release qualification.

`source-build.json` pins the complete LibreOffice and Firebird source archives,
the original LibreOffice Windows Firebird patches, and our two patches. Keep
those source inputs and the patch receipts with the build evidence. The caller
must authenticate the complete LibreOffice archive before extracting a fresh,
owned tree. The installer also authenticates each source file it changes.

```
python suite/engine-build/enable_firebird_arm64.py --libreoffice-source C:/build/lo --evidence-directory C:/build/evidence
```

The installer removes only the Windows ARM64 assignment that forcibly disables
Firebird in `configure.ac`. Autoconf parses command-line options before executing
that assignment: `--enable-firebird-sdbc` alone therefore does not enable it.
The installer adds an ARM64-only Firebird patch after the existing upstream
patches. The patch recognizes `_M_ARM64` and selects the existing `CpuArm64 = 15`
implementation identity instead of incorrectly falling through to Intel/I386.
It leaves atomics, assembly and database formats unchanged.
The only inline x86 assembly found in the pinned source is legacy Win9x code,
guarded by `WIN9X_SUPPORT`; no speculative assembly replacement is included.

The installer also corrects the Firebird build's temporary loader path for
Windows ARM64. The pinned Windows helper produces a complete `PATH=...`
assignment per call; concatenating two calls joins the ICU directory to the
next literal `PATH=`. This upstream expression is independent of the CPU.
Our conditional correction targets `WNT_AARCH64` and leaves the original
expression for x64 and other platforms unchanged. It passes ICU's `source/lib`
and Firebird's `bin` directory to one existing helper call, preserving its base
paths, inherited `PATH`, directory order and quoting through both make levels.
The pinned Windows `prefix.mingw` sets `LIB=$(BIN)` and builds the client DLL
there. The examples recipe launches its local `isql` copy outside that directory;
its own `PATH` inserts a mixed `C:/.../bin` pathname. The helper supplies the
converted Cygwin directory explicitly instead of the unused Firebird `lib` path.
The manifest authenticates the original and effective external build recipe,
and the source-hook receipt retains both complete files as evidence.

Native source run `39034993907` reached database bootstrap and reported
`Could not find acceptable ICU library`. The compiled ICU 78.3 and release DLL
names are within Firebird's supported search. The source replay establishes
the malformed path; the original run did not retain ICU DLL bytes or a Windows
loader error code. The correction does not establish successful native ICU
loading, resolve every possible dependency failure or qualify Base. Missing
`firebird.msg` formatting accompanies the database failures; the build creates
that message file after its message database, so copying a message file does
not repair the demonstrated loader path.

Native source run `39039743949` progressed to the examples `empbuild.fdb`
recipe, where `gen/examples/isql.exe` reported a loader error; make recorded
status 127.
The retained log does not identify the missing DLL or preserve executable import
bytes. The source replay proves the directory mismatch and Bash path expansion;
it does not prove this correction resolves that Windows loader failure.

The standalone `isql` proof runs outside that make child. It validates the
compiled internal ICU 78.3 release triplet as owned native ARM64 DLLs and
retains each file's size and SHA256. Only the create/reopen child processes
receive the compiled ICU directory and owned Firebird `plugins` directory before
the inherited Windows `PATH`, plus
their explicit `FIREBIRD` root. The controller environment stays unchanged.
Command receipts retain hashes of those effective values and the proof records
the selected prefix/root, without dumping the inherited host environment.
Even ASCII database creation prepares Unicode system metadata and loads ICU;
this provisioning is required independently of the integer SQL fixture. The
source and portable command checks do not establish an actual Windows ICU
load or native Base qualification.

The locked LibreOffice `firebird-Engine12.patch` returns a bare plugin name in
normal mode. Make's `FIREBIRD_BOOT_BUILD` path instead uses the full plugin
directory; that successful bootstrap does not provision a later standalone
process. Run `39043828006` completed both Firebird make targets, then its native
standalone `isql` reported an XNET network error. The source trace shows that
missing optional embedded plugins can be skipped before this fallback. The
standalone proof now validates the owned `plugins/Engine12.dll` as a native ARM64
DLL, records its path/size/SHA256 in `isql-plugins.json`, and provides that directory
after ICU only to both proof children. It does not set boot mode, change provider
order or configuration, copy plugins, or relax SQL/Base checks. Actual native
plugin loading and database persistence remain subject to the next build.

The same ARM64-only patch selects Firebird's existing `_controlfp` path for
the three Windows floating-point save/mask/restore guards, as newer upstream
Firebird does for ARM64. Microsoft restricts `__control87_2` to x86; its UCRT
header declares that function only under `_M_IX86`. The x64 and i386 branches,
control masks, calls and ordering remain unchanged. The source test compiles
the real header after all 25 authenticated LibreOffice Windows patches against
declaration-only Microsoft API visibility fixtures. It proves source selection
and syntax; actual Windows compiler, floating-point runtime behavior and Base
persistence still require the native build and qualification gates.

Native source run `39026193296` reached Firebird's generated ODS test and
stopped at the fixed `src/include/gen/autoconfig_msvc.h` platform guard.
`ods.awk` includes that header directly for MSVC, independently of the generated
configure header. The ARM64 port adds a pure `_M_ARM64` branch defining the
existing ARM64 CPU identity, eight-byte pointer and `size_t` definitions, and
eight-byte Firebird alignment. The existing Windows `long` definition remains
four bytes and double alignment remains eight. The x64 and x86 branches are
unchanged; the unsupported-platform guard remains. The manifest separately pins
the archived header, its state after all 25 upstream patches, and the ported
header: the upstream warning patch changes this file before our branch is added.
Mandatory source checks compile the real fixed header and CPU branch for all
three target macro sets. They establish source selection and definitions;
actual Windows ABI, ODS comparison and complete native Base qualification remain
required.

The remote client code also requires a Windows ARM64 protocol architecture
identity. The port backports Firebird's existing `arch_winnt_arm64 = 44` and
the `WIN_NT && ARM64` selection from upstream commit
`c02ba31824f5cee34cc8966fc44b38e6b395152a`. The manifest pins both upstream
source URLs and SHA256 values and the before/after bytes of the two local
headers. Existing architecture IDs retain their values; only the terminal
`arch_max` sentinel advances to 45. The generic/canonical protocol negotiation
stays unchanged. ARM64 must have a distinct identity because equality with the
local architecture enables raw symmetric record transfer; aliasing it to the
generic, 32-bit ARM or x64 identity would change that decision. The source check
reproduces the missing declaration using the real fixed MSVC header, Windows
common branch, remote header and protocol enum, then compiles ARM64, x64 and
x86 selections. It proves source selection and preserves negotiation bytes;
actual native transport interoperability and Base persistence remain required.

Native source run `39029745766` passed the fixed-header ODS check, then the
linker ignored `temp/Release/common.lib` with LNK4003 before reporting 69
unresolved symbols in `gpre_boot.exe`. The frozen common archive recipe used
GNU `ar crus`; the actual failed archive bytes were not retained. The ARM64
candidate changes only that recipe for the generated `PLATFORM=win32` and
`CpuType=aarch64` selection to use the selected MSVC native librarian with
`/NOLOGO /OUT:<archive>`. Other CPU/platform selections retain the original
GNU recipe. The driver derives `bin/Hostarm64/arm64/lib.exe` from configure's
selected compiler root, rejects linked paths or a foreign PE, retains its
identity, and exports its quoted literal path only to owned make children.
There is no `PATH` fallback. Editline remains disabled by the existing external
recipe, and the native build uses LibreOffice's separately built LibTomMath;
their unused Firebird archive recipes are unchanged. Portable checks execute
the exact common archive rule, including a tool/output path containing spaces,
missing-tool rejection, native-tool failure propagation and unchanged x64/x86
selection. These command-boundary checks do not establish a valid native
archive or engine; the separate native archive/link diagnostic and full build
remain required.

Run the build on actual Windows ARM64 and verify the native host before using
these options in `autogen.input`:

```
--build=aarch64-pc-cygwin
--host=aarch64-pc-cygwin
--with-distro=LibreOfficeWinArm64
--with-visual-studio=2026
--with-package-format=archive
--disable-online-update
--disable-online-update-mar
--disable-breakpad
--enable-firebird-sdbc
--without-system-firebird
```

Cygwin x64 tools can run the build shell. The native ARM64 compiler and its
produced executables must run on the ARM64 host. A cross build inferred from an
x64 Cygwin shell is insufficient: the exact LibreOffice configuration skips its
bundled Firebird build when `cross_compiling=yes`. Leave that cross-build guard
unchanged. After running `autogen.sh`, require `OS=WNT`, `CPUNAME=AARCH64`,
`ENABLE_FIREBIRD_SDBC=TRUE`, `PKGFORMAT=archive`, `BUILD_TYPE` containing `FIREBIRD`,
and an empty `CROSS_COMPILING` in `config_host.mk`. Preserve `config.log`,
`config_host.mk`, compiler versions and the source-hook receipt.

The automated driver selects Visual Studio 2026 ARM64 C++ tools (MSVC18/v145)
and Windows SDK 10.0.22000 or later;
Skia/PDFium need that SDK floor. Native compiler discovery uses
`Hostarm64/arm64`. The driver runs `make ExternalProject_firebird`, `make firebird`,
then `make build` for the Full phase. It audits `instdir`, stages authenticated
native app-local CRT files, proves Base persistence, and ZIPs that installation
tree. It does not run `make instsetoo_native` or publish an upstream MSI.

The explicit archive option overrides the distro's MSI packaging default while
retaining its Java, ODK, help, extensions and Korean-language configuration.
It avoids MSI-only Font::TTF and translated-installer WiLangId requirements;
the normal Windows compiler/SDK checks still apply. Required native CRT files
come from the driver's separate authenticated app-local CRT stage rather than
MSI merge modules. `make check` and the complete Suite qualification remain
separate checks; `make build` alone does not establish either.

The fork does not publish through TDF's updater or crash-reporting services.
The explicit online-update, MAR-update and Breakpad disable options override
those optional upstream service choices without inventing a privacy-policy
URL. The generated configuration must contain empty `ENABLE_ONLINE_UPDATE`,
`ENABLE_ONLINE_UPDATE_MAR` and `ENABLE_BREAKPAD` values, and `BUILD_TYPE` must
exclude `ONLINEUPDATE` and `BREAKPAD`. Java, ODK, help, Korean, database and
Firebird settings remain required as before. Suite local `NativeDiagnostics`,
owned-process identity, clean shutdown, zero-exit and crash-archive checks
remain required. An absent private `profile/crash` directory can be archived
completely without a dump; owned-process shutdown records supply shutdown
evidence. A build without Breakpad does not claim dump capture.

The authoritative Windows build prerequisites
and supported setup are documented at
<https://wiki.documentfoundation.org/Development/BuildingOnWindows>.

The external build places the native runtime in
`workdir/UnpackedTarball/firebird/gen/Release/firebird/` (or `Debug`):
`bin/ifbclient.dll`, `plugins/Engine12.dll`, and `intl/fbintl.dll`.
Its `bin/isql.exe`, when built, can provide a first create/insert/select/commit/
reopen check. Installed Office paths are `program/ifbclient.dll`,
`program/Engine12.dll`, and `program/intl/fbintl.dll`. The SDBC driver may be merged
into `mergedlo.dll`; requiring a standalone driver DLL is incorrect.

Before qualification, verify native ARM64 PE/process identity, then run the
existing Suite Base engine test with actual rows persisted after close and
independent reopen. Add Unicode paths/data, transaction rollback, BLOBs, and
x64/ARM64 ODB round-trips. The complete native Suite GUI, Korean IME, startup,
lifecycle and HWP gates still apply. A successful external build or SQL probe
alone does not qualify Base or the complete Suite.

Focused source checks use local inputs explicitly and never download them:

```
OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE=1 \
OPENGEUL_FIREBIRD_SOURCE_ARCHIVE=/path/Firebird-3.0.13.33818-0.tar.bz2 \
OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES=/path/lo/external/firebird \
python -m unittest suite.tests.test_firebird_arm64_port -v
```

The patch folder must contain the pinned `UnpackedTarball_firebird.mk`, its
25 Windows patches. The tests read an unmodified `configure.ac` from the LO
source root, or from `OPENGEUL_LIBREOFFICE_CONFIGURE_AC`. A local research fixture
can instead place `configure.ac` beside the patches. GNU patch, a C compiler/preprocessor, GNU Autoconf, and `sh` are
required for all source checks. Without explicit local inputs, ordinary Suite
unit runs skip these source checks with a reason. The native engine build must
run them with authenticated inputs and tools available, setting
`OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE=1` so missing inputs/tools fail the gate.


The ARM64 app-local VC runtime stage uses the exact eight-file native ABI
family. It excludes `vcruntime140_1.dll`, whose installed compatibility image
has an x64 default PE header and ARM64X hybrid metadata; its presence in an
ARM64 redist folder does not make it an exact AA64 image. The eight admitted
files may themselves contain ARM64X metadata and must retain their AA64 default
header, valid Microsoft signature, version-resource identity and selected
compiler version floor. The actual native ARM64 C++ exception/vector diagnostic
proved this eight-file ABI on the selected VS2026 toolchain; that diagnostic
does not qualify the Office engine or Firebird.

After the complete runtime PE audit, the source-built native Python runs
`suite/crt.py` against every native image in `instdir`, reading both normal and
delay import tables without loading the images. Any VC dependency outside the
exact ARM64 family, including a dependency on the omitted compatibility DLL,
fails the build. The engine receipt records this closure, and extraction and
payload verification recompute it from the authenticated runtime bytes. The
reader supports PE32/PE32+ file-backed import metadata with explicit bounds and
rejects legacy VA-based delay descriptors. Exact CRT copying and all native
Office, Java, ODK, help, Korean resources and Base gates remain required. The
public x64 family and default remain the original nine files.

Each owned make-target shell script exports the fixed
`TAR_OPTIONS=--force-local`. The authenticated source Makefile's
`get-submodules` target invokes `bin/unpack-sources`, which calls bare GNU tar
with configure's native `C:/...` archive paths. GNU tar otherwise interprets
that colon as remote-host syntax, as observed in native source run
`39021455577`. The option is confined to the build child environment and
replaces inherited tar options so exclusions cannot silently drop Korean
resources. Actual target scripts are retained with the build evidence.
Source URLs, sizes and SHA checks, the three help/dictionary/translation inputs,
and their language configuration remain required. This path correction does
not establish Firebird product compilation or Office qualification.

The pinned `bin/unpack-sources` helper also uses a positive `-path git-hooks`
predicate while its comment says to ignore that directory. Consequently it
extracts all three archives but links only `git-hooks`, leaving the root
`dictionaries/Module_dictionaries.mk` absent, as observed in native run
`39024071446`. The guarded source installer corrects only that predicate to
`! -path`, with pinned pristine and effective SHA checks. The native driver
passes its owned evidence directory to retain both exact helper versions and
records the source-hook receipt. The existing relative module-link behavior,
source archive authentication, Korean/help/dictionary inputs and build targets
remain required. Use a fresh owned source tree: the helper skips extraction
and linking once an archive's destination exists. Portable GNU-tool tests
prove all three root links and module lookups; actual Cygwin links and the
native build remain Windows qualifications.

Native module-link diagnostic `39027528344` then observed a separate Windows
access boundary: all three direct unpacked marker files were readable by
native ARM64 Python and PowerShell, while their root links were unreadable in
the inherited Cygwin mode. With the child-only
`CYGWIN=winsymlinks:nativestrict` wrapper, both readers matched all three root
and direct files. The producer uses that tested Cygwin `env.exe` wrapper before
starting Bash for each make target. The controller environment and other
Cygwin stages keep their inherited settings. Native link creation fails rather
than falling back; no registry or Developer Mode changes are made. Command
receipts retain the actual launcher and mode arguments alongside the unchanged
`TAR_OPTIONS=--force-local` make scripts. This controlled resource-read proof
does not qualify the full Office or Firebird build.

The same strict mode cannot create a source-archive symlink before its target
exists. Native run `39052527005` reached the full `build` target after Firebird
and both standalone SQL processes passed, then GNU tar failed on zstd's
`tests/cli-tests/bin/unzstd` link to `zstd`. The authenticated zstd 1.5.7 archive
contains 743 members: 637 regular files, 104 directories and two CLI-test links.
The link target is a regular shell wrapper stored immediately after `unzstd`;
the native zstd library's headers and compiled inputs are regular files. The
pinned upstream zstd recipe already documents this extraction-order problem
for MSYS.

The guarded installer appends a Windows ARM64 target-specific
`CYGWIN=winsymlinks:sys` export to that exact zstd archive's `UnpackedTarget`.
This preserves both source-test links as Cygwin links, including the temporarily
dangling link, without changing other archive targets or the outer strict
module/DLL link policy. GNU tar errors still fail the target before its success
stamp; no source members are excluded or removed. The source manifest binds
the original and effective recipe hashes and the original zstd archive hash.
Both recipe versions are retained in build evidence, with additive
`sourceHooks.zstdSourceLinks` provenance. Use a fresh source tree. Portable GNU
make tests verify target, sibling and architecture scope; actual Cygwin
extraction and native alias access require the separate Windows control before
another full build. This correction does not qualify that build or its runtime.

The MDDS 3.2.1 equality correction addresses the C2382 declaration/definition
failure observed in Native20. The bounded native ARM64 control `39068742893`
reproduced that error with MSVC 19.51.36260 and passed compilation and unchanged
normal/throwing equality and inequality checks after relocating only the exact
`operator==` body into its class. Its `const noexcept(nothrow_eq_comparable_v)`
contract is unchanged. This control proves the tested headers and probe; the
original gnumeric translation units and their PCH were unavailable, and full
engine and Base qualification still require the native build.

The installer authenticates the original MDDS recipe, existing GCC12 patch and
new two-header patch before writing source. It appends the correction after the
GCC12 patch only for `WNT_AARCH64`. The `.patch.1` suffix deliberately selects
strip level 1 despite the upstream recipe's default level 0. Other platform
patch selection stays unchanged. The additive `mddsEquality` manifest pins the
complete archive, recipe, patch, original/candidate headers and unchanged
GCC12-patched `node.hpp`; `sourceHooks.mddsEquality` records recipe and patch
hashes and retains both recipe versions.

The native driver authenticates the complete MDDS archive before mandatory
source tests and exports `OPENGEUL_MDDS_SOURCE_ARCHIVE`. Local source runners
must pass that archive together with the existing Firebird inputs; the optional
`OPENGEUL_LIBREOFFICE_MDDS_PATCHES` points to an authenticated `external/mdds`
directory when it is not beside the Firebird patch folder. No tests download
inputs. The source case uses GNU make for platform selection and real GNU patch
to reproduce the exact candidate header hashes. On native builds, three small
actual unpacked MDDS headers are retained as `actual-mdds-*` with source paths,
actual and expected identities in `source-build-receipt.json.mddsHeaders`, even
on a later build failure. Linked paths and output collisions are rejected;
retention errors preserve the original build failure. Full admission requires
all three actual headers to match the locked post-patch identities.

The ATL correction addresses Native22's missing `atlbase.h` and the bounded
control's unresolved Cygwin `atls.lib` path. It changes only the authenticated
ActiveX recipe under `WNT_AARCH64` and an actual GNU make `MAKE_HOST` ending in
`-cygwin`. `cygpath -lm` supplies quoted native Windows include and library
arguments. The explicit full `atls.lib` path goes through this recipe's linker
flags because common gbuild sorts `T_LIBS` as words; all system libraries and
other profiles retain their original behavior. Failed or empty conversions stop
make. Original/effective recipes and hashes are retained under
`sourceHooks.atlNativePaths`; existing source pins and qualification gates stay
unchanged.

Native24 exposed the same include-path boundary in `embedserv/Library_emser.mk`.
The additive `atlConsumerNativePaths` lock covers that recipe, the OLE automation
bridge, both Windows accessibility libraries, and the UAccCOM resource recipe.
Each complete pristine recipe and its effective bytes are pinned separately.
Their private conversions apply only to `WNT_AARCH64_MSC` with genuine Cygwin
GNU make; the existing ActiveX hook remains byte-identical. The three existing
static ATL library consumers route their full `atls.lib` operand through their
existing linker flags. UAccCOM keeps its original absence of `LIBPATH`; the
include-only service and resource recipes ignore `ATL_LIB` entirely. Resource
tests preserve both RC and dependency-generation arguments. The service/resource
scope follows their explicit ATL include arguments; neither is claimed as an
observed missing-header failure in Native24.

All five inputs, output pins, and new evidence destinations are checked before
source installation begins. Each original/effective recipe is retained with its
hashes under `sourceHooks.atlConsumerNativePaths.recipes`. Validation failures
leave source and evidence unchanged. Installation still uses an owned fresh
source tree and does not promise rollback after arbitrary filesystem I/O errors.

The native driver exports `OPENGEUL_LIBREOFFICE_ATL_SOURCE` as the pristine
extracted LibreOffice root and sets both `OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE=1`
and `OPENGEUL_ATL_REQUIRE_CYGWIN_REPLAY=1`. The shared source flag requires
authentic recipe, architecture profile, configure source and relevant gbuild
inputs; Linux source integration retains its explicitly labelled argv adapter
replay. The separate Cygwin flag also requires authentic ATL source, even when
the shared flag is unset, and additionally requires actual Cygwin GNU make, Bash
and cygpath for native path conversion and linker argument replay. Missing
source/tools or an unsupported profile fails that mode without a skip. Native
Windows unit discovery skips POSIX replay only when neither strict flag requires
it. No tests download source or execute a product binary. Control 39098589144 supports bounded
native compile/link path feasibility; it did not prove all consumed static
library architectures or qualify the full engine, Base, IME or E2E behavior.
