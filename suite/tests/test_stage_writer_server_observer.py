"""Synthetic pinned containers over the real normal ARM fixture; no desktop."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from suite.tests import test_calc_dispatch_integration as calc_fixture
from suite.tests.test_payload import pe

ROOT=Path(__file__).resolve().parents[2]
FAMILY='writer-server-observer-diagnostic'
CORE='9dea406ab7695df6325b11b0e19fdca8db4b7276'


def normal_source_fixture():
    """Synthetic pre-overlay hooks from the current pure source-profile fixture.

    This is not the normal ARM497 producer owner or runtime qualification.
    The diagnostic producer uses the independently pinned254 raw manifest.
    """
    from suite.tests import test_prepare_source_profile_v2 as profiles
    proof=profiles.PrepareSourceProfileV2Tests().source_only('arm64')
    keys=('sourcePin','sourcePortManifestSha256','nativeTargetsSha256','sourceRecipeProof',
        'sourceHooks','winAccFocusOrderSourcePatch','flexFatalCompatibilitySourcePatch')
    proof={key:proof[key] for key in keys}
    proof['sourcePortManifestSha256']='37fba766084127e2fdf2f51c3108290a39ddfdaa895af03c68d3cfc8b35d2020'
    proof['sourceRecipeProof']['manifestSha256']=proof['sourcePortManifestSha256']
    return proof


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module);return module


def sha(raw):return hashlib.sha256(raw).hexdigest()


class WriterStageTests(unittest.TestCase):
    def setUp(self):
        path=ROOT/'suite/scripts/stage-writer-server-observer.py'
        self.assertTrue(path.is_file(),'Writer consumer stage is missing')
        self.m=load('writer_stage_contract',path)
        self.old=calc_fixture.ArtifactTests();self.old.setUp();self.addCleanup(self.old.doCleanups)
        self.base=self.old.f.root;self.output=self.base.parent/'writer-output'
        self.archive=self.base.parent/'OpenGeul-Office-engine-arm64-writer-server-observer.zip'
        self.receipt=self.base.parent/'writer-server-observer-source-build-receipt.json'
        self.artifact=self.base.parent/'github-artifact.zip'
        self.source_lock=self.base.parent/'source-lock.json';self.lock_file=self.base.parent/'writer-input.json'
        package=ROOT/'suite/config/writer-server-observer-9dea'
        self.assertTrue(package.is_dir(),'Writer source package is missing from this checkout')
        self.source_lock.write_bytes((package/'source-lock.json').read_bytes());self.source=json.loads(self.source_lock.read_bytes())
        self.entries=dict(self.old.entries);self.entries.pop(self.old.m.MARKER)
        binaries=[]
        for path in ('program/UAccCOM.dll','program/winaccessibility.dll'):
            self.entries[path]=pe(0xaa64,dll=True)
            binaries.append(dict(path=path,bytes=len(self.entries[path]),sha256=sha(self.entries[path]),machine=0xaa64))
        self.marker=dict(schemaVersion=1,family=FAMILY,kind=FAMILY,sourceCommit='b'*40,sourceTree='d'*40,sourceRun=123,runAttempt=1,coreCommit=CORE,
            sourceLockSha256=sha(self.source_lock.read_bytes()),patchSha256=self.source['patch']['sha256'],wireSchema=self.source['wireSchema'],
            descriptorSchemaVersion=1,mappingBytes=131328,ipcVersion=1,sinkAbiVersion=2,requiredRebuiltLibraries=['UAccCOM','winaccessibility'],
            binaries=binaries,fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
        self.hooks=dict(schemaVersion=1,kind=self.source['kind'],passed=True,target='windows-arm64',coreCommit=CORE,
            lockSha256=self.marker['sourceLockSha256'],patch=self.source['patch'],wireSchema=self.source['wireSchema'],
            sources=self.source['sources'],payloads=self.source['payloads'],dependencies=self.source['dependencies'],
            ipcVersion=1,sinkAbiVersion=2,mappingBytes=131328,descriptorSchemaVersion=1,requiredRebuiltLibraries=['UAccCOM','winaccessibility'],
            fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
        self.pack()

    def pack(self):
        raw=json.dumps(self.marker).encode()
        self.entries['writer-server-observer-diagnostic.json']=raw
        self.entries['program/opengeul-writer-server-observer-diagnostic.json']=raw
        with zipfile.ZipFile(self.archive,'w') as zipped:
            for name,data in self.entries.items():zipped.writestr(name,data)
        self.proof=dict(schemaVersion=1,kind='native-office-engine-writer-server-observer-diagnostic',phase='Full',architecture='arm64',stage='complete',
            status='native-engine-writer-server-observer-diagnostic-built',passed=True,fullEngineQualified=False,acceptanceEligible=False,guiVerified=False,
            sourceCommit='b'*40,sourceTree='d'*40,sourceRun=123,runAttempt=1,sourceLockSha256=self.marker['sourceLockSha256'],
            host=dict(isWindows=True,processMachine=0,nativeMachine=0xaa64),
            writerServerObserverSourceHooks=self.hooks,writerServerObserverRuntime=self.marker,
            artifact=dict(path='producer-owned',size=self.archive.stat().st_size,sha256=sha(self.archive.read_bytes())))
        self.proof.update(normal_source_fixture())
        self.receipt.write_text(json.dumps(self.proof))
        self.repack_outer()

    def repack_outer(self):
        with zipfile.ZipFile(self.artifact,'w') as zipped:
            zipped.write(self.archive,self.archive.name);zipped.write(self.receipt,self.receipt.name)
        self.lock=dict(schemaVersion=1,kind='writer-server-observer-diagnostic-input',architecture='arm64',repository='ATLKR/OpenGeul',repositoryId=1405493151,
            sourceCommit='b'*40,sourceTree='d'*40,runId=123,runAttempt=1,artifactId=456,artifactSha256=sha(self.artifact.read_bytes()),artifactSize=self.artifact.stat().st_size,
            sourceLockSha256=self.marker['sourceLockSha256'],coreCommit=CORE,patchSha256=self.source['patch']['sha256'],wireSchemaSha256=self.source['wireSchema']['sha256'])
        self.lock_file.write_text(json.dumps(self.lock))

    def repack_entries(self,entries):
        with zipfile.ZipFile(self.archive,'w') as zipped:
            for name,data in entries.items():zipped.writestr(name,data)
        self.proof['artifact'].update(size=self.archive.stat().st_size,sha256=sha(self.archive.read_bytes()))
        self.receipt.write_text(json.dumps(self.proof));self.repack_outer()

    def stage(self,**options):
        args=dict(baseline=self.base,artifact=self.artifact,archive=self.archive,receipt=self.receipt,source_lock=self.source_lock,
            diagnostic_lock=self.lock_file,output=self.output,expected_suite_source_commit='a'*40)
        return self.m.stage(**{**args,**options})

    def require(self,**options):
        args=dict(output=self.output,baseline=self.base,artifact=self.artifact,diagnostic_lock=self.lock_file,source_lock=self.source_lock,
            expected_suite_source_commit='a'*40)
        return self.m.require_writer_observer_stage(**{**args,**options})

    def test_real_staging_preserves_normal_baseline_and_never_has_normal_inventory(self):
        before=self.m.payload._scan(self.base)
        self.stage();ready=self.require()
        self.assertEqual(before,self.m.payload._scan(self.base))
        for name,record in before.items():
            if not name.startswith('Office/') and name!='suite-inventory.json':
                self.assertEqual(record['sha256'],sha((self.output/name).read_bytes()),name)
        self.assertEqual(self.source_lock.read_bytes(),(self.output/'writer-server-observer-source-lock.json').read_bytes())
        self.assertEqual(self.receipt.read_bytes(),(self.output/'writer-server-observer-source-build-receipt.json').read_bytes())
        for path in ('writer-server-observer-diagnostic.json','program/opengeul-writer-server-observer-diagnostic.json'):
            self.assertEqual(self.entries[path],(self.output/'Office'/path).read_bytes())
        self.assertEqual(ready['sourceTree'],'d'*40);self.assertEqual(ready['mappingBytes'],131328)
        self.assertFalse(ready['acceptanceEligible']);self.assertFalse(ready['fullEngineQualified']);self.assertFalse(ready['guiVerified'])
        with self.assertRaisesRegex(ValueError,'Writer observer diagnostic'):
            self.m.payload.verify_payload(self.output,json.loads((self.output/'suite-inventory.json').read_bytes()))

    def test_new_family_requires_typed_marker_run_and_attempt_and_no_legacy_core(self):
        original=copy.deepcopy(self.marker)
        for key,value in [('sourceRun',None),('sourceRun',True),('sourceRun',124),('runAttempt',True),
                ('runAttempt',2),('coreCommit','bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'),('extra',False)]:
            with self.subTest(field=key):
                self.marker=copy.deepcopy(original)
                if value is None:self.marker.pop(key)
                else:self.marker[key]=value
                self.pack()
                with self.assertRaises(ValueError):self.stage()
                self.assertFalse(self.output.exists())

    def test_preoverlay_recipe_is_exact_diagnostic_source_only_not_normal497_authority(self):
        self.m._normal_source_recipe(self.proof)
        from suite import prepare
        with self.assertRaises(ValueError):prepare._source_new_recipe(self.proof,'arm64')
        original=copy.deepcopy(self.proof)
        changes=[lambda p:p.pop('sourceRecipeProof'),
            lambda p:p['sourceRecipeProof'].update(manifestSha256='9bf'+'0'*61),
            lambda p:p['sourceRecipeProof'].update(recipeSha256='0'*64),
            lambda p:p['sourceRecipeProof']['hookOrder'].reverse(),
            lambda p:p['sourceRecipeProof']['armGuardedSources'][0].update(unchanged=0),
            lambda p:p['sourceRecipeProof'].update(fullEngineQualified=True),
            lambda p:p['sourceHooks']['dotnetProjectGraph']['sources'][0].update(afterSha256='0'*64),
            lambda p:p['sourceHooks']['moduleBootstrap']['evidence'].update(original='C:\\other\\original-unpack-sources'),
            lambda p:p['winAccFocusOrderSourcePatch'].update(beforeFocusBaseline='legacy-bf6'),
            lambda p:p['flexFatalCompatibilitySourcePatch'].update(nativeBuildVerified=True),
            lambda p:p['sourcePin'].update(coreCommit='bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1')]
        for index,change in enumerate(changes):
            with self.subTest(change=index):
                proof=copy.deepcopy(original);change(proof)
                with self.assertRaises(ValueError):self.m._normal_source_recipe(proof)

    def test_source_metadata_has_one_raw_pin_and_cannot_select_another_family(self):
        self.assertEqual(sha(self.source_lock.read_bytes()),self.m.SOURCE_LOCK_SHA256)
        self.assertEqual(self.source['targets'],['windows-arm64'])
        source=copy.deepcopy(self.source);source['targets'].append('windows-x64')
        self.source_lock.write_text(json.dumps(source))
        self.marker['sourceLockSha256']=sha(self.source_lock.read_bytes());self.pack()
        with self.assertRaises(ValueError):self.stage()
        self.assertFalse(self.output.exists())

    def test_preoverlay_check_preserves_original_exception_identity(self):
        for kind in (OSError,TypeError,KeyError,KeyboardInterrupt,SystemExit):
            error=kind()
            def check():raise error
            with self.subTest(kind=kind.__name__),self.assertRaises(kind) as caught:
                self.m._normal_source_recipe(self.proof,check)
            self.assertIs(caught.exception,error)

    def test_new_stage_is_rejected_by_normal_menu_ime_and_launch_before_input(self):
        self.stage()
        layout=self.base.parent/'normal-callers';e2e=layout/'suite/e2e';e2e.mkdir(parents=True)
        shutil.copyfile(ROOT/'suite/payload.py',layout/'suite/payload.py')
        for name in ('windows_smoke.py','korean_ime_smoke.py','native_menu_smoke.py',
                'native_window_evidence.py','ascii_editor_input.py'):
            shutil.copyfile(ROOT/'suite/e2e'/name,e2e/name)
        with patch.object(sys,'path',[str(e2e),str(ROOT/'suite/e2e'),*sys.path]):
            launcher=load('writer9_normal_launcher',e2e/'windows_smoke.py')
            with patch.object(launcher,'prepare_launch_pointer',side_effect=AssertionError('Pointer reached')),\
                    patch.object(launcher.subprocess,'Popen',side_effect=AssertionError('Launch reached')):
                with self.assertRaisesRegex(ValueError,'Writer observer diagnostic'):
                    launcher.launch_suite(['synthetic.exe'],self.output,self.base.parent/'normal-output','synthetic')
            with patch.dict(sys.modules,{'windows_smoke':launcher}):
                modules=[launcher,load('writer9_normal_ime',e2e/'korean_ime_smoke.py'),load('writer9_normal_menu',e2e/'native_menu_smoke.py')]
                for module in modules:
                    args=['--suite',str(self.output)]
                    if module is not modules[1]:args+=['--fixtures',str(self.base.parent/'fixtures'),'--output',str(self.base.parent/'normal-output')]
                    with self.subTest(caller=module.__name__),patch.object(module,'os',SimpleNamespace(name='nt')):
                        with self.assertRaisesRegex(ValueError,'Writer observer diagnostic'):module.main(args)

    def test_unpinned_or_changed_outer_inner_receipt_and_lock_are_rejected(self):
        for target in (self.artifact,self.archive,self.receipt,self.source_lock):
            with self.subTest(name=target.name):
                original=target.read_bytes();target.write_bytes(original+b'changed')
                try:
                    with self.assertRaises(ValueError):self.stage()
                    self.assertFalse(self.output.exists())
                finally:target.write_bytes(original)

    def test_one_dll_overlay_other_architecture_calc_mix_and_tree_mismatch_are_rejected(self):
        original=copy.deepcopy(self.entries)
        for kind in ('overlay','foreign','calc','tree'):
            with self.subTest(kind=kind):
                self.entries=copy.deepcopy(original)
                if kind=='overlay':self.entries['program/UAccCOM.dll']=self.entries['program/UAccCOM.dll'][:-1]+bytes([self.entries['program/UAccCOM.dll'][-1]^1])
                elif kind=='foreign':self.entries['program/UAccCOM.dll']=pe(0x8664,dll=True)
                elif kind=='calc':self.entries['program/opengeul-calc-dispatch-diagnostic.json']=b'{}'
                else:self.marker['sourceTree']='e'*40
                self.pack()
                with self.assertRaises(ValueError):self.stage()
                self.assertFalse(self.output.exists());self.marker['sourceTree']='d'*40

    def test_interruption_has_root_marker_before_executable_extraction(self):
        with patch.object(self.m,'_extract_runtime',side_effect=RuntimeError('synthetic extraction stop')):
            with self.assertRaises(RuntimeError):self.stage()
        self.assertTrue((self.output/'writer-server-observer-diagnostic.json').is_file())
        self.assertFalse(json.loads((self.output/'writer-server-observer-diagnostic.json').read_bytes())['stageComplete'])
        with self.assertRaises(ValueError):self.m.payload.verify_payload(self.output,{})

    def test_require_detects_output_binary_or_baseline_change_and_keeps_original_check_exception(self):
        self.stage();binary=self.output/'Office/program/UAccCOM.dll';original=binary.read_bytes();binary.write_bytes(original+b'overlay')
        with self.assertRaises(ValueError):self.require()
        binary.write_bytes(original)
        class Expired(Exception):pass
        error=Expired()
        def check():raise error
        with self.assertRaises(Expired) as caught:self.require(check=check)
        self.assertIs(caught.exception,error)

    def test_qualification_host_source_and_abi_flags_cannot_self_authorize(self):
        original=copy.deepcopy(self.proof)
        for kind in ('qualified','gui','host','hook-abi','tree'):
            with self.subTest(kind=kind):
                self.proof=copy.deepcopy(original)
                if kind=='qualified':self.proof['fullEngineQualified']=True
                elif kind=='gui':self.proof['guiVerified']=True
                elif kind=='host':self.proof['host']['nativeMachine']=0x8664
                elif kind=='hook-abi':self.proof['writerServerObserverSourceHooks']['sinkAbiVersion']=1
                else:self.proof['sourceTree']='e'*40
                self.receipt.write_text(json.dumps(self.proof));self.repack_outer()
                with self.assertRaises(ValueError):self.stage()
                self.assertFalse(self.output.exists())

    def test_marker_case_alias_traversal_and_file_directory_collision_are_rejected(self):
        original=copy.deepcopy(self.entries)
        for kind in ('alias','traversal','collision'):
            with self.subTest(kind=kind):
                entries=copy.deepcopy(original)
                if kind=='alias':entries['PROGRAM/OPENGEUL-WRITER-SERVER-OBSERVER-DIAGNOSTIC.JSON']=entries.pop('program/opengeul-writer-server-observer-diagnostic.json')
                elif kind=='traversal':entries['../outside.json']=b'{}'
                else:entries['program']=b'collision'
                self.repack_entries(entries)
                with self.assertRaises(ValueError):self.stage()
                self.assertFalse(self.output.exists())

    def test_root_marker_precedes_even_baseline_executable_copy(self):
        def stop(*args,**kwargs):
            self.assertTrue((self.output/'writer-server-observer-diagnostic.json').is_file())
            self.assertFalse((self.output/'OpenGeul.Office.exe').exists())
            raise RuntimeError('synthetic baseline copy stop')
        with patch.object(self.m.shutil,'copytree',side_effect=stop):
            with self.assertRaises(RuntimeError):self.stage()
        self.assertFalse(json.loads((self.output/'writer-server-observer-diagnostic.json').read_bytes())['stageComplete'])

    def test_fresh_outputs_and_mixed_baseline_are_rejected_without_relabeling(self):
        for output in (self.base,self.base/'nested',self.base.parent):
            with self.subTest(output_kind=output.name):
                with self.assertRaises(ValueError):self.stage(output=output)
        self.old.f.write('calc-dispatch-diagnostic.json',b'{}')
        with self.assertRaises(ValueError):self.stage()
        self.assertFalse(self.output.exists())

    def test_marker_removal_or_shell_worker_hwp_delta_cannot_make_a_normal_copy(self):
        self.stage()
        for name in ('worker/session.py','HWP/OpenGeul.exe','OpenGeul.Office.exe'):
            with self.subTest(name=name):
                path=self.output/name;raw=path.read_bytes();path.write_bytes(raw+b'changed')
                with self.assertRaises(ValueError):self.require()
                path.write_bytes(raw)
        (self.output/'writer-server-observer-diagnostic.json').unlink()
        (self.output/'Office/program/opengeul-writer-server-observer-diagnostic.json').unlink()
        with self.assertRaises((ValueError,OSError)):self.require()
        with self.assertRaises(ValueError):self.m.payload.verify_payload(self.output,json.loads((self.output/'suite-inventory.json').read_bytes()))

    def test_same_length_matching_hash_executable_renamed_dll_is_not_native_dll_proof(self):
        entries=copy.deepcopy(self.entries);data=pe(0xaa64,dll=False)
        entries['program/UAccCOM.dll']=data
        self.marker['binaries'][0].update(bytes=len(data),sha256=sha(data))
        raw=json.dumps(self.marker).encode();entries['writer-server-observer-diagnostic.json']=raw;entries['program/opengeul-writer-server-observer-diagnostic.json']=raw
        self.proof['writerServerObserverRuntime']=self.marker
        self.repack_entries(entries)
        with self.assertRaises(ValueError):self.stage()

    def test_original_preparation_check_can_stop_after_root_marker_without_renewal(self):
        class Expired(Exception):pass
        error=Expired()
        def check():
            if (self.output/'writer-server-observer-diagnostic.json').exists():raise error
        with self.assertRaises(Expired) as caught:self.stage(check=check)
        self.assertIs(caught.exception,error)
        self.assertTrue((self.output/'writer-server-observer-diagnostic.json').is_file())
        self.assertFalse((self.output/'Office/program/soffice.bin').exists())

    def test_resealing_self_inventory_cannot_replace_authenticated_office_engine_or_configuration(self):
        self.stage();original_inventory=(self.output/'suite-inventory.json').read_bytes()
        overlay=json.loads((self.output/'writer-server-observer-diagnostic.json').read_bytes())
        for name in ('program/soffice.bin','share/registry/main.xcd','opengeul-branding.json'):
            with self.subTest(name=name):
                target=self.output/'Office'/name;raw=target.read_bytes();target.write_bytes(raw+b'changed')
                resealed=self.m._diagnostic_inventory(self.output,overlay,None)
                (self.output/'suite-inventory.json').write_text(json.dumps(resealed))
                try:
                    with self.assertRaises(ValueError):self.require()
                finally:target.write_bytes(raw);(self.output/'suite-inventory.json').write_bytes(original_inventory)


if __name__=='__main__':unittest.main()
