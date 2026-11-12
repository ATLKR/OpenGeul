# Packaged Context Observer Implementation Plan

> For agentic workers: implement only the assigned scratch files with TDD and retain independent review.

Goal: Produce read-only collector source plus strict unqualified observation/bundle validation, without a live launcher or servicing.
Architecture: Portable C++ policy with injected OS boundary; Windows SDK-only port; separate Python schema validator.
Tech Stack: C++17, Win32/C++WinRT headers already supplied by a future standard runner, Python standard library.
Spec: DESIGN.md and SCHEMA.md in this directory.

## Global Constraints

No Main/native/pure40 changes; no new dependencies/SDK install/auth/CI/OS action/Store. Observer <=10s within original <=90s phase deadline; synchronous hard wall bound remains unproven without an external watchdog. No file/profile writes, marker, creation, enumeration, WMI, UI or servicing. No original-helper HANDLE claim or fabricated path-less identity. Whole production bundle needs an independently supplied SHA.

## Review Focus

- Cmdlet identity alone is not real product token/UDF/launcher ownership.
- Three existing roots require real paths and distinct native FileIDs, not JSON labels.
- Missing/aliased/reparse/changed paths stop, and cleanup closes only retained handles.
- Source-only recipe/bundle pins never qualify an installed package.
- Budget checks do not prove a synchronous WinRT call cannot hang.

## Task1: Strict observation metadata and complete bundle

Files: observation_contract.py, tests/test_observation_contract.py (assigned separate worker).
- [ ] Write exact-schema/unknown-field/type/path/FileID/budget/source-binding/false-authority/bundle-counterexample tests; run numeric RED.
- [ ] Implement independent expected request, validation and source bundle integrity; return metadata-only witness whose phase conversion always rejects.
- [ ] Run all direct tests with literal synthetic environment; retain numeric GREEN and freeze.

## Task2: Portable collector and typed Windows port

Files: context_observer.hpp, context_observer_windows.cpp, tests/core_tests.cpp, tests/test_portable_core.py.
- [ ] Write real compiled C++ policy tests for good observations and missing root/reparse/alias/wrong context/identity swap/deadline/cleanup failures; record RED without printing compiler stderr.
- [ ] Implement core whose operations are strictly read-only, source-bound, three-handle-retained and fail-closed; execute the compiled tests.
- [ ] Implement Windows port using exact typed supported APIs and add source guard tests. Native compile/run remains explicitly unverified, no implicit cross-compiler install.

## Task3: Freeze and independent review

Files: run_checks.py, bundle-manifest.json, final-manifest.json, numeric receipts; code source hashes are complete and source-only.
- [ ] Run all new portable tests once on final source, AST/static/privacy checks and original pure40 file-hash preservation (do not rerun its tests).
- [ ] Reuse an existing reviewer; fix material findings without changing scope.
- [ ] Deliver exact files/hashes/test counts and remaining launcher/Windows/qualified-input blockers. No checkout apply or Git/CI action.
