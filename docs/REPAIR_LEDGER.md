# PR #1 repair ledger

## 2026-10-05

User authorized continued repairs, verified merge, then selected HOP issue/PR follow-ups.

Observed failures: run 37313586487 built the GUI and CLI but linking the subsequent fixture example failed with missing skparagraph.lib. The editor and standalone CLI reused the same target directory despite separate lockfiles and native-skia feature graphs. Separate their target directories and create fixtures using the already-tested debug graph before release/CLI builds.

Run 37318297039 Chromium passed 7/8 scenarios; valid namespace-aliased missing-font input became invalid XML after save. Reproduced locally with the exact production WASM and independent ElementTree parsing. The parser stores raw paraHead fragments while the writer emits only canonical namespace declarations. Preserve inherited namespace bindings on detached fragment roots, without renaming text/QName values or weakening fixture validation. Also preserve aliased memo properties and head-tail XML.

The native parser and WASM parser both require this source fix. Linux now builds source-bound WASM first; Windows verifies hashes and source identifiers before consuming it. Browser jobs test production sources and that same rebuilt WASM in parallel with Windows compilation; native jobs test the actual packaged executable. All existing release gates remain mandatory.

Local evidence: namespace export failed before the fix; new WASM integrity tests observed failing then passing (5 tests). Python/Node syntax checks passed. Rust compilation and full pipeline must be checked in Actions before claiming the repair is complete or merging. No relaxed assertion, fake result, trusted signing key, font program or real customer document was added.
