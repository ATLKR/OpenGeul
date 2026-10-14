"""Fail-closed source/proof boundary tests; real routing is tested in tests/hop."""
import copy
import hashlib
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import shape_creation_history as shape


class ShapeCreationProofTests(unittest.TestCase):
    def setUp(self):
        self.helper=hashlib.sha256((ROOT/shape.HELPER).read_bytes()).hexdigest()
        self.proof={'beforeSha256':dict(shape.INPUT_SOURCE_SHA256),
                    'afterSha256':dict(shape.OUTPUT_SOURCE_SHA256),
                    'helperSha256':self.helper}
        self.files=dict(shape.OUTPUT_SOURCE_SHA256)
        self.helpers={shape.HELPER:self.helper}

    def test_exact_reviewed_proof_and_observed_source_binding(self):
        shape.validate_contract(self.proof,self.files,self.helpers)

    def test_reviewed_input_output_pins_are_distinct_and_fixed(self):
        self.assertEqual(shape.INPUT_SHA256,'ee144804d21ea5585fc03e5057317310990197c3b096c9aa34caa8006299d3c8')
        self.assertEqual(shape.OUTPUT_SHA256,'bd3e440d6c71f268d58018d5ed84a6f1622d5f15264b267fcd40f5933c51aaac')
        self.assertEqual(shape.CONNECTOR_INPUT_SHA256,'ec265208f6fa7bd4bb82368c8a611c4915a0be89d9acb99108fad911f12a4dec')
        self.assertEqual(shape.CONNECTOR_OUTPUT_SHA256,'61bdad87ff678d8279ec8103aa54a2c6aa7d238006bff7e30a92bef5f101e2e0')
        self.assertEqual(set(shape.SOURCE_FILES),{shape.HANDLER,shape.CONNECTOR})
        self.assertNotEqual(shape.INPUT_SHA256,shape.OUTPUT_SHA256)

    def test_coordinated_after_hash_forgery_cannot_replace_fixed_output(self):
        for path in shape.SOURCE_FILES:
            forged=copy.deepcopy(self.proof); forged['afterSha256'][path]='0'*64
            with self.assertRaisesRegex(ValueError,'reviewed'):
                shape.validate_contract(forged,{**self.files,path:'0'*64},self.helpers)

    def test_legacy_source_and_coordinated_legacy_proof_cannot_qualify(self):
        forged=copy.deepcopy(self.proof); forged['afterSha256'][shape.HANDLER]=shape.INPUT_SHA256
        with self.assertRaises(ValueError):
            shape.validate_contract(forged,{**self.files,shape.HANDLER:shape.INPUT_SHA256},self.helpers)

    def test_changed_input_claim_and_unknown_proof_keys_are_rejected(self):
        forged=copy.deepcopy(self.proof); forged['beforeSha256'][shape.HANDLER]='1'*64
        with self.assertRaises(ValueError):shape.validate_contract(forged,self.files,self.helpers)
        for key in self.proof:
            missing=copy.deepcopy(self.proof);missing.pop(key)
            with self.assertRaises(ValueError):shape.validate_contract(missing,self.files,self.helpers)
        with self.assertRaises(ValueError):shape.validate_contract({**self.proof,'optional':True},self.files,self.helpers)

    def test_observed_source_bytes_and_helper_identity_are_required(self):
        for path in shape.SOURCE_FILES:
            with self.assertRaisesRegex(ValueError,'prepared'):
                shape.validate_contract(self.proof,{**self.files,path:'2'*64},self.helpers)
        with self.assertRaisesRegex(ValueError,'helper'):
            shape.validate_contract(self.proof,self.files,{})
        forged=copy.deepcopy(self.proof);forged['helperSha256']='3'*64
        with self.assertRaisesRegex(ValueError,'helper'):
            shape.validate_contract(forged,self.files,{shape.HELPER:'3'*64})

    def test_matching_creation_anchor_in_unknown_source_still_fails(self):
        with self.assertRaisesRegex(ValueError,'input changed'):
            shape.transformed(shape.OLD.encode('utf-8'))
        with self.assertRaisesRegex(ValueError,'input changed'):
            shape.transformed((shape.OLD+'\n// tampered source').encode('utf-8'))
        with self.assertRaisesRegex(ValueError,'input changed'):
            shape.transformed(shape.CONNECTOR_OLD.encode('utf-8'),shape.CONNECTOR)

    def test_omitted_connector_source_or_proof_cannot_qualify(self):
        for key in ('beforeSha256','afterSha256'):
            missing=copy.deepcopy(self.proof);missing[key].pop(shape.CONNECTOR)
            with self.assertRaises(ValueError):shape.validate_contract(missing,self.files,self.helpers)
        missing_files=dict(self.files);missing_files.pop(shape.CONNECTOR)
        with self.assertRaises(ValueError):shape.validate_contract(self.proof,missing_files,self.helpers)


if __name__=='__main__':unittest.main(verbosity=2)
