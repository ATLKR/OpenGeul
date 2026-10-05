# OpenGeul Windows distribution implementation plan

## User-approved scope (2026-10-05)

Implement ATLKR/OpenGeul as a public, independently branded distribution of rhwp and HOP for Windows. Preserve the upstream Windows document editing, viewing, saving, printing, PDF export and command-line capabilities rather than replacing them with a stub or a web link. DOCX/XLSX/PPTX and LibreOffice integration are future work, not advertised features.

Use installed fonts, provide an explicit official-source font installation guide, preserve third-party notices, and never publish third-party font files or private credentials. Disable upstream application self-updates in the MSIX channel. Unsigned MSIX and portable development builds must be labeled honestly; they are not Store-signed consumer installers.

## License boundary

OpenGeul-authored code: MIT. Upstream rhwp/HOP and third-party components retain their own notices and licenses. Future LibreOffice imports must retain applicable MPL-2.0 and other component licenses; the MIT root license does not relicense imported code. Prefer an isolated engine/adapter boundary.

## Implementation tasks

1. Inspect the existing bootstrap and the exact upstream sources; record immutable source revisions and baseline tests.
2. Add regression tests for preparation, feature preservation, font policy, identity/version generation, package contents and release authorization. Run them before implementing fixes.
3. Prepare a reproducible complete upstream Windows build with OpenGeul overlays, not a reduced replacement editor; include the rhwp CLI where supported.
4. Build and test on standard GitHub Windows runners, generate unsigned MSIX and portable artifacts, preserve source/license/provenance information and SHA-256 checksums.
5. Run CI for pushes and pull requests. Publish clearly labeled prereleases only after required checks and an authorized main/tag trigger, never from an untrusted pull request.
6. Verify the actual GitHub Actions result and inspect the generated package/release. Distinguish automated build evidence from manual Windows UX, HWP round-trip, font fidelity and Store certification checks.

## Completion evidence

Record remote commit, workflow run, test results, package names/checksums, release URL, and remaining manual verification in docs/VERIFICATION.md. Do not describe a queued workflow or source-only scaffold as a completed MSIX build.
