# Mouse-up Retrieval Implementation Plan

> **For agentic workers:** Execute the authorized bounded diagnostic with test-first implementation and independent review. Do not push or run CI before root review.

**Goal:** Distinguish the observed ARM64 mouse-up retrieval path and coordinate-origin hypothesis.

**Architecture:** Append bounded retrieval records to the existing passive observer protocol, correlated to committed capture events. Decode them independently from acceptance or input admission.

**Tech Stack:** Native C++ Win32 observer, Python ctypes decoder and unittest fixtures.

**Spec:** `docs/superpowers/specs/2026-10-25-mouse-up-retrieval-design.md`

## Global constraints

Original deadlines, ownership, privacy, one-click/input and preparation gates remain unchanged. Three metadata records maximum; two stacks maximum; 16 frames per stack. No raw addresses or paths persisted.

## Review focus

- Expiry during a native call preserves incomplete status and prevents subsequent calls.
- Unknown or changing module mappings disclose no raw address.
- Duplicate retrievals cannot exceed per-event buckets or retry input.
- Malformed/partial records cannot become complete evidence.
- Native structure layout and existing protocol prefix remain consistent on x64 and ARM64.

## Task: correlated retrieval records

Files: `suite/e2e/ascii_message_protocol.h`, `ascii_message_protocol.py`, `ascii_message_observer.cpp`, `ascii_message_windows.py`, `editor_capture_diagnostic.py`, and focused tests under `suite/tests/`.

- [x] Add failing executable fixture and decoder tests for missing bounded retrieval records, including the five review conditions above.
- [x] Run focused tests and retain the expected missing-capability failure.
- [x] Implement fixed-size append-only records and minimal native sampling, with fixed module-ID mapping and unknown redaction.
- [x] Decode correlated records with strict types, identity/deadline/publication validation and explicit limitations.
- [x] Pass focused tests, independent review and the full local suite on frozen source.
- [ ] Commit/push the reviewed substantive diagnostic; inspect exact first-attempt native results before any behavior correction or subsequent execution.
