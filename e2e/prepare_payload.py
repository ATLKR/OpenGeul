"""Validate complete MSIX/portable parity before creating a test runtime.

A checksum validates bytes, not their author. Same-run artifact selection remains
required by CI; this verifier prevents incomplete manifests or mismatched runtime
resources from making a different portable program stand in for the MSIX.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

MAX_MEMBERS = 10_000
MAX_UNCOMPRESSED = 512 * 1024 * 1024
MAX_FILE = 128 * 1024 * 1024
PACKAGING_ONLY = frozenset({'AppxBlockMap.xml', '[Content_Types].xml', 'AppxMetadata/CodeIntegrity.cat'})
RESERVED = re.compile(r'(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z')


def safe_name(value: str) -> str:
    name = value.replace('\\', '/')
    parts = name.rstrip('/').split('/')
    if (not parts or any(p in ('', '.', '..') or p.rstrip(' .') != p or RESERVED.fullmatch(p) for p in parts)
            or any(ord(c) < 32 or c in ':<>"|?*' for c in name)):
        raise ValueError(f'Unsafe Windows archive path: {value!r}')
    return '/'.join(parts)


def stream_hash(stream) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


def verify_checksums(package: Path) -> dict[str, str]:
    if package.is_symlink() or not package.is_dir(): raise ValueError('Invalid package directory')
    paths = list(package.iterdir())
    if len(paths) > 64: raise ValueError('Unexpected artifact file count')
    for path in paths:
        if path.is_symlink() or not path.is_file(): raise ValueError('Only regular artifact files are allowed')
        if path.stat().st_size > MAX_UNCOMPRESSED: raise ValueError('Artifact exceeds size limit')
        if safe_name(path.name) != path.name: raise ValueError('Unsafe artifact filename')
    manifest = package / 'SHA256SUMS.txt'
    if not manifest.is_file() or not 1 <= manifest.stat().st_size <= 64 * 1024:
        raise ValueError('Missing or empty checksum manifest')
    expected = {}; aliases = set()
    for line in manifest.read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{64})[ \t]+\*?(.+)', line)
        if match is None: raise ValueError('Invalid checksum manifest record')
        digest, name = match.groups()
        if '/' in name or '\\' in name or safe_name(name) != name or name == manifest.name:
            raise ValueError('Checksum filename must be a safe basename')
        if name.casefold() in aliases: raise ValueError('Duplicate checksum entry')
        aliases.add(name.casefold()); expected[name] = digest.lower()
    actual = {p.name for p in paths if p.name != manifest.name}
    if not expected or actual != set(expected): raise ValueError('Checksum manifest must cover every artifact exactly once')
    for name, digest in expected.items():
        with (package / name).open('rb') as stream:
            if stream_hash(stream) != digest: raise ValueError(f'Hash mismatch: {name}')
    return expected


def inventory(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > MAX_MEMBERS or sum(e.file_size for e in entries) > MAX_UNCOMPRESSED:
        raise ValueError('Archive exceeds expansion limits')
    aliases = set(); files = {}
    for entry in entries:
        name = safe_name(entry.filename)
        key = name.casefold()
        if key in aliases: raise ValueError('Duplicate or case-aliased archive member')
        aliases.add(key)
        kind = stat.S_IFMT(entry.external_attr >> 16)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.flag_bits & 1:
            raise ValueError('Special or encrypted archive member')
        if entry.file_size > MAX_FILE: raise ValueError('Archive member exceeds size limit')
        if not entry.is_dir(): files[name] = entry
    file_keys = {n.casefold() for n in files}
    for name in aliases:
        if any(str(p).casefold() in file_keys for p in PurePosixPath(name).parents if str(p) != '.'):
            raise ValueError('Archive file/directory path collision')
    return files


def prepare(package: Path, output: Path):
    if output.exists() or output.is_symlink(): raise ValueError('Refusing to overwrite an existing test runtime')
    verify_checksums(package)
    msix = list(package.glob('*.msix')); portable = list(package.glob('*portable.zip'))
    if len(msix) != 1 or len(portable) != 1: raise ValueError('Exactly one MSIX and portable archive required')
    from releasekit import verify_msix
    verify_msix(msix[0])
    with zipfile.ZipFile(portable[0]) as archive, zipfile.ZipFile(msix[0]) as packaged:
        portable_files, packaged_files = inventory(archive), inventory(packaged)
        runtime_files = {n:e for n,e in packaged_files.items() if n not in PACKAGING_ONLY}
        if set(portable_files) != set(runtime_files):
            raise ValueError('Portable/MSIX runtime file set mismatch')
        digests = {}
        for name, item in portable_files.items():
            other = runtime_files[name]
            if item.file_size != other.file_size: raise ValueError(f'Portable/MSIX payload mismatch: {name}')
            with archive.open(item) as stream: digest = stream_hash(stream)
            with packaged.open(other) as stream:
                if digest != stream_hash(stream): raise ValueError(f'Portable/MSIX payload mismatch: {name}')
            digests[name] = digest
        # Only verified files reach disk; exceptions remove the staging directory.
        output.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.opengeul-verified-', dir=output.parent))
        try:
            for name, entry in portable_files.items():
                target = stage.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open('xb') as dest: shutil.copyfileobj(source, dest)
                with target.open('rb') as stream:
                    if stream_hash(stream) != digests[name]: raise ValueError('Extracted runtime changed')
            if output.exists() or output.is_symlink(): raise ValueError('Runtime destination appeared during validation')
            stage.rename(output)
        finally:
            if stage.exists(): shutil.rmtree(stage)
    result = {'msix': msix[0].name, 'portable': portable[0].name,
              'editorSha256': digests['OpenGeul.exe'], 'verifiedRuntimeFiles': len(digests),
              'runtimeManifestSha256': hashlib.sha256(json.dumps(digests,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    print(json.dumps(result))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('package', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args(); prepare(args.package, args.output)
