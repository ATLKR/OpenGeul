# Virtual printer verification

## Actual path

The unchanged production Windows app opens its normal Print UI. The test selects its own uniquely named Microsoft Print To PDF queue in the real system dialog, selects A4 portrait in the driver's Preferences/Advanced controls, supplies an output path, verifies the retained spooler job, and independently renders the resulting PDF with PDFium. App PDF export, CDP PrintToPDF, mocked callbacks and canned spool files are not substitutes.

Eight scenarios per Windows image: HWP; HWPX; tables with negative, zero and positive line spacing; two-page output; page-2-only selection; cancellation with no output and a still-editable document. Inputs are synthetic, with no customer corpus or font files. Existing 62 editor UI executions and MSIX installation gates remain required independently.

## Media and visible-ink checks

A4 is selected explicitly and PDF page dimensions must match. Simply setting queue PaperSize=9 proved insufficient because other DEVMODE fields still described Letter. No default printer or global driver preferences are modified.

The observed Microsoft PDF driver output outlines glyphs, so its text extraction is empty. The live printer test therefore uses fixed, visually reviewed visible-ink fingerprints rather than claiming printed PDFs are searchable. Each full page is rasterized at 216 DPI with PDFium, thresholded at 160, and compared exactly with the committed dimensions, ink count, bounding box and SHA-256 mask. A changed pixel fails; CI never regenerates or approves its own reference. Actual page PNGs and mismatch metrics are retained for diagnosis. Searchable-PDF checks remain separate unit controls.

The initial reference records eight reviewed A4 pages from run 37415109909, Windows 2022 artifact 11389924227, built from PR4 product commit 0aedc704fe75b996bfa86f666f23e4297071de83. All five table rows, final descenders, Korean/Latin basic text, page markers and page-range output were visually checked. It is a narrow visual regression baseline, not a Hancom-certified layout oracle. Intentional compressed inter-line spacing remains compressed. Driver, PDFium or installed-font changes can legitimately require an explicit baseline review; do not silently loosen or regenerate expectations to make CI green.

## Safety and evidence

Only disposable GitHub-hosted Windows runners are accepted. The test creates a random OpenGeul-CI queue using Microsoft's existing local driver and PORTPROMPT:, validates its exact name/driver/port, and removes only its own jobs and queue. No physical/network printer is selected. No external driver, paid larger runner, additional signing key, font binary or user document is needed.

Evidence includes synthetic printer PDFs, page PNGs, requested and actual media, spooler job metadata, source/binary hashes, dialog screenshots, JSON and JUnit. Retention is one day. No spool files or font files are uploaded.

## Build provenance and limits

Early print-probe jobs reuse the exact PR4 binary from run 37404480348 to investigate the harness. These are not fresh final-candidate build evidence. The integrated virtual-print jobs consume artifacts from their own workflow run, verify the package payload, and block release on failure. PRs cannot publish.

Passing these tests does not certify physical paper feed, hardware duplex, ink/toner, color calibration, vendor PCL/PostScript or firmware, arbitrary documents or the original HOP reporters' documents. Store/WACK and trusted signing are still separate.
