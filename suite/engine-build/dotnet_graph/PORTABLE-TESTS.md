# Portable diagnostic checks

From the repository root, run `python suite/engine-build/dotnet_graph/run-portable-tests.py` using Python 3.12 and the existing PyYAML dependency. No package installation is performed. The command prints only numeric counts and exits nonzero on any failure, skip, or missing expected test.

The tests import the shipped sibling runtime and read the actual repository workflow. The original public gmake metadata and original workflow are test fixtures only. This path is outside ordinary `suite/tests` discovery and neither the default Full job nor the diagnostic SDK job runs it implicitly.

The 92 synthetic/source checks were executed on Linux. They do not prove Win32 behavior, Microsoft.Build.Framework ABI, actual SDK restores, DLL locking, API execution, source qualification, or Windows acceptance. The diagnostic job must obtain those bounded observations separately.

The isolated diagnostic push explicitly enables closed bootstrap error-code observations. Its own Windows pipe preflight must pass before SDK output is read. Raw output stays in bounded memory; only numeric family/code/count and status fields enter the receipt. These textual tokens are observations, not authenticated MSBuild events. The original NUL launcher and held-descendant preflights remain required. Synchronous OS calls cannot be preempted by the controller; late completion is rejected against the original deadline.

Unrecognized error headers remain incomplete evidence. Their fixed numeric shape counts are retained while bounded observation continues to later codes and natural process exit. The final incomplete receipt still fails before graph execution. Overflow, identity changes and native API failures retain immediate cleanup. A forced cleanup exit code does not establish a natural SDK failure.
