from pathlib import Path
import copy
import hashlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import stored_lineseg_origin as origin

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

class StoredLineSegOriginPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        self.before = {}; self.after = {}
        for name, (old, new) in origin.REPLACEMENTS.items():
            raw = ('// isolated policy fixture\n'+old+'\n').encode()
            path = self.source/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            self.before[name] = sha(raw)
            self.after[name] = sha(raw.replace(old.encode(),new.encode()))
        self.addCleanup(patch.stopall)
        patch.object(origin,'INPUT_SOURCE_SHA256',self.before).start()
        patch.object(origin,'OUTPUT_SOURCE_SHA256',self.after).start()

    def applied(self):
        proof = origin.apply(self.source)
        helpers = {origin.HELPER: sha((ROOT/origin.HELPER).read_bytes())}
        return proof,helpers

    def test_real_public_regression_is_mandatory_in_native_graph(self):
        sys.path.insert(0,str(ROOT/'scripts'))
        import prepare_native_tests
        self.assertEqual(prepare_native_tests.TARGETS.get('opengeul_stored_lineseg_origin'),'opengeul_stored_lineseg_tests.rs')
        body=(ROOT/'scripts/build-msix.ps1').read_text()
        self.assertIn('cargo test --locked --target $target --test opengeul_stored_lineseg_origin --features native-skia',body)

    def test_exact_three_source_proof_and_owned_helper(self):
        proof,helpers=self.applied()
        self.assertEqual(set(proof), {'beforeSha256','afterSha256','helperSha256'})
        self.assertEqual(proof['beforeSha256'],self.before)
        self.assertEqual(proof['afterSha256'],self.after)
        origin.validate_contract(proof,self.after,helpers)
        for name in origin.SOURCE_FILES:self.assertEqual(sha((self.source/name).read_bytes()),self.after[name])

    def test_any_missing_source_is_rejected_before_other_files_change(self):
        name=origin.SOURCE_FILES[-1];(self.source/name).unlink()
        with self.assertRaises(ValueError):origin.apply(self.source)
        for name in origin.SOURCE_FILES[:-1]:self.assertEqual(sha((self.source/name).read_bytes()),self.before[name])

    def test_any_pristine_source_drift_is_rejected_before_any_write(self):
        name=origin.SOURCE_FILES[-1];(self.source/name).write_bytes((self.source/name).read_bytes()+b'// drift\n')
        with self.assertRaises(ValueError):origin.apply(self.source)
        for name in origin.SOURCE_FILES[:-1]:self.assertEqual(sha((self.source/name).read_bytes()),self.before[name])

    def test_duplicate_patch_anchor_is_not_admitted(self):
        name=origin.SOURCE_FILES[0];old,_=origin.REPLACEMENTS[name];raw=(old+old).encode();(self.source/name).write_bytes(raw);self.before[name]=sha(raw)
        with self.assertRaises(ValueError):origin.apply(self.source)

    def test_reapplication_cannot_refresh_or_repair_a_prior_proof(self):
        self.applied()
        with self.assertRaises(ValueError):origin.apply(self.source)

    def test_coherent_legacy_after_source_and_proof_are_rejected(self):
        proof,helpers=self.applied();old=copy.deepcopy(proof);old['afterSha256']=dict(self.before)
        with self.assertRaises(ValueError):origin.validate_contract(old,self.before,helpers)

    def test_missing_extra_wrong_pin_and_wrong_helper_proofs_are_rejected(self):
        proof,helpers=self.applied()
        variants=[]
        for field in proof:
            bad=copy.deepcopy(proof);bad.pop(field);variants.append(bad)
        bad=copy.deepcopy(proof);bad['unexpected']=True;variants.append(bad)
        for field in ('beforeSha256','afterSha256'):
            bad=copy.deepcopy(proof);bad[field][origin.SOURCE_FILES[0]]='0'*64;variants.append(bad)
        bad=copy.deepcopy(proof);bad['helperSha256']='0'*64;variants.append(bad)
        for bad in variants:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):origin.validate_contract(bad,self.after,helpers)
        with self.assertRaises(ValueError):origin.validate_contract(proof,self.after,{origin.HELPER:'0'*64})
        missing=dict(self.after);missing.pop(origin.SOURCE_FILES[0])
        with self.assertRaises(ValueError):origin.validate_contract(proof,missing,helpers)

if __name__=='__main__':unittest.main()
