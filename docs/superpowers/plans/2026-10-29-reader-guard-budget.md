# Reader Guard Budget Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans task by task. Check completed steps against actual receipts.

**Goal:** Distinguish the existing reader-budget failures without changing input or guards.

**Architecture:** A pure integer validator and privately bound producer snapshots supply optional kind-1 schema8. Writer freezes phase metadata at its guard failure before semantic cleanup. Calc binds the current failed shortcut invocation.

**Tech Stack:** Existing Python standard library and unittest; no new dependency or native ABI.

**Spec:** `docs/superpowers/specs/2026-10-29-reader-guard-budget.md`.

## Global Constraints

- Original 12-second reader limits, other original deadlines and all guards remain.
- No additional native/clock queries, input, focus/capture setters or retries.
- No raw content, path, URL, inventory payload or error text in the new vector.
- Existing case schemas1..7, compartment models1/2 and carrier3 remain valid.
- No main merge, distribution, new cost, credential or permission changes.

## Review Focus

- Two identical Calc deadline leaves can have different observation histories.
- Writer phase0 and zero-valued observations must not become unknown or phase1.
- Finally cleanup on the same clock tick must not change the earlier snapshot.
- Cloned records, stale invocations and partial rows must not borrow a binding.
- Optional projection/publication failure must preserve primary error and cleanup.

### Task 1: Bound existing observations

**Files:** create `suite/e2e/reader_guard_summary.py` and `suite/tests/test_reader_guard_summary.py`; minimally modify `capture_readiness.py` and `ime_keyboard_session.py`.

**Interfaces:** `freeze_writer(record, primary, session, context) -> None`,
`bind(record, primary) -> None`, `project(record) -> list[int] | None`,
`valid(vector) -> bool`. Decoder validation imports no producer.

- [ ] Demonstrate Calc first-check and positive-capture-wait failures with the original helper, plus Writer inner-validator failure.
- [ ] Run RED tests for a known first-check clock and the original single failed IME clock sample.
- [ ] Retain those existing reads privately, freeze Writer before finally and implement the exact 20-integer contract.
- [ ] Test immutable snapshots, exact object/failure/owner joins, stale/cloned rows, phase0, unknown masks, signed times, raw-field access traps and unchanged clock/native/input counts.

### Task 2: Closed notices and original failure paths

**Files:** `numeric_notice.py`, `windows_smoke.py`, `korean_ime_smoke.py`, corresponding existing notice/entry tests.

**Interfaces:** codec `capture_reader_guard(record, primary)` and `emit_reader_guard_case(name, record)` are optional and never replace the original error; schema8 adds `readerGuard` to the v2 keys.

- [ ] Write RED tests for both explicit contexts, cross-context/forged rejection, old-version decoding, message size and no extra Writer raw artifact.
- [ ] Bind during original failure handling; emit the extra Writer case only when the bound schema8 projection qualifies.
- [ ] Preserve the original case file, callback file, failure identity and publication/cleanup precedence on projection or write failures.
- [ ] Run affected checks and obtain independent review before freezing.

### Task 3: Exact-source validation and Windows execution

- [ ] Freeze candidate hashes, source patch and review receipts; run one configured full Linux suite with existing validation Python/PowerShell/XDG paths.
- [ ] Commit, freeze the new pure decoder including the summary module, and run isolated producer/consumer checks against that source.
- [ ] Recheck remote source and active CI before the next single standard Windows run; use the prepared paired normal-acceptance transition only after reviewing the candidate.
- [ ] Validate actual notices, original process exits and full product gates; do not infer release readiness from a diagnostic or unit-only pass.
