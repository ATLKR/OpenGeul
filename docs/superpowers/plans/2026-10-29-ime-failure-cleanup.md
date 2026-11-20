# IME failure cleanup and layout evidence plan

> **For agentic workers:** Use superpowers:subagent-driven-development for implementation and independent review.

**Goal:** Keep original restoration reachable after event collection failure and
locate layout guard mismatches without another native observation.

**Architecture:** Separate existing cleanup try blocks. Pure bounded projection
of values at the original failing layout assertion feeds kind 1 schema 10.

**Tech Stack:** Python standard library and the existing IME/scenario controllers.

**Spec:** docs/superpowers/specs/2026-10-29-ime-failure-cleanup-design.md

## Global constraints

- Keep primary error, one restoration attempt and existing cleanup order.
- No extra queries/input/layout changes/focus actions/deadline extension.
- Numeric evidence only; case notices at most 2048 bytes; legacy schemas unchanged.

## Review focus

- Diagnostic event failure must not block original restoration.
- Restoration and event failures must not overwrite each other or the primary.
- Wrong retained identities or a successful US guard must not emit failure evidence.
- Zero HKL is an observed value, not proof of an active Korean profile.
- Consumer imports must not initialize any Windows/native producer.

### Task 1: Restoration cleanup

**Files:** suite/e2e/korean_ime_smoke.py and
suite/tests/test_ime_composition_progress.py.

- [ ] Reproduce the skipped restoration with actual case harness (RED).
- [ ] Separate event retention from the one existing restoration attempt.
- [ ] Verify primary identity, exact once restoration/close and dual-error retention.

### Task 2: Existing guard evidence

**Files:** create suite/e2e/keyboard_layout_summary.py and its tests; modify
ime_keyboard_session.py, scenario_editor_shortcuts.py, numeric_notice.py and
test_numeric_notice.py.

**Interfaces:** `remember(record, origin, slot, keyboard, binding)` retains only
the closed snapshot; `project(record)` returns its numeric list or None;
`valid(value)` validates the fixed vector.

- [ ] Add failing tests for both actual guards and numeric producer/consumer.
- [ ] Retain existing HKLs/binding only when the original layout predicate fails.
- [ ] Bind schema 10 to the original assertion source, case and retained identity.
- [ ] Verify rejection, optional fallback, legacy formats, size and pure imports.

### Task 3: Verification

- [ ] Run configured Linux checks and independent final source review.
- [ ] Check active CI and remote source before commit/push.
- [ ] Freeze the committed decoder and run one normal paired Windows acceptance.
- [ ] Read the terminal receipts and continue from the new measured results.
