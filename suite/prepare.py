"""Pinned inputs and fresh-path extraction for the separate Office Suite package."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MSI_VC_DEPENDENCIES = frozenset({
    'concrt140.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
    'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll', 'vcruntime140.dll',
    'vcruntime140_1.dll', 'vcruntime140_threads.dll',
})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
    return digest.hexdigest()


def check_asset(asset: dict, path: Path) -> None:
    if path.is_symlink() or not path.is_file(): raise ValueError('Input must be a regular file')
    if path.stat().st_size != asset['size'] or sha256(path) != asset['sha256']:
        raise ValueError('Locked input size/SHA256 does not match: ' + path.name)


def download_locked(asset: dict, destination: Path) -> Path:
    url = asset.get('url', '')
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
        or type(asset.get('size')) is not int or asset['size'] <= 0
        or not re.fullmatch(r'[0-9a-f]{64}', asset.get('sha256', ''))):
        raise ValueError('A complete HTTPS input size/SHA256 lock is required')
    if destination.exists() or destination.is_symlink():
        check_asset(asset, destination)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.partial')
    if temporary.exists() or temporary.is_symlink(): raise ValueError('Partial input already exists')
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'OpenGeul-Office-build/0.1'})
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open('xb') as stream:
            if urllib.parse.urlsplit(response.url).scheme != 'https':
                raise ValueError('Input redirected to an insecure URL')
            size = 0
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                size += len(chunk)
                if size > asset['size']: raise ValueError('Download exceeds locked size')
                stream.write(chunk)
        check_asset(asset, temporary)
        temporary.rename(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def archive_path(name: str) -> str:
    name = name.rstrip('/')
    parts = name.split('/')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                *(f'LPT{i}' for i in range(1, 10))}
    if (not name or '\\' in name or ':' in name or '\x00' in name
        or PurePosixPath(name).is_absolute() or any(ord(c) < 32 for c in name)
        or any(p in ('', '.', '..') or p.endswith((' ', '.'))
               or p.split('.')[0].upper() in reserved for p in parts)):
        raise ValueError('Unsafe archive path: ' + repr(name))
    return name


def extract_hwp_zip(archive: Path, destination: Path, *, limit: int = 512 * 1024 * 1024) -> None:
    if destination.exists() or destination.is_symlink(): raise ValueError('Output already exists')
    with zipfile.ZipFile(archive) as source:
        seen = set(); total = 0
        members = source.infolist()
        if not members or len(members) > 10000: raise ValueError('Invalid HWP archive member count')
        for member in members:
            # ZipInfo may normalize Windows separators or truncate at NUL.
            # Admit the raw central-directory name before using its normalized name.
            archive_path(member.orig_filename)
            name = archive_path(member.filename)
            if name.casefold() in seen: raise ValueError('Archive path collision')
            seen.add(name.casefold())
            if stat.S_ISLNK(member.external_attr >> 16): raise ValueError('Archive symlink is forbidden')
            total += member.file_size
            if member.file_size > 128 * 1024 * 1024 or total > limit:
                raise ValueError('HWP archive exceeds extraction bound')
        if 'opengeul.exe' not in seen: raise ValueError('HWP archive has no root editor')
        destination.mkdir(parents=True)
        for member in members:
            target = destination / archive_path(member.filename)
            if member.is_dir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as reader, target.open('xb') as writer:
                    while chunk := reader.read(1024 * 1024): writer.write(chunk)


def normalize_admin_runtime(source: Path, destination: Path, *, admin_metadata: bool = False, msi_name: str | None = None) -> Path:
    """Project INSTALLLOCATION content from the pinned MSI's admin source image.

    Windows honors DefaultDir's source name '.' and places program at TARGETDIR;
    System/System64 and the administrative MSI are not application-root files.
    The original extraction remains unchanged, including non-native merge modules.
    """
    directories = {'help', 'presets', 'program', 'readmes', 'share'}
    files = {'CREDITS.fodt', 'LICENSE.html', 'NOTICE', 'license.txt', 'update-settings.ini'}
    allowed = directories | files
    administrative = {'System', 'System64', 'Fonts', 'Windows', 'Templates'} if admin_metadata else set()
    if admin_metadata and msi_name:
        if Path(msi_name).name != msi_name or not msi_name.lower().endswith('.msi'):
            raise ValueError('Invalid administrative MSI filename')
        administrative.add(msi_name)
    if destination.exists() or destination.is_symlink():
        raise ValueError('Normalized MSI runtime output already exists')
    if (source.is_symlink() or not source.is_dir() or source.resolve() == destination.absolute()
            or source.resolve() in destination.absolute().parents):
        raise ValueError('MSI runtime projection requires separate regular directories')
    entries = {path.name: path for path in source.iterdir()}
    unexpected = set(entries) - allowed - administrative
    if unexpected:
        raise ValueError('Unexpected MSI runtime root entries: '+', '.join(sorted(unexpected)))
    missing = allowed - entries.keys()
    if missing:
        raise ValueError('Missing pinned MSI application root entries: '+', '.join(sorted(missing)))
    for name, path in entries.items():
        info = path.lstat()
        if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('MSI runtime root symlink/reparse point: '+name)
        if name not in allowed:
            continue
        if (name in directories and not path.is_dir()) or (name in files and not path.is_file()):
            raise ValueError('Invalid MSI application root entry kind: '+name)
        for child in path.rglob('*') if path.is_dir() else ():
            child_info = child.lstat()
            if child.is_symlink() or getattr(child_info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('MSI runtime symlink/reparse point: '+str(child))
            if not (child.is_dir() or child.is_file()):
                raise ValueError('MSI runtime special file: '+str(child))
    destination.mkdir(parents=True)
    for name in sorted(allowed):
        if name in directories:
            shutil.copytree(entries[name], destination/name)
        else:
            shutil.copy2(entries[name], destination/name)
    return destination


def extract_msi(archive: Path, destination: Path) -> Path:
    if os.name != 'nt': raise ValueError('GUI MSI extraction requires Windows')
    if destination.exists(): raise ValueError('MSI extraction output already exists')
    destination.mkdir(parents=True)
    log = destination.parent / (destination.name + '.msi.log')
    result = subprocess.run(['msiexec.exe', '/a', str(archive.resolve()), '/qn', '/norestart',
                             'TARGETDIR=' + str(destination.resolve()), '/L*v', str(log.resolve())],
                            timeout=300, check=False)
    if result.returncode != 0: raise ValueError(f'MSI extraction failed ({result.returncode}); see {log.name}')
    matches = list(destination.glob('**/program/soffice.exe'))
    if len(matches) != 1: raise ValueError('MSI must contain one Office runtime')
    runtime = matches[0].parent.parent
    if not (runtime/'program/python.exe').is_file(): raise ValueError('Runtime has no bundled UNO Python')
    runtime = normalize_admin_runtime(runtime, destination.with_name(destination.name+'-runtime'),
                                      admin_metadata=runtime == destination, msi_name=archive.name)
    # Administrative images may flatten ARM64 and AMD64 merge-module rows onto
    # the same System64 filenames. Recover the exact native AMD64 File IDs from
    # the authenticated original cabinet instead of trusting those paths.
    try:
        from suite.msi_cab import recover_x64_crt
    except ModuleNotFoundError:
        from msi_cab import recover_x64_crt
    crt = destination.with_name(destination.name + '-native-crt')
    crt.mkdir(exist_ok=False)
    recovered = recover_x64_crt(archive, crt/'System64')
    files = stage_msi_dependencies(crt, runtime)
    for name, record in recovered.items():
        files['program/'+name].update(fileId=record['fileId'], cabinet=record['cabinet'])
    receipt = runtime/'opengeul-msi-dependencies.json'
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump({'schemaVersion': 1, 'architecture': 'x64', 'inputMsiSha256': sha256(archive),
                   'recovery': 'embedded-amd64-file-ids', 'files': files}, stream, indent=2)
        stream.write('\n')
    return runtime


def stage_msi_dependencies(extraction_root: Path, runtime_root: Path) -> dict:
    """Copy the pinned MSI's native x64 VC++ DLLs into its scratch runtime.

    Administrative extraction puts these files in System64 rather than program.
    Validate every source and existing destination before copying any dependency;
    never use the sibling System directory containing x86 binaries.
    """
    try:
        from suite.payload import _pe
    except ModuleNotFoundError:
        from payload import _pe

    def regular(path, *, directory=False):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('MSI dependency symlink/reparse point: '+str(path))
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise ValueError('MSI dependency requires a regular '+('directory' if directory else 'file'))
        return info

    source = extraction_root/'System64'
    target = runtime_root/'program'
    for directory in (extraction_root, source, runtime_root, target):
        regular(directory, directory=True)
    candidates = {}
    for path in source.iterdir():
        name = path.name.lower()
        if not re.fullmatch(r'(?:msvcp140[^/]*|vcruntime140[^/]*|concrt140)\.dll', name):
            continue
        if name in candidates:
            raise ValueError('MSI dependency source case collision: '+name)
        candidates[name] = path
    missing = MSI_VC_DEPENDENCIES - candidates.keys()
    if missing:
        raise ValueError('Missing pinned MSI System64 dependencies: '+', '.join(sorted(missing)))
    existing = {}
    for path in target.iterdir():
        name = path.name.lower()
        if name in candidates:
            if name in existing:
                raise ValueError('MSI dependency destination case collision: '+name)
            existing[name] = path
    result = {}
    for name, path in sorted(candidates.items()):
        info = regular(path)
        _pe(path)
        with path.open('rb') as stream:
            stream.seek(60)
            pe_offset = struct.unpack('<I', stream.read(4))[0]
            stream.seek(pe_offset+4)
            if struct.unpack('<H', stream.read(2))[0] != 0x8664:
                raise ValueError('MSI dependency must use native x64 architecture: '+name)
        digest = sha256(path)
        if name in existing:
            other = existing[name]
            other_info = regular(other)
            if other_info.st_size != info.st_size or sha256(other) != digest:
                raise ValueError('Conflicting runtime MSI dependency: '+name)
        result['program/'+name] = {'source': 'System64/'+path.name,
                                  'size': info.st_size, 'sha256': digest}
    # All dependency and collision checks have succeeded before any runtime write.
    for name, path in sorted(candidates.items()):
        if name not in existing:
            with path.open('rb') as reader, (target/name).open('xb') as writer:
                shutil.copyfileobj(reader, writer)
            record = result['program/'+name]
            if (target/name).stat().st_size != record['size'] or sha256(target/name) != record['sha256']:
                raise ValueError('Staged MSI dependency differs from its input: '+name)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--shell', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    lock = json.loads((ROOT/'suite/config/runtime.lock.json').read_text(encoding='utf-8'))
    msi = download_locked(lock['runtime'], args.work/'inputs/office.msi')
    hwp = download_locked(lock['hwp'], args.work/'inputs/hwp.zip')
    runtime = extract_msi(msi, args.work/'msi')
    from package import assemble
    assemble(runtime=runtime, hwp=hwp, shell=args.shell, output=args.output, lock=lock)
    print('OpenGeul Office package prepared and verified:', args.output)


if __name__ == '__main__': main()
