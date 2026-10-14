"""Pinned cursor transform boundary; native routing lives in tests/hop."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import nested_line_navigation as nav


class NestedLineNavigationProofTests(unittest.TestCase):
    def setUp(self):
        self.helper=hashlib.sha256((ROOT/nav.HELPER).read_bytes()).hexdigest()
        self.proof={'beforeSha256':dict(nav.INPUT_SOURCE_SHA256),'afterSha256':dict(nav.OUTPUT_SOURCE_SHA256),'helperSha256':self.helper}
        self.files=dict(nav.OUTPUT_SOURCE_SHA256);self.helpers={nav.HELPER:self.helper}

    def test_exact_reviewed_contract(self):
        nav.validate_contract(self.proof,self.files,self.helpers)

    def test_pristine_input_and_distinct_output_are_fixed(self):
        self.assertEqual(nav.SOURCE_FILES,(nav.CURSOR,nav.BRIDGE))
        self.assertEqual(nav.INPUT_SHA256,'42e7aaaea9e4d0da0be8dee9c419c11aa0e241e410e41afc1bc148caa2b28d97')
        self.assertEqual(nav.OUTPUT_SHA256,'13d1c0d42fb80a54b2979e3ce98200eea5dd26afacd7a62eb809c3008e93fb20')
        self.assertNotEqual(nav.INPUT_SHA256,nav.OUTPUT_SHA256)
        self.assertEqual(nav.INPUT_SOURCE_SHA256[nav.BRIDGE],'f50c0ed04e6bf0953b6f41140ffb9d00a874550c8453894314fc865828e93c8e')
        self.assertEqual(nav.OUTPUT_SOURCE_SHA256[nav.BRIDGE],'d16842afa5e37f673d587614c7b02094bb8f082280d347152ec8cf0b522f23a3')

    def test_coordinated_unreviewed_or_legacy_after_bytes_cannot_qualify(self):
        for value in ('0'*64,nav.INPUT_SHA256):
            proof=copy.deepcopy(self.proof);proof['afterSha256'][nav.CURSOR]=value
            with self.assertRaisesRegex(ValueError,'reviewed'):nav.validate_contract(proof,{nav.CURSOR:value},self.helpers)

    def test_missing_extra_and_forged_source_proofs_are_rejected(self):
        for key in self.proof:
            proof=copy.deepcopy(self.proof);proof.pop(key)
            with self.assertRaises(ValueError):nav.validate_contract(proof,self.files,self.helpers)
        with self.assertRaises(ValueError):nav.validate_contract({**self.proof,'optional':True},self.files,self.helpers)
        proof=copy.deepcopy(self.proof);proof['beforeSha256'][nav.CURSOR]='1'*64
        with self.assertRaises(ValueError):nav.validate_contract(proof,self.files,self.helpers)
        for key in ('beforeSha256','afterSha256'):
            proof=copy.deepcopy(self.proof);proof[key]['unrelated.ts']='2'*64
            with self.assertRaises(ValueError):nav.validate_contract(proof,self.files,self.helpers)

    def test_actual_after_bytes_and_current_helper_are_required(self):
        with self.assertRaisesRegex(ValueError,'prepared'):nav.validate_contract(self.proof,{},self.helpers)
        with self.assertRaisesRegex(ValueError,'prepared'):nav.validate_contract(self.proof,{nav.CURSOR:'3'*64},self.helpers)
        with self.assertRaisesRegex(ValueError,'helper'):nav.validate_contract(self.proof,self.files,{})
        proof=copy.deepcopy(self.proof);proof['helperSha256']='4'*64
        with self.assertRaisesRegex(ValueError,'helper'):nav.validate_contract(proof,self.files,{nav.HELPER:'4'*64})

    def test_each_observed_source_hash_is_required_independently(self):
        for name in nav.SOURCE_FILES:
            files=dict(self.files);files[name]='5'*64
            with self.assertRaisesRegex(ValueError,'prepared'):nav.validate_contract(self.proof,files,self.helpers)
            files=dict(self.files);files.pop(name)
            with self.assertRaisesRegex(ValueError,'prepared'):nav.validate_contract(self.proof,files,self.helpers)

    def test_cursor_only_legacy_proof_and_bridge_changed_before_cannot_qualify(self):
        proof=copy.deepcopy(self.proof)
        for key in ('beforeSha256','afterSha256'):proof[key].pop(nav.BRIDGE)
        with self.assertRaisesRegex(ValueError,'reviewed'):nav.validate_contract(proof,self.files,self.helpers)
        proof=copy.deepcopy(self.proof);proof['beforeSha256'][nav.BRIDGE]='6'*64
        with self.assertRaisesRegex(ValueError,'reviewed'):nav.validate_contract(proof,self.files,self.helpers)

    def test_nonobject_contract_inputs_are_rejected(self):
        for proof,files,helpers in ((None,self.files,self.helpers),(self.proof,None,self.helpers),(self.proof,self.files,None)):
            with self.assertRaises(ValueError):nav.validate_contract(proof,files,helpers)

    def test_matching_anchors_in_unreviewed_source_are_still_rejected(self):
        for data in (nav.REPLACEMENTS[0][0].encode(),('\n'.join(old for old,_ in nav.REPLACEMENTS)).encode()):
            with self.assertRaisesRegex(ValueError,'input changed'):nav.transformed(data)

    def test_apply_rejects_missing_unknown_and_symlink_sources_without_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary);path=source/nav.CURSOR
            with self.assertRaises(ValueError):nav.apply(source)
            path.parent.mkdir(parents=True);raw=nav.REPLACEMENTS[0][0].encode();path.write_bytes(raw)
            with self.assertRaises(ValueError):nav.apply(source)
            self.assertEqual(path.read_bytes(),raw)
            target=source/'owned-source.ts';target.write_bytes(raw);path.unlink();path.symlink_to(target)
            with self.assertRaisesRegex(ValueError,'regular'):nav.apply(source)
            self.assertEqual(target.read_bytes(),raw)


if __name__=='__main__':unittest.main(verbosity=2)
