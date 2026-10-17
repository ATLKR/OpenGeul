"""Exact Microsoft VC runtime families for native Suite architectures.

The ARM64 family excludes the x64-header hybrid exception-runtime companion. Every admitted
file still needs its normal architecture, source and signature validation.
"""

from pathlib import Path
import re
import stat
import struct

_X64 = ('concrt140.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
        'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll', 'vcruntime140.dll',
        'vcruntime140_1.dll', 'vcruntime140_threads.dll')
_ARM64 = tuple(name for name in _X64 if name != 'vcruntime140_1.dll')


def crt_names(architecture: str = 'x64') -> tuple[str, ...]:
    """Return the complete exact family; the public default remains x64."""
    if architecture == 'x64':
        return _X64
    if architecture == 'arm64':
        return _ARM64
    raise ValueError('Unsupported native CRT architecture: '+str(architecture))


_VC_IMPORT = re.compile(r'(?:concrt|msvcp|vcruntime|vccorlib|msvcr|msvcm)[0-9][a-z0-9_.-]*\Z')
_VC_CRT = re.compile(r'(?:concrt|msvcp|vcruntime|vccorlib|msvcr|msvcm)[0-9][a-z0-9_]*\.dll\Z')


def is_vc_crt_file(name: str) -> bool:
    return _VC_CRT.fullmatch(name.casefold()) is not None


def _regular(path: Path, *, directory: bool = False):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError('CRT import audit requires unlinked regular paths: '+str(path))


def _machine(path: Path) -> int:
    with path.open('rb') as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise ValueError('Invalid PE during CRT import audit: '+str(path))
        offset = struct.unpack_from('<I', header, 60)[0]
        if not 64 <= offset <= min(1024*1024, path.stat().st_size-6):
            raise ValueError('Invalid PE offset during CRT import audit: '+str(path))
        stream.seek(offset); signature = stream.read(6)
        if len(signature) != 6 or signature[:4] != b'PE\0\0':
            raise ValueError('Invalid PE signature during CRT import audit: '+str(path))
        return struct.unpack_from('<H', signature, 4)[0]


def validate_crt_imports(root: Path, *, architecture: str = 'x64') -> dict:
    """Audit normal/delayed VC imports in an independently architecture-audited tree.

    This validates native image dependencies and the exact private CRT family;
    the caller must also enforce its full native/AnyCPU/template PE policy and
    authenticate CRT signatures, versions and bytes. It does not infer product
    qualification from a CRT diagnostic or silently omit a required DLL.
    """
    expected = crt_names(architecture)
    native = {'x64': 0x8664, 'arm64': 0xaa64}[architecture]
    root = Path(root).absolute()
    for directory in (root, *root.parents):
        _regular(directory, directory=True)
    program = root/'program'; _regular(program, directory=True)
    for name in expected:
        path = program/name
        try:
            _regular(path)
            if _machine(path) != native:
                raise ValueError('CRT must have the exact native PE machine')
        except (OSError, ValueError) as error:
            raise ValueError('Missing or non-native private CRT: '+name) from error
    try:
        from suite.pe_imports import read_pe_imports
    except ModuleNotFoundError:
        from pe_imports import read_pe_imports
    checked = 0; records = []; count = 0
    for path in sorted(root.rglob('*'), key=lambda path: path.relative_to(root).as_posix()):
        count += 1
        if count > 100_000:
            raise ValueError('CRT import audit exceeds its entry bound')
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400:
            continue
        _regular(path)
        name = path.name.casefold()
        relative = path.relative_to(root).as_posix()
        if is_vc_crt_file(name) and (name not in expected or path.parent != program):
            raise ValueError('Unexpected private CRT family/path: '+relative)
        with path.open('rb') as stream:
            magic = stream.read(2)
        if magic != b'MZ' and path.suffix.casefold() not in ('.exe', '.dll', '.pyd') and name != 'soffice.bin':
            continue
        if _machine(path) != native:
            # The independent whole-tree PE gate handles AnyCPU and pinned
            # unexecuted cross-platform templates. They are not native hosts.
            continue
        try:
            imports = read_pe_imports(path)
        except ValueError as error:
            raise ValueError('CRT import audit failed for '+relative+': '+str(error)) from error
        checked += 1
        selected = {}
        for kind in ('normal', 'delay'):
            selected[kind] = [name for name in imports[kind] if _VC_IMPORT.fullmatch(name)]
            unexpected = set(selected[kind])-set(expected)
            if unexpected:
                raise ValueError('Unsupported '+architecture+' '+kind+' CRT import in '+relative+': '+', '.join(sorted(unexpected)))
        if selected['normal'] or selected['delay']:
            records.append(dict(path=relative, **selected))
    if not checked:
        raise ValueError('CRT import audit contains no native PE images')
    return dict(schemaVersion=1, architecture=architecture, passed=True,
                requiredCrtFiles=list(expected), checkedPeCount=checked, imports=records)


def main(argv=None):
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--architecture', choices=('x64', 'arm64'), default='x64')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    proof = validate_crt_imports(args.root, architecture=args.architecture)
    for directory in (args.output.absolute().parent, *args.output.absolute().parent.parents):
        _regular(directory, directory=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(proof, stream, indent=2); stream.write('\n')


if __name__ == '__main__':
    main()
