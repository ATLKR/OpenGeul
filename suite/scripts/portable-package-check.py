"""Verify a final portable ZIP, coexistence and file repair by fresh extraction.

This is a disposable file check, not an installer, updater or Windows GUI gate.
The staged inventory is the trust input; a ZIP cannot authenticate itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from suite.payload import (INVENTORY, MAX_FILES, MAX_METADATA, REQUIRED, _hash,
                           _json, _kind, _name, _scan, verify_payload)
from suite.prepare import archive_path


def _path(value: Path, *, fresh=False, directory=False) -> Path:
    path = Path(value).absolute()
    for item in (*reversed(path.parents), path):
        if item != item.parent:
            _name(item.name)
            with os.scandir(item.parent) as entries:
                for count, entry in enumerate(entries, 1):
                    if count > MAX_FILES:
                        raise ValueError('Path parent scan exceeds bound')
                    if entry.name.casefold() == item.name.casefold() and entry.name != item.name:
                        raise ValueError('Case-aliased input/output path')
        if item == path and fresh:
            if item.exists() or item.is_symlink():
                raise ValueError('Output or receipt already exists')
        else:
            info = _kind(item)
            if item != path or directory:
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError('Input/output requires regular parent directories')
            elif not stat.S_ISREG(info.st_mode):
                raise ValueError('Archive must be a regular file')
    if str(path.resolve(strict=not fresh)).casefold() != str(path).casefold():
        raise ValueError('Native resolved input/output path is aliased')
    return path


def _member(source, member, expected, writer=None):
    digest = hashlib.sha256(); size = 0
    with source.open(member) as reader:
        while block := reader.read(1024*1024):
            size += len(block)
            if size > expected['size']:
                raise ValueError('ZIP member exceeds inventory size')
            digest.update(block)
            if writer is not None:
                writer.write(block)
    if size != expected['size'] or digest.hexdigest() != expected['sha256']:
        raise ValueError('ZIP member size/SHA256 differs from staged inventory')


def _authenticate(source, expected):
    directories = {str(parent) for name in expected for parent in PurePosixPath(name).parents
                   if str(parent) != '.'}
    members = source.infolist(); seen = set(); files = set()
    if not members or len(members) > len(expected)+len(directories):
        raise ValueError('ZIP member count exceeds staged inventory bound')
    for member in members:
        _name(archive_path(member.orig_filename))
        name = _name(archive_path(member.filename))
        directory = member.is_dir()
        kind = stat.S_IFMT(member.external_attr >> 16)
        if (name.casefold() in seen or member.flag_bits & 1 or member.external_attr & 0x400
                or kind not in ((0, stat.S_IFDIR) if directory else (0, stat.S_IFREG))
                or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise ValueError('Unsafe ZIP member kind, encoding or collision')
        seen.add(name.casefold())
        if directory:
            if name not in directories or member.file_size:
                raise ValueError('ZIP directory is outside staged inventory')
        else:
            if name not in expected or member.file_size != expected[name]['size']:
                raise ValueError('ZIP files/sizes differ from staged inventory')
            files.add(name)
    if files != expected.keys():
        raise ValueError('ZIP lacks staged inventory files')
    # Authenticate every member before creating any destination or receipt.
    for member in members:
        if not member.is_dir():
            _member(source, member, expected[member.filename])


def _extract(source, expected, destination):
    destination.mkdir()
    for member in source.infolist():
        if member.is_dir():
            continue
        target = destination/member.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as writer:
            _member(source, member, expected[member.filename], writer)


def _save(stream, result):
    stream.seek(0)
    json.dump(result, stream, ensure_ascii=False, indent=2)
    stream.write('\n'); stream.truncate(); stream.flush(); os.fsync(stream.fileno())


def _identity(info):
    return tuple(getattr(info, field) for field in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns'))


def check_package(*, baseline: Path, archive: Path, output: Path, receipt: Path) -> dict:
    baseline = _path(baseline, directory=True)
    archive = _path(archive)
    output = _path(output, fresh=True)
    receipt = _path(receipt, fresh=True)
    paths = [tuple(part.casefold() for part in path.parts)
             for path in (baseline, archive, output, receipt)]
    for index, left in enumerate(paths):
        for right in paths[index+1:]:
            if left[:len(right)] == right or right[:len(left)] == left:
                raise ValueError('Baseline, ZIP, output and receipt must not intersect')
    inventory = _json(baseline/INVENTORY)
    verify_payload(baseline, inventory)
    inventory_sha = _hash(baseline/INVENTORY)
    expected = dict(inventory['files'])
    expected[INVENTORY] = {'size': (baseline/INVENTORY).stat().st_size, 'sha256': inventory_sha}
    hwp = {name: record for name, record in expected.items() if name.startswith('HWP/')}
    if not hwp:
        raise ValueError('HWP assets are required to measure existing HWP preservation')
    # Bound physical input as well as decompression; normal final ZIPs contain
    # only the staged bytes and small per-member headers, with no appended data.
    zip_bound = 2*sum(record['size'] for record in expected.values()) + MAX_METADATA
    zip_bound += sum(2*len(name.encode('utf-8'))+1024 for name in expected)
    if not 0 < archive.stat().st_size <= min(zip_bound, 16*1024**3):
        raise ValueError('ZIP physical size exceeds staged inventory bound')
    archive_identity = _identity(_kind(archive))
    archive_sha = _hash(archive)
    installed = output/'OpenGeul Office 설치 검증'
    repaired = output/'OpenGeul Office 복구 검증'
    result = {
        'schemaVersion': 1, 'kind': 'portable-package-file-check', 'passed': False,
        'sourceCommit': _json(baseline/'suite-provenance.json')['sourceCommit'],
        'architecture': inventory['architecture'], 'baselineRoot': str(baseline),
        'archivePath': str(archive), 'archiveSha256': archive_sha,
        'inventorySha256': inventory_sha, 'archiveInventoryMatched': False,
        'extractedRoot': str(installed), 'repairedRoot': str(repaired),
        'relocationVerified': False, 'sameVersionCoexistenceVerified': False,
        'corruptionDetected': False, 'repairVerified': False,
        'updateVerified': False, 'guiVerified': False,
        'existingHwpPreserved': {'passed': False, 'files': {}},
    }
    with archive.open('rb') as raw, zipfile.ZipFile(raw) as source:
        if _identity(os.fstat(raw.fileno())) != archive_identity:
            raise ValueError('ZIP identity changed before opening')
        _authenticate(source, expected)
        if _identity(_kind(archive)) != archive_identity or _hash(archive) != archive_sha:
            raise ValueError('ZIP changed during authentication')
        _path(output, fresh=True); _path(receipt, fresh=True)
        output.mkdir()
        _extract(source, expected, installed)
        verify_payload(installed, inventory)
        result['archiveInventoryMatched'] = True
        result['creationReceipt'] = {'root': str(installed), 'inventoryVerified': True,
                                     'archiveSha256': archive_sha, 'inventorySha256': inventory_sha}
        with receipt.open('x+', encoding='utf-8') as journal:
            # Persist ownership and successful creation before touching bytes.
            # Any interruption leaves passed=false; partial trees cannot qualify.
            _save(journal, result)
            victim = 'Office/program/soffice.bin'
            assert victim in REQUIRED and not victim.startswith('HWP/')
            if _hash(installed/victim) != expected[victim]['sha256']:
                raise ValueError('Owned corruption target changed')
            with (installed/victim).open('ab') as stream:
                stream.write(b'\nportable-package-file-check deliberate corruption\n')
            corrupted = _scan(installed)
            if (corrupted.keys() != inventory['files'].keys()
                    or {name for name in corrupted if corrupted[name] != expected[name]} != {victim}):
                raise ValueError('Corruption changed more than the selected owned Office file')
            result['corruption'] = {'path': victim, 'operation': 'append',
                                    'before': expected[victim], 'after': corrupted[victim]}
            try:
                verify_payload(installed, inventory)
            except ValueError:
                result['corruptionDetected'] = True
            else:
                raise ValueError('Deliberate corruption was not detected')
            _extract(source, expected, repaired)
            verify_payload(repaired, inventory)
            verify_payload(baseline, inventory)
            if (_scan(installed) != corrupted or _hash(installed/INVENTORY) != inventory_sha
                    or _hash(baseline/INVENTORY) != inventory_sha
                    or _identity(_kind(archive)) != archive_identity or _hash(archive) != archive_sha):
                raise ValueError('Input or original extraction changed during repair')
            for name, record in hwp.items():
                measured = {'baselineSha256': _hash(baseline/name),
                            'extractedSha256': _hash(installed/name),
                            'repairedSha256': _hash(repaired/name)}
                if set(measured.values()) != {record['sha256']}:
                    raise ValueError('Existing HWP bytes changed')
                result['existingHwpPreserved']['files'][name] = measured
            result.update(passed=True, relocationVerified=True,
                          sameVersionCoexistenceVerified=True, repairVerified=True)
            result['existingHwpPreserved']['passed'] = True
            _save(journal, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'archive', 'output', 'receipt'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    check_package(**vars(args))
    print('Portable ZIP file check passed; receipt: '+str(args.receipt))


if __name__ == '__main__':
    main()
