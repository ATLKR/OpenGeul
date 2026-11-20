"""Normalize only reviewed dependency and reader edits for the historical oracle.

Actual workflow readers and source receipts keep their original, current bytes.
Any other edit remains visible to the independent original-job SHA256 check.
"""

CURRENT_NORMAL_IF = ("    if: github.event.repository.private == false && "
    "(github.ref != 'refs/heads/work/opengeul-office-native-writer-observer')\n")
EXACT_SDK_SETUP = ("    - uses: actions/setup-dotnet@0f4a354dd5547a28c70b7853dbd95d5b67886e73\n"
    "      with:\n"
    "        dotnet-version: '10.0.404'\n"
    "        skip-lts-prepass: true\n"
    "        architecture: ${{ matrix.architecture }}\n")
CURRENT_PILLOW_INSTALL = "        python -m pip install Pillow==13.0.0\n"
EXACT_YAML_SETUP = ("        python -m pip install PyYAML==6.0.3\n"
    "        if ($LASTEXITCODE -ne 0) { throw 'Pinned YAML workflow tooling installation failed.' }\n")
EXACT_UI_READINESS_INSTALL = (
    '    - name: 실제 한국어 IME와 네이티브 UI 검사 준비\n'
    '      shell: pwsh\n'
    '      run: |\n'
    '        python -m pip install pywinauto==0.6.9 comtypes==1.5.0\n'
    "        if ($LASTEXITCODE -ne 0) { throw 'Native UI test prerequisites failed.' }\n")
EXACT_READER_CONSOLE_INSTALL = (
    "        if ($env:OPENGEUL_SUITE_RUN_MODE -ceq 'reader-console-diagnostic') {\n"
    '          python -m pip install pywinauto==0.6.9 comtypes==1.5.0\n'
    "          if ($LASTEXITCODE -ne 0) { throw 'Native UI test prerequisites failed.' }\n"
    '        }\n')

# These are exact source-only reader deltas, not a generic legacy fallback.
# Each prologue must remain adjacent to its one original command. Missing,
# duplicate or modified current routes cannot be treated as historical support.
EXACT_CALC_READER_SETUP = (
    "        $sourceReaderArgs = @()\n"
    "        if ($env:OPENGEUL_SUITE_RUN_MODE -ceq 'acceptance') {\n"
    "          if ($env:SUITE_RUNTIME_FORMAT -ceq 'source-built-zip') {\n"
    "            if ('${{ matrix.architecture }}' -cnotin @('x64', 'arm64')) { throw 'Unsupported source reader architecture.' }\n"
    "            $sourceReaderArgs = @('--source-qualified-reader', '${{ matrix.architecture }}')\n"
    "          } elseif ($env:SUITE_RUNTIME_FORMAT -cne 'msi') {\n"
    "            throw 'Unsupported Suite runtime format for the model reader.'\n"
    "          }\n"
    "        }\n")
EXACT_IME_READER_SETUP = (
    "        $sourceReaderArgs = @()\n"
    "        if ($env:SUITE_RUNTIME_FORMAT -ceq 'source-built-zip') {\n"
    "          if ('${{ matrix.architecture }}' -cnotin @('x64', 'arm64')) { throw 'Unsupported source reader architecture.' }\n"
    "          $sourceReaderArgs = @('--source-qualified-reader', '${{ matrix.architecture }}')\n"
    "        } elseif ($env:SUITE_RUNTIME_FORMAT -cne 'msi') {\n"
    "          throw 'Unsupported Suite runtime format for the model reader.'\n"
    "        }\n")
REVIEWED_READER_COMMANDS = (
    (EXACT_CALC_READER_SETUP,
     '        python suite/e2e/calc_save_smoke.py --suite $env:SUITE_PACKAGE --fixtures .work/suite-engine/fixtures --output .work/suite-calc-save'),
    (EXACT_CALC_READER_SETUP,
     '        python suite/e2e/calc_close_probe.py --suite $env:SUITE_PACKAGE --fixtures .work/suite-engine/fixtures --output .work/suite-calc-close'),
    (EXACT_IME_READER_SETUP,
     '        python suite/e2e/korean_ime_smoke.py --suite $env:SUITE_PACKAGE --fixtures .work/suite-engine/fixtures --readiness .work/suite-korean-readiness/readiness.json --output .work/suite-korean-ime'),
)


# One exact reviewed Writer failure-observation route; no legacy fallback.
EXACT_WRITER_SAME_ROOT_SETUP = (
    '        $writerSameRootArgs = @()\n'
    "        if ($env:OPENGEUL_SUITE_RUN_MODE -ceq 'acceptance' -and\n"
    "            $env:GITHUB_ACTIONS -ceq 'true' -and\n"
    "            $env:RUNNER_ENVIRONMENT -ceq 'github-hosted' -and\n"
    "            $env:RUNNER_OS -ceq 'Windows' -and\n"
    "            (('${{ matrix.architecture }}' -ceq 'arm64' -and $env:RUNNER_ARCH -ceq 'ARM64') -or ('${{ matrix.architecture }}' -ceq 'x64' -and $env:RUNNER_ARCH -ceq 'X64')) -and\n"
    "            $env:GITHUB_REPOSITORY -ceq 'ATLKR/OpenGeul' -and\n"
    "            $env:GITHUB_EVENT_NAME -ceq 'push' -and\n"
    "            $env:GITHUB_JOB -ceq 'windows-suite' -and\n"
    "            $env:GITHUB_REF -ceq 'refs/heads/work/opengeul-office-arm64' -and\n"
    "            $env:GITHUB_WORKFLOW_REF -ceq 'ATLKR/OpenGeul/.github/workflows/office-suite.yml@refs/heads/work/opengeul-office-arm64' -and\n"
    "            $env:GITHUB_RUN_ATTEMPT -ceq '1' -and\n"
    "            $env:GITHUB_ACTOR -ceq 'ATLKR' -and\n"
    "            $env:GITHUB_ACTOR_ID -ceq '65988341' -and\n"
    "            $env:GITHUB_SHA -cmatch '\\A[0-9a-f]{40}\\z' -and\n"
    '            $env:GITHUB_WORKFLOW_SHA -ceq $env:GITHUB_SHA -and\n'
    "            $env:GITHUB_RUN_ID -cmatch '\\A[1-9][0-9]{0,19}\\z' -and\n"
    '            "${{ github.event.repository.full_name == \'ATLKR/OpenGeul\' && github.event.repository.private == false && github.event.repository.id > 0 && github.event.sender.login == \'ATLKR\' && github.event.sender.id == 65988341 && github.event.sender.type == \'User\' && github.event.ref == \'refs/heads/work/opengeul-office-arm64\' && github.event.deleted == false && github.event.after == github.sha }}" -ceq \'true\') {\n'
    "          $writerSameRootArgs = @('--writer-same-root-diagnostic', '${{ matrix.architecture }}')\n"
    '        }\n'
)
WRITER_SAME_ROOT_COMMAND = '        python suite/e2e/korean_ui_smoke.py --suite $env:SUITE_PACKAGE --fixtures .work/suite-engine/fixtures --output .work/suite-korean-ui'


def original_normal_oracle_text(normal):
    if type(normal) is not str:
        raise ValueError('Historical normal-job oracle requires text')
    normal = _without_engine_summary_artifacts(normal)
    normal = _without_bundled_clang_probe(normal)
    changes = ((CURRENT_NORMAL_IF, '    if: github.event.repository.private == false\n'),
        (EXACT_SDK_SETUP, ''),
        (CURRENT_PILLOW_INSTALL, '        python -m pip install Pillow==12.3.0\n'),
        (EXACT_YAML_SETUP, ''),
        (EXACT_UI_READINESS_INSTALL, EXACT_UI_READINESS_INSTALL.replace(' comtypes==1.5.0', '', 1)),
        (EXACT_READER_CONSOLE_INSTALL, EXACT_READER_CONSOLE_INSTALL.replace(' comtypes==1.5.0', '', 1)))
    for before, after in changes:
        if normal.count(before) != 1:
            raise ValueError('Reviewed normal-job dependency delta differs')
        normal = normal.replace(before, after, 1)
    for setup, command in REVIEWED_READER_COMMANDS:
        before = setup + command + ' @sourceReaderArgs\n'
        if normal.count(before) != 1:
            raise ValueError('Reviewed normal-job source-reader delta differs')
        normal = normal.replace(before, command + '\n', 1)
    before = EXACT_WRITER_SAME_ROOT_SETUP + WRITER_SAME_ROOT_COMMAND + ' @writerSameRootArgs\n'
    if normal.count(before) != 1:
        raise ValueError('Reviewed normal-job Writer failure-observation delta differs')
    normal = normal.replace(before, WRITER_SAME_ROOT_COMMAND + '\n', 1)
    return normal


# One exact reviewed read-only probe block; no production or broad-name fallback.
BUNDLED_CLANG_PROBE_START = '    - name: Observe the selected VS bundled Clang pair without changing acceptance\n'
BUNDLED_CLANG_PROBE_AFTER = '    - name: 모든 검증을 통과한 Suite 개발 패키지 전달\n'
BUNDLED_CLANG_PROBE_SHA256 = '51775e3521c251a614b1cf6ff47e1163e0cabab6dfcba31207b27407203d12aa'


def _without_bundled_clang_probe(normal):
    import hashlib
    if BUNDLED_CLANG_PROBE_START not in normal:
        return normal
    if normal.count(BUNDLED_CLANG_PROBE_START) != 1 or normal.count(BUNDLED_CLANG_PROBE_AFTER) != 1:
        raise ValueError('Reviewed bundled Clang observation delta differs')
    start = normal.index(BUNDLED_CLANG_PROBE_START)
    if normal.rfind('    - name:', 0, start) != normal.index(BUNDLED_CLANG_PROBE_AFTER):
        raise ValueError('Reviewed bundled Clang observation must follow the final original step')
    block = normal[start:]
    if (hashlib.sha256(block.encode('utf-8')).hexdigest() != BUNDLED_CLANG_PROBE_SHA256 or
            block.count('    - name:') != 3):
        raise ValueError('Reviewed bundled Clang observation delta differs')
    return normal[:start]


# Exact supplemental metadata-only collection; all original job bytes remain.
ENGINE_SUMMARY_FIRST_BLOCK = '    - name: Validate first closed engine failure summary\n      id: engine-summary-first-validation\n      if: "always() && steps.build.outcome == \'success\' && (steps.fixtures.outcome == \'success\' || steps.fixtures.outcome == \'failure\' || steps.fixtures.outcome == \'cancelled\')"\n      shell: pwsh\n      run: |\n        python -B suite/scripts/publish-engine-failure-summary.py --ordinal 1 --architecture \'${{ matrix.architecture }}\'\n        if ($LASTEXITCODE -ne 0) { throw \'Closed supplemental engine summary was not collected.\' }\n    - name: Upload first closed engine failure summary\n      id: engine-summary-first-evidence\n      if: "always() && steps.engine-summary-first-validation.outcome == \'success\'"\n      uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02\n      with:\n        name: opengeul-suite-engine-summary-first-${{ matrix.architecture }}-${{ github.run_id }}-${{ github.run_attempt }}\n        path: .work/suite-engine-summary-first/\n        retention-days: 1\n        if-no-files-found: error\n'
ENGINE_SUMMARY_REPEATED_BLOCK = '    - name: Validate repeated closed engine failure summary\n      id: engine-summary-repeated-validation\n      if: "always() && steps.build.outcome == \'success\' && (steps.engine-repeat.outcome == \'success\' || steps.engine-repeat.outcome == \'failure\' || steps.engine-repeat.outcome == \'cancelled\')"\n      shell: pwsh\n      run: |\n        python -B suite/scripts/publish-engine-failure-summary.py --ordinal 2 --architecture \'${{ matrix.architecture }}\'\n        if ($LASTEXITCODE -ne 0) { throw \'Closed supplemental engine summary was not collected.\' }\n    - name: Upload repeated closed engine failure summary\n      id: engine-summary-repeated-evidence\n      if: "always() && steps.engine-summary-repeated-validation.outcome == \'success\'"\n      uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02\n      with:\n        name: opengeul-suite-engine-summary-repeated-${{ matrix.architecture }}-${{ github.run_id }}-${{ github.run_attempt }}\n        path: .work/suite-engine-summary-repeated/\n        retention-days: 1\n        if-no-files-found: error\n'
ENGINE_SUMMARY_FIRST_BEFORE = '      id: fixtures\n      if: "!cancelled() && steps.build.outcome == \'success\' && env.OPENGEUL_SUITE_RUN_MODE != \'reader-console-diagnostic\'"\n'
ENGINE_SUMMARY_FIRST_AFTER = '    - name: 여섯 모듈 native 메뉴·키보드·포커스 실제 검증\n'
ENGINE_SUMMARY_REPEATED_BEFORE = '      if: "env.OPENGEUL_SUITE_RUN_MODE == \'acceptance\' && (!cancelled() && steps.build.outcome == \'success\')"\n'
ENGINE_SUMMARY_REPEATED_AFTER = '    - name: 모든 네이티브 진단 보존·해시와 크래시 부재 확인\n'
ENGINE_SUMMARY_REPEAT_NAME = '    - name: 새 문서 집합으로 전체 UI·E2E를 두 번째 독립 실행\n'


def _without_engine_summary_artifacts(normal):
    signals=('engine-summary-first-', 'engine-summary-repeated-', '      id: engine-repeat\n',
             'suite/scripts/publish-engine-failure-summary.py')
    if not any(value in normal for value in signals):return normal
    for block,before,after in ((ENGINE_SUMMARY_FIRST_BLOCK,ENGINE_SUMMARY_FIRST_BEFORE,ENGINE_SUMMARY_FIRST_AFTER),
                               (ENGINE_SUMMARY_REPEATED_BLOCK,ENGINE_SUMMARY_REPEATED_BEFORE,ENGINE_SUMMARY_REPEATED_AFTER)):
        if normal.count(block)!=1 or normal.count(before+block+after)!=1:
            raise ValueError('Reviewed supplemental summary delta differs')
    tagged=ENGINE_SUMMARY_REPEAT_NAME+'      id: engine-repeat\n'
    if normal.count(tagged)!=1 or normal.count('      id: engine-repeat\n')!=1:
        raise ValueError('Reviewed repeated engine step identity differs')
    normal=normal.replace(ENGINE_SUMMARY_FIRST_BLOCK,'',1).replace(ENGINE_SUMMARY_REPEATED_BLOCK,'',1)
    return normal.replace(tagged,ENGINE_SUMMARY_REPEAT_NAME,1)
