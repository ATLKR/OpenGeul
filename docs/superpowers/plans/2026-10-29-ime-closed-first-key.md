# Original first-key diagnosis implementation plan

> **For agentic workers:** Use superpowers:executing-plans, with independent review of the tested source.

**Goal:** Correct documented GUID input and observe the original ARM64 IME state transition.

**Architecture:** Normalize only fixed GUID literals, then select the existing
bounded diagnostic route and its already locked runtime/carrier. No new native
observation mechanism or engine build is introduced.

**Tech Stack:** Python ctypes/comtypes, existing Windows workflow and C++ observer.

**Spec:** docs/superpowers/specs/2026-10-29-ime-closed-first-key.md

## Global constraints

- Preserve UUID bytes, native calls, input, ownership, cleanup and original budgets.
- Numeric-only evidence; no document/input text, raw log or credential collection.
- Diagnostic runs cannot qualify a ZIP or substitute for final paired acceptance.
- Do not retry stopped artifact downloads, add permissions/costs, merge or release.

## Review focus

- Synthetic API boundaries must not be presented as Windows runtime proof.
- Zero HRESULT/default role values do not prove successful calls.
- GUID normalization must preserve service and requested interface identities.
- Missing/capped callbacks remain inconclusive without input replay.
- Mode selection must keep every product qualification gate closed.

### Task 1: GUID normalization

**Files:** suite/e2e/writer_os_accessibility.py and
suite/tests/test_writer_os_accessibility.py.

- [x] Reproduce the documented format boundary in real backend paths (RED four tests).
- [x] Add braces to the five literals and verify the four tests and 31 related checks.
- [ ] Run the integrated configured Linux checks and independent review.

### Task 2: Original first-key evidence

**Files:** .github/workflows/office-suite.yml.

- [x] Select existing ime-mode-diagnostic while preserving prefix and routing guards.
- [ ] Verify exact source and mode selection, then check active/remote state.
- [ ] Commit/push once and observe the existing standard Windows runner execution.
- [ ] Collect the terminal numeric callback/eligibility/resolution/retirement record.
- [ ] Fix only what new evidence establishes and return to paired normal acceptance.
