# HOP upstream follow-up triage

## First downstream changes

- golbin/hop#101, FMsongX2 commit f9bbe8dc66172a1959af1e388e6c28a5b597c5a6: backport the unmodified-character shortcut filter. Relates to Windows issue #95 and macOS issue #100. Keep Ctrl/Cmd+P, F6/F7 and object-property menu/button access. Remove stale plain-P shortcut labels. Local real-source keyboard regression: 6 failures before, 10 passing after; real keyboard UI save/reopen proof is required separately.
- golbin/hop#97: add a persistent View > toolbar-label visibility preference. Default stays visible, storage-denied sessions remain usable, hidden button labels retain accessible names. Seven local preference unit tests passed after the expected RED phase. UI persistence and document-nonmutation checks are part of the new browser probe, not yet a claim of native verification.

No upstream PR is merged and no upstream issue is closed by these downstream changes. Preserve MIT notices and contributor attribution.

## Next candidates requiring distinct reproduction

- #99 / #78: table-cell clipping and PDF layout. Need minimal synthetic table/shape fixtures and independent render evidence; text-only round trips do not establish a fix.
- #73: saved-document corruption. Existing round-trip tests improve coverage but do not prove the reporter's document is fixed.
- #96: rich clipboard formatting needs Windows native clipboard cases.
- #98: password-protected documents need explicit decryption/save policy, not silent plaintext output.
- #80: ARM64 needs a separately built and tested target; x64 emulation is not a native ARM64 claim.
- PR #86: Hanja conversion needs dictionary-data provenance and license review before inclusion.
- PR #87: web demo/UI redesign and HTML named .doc exports are not wholesale Windows backports.
- PR #69: do not re-enable unsafe automatic lineseg repair against the current pinned baseline policy.
- PR #71 (AI/cloud) and #49 (Android): outside the current Windows HWP/HWPX scope.
- PR #74 / #84: macOS native clipboard/AppKit fixes are not Windows fixes.

Some unmerged proposals are closed or superseded. Check actual diff, maintainer comments and current source before applying; do not assume all unmerged work should be imported.
