"""Read bounded PE import-module metadata without loading executable code.

PE32 and PE32+ with standard power-of-two section alignment of at least 4 KiB
are supported; low-alignment layouts fail closed. Delay imports must use
modern RVA attributes (1); legacy VA descriptors and unknown attributes fail
closed. Symbol thunk contents are outside this reader's scope. Limits are 96 sections, 1 MiB per
directory, 4096 nonzero descriptors per table, and 255 ASCII bytes per name.
Names are safe module basenames (including modules such as WINSPOOL.DRV),
lowercased, deduplicated, and sorted. Architecture and dependency policy belong
to the caller. Malformed or ambiguous metadata raises ValueError.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import struct
from typing import BinaryIO


_MAX_SECTIONS = 96
_MAX_DIRECTORY = 1024 * 1024
_MAX_DESCRIPTORS = 4096
_MAX_NAME = 255
_RVA_LIMIT = 1 << 32
_BASENAME = re.compile(rb'[A-Za-z0-9_][A-Za-z0-9_.-]*')


class _Reader:
    def __init__(self, stream: BinaryIO):
        self.stream = stream
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('PE import input must be a regular file')
        self.size = info.st_size
        dos = self.read(0, 64)
        if dos[:2] != b'MZ':
            raise ValueError('Missing DOS signature')
        pe_offset = struct.unpack_from('<I', dos, 60)[0]
        if pe_offset < 64:
            raise ValueError('PE header overlaps the DOS header')
        coff = self.read(pe_offset, 24)
        if coff[:4] != b'PE\0\0':
            raise ValueError('Missing PE signature')
        section_count = struct.unpack_from('<H', coff, 6)[0]
        optional_size = struct.unpack_from('<H', coff, 20)[0]
        if not 1 <= section_count <= _MAX_SECTIONS:
            raise ValueError('PE section count is outside its bound')
        if not 2 <= optional_size <= 4096:
            raise ValueError('PE optional header size is outside its bound')
        self.optional = self.read(pe_offset + 24, optional_size)
        magic = struct.unpack_from('<H', self.optional)[0]
        if magic == 0x20b:
            self.directory_offset = 112
        elif magic == 0x10b:
            self.directory_offset = 96
        else:
            raise ValueError('Only PE32 and PE32+ optional headers are supported')
        if optional_size < self.directory_offset:
            raise ValueError('Truncated PE optional header')
        self.directory_count = struct.unpack_from('<I', self.optional, self.directory_offset - 4)[0]
        if self.directory_count > 16 or self.directory_count * 8 > optional_size - self.directory_offset:
            raise ValueError('PE data directory count does not fit the optional header')

        # Microsoft PE/COFF Optional Header and Section Table specifications:
        # https://learn.microsoft.com/en-us/windows/win32/debug/pe-format
        # Low-alignment images have additional file/RVA identity rules. They
        # are deliberately unsupported rather than interpreted as this layout.
        section_alignment, file_alignment = struct.unpack_from('<II', self.optional, 32)
        if not 512 <= file_alignment <= 65536 or file_alignment & (file_alignment - 1):
            raise ValueError('Invalid PE FileAlignment')
        if section_alignment < 4096 or section_alignment & (section_alignment - 1):
            raise ValueError('Unsupported low or non-power-of-two PE SectionAlignment')
        if section_alignment < file_alignment:
            raise ValueError('PE SectionAlignment must be at least FileAlignment')
        image_size = struct.unpack_from('<I', self.optional, 56)[0]
        if not image_size or image_size % section_alignment:
            raise ValueError('PE image size does not follow section alignment')

        section_offset = pe_offset + 24 + optional_size
        section_bytes = self.read(section_offset, section_count * 40)
        header_end = section_offset + len(section_bytes)
        declared_headers = struct.unpack_from('<I', self.optional, 60)[0]
        self.headers = declared_headers
        if self.headers < header_end or self.headers > self.size or self.headers % file_alignment:
            raise ValueError('PE header extent is truncated or inconsistent with FileAlignment')
        if self.headers > image_size:
            raise ValueError('PE image size does not cover its headers')

        self.sections = []
        raw_ranges = []
        for index in range(section_count):
            virtual_size, rva, raw_size, raw = struct.unpack_from('<IIII', section_bytes, index * 40 + 8)
            if rva % section_alignment or raw % file_alignment or raw_size % file_alignment:
                raise ValueError('PE section RVA or raw pointer/size violates alignment')
            virtual_end = rva + max(virtual_size, raw_size)
            if virtual_end > _RVA_LIMIT:
                raise ValueError('Section RVA extent overflows')
            if virtual_end > image_size:
                raise ValueError('PE section exceeds image size bounds')
            if virtual_end > rva:
                if rva < self.headers:
                    raise ValueError('Section RVA overlaps mapped headers')
                self.sections.append((rva, virtual_end, raw, raw_size))
            if raw_size:
                if raw < self.headers or raw + raw_size > self.size:
                    raise ValueError('Section raw bytes are truncated or overlap headers')
                raw_ranges.append((raw, raw + raw_size))
        self.sections.sort()
        self._unambiguous([(start, end) for start, end, _, _ in self.sections], 'virtual sections')
        self._unambiguous(sorted(raw_ranges), 'raw sections')

    @staticmethod
    def _unambiguous(ranges: list[tuple[int, int]], label: str) -> None:
        if any(previous[1] > current[0] for previous, current in zip(ranges, ranges[1:])):
            raise ValueError('Ambiguous overlapping ' + label)

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > self.size:
            raise ValueError('Truncated PE file bounds')
        self.stream.seek(offset)
        data = self.stream.read(length)
        if len(data) != length:
            raise ValueError('PE file changed or was truncated while reading')
        return data

    def chunk(self, rva: int) -> tuple[int, int]:
        """Return the file offset and contiguous backed bytes at an RVA."""
        if not 0 <= rva < _RVA_LIMIT:
            raise ValueError('Invalid PE RVA')
        if rva < self.headers:
            return rva, self.headers - rva
        for start, end, raw, raw_size in self.sections:
            if start <= rva < end:
                relative = rva - start
                if relative >= raw_size:
                    raise ValueError('PE RVA has no file-backed bytes')
                return raw + relative, raw_size - relative
        raise ValueError('PE RVA has no section mapping')

    def rva_bytes(self, rva: int, length: int) -> bytes:
        if rva + length > _RVA_LIMIT:
            raise ValueError('PE RVA read overflows')
        parts = []
        while length:
            offset, available = self.chunk(rva)
            count = min(length, available)
            parts.append(self.read(offset, count))
            rva += count
            length -= count
        return b''.join(parts)

    def name(self, rva: int) -> str:
        result = bytearray()
        remaining = _MAX_NAME + 1
        while remaining:
            offset, available = self.chunk(rva)
            count = min(available, remaining)
            data = self.read(offset, count)
            terminator = data.find(b'\0')
            if terminator >= 0:
                result.extend(data[:terminator])
                if not _BASENAME.fullmatch(result) or result.endswith(b'.'):
                    raise ValueError('Import name must be an ASCII module basename')
                return result.decode('ascii').lower()
            result.extend(data)
            remaining -= count
            rva += count
        raise ValueError('Import name is unterminated or exceeds its bound')

    def directory(self, index: int, *, delay: bool) -> tuple[tuple[str, ...], tuple[int, int] | None]:
        if index >= self.directory_count:
            return (), None
        rva, size = struct.unpack_from('<II', self.optional, self.directory_offset + index * 8)
        if not rva and not size:
            return (), None
        width = 32 if delay else 20
        if not rva or not size or not width <= size <= _MAX_DIRECTORY or rva + size > _RVA_LIMIT:
            raise ValueError('Import directory RVA/size is absent, truncated, or outside its bound')
        names = set()
        # Directory sizes may include names and thunks after the terminator.
        # Only the actual descriptor array defines its overlap extent.
        for index in range(min(size // width, _MAX_DESCRIPTORS + 1)):
            descriptor = self.rva_bytes(rva + index * width, width)
            if not any(descriptor):
                return tuple(sorted(names)), (rva, rva + (index + 1) * width)
            if index == _MAX_DESCRIPTORS:
                raise ValueError('Import descriptor count exceeds its bound')
            if delay:
                attributes, name = struct.unpack_from('<II', descriptor)
                if attributes != 1:
                    raise ValueError('Unsupported delay attributes; legacy VA descriptors are forbidden')
            else:
                name = struct.unpack_from('<I', descriptor, 12)[0]
            if not name:
                raise ValueError('Nonzero import descriptor has no module name')
            names.add(self.name(name))
        raise ValueError('Import descriptor table has no complete zero terminator')


def read_pe_imports(path: Path) -> dict:
    """Return ``{'normal': tuple[str, ...], 'delay': tuple[str, ...]}``.

    Inspection uses bounded file reads and never loads the supplied module.
    Import tables may span adjacent mapped sections. Declared directory size
    overlap alone is allowed; overlapping actual descriptor arrays is rejected.
    """
    with Path(path).open('rb') as stream:
        reader = _Reader(stream)
        normal, normal_range = reader.directory(1, delay=False)
        delay, delay_range = reader.directory(13, delay=True)
        if normal_range and delay_range:
            if max(normal_range[0], delay_range[0]) < min(normal_range[1], delay_range[1]):
                raise ValueError('Normal and delay import descriptor arrays overlap')
        return {'normal': normal, 'delay': delay}
