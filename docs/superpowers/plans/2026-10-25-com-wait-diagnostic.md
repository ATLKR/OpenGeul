# Synthetic STA dispatch implementation plan

Execute within the authorized bounded CI diagnosis. Independent review and
full local validation precede a substantive owner-branch push. No product
behavior changes or acceptance claims are included.

Spec: `docs/superpowers/specs/2026-10-25-com-wait-diagnostic.md`.

1. Implement an isolated diagnostic child and retained-process controller in
   `suite/shell-tests/ComWaitDiagnostic.cs`, with minimal `Program.cs` routing.
   Test receipt identity, ordering, bounds, classification and cleanup contracts
   before implementation; compile standalone C# locally. Native execution stays
   explicit and separate from normal shell tests.
2. Add `com-wait-diagnostic` workflow mode with the existing owner/source
   admission, exact receipt upload and explicit nonacceptance. Preserve existing
   GUI mode prerequisites. Add regression tests for all mode transitions and
   run commands; update suite usage documentation.
3. Independently cross-review callback ABI/lifetime, deadline/termination and
   mode admission. Freeze source and run the full local suite. Push only after
   passing checks; inspect both native jobs and their complete receipts.
4. Update the finite hypothesis ledger from actual results. Distinguish observed
   synthetic delivery from physical Office input, and do not rerun unchanged
   experiments or promote these receipts to paired acceptance.

Status: implementation and independent review complete. Full local suite passed 2404 tests, 12 skipped, zero failures/errors in 281.026 seconds. Standalone C# compilation and pure receipt contracts passed. Native net8 build and real Windows execution remain pending; these local results do not validate dispatch behavior.

Native run 40162247190 at 383f0edd23f5f23f631cf5f21a168b095357c8b0
passed all 2404 unit tests on both architectures (36 skips each), then failed
the net8 shell build with CA1416 inside the escaped Thread delegate. No
synthetic arm ran. The caller's Windows platform guard does not establish the
delegate's platform context for analysis. Put the guard inside the delegate,
without suppressing the analyzer. Seven focused local checks and independent
review passed for this correction; the native build remains the required check.
