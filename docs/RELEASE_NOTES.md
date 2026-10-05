Unsigned Windows development build. Not a Microsoft Store-certified or trusted-signed installer.

Built from pinned HOP 0.4.4 and rhwp 0.8.4 sources with OpenGeul branding, installed-font-only policy, official font download help, and upstream self-updates disabled. Includes the HOP Windows editor and rhwp CLI with native Skia options. HWP/HWPX opening, HWP saving, PDF export, printing, drag/drop, multi-window and file associations are retained. HOP's UI does not yet support HWPX saving or autosave/recovery. CLI capabilities and limits are listed in rhwp-help.txt.

- MSIX: unsigned package for development/review/future signing. Normal trusted installation requires appropriate signing or Store distribution.
- Portable ZIP: extract the entire directory and run OpenGeul.exe. Requires installed Microsoft Edge WebView2 Runtime. CLI is Tools/rhwp.exe. Windows/company security policy may block unsigned programs; do not disable protection.
- No font files or private keys are included. Use official font publishers; missing fonts can alter layout.
- SHA256SUMS.txt and provenance.json record integrity and exact source revisions.
- CI verifies tests/build/package structure; it does not establish visual fidelity, clean-machine installation, full font/license compliance or Store approval. Back up important originals and test round-trips.
- Own code is MIT; upstream and dependency notices remain applicable. No LibreOffice integration is included yet.
