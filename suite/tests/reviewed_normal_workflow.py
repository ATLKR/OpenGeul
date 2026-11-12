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
    changes = ((CURRENT_NORMAL_IF, '    if: github.event.repository.private == false\n'),
        (EXACT_SDK_SETUP, ''),
        (CURRENT_PILLOW_INSTALL, '        python -m pip install Pillow==12.3.0\n'),
        (EXACT_YAML_SETUP, ''))
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
