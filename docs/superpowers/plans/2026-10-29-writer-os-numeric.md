# Writer OS numeric evidence implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for implementation and independent review.

**Goal:** Preserve existing numeric Writer OS failure details in closed notices.

**Architecture:** A pure summary module validates and projects the completed OS
result. numeric_notice adds a context-bound kind 1 schema 9; no new native calls.

**Tech Stack:** Python standard library, existing Windows acceptance workflow.

**Spec:** docs/superpowers/specs/2026-10-29-writer-os-numeric-design.md

## Global constraints

- Numeric evidence only; maximum case notice 2048 bytes.
- Preserve schemas 1 through 8 and current numeric identifiers.
- Preserve OS watchdog, VCL/input/focus, primary error, cleanup and lifetime gates.
- Use only the completed result for the exact retained Writer process generation.

## Review focus

- Stale or another case's result must not become current failure evidence.
- Cleanup counters and HRESULTs must not become engine death claims.
- Optional projection errors must leave the original notice available.
- Largest legal values must fit the same transport limit.
- A decoder must remain importable without producer/native modules.

### Task 1: Closed pure projection and notice integration

**Files:** create suite/e2e/writer_os_summary.py and
suite/tests/test_writer_os_summary.py; modify suite/e2e/numeric_notice.py and
suite/tests/test_numeric_notice.py.

**Interfaces:** summary `project(record)` returns a fixed numeric list or None;
`valid(value)` returns bool. Numeric notice binds scope/case/module/stage/source
and observed retained process identity before selecting schema 9.

- [ ] Add round-trip, distinct root-failure and wrong-context/owner tests; observe RED.
- [ ] Implement the smallest fixed vector and schema 9 producer/decoder.
- [ ] Verify malformed, extra, boolean, range and cleanup counter rejection.
- [ ] Verify bad optional projection preserves the original notice and all legacy schemas.
- [ ] Verify worst-case messages remain at most 2048 bytes and imports stay pure.
- [ ] Run relevant tests, then configured full Linux checks and independent review.

### Task 2: Exact-source Windows evidence

- [ ] Preserve source hashes and review the staged objects before commit/push.
- [ ] Freeze and offline-test the committed decoder, including strict pagination.
- [ ] Check active runs and run the standard paired normal acceptance workflow once.
- [ ] Collect closed terminal numeric receipts and continue fixes from new evidence.
