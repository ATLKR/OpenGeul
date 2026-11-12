# Normal .NET source graph regression

This explicit check uses existing GNU make and PowerShell 7 on Linux. It is not
part of ordinary Windows unittest discovery and never installs a tool, invokes
the .NET SDK, publishes a package or qualifies an engine.

Run from the repository with explicit existing executable paths and a fresh
result path:

```sh
python3 -I -S suite/engine-build/dotnet_project_graph_regression/runner.py \
  --make /absolute/path/to/existing/make \
  --pwsh /absolute/path/to/existing/pwsh \
  --output /tmp/fresh-dotnet-source-result.json
```

Success requires exactly 22 checks, zero failures/errors/skips and exit zero.
Each make child has a ten-second bound and each PowerShell child a twenty-second
bound. Output is discarded except for the bounded make metadata needed for XML
and CLI checks and the final numeric receipt. The caller's environment is never
copied into a diagnostic record or child environment.

The original 9dea gbuild macros produce the five synthetic caller projects. The
version query uses an owned fixed stub, not a .NET host. The metadata checks keep
library `netstandard2.0`, SDK-derived test TFM, original NUnit/DispatchProxy pins,
gmake prerequisites, reference metadata and package Content mappings. Drive-path
and Korean-directory expansion are actual GNU make string expansion on Linux;
they are not actual Windows/Cygwin path execution.

The PowerShell checks use the actual finite Python source installer and the
independent producer proof binder. The source fixture is a subset of exact
official original files, not a complete LibreOffice archive. A removed new hook
cannot be relabelled as a valid old source plan.

Actual normal Windows source Full, its NUnit/pack behavior, installed runtime,
GUI/IME and final Suite qualification remain separate gates. The numeric output
always marks source qualification and acceptance false.

All official originals retain their source license headers. `asset-pins.json`
binds the source/test fixture bytes. `fixtures/TargetLocations.pin.json` identifies
the previously verified official four-line excerpt; the full file is not
represented as having been restored. `fixtures/source-context/solenv/gbuild/Helper.mk`
documents why deprecated `gb_Helper_native_path` must not be used.
