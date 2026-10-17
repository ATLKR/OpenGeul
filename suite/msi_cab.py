"""Recover exact native CRT members from a read-only Windows MSI database.

Administrative extraction can flatten AMD64 and ARM64 rows onto the same name.
This module selects original File IDs and extracts those cabinet members only.
"""
from contextlib import contextmanager
import ctypes
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import struct
import subprocess
import tempfile

EXPECTED_X64_CRT = ('concrt140.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
                    'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll', 'vcruntime140.dll',
                    'vcruntime140_1.dll', 'vcruntime140_threads.dll')
_ARCHITECTURES = {'x64': ('amd64', 'AMD64', 0x8664), 'arm64': ('arm64', 'ARM64', 0xAA64)}


def _architecture(architecture):
    try:
        return _ARCHITECTURES[architecture]
    except (KeyError, TypeError):
        raise ValueError('Unsupported native CRT architecture: ' + str(architecture)) from None


def _safe_member(value):
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,254}', value)
            or value.endswith('.') or value in ('.', '..') or PureWindowsPath(value).is_reserved()):
        raise ValueError('Unsafe MSI cabinet or File ID: ' + repr(value))
    return value


def _positive(value, label):
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and re.fullmatch(r'[0-9]+', value) and int(value) > 0:
        return int(value)
    raise ValueError('Invalid MSI ' + label)


def select_crt(file_rows, media_rows, *, architecture='x64'):
    """Map the nine friendly DLL names to exact native File IDs and Media rows."""
    marker, label, _ = _architecture(architecture)
    native = re.compile(r'_' + marker + r'(?:[._]|$)', re.IGNORECASE)
    others = '|'.join(value for value in ('amd64', 'arm64', 'x86', 'ia64') if value != marker)
    other_arch = re.compile(r'_(?:' + others + r')(?:[._]|$)', re.IGNORECASE)
    disks = []
    for row in media_rows:
        disks.append((_positive(row.get('DiskId'), 'DiskId'),
                      _positive(row.get('LastSequence'), 'LastSequence'), row.get('Cabinet')))
    disks.sort()
    if (not disks or len({disk[0] for disk in disks}) != len(disks)
            or any(first[1] >= second[1] for first, second in zip(disks, disks[1:]))):
        raise ValueError('Missing or ambiguous MSI Media sequence ranges')
    result, file_ids, sequences = {}, set(), set()
    for row in file_rows:
        filename = row.get('FileName')
        if not isinstance(filename, str):
            continue
        name = filename.rsplit('|', 1)[-1].casefold()
        if name not in EXPECTED_X64_CRT:
            continue
        file_id, component = row.get('File'), row.get('Component_')
        if not isinstance(file_id, str) or not isinstance(component, str):
            raise ValueError('Missing MSI File ID or Component')
        if not (native.search(file_id) or native.search(component)):
            continue
        if other_arch.search(file_id) or other_arch.search(component):
            raise ValueError('Conflicting architecture in MSI File row')
        _safe_member(file_id)
        sequence = _positive(row.get('Sequence'), 'File Sequence')
        if name in result or file_id.casefold() in file_ids or sequence in sequences:
            raise ValueError('Duplicate ' + label + ' CRT row in MSI: ' + name)
        disk = next((disk for disk in disks if sequence <= disk[1]), None)
        if disk is None:
            raise ValueError('Missing cabinet for MSI File sequence')
        cabinet = disk[2]
        if not isinstance(cabinet, str) or not cabinet.startswith('#'):
            raise ValueError('Selected CRT cabinet must be embedded in the MSI')
        _safe_member(cabinet[1:])
        result[name] = {'fileId': file_id, 'cabinet': cabinet}
        file_ids.add(file_id.casefold())
        sequences.add(sequence)
    missing = set(EXPECTED_X64_CRT) - set(result)
    if missing:
        raise ValueError('MSI is missing ' + label + ' CRT files: ' + ', '.join(sorted(missing)))
    return {name: result[name] for name in EXPECTED_X64_CRT}


def select_x64_crt(file_rows, media_rows):
    """Compatibility entry point for exact AMD64 CRT selection."""
    return select_crt(file_rows, media_rows, architecture='x64')


def _verify_native(path, *, architecture):
    _, label, machine = _architecture(architecture)
    with path.open('rb') as source:
        header = source.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise ValueError('Recovered CRT is not a ' + label + ' PE: ' + path.name)
        offset = struct.unpack_from('<I', header, 60)[0]
        if offset < 64 or offset > path.stat().st_size - 6:
            raise ValueError('Recovered CRT has an invalid ' + label + ' PE header: ' + path.name)
        source.seek(offset)
        signature = source.read(6)
        if signature[:4] != b'PE\0\0' or struct.unpack_from('<H', signature, 4)[0] != machine:
            raise ValueError('Recovered CRT must be ' + label + ': ' + path.name)


def windows_expand_path():
    if os.name != 'nt':
        raise OSError('MSI cabinet extraction requires Windows')
    root = os.environ.get('SystemRoot')
    if not root:
        raise OSError('Windows SystemRoot is unavailable')
    executable = Path(root) / 'System32' / 'expand.exe'
    if not executable.is_file():
        raise OSError('Windows expand.exe is unavailable')
    return executable


def expand_file(cabinet, file_id, destination):
    _safe_member(file_id)
    subprocess.run([str(windows_expand_path()), '-F:' + file_id, str(cabinet), str(destination)],
                   check=True, capture_output=True, timeout=120,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def recover_crt(msi: Path, output: Path, *, architecture='x64') -> dict:
    """Return friendly DLL -> {path, fileId, cabinet}, publishing a fresh directory.

    The caller pins and verifies the MSI digest. Original MSI and existing output
    directories are never modified. Failure leaves no partially published output.
    """
    _architecture(architecture)
    msi, output = Path(msi).resolve(strict=True), Path(output).absolute()
    if not msi.is_file():
        raise ValueError('MSI source must be a file')
    if output.exists() or output.is_symlink():
        raise ValueError('CRT recovery output must not already exist')
    if not output.parent.is_dir():
        raise ValueError('CRT recovery output parent must exist')
    with tempfile.TemporaryDirectory(prefix='.opengeul-msi-', dir=output.parent) as temporary:
        scratch = Path(temporary)
        staged = scratch / 'recovered'
        staged.mkdir()
        with WindowsMsiDatabase(msi) as database:
            selected = select_crt(database.file_rows(), database.media_rows(), architecture=architecture)
            cabinets = {}
            for row in selected.values():
                stream = row['cabinet'][1:]
                if stream not in cabinets:
                    cabinet = scratch / stream
                    database.extract_stream(stream, cabinet, msi.stat().st_size)
                    with cabinet.open('rb') as source:
                        if source.read(4) != b'MSCF':
                            raise ValueError('Embedded MSI stream is not a cabinet')
                    cabinets[stream] = cabinet
        for index, (name, row) in enumerate(selected.items()):
            extracted = scratch / ('member-' + str(index))
            extracted.mkdir()
            expand_file(cabinets[row['cabinet'][1:]], row['fileId'], extracted)
            member = extracted / row['fileId']
            if (member.is_symlink() or not member.is_file()
                    or any(path.name.casefold() != row['fileId'].casefold() for path in extracted.iterdir())):
                raise ValueError('Exact MSI cabinet member is missing or ambiguous: ' + row['fileId'])
            _verify_native(member, architecture=architecture)
            shutil.copyfile(member, staged / name)
        if output.exists() or output.is_symlink():
            raise ValueError('CRT recovery output was created during extraction')
        # On Windows rename fails if the destination already exists, including a
        # directory created by another producer while extraction was in progress.
        staged.rename(output)
    return {name: dict(row, path=output / name) for name, row in selected.items()}


def recover_x64_crt(msi: Path, output: Path) -> dict:
    """Compatibility entry point for exact native AMD64 CRT recovery."""
    return recover_crt(msi, output, architecture='x64')


class WindowsMsiDatabase:
    """Small read-only MSI API wrapper; every database/view/record is owned."""
    def __init__(self, path):
        if os.name != 'nt':
            raise OSError('Reading MSI cabinets through Windows Installer requires Windows')
        self.api = ctypes.WinDLL('msi', use_last_error=True)
        self.handle = ctypes.c_uint32()
        self._bind()
        self._check(self.open_database(str(path), None, ctypes.byref(self.handle)), 'open MSI read-only')

    def _bind(self):
        uint, pointer = ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)
        def function(name, args, result=uint):
            call = getattr(self.api, name)
            call.argtypes, call.restype = args, result
            return call
        self.open_database = function('MsiOpenDatabaseW', [ctypes.c_wchar_p, ctypes.c_void_p, pointer])
        self.close_handle = function('MsiCloseHandle', [uint])
        self.open_view = function('MsiDatabaseOpenViewW', [uint, ctypes.c_wchar_p, pointer])
        self.execute_view = function('MsiViewExecute', [uint, uint])
        self.fetch_view = function('MsiViewFetch', [uint, pointer])
        self.close_view = function('MsiViewClose', [uint])
        self.get_string = function('MsiRecordGetStringW', [uint, uint, ctypes.c_wchar_p, pointer])
        self.get_integer = function('MsiRecordGetInteger', [uint, uint], ctypes.c_int32)
        self.create_record = function('MsiCreateRecord', [uint])
        self.set_string = function('MsiRecordSetStringW', [uint, uint, ctypes.c_wchar_p])
        self.read_stream = function('MsiRecordReadStream', [uint, uint, ctypes.c_void_p, pointer])

    @staticmethod
    def _check(status, operation):
        if status != 0:
            raise OSError(status, 'Windows Installer could not ' + operation)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.handle.value:
            self.close_handle(self.handle)
            self.handle.value = 0

    @contextmanager
    def _view(self, query, parameters=0):
        handle = ctypes.c_uint32()
        self._check(self.open_view(self.handle, query, ctypes.byref(handle)), 'open query')
        try:
            self._check(self.execute_view(handle, parameters), 'execute query')
            yield handle
        finally:
            self.close_view(handle)
            self.close_handle(handle)

    @contextmanager
    def _record(self, view):
        record = ctypes.c_uint32()
        status = self.fetch_view(view, ctypes.byref(record))
        if status == 259:  # ERROR_NO_MORE_ITEMS
            yield None
            return
        self._check(status, 'fetch query record')
        try:
            yield record
        finally:
            self.close_handle(record)

    def _string(self, record, index):
        size = ctypes.c_uint32()
        status = self.get_string(record, index, None, ctypes.byref(size))
        if status not in (0, 234):  # ERROR_MORE_DATA is the size-probe result
            self._check(status, 'read string length')
        size.value += 1
        buffer = ctypes.create_unicode_buffer(size.value)
        self._check(self.get_string(record, index, buffer, ctypes.byref(size)), 'read string')
        return buffer.value

    def _rows(self, query, fields):
        rows = []
        with self._view(query) as view:
            while True:
                with self._record(view) as record:
                    if record is None:
                        return rows
                    row = {}
                    for index, (name, integer) in enumerate(fields, 1):
                        row[name] = self.get_integer(record, index) if integer else self._string(record, index)
                    rows.append(row)

    def file_rows(self):
        return self._rows('SELECT `File`, `FileName`, `Sequence`, `Component_` FROM `File`',
                          (('File', False), ('FileName', False), ('Sequence', True), ('Component_', False)))

    def media_rows(self):
        return self._rows('SELECT `DiskId`, `LastSequence`, `Cabinet` FROM `Media`',
                          (('DiskId', True), ('LastSequence', True), ('Cabinet', False)))

    def extract_stream(self, name, destination, limit):
        _safe_member(name)
        parameters = self.create_record(1)
        if not parameters:
            raise OSError('Windows Installer could not create stream query parameters')
        try:
            self._check(self.set_string(parameters, 1, name), 'set stream query parameter')
            with self._view('SELECT `Data` FROM `_Streams` WHERE `Name` = ?', parameters) as view:
                with self._record(view) as record:
                    if record is None:
                        raise ValueError('Embedded MSI cabinet stream is missing: ' + name)
                    self._copy_stream(record, destination, limit)
                with self._record(view) as duplicate:
                    if duplicate is not None:
                        raise ValueError('Duplicate embedded MSI cabinet stream: ' + name)
        finally:
            self.close_handle(parameters)

    def _copy_stream(self, record, destination, limit):
        total = 0
        buffer = ctypes.create_string_buffer(65536)
        with Path(destination).open('xb') as output:
            while True:
                size = ctypes.c_uint32(len(buffer))
                self._check(self.read_stream(record, 1, buffer, ctypes.byref(size)), 'read embedded cabinet')
                if not size.value:
                    return
                total += size.value
                if size.value > len(buffer) or total > limit:
                    raise ValueError('Embedded MSI cabinet exceeds source size bound')
                output.write(buffer.raw[:size.value])
