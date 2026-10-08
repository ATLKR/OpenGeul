# OpenGeul · 오픈글

Independent Windows distribution of [HOP](https://github.com/golbin/hop) and [rhwp](https://github.com/edwardkim/rhwp). Own code is **MIT**, with upstream and dependency licenses preserved. Not affiliated with or endorsed by Hancom, HOP, rhwp or The Document Foundation.

## Scope

The build compiles the complete pinned HOP desktop app and upstream rhwp editor/engine, not a launcher for a separately installed HOP. It additionally builds the rhwp command-line program with `native-skia` for advanced conversion/rendering. Sources are pinned in `config/upstream.lock.json`; `scripts/prepare_upstream.py` checks out the full source and applies auditable overlays. `upstream/hop` links to the same revision for navigation.

OpenGeul supports **HWP/HWPX opening, editing and saving**, including Save As between the two formats. PDF export, the Windows print dialog, drag-and-drop, multiple windows, recent documents, staged/atomic save and external-modification checks are retained. The downstream engine includes a narrowly tested correction for the final line of compressed inline-table cells. Plain `p/P` input and persistent toolbar-label visibility are also supported. **Autosave/recovery is not provided.** CLI capabilities are separate and documented by `--help`; no promise of perfect fidelity is made. LibreOffice/DOCX/XLSX/PPTX integration is outside this release.

## Builds and prereleases

[Actions](https://github.com/ATLKR/OpenGeul/actions) runs policy tests and Windows builds on main pushes and pull requests. A main/version-tag build that passes every required gate publishes a clearly labeled [development prerelease](https://github.com/ATLKR/OpenGeul/releases). Pull requests never publish releases. Manual `checks`, `engine` and `full` stages are supported; only full validated builds on authorized refs can publish. Standard public runners, bounded artifacts and consumed-transport cleanup are documented in [free CI](docs/FREE_CI.md). No signing secret, PAT or Store account is required for the unsigned GitHub prerelease.

Outputs: unsigned MSIX, unsigned portable ZIP, SHA-256 checksums, source/package provenance and CLI help. An unsigned MSIX is **not** a trusted double-click installer. Portable ZIP users need the installed Microsoft Edge WebView2 Runtime. Respect Windows and company security policy; do not disable protection.

## Fonts

No third-party font programs are bundled. Installed Windows/user fonts are used; **글꼴 도움말** opens official Noto download pages and Windows font settings. The app never silently installs fonts or extracts another product's fonts. See [font policy](docs/FONTS.md). Font substitution may change line/page layout; keep originals. PDF metadata checks are a safeguard, not a legal audit.

## Build locally on Windows

Requires PowerShell 7, Python 3.11+, Node 24/Corepack, Git, Rustup, Visual Studio C++ build tools and Windows SDK. Use a clean working directory.

The Windows build requires the source-bound WASM files produced by `scripts/build-wasm.sh` on Linux at the **same OpenGeul revision**. The simplest reproducible route is Actions > OpenGeul Windows build and release > Run workflow > `full`. For a local Windows build, supply that revision's verified WASM directory explicitly:

```powershell
./scripts/build-msix.ps1 -WasmDirectory C:\path\to\verified-wasm
```

The script rejects mismatched engine/patch provenance. Do not substitute an arbitrary upstream WASM package.

Preparation refuses to reset existing `.work/hop`, `.work/payload` or `dist` directories. Preserve work before rebuilding. Upstream contracts run before product-policy changes; modified frontend/native tests run afterward. Critical document-session files are hash-checked unchanged.

## Licensing and verification

See [MIT license](LICENSE), [third-party notices](THIRD_PARTY_NOTICES.md), [future LibreOffice policy](docs/LICENSE_POLICY.md), [verification](docs/VERIFICATION.md), [setup](docs/SETUP.md) and [release checklist](docs/RELEASE_CHECKLIST.md). Future MPL imports retain MPL; this repository's MIT license cannot erase their obligations.
