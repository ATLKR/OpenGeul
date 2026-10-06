# E2E and HWPX save coverage

This document describes configured coverage, not a claim that an unexecuted run passed. Consult the exact commit's Actions run and `results.json`/JUnit output.

## Release gates

The Windows release workflow uses standard public runners only. It first builds the production Windows x64 application, CLI, portable ZIP, unsigned MSIX, production frontend, and synthetic fixtures from pinned upstream sources. Three groups then run in parallel against those outputs:

| Gate | Environment | Configured checks |
|---|---|---|
| Native application | `windows-2025`, `windows-2022` | 14 UI tests per OS using the production WebView2 application and real native file dialogs |
| Production browser frontend | Chromium, Firefox, WebKit on `ubuntu-24.04` | 8 UI tests per browser using genuine WASM export and browser downloads |
| Installation | `windows-2025` | Sign a copy with an ephemeral test certificate, install, inspect identity/file associations, uninstall, preserve original unsigned package |

The 52 UI scenarios cover opening, committed Unicode input, HWPX edit/save/reopen, three successive round trips, undo/redo, zoom without source modification, missing fonts, explicit font help and no automatic font downloading. Native-only scenarios add HWP/HWPX Save As conversion, cancelled native dialogs, legacy HWP save, multiple windows and malformed-file error recovery. A separate standard-library ZIP/XML oracle checks serialized text and package invariants independently of rhwp. These are not pixel-perfect Hancom compatibility tests.

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

`results.json`, JUnit, synthetic document outputs, screenshots and action-only traces are retained for one day. Browser profiles are outside the evidence directory. Trace network/DOM resource capture is disabled so installed font programs cannot be republished as trace resources. No production test API, private document, signing key, certificate or test-signed MSIX is shipped. The downloaded portable editor and CLI must exactly match the executables inside the verified MSIX.

A failure, skip, missing expected test, or installation failure blocks release. Tests are not automatically retried to conceal flaky results. PRs never publish releases. A weekly scheduled run tests only; main/tag/manual publication still requires every gate.

## Limits

GitHub Windows labels currently represent server runner images, not a full consumer Windows 10/11 device matrix. Native tests use Windows UI Automation plus WebView2 CDP enabled by environment variables for that launched process only. Browser tests explicitly disable the File System Access picker to test the real cross-browser download fallback; they do not validate native Windows dialogs. `insert_text` verifies committed Unicode, not a real user's Windows IME composition session. Real printers, accessibility hardware, encrypted documents, complicated business templates, all third-party font rights and Store certification require additional validation. HWPX support uses the pinned serializer; unsupported source features may not retain perfect fidelity. Keep original files when evaluating development builds.

References: GitHub Actions billing documentation and Playwright's official WebView2 testing guide.
