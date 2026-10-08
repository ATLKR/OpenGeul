# Release-candidate repairs — 2026-10-06

## Root causes and scoped corrections

The failing Windows 2022 spooler PDFs had A4 media but their content was scaled and offset. Independent PDF inspection found a white page path at (25.44,35.76)-(571.44,807.00) rather than (0.24,0)-(595.32,841.92), with retained glyph/operator counts. Native preview inspection showed Letter paper and Default extra margins before the A4 system-driver dialog. Configure both stages explicitly: A4, no additional preview margins and actual size; the actual driver remains A4 portrait.

WebView2 153 exposes dropdowns as ComboBox, while the older runtime uses named Buttons. Both offer native ExpandCollapse and ListItem options. SelectionItem.Select did not commit the newer preview's value even without Collapse. A single native option click does, followed by readback of the committed value. The owned system-print action uses its actual UIA InvokePattern once, avoiding small-display keyboard/click timing problems. There is no app test hook, direct-PDF shortcut or security flag.

## Real diagnostic evidence (not final-candidate build proof)

- Diagnostic 37443984734 on Windows 2022: all eight native printing scenarios passed with the original exact fingerprints after preview configuration.
- Single-case diagnostic 37445466435: both Windows images printed HWPX successfully after the option-click correction.
- All-case diagnostic 37445818877: Windows 2022 passed 8/8. Windows 2025 passed 7/8; the remaining case was the independently reviewed glyph variant below, not missing lines or a failed spooler.
- These diagnostic runs reuse PR4 binary 375a067e7d0ecdbb16c8efbd16760335172849003b7584218adc00b668c818ce from source 0aedc704fe75b996bfa86f666f23e4297071de83. They never replace the final full workflow's same-run candidate tests.

## Explicit reference review, not a relaxed comparison

Windows 2025 table-0 output from run 37445818877, artifact 11403760205, has the same A4 dimensions, bounds, text, table borders and placement as the original. Both PDF page streams contain 1,858 operators; the only ten changed operands are coordinates of one digit-4 crossbar (-2.24/-3.37 versus -2.40/-3.36). All five rows and the terminal descender are visually intact. At 216 DPI this changes exactly eight thresholded pixels in [479,388,490,389].

Retain every original fingerprint, and add only this exact independently reviewed whole-page variant, scoped to table-0 page 1 with its run/artifact/review provenance. Unreviewed hashes, other cases/pages, changed bounds, missing review, duplicate variants and altered pixels still fail. There is no generic pixel tolerance or candidate-generated baseline. Re-reading all seven actual Windows 2025 output PDFs with this fixed reference set passes independent geometry/raster inspection; fresh CI must still execute the real print path.

## Local review and final gate

New setting/order/action tests were observed failing before the fix. The local complete policy suite passes 150 tests, CI helper suite passes 81, and independent PDF/raster suite passes 31 (including eight reviewed-variant negative controls). The existing print-output save helper and exact-HWND error/file-dialog fixes are preserved.

The final product patch version is 1.1.1 (MSIX 1.1.1.0). Application functionality is unchanged by the print harness correction; release notes now correctly advertise the previously implemented HWPX saving. Full source build, all 78 UI executions and MSIX installation must pass on the final candidate before merge/publication. This document does not mark that pending final execution successful. Reviewed in-session; no independent/subagent review is claimed.
