"""Read-only external source admission for the native-menu E2E controller.

This joins authenticated Full source evidence to two packaged provider files.
It grants no process, COM-origin, input, or GUI-acceptance claim. Existing whole
asset/payload checks are bounded by checks before/after; synchronous I/O cannot
be hard-preempted. New streaming reads also check the original absolute deadline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import time
from types import MappingProxyType
from typing import Mapping
import zipfile

# E2E CLIs put only this directory on sys.path, including from external cwd.
# Resolve canonical dependencies from this checked-in file, never a bare fallback.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from suite import payload, prepare


# Fixed reviewed harness inputs, never a supplied lock path or packaged lock.
_HARNESS_ROOT = prepare.ROOT
_LOCK_NAMES = {'x64': 'runtime.lock.json', 'arm64': 'runtime.arm64.lock.json'}
_CORE = 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
_PROVIDERS = ((1, 'program/UAccCOM.dll'), (2, 'program/winaccessibility.dll'))
_MAX_ARCHIVE_BYTES = 8*1024*1024*1024
_MAX_FILE_BYTES = 1024*1024*1024
_MAX_MEMBERS = 100_000
_CHUNK = 1024*1024
_ADMISSION_SEAL = object()
_PATCH_FIELDS = dict(schemaVersion=1, kind='winacc-focus-order-source-patch', passed=True,
    coreCommit=_CORE, path='winaccessibility/source/service/AccObjectWinManager.cxx',
    beforeSha256='ab5ed31cac9b262461b1d7e45fbe4a5758fef852a0f51c08c0c6f8e25d1c9be0',
    afterSha256='5e5f42a6b448c0d9c70a05bf762e86951565b5a96decaf050399f577dd38332b',
    patchSha256='968379ba427ac952c5c7df7f0c37ceabb495310acc224ee5380d51f523fb3ed7',
    nativeBuildVerified=False, guiVerified=False, currentCiRootCauseConfirmed=False)
_PATCH_FILES = [
    dict(path='winaccessibility/source/service/AccObjectWinManager.cxx',
        beforeBytes=33670, afterBytes=33670,
        beforeSha256='ab5ed31cac9b262461b1d7e45fbe4a5758fef852a0f51c08c0c6f8e25d1c9be0',
        afterSha256='5e5f42a6b448c0d9c70a05bf762e86951565b5a96decaf050399f577dd38332b'),
    dict(path='winaccessibility/source/service/AccObject.cxx', beforeBytes=26374, afterBytes=26374,
        beforeSha256='e0e27e04a32b28eb3883e3020a037baa858c5014d5b769e86f05417b32d66e8e',
        afterSha256='e0e27e04a32b28eb3883e3020a037baa858c5014d5b769e86f05417b32d66e8e'),
    dict(path='winaccessibility/source/UAccCOM/MAccessible.cxx', beforeBytes=90847, afterBytes=90847,
        beforeSha256='98cb71a8b4c65683ad5ab891bff83a2fc6702bbff39c79d27b74d3a405a9ffad',
        afterSha256='98cb71a8b4c65683ad5ab891bff83a2fc6702bbff39c79d27b74d3a405a9ffad')]


def _deadline(deadline: float) -> None:
    if (type(deadline) not in (int, float) or not math.isfinite(deadline)
            or time.monotonic() >= deadline):
        raise ValueError('Source menu admission deadline expired or invalid')


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def _absolute(path: Path) -> Path:
    path = Path(path)
    if '..' in path.parts:
        raise ValueError('Source menu identity path is ambiguous')
    return path.absolute()


def _stat_identity(info) -> tuple[int, ...]:
    return tuple(getattr(info, key) for key in
        ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


@dataclass(frozen=True, slots=True)
class _FileState:
    file: tuple[int, ...]
    ancestors: tuple[tuple[int, ...], ...]


def _file_state(path: Path, deadline: float, *, limit: int) -> _FileState:
    path = _absolute(path)
    ancestors = []
    try:
        for parent in reversed(path.parents):
            _deadline(deadline)
            info = parent.lstat()
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or getattr(info, 'st_file_attributes', 0) & 0x400):
                raise ValueError('Source menu identity has a linked or non-directory ancestor')
            ancestors.append((info.st_dev, info.st_ino, info.st_mode))
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400
                or not 0 < info.st_size <= limit):
            raise ValueError('Source menu identity requires a bounded regular file')
    except OSError:
        raise ValueError('Source menu identity file is unavailable') from None
    _deadline(deadline)
    return _FileState(_stat_identity(info), tuple(ancestors))


def _unchanged(path: Path, before: _FileState, deadline: float, *, limit: int) -> None:
    if _file_state(path, deadline, limit=limit) != before:
        raise ValueError('Source menu identity changed during verification')


def _stream(reader, *, size: int, deadline: float, collect: bool = False) -> tuple[str, bytes]:
    result = hashlib.sha256()
    total, blocks = 0, []
    while True:
        _deadline(deadline)
        block = reader.read(min(_CHUNK, size-total+1))
        _deadline(deadline)
        if not block:
            break
        total += len(block)
        if total > size:
            raise ValueError('Source menu stream exceeds its size bound')
        result.update(block)
        if collect:
            blocks.append(block)
    if total != size:
        raise ValueError('Source menu stream size differs from its identity')
    return result.hexdigest(), b''.join(blocks)


def _hash_file(path: Path, *, deadline: float, limit: int,
               collect: bool = False) -> tuple[str, bytes, _FileState]:
    before = _file_state(path, deadline, limit=limit)
    try:
        with path.open('rb') as reader:
            if _stat_identity(os.fstat(reader.fileno())) != before.file:
                raise ValueError('Source menu opened file identity differs')
            digest, data = _stream(reader, size=before.file[3], deadline=deadline, collect=collect)
            if _stat_identity(os.fstat(reader.fileno())) != before.file:
                raise ValueError('Source menu opened file changed during verification')
    except OSError:
        raise ValueError('Source menu identity read failed') from None
    _unchanged(path, before, deadline, limit=limit)
    return digest, data, before


def _json_file(path: Path, deadline: float) -> tuple[dict, str, _FileState]:
    digest, data, state = _hash_file(path, deadline=deadline, limit=payload.MAX_METADATA, collect=True)
    try:
        value = payload._json_bytes(data, 'source menu metadata')
    except ValueError:
        raise ValueError('Source menu metadata is malformed') from None
    _deadline(deadline)
    return value, digest, state


@dataclass(frozen=True, slots=True)
class _ProviderMember:
    role: int
    member_name: str
    size: int
    sha256: str


def _hash_provider_members(archive: Path, *, deadline: float) -> tuple[_ProviderMember, ...]:
    """Hash exact provider members without extracting or trusting a path alias."""
    archive = _absolute(archive)
    before = _file_state(archive, deadline, limit=_MAX_ARCHIVE_BYTES)
    try:
        with archive.open('rb') as raw:
            if _stat_identity(os.fstat(raw.fileno())) != before.file:
                raise ValueError('Source menu opened ZIP identity differs')
            with zipfile.ZipFile(raw) as source:
                members = source.infolist()
                if not members or len(members) > _MAX_MEMBERS:
                    raise ValueError('Source menu ZIP member count exceeds bound')
                aliases, explicit, selected, total = {}, set(), {}, 0
                for member in members:
                    _deadline(deadline)
                    try:
                        prepare.archive_path(member.orig_filename)
                        name = prepare.archive_path(member.filename)
                    except ValueError:
                        raise ValueError('Source menu ZIP member path is unsafe') from None
                    key = name.casefold()
                    directory = member.is_dir()
                    kind = stat.S_IFMT(member.external_attr >> 16)
                    if (key in explicit or key.split('/')[0] in
                            ('opengeul-source-build.json', 'opengeul-msi-dependencies.json')
                            or member.flag_bits & 1 or member.external_attr & 0x400
                            or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                            or kind not in ((0, stat.S_IFDIR) if directory else (0, stat.S_IFREG))):
                        raise ValueError('Source menu ZIP member kind or collision is unsafe')
                    explicit.add(key)
                    parts = name.split('/')
                    for index in range(1, len(parts)+1):
                        prefix = '/'.join(parts[:index])
                        alias, is_directory = prefix.casefold(), index < len(parts) or directory
                        if alias in aliases and (aliases[alias][0] != prefix
                                or not aliases[alias][1] or not is_directory):
                            raise ValueError('Source menu ZIP has a case or path collision')
                        aliases[alias] = (prefix, is_directory)
                    total += member.file_size
                    if (not 0 <= member.file_size <= _MAX_FILE_BYTES or total > _MAX_ARCHIVE_BYTES
                            or directory and member.file_size
                            or not 0 <= member.compress_size <= before.file[3]):
                        raise ValueError('Source menu ZIP exceeds its declared size bound')
                    if name in dict(_PROVIDERS).values() and not directory:
                        selected[name] = member
                result = []
                for role, name in _PROVIDERS:
                    member = selected.get(name)
                    if member is None or member.file_size <= 0:
                        raise ValueError('Source menu ZIP lacks an exact provider member')
                    with source.open(member) as reader:
                        digest, _ = _stream(reader, size=member.file_size, deadline=deadline)
                    result.append(_ProviderMember(role, name, member.file_size, digest))
            if _stat_identity(os.fstat(raw.fileno())) != before.file:
                raise ValueError('Source menu opened ZIP changed during verification')
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise ValueError('Source menu ZIP read failed') from None
    _unchanged(archive, before, deadline, limit=_MAX_ARCHIVE_BYTES)
    return tuple(result)


def _recipe_identity(proof: dict, runtime: dict, architecture: str) -> str:
    patch = proof.get('winAccFocusOrderSourcePatch')
    if (runtime.get('sourceCoreCommit') != _CORE or not isinstance(patch, dict)
            or any(type(patch.get(key)) is not type(value) or patch[key] != value
                   for key, value in _PATCH_FIELDS.items())
            or _canonical(patch.get('sourceFiles')) != _canonical(_PATCH_FILES)
            or architecture == 'arm64' and proof.get('sourceRecipeProof') is not None):
        raise ValueError('Source menu source core or reviewed WinAcc recipe differs')
    # ARM's historical Full proof has no sourceRecipeProof. Its independently
    # locked manifest and fixed common patch remain bound, without today's x64
    # manifest. The existing x64 validator already enforces its complete recipe.
    recipe = dict(architecture=prepare.native_machine(architecture),
        sourceManifestSha256=runtime['sourceBuild']['patchManifestSha256'],
        winAccPatch=dict(_PATCH_FIELDS, sourceFiles=_PATCH_FILES),
        sourceRecipe=proof.get('sourceRecipeProof'))
    return hashlib.sha256(_canonical(recipe)).hexdigest()


@dataclass(frozen=True, slots=True)
class _ProviderIdentity:
    member: _ProviderMember
    state: _FileState = field(repr=False)


@dataclass(frozen=True, slots=True, init=False)
class SourceMenuAdmission:
    """Immutable controller context; obtain it through admission before launch."""
    suite_root: Path = field(repr=False)
    architecture: str
    admission_sha256: str
    _providers: tuple[_ProviderIdentity, ...] = field(repr=False)
    _summary: Mapping[str, object] = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __init__(self):
        raise TypeError('Source menu admission requires the verified factory')

    def _require_admitted(self) -> None:
        if (getattr(self, '_seal', None) is not _ADMISSION_SEAL
                or tuple((item.member.role, item.member.member_name)
                         for item in self._providers) != _PROVIDERS):
            raise ValueError('Source menu context was not admitted with both providers')

    def summary(self) -> Mapping[str, object]:
        """Closed immutable numeric/binary identity summary, without local paths."""
        self._require_admitted()
        return self._summary

    def verify_provider_files(self, deadline: float) -> None:
        """Recheck the two actual providers once before the action's first input."""
        _deadline(deadline)
        self._require_admitted()
        for provider in self._providers:
            member = provider.member
            digest, _, state = _hash_file(self.suite_root/'Office'/member.member_name,
                deadline=deadline, limit=_MAX_FILE_BYTES)
            if (state != provider.state or state.file[3] != member.size or digest != member.sha256):
                raise ValueError('Source menu admitted provider identity changed')
        _deadline(deadline)


def admit_source_menu_runtime(suite: Path, *, architecture: str, engine_zip: Path,
                              receipt: Path, deadline: float) -> SourceMenuAdmission:
    """Fail closed unless external Full source evidence joins both actual PEs.

    Full ZIP and payload hashing happen once here, before launch. The existing
    payload validator also authenticates its bundled receipt and calls
    validate_source_build_runtime with the final branding. No writing extractor
    or downloader is used, and a caller's absolute deadline is never renewed.
    """
    _deadline(deadline)
    if type(architecture) is not str or architecture not in _LOCK_NAMES:
        raise ValueError('Source menu architecture is unsupported')
    suite, engine_zip, receipt = map(_absolute, (suite, engine_zip, receipt))
    lock_path = _HARNESS_ROOT/'suite/config'/_LOCK_NAMES[architecture]
    lock, lock_sha, lock_state = _json_file(lock_path, deadline)
    runtime = lock.get('runtime')
    if (type(lock.get('schemaVersion')) is not int or lock['schemaVersion'] != 1
            or lock.get('architecture') != architecture or not isinstance(runtime, dict)
            or runtime.get('sourceCoreCommit') != _CORE):
        raise ValueError('Source menu requires an external reviewed source runtime lock')
    try:
        prepare.validate_source_build_lock(runtime, architecture=architecture)
    except ValueError:
        raise ValueError('Source menu external source lock is unsupported') from None
    _deadline(deadline)
    provenance, _, provenance_state = _json_file(suite/'suite-provenance.json', deadline)
    if (provenance.get('architecture') != architecture
            or _canonical(provenance.get('runtime')) != _canonical(runtime)):
        raise ValueError('Source menu bundle runtime differs from external reviewed lock')
    inventory, inventory_sha, inventory_state = _json_file(suite/'suite-inventory.json', deadline)
    if inventory.get('architecture') != architecture:
        raise ValueError('Source menu inventory architecture differs')
    archive_state = _file_state(engine_zip, deadline, limit=_MAX_ARCHIVE_BYTES)
    receipt_state = _file_state(receipt, deadline, limit=8*1024*1024)
    try:
        prepare.check_asset(runtime, engine_zip)
    except (OSError, ValueError):
        raise ValueError('Source menu external engine ZIP verification failed') from None
    _unchanged(engine_zip, archive_state, deadline, limit=_MAX_ARCHIVE_BYTES)
    try:
        proof = prepare.validate_source_build_receipt(runtime, receipt, architecture=architecture)
    except (OSError, ValueError):
        raise ValueError('Source menu external Full receipt verification failed') from None
    _unchanged(receipt, receipt_state, deadline, limit=8*1024*1024)
    recipe_sha = _recipe_identity(proof, runtime, architecture)
    watches = [(lock_path, lock_state, payload.MAX_METADATA),
        (suite/'suite-provenance.json', provenance_state, payload.MAX_METADATA),
        (suite/'suite-inventory.json', inventory_state, payload.MAX_METADATA),
        (engine_zip, archive_state, _MAX_ARCHIVE_BYTES), (receipt, receipt_state, 8*1024*1024)]
    for name in ('suite-product.json', 'runtime-branding.json', 'Office/opengeul-branding.json',
                 'Office/opengeul-source-build.json', 'Office/program/version.ini',
                 'Office/program/setup.ini', 'Office/program/bootstrap.ini',
                 'Sources/OpenGeul-Office-source.zip'):
        path = suite/name
        limit = _MAX_ARCHIVE_BYTES if name.startswith('Sources/') else payload.MAX_METADATA
        watches.append((path, _file_state(path, deadline, limit=limit), limit))
    provider_states = {name: _file_state(suite/'Office'/name, deadline, limit=_MAX_FILE_BYTES)
                       for _, name in _PROVIDERS}
    _deadline(deadline)
    try:
        payload.verify_payload(suite, inventory)
    except (OSError, ValueError):
        raise ValueError('Source menu complete Suite payload verification failed') from None
    _deadline(deadline)
    bundled = inventory['files'].get('Office/opengeul-source-build.json')
    if bundled != dict(size=receipt_state.file[3], sha256=runtime['sourceBuild']['receiptSha256']):
        raise ValueError('Source menu inventoried receipt differs from external Full receipt')
    providers = []
    for member in _hash_provider_members(engine_zip, deadline=deadline):
        digest, _, state = _hash_file(suite/'Office'/member.member_name,
            deadline=deadline, limit=_MAX_FILE_BYTES)
        if (state != provider_states[member.member_name]
                or state.file[3] != member.size or digest != member.sha256
                or inventory['files'].get('Office/'+member.member_name) !=
                   dict(size=member.size, sha256=member.sha256)):
            raise ValueError('Source menu provider ZIP, actual bytes and inventory differ')
        providers.append(_ProviderIdentity(member, state))
    for path, before, limit in watches:
        _unchanged(path, before, deadline, limit=limit)
    body = dict(schemaVersion=1, architecture=prepare.native_machine(architecture),
        lockSha256=lock_sha, receiptSha256=runtime['sourceBuild']['receiptSha256'],
        engineZipSha256=runtime['sha256'], inventorySha256=inventory_sha,
        sourceCoreCommit=_CORE, sourceRecipeSha256=recipe_sha,
        providers=[dict(role=item.member.role, size=item.member.size, sha256=item.member.sha256)
                   for item in providers])
    admission_sha = hashlib.sha256(_canonical(dict(suiteRoot=str(suite), summary=body))).hexdigest()
    body['providers'] = tuple(MappingProxyType(item) for item in body['providers'])
    summary = MappingProxyType(dict(body, admissionSha256=admission_sha))
    _deadline(deadline)
    admitted = object.__new__(SourceMenuAdmission)
    for key, value in (('suite_root', suite), ('architecture', architecture),
            ('admission_sha256', admission_sha), ('_providers', tuple(providers)),
            ('_summary', summary), ('_seal', _ADMISSION_SEAL)):
        object.__setattr__(admitted, key, value)
    return admitted
