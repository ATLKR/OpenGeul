"""Pinned inputs and fresh-path extraction for the separate Office Suite package."""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
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
NATIVE_MACHINES = {'x64': 0x8664, 'arm64': 0xAA64}
try:
    from suite.crt import crt_names, is_vc_crt_file
except ModuleNotFoundError:
    from crt import crt_names, is_vc_crt_file

# Compatibility name retains the existing public x64 family.
MSI_VC_DEPENDENCIES = frozenset(crt_names())


def native_machine(architecture: str) -> int:
    try:
        return NATIVE_MACHINES[architecture]
    except (KeyError, TypeError):
        raise ValueError('Unsupported native Suite architecture: '+str(architecture)) from None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
    return digest.hexdigest()


def check_asset(asset: dict, path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
            or getattr(info, 'st_file_attributes', 0) & 0x400):
        raise ValueError('Input must be a regular file without reparse points')
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
    name = name[:-1] if name.endswith('/') else name
    parts = name.split('/')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$', *(f'COM{i}' for i in '123456789¹²³'),
                *(f'LPT{i}' for i in '123456789¹²³')}
    if (not name or any(c in name for c in '\\:<>"|?*\x00')
        or PurePosixPath(name).is_absolute() or any(ord(c) < 32 for c in name)
        or any(p in ('', '.', '..') or p.endswith((' ', '.'))
               or p.split('.')[0].rstrip(' ').upper() in reserved for p in parts)):
        raise ValueError('Unsafe archive path: ' + repr(name))
    return name


def validate_source_build_lock(runtime: dict, *, architecture: str) -> dict:
    """Require immutable external pins; a receipt never authorizes itself."""
    def digest(value):
        return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None
    def positive(value):
        return type(value) is int and value > 0
    build = runtime.get('sourceBuild')
    if (architecture != 'arm64' or runtime.get('format') != 'source-built-zip'
            or not isinstance(build, dict) or not positive(runtime.get('size'))
            or not digest(runtime.get('sha256'))
            or not isinstance(runtime.get('sourceCoreCommit'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', runtime['sourceCoreCommit'])
            or not isinstance(build.get('sourceCommit'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', build['sourceCommit'])
            or any(not digest(build.get(key)) for key in
                   ('receiptSha256', 'artifactSha256', 'patchManifestSha256'))
            or any(not positive(build.get(key)) for key in ('runId', 'artifactId'))):
        raise ValueError('Complete ARM64 source-build lock and externally pinned receipt are required')
    for key in ('url', 'sourceUrl'):
        url = runtime.get(key)
        try:
            parsed = urllib.parse.urlsplit(url) if isinstance(url, str) else None
            valid = (parsed and parsed.scheme == 'https' and parsed.hostname
                     and not parsed.username and not parsed.password and not any(ord(c) <= 32 for c in url))
        except ValueError:
            valid = False
        if not valid: raise ValueError('Source-build lock requires complete HTTPS provenance')
    if not digest(runtime.get('sourceSha256')) or not isinstance(runtime.get('version'), str):
        raise ValueError('Source-build lock requires authenticated upstream source provenance')
    return build


def validate_source_build_receipt(runtime: dict, receipt: Path, *, architecture: str) -> dict:
    """Authenticate exact driver evidence before interpreting its native/Base claims."""
    build = validate_source_build_lock(runtime, architecture=architecture)
    info = receipt.lstat()
    if (not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
            or not 0 < info.st_size <= 8*1024*1024 or sha256(receipt) != build['receiptSha256']):
        raise ValueError('Source-build receipt does not match its external locked SHA256 or size bound')
    try:
        from suite.payload import _json_bytes
    except ModuleNotFoundError:
        from payload import _json_bytes
    proof = _json_bytes(receipt.read_bytes(), 'source-build receipt')
    def positive(value):
        return type(value) is int and value > 0
    def native(value):
        return (isinstance(value, dict) and type(value.get('processMachine')) is int
                and value['processMachine'] == 0 and type(value.get('nativeMachine')) is int
                and value['nativeMachine'] == 0xaa64)
    if (type(proof.get('schemaVersion')) is not int or proof['schemaVersion'] != 1
            or proof.get('kind') != 'native-office-engine-source-build'
            or proof.get('phase') != 'Full' or proof.get('architecture') != 'arm64'
            or proof.get('passed') is not True or proof.get('fullEngineQualified') is not True
            or proof.get('guiVerified') is not False or proof.get('stage') != 'complete'
            or proof.get('status') != 'native-engine-source-build-qualified'
            or proof.get('sourceCommit') != build['sourceCommit']
            or type(proof.get('sourceRun')) is not int or proof['sourceRun'] != build['runId']
            or proof.get('sourcePortManifestSha256') != build['patchManifestSha256']
            or not isinstance(proof.get('sourceTree'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', proof['sourceTree'])
            or not positive(proof.get('runAttempt'))
            or not isinstance(proof.get('driverSha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', proof['driverSha256'])
            or not native(proof.get('host')) or proof['host'].get('isWindows') is not True):
        raise ValueError('Source-build receipt does not qualify an authenticated full native ARM64 engine')
    source = proof.get('sourcePin'); artifact = proof.get('artifact'); config = proof.get('configuration')
    if (not isinstance(source, dict) or any(source.get(a) != runtime.get(b) for a, b in
            (('url', 'sourceUrl'), ('sha256', 'sourceSha256'), ('version', 'version')))
            or not positive(source.get('size')) or not isinstance(artifact, dict)
            or type(artifact.get('size')) is not int or artifact['size'] != runtime['size']
            or artifact.get('sha256') != runtime['sha256']):
        raise ValueError('Source-build receipt artifact/source identity differs from locked input')
    required = {'OS': 'WNT', 'COM': 'MSC', 'CPUNAME': 'AARCH64',
                'HOST_PLATFORM': 'aarch64-pc-cygwin', 'BUILD_PLATFORM': 'aarch64-pc-cygwin',
                'ENABLE_FIREBIRD_SDBC': 'TRUE', 'CROSS_COMPILING': '', 'SYSTEM_FIREBIRD': '',
                'PKGFORMAT': 'archive', 'ENABLE_ONLINE_UPDATE': '',
                'ENABLE_ONLINE_UPDATE_MAR': '', 'ENABLE_BREAKPAD': ''}
    if (not isinstance(config, dict) or any(config.get(key) != value for key, value in required.items())
            or not isinstance(config.get('BUILD_TYPE'), str)
            or not {'FIREBIRD', 'LIBATOMIC_OPS', 'LIBTOMMATH'} <= set(config['BUILD_TYPE'].split())
            or {'BREAKPAD', 'ONLINEUPDATE'} & {token.upper() for token in config['BUILD_TYPE'].split()}):
        raise ValueError('Source-build receipt configuration does not prove native internal Firebird and disabled OEM services')
    _source_build_identity(proof, runtime['sourceCoreCommit'])
    base = proof.get('baseProof')
    if (not isinstance(base, dict) or type(base.get('schemaVersion')) is not int or base['schemaVersion'] != 1
            or base.get('passed') is not True or base.get('guiVerified') is not False
            or base.get('independentReopenVerified') is not True
            or base.get('rows') != [{'id': 1, 'text': 'Engine-OpenGeul-base 한글', 'amount': 42}]
            or type(base['rows'][0]['id']) is not int or type(base['rows'][0]['amount']) is not int
            or not isinstance(base.get('odbSha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', base['odbSha256'])):
        raise ValueError('Source-build receipt lacks exact independent Base persistence proof')
    processes = base.get('nativeProcesses')
    if (not isinstance(processes, list) or len(processes) != 3
            or any(not native(item) or not positive(item.get('pid')) for item in processes)
            or any(item['pid'] == processes[0]['pid'] for item in processes[1:])
            or processes[0].get('role') != 'uno-python'):
        raise ValueError('Source-build Base proof lacks actual native Python/Office process witnesses')
    images = []
    for process, phase in zip(processes[1:], ('create', 'reopen')):
        image = process.get('image')
        if (process.get('role') != 'uno-host' or process.get('jobOwned') is not True
                or process.get('phase') != phase or not positive(process.get('creationTime'))
                or not isinstance(image, str) or '\x00' in image
                or not PureWindowsPath(image).is_absolute()
                or tuple(part.casefold() for part in PureWindowsPath(image).parts[-2:]) != ('program', 'soffice.bin')):
            raise ValueError('Source-build Base proof requires owned actual soffice.bin create/reopen hosts')
        images.append(str(PureWindowsPath(image)).casefold())
    if (images[0] != images[1] or (processes[1]['pid'], processes[1]['creationTime']) ==
            (processes[2]['pid'], processes[2]['creationTime'])):
        raise ValueError('Source-build Base proof must independently reopen with the same engine')
    _source_build_crt(proof)
    return proof


def _source_build_identity(proof: dict, core: str) -> dict:
    """Replay the emitted correction/final proof against the external source core pin."""
    source = proof.get('sourcePin'); identity = proof.get('runtimeBuildIdentity')
    def digest(value):
        return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None
    if (not isinstance(core, str) or not re.fullmatch(r'[0-9a-f]{40}', core)
            or not isinstance(source, dict) or source.get('coreCommit') != core
            or not isinstance(identity, dict) or type(identity.get('schemaVersion')) is not int
            or identity['schemaVersion'] != 1
            or identity.get('mechanism') != 'explicit-generated-config-correction-from-authenticated-source-pin'
            or identity.get('expectedBuildId') != core
            or identity.get('sourceArchiveUrl') != source.get('url')
            or identity.get('sourceArchiveSha256') != source.get('sha256')
            or type(identity.get('sourceArchiveSize')) is not int
            or identity['sourceArchiveSize'] != source.get('size')):
        raise ValueError('Source-build runtime identity differs from externally pinned upstream core/source')
    files = identity.get('files'); final = identity.get('finalVerification')
    names = {'program/version.ini', 'program/setup.ini'}
    if (not isinstance(files, dict) or set(files) != names or not isinstance(final, dict)
            or final.get('passed') is not True or final.get('expectedBuildId') != core
            or not isinstance(final.get('files'), dict) or set(final['files']) != names):
        raise ValueError('Source-build runtime identity final verification is missing or incomplete')
    originals = [record.get('originalBuildId') if isinstance(record, dict) else None
                 for record in files.values()]
    if not all(isinstance(value, str) for value in originals) or len(set(originals)) != 1:
        raise ValueError('Source-build original identity modes disagree')
    original = originals[0]
    mode = ('empty' if original == '' else 'pinned-core' if original == core else
            'actual-parent' if original == proof.get('sourceCommit') else 'installed-no-git-fallback')
    if 'identityMode' in identity and identity['identityMode'] != mode:
        raise ValueError('Source-build identity mode differs from original identities')
    if mode == 'installed-no-git-fallback':
        # A mode tag or a general installer-label regex never authorizes admission.
        expected_config = dict(LIBO_VERSION_MAJOR='26', LIBO_VERSION_MINOR='8', LIBO_VERSION_MICRO='1',
                               LIBO_VERSION_PATCH='1', LIBO_VERSION_SUFFIX='')
        expected_source = dict(version='26.8.1.1', coreCommit='bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1',
            url='https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-26.8.1.1.tar.xz',
            size=302435508, sha256='296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785')
        config = proof.get('configuration')
        if (source != expected_source or core != expected_source['coreCommit']
                or not isinstance(config, dict) or any(config.get(k) != v for k, v in expected_config.items())):
            raise ValueError('Installed identity fallback requires exact authenticated source/configuration')
        build = config['LIBO_VERSION_MAJOR'] + config['LIBO_VERSION_MINOR'] + '0'
        normalized = re.search(r'(\w+?)(\d+)', build).group(2)
        fallback = normalized + '(Build:' + config['LIBO_VERSION_PATCH'] + ')'
        derivation = dict(rule='libreoffice-26.8.1.1-installer-no-git-v1', configuration=expected_config,
                          build=build, normalizedBuild=normalized, installerBuildId=config['LIBO_VERSION_PATCH'],
                          buildid=fallback)
        if (identity.get('identityMode') != mode or original != fallback
                or identity.get('installedFallbackDerivation') != derivation):
            raise ValueError('Installed identity fallback derivation differs from authenticated installer formula')
    if mode == 'installed-no-git-fallback' or 'stageReceipt' in identity or 'originals' in identity:
        # Compact replay checks descriptors and their shared pinned receipt reference.
        # Producer/audit authenticate the separate map and original raw bytes; those
        # diagnostic files are deliberately outside the two-file qualified artifact.
        reference = identity.get('stageReceipt'); stage = proof.get('installedRuntimeStage')
        descriptors = identity.get('originals')
        if (not isinstance(reference, dict) or set(reference) != {'path', 'bytes', 'sha256'}
                or not isinstance(reference.get('path'), str) or not reference['path']
                or '\x00' in reference['path'] or type(reference.get('bytes')) is not int
                or not 0 < reference['bytes'] <= 32*1024*1024 or not digest(reference.get('sha256'))
                or not isinstance(stage, dict) or stage.get('passed') is not True
                or stage.get('receipt') != reference
                or not isinstance(descriptors, dict) or set(descriptors) != names):
            raise ValueError('Installed identity stage/original descriptors are incomplete or inconsistent')
        archives = set(); wrappers = set()
        for name, descriptor in descriptors.items():
            if (not isinstance(descriptor, dict)
                    or set(descriptor) != {'archivePath', 'archiveMember', 'bytes', 'sha256'}
                    or type(descriptor.get('bytes')) is not int or not 0 < descriptor['bytes'] <= 65536
                    or descriptor.get('sha256') != files[name].get('beforeSha256')
                    or not digest(descriptor.get('sha256'))
                    or not isinstance(descriptor.get('archivePath'), str) or not descriptor['archivePath']
                    or '\x00' in descriptor['archivePath']
                    or not isinstance(descriptor.get('archiveMember'), str)
                    or not descriptor['archiveMember'].endswith('/'+name)):
                raise ValueError('Installed identity original descriptor differs: '+name)
            member = archive_path(descriptor['archiveMember'])
            wrappers.add(member[:-len('/'+name)])
            archives.add(descriptor['archivePath'])
        if len(archives) != 1 or len(wrappers) != 1:
            raise ValueError('Installed identity originals do not share one main archive wrapper')
    for name, record in files.items():
        original = record.get('originalBuildId') if isinstance(record, dict) else None
        if (not isinstance(record, dict) or not isinstance(original, str)
                or record.get('buildid') != core or record.get('corrected') is not (original != core)
                or not digest(record.get('beforeSha256')) or not digest(record.get('sha256'))
                or original == core and record['beforeSha256'] != record['sha256']
                or final['files'][name] != {'buildid': core, 'sha256': record['sha256']}):
            raise ValueError('Source-build runtime identity original/corrected/final metadata differs: '+name)
    return identity


def _source_build_crt(proof: dict) -> tuple[dict, dict]:
    """Join the driver's preflight, signed sources, copied bytes and legal snapshot."""
    plan = proof.get('crtPreflight'); copied = proof.get('appLocalCrt'); terms = proof.get('crtRedistributionTerms')
    expected = frozenset(crt_names('arm64'))
    def version(value):
        if not isinstance(value, str) or not re.fullmatch(r'14\.[0-9]+\.[0-9]+(?:\.[0-9]+)?', value):
            raise ValueError('Source-build CRT compiler/runtime version is invalid')
        return tuple(map(int, value.split('.'))) + ((0,) if value.count('.') == 2 else ())
    if (not isinstance(plan, dict) or not isinstance(copied, dict)
            or plan.get('schemaVersion') != 1 or copied.get('schemaVersion') != 1
            or plan.get('toolset') != 'v145' or copied.get('toolset') != 'v145'
            or plan.get('architecture') != 'arm64' or copied.get('architecture') != 'arm64'
            or not isinstance(plan.get('files'), list) or len(plan['files']) != len(expected)
            or not isinstance(copied.get('files'), list) or len(copied['files']) != len(expected)):
        raise ValueError('Source-build CRT requires the complete native VS2026 ARM64 eight-file family')
    minimum = version(plan.get('minimumRuntimeVersion'))
    if minimum != version(plan.get('compilerToolsVersion')):
        raise ValueError('Source-build CRT version floor differs from selected compiler')
    source_dir = plan.get('sourceDirectory'); program_dir = copied.get('programDirectory')
    if (not isinstance(source_dir, str) or not isinstance(program_dir, str)
            or '\x00' in source_dir or '\x00' in program_dir
            or not PureWindowsPath(source_dir).is_absolute() or not PureWindowsPath(program_dir).is_absolute()
            or PureWindowsPath(program_dir).name.casefold() != 'program'
            or copied.get('sourceDirectory') != source_dir
            or any(PureWindowsPath(item['image']).parent != PureWindowsPath(program_dir)
                   for item in proof['baseProof']['nativeProcesses'][1:])):
        raise ValueError('Source-build CRT source/runtime directories differ from qualified engine')
    records = {}
    for record in plan['files']:
        if not isinstance(record, dict) or record.get('name') not in expected:
            raise ValueError('Unexpected source-build CRT file')
        name = record['name']; signature = record.get('signature')
        if (name in records or type(record.get('machine')) is not int or record['machine'] != 0xaa64
                or type(record.get('size')) is not int or record['size'] <= 0
                or not isinstance(record.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', record['sha256'])
                or not isinstance(record.get('sourcePath'), str) or '\x00' in record['sourcePath']
                or PureWindowsPath(record['sourcePath']) != PureWindowsPath(source_dir)/name
                or not isinstance(signature, dict) or signature.get('status') != 'Valid'
                or not isinstance(signature.get('signerSubject'), str)
                or not re.search(r'(?:^|,\s*)O=Microsoft Corporation(?:,|$)', signature['signerSubject'])
                or not isinstance(signature.get('signerThumbprint'), str)
                or not re.fullmatch(r'[0-9a-fA-F]{40}', signature['signerThumbprint'])
                or signature.get('companyName') != 'Microsoft Corporation'
                or not isinstance(signature.get('originalFilename'), str)
                or signature['originalFilename'].casefold() != name):
            raise ValueError('Source-build CRT native machine/Microsoft signature identity is invalid')
        for field in ('fileVersionParts', 'productVersionParts'):
            parts = signature.get(field)
            if (not isinstance(parts, list) or len(parts) != 4
                    or any(type(part) is not int or part < 0 for part in parts)
                    or parts[0] != 14 or tuple(parts) < minimum):
                raise ValueError('Source-build CRT signed runtime is older than selected compiler')
        records[name] = record
    if set(records) != expected:
        raise ValueError('Source-build CRT exact ARM64 eight-file family is incomplete')
    seen = set()
    for item in copied['files']:
        source = item.get('source') if isinstance(item, dict) else None
        name = source.get('name') if isinstance(source, dict) else None
        if (not isinstance(name, str) or name not in records or name in seen or source != records[name]
                or item.get('copiedSha256') != records[name]['sha256']
                or type(item.get('alreadyIdentical')) is not bool
                or not isinstance(item.get('destination'), str) or '\x00' in item['destination']
                or PureWindowsPath(item['destination']) != PureWindowsPath(program_dir)/name):
            raise ValueError('Source-build CRT preflight/source/copied byte identities differ')
        seen.add(name)
    app_terms = copied.get('redistributionTerms')
    if (not isinstance(terms, dict) or not isinstance(app_terms, dict)
            or terms.get('url') != 'https://learn.microsoft.com/en-us/visualstudio/releases/2026/redistribution'
            or type(terms.get('size')) is not int or not 0 < terms['size'] <= 2*1024*1024
            or not isinstance(terms.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', terms['sha256'])
            or app_terms.get('sha256') != terms['sha256'] or not isinstance(app_terms.get('path'), str)
            or '\x00' in app_terms['path'] or PureWindowsPath(app_terms['path']) !=
                PureWindowsPath(program_dir).parent/'share/readme/Microsoft-VC145-redistribution.html'):
        raise ValueError('Source-build CRT redistribution terms snapshot differs from packaged legal source')
    _source_build_import_closure(proof)
    return records, terms


def _source_build_import_closure(proof: dict) -> dict:
    closure = proof.get('crtImportClosure')
    expected = list(crt_names('arm64'))
    if (not isinstance(closure, dict)
            or set(closure) != {'schemaVersion', 'architecture', 'passed', 'requiredCrtFiles', 'checkedPeCount', 'imports'}
            or type(closure.get('schemaVersion')) is not int or closure['schemaVersion'] != 1
            or closure.get('architecture') != 'arm64' or closure.get('passed') is not True
            or closure.get('requiredCrtFiles') != expected
            or type(closure.get('checkedPeCount')) is not int or not 0 < closure['checkedPeCount'] <= 100_000
            or not isinstance(closure.get('imports'), list) or len(closure['imports']) > closure['checkedPeCount']):
        raise ValueError('Source-build CRT requires an exact successful ARM64 normal/delay import closure')
    paths = set()
    for item in closure['imports']:
        if (not isinstance(item, dict) or set(item) != {'path', 'normal', 'delay'}
                or not isinstance(item['path'], str)):
            raise ValueError('Invalid source-build CRT import record')
        name = archive_path(item['path'])
        if name.casefold() in paths:
            raise ValueError('Duplicate source-build CRT import image')
        paths.add(name.casefold())
        for kind in ('normal', 'delay'):
            names = item[kind]
            if (not isinstance(names, list) or any(not isinstance(name, str) or name not in expected for name in names)
                    or names != sorted(set(names))):
                raise ValueError('Unexpected source-build CRT normal/delay import')
        if not item['normal'] and not item['delay']:
            raise ValueError('Empty source-build CRT import record')
    return closure


def validate_source_build_runtime(runtime_root: Path, proof: dict, *, branding: dict | None = None) -> None:
    """Replay metadata and CRT bytes after authenticating the receipt against its lock.

    Only the final Suite payload supplies branding; preparation checks the exact
    original metadata hash, and packaging joins that hash to the branded bytes.
    """
    records, terms = _source_build_crt(proof)
    core = proof.get('sourcePin', {}).get('coreCommit')
    identity = _source_build_identity(proof, core)
    for name, section in (('program/version.ini', 'Version'), ('program/setup.ini', 'Bootstrap')):
        path = runtime_root/name
        expected_hash = identity['files'][name]['sha256']
        if branding is not None and name == 'program/version.ini':
            changes = branding.get('modifiedFiles') if isinstance(branding, dict) else None
            branded_source = branding.get('source') if isinstance(branding, dict) else None
            change = changes.get(name) if isinstance(changes, dict) else None
            if (not isinstance(change, dict) or change.get('beforeSha256') != expected_hash
                    or not isinstance(change.get('sha256'), str)
                    or not re.fullmatch(r'[0-9a-f]{64}', change['sha256'])
                    or not isinstance(branded_source, dict) or branded_source.get('buildId') != core):
                raise ValueError('Source-build runtime identity is not joined to actual branding input/output')
            expected_hash = change['sha256']
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
                    or not 0 < info.st_size <= 1024*1024 or sha256(path) != expected_hash):
                raise ValueError('Runtime metadata bytes differ')
            metadata = configparser.RawConfigParser()
            text = path.read_text(encoding='utf-8-sig')
            assignments = re.findall(r'(?im)^[ \t]*buildid[ \t]*=([^\r\n]*)', text)
            metadata.read_string(text)
            if (metadata.sections() != [section] or metadata.defaults()
                    or assignments != [core]
                    or metadata.get(section, 'buildid', fallback=None) != core):
                raise ValueError('Effective runtime buildid differs')
        except (OSError, UnicodeError, configparser.Error, ValueError) as error:
            raise ValueError('Source-build runtime identity/buildid bytes are missing, changed or ambiguous: '+name) from error
    try:
        from suite.payload import _pe
    except ModuleNotFoundError:
        from payload import _pe
    for name, record in records.items():
        path = runtime_root/'program'/name
        try:
            check_asset(record, path)
            _pe(path, architecture='arm64')
            with path.open('rb') as stream:
                stream.seek(60); offset = struct.unpack('<I', stream.read(4))[0]
                stream.seek(offset+4)
                if struct.unpack('<H', stream.read(2))[0] != 0xaa64:
                    raise ValueError('App-local CRT must be native ARM64')
        except (OSError, ValueError, struct.error) as error:
            raise ValueError('Source-build CRT bytes/machine differ from authenticated receipt: '+name) from error
    try:
        check_asset(terms, runtime_root/'share/readme/Microsoft-VC145-redistribution.html')
    except (OSError, ValueError) as error:
        raise ValueError('Source-build CRT redistribution terms bytes differ from authenticated receipt') from error
    try:
        from suite.crt import validate_crt_imports
    except ModuleNotFoundError:
        from crt import validate_crt_imports
    if validate_crt_imports(runtime_root, architecture='arm64') != _source_build_import_closure(proof):
        raise ValueError('Source-build CRT normal/delay import closure differs from authenticated receipt')


def extract_source_engine_zip(archive: Path, destination: Path, *, runtime: dict, receipt: Path,
                              architecture: str, limit: int = 8*1024*1024*1024,
                              max_files: int = 100_000, max_file_size: int = 1024*1024*1024) -> Path:
    """Extract a locally supplied, externally authenticated qualified source engine."""
    validate_source_build_lock(runtime, architecture=architecture)
    check_asset(runtime, archive)
    proof = validate_source_build_receipt(runtime, receipt, architecture=architecture)
    if destination.exists() or destination.is_symlink(): raise ValueError('Source engine output already exists')
    for parent in destination.absolute().parents:
        if parent.exists() or parent.is_symlink():
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Source engine output requires unlinked regular parent directories')
    with zipfile.ZipFile(archive) as source:
        members = source.infolist(); aliases = {}; explicit = set(); total = 0
        if not members or len(members) > max_files: raise ValueError('Source engine ZIP member count exceeds bound')
        for member in members:
            archive_path(member.orig_filename)
            name = archive_path(member.filename); key = name.casefold()
            kind = stat.S_IFMT(member.external_attr >> 16)
            directory = member.is_dir()
            if (key in explicit or key.split('/')[0] in ('opengeul-source-build.json', 'opengeul-msi-dependencies.json')
                    or member.flag_bits & 1 or member.external_attr & 0x400
                    or kind not in ((0, stat.S_IFDIR) if directory else (0, stat.S_IFREG))):
                raise ValueError('Unsafe source engine ZIP member kind/collision: '+name)
            explicit.add(key)
            parts = name.split('/')
            for index in range(1, len(parts)+1):
                prefix = '/'.join(parts[:index]); alias = prefix.casefold()
                is_directory = index < len(parts) or directory
                if alias in aliases and (aliases[alias][0] != prefix or not aliases[alias][1] or not is_directory):
                    raise ValueError('Source engine ZIP case/path collision: '+name)
                aliases[alias] = (prefix, is_directory)
            total += member.file_size
            if member.file_size > max_file_size or total > limit or (directory and member.file_size):
                raise ValueError('Source engine ZIP exceeds extraction size bound')
        required = {'program/'+name for name in ('soffice.exe', 'soffice.bin', 'python.exe', 'pyuno.pyd',
                     'ifbclient.dll', 'Engine12.dll', 'intl/fbintl.dll')}
        if any(name.casefold() not in aliases or aliases[name.casefold()][1] for name in required):
            raise ValueError('Source engine ZIP lacks required native Office/Base runtime files')
        destination.mkdir(parents=True)
        for member in members:
            target = destination/archive_path(member.filename)
            if member.is_dir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as reader, target.open('xb') as writer:
                    size = 0
                    while chunk := reader.read(1024*1024):
                        size += len(chunk)
                        if size > member.file_size: raise ValueError('Source engine ZIP member exceeds declared size')
                        writer.write(chunk)
                    if size != member.file_size: raise ValueError('Source engine ZIP member size mismatch')
    validate_source_build_runtime(destination, proof)
    with receipt.open('rb') as reader, (destination/'opengeul-source-build.json').open('xb') as writer:
        shutil.copyfileobj(reader, writer)
    return destination


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


def extract_msi(archive: Path, destination: Path, *, architecture: str = 'x64') -> Path:
    native_machine(architecture)
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
    # the same System64 filenames. Recover the exact native File IDs from
    # the authenticated original cabinet instead of trusting those paths.
    try:
        from suite.msi_cab import recover_crt
    except ModuleNotFoundError:
        from msi_cab import recover_crt
    crt = destination.with_name(destination.name + '-native-crt')
    crt.mkdir(exist_ok=False)
    recovered = recover_crt(archive, crt/'System64', architecture=architecture)
    files = stage_msi_dependencies(crt, runtime, architecture=architecture)
    for name, record in recovered.items():
        files['program/'+name].update(fileId=record['fileId'], cabinet=record['cabinet'])
    receipt = runtime/'opengeul-msi-dependencies.json'
    with receipt.open('x', encoding='utf-8') as stream:
        marker = 'amd64' if architecture == 'x64' else 'arm64'
        json.dump({'schemaVersion': 1, 'architecture': architecture, 'inputMsiSha256': sha256(archive),
                   'recovery': 'embedded-'+marker+'-file-ids', 'files': files}, stream, indent=2)
        stream.write('\n')
    return runtime


def stage_msi_dependencies(extraction_root: Path, runtime_root: Path, *, architecture: str = 'x64') -> dict:
    """Copy the pinned MSI's native VC++ DLLs into its scratch runtime.

    Administrative extraction puts these files in System64 rather than program.
    Validate every source and existing destination before copying any dependency;
    never use the sibling System directory containing x86 binaries.
    """
    machine = native_machine(architecture)
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
    expected = frozenset(crt_names(architecture))
    if architecture == 'arm64' and candidates.keys() - expected:
        raise ValueError('Unexpected ARM64 CRT family members: '+', '.join(sorted(candidates.keys() - expected)))
    missing = expected - candidates.keys()
    if missing:
        raise ValueError('Missing pinned MSI System64 dependencies: '+', '.join(sorted(missing)))
    existing = {}
    for path in target.iterdir():
        name = path.name.lower()
        if architecture == 'arm64' and is_vc_crt_file(name) and name not in expected:
            raise ValueError('Unexpected ARM64 CRT destination family member: '+name)
        if name in candidates:
            if name in existing:
                raise ValueError('MSI dependency destination case collision: '+name)
            existing[name] = path
    result = {}
    for name, path in sorted(candidates.items()):
        info = regular(path)
        _pe(path, architecture=architecture)
        with path.open('rb') as stream:
            stream.seek(60)
            pe_offset = struct.unpack('<I', stream.read(4))[0]
            stream.seek(pe_offset+4)
            if struct.unpack('<H', stream.read(2))[0] != machine:
                raise ValueError('MSI dependency must use native '+architecture+' architecture: '+name)
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
    parser.add_argument('--architecture', choices=tuple(NATIVE_MACHINES), default='x64')
    parser.add_argument('--engine-archive', type=Path,
                        help='Locally authenticated source-built engine ZIP (source-built-zip lock only)')
    parser.add_argument('--engine-receipt', type=Path,
                        help='Exact source-build-receipt.json pinned by the committed runtime lock')
    args = parser.parse_args()
    lock_name = 'runtime.lock.json' if args.architecture == 'x64' else 'runtime.arm64.lock.json'
    lock = json.loads((ROOT/'suite/config'/lock_name).read_text(encoding='utf-8'))
    if lock.get('architecture') != args.architecture:
        raise ValueError('Runtime lock architecture does not match requested native architecture')
    runtime_format = lock['runtime'].get('format', 'msi')
    if runtime_format == 'source-built-zip':
        if (args.engine_archive is None or args.engine_receipt is None
                or not args.engine_archive.exists() or not args.engine_receipt.exists()):
            raise ValueError('Authenticated source-build artifact needed: supply --engine-archive with the local '
                             'inner engine ZIP and --engine-receipt with its externally pinned source-build-receipt.json')
        runtime = extract_source_engine_zip(args.engine_archive, args.work/'source-engine-runtime',
                                            runtime=lock['runtime'], receipt=args.engine_receipt,
                                            architecture=args.architecture)
    elif runtime_format == 'msi':
        if args.engine_archive is not None or args.engine_receipt is not None:
            raise ValueError('Engine archive/receipt options require a source-built-zip runtime lock')
        msi = download_locked(lock['runtime'], args.work/'inputs/office.msi')
    else:
        raise ValueError('Unsupported runtime format: '+str(runtime_format))
    hwp = download_locked(lock['hwp'], args.work/'inputs/hwp.zip')
    if runtime_format == 'msi':
        runtime = extract_msi(msi, args.work/'msi', architecture=args.architecture)
    from package import assemble
    assemble(runtime=runtime, hwp=hwp, shell=args.shell, output=args.output, lock=lock)
    print('OpenGeul Office package prepared and verified:', args.output)


if __name__ == '__main__': main()
