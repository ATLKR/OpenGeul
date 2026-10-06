# OpenGeul 1.1.1 — unsigned Windows development build

This is a development prerelease, not a Microsoft Store-certified or trusted-signed installer. Own code is MIT, with upstream and third-party notices preserved.

## Included

- HWP/HWPX opening, editing, saving and Save As between both formats, with staged/atomic writes, external-modification detection and round-trip regression checks.
- Windows HOP editor plus `Tools/rhwp.exe` CLI with native Skia options, built from the pinned upstream revisions in `provenance.json`.
- A narrow terminal-negative-spacing fix for inline-table last-line clipping; normal inter-line compression and positive spacing are preserved. This is not a claim that every table or the original HOP #99/#78 documents is fixed.
- Normal `p/P` input with print shortcuts retained, and persistent toolbar-label visibility.
- Installed-font-only policy, official font help, independent branding, and upstream self-updates disabled.

## Release verification

Publication requires the same-run source-built WASM/browser gates, Windows compile and unit tests, 62 editor UI executions, 16 real virtual-printer scenarios, and MSIX test-sign/install/file-association/uninstall checks. A failed or skipped required gate cannot publish. The eight printer scenarios per Windows image use the application's real Print UI, the Windows system dialog, an isolated Microsoft Print To PDF queue, completed spooler jobs and independently rendered output. Browser preview and driver are both configured to A4 portrait with no additional preview margins and actual size.

Printer output is checked against exact reviewed whole-page fingerprints, including one documented WebView2 153 digit-4 outline variant. No generic pixel tolerance or automatic baseline update is used. Consult `docs/RELEASE_READINESS.md` for investigation evidence and the linked Actions run for this release's final result; diagnostic probes using older binaries are not fresh-candidate proof.

## Use and limits

- MSIX is unsigned and requires appropriate trust/signing or Store distribution for normal trusted installation.
- Extract the entire portable ZIP and run `OpenGeul.exe`. Microsoft Edge WebView2 Runtime must be installed. Respect Windows/company security policy; do not disable protection.
- Font files and private keys are not distributed. Installed fonts retain their licenses; missing fonts can change layout. Keep original documents and verify important output.
- Autosave/recovery and LibreOffice/DOCX/XLSX/PPTX integration are not included. CLI commands and limitations are in `rhwp-help.txt`.
- Automated virtual printing does not certify physical feed/duplex, vendor drivers/firmware, color calibration, arbitrary documents, font licensing, Korean OS IME in all environments or Store/WACK approval.
- `SHA256SUMS.txt` and `provenance.json` identify the exact published files, source and build. MSIX package version is 1.1.1.0, newer than the previous 1.1.0.0 development package.
