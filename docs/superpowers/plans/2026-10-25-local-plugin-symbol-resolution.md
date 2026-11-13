# Local symbol adapter preparation

1. Implement only the pure eligibility checks and native file-only adapter, with
   synthetic API-boundary tests. No CLI, workflow or observer wiring yet.
2. Review local/remote path ordering, held-file identity, native ABI assumptions,
   result bounds, original deadlines and mandatory cleanup. Run the full local
   suite on the frozen source.
3. Await the exact matched native build artifact. Independently validate its
   identity/provenance before designing the owned-child watchdog integration and
   loaded-editor module binding. No native invocation precedes that review.
4. Only a reviewed bounded replay of the original failure may produce eligible
   frame queries. Preserve the stopping rule and original acceptance gates.

Status: unwired adapter and synthetic tests implemented. Review corrected
read/delete sharing, remote-drive rejection before artifact access, and ancestor
reparse rejection before child lookup. Local focused tests pass (38 combined). Final local suite passed 2518 tests,
zero failures/errors, 12 skips, 316.334 seconds; frozen source hashes match.
Native ABI, symbol loading and caller attribution remain unverified. The module
has no CLI, workflow or observer wiring.
