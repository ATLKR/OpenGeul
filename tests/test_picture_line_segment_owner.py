"""Closed Source4 picture row-owner source/proof admission policy."""
from pathlib import Path
import copy
import hashlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import picture_line_segment_owner as owner

class PictureLineOwnerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name);self.name=owner.SOURCE_FILES[0]
        self.path=self.source/self.name;self.path.parent.mkdir(parents=True)
        self.before=b'// isolated owned policy fixture\n'+b'\n'.join(old.encode() for old,new in owner.REPLACEMENTS)
        after=self.before
        for old,new in owner.REPLACEMENTS:after=after.replace(old.encode(),new.encode())
        self.path.write_bytes(self.before)
        self.before_map={self.name:hashlib.sha256(self.before).hexdigest()}
        self.after_map={self.name:hashlib.sha256(after).hexdigest()}
        for name,value in [('INPUT_SOURCE_SHA256',self.before_map),('OUTPUT_SOURCE_SHA256',self.after_map)]:
            override=patch.object(owner,name,value);override.start();self.addCleanup(override.stop)
        self.helpers={owner.HELPER:owner.sha(ROOT/owner.HELPER)}

    def test_exact_current_source_proof_and_helper_are_required(self):
        proof=owner.apply(self.source)
        self.assertEqual(proof,{'beforeSha256':self.before_map,'afterSha256':self.after_map,'helperSha256':self.helpers[owner.HELPER]})
        owner.validate_contract(proof,self.after_map,self.helpers)

    def test_missing_and_drifted_source_are_rejected_before_writing(self):
        self.path.unlink()
        with self.assertRaises(ValueError):owner.apply(self.source)
        raw=self.before+b'\n// source drift\n';self.path.write_bytes(raw)
        with self.assertRaises(ValueError):owner.apply(self.source)
        self.assertEqual(self.path.read_bytes(),raw)

    def test_duplicate_geometry_boundary_anchor_is_not_admitted(self):
        old,new=owner.REPLACEMENTS[0];raw=self.before+old.encode();self.path.write_bytes(raw)
        with patch.object(owner,'INPUT_SOURCE_SHA256',{self.name:hashlib.sha256(raw).hexdigest()}):
            with self.assertRaises(ValueError):owner.apply(self.source)
        self.assertEqual(self.path.read_bytes(),raw)

    def test_reapplication_cannot_repair_or_refresh_an_old_record(self):
        owner.apply(self.source)
        with self.assertRaises(ValueError):owner.apply(self.source)

    def test_symlink_source_is_rejected_without_mutating_its_target(self):
        self.path.unlink();target=self.source/'owned-target.rs';target.write_bytes(self.before);self.path.symlink_to(target)
        with self.assertRaises(ValueError):owner.apply(self.source)
        self.assertEqual(target.read_bytes(),self.before)

    def test_coherent_legacy_source_and_proof_are_rejected(self):
        proof=owner.apply(self.source);proof['afterSha256']=dict(self.before_map)
        with self.assertRaises(ValueError):owner.validate_contract(proof,self.before_map,self.helpers)

    def test_missing_extra_wrong_hash_and_absent_helper_are_rejected(self):
        proof=owner.apply(self.source);variants=[]
        for key in proof:
            bad=copy.deepcopy(proof);bad.pop(key);variants.append(bad)
        bad=copy.deepcopy(proof);bad['unexpected']=True;variants.append(bad)
        for key in ('beforeSha256','afterSha256'):
            bad=copy.deepcopy(proof);bad[key][self.name]='0'*64;variants.append(bad)
        bad=copy.deepcopy(proof);bad['helperSha256']='0'*64;variants.append(bad)
        for bad in variants:
            with self.subTest(proof=bad),self.assertRaises(ValueError):owner.validate_contract(bad,self.after_map,self.helpers)
        with self.assertRaises(ValueError):owner.validate_contract(proof,{},self.helpers)
        with self.assertRaises(ValueError):owner.validate_contract(proof,self.after_map,{})

if __name__=='__main__':unittest.main()
