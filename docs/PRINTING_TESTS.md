# Virtual-printer E2E

The user requested printer simulation on free hosted runners. These tests call
OpenGeul's real **File > Print** UI. They select an isolated queue using the inbox
**Microsoft Print To PDF** Windows driver on `PORTPROMPT:` and require a real,
retained Windows spooler job AND an independently readable PDF. They never replace
printing with `Page.printToPDF`, browser `page.pdf()`, or the app's PDF export.

Seven scenarios on each of windows-2022 and windows-2025: HWPX, HWP, three-page
pagination without blank trailing pages, landscape, unsaved edits without saving,
cancellation without jobs, and compressed table terminal glyphs versus a
zero-spacing control. PDFium renders at 144 dpi; checks include paper size, exact
marker occurrence, nonblank pixels inside glyph boxes, and terminal glyph ink
comparison. This is not OCR and does not need a paid printer emulator.

A uniquely named, nonshared printer queue is created only on disposable
GitHub-hosted Windows runners. The prior default printer is restored and only the
owned queue/jobs are removed. No external driver, shared physical printer, copied
font file, user document or signing key is used. Missing inbox printer/runtime,
failed setup, skipped tests and incomplete scenarios fail the gate, not a pass.
Evidence (synthetic PDFs, page PNGs, JSON, JUnit, bounded UI traces) lasts one day.

`.github/workflows/printing.yml` is a reusable workflow. The full MSIX workflow
passes its own run ID/SHA and requires its printer gate before release. The
branch-only printer harness probe uses the separately verified PR4 candidate
from run 37404480348 (tested merge 21ec23749f74f932a9870cefcfa85cae1f3584db).
That older-binary probe is never a substitute for a release's same-run checks.

Not established: actual paper transport, ink/toner/color accuracy, vendor PCL/PS
firmware, duplex hardware, physical margins, unavailable-printer/network faults,
all fonts, all Korean IME scenarios or every real document. Physical printer
acceptance remains separate. Tests deliberately do not auto-install third-party
driver software or turn off security protections.

Primary references:
- https://learn.microsoft.com/en-us/microsoft-edge/webview2/how-to/print
- https://learn.microsoft.com/en-us/windows/win32/printdocs/printer-info-2
- https://learn.microsoft.com/en-us/windows/win32/printdocs/job-info-2
- https://pypdfium2.readthedocs.io/en/stable/python_api.html

Verification checkpoint: 14 new oracle regressions observed failing before
implementation; all 88 local Python tests pass after adding the gate. This local
result is not a claim that either real Windows printer run has passed. Consult
actual PR checks for the current head. Keep the PR draft until they succeed.
