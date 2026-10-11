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

Preflight gates the source-built WASM. After preflight and WASM succeed, `windows-editor` and `windows-cli` compile in parallel on separate standard `windows-2025` runners, alongside all three browser E2E jobs. The `build` job joins both validated components and packages the payload without recompiling either runtime. A browser failure can arrive after Windows compilation starts and still blocks publication through the unchanged final release gates. This schedule overlaps work; it does not promise a shorter successful run or lower account-wide cost.

The engine and Windows payload are each built once per full run and shared with downstream jobs from **that same run**. Native fixture transport no longer contains another copy of the browser frontend. Native and virtual-print matrices each use at most two standard runners; all three browsers remain enabled. No old diagnostic binary substitutes for a final-candidate build.

PR updates cancel obsolete executions of the same PR. Main release runs keep the existing non-interrupting concurrency behavior, so publication is not cancelled halfway through an upload. Documents-only changes still avoid the heavy workflow. Logs and job summaries carry routine results rather than copying every successful screenshot.

## Storage bounds

Each evidence job stages its output separately: at most **1 MiB** on success or **12 MiB** on failure/cancellation, including its index. Root JSON/JUnit outcomes are retained first; failed-case evidence has priority. Oversized/unsupported files and all source documents, fonts and keys are excluded; omissions are recorded, not concealed. Failed test status is never changed by evidence packing. Failure traces are checked for fonts and expansion limits. Existing raw evidence is left in the runner's temporary workspace, not deleted from other runs.

Before upload, each transport directory has a file-size ceiling: rebuilt WASM 32 MiB, browser inputs 64 MiB, editor component 64 MiB, CLI component 32 MiB, Windows package outputs 96 MiB and native fixtures 16 MiB. The protocol 2 CLI component stores the runtime as deterministic gzip, so its 32 MiB limit covers the compressed runtime and metadata; the restored raw CLI and joined logical payload each remain bounded to 96 MiB. The join verifies the complete single gzip member, CRC/end of stream, raw size, SHA256 and x64 PE header. Exceeding a ceiling fails rather than silently uploading more. All uploads use compression level 9 and one-day retention. These are per-upload bounds, **not** an account-wide storage reservation; multiple runs and other repositories can share allowances. Only genuinely releasable binaries belong in GitHub Releases, not arbitrary cache files.

Temporary transport cleanup is limited to the owned public repository's first-attempt run, a complete validated same-run artifact batch and successful required consumers. Failed runs retain their inputs, successful PRs retain their unpublished Windows package, and test evidence is never selected for cleanup. The cleanup verifies each selected artifact again before deletion and does not remove another run's artifacts or Release assets.

## Verification boundary

[Source run 64](https://github.com/ATLKR/OpenGeul/actions/runs/38167617349), attempt 1, completed successfully on `a51cb3547f9cbd8f090fb032f550810855feaed3`. All 14 required source jobs and transport cleanup succeeded. The [qualified development release](https://github.com/ATLKR/OpenGeul/releases/tag/v1.1.2-dev.64.1) contains the six verified original assets, with 1,562-file MSIX/portable runtime parity. Both Windows versions passed 16 original native cases and eight password cases, with 41 recorded native runtime sessions per OS; all three browsers and both virtual-printer matrices passed. The 13 required WACK tests passed with optional Blocked executables findings retained; this is not complete WACK PASS or Microsoft Store certification. No physical-printer qualification is claimed. The Windows producer-to-package interval was 39 minutes 53 seconds; the full workflow interval was 54 minutes 15 seconds. These are observations for this exact run, not an account-wide cost or future-duration guarantee.

### Historical context (2026-10-06)

The previous run `37421054207` built and passed all browsers and MSIX installation, but failed virtual printing and one Windows2025 native test. That earlier run was not release-qualified. The native failure trace reached `plugin:dialog|message` after an invalid document opened: an unbound class/PID selector then waited on the replacement TaskDialog. The concurrent commit `7bccfcc` already freezes the original file picker HWND and validates its action button; that implementation is preserved. This update applies exact-window binding to error-dialog dismissal as well. It still waits for closure and separately tests the expected error message; there is no retry or bypass.

Local verification uses a hash-verified earlier source snapshot for unchanged files plus these explicit changes: 36 new CI tests and four native selector tests pass, and that snapshot's existing 75 tests remain passing. This is not a claim that the newer branch's whole suite or physical printers passed locally. Fresh GitHub CI on the committed candidate is authoritative. No raster baseline or printing comparison threshold was changed.

Integration note: the branch advanced from `0999cf2` to `7bccfcc` while preparing these changes. The latter commit's native picker and print activation changes are retained, not overwritten. This CI update is applied on top of that newer head; its policy result does not establish a successful full printing run.
