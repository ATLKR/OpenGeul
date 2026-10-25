# Owned IME Notification Caller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Identify the delivery caller of the first owned typed IME closure once.
**Architecture:** Reuse the existing hook, bounded stack classifier, held plugin
identity and isolated symbol worker. Append diagnostic-only evidence; preserve
the original acceptance paths and clocks.
**Tech Stack:** Python, native C++/Win32, GitHub Windows x64/ARM64 runners.
**Spec:** docs/superpowers/specs/2026-10-25-ime-notification-caller-design.md

## Global Constraints

- At most one record and sixteen fixed-whitelist frames.
- Original QPC, thirty-second preparation/analysis, ownership and admission gates.
- No input/mode retries, new rights, callback subscriptions or public release.
- Unknown frames redacted; matched plugin proof required for private RVAs.
- Diagnostic-only output never qualifies acceptance or graceful retirement.

## Review Focus

- Reentrant or foreign callbacks must not replace the first selected sample.
- Expiry between native calls must leave an unpublished inconclusive record.
- Module/file identity changes must suppress private attribution.
- Hook callback wParam must remain distinct from message payload wParam.
- Missing/failed cleanup or partial evidence must not become a caller claim.

### Task 1: Shared bounded native primitives

Files: ascii_message_observer.cpp, ascii_message_preparation.py, a focused shared
native header, and existing/native synthetic observer tests.

- [x] Add failing compiled tests for bounded module classification, raw-address
  redaction, changed plugin identity and clock expiry between calls.
- [x] Extract only the existing stack and plugin-origin primitives into a shared
  header with injected clock and immutable binding; preserve mouse contracts.
- [x] Run the existing retrieval/plugin-origin native regression tests unchanged
  in meaning, plus the new shared primitive tests.

### Task 2: First-close record and decode

Files: korean_ime_smoke.py, focused native/Python notification tests, and the
existing plugin-file preparation helper if shared preparation is necessary.

- [x] Add RED tests for command3 open baseline, first valid closure only,
  sent-by-current-thread Boolean, sequence/identity/deadline joins, partial and
  reentrant rejection, disabled mode and preserved ABI prefix.
- [x] Append a bounded opt-in record; retain the original preparation budget and
  held file lease. Decode only after validating all immutable and correlated data.
- [x] Verify no changes to input, restoration, deadlines, forced cleanup or normal
  acceptance. Run focused tests including real compiled callback seams.

### Task 3: Matched caller analysis and native execution

Files: matched_plugin_diagnostic.py, plugin_symbol_resolution.py, office-suite.yml,
and their existing tests plus focused notification-selection tests.

- [x] Test exact first-sample selection, closed symbol tags, changed identity,
  unresolved/capped/deferred results and same-source first-attempt admission.
- [x] Reuse exact symbol fetch/qualification for ARM64 mode diagnosis and the
  isolated resolver. Preserve all original privacy and deliberate nonacceptance
  gates. Do not require unrelated optional symbols for original qualification.
- [ ] Independent review, frozen full suite, staged value-free privacy scan and
  one substantive owner-branch push after checks pass.
- [ ] Inspect both terminal native jobs and verified artifacts. Apply the spec's
  stopping rule; no identical rerun. Keep final full paired acceptance pending.
