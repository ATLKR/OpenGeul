# Local native symbol resolution of captured plugin frames

The matched-symbol source build is the prerequisite, not caller proof. Existing
traces redacted the plugin frames to zero, so they cannot be recovered by adding
symbols. Do not expand the stopped disassembly classifier.

Prepare a standalone native ARM64, file-only DbgHelp query adapter. It may load
the explicit verified local PDB as symbol data, never execute/load the target
DLL or invade/enumerate a process. Require existing system DbgHelp availability;
do not install or register tools. Verify exact DLL/PDB hashes and RSDS GUID/age
against the retained identity receipt before any native symbol operation.

Use a unique symbol session, explicit local pair-only search directory and
options excluding environment symbol paths, automatic symbol-server discovery,
unqualified image search, deferred loading and prompts. Reject remote/UNC/srv
syntax and nonempty ambient symbol paths. Do not claim SYMOPT_SECURE alone
disables network access. Load the exact existing PDB path, then require the
reported PDB path, GUID/age and SymPdb type to match before querying. Unknown
or unexpected lookup fails closed; never fall back to a symbol server.

At most 32 ARM64 return RVAs are eligible, corresponding to the existing two
16-frame stacks. Preserve the return RVA; query return RVA minus four. A result
must be a containing nonzero-size PDB function in the expected module and image
bounds. Nearest export, zero-sized, ambiguous, unrecognized or out-of-range
results remain unresolved. Output only a finite source-function tag and relative
offsets, identity and completeness/cleanup metadata; no raw symbols, addresses,
paths, stack bytes or PDB contents.

Keep all calls serialized in an owned child under a caller-supplied original
30-second total/27-second work plus three-second cleanup budget. Require unload,
session cleanup and retained child exit. Native APIs are not preemptible; the
parent watchdog owns the hard stop. No query resumes or renews an expired budget.

This adapter alone does not authorize an editor run. Before one later owned Calc
reproduction, review a bounded addition of only vclplug_winlo to the existing
module whitelist and bind the observed loaded plugin to the matched artifact.
Retain the original ownership, preparation, privacy, case count, frame cap,
capture deadline and partial/overflow/expiry semantics. Keep symbol work outside
the hook. The new binary requires new runtime evidence; old hashes are not
interchangeable with a newly built symbol-enabled binary.

A decisive diagnosis requires the actual failing mouse-up retrieval and named
caller chain with a matching plugin identity and pinned source call site.
Function names alone do not justify a global COM dispatch change. A nonfailure,
incomplete trace or unresolved mapping stops the experiment without automatic
rerun or wider instrumentation.
