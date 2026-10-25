# Writer navigation diagnostic implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

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
- [ ] Add Writer admission, real cleanup and success/failure phase regressions; run RED.
- [ ] Allow only Writer/Impress in existing CLI/case/diagnostic stop; keep normal close unchanged.
- [ ] Run focused regressions GREEN, including Impress and expired-deadline cases.

### Task2: Select one reviewed experiment
Files: .github/workflows/office-suite.yml and existing fixed-mode workflow tests.
- [ ] Change fixed mode to navigation-diagnostic and existing CLI target to writer;
      update exact target/mode contracts, retaining all prerequisite assertions.
- [ ] Run relevant workflow and full local tests; independently review final diff.
- [ ] Commit/push reviewed substantive change; monitor exact attempt1 to terminal.
- [ ] Preserve/hash-check evidence, classify using spec stop conditions. No unchanged rerun.
