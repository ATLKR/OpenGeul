"""Bounded native compiler EXE admission; no process launch or DLL loading."""
import hashlib
import os
from pathlib import Path
import re
import struct


MAX_TOOL_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
MACHINES = {'x64': 0x8664, 'arm64': 0xaa64}
STAT_FIELDS = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')


def validate_tool_pin(value, architecture, name):
    assert architecture in MACHINES and name in ('clang-cl.exe', 'lld-link.exe')
    assert type(value) is dict and set(value) == {'path', 'bytes', 'sha256', 'machine'}
    assert type(value['path']) is str and Path(value['path']).is_absolute() and Path(value['path']).name == name
    assert type(value['bytes']) is int and 0 < value['bytes'] <= MAX_TOOL_BYTES
    assert type(value['machine']) is int and value['machine'] == MACHINES[architecture]
    assert type(value['sha256']) is str and re.fullmatch('[0-9a-f]{64}', value['sha256'])


def pin_native_tool(path, architecture, *, check, facts=None):
    """Stream under the caller's original deadline; reject managed/foreign EXEs."""
    assert architecture in MACHINES
    path = Path(path)
    check()
    assert path.is_absolute() and path.is_file(), 'Native compiler tool is unavailable'
    for part in (path, *path.parents):
        assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(), 'Linked native compiler path'
    assert facts is None or type(facts) is dict and not facts
    def identity(value):
        return tuple(getattr(value, key) for key in STAT_FIELDS)
    def observe(label, query):
        check()
        value = query()
        raw = dict(zip(STAT_FIELDS, identity(value)))
        assert all(type(v) is int and v.bit_length() <= 256 for v in raw.values()), 'Invalid native compiler stat metadata'
        if facts is not None: facts[label] = raw
        check()
        return value
    before = observe('pathBefore', path.stat)
    assert 0 < before.st_size <= MAX_TOOL_BYTES, 'Native compiler tool exceeds bound'
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        fd_before = observe('fdBefore', lambda: os.fstat(stream.fileno()))
        def read(length):
            check()
            raw = stream.read(length)
            check()
            return raw
        dos = read(64)
        assert len(dos) == 64 and dos[:2] == b'MZ', 'Invalid native compiler DOS header'
        offset = struct.unpack_from('<I', dos, 60)[0]
        assert 64 <= offset <= 1024 * 1024, 'Invalid native compiler PE offset'
        stream.seek(offset)
        header = read(24)
        assert len(header) == 24 and header[:4] == b'PE\0\0', 'Invalid native compiler PE signature'
        machine, sections, _, _, _, optional_size, flags = struct.unpack_from('<HHIIIHH', header, 4)
        assert machine == MACHINES[architecture], 'Native compiler EXE host machine mismatch: ' + hex(machine)
        assert 1 <= sections <= 96 and 112 <= optional_size <= 4096 and flags & 2 and not flags & 0x2000, 'Native compiler must be an executable, not a DLL'
        optional = read(optional_size)
        assert len(optional) == optional_size and struct.unpack_from('<H', optional)[0] == 0x20b, 'Native compiler requires PE32+'
        directories = struct.unpack_from('<I', optional, 108)[0]
        assert directories <= 16 and optional_size >= 112 + directories * 8, 'Invalid compiler PE data directories'
        if directories > 14:
            assert struct.unpack_from('<II', optional, 112 + 14 * 8) == (0, 0), 'Managed compiler executable is forbidden'
        stream.seek(0)
        while True:
            raw = read(CHUNK_BYTES)
            if not raw: break
            size += len(raw)
            assert size <= MAX_TOOL_BYTES, 'Native compiler tool exceeds bound'
            digest.update(raw)
        fd_after = observe('fdAfter', lambda: os.fstat(stream.fileno()))
        assert identity(fd_after) == identity(fd_before), 'Native compiler held FD changed while reading'
    after = observe('pathAfter', path.stat)
    assert identity(after) == identity(before), 'Native compiler path changed while reading'
    assert size == before.st_size == fd_before.st_size == fd_after.st_size == after.st_size, 'Native compiler streamed bytes disagree with stat sizes'
    value = dict(path=str(path), bytes=size, sha256=digest.hexdigest(), machine=machine)
    validate_tool_pin(value, architecture, path.name)
    check()
    return value
