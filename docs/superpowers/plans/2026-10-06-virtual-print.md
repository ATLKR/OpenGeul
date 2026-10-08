# Virtual printer E2E implementation

Goal: test the real OpenGeul Print path on free standard Windows runners, not app PDF export.

1. Inventory the built-in driver and inspect real modal UI on Windows 2022 and 2025.
2. Build negative controls for missing/invisible/clipped content, blank/extra pages, wrong media and reference drift before implementing the corresponding oracle.
3. Generate synthetic documents; own only a uniquely named Microsoft Print To PDF queue on PORTPROMPT:. Never change or use a default/hardware printer.
4. Drive actual print dialogs, record spooler jobs and source immutability; configure the real per-job A4 media instead of inconsistent default DEVMODE fields.
5. Gate release on two same-run virtual-printer jobs, preserving the existing 62 UI executions and MSIX install checks. Verify fresh-candidate CI before merge.

Ruling: the actual virtual driver outlines text; text extraction alone cannot validate it. Visually review the fixed synthetic A4 output and commit its exact visible-ink fingerprints. Candidate CI never captures/approves its own baseline. No raster tolerance or automatic flaky retry is used. The unit suite independently proves detection of missing/clipped/extra ink and wrong page dimensions.

Current checkpoint: reference pages reviewed; 23 PDF/raster unit tests and 75 policy tests pass locally. Native Windows 2025 preview activation is being verified separately. These results do not substitute for final-candidate printing or full CI.
