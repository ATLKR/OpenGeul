# Free-only CI operating policy (2026-10-06)

## What is and is not free

GitHub documents standard GitHub-hosted runners in public repositories as free; larger runners are always charged. Splitting a paid job into steps does not make it free. This repository allows only `ubuntu-24.04`, `windows-2022`, and `windows-2025`, and places a public-repository predicate on every job before runner allocation. CI audits the explicit runner labels, static matrices, reviewed action commit pins, timeouts and one-day retention. Automatic Actions caches, custom images/snapshots, LFS and unreviewed service actions are not enabled.

The account's billing state and other repositories are not inferable from this workflow. This audit is an accidental-drift check, not a security boundary against a writer who can change the policy too. It cannot guarantee the owner's entire account costs zero or retroactively remove accrued storage. Artifact/Packages storage and cache allowances need separate consideration.

**Owner backstop:** in GitHub Billing and licensing > Budgets and alerts, create a repository-scoped Actions budget of **$0** and select **Stop usage when budget limit is reached** (not just email alerts). Check that the budget actually covers metered Actions storage; keep cache eviction limits at the included 10 GB, without opting into paid extra storage. This change does not read or change those account settings. A budget may block additional artifacts rather than permit an overage; do not work around that by enabling paid capacity.

Official references, checked 2026-10-06:
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/billing/how-tos/set-up-budgets
- https://docs.github.com/en/actions/reference/limits
- https://github.blog/changelog/2025-11-20-github-actions-cache-size-can-now-exceed-10-gb-per-repository/

## Stages

The Windows build workflow has explicit manual modes. `full` is the default. Pushes, tags, PRs and scheduled runs always use full mode; a PR cannot request a smaller gate through event inputs.

| Mode | Work performed | Publication |
| --- | --- | --- |
| `checks` | Public/free policy audit, CI regression tests, package/policy tests | Never |
| `engine` | Checks plus source-built WASM, frontend tests/build, all three browser E2E environments | Never |
| `full` | Engine checks, Windows build, both Windows native E2E environments, both virtual printers, MSIX installation | Only after every required gate succeeds and the existing trusted repository/ref/event rule allows it |

Preflight is a dependency of the engine. Windows compilation waits for preflight, WASM and browser E2E success, so a fast failed test does not launch the 120-minute-cap compilation job. This may add the short browser phase to a successful run's critical path; it is deliberately optimized for faster failure feedback and avoiding wasted rebuilds, not a promise that every green run is faster.

The engine and Windows payload are each built once per full run and shared with downstream jobs from **that same run**. Native fixture transport no longer contains another copy of the browser frontend. Native and virtual-print matrices each use at most two standard runners; all three browsers remain enabled. No old diagnostic binary substitutes for a final-candidate build.

PR updates cancel obsolete executions of the same PR. Main release runs keep the existing non-interrupting concurrency behavior, so publication is not cancelled halfway through an upload. Documents-only changes still avoid the heavy workflow. Logs and job summaries carry routine results rather than copying every successful screenshot.

## Storage bounds

Each evidence job stages its output separately: at most **1 MiB** on success or **12 MiB** on failure/cancellation, including its index. Root JSON/JUnit outcomes are retained first; failed-case evidence has priority. Oversized/unsupported files and all source documents, fonts and keys are excluded; omissions are recorded, not concealed. Failed test status is never changed by evidence packing. Failure traces are checked for fonts and expansion limits. Existing raw evidence is left in the runner's temporary workspace, not deleted from other runs.

Before transport upload, uncompressed-file totals must fit: rebuilt WASM 32 MiB, browser inputs 64 MiB, Windows package outputs 96 MiB, native fixtures 16 MiB. Exceeding the ceiling fails rather than silently uploading more. All uploads use compression level 9 and one-day retention. These are per-upload bounds, **not** an account-wide storage reservation; multiple runs and other repositories can share allowances. Only genuinely releasable binaries belong in GitHub Releases, not arbitrary cache files.

## Current verification boundary

The previous run `37421054207` built and passed all browsers and MSIX installation, but failed virtual printing and one Windows2025 native test. Those failures remain release blockers. The native failure trace reached `plugin:dialog|message` after an invalid document opened: an unbound class/PID selector then waited on the replacement TaskDialog. The concurrent commit `7bccfcc` already freezes the original file picker HWND and validates its action button; that implementation is preserved. This update applies exact-window binding to error-dialog dismissal as well. It still waits for closure and separately tests the expected error message; there is no retry or bypass.

Local verification uses a hash-verified earlier source snapshot for unchanged files plus these explicit changes: 36 new CI tests and four native selector tests pass, and that snapshot's existing 75 tests remain passing. This is not a claim that the newer branch's whole suite or physical printers passed locally. Fresh GitHub CI on the committed candidate is authoritative. No raster baseline or printing comparison threshold was changed.

Integration note: the branch advanced from `0999cf2` to `7bccfcc` while preparing these changes. The latter commit's native picker and print activation changes are retained, not overwritten. This CI update is applied on top of that newer head; its policy result does not establish a successful full printing run.
