# Print hardening checkpoint — 2026-10-06

This checkpoint records test automation changes, not a product release or blanket printing compatibility claim.

## Implemented

- Replace the unreliable Ctrl+Shift+P preview accelerator with one physical click of the exact visible/enabled system-print action inside the owned Print/RootView accessibility window. Both the older Button and newer Hyperlink roles are supported. No force-accessibility flag, security downgrade or app-specific hook is added.
- Maximize the actual app window before printing: failed multipage screenshots showed the preview footer outside the hosted runner's 1024x768 work area. Final verification of this adjustment is pending.
- Require the exact scenario's retained spooler job to be PRINTED, with no textual/error/active status, matching one/two-page completion counts and actual A4 portrait media. Pending and queued are not success.
- Validate all eight scenario names exactly once, preserve source hashes even on failure/cancellation, capture failures before app teardown, and close the app before deleting its owned queue.
- Require complete artifact checksum coverage and full MSIX/portable runtime equality, including DLLs/assets/notices. Reject duplicates, Windows path aliases, special/symlink entries, path traversal, expansion limits and mismatched resources before staged extraction; never overwrite an existing runtime.

## Verified evidence

- Local policy suite: 121 passed. Independent PDF/raster unit suite: 23 passed. New regression coverage was observed RED before implementation; removing the textual-status check makes its negative control fail.
- Real package artifact 11387902336 from PR4 run 37404480348: 1,432 runtime files match, editor SHA-256 375a067e7d0ecdbb16c8efbd16760335172849003b7584218adc00b668c818ce, runtime manifest SHA-256 37c702879d315e8c9248e653ce88a236c30556d6c1c69442ae059d7f1baea48b. The strengthened verifier also completed on both diagnostic Windows jobs.
- Run 37418948716 proved the real system-dialog action works with ordinary on-demand accessibility on both Windows images. This inspected the UI; it did not print.
- Run 37420165987 at 8f37bdf used that prior PR4 binary, not a newly built candidate. Windows2025 completed five of eight full printer scenarios, including HWP/HWPX and negative/positive-spacing tables, against unchanged reference fingerprints. The earlier all-eight system-dialog failure no longer occurs. However two multipage/range cases encountered inaccessible preview controls, and the zero-spacing reference comparison failed.
- In the same run Windows2022 completed actual spooler printing and media checks for six output cases, but their exact rasters differed from the reference; multipage encountered a dialog timeout. Cancellation passed. This is NOT an all-green run.

## Failures deliberately preserved

Windows2022 raster bounds showed shifted/scaled output, despite correct A4 job media. Windows2025's zero-spacing case differed at eight thresholded pixels (gray levels 154/155 vs 160/161) while dimensions and bounds matched. These are observations, not a proven cause or permission to replace references. No tolerance, baseline acceptance or skipped gate was introduced to hide them. The display-size adjustment is running separately in the diagnostic branch; all final-candidate same-run Windows/print checks remain required before merge.

The diagnostic workflow is isolated in work/print-accessibility-check and is NOT part of PR6 or the release path. PR6 remains draft. Hardware behavior, arbitrary documents, the original HOP report documents, trusted signing and Store/WACK are still outside the evidence above.
