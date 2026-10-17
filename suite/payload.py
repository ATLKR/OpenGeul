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
REQUIRED = frozenset({
    'OpenGeul.Office.exe', 'OpenGeul.Office.dll', 'suite-product.json',
    'suite-provenance.json', 'runtime-branding.json', 'Office/opengeul-branding.json',
    'Office/program/soffice.exe', 'Office/program/soffice.bin', 'Office/program/python.exe',
    'worker/office_worker.py', 'worker/session.py', 'worker/native.py',
    'worker/native_windows.py', 'worker/dispatch.py', 'Notices/OpenGeul-Office-LICENSE.txt',
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
ARM64_COMPANION_PE_ADMISSIONS = {}


def _architecture(architecture: str) -> str:
    if not isinstance(architecture, str) or architecture not in NATIVE_MACHINES:
        raise ValueError(f'Unsupported Suite architecture: {architecture!r}')
    return architecture


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


def _scan(root: Path) -> dict:
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
    if (lock.get('schemaVersion') != 1 or lock.get('architecture') != architecture
            or lock.get('version') != provenance['version'] or not isinstance(lock.get('runtime'), dict)
            or any(lock['runtime'].get(key) != provenance['runtime'].get(key)
                   for key in ('sha256', 'url', 'sourceUrl', 'sourceSha256'))):
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
    _metadata(root, files, architecture=architecture)
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
