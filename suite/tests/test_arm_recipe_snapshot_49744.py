"""Fixed old ARM source metadata compatibility only; no Qualified/Full artifact."""
from pathlib import Path
import copy
import hashlib
import unittest
import test_prepare_source_profile_v2 as fixture
from suite import prepare,source_contracts

OLD='9bf183e354ee1f68158233bad959ac8a756c3e667cb0892760b98c44aabb8e50'
NEW='37fba766084127e2fdf2f51c3108290a39ddfdaa895af03c68d3cfc8b35d2020'
OWNER=dict(sourceCommit='49744d20edd3932917a618c68b3700d7f9f1b8ed',sourceTree='95ad954e01638bbabdf0f11926f302eb09723bcd',sourceRun=43253800021,runAttempt=1)

class ArmSnapshotTests(unittest.TestCase):
    def proof(self,arch='arm64'):
        proof=fixture.PrepareSourceProfileV2Tests().source_only(arch)
        if arch=='arm64':proof.update(OWNER)
        self.assertNotIn('artifact',proof);self.assertNotIn('Full',proof.values())
        return proof
    def test_real_snapshot_and_arch_specific_expected_hashes_remain_separate(self):
        path=Path(prepare.__file__).parent/'engine-build/source-build.26.8.2.2.arm64-49744.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),OLD)
        a=source_contracts.new_source_only_expectations(dict(source_contracts.NEW_SOURCE),'arm64')
        x=source_contracts.new_source_only_expectations(dict(source_contracts.NEW_SOURCE),'x64')
        self.assertEqual((a.source_manifest_sha256,x.source_manifest_sha256),(OLD,NEW))
        self.assertFalse(a.qualifies_runtime);self.assertFalse(x.qualifies_runtime)
    def test_exact_arm_recipe_metadata_has_no_runtime_authority(self):
        proof=self.proof();self.assertEqual(proof['sourcePortManifestSha256'],OLD)
        self.assertIsNone(prepare._source_new_recipe(proof,'arm64'))
        runtime=dict(format='source-built-zip',version='26.8.2.2',sourceCoreCommit=source_contracts.NEW.core,
            sourceUrl=source_contracts.NEW_SOURCE['url'],sourceSha256=source_contracts.NEW_SOURCE['sha256'])
        with self.assertRaises(ValueError):prepare.validate_source_build_lock(runtime,architecture='arm64')
    def test_missing_foreign_or_untyped_producer_never_selects_the_arm_snapshot(self):
        for field,changed in [('sourceCommit',None),('sourceCommit','0'*40),('sourceTree',None),('sourceTree','0'*40),
            ('sourceRun',None),('sourceRun',43253800579),('sourceRun',float(43253800021)),('runAttempt',None),('runAttempt',True),('runAttempt',2)]:
            proof=self.proof()
            if changed is None:proof.pop(field)
            else:proof[field]=changed
            with self.subTest(field=field,valueKind=type(changed).__name__),self.assertRaises(ValueError):prepare._source_new_recipe(proof,'arm64')
    def test_no_cross_arch_manifest_or_automatic_fallback(self):
        for arch,forbidden in [('arm64',NEW),('x64',OLD)]:
            proof=self.proof(arch);proof['sourcePortManifestSha256']=forbidden;proof['sourceRecipeProof']['manifestSha256']=forbidden
            with self.subTest(arch=arch),self.assertRaises(ValueError):prepare._source_new_recipe(proof,arch)

    def test_the_old_arm_original_vector_and_canonical_plan_remain_mandatory(self):
        for kind in ('guard-before','guard-after','omit-guard','other-recipe'):
            proof=self.proof();recipe=proof['sourceRecipeProof']
            if kind=='guard-before':recipe['armGuardedSources'][0]['beforeSha256']='0'*64
            elif kind=='guard-after':recipe['armGuardedSources'][0]['sha256']='0'*64
            elif kind=='omit-guard':recipe['armGuardedSources'].pop()
            else:recipe['recipeSha256']='26a58083e03132ea83a6def9ef4b2c432660a7e8bbcf75063bb325797db8ef4b'
            with self.subTest(kind=kind),self.assertRaises(ValueError):prepare._source_new_recipe(proof,'arm64')
