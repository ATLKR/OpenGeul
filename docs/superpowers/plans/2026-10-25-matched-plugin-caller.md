# Matched plugin caller implementation plan

> **For agentic workers:** Use superpowers:executing-plans task by task, with independent review before native execution.

**Goal:** Identify the caller of the original failed mouse-up with the newly
qualified native plugin, without changing Office behavior or acceptance gates.

**Architecture:** Retain a verified plugin file lease before launching the owned
editor; correlate one appended file-origin sidecar with existing bounded stacks.
Use the existing owned Job helper to run file-only system DbgHelp outside hooks.

**Tech stack:** Existing Python/ctypes, Win32 C++, PowerShell and GitHub Actions.

**Spec:** ../specs/2026-10-25-matched-plugin-caller-design.md

## Global constraints

- Existing owner-push/attempt-1, privacy, readiness and ownership gates.
- Three fresh sequential cases; 16 frames and two up-stacks; original five seconds.
- Shared preparation 30 seconds; each offline operation 30 seconds, 27+3 split.
- No extra input, symbol network fallback, module enumeration/loading/ref changes.
- No GUI/acceptance claim from file identity or native symbol qualification.

## Review focus

- Directory/link changes and wrong file identity must prevent plugin attribution.
- Deadline expiry and partial sidecar publication must never create a complete row.
- Native symbol hangs must terminate only the originally owned Job and retain exit evidence.
- Wrong artifacts or native symbol format must stop before expensive editor work.
- Normal acceptance/default observer paths must make no extra plugin-binding calls.

## 1. Bind the known loaded plugin's file origin

Files: new suite/e2e/plugin_file_origin.py; ascii_message_protocol.py/.h,
ascii_message_observer.cpp, ascii_message_windows.py, ascii_message_preparation.py,
editor_capture_diagnostic.py, korean_ime_smoke.py; focused tests in suite/tests.

- [x] Write failing tests for prelaunch lease hash/RSDS/file-ID rejection, sharing,
  cleanup on launch failure, and retention through the existing cohort exit gate.
- [x] Implement PluginFileLease(path, proof, budget), private binding data and a
  path-free receipt. Share one original preparation budget with prepare_observer.
- [x] Add opt-in appended ABI header/sidecar, preserving existing event prefix.
  Test disabled zero-extra-API behavior, wrong path (no other-path open), wrong
  file ID/volume/size, changed module handle, late return and partial publication.
- [x] Pass the private lease explicitly through the focus case/probe/transport;
  never insert it into a serializable prepared-library or result dictionary.
- [x] Run focused native-ABI portable tests and request independent review.

## 2. Resolve symbols in an owned bounded child

Files: plugin_symbol_resolution.py; new suite/scripts/resolve-plugin-symbols.py;
focused tests in suite/tests/test_plugin_symbol_resolution.py and a wrapper test.

- [x] Test one fixed-name native qualification round trip and strict range/tag
  validation, with no arbitrary-name or enumeration interface.
- [x] Implement native fixed-name qualification using the existing verified pair
  session, retaining its exact local search/options/held-PDB/cleanup requirements.
- [x] Reuse ascii_message_preparation._Runtime/_run_stage for the parent watchdog;
  pass original parent monotonic start/deadlines to the child without renewal.
- [x] Test hung child, nonzero exit, surviving Job member, cleanup error, stale or
  oversized output, and unknown symbol. Emit only sanitized stage/identity facts.
- [x] Select at most the first eligible failed case, validate its original
  correlation and sidecar, and resolve at most 32 existing return RVAs minus four.
- [x] Run focused tests and independent review; no native execution yet.

## 3. Pin inputs and wire one diagnostic execution

Files: runtime.arm64.lock.json; new plugin-symbol artifact lock/fetch helper using
existing fetch-source-engine.ps1 transport primitives; office-suite.yml; tests.

- [x] Pin the independently verified engine and symbol artifacts from 40171709989,
  including the external source receipt hash and exact pair hashes/identity.
- [x] Test metadata/source mismatch, ZIP family/link/duplicate rejection and exact
  archive bytes. Reuse existing bounded no-auth redirect handling; never log URLs.
- [x] Wire symbol qualification before GUI readiness, then the existing focus
  cohort with optional binding, then offline resolution even on a focus failure.
  Keep explicit nonacceptance and prevent delivery from this diagnostic mode.
- [ ] Run the full frozen local suite, inspect the complete diff and independent
  review. Commit and push only the authorized Suite work branch once.
- [ ] Follow that exact native run through completion; verify artifact hashes,
  trace completeness/limits and caller evidence. Stop on the specified negative
  outcomes; do not invent a behavior patch from a green diagnostic step.
