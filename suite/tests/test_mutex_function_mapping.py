"""Synthetic ARM64 PE metadata; no binary loading or Windows dependency."""
import hashlib
import importlib.util
import json
import os
import stat
from unittest import mock
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/map-mutex-function.py'


def image(fixture=False):
    b = bytearray(0x2400)
    def put(rva, fmt, *values):
        off = rva if rva < 0x400 else rva - 0xc00
        struct.pack_into('<'+fmt, b, off, *values)
    def string(rva, value):
        off = rva-0xc00; encoded=value.encode()+b'\0'; b[off:off+len(encoded)]=encoded
    base = 0x180000000
    b[:2]=b'MZ'; put(0x3c,'I',0x80); b[0x80:0x84]=b'PE\0\0'
    put(0x84,'HHIIIHH',0xaa64,2,0,0,0,240,0x2022)
    put(0x98,'H',0x20b); put(0x98+24,'Q',base); put(0x98+56,'II',0x4000,0x400); put(0x98+108,'I',16)
    for off,va,size,raw,flags in ((0x188,0x1000,0x1000,0x400,0x60000020),(0x1b0,0x2000,0x1000,0x1400,0x40000040)):
        put(off+8,'IIII',size,va,size,raw); put(off+36,'I',flags)
    put(0x98+136,'II',0x2700,8); put(0x2700,'II',0x1000,(16<<2)|1)
    # Contiguous ADRP x8, LDR x8,[x8,#0x400], BLR x8 -> IAT 0x2400.
    put(0x1000,'III',0xb0000008,0xf9420108,0xd63f0100)
    derived='.?AVOpenGeulFixtureMutex@@' if fixture else '.?AVWinSalYieldMutex@@'
    parent='.?AVOpenGeulFixtureBase@@' if fixture else '.?AVSolarMutex@comphelper@@'
    put(0x2000,'QQ',base+0x2a00,0); string(0x2010,derived)
    put(0x2080,'QQ',base+0x2a00,0); string(0x2090,parent)
    # COL, self/base hierarchy and descriptors (public nonvirtual base at offset0).
    put(0x2100,'IIIIII',1,0,0,0x2000,0x2140,0x2100)
    put(0x2140,'IIII',0,0,2,0x2160); put(0x2160,'II',0x2180,0x21c0)
    put(0x2180,'IIiiiII',0x2000,1,0,-1,0,0x40,0x2140)
    put(0x21c0,'IIiiiII',0x2080,0,0,-1,0,0x40,0x2200)
    put(0x2200,'IIII',0,0,1,0x2220); put(0x2220,'I',0x21c0)
    put(0x2240,'Q',base+0x2100)
    for i in range(5):put(0x2248+8*i,'Q',base+(0x1100+4*i if i<4 else 0x1000))
    # Relocations authenticate absolute COL/vtable pointers as image addresses.
    put(0x98+152,'II',0x2800,20); put(0x2800,'II6H',0x2000,20,*[0xa240+8*i for i in range(6)])
    # Normal imports.
    put(0x98+120,'II',0x2300,40); put(0x2300,'IIIII',0x2380,0,0,0x2360,0x2400)
    string(0x2360,'sal3.dll'); put(0x2380,'QQ',0x2420,0); put(0x2400,'QQ',0x2420,0); put(0x2420,'H',0); string(0x2422,'osl_waitCondition')
    if fixture:
        put(0x98+112,'II',0x2500,0x100); put(0x2514,'IIIII',1,1,0x2540,0x2550,0x2560)
        put(0x2540,'I',0x1000);put(0x2550,'I',0x2580);put(0x2560,'H',0)
        string(0x2580,'?doAcquire@OpenGeulFixtureMutex@@MEAAXI@Z')
    return bytes(b)


def change(data,rva,fmt,value):
    b=bytearray(data);struct.pack_into('<'+fmt,b,rva if rva<0x400 else rva-0xc00,value);return bytes(b)


class MutexMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SCRIPT.exists():
            spec=importlib.util.spec_from_file_location('mutex_mapper',SCRIPT)
            cls.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.m)
    def setUp(self):self.assertTrue(SCRIPT.exists(),'bounded mutex mapper absent')
    def test_fixture_exact_export_slot_then_production_import_call(self):
        a=self.m.map_mutex_pe(image(True),lambda:None,fixture=True)
        self.assertEqual(a['status'],'exact');self.assertEqual(a['slot'],4)
        r=self.m.map_mutex_pe(image(),lambda:None)
        self.assertEqual(r['status'],'exact');self.assertEqual(r['entryRva'],0x1000)
        self.assertEqual(r['conditionWaitCallRva'],0x1008)
    def test_wrong_type_base_self_slot_and_missing_relocation_inconclusive(self):
        for b,fixture_mode in ((change(image(),0x2010,'B',88),False),(change(image(),0x2090,'B',88),False),(change(image(),0x2114,'I',0x2104),False),
                  (change(image(True),0x2268,'Q',0x180001100),True),(change(image(),0x98+156,'I',0),False)):
            self.assertEqual(self.m.map_mutex_pe(b,lambda:None,fixture=fixture_mode)['status'],'inconclusive')
    def test_unsupported_call_fragment_and_duplicate_vtable_inconclusive(self):
        b=bytearray(image());struct.pack_into('<Q',b,0x2290-0xc00,0x180002100)
        # A second fully formed relocated table is an ambiguity, not an arbitrary first-match choice.
        b[0x2298-0xc00:0x22c0-0xc00]=b[0x2248-0xc00:0x2270-0xc00]
        struct.pack_into('<II12H',b,0x2800-0xc00,0x2000,32,*[0xa240+8*i for i in range(6)],*[0xa290+8*i for i in range(6)])
        struct.pack_into('<I',b,0x98+156,32)
        for data in (change(image(),0x1008,'I',0xd503201f),change(image(),0x2704,'I',(16<<2)|2),bytes(b)):
            self.assertEqual(self.m.map_mutex_pe(data,lambda:None)['status'],'inconclusive')
    def test_bad_architecture_overlap_bounds_and_deadline_rejected(self):
        for b in (change(image(),0x84,'H',0x8664),change(image(),0x1b0+12,'I',0x1000),image()[:0x2100]):
            with self.assertRaises(self.m.MappingError):self.m.map_mutex_pe(b,lambda:None)
        def expired():raise self.m.MappingError('analysis-deadline')
        with self.assertRaisesRegex(self.m.MappingError,'analysis-deadline'):self.m.map_mutex_pe(image(),expired)
    def test_fixture_mismatch_stops_before_archive_open_and_sanitized_cli(self):
        with tempfile.TemporaryDirectory() as d:
            fp=Path(d)/'fixture.dll';fp.write_bytes(change(image(True),0x2268,'Q',0x180001100))
            with self.assertRaisesRegex(self.m.MappingError,'fixture-proof'):
                self.m.analyze(Path(d)/'unopened.zip',{'architecture':'arm64'},fp)
            out=Path(d)/'receipt.json'
            self.assertEqual(self.m.main(['--archive',str(Path(d)/'private.zip'),'--lock',str(Path(d)/'private.lock'),'--fixture',str(fp),'--output',str(out)]),1)
            self.assertNotIn(d,out.read_text())
    def test_authenticated_held_archive_exact_member_and_shared_budget(self):
        with tempfile.TemporaryDirectory() as d:
            fp=Path(d)/'fixture.dll';fp.write_bytes(image(True));zp=Path(d)/'engine.zip'
            with zipfile.ZipFile(zp,'w') as z:z.writestr('program/vclplug_winlo.dll',image())
            lock={'architecture':'arm64','runtime':{'sourceCoreCommit':self.m.SOURCE_CORE_COMMIT,'size':zp.stat().st_size,'sha256':hashlib.sha256(zp.read_bytes()).hexdigest()}}
            with mock.patch.dict(os.environ,{},clear=True):r=self.m.analyze(zp,lock,fp)
            self.assertEqual(r['status'],'exact');self.assertEqual(r['fixture']['status'],'exact')
            self.assertIsNone(r['sourceCommit']);self.assertFalse(r['acceptance']);self.assertFalse(r['physicalInputReproduced'])
            self.assertEqual(r['fixtureSha256'],hashlib.sha256(image(True)).hexdigest())
            lock['runtime']['sha256']='0'*64
            with self.assertRaisesRegex(self.m.MappingError,'archive-sha256'):self.m.analyze(zp,lock,fp)
            ticks=iter([0,0,31])
            with self.assertRaisesRegex(self.m.MappingError,'analysis-deadline'):self.m.analyze(zp,lock,fp,clock=lambda:next(ticks))

    def test_wrong_hierarchy_virtual_base_alias_and_truncated_references(self):
        for data in (change(image(),0x2144,'I',1),change(image(),0x2148,'I',3),change(image(),0x21cc,'i',0),change(image(),0x21d4,'I',0x41)):
            self.assertEqual(self.m.map_mutex_pe(data,lambda:None)['status'],'inconclusive')
        with self.assertRaises(self.m.MappingError):self.m.map_mutex_pe(change(image(),0x2150-4,'I',0xfffffff0),lambda:None)
    def test_duplicate_type_or_col_never_selects_first_match(self):
        b=bytearray(image());name=b'.?AVWinSalYieldMutex@@\0';b[0x2910-0xc00:0x2910-0xc00+len(name)]=name
        self.assertEqual(self.m.map_mutex_pe(bytes(b),lambda:None)['status'],'inconclusive')
        b=bytearray(image());b[0x2900-0xc00:0x2918-0xc00]=b[0x2100-0xc00:0x2118-0xc00];struct.pack_into('<I',b,0x2914-0xc00,0x2900)
        self.assertEqual(self.m.map_mutex_pe(bytes(b),lambda:None)['status'],'inconclusive')
    def test_import_register_mismatch_wrong_dll_and_duplicate_calls_decline(self):
        wrong=bytearray(image());wrong[0x2360-0xc00:0x2368-0xc00]=b'otherdll'
        duplicate=bytearray(image());duplicate[0x1010-0xc00:0x101c-0xc00]=duplicate[0x1000-0xc00:0x100c-0xc00]
        for data in (change(image(),0x1008,'I',0xd63f0120),bytes(wrong),bytes(duplicate),change(image(),0x1000,'I',0x94000000)):
            self.assertEqual(self.m.map_mutex_pe(data,lambda:None)['status'],'inconclusive')
    def test_deadline_is_checked_inside_metadata_iteration(self):
        calls=[]
        def check():
            calls.append(1)
            if len(calls)>60:raise self.m.MappingError('analysis-deadline')
        with self.assertRaisesRegex(self.m.MappingError,'analysis-deadline'):self.m.map_mutex_pe(image(),check)
    def test_archive_alias_link_directory_duplicate_and_changed_held_file_rejected(self):
        link=zipfile.ZipInfo('program/vclplug_winlo.dll');link.external_attr=(stat.S_IFLNK|0o777)<<16
        directory=zipfile.ZipInfo('program/vclplug_winlo.dll');directory.create_system=0;directory.external_attr=0x10
        for entries, reason in (([('PROGRAM/VCLPLUG_WINLO.DLL',image())],'exact-member-required'), ([(link,image())],'member-type-or-size'), ([(directory,image())],'member-type-or-size'),
                        ([('program/vclplug_winlo.dll',image()),('program/vclplug_winlo.dll.',image())],'exact-member-required')):
            with tempfile.TemporaryDirectory() as d:
                fp=Path(d)/'fixture.dll';fp.write_bytes(image(True));zp=Path(d)/'engine.zip'
                with zipfile.ZipFile(zp,'w') as z:
                    for name,data in entries:z.writestr(name,data)
                lock={'architecture':'arm64','runtime':{'sourceCoreCommit':self.m.SOURCE_CORE_COMMIT,'size':zp.stat().st_size,'sha256':hashlib.sha256(zp.read_bytes()).hexdigest()}}
                with self.assertRaisesRegex(self.m.MappingError,reason):self.m.analyze(zp,lock,fp)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'held';p.write_bytes(b'held data');original=self.m.os.fstat;calls=[]
            def changed(fd):
                value=original(fd);calls.append(1)
                if len(calls)==1:return value
                class Snapshot:pass
                out=Snapshot()
                for key in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns'):setattr(out,key,getattr(value,key))
                out.st_mtime_ns+=1;return out
            with mock.patch.object(self.m.os,'fstat',changed):
                with self.assertRaisesRegex(self.m.MappingError,'held-input-changed'):self.m._held_bytes(p,100,lambda:None)

    def test_secondary_offsets_wrong_iat_duplicate_imports_and_exports_decline(self):
        duplicates=bytearray(image());duplicates[0x2314-0xc00:0x2328-0xc00]=duplicates[0x2300-0xc00:0x2314-0xc00]
        struct.pack_into('<I',duplicates,0x98+124,60)
        exports=bytearray(image(True));struct.pack_into('<IIIII',exports,0x2514-0xc00,2,2,0x2540,0x2550,0x2560)
        struct.pack_into('<II',exports,0x2540-0xc00,0x1000,0x1000);struct.pack_into('<II',exports,0x2550-0xc00,0x2580,0x2580);struct.pack_into('<HH',exports,0x2560-0xc00,0,1)
        for data,mode in ((change(image(),0x2104,'I',8),False),(change(image(),0x2108,'I',4),False),
                          (change(image(),0x1004,'I',0xf9420508),False),(bytes(duplicates),False),(bytes(exports),True)):
            self.assertEqual(self.m.map_mutex_pe(data,lambda:None,fixture=mode)['status'],'inconclusive')
    def test_unpacked_unwind_and_chain_scope(self):
        data=bytearray(image());struct.pack_into('<I',data,0x2704-0xc00,0x2740)
        struct.pack_into('<I',data,0x2740-0xc00,16|(1<<27));data[0x2744-0xc00:0x2748-0xc00]=bytes((0xe4,0xe3,0xe3,0xe3))
        self.assertEqual(self.m.map_mutex_pe(bytes(data),lambda:None)['status'],'exact')
        data[0x2745-0xc00]=0xe5
        self.assertEqual(self.m.map_mutex_pe(bytes(data),lambda:None)['status'],'inconclusive')
    def test_archive_symlink_and_member_cap_before_decompression(self):
        with tempfile.TemporaryDirectory() as d:
            fp=Path(d)/'fixture.dll';fp.write_bytes(image(True));zp=Path(d)/'engine.zip'
            with zipfile.ZipFile(zp,'w') as z:z.writestr('program/vclplug_winlo.dll',image())
            lock={'architecture':'arm64','runtime':{'sourceCoreCommit':self.m.SOURCE_CORE_COMMIT,'size':zp.stat().st_size,'sha256':hashlib.sha256(zp.read_bytes()).hexdigest()}}
            link=Path(d)/'alias.zip'
            try:link.symlink_to(zp)
            except OSError:pass # Windows runners may not permit symlink creation; cap path still executes.
            else:
                with self.assertRaisesRegex(self.m.MappingError,'symlink'):self.m.analyze(link,lock,fp)
            original=zipfile.ZipFile.infolist
            def oversized(z):
                rows=original(z);rows[0].file_size=self.m.MAX_MEMBER+1;return rows
            with mock.patch.object(zipfile.ZipFile,'infolist',oversized),mock.patch.object(zipfile.ZipFile,'open',side_effect=AssertionError('must not decompress')):
                with self.assertRaisesRegex(self.m.MappingError,'member-type-or-size'):self.m.analyze(zp,lock,fp)
    def test_rejected_receipt_retains_only_validated_source_and_known_fixture_hash(self):
        with tempfile.TemporaryDirectory() as d:
            fp=Path(d)/'fixture.dll';fp.write_bytes(image(True));lp=Path(d)/'lock.json';out=Path(d)/'receipt.json'
            lp.write_text(json.dumps({'architecture':'arm64','runtime':{'sourceCoreCommit':self.m.SOURCE_CORE_COMMIT,'size':1,'sha256':'0'*64}}))
            with mock.patch.dict(os.environ,{'GITHUB_SHA':'a'*40}):
                self.assertEqual(self.m.main(['--archive',d+'/missing','--lock',str(lp),'--fixture',str(fp),'--output',str(out)]),1)
            r=json.loads(out.read_text());self.assertEqual(r['sourceCommit'],'a'*40)
            self.assertEqual(r['fixtureSha256'],hashlib.sha256(image(True)).hexdigest());self.assertNotIn(d,out.read_text())

    def test_changed_or_missing_source_pin_cannot_apply_old_virtual_layout(self):
        with tempfile.TemporaryDirectory() as d:
            fp=Path(d)/'fixture.dll';fp.write_bytes(image(True))
            for core in (None,'a'*40):
                lock={'architecture':'arm64','runtime':{'sourceCoreCommit':core,'size':1,'sha256':'0'*64}}
                with self.assertRaisesRegex(self.m.MappingError,'unsupported-source-layout'):
                    self.m.analyze(Path(d)/'must-not-open.zip',lock,fp)

    def test_register31_is_not_general_register_import_dataflow(self):
        for a,b,c in ((0xb000001f,0xf94203e8,0xd63f0100),(0xb0000008,0xf942011f,0xd63f03e0)):
            data=bytearray(image());struct.pack_into('<III',data,0x1000-0xc00,a,b,c)
            self.assertEqual(self.m.map_mutex_pe(bytes(data),lambda:None)['status'],'inconclusive')
    def test_every_absolute_vtable_pointer_requires_dir64_relocation(self):
        for i in range(1,5):
            data=change(image(),0x2808+2*i,'H',0)
            self.assertEqual(self.m.map_mutex_pe(data,lambda:None)['status'],'inconclusive')
