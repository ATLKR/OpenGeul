# Calc save dispatch implementation plan

> **For agentic workers:** Use the existing shared checkout with unique file ownership. Do not create worktrees. Execute the user's already authorized work without another approval checkpoint.

**Goal:** Locate the original ARM64 IME Calc save failure with a bounded numeric diagnostic, then correct demonstrated causes and qualify the final code on Windows.

**Architecture:** A fixed native protocol and bounded recorder observe the existing engine save path. A controller binds the original process generation and deadline. Source authentication and separate artifact qualification prevent diagnostic runtime delivery.

**Tech stack:** C++17, Windows APIs, Python ctypes/unittest, PowerShell, existing GitHub Windows runners.

**Spec:** `docs/superpowers/specs/2026-10-26-calc-save-dispatch.md`.

## Global constraints

Use one absolute deadline of at most 30 seconds, numeric IPC, capacity 128 and depth eight. Retain original process handles. Collect no input or document content. Preserve ordinary runtime locks and HWP packages. Do not merge, release, publish, or deploy.

## Review focus

Stale process generations must reject before publication. Deadline expiry must not create another allowance. Nested save dispatch must preserve parent identity. Cleanup failure must remain visible. Diagnostic artifacts must never satisfy ordinary package qualification.

## Tasks

- [x] Recover accessible evidence, inventory CI, and distinguish original failures.
- [ ] Write failing native recorder behavior tests, implement its wire and Windows adapter, and verify portable behavior.
- [ ] Write failing source authentication and diagnostic build isolation checks, implement probes and explicit diagnostic build mode, and verify normal builds retain their contract.
- [ ] Write failing controller/consumer ownership, ABI, deadline and cleanup checks, implement them, and connect to the original single IME save.
- [ ] Independently review all changes; run frozen local validation and privacy checks before committing and pushing.
- [ ] Check remote run identities, compile once on the standard ARM64 runner, consume the diagnostic evidence, and correct proven causes.
- [ ] Restore full acceptance and verify actual x64/ARM64 input, focus, accessibility, persistence, lifecycle, installer and diagnostic integrity gates on the final commit. Preserve unresolved failures as failures.
