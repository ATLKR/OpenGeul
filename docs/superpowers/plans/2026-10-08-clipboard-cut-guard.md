# Async clipboard cut guard implementation plan

> Execute inline with test-driven development; no merge or publication in this task.

**Goal:** Prevent a delayed text cut from deleting a selection belonging to a replacement document or input handler.
**Architecture:** Capture the serialized selection and public WasmBridge.documentGeneration before the clipboard await. Authorize deletion only for the same loaded generation, same handler and exact original selection. Keep existing clipboard bytes, fallback and object delegation unchanged.
**Tech stack:** pinned HOP TypeScript, source-bound Python patcher, Node source-execution tests, existing Windows/browser CI.
**Spec:** The observed async boundary in pinned HOP edit.ts (blob b53a3a3797734ce9318f4319951807a8c24d90b6), documented in docs/CLIPBOARD_CUT_GUARD.md.

## Constraints
Separate draft branch from main56ca883; leave PR7's running native-zoom candidate unchanged. No engine/version/print-reference/runner/permission changes. Do not claim this fixes HOP96 rich clipboard layout. No customer documents, clipboard-content logging or native test backdoors.

## Tasks
- [x] Execute original command with a delayed clipboard: six guard cases fail, seven existing behaviors pass.
- [x] Write patcher safety/provenance/order tests and observe failure before implementation.
- [x] Add the minimal snapshot guard; update only the upstream test double's real bridge fields, not expectations.
- [x] Wire both build paths before source tests; local 13 Node + 9 Python controls pass. Full GitHub execution remains pending.
- [ ] Check exact remote/local blobs, review, publish a separate draft PR and inspect real CI.

## Review focus
Copied selection mutated during await; unloaded/replaced document with identical coordinates; new handler; denied clipboard; unchanged successful cut, copy, cell-text and object delegation. Same-document content revision with unchanged selection and native OS timing remain separate evidence boundaries.
