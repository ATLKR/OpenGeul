This is a diagnostic-only reproduction of the native22 ATL prerequisite failure.

The selected toolchain is frozen to VS18 Enterprise 18.10.12224.181, v145
14.51.36231. A changed runner fails closed for review. The workflow accepts manual
dispatch with matching source_sha, or pushes on work/opengeul-office-native-atl-control
for explicitly listed diagnostic paths. Every accepted run uses the immutable
event SHA. It does not run on main, pull requests, schedules, or product workflows.

source.json pins exact members of the locally rehashed official LibreOffice
26.8.1.1 source archive, the dedicated diagnostic reader, and non-code ATL input
profiles. configure-atl-selection.sh consists only of the two
listed physical-LF ranges from configure.ac. It executes the original ATL path
selection with explicit selected-toolchain inputs and real Cygwin GNU make.
This is not a full configure or gbuild invocation. Library_so_activex.mk and
com_MSC_class.mk establish how those paths reach the native compiler/linker;
the separate diagnostic makefiles retain their exact command arguments.

The control observes installer membership separately from actual headers and
static build inputs. The exact actual control1 archives each contain linker
metadata, five ARM64 AA64 objects, and five ARM64EC A641 objects. The dedicated
ATL reader retains these variants explicitly; it does not call the whole archive
native or change the shared strict JNI import-library reader. Exact archive and
member hashes, names, offsets and ordinary COFF bounds bind the input profiles.
Official-package members match the actual library bytes/SHA256; catalogue and
declared package-length anomalies remain recorded without claiming a complete
catalogue authentication chain. No Microsoft archive/object payload is included.
The control provisions only the already reviewed/pinned
Cygwin build helpers. It never installs Visual Studio, ATL, or any product.
Absent/rejected prerequisite files stop the control without substitutes.

Baseline/candidate header compiles use identical optimized native CL flags.
Then independent baseline/candidate linker commands use the same candidate
object. Candidate changes only the ATL path spelling. /showIncludes must
witness the exact censused headers. Both linker arms use the original selected
archive unchanged; no native-only derivative is substituted. A native AA64 PE
alone cannot prove what was consumed. EVERY selected-atls Loaded member and map
contribution must resolve through its complete archived name to one exact member
offset/hash with an AA64 COFF header. A641, unknown, duplicated, unaccounted or
ambiguous entries fail closed. Actual basenames collide across variants; this
initial oracle implements no basename, offset-syntax or symbol fallback. If
native logs/maps omit full names, both arm observations are retained and the
strict control remains inconclusive. Input readiness for this measurement is
separate from all-consumed-AA64 admission. The program
calls CComModule::RegisterServer solely to create a real ATL link dependency;
neither executable is run.

Original raw logs, makefiles, shell scripts, argument arrays, source/tool/file
hashes and owned-command receipts are retained, including normal expected
baseline failures. Timeouts, forced cleanup, missing EOF, unrelated errors and
missing extraction evidence remain inconclusive failures. The reviewed command
helper owns the direct Cygwin command; it does not independently attest native
compiler descendant process handles or claim descendant job membership.

No observation here qualifies an engine, Python build, Base, GUI or release.
Product qualification flags stay false. Native Windows header/link A/B and
consumption outcomes remain unobserved until root publishes a separately reviewed
diagnostic commit for a matching push or manual dispatch. Focused private-corpus
reader tests are opt-in with OPENGEUL_NATIVE_ATL_REQUIRE_CORPUS=1 and an explicit
OPENGEUL_NATIVE_ATL_CORPUS directory; required missing inputs fail rather than
being replaced or downloaded. The workflow itself still runs only the probe.
