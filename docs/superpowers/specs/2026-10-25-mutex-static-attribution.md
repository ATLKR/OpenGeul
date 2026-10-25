# Static prerequisite for an owned-editor caller discriminator

Run 40164740782 at 16f651a6 passed both native diagnostic fixtures: during-wait
posted mouse-up was deferred by CoWait flags 8 and delivered by flags 24. Neither
architecture reproduced the original physical mouse-up flags-3 removal without
release. Do not change production dispatch policy or repeat posted variants.

The original stack has unknown frames immediately above `osl_waitCondition`.
The authenticated engine inventory contains `vclplug_winlo.dll`, omitted from
the fixed observer list. Adding its name alone would produce unnamed offsets:
no matching PDB/map was retained. Before another GUI run, test whether the exact
private `WinSalYieldMutex::doAcquire` entry has a defensible binary naming anchor.

## One static question

Can the locked ARM64 plugin's RTTI, primary vtable and unwind metadata identify
the mutex-acquire function unambiguously, with its condition-wait import call?
Use only the existing admitted owner-push static workflow and unchanged engine
fetch. Do not load the plugin, execute Office, change hooks, upload binaries or
retry the separately denied direct engine download.

First compile a tiny mirrored single-base hierarchy with the existing native
MSVC ARM64 compiler. Retain the pinned base's virtual declaration order:
destructor, tryToAcquire, IsCurrentThread, doRelease, doAcquire. Reverse the two
override declarations as in the real derived class. Verify the candidate slot
against the fixture's exact exported doAcquire entry. A fixture mismatch stops
production attribution. Never execute this fixture DLL.

Then validate exact type descriptor `.?AVWinSalYieldMutex@@`, signature-1
CompleteObjectLocator with self-reference, zero primary offsets, and the exact
single nonvirtual SolarMutex base hierarchy. Require a unique preferred-base
vtable reference and executable slot entry. Require a nonfragment ARM64 unwind
range starting at that entry and an unambiguous supported call sequence to the
`sal3.dll` import `osl_waitCondition` inside the range. Unsupported thunks,
ambiguous candidates, absent metadata or unsupported instruction sequences are
inconclusive, not nearest-symbol guesses.
The hard-coded class layout is valid only for the inspected pinned core revision.
A missing or different `sourceCoreCommit` cannot produce exact attribution.
The decoded import-call location is static evidence; a later observed caller
must match its return address, not merely fall somewhere in the function range.

## Bounds and evidence

Reuse held archive authentication, exact member selection and byte caps. Share
one 30-second analysis deadline. Fixture discovery/compilation uses the existing
owned-process preparation primitive with its unchanged 30-second bound and
cleanup reserve; it does not consume or replace any Office preparation gate.
Limit candidates, section ranges, imports, unwind entries and output size.
Upload only a bounded receipt with source/hash identities, RVAs, validation
statuses and cleanup result. No paths, absolute PCs, DLLs or full disassembly.

Test malformed and duplicate RTTI chains, wrong base/slot, range overlap,
unsupported calls, wrong architecture, archive corruption and deadline expiry.
Independently review and run local validation before one static native run.

Successful naming enables one later owned-editor caller comparison; it does
not establish the mutex holder, trigger or safe repair. Inconclusive metadata
ends this attribution route until a matching symbol source or another exact
anchor is available. Do not launch an offsets-only GUI run.

ABI references: LLVM's [Microsoft RTTI implementation](https://github.com/llvm/llvm-project/blob/main/clang/lib/CodeGen/MicrosoftCXXABI.cpp)
and [Microsoft vtable builder](https://github.com/llvm/llvm-project/blob/main/clang/lib/AST/VTableBuilder.cpp).
Pinned source: core bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1,
`include/comphelper/solarmutex.hxx` and `vcl/win/app/salinst.cxx`.
