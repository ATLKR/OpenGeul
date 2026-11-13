"""Portable contracts with an independent compiler-free locked-installer check."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from writer_server_compile_support import compiled_fixture,require_compiler

BACKEND=Path(__file__).resolve().parents[1]/'engine-build/writer-server-observer-diagnostic'


def installer():
    spec=importlib.util.spec_from_file_location('writer_install',BACKEND/'install.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def copy_source(temporary):
    tree=Path(temporary)/'source';shutil.copytree(BACKEND/'tests/upstream',tree);(tree/'include').mkdir()
    return tree


class WireContract(unittest.TestCase):
    def test_missing_or_wrong_wire_cannot_admit_frontend(self):
        self.assertTrue((BACKEND/'wire.h').is_file())
        with compiled_fixture(self,BACKEND/'tests/wire_contract.cpp',includes=[BACKEND]) as image:
            result=image.run();self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),{'identityBytes':128,'controlBytes':128,'rowBytes':64,
                'mappingBytes':131328,'sinkRequestBytes':80,'sinkReplyBytes':32,'descriptorAccepted':1,'malformedRejected':8})


class RecorderContract(unittest.TestCase):
    def test_invalidated_closed_expired_and_holes_never_become_complete(self):
        with compiled_fixture(self,BACKEND/'tests/recorder_contract.cpp',includes=[BACKEND]) as image:
            result=image.run();self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),{'contractsPassed':15})


class SessionContract(unittest.TestCase):
    def test_setup_has_one_winner_and_failed_never_retries(self):
        with compiled_fixture(self,BACKEND/'tests/session_contract.cpp',includes=[BACKEND]) as image:
            result=image.run();self.assertEqual(result.returncode,0,result.stderr)


class SourceInstallContract(unittest.TestCase):
    def test_exact_9dea_arm_only_source_admission(self):
        self.assertTrue((BACKEND/'source-lock.json').is_file(), '9dea source backend is missing')
        module=installer()
        with tempfile.TemporaryDirectory() as temporary:
            tree=copy_source(temporary)
            result=module.install(tree,'windows-arm64','9dea406ab7695df6325b11b0e19fdca8db4b7276')
            self.assertEqual(result['coreCommit'],'9dea406ab7695df6325b11b0e19fdca8db4b7276')
            self.assertEqual(result['target'],'windows-arm64')
            self.assertEqual(result['requiredRebuiltLibraries'],['UAccCOM','winaccessibility'])
            self.assertFalse(result['fullEngineQualified'])
            self.assertFalse(result['acceptanceEligible'])
            self.assertFalse(result['guiVerified'])

    def test_legacy_core_and_x64_reject_before_any_source_or_payload_write(self):
        module=installer()
        for target,core in (('windows-arm64','bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'),
                            ('windows-x64','9dea406ab7695df6325b11b0e19fdca8db4b7276')):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as temporary:
                tree=copy_source(temporary)
                before={str(path.relative_to(tree)):path.read_bytes() for path in tree.rglob('*') if path.is_file()}
                with self.assertRaises(ValueError):module.install(tree,target,core)
                after={str(path.relative_to(tree)):path.read_bytes() for path in tree.rglob('*') if path.is_file()}
                self.assertEqual(after,before)
                self.assertFalse((tree/'include/opengeul_writer_observer').exists())

    def test_actual_normal_arm_recipe_then_single_observer_overlay(self):
        # Explicit authenticated pristine projection; no network or source writes.
        from suite.tests.test_native_source_recipe import load,manifest
        value=os.environ.get('OPENGEUL_NATIVE_SOURCE_RECIPE_SOURCE')
        if not value:
            if os.environ.get('OPENGEUL_NATIVE_SOURCE_RECIPE_REQUIRE_SOURCE')=='1':
                self.fail('Mandatory pristine9 recipe inputs are missing')
            self.skipTest('Explicit pristine9 source projection required')
        recipe=load('apply_native_source');lock=manifest()
        plan=recipe._select_plan(lock,(BACKEND.parent/'native-targets.json').read_bytes(),'arm64')
        observer=json.loads((BACKEND/'source-lock.json').read_bytes())
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'source';source.mkdir();(source/'include').mkdir()
            evidence=Path(temporary)/'recipe';evidence.mkdir()
            for row in plan['sources']+plan['sourceDependencies']:
                raw=recipe._regular(Path(value)/row['path'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(),row['beforeSha256'])
                path=source/row['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            # Byte-compatible observer dependencies/header are immutable closure fixtures.
            for row in observer['sources']+observer['dependencies']:
                path=source/row['path']
                if not path.exists():
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes((BACKEND/'tests/upstream'/row['path']).read_bytes())
            normal=recipe.apply_native_source(source,evidence,architecture='arm64')
            self.assertEqual(normal['sourceRecipeProof']['recipeSha256'],'9b10511f31066a5966014c6357268b4d1dcfa3ffa24eb9c97c8bc0c05dbef0fe')
            self.assertEqual(normal['sourceRecipeProof']['hookOrder'],['arm64Full','winAccFocusOrder','flexFatalCompatibility','dotnetProjectGraph'])
            normal_evidence={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in evidence.iterdir() if p.is_file()}
            for row in observer['sources']:
                self.assertEqual(hashlib.sha256((source/row['path']).read_bytes()).hexdigest(),row['before']['sha256'])
            proof=installer().install(source,'windows-arm64','9dea406ab7695df6325b11b0e19fdca8db4b7276')
            self.assertFalse(proof['fullEngineQualified'])
            for row in observer['sources']:
                self.assertEqual(hashlib.sha256((source/row['path']).read_bytes()).hexdigest(),row['after']['sha256'])
            self.assertEqual(normal_evidence,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in evidence.iterdir() if p.is_file()})
            # A repeated observer installation must reject rather than reapply.
            with self.assertRaises(ValueError):installer().install(source,'windows-arm64')

    def test_source_lock_cannot_widen_the_dedicated_target_family(self):
        module=installer()
        with tempfile.TemporaryDirectory() as temporary:
            tree=copy_source(temporary);package=Path(temporary)/'package'
            shutil.copytree(BACKEND,package)
            path=package/'source-lock.json';lock=json.loads(path.read_bytes())
            lock['targets']=['windows-arm64','windows-x64'];path.write_text(json.dumps(lock))
            before={str(p.relative_to(tree)):p.read_bytes() for p in tree.rglob('*') if p.is_file()}
            with self.assertRaises(ValueError):module.install(tree,'windows-arm64',package=package)
            self.assertEqual(before,{str(p.relative_to(tree)):p.read_bytes() for p in tree.rglob('*') if p.is_file()})

    def test_python_source_lock_rejects_tamper_before_any_write(self):
        module=installer();lock=json.loads((BACKEND/'source-lock.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            tree=copy_source(temporary)
            originals={item['path']:(tree/item['path']).read_bytes() for item in lock['sources']}
            target=tree/lock['sources'][0]['path'];target.write_bytes(target.read_bytes()+b'bad')
            with self.assertRaises(ValueError):module.install(tree,'windows-arm64')
            for name,raw in originals.items():
                if name!=lock['sources'][0]['path']:self.assertEqual((tree/name).read_bytes(),raw)
            target.write_bytes(originals[lock['sources'][0]['path']]);result=module.install(tree,'windows-arm64')
            self.assertFalse(result['acceptanceEligible']);self.assertFalse(result['fullEngineQualified'])
            self.assertEqual(result['requiredRebuiltLibraries'],['UAccCOM','winaccessibility'])
            for item in lock['sources']:
                self.assertEqual(hashlib.sha256((tree/item['path']).read_bytes()).hexdigest(),item['after']['sha256'])

    def test_link_added_at_write_open_is_rejected_before_source_or_payload_write(self):
        module=installer();lock=json.loads((BACKEND/'source-lock.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            tree=copy_source(temporary);target=tree/lock['sources'][0]['path'];alias=Path(temporary)/'alias'
            before={item['path']:hashlib.sha256((tree/item['path']).read_bytes()).hexdigest() for item in lock['sources']}
            try:os.link(target,alias);alias.unlink()
            except OSError as error:self.skipTest('Hardlink fixture unavailable: '+type(error).__name__)
            original_open=Path.open
            def raced_open(path,mode='r',*args,**kwargs):
                if path==target and mode=='r+b' and not alias.exists():os.link(target,alias)
                return original_open(path,mode,*args,**kwargs)
            with patch.object(Path,'open',raced_open):
                with self.assertRaises(ValueError):module.install(tree,'windows-arm64')
            for name,digest in before.items():self.assertEqual(hashlib.sha256((tree/name).read_bytes()).hexdigest(),digest,'Aliased source was modified before rejection')
            self.assertFalse((tree/'include/opengeul_writer_observer').exists())

    def test_installed_methods_preserve_original_behavior_and_callback_contract(self):
        require_compiler()
        from source_behavior_fixture import exercise_patched_source,exercise_private_header,exercise_route_methods,exercise_map_deletion
        with tempfile.TemporaryDirectory() as temporary:
            tree=copy_source(temporary);installer().install(tree,'windows-arm64')
            for exercise in (exercise_patched_source,exercise_route_methods,exercise_map_deletion):exercise(self,tree,BACKEND/'tests/upstream')
            exercise_private_header(self,tree)


class CompilerMacroContract(unittest.TestCase):
    def test_fake_sdk_preserves_a_compiler_defined_calling_convention(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);include=root/'include/opengeul_writer_observer';include.mkdir(parents=True)
            shutil.copyfile(BACKEND/'wire.h',include/'wire.h')
            source=root/'macro.cpp'
            source.write_text('#include <string_view>\n#ifdef __cdecl\n#undef __cdecl\n#endif\n'
                '#define __cdecl __attribute__((used))\n#include <windows.h>\n'
                '#define STRINGIFY_I(x) #x\n#define STRINGIFY(x) STRINGIFY_I(x)\n'
                'static_assert(std::string_view(STRINGIFY(__cdecl))=="__attribute__((used))");\nint main(){}\n')
            with compiled_fixture(self,source,includes=[BACKEND/'tests/fake_sdk',root/'include']) as image:
                self.assertEqual(image.run().returncode,0)


class NativeBoundaryContract(unittest.TestCase):
    def test_actual_native_session_rejects_prearm_pin_failure_and_dead_controller(self):
        require_compiler()
        with tempfile.TemporaryDirectory() as temporary:
            temp=Path(temporary);include=temp/'include/opengeul_writer_observer';include.mkdir(parents=True)
            for name in ('wire.h','atomic.h','descriptor.h','private_sink.hxx','recorder.h','session.h','observer_api.hxx'):shutil.copyfile(BACKEND/name,include/name)
            with compiled_fixture(self,BACKEND/'tests/native_contract.cpp',includes=[BACKEND/'tests/fake_sdk',temp/'include',BACKEND],
                    extra_flags=['-D_WIN32','-D_WIN64','-DOPENGEUL_WRITER_SERVER_OBSERVER_DIAGNOSTIC']) as image:
                for mode in (0,1,2,3,4):
                    result=image.run(input=str(mode));self.assertEqual(result.returncode,0,result.stderr)


class ActiveCleanupContract(unittest.TestCase):
    def test_forced_real_enter_leave_contention_is_bounded_and_never_fakes_active_zero(self):
        require_compiler()
        with tempfile.TemporaryDirectory() as temporary:
            temp=Path(temporary);include=temp/'include/opengeul_writer_observer';include.mkdir(parents=True)
            for name in ('wire.h','atomic.h','descriptor.h','private_sink.hxx','recorder.h','session.h','observer_api.hxx'):shutil.copyfile(BACKEND/name,include/name)
            with compiled_fixture(self,BACKEND/'tests/cleanup_contention.cpp',includes=[BACKEND/'tests/fake_sdk',temp/'include'],
                    extra_flags=['-D_WIN32','-D_WIN64','-DOPENGEUL_WRITER_SERVER_OBSERVER_DIAGNOSTIC']) as image:
                result=image.run(seconds=15);self.assertEqual(result.returncode,0,'cleanup exceeded32CAS or failed to preserve incomplete/nonzeroactive')


class AdmissionContentionContract(unittest.TestCase):
    def test_open_gate_contention_loss_remains_incomplete_after_other_scopes_exit(self):
        require_compiler()
        with tempfile.TemporaryDirectory() as temporary:
            temp=Path(temporary);include=temp/'include/opengeul_writer_observer';include.mkdir(parents=True)
            for name in ('wire.h','atomic.h','descriptor.h','private_sink.hxx','recorder.h','session.h','observer_api.hxx'):shutil.copyfile(BACKEND/name,include/name)
            with compiled_fixture(self,BACKEND/'tests/admission_contention.cpp',includes=[BACKEND/'tests/fake_sdk',temp/'include'],
                    extra_flags=['-D_WIN32','-D_WIN64','-DOPENGEUL_WRITER_SERVER_OBSERVER_DIAGNOSTIC']) as image:
                result=image.run(seconds=15);self.assertEqual(result.returncode,0,'Open-gate CAS exhaustion lost its durable incomplete/dropped evidence')


class CompilerAvailabilityContract(unittest.TestCase):
    def test_missing_compiler_is_explicit_skip_and_fallback_is_selected(self):
        with patch('writer_server_compile_support.shutil.which',return_value=None):
            with self.assertRaises(unittest.SkipTest):require_compiler()
            suite=unittest.TestSuite([SourceInstallContract('test_python_source_lock_rejects_tamper_before_any_write'),
                WireContract('test_missing_or_wrong_wire_cannot_admit_frontend')])
            result=unittest.TestResult();suite.run(result)
            self.assertEqual((result.testsRun,len(result.errors),len(result.failures),len(result.skipped)),(2,0,0,1))
        with patch('writer_server_compile_support.shutil.which',side_effect=lambda name:'/synthetic/g++' if name=='g++' else None):
            self.assertEqual(require_compiler(),'/synthetic/g++')


if __name__=='__main__':unittest.main()
