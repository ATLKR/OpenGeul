# HOP request coverage — 2026-10-08

## Snapshot and meaning of coverage

**Not all HOP user requests are implemented or verified in OpenGeul.** This inventory separates upstream issue status, downstream source inclusion, narrow tests, and an actually published package. A closed upstream issue is not evidence that the pinned downstream build includes its fix. Passing the existing 78 UI executions is not an exhaustive compatibility certification.

Sources read through the connected GitHub API:

- [Published OpenGeul 1.1.1 development release](https://github.com/ATLKR/OpenGeul/releases/tag/v1.1.1-dev.29.1), source `56ca88331a2fdba47bcc6e7ec27ad433df89fe72`.
- [OpenGeul upstream pins](https://github.com/ATLKR/OpenGeul/blob/56ca88331a2fdba47bcc6e7ec27ad433df89fe72/config/upstream.lock.json): HOP 0.4.4 at `d426f0395e97bc1972f66d894d1a7c76a36374bc`; rhwp 0.8.4 at `496333b27d21ddb9114ba9ae340bcb895870c9a7`, plus explicit downstream overlays.
- [Newer HOP source comparison](https://github.com/golbin/hop/compare/d426f0395e97bc1972f66d894d1a7c76a36374bc...80888af2b8c8a18aea16f824d2d92309a290b1ad): five additional commits at this snapshot. It includes the rhwp 0.8.7 integration and subsequent password/desktop-control work. They are not automatically included in OpenGeul.
- [HOP open issues](https://github.com/golbin/hop/issues?q=is%3Aissue%20is%3Aopen): 17 returned, search `incomplete_results=false`. [Open PR collection](https://api.github.com/repos/golbin/hop/pulls?state=open&per_page=100): empty. Closed PRs may have been merged, superseded or declined; none of those meanings are assumed from closure alone.

The inventory below covers every open issue in that snapshot and selected closed requests relevant to downstream gaps. It is not a claim to have reproduced all historical reports or read every comment/attachment. Multi-part issues are not counted as wholly solved when only one part is supported.

## Already included, with bounded evidence

| Request | OpenGeul status and limit |
| --- | --- |
| [#95](https://github.com/golbin/hop/issues/95), [#100](https://github.com/golbin/hop/issues/100): ordinary p/P input | The [#101](https://github.com/golbin/hop/pull/101) shortcut backport is in the released downstream patcher, with keyboard and saved-document regressions. The Windows build does not certify the reporter's macOS package. |
| [#97](https://github.com/golbin/hop/issues/97): optional toolbar labels | A downstream persistent label preference is in the released product. This is not the entire responsive-toolbar/overflow request in #94. |
| HWPX editing/saving | Implemented by OpenGeul PR1 before this release, with later round-trip gates. This does not prove Hancom can open every saved HWP/HWPX or resolve #73's original file. |
| [#99](https://github.com/golbin/hop/issues/99), [#78](https://github.com/golbin/hop/issues/78): missing table content | A narrow terminal-negative-spacing clamp and same-run real Windows virtual-print tests are included. These are partial evidence only: the original reported documents and arbitrary printer hardware remain unverified. |
| [#90](https://github.com/golbin/hop/issues/90): theme support | The pinned host already calls `initThemeSync`; do not label theme support absent simply because no new downstream patch was added. This audit did not reproduce the original Windows theme report. |

## Every currently open issue

| HOP issue | Request | Downstream classification / next evidence |
| --- | --- | --- |
| [#102](https://github.com/golbin/hop/issues/102) | Synchronized split views of the same document | Not added. Separate independent document windows are not synchronized views. Requires a shared document/undo/session design. |
| [#99](https://github.com/golbin/hop/issues/99) | Last wrapped line missing in table cells, screen/PDF/print | Partial narrow correction only. Obtain and reproduce the exact HWP case before a closure claim. |
| [#96](https://github.com/golbin/hop/issues/96) | Cross-window copy loses paragraph alignment/spacing | Not verified fixed. Requires a real two-window rich clipboard round trip, not plain-text typing tests. |
| [#91](https://github.com/golbin/hop/issues/91) | Page numbers; text drag into table; cell-local Select All; column-width dragging | Four separate acceptance criteria. Existing table/page feature code is not proof of all four; macOS native behavior is outside this Windows package. |
| [#89](https://github.com/golbin/hop/issues/89) | Apple Silicon code-signature failure | Outside the current Windows unsigned distribution. No macOS signing/notarization claim. |
| [#85](https://github.com/golbin/hop/issues/85) | Table typing is temporarily invisible / delayed | Not verified fixed. Requires timed visible-render evidence with real input; final-composition fixes alone do not prove it. |
| [#81](https://github.com/golbin/hop/issues/81) | General document conversion/layout quality | Not blanket-resolved. Representative source documents and independent layout references are required. |
| [#80](https://github.com/golbin/hop/issues/80) | Windows ARM64 installers and signing | Not delivered. Current packages and PE checks are x64; trusted signing is separate. |
| [#79](https://github.com/golbin/hop/issues/79) | Pop!_OS Hangul switching | Linux-specific; outside the current Windows package and tests. |
| [#78](https://github.com/golbin/hop/issues/78) | Table numbers/text disappear on printing | Partial synthetic virtual-print coverage. Original document/vendor printer output is not certified. |
| [#77](https://github.com/golbin/hop/issues/77) | Fedora/KDE/fcitx5 typing delay | Linux-specific; no matching native environment verified. |
| [#76](https://github.com/golbin/hop/issues/76) | Insert/move a signature image over a table | Not verified fixed. Needs image insertion, anchoring/wrapping and save/reopen evidence for the supplied case. |
| [#73](https://github.com/golbin/hop/issues/73) | Saved HWP becomes corrupt/incompatible | High-priority unverified original case. Generic round trips do not substitute for original-file and Hancom checks. Preserve originals. |
| [#72](https://github.com/golbin/hop/issues/72) | Linux ARM64/Wayland maximize | Outside this Windows distribution. |
| [#70](https://github.com/golbin/hop/issues/70) | Superscript is flattened in print | No issue-specific proof. Current eight print scenarios do not explicitly test superscript baseline/size. |
| [#68](https://github.com/golbin/hop/issues/68) | Linux AppImage startup crash | Outside this Windows distribution. Disabling the upstream updater does not prove the Linux crash fixed. |
| [#50](https://github.com/golbin/hop/issues/50) | Android distribution | Not included. Desktop source sharing is not a tested Android package. |

## Closed upstream requests still requiring downstream work

- [#98](https://github.com/golbin/hop/issues/98), [#34](https://github.com/golbin/hop/issues/34): newer HOP's [password/session changes](https://github.com/golbin/hop/commit/2b1189b3079045481134864d9ccb02ca535ea6bb) are not in the current OpenGeul pin. Porting only the prompt is unsafe: cancellation, pending document operations, original encryption protection and explicit plaintext Save As consent must be reconciled with OpenGeul's HWPX saves.
- [#94](https://github.com/golbin/hop/issues/94): the pinned renderer auto-fits below 1024px even in the desktop runtime. This draft fixes only preservation of the chosen desktop zoom across document loads. Toolbar overflow/layout and macOS native window testing are separate; this document does not mark the complete issue resolved.
- [#92](https://github.com/golbin/hop/issues/92): searchable PDF export is not established by printer success. The tested Microsoft virtual printer outlines glyphs; exact visible ink does not make a PDF searchable.
- [#20](https://github.com/golbin/hop/issues/20): upstream application auto-update is deliberately disabled in OpenGeul. Automatic GitHub development-release publication is not an in-app updater.

## First follow-up: desktop zoom portion of #94

The host adapter follows the reviewed capture/load/restore sequence from HOP commit `2b1189b3079045481134864d9ccb02ca535ea6bb` without importing its engine/password changes. Only desktop loads restore zoom; browser/mobile retains its existing auto-fit. The existing build patcher installs it in both build paths and records before/after host hashes. Missing/duplicate anchors or a pre-existing `desktopZoom` name fail before modifying the existing backports.

Tests execute the actual prepared host initialization function, with only external DOM/font/canvas boundaries doubled. Narrow desktop checks failed before the change; all 13 Node cases and five patch-entry/negative Python cases pass after it. The local scaffold is intentionally partial, not a clone or a full native app execution; full current GitHub CI remains mandatory. A production Windows check at 960/1023/1025px, selected zoom, document switch/reopen and editable saved output remains a review item before merge. No native regression test specifically exercising that viewport sequence is claimed here.

No upstream pin, app version, raster reference, existing 78 UI gate, workflow permission, runner class, billing setting or published release is changed. The original exact print references plus their one reviewed digit-4 variant remain intact. This is an in-session review, not an independent reviewer sign-off.
