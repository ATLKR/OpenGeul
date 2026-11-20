"""Exact ARM producer source metadata; no Full artifact or adoption authority."""
import copy
import hashlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest

import test_prepare_source_profile_v2 as fixture
from suite import prepare, source_contracts

OLD_OWNER=dict(sourceCommit='49744d20edd3932917a618c68b3700d7f9f1b8ed',
    sourceTree='95ad954e01638bbabdf0f11926f302eb09723bcd',sourceRun=43253800021,runAttempt=1)
NEW_OWNER=dict(sourceCommit='ceabc8032358b2e2a4b89acea5d1009abcdb68a3',
    sourceTree='274ef965899577a8f36a0a1cbf4f5081f41c882f',sourceRun=44616583865,runAttempt=1)
MANIFEST_SHA='9bf183e354ee1f68158233bad959ac8a756c3e667cb0892760b98c44aabb8e50'
RECIPE_SHA='9b10511f31066a5966014c6357268b4d1dcfa3ffa24eb9c97c8bc0c05dbef0fe'


class ArmRecipeOwnerTests(unittest.TestCase):
    def proof(self, owner=NEW_OWNER):
        proof=fixture.PrepareSourceProfileV2Tests().source_only('arm64')
        proof.update(owner)
        return proof

    def test_new_exact_owner_selects_existing_source_recipe_without_changing_proof(self):
        proof=self.proof();before=copy.deepcopy(proof)
        self.assertIsNone(prepare._source_new_recipe(proof,'arm64'))
        self.assertEqual(proof,before)
        self.assertEqual(proof['sourcePortManifestSha256'],MANIFEST_SHA)
        self.assertEqual(proof['sourceRecipeProof']['recipeSha256'],RECIPE_SHA)
        for key in ('artifact','passed','phase','status','fullEngineQualified','acceptanceEligible'):
            self.assertNotIn(key,proof)

    def test_each_named_owner_record_is_exact_and_immutable(self):
        for record,expected in ((source_contracts.ARM_49744_RECIPE_OWNER,OLD_OWNER),
                (source_contracts.ARM_CEABC803_RECIPE_OWNER,NEW_OWNER)):
            with self.subTest(owner=expected['sourceRun']):
                self.assertEqual(dict(record),expected)
                with self.assertRaises(TypeError):record['runAttempt']=2
        expected=source_contracts.new_source_only_expectations(dict(source_contracts.NEW_SOURCE),'arm64')
        self.assertIs(expected.qualifies_runtime,False)
        self.assertEqual(expected.source_manifest_sha256,MANIFEST_SHA)

    def test_original_owner_remains_accepted_without_qualification_flags(self):
        proof=self.proof(OLD_OWNER);before=copy.deepcopy(proof)
        self.assertIsNone(prepare._source_new_recipe(proof,'arm64'))
        self.assertEqual(proof,before)

    def test_no_mixed_commit_tree_or_run_can_select_a_known_owner(self):
        fields=('sourceCommit','sourceTree','sourceRun')
        for selection in itertools.product((0,1),repeat=3):
            if len(set(selection))==1:continue
            owner={key:(OLD_OWNER,NEW_OWNER)[side][key] for key,side in zip(fields,selection)}
            owner['runAttempt']=1
            with self.subTest(selection=selection),self.assertRaises(ValueError):
                prepare._source_new_recipe(self.proof(owner),'arm64')

    def test_missing_untyped_or_foreign_fields_and_non_dict_proofs_are_rejected(self):
        class Text(str):pass
        class Number(int):pass
        class Object(dict):pass
        for owner in (OLD_OWNER,NEW_OWNER):
            for key,value in owner.items():
                invalid=(None,True,float(value),str(value),Number(value)) if type(value)is int else (None,value.encode(),Text(value),'0'*40)
                for changed in invalid:
                    proof=self.proof(owner);proof[key]=changed
                    with self.subTest(field=key,kind=type(changed).__name__),self.assertRaises(ValueError):
                        prepare._source_new_recipe(proof,'arm64')
                proof=self.proof(owner);proof.pop(key)
                with self.subTest(missing=key),self.assertRaises(ValueError):
                    prepare._source_new_recipe(proof,'arm64')
            for attempt in (0,2,-1):
                proof=self.proof(owner);proof['runAttempt']=attempt
                with self.subTest(attempt=attempt),self.assertRaises(ValueError):
                    prepare._source_new_recipe(proof,'arm64')
        for proof in (None,[],Object(NEW_OWNER)):
            with self.subTest(kind=type(proof).__name__),self.assertRaises(ValueError):
                prepare._source_new_arm_recipe_owner(proof)

    def test_unregistered_runs_and_diagnostic_producer_cannot_borrow_known_owner(self):
        # Public diagnostic source/run identity; no unobserved diagnostic tree is invented.
        diagnostic_commit='867ee1db23d9142ffd2f7984793482831e359af5'
        diagnostic_run=40666981474
        for change in ({'sourceRun':NEW_OWNER['sourceRun']+1},
                {'sourceCommit':diagnostic_commit},{'sourceRun':diagnostic_run},
                {'sourceCommit':diagnostic_commit,'sourceRun':diagnostic_run}):
            proof=self.proof();proof.update(change)
            with self.subTest(fields=tuple(change)),self.assertRaises(ValueError):
                prepare._source_new_recipe(proof,'arm64')

    def test_owner_selection_does_not_bypass_external_full_receipt_authentication(self):
        proof=self.proof()
        self.assertIsNone(prepare._source_new_recipe(proof,'arm64'))
        runtime=dict(format='source-built-zip',version=source_contracts.NEW.version,
            sourceCoreCommit=source_contracts.NEW.core,sourceUrl=source_contracts.NEW_SOURCE['url'],
            sourceSha256=source_contracts.NEW_SOURCE['sha256'],size=1,sha256='1'*64,
            url='https://example.invalid/synthetic-full.zip')
        with self.assertRaises(ValueError):prepare.validate_source_build_lock(runtime,architecture='arm64')
        with tempfile.TemporaryDirectory() as directory:
            receipt=Path(directory)/'source-only.json'
            runtime['sourceBuild']=dict(receiptSha256='0'*64,sourceCommit=NEW_OWNER['sourceCommit'],
                sourceTree=NEW_OWNER['sourceTree'],runId=NEW_OWNER['sourceRun'],artifactId=1,
                artifactSha256='2'*64,patchManifestSha256=MANIFEST_SHA,driverSha256='3'*64,
                nativeTargetsSha256='ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc')
            receipt.write_bytes(json.dumps(proof,sort_keys=True).encode())
            with self.assertRaises(ValueError):
                prepare.validate_source_build_receipt(runtime,receipt,architecture='arm64')
            # Even a synthetically matching receipt digest supplies no Full proof.
            runtime['sourceBuild']['receiptSha256']=hashlib.sha256(receipt.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                prepare.validate_source_build_receipt(runtime,receipt,architecture='arm64')
            proof.update(kind='native-office-engine-calc-dispatch-diagnostic',phase='Full',
                passed=True,fullEngineQualified=True,acceptanceEligible=True)
            receipt.write_bytes(json.dumps(proof,sort_keys=True).encode())
            runtime['sourceBuild']['receiptSha256']=hashlib.sha256(receipt.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                prepare.validate_source_build_receipt(runtime,receipt,architecture='arm64')

    def test_new_owner_keeps_all_existing_typed_false_recipe_flags(self):
        for key in ('nativeBuildVerified','fullEngineQualified','acceptanceEligible','guiVerified'):
            for changed in (True,0):
                proof=self.proof();proof['sourceRecipeProof'][key]=changed
                with self.subTest(flag=key,kind=type(changed).__name__),self.assertRaises(ValueError):
                    prepare._source_new_recipe(proof,'arm64')


if __name__=='__main__':unittest.main()
