# Delayed text-cut ownership guard — 2026-10-08

While investigating HOP #96's cross-window formatting request, a separate source-level safety defect was reproduced. The pinned HOP text `edit:cut` command waits for clipboard writing, then authorizes deletion using only selection coordinates. If another document has replaced the source while the clipboard Promise is pending, the same coordinates can authorize `performDelete` against that replacement. The previous selection object is also serialized after the await, instead of freezing its original values.

## Reproduction and correction

The complete original `apps/studio-host/src/command/commands/edit.ts` was fetched at HOP `d426f0395e97bc1972f66d894d1a7c76a36374bc` and its Git blob matched `b53a3a3797734ce9318f4319951807a8c24d90b6`. A Node test executes its actual command definitions with only the document/input/OS-clipboard boundaries doubled. Deferring the clipboard Promise and changing the loaded document generation while retaining selection coordinates causes a deletion in the unpatched command. Six negative controls failed; seven existing behaviors passed.

The fix captures an immutable serialized selection and the public `WasmBridge.documentGeneration` before yielding. Deletion requires a valid unchanged generation, a still-loaded document, the same input handler and exactly the copied selection. `documentGeneration` increments even when identical bytes are reopened or a blank document is recreated; a file digest alone would not establish session ownership. The pinned bridge's actual accessor/load implementation was read before choosing this guard.

Normal text/cell cut still copies once before deleting once. Copy, clipboard export bytes, HTML-to-text fallback, paste and picture/table-object delegation remain unchanged. If ownership changed, the completed copy may remain in the OS clipboard, but this command does not delete the newly selected document's contents. No clipboard contents are added to diagnostic logs.

## Source and build controls

`scripts/patch_clipboard_cut.py` validates exact original source and test Git blobs before changing either. It updates only the existing upstream test double's `documentGeneration` and `hasLoadedDocument` fields; assertions are not removed or weakened. Source drift, duplicate/missing anchors, symbolic links and invalid/already-owned provenance fail closed. Both existing Linux/Windows build scripts apply the guard before `tests/hop/*.test.mjs` and product compilation. Before/after source/test hashes and the patcher hash are recorded in the existing package provenance ledger.

Local verification: 13 source-execution tests pass after the fix; nine patch ownership/provenance/build-order tests pass; Python compilation and Bash syntax pass. The latter suite was first observed failing before implementation, and its build-hook case also failed before wiring. Both original build scripts and the upstream command test file were materialized and matched their returned Git blob hashes. The local workspace is a partial source snapshot, not a Windows application run or the complete repository test suite. The existing upstream Vitest suite and full candidate CI must still execute on GitHub.

## Boundaries

This does **not** establish a fix for #96's paragraph alignment/spacing loss, cross-window rich-clipboard fidelity, object-cut handling, or every same-document content-revision race with unchanged selection. It is a narrow guard against the reproduced document/handler/selection ownership errors. A native user-timed clipboard race was not reproduced here; no real user document was altered.

This work is isolated from PR7's native zoom branch so that its running candidate is not cancelled or modified. It changes no engine pin, app version, print reference, workflow runner/permission, billing setting or published release. The current main branch's 78 UI cases and MSIX/engine gates remain intact; PR7 separately adds six native zoom cases for 84. Both sets must be retained and revalidated when integrated. The old printer references and the one previously reviewed digit-4 whole-page variant are untouched.

Review is in-session, not an independent/subagent sign-off. Keep the new PR draft until full CI and integration review succeed; no new release or all-HOP-requests completion is claimed.
