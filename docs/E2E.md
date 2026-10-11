# E2E and HWPX save coverage

This document describes configured coverage, not a claim that an unexecuted run passed. Consult the exact commit's Actions run and `results.json`/JUnit output.

## Release gates

The Windows release workflow uses standard public runners only. It first builds the production Windows x64 application, CLI, portable ZIP, unsigned MSIX, production frontend, and synthetic fixtures from pinned upstream sources. Three groups then run in parallel against those outputs:

| Gate | Environment | Configured checks |
|---|---|---|
| Native application | `windows-2025`, `windows-2022` | 16 editor UI tests plus 8 password-safety cases per OS using the production WebView2 application and real native file dialogs |
| Production browser frontend | Chromium, Firefox, WebKit on `ubuntu-24.04` | 10 UI tests per browser using genuine WASM export and browser downloads |
| Installation | `windows-2025` | Sign a copy with an ephemeral test certificate, prepare declared VCLibs framework dependencies, activate the installed app under its package identity, run its installed CLI, inspect associations and uninstall |
| WACK | Same signed candidate MSIX on `windows-2025`, after installed smoke and removal | Run the available Windows App Certification Kit and validate its actual XML result, identity, version and complete-run state; explicitly record unavailable kit |

The original 62 editor UI scenarios cover opening, committed Unicode input, HWPX edit/save/reopen, three successive round trips, undo/redo, zoom without source modification, missing fonts, explicit font help and no automatic font downloading. Native-only scenarios add HWP/HWPX Save As conversion, cancelled native dialogs, legacy HWP save, multiple windows and malformed-file error recovery. A separate standard-library ZIP/XML oracle checks serialized text and package invariants independently of rhwp. These are not pixel-perfect Hancom compatibility tests.

Eight additional password-safety cases per Windows image bring the editor UI total to 78. Source-bound WASM generates only task-authored encrypted HWP/HWPX documents; independent container/XML controls reject wrong or missing passwords and verify plaintext roundtrips before UI use. Real password retry/cancel and both Save As formats must preserve the protected-source checksum. Native dirty-document replacement and physical Alt+F4 requests verify cancellation, plaintext-consent cancellation, and a committed safety Save As followed by the original PID exiting normally before cleanup. Fresh native processes reopen and edit the plaintext outputs. The package source/run and its recorded rebuilt engine must match the current workflow; the original 16-case suite remains intact.


Native regression tests additionally exercise revision conflicts, external file changes, invalid or wrongly labelled bytes, failed atomic replacement, staging ownership, and dirty-state preservation. Frontend regression tests cover both serializers, cancellation, write failures, concurrent saves and edits during async writing/cleanup. The baseline RED probe deliberately demonstrates the original HWPX rejection, then restores the original test before feature patching.

## Reproduction

After a Windows development build:

```powershell
python -m pip install -r e2e/requirements.txt
python e2e/prepare_payload.py dist .work/e2e-runtime
$env:E2E_MODE='native'
$env:E2E_EXE=(Resolve-Path .work/e2e-runtime/OpenGeul.exe).Path
$env:E2E_FIXTURES=(Resolve-Path .work/e2e-fixtures).Path
$env:E2E_OUTPUT=Join-Path $pwd '.work/evidence'
python e2e/run.py
```

An installed WebView2 Runtime is required. `ensure-webview2.ps1` and `msix-install.ps1` deliberately refuse non-GitHub execution: they provision or temporarily modify a disposable test host, not an end user's system. Browser testing serves `.work/hop/apps/studio-host/dist` at loopback port 7700, sets `E2E_MODE=browser` and `E2E_BROWSER=chromium|firefox|webkit`, and installs the pinned Playwright browser first.

## Evidence and security

Bounded evidence is retained for one day: successful jobs keep up to 1 MiB of text/JSON/JUnit, and failed jobs keep up to 12 MiB including screenshots and safe action-only traces. Both native suites' outcomes and the password suite's source/runtime identity and small synthetic fixture metadata are prioritized before per-case diagnostics; failed-case diagnostics precede successful-case diagnostics. Omissions are recorded without changing test status. Document and font files are excluded. Browser profiles are outside the evidence directory. Trace network/DOM resource capture is disabled so installed font programs cannot be republished as trace resources. No production test API, private document, signing key, certificate or test-signed MSIX is shipped. The downloaded portable editor and CLI must exactly match the executables inside the verified MSIX.

A failure, skip, missing expected test, or installation failure blocks release. Tests are not automatically retried to conceal flaky results. PRs never publish releases. A weekly scheduled run tests only; main/tag/manual publication still requires every gate.

The installation artifact includes `installed-launch.json`, `installed-cli.json`, installed CLI help, registered framework provenance and `wack.json`. The CLI probe uses `Invoke-CommandInDesktopPackage` with `PreventBreakaway`, verifies its package identity and runs the installed CLI inside that package graph. An available kit runs `appcert reset` and `appcert test -appxpackagepath ... -reportoutputpath ...` against the exact hash-verified signed MSIX after installed-package removal, following [Microsoft's command-line instructions](https://learn.microsoft.com/en-us/windows/uwp/debug-test-perf/windows-app-certification-kit#validate-your-windows-app-using-the-windows-app-certification-kit-from-a-command-line). The gate requires a finalized, non-partial XML report for the candidate identity/version and an exit code of zero. Centennial identity comes from the embedded AppxPackage manifest and must agree with the program record and any nonblank report headers. Every required test must pass; required warnings or failures, missing or malformed XML, mismatched identity/version and a 15-minute timeout block the gate. Following [Microsoft's required versus optional Desktop Bridge tests](https://learn.microsoft.com/en-us/windows/uwp/debug-test-perf/windows-desktop-bridge-app-tests#required-versus-optional-tests), optional findings may yield `submissionCheckPassed=true` while `status=warning`, `passed=false`, the raw overall result and finding messages remain in the evidence. A complete WACK PASS still requires all tests to pass. The XML and logs use the existing bounded evidence artifact. If the kit is absent, `wack.json` reports `status=unavailable` and `passed=false`; installation may still pass, but WACK remains unverified. Consumer Windows 10/11 and Partner Center certification remain separate.

## Limits

GitHub Windows labels currently represent server runner images, not a full consumer Windows 10/11 device matrix. Native tests use Windows UI Automation and scoped WebView2 CDP. Elevated hosted runs may use temporary executable-specific registry overrides, restored during cleanup; they are restricted to disposable GitHub hosts. Browser tests explicitly disable the File System Access picker to test the real cross-browser download fallback; they do not validate native Windows dialogs. `insert_text` verifies committed Unicode, not a real user's Windows IME composition session. Real printers, accessibility hardware, encrypted documents beyond the synthetic supported-format cases, complicated business templates, all third-party font rights and Store certification require additional validation. HWPX support uses the pinned serializer; unsupported source features may not retain perfect fidelity. Keep original files when evaluating development builds.

References: GitHub Actions billing documentation and Playwright's official WebView2 testing guide.
