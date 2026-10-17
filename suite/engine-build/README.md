# Native ARM64 Firebird source-build candidate

The official LibreOffice 26.8.1.1 Windows ARM64 MSI is a baseline. It has no
embedded Firebird driver. It cannot qualify the current Suite Base contract.
This directory starts a source port; it does not establish a working native Base
runtime or release qualification.

`source-build.json` pins the complete LibreOffice and Firebird source archives,
the original LibreOffice Windows Firebird patches, and our two patches. Keep
those source inputs and the patch receipts with the build evidence. The caller
must authenticate the complete LibreOffice archive before extracting a fresh,
owned tree. The installer also checks the exact two source files it changes.

```
python suite/engine-build/enable_firebird_arm64.py --libreoffice-source C:/build/lo
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

Run the build on actual Windows ARM64 and verify the native host before using
these options in `autogen.input`:

```
--build=aarch64-pc-cygwin
--host=aarch64-pc-cygwin
--with-distro=LibreOfficeWinArm64
--enable-firebird-sdbc
--without-system-firebird
```

Cygwin x64 tools can run the build shell. The native ARM64 compiler and its
produced executables must run on the ARM64 host. A cross build inferred from an
x64 Cygwin shell is insufficient: the exact LibreOffice configuration skips its
bundled Firebird build when `cross_compiling=yes`. Leave that cross-build guard
unchanged. After running `autogen.sh`, require `OS=WNT`, `CPUNAME=AARCH64`,
`ENABLE_FIREBIRD_SDBC=TRUE`, `BUILD_TYPE` containing `FIREBIRD`, and
`CROSS_COMPILING` unequal to `TRUE` in `config_host.mk`. Preserve `config.log`,
`config_host.mk`, compiler versions and the source-hook receipt.

Use Visual Studio 2022 ARM64 C++ tools and Windows SDK 10.0.22000 or later;
Skia/PDFium need that SDK floor. Native compiler discovery uses
`Hostarm64/arm64`. Start with `make ExternalProject_firebird` (or `make firebird`)
before spending time on the full `make build`, `make check`, and
`make instsetoo_native` stages. The authoritative Windows build prerequisites
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
