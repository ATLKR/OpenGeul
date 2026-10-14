"""Fail-closed source/proof policy for real-body picture-band admission."""
from pathlib import Path
import copy
import hashlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import virtual_picture_layout_admission as admission

class VirtualPictureAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name);self.name=admission.SOURCE_FILES[0];self.path=self.source/self.name;self.path.parent.mkdir(parents=True)
        old,new=admission.REPLACEMENTS[0];self.before=('// owned isolated source policy\n'+old).encode();self.after=self.before.replace(old.encode(),new.encode());self.path.write_bytes(self.before)
        self.before_map={self.name:hashlib.sha256(self.before).hexdigest()};self.after_map={self.name:hashlib.sha256(self.after).hexdigest()}
        for name,value in [('INPUT_SOURCE_SHA256',self.before_map),('OUTPUT_SOURCE_SHA256',self.after_map)]:
            override=patch.object(admission,name,value);override.start();self.addCleanup(override.stop)
        self.helpers={admission.HELPER:admission.sha(ROOT/admission.HELPER)}

    def test_exact_pinned_source_and_helper_proof(self):
        proof=admission.apply(self.source);self.assertEqual(proof,{'beforeSha256':self.before_map,'afterSha256':self.after_map,'helperSha256':self.helpers[admission.HELPER]});admission.validate_contract(proof,self.after_map,self.helpers)

    def test_missing_or_drifted_source_never_gets_patched(self):
        self.path.unlink()
        with self.assertRaises(ValueError):admission.apply(self.source)
        raw=self.before+b'\n// drift\n';self.path.write_bytes(raw)
        with self.assertRaises(ValueError):admission.apply(self.source)
        self.assertEqual(self.path.read_bytes(),raw)

    def test_duplicate_body_admission_anchor_is_rejected(self):
        old,new=admission.REPLACEMENTS[0];raw=self.before+old.encode();self.path.write_bytes(raw)
        with patch.object(admission,'INPUT_SOURCE_SHA256',{self.name:hashlib.sha256(raw).hexdigest()}):
            with self.assertRaises(ValueError):admission.apply(self.source)

    def test_reapplication_does_not_refresh_the_original_pin(self):
        admission.apply(self.source)
        with self.assertRaises(ValueError):admission.apply(self.source)

    def test_symlink_cannot_change_the_real_source(self):
        self.path.unlink();target=self.source/'owned-target.rs';target.write_bytes(self.before);self.path.symlink_to(target)
        with self.assertRaises(ValueError):admission.apply(self.source)
        self.assertEqual(target.read_bytes(),self.before)

    def test_coherent_legacy_proof_and_source_fail(self):
        proof=admission.apply(self.source);proof['afterSha256']=dict(self.before_map)
        with self.assertRaises(ValueError):admission.validate_contract(proof,self.before_map,self.helpers)

    def test_missing_extra_wrong_hash_and_absent_helper_fail(self):
        proof=admission.apply(self.source);variants=[]
        for key in proof:
            bad=copy.deepcopy(proof);bad.pop(key);variants.append(bad)
        bad=copy.deepcopy(proof);bad['unexpected']=True;variants.append(bad)
        for key in ('beforeSha256','afterSha256'):
            bad=copy.deepcopy(proof);bad[key][self.name]='0'*64;variants.append(bad)
        bad=copy.deepcopy(proof);bad['helperSha256']='0'*64;variants.append(bad)
        for bad in variants:
            with self.subTest(proof=bad),self.assertRaises(ValueError):admission.validate_contract(bad,self.after_map,self.helpers)
        with self.assertRaises(ValueError):admission.validate_contract(proof,{},self.helpers)
        with self.assertRaises(ValueError):admission.validate_contract(proof,self.after_map,{})

if __name__=='__main__':unittest.main()
