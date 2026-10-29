# Writer Windows document accessibility exposure

## Scope and approach

Add one Writer-only check to the existing Korean UI OS collector. The current
VCL notebookbar role/parent/index/bounds/focus-restoration check remains intact.
This new check establishes only Windows exposure of the owned document role,
focused descendant and IA2 text interface. It does not certify Narrator/NVDA,
text correctness, reading order or general screen-reader compatibility.

Use LibreOffice's native MSAA/IAccessible2 path. Requiring UIA TextPattern would
impose a different provider contract. A separate executable or native bridge is
unnecessary: existing Windows ctypes and the existing comtypes dependency supply
the required ABI. No installation, registration, provider or engine change is
part of this work.

## Observation and lifetime

The original OS child first writes its unchanged UIA diagnostic snapshot. It
then flushes the fixed numeric `1` line, proving that the original snapshot's
file close succeeded, before checking the Writer probe in that same child and
same 45-second watchdog. Raw Windows timeout bytes may use CRLF for this line.
The probe result is one closed numeric JSON record of at most 4096 UTF-8 bytes on
stdout after that checkpoint. The parent discards stderr for this Writer path. No new artifact file is
created; the existing case JSON retains the validated numeric result.
Only the retained generation number and fixed Office executable path are added
to the original child's arguments. No stdin pipe is added: Windows CPython's
communicate writes stdin synchronously before its timed reader join, so deferring
that read until after a provider call could block the existing watchdog.

Retain the exact Office generation and verify PID, creation time, executable
image and native child HWND before and after observation. Check the retained
process and HWND before each COM query. Failed ownership refuses more queries.
Query OBJID_CLIENT on that exact HWND, call accFocus exactly once, then follow
at most 32 parent edges using canonical IUnknown identity. Require connection to
the original root and a DOCUMENT role (15). The focused object must report the
focused state. Query IServiceProvider, then QueryService with SID_IAccessible for
IAccessible2 and IAccessibleText support; do not call text methods.

Read only numeric role/state and VT_I4 or VT_DISPATCH focus payloads. Reject
other VARIANT types without decoding their payload. Never request Name, Value,
Description, text, caret offsets, selections or setters. Keep every acquired
COM reference separately even when addresses match. Clear each owned output
VARIANT once and release every owned interface once, including failure paths.
A cleanup failure prevents success and cannot replace the first probe failure.
The observer retains its owner before acquiring the process handle. Its one
cleanup block therefore records initialization and close failures separately.
Check the native CloseHandle result for this retained handle; an attempted close
alone does not qualify as a verified release. Attempt each owned handle once.
If the shared witness constructor raises before returning its handle, its
internal cleanup is unobserved here. Keep ownerReleased zero in that case and
do not invent a cleanup failure or a successful release.

Hold an unsuccessful probe result while running the original VCL collection and
tab validation. Only after those succeed enforce the Writer OS gate. A new probe
timeout may be held only when the original UIA snapshot was already completed;
an original OS collection failure retains its existing priority. Probe-only mode
does not claim acceptance. osScreenReaderExposureCertified remains false.

## ABI evidence

- Microsoft SDK [IAccessibleVtbl](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/oleacc.h#L659)
  defines IUnknown slots 0..2, parent 7, child 9, role 13, state 14 and focus 18.
  Child VARIANT arguments are passed by value; output VARIANTs are pointers.
- SDK [IServiceProvider](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/servprov.h#L141)
  appends QueryService at slot 3. Use HRESULT/LONG32 and STDMETHODCALLTYPE.
- LibreOffice 26.8.1.1 [QueryService](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/winaccessibility/source/UAccCOM/MAccessible.cxx#L961)
  accepts SID IID_IAccessible, while its [interface map](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/winaccessibility/source/UAccCOM/MAccessible.cxx#L2130)
  checks the actual UNO text-interface support.
- [Writer document](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/sw/source/core/access/accdoc.cxx#L58)
  uses DOCUMENT_TEXT, [mapped to MSAA DOCUMENT](https://github.com/LibreOffice/core/blob/libreoffice-26.8.1.1/winaccessibility/source/service/AccObject.cxx#L225).
- comtypes [VARIANT](https://github.com/enthought/comtypes/blob/1.4.13/comtypes/automation.py#L134)
  supplies the actual Windows layout. Clone its fields into a plain ctypes
  structure without its value conversion/destructor, verify 64-bit size and
  field offsets at runtime, and use raw HRESULT ctypes calls. High-level COM
  getters automatically convert output VARIANTs and therefore are unsuitable.

## Implementation plan and validation

Files: `suite/e2e/korean_ui_smoke.py`, new
`suite/e2e/writer_os_accessibility.py`, direct tests in
`suite/tests/test_writer_os_accessibility.py` and
`suite/tests/test_korean_ui_smoke.py`, and this document. No codec/workflow edits.

- [x] Write failing tests for closed results, owned focus/document ancestry,
  unsupported interfaces, cycles/depth, ownership failure and cleanup priority.
- [x] Implement the bounded observer and exact SDK raw ABI; test the actual
  ctypes calls using deterministic COM vtables and VARIANT sentinels.
- [x] Integrate the single existing OS child and deferred VCL-first enforcement;
  test timeout/protocol failures, unchanged other modules and one original call.
- [x] Run only related tests, obtain an independent narrow review and preserve
  frozen hashes plus a patch. Root performs integration and later Windows runs.

Linux fake-interface/ABI checks do not establish actual x64 or ARM64 COM calls.
Fresh actual Windows observation of the exact source remains required.

The related three Linux test modules pass 79 tests. Independent review found
two boundaries that were repaired and rechecked: an empty-lifetime forged
success, and Windows CRLF timeout checkpoints. A source-confirmed Windows
synchronous stdin-write risk was removed by using arguments instead. The final
integration review also found that the reused process witness did not check
CloseHandle's result. The observer now checks that result locally and keeps
initialization failures distinct from cleanup failures. It also refuses to claim
release of a handle that the shared constructor never exposed. These cases have
failing-before/passing-after checks. Existing COM apartment initialization and
uninitialization are left to the original UIA collector; the new probe owns no
CoInitializeEx call. These results qualify the observer implementation only.
