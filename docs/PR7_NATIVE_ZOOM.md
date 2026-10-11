# PR7 native desktop zoom verification — 2026-10-08

This supplements the initial HOP request inventory and its manual native-QA item.
It addresses only the document-load zoom portion of HOP #94, not every HOP request,
responsive toolbar layout or the reporter's macOS environment.

## Added release-gated scenarios

The existing native suite now also executes three cases on each Windows image:
actual WebView client widths 960, 1023 and 1025 CSS pixels. A Win32 move resizes the
owned Tauri HWND; measured `innerWidth` is authoritative. DPI/frame calibration is
bounded and cannot turn an unreachable width into a pass. No viewport emulation,
private app bridge, dispatcher injection or product API is used.

Each case selects 150% document zoom through the normal keyboard/status controls,
then uses the real file-open dialog to switch HWPX -> HWP -> HWPX without restarting
the application. It checks the same process/page/HWND, status-bar zoom, actual
rendered canvas dimensions and editing readiness. It edits, saves to a new HWPX,
switches away and reopens it in the same window, edits again and independently
checks both saved markers exactly once. Original HWP/HWPX hashes are checked even
on failure. Native dimensions, measured CSS geometry, checkpoint JSON and a final
viewport screenshot feed the existing bounded evidence mechanism.

Geometry allows only 0.5 CSS pixel of layout-rounding difference between measured
canvas sizes. This is not a print-output tolerance. All printer goldens and the
one separately reviewed digit-4 whole-page variant remain untouched.

## Required coverage cannot be replaced with duplicate cases

`e2e/suite_contract.py` enumerates the original ten browser methods, six additional
native methods and three new native zoom methods. The runner requires each exact
method once and passed; equal totals with a missing case, duplicate, unknown name,
failure or skip are rejected. JSON carries the required method list.

- Browsers: 10 x 3 = 30, unchanged.
- Windows native editor: 19 x 2 = 38 (the original 32 plus six zoom executions).
- Virtual printing: 8 x 2 = 16, unchanged.
- Total required UI executions: **84**, plus the unchanged build/engine and MSIX
  install/association/uninstall gates. Existing job dependencies, runner classes,
  permissions, cleanup, version and upstream pins are unchanged.

## Verification boundary

The three modified original Python files and unchanged test_editor.py were
materialized and matched their Git blob SHAs at PR7 head
`e6747dda48a6f530d8a1643c22ef4df52ac4b8e7`. The local workspace is a partial source
snapshot, not a full clone or Windows runner.

The initial 22 new helper/coverage tests failed when the implementation was absent.
Review added five controls; two exposed invalid-reference/unknown-width acceptance
and were observed failing before those guards were added. All **27** focused tests
then passed, as did Python compilation. Boundary doubles verify the native resize
and file-open dispatch logic; they do not constitute actual Windows execution.
The coverage check reads real test-method definitions from the existing sources.

Fresh GitHub policy and full candidate CI are authoritative. Native zoom success,
complete 84-case UI success, merge and publication must not be inferred from local
unit tests or the previous 78-case release. Keep PR7 draft until its actual native
and full gates pass and remaining review is complete. Review here is in-session,
not a separate reviewer sign-off. No release or Store/signing claim is made.
