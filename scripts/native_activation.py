"""Prepare checksum-pinned, source-level Windows activation adapters.

This changes reviewed source, never a compiled binary or the certification SDK.
The full original and prepared vendor inventory is part of the source ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import tomllib
import urllib.request

from buildkit import ROOT, replace_once

MAX_ARCHIVE = 4 * 1024 * 1024
MAX_EXPANDED = 32 * 1024 * 1024
MAX_FILES = 1500
PATCH_INPUT = ROOT / 'overlay/native-activation-patches.json'
SHIM = ROOT / 'overlay/native-open'
FEATURE = 'opengeul-store-no-restart'
REGISTRY_INPUTS = {
    'windows': ('0.61.3', '9babd3a767a4c1aef6900409f85f5d53ce2544ccdfaa86dad48c91782c6d6893'),
    'windows-future': ('0.2.1', 'fc6a41e98427b19fe4b73c550f060b59fa592d7d686537eebf9385621bfbad8e'),
    'open': ('5.3.3', '43bb73a7fa3799b198970490a51174027ba0d4ec504b03cd08caf513d40024bc'),
}
RESERVED = re.compile(r'(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def provision_vendor(content: bytes, specification: dict, destination: Path) -> dict:
    """Validate the complete archive before writing any prepared source."""
    if len(content) > MAX_ARCHIVE or sha(content) != specification['checksum']:
        raise ValueError('Native activation crate archive checksum/size mismatch')
    if destination.exists() or destination.is_symlink():
        raise ValueError('Native activation vendor destination already exists')
    prefix = specification['name'] + '-' + specification['version']
    files: dict[str, bytes] = {}
    seen = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(content), mode='r:gz') as archive:
        for entry in archive:
            parts = entry.name.split('/')
            if (len(parts) < 2 or parts[0] != prefix or '\\' in entry.name
                    or any(p in ('', '.', '..') or p.rstrip(' .') != p or RESERVED.fullmatch(p)
                           or any(ord(c) < 32 or ord(c) == 127 or c in ':<>"|?*' for c in p)
                           for p in parts)):
                raise ValueError('Unsafe native activation archive path')
            name = '/'.join(parts[1:])
            if name.casefold() in seen or not entry.isfile():
                raise ValueError('Duplicate/non-file native activation archive member')
            seen.add(name.casefold())
            total += entry.size
            if entry.size < 0 or total > MAX_EXPANDED or len(seen) > MAX_FILES:
                raise ValueError('Native activation archive expansion limit exceeded')
            stream = archive.extractfile(entry)
            if stream is None:
                raise ValueError('Native activation archive member is unreadable')
            value = stream.read(entry.size + 1)
            if len(value) != entry.size:
                raise ValueError('Native activation archive member size mismatch')
            files[name] = value
    original = {name: sha(value) for name, value in sorted(files.items())}
    for name, patch in specification['patches'].items():
        if name not in files or sha(files[name]) != patch['sha256']:
            raise ValueError('Native activation patch source changed: ' + name)
        value = files[name].decode('utf-8')
        for before, after in patch['replacements']:
            value = replace_once(value, before, after)
        files[name] = value.encode('utf-8')
    destination.parent.mkdir(parents=True, exist_ok=True)
    for ancestor in [destination.parent, *destination.parent.parents]:
        if ancestor.is_symlink():
            raise ValueError('Native activation destination has a symlink ancestor')
    stage = Path(tempfile.mkdtemp(prefix='.native-activation-', dir=destination.parent))
    try:
        for name, value in sorted(files.items()):
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {'name': specification['name'], 'version': specification['version'],
            'archiveSha256': specification['checksum'], 'originalFiles': original,
            'preparedFiles': {name: sha(value) for name, value in sorted(files.items())}}


def desktop_manifest(value: str) -> str:
    value = replace_once(value, 'open = "5"\n', '')
    value = replace_once(value, 'tauri = { version = "=2.11.1", features = [] }',
                         'tauri = { version = "=2.11.1", features = ["' + FEATURE + '"] }')
    value = replace_once(value, '[patch.crates-io]\n', '''[patch.crates-io]
tauri = { path = "opengeul-native/tauri-2.11.1" }
tauri-runtime-wry = { path = "opengeul-native/tauri-runtime-wry-2.11.1" }
''')
    return value.rstrip() + '''

[target.'cfg(windows)'.dependencies]
opengeul-native-open = { path = "opengeul-native/native-open" }

[target.'cfg(not(windows))'.dependencies]
open = "5"

[workspace]
members = ["opengeul-native/native-open"]
default-members = ["."]
exclude = ["opengeul-native/tauri-2.11.1", "opengeul-native/tauri-runtime-wry-2.11.1"]
resolver = "2"
'''


def transform_lock(value: str) -> str:
    """Deterministic reviewed transformation; Cargo --locked must verify on CI."""
    specifications = json.loads(PATCH_INPUT.read_text(encoding='utf-8'))['crates']
    blocks = value.split('[[package]]\n')
    selected = set()
    for index, body in enumerate(blocks[1:], 1):
        package = tomllib.loads(body)
        name = package['name']
        if name in specifications:
            specification = specifications[name]
            if (package['version'] != specification['version']
                    or package.get('source') != 'registry+https://github.com/rust-lang/crates.io-index'
                    or package.get('checksum') != specification['checksum'] or name in selected):
                raise ValueError('Native activation lock source changed')
            selected.add(name)
            body = replace_once(body, 'source = "' + package['source'] + '"\n', '')
            body = replace_once(body, 'checksum = "' + specification['checksum'] + '"\n', '')
        if name in ('hop-desktop', 'tauri-runtime-wry'):
            dependencies = package['dependencies']
            original = 'dependencies = [\n' + ''.join(' "' + item + '",\n' for item in dependencies) + ']\n'
            updated = 'dependencies = [\n' + ''.join(' "' + item + '",\n' for item in sorted(dependencies + ['opengeul-native-open'])) + ']\n'
            body = replace_once(body, original, updated)
        if name == 'opengeul-native-open':
            raise ValueError('Native activation lock was already transformed')
        blocks[index] = body
    if selected != set(specifications):
        raise ValueError('Native activation lock packages are missing')
    insert = '''[[package]]
name = "opengeul-native-open"
version = "1.0.0"
dependencies = [
 "windows",
 "windows-future",
]

'''
    result = '[[package]]\n'.join(blocks)
    result = replace_once(result, '[[package]]\nname = "openssl-probe"\n', insert + '[[package]]\nname = "openssl-probe"\n')
    return validate_lock(result)


def validate_lock(value: str) -> str:
    packages = tomllib.loads(value)['package']
    selected = {}
    for name in ('tauri', 'tauri-runtime-wry', 'opengeul-native-open', 'hop-desktop', 'windows', 'windows-future', 'open'):
        matching = [package for package in packages if package['name'] == name]
        if len(matching) != 1:
            raise ValueError('Native activation lock selection is ambiguous: ' + name)
        selected[name] = matching[0]
    for name in ('tauri', 'tauri-runtime-wry'):
        if selected[name]['version'] != '2.11.1' or any(key in selected[name] for key in ('source', 'checksum')):
            raise ValueError('Native activation vendor lock is invalid')
    for name in ('hop-desktop', 'tauri-runtime-wry'):
        if selected[name]['dependencies'].count('opengeul-native-open') != 1:
            raise ValueError('Native activation lock dependency missing')
    shim = selected['opengeul-native-open']
    if (shim['version'] != '1.0.0' or shim['dependencies'] != ['windows', 'windows-future']
            or 'source' in shim or 'checksum' in shim):
        raise ValueError('Native activation shim lock is invalid')
    for name, (version, checksum) in REGISTRY_INPUTS.items():
        if (selected[name]['version'] != version or selected[name].get('checksum') != checksum
                or selected[name].get('source') != 'registry+https://github.com/rust-lang/crates.io-index'):
            raise ValueError('Native activation registry dependency source changed: ' + name)
    return value


def _download(specification: dict, cache: Path) -> bytes:
    name = specification['name'] + '-' + specification['version'] + '.crate'
    path = cache / name
    if path.exists():
        if path.is_symlink() or path.stat().st_size > MAX_ARCHIVE:
            raise ValueError('Invalid cached native activation crate')
        content = path.read_bytes()
    else:
        url = 'https://static.crates.io/crates/' + specification['name'] + '/' + name
        with urllib.request.urlopen(url, timeout=60) as response:
            if response.status != 200 or response.url != url:
                raise ValueError('Unexpected native activation crate response')
            content = response.read(MAX_ARCHIVE + 1)
        if len(content) > MAX_ARCHIVE or sha(content) != specification['checksum']:
            raise ValueError('Native activation downloaded crate checksum mismatch')
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    if sha(content) != specification['checksum']:
        raise ValueError('Native activation cached crate checksum mismatch')
    return content


def apply(source: Path, *, cache: Path | None = None) -> dict:
    native = source / 'apps/desktop/src-tauri'
    destination = native / 'opengeul-native'
    if destination.exists() or destination.is_symlink():
        raise ValueError('Native activation source was already prepared')
    manifest = native / 'Cargo.toml'
    before = manifest.read_bytes()
    prepared = desktop_manifest(before.decode('utf-8')).encode('utf-8')
    lock = (native / 'Cargo.lock').read_bytes()
    validate_lock(lock.decode('utf-8'))
    specifications = json.loads(PATCH_INPUT.read_text(encoding='utf-8'))['crates']
    cache = cache if cache is not None else ROOT / '.work/native-activation-crates'
    archives = {name: _download(specification, cache) for name, specification in specifications.items()}
    ledger = {'formatVersion': 1, 'patchInputSha256': sha(PATCH_INPUT.read_bytes()),
              'originalManifestSha256': sha(before), 'preparedManifestSha256': sha(prepared),
              'preparedLockSha256': sha(lock), 'crates': {}, 'shimFiles': {}}
    stage = Path(tempfile.mkdtemp(prefix='.native-activation-', dir=native))
    try:
        for name, specification in sorted(specifications.items()):
            relative = name + '-' + specification['version']
            ledger['crates'][relative] = provision_vendor(archives[name], specification, stage / relative)
        for local in sorted(SHIM.rglob('*')):
            if local.is_symlink():
                raise ValueError('Native activation shim has a symlink')
            if local.is_file():
                name = local.relative_to(SHIM).as_posix()
                target = stage / 'native-open' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(local.read_bytes())
                ledger['shimFiles'][name] = sha(target.read_bytes())
        stage.rename(destination)
        manifest.write_bytes(prepared)
        (native / '.opengeul-native-activation.json').write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return ledger


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--cache', type=Path)
    args = parser.parse_args()
    ledger = apply(args.source, cache=args.cache)
    print(json.dumps({'preparedCrates': sorted(ledger['crates']), 'preparedManifestSha256': ledger['preparedManifestSha256']}))


if __name__ == '__main__':
    main()
