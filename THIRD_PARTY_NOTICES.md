# Third-party notices

OpenGeul is an independent downstream distribution based on HOP and rhwp. The MIT license of OpenGeul's new code does not replace upstream or dependency licenses.

Pinned upstreams:
- HOP: https://github.com/golbin/hop/tree/34bd15c97e0851627cb7f055042c5340198aeb7f
- rhwp: https://github.com/edwardkim/rhwp/tree/1a76570e833917d15817415a53c09ad61ab3203f
- svg2pdf 0.13.0 vendor patch: https://github.com/edwardkim/rhwp/tree/1a76570e833917d15817415a53c09ad61ab3203f/vendor/svg2pdf (upstream provenance in `RHWP_PATCHES.md`)

HOP and rhwp license text, including source excerpts/derived integration code:

```
MIT License

Copyright (c) 2025-2026 Edward Kim

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

The Windows build copies upstream LICENSE files and collects dependency license texts into Notices/Dependencies. Its inventory is deliberately over-inclusive and requires human review: it is not a complete SBOM or compliance certification. Check native/runtime/transitive dependencies, generated WASM, CanvasKit, Skia, resources and omitted notice texts before a supported stable release.

The native-Skia CLI includes rust-skia `skia-safe` and `skia-bindings` 0.153.3. Their exact [MIT license text](notices/rust-skia-0.153.3-LICENSE.txt) is from upstream commit `b7f043e0b1e2a850e702245de811f01df1f6b0ff`, SHA-256 `4b33ed5b329a3a79eb1243fd91373c68b0ae0b9df7503bfc50d0c5253adf1b9a`. Packaging copies it into each crate's notice directory and records its provenance in the dependency inventory. This rust-skia notice does not replace Google Skia or other dependency notices.

No font binaries are included in this repository or intended runtime payload. Linking to a publisher does not sublicense their fonts. Installed fonts retain their original licenses. Trademarks and Store policies are separate from source-code licenses. Future LibreOffice imports retain their applicable MPL and other licenses; see docs/LICENSE_POLICY.md.

## Retired downstream backports

Earlier OpenGeul sources adapted the plain-character shortcut fix from HOP PR #101 by FMsongX2, commit `f9bbe8dc66172a1959af1e388e6c28a5b597c5a6` (https://github.com/golbin/hop/pull/101), and supplied a toolbar-label preference for HOP issue #97. The current distribution uses rhwp 0.8.7's result-aware shortcut dispatch and HOP 0.4.5's native toolbar preference. The duplicate downstream implementations are removed; regression coverage remains. A narrow migration carries the earlier OpenGeul hidden-label choice into HOP's native storage key. This does not claim PR #101 was merged.

Earlier OpenGeul sources narrowly adapted the terminal negative-line-spacing clamp from rhwp PR #6074 by planet6897, commit `c7d3c66398acdb3c093fdea6fef573e14f771a6c` (https://github.com/edwardkim/rhwp/pull/6074). That work was incorporated upstream via PR #6076 and is present in the pinned rhwp 0.8.7 engine. The duplicate source patch is removed; synthetic native/WASM geometry regressions remain. The original rhwp MIT notice above remains applicable. This does not establish that all HOP table or printing reports are resolved.
