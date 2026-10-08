# CI transport retention and cost boundaries — 2026-10-06

This extends the existing public-only checks / engine / full workflow. All 62 editor UI executions, 16 virtual-printer scenarios and MSIX installation gates remain in full mode. No printer output reference, comparison threshold or application source changes here.

## Stage and retention behavior

- `checks`: policy/unit checks only, no transport uploads or cleanup job.
- `engine`: source-built WASM plus all browser E2E jobs. The engine stays in the build workspace instead of uploading an unused WASM transport. When consumers succeed, only that run's browser-input transport is removed.
- `full`: build one engine and one Windows payload, then test them on all existing environments. After every required consumer succeeds, remove only that run's named WASM, browser-input and native-fixture transports. On a successful publication, also remove the Actions copy of the package; GitHub Release assets are untouched.
- Successful PRs and scheduled/unpublished full builds keep the MSIX/portable candidate artifact for its original one-day retention. All test evidence retains its existing bounded one-day policy.
- Failure, cancellation, a skipped required test or incomplete status prevents deletion. Forks, Dependabot runs and re-run attempts do not receive cleanup authority. They fall back to one-day expiry.

## Safety of cleanup

The final job depends on preflight, WASM, browsers, Windows build, both native and printer matrices, MSIX install and release. Its own `actions: write` permission is not granted to tests or builds. It uses the normal temporary GitHub token, not an additional secret. It reads only the current workflow run's artifacts, validates repository, source SHA, workflow path and run attempt, then validates the entire selected batch again before the first deletion. An incomplete listing, missing expected artifact, duplicate name/ID, oversized input or changed metadata fails closed. API failures are reported; failed DELETE requests are not retried. A mid-cleanup API failure can leave a partly cleaned run, whose successful removals are logged.

Only three exact transport names (plus the package after successful release) are candidates. Other runs, unknown artifact names, diagnostics, source files, caches, Releases and billing settings are not cleanup targets. The code has no repository-wide purge route. No artifact has been deleted directly from this development session.

Deletion means that re-running only downstream jobs after a successful first attempt may lack deleted intermediate inputs. Use a full new run when those inputs are needed; the code does not fetch an older artifact to mask this. Failed first attempts retain their inputs specifically for debugging/retry. As with any artifact cleanup, no account-wide storage reservation is implied.

## Free usage boundary

Standard GitHub-hosted runners on public repositories are free; splitting a paid runner into smaller steps would not make it free. This repository retains the static ubuntu-24.04 / windows-2022 / windows-2025 allowlist, and does not enable larger/self-hosted runners, paid caches, custom images or LFS. The workflow policy now also rejects job-level `continue-on-error`, not only step-level suppression.

Artifact storage accrues by retained size and time. Removing successfully consumed transport early reduces future accumulation, not charges already accrued. Logs and step summaries are used for the cleanup report instead of another artifact upload. The $0 Actions budget with **Stop usage when budget limit is reached**, scoped appropriately by the repository owner, remains the required billing backstop. Budget settings and actual billed usage were not read or changed here.

Official references checked 2026-10-06:
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/billing/how-tos/set-up-budgets
- https://docs.github.com/en/rest/actions/artifacts?apiVersion=2022-11-28

## Verification at implementation time

The starting `ci/policy.py` and Windows workflow were materialized and matched their Git blob hashes at source commit 134e7f55a36855e3227b8c0195c62e5d40fa32da. An older source artifact was only a local working scaffold, not claimed to be the complete current tree.

- New job-level suppression tests: three failed on the old policy, then passed with the guard.
- New cleanup module tests: all 27 failed while implementation was missing, then passed; synthetic REST boundaries prove zero deletes for failures, wrong owners, changed metadata and incomplete lists.
- New workflow tests: three failed before wiring, then passed. The original six release prerequisites and all existing matrix members are unchanged.
- All **39 new local tests** pass; Python syntax and the modified workflow's public/standard-runner audit pass.
- No live deletion, final Windows printing pass, complete candidate build, merge or release is inferred from these local tests. Fresh GitHub policy/full workflow results on the committed candidate remain separate evidence.

Review was performed in-session with explicit negative controls; no independent/subagent review is claimed. The pending virtual-printer failures are not removed or reclassified by this CI-only change.
