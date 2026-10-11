# HOP 0.4.5 / rhwp 0.8.7 integration

The October 11, 2026 update pins the official HOP `v0.4.5` release at `34bd15c97e0851627cb7f055042c5340198aeb7f` and its exact rhwp `v0.8.7` submodule at `1a76570e833917d15817415a53c09ad61ab3203f`. The repositories remain `https://github.com/golbin/hop.git` and `https://github.com/edwardkim/rhwp.git`. HOP's newer default-branch commit adds release-verification documentation; it is not required for this runtime update. The rhwp release's later CLI asset repackaging does not change its source tag. The Rust 1.93.1 and pnpm 10.33.0 pins remain unchanged.

The current engine replaces the earlier keyboard, toolbar and terminal-negative-spacing backports. Their attribution remains in `THIRD_PARTY_NOTICES.md`; their source patches and table-patch ledger requirement are removed. A narrow migration preserves the previous OpenGeul hidden-toolbar preference while respecting HOP's newer explicit preference. The independent table oracle and observed pristine-WASM hashes are documented in `TABLE_HEIGHT_VERIFICATION.md`.

The HWPX staging overlay preserves upstream's public document-operation wrappers and private safety-save methods. Private format fallback avoids taking a nested operation lock. The encrypted-document consent applies to the chosen HWP/HWPX format; cancellation preserves the original document and password flag, and only a committed plaintext replacement clears that flag. The final-composition reconciliation runs after rhwp's new cell-block IME guard. Regression tests exercise consent, dirty safety save, edits during safety save and concurrent open/PDF/print/close attempts against the actual generated Studio source.

## PDF policy call graph

The GUI remains on `apps/desktop/src-tauri/src/pdf_export.rs::export_core_to_pdf` → `apps/desktop/rhwp-adapter/src/lib.rs::searchable_pdf_from_svg_pages` → `renderer/pdf.rs::svgs_to_pdf_with_options`. The CLI initializes `PdfBackend::default()` in `src/cli/outputs/pdf.rs`; upstream's default enum variant is `CompatibilitySvg`. Its SVG branch reaches the same conversion sink. SVG wrappers converge at `svgs_to_pdf_with_links_and_to_chunk`, where OpenGeul filters the real font database before conversion and rejects explicitly requested fonts whose embedding metadata prohibits subsetting.

The newly available `--backend direct` branch reaches `render_pages_pdf_direct_native_with_profile_and_options`, which delegates to the `DocumentCore` implementation and then `layer_trees_to_pdf_with_links`. The three public layer-tree PDF functions converge at this sink. Skia's renderer constructs its own system font manager, loads custom font paths, and can consume portable glyph-run font bytes. Filtering the SVG font database or only custom paths cannot enforce the same embedding policy on that path. OpenGeul therefore rejects this optional direct PDF sink with an explicit error recommending the SVG backend. The PNG renderer remains usable. This is a bounded compatibility policy until a Skia font-resource filter can be independently verified.

The native policy target uses upstream's existing MIT-licensed deterministic `RHWPExactKerningSmoke.ttf` test fixture. It changes only its in-memory OS/2 embedding bits and family name to cover allowed/restricted fonts without depending on installed fonts. It checks valid allowed SVG PDFs, a restricted SVG error, all three direct entry points including portable glyph resources, the positive default SVG backend and retained PNG rendering. No font binary is added to this repository or the distributed application. rhwp 0.8.7 disables automatic integration-test discovery, so `prepare_native_tests.py` explicitly registers and source-hashes both the table and policy targets instead of relying on a copied test file being discovered.

## Local checks and remaining gates

Local checks used an isolated sparse checkout of the exact pinned commits at `.work/validation-hop`, with the same downstream transformations applied sequentially. This is source verification, not a replacement for the production full-checkout pipeline. Recorded commands include:

```text
python -m unittest discover -s tests -v                         # 220 passed
HOP_SOURCE="$PWD/.work/validation-hop" RHWP_SOURCE="$PWD/.work/validation-hop/third_party/rhwp" node --experimental-strip-types --loader ./tests/hop/loader.mjs --test tests/hop/*.test.mjs
                                                              # 33 keyboard/toolbar checks passed
node --experimental-strip-types --test tests/composition-final.test.mjs tests/save-format.test.mjs
                                                              # 22 passed
(cd .work/validation-hop && corepack pnpm run test:studio)        # 177 passed, 23 files
(cd .work/validation-hop && corepack pnpm run build:studio)       # passed
python scripts/buildkit.py frontend .work/validation-hop/apps/studio-host/dist
                                                              # font-file audit passed
node e2e/table_height.mjs verify .work/validation-hop/apps/studio-host/vendor/rhwp-core .work/table-fixtures
                                                              # 6 pristine cases passed
python scripts/prepare_native_tests.py .work/validation-hop/third_party/rhwp
                                                              # explicit targets registered
CARGO_HOME="$PWD/.work/cargo" RUSTUP_HOME="$PWD/.work/rustup" CARGO_TARGET_DIR="$PWD/.work/target-namespace-api" .work/cargo/bin/cargo test --manifest-path overlay/namespace-tests/Cargo.toml
                                                              # 7 passed against quick-xml 0.42.0
CARGO_HOME="$PWD/.work/cargo" RUSTUP_HOME="$PWD/.work/rustup" CARGO_TARGET_DIR="$PWD/.work/target-wasm-check" CARGO_BUILD_JOBS=2 CARGO_PROFILE_DEV_DEBUG=0 .work/cargo/bin/cargo check --manifest-path .work/native-policy-source/Cargo.toml --locked --target wasm32-unknown-unknown --lib
                                                              # production wasm32 Rust graph passed
LIBRARY_PATH="$PWD/.work/native-system-libs" CARGO_BUILD_JOBS=2 CARGO_HOME="$PWD/.work/cargo" RUSTUP_HOME="$PWD/.work/rustup" CARGO_TARGET_DIR="$PWD/.work/target-native-validation" .work/cargo/bin/cargo test --manifest-path .work/native-policy-source/Cargo.toml --locked --features native-skia --test opengeul_pdf_policy --config 'profile.dev.package.rhwp.debug=0' --config 'profile.test.package.rhwp.debug=0'
                                                              # 4 native policy checks passed
```

The pristine WASM's original provenance identifies the exact rhwp commit and matches the bytes used for the table check. It still reproduces the namespace RED control, so the source-built namespace overlay remains necessary. Local logs and hash evidence are under `.work/upgrade-evidence`; those ignored files are evidence from this workspace, not release artifacts.

Compiling the generated engine uncovered an additional namespace-helper dependency incompatibility: quick-xml 0.42 exposes attribute keys as strings, whereas the earlier helper expected byte slices. A private probe using the unchanged helper and exact `quick-xml = "=0.42.0"` reproduced the `to_vec` compile error (`namespace-api-red.log`). The production helper now owns key strings and compares those strings directly; it leaves XML fragments, QName values and escaping behavior unchanged. The actual standalone regression target now pins 0.42.0 and passes all seven alias, inherited/default namespace, local rebinding, exact-byte, escaped-URI and invalid-fragment cases (`namespace-api-green.log`). Both generated native/WASM source copies and namespace-ledger helper hashes match the fixed overlay. The production wasm32 Rust graph passes `cargo check --locked --target wasm32-unknown-unknown --lib` (`wasm-compile-check.log`); this is a type-compilation check, not the required release WASM/browser run.

Cargo's sparse-checkout fingerprint handling required a validation-only source copy without Git metadata at `.work/native-policy-source`; checked manifest, lock, parser helper/header, PDF source/guard, test and fixture hashes match the generated tree (`pdf-policy-source-hashes.json`). The sparse checkout also fetched the exact pinned `saved/blank2010.hwp` compile-time template, SHA-256 `43f472751fafefb8c66b0f831660ebed51e443a46bebe44c75bba918154ce4c9`. Production preparation still performs its normal complete fetch. Native Skia compiled, then linked using task-local names for the system's existing FreeType/fontconfig runtime libraries; no system file or dependency pin changed. The real PDF target passes all four tests (`pdf-policy-native-final.log`): allowed SVG output remains complete and searchable, restricted SVG output is rejected, all direct PDF entry points reject unsafe embedding, and native PNG remains available. The table target passes against both the native-Skia graph and the matching default-feature distribution graph.

The source-built WASM/browser pipeline, native Rust geometry and embedding-policy tests, Windows compile/unit tests, installed MSIX behavior, password-document UI, 62 editor UI executions and all virtual-printer comparisons must pass on the final candidate. Existing print goldens are retained. Windows UI, printing and WACK are not established by the local source/frontend results. Upstream's unchanged Windows build script does not resolve the independent DPI certification gate. The ordinary SDK package-input route and its controlled diagnostic evidence are documented in `WACK_PACKAGE_INPUT.md`; the updated source still requires its own complete qualification.

rust-skia is now 0.153.3, source commit `b7f043e0b1e2a850e702245de811f01df1f6b0ff`; Cargo.lock retains each exact crate checksum. Its MIT license text is unchanged (1,123 bytes; SHA-256 `4b33ed5b329a3a79eb1243fd91373c68b0ae0b9df7503bfc50d0c5253adf1b9a`), with the updated versioned notice retained.
