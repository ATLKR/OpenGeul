# Portable diagnostic checks

From the repository root, run `python suite/engine-build/dotnet_graph/run-portable-tests.py` using Python 3.12 and the existing PyYAML dependency. No package installation is performed. The command prints only numeric counts and exits nonzero on any failure, skip, or missing expected test.

The tests import the shipped sibling runtime and read the actual repository workflow. The original public gmake metadata and original workflow are test fixtures only. This path is outside ordinary `suite/tests` discovery and neither the default Full job nor the diagnostic SDK job runs it implicitly.

The 46 synthetic/source checks were executed on Linux. They do not prove Win32 behavior, Microsoft.Build.Framework ABI, actual SDK restores, DLL locking, API execution, source qualification, or Windows acceptance. The diagnostic job must obtain those bounded observations separately.
