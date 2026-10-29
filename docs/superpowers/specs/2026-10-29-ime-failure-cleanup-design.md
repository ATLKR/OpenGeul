# IME failure cleanup and original layout evidence

The original failed composition must remain the primary failure. A final event
snapshot is diagnostic collection; its failure must not skip the existing one
owned-thread restoration command. Separate those two existing cleanup operations
into independent try blocks, preserve their errors separately, and keep observer,
keyboard and retained-process cleanup in their existing order. Do not retry a
failed restoration or restore an unrelated/controller/global input state.

The paired acceptance evidence also contains exact-US layout guard failures.
It does not identify whether the original target or controller layout differed.
Record only values already returned by that failed guard, immediately before its
original assertion. Add no query, layout activation, input, focus change or time
budget. Optional evidence failure must leave the assertion and primary error.

Use a closed seven-integer vector: origin (1 IME, 2 scenario), keyboard slot
(1 primary, 2 scenario focus/host), retained engine PID, creation time, child HWND,
observed target HKL, observed controller HKL. The first five are positive bounded
integers (origin/slot enums, PID u32, generation/HWND u64); HKLs are u64 including
zero, which means only the API's observed value. At least one HKL differs from
0x04090409. IME permits only slot 1. No key/input text, path, error message or
document content is included.

The collector binds the original case record to its current retained session
binding; it never discovers another process. Kind 1 schema 10 independently
validates scope/case/module, original assertion source and owned frames, and
matching PID/generation/child observations. Keep schema 1 through 9 meanings and
the 2048-byte limit. A rejected optional projection falls back to the original
notice. This does not establish that a previous restoration failed or caused a
later guard failure; it only locates the observed mismatch.

The chosen approach separates existing cleanup and projects existing guard
values. Weakening the US guard, changing the user input configuration, repeating
input, or querying again after failure would change the experiment and is outside
this correction. All ownership, deadline, lifetime and deployment gates remain.

Verify RED/GREEN with the actual case harness: first composition failure plus
final event snapshot failure must attempt restoration once and close each helper
once, preserving the first exception. Restoration failure must not be retried and
both cleanup errors must survive. Exercise each numeric origin/slot, wrong
identity/context, bounds/types, fallback, transport size and legacy round trips.
