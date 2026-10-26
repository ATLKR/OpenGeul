# Writer navigation diagnostic implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Test original Writer Ctrl+End delivery with the existing bounded tracer.
**Architecture:** Allow Writer in the existing navigation-only case and cleanup;
select it through the existing diagnostic workflow. Observer code stays unchanged.
**Tech Stack:** Python unittest, PowerShell, existing native Windows observer.
**Spec:** ../specs/2026-10-25-writer-navigation-diagnostic.md

## Global constraints
One original Ctrl+End, one fresh case per architecture; original60-second setup
and subordinate deadlines; unchanged privacy/ownership/first-attempt admission.
No console experiment, engine rebuild, additional input or acceptance weakening.

## Review focus
Writer action ordering; Impress compatibility; semantic failure trace retention;
normal unsaved-session rejection; no ASCII/IME/save after diagnostic PRE.

### Task1: Reuse existing case for Writer
Files: suite/e2e/korean_ime_smoke.py, suite/e2e/navigation_diagnostic.py;
tests suite/tests/test_navigation_diagnostic.py, test_ime_case_phases.py.
- [x] Add Writer admission, real cleanup and success/failure phase regressions; run RED.
- [x] Allow only Writer/Impress in existing CLI/case/diagnostic stop; keep normal close unchanged.
- [x] Run focused regressions GREEN, including Impress and expired-deadline cases.

### Task2: Select one reviewed experiment
Files: .github/workflows/office-suite.yml and existing fixed-mode workflow tests.
- [x] Change fixed mode to navigation-diagnostic and existing CLI target to writer;
      update exact target/mode contracts, retaining all prerequisite assertions.
- [x] Run relevant workflow and full local tests; independently review final diff.
- [x] Commit/push reviewed substantive change; monitor exact attempt1 to terminal.
- [x] Preserve/hash-check evidence, classify using spec stop conditions. No unchanged rerun.

Outcome: run40237954954/f3778a0 terminal. x64 complete queue-only trace and
semantic success; ARM64 failed engine prerequisites before navigation. No
unchanged rerun. Existing hooks cannot classify missing handler execution from
absent sent-message rows. See updated spec and external evidence ledger. A local
follow-up preserves generated prerequisite failure reports; it does not recover
this run's missing exceptions or change engine behavior.

### Follow-up: correct proven removal-flag blind spot
- [x] Execute the real HookGet plus navigation producer in a portable regression;
      reproduce missing flags3 row, retaining flags0/2 and forwarding checks.
- [x] Admit PM_REMOVE as a bitmask; update the existing capture integration test
      and correct the workflow's stale Impress display label to Writer.
- [x] Independent review and full local validation of the correction.
- [x] Finish current run40241619571 before considering corrected native execution.

Corrected run40244859920/353fe9b: both actual diagnostics passed; no causal
behavior fix established. Close experiment and restore existing full acceptance
mode with unchanged gates, reviewed separately and checked by workflow tests.
