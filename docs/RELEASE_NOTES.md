Unsigned Windows development build. Not a Microsoft Store-certified or trusted-signed installer.

Built from the pinned HOP and rhwp sources recorded in provenance.json, with OpenGeul branding, installed-font-only policy, official font download help, and upstream self-updates disabled. Includes the Windows editor and the separate rhwp CLI with native Skia options. Exact feature scope and verification evidence are revision-specific; consult the source commit's README, docs/E2E.md and docs/VERIFICATION.md rather than assuming that a package build proves full document compatibility. Autosave/recovery and LibreOffice integration are not provided. CLI capabilities and limits are listed in rhwp-help.txt.

- MSIX: unsigned package for development/review/future signing. Normal trusted installation requires appropriate signing or Store distribution.
- Portable ZIP: extract the entire directory and run OpenGeul.exe. Requires installed Microsoft Edge WebView2 Runtime. CLI is Tools/rhwp.exe. Windows/company security policy may block unsigned programs; do not disable protection.
- No font files or private keys are included. Use official font publishers; missing fonts can alter layout. Installed fonts retain their own license conditions.
- SHA256SUMS.txt and provenance.json record integrity and exact source revisions. CI artifacts and GitHub release assets are distinct; only published release assets appear here.
- Automated verification does not establish perfect visual fidelity, real OS IME behavior, real-printer output, full font/license compliance or Microsoft Store approval. Back up important originals and verify representative documents independently.
- Own code is MIT; upstream and dependency notices remain applicable. Future LibreOffice imports must retain their applicable original licenses.
