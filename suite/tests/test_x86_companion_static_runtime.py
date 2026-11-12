"""Exact source-only CRT selection; never a native-build qualification."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
ENGINE=ROOT/'suite/engine-build'
FIXTURE=ROOT/'suite/tests/fixtures/twain-source-9dea'

def load():
    path=ENGINE/'apply_x86_companion_crt.py'
    if not path.is_file():return None
    spec=importlib.util.spec_from_file_location('owned_x86_crt',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def descriptor():return json.loads((ENGINE/'source-build.json').read_bytes())['windowsX86CompanionStaticRuntime']

class StaticRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source=self.root/'source';self.evidence=self.root/'evidence';self.source.mkdir();self.evidence.mkdir()
    def seed(self):
        for p in ('shell/Library_spsupp_x86.mk','extensions/Executable_twain32shim.mk'):
            f=self.source/p;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes((FIXTURE/p).read_bytes())
    def test_source_manifest_and_dispatcher_require_both_exact_targets(self):
        pin=descriptor();self.assertEqual(pin['condition'],'WNT_X86_64_MSC')
        self.assertEqual([r['path']for r in pin['sources']],['shell/Library_spsupp_x86.mk','extensions/Executable_twain32shim.mk'])
        raw=(ENGINE/'apply_native_source.py').read_text()
        self.assertIn("'x86CompanionStaticRuntime'",raw)
        self.assertIn("_install_x86_companion_static_runtime",raw)
    def test_real_source_transform_retains_exact_original_and_effective_for_this_run(self):
        m=load();self.assertIsNotNone(m);self.seed();result=m.install(self.source,self.evidence,descriptor())
        self.assertEqual(len(result['recipes']),2)
        for row,pin in zip(result['recipes'],descriptor()['sources']):
            original=Path(row['evidence']['original']);effective=Path(row['evidence']['effective'])
            self.assertEqual(original.parent,self.evidence);self.assertEqual(effective.parent,self.evidence)
            self.assertEqual(original.read_bytes(),(FIXTURE/pin['path']).read_bytes())
            self.assertEqual(effective.read_bytes(),(self.source/pin['path']).read_bytes())
            self.assertEqual(hashlib.sha256(effective.read_bytes()).hexdigest(),pin['afterSha256'])
        for key in ('nativeBuildVerified','fullEngineQualified','acceptanceEligible','guiVerified'):self.assertIs(result[key],False)
    def test_drifted_second_input_is_rejected_before_evidence_or_first_source_write(self):
        m=load();self.assertIsNotNone(m);self.seed();first=self.source/'shell/Library_spsupp_x86.mk';before=first.read_bytes()
        (self.source/'extensions/Executable_twain32shim.mk').write_bytes(b'changed')
        with self.assertRaises(ValueError):m.install(self.source,self.evidence,descriptor())
        self.assertEqual(first.read_bytes(),before);self.assertEqual(list(self.evidence.iterdir()),[])
    def test_reapply_and_preexisting_evidence_are_rejected(self):
        m=load();self.assertIsNotNone(m);self.seed();m.install(self.source,self.evidence,descriptor())
        with self.assertRaises(ValueError):m.install(self.source,self.evidence,descriptor())
    def test_effective_targets_keep_objects_libraries_and_x86_lto_contract(self):
        m=load();self.assertIsNotNone(m)
        for row in descriptor()['sources']:
            original=(FIXTURE/row['path']).read_bytes();effective=m.transform(original,row)
            self.assertEqual(effective.count(b'-MT -U_DLL'),1)
            self.assertEqual(effective.replace(m.addition(row['path']),b''),original)
            self.assertIn(b'_set_x86,',effective);self.assertIn(b'-GL-',effective);self.assertIn(b'-LTCG:OFF',effective)
            self.assertNotIn(b'disable_standard_system_libs',effective);self.assertNotIn(b'libcmt',effective)
