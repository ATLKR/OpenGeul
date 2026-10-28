# Portable acceptance implementation plan

**Goal:** Verify the delivered ZIP and relocated startup paths on both Windows architectures.

**Spec:** `docs/superpowers/specs/2026-10-28-portable-acceptance.md`.

- [x] Reproduce missing final-ZIP and foreign-working-directory coverage with failing checks.
- [x] Implement authenticated extraction, owned corruption detection, fresh extraction repair and HWP hash preservation.
- [x] Route the existing startup plan through an explicit foreign child working directory.
- [x] Verify the actual workflow command with real file checks and synthetic packages; independently review it.
- [x] Run the complete final local suite (2,773 tests, 14 skipped) and prepare the candidate commit.
- [ ] Preserve the active Windows run, then submit the new final-code acceptance on both architectures.
- [ ] Inspect the new Windows package, input, UI, persistence, lifecycle and integrity evidence before qualifying a release candidate.
