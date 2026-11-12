"""Inventory independent native Windows Suites without changing HWP release contracts.

The receipt proves byte consistency against its trusted input, not authorship or
GUI correctness. The package builder verifies the locked upstream downloads.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
from urllib.parse import urlsplit
import zipfile


INVENTORY = 'suite-inventory.json'
WRITER_OBSERVER_MARKERS = frozenset({'writer-server-observer-diagnostic.json',
    'office/program/opengeul-writer-server-observer-diagnostic.json'})
REQUIRED = frozenset({
    'OpenGeul.Office.exe', 'OpenGeul.Office.dll', 'suite-product.json',
    'suite-provenance.json', 'runtime-branding.json', 'Office/opengeul-branding.json',
    'Office/program/soffice.exe', 'Office/program/soffice.bin', 'Office/program/python.exe',
    'worker/office_worker.py', 'worker/session.py', 'worker/native.py',
    'worker/native_windows.py', 'worker/dispatch.py', 'worker/calc_save.py',
    'worker/calc_close.py', 'worker/save_diagnostics.py', 'worker/native_diagnostics.py',
    'Notices/OpenGeul-Office-LICENSE.txt',
    'Notices/LibreOffice-LICENSE.txt', 'Notices/CORRESPONDING_SOURCE.md',
    'Sources/OpenGeul-Office-source.zip',
})
ROOT_FILES = frozenset({
    'OpenGeul.Office.exe', 'suite-product.json', 'suite-provenance.json',
    'runtime-branding.json', INVENTORY, 'OpenGeul.Office.deps.json',
    'OpenGeul.Office.runtimeconfig.json', 'createdump.exe',
    'README.txt',
})
DIRECTORIES = frozenset({'Office', 'worker', 'Notices', 'HWP', 'Sources'})
SHA = re.compile(r'[0-9a-f]{64}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}\Z')
VERSION = re.compile(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?\Z')
RESERVED = re.compile(r'(?i)(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?\Z')
CULTURE = re.compile(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\Z')
MAX_FILES = 100_000
MAX_METADATA = 8 * 1024 * 1024
NATIVE_MACHINES = {'x64': 0x8664, 'arm64': 0xaa64}
SOURCE_LOCKS = {'x64': 'suite/config/runtime.lock.json',
                'arm64': 'suite/config/runtime.arm64.lock.json'}
# Exact companion bytes from the authenticated LibreOffice 26.8.1.1 x64 MSI:
# c6298b10cfa1748bcbedad94c62ce771e240e5021bfd6d7a967cd571b04b5312.
# These optional compatibility components and Python cross-platform launcher
# templates are not Suite native hosts. New paths/versions require review.
# Inventory schema stays unchanged: every admitted asset still has its full hash.
COMPANION_PE_ADMISSIONS = {
    'Office/program/twain32shim.exe': {
        'machine': 0x14c, 'role': 'x86CompatibilityHelper',
        'sha256': 'e8c0e07120c789b8c59e6723a9b11d638982805549d46247566847dd7b51a06e'},
    'Office/program/spsupp_x86.dll': {
        'machine': 0x14c, 'role': 'x86CompatibilityHelper',
        'sha256': '79f39ee0c430d9129dc33905f47d5d89b87a2268055807888fcee77d239119c9'},
    'Office/program/policy.1.0.cli_cppuhelper.dll': {
        'machine': 0x14c, 'role': 'managedPublisherPolicy',
        'sha256': 'b72b73d325847ecb8dae62bead73b58d9c79dd718d797664bcfde790753dcb00'},
    'Office/program/python-core-3.13.15/lib/setuptools/gui-32.exe': {
        'machine': 0x14c, 'role': 'pythonLauncherTemplate',
        'sha256': '85dae1e95d77845f2cb59bcac3d4afe74bbe4c91a9bcc5bf4a71cd43104dbe7c'},
    'Office/program/python-core-3.13.15/lib/setuptools/gui.exe': {
        'machine': 0x14c, 'role': 'pythonLauncherTemplate',
        'sha256': '85dae1e95d77845f2cb59bcac3d4afe74bbe4c91a9bcc5bf4a71cd43104dbe7c'},
    'Office/program/python-core-3.13.15/lib/setuptools/cli.exe': {
        'machine': 0x14c, 'role': 'pythonLauncherTemplate',
        'sha256': '32acc1bc543116cbe2cff10cb867772df2f254ff2634c870aef0b46c4b696fdb'},
    'Office/program/python-core-3.13.15/lib/setuptools/gui-arm64.exe': {
        'machine': 0xaa64, 'role': 'pythonLauncherTemplate',
        'sha256': 'e694f4743405c8b5926ff457db6fe7f1a12dec7c16a9c3864784d3f4e07ae097'},
    'Office/program/python-core-3.13.15/lib/setuptools/cli-32.exe': {
        'machine': 0x14c, 'role': 'pythonLauncherTemplate',
        'sha256': '32acc1bc543116cbe2cff10cb867772df2f254ff2634c870aef0b46c4b696fdb'},
    'Office/program/python-core-3.13.15/lib/setuptools/cli-arm64.exe': {
        'machine': 0xaa64, 'role': 'pythonLauncherTemplate',
        'sha256': 'b9a7d08da880dfac8bcf548eba4b06fb59b6f09b17d33148a0f6618328926c61'},
    'Office/program/python-core-3.13.15/lib/pip/_vendor/distlib/t64-arm.exe': {
        'machine': 0xaa64, 'role': 'pythonLauncherTemplate',
        'sha256': 'ebc4c06b7d95e74e315419ee7e88e1d0f71e9e9477538c00a93a9ff8c66a6cfc'},
    'Office/program/python-core-3.13.15/lib/pip/_vendor/distlib/w32.exe': {
        'machine': 0x14c, 'role': 'pythonLauncherTemplate',
        'sha256': '47872cc77f8e18cf642f868f23340a468e537e64521d9a3a416c8b84384d064b'},
    'Office/program/python-core-3.13.15/lib/pip/_vendor/distlib/w64-arm.exe': {
        'machine': 0xaa64, 'role': 'pythonLauncherTemplate',
        'sha256': 'c5dc9884a8f458371550e09bd396e5418bf375820a31b9899f6499bf391c7b2e'},
    'Office/program/python-core-3.13.15/lib/pip/_vendor/distlib/t32.exe': {
        'machine': 0x14c, 'role': 'pythonLauncherTemplate',
        'sha256': '6b4195e640a85ac32eb6f9628822a622057df1e459df7c17a12f97aeabc9415b'},
}


# ARM64 exceptions require their own exact path/machine/hash review. Do not
# inherit x64 compatibility helpers or assume that similarly named ARM64 MSI
# companions have identical bytes. Unknown non-native assets fail closed.
ARM64_COMPANION_PE_ADMISSIONS = {
    'Office/program/python-core-3.13.15/lib/pip/_vendor/distlib/t32.exe': {
        'machine': 0x14c, 'role': 'pythonLauncherTemplate',
        'sha256': '6b4195e640a85ac32eb6f9628822a622057df1e459df7c17a12f97aeabc9415b'},
    'Office/program/python-core-3.13.15/lib/pip/_vendor/distlib/t64.exe': {
        'machine': 0x8664, 'role': 'pythonLauncherTemplate',
        'sha256': '81a618f21cb87db9076134e70388b6e9cb7c2106739011b6a51772d22cae06b7'},
    'Office/program/python-core-3.13.15/lib/pip/_vendor/distlib/w32.exe': {
        'machine': 0x14c, 'role': 'pythonLauncherTemplate',
        'sha256': '47872cc77f8e18cf642f868f23340a468e537e64521d9a3a416c8b84384d064b'},
    'Office/program/python-core-3.13.15/lib/pip/_vendor/distlib/w64.exe': {
        'machine': 0x8664, 'role': 'pythonLauncherTemplate',
        'sha256': '7a319ffaba23a017d7b1e18ba726ba6c54c53d6446db55f92af53c279894f8ad'},
    'Office/program/python-core-3.13.15/lib/setuptools/cli-32.exe': {
        'machine': 0x14c, 'role': 'pythonLauncherTemplate',
        'sha256': '32acc1bc543116cbe2cff10cb867772df2f254ff2634c870aef0b46c4b696fdb'},
    'Office/program/python-core-3.13.15/lib/setuptools/cli-64.exe': {
        'machine': 0x8664, 'role': 'pythonLauncherTemplate',
        'sha256': 'bbb3de5707629e6a60a0c238cd477b28f07f0066982fda953fa6fcec39073a4a'},
    'Office/program/python-core-3.13.15/lib/setuptools/cli.exe': {
        'machine': 0x14c, 'role': 'pythonLauncherTemplate',
        'sha256': '32acc1bc543116cbe2cff10cb867772df2f254ff2634c870aef0b46c4b696fdb'},
    'Office/program/python-core-3.13.15/lib/setuptools/gui-32.exe': {
        'machine': 0x14c, 'role': 'pythonLauncherTemplate',
        'sha256': '85dae1e95d77845f2cb59bcac3d4afe74bbe4c91a9bcc5bf4a71cd43104dbe7c'},
    'Office/program/python-core-3.13.15/lib/setuptools/gui-64.exe': {
        'machine': 0x8664, 'role': 'pythonLauncherTemplate',
        'sha256': '3471b6140eadc6412277dbbefe3fef8c345a0f1a59776086b80a3618c3a83e3b'},
    'Office/program/python-core-3.13.15/lib/setuptools/gui.exe': {
        'machine': 0x14c, 'role': 'pythonLauncherTemplate',
        'sha256': '85dae1e95d77845f2cb59bcac3d4afe74bbe4c91a9bcc5bf4a71cd43104dbe7c'},
}


# Exact nonexecuted templates from Python-3.13.17.tar.xz, authenticated by
# LibreOffice core 9dea406ab7695df6325b11b0e19fdca8db4b7276 download.lst:
# SHA256 6020bd10aff3bf4821be16f088ebb1591beb7b811dcd8fab1da8f7c22a7b27e7.
# The Python pre-action extracts setuptools 79.0.1 and pip 26.2.2 wheels;
# ExternalPackage_python3.mk explicitly packages these fourteen members.
PYTHON17_PE_TEMPLATES = {
    'Office/program/python-core-3.13.17/lib/setuptools/cli-32.exe': {
        'machine': 332, 'role': 'pythonLauncherTemplate',
        'sha256': '32acc1bc543116cbe2cff10cb867772df2f254ff2634c870aef0b46c4b696fdb'},
    'Office/program/python-core-3.13.17/lib/setuptools/cli-64.exe': {
        'machine': 34404, 'role': 'pythonLauncherTemplate',
        'sha256': 'bbb3de5707629e6a60a0c238cd477b28f07f0066982fda953fa6fcec39073a4a'},
    'Office/program/python-core-3.13.17/lib/setuptools/cli-arm64.exe': {
        'machine': 43620, 'role': 'pythonLauncherTemplate',
        'sha256': 'b9a7d08da880dfac8bcf548eba4b06fb59b6f09b17d33148a0f6618328926c61'},
    'Office/program/python-core-3.13.17/lib/setuptools/cli.exe': {
        'machine': 332, 'role': 'pythonLauncherTemplate',
        'sha256': '32acc1bc543116cbe2cff10cb867772df2f254ff2634c870aef0b46c4b696fdb'},
    'Office/program/python-core-3.13.17/lib/setuptools/gui-32.exe': {
        'machine': 332, 'role': 'pythonLauncherTemplate',
        'sha256': '85dae1e95d77845f2cb59bcac3d4afe74bbe4c91a9bcc5bf4a71cd43104dbe7c'},
    'Office/program/python-core-3.13.17/lib/setuptools/gui-64.exe': {
        'machine': 34404, 'role': 'pythonLauncherTemplate',
        'sha256': '3471b6140eadc6412277dbbefe3fef8c345a0f1a59776086b80a3618c3a83e3b'},
    'Office/program/python-core-3.13.17/lib/setuptools/gui-arm64.exe': {
        'machine': 43620, 'role': 'pythonLauncherTemplate',
        'sha256': 'e694f4743405c8b5926ff457db6fe7f1a12dec7c16a9c3864784d3f4e07ae097'},
    'Office/program/python-core-3.13.17/lib/setuptools/gui.exe': {
        'machine': 332, 'role': 'pythonLauncherTemplate',
        'sha256': '85dae1e95d77845f2cb59bcac3d4afe74bbe4c91a9bcc5bf4a71cd43104dbe7c'},
    'Office/program/python-core-3.13.17/lib/pip/_vendor/distlib/t32.exe': {
        'machine': 332, 'role': 'pythonLauncherTemplate',
        'sha256': '6b4195e640a85ac32eb6f9628822a622057df1e459df7c17a12f97aeabc9415b'},
    'Office/program/python-core-3.13.17/lib/pip/_vendor/distlib/t64-arm.exe': {
        'machine': 43620, 'role': 'pythonLauncherTemplate',
        'sha256': 'ebc4c06b7d95e74e315419ee7e88e1d0f71e9e9477538c00a93a9ff8c66a6cfc'},
    'Office/program/python-core-3.13.17/lib/pip/_vendor/distlib/t64.exe': {
        'machine': 34404, 'role': 'pythonLauncherTemplate',
        'sha256': '81a618f21cb87db9076134e70388b6e9cb7c2106739011b6a51772d22cae06b7'},
    'Office/program/python-core-3.13.17/lib/pip/_vendor/distlib/w32.exe': {
        'machine': 332, 'role': 'pythonLauncherTemplate',
        'sha256': '47872cc77f8e18cf642f868f23340a468e537e64521d9a3a416c8b84384d064b'},
    'Office/program/python-core-3.13.17/lib/pip/_vendor/distlib/w64-arm.exe': {
        'machine': 43620, 'role': 'pythonLauncherTemplate',
        'sha256': 'c5dc9884a8f458371550e09bd396e5418bf375820a31b9899f6499bf391c7b2e'},
    'Office/program/python-core-3.13.17/lib/pip/_vendor/distlib/w64.exe': {
        'machine': 34404, 'role': 'pythonLauncherTemplate',
        'sha256': '7a319ffaba23a017d7b1e18ba726ba6c54c53d6446db55f92af53c279894f8ad'},
}

_PYTHON_TEMPLATE_SOURCES = {
    'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1': {
        'version': '26.8.1.1',
        'sourceUrl': 'https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-26.8.1.1.tar.xz',
        'sourceSha256': '296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785'},
    '9dea406ab7695df6325b11b0e19fdca8db4b7276': {
        'version': '26.8.2.2',
        'sourceUrl': 'https://download.documentfoundation.org/libreoffice/src/26.8.2/libreoffice-26.8.2.2.tar.xz',
        'sourceSha256': 'f0012302d9cc70955bd55890d3aaccf6c55677c4a6a46e1003f996b1b0dae8e7'},
}


def _architecture(architecture: str) -> str:
    if not isinstance(architecture, str) or architecture not in NATIVE_MACHINES:
        raise ValueError(f'Unsupported Suite architecture: {architecture!r}')
    return architecture


def _python_template_admissions(core_commit: str, architecture: str, version: str) -> dict:
    """Select only reviewed foreign templates for one exact source core/version."""
    architecture = _architecture(architecture)
    if (not isinstance(core_commit, str) or core_commit not in _PYTHON_TEMPLATE_SOURCES
            or version != _PYTHON_TEMPLATE_SOURCES[core_commit]['version']):
        raise ValueError('Python templates require an exact reviewed source core/version')
    if core_commit == '9dea406ab7695df6325b11b0e19fdca8db4b7276':
        pins = PYTHON17_PE_TEMPLATES
    else:
        pins = (COMPANION_PE_ADMISSIONS if architecture == 'x64'
                else ARM64_COMPANION_PE_ADMISSIONS)
    return {name: dict(pin) for name, pin in pins.items()
            if pin['role'] == 'pythonLauncherTemplate'
            and pin['machine'] != NATIVE_MACHINES[architecture]}


def _source_python_template_admissions(runtime: dict, architecture: str) -> dict:
    """Require the validated source-built runtime's exact archive identity."""
    if not isinstance(runtime, dict) or runtime.get('format') != 'source-built-zip':
        raise ValueError('Python source template admission requires a source-built runtime')
    pins = _python_template_admissions(runtime.get('sourceCoreCommit'), architecture,
                                       runtime.get('version'))
    source = _PYTHON_TEMPLATE_SOURCES[runtime['sourceCoreCommit']]
    if any(runtime.get(key) != source[key] for key in ('sourceUrl', 'sourceSha256')):
        raise ValueError('Python source template archive identity differs from the reviewed core')
    return pins


def _name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError('Payload path must be a string')
    parts = name.split('/')
    if (not parts or '\\' in name or any(p in ('', '.', '..') or p.rstrip(' .') != p
            or RESERVED.fullmatch(p) for p in parts)
            or any(ord(c) < 32 or ord(c) == 127 or c in ':<>"|?*' for c in name)):
        raise ValueError(f'Unsafe Windows payload path: {name!r}')
    return name


def _kind(path: Path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError(f'Payload symlink/reparse point: {path}')
    return info


def _layout(name: str, *, directory=False):
    parts = name.split('/')
    if len(parts) == 1:
        if directory and (name in DIRECTORIES or CULTURE.fullmatch(name)):
            return
        if not directory and (name in ROOT_FILES or Path(name).suffix.lower() in ('.dll', '.pdb', '.json', '.exe', '.config', '.xml')):
            return
    elif len(parts) == 2 and CULTURE.fullmatch(parts[0]) and not directory and parts[1].endswith('.resources.dll'):
        return
    elif parts[0] in DIRECTORIES:
        if parts[0] == 'Sources':
            if not directory and name == 'Sources/OpenGeul-Office-source.zip':
                return
            raise ValueError(f'Unexpected Suite source payload path: {name}')
        if parts[0] != 'worker' or (not directory and len(parts) == 2 and name.endswith('.py')):
            return
    raise ValueError(f'Unexpected Suite payload path: {name}')


def _hash(path: Path) -> str:
    before = _kind(path)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f'Payload requires regular files: {path}')
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    after = _kind(path)
    if any(getattr(before, field) != getattr(after, field)
           for field in ('st_size', 'st_mtime_ns', 'st_dev', 'st_ino')):
        raise ValueError(f'Payload changed during hashing: {path}')
    return result.hexdigest()


def _reject_writer_observer(root: Path):
    root = Path(root).absolute()
    for part in (*reversed(root.parents), root):
        _kind(part)
    def matching(folder, name):
        if not folder.is_dir(): return []
        with os.scandir(folder) as entries:
            return [folder/entry.name for entry in entries if entry.name.casefold()==name]
    if matching(root, 'writer-server-observer-diagnostic.json'):
        raise ValueError('Writer observer diagnostic cannot enter a normal Suite payload')
    for office in matching(root, 'office'):
        _kind(office)
        for program in matching(office, 'program'):
            _kind(program)
            if matching(program, 'opengeul-writer-server-observer-diagnostic.json'):
                raise ValueError('Writer observer diagnostic cannot enter a normal Suite payload')


def _scan(root: Path) -> dict:
    _reject_writer_observer(root)
    root = Path(root).absolute()
    for parent in (*reversed(root.parents), root):
        _kind(parent)
    if not stat.S_ISDIR(_kind(root).st_mode):
        raise ValueError('Payload root must be a directory')
    files, aliases = {}, set()

    def visit(folder):
        with os.scandir(folder) as entries:
            names = sorted(entry.name for entry in entries)
        for basename in names:
            path = folder/basename
            name = _name(path.relative_to(root).as_posix())
            key = name.casefold()
            if key in aliases:
                raise ValueError(f'Case-aliased payload path collision: {name}')
            aliases.add(key)
            info = _kind(path)
            directory = stat.S_ISDIR(info.st_mode)
            _layout(name, directory=directory)
            if directory:
                visit(path)
            elif stat.S_ISREG(info.st_mode):
                if len(files) >= MAX_FILES:
                    raise ValueError('Suite payload file count exceeds limit')
                if name != INVENTORY:
                    files[name] = {'size': info.st_size, 'sha256': _hash(path)}
            else:
                raise ValueError(f'Payload special file: {name}')

    visit(root)
    missing = REQUIRED - files.keys()
    if missing:
        raise ValueError('Missing required Suite payload files: '+', '.join(sorted(missing)))
    if any(files[name]['size'] == 0 for name in REQUIRED):
        raise ValueError('Required Suite payload files cannot be empty')
    return dict(sorted(files.items()))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate payload JSON key: {key}')
        result[key] = value
    return result


def _json_bytes(data: bytes, label: str) -> dict:
    try:
        result = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_pairs,
                            parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Invalid payload JSON: {label}') from error
    if not isinstance(result, dict):
        raise ValueError(f'Payload JSON must be an object: {label}')
    return result


def _json(path: Path) -> dict:
    info = _kind(path)
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_METADATA:
        raise ValueError(f'Invalid payload JSON size or kind: {path.name}')
    return _json_bytes(path.read_bytes(), path.name)


def _sha(value) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _https(value) -> bool:
    if not isinstance(value, str) or any(ord(c) <= 32 for c in value):
        return False
    try:
        url = urlsplit(value)
        return url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password
    except ValueError:
        return False


def _source_archive(root: Path, provenance: dict, *, architecture: str):
    path = root/'Sources/OpenGeul-Office-source.zip'
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.comment != provenance['sourceCommit'].encode('ascii'):
                raise ValueError('Suite source archive Git commit differs from provenance')
            entries = archive.infolist()
            if not entries or len(entries) > MAX_FILES or sum(entry.file_size for entry in entries) > 512*1024*1024:
                raise ValueError('Suite source archive exceeds size/count limits')
            aliases, has_code = set(), False
            for entry in entries:
                name = _name(entry.filename.rstrip('/'))
                kind = stat.S_IFMT(entry.external_attr >> 16)
                if (name.casefold() in aliases or kind not in (0, stat.S_IFREG, stat.S_IFDIR)
                        or entry.flag_bits & 1 or entry.file_size > 128*1024*1024):
                    raise ValueError(f'Unsafe Suite source archive member: {name}')
                aliases.add(name.casefold())
                has_code |= name.startswith('suite/') and name.endswith(('.py', '.cs')) and entry.file_size > 0
            if not has_code:
                raise ValueError('Suite source archive contains no Suite implementation source')
            name = SOURCE_LOCKS[architecture]
            if archive.getinfo(name).file_size > MAX_METADATA:
                raise ValueError('Packaged Suite runtime lock exceeds metadata limit')
            lock = _json_bytes(archive.read(name), name)
    except (zipfile.BadZipFile, KeyError, OSError) as error:
        raise ValueError('Invalid Suite corresponding-source archive') from error
    locked_runtime = lock.get('runtime')
    source_built = (provenance['runtime'].get('format') == 'source-built-zip'
                    or isinstance(locked_runtime, dict) and locked_runtime.get('format') == 'source-built-zip')
    if (lock.get('schemaVersion') != 1 or lock.get('architecture') != architecture
            or lock.get('version') != provenance['version'] or not isinstance(lock.get('runtime'), dict)
            or any(lock['runtime'].get(key) != provenance['runtime'].get(key)
                   for key in ('sha256', 'url', 'sourceUrl', 'sourceSha256'))
            or source_built and locked_runtime != provenance['runtime']):
        raise ValueError('Suite runtime/source provenance differs from its packaged source lock')
    if provenance.get('hwp') is not None and (not isinstance(lock.get('hwp'), dict)
            or any(lock['hwp'].get(key) != provenance['hwp'].get(key) for key in ('sha256', 'url'))):
        raise ValueError('Suite HWP provenance differs from its packaged source lock')


def _metadata(root: Path, files: dict, *, architecture: str):
    product, provenance = (_json(root/name) for name in ('suite-product.json', 'suite-provenance.json'))
    if provenance.get('architecture') != architecture:
        raise ValueError('Suite provenance architecture differs from payload architecture')
    if (type(product.get('schemaVersion')) is not int or product['schemaVersion'] != 1
            or product.get('productName') != 'OpenGeul Office'
            or product.get('version') != provenance.get('version')):
        raise ValueError('Suite product identity/version differs from provenance')
    if (type(provenance.get('schemaVersion')) is not int or provenance['schemaVersion'] != 1
            or provenance.get('productName') != 'OpenGeul Office'
            or not isinstance(provenance.get('version'), str) or not VERSION.fullmatch(provenance['version'])
            or not isinstance(provenance.get('sourceCommit'), str) or not COMMIT.fullmatch(provenance['sourceCommit'])):
        raise ValueError('Invalid Suite source/version provenance')
    for field, name in (('sourceArchiveSha256', 'Sources/OpenGeul-Office-source.zip'),
                        ('brandingReceiptSha256', 'runtime-branding.json')):
        if not _sha(provenance.get(field)) or provenance[field] != files[name]['sha256']:
            raise ValueError('Suite source/branding provenance hash mismatch: '+field)
    runtime = provenance.get('runtime')
    if (not isinstance(runtime, dict) or not _sha(runtime.get('sha256')) or not _sha(runtime.get('sourceSha256'))
            or not _https(runtime.get('url')) or not _https(runtime.get('sourceUrl'))):
        raise ValueError('Invalid Suite runtime input/source provenance')
    hwp_files = any(name.startswith('HWP/') for name in files)
    if hwp_files:
        required = {'HWP/OpenGeul.exe', 'HWP/Tools/rhwp.exe', 'HWP/Notices/OpenGeul-LICENSE.txt'}
        hwp = provenance.get('hwp')
        if (not required <= files.keys() or not isinstance(hwp, dict)
                or not _sha(hwp.get('sha256')) or not _https(hwp.get('url'))):
            raise ValueError('Incomplete original HWP runtime/license/input provenance')
    elif provenance.get('hwp') is not None:
        raise ValueError('HWP provenance supplied without its payload')
    _source_archive(root, provenance, architecture=architecture)
    runtime_format = runtime.get('format', 'msi')
    if runtime_format == 'source-built-zip':
        try:
            from suite.prepare import validate_source_build_receipt, validate_source_build_runtime
        except ModuleNotFoundError:
            from prepare import validate_source_build_receipt, validate_source_build_runtime
        receipt_path = root/'Office/opengeul-source-build.json'
        if 'Office/opengeul-source-build.json' not in files:
            raise ValueError('Source-built runtime is missing its externally locked source-build receipt')
        proof = validate_source_build_receipt(runtime, receipt_path, architecture=architecture)
        validate_source_build_runtime(root/'Office', proof, architecture=architecture, branding=_json(root/'runtime-branding.json'), runtime=runtime)
        if 'Office/opengeul-msi-dependencies.json' in files:
            raise ValueError('Source-built runtime cannot claim an MSI extraction receipt')
    elif runtime_format != 'msi':
        raise ValueError('Unsupported Suite runtime format')
    branding = _json(root/'runtime-branding.json')
    if branding != _json(root/'Office/opengeul-branding.json'):
        raise ValueError('Root/runtime branding receipts differ')
    manifest_hash = hashlib.sha256(json.dumps(product, sort_keys=True, separators=(',', ':'),
                                             ensure_ascii=False).encode('utf-8')).hexdigest()
    source = branding.get('source')
    if (type(branding.get('schemaVersion')) is not int or branding['schemaVersion'] != 1
            or branding.get('productName') != 'OpenGeul Office'
            or branding.get('manifestSha256') != manifest_hash or not _sha(branding.get('inputTreeSha256'))
            or not isinstance(source, dict) or not isinstance(source.get('buildId'), str)
            or not COMMIT.fullmatch(source['buildId']) or not _https(source.get('sourceUrl'))
            or not isinstance(source.get('productKey'), str) or not source['productKey'].strip()):
        raise ValueError('Invalid runtime branding source/manifest receipt')
    changed, legal = branding.get('modifiedFiles'), branding.get('preservedLegalFiles')
    if not isinstance(changed, dict) or not changed or not isinstance(legal, dict) or not legal:
        raise ValueError('Missing branding modifications or preserved legal files')
    aliases = set()
    for name, record in changed.items():
        path = 'Office/'+_name(name)
        if (name.casefold() in aliases or not isinstance(record, dict)
                or set(record) != {'beforeSha256', 'sha256'}
                or (record['beforeSha256'] is not None and not _sha(record['beforeSha256']))
                or not _sha(record['sha256']) or path not in files or files[path]['sha256'] != record['sha256']):
            raise ValueError(f'Runtime branding modified file mismatch: {name}')
        aliases.add(name.casefold())
    for name, sha in legal.items():
        path = 'Office/'+_name(name)
        if (name.casefold() in aliases or not _sha(sha)
                or path not in files or files[path]['sha256'] != sha):
            raise ValueError(f'Preserved runtime legal file mismatch: {name}')
        aliases.add(name.casefold())
    return runtime


def _pe(path: Path, *, companion: dict | None = None, architecture: str = 'x64'):
    """Require native hosts; admit only explicitly pinned optional companions."""
    architecture = _architecture(architecture)
    size = path.stat().st_size
    with path.open('rb') as stream:
        def read(offset, length):
            if offset < 0 or length < 0 or offset+length > size:
                raise ValueError(f'Truncated PE image: {path.name}')
            stream.seek(offset)
            data = stream.read(length)
            if len(data) != length:
                raise ValueError(f'Truncated PE image: {path.name}')
            return data

        dos = read(0, 64)
        offset = struct.unpack_from('<I', dos, 60)[0]
        if dos[:2] != b'MZ' or not 64 <= offset <= 1024*1024:
            raise ValueError(f'Invalid PE image: {path.name}')
        header = read(offset, 24)
        if header[:4] != b'PE\0\0':
            raise ValueError(f'Invalid PE signature: {path.name}')
        machine, sections, _, _, _, optional_size, characteristics = struct.unpack_from('<HHIIIHH', header, 4)
        if not 1 <= sections <= 96 or not 96 <= optional_size <= 4096:
            raise ValueError(f'Invalid PE headers: {path.name}')
        optional = read(offset+24, optional_size)
        magic = struct.unpack_from('<H', optional)[0]
        section_data = read(offset+24+optional_size, sections*40)
        section_ranges = []
        for index in range(sections):
            _, rva, raw_size, raw_offset = struct.unpack_from('<IIII', section_data, index*40+8)
            if raw_offset+raw_size > size:
                raise ValueError(f'Truncated PE section: {path.name}')
            section_ranges.append((rva, raw_size, raw_offset))
        role = None
        if companion is not None:
            role = companion['role']
            expected_magic = 0x10b if companion['machine'] == 0x14c else 0x20b
            if (machine != companion['machine'] or magic != expected_magic
                    or _hash(path) != companion['sha256']
                    or role not in ('x86CompatibilityHelper', 'pythonLauncherTemplate', 'managedPublisherPolicy')
                    or (role != 'pythonLauncherTemplate' and machine != 0x14c)):
                raise ValueError(f'Pinned Office companion bytes/architecture mismatch: {path.name}')
            if role in ('x86CompatibilityHelper', 'pythonLauncherTemplate'):
                return
        if machine == NATIVE_MACHINES[architecture] and magic == 0x20b:
            return
        if machine != 0x14c or magic != 0x10b or path.suffix.lower() != '.dll' or not characteristics & 0x2000:
            raise ValueError(f'Payload code must use {architecture} architecture: {path.name}')

        def at_rva(rva, length):
            for start, raw_size, raw_offset in section_ranges:
                if start <= rva and rva+length <= start+raw_size:
                    return read(raw_offset+rva-start, length)
            raise ValueError(f'Invalid managed PE RVA: {path.name}')

        if optional_size < 96+15*8 or struct.unpack_from('<I', optional, 92)[0] < 15:
            raise ValueError(f'Non-{architecture} code is not an AnyCPU managed DLL: {path.name}')
        clr_rva, clr_size = struct.unpack_from('<II', optional, 96+14*8)
        if not clr_rva or clr_size < 72:
            raise ValueError(f'Non-{architecture} code lacks managed CLR metadata: {path.name}')
        clr = at_rva(clr_rva, 72)
        cb = struct.unpack_from('<I', clr)[0]
        metadata_rva, metadata_size, flags = struct.unpack_from('<III', clr, 8)
        # The pinned publisher policy is an upstream strong-named x86 assembly
        # (0x0b), not an AnyCPU host; retain its CLR metadata checks separately.
        invalid_flags = flags != 0xb if role == 'managedPublisherPolicy' else not flags & 1 or flags & (2 | 16 | 0x20000)
        if (cb < 72 or cb > clr_size or invalid_flags
                or metadata_size < 16 or at_rva(metadata_rva, metadata_size)[:4] != b'BSJB'):
            raise ValueError(f'Non-{architecture} DLL must be IL-only AnyCPU: {path.name}')


def _validate(root: Path, files: dict, *, architecture: str):
    if WRITER_OBSERVER_MARKERS & {name.casefold() for name in files}:
        raise ValueError('Writer observer diagnostic cannot enter a normal Suite payload')
    if {'office/program/opengeul-calc-dispatch-diagnostic.json',
            'calc-dispatch-diagnostic.json'} & {name.casefold() for name in files}:
        raise ValueError('Diagnostic engine cannot qualify a distributable Suite payload')
    runtime = _metadata(root, files, architecture=architecture)
    if runtime.get('format', 'msi') == 'source-built-zip':
        companions = _source_python_template_admissions(runtime, architecture)
        # _metadata already authenticated the normal Full receipt and whole runtime.
        if architecture=='x64' and runtime.get('sourceCoreCommit')==_SOURCE_COMPANION_CORE:
            try:
                from suite.prepare import validate_source_build_receipt
            except ModuleNotFoundError:
                from prepare import validate_source_build_receipt
            proof=validate_source_build_receipt(runtime,root/'Office/opengeul-source-build.json',architecture=architecture)
            companions=dict(companions,**{'Office/'+name:record for name,record in
                _source_companion_admissions(runtime,proof,architecture=architecture).items()})
    else:
        companions = (COMPANION_PE_ADMISSIONS if architecture == 'x64'
                      else ARM64_COMPANION_PE_ADMISSIONS)
    for name in files:
        path = root/name
        with path.open('rb') as stream:
            magic = stream.read(2)
        if magic == b'MZ' or path.suffix.lower() in ('.exe', '.dll', '.pyd') or name == 'Office/program/soffice.bin':
            try:
                _pe(path, companion=companions.get(name), architecture=architecture)
            except ValueError as error:
                raise ValueError(f'{name}: {error}') from error


def create_inventory(root: Path, *, architecture: str = 'x64') -> dict:
    """Validate staged native content and return its complete deterministic inventory.

    Only ``suite-inventory.json`` is excluded, so callers can write this receipt
    after creating it without introducing a circular hash.
    """
    architecture = _architecture(architecture)
    root = Path(root)
    files = _scan(root)
    _validate(root, files, architecture=architecture)
    return {'schemaVersion': 1, 'architecture': architecture, 'files': files}


def verify_payload(root: Path, receipt: dict) -> None:
    """Reject malformed receipts, file changes, missing/extra files and mixed code."""
    _reject_writer_observer(root)
    if (not isinstance(receipt, dict) or set(receipt) != {'schemaVersion', 'architecture', 'files'}
            or type(receipt['schemaVersion']) is not int or receipt['schemaVersion'] != 1
            or not isinstance(receipt['architecture'], str) or receipt['architecture'] not in NATIVE_MACHINES
            or not isinstance(receipt['files'], dict)
            or not receipt['files'] or len(receipt['files']) > MAX_FILES):
        raise ValueError('Invalid Suite inventory receipt')
    aliases = set()
    for name, record in receipt['files'].items():
        _name(name)
        if (name == INVENTORY or name.casefold() in aliases or not isinstance(record, dict)
                or set(record) != {'size', 'sha256'} or type(record['size']) is not int
                or record['size'] < 0 or not _sha(record['sha256'])):
            raise ValueError(f'Invalid Suite inventory file record: {name}')
        aliases.add(name.casefold())
    root = Path(root)
    actual = create_inventory(root, architecture=receipt['architecture'])
    if actual != receipt:
        raise ValueError('Suite payload does not match its complete inventory')
    inventory = root/INVENTORY
    if inventory.exists() and _json(inventory) != receipt:
        raise ValueError('Stored Suite inventory differs from supplied receipt')


# Exact original public core9dea inputs; metadata alone grants no runtime authority.
SOURCE_COMPANION_SOURCE_PINS = [{'bytes': 31916, 'gitBlob': '3a9b342e6d805541daed7fad5c82fa68dd73d7fe', 'path': 'Repository.mk', 'sha256': '987811db83fe6937d0d959bc602c3d7828c9c8569469eb56cc72c6cb3c47bc6a'}, {'bytes': 617, 'gitBlob': '7d01a7b020ed40730d5b444f1d758d47dd42007f', 'path': 'scp2/InstallModule_spsupp.mk', 'sha256': 'a5af6a9d18768b21b77faa7de35e87c31d35ecb52ea8eb161cfc6e8b8c2a5efa'}, {'bytes': 1879, 'gitBlob': 'ba1ec46020286eb722c2bbda91e1738d502c06ac', 'path': 'scp2/source/spsupp/module_spsupp.scp', 'sha256': '281d881eaa2ca541c43c4673ea49a5fde526c422f478122f4193c5ae4d10eb1e'}, {'bytes': 1067, 'gitBlob': 'c905118bef5849f60e638b8ac97d3183edb2757a', 'path': 'shell/Executable_spsupp_helper.mk', 'sha256': 'b96bc08051232b47ec5cdd9083fe4fa752e614fdb72149d4f4387d575cb2f407'}, {'bytes': 1444, 'gitBlob': '17183d8b92dabca94901efa7cb097b5391d089e8', 'path': 'shell/Library_spsupp_x86.mk', 'sha256': '68a515669d5730ef7ce4d23def0c288110b259ba01e89aa3bb3275d33b496c56'}, {'bytes': 2469, 'gitBlob': '58a598714a055f2058b1f7269f76ba0ed639d0b5', 'path': 'shell/Module_shell.mk', 'sha256': '062d0ccc982bb925b4d2119bc5ec9e8b1987a07854eb69980f72853e2837f4be'}, {'bytes': 18091, 'gitBlob': '701deef38f50bb566e3623c458638d116ace6ee9', 'path': 'shell/source/win32/spsupp/COMOpenDocuments.cxx', 'sha256': '4bafc6680d374c9b88b8dd145f2ac0f550da83e0b41344938bd0236b985946c8'}, {'bytes': 177, 'gitBlob': 'f6828a3e8d43c72d31c62f5f222a7bfa8a4a0a28', 'path': 'shell/source/win32/spsupp/spsupp.def', 'sha256': '8f7d97fafa4653525b766d502221948ed1d97ffe9d5e42069677169b418ddcd7'}, {'bytes': 5445, 'gitBlob': '45d5f47b13a1c066526ba389e2d2d10e941f15b2', 'path': 'shell/source/win32/spsupp/spsupp.idl', 'sha256': '750fc59aa7035aa468a3fa238438554a60d4150db650cbe2971694f645842ccb'}, {'bytes': 5099, 'gitBlob': 'ea82e041c19e161d298ffb6a63126d080c697dae', 'path': 'shell/source/win32/spsupp/spsuppServ.cxx', 'sha256': 'd20edcb195f5576e15cfb1691830d445b6da4de3de00838dc595910173823598'}, {'bytes': 16781, 'gitBlob': 'e58dc3974466f98667978b3ecde5a1e63752c345', 'path': 'solenv/gbuild/Library.mk', 'sha256': '1cab3987867b8e27fc395f1ef8145cfe6f791fa747f214aa69424e554b5e96d0'}, {'bytes': 111066, 'gitBlob': '3550b856dd60a597bb38df36aab6a30702686784', 'path': 'solenv/gbuild/LinkTarget.mk', 'sha256': '075c6497a70d1775374d552dad585aa01fb3eece14482f38386acb8900e3b1b8'}, {'bytes': 29428, 'gitBlob': '6e3a6da1a578bf66ca4bbd0377f86d3c4112a322', 'path': 'solenv/gbuild/platform/com_MSC_class.mk', 'sha256': 'e51a5e8469dadbee611142443f6056a43e0f0d194bae75f16428e45449fd9ada'}]

_SOURCE_COMPANION_CORE='9dea406ab7695df6325b11b0e19fdca8db4b7276'
_SOURCE_COMPANION_PATH='program/spsupp_x86.dll'
_SOURCE_COMPANION_EXPORTS=['DllCanUnloadNow','DllGetClassObject','DllInstall','DllRegisterServer','DllUnregisterServer']
_SOURCE_COMPANION_OS_IMPORTS=frozenset(('advapi32.dll','kernel32.dll','ole32.dll','oleaut32.dll','user32.dll','ntdll.dll','msvcrt.dll'))

def _source_companion_binding(value):
    keys={'sourceCommit','sourceTree','sourceRun','runAttempt','recipeSha256'}
    if (type(value) is not dict or set(value)!=keys
            or any(type(value[k]) is not str or not COMMIT.fullmatch(value[k]) for k in ('sourceCommit','sourceTree'))
            or type(value['sourceRun']) is not int or not 0<value['sourceRun']<2**63
            or type(value['runAttempt']) is not int or value['runAttempt']!=1
            or type(value['recipeSha256']) is not str or not SHA.fullmatch(value['recipeSha256'])):
        raise ValueError('Invalid source companion build binding')
    return value

def _source_companion_identity(value,path,machine,role=None):
    keys={'path','machine','size','sha256'} | ({'role'} if role else set())
    if (type(value) is not dict or set(value)!=keys or value['path']!=path
            or type(value['machine']) is not int or value['machine']!=machine
            or type(value['size']) is not int or not 64<=value['size']<=16*1024*1024
            or type(value['sha256']) is not str or not SHA.fullmatch(value['sha256'])
            or role and value['role']!=role):
        raise ValueError('Invalid exact source companion binary identity')

def _source_companion_component(component,build_binding):
    """Validate component consistency, never Full authentication or launch authority."""
    _source_companion_binding(build_binding)
    keys={'schemaVersion','kind','architecture','coreCommit','path','role','machine','size','sha256','buildBinding',
          'sourceIntent','sourceProofs','configuredX86','linkTarget','nativeHelper','installedArchive',
          'exports','imports','dependencyPolicy','fullEngineQualified','acceptanceEligible','guiVerified'}
    if (type(component) is not dict or set(component)!=keys or type(component['schemaVersion']) is not int
            or component['schemaVersion']!=1 or component['kind']!='source-built-x86-sharepoint-companion'
            or component['architecture']!='x64' or component['coreCommit']!=_SOURCE_COMPANION_CORE
            or component['path']!=_SOURCE_COMPANION_PATH or component['role']!='x86CompatibilityHelper'
            or type(component['machine']) is not int or component['machine']!=0x14c
            or type(component['size']) is not int or not 64<=component['size']<=16*1024*1024
            or type(component['sha256']) is not str or not SHA.fullmatch(component['sha256'])
            or component['sourceIntent']!='sharepoint-inproc-32bit-com-client'
            or component['configuredX86'] is not True
            or any(component[k] is not False for k in ('fullEngineQualified','acceptanceEligible','guiVerified'))):
        raise ValueError('Unreviewed source companion component')
    _source_companion_binding(component['buildBinding'])
    if component['buildBinding']!=build_binding:raise ValueError('Source companion belongs to a different build')
    if component['sourceProofs']!=SOURCE_COMPANION_SOURCE_PINS:raise ValueError('Source companion original source proof differs')
    target=component['linkTarget']
    if (type(target) is not dict or set(target)!={'path','size','sha256'}
            or target['path']!='workdir/LinkTarget/Library/spsupp_x86.dll'
            or type(target['size']) is not int or target['size']!=component['size']
            or target['sha256']!=component['sha256']):raise ValueError('Source companion linktarget differs from installed bytes')
    _source_companion_identity(component['nativeHelper'],'program/spsupp_helper.exe',0x8664,'nativeX64')
    archive=component['installedArchive']
    if (type(archive) is not dict or set(archive)!={'kind','size','sha256','stageReceiptSha256'} or archive['kind']!='main'
            or type(archive['size']) is not int or archive['size']<1
            or any(type(archive[k]) is not str or not SHA.fullmatch(archive[k]) for k in ('sha256','stageReceiptSha256'))):
        raise ValueError('Source companion installed archive proof differs')
    if component['exports']!=_SOURCE_COMPANION_EXPORTS:raise ValueError('Source companion COM exports differ')
    imports=component['imports']
    if type(imports) is not dict or set(imports)!={'normal','delay'}:raise ValueError('Missing source companion import observations')
    for values in imports.values():
        if (type(values) is not list or any(type(n) is not str or n not in _SOURCE_COMPANION_OS_IMPORTS for n in values)
                or values!=sorted(set(values))):raise ValueError('Unresolved source companion dependency')
    if ('kernel32.dll' not in imports['normal'] or component['dependencyPolicy']!='x86-os-only-no-private-shadow-v1'):
        raise ValueError('Source companion dependency closure is incomplete')
    return {_SOURCE_COMPANION_PATH:{k:component[k] for k in ('machine','role','size','sha256')}}

def _source_companion_regular(path):
    path=Path(path).absolute()
    if '..' in path.parts:raise ValueError('Source companion path has a parent alias')
    for current in (path,*path.parents):
        info=current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('Source companion path is linked')
    if not path.is_file():raise ValueError('Source companion requires a regular file')
    return path

def _source_companion_pe(path,*,read_exports=True):
    """Read bounded PE metadata from one retained file; never load executable code."""
    try:
        from suite.pe_imports import _Reader
    except ModuleNotFoundError:
        from pe_imports import _Reader
    path=_source_companion_regular(path)
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 64<=before.st_size<=16*1024*1024:
            raise ValueError('Source companion PE exceeds its bound')
        reader=_Reader(stream);dos=reader.read(0,64);offset=struct.unpack_from('<I',dos,60)[0]
        header=reader.read(offset,24);machine=struct.unpack_from('<H',header,4)[0];flags=struct.unpack_from('<H',header,22)[0]
        magic=struct.unpack_from('<H',reader.optional)[0]
        def directory(index):
            return struct.unpack_from('<II',reader.optional,reader.directory_offset+index*8) if index<reader.directory_count else (0,0)
        clr=directory(14);exports=[];export_module=None;export_rva,export_size=directory(0)
        if bool(export_rva)!=bool(export_size):raise ValueError('Partial source companion export directory')
        if export_rva and read_exports:
            if not 40<=export_size<=1024*1024:raise ValueError('Source companion export directory exceeds bound')
            data=reader.rva_bytes(export_rva,40);export_module=reader.name(struct.unpack_from('<I',data,12)[0])
            count,names,functions,names_rva,ordinals=struct.unpack_from('<IIIII',data,20)
            if not 1<=count<=256 or names!=count:raise ValueError('Source companion exports are incomplete')
            function_values=struct.unpack('<'+'I'*count,reader.rva_bytes(functions,count*4))
            name_values=struct.unpack('<'+'I'*names,reader.rva_bytes(names_rva,names*4))
            ordinal_values=struct.unpack('<'+'H'*names,reader.rva_bytes(ordinals,names*2))
            if set(ordinal_values)!=set(range(count)):raise ValueError('Source companion export ordinals alias')
            for value in function_values:
                if not value or export_rva<=value<export_rva+export_size:raise ValueError('Source companion forwarded export is forbidden')
                reader.rva_bytes(value,1)
            for value in name_values:
                raw=bytearray()
                for index in range(65):
                    byte=reader.rva_bytes(value+index,1)
                    if byte==b'\0':break
                    raw.extend(byte)
                else:raise ValueError('Source companion export name exceeds bound')
                if not re.fullmatch(rb'[A-Za-z_][A-Za-z0-9_]{0,63}',raw):raise ValueError('Invalid source companion export name')
                exports.append(raw.decode('ascii'))
            if len(set(exports))!=len(exports):raise ValueError('Source companion duplicate export')
        entry=struct.unpack_from('<I',reader.optional,16)[0];subsystem=struct.unpack_from('<H',reader.optional,68)[0];entry_executable=False
        section_count=struct.unpack_from('<H',header,6)[0];optional_size=struct.unpack_from('<H',header,20)[0]
        section_bytes=reader.read(offset+24+optional_size,section_count*40)
        for index in range(section_count):
            section_rva,raw_size=struct.unpack_from('<II',section_bytes,index*40+12)
            characteristics=struct.unpack_from('<I',section_bytes,index*40+36)[0]
            if section_rva<=entry<section_rva+raw_size and characteristics&0x20000000:
                reader.rva_bytes(entry,1);entry_executable=True
        normal,nrange=reader.directory(1,delay=False);delay,drange=reader.directory(13,delay=True)
        if nrange and drange and max(nrange[0],drange[0])<min(nrange[1],drange[1]):raise ValueError('Source companion import tables overlap')
        stream.seek(0);digest=hashlib.file_digest(stream,'sha256').hexdigest();after=os.fstat(stream.fileno());current=path.stat()
        identity=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
        if identity(before)!=identity(after) or identity(before)!=identity(current):raise ValueError('Source companion changed during retained read')
        return dict(size=before.st_size,sha256=digest,machine=machine,optionalMagic=magic,isDll=bool(flags&0x2000),
                    executable=bool(flags&2),entryPoint=entry,entryMappedExecutable=entry_executable,subsystem=subsystem,exportDirectoryPresent=bool(export_rva or export_size),clrRva=clr[0],clrSize=clr[1],exportModule=export_module,exports=sorted(exports),imports=dict(normal=list(normal),delay=list(delay)))

def _source_companion_runtime(runtime_root,component):
    _source_companion_component(component,component['buildBinding'])
    root=Path(runtime_root);binary=_source_companion_pe(root/_SOURCE_COMPANION_PATH)
    if (binary['machine']!=0x14c or binary['optionalMagic']!=0x10b or not binary['isDll'] or not binary['executable']
            or binary['clrRva'] or binary['clrSize'] or binary['exportModule']!='spsupp_x86.dll' or any(binary[k]!=component[k] for k in ('size','sha256','exports','imports'))):
        raise ValueError('Source companion actual native PE differs from its proof')
    helper=_source_companion_pe(root/'program/spsupp_helper.exe');expected=component['nativeHelper']
    if (helper['machine']!=0x8664 or helper['optionalMagic']!=0x20b or helper['isDll'] or not helper['executable'] or helper['clrRva'] or helper['clrSize']
            or any(helper[k]!=expected[k] for k in ('size','sha256'))):raise ValueError('Source companion lacks its exact native helper')
    imported=set(component['imports']['normal'])|set(component['imports']['delay'])
    for item in (root/'program').iterdir():
        if item.name.casefold() in imported:raise ValueError('Private product file shadows a source companion system dependency')
    return True

def _source_companion_admissions(runtime,proof,*,architecture):
    """Internal Full consumer consistency only; external receipt pins remain mandatory."""
    if type(runtime) is not dict or type(proof) is not dict:raise ValueError('Source companion requires authenticated Full context')
    core=runtime.get('sourceCoreCommit')
    if runtime.get('format')!='source-built-zip' or core not in _PYTHON_TEMPLATE_SOURCES:
        raise ValueError('Source companion requires an exact source-built runtime profile')
    if architecture not in ('x64','arm64'):raise ValueError('Invalid source companion architecture')
    if architecture!='x64' or core!='9dea406ab7695df6325b11b0e19fdca8db4b7276':
        if proof.get('sourceCompanionProof') is not None or proof.get('sourceTwainProof') is not None:raise ValueError('Source companion is outside its reviewed profile')
        return {}
    source=_PYTHON_TEMPLATE_SOURCES[core]
    if (runtime.get('format')!='source-built-zip' or any(runtime.get(k)!=source[k] for k in ('version','sourceUrl','sourceSha256'))
            or any(proof.get(k) is not True for k in ('passed','fullEngineQualified','acceptanceEligible'))
            or proof.get('guiVerified') is not False):raise ValueError('Source companion requires normal authenticated Full proof')
    from_source=proof.get('sourcePin')
    expected_source=dict(version=source['version'],coreCommit=core,url=source['sourceUrl'],size=302823256,sha256=source['sourceSha256'])
    if type(from_source) is not dict or from_source!=expected_source or type(from_source.get('size')) is not int:
        raise ValueError('Source companion original archive tuple differs')
    binding={k:proof.get(k) for k in ('sourceCommit','sourceTree','sourceRun','runAttempt')}
    binding['recipeSha256']=proof.get('sourceRecipeProof',{}).get('recipeSha256')
    component=proof.get('sourceCompanionProof');result=_source_companion_component(component,binding)
    if component['installedArchive']['stageReceiptSha256']!=proof.get('installedRuntimeStage',{}).get('receipt',{}).get('sha256'):
        raise ValueError('Source companion installed stage receipt differs')
    twain=proof.get('sourceTwainProof');second=_source_twain_component(twain,binding)
    if twain['installedArchive']!=component['installedArchive']:
        raise ValueError('Source companion families belong to different installed archives')
    return {**result,**second}


# Exact original/effective source intent for the separate TWAIN executable.
SOURCE_TWAIN_SOURCE_PINS = [{'bytes': 31916, 'gitBlob': '3a9b342e6d805541daed7fad5c82fa68dd73d7fe', 'path': 'Repository.mk', 'sha256': '987811db83fe6937d0d959bc602c3d7828c9c8569469eb56cc72c6cb3c47bc6a', 'effectiveBytes': 31916, 'effectiveSha256': '987811db83fe6937d0d959bc602c3d7828c9c8569469eb56cc72c6cb3c47bc6a'}, {'bytes': 1009, 'gitBlob': '0fa51671410a901e276cadb0ff04dc360b0e52b2', 'path': 'cli_ure/CliNativeLibrary_cli_cppuhelper.mk', 'sha256': '7c776454bb55e541da3a937c8edf44166cb3d3837789b95c0359ec52c8df9bba', 'effectiveBytes': 1119, 'effectiveSha256': '6519e9014c32f8323e3501f49d189e6da428b3d3b1f85d7ad96471aedcfd051f'}, {'bytes': 803, 'gitBlob': 'b1cdc680d9db8ed0fca486a5987b3d417e364c47', 'path': 'cli_ure/Module_cli_ure.mk', 'sha256': '1c707e8e3386c8c291c7b7f8bebb642346c0154235d3e2e5b5751f651ef70dd8', 'effectiveBytes': 803, 'effectiveSha256': '1c707e8e3386c8c291c7b7f8bebb642346c0154235d3e2e5b5751f651ef70dd8'}, {'bytes': 410, 'gitBlob': '627a3a564f278c5c45475b955fa6a78c47fafdc2', 'path': 'cli_ure/source/native/cli_cppuhelper_config', 'sha256': 'dc009c1b46573a1264d97af8a2231defac0f6ce6f74011da9a51da096140e327', 'effectiveBytes': 410, 'effectiveSha256': 'dc009c1b46573a1264d97af8a2231defac0f6ce6f74011da9a51da096140e327'}, {'bytes': 1456, 'gitBlob': '11cd9e737649f4dbd8a6905acd70c995c4c08965', 'path': 'cli_ure/version/version.txt', 'sha256': '208f1e0dd84a774d81ba96dff023d2791cb0243ec43dd45dff79c94abd49f985', 'effectiveBytes': 1456, 'effectiveSha256': '208f1e0dd84a774d81ba96dff023d2791cb0243ec43dd45dff79c94abd49f985'}, {'bytes': 1235, 'gitBlob': 'f063f7d6e3b404436ee3e8d9194b40dbd53ff6b8', 'path': 'extensions/Executable_twain32shim.mk', 'sha256': '9dfc8323e9d5af2611a9330fd67d7244a248825af1ce73aa7bd9ecdea1d674c4', 'effectiveBytes': 1235, 'effectiveSha256': '9dfc8323e9d5af2611a9330fd67d7244a248825af1ce73aa7bd9ecdea1d674c4'}, {'bytes': 1453, 'gitBlob': '51c48fbfdf68f0aca927f5cd19d431bf7201e770', 'path': 'extensions/Library_scn.mk', 'sha256': '76ef7253efb58b17def410e2f09fd5f4ca4b3558823a7e76632a779e28928eb4', 'effectiveBytes': 1453, 'effectiveSha256': '76ef7253efb58b17def410e2f09fd5f4ca4b3558823a7e76632a779e28928eb4'}, {'bytes': 2607, 'gitBlob': 'b1cc40d8dd7949ee4004c9e6d06467e1eb3666ee', 'path': 'extensions/Module_extensions.mk', 'sha256': '6566d4579d64ef7918d326011808fda07d5ab5f537c1b47dc3bb6f564fad09e3', 'effectiveBytes': 2607, 'effectiveSha256': '6566d4579d64ef7918d326011808fda07d5ab5f537c1b47dc3bb6f564fad09e3'}, {'bytes': 19760, 'gitBlob': '933531526f7a8635f735a71fb2715fc43c8d9015', 'path': 'extensions/source/scanner/scanwin.cxx', 'sha256': 'd2feb91be2435d3eaf4f8be83041271994e4052e891de25aedaaa7c4b26edb7d', 'effectiveBytes': 19760, 'effectiveSha256': 'd2feb91be2435d3eaf4f8be83041271994e4052e891de25aedaaa7c4b26edb7d'}, {'bytes': 18601, 'gitBlob': 'a1e17773196868cd38b1d1e4f2555bb0bef50625', 'path': 'extensions/source/scanner/twain32shim.cxx', 'sha256': '1afedfa7aba7ffe50f85bc9166ab58a3cf6d4ab3addf1871514cc60a992c1369', 'effectiveBytes': 18601, 'effectiveSha256': '1afedfa7aba7ffe50f85bc9166ab58a3cf6d4ab3addf1871514cc60a992c1369'}, {'bytes': 1883, 'gitBlob': 'c9e87ee8bb57336f036d31658a82480b271da790', 'path': 'extensions/source/scanner/twain32shim.hxx', 'sha256': 'b6ae52cf7a4ef5ed8fc0933f9b79de8ec26b47e25cc27caed9403eefc55c63e3', 'effectiveBytes': 1883, 'effectiveSha256': 'b6ae52cf7a4ef5ed8fc0933f9b79de8ec26b47e25cc27caed9403eefc55c63e3'}, {'bytes': 617, 'gitBlob': '7d01a7b020ed40730d5b444f1d758d47dd42007f', 'path': 'scp2/InstallModule_spsupp.mk', 'sha256': 'a5af6a9d18768b21b77faa7de35e87c31d35ecb52ea8eb161cfc6e8b8c2a5efa', 'effectiveBytes': 617, 'effectiveSha256': 'a5af6a9d18768b21b77faa7de35e87c31d35ecb52ea8eb161cfc6e8b8c2a5efa'}, {'bytes': 1879, 'gitBlob': 'ba1ec46020286eb722c2bbda91e1738d502c06ac', 'path': 'scp2/source/spsupp/module_spsupp.scp', 'sha256': '281d881eaa2ca541c43c4673ea49a5fde526c422f478122f4193c5ae4d10eb1e', 'effectiveBytes': 1879, 'effectiveSha256': '281d881eaa2ca541c43c4673ea49a5fde526c422f478122f4193c5ae4d10eb1e'}, {'bytes': 1067, 'gitBlob': 'c905118bef5849f60e638b8ac97d3183edb2757a', 'path': 'shell/Executable_spsupp_helper.mk', 'sha256': 'b96bc08051232b47ec5cdd9083fe4fa752e614fdb72149d4f4387d575cb2f407', 'effectiveBytes': 1067, 'effectiveSha256': 'b96bc08051232b47ec5cdd9083fe4fa752e614fdb72149d4f4387d575cb2f407'}, {'bytes': 1444, 'gitBlob': '17183d8b92dabca94901efa7cb097b5391d089e8', 'path': 'shell/Library_spsupp_x86.mk', 'sha256': '68a515669d5730ef7ce4d23def0c288110b259ba01e89aa3bb3275d33b496c56', 'effectiveBytes': 1444, 'effectiveSha256': '68a515669d5730ef7ce4d23def0c288110b259ba01e89aa3bb3275d33b496c56'}, {'bytes': 2469, 'gitBlob': '58a598714a055f2058b1f7269f76ba0ed639d0b5', 'path': 'shell/Module_shell.mk', 'sha256': '062d0ccc982bb925b4d2119bc5ec9e8b1987a07854eb69980f72853e2837f4be', 'effectiveBytes': 2469, 'effectiveSha256': '062d0ccc982bb925b4d2119bc5ec9e8b1987a07854eb69980f72853e2837f4be'}, {'bytes': 18091, 'gitBlob': '701deef38f50bb566e3623c458638d116ace6ee9', 'path': 'shell/source/win32/spsupp/COMOpenDocuments.cxx', 'sha256': '4bafc6680d374c9b88b8dd145f2ac0f550da83e0b41344938bd0236b985946c8', 'effectiveBytes': 18091, 'effectiveSha256': '4bafc6680d374c9b88b8dd145f2ac0f550da83e0b41344938bd0236b985946c8'}, {'bytes': 177, 'gitBlob': 'f6828a3e8d43c72d31c62f5f222a7bfa8a4a0a28', 'path': 'shell/source/win32/spsupp/spsupp.def', 'sha256': '8f7d97fafa4653525b766d502221948ed1d97ffe9d5e42069677169b418ddcd7', 'effectiveBytes': 177, 'effectiveSha256': '8f7d97fafa4653525b766d502221948ed1d97ffe9d5e42069677169b418ddcd7'}, {'bytes': 5445, 'gitBlob': '45d5f47b13a1c066526ba389e2d2d10e941f15b2', 'path': 'shell/source/win32/spsupp/spsupp.idl', 'sha256': '750fc59aa7035aa468a3fa238438554a60d4150db650cbe2971694f645842ccb', 'effectiveBytes': 5445, 'effectiveSha256': '750fc59aa7035aa468a3fa238438554a60d4150db650cbe2971694f645842ccb'}, {'bytes': 5099, 'gitBlob': 'ea82e041c19e161d298ffb6a63126d080c697dae', 'path': 'shell/source/win32/spsupp/spsuppServ.cxx', 'sha256': 'd20edcb195f5576e15cfb1691830d445b6da4de3de00838dc595910173823598', 'effectiveBytes': 5099, 'effectiveSha256': 'd20edcb195f5576e15cfb1691830d445b6da4de3de00838dc595910173823598'}, {'bytes': 7146, 'gitBlob': '9c97e036fe2b8a4d4589f8dbae28d724512e2faf', 'path': 'solenv/gbuild/CliAssembly.mk', 'sha256': 'da616d706d48e9fd274be62bd177fe25239a654850d6c68f2769135c13c8bab7', 'effectiveBytes': 7146, 'effectiveSha256': 'da616d706d48e9fd274be62bd177fe25239a654850d6c68f2769135c13c8bab7'}, {'bytes': 3693, 'gitBlob': '9e19ccd709b59c2e3e0a84ff91db69076f1941d5', 'path': 'solenv/gbuild/CliNativeLibrary.mk', 'sha256': '22b98aa8dcef01fb3355a38a8de642289191385ab4f352dbd2ed3ff87c2d3e19', 'effectiveBytes': 3693, 'effectiveSha256': '22b98aa8dcef01fb3355a38a8de642289191385ab4f352dbd2ed3ff87c2d3e19'}, {'bytes': 16781, 'gitBlob': 'e58dc3974466f98667978b3ecde5a1e63752c345', 'path': 'solenv/gbuild/Library.mk', 'sha256': '1cab3987867b8e27fc395f1ef8145cfe6f791fa747f214aa69424e554b5e96d0', 'effectiveBytes': 16781, 'effectiveSha256': '1cab3987867b8e27fc395f1ef8145cfe6f791fa747f214aa69424e554b5e96d0'}, {'bytes': 111066, 'gitBlob': '3550b856dd60a597bb38df36aab6a30702686784', 'path': 'solenv/gbuild/LinkTarget.mk', 'sha256': '075c6497a70d1775374d552dad585aa01fb3eece14482f38386acb8900e3b1b8', 'effectiveBytes': 111066, 'effectiveSha256': '075c6497a70d1775374d552dad585aa01fb3eece14482f38386acb8900e3b1b8'}, {'bytes': 29428, 'gitBlob': '6e3a6da1a578bf66ca4bbd0377f86d3c4112a322', 'path': 'solenv/gbuild/platform/com_MSC_class.mk', 'sha256': 'e51a5e8469dadbee611142443f6056a43e0f0d194bae75f16428e45449fd9ada', 'effectiveBytes': 29428, 'effectiveSha256': 'e51a5e8469dadbee611142443f6056a43e0f0d194bae75f16428e45449fd9ada'}]

_SOURCE_TWAIN_PATH='program/twain32shim.exe'
_SOURCE_TWAIN_OS_IMPORTS=frozenset(('kernel32.dll','user32.dll','ole32.dll','shell32.dll','gdi32.dll','advapi32.dll','ntdll.dll','msvcrt.dll'))

def _source_twain_component(component,build_binding):
    """TWAIN EXE profile, separate from the SharePoint in-process COM DLL."""
    _source_companion_binding(build_binding)
    keys={'schemaVersion','kind','architecture','coreCommit','path','role','machine','size','sha256','buildBinding',
          'sourceIntent','sourceProofs','configuredX86','linkTarget','nativePeer','installedArchive','exports','imports',
          'dependencyPolicy','fullEngineQualified','acceptanceEligible','guiVerified'}
    if (type(component) is not dict or set(component)!=keys or type(component['schemaVersion']) is not int
            or component['schemaVersion']!=1 or component['kind']!='source-built-x86-twain-companion'
            or component['architecture']!='x64' or component['coreCommit']!=_SOURCE_COMPANION_CORE
            or component['path']!=_SOURCE_TWAIN_PATH or component['role']!='x86CompatibilityHelper'
            or type(component['machine']) is not int or component['machine']!=0x14c
            or type(component['size']) is not int or not 64<=component['size']<=16*1024*1024
            or type(component['sha256']) is not str or not SHA.fullmatch(component['sha256'])
            or component['sourceIntent']!='twain-32bit-driver-process-bridge' or component['configuredX86'] is not True
            or any(component[k] is not False for k in ('fullEngineQualified','acceptanceEligible','guiVerified'))):
        raise ValueError('Unreviewed source TWAIN component')
    _source_companion_binding(component['buildBinding'])
    if component['buildBinding']!=build_binding:raise ValueError('Source TWAIN belongs to a different build')
    if component['sourceProofs']!=SOURCE_TWAIN_SOURCE_PINS:raise ValueError('TWAIN original/effective source proof differs')
    target=component['linkTarget']
    if (type(target) is not dict or set(target)!={'path','size','sha256'}
            or target['path']!='workdir/LinkTarget/Executable/twain32shim.exe' or type(target['size']) is not int
            or target['size']!=component['size'] or target['sha256']!=component['sha256']):
        raise ValueError('TWAIN source target differs from installed bytes')
    _source_companion_identity(component['nativePeer'],'program/scnlo.dll',0x8664,'nativeX64')
    archive=component['installedArchive']
    if (type(archive) is not dict or set(archive)!={'kind','size','sha256','stageReceiptSha256'} or archive['kind']!='main'
            or type(archive['size']) is not int or archive['size']<1
            or any(type(archive[k]) is not str or not SHA.fullmatch(archive[k]) for k in ('sha256','stageReceiptSha256'))):
        raise ValueError('TWAIN installed archive proof differs')
    if type(component['exports']) is not list or component['exports']:raise ValueError('TWAIN executable cannot claim COM exports')
    imports=component['imports']
    if type(imports) is not dict or set(imports)!={'normal','delay'}:raise ValueError('Missing TWAIN import observations')
    for values in imports.values():
        if (type(values) is not list or any(type(n) is not str or n not in _SOURCE_TWAIN_OS_IMPORTS for n in values)
                or values!=sorted(set(values))):raise ValueError('Unresolved TWAIN dependency')
    if 'kernel32.dll' not in imports['normal'] or component['dependencyPolicy']!='x86-twain-os-only-no-private-shadow-v1':
        raise ValueError('TWAIN dependency closure is incomplete')
    return {_SOURCE_TWAIN_PATH:{k:component[k] for k in ('machine','role','size','sha256')}}

def _source_twain_runtime(runtime_root,component):
    _source_twain_component(component,component['buildBinding']);root=Path(runtime_root)
    binary=_source_companion_pe(root/_SOURCE_TWAIN_PATH)
    if (binary['machine']!=0x14c or binary['optionalMagic']!=0x10b or binary['isDll'] or not binary['executable']
            or binary['subsystem']!=2 or not binary['entryPoint'] or not binary['entryMappedExecutable']
            or binary['exportDirectoryPresent'] or binary['exports'] or binary['clrRva'] or binary['clrSize']
            or any(binary[k]!=component[k] for k in ('size','sha256','imports'))):
        raise ValueError('TWAIN actual x86 GUI executable differs from its proof')
    peer=_source_companion_pe(root/'program/scnlo.dll',read_exports=False);expected=component['nativePeer']
    if (peer['machine']!=0x8664 or peer['optionalMagic']!=0x20b or not peer['isDll'] or not peer['executable']
            or peer['clrRva'] or peer['clrSize'] or any(peer[k]!=expected[k] for k in ('size','sha256'))):
        raise ValueError('TWAIN lacks its exact native scanner peer')
    imported=set(component['imports']['normal'])|set(component['imports']['delay'])
    for item in (root/'program').iterdir():
        if item.name.casefold() in imported:raise ValueError('Private product file shadows a TWAIN system dependency')
    return True
