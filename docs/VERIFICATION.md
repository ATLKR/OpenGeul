# Verification ledger

## 2026-10-05 — baseline and implementation

- Legacy bootstrap: 19 Python tests passed, but never compiled on Windows.
- Actual Windows baseline run 37290548163: dependency install succeeded; upstream contracts had 29 passes, 2 failures, 1 intentional Windows skip. Failures were CRLF mutation of vendored JS provenance and Windows path separators in a source-boundary test.
- Corrected baseline run 37291330701: SUCCESS, including upstream contracts, frontend tests and TypeScript/Vite editor build. Fixes preserve LF before checkout and normalize only the test path comparison; no failing assertion is disabled.
- New release/PE/MSIX/owner policy tests were observed failing before implementation. Local Python suite at that checkpoint: 19 passed.

## 2026-10-05 — verified Windows build and published prerelease

Application source commit: `0349523066585437bdd06de8291a1d66a8d3b95f`.

- [Windows build and release run 37293488174](https://github.com/ATLKR/OpenGeul/actions/runs/37293488174) completed with `success`.
- The workflow runs `scripts/build-msix.ps1` on `windows-2025`, uploads the build outputs, rechecks `SHA256SUMS.txt` and the MSIX in the release job, and publishes an explicitly unsigned development prerelease. This is an actual successful run, not a queued or predicted build.
- [Published prerelease v1.0.0-dev.2.1](https://github.com/ATLKR/OpenGeul/releases/tag/v1.0.0-dev.2.1) is public, not a draft, and marked as a prerelease.
- Published assets include `OpenGeul_1.0.0.0_x64_development-unsigned.msix`, `OpenGeul_1.0.0_windows-x64_unsigned-portable.zip`, `AppxManifest.xml`, `SHA256SUMS.txt`, `provenance.json`, and `rhwp-help.txt`.
- The release contains the HOP Windows editor and rhwp CLI built from the pinned source versions documented in `provenance.json`. It does not include LibreOffice or promise DOCX/XLSX/PPTX support.
- This documentation update does not rebuild or change that released application binary. Build claims above refer to the explicit application commit and run, not automatically to later commits.

## Supported scope versus unverified behavior

The release retains the pinned upstream HOP Windows editor and rhwp CLI rather than reimplementing their engines. HWP/HWPX opening, HWP saving, PDF export, printing, drag/drop, multi-window behavior and file-association configuration are included in the source integration. Inclusion is not proof of correctness for every document or Windows configuration.

HOP's current UI does not provide HWPX saving or autosave/recovery. OpenGeul has not added or certified those features. Consult the shipped `rhwp-help.txt` for the separate CLI capabilities and limits.

The installed-font-only policy and official download help are product safeguards, not a determination that every font already present on a user's computer is licensed for every intended use. Font embedding rights and the native Skia direct-PDF path need their own review; no blanket legal or compatibility guarantee is made.

## Still requires manual verification before a stable release

- Clean-machine GUI startup and WebView2 Runtime handling without Hancom or Microsoft Office installed.
- Korean IME, accessibility, multi-window file activation and Windows file associations.
- Representative HWP editing/saving and reopening in the original application; HWPX opening; visual fidelity, printing and PDF output.
- Missing-font behavior: official download, user installation, font rescan and predictable substitution without silent downloads or extraction from other applications.
- PDF embedding policy across all available export/rendering paths, including native Skia.
- Hostile-document handling, recovery expectations, WACK and Microsoft Store certification.
- Trusted signing and production installation/update behavior.

Unsigned MSIX files are development/review artifacts, not trusted production installers. Normal installation requires the appropriate signing/trust setup or a Store-signed release. The portable ZIP can be extracted as a whole and tested using `OpenGeul.exe` with an installed WebView2 Runtime; the CLI is `Tools/rhwp.exe`. Organizational security policy can still block unsigned executables. Do not disable security protections to bypass that policy.
