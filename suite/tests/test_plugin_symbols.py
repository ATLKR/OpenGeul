"""Synthetic ARM64 RSDS + MSF7 identity, without native tools or execution."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/retain-plugin-symbols.py'
GUID=uuid.UUID('00112233-4455-6677-8899-aabbccddeeff')
MAGIC=b'Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0'

def dll(guid=GUID,age=2):
    b=bytearray(0x600);b[:2]=b'MZ';struct.pack_into('<I',b,60,0x80);b[0x80:0x84]=b'PE\0\0'
    struct.pack_into('<HHIIIHH',b,0x84,0xaa64,1,0,0,0,240,0x2022)
    opt=0x98;struct.pack_into('<H',b,opt,0x20b)
    struct.pack_into('<II',b,opt+56,0x2000,0x200);struct.pack_into('<I',b,opt+108,16)
    struct.pack_into('<II',b,opt+112+6*8,0x1000,28)
    struct.pack_into('<IIII',b,0x188+8,0x400,0x1000,0x400,0x200)
    cv=b'RSDS'+guid.bytes_le+struct.pack('<I',age)+b'C:\\private\\vclplug_winlo.pdb\0'
    struct.pack_into('<IIHHIIII',b,0x200,0,0,0,0,2,len(cv),0x1040,0x240)
    b[0x240:0x240+len(cv)]=cv
    return bytes(b)

def pdb(guid=GUID,age=2):
    size=512;b=bytearray(6*size);b[:32]=MAGIC
    struct.pack_into('<6I',b,32,size,1,6,16,0,3)
    struct.pack_into('<I',b,3*size,4)
    struct.pack_into('<4I',b,4*size,2,0,28,5)
    struct.pack_into('<III',b,5*size,20000404,0,age);b[5*size+12:5*size+28]=guid.bytes_le
    return bytes(b)

def changed(data,offset,fmt,value):
    b=bytearray(data);struct.pack_into('<'+fmt,b,offset,value);return bytes(b)

class PluginSymbolsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(),'symbol retention helper absent')
        spec=importlib.util.spec_from_file_location('retain_plugin_symbols_test',SCRIPT)
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve()
        self.source=self.root/'source';self.source.mkdir();self.output=self.root/'pair'
        self.dp=self.source/'instdir/program/vclplug_winlo.dll';self.dp.parent.mkdir(parents=True);self.dp.write_bytes(dll())
        self.pp=self.source/'workdir/LinkTarget/Library/vclplug_winlo.pdb';self.pp.parent.mkdir(parents=True);self.pp.write_bytes(pdb())
        self.config=self.source/'config_host.mk';self.config.write_text('export ENABLE_SYMBOLS_FOR=Library_vclplug_win\n')
    def retain(self):return self.m.retain(self.source,self.output,'a'*40,self.config)
    def test_verified_pair_hashes_fixed_names_and_no_path_leak(self):
        r=self.retain()
        self.assertTrue(r['identityMatched']);self.assertFalse(r['symbolContentsValidated']);self.assertFalse(r['acceptance'])
        self.assertEqual(r['matchedIdentity'],{'guid':str(GUID),'age':2})
        self.assertEqual(set(p.name for p in self.output.iterdir()),{'vclplug_winlo.dll','vclplug_winlo.pdb','receipt.json'})
        self.assertEqual(r,json.loads((self.output/'receipt.json').read_text()))
        self.assertEqual(r['files']['dll']['sha256'],hashlib.sha256(dll()).hexdigest())
        self.assertEqual(r['configSha256'],hashlib.sha256(self.config.read_bytes()).hexdigest())
        self.assertNotIn(str(self.root),json.dumps(r));self.assertNotIn('private',json.dumps(r))
    def test_guid_age_mismatch_never_writes_output(self):
        for data in (pdb(age=3),pdb(uuid.UUID(int=1))):
            self.pp.write_bytes(data)
            with self.assertRaises(self.m.SymbolError):self.retain()
            self.assertFalse(self.output.exists())
    def test_invalid_pe_headers_raw_pointer_and_duplicate_codeview(self):
        cases=[changed(dll(),0x84,'H',0x8664),changed(dll(),0x98,'H',0x10b),
               changed(dll(),0x200+24,'I',0xffffff00),changed(dll(),0x200+20,'I',0x1044),dll()[:100]]
        dup=bytearray(dll());dup[0x21c:0x238]=dup[0x200:0x21c];struct.pack_into('<I',dup,0x98+112+6*8+4,56);cases.append(bytes(dup))
        for data in cases:
            with self.subTest(data=data[:4]),self.assertRaises(self.m.SymbolError):self.m.pe_identity(data)
    def test_bad_msf_sizes_blocks_directory_and_info_version(self):
        cases=[pdb()[:100],changed(pdb(),32,'I',513),changed(pdb(),40,'I',7),
               changed(pdb(),52,'I',99),changed(pdb(),1536,'I',99),
               changed(pdb(),2048+12,'I',4),changed(pdb(),2048,'I',70000),
               changed(pdb(),2048+8,'I',27),changed(pdb(),2560,'I',123)]
        for data in cases:
            with self.subTest(size=len(data)),self.assertRaises(self.m.SymbolError):self.m.pdb_identity(data)
    def test_config_and_input_caps_and_existing_output(self):
        self.output.mkdir()
        with self.assertRaises(self.m.SymbolError):self.retain()
        self.output.rmdir()
        with patch.object(self.m,'MAX_PDB',100):
            with self.assertRaises(self.m.SymbolError):self.retain()
        self.assertFalse(self.output.exists())
    def test_symlink_file_and_ancestor_are_rejected(self):
        link=self.source/'linked'
        try:link.symlink_to(self.dp)
        except OSError as exc:self.skipTest('Host cannot create a test symlink: '+type(exc).__name__)
        with self.assertRaises(self.m.SymbolError):self.m.read_regular(link,4096)
        linked=self.root/'alias';linked.symlink_to(self.source,target_is_directory=True)
        with self.assertRaises(self.m.SymbolError):self.m.read_regular(linked/'config_host.mk',4096)
    def test_same_api_stability_cross_ctime_and_identity(self):
        original=os.fstat
        def observed(fd):
            v=original(fd);fields={k:getattr(v,k) for k in self.m.STAT_FIELDS};fields['st_ctime_ns']+=1
            return SimpleNamespace(**fields)
        with patch.object(self.m.os,'fstat',side_effect=observed):self.assertEqual(self.m.read_regular(self.dp,4096),dll())
        calls=[]
        def mutated(fd):
            v=observed(fd);calls.append(fd)
            if len(calls)==2:v.st_mtime_ns+=1
            return v
        with patch.object(self.m.os,'fstat',side_effect=mutated):
            with self.assertRaises(self.m.SymbolError):self.m.read_regular(self.dp,4096)
    def test_cli_rejects_without_exposing_paths(self):
        self.dp.write_bytes(b'bad')
        from contextlib import redirect_stdout
        import io
        out=io.StringIO()
        with redirect_stdout(out):code=self.m.main(['--source-root',str(self.source),'--output',str(self.output),'--source-commit','a'*40,'--config',str(self.config)])
        self.assertEqual(code,1);self.assertNotIn(str(self.root),out.getvalue());self.assertFalse(self.output.exists())
    def test_discontiguous_directory_preserves_info_stream_identity(self):
        b=bytearray(8*512);b[:3072]=pdb()
        directory=struct.pack('<I',130)+struct.pack('<130I',0,28,*([0]*128))+struct.pack('<I',5)
        struct.pack_into('<I',b,40,8);struct.pack_into('<I',b,44,len(directory))
        struct.pack_into('<II',b,1536,4,7)
        b[2048:2560]=directory[:512];b[7*512:7*512+len(directory)-512]=directory[512:]
        self.assertEqual(self.m.pdb_identity(bytes(b)),{'guid':str(GUID),'age':2})
        struct.pack_into('<I',b,1536+4,4)
        with self.assertRaises(self.m.SymbolError):self.m.pdb_identity(bytes(b))
    def test_reserved_or_shared_stream_blocks_fail(self):
        for page in (0,1,2,3,4,99):
            with self.subTest(page=page),self.assertRaises(self.m.SymbolError):
                self.m.pdb_identity(changed(pdb(),2048+12,'I',page))
        b=bytearray(pdb());struct.pack_into('<I',b,44,20)
        struct.pack_into('<5I',b,2048,2,28,28,5,5)
        with self.assertRaises(self.m.SymbolError):self.m.pdb_identity(bytes(b))
    def test_zero_identity_unknown_codeview_and_nonfinal_pdb_name_reject(self):
        for raw in (dll(uuid.UUID(int=0)),dll(age=0),changed(dll(),0x240,'I',0),
                    dll().replace(b'vclplug_winlo.pdb',b'vclplug_other.pdb')):
            with self.assertRaises(self.m.SymbolError):self.m.pe_identity(raw)
    def test_cross_api_inode_and_final_path_change_reject(self):
        original=os.fstat
        def wrong(fd):
            v=original(fd);fields={k:getattr(v,k) for k in self.m.STAT_FIELDS};fields['st_ino']+=1
            return SimpleNamespace(**fields)
        with patch.object(self.m.os,'fstat',side_effect=wrong),self.assertRaises(self.m.SymbolError):
            self.m.read_regular(self.dp,4096)
        original_stat=Path.stat;calls=[]
        def changed_path(path,*args,**kwargs):
            v=original_stat(path,*args,**kwargs)
            if path==self.dp and kwargs.get('follow_symlinks') is not False:
                calls.append(1)
                if len(calls)==2:
                    fields={k:getattr(v,k) for k in self.m.STAT_FIELDS};fields['st_mtime_ns']+=1
                    return SimpleNamespace(**fields)
            return v
        with patch.object(Path,'stat',changed_path),self.assertRaises(self.m.SymbolError):
            self.m.read_regular(self.dp,4096)
    def test_copy_failure_removes_owned_output_preserves_sources(self):
        original=Path.open
        def fail(path,*args,**kwargs):
            if path==self.output/'vclplug_winlo.pdb':raise OSError('synthetic write failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',fail),self.assertRaises(OSError):self.retain()
        self.assertFalse(self.output.exists());self.assertEqual(self.dp.read_bytes(),dll());self.assertEqual(self.pp.read_bytes(),pdb())
    def test_existing_output_and_wrong_config_preserved(self):
        self.output.mkdir();sentinel=self.output/'unrelated';sentinel.write_bytes(b'keep')
        with self.assertRaises(self.m.SymbolError):self.retain()
        self.assertEqual(sentinel.read_bytes(),b'keep')
        with self.assertRaises(self.m.SymbolError):
            self.m.retain(self.source,self.root/'other','a'*40,self.root/'wrong-config')
    def test_windows_reparse_attribute_rejected(self):
        original=Path.lstat
        def reparse(path,*args,**kwargs):
            value=original(path,*args,**kwargs)
            if path==self.dp:return SimpleNamespace(st_mode=value.st_mode,st_file_attributes=1024)
            return value
        with patch.object(Path,'lstat',reparse),self.assertRaises(self.m.SymbolError):self.m.read_regular(self.dp,4096)
    def test_zero_source_commit_rejected_before_retention(self):
        with self.assertRaises(self.m.SymbolError):self.m.retain(self.source,self.output,'0'*40,self.config)
        self.assertFalse(self.output.exists())

    def test_linked_parent_rejected_before_any_child_lookup(self):
        original=Path.lstat;calls=[]
        def observed(path,*args,**kwargs):
            calls.append(path)
            if path==self.dp:raise AssertionError('child accessed before linked parent rejection')
            value=original(path,*args,**kwargs)
            if path==self.dp.parent:return SimpleNamespace(st_mode=value.st_mode,st_file_attributes=1024)
            return value
        with patch.object(Path,'lstat',observed):
            with self.assertRaisesRegex(self.m.SymbolError,'linked-path'):
                self.m.read_regular(self.dp,4096)
        self.assertNotIn(self.dp,calls)
