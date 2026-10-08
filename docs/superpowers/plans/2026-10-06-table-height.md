# Terminal table-line height implementation plan

**Goal:** Prevent compressed trailing line spacing from making a multi-paragraph table cell shorter than its last painted glyph line.
**Architecture:** Adapt only the terminal-negative-spacing part of rhwp PR 6074 to pinned rhwp 0.8.4. Keep the existing nonterminal and positive-spacing rules, parser fixes, font policy and all 62 UI gates. Patch native and source-built WASM identically; bind the patch to WASM provenance.
**Scope:** Related to HOP #99/#78, not proof that those reporters' documents or every printer are fixed. Do not import the broader row-growth heuristics from rhwp PR 6068 or normalize stored LINE_SEG values.

- [x] Generate a minimal synthetic five-paragraph inline table with public production WASM APIs and namespace-preserving XML mutation. Reproduce terminal glyph box overflow: 2.2px for -300 HWPUNIT spacing; zero/positive controls stay inside.
- [x] Add a strict, exact-pinned-file patcher and refusal tests.
- [ ] Run the synthetic geometry test against original and rebuilt WASM. Require the original to fail only the negative case and the rebuilt engine to pass all three cases, before and after save/reopen.
- [ ] Run the same synthetic documents through the native Rust render tree. Keep native targets isolated from Skia CLI outputs.
- [x] Include the patcher in source provenance and preserve contributor attribution.
- [ ] Open a draft PR; merge only after the full actual CI is green. Record failed/pending gates, never replace them with a probe result.

Review focus: positive trailing compatibility; negative nonterminal spacing remains compressed; exact pinned source drift; no font/customer document fixtures; same native/WASM patch and release gates. No fresh-context reviewer tool is available in this session; perform a separate diff review and leave PR draft until CI/review completes.
