# WACK DPI carrier observation plan

**Goal:** Identify the exact static failure path before selecting another package experiment.

**Evidence:** Run43 archive SHA256 `c0a455b1ec98355c96d4e365a466b6ab9d557480447f103e976d2f9581cea8cd`; editor hash and PMv2 observations match Run42. The confirmed message carrier is `microsoft.windows.softwarelogo.tests.dll`, SHA256 `61bae06c0dcfa220fff9f771060133bd74c27a2921000a5889e78d24d2eb3679`.

**Constraints:** Keep main, application packages, WACK classification and Store state unchanged during observation. Use the existing public disposable Windows runner. Do not execute SDK test modules, copy them into artifacts, or expose credentials. Preserve explicit size/time limits and report truncation.

1. Read the confirmed managed carrier with the installed IL disassembler and preserve bounded DPI method, catch and referenced method evidence.
2. Read the exact DPI test mapping from installed configuration.xml.
3. Run the diagnostic branch workflow once; verify carrier/tool identity and inspect its artifact.
4. Choose one subsequent experiment only if the observed code supplies a specific failure mechanism. Otherwise preserve the unresolved blocker without publishing an unverified release.

**Verification:** Static workflow policy and diff checks; extractor self-check; actual Windows execution. Prior baseline: 220 repository tests and 81 CI tests passed on main `8cec8ac`.
