# Verification ledger

## 2026-10-05

- Legacy bootstrap: 19 Python tests passed, but never compiled on Windows.
- Actual Windows baseline run 37290548163: dependency install succeeded; upstream contracts had 29 passes, 2 failures, 1 intentional Windows skip. Failures were CRLF mutation of vendored JS provenance and Windows path separators in a source-boundary test.
- Corrected baseline run 37291330701: SUCCESS, including upstream contracts, frontend tests and TypeScript/Vite editor build. Fixes preserve LF before checkout and normalize only the test path comparison; no failing assertion is disabled.
- New release/PE/MSIX/owner policy tests were observed failing before implementation. Current local Python suite: 19 passed.
- Actual downstream Windows build/package/release results are recorded in Actions and provenance.json. A queued or pending run is not a built MSIX.

Not established by build alone: clean-machine GUI startup, IME, visual fidelity/round-trip, complete font rights, optional Skia direct PDF embedding review, hostile-document security, WACK/Store certification, trusted signing, accessibility or autosave/recovery. Existing upstream limitations remain.
