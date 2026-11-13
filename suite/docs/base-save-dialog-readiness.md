# Base Save As readiness evidence

This is an end-to-end harness correction. It changes no product dialog, Office
worker, input text, shortcut, save implementation, or document format policy.

## Original evidence and limits

Full Windows run `38980838708`, attempt 1, source
`9fbd4ba00c8c9eaf17764dc908187f44655ac112` passed the first 13-case GUI cohort.
Its second cohort failed `new-base` before filename input at the assertion for
one visible, enabled `Edit` with AutomationId `1001` and one `Button` with
AutomationId `1`. The failure screenshot shows a rendered Save As dialog, but
its raw result contains no contemporaneous UIA counts or tree. Missing,
disabled, duplicated, or unavailable provider results cannot be distinguished
retrospectively. This correction does not establish that a timing race caused
that failure, or establish a cause for earlier physical Writer input loss.

The product path is `OfficeDocumentForm.SaveDocumentAsync`: it creates the
WinForms `SaveFileDialog`, calls `ShowDialog(this)`, and sends the worker save
request only after OK. The Base database wizard is not involved in this path.
The prior harness waited for an owned native dialog HWND, then queried its
controls once. Native window existence and complete control readiness are
separate conditions.

The retained `pywinauto 0.6.9` wheel and matching source establish two error
conversion paths: `UIAElementInfo._get_elements` catches `COMError`/`ValueError`
and returns an empty list, and `elements_from_uia_array` skips a `COMError` for
an individual element. The replacement therefore calls the actual
`IUIAutomationElement.FindAll`, array `Length`/`GetElement`, and typed current
properties directly. Failed calls retain their operation, actual exception
type/message/arguments, and actual exception HRESULT if exposed. Successful
comtypes calls do not expose a raw success HRESULT; no synthetic S_OK is
recorded.

## Runtime boundary

`save_new_base` keeps its original physical File menu click and Ctrl+S, once
each. One absolute 20-second dialog deadline starts immediately afterward,
before window discovery. Window discovery, the single native focus action,
raw control observations, and final wrapper binding all consume that budget.
A maximum of 201 observations also bounds an unadvancing clock. Polling only
reads; it neither repeats input nor changes selection or layout.

The first matching dialog freezes its HWND and actual UIA root runtime ID.
Every observation retains the original Popen process poll and native document
and dialog identities, including HWND, PID, thread, root, class, owner, title,
visibility, and foreground. Document/dialog identity is checked before and
after each query. A missing initial window can be pending. A bound window
that disappears, changes, or has a foreign owner fails.

Each raw UIA query is rooted at that exact dialog and enumerates Edit and
Button types, with at most 512 returned elements. It retains raw array count,
all element indices, AutomationIds, control types, process IDs, native HWNDs,
runtime IDs, offscreen and enabled states, and exact candidate counts before
filtering visibility or enabled state. A partial failed query preserves the
properties read before the failure, labels candidate counts incomplete, and
cannot qualify readiness.

Only missing, hidden, or disabled exact controls can be pending. Duplicate
exact controls, provider/API/property errors, foreign processes, replaced
identities, and invalid native ancestry fail immediately. The filename and
Save controls require distinct live runtime IDs and actual bounded UIA
parent chains ending at the first Window element, which must be the exact
owned dialog. Every nonzero native ancestor HWND must also be live and owned
under that dialog. DirectUI controls with native HWND zero remain supported
through the actual UIA chain and `CompareElements`; no handle is invented.
The Microsoft SDK declares `UIA_HWND` as `void *` and the getter as an out
pointer. Actual run logs identify comtypes 1.4.17, whose generator maps that
type to ctypes `c_void_p`; a successful null out value is Python `None`.
`nativeHwndRaw` therefore preserves the actual integer or `None`, while
`nativeHwnd` maps only exact `None` to zero. Missing properties, exceptions,
booleans, strings, and floats are not converted to zero. Portable replay
requires consistent raw/canonical values in controls, roots, ancestry, and
wrappers. The official declaration is pinned at Microsoft/win32metadata
commit `9cf94833626504b330c2f616ce71a2d3497cdc76`,
`generation/WinSDK/RecompiledIdlHeaders/um/UIAutomationClient.h:668,1770-1772`.

Final pywinauto wrappers are constructed from the same returned raw elements.
Their raw properties and actual `CompareElements` result must still match the
selected snapshot. No fresh selector is used to replace a control. Filename
input starts only after this strict check. The existing physical filename
entry, exact Value-pattern readback, fresh-target guard, Save click, dialog
close, ODB MIME/Firebird validation, post-cleanup hash, and independent UNO
checks are unchanged.

## Portable replay

Successful `new-base` results now retain `baseSaveDialogReadiness`.

```python
require_base_save_dialog_readiness(
    case['baseSaveDialogReadiness'], case['shellPid'],
    case['windowHwnd'], 'OpenGeul Base — 다른 이름으로 저장')
```

This source API performs no Windows, UIA, filesystem, or input calls. It
recomputes readiness and candidate counts, validates raw native/UIA links,
requires one original deadline and ordered bounded observations, stops at the
first ready observation, checks one focus/original input sequence, and joins
the final wrappers to that snapshot. By default it also requires the actual
`filenameInputStartedAt` timestamp after readiness. Only the runtime's internal
pre-input gate passes `before_input=True` because no filename input has yet
occurred. Delivery replay must use the default four-argument call.

Failed cases keep raw observations and an explicit failure. A diagnostic
screenshot or a later ready control cannot turn the original failed case into
a pass. Offline boundary tests establish harness behavior, not corrected
Windows execution or overall Suite qualification.
