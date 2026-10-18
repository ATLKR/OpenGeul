This is a diagnostic-only reproduction of the native22 ATL prerequisite failure.

The selected toolchain is frozen to VS18 Enterprise 18.10.12224.181, v145
14.51.36231. A changed runner fails closed for review. The workflow accepts only
an exact reviewed commit on work/opengeul-office-native-atl-control; it does not
run on main, pull requests, push, schedules, or product workflows.

source.json pins exact members of the locally rehashed official LibreOffice
26.8.1.1 source archive. configure-atl-selection.sh consists only of the two
listed physical-LF ranges from configure.ac. It executes the original ATL path
selection with explicit selected-toolchain inputs and real Cygwin GNU make.
This is not a full configure or gbuild invocation. Library_so_activex.mk and
com_MSC_class.mk establish how those paths reach the native compiler/linker;
the separate diagnostic makefiles retain their exact command arguments.

The control observes installer membership separately from actual headers and
the ARM64 static library. It provisions only the already reviewed/pinned
Cygwin build helpers. It never installs Visual Studio, ATL, or any product.
Absent/rejected prerequisite files stop the control without substitutes.

Baseline/candidate header compiles use identical optimized native CL flags.
Then independent baseline/candidate linker commands use the same candidate
object. Candidate changes only the ATL path spelling. /showIncludes must
witness the exact censused headers. The selected atls.lib archive must contain
only ARM64 code members. A candidate native AA64 PE is admitted only alongside
the linker's explicit selected-archive member extraction witness. The program
calls CComModule::RegisterServer solely to create a real ATL link dependency;
neither executable is run.

Original raw logs, makefiles, shell scripts, argument arrays, source/tool/file
hashes and owned-command receipts are retained, including normal expected
baseline failures. Timeouts, forced cleanup, missing EOF, unrelated errors and
missing extraction evidence remain inconclusive failures. The reviewed command
helper owns the direct Cygwin command; it does not independently attest native
compiler descendant process handles or claim descendant job membership.

No observation here qualifies an engine, Python build, Base, GUI or release.
All qualification flags stay false. Actual Windows outcomes remain unobserved
until root publishes and dispatches a separately reviewed diagnostic commit.
