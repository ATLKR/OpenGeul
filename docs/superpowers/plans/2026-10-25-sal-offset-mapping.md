# SAL Offset Mapping Implementation Plan

> **For agentic workers:** Execute test-first within the authorized CI diagnosis; independent review before root push.

**Goal:** Resolve the observed sal3.dll return RVA against exact pinned bytes without another GUI experiment.

**Architecture:** A bounded static Python PE reader consumes the existing authenticated engine archive. The existing workflow gains a file-only nonacceptance mode with unchanged owner-push admission.

**Tech Stack:** Python standard library, PowerShell existing context guard, GitHub Actions existing native runners.

**Spec:** `docs/superpowers/specs/2026-10-25-sal-offset-mapping.md`

## Global constraints

One 30-second analysis deadline; 32 MiB SAL member; native ARM64 PE; exact archive SHA/size; no binary upload/download bypass, process execution or GUI interaction. Existing GUI and acceptance gates unchanged.

## Review focus

- Malformed/overlapping RVA ranges and excessive tables fail closed.
- Packed/unpacked unwind data must not turn an approximate export into an exact mapping.
- Wrong archive, duplicate/linked member, changed source or expired deadline is rejected.
- Retry/nonowner/event-source mismatch cannot fetch or analyze.
- Static-only mode cannot qualify delivery or weaken existing GUI modes.

## Task1: parser and receipt

Files: `suite/scripts/map-sal-offset.py`, reusable helper if needed, `suite/tests/test_sal_offset_mapping.py`.

- [x] Write failing synthetic PE/ZIP tests for exact exported range mapping and all malformed/boundary cases above.
- [x] Implement held-input authentication, bounded member reading and strict export/unwind mapping; return explicit inconclusive classification when exact attribution is unavailable.
- [x] Pass focused tests and independent review; preserve failure receipts without raw binary/path/credential dumps.

## Task2: workflow integration

Files: `.github/workflows/office-suite.yml`, focused workflow tests, `suite/README.md`.

- [x] Add regression checks for admission before fetch and unchanged existing mode gates.
- [x] Add static mode, reuse existing context guard and exact source checks, run parser only on ARM64, retain only bounded metadata, prohibit qualification.
- [x] Full local validation on frozen source and independent review: 2397 tests passed, 12 skipped, 269.691 seconds; 17 mapper and 35 workflow focused tests passed.
- [x] Run one first-attempt native static analysis and inspect its terminal receipt: run 40160669513 at 001cdd73e234000b94ea6320b54734ce440623a6 identified exact export `osl_waitCondition`, range [406400,406556), return RVA 406484. Both native unit suites passed 2397 tests (36 skips), shell 92/92; only the intentional nonacceptance guard failed. Receipt hash and archive provenance independently verified.
