# Third-party notices

OpenGeul is an independent downstream distribution based on HOP and rhwp. The MIT license of OpenGeul's new code does not replace upstream or dependency licenses.

Pinned upstreams:
- HOP: https://github.com/golbin/hop/tree/d426f0395e97bc1972f66d894d1a7c76a36374bc
- rhwp: https://github.com/edwardkim/rhwp/tree/496333b27d21ddb9114ba9ae340bcb895870c9a7
- svg2pdf patch: https://github.com/edwardkim/svg2pdf/commit/2caeb0a038f9128b79833d803b94c2667565c4da

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

No font binaries are included in this repository or intended runtime payload. Linking to a publisher does not sublicense their fonts. Installed fonts retain their original licenses. Trademarks and Store policies are separate from source-code licenses. Future LibreOffice imports retain their applicable MPL and other licenses; see docs/LICENSE_POLICY.md.

## Reviewed downstream backport

The plain-character shortcut fix is adapted from HOP PR #101 by FMsongX2, commit `f9bbe8dc66172a1959af1e388e6c28a5b597c5a6` (https://github.com/golbin/hop/pull/101). It prevents unmodified printable keys from being captured as global shortcuts; the HOP/rhwp MIT notices above remain applicable. OpenGeul adds regression coverage and does not claim the upstream PR has been merged. The toolbar-label preference is an OpenGeul implementation addressing HOP issue #97, not imported code from that issue.

The terminal negative-line-spacing clamp is adapted from rhwp PR #6074 by planet6897, commit `c7d3c66398acdb3c093fdea6fef573e14f771a6c` (https://github.com/edwardkim/rhwp/pull/6074). That work was incorporated upstream via PR #6076. OpenGeul limits the adaptation to terminal inline-table lines in its pinned 0.8.4 engine and supplies its own synthetic regression fixtures. The original rhwp MIT notice above remains applicable. This is not an upgrade to the complete newer engine and does not establish that all HOP table or printing reports are resolved.
