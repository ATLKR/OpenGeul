"""Normalize only reviewed dependency edits for the frozen historical test oracle.

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
    return normal
