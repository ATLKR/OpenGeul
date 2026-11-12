# Fixed IME native-fixture compiler observation

This diagnostic admits only Suite commit `b98b555b646f8fd412057afb880e8b4c35262f9a` and the nine source sizes/hashes embedded in the collector. It checks the actual checkout HEAD and bytes, copies only those verified bytes to an owned temporary tree, and runs the original three native fixture methods. `helper()` reads the original observer string through AST without importing the document UI.

```text
python suite/scripts/ime-finalization-compiler-observation/observe-ime-finalization-compile.py --source-root .work/ime-finalization-source --architecture x64 --output .work/ime-finalization-compile
python -I -B suite/scripts/ime-finalization-compiler-observation/test_collector.py
```

The second command is synthetic and does not compile or execute native Windows code. `pinned-source/` contains the nine public source snapshots needed to reproduce its boundary tests; they remain tied to the original Suite commit.

The original `/W4 /WX /std:c++17`, compiler 60-second deadline, VS discovery 15 seconds, execution 5 seconds, completed-image cleanup, native PE checks, environment allowlist and failure assertions are preserved. A failed, errored or skipped fixture returns exit 1. This tool cannot qualify Suite acceptance, SDK compilation, document input or a product release.

Only `report.numeric.json` is published. Source/output must be local ordinary paths, output must be fresh and outside source, and the output parent must exist. Once that directory exists, ordinary setup failures also produce a report. Reports are at most 32 KiB. Each case retains at most 32 diagnostics: stream, severity, C/D/LNK numeric code, fixed public file role and line. Unknown paths retain file/line 0. Compiler bodies, arbitrary paths, environment values, argv and exception representations are not serialized. The original compiler output exists only in RAM.

The workflow selects an already-installed native Python and runs this in a separate bounded eight-minute job on the two standard Windows hosts. The existing SDK six-minute job, four-minute step, 180-second outer gate and 30-second native phases are unchanged. Normal Suite acceptance does not run on this diagnostic branch.

The baseline Suite run [43274358224](https://github.com/ATLKR/OpenGeul/actions/runs/43274358224) failed two fixture compilations before UI with exit 2 on both architectures. Its caller discarded compiler output. C4312 and C4267 are source-level hypotheses until actual diagnostics are observed; no fixture or warning policy was changed to accept them.

The independent two-host compiler observation is an explicit opt-in diagnostic on the existing SDK branch. In addition to the exact public repository, owner, actor, branch and first-attempt gates, the push head commit message must contain `[ime-finalization-compile]`. A schema5 SDK-only commit omits this marker: the two SDK jobs run and the unchanged IME compiler samples are not repeated. Normal product Suite unit tests and acceptance gates are unchanged. The six actual MSVC cases from run43291887112 remain separate preserved evidence. No new runner, setting or permission is introduced.

The marker check uses GitHub's documented case-insensitive [contains](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#contains) function. For SDK-only observation, omit the marker from the entire head commit message, including its body.
