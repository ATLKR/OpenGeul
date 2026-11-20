# Reader Console Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Test the packaged reader console hypothesis once without changing behavior.
**Architecture:** Add an opt-in console-only entry point to the existing reader;
reuse its exact launcher and private Job. A separate controller verifies identities
and publishes only authorized numeric snapshots under one deadline.
**Tech Stack:** Python ctypes/Win32 and existing GitHub ARM64 runner.
**Spec:** docs/superpowers/specs/2026-10-25-reader-console-diagnostic.md

## Global Constraints

One launch/retirement,30-second execution including cleanup;5-second cleanup reserve.
No foreign console inspection, text, input, process attachment or security changes.
Exact source/owner-push/privacy admission; no acceptance or release qualification.

## Review Focus

- A foreign HWND must be rejected before visibility inspection.
- A helper or Job member generation mismatch must prevent attribution.
- Partial handshake, timeout and cleanup failure must remain failures.
- Artifact schema must reject extra fields and retain only authorized metadata.
- Mode wiring must leave ordinary acceptance prerequisites unchanged.

## Task1: Bounded console probe and controller

Files: suite/e2e/reader_console_diagnostic.py, writer_model_reader.py,
suite/tests/test_reader_console_diagnostic.py.
Interfaces: helper(directory), run(suite,output), validate_handshake(row),
observe_owned_console(api,row,members,clock,deadline).
- [ ] Write RED tests for strict numeric schema, foreign/generation rejection,
  original deadline, single launch/retirement and failure cleanup.
- [ ] Implement helper identity verification and controller using existing Job
  ownership and launch APIs; no product launcher change.
- [ ] Run focused tests and original reader regressions.

## Task2: Admitted one-run execution

Files: .github/workflows/office-suite.yml, workflow regression tests.
- [ ] Test reader-console mode ARM-only execution, all admission/privacy gates,
  no Korean readiness/engine fixtures and deliberate nonacceptance.
- [ ] Wire one probe and receipt-only upload; retain original modes' behavior.
- [ ] Independent review, frozen full suite and staged privacy scan, then one push.
- [ ] Inspect terminal run and exact artifacts; close hypothesis without rerun.
