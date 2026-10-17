# Writer observer Windows contract correction

This is an E2E-only correction based on Suite `9fbd4ba00c8c9eaf17764dc908187f44655ac112`.
Run `38980838708` rejected all six Writer cases during the first observer
constructor, before physical input. Its raw evidence does not retain the rejected
repr, so the failing prefix/length conjunct cannot be identified retrospectively.
The prior physical input-loss boundary remains unproven.

## Retained proxy identity

Pinned PyUNO uses one static extension `PyUNOType`, whose `tp_name` is `pyuno`.
`Runtime::any2PyObject` maps UNO interface values to `PyUNO_new`; that function
allocates this extension type. `PyUNO_cmp` compares wrapped UNO `Any` values.
`PyUNO_repr` instead calls `PyUNO_str`, whose `val2str` defaults to DEEP mode:
it adds the implementation name and all supported services/interfaces. There is
no 4,096-character identity contract for this diagnostic display.

The reader therefore retains the actual local component context and each
original frame/controller/model proxy. It checks `type(proxy) is type(local)`
and the source-defined type name, then records actual `id(proxy)` values scoped
to the owned helper generation. These are Python wrapper identities, not claims
of global native UNO identity. No display repr is required. Actual PyUNO equality,
unique native child-to-frame resolution, reciprocal controller/frame/model links,
exact document URL, original process generation and readonly full-body checks
remain mandatory. Before/after raw type/ID metadata and every cross-read identity
must agree. The seven actual packaged Python file roles are verified before
resolving the live document.

Constructor failures attach partial frame enumeration, actual type/ID metadata
and any completed UNO snapshot before releasing client references. The helper
retains those diagnostics even when construction never returns an assigned
reader. Cleanup without an established model binding can record successful
physical helper cleanup, while `contextQualified` and `cleanupSucceeded` stay
false. It cannot qualify an edit or mask the original error with a binding-None
exception. No document is loaded, written, dispatched, closed or re-opened.

## Console companion ownership

The pinned `program/python.exe` launcher creates the core interpreter with
`CREATE_UNICODE_ENVIRONMENT` and waits for its exit. It does not pass
`CREATE_NO_WINDOW` to that child. The unchanged owned-process wrapper already
uses suspended creation, Unicode environment and `CREATE_NO_WINDOW` for the
launcher. Actual failed-run jobs each retained a System32 `conhost.exe` companion.

Before launch, the E2E controller calls typed `GetSystemDirectoryW`, requires a
plain absolute local drive path, and opens exactly its `conhost.exe` with one
readonly native file HANDLE and share-READ only. It hashes that same bounded file
once and records actual native file ID, volume, creation/write times, size,
attributes, file type and final path. Each observation and cleanup rechecks the
same retained HANDLE. The initial `systemConsoleHost` witness remains immutable;
`systemConsoleHostRecheck` records current metadata separately. Last-access time
is retained as raw metadata and excluded from content identity.

Only at most one companion with that exact frozen system image may accompany
packaged Python members in the private helper JOB. Its retained process HANDLE,
PID/creation time, actual JOB membership, normal exit and HANDLE closure remain
required. Every unrelated image is rejected. The actual observer and release
acknowledgement must identify the packaged core Python process, never the console
companion. All JOB members must be signaled with exit zero, the JOB must be empty,
and the added OS-file HANDLE must have an actual successful CloseHandle result.
The product `worker/native_windows.py` is unchanged.

The original one twelve-second absolute budget includes witness acquisition,
startup, reads, unchanged physical input and final cleanup. Only the helper JOB
may be terminated on expiry. No extra input, input retry or timing extension is
introduced. A subsequent Windows run must establish corrected runtime behavior;
source and portable fake tests are not Windows execution evidence.

## Sequential process-state observations

Run `38985711992` reached exact first-marker full-body equality in all six Writer
cases, then failed reader cleanup. Five errors say `Reader is not alive`; one has
no message. All six release acknowledgements and their three native observer
HANDLE closures succeeded. The failing member rows were not retained, so their
PIDs and actual exit codes cannot be recovered from that run. These failures do
not establish the cause of the earlier physical input losses.

`WaitForSingleObject(handle, 0)` samples whether the retained process object is
signaled at that call. A subsequent `GetExitCodeProcess` samples its later exit
status. The process may terminate between them: `WAIT_TIMEOUT` (258), followed
by an exit code of zero, is a valid pair of sequential observations. It does not
prove that the first wait was signaled. The E2E reader now calls these existing
typed APIs directly, leaving the product worker implementation unchanged.

Only during the release RPC and subsequent cleanup may the pair `(258, 0)` remain
pending. Actual model reads still require the core interpreter's strict
`(258, 259)` live pair. Every retained launcher/core/console process must later
produce a fresh independent `(0, 0)` pair on its same original HANDLE, and the
private JOB must be empty. Once a process object is signaled on termination it
remains signaled; its following successful exit-code query supplies the terminal
code. A third wait does not turn an earlier timeout into a signaled observation.
Any other nonzero terminal code, failed API, foreign generation or failed closure
keeps cleanup failed. The existing `.01` polling and original absolute deadline
are unchanged. There is no extra input, delay, input retry or deadline reset.

Every individual sample is retained before validation, including partial API
failures and the first failure before forced helper-job cleanup. The receipt has
a `memberStateIdentities` table of actual PID, creation time, image, retained
process HANDLE and private JOB HANDLE. `memberStateSamples` references that table
by its zero-based `member` index, with an individual `index`, `phase`, start/end
`times`, and ordered raw `calls`. Call arrays contain:

- `['IsProcessInJob', timestamp, BOOL, inOwnedJob, LastError]`
- `['WaitForSingleObject', timestamp, DWORD, LastError]` (timeout is always zero)
- `['GetExitCodeProcess', timestamp, BOOL, exitCode, LastError]`

An unsuccessful exit query records `null` for its unavailable exit code. Partial
failure receipts omit calls that were never made. This is a compact encoding of
actual observations, not a synthesized success flag. At most 4,096 individual
samples are permitted; exceeding that count fails before the next native call.
The original two-MiB JSON transport bound remains enforced. A maximum-size
portable fixture fits that bound without dropping any samples. Final
`readerMembers` retain the detailed raw pair; portable replay resolves every
identity reference, validates call order/results/times, and joins each final row
to the last actual same-HANDLE sample. A retained process observed signaled may
never become unsignaled in a later sample. Unobserved or substituted identities
and impossible terminal-state reversals fail.

The release RPC also rechecks its exact expected reply file once if the launcher
exits after an earlier file-existence check. The helper can atomically publish
its acknowledgement between those two observations. The same bounded reader
and sequence/action/error checks apply; missing or invalid replies still fail.
This adds no request, wait or deadline. It is a separately reproduced source
race, not an inferred cause of the six historical cleanup failures.

Official Microsoft contracts used for this correction:

- [WaitForSingleObject](https://learn.microsoft.com/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject),
  pinned documentation commit `19f6baf0a22c2eace5b6b9b62f979c20aab84dac`,
  SHA-256 `29474b87ad9e518fbb7e7bc1d2169646f8f3b00c7e6d332f64309c16a8b038dd`.
- [GetExitCodeProcess](https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-getexitcodeprocess),
  commit `d43984d7c322f7d7d35704d6d1ad36dc3539703b`,
  SHA-256 `f5a7b618ecd47b63e3a8c785ab525e9724183abbea62ace2aac80cce2a38c7c0`.
- [Terminating a process](https://learn.microsoft.com/windows/win32/procthread/terminating-a-process),
  commit `3aee48ac3f48e187d17bdfd56951741737331749`,
  SHA-256 `4aec64a3904899803567b16004d171040ca7daefe9ef1bbb3c0097bdb6ba4d58`.

This source correction needs a new Windows run to establish actual behavior.
The failed run remains failed; no previous exit code is normalized to zero.

## Pinned source provenance

The Suite runtime lock selects LibreOffice `26.8.1.1`. Official annotated tag
`f3b61cf45f5198919f352f5163cd1dc2c000ba28` resolves to commit
`bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1`. Cached source bytes were matched against
that official tag's Git blob IDs and sizes. This checks source provenance; no
PGP signature verification claim is made.

| File | Immutable source | SHA-256 |
|---|---|---|
| pyuno.cxx | [source](https://raw.githubusercontent.com/LibreOffice/core/bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/pyuno/source/module/pyuno.cxx) | `853a85ec41619db8746dfbe5149def78b192a5f30d1c84201da66e1380f76fb2` |
| pyuno_runtime.cxx | [source](https://raw.githubusercontent.com/LibreOffice/core/bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/pyuno/source/module/pyuno_runtime.cxx) | `ab77b6b1e74850e98f49961206efcb15e5d6f6261ce1b56ae7a4ebca9f54a272` |
| pyuno_module.cxx | [source](https://raw.githubusercontent.com/LibreOffice/core/bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/pyuno/source/module/pyuno_module.cxx) | `1e9ec4d8aae82ac3b695d3cdb97a5e1dd76f000cfc3f7c089865cc876b13d9f5` |
| uno.py | [source](https://raw.githubusercontent.com/LibreOffice/core/bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/pyuno/source/module/uno.py) | `b3595c91a0660ad99e85f82504b9efe1092f2dd6fa9300e27d02180a42aa4183` |
| pyuno_impl.hxx | [source](https://raw.githubusercontent.com/LibreOffice/core/bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/pyuno/source/module/pyuno_impl.hxx) | `d19d6a2bdbaf4a454ae69b336c9ca4c78c0b2e9236626a0f865dc2802d99698a` |
| python.cxx | [source](https://raw.githubusercontent.com/LibreOffice/core/bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/pyuno/zipcore/python.cxx) | `94277db75a1af510e0b501f582154aeb90a281c360bd9c37ecc90b5ec50e5df4` |

The lock retains MSI SHA-256
`c6298b10cfa1748bcbedad94c62ce771e240e5021bfd6d7a967cd571b04b5312`
and source archive SHA-256
`296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785`.
See [Python id()](https://docs.python.org/3.13/library/functions.html#id),
[GetSystemDirectoryW](https://learn.microsoft.com/windows/win32/api/sysinfoapi/nf-sysinfoapi-getsystemdirectoryw),
[GetFileInformationByHandle](https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle)
and [process creation flags](https://learn.microsoft.com/windows/win32/procthread/process-creation-flags)
for the public API contracts. Existing upstream license and source notices remain
unchanged.
