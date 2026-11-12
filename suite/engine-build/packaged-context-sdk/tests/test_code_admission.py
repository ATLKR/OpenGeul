import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
RUNTIME=('approved_launch.py','ci_entry.py','owned_job_win32.py','run_sdk_gate.py','sdk_smoke.hpp',
 'supervisor.py','toolchain.py','windows_sdk_smoke.cpp')

class ApprovalTests(unittest.TestCase):
    def api(self):
        self.assertTrue((ROOT/'approved_launch.py').is_file(),'external manifest bootstrap required')
        import approved_launch
        return approved_launch
    def copy_approved(self,root):
        rows=[]
        for name in RUNTIME:
            b=(ROOT/name).read_bytes();(root/name).write_bytes(b)
            rows.append({'path':name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
        value={'schemaVersion':1,'kind':'sdk-gate-code-approval','files':rows}
        raw=json.dumps(value,sort_keys=True,separators=(',',':')).encode()+b'\n'
        path=root/'approved-sdk-code.json';path.write_bytes(raw)
        return path,hashlib.sha256(raw).hexdigest()
    def test_exact_external_manifest_admits_source_bytes_without_qualifying_runtime(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);manifest,pin=self.copy_approved(root)
            context=m.admit_code(root,manifest,pin)
            context.require_root(root)
            self.assertEqual(context.manifest_sha256,pin)
            self.assertEqual(context.read_approved('windows_sdk_smoke.cpp'),(root/'windows_sdk_smoke.cpp').read_bytes())
            self.assertFalse(context.qualification);self.assertFalse(context.can_service)
    def test_changed_header_entry_controller_or_validator_cannot_admit(self):
        m=self.api()
        for index,name in enumerate(RUNTIME):
            with self.subTest(slot=index),tempfile.TemporaryDirectory() as td:
                root=Path(td);manifest,pin=self.copy_approved(root)
                (root/name).write_bytes(b'int wmain(){return 0;}\n' if name=='windows_sdk_smoke.cpp' else (root/name).read_bytes()+b'\n')
                with self.assertRaises(m.ApprovalFailure):m.admit_code(root,manifest,pin)
    def test_mutated_manifest_cannot_choose_its_own_hash(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);manifest,pin=self.copy_approved(root)
            value=json.loads(manifest.read_bytes());value['files'][0]['sha256']='0'*64
            manifest.write_text(json.dumps(value))
            with self.assertRaises(m.ApprovalFailure):m.admit_code(root,manifest,pin)
            with self.assertRaises(m.ApprovalFailure):m.admit_code(root,manifest,None)
    def test_stale_admission_rechecks_input_before_copy(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);manifest,pin=self.copy_approved(root);context=m.admit_code(root,manifest,pin)
            p=root/'sdk_smoke.hpp';p.write_bytes(p.read_bytes()+b'\n')
            with self.assertRaises(m.ApprovalFailure):context.read_approved('sdk_smoke.hpp')
    def test_alias_or_extra_manifest_slot_and_forged_context_fail_closed(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);manifest,pin=self.copy_approved(root)
            p=root/'sdk_smoke.hpp';p.unlink();p.symlink_to(ROOT/'sdk_smoke.hpp')
            with self.assertRaises(m.ApprovalFailure):m.admit_code(root,manifest,pin)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);manifest,pin=self.copy_approved(root);v=json.loads(manifest.read_bytes())
            v['files'].append({'path':'other.py','bytes':1,'sha256':'0'*64})
            raw=json.dumps(v).encode();manifest.write_bytes(raw)
            with self.assertRaises(m.ApprovalFailure):m.admit_code(root,manifest,hashlib.sha256(raw).hexdigest())
        with self.assertRaises(m.ApprovalFailure):m.require_admission({'approved':True},ROOT)
    def test_tampered_entry_is_rejected_by_isolated_bootstrap_before_gate_import(self):
        self.api()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);manifest,pin=self.copy_approved(root)
            (root/'windows_sdk_smoke.cpp').write_bytes(b'int wmain(){return 0;}\n')
            p=subprocess.Popen([sys.executable,'-I','-B',str(root/'approved_launch.py'),
              '--approved-manifest',str(manifest),'--expected-approved-manifest-sha256',pin,
              '--diagnostic-sdk-only','--architecture','x64','--source-bundle',str(ROOT/'frozen-v2'),
              '--work-root',str(root/'unused'),'--output',str(root/'unused/sdk-gate.numeric.json')],
              cwd=root,env={'PATH':'/usr/bin:/bin'},stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:code=p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=1);self.fail('bounded bootstrap failed to exit')
            self.assertEqual(code,3);self.assertFalse((root/'unused').exists())
    def test_isolated_valid_bootstrap_reaches_platform_rejection_without_false_success(self):
        self.api()
        if sys.platform=='win32':return
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);manifest,pin=self.copy_approved(root)
            p=subprocess.Popen([sys.executable,'-I','-B',str(root/'approved_launch.py'),
              '--approved-manifest',str(manifest),'--expected-approved-manifest-sha256',pin,
              '--diagnostic-sdk-only','--architecture','x64','--source-bundle',str(ROOT/'frozen-v2'),
              '--work-root',str(root/'unused'),'--output',str(root/'unused/sdk-gate.numeric.json')],
              cwd=root,env={'PATH':'/usr/bin:/bin'},stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:code=p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=1);self.fail('bounded bootstrap failed to exit')
            self.assertEqual(code,2);self.assertFalse((root/'unused').exists())
