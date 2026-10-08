# Free CI verification checkpoint — 2026-10-06

The public/free-runner stage and bounded evidence changes were committed as `cf8e9987e85f4b9972430102c4403c850a832469`, preserving concurrent print activation changes from `7bccfcc`. Actual policy run [37435043657](https://github.com/ATLKR/OpenGeul/actions/runs/37435043657) passed 36 CI tests, 127 package/policy tests and six standalone Rust font-metadata tests. This is not a complete Windows, virtual-printer or release pass.

A follow-up source review found that the concurrent print-focus rewrite had removed `fill_print_output`, although `virtual_print.py` still imports it. A new preflight contract test proves the missing export before another expensive Windows build. Five native-boundary unit checks also pin stable filename/Save readiness, hidden or ambiguous controls, rejected output names and no second click after a dispatched input error. All six tests were observed failing on the missing-function source; restoring only the missing shell-save helper makes all six pass. The existing semantic preview changes are otherwise unchanged.

Local final CI helper suite: 42 passed. The older hash-verified local source snapshot's 79 package/native helper tests also pass, but the newer complete package suite is only claimed from its actual GitHub run above. The new candidate requires fresh CI and all existing 62 editor UI plus 16 virtual-print gates; failure must continue to block release. No printing raster reference, comparison threshold, account budget, paid runner or signing secret was changed.

Manual modes and storage caps are documented in FREE_CI.md. The repository owner still needs an appropriate Actions $0 stop-usage budget as the account-level backstop; these scripts do not read or set billing permissions.
