"""Source-only 9dea consumer proofs; no qualified receipt, ZIP or adoption."""
import copy
import hashlib
import json
from pathlib import Path, PureWindowsPath
import unittest

from suite import prepare as consumer
from suite.source_contracts import NEW_SOURCE, LEGACY_SOURCE, new_source_only_expectations

ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/'suite/engine-build/source-build.26.8.2.2.json'
MANIFEST_SHA='9bf183e354ee1f68158233bad959ac8a756c3e667cb0892760b98c44aabb8e50'
PARENT='C:\\build\\evidence\\source-recipe'
FLAGS=dict(nativeBuildVerified=False,fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)


def evidence(names,parent=PARENT):
    return {key:str(PureWindowsPath(parent)/name) for key,name in names.items()}


class PrepareSourceProfileV2Tests(unittest.TestCase):
    def require(self,name):
        value=getattr(consumer,name,None)
        self.assertTrue(callable(value),'Missing preparatory source-profile consumer API')
        return value

    def manifest(self):
        self.assertTrue(MANIFEST.is_file(),'Missing independently reviewed per-core manifest')
        return json.loads(MANIFEST.read_bytes())

    def source_only(self,architecture):
        manifest=self.manifest();expected=new_source_only_expectations(dict(NEW_SOURCE),architecture)
        plan=self.require('_source_new_plan')(manifest,architecture)
        recipe=dict(expected.recipe_fields);recipe['hookOrder']=list(expected.hooks)
        recipe['armGuardedSources']=[dict(path=row['path'],beforeSha256=row['beforeSha256'],
            sha256=row['beforeSha256'] if architecture=='x64' else row['afterSha256'],unchanged=architecture=='x64')
            for row in plan['armGuardedSources']]
        bootstrap=manifest['moduleBootstrap']
        hooks=dict(architecture=architecture,nativeBuildVerified=False,basePersistenceVerified=False,
            moduleBootstrap=dict(path=bootstrap['path'],beforeSha256=bootstrap['sha256'],afterSha256=bootstrap['afterSha256'],
                evidence=evidence(dict(original='original-unpack-sources',effective='effective-unpack-sources'))))
        if architecture=='x64':
            hooks['kind']='native-windows-common-source-hooks'
            for field,pin_name,kind in (
                    ('firebirdLoaderPath','windowsFirebirdLoaderPath','windows-firebird-loader-path-source-hook'),
                    ('zstdSourceLinks','windowsZstdSourceLinks','windows-zstd-source-links-source-hook'),
                    ('gpgBuildCompilerPath','windowsGpgBuildCompilerPath','windows-gpg-build-compiler-path-source-hook'),
                    ('harfbuzzNativeMesonPaths','windowsHarfbuzzNativeMesonPaths','windows-x64-harfbuzz-native-meson-source-hook'),
                    ('cliPublisherPolicyPlatform','windowsCliPublisherPolicyPlatform','windows-x64-cli-publisher-policy-platform-source-hook')):
                pin=manifest[pin_name]
                hooks[field]=dict(schemaVersion=1,kind=kind,path=pin['path'],condition=pin['condition'],
                    beforeBytes=pin['size'],afterBytes=pin['afterSize'],beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'],
                    evidence=evidence({side:side+'-x64-'+pin['path'].rsplit('/',1)[-1] for side in ('original','effective')}),**FLAGS)
            rows=[]
            for index,pin in enumerate(consumer._source_x64_atl_pins(manifest),1):
                rows.append(dict(path=pin['path'],beforeBytes=pin['size'],afterBytes=pin['afterSize'],
                    beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'],
                    evidence=evidence({side:side+'-x64-atl-'+format(index,'02d')+'-'+pin['path'].rsplit('/',1)[-1] for side in ('original','effective')})))
            hooks['atlNativePaths']=dict(schemaVersion=1,kind='windows-x64-native-atl-source-hooks',
                condition='WNT_X86_64_MSC && MAKE_HOST=%-cygwin',recipes=rows,**FLAGS)
        else:
            hooks.update(schemaVersion=1,status='source-hook-installed-native-build-pending',
                libreofficeVersion='26.8.2.2',firebirdVersion='3.0.14.33856-0',
                sourceHook=manifest['sourceHook']['path'],beforeSha256=manifest['sourceHook']['sha256'],afterSha256=manifest['sourceHook']['afterSha256'],
                portPatchSha256=manifest['portPatch']['sha256'],configurePatchSha256=manifest['configurePatch']['sha256'],
                configureBeforeSha256=manifest['configureSource']['sha256'],configureAfterSha256=manifest['configureSource']['afterSha256'])
            for field in ('icuBuildPath','zstdSourceLinks','mddsEquality','pythonNativeHost','atlNativePaths','harfbuzzNativeMesonPaths'):
                config=manifest[field];pin=config.get('recipe',config)
                value=dict(path=pin['path'],beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'],
                    evidence=evidence({side:side+'-'+pin['path'].rsplit('/',1)[-1] for side in ('original','effective')}))
                if 'scope' in config:value['scope']=config['scope']
                if field=='zstdSourceLinks':value['archive']=config['archive']
                if field=='mddsEquality':value.update(patchSha256=config['patch']['sha256'],upstreamPatchSha256=config['upstreamPatch']['sha256'])
                if field=='pythonNativeHost':
                    value.update(targetsSha256=config['targets']['sha256'],targetsPath='C:\\build\\source\\external\\python3\\opengeul-native-arm64-tools.targets')
                    value['evidence']['targets']=PARENT+'\\effective-opengeul-native-arm64-tools.targets'
                hooks[field]=value
            hooks['atlConsumerNativePaths']=dict(scope=manifest['atlConsumerNativePaths']['scope'],recipes=[
                dict(path=pin['path'],beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'],
                    evidence=evidence({side:side+'-'+pin['path'].rsplit('/',1)[-1] for side in ('original','effective')}))
                for pin in manifest['atlConsumerNativePaths']['recipes']])
        graph=manifest['windowsDotnetProjectGraph']
        hooks['dotnetProjectGraph']=dict(schemaVersion=1,kind='windows-dotnet-project-graph-source-hook',
            coreCommit=graph['coreCommit'],architecture=architecture,sources=[
                dict(path=pin['path'],beforeBytes=pin['size'],afterBytes=pin['afterSize'],
                    beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'],
                    evidence=evidence({side:side+'-'+pin['path'].rsplit('/',1)[-1] for side in ('original','effective')}))
                for pin in graph['sources']],**FLAGS)
        pin=manifest['winAccFocusOrder'];winacc=dict(expected.winacc_fields)
        winacc['sourceFiles']=[dict(path=row['path'],beforeBytes=row['size'],
            afterBytes=pin['afterBytes'] if row['path']==pin['path'] else row['size'],beforeSha256=row['sha256'],
            afterSha256=pin['afterSha256'] if row['path']==pin['path'] else row['sha256']) for row in pin['sources']]
        winacc['evidence']=evidence(dict(original='original-AccObjectWinManager.cxx',effective='effective-AccObjectWinManager.cxx',patch='winacc-focus-order.patch'))
        flex=dict(expected.flex_fields);flex['evidence']=evidence({side:side+'-'+architecture+'-sqlflex.l' for side in ('original','effective')})
        return dict(sourcePin=dict(NEW_SOURCE),sourcePortManifestSha256=MANIFEST_SHA,
            nativeTargetsSha256=expected.native_targets_sha256,sourceRecipeProof=recipe,
            sourceHooks=hooks,winAccFocusOrderSourcePatch=winacc,flexFatalCompatibilitySourcePatch=flex)

    def check(self,proof,architecture):
        return self.require('_source_new_recipe')(proof,architecture)

    def test_new_manifest_is_exact_authenticated_producer_snapshot(self):
        self.manifest();self.assertEqual(hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),MANIFEST_SHA)

    def test_both_canonical_plans_and_source_only_proofs(self):
        for architecture,count,guards,digest in [('arm64',20,13,'9b10511f31066a5966014c6357268b4d1dcfa3ffa24eb9c97c8bc0c05dbef0fe'),
                ('x64',22,4,'66704ff304812a3181912c38723e4d0333670055dbb0c879e46fcc1ea961324d')]:
            with self.subTest(architecture=architecture):
                plan=self.require('_source_new_plan')(self.manifest(),architecture)
                self.assertEqual((len(plan['sources']),len(plan['armGuardedSources'])),(count,guards))
                self.assertEqual(hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest(),digest)
                proof=self.source_only(architecture);before=copy.deepcopy(proof)
                self.assertIsNone(self.check(proof,architecture));self.assertEqual(proof,before)
                self.assertNotIn('artifact',proof);self.assertNotIn('Full',proof.values())

    def test_new_core_profile_and_manifest_cannot_be_relabelled(self):
        proof=self.source_only('arm64')
        for field,value in [('version','26.8.1.1'),('coreCommit',LEGACY_SOURCE['coreCommit']),('size',1),('sha256','0'*64),('url','https://example.invalid/source')]:
            row=copy.deepcopy(proof);row['sourcePin'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.check(row,'arm64')
        for field in ('sourcePortManifestSha256','nativeTargetsSha256'):
            row=copy.deepcopy(proof);row[field]='0'*64
            with self.assertRaises(ValueError):self.check(row,'arm64')

    def test_recipe_rows_order_hook_order_and_typed_false_flags_are_closed(self):
        for architecture in ('arm64','x64'):
            proof=self.source_only(architecture)
            for change in (lambda p:p.pop('sourceRecipeProof'),lambda p:p['sourceRecipeProof'].update(recipeSha256='0'*64),
                    lambda p:p['sourceRecipeProof']['armGuardedSources'].reverse(),lambda p:p['sourceRecipeProof']['hookOrder'].pop(),
                    lambda p:p['sourceRecipeProof'].update(nativeBuildVerified=0),lambda p:p['sourceRecipeProof'].update(acceptanceEligible=True),
                    lambda p:p['sourceRecipeProof']['armGuardedSources'][0].update(unchanged=1),lambda p:p['sourceRecipeProof'].update(extra=False)):
                row=copy.deepcopy(proof);change(row)
                with self.assertRaises(ValueError):self.check(row,architecture)

    def test_flex_winacc_and_cli_are_source_only_and_same_run(self):
        for architecture in ('arm64','x64'):
            proof=self.source_only(architecture)
            changes=[lambda p:p.pop('flexFatalCompatibilitySourcePatch'),lambda p:p.pop('winAccFocusOrderSourcePatch'),
                lambda p:p['flexFatalCompatibilitySourcePatch'].update(nativeBuildVerified=True),
                lambda p:p['flexFatalCompatibilitySourcePatch'].update(architecture='other'),
                lambda p:p['winAccFocusOrderSourcePatch'].update(currentCiRootCauseConfirmed=True),
                lambda p:p['winAccFocusOrderSourcePatch']['sourceFiles'][0].update(afterSha256='0'*64),
                lambda p:p['flexFatalCompatibilitySourcePatch']['evidence'].update(original='C:\\other\\original-'+architecture+'-sqlflex.l'),
                lambda p:p['winAccFocusOrderSourcePatch']['evidence'].update(patch='C:\\other\\winacc-focus-order.patch')]
            if architecture=='x64':changes += [lambda p:p['sourceHooks'].pop('cliPublisherPolicyPlatform'),
                lambda p:p['sourceHooks']['cliPublisherPolicyPlatform'].update(guiVerified=0),
                lambda p:p['sourceHooks']['cliPublisherPolicyPlatform']['evidence'].update(effective='C:\\other\\effective-x64-CliNativeLibrary_cli_cppuhelper.mk')]
            for change in changes:
                row=copy.deepcopy(proof);change(row)
                with self.assertRaises(ValueError):self.check(row,architecture)

    def test_noncanonical_relative_unc_alias_and_extra_descriptor_are_rejected(self):
        proof=self.source_only('arm64')
        for path in ('relative\\original-arm64-sqlflex.l','\\\\host\\share\\original-arm64-sqlflex.l',
                'C:\\build\\evidence\\source-recipe\\..\\source-recipe\\original-arm64-sqlflex.l',
                'C:/build/evidence/source-recipe/original-arm64-sqlflex.l',
                'C:\\BUILD\\evidence\\source-recipe\\original-arm64-sqlflex.l'):
            row=copy.deepcopy(proof);row['flexFatalCompatibilitySourcePatch']['evidence']['original']=path
            with self.subTest(pathKind=path[:2]),self.assertRaises(ValueError):self.check(row,'arm64')
        row=copy.deepcopy(proof);row['flexFatalCompatibilitySourcePatch']['evidence']['extra']='C:\\unknown'
        with self.assertRaises(ValueError):self.check(row,'arm64')

    def test_real_arm_nested_hooks_are_required_source_bound_and_same_run(self):
        proof=self.source_only('arm64')
        fields=('icuBuildPath','zstdSourceLinks','mddsEquality','pythonNativeHost','atlNativePaths','atlConsumerNativePaths','harfbuzzNativeMesonPaths')
        for field in fields:
            row=copy.deepcopy(proof);row['sourceHooks'].pop(field)
            with self.subTest(field=field,kind='missing'),self.assertRaises(ValueError):self.check(row,'arm64')
            for kind in ('foreign-parent','pin'):
                row=copy.deepcopy(proof);hook=row['sourceHooks'][field]
                if field=='atlConsumerNativePaths':hook=hook['recipes'][0]
                if kind=='pin':hook['afterSha256']='0'*64
                else:hook['evidence']['original']='C:\\other\\'+PureWindowsPath(hook['evidence']['original']).name
                with self.subTest(field=field,kind=kind),self.assertRaises(ValueError):self.check(row,'arm64')

    def test_real_arm_top_fields_and_native_targets_descriptor_are_closed(self):
        proof=self.source_only('arm64')
        for field in ('portPatchSha256','configurePatchSha256','configureBeforeSha256','configureAfterSha256'):
            row=copy.deepcopy(proof);row['sourceHooks'][field]='0'*64
            with self.subTest(field=field),self.assertRaises(ValueError):self.check(row,'arm64')
        for path in ('relative','C:\\build\\source\\external\\python3\\wrong.targets','C:\\build\\evidence\\source-recipe\\external\\python3\\opengeul-native-arm64-tools.targets'):
            row=copy.deepcopy(proof);row['sourceHooks']['pythonNativeHost']['targetsPath']=path
            with self.assertRaises(ValueError):self.check(row,'arm64')

    def test_new_python_foreign_family_is_source_bound_and_old_default_unchanged(self):
        old=consumer._source_python_templates()
        try:templates=consumer._source_python_templates(dict(sourcePin=dict(NEW_SOURCE)))
        except TypeError:self.fail('Missing source-bound Python17 inventory selector')
        self.assertEqual(len(templates),10);self.assertTrue(all('python-core-3.13.17/' in key for key in templates))
        self.assertTrue(all(pin['machine']!=0x8664 for pin in templates.values()))
        self.assertEqual(consumer._source_python_templates(),old)
        with self.assertRaises(ValueError):consumer._source_python_templates(dict(sourcePin=dict(NEW_SOURCE)|dict(sha256='0'*64)))

    def test_fallback_identity_uses_exact_new_source_and_build2_formula(self):
        core=NEW_SOURCE['coreCommit'];config=dict(LIBO_VERSION_MAJOR='26',LIBO_VERSION_MINOR='8',LIBO_VERSION_MICRO='2',LIBO_VERSION_PATCH='2',LIBO_VERSION_SUFFIX='')
        reference=dict(path='C:\\evidence\\installed-stage.json',bytes=100,sha256='d'*64)
        files={name:dict(originalBuildId='680(Build:2)',buildid=core,corrected=True,beforeSha256='1'*64,sha256='2'*64) for name in ('program/version.ini','program/setup.ini')}
        identity=dict(schemaVersion=1,mechanism='explicit-generated-config-correction-from-authenticated-source-pin',expectedBuildId=core,
            sourceArchiveUrl=NEW_SOURCE['url'],sourceArchiveSha256=NEW_SOURCE['sha256'],sourceArchiveSize=NEW_SOURCE['size'],identityMode='installed-no-git-fallback',
            files=files,finalVerification=dict(passed=True,expectedBuildId=core,files={key:dict(buildid=core,sha256='2'*64) for key in files}),
            stageReceipt=reference,originals={key:dict(archivePath='C:\\main.zip',archiveMember='wrapper/'+key,bytes=40,sha256='1'*64) for key in files},
            installedFallbackDerivation=dict(rule='libreoffice-26.8.2.2-installer-no-git-v1',configuration=config,build='2680',normalizedBuild='680',installerBuildId='2',buildid='680(Build:2)'))
        proof=dict(sourcePin=dict(NEW_SOURCE),configuration=config,runtimeBuildIdentity=identity,installedRuntimeStage=dict(passed=True,receipt=reference))
        try:value=consumer._source_build_identity(proof,core)
        except ValueError:self.fail('New exact source fallback is unsupported')
        self.assertEqual(value,identity)
        row=copy.deepcopy(proof);row['configuration']['LIBO_VERSION_PATCH']='1'
        with self.assertRaises(ValueError):consumer._source_build_identity(row,core)

    def test_source_metadata_never_supplies_missing_external_adoption_pins(self):
        runtime=dict(format='source-built-zip',version=NEW_SOURCE['version'],sourceCoreCommit=NEW_SOURCE['coreCommit'],sourceUrl=NEW_SOURCE['url'],sourceSha256=NEW_SOURCE['sha256'])
        for architecture in ('arm64','x64'):
            with self.assertRaises(ValueError):consumer.validate_source_build_lock(runtime,architecture=architecture)


if __name__=='__main__':unittest.main()
