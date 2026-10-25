#!/usr/bin/env python3
"""Bounded file-only ARM64 mutex attribution. No DLL loading or symbol guessing."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import time
import zipfile

_spec = importlib.util.spec_from_file_location('opengeul_sal_mapping', Path(__file__).with_name('map-sal-offset.py'))
_sal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sal)
MappingError = _sal.MappingError
require = _sal.require
MAX_MEMBER = _sal.MAX_MEMBER
MAX_ARCHIVE = _sal.MAX_ARCHIVE
MAX_CANDIDATES = 16
SOURCE_CORE_COMMIT = 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
FIXTURE_EXPORT = '?doAcquire@OpenGeulFixtureMutex@@MEAAXI@Z'


class PE:
    def __init__(self, data, check):
        self.data, self.check = data, check
        check(); require(0 < len(data) <= MAX_MEMBER, 'member-size')
        require(self.take(0, 2) == b'MZ', 'dos-header')
        pe = self.u(0x3c)
        require(self.take(pe, 4) == b'PE\0\0' and self.u(pe+4, 'H') == 0xaa64, 'native-arm64-required')
        count, opt_size = self.u(pe+6, 'H'), self.u(pe+20, 'H')
        opt = pe+24
        require(1 <= count <= 96 and opt_size >= 160 and self.u(opt, 'H') == 0x20b, 'pe32plus-header')
        self.take(opt, opt_size)
        self.base = self.u(opt+24, 'Q')
        require(self.base > 0 and self.base % 65536 == 0, 'preferred-base')
        image_size, headers = self.u(opt+56), self.u(opt+60)
        dirs = self.u(opt+108)
        require(6 <= dirs <= 16 and 112+dirs*8 <= opt_size, 'directory-count')
        require(opt+opt_size+count*40 <= headers <= len(data) and headers <= image_size, 'headers-size')
        self.directories = [(self.u(opt+112+i*8), self.u(opt+116+i*8)) for i in range(dirs)]
        self.sections = []
        for i in range(count):
            off = opt+opt_size+i*40
            vs, va, size, raw = struct.unpack('<IIII', self.take(off+8, 16)); span = max(vs, size)
            require(span > 0 and va >= headers and va+span <= image_size, 'section-range')
            if size: require(raw >= headers, 'section-header-overlap'); self.take(raw, size)
            for ova, osp, oraw, osize, _ in self.sections:
                require(va+span <= ova or ova+osp <= va, 'section-overlap')
                require(not size or not osize or raw+size <= oraw or oraw+osize <= raw, 'section-file-overlap')
            self.sections.append((va, span, raw, size, self.u(off+36)))

    def take(self, offset, count):
        self.check()
        require(0 <= offset <= len(self.data) and 0 <= count <= len(self.data)-offset, 'file-range')
        return self.data[offset:offset+count]

    def u(self, off, fmt='I'):
        return struct.unpack('<'+fmt, self.take(off, struct.calcsize('<'+fmt)))[0]

    def rva(self, addr, count, executable=False):
        self.check(); require(addr > 0 and count > 0 and addr+count <= 0x100000000, 'rva-range')
        found = [(raw+addr-va, flags) for va, _, raw, size, flags in self.sections if va <= addr and addr+count <= va+size]
        require(len(found) == 1, 'unmapped-rva')
        off, flags = found[0]
        require(not executable or flags & 0x20000000, 'nonexecutable-range')
        return off

    def word(self, addr, fmt='I'):
        return self.u(self.rva(addr, struct.calcsize('<'+fmt)), fmt)

    def name(self, addr):
        chars = bytearray()
        for i in range(256):
            value = self.word(addr+i, 'B')
            if not value: return bytes(chars)
            require(32 <= value <= 126, 'name-encoding'); chars.append(value)
        raise MappingError('name-bound')

    def find(self, needle, alignment=1):
        found = []
        for va, _, raw, size, flags in self.sections:
            if flags & 0x20000000 or not flags & 0x40000000: continue
            start, end = raw, raw+size
            while start < end:
                self.check(); off = self.data.find(needle, start, end)
                if off < 0: break
                addr = va+off-raw
                if addr % alignment == 0:
                    found.append(addr); require(len(found) <= MAX_CANDIDATES, 'candidate-cap')
                start = off+1
        return found

    def relocation_targets(self):
        addr, size = self.directories[5]
        if not size: return set()
        require(size <= 4*1024*1024, 'relocation-size')
        off = self.rva(addr, size); end = off+size; result = set(); entries = 0
        while off < end:
            self.check(); require(off+8 <= end, 'relocation-block')
            page, length = self.u(off), self.u(off+4)
            require(page % 4096 == 0 and length >= 8 and length % 2 == 0 and off+length <= end, 'relocation-block')
            for entry in range(off+8, off+length, 2):
                value = self.u(entry, 'H'); entries += 1
                require(entries <= 500000, 'relocation-cap')
                if value >> 12 == 10:
                    target = page+(value & 4095); self.rva(target, 8)
                    require(target not in result, 'duplicate-relocation'); result.add(target)
            off += length
        return result

    def exports(self):
        addr, size = self.directories[0]
        if not size: return []
        require(size >= 40, 'export-directory'); off = self.rva(addr, size)
        nf, nn, fa, na, oa = struct.unpack('<IIIII', self.take(off+20, 20))
        require(nn <= nf <= 100000, 'export-cap')
        if nf: self.rva(fa, nf*4)
        if nn: self.rva(na, nn*4); self.rva(oa, nn*2)
        result = []
        for i in range(nn):
            ordinal = self.word(oa+i*2, 'H'); require(ordinal < nf, 'export-ordinal')
            target = self.word(fa+ordinal*4)
            name = self.name(self.word(na+i*4))
            if name == FIXTURE_EXPORT.encode() and not addr <= target < addr+size: result.append(target)
        return result

    def condition_imports(self):
        addr, size = self.directories[1]
        if not size: return []
        require(20 <= size <= 128*20, 'import-directory-cap'); off = self.rva(addr, size)
        result = []
        for index in range(size//20):
            descriptor = struct.unpack('<IIIII', self.take(off+index*20, 20))
            if not any(descriptor): return result
            original, _, _, dll, first = descriptor
            name = self.name(dll).lower()
            if name != b'sal3.dll': continue
            lookup = original or first
            for i in range(16384):
                value = self.word(lookup+i*8, 'Q'); self.rva(first+i*8, 8)
                if value == 0: break
                if value & (1 << 63): continue
                require(value <= 0xffffffff, 'import-name-rva')
                if self.name(value+2) == b'osl_waitCondition': result.append(first+i*8)
            else: raise MappingError('import-entry-cap')
        raise MappingError('unterminated-import-directory')


def _hierarchy(pe, col, derived, parent):
    """Only exact public, single, nonvirtual inheritance; unsupported shapes decline."""
    if tuple(pe.word(col+i*4) for i in range(3)) != (1, 0, 0) or pe.word(col+20) != col: return False
    if pe.word(col+12) != derived: return False
    hierarchy = pe.word(col+16)
    if (pe.word(hierarchy), pe.word(hierarchy+4), pe.word(hierarchy+8)) != (0, 0, 2): return False
    array = pe.word(hierarchy+12)
    for i, (type_rva, contained) in enumerate(((derived, 1), (parent, 0))):
        bcd = pe.word(array+i*4)
        td, num, mdisp, pdisp, vdisp, attributes, nested = struct.unpack('<IIiiiII', pe.take(pe.rva(bcd, 28), 28))
        if (td, num, mdisp, pdisp, vdisp) != (type_rva, contained, 0, -1, 0) or attributes != 0x40: return False
        if i == 0:
            if nested != hierarchy: return False
        else:
            if (pe.word(nested), pe.word(nested+4), pe.word(nested+8)) != (0, 0, 1): return False
            if pe.word(pe.word(nested+12)) != bcd: return False
    return True


def map_mutex_pe(data, check, *, fixture=False):
    pe = PE(data, check)
    result = {'status': 'inconclusive', 'reason': 'no-unique-rtti-vtable-proof', 'slot': 4, 'fixture': fixture}
    derived = b'.?AVOpenGeulFixtureMutex@@' if fixture else b'.?AVWinSalYieldMutex@@'
    parent = b'.?AVOpenGeulFixtureBase@@' if fixture else b'.?AVSolarMutex@comphelper@@'
    types = []
    for name in (derived, parent):
        matches = pe.find(name+b'\0', 8)
        if len(matches) != 1: return result
        td = matches[0]-16
        pe.rva(td, len(name)+17)
        if pe.word(td+8, 'Q') != 0: return result
        types.append(td)
    # Signature/primary offsets/type RVA narrows candidates before the finite cap.
    prefix = struct.pack('<IIII', 1, 0, 0, types[0])
    cols = [addr for addr in pe.find(prefix, 4) if _hierarchy(pe, addr, *types)]
    if len(cols) != 1: return result
    col = cols[0]; relocations = pe.relocation_targets()
    tables = []
    for reference in pe.find(struct.pack('<Q', pe.base+col), 8):
        if not all(reference+8*i in relocations for i in range(6)): continue
        entries = [pe.word(reference+8+8*i, 'Q')-pe.base for i in range(5)]
        for entry in entries: pe.rva(entry, 4, True)
        if len(set(entries)) != 5: continue # No inferred identity across folded entries.
        tables.append((reference+8, entries[4]))
    if len(tables) != 1: return result
    table, entry = tables[0]
    if entry % 4: return result
    # Reuse the existing independently tested ARM64 unwind validator without modifying it.
    unwind = _sal.map_pe(data, entry+4, check)
    extent = unwind.get('functionRange')
    if not extent or extent['beginRva'] != entry or unwind.get('unwindFragment'):
        result['reason'] = 'unsupported-or-inexact-unwind'; return result
    end = extent['endRvaExclusive']
    require(end-entry <= 65536, 'function-size-cap')
    result.update(typeRva=types[0], completeObjectLocatorRva=col, vftableRva=table, entryRva=entry, functionRange=extent)
    if fixture:
        if pe.exports() != [entry]: result['reason'] = 'fixture-export-slot-mismatch'; return result
        result.update(status='exact', reason='fixture-export-slot-and-unwind', exportName=FIXTURE_EXPORT)
        check(); return result
    imports = pe.condition_imports()
    if len(imports) != 1: result['reason'] = 'no-unique-condition-import'; return result
    calls = []
    for pc in range(entry, end-8, 4):
        check(); a, b, c = (pe.word(pc+i*4) for i in range(3))
        # Only contiguous ADRP Xn; LDR Xt,[Xn,#imm]; BLR Xt. No thunk or CFG guess.
        if a & 0x9f000000 != 0x90000000 or b & 0xffc00000 != 0xf9400000 or c & 0xfffffc1f != 0xd63f0000: continue
        # Register 31 is XZR for ADRP/LDR destination but SP as LDR base; never dataflow.
        if a & 31 == 31 or b & 31 == 31: continue
        if a & 31 != (b >> 5) & 31 or b & 31 != (c >> 5) & 31: continue
        imm = ((a >> 5) & 0x7ffff) << 2 | ((a >> 29) & 3)
        if imm & (1 << 20): imm -= 1 << 21
        target = (pc & ~4095) + imm*4096 + ((b >> 10) & 4095)*8
        if target == imports[0]: calls.append(pc+8)
    if len(calls) != 1: result['reason'] = 'unsupported-or-ambiguous-condition-call'; return result
    result.update(status='exact', reason='fixture-grounded-rtti-slot-unwind-import-call',
                  functionName='WinSalYieldMutex::doAcquire', conditionWaitIatRva=imports[0], conditionWaitCallRva=calls[0], conditionWaitReturnRva=calls[0]+4, runtimeExecutionProved=False)
    check(); return result


def _held_bytes(path, cap, check, *, expected_size=None):
    path = Path(path); check(); require(not path.is_symlink(), 'input-symlink')
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= cap and (expected_size is None or before.st_size == expected_size), 'input-size-or-type')
        chunks = []; total = 0
        while True:
            check(); chunk = stream.read(min(1024*1024, cap+1-total)); check()
            if not chunk: break
            total += len(chunk); require(total <= cap, 'read-size-bound'); chunks.append(chunk)
        after = os.fstat(stream.fileno())
        require(tuple(getattr(before, k) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')) ==
                tuple(getattr(after, k) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')), 'held-input-changed')
        require(total == before.st_size, 'input-size-changed')
    check(); return b''.join(chunks)


def analyze(archive, lock, fixture, *, clock=time.monotonic):
    identity = {}
    try:
        return _analyze(archive, lock, fixture, clock=clock, identity=identity)
    except Exception as exc:
        exc.mutex_identity = identity
        raise


def _analyze(archive, lock, fixture, *, clock, identity):
    deadline = clock()+30
    def check(): require(clock() < deadline, 'analysis-deadline')
    fixture_data = _held_bytes(fixture, MAX_MEMBER, check)
    identity['fixtureSha256'] = hashlib.sha256(fixture_data).hexdigest(); check()
    proof = map_mutex_pe(fixture_data, check, fixture=True)
    require(proof['status'] == 'exact', 'fixture-proof-required')
    runtime = lock['runtime']
    require(runtime.get('sourceCoreCommit') == SOURCE_CORE_COMMIT, 'unsupported-source-layout')
    identity['sourceCoreCommit'] = SOURCE_CORE_COMMIT
    size = runtime['size']; expected = runtime['sha256']
    require(lock.get('architecture') == 'arm64' and type(size) is int and 0 < size <= MAX_ARCHIVE and isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected), 'lock-contract')
    blob = _held_bytes(archive, MAX_ARCHIVE, check, expected_size=size)
    digest = hashlib.sha256(blob).hexdigest(); check(); require(digest == expected, 'archive-sha256')
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        check(); entries = z.infolist(); require(len(entries) <= 100000, 'zip-entry-count')
        candidates = [v for v in entries if v.filename.replace('\\','/').rstrip('/').split('/')[-1].rstrip(' .').casefold() == 'vclplug_winlo.dll']
        require(len(candidates) == 1 and candidates[0].filename == 'program/vclplug_winlo.dll', 'exact-member-required')
        member = candidates[0]; mode = member.external_attr >> 16
        require(not member.is_dir() and not member.external_attr & 0x10 and stat.S_IFMT(mode) in (0, stat.S_IFREG) and not member.flag_bits & 1 and 0 < member.file_size <= MAX_MEMBER, 'member-type-or-size')
        with z.open(member) as stream:
            chunks = []; total = 0
            while True:
                check(); chunk = stream.read(min(1024*1024, MAX_MEMBER+1-total)); check()
                if not chunk: break
                total += len(chunk); require(total <= MAX_MEMBER, 'member-size-bound'); chunks.append(chunk)
            data = b''.join(chunks)
        require(len(data) == member.file_size, 'member-size-mismatch')
    result = map_mutex_pe(data, check)
    sha = os.environ.get('GITHUB_SHA', '')
    result.update(schemaVersion=1, kind='static-mutex-function-mapping', acceptance=False, physicalInputReproduced=False,
                  sourceCommit=sha if re.fullmatch('[0-9a-f]{40}', sha) else None,
                  sourceCoreCommit=SOURCE_CORE_COMMIT, slotProofPolicy='pinned-single-base-microsoft-arm64-v1',
                  archiveSha256=digest, archiveSize=size, member='program/vclplug_winlo.dll', memberSha256=hashlib.sha256(data).hexdigest(),
                  memberSize=len(data), fixtureSha256=hashlib.sha256(fixture_data).hexdigest(), fixture=proof, analysisBudgetSeconds=30)
    check(); require(len(json.dumps(result)) <= 8192, 'receipt-size'); return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'lock', 'fixture', 'output'): p.add_argument('--'+name, required=True, type=Path)
    args = p.parse_args(argv)
    try:
        require(args.lock.stat().st_size <= 65536, 'lock-size')
        result = analyze(args.archive, json.loads(args.lock.read_text(encoding='utf-8')), args.fixture); code = 0
    except Exception as exc:
        result = {'schemaVersion':1, 'kind':'static-mutex-function-mapping', 'acceptance':False, 'physicalInputReproduced':False,
                  'status':'rejected', 'failureClass':type(exc).__name__, 'reason':str(exc) if isinstance(exc, MappingError) else 'input-or-parser-failure'}
        sha = os.environ.get('GITHUB_SHA', '')
        result['sourceCommit'] = sha if re.fullmatch('[0-9a-f]{40}', sha) else None
        result.update(getattr(exc, 'mutex_identity', {}))
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2)+'\n', encoding='utf-8')
    return code


if __name__ == '__main__': raise SystemExit(main())
