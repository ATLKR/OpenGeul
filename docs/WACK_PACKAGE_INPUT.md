# WACK package-input qualification

Installed MSIX smoke checks the signed candidate's package identity, visible GUI,
CLI and registered HWP/HWPX file types. After removing that test installation,
the ordinary Windows SDK App Certification Kit analyses the same signed bytes
using its documented `appcert test -appxpackagepath` command. The test certificate
remains trusted until certification and cleanup finish. The signed copy is hashed
after signature verification, immediately before WACK and after WACK; the unsigned
release artifact is also checked for modification.

Microsoft documents both command modes in [Windows App Certification Kit](https://learn.microsoft.com/en-us/windows/uwp/debug-test-perf/windows-app-certification-kit).
This changes the SDK's input mode; it does not change the candidate's manifest,
WindowsApps permissions, SDK binaries, test selection or report classifier.
Installed behavior continues to be checked separately. WACK runs in the ordinary
runner process context, rather than a package-identity debugging token.

## Controlled comparison

Diagnostic run [38141248234](https://github.com/ATLKR/OpenGeul/actions/runs/38141248234)
used the previously tested diagnostic copy of source candidate
`e9cf4310cfc67438db4b4e7a12d6fabd6de1bc19` without another manifest revision.
The signed input MSIX SHA-256 was
`568092a6fe1bf6561565d0f25424a1babac809b988cebfa72ee903d67b7c595c`.
The executable SHA-256 remained
`e282955c8e460cb66270949e51e492162bce7cebb75ae62562043c05885f8490`.

Both complete Centennial reports contained the same 24 tests: 13 required and
11 optional. Full-name mode produced 12 required passes and a mandatory DPI
warning. Package-input mode produced all 13 required passes, including DPI.
Both retained the same optional blocked-executables failure with 14 messages.
The package-input report matched the expected development identity and
`1.1.2.0`, reported `PARTIAL_RUN=FALSE`, and exited with code zero. Its SHA-256 was
`a04d58fbf1a60b27087dc4450142ebcc367e4120841fe7b7530930096faa5d71`.

Full-name mode analysed the registered WindowsApps executable. Package-input
mode analysed the SDK's temporary extraction. Earlier same-byte controls showed
native `CreateActCtxW` returning access denied only on the installed WindowsApps
path, while the payload and an equally long owned-copy path succeeded. The exact
SDK internal access check has not been established. The separate package-identity
debugging control failed environment verification and supplies no comparison.

The unchanged report classifier returns `submissionCheckPassed=true` and
`passed=false` for this report. Required warnings, failures, partial reports and
identity/version mismatches still block qualification. Optional findings remain
visible; this result is neither a complete WACK PASS nor Microsoft Store approval.

This diagnostic report does not qualify the updated HOP/rhwp source. Each final
candidate must run its own complete Windows build, installed smoke, ordinary
package-input WACK, editor and virtual-printer gates before release.
