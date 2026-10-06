# Table-height backport verification

Target: the terminal-negative-trailing case from rhwp PR 6074 (`c7d3c66398acdb3c093fdea6fef573e14f771a6c`, planet6897), adapted narrowly to inline tables in pinned rhwp 0.8.4. This is related to HOP #99/#78 but is not proof those exact reports are resolved. The original #99 attachment is not present in that report, and print-driver behavior is a separate test target.

Local reproduction uses source-verified WASM artifact 11381666392 from PR2 run 37391710620. A five-paragraph synthetic HWPX table has 1000-HWPUNIT lines, -300-HWPUNIT spacing, 141-HWPUNIT top/bottom padding, and no declared-height shrink heuristic. The last painted line exceeds the cell box by 2.2px; cell height is 50.4px instead of 54.4px. Zero/positive spacing controls remain inside (70.4px/110.4px). The normal assertion was observed failing; the explicit negative-control runner succeeds only when that precise clipping and both positive controls are observed.

The fix preserves inter-line compression, positive terminal spacing, block-table handling and stored LINE_SEG data. It changes both reviewed height-measurement sites after validating the exact original Git blob. The broader PR6068 growth heuristics are not imported.

Six local patcher refusal/scope tests and Python/Node syntax checks passed. Source drift, incorrect replacement counts and an unowned prepatched file are rejected. The full repository tests, rebuilt-WASM geometry gate and native Rust geometry gate must run on GitHub before merge. This document does not claim those pending gates passed.

Existing 62 browser/native UI executions and MSIX installation checks remain enabled. Synthetic fixtures are generated in the runner, never taken from customer documents. No font programs are added. Geometry verification is not a full Hancom pixel-golden or a physical-printer test.
