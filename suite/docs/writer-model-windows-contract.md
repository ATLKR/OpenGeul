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
