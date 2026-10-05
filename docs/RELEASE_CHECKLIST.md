# Release gates

Unsigned developer prereleases may be published only after required automated tests, complete native build, package verification and checksums succeed. They are not supported stable releases or trusted installers.

Before a supported stable/Store release, verify and record:
- Clean Windows 10/11 installation, startup, uninstall/update; installed/missing WebView2 and VC runtime behavior; offline operation.
- HWP/HWPX double-click, drag/drop, multiple windows, Korean/space/long/UNC paths, HOP/other app coexistence; never force defaults.
- Korean IME, accessibility, DPI and keyboard navigation.
- Installed system/per-user fonts, font help, missing-font/fallback layout warnings, Canvas2D/CanvasKit and PDF/printing.
- Representative documents: open/edit/save/reopen in originating applications, values, tables, images, equations, notes, printing, unsupported/password/large files and graceful failure. Preserve originals.
- No bundled font programs, credentials, personal test documents or unauthorized assets, including nested JS/WASM/EXE resources. File/magic scans alone are not a complete embedded-data audit.
- Full dependency/Skia/CanvasKit/WASM license texts and notices; missing inventory entries reviewed; vulnerability checks.
- Native SVG PDF metadata guard, optional direct Skia PDF, embedded document fonts and print-driver rights reviewed separately.
- WACK and actual Partner Center identity, Store name rights, screenshots, age rating, support contact, privacy statement and runFullTrust explanation.
- Real signing or Store distribution for normal trusted MSIX installation. Never publish private keys or tell users to disable protection.

HOP's current HWPX-save and autosave/recovery limitations must be disclosed, not represented as implemented.
