# Bounded call-family discriminator

1. Add failing parser and native lifecycle contracts for exact-range completeness,
   known fixture call, sanitized output, clobbers and the original deadline.
2. Implement a pure classifier and compile-only fixture export; integrate the
   existing native tool in an owned temporary scope without executing either DLL.
3. Enable only the explicit static workflow flag, retaining admission, receipt-only
   upload and intentional nonacceptance. Independently review and validate locally.
4. Run one first-attempt static CI query and inspect exact-source receipts through
   completion. Do not broaden ranges or repeat an unknown result automatically.

Status: implementation and independent review complete. Full local suite passed 2471 tests, 12 skips, zero failures/errors, 298.691 seconds. Native inspection remains pending. No product fix.

Native prerequisite failure: run 40169065518 at d8c504fd ended before the query.
Both native unit suites rejected stable Windows path/held-file `ctime`
differences in the new reader. CPython 3.12 uses birth time for path `stat` and
change time for held-file `fstat`. This is an observation implementation defect,
not a result of the call-family experiment or an Office behavior correction.

Repair: compare all five metadata fields within each API, retain cross-API
volume/file identity and size equality, exact bytes and original deadline.
A synthetic stable-ctime-difference regression failed before the repair; changed
held metadata, changed path metadata and cross-API identity/size mismatch remain
rejected. Independent review passed 47 focused checks. The one native query is
still pending; its stopping rule is unchanged.

Reader repair full local validation: 2474 tests, zero failures/errors, 12 skips,
294.862 seconds. Reviewed implementation/test hashes unchanged. Native validation
remains required.
