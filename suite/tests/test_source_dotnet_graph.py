"""Synthetic source-only .NET graph evidence; no Full/runtime qualification."""
import copy
import unittest

from suite import prepare as consumer
from suite import source_contracts as contracts
import test_prepare_source_profile_v2 as profiles


class SourceDotnetGraphTests(unittest.TestCase):
    def manifest(self):
        return profiles.PrepareSourceProfileV2Tests().manifest()

    def source_only(self, architecture):
        return profiles.PrepareSourceProfileV2Tests().source_only(architecture)

    def pins(self,manifest):
        function=getattr(consumer,'_source_new_dotnet_pins',None)
        self.assertTrue(callable(function),'Missing closed source graph descriptor validation')
        return function(manifest)

    def test_missing_dotnet_hook_rejected_for_each_new_source_architecture(self):
        for architecture in ('arm64', 'x64'):
            with self.subTest(architecture=architecture):
                proof=self.source_only(architecture)
                proof['sourceHooks'].pop('dotnetProjectGraph',None)
                with self.assertRaises(ValueError):
                    consumer._source_new_recipe(proof,architecture)

    def test_exact_source_graph_is_common_ordered_and_source_only(self):
        manifest=self.manifest();pins=self.pins(manifest)
        self.assertEqual([row['path'] for row in pins],
            ['solenv/gbuild/DotnetLibrary.mk','solenv/gbuild/DotnetTest.mk'])
        self.assertEqual([(row['size'],row['sha256']) for row in pins],[(5315,
            'f4d2e54af51037267b4027461d7caa6c7a22d3660b99bedeb68f2160d46f476b'),(5154,
            '5391ab97bd1a43c71584afd2819499c1fca75ab95a2e35835dc7e10a02813272')])
        for architecture,guarded_count in (('arm64',13),('x64',4)):
            with self.subTest(architecture=architecture):
                proof=self.source_only(architecture)
                self.assertIsNone(consumer._source_new_recipe(proof,architecture))
                plan=consumer._source_new_plan(manifest,architecture)
                paths=[row['path'] for row in plan['sources']]
                index=paths.index(manifest['flexFatalCompatibility']['path'])
                self.assertEqual(paths[index+1:index+3],[row['path'] for row in pins])
                self.assertEqual(proof['sourceRecipeProof']['hookOrder'][-1],'dotnetProjectGraph')
                self.assertEqual(len(plan['armGuardedSources']),guarded_count)
                for key in profiles.FLAGS:
                    self.assertIs(proof['sourceHooks']['dotnetProjectGraph'][key],False)
                for key in ('passed','phase','status'):
                    self.assertNotIn(key,proof)

    def test_closed_descriptor_rejects_shape_type_core_order_and_duplicate_drift(self):
        original=self.manifest()
        changes=[lambda p:p.pop('windowsDotnetProjectGraph'),
            lambda p:p['windowsDotnetProjectGraph'].update(extra=1),
            lambda p:p['windowsDotnetProjectGraph'].update(schemaVersion=True),
            lambda p:p['windowsDotnetProjectGraph'].update(coreCommit=contracts.LEGACY.core),
            lambda p:p['windowsDotnetProjectGraph'].update(architecture='x64'),
            lambda p:p['windowsDotnetProjectGraph'].update(sources=[]),
            lambda p:p['windowsDotnetProjectGraph'].update(sources=tuple(p['windowsDotnetProjectGraph']['sources'])),
            lambda p:p['windowsDotnetProjectGraph']['sources'].reverse(),
            lambda p:p['windowsDotnetProjectGraph']['sources'].__setitem__(1,copy.deepcopy(p['windowsDotnetProjectGraph']['sources'][0]))]
        for index,change in enumerate(changes):
            with self.subTest(change=index):
                manifest=copy.deepcopy(original);change(manifest)
                with self.assertRaises(ValueError):self.pins(manifest)

    def test_each_original_and_effective_source_field_is_independently_pinned(self):
        original=self.manifest()
        for index in (0,1):
            for field,value in (('path','solenv/gbuild/Other.mk'),('size',True),
                    ('size',1),('sha256','1'*64),('afterSize',True),('afterSize',1),
                    ('afterSha256','2'*64),('extra',0)):
                with self.subTest(source=index,field=field):
                    manifest=copy.deepcopy(original)
                    manifest['windowsDotnetProjectGraph']['sources'][index][field]=value
                    with self.assertRaises(ValueError):self.pins(manifest)
            for field in ('path','size','sha256','afterSize','afterSha256'):
                with self.subTest(source=index,missing=field):
                    manifest=copy.deepcopy(original)
                    manifest['windowsDotnetProjectGraph']['sources'][index].pop(field)
                    with self.assertRaises(ValueError):self.pins(manifest)

    def test_graph_expectations_reject_legacy_and_source_tuple_drift(self):
        expectation=getattr(contracts,'dotnet_project_graph_expectation',None)
        self.assertTrue(callable(expectation),'Missing exact-core graph expectations')
        invalid=[dict(contracts.LEGACY_SOURCE),dict(contracts.NEW_SOURCE,coreCommit='0'*40),
            dict(contracts.NEW_SOURCE,size=True),dict(contracts.NEW_SOURCE,version='26.8.2.1')]
        for index,pin in enumerate(invalid):
            with self.subTest(pin=index),self.assertRaises(ValueError):expectation(pin)

    def test_hook_requires_exact_source_only_schema_core_architecture_and_flags(self):
        changes=[lambda h:h.update(extra=1),lambda h:h.update(schemaVersion=True),
            lambda h:h.update(kind='native-engine-source-build-qualified'),
            lambda h:h.update(coreCommit=contracts.LEGACY.core),
            lambda h:h.update(architecture='ARM64'),lambda h:h.pop('sources'),
            lambda h:h.update(sources=[]),lambda h:h['sources'].reverse(),
            lambda h:h['sources'].__setitem__(1,copy.deepcopy(h['sources'][0]))]
        for field in profiles.FLAGS:
            changes.extend([lambda h,key=field:h.update({key:True}),
                lambda h,key=field:h.update({key:0}),lambda h,key=field:h.pop(key)])
        for architecture in ('arm64','x64'):
            original=self.source_only(architecture)
            for index,change in enumerate(changes):
                with self.subTest(architecture=architecture,change=index):
                    proof=copy.deepcopy(original);change(proof['sourceHooks']['dotnetProjectGraph'])
                    with self.assertRaises(ValueError):consumer._source_new_recipe(proof,architecture)

    def test_hook_rows_cannot_substitute_a_source_or_effective_identity(self):
        for architecture in ('arm64','x64'):
            original=self.source_only(architecture)
            for index in (0,1):
                for field,value in (('path','solenv/gbuild/Other.mk'),('beforeBytes',True),
                        ('afterBytes',True),('beforeSha256','3'*64),('afterSha256','4'*64),('extra',1)):
                    with self.subTest(architecture=architecture,source=index,field=field):
                        proof=copy.deepcopy(original)
                        proof['sourceHooks']['dotnetProjectGraph']['sources'][index][field]=value
                        with self.assertRaises(ValueError):consumer._source_new_recipe(proof,architecture)

    def test_retained_evidence_is_canonical_distinct_and_in_the_original_run_parent(self):
        for architecture in ('arm64','x64'):
            original=self.source_only(architecture)
            for index in (0,1):
                name=('DotnetLibrary.mk','DotnetTest.mk')[index]
                for side in ('original','effective'):
                    values=[profiles.PARENT+'\\other.mk','C:\\other-run\\'+side+'-'+name,
                        profiles.PARENT.upper()+'\\'+side+'-'+name,
                        profiles.PARENT+'\\..\\'+side+'-'+name,
                        (profiles.PARENT+'\\'+side+'-'+name).replace('\\','/'),
                        side+'-'+name]
                    for value in values:
                        with self.subTest(architecture=architecture,source=index,side=side):
                            proof=copy.deepcopy(original)
                            proof['sourceHooks']['dotnetProjectGraph']['sources'][index]['evidence'][side]=value
                            with self.assertRaises(ValueError):consumer._source_new_recipe(proof,architecture)
                for missing in ('original','effective'):
                    with self.subTest(architecture=architecture,source=index,missing=missing):
                        proof=copy.deepcopy(original)
                        proof['sourceHooks']['dotnetProjectGraph']['sources'][index]['evidence'].pop(missing)
                        with self.assertRaises(ValueError):consumer._source_new_recipe(proof,architecture)

    def test_existing_recipe_id_hooks_and_guarded_sources_cannot_be_downgraded(self):
        for architecture in ('arm64','x64'):
            original=self.source_only(architecture)
            for change in (lambda p:p['sourceRecipeProof']['hookOrder'].pop(),
                    lambda p:p['sourceRecipeProof'].update(recipeId='windows-old'),
                    lambda p:p['sourceRecipeProof']['armGuardedSources'].pop(),
                    lambda p:p['sourceRecipeProof'].update(recipeSha256='5'*64)):
                with self.subTest(architecture=architecture):
                    proof=copy.deepcopy(original);change(proof)
                    with self.assertRaises(ValueError):consumer._source_new_recipe(proof,architecture)


if __name__=='__main__':unittest.main()
