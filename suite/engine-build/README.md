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
It leaves atomics, assembly, database formats and protocol numbers unchanged.
The only inline x86 assembly found in the pinned source is legacy Win9x code,
guarded by `WIN9X_SUPPORT`; no speculative assembly replacement is included.

The same ARM64-only patch selects Firebird's existing `_controlfp` path for
the three Windows floating-point save/mask/restore guards, as newer upstream
Firebird does for ARM64. Microsoft restricts `__control87_2` to x86; its UCRT
header declares that function only under `_M_IX86`. The x64 and i386 branches,
control masks, calls and ordering remain unchanged. The source test compiles
the real header after all 25 authenticated LibreOffice Windows patches against
declaration-only Microsoft API visibility fixtures. It proves source selection
and syntax; actual Windows compiler, floating-point runtime behavior and Base
persistence still require the native build and qualification gates.

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
