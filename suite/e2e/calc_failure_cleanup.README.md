# Cleanup after a failed first Calc observation

The pending-cell Save and Close probes create a private byte-for-byte copy of
the generated engine fixture. A failed first observer read must remain a failed
case. It must also leave the Suite a chance to archive its real shutdown proof.
Killing the Suite immediately skips that close path; EOF is intentionally not
permission to discard an attached Calc document.

`calc_failure_cleanup` freezes the exact baseline copy before launch and retains
the native shell and engine generations at attachment. After a failed observer
is physically released, it may post one owned WM_CLOSE and physically select
Discard through the existing exact three-choice Suite dialog checks. It verifies
the original launch command, Popen HANDLE, executable paths and creation times,
Suite/panel/editor relationships, unchanged workbook hash and all five expected
cell values before close and again before the choice. It then checks unchanged
bytes, the retained engine's exit and a zero shell exit after closing Home.

Authorization applies only to `observe-clean-before-input` in the Save probe or
`observe-before-input` in the Close probe. The stage changes before navigation
starts, so even a partially sent key sequence excludes this path. Any input,
original shortcut, changed generation, changed file, foreign/ambiguous prompt or
unproved observer release refuses Discard. This is not a retry of the measured
Save/Close action. The existing forced process cleanup remains the last resort.

The original error, failure stage and `success:false` remain unchanged. The
separate `failureCleanup` record describes this secondary attempt and always
sets `productShutdownQualified:false`. Only the existing raw native archive
validator can qualify product shutdown. The failed observation remains
unqualified even when its physical observer cleanup succeeded. Portable tests
exercise the boundary and both real harness control paths; Windows execution
must still establish actual UI behavior and archive completeness.
