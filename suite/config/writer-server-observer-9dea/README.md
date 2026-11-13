# 9dea Writer server-observer source metadata

These raw source-lock and wire-schema files are the frozen ARM-only diagnostic
producer contract. They do not qualify a runtime or identify an actual build.
The retained bf6 backend in `suite/engine-build/writer-server-observer-diagnostic`
is a separate historical implementation and is not selected by this consumer.

The producer ref is `work/opengeul-office-native-writer-observer-9dea`.
The manual Suite ref is `work/opengeul-office-native-writer-observer-suite-9dea`.
The diagnostic pre-overlay proof uses the254 source snapshot's exact manifest
`37fba766084127e2fdf2f51c3108290a39ddfdaa895af03c68d3cfc8b35d2020`
and ARM recipe
`9b10511f31066a5966014c6357268b4d1dcfa3ffa24eb9c97c8bc0c05dbef0fe`.
These do not replace the normal ARM497 or x64 qualified runtime locks.

A completed, successful native ARM producer run and its actual two-file artifact
must be externally pinned before acquisition. No diagnostic input lock is supplied
here. Both rebuilt DLLs, paired marker bytes, typed sourceRun/runAttempt and all
source hooks must match that external input. IPC1, sink ABI2 and mapping131328 are
unchanged. A staged diagnostic is always ineligible for normal payload or release
acceptance; the observation job deliberately ends without qualification.
