# Native x64 Source Qualification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and independently consume a genuinely native x64 source engine while preserving ARM64 compatibility and all acceptance gates.

**Architecture:** One target-aware producer owns the build/proof lifecycle; fixed per-architecture workflows produce independently successful runs. Fixed authenticated policy selects target expectations, legacy ARM v1 stays exact, and new x64 uses explicit v2 proof.

**Tech Stack:** PowerShell, Python 3.12/unittest, GitHub Actions existing Windows runners, pinned LibreOffice C++/gbuild, MSVC and native Firebird/Base.

**Spec:** [2026-11-07-native-x64-source-qualification.md](../specs/2026-11-07-native-x64-source-qualification.md).

## Global Constraints

- Public `Architecture` is exactly `arm64|x64`, default `arm64`; no injected target maps or policy paths.
- Pinned core is `bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1`; ARM remains VS2026/v145 and strict v1; x64 is explicit VS2022/v143 and v2.
- One absolute 330-minute script budget, 360-minute job; preserve `$script:NativeEngineBuildBudget` scope.
- x64 CRT floor is the selected, bounded default-tools package metadata version, not a relabelled compiler servicing-resource maximum. Preserve resource/native witnesses; reread metadata at configure and final admission. Rank complete same-VS signed nine-file CRT sets by actual minimum file version, never the directory label. ARM v1 behavior remains unchanged; see the spec's explicit field and evidence contract.
- Runner choice follows the spec’s dated official inventory rationale. Actual filtered VS2022/v143 preflight remains authoritative; a zero/ambiguous match may collect one read-only unfiltered diagnostic (at most one minute within the original deadline), then fails without selecting from it, installing tools or switching profiles.
- x64 workflow/ref is `.github/workflows/office-native-engine-x64.yml` / `work/opengeul-office-native-engine-x64`, existing standard `windows-2022`; established ARM branch/workflow remain untouched initially.
- Never cancel/duplicate recorded runs `42304325191` and `42309580135`; check their actual state before any later submission. No new runner, permission, credential, SDK fallback, install, release or main merge.
- Preserve ARM `6714099caea00c800c900272574ae1c6b6144225` / `42203789086` input. Never copy the producer checkout's stale ARM lock to the main checkout; no fabricated successful x64 lock.
- Use synthetic environments and allowlisted non-secret observations only; never dump environment/process arguments or expose signed artifact URLs.

## Review Focus

- A valid-looking caller map or self-labelled receipt must not select policy (Tasks 1/4).
- A newly discovered hook or distro default must not silently enter the x64 build (Task 2).
- No-symbol Full, unrelated workflow failure or late helper import must not bypass trust/deadline gates (Tasks 1/3/4).
- ARM's allowed helper PE exceptions and old proofs must remain architecture-specific (Tasks 1/3/4).
- Native Full/WinAcc DLL presence must not be presented as actual Suite GUI success (Task 5).

Tasks 1–3 run in the existing producer checkout on
`work/opengeul-office-native-engine-x64`; keep the established ARM branch intact.
Task 4 runs in the newer Suite checkout on `work/opengeul-office-arm64`, including
its `test_portable_package_workflow.py`, which is absent from the old producer.
Commands use each checkout's existing Python 3.12 validation environment and
PowerShell. Portable passes are not Windows qualification. Record exact
interpreter, platform, counts and skips.
Each task ends in a focused reviewable commit only after its RED/GREEN evidence;
do not bulk-copy between checkouts. Dependencies are 1 → 2 → 3; Task 4 may run while Task 5 builds the reviewed producer. Task 5 input adoption and Suite execution require Task 4 completion.

---

### Task 1: Freeze ARM defaults and introduce authenticated finite target policy

**Files:** create `suite/engine-build/native-targets.json` and `suite/tests/test_native_engine_targets.py`; modify `suite/engine-build/source-build.json`, `suite/scripts/build-native-engine.ps1`, `suite/tests/test_native_engine_build.py`, `suite/tests/test_native_engine_prereqs.py`.

**Interfaces:** producer adds `[ValidateSet('arm64','x64')][string]$Architecture='arm64'`. Internal `Get-NativeEngineTarget(Architecture) -> private validated policy` reads the fixed tracked file and manifest digest. Target-sensitive helper boundaries accept finite architecture, never a public map/path.

- [ ] **RED:** freeze omitted/default/explicit ARM outputs and v145 recipe/config/diagnostic behavior. Add `test_target_policy_rejects_unknown_architecture_rows_hash_and_path_injection`, `test_no_symbol_full_requires_owner_first_push_attempt_and_source`, and `test_target_resolution_preserves_single_script_budget`. Assert x64 policy facts from the spec, exact fixed workflows/refs/artifacts, the official VS2022 redistribution URL, wrong native machine rejection, and no scope/reset side effect.
- [ ] Run `python -m unittest discover -s suite/tests -p 'test_native_engine_targets.py' -v`; expected new-contract failures. Preserve the old ARM baseline result before editing.
- [ ] **GREEN:** implement the finite option/resolver and unconditional normal-Full admission boundary, retaining the symbols-specific checks. Keep budget functions in the existing script scope. Do not generalize every ARM helper yet or execute a build.
- [ ] Run the target tests plus `python -m unittest discover -s suite/tests -p 'test_native_engine_build.py' -v` and `python -m unittest discover -s suite/tests -p 'test_native_engine_prereqs.py' -v`; expected all applicable tests pass with ARM snapshots unchanged.
- [ ] Review policy authentication, owner admission and budget ownership; commit `refactor: define authenticated native engine target policy`.

### Task 2: Make the complete source recipe explicit and fail closed

**Files:** create `suite/engine-build/apply_native_source.py` and `suite/tests/test_native_source_recipe.py`; modify `suite/engine-build/source-build.json`; narrowly reuse `enable_firebird_arm64.py` and `apply_winacc_focus_order.py` without changing established ARM outputs. Extend relevant existing `test_native_source_module_links.py`, `test_firebird_arm64_port.py` / `test_winacc_focus_order.py` fixtures when an extraction is necessary.

**Interfaces:** `apply_native_source(source_root: Path, evidence_directory: Path, *, architecture: str) -> dict` consumes Task 1's fixed recipe key and authenticated manifest. It returns exact applied-hook receipts; production callers cannot supply recipe contents or manifest paths.

- [ ] Consume the completed, source-policy-reviewed inventory: x64 selects exactly `moduleBootstrap`, `firebirdLoaderPath`, then `winAccFocusOrder`, with authenticated before/after bytes; reclassify only the source-proven Windows Firebird loader expression and exclude the twelve remaining ARM-only targets. Preserve ARM full-installer (bootstrap included) then WinAcc. This approval is source-only; actual x64 execution remains a separate gate. Future unknown hooks or membership drift prevent recipe success and any long build.
- [ ] **RED:** add `test_arm_recipe_outputs_match_frozen_manifest`, `test_arm_full_installer_then_winacc_without_duplicate_bootstrap`, `test_x64_recipe_applies_exactly_bootstrap_loader_then_winacc`, `test_x64_leaves_all_12_arm_only_targets_unchanged`, `test_windows_loader_paths_survive_both_make_levels_for_each_owned_recipe`, `test_unknown_missing_duplicate_reordered_or_modified_hook_fails`. Use pinned source fixtures and exact WinAcc original/candidate behavioral witnesses.
- [ ] Run `python -m unittest discover -s suite/tests -p 'test_native_source_recipe.py' -v`; expected failures before the dispatcher exists.
- [ ] **GREEN:** implement the exact finite recipe dispatcher: x64 bootstrap then its exact Windows loader-path hook then WinAcc; ARM full existing installer then WinAcc, without a separate bootstrap call. Reuse narrowly tested existing hook functions and require all relevant hashes/outputs; never route x64 through ARM install-all or broaden ARM guards.
- [ ] Run recipe tests, `python -m unittest discover -s suite/tests -p 'test_native_source_module_links.py' -v`, `python -m unittest discover -s suite/tests -p 'test_firebird_arm64_port.py' -v`, and `python -m unittest discover -s suite/tests -p 'test_winacc_focus_order.py' -v`; expected exact recipe/behavior passes. Review complete recipe and commit `feat: authenticate native engine source recipes`.

### Task 3: Complete the shared producer and independent fixed x64 workflow

**Files:** modify `suite/scripts/build-native-engine.ps1`, `suite/tests/test_native_engine_build.py`, `suite/tests/test_native_engine_prereqs.py`, `suite/tests/test_native_engine_archive.py`, `suite/tests/test_native_engine_oem_policy.py`; create `.github/workflows/office-native-engine-x64.yml` and `suite/tests/test_native_source_workflows.py`. Reuse existing `Get-CrtNames`, its conformance to `suite/crt.py`, and `stage_installed_runtime.py`; do not duplicate CRT lists. Leave the ARM workflow/ref unchanged in this stage.

**Interfaces:** `Invoke-NativeEngineBuild(...existing..., Architecture='arm64')` owns one lifecycle and invokes Task 2 before configure. Target-sensitive host/config/JDK/librarian/CRT/product/Base helpers accept explicit architecture. x64 emits normal v2 proof and `OpenGeul-Office-engine-x64.zip`; ARM retains its v1 required contract. New x64 job name is `native-firebird-and-office-x64`.

- [ ] **RED:** add native x64 host/controller/cl/link/lib/JDK/CRT/SDK rejection tests; `test_x64_configuration_requires_archive_and_oem_exclusions` and exact generated x64 configure/build-type/OEM tests; wrong PE/helper-role, missing WinAcc/hash/import, no native Base independent-reopen/row/retirement, and diagnostic-as-normal rejection tests. Bind `Save-VcRedistributionTerms` URL/snapshot/hash to the selected VS profile; require matching bounded default-tools metadata and its unchanged hash, reject missing nine-file x64 signed CRT or actual DLL versions below the configured package floor, and preserve ARM terms. Cover distinct package/resource/DLL versions, old-folder/new-DLL admission, new-folder/old-DLL rejection and eligible signature/PE failures without fallback. Assert no successful proof/archive on any failure and no toolchain/SDK/runtime-installer fallback.
- [ ] **RED:** add `test_fixed_x64_workflow_branch_runner_job_and_artifact`, `test_architecture_runs_do_not_cancel_or_trigger_each_other`, `test_shared_dependencies_are_in_validation_inventory`, and `test_whole_run_success_is_not_replaced_by_matrix_row_success`. Verify fixed permissions, owner gate without symbols, 330/360 budget and exact two archive members.
- [ ] Run `python -m unittest discover -s suite/tests -p 'test_native_source_workflows.py' -v` plus the changed producer test modules; expected new-contract failures.
- [ ] **GREEN:** thread finite architecture through the existing lifecycle, preserving script scope and ARM output semantics. Bind all actual x64 compiler/source/config/PE/CRT/WinAcc/Base/run facts in v2; qualification flags are computed only at final success. Add fixed x64 workflow with existing runner/tools and first-step deadline. Do not launch it yet.
- [ ] Run all four changed existing producer test modules, new workflow tests, then `python -m unittest discover -s suite/tests -v`. Review negative proof cases, source binding, trigger/concurrency inventory and ARM compatibility; commit `feat: add fixed native x64 source producer`.

### Task 4: Consume x64 v2 without weakening ARM v1 or changing input locks

**Files:** in the newer Suite checkout, modify `suite/scripts/fetch-source-engine.ps1`, `suite/prepare.py`, `suite/package.py`, `suite/payload.py`, `.github/workflows/office-suite.yml`, `suite/tests/test_fetch_source_engine.py`, `suite/tests/test_prepare.py`, `suite/tests/test_package.py`, `suite/tests/test_payload.py`, `suite/tests/test_portable_package_workflow.py`. Selectively integrate reviewed target policy/source metadata and implement consumer support against these newer files. Never wholesale-copy old producer consumer files or its ARM lock. All runtime locks remain untouched.

**Interfaces:** use the three Python signatures in the spec. Fetch selects the fixed workflow/ref/job/artifact/inner ZIP from committed expected architecture and validates whole-run success, attempt/source joins and external hashes. Suite acquisition selects validated `runtime.format`, never architecture alone; once source is selected there is no MSI recovery path.

- [ ] **RED:** preserve all legacy ARM v1 positive/negative fixtures. Add x64 v2 success fixtures and one-field mutations for cross-architecture relabelling, untrusted workflow/ref/job/owner/attempt/source, failed whole run with successful job, stale/missing hashes, WinAcc/source-recipe omission, CRT mismatch, archive aliases/extra members/reparse paths and source-fetch failure followed by MSI. Verify package/final-payload replay independently rejects swapped expected architecture.
- [ ] Run the five listed consumer test modules individually; expected new x64 fixture failures while ARM baseline remains green. Synthetic fixtures are labelled unit fixtures and never copied into runtime locks.
- [ ] **GREEN:** add explicit x64 v2 branch, propagate expected architecture to runtime replay, read fixed tracked policy, and wire format-based acquisition. Preserve bounded/cancellable fetch, no-overwrite paths and separation of authenticated API requests from uncredentialed signed downloads.
- [ ] Run the five changed consumer test modules, then `python -m unittest discover -s suite/tests -v` in the newer Suite checkout. Run any shared-policy regression in its owning producer checkout separately; do not run Suite-only tests from the old producer. Diff-review runtime locks byte-for-byte unchanged and confirm no secret-bearing output or generated qualified input; commit `feat: validate native x64 source inputs`.

### Task 5: Qualify real independent outputs and adopt only proven inputs

**Files:** operational evidence plus, only after qualification, the existing x64 `suite/config/runtime.lock.json` and later `suite/config/runtime.arm64.lock.json` in the Suite checkout as separate reviewed changes; relevant producer/consumer tests receive regression fixtures only for newly observed defects. No successful lock is a setup step.

**Interfaces:** each actual run consumes a reviewed committed producer head and fixed workflow/ref. Adoption consumes authenticated complete successful-run metadata, exact outer/inner ZIP and receipt hashes, actual v2 proof and native runtime replay. Source proof always records `guiVerified=false`; separately retained Suite evidence owns GUI qualification.

- [ ] **RED/pre-submit:** check existing runs and exact heads once; attach any newly observed defect to a failing focused contract test before correcting it. Confirm completed recipe inventory, native-preflight-before-download order, no active duplicate and no secret-bearing new diff/artifacts.
- [ ] After Task 3 review, while Task 4 consumer work proceeds independently, review/push the producer-only implementation on `work/opengeul-office-native-engine-x64`; use only its fixed existing standard `windows-2022` workflow. Capture native preflight and, if successful, the same-budget x64 Full/native Base/retirement result. Missing tools or time exhaustion is a failed/unqualified run, not authority to install, extend time or weaken proof.
- [ ] Verify completed/success whole-run metadata and all bytes/provenance independently; only then review the real x64 lock change. Run exact fixture/replay tests from Task 4 before committing that pin. Keep old ARM input unchanged.
- [ ] Run the standard actual x64 Suite on that exact input/head: native menu actions and Escape/outside-click, repeats/transitions, preview/fullscreen return, save/cancel/close/focus, accessibility, Korean input/save/reopen, lifetime and applicable package/install/update/repair gates. Preserve raw evidence/screenshots/process retirement and separate every skipped/failed gate. Fix failures through focused RED/GREEN regressions and evidence-based reruns; no RC claim until required gates pass.
- [ ] After a separate review permits promotion of the shared driver to the established ARM producer branch, run a distinct actual ARM Full, then verify its real output and ARM Suite before any new ARM adoption. Never cite the original 2921 run as validation of the refactor. Review final exact input/head/gate inventory; commit only genuine adopted pins, with release/deployment still excluded.

## Plan self-check

All spec boundaries have an owner: fixed policy/admission/defaults (1), complete
authenticated recipe (2), one timed native lifecycle and independent workflow
(3), strict per-architecture consumption and payload replay (4), actual builds,
independent adoption and GUI acceptance (5). The reviewed x64 recipe is exactly
bootstrap, exact x64 loader-path correction, then WinAcc; actual native recipe execution and toolchain/time
feasibility remain qualification gates, not assertions of success. No
implementation, test, CI or lock change occurred in this design pass.
