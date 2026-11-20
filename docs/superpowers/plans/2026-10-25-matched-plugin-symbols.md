# Matched plugin symbols implementation

1. Add executable synthetic PE/PDB identity regression tests and a bounded helper
   that retains only the exact matching native plugin pair and provenance.
2. Add the default-off Full-only build switch, exact generated configuration
   checks and diagnostic retention before packaging, within existing budgets.
3. Opt the existing native-engine owner-push workflow into this diagnostic build;
   preserve normal source qualification and separate the symbol artifact.
4. Independently review, run focused/full local validation and push only the
   existing native-engine branch after verifying ancestry and clean source.
5. Follow that exact build through completion. Matching symbols enable a later
   bounded owned-editor diagnosis; they do not establish a behavior correction.

Status: implementation and independent focused review complete. Full local
validation and native-engine history reconciliation pending. No build launched.

The native-engine branch contains separately retained source-build history. A
normal merge must preserve the later Suite implementations in seven conflicts;
read-only review found no unique old-branch fix missing from those files. Do not
force-push or replace later lifetime, geometry or cleanup validation.
