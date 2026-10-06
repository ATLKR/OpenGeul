# Free CI transport lifecycle implementation plan

> Execute inline using superpowers:executing-plans and test-driven-development.

**Goal:** reduce temporary Actions storage while keeping every release gate and failure diagnostic.
**Architecture:** extend the existing checks/engine/full workflow. A final, standard-runner job validates all consumer results and removes only its own run's exact temporary transport artifacts. PR candidate binaries and evidence remain available; published release assets are never touched.
**Tech stack:** Python standard library, strict YAML policy, GitHub Actions REST API.
**Spec:** docs/FREE_CI.md and the user's request for free-only staged CI/CD.

## Constraints and review focus
- Only public ATLKR/OpenGeul, standard runners, no paid cache/custom image/LFS or billing changes.
- No cleanup before all mode-required consumers and any eligible publication succeed.
- Do not delete failed/cancelled runs, other runs, fork/Dependabot artifacts, unknown names, evidence or Releases.
- Artifact IDs must come from a complete same-run API listing and be revalidated before deletion.
- No account-wide zero-cost promise; owner-set $0 stop-usage budget is still required.
- Preserve unrelated concurrent changes and print pixel expectations. Changes apply to PR6 at its verified current head.

## Tasks
- [x] Reproduce audit accepting job-level continue-on-error; add a failing regression and reject it.
- [x] Test exact success/mode/ownership predicates and no-delete negative cases before implementing cleanup.
- [x] Add last-consumer cleanup job and engine-only upload suppression; retain all existing UI/print/MSIX release dependencies.
- [ ] Re-run focused local tests, review the exact diff, push with expected head, and inspect fresh GitHub checks.

## Source boundary
ci/policy.py and .github/workflows/msix.yml were materialized and their Git blob hashes match 134e7f5. Other local files originate from the hash-verified adcf128 snapshot; do not claim it is the complete latest repository. Latest full CI, not that older snapshot, is authoritative for full-suite results.
