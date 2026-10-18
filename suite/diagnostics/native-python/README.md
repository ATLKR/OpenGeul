# CPython host control

The failed Native21 build used HostX86 ARM64-target link-time code generation and
reported C1002/32-bit heap exhaustion before an automatic HostX64 retry. MSBuild
still failed. This diagnostic reconstructs pinned complete Python sources using
the authentic LibreOffice preactions, patch order, zero-fuzz GNU patch and CRLF
restoration. GNU patch explicitly uses --binary, as the LO recipe requires for
Git-bash mixed line endings; full-tree hashes still require authentic bytes. No product patch is installed.

Both arms use authentic patched pcbuild.sln `pythoncore` Release|ARM64, original
`/maxcpucount`, `/MP`, `/O2`, `/GL`, `/LTCG`, `/Zm200`, v145/VS18 and SDK 26100.
The default baseline must emit HostX86 paths. Installed property rules are
measured for PreferredToolArchitecture values first; a measured ARM64 selection
uses that property alone. If unresolved, the candidate explicitly sets conditional
CLToolPath/LinkToolPath for ARM64 and reports this fallback mechanism separately.
The authentic x64 freeze-helper mapping remains. Actual absolute compiler/linker paths and evaluated VCToolsInstallDir/version
are bound to inventoried pre/post-build PE/hash/version identities; wrong roots
and toolsets fail admission. Property names alone never admit the result. Baseline requires direct MSBuild exit1, exactly one summary error and only a
known heap diagnostic (repeated summary allowed). Original HACL243 remains the
only exact original-site reproduction. The separately observed, source-bound
Objects/unicodetype_db.h4295 variant can permit candidate measurement, while
originalSiteReproduced, causal correction and strict workflow success stay false. Crashes, unrelated
errors and a zero-exit direct linker cannot reproduce the baseline. Candidate
feasibility can be retained after a successful baseline, but overall workflow
success requires exact baseline reproduction plus candidate native build/KAT.

The unchanged candidate python.vcxproj builds the native interpreter after the
solution core target. The solution `python` target would require all its extension
dependencies; no dependencies or modules are removed to imitate a full solution.
Full extension/Office/Base/UI coverage remains pending compiled LO externals.
The bootstrap directory named pythonx86 contains an authenticated AMD64 Python
build helper, not a product output. Original source/project/generated/object
bytes were not retained; this is source-pinned reconstruction, not exact replay.

The native controller observes the live interpreter executable, loaded DLL and
IsWow64Process2 (0/AA64) while built-in _sha2 KATs wait for release. Fixed SHA224,
SHA256, SHA384 and SHA512 vectors cover empty/abc/million-a, streaming, copy and
111/112/127/128/129-byte padding boundaries. The expected values are committed
constants, generated independently during implementation with Python hashlib;
the tested interpreter imports _sha2 directly and never uses that oracle.

Each patch retains its raw before/after targets, .orig/.rej files, source/patch
hashes and CR/LF counts even on failure. The artifact also includes partial
preparation PCbuild and zlib directories before either A/B arm exists.
Artifacts retain MSBuild binlogs, command receipts, complete object/resource
inputs, response/tlog files, generated headers and hash inventories. Source
archives are official pin-verified downloads. All diagnostic MSBuild child processes receive a selected environment allowlist,
excluding runner credentials and arbitrary variables. The parent environment is
never changed; only allowed values are read. ALLUSERSPROFILE and SystemDrive
are explicit OS fields required by the documented CommonApplicationData known-folder
contract. Before either build arm, the same Full-framework MSBuild resolves that
folder and initializes its real FileTracker in a bounded preflight; new Windows
results must establish whether this addresses the measured environment failure. The owned bounded command wrapper
clears the child ProcessStartInfo environment and adds those explicit values. The raw inherited PATH travels through private work storage
and is deleted in finally. The sanitized known tool PATH is digest-recorded;
MSBuild may also retain these known tool paths in binlogs/evaluation evidence.
This exception is explicit because tool discovery requires them. No inherited
credential-bearing PATH values enter those logs.

The global component budget is 80 minutes including downloads, with a 90-minute
job cap and nominal ten-minute upload reserve. Each build has a 22-minute cap;
remaining time is shared. Original full-solution Python duration (~5m11) is
context, not a duration promise. Failures preserve artifacts; command receipts
prove direct process identity/death and pipe drain only, not descendant census.
Runtime observer records its own candidate child cleanup separately, observes
through the retained Popen CreateProcess handle, and records creation FILETIME. Rollback is
to stop dispatching this branch-only workflow; no production settings change.

PreferredToolArchitecture requests use four indexed evidence names so ARM64 and
arm64 remain distinct on Windows. Each measurement rejects prior output before
launch and binds its receipt to the current exact argv. The earlier control2
measured default/x86/uppercase ARM64 as x86; its lowercase request reused an
uppercase path and did not establish a separate property result.

Actual executable tokens are parsed separately from Tracker wrappers; the wrapper
/c child tool is independently bound. ARM64 product flags are checked separately
from unchanged same-VS x64 _freeze_module output commands, whose authentic /Od
flags remain scoped as helper evidence. Link input closure uses only the direct
ARM64 python313.dll command and contiguous object/resource continuation lines,
with all 235 inputs bound to the product object directory. Property tables and
Tracker /r aggregate tokens cannot supply product input evidence. Raw Link span
lines, physical LF numbers and a byte-preserving span hash are retained.

Tracker children are parsed before basename classification: unknown executables
fail admission. The existing SDK resource compiler is separately scoped to the
retained SdkBinPath, SDK10.0.26100.0, and exact python_nt.rc/python_nt.res paths.
Each product CL invocation must carry its own /O2 /GL /MP /Zm200; each product
Link must carry /LTCG /MACHINE:ARM64. Windows argv tokenization accounts for
unquoted and relative object/resource operands, duplicates and response tokens.
Unsupported response inputs and operands fail closed. The diagnostic task-end
marker closes the expanded Link span so continuation operands cannot disappear.
