# PR #1 repair ledger

## 2026-10-05

User authorized continued repairs, verified merge, then selected HOP issue/PR follow-ups.

Observed failures: run 37313586487 built the GUI and CLI but linking the subsequent fixture example failed with missing skparagraph.lib. The editor and standalone CLI reused a target directory despite separate lockfiles and native-skia feature graphs. Separate their target directories and create fixtures using the already-tested debug graph before release/CLI builds.

Run 37318297039 Chromium passed 7/8 scenarios; valid namespace-aliased input became invalid XML after save. Reproduced locally with the exact production WASM and independent ElementTree parsing. The parser stores raw paraHead fragments while the writer emits only canonical namespace declarations. Preserve inherited namespace bindings on detached fragment roots, without renaming text/QName values or weakening fixture validation. Also preserve aliased memo properties and head-tail XML. A new URI-escaping unit test caught a double-escape error; it was fixed rather than suppressed.

The native parser and WASM parser both use the same source fix. Linux builds source-bound WASM first; Windows verifies hashes and source identifiers before consuming it. Browser jobs run against production sources and that same rebuilt WASM, while native jobs test the packaged executable. All required release gates remain mandatory.

### Browser verification and input ordering

- Run 37332857367 at 82d524a: namespace regression plus Chromium 8/8 and WebKit 8/8 passed; Firefox still failed. Waiting for editing readiness was appropriate but did not fix Firefox text loss.
- Diagnostic run 37334337631 captured trusted DOM events: Firefox emits compositionstart, compositionupdate, beforeinput, compositionend, then input. Upstream cleared textarea.value in compositionend before processing any text. Real ASCII key events worked, disproving a general focus/readiness failure.
- Added a narrow final-composition reconciliation before upstream records undo/clears the input. It uses the original onInput path, is not a browser or test-mode bypass, does not double-insert already-applied composition text, and rejects inactive/cancelled states. Eight unit tests observed RED then GREEN.
- Probe run 37335188746 at d299415: all three production-frontend builds and their unchanged 8-case E2E suites passed. This is browser evidence only, not a substitute for final Windows package/native/install gates.

Local Python policy/integrity suite: 38 passed; Node format+composition suite: 22 passed. Seven Rust namespace helper tests passed in the WASM build. No assertion was removed or relaxed. Native Windows and installation outcomes must be recorded from the exact final PR run before merging.
