# One bounded static call-family discriminator

Run 40166893778 at 7c051f94 completed native fixture preparation in 4.563
seconds, proved the exported fixture's slot 4, and authenticated the production
plugin's unique RTTI/vtable candidate range [100192,100292). Production naming
remains inconclusive: the contiguous ADRP/LDR/BLR predicate found no unique
condition-wait call. The receipt cannot distinguish zero matches, multiple
matches, nonadjacent loading or a direct call. Do not guess or run Office again.

## Concrete question

Classify calls in exactly that authenticated 100-byte candidate with the existing
native MSVC disassembler. Retain only bounded call kinds, relative call/target
offsets, known import matches and explicit unsupported-flow outcomes. This is
one static discriminator, not a production decoder or input-policy correction.
It must not promote the existing inconclusive attribution to exact by itself.

Use DUMPBIN `/NOPDB /DISASM:NOBYTES /RANGE:vaMin,vaMax`; addresses passed to the
tool are preferred image base plus the proven range, with the final instruction
start as vaMax. Independently validate a complete, aligned, unique instruction
row for every four bytes of the range. Validate the same parser against the
native fixture before inspecting production. Fixture `doAcquire` must contain
a direct call to a known exported, non-inlined synthetic helper.

The tool and target run only as native ARM64. Do not load or execute either DLL,
search PDBs, install tools, use remote symbols, expand credentials or retry the
denied direct artifact download. Materialize only the already authenticated DLL
bytes into a newly owned temporary folder on the runner, pin them before and
after the tool, and remove the temporary DLL and raw output during cleanup.

## Bounds

Discovery, archive validation, extraction, fixture disassembly, production
disassembly and classification share the original 30-second analysis allowance,
with 27 seconds for work and three reserved for existing owned-process cleanup.
No new budget at fallback entry. Reuse the owned Job primitive, require natural
root/job exit and handle closure, and fail closed when cleanup is unconfirmed.
Tool stdout/stderr are private temporary files, each capped at 256 KiB when read.
Require at most 25 production instructions and eight call records. Do not follow
out-of-range callees or expand the range. A direct branch target is not proof of
an import thunk destination.

No raw instruction bytes, full disassembly, absolute addresses, command paths,
environment text or DLLs enter the public receipt. Retain hashes, bounded
classifications, relative offsets, completeness and lifecycle status only.
Unknown syntax, row gaps, clobbered/ambiguous register flow, zero/multiple calls
and unsupported call forms remain explicit, never inferred into a proof.

## Verification and stopping rule

Test malformed/oversized output, out-of-range or missing rows, register clobbers,
multiple calls, fixture target mismatch, shared-deadline exhaustion and owned
cleanup. Independently review and validate locally before one static CI run.
The result selects a concrete, testable instruction-path correction or records
the missing exact evidence. No automatic second disassembly query, expanded
range, offsets-only GUI run or dispatch change follows from an unknown result.

Official tool contracts: [RANGE](https://learn.microsoft.com/en-us/cpp/build/reference/range),
[DISASM](https://learn.microsoft.com/en-us/cpp/build/reference/disasm),
[NOPDB](https://learn.microsoft.com/en-us/cpp/build/reference/nopdb).
