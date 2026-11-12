"""Source-component units only: no Full, qualified runtime or execution proof."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import shutil
import struct
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('spsupp_payload',ROOT/'suite/payload.py')
payload=importlib.util.module_from_spec(spec);spec.loader.exec_module(payload)
EXPORTS=['DllCanUnloadNow','DllGetClassObject','DllInstall','DllRegisterServer','DllUnregisterServer']

def image(*,native=False,exports=EXPORTS,import_name='kernel32.dll',clr=False,forwarder=False):
    b=bytearray(0x1200);b[:2]=b'MZ';struct.pack_into('<I',b,60,0x80)
    b[0x80:0x84]=b'PE\0\0';opt=0x98;size=240 if native else 224
    struct.pack_into('<HHIIIHH',b,0x84,0x8664 if native else 0x14c,1,0,0,0,size,0x22 if native else 0x2102)
    struct.pack_into('<H',b,opt,0x20b if native else 0x10b)
    struct.pack_into('<II',b,opt+32,0x1000,0x200);struct.pack_into('<II',b,opt+56,0x2000,0x200)
    off=112 if native else 96;struct.pack_into('<I',b,opt+off-4,16)
    section=opt+size;b[section:section+5]=b'.text';struct.pack_into('<IIII',b,section+8,0x1000,0x1000,0x1000,0x200)
    struct.pack_into('<I',b,section+36,0x60000020)
    def pos(rva):return rva-0x1000+0x200
    if exports and not native:
        struct.pack_into('<II',b,opt+off,0x1100,0x200)
        struct.pack_into('<IIHHIIIIIII',b,pos(0x1100),0,0,0,0,0x11a0,1,len(exports),len(exports),0x1140,0x1160,0x1180)
        b[pos(0x11a0):pos(0x11a0)+15]=b'spsupp_x86.dll\0'
        cursor=0x11c0
        for n,name in enumerate(exports):
            struct.pack_into('<I',b,pos(0x1140)+n*4,0x1190 if forwarder else 0x1500+n)
            struct.pack_into('<I',b,pos(0x1160)+n*4,cursor);struct.pack_into('<H',b,pos(0x1180)+n*2,n)
            raw=name.encode()+b'\0';b[pos(cursor):pos(cursor)+len(raw)]=raw;cursor+=len(raw)
    if import_name:
        struct.pack_into('<II',b,opt+off+8,0x1400,40)
        struct.pack_into('<IIIII',b,pos(0x1400),0,0,0,0x1480,0)
        raw=import_name.encode()+b'\0';b[pos(0x1480):pos(0x1480)+len(raw)]=raw
    if clr:struct.pack_into('<II',b,opt+off+14*8,0x1600,72)
    return bytes(b)

class SourceCompanionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def setup_component(self):
        self.assertTrue(hasattr(payload,'_source_companion_component'),'source-bound component validator is required')
        self.runtime=self.root/'runtime';(self.runtime/'program').mkdir(parents=True)
        dll=image();helper=image(native=True);(self.runtime/'program/spsupp_x86.dll').write_bytes(dll);(self.runtime/'program/spsupp_helper.exe').write_bytes(helper)
        sha=lambda b:hashlib.sha256(b).hexdigest()
        self.binding=dict(sourceCommit='1'*40,sourceTree='2'*40,sourceRun=123,runAttempt=1,recipeSha256='3'*64)
        component=dict(schemaVersion=1,kind='source-built-x86-sharepoint-companion',architecture='x64',coreCommit='9dea406ab7695df6325b11b0e19fdca8db4b7276',path='program/spsupp_x86.dll',role='x86CompatibilityHelper',machine=332,size=len(dll),sha256=sha(dll),buildBinding=dict(self.binding),sourceIntent='sharepoint-inproc-32bit-com-client',sourceProofs=copy.deepcopy(payload.SOURCE_COMPANION_SOURCE_PINS),configuredX86=True,linkTarget=dict(path='workdir/LinkTarget/Library/spsupp_x86.dll',size=len(dll),sha256=sha(dll)),nativeHelper=dict(path='program/spsupp_helper.exe',machine=34404,role='nativeX64',size=len(helper),sha256=sha(helper)),installedArchive=dict(kind='main',size=1024,sha256='4'*64,stageReceiptSha256='5'*64),exports=list(EXPORTS),imports=dict(normal=['kernel32.dll'],delay=[]),dependencyPolicy='x86-os-only-no-private-shadow-v1',fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
        return component
    def test_exact_component_and_actual_bytes_are_separate_from_full_authority(self):
        p=self.setup_component();admitted=payload._source_companion_component(p,self.binding)
        self.assertEqual(set(admitted),{'program/spsupp_x86.dll'});payload._source_companion_runtime(self.runtime,p)
        with self.assertRaises(ValueError):payload._source_companion_admissions({},p,architecture='x64')
    def test_binding_missing_cross_run_and_untyped_values_reject(self):
        p=self.setup_component()
        for key,value in [('sourceRun',124),('sourceRun',True),('runAttempt',2),('sourceCommit','6'*40),('recipeSha256','7'*64)]:
            q=copy.deepcopy(p);q['buildBinding'][key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):payload._source_companion_component(q,self.binding)
    def test_source_omission_drift_and_extra_fields_reject(self):
        p=self.setup_component()
        for change in ('omit','drift','extra'):
            q=copy.deepcopy(p)
            if change=='omit':q['sourceProofs'].pop()
            elif change=='drift':q['sourceProofs'][0]['sha256']='0'*64
            else:q['sourceProofs'][0]['extra']=False
            with self.subTest(case=change),self.assertRaises(ValueError):payload._source_companion_component(q,self.binding)
    def test_wrong_path_arch_role_and_qualification_cannot_be_admitted(self):
        p=self.setup_component()
        for key,value in [('path','program/other.dll'),('architecture','arm64'),('role','nativeX64'),('machine',34404),('configuredX86',False),('fullEngineQualified',True)]:
            q=copy.deepcopy(p);q[key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):payload._source_companion_component(q,self.binding)
    def test_linktarget_and_native_helper_identities_must_join(self):
        p=self.setup_component()
        q=copy.deepcopy(p);q['linkTarget']['sha256']='0'*64
        with self.assertRaises(ValueError):payload._source_companion_component(q,self.binding)
        (self.runtime/'program/spsupp_helper.exe').write_bytes(image())
        with self.assertRaises(ValueError):payload._source_companion_runtime(self.runtime,p)
    def test_export_drift_clr_and_forwarders_reject(self):
        p=self.setup_component()
        for value in (image(exports=EXPORTS[:-1]),image(clr=True),image(forwarder=True)):
            q=copy.deepcopy(p);q['size']=len(value);q['sha256']=hashlib.sha256(value).hexdigest();q['linkTarget'].update(size=len(value),sha256=q['sha256']);(self.runtime/'program/spsupp_x86.dll').write_bytes(value)
            with self.assertRaises(ValueError):payload._source_companion_runtime(self.runtime,q)
    def test_vc_unknown_import_and_private_system_shadow_reject(self):
        p=self.setup_component()
        for name in ('vcruntime140.dll','other.dll'):
            q=copy.deepcopy(p);q['imports']['normal']=[name]
            with self.assertRaises(ValueError):payload._source_companion_component(q,self.binding)
        (self.runtime/'program/KERNEL32.DLL').write_bytes(image(native=True))
        with self.assertRaises(ValueError):payload._source_companion_runtime(self.runtime,p)
    def test_changed_staged_bytes_and_alias_paths_reject(self):
        p=self.setup_component();file=self.runtime/'program/spsupp_x86.dll';raw=file.read_bytes();file.write_bytes(raw+b'x')
        with self.assertRaises(ValueError):payload._source_companion_runtime(self.runtime,p)
        file.unlink();target=self.root/'other.dll';target.write_bytes(raw);file.symlink_to(target)
        with self.assertRaises(ValueError):payload._source_companion_runtime(self.runtime,p)
