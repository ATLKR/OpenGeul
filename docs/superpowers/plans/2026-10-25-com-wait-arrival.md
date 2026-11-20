# During-wait arrival implementation plan

Spec: `docs/superpowers/specs/2026-10-25-com-wait-arrival.md`.

1. Write failing executable contracts for exact-owned callback posting,
   single-post/phase/deadline rules, receipt chronology, initially empty ordinary
   control, and producer-resource cleanup.
2. Implement the bounded rendezvous producer and receiver-post intervention in
   `suite/shell-tests/ComWaitDiagnostic.cs`; keep the existing command and gated
   workflow. Update standalone tests and stimulus documentation.
3. Independently review callback ABI, lifetime/quiescence and all existing
   budgets. Freeze and run local validation before one owner-branch push.
4. Inspect terminal native results and exact-source receipts. If delivery is
   again deferred, stop synthetic posted variants; do not rerun unchanged or
   claim the physical Office failure is fixed.

Status: implementation and independent review complete. Seven focused checks and full local validation passed: 2404 tests, 12 skips, zero failures/errors, 283.670 seconds. Native execution of this timing variant is pending. No production change.
