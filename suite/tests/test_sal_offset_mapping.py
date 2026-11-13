import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest import mock
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/map-sal-offset.py'


def fixture(flag=1, export_start=0x1000):
    b = bytearray(0xa00)
    def put(off, fmt, *v): struct.pack_into('<' + fmt, b, off, *v)
    b[:2] = b'MZ'; put(0x3c, 'I', 0x80); b[0x80:0x84] = b'PE\0\0'
    put(0x84, 'HHIIIHH', 0xaa64, 1, 0, 0, 0, 240, 0x2022)
    put(0x98, 'H', 0x20b); put(0x98+56, 'II', 0x2000, 0x200)
    put(0x98+108, 'I', 16)
    put(0x98+112, 'II', 0x1200, 0x80)
    put(0x98+112+24, 'II', 0x1300, 8)
    b[0x188:0x190] = b'.text\0\0\0'
    put(0x190, 'IIII', 0x800, 0x1000, 0x800, 0x200)
    put(0x188+36, 'I', 0x60000020)
    put(0x400+20, 'IIIII', 1, 1, 0x1240, 0x1244, 0x1248)
    put(0x440, 'I', export_start); put(0x444, 'I', 0x1260); put(0x448, 'H', 0)
    b[0x460:0x472-1] = b'osl_waitCondition\0'
    put(0x500, 'II', 0x1000, (32 << 2) | flag if flag else 0x1400)
    put(0x600, 'I', 32 | (1 << 27)) # one code word
    put(0x204, 'I', 0x94000000) # BL at returnRva-4
    return bytes(b)


class SalMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SCRIPT.exists(): return
        spec = importlib.util.spec_from_file_location('sal_map', SCRIPT)
        cls.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.m)

    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'bounded SAL mapper not implemented')

    def parse(self, b=None): return self.m.map_pe(b or fixture(), 0x1008, lambda: None)

    def test_exact_packed_and_unpacked_range(self):
        for flag in (0, 1):
            r = self.parse(fixture(flag))
            self.assertEqual(r['status'], 'exact')
            self.assertEqual(r['exportName'], 'osl_waitCondition')
            self.assertEqual(r['functionRange'], {'beginRva': 4096, 'endRvaExclusive': 4224})

    def test_nearby_export_fragment_forwarder_and_boundary_inconclusive(self):
        for b in (fixture(export_start=0xffc), fixture(2), fixture(export_start=0x1260)):
            self.assertEqual(self.parse(b)['status'], 'inconclusive')
        self.assertEqual(self.m.map_pe(fixture(), 0x1000, lambda: None)['status'], 'inconclusive')

    def test_bad_machine_truncated_mapping_reserved_unwind_and_excessive_exports(self):
        for offset, fmt, value in ((0x84, 'H', 0x8664), (0x194, 'I', 0xfffffff0),
                                   (0x414, 'I', 1000001)):
            b = bytearray(fixture()); struct.pack_into('<'+fmt, b, offset, value)
            with self.assertRaises(self.m.MappingError): self.parse(bytes(b))
        with self.assertRaises(self.m.MappingError): self.parse(fixture()[:0x550])

    def test_parent_link_unknown_is_inconclusive(self):
        b=bytearray(fixture()); struct.pack_into('<I',b,0x504,0x1303)
        self.assertEqual(self.parse(bytes(b))['status'],'inconclusive')

    def test_ambiguous_exact_export_is_inconclusive(self):
        b=bytearray(fixture())
        struct.pack_into('<IIIII',b,0x414,2,2,0x1280,0x1290,0x1298)
        struct.pack_into('<II',b,0x480,0x1000,0x1000)
        struct.pack_into('<II',b,0x490,0x1260,0x12b0)
        struct.pack_into('<HH',b,0x498,0,1)
        b[0x4b0:0x4b6]=b'alias\0'
        self.assertEqual(self.parse(bytes(b))['status'],'inconclusive')

    def test_overlap_and_cross_section_mapping_rejected(self):
        b=bytearray(fixture()); struct.pack_into('<I',b,0x98+140,16)
        struct.pack_into('<II',b,0x508,0x1004,129)
        with self.assertRaises(self.m.MappingError): self.parse(bytes(b))
        b=bytearray(fixture()); struct.pack_into('<I',b,0x98+116,0x700)
        with self.assertRaises(self.m.MappingError): self.parse(bytes(b))

    def test_not_call_and_phantom_unwind_inconclusive(self):
        b=bytearray(fixture()); struct.pack_into('<I',b,0x204,0xd503201f)
        self.assertEqual(self.parse(bytes(b))['status'],'inconclusive')
        b=bytearray(fixture(0)); b[0x604]=0xe5
        self.assertEqual(self.parse(bytes(b))['status'],'inconclusive')

    def test_nonleading_chain_marker_is_inconclusive(self):
        b=bytearray(fixture(0))
        # Structurally bounded code bytes: save_regp operand; end_c; end.
        b[0x604:0x608]=bytes((0xc8, 0x02, 0xe5, 0xe4))
        result=self.parse(bytes(b))
        self.assertEqual(result['status'],'inconclusive')
        self.assertTrue(result['unwindFragment'])
        self.assertNotIn('exportName',result)

    def test_dos_directory_bit_without_trailing_slash_rejected(self):
        member=zipfile.ZipInfo('program/sal3.dll')
        member.create_system=0
        member.external_attr=0x10
        with self.assertRaisesRegex(self.m.MappingError,'member-type-or-size'):
            self.analyze([(member,fixture())])

    def test_export_path_not_emitted(self):
        b=bytearray(fixture()); b[0x460:0x471]=b'/private/location'
        with self.assertRaises(self.m.MappingError): self.parse(bytes(b))

    def test_cli_failure_receipt_never_contains_input_path(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'receipt.json'
            code=self.m.main(['--archive',d+'/secret-input','--lock',d+'/secret-lock','--output',str(out)])
            self.assertEqual(code,1)
            receipt=json.loads(out.read_text())
            self.assertEqual(receipt['status'],'rejected')
            self.assertNotIn(d,out.read_text())

    def analyze(self, entries=None, bad_hash=False, clock=lambda: 0):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'engine.zip'
            with zipfile.ZipFile(p, 'w') as z:
                for n, b in entries or [('program/sal3.dll', fixture())]: z.writestr(n, b)
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            lock = {'architecture':'arm64', 'runtime':{'size':p.stat().st_size,
                'sha256': '0'*64 if bad_hash else digest, 'sourceCoreCommit':'a'*40}}
            return self.m.analyze(p, lock, clock=clock, return_rva=0x1008)

    def test_authenticated_archive_only_and_hashes(self):
        r = self.analyze()
        self.assertEqual(r['status'], 'exact')
        self.assertEqual(r['memberSha256'], hashlib.sha256(fixture()).hexdigest())
        self.assertNotIn('archivePath', r)

    def test_bad_hash_alias_duplicate_link_and_oversize_rejected(self):
        with self.assertRaises(self.m.MappingError): self.analyze(bad_hash=True)
        symlink = zipfile.ZipInfo('program/sal3.dll'); symlink.create_system=3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        for entries in ([('x/program/sal3.dll', fixture())], [('program/./sal3.dll', fixture())],
                        [('program/sal3.dll',fixture()), ('PROGRAM/SAL3.DLL',fixture())],
                        [('program/sal3.dll',fixture()), ('program/sal3.dll.',fixture())],
                        [(symlink, fixture())]):
            with self.assertRaises(self.m.MappingError): self.analyze(entries)

    def test_oversized_member_rejected_before_open(self):
        original=zipfile.ZipFile.infolist
        def oversized(z):
            items=original(z); items[0].file_size=self.m.MAX_MEMBER+1; return items
        real_open=zipfile.ZipFile.open
        def no_read(z,name,mode='r',*args,**kwargs):
            if mode=='r': raise AssertionError('must not decompress')
            return real_open(z,name,mode,*args,**kwargs)
        with mock.patch.object(zipfile.ZipFile,'infolist',oversized):
            with mock.patch.object(zipfile.ZipFile,'open',no_read):
                with self.assertRaisesRegex(self.m.MappingError,'member-type-or-size'): self.analyze()

    def test_changed_held_archive_rejected(self):
        original=self.m.os.fstat; calls=[]
        def changed(fd):
            v=original(fd); calls.append(1)
            if len(calls)==1: return v
            class Snapshot: pass
            result=Snapshot()
            for key in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns'):
                setattr(result,key,getattr(v,key))
            result.st_mtime_ns+=1
            return result
        with mock.patch.object(self.m.os,'fstat',changed):
            with self.assertRaisesRegex(self.m.MappingError,'archive-changed'): self.analyze()

    def test_pe_deadline_not_renewed_during_tables(self):
        calls=[]
        def check():
            calls.append(1)
            if len(calls)>30: raise self.m.MappingError('analysis-deadline')
        with self.assertRaisesRegex(self.m.MappingError,'analysis-deadline'):
            self.m.map_pe(fixture(),0x1008,check)

    def test_expired_deadline_rejected(self):
        times = iter([0, 31])
        with self.assertRaises(self.m.MappingError): self.analyze(clock=lambda: next(times,31))


if __name__ == '__main__': unittest.main()
