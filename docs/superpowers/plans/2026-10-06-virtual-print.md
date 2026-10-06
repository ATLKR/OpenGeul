# Virtual printer E2E plan

Goal: exercise the production Print command through Windows printing, independently of PDF export, using free standard runners.

Architecture: a same-build executable and WASM-derived synthetic fixtures; a disposable, run-scoped Microsoft Print To PDF queue; native accessible print UI and real spool job; independent PDF text and raster inspection. No production API mocks, physical/network printer, font payload or signing change.

- [x] Confirm inbox driver on Windows 2022 and 2025.
- [x] Reproduce missing accessibility in the embedded print preview; opt into the documented complete accessibility flag only in test sessions, with unchanged default arguments and cleanup.
- [x] Add negative controls for malformed/missing/blank/invisible/clipped PDF output and unsafe queues; observe failure before implementation and local green after.
- [x] Generate basic, three-page and table HWP/HWPX fixtures using the production WASM; assert page counts after serialization/reopen.
- [ ] Verify all eight actual print cases on both runner images against the known successful main payload.
- [ ] Integrate the printer jobs into the same-run release dependency graph, without weakening the existing 62 UI cases.
- [ ] Inspect real output images, review diff, and keep PR draft until full candidate CI is green.

Boundaries: simulated committed text is not an OS IME test; a virtual spool job and its PDF do not establish physical hardware, vendor drivers, ink, color accuracy, duplex or paper feeding. Synthetic table coverage does not close HOP #78/#99 on reporters' documents. Do not treat probe reuse as fresh candidate build evidence.
