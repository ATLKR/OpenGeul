"""Exact TWAIN component-only units; no Full or executable runtime is invented."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import struct
import tempfile
import unittest

from test_source_companion import image
import test_source_companion as sharepoint_fixture

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('twain_payload',ROOT/'suite/payload.py')
payload=importlib.util.module_from_spec(spec);spec.loader.exec_module(payload)

def twain_image():
    b=bytearray(image(exports=[]));struct.pack_into('<H',b,0x80+22,0x102)
    struct.pack_into('<I',b,0x98+16,0x1500);struct.pack_into('<H',b,0x98+68,2)
    return bytes(b)

def peer_image():
    b=bytearray(image(native=True));struct.pack_into('<H',b,0x80+22,0x2022);return bytes(b)

class TwainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def component(self):
        self.assertTrue(hasattr(payload,'_source_twain_component'),'distinct strict TWAIN profile is required')
        self.runtime=self.root/'runtime';(self.runtime/'program').mkdir(parents=True)
        exe=twain_image();peer=peer_image();(self.runtime/'program/twain32shim.exe').write_bytes(exe);(self.runtime/'program/scnlo.dll').write_bytes(peer)
        digest=lambda b:hashlib.sha256(b).hexdigest();self.binding=dict(sourceCommit='1'*40,sourceTree='2'*40,sourceRun=123,runAttempt=1,recipeSha256='3'*64)
        return dict(schemaVersion=1,kind='source-built-x86-twain-companion',architecture='x64',coreCommit='9dea406ab7695df6325b11b0e19fdca8db4b7276',path='program/twain32shim.exe',role='x86CompatibilityHelper',machine=332,size=len(exe),sha256=digest(exe),buildBinding=dict(self.binding),sourceIntent='twain-32bit-driver-process-bridge',sourceProofs=copy.deepcopy(payload.SOURCE_TWAIN_SOURCE_PINS),configuredX86=True,linkTarget=dict(path='workdir/LinkTarget/Executable/twain32shim.exe',size=len(exe),sha256=digest(exe)),nativePeer=dict(path='program/scnlo.dll',machine=34404,role='nativeX64',size=len(peer),sha256=digest(peer)),installedArchive=dict(kind='main',size=1024,sha256='4'*64,stageReceiptSha256='5'*64),exports=[],imports=dict(normal=['kernel32.dll'],delay=[]),dependencyPolicy='x86-twain-os-only-no-private-shadow-v1',fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
    def test_exact_exe_and_scanner_peer_are_a_separate_nonqualifying_profile(self):
        p=self.component();result=payload._source_twain_component(p,self.binding)
        self.assertEqual(set(result),{'program/twain32shim.exe'});payload._source_twain_runtime(self.runtime,p)
        with self.assertRaises(ValueError):payload._source_companion_component(p,self.binding)
    def test_cross_profile_path_arch_run_and_counts_reject(self):
        p=self.component()
        for key,value in [('kind','source-built-x86-sharepoint-companion'),('path','program/other.exe'),('architecture','arm64'),('role','nativeX64'),('machine',True),('fullEngineQualified',True)]:
            q=copy.deepcopy(p);q[key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):payload._source_twain_component(q,self.binding)
        q=copy.deepcopy(p);q['buildBinding']['sourceRun']=124
        with self.assertRaises(ValueError):payload._source_twain_component(q,self.binding)
    def test_all_original_and_reviewed_effective_source_proofs_are_required(self):
        p=self.component();self.assertEqual(len(p['sourceProofs']),25)
        for kind in ('omit','original','effective'):
            q=copy.deepcopy(p)
            if kind=='omit':q['sourceProofs'].pop()
            else:q['sourceProofs'][0]['sha256' if kind=='original' else 'effectiveSha256']='0'*64
            with self.subTest(kind=kind),self.assertRaises(ValueError):payload._source_twain_component(q,self.binding)
    def test_dll_clr_console_unmapped_entry_and_exports_are_not_twain_executables(self):
        p=self.component();values=[]
        for offset,fmt,value in [(0x80+22,'<H',0x2102),(0x98+68,'<H',3),(0x98+16,'<I',0x9000),(0x98+96+14*8,'<I',0x1600)]:
            b=bytearray(twain_image());struct.pack_into(fmt,b,offset,value);values.append(bytes(b))
        values.append(image())
        for ordinal,data in enumerate(values):
            q=copy.deepcopy(p);q.update(size=len(data),sha256=hashlib.sha256(data).hexdigest());q['linkTarget'].update(size=len(data),sha256=q['sha256']);(self.runtime/'program/twain32shim.exe').write_bytes(data)
            with self.subTest(case=ordinal),self.assertRaises(ValueError):payload._source_twain_runtime(self.runtime,q)
    def test_native_scanner_peer_and_dependency_closure_cannot_be_replaced(self):
        p=self.component();q=copy.deepcopy(p);q['nativePeer']['role']='managedAnyCpu'
        with self.assertRaises(ValueError):payload._source_twain_component(q,self.binding)
        (self.runtime/'program/scnlo.dll').write_bytes(twain_image())
        with self.assertRaises(ValueError):payload._source_twain_runtime(self.runtime,p)
        for name in ('vcruntime140.dll','private.dll'):
            q=copy.deepcopy(p);q['imports']['normal']=[name]
            with self.assertRaises(ValueError):payload._source_twain_component(q,self.binding)
    def test_new_twain_os_modules_do_not_widen_the_sharepoint_dll_profile(self):
        p=self.component();p['imports']['normal']=['kernel32.dll','shell32.dll']
        payload._source_twain_component(p,self.binding)
        fixture=sharepoint_fixture.SourceCompanionTests('test_exact_component_and_actual_bytes_are_separate_from_full_authority');fixture.setUp();self.addCleanup(fixture.doCleanups)
        other=fixture.setup_component();other['imports']['normal']=['kernel32.dll','shell32.dll']
        with self.assertRaises(ValueError):payload._source_companion_component(other,fixture.binding)
    def test_twain_metadata_cannot_be_smuggled_into_legacy_or_arm_profiles(self):
        legacy=next(core for core in payload._PYTHON_TEMPLATE_SOURCES if core!=payload._SOURCE_COMPANION_CORE)
        for core,architecture in ((legacy,'x64'),(payload._SOURCE_COMPANION_CORE,'arm64')):
            with self.subTest(architecture=architecture),self.assertRaises(ValueError):
                payload._source_companion_admissions(dict(format='source-built-zip',sourceCoreCommit=core),
                    dict(sourceTwainProof={}),architecture=architecture)
    def test_actual_delay_imports_and_private_system_shadow_remain_fail_closed(self):
        p=self.component();binary=bytearray(twain_image())
        struct.pack_into('<II',binary,0x98+96+13*8,0x1700,64)
        struct.pack_into('<II',binary,0x900,1,0x1780);binary[0x980:0x98b]=b'user32.dll\0'
        data=bytes(binary);q=copy.deepcopy(p);q.update(size=len(data),sha256=hashlib.sha256(data).hexdigest());q['linkTarget'].update(size=len(data),sha256=q['sha256']);q['imports']['delay']=['user32.dll']
        (self.runtime/'program/twain32shim.exe').write_bytes(data);payload._source_twain_runtime(self.runtime,q)
        shadow=self.runtime/'program/USER32.DLL';shadow.write_bytes(peer_image())
        with self.assertRaises(ValueError):payload._source_twain_runtime(self.runtime,q)
        shadow.unlink()
        for name in ('private.dll','vcruntime140.dll'):
            q['imports']['delay']=[name]
            with self.subTest(module=name),self.assertRaises(ValueError):payload._source_twain_component(q,self.binding)
