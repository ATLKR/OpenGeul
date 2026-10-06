# Print E2E and tested-payload hardening

> For agentic workers: use superpowers:executing-plans and test-driven-development.

**Goal:** remove observed native-print automation blockers without weakening output checks, and prove the tested portable payload equals the released MSIX payload.
**Architecture:** keep the production application unchanged; exercise its real print UI with explicit native control readiness. Validate archive contents before extracting into an isolated runtime and require a completed owned spooler job.
**Tech stack:** Python, pywinauto, WebView2 accessibility, Win32 spooler, GitHub standard Windows runners.
**Spec:** docs/PRINTING_TESTS.md and the user's request to improve virtual-printer testing.

## Constraints
- Retain all 62 editor UI and 16 virtual-printer executions; no skips, silent retries or relaxed pixel references.
- Never print to hardware, change a default printer, ship fonts or disable runtime security.
- Diagnostic probes may reuse the explicitly recorded previous PR4 binary; final release gates use only their own run's payload.
- No unverified change is merged or described as a final printing pass.

## Review focus
- A visible preview does not mean its keyboard accelerator or accessibility tree is ready.
- Every MSIX runtime file, not only the two EXEs, must match the portable archive.
- Missing checksum entries, duplicate/case-aliased Windows paths and invalid ZIP data must fail before extraction.
- A queued or paused job is not completed printing; actual media and page counts must match.
- Failed or cancelled printing must preserve originals and clean up only owned resources.

## Tasks
- [x] Observe default/forced accessibility trees and the real system-print link on both Windows images; replace only the demonstrated unreliable input path.
- [x] Add failing archive parity/manifest/path safety tests; implement preflight verification and staged extraction; run the complete local policy suite.
- [x] Add failing spooler result tests; validate exact queue, completed status, media and page counts; verify old successful evidence still satisfies the stronger contract.
- [ ] Run native diagnostic checks, review diff, then update PR6 once with the verified fixes and keep the full fresh-candidate CI authoritative.

## Evidence
- Baseline adcf128 (a0f1366 plus diagnostic-only workflow): all 75 policy tests passed locally after every extracted Git blob matched its returned source tree SHA.
- Prior Win2025 run 37416925059 repeatedly reached a visible Print preview but never opened the system Print dialog. Its screenshot contains the system-print link; no #32770 dialog was created.
- Prior successful Win2022 run 37416539691 has Status=128 (PRINTED), A4 portrait and exact one/two-page spooler counts in all seven output scenarios.

- RED controls: previous payload preparation failed 17 of 21 real-archive cases; UI policy and spooler validators were missing; removing textual-status handling makes its dedicated negative control fail. GREEN: 121 policy tests and 23 independent PDF/raster tests.
- Complete real artifact preflight: 1,432 matching runtime files, editor SHA-256 375a067e7d0ecdbb16c8efbd16760335172849003b7584218adc00b668c818ce; runtime manifest 37c702879d315e8c9248e653ce88a236c30556d6c1c69442ae059d7f1baea48b.
- Review ruling: on-demand UIA already exposes the working system-print control on both images. Do not adopt the unnecessary force-accessibility experiment or any renderer-security flags.
- A full diagnostic printing run at 8f37bdf uses the prior PR4 binary to check the harness. Final PR6 release gates remain same-run and are not replaced by that diagnostic. No external/subagent code review is claimed; diff and negative controls were reviewed in-session.
