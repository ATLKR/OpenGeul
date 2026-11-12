# Packaged-context observation candidate (scratch only)

This completes one source-only observation component, not an installed app worker, launcher or servicing gate. Main/native/pure40 source files are not changed. No SDK was installed and no Windows process, app/package, UI or Store action was invoked.

The production bundle is exactly `context_observer.hpp`, `context_observer_windows.cpp` and `observation_contract.py`. The C++ core retains and reopens three existing directory objects and rejects missing paths, reparse objects, shared FileIDs, changed identities, emulation, bad clocks and uncertain cleanup. The Windows SDK port queries package identity/current TokenUser/native machine, KnownFolder and WinRT LocalFolder metadata. It has no executable entry point. Its C++ RAII handle class was separately compiled with copy elision disabled; Windows SDK ABI/projection compile is still unverified.

There are no explicit create/write/servicing calls in the Windows port. This is **not an OS side-effect-free guarantee**: WinRT/OS getter initialization effects remain unknown and `osImplicitEffectsKnown` is always false. FileID opens request READ_ATTRIBUTES, share READ|WRITE|DELETE and OPEN_EXISTING. No delete/rename test is performed. Handles close after observation; no durable servicing lease or fresh ownership is claimed. Component reparse checks and reopened object comparisons are bounded snapshots, not a claim of atomic protection against arbitrary concurrent namespace replacement.

Metadata validation requires paths together with native identities, source-only independent expectations, the original clock window, ten false authority/origin flags and exact whole-bundle hashes. It returns only copied metadata. `run_native` and phase conversion always reject. An actual helper packet cannot self-authorize execution, root adoption, update, repair or removal.

## Observed verification

Final portable check after the independently reviewed apartment-order fix: **59 tests, failures0/errors0/skipped0**, source hashes unchanged. These include actual Linux g++ compilation/execution of the portable policy and an actual generated synthetic C++ JSON projection validated by Python against the actual three-file source bundle. They do not compile or run the Windows SDK port. The old pure40 tests were not repeated; its eight frozen deliverable byte hashes are checked separately. The earlier56-test source and receipt are preserved in frozen-before-apartment-fix/. WinRT initialization is now lazy, after pure request/package/path validation, and its actual portable C++ guard tests cover zero initialization for expired input and exactly one uninitialization after successful initialization on postcheck/query failures. This is not Windows/SDK execution.

Reproduction (writes a new bounded numeric result only):

```
python -B run_checks.py --output validation-reproduction.json
```

Use a fresh `validation-*.json` name; original results are never overwritten. The outer controller stops waiting after60s and reports a still-running owned test process without forcekill or a false pass. Test compilers and synthetic processes have their own finite waits and no raw output capture. This portable controller is not a package launcher or the unresolved Windows watchdog.

## Windows work still required

1. Compile the SDK source with existing target VS/Windows SDK only. An example future compile-only command is `cl /nologo /c /std:c++17 /EHsc /W4 /WX /MT /DUNICODE /D_UNICODE context_observer_windows.cpp`. Missing headers/libs are unsupported; no implicit download. This builds an object, not a runnable/admitted observer. No executable hash is fabricated here.
2. Establish and review a supported activation route that retains the exact original helper process HANDLE/generation and an external watchdog within the unchanged phase budget. The documented Appx cmdlet only guarantees diagnostic package identity/resource access, not product-token equivalence or the required HANDLE contract. `ActivateApplication` targets the manifest app and returns a PID; it is not an arbitrary-probe original-HANDLE substitute.
3. With authentic exact qualified input and separately verified embedded manifest/source recipe, obtain real x64/ARM64 package-context API/path/FileID/close observations. KnownFolder paths are observed, not expanded from environment variables. LocalState comes only from WinRT. The packet cannot establish actual browser UDF equivalence or newly created default-directory ownership.
4. Keep fresh/default UDF, LocalState, Roaming, normal process retirement, update/Repair and final Suite evidence as later separate gates. The existing pure40 and current empty native Repair profile set remain unchanged. No Reset, uninstall-first, downgrade, profile deletion, forced close or existing HWP replacement is introduced.
