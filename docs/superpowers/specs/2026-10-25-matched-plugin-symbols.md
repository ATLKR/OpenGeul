# Matched native plugin symbols

The bounded classifier stopped after run 40170136188 at 0eded267: native
fixture disassembly completed, but its parser rejected an unsupported mnemonic.
Production disassembly never ran. Do not expand that parser or repeat its query.

Use the existing native ARM64 source-build workflow and its original 330-minute
build/360-minute job budgets to retain matching symbols for the owned editor's
Windows plugin. No debugger service, remote access, credentials, security setting
or paid infrastructure is added. The original Suite privacy and owner-push gates
remain prerequisites for any later editor execution.

Add an opt-in `-MutexSymbols` build switch, requiring Full phase. Configure only
`--enable-symbols=Library_vclplug_win`; reject debug/dbgutil, optimized-debug and
debug CRT configuration. Preserve normal optimization and release CRT. Verify
the effective generated symbol filter before compilation.

Retain `instdir/program/vclplug_winlo.dll` and the final linked
`workdir/LinkTarget/Library/vclplug_winlo.pdb` in a separate diagnostic artifact.
Never substitute the intermediate `.objects.pdb`. Verify native ARM64 PE,
CodeView RSDS GUID/age and matching PDB information-stream identity, plus exact
file sizes and hashes, source/configuration provenance and bounded regular-file
reads. Unknown, malformed, partial or mismatched identities fail closed. Do not
label matching identity as a complete symbol-content validation.

The diagnostic artifact is not an Office release pair and does not update the
current runtime lock. New symbols cannot name old trace offsets unless the old
binary identity matches. Otherwise reproduce only with the new matched binary
under unchanged Suite acceptance/ownership/timing gates.

For this diagnostic source build, require an exact owner push on the existing
native-engine work branch, attempt 1, matching event/source/workflow commit and
clean source. Keep the default build switch off for callers. No empty commit,
forced push, workflow retry or default-branch change is permitted.

Test malformed PE/PDB identity, mismatch, configuration rejection and default
behavior locally; independently review before the existing source build. Record
native source qualification separately from GUI evidence. Stop on an unavailable
tool or symbol format rather than installing tools or broadening access.
