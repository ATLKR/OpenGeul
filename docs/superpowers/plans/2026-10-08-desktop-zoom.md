# Desktop zoom preservation implementation plan

**Goal:** Address only the desktop document-open zoom-reset portion of HOP #94.
**Architecture:** Apply the reviewed host-only capture/load/restore sequence from HOP commit 2b1189b3079045481134864d9ccb02ca535ea6bb to the pinned host during both existing build paths. Do not upgrade the engine or change document writes.
**Spec:** https://github.com/golbin/hop/issues/94 and docs/HOP_REQUEST_COVERAGE.md.
**Base:** OpenGeul 56ca88331a2fdba47bcc6e7ec27ad433df89fe72.

## Constraints
Keep HOP/rhwp pins, every existing 78 UI gate, print references, permissions, runners and published release unchanged. New work is a draft PR, not a merge or deployment. Toolbar wrapping/overflow, password documents, other operating systems and full issue closure are separate work.

## Tasks
- [x] Reproduce desktop zoom reset in the real extracted host initialization function; keep browser/mobile auto-fit and error paths as controls.
- [x] Add fail-closed unique-anchor transform and tests before implementing it; run it through the actual existing patch entrypoint.
- [x] Apply the minimal host change and record source hashes and upstream attribution in build provenance.
- [ ] Run focused tests, inspect the diff, create a new draft PR and read actual current CI.

## Verification boundary
Local workspace is a deliberately partial scaffold: the original patcher was matched to its Git blob; the contiguous initializeDocument function was read from pinned HOP source. The Node test in CI reads the full freshly prepared production host source. Local OS/canvas boundary doubles do not prove native viewport behavior or replace full CI. No fresh-context reviewer is available; review is in-session.
