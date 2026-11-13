# Owned Writer Observer Request Push Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Run the existing isolated ARM64 Writer diagnostic from an explicit
request-only push whose code and actual producer lock equal a reviewed parent.

**Architecture:** Keep the existing manual path. Add one exact dedicated-branch
push profile to the same job; admit its public event, raw Git graph and request
before any acquisition. Keep actual execution SHA T distinct from approved R.

**Tech Stack:** Existing Python 3.12, pinned GitHub Actions, PowerShell and Git.

**Spec:** `docs/superpowers/specs/2026-11-13-writer-observer-request-push-design.md`

## Global Constraints

- Dedicated branch only: `work/opengeul-office-native-writer-observer-suite-9dea`.
- Request schema exactly four keys; phase JSON integer `6..1200`, no default.
- Marker exactly `[opengeul-writer-observer-9dea-run]`; raw Git message is marker
  plus terminal LF, event message permits that single LF or none, extra body 0.
- Request blob cap 1024 bytes; read only admitted Git bytes before filesystem validation.
- One original 30-second static budget; runtime work/deadline remain 25/30 seconds.
- Existing manual inputs, normal jobs/locks, ABI 2/IPC 1, two-DLL proof and all
  false qualification flags remain intact.
- No request, placeholder 16-field lock, CI submission, main or Store action in
  this implementation task. Real R/T publication waits for producer evidence.
- Secret-free finite test environments; no raw event/message/environment output.

## Review Focus

- Shallow Git history or replacement refs must not hide extra parents or changes.
- Case aliases, symlinks and malformed request blobs must fail before unsafe reads.
- Payload omissions or a spoofed marker must not become execution authority.
- Phase output must not be emitted before source admission or allow shell content.
- An ordinary R push and the dedicated diagnostic must never qualify normal Suite.

## Task 1: Add and verify one owner request path

**Files:**

- Modify `.github/workflows/office-suite.yml`.
- Modify `suite/scripts/writer-server-observer-workflow.py`.
- Test `suite/tests/test_writer_server_observer_workflow.py`.

**Interfaces:**

- Preserve `require_context(values, event) -> bool` and
  `verify_source(root, head) -> int` for existing callers.
- Add `require_push_context(values, event) -> bool` for the closed push metadata.
- Add `verify_request_source(root, head, event) -> tuple[int, int]`, returning the
  tracked file count and explicit phase. Share a private source-admission routine
  with `verify_source`; it owns the one 30-second clock/Git reader. The manual
  wrapper still returns only the integer count.
- Add `phase_seconds(value: str) -> int` for the manual canonical decimal input
  and `write_phase_output(path, phase: int) -> None` for the one fixed step key.
  Emit only `phase_seconds=<canonical integer>` after context and complete source
  verification. Keep raw event/request data private and numeric artifact schemas
  closed; the approved parent remains independently auditable in T's Git request.

- [ ] Write failing request-context/graph tests with a local synthetic R/T Git
  repository. Assert valid request returns its phase and T provenance, while
  wrong owner/ref/attempt/head, force/create/delete, wrong before/after/list,
  merge, missing parent and replacement-object tricks reject.
- [ ] Run the new tests once against the current implementation; retain the
  actual failure count and public source location without exception arguments.
- [ ] Add bounded committed-blob parsing, exact raw-parent/message/tree checks and
  canonical path/mode checks inside the shared static deadline. Assert ordinary
  code/lock changes, old/case-alias request, duplicate keys, bool/string/float
  phase, out-of-range values and dirty source all reject.
- [ ] Add output tests: only admitted canonical phase is emitted; missing,
  aliased, dirty or unwritable output rejects. Existing manual valid/invalid
  cases and caller APIs remain covered.
- [ ] Add the exact dedicated branch and fixed message preselector to the same
  workflow job, checkout depth 2 and validated phase wiring. Do not use commit
  added/modified/removed fields. Normal job remains excluded on this ref.
- [ ] Test unmarked R skips ARM; spoofed marker still fails admission; both routes
  use validated phase; unchanged normal matrices/steps, action pins, uploads,
  closed numeric reports and intentional diagnostic failure remain exact.
- [ ] Preserve the historical workflow fixture and digest. In its test oracle,
  reverse only the one exact reviewed dedicated-branch addition; reject missing,
  duplicate and foreign edits. Production source readers get no normalization.
- [ ] Run the relevant workflow/source/fetch/stage/policy regression modules on
  the final bytes, plus syntax/static checks. Retain actual counts and skips.
- [ ] Independently review the final diff; apply only verified findings and rerun
  affected checks. Scan the added source/artifacts without printing secret values.
- [ ] Commit the reviewed implementation and docs on the existing dedicated
  branch. Preserve normal `work/opengeul-office-arm64` and its running CI.

## Deferred real execution

- [ ] After the actual producer completes, authenticate its original artifact,
  source receipt, two DLLs and all nonqualification fields; create the real
  16-field external lock only from observed values.
- [ ] Review the final R without a request file, publish R once and confirm its
  all-skipped run performed no diagnostic/acceptance work.
- [ ] Create T with only the strict request JSON and fixed message, recheck the
  exact parent/tree/source invariants, then publish T once after the same-ref run
  is terminal. Observe actual Windows context, baseline, runtime and retirement.
- [ ] Keep Linux tests, source qualification, diagnostic observations and normal
  product acceptance separate in the outcome report.
