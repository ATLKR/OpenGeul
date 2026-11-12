import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime import bounded,fixture,controller
s=importlib.util.spec_from_file_location('owned_fake_runtime',ROOT/'tests/test_runtime.py');fake=importlib.util.module_from_spec(s);s.loader.exec_module(fake)

class BoundaryTests(unittest.TestCase):
    def test_unknown_environment_is_rejected_before_any_launch(self):
        clock=fake.Clock();api=fake.FakeApi(clock,True,False)
        state=bounded.Runner(api,clock=clock,pause=clock.pause).run([(['owned.exe'],'owned',{'GH_TOKEN':'SYNTHETIC'})],3.)
        self.assertFalse(state['completed']);self.assertEqual(api.count,0)
    def test_late_cleanup_cannot_relabel_a_phase_as_completed(self):
        clock=fake.Clock()
        class Late(fake.FakeApi):
            def state(self,h):
                clock.now+=.75
                return super().state(h)
        api=Late(clock,False,True)
        state=bounded.Runner(api,clock=clock,pause=clock.pause).run([(['owned.exe'],'owned',fake.explicit_environment(bounded))],3.)
        self.assertFalse(state['completed']);self.assertFalse(state['cleanupProved'])
    def test_foreign_generation_cannot_be_replaced_by_same_pid(self):
        clock=fake.Clock()
        class Foreign(fake.FakeApi):
            def identity(self,h):return (999,999) if h!=99 else (100,101)
        api=Foreign(clock,True,False)
        state=bounded.Runner(api,clock=clock,pause=clock.pause).run([(['owned.exe'],'owned',fake.explicit_environment(bounded))],3.)
        self.assertFalse(state['completed'])
    def test_controller_retained_handle_on_failed_admission_is_closed(self):
        clock=fake.Clock()
        class Partial(fake.FakeApi):
            def retain_current_controller(self):
                e=bounded.ProbeFailure(14);e.retained_handle=99;raise e
        api=Partial(clock,True,False)
        state=bounded.Runner(api,clock=clock,pause=clock.pause).run([(['owned.exe'],'owned',fake.explicit_environment(bounded))],3.)
        self.assertFalse(state['completed']);self.assertIn(99,api.closed)
    def test_sdk_private_env_is_the_only_native_snapshot_adaptation(self):
        original=(ROOT/'runtime/native_snapshot.py').read_text();adapted=(ROOT/'runtime/sdk_win32.py').read_text()
        start=original.index('_ENV_KEYS =');end=original.index('\n\n\nclass FailureCode',start)
        other_start=adapted.index('_ENV_KEYS =');other_end=adapted.index('\n\n\nclass FailureCode',other_start)
        extra="        if name.casefold() in _ENV_FALSE_KEYS and value != 'false':\n            raise NativeCallError(FailureCode.INVALID_INPUT)\n"
        missing="    if not _ENV_FALSE_KEYS <= folded:\n        raise NativeCallError(FailureCode.INVALID_INPUT)\n"
        normalized=adapted[:other_start]+adapted[other_end:]
        self.assertEqual(normalized.count(extra),1);self.assertEqual(normalized.count(missing),1)
        self.assertEqual(original[:start]+original[end:],normalized.replace(extra,'').replace(missing,''))
        from runtime import sdk_win32,native_snapshot
        self.assertEqual(sdk_win32._environment_block(fake.explicit_environment(bounded))[-1],0)
        with self.assertRaises(native_snapshot.NativeCallError):native_snapshot._environment_block({'DOTNET_CLI_HOME':'synthetic'})
        with self.assertRaises(sdk_win32.NativeCallError):sdk_win32._environment_block({'GH_TOKEN':'SYNTHETIC'})
    def test_renderer_uses_original_framework_and_isolated_owned_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root=fixture.render(Path(td)/'candidate','candidate','10.0.404',Path(td)/'SDK',ROOT)
            for name in fixture.NAMES:
                p=ET.fromstring((root/'DotnetLibrary'/name/(name+'.csproj')).read_bytes())
                self.assertEqual(p.findtext('PropertyGroup/TargetFramework'),'netstandard2.0')
                self.assertEqual(p.findtext('PropertyGroup/BuildProjectReferences'),'false')
                self.assertEqual(p.findtext('PropertyGroup/OutputPath'),root.as_posix()+'/DotnetLibrary/'+name+'/')
            config=ET.fromstring((root/'NuGet.Config').read_bytes())
            self.assertEqual([x.attrib['value'] for x in config.findall('packageSources/add')],['https://api.nuget.org/v3/index.json'])
            self.assertIsNone(config.find('packageSourceCredentials'))
            self.assertTrue((root/'DiagnosticPackage/DiagnosticPackage.csproj').is_file())
    def test_baseline_does_not_silently_receive_candidate_properties(self):
        with tempfile.TemporaryDirectory() as td:
            root=fixture.render(Path(td)/'baseline','baseline','10.0.404',Path(td)/'SDK',ROOT)
            for name in fixture.NAMES:
                p=ET.fromstring((root/'DotnetLibrary'/name/(name+'.csproj')).read_bytes())
                self.assertIsNone(p.find('PropertyGroup/BuildProjectReferences'))
                self.assertIsNone(p.find('PropertyGroup/OutputPath'))
    def test_pinned_sources_reject_mutation_before_render(self):
        import shutil
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);assets=root/'assets';assets.mkdir()
            manifest=json.loads((ROOT/'asset-pins.json').read_bytes())
            shutil.copy2(ROOT/'asset-pins.json',assets/'asset-pins.json')
            for item in manifest['files']:
                target=assets/item['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/item['path'],target)
            p=assets/'source-snapshot/solenv/gbuild/DotnetLibrary.mk';p.write_bytes(p.read_bytes()+b'\n')
            with self.assertRaises(bounded.ProbeFailure):fixture.verify_assets(assets)
            self.assertFalse((root/'rendered').exists())
    def test_alias_and_unsafe_path_fail_before_filesystem_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'owned').mkdir();(root/'alias').symlink_to(root/'owned',target_is_directory=True)
            with self.assertRaises(bounded.ProbeFailure):fixture.safe_path(root/'alias/output')
            with self.assertRaises(bounded.ProbeFailure):fixture.safe_path(root/'unsafe;path')
    def package(self,td,*,extra=False,changed=False):
        root=Path(td)
        for name in fixture.NAMES:
            p=root/'DotnetLibrary'/name/(name+'.dll');p.parent.mkdir(parents=True);p.write_bytes(b'owned-synthetic-'+name.encode())
        p=root/'owned-diagnostic.nupkg'
        with zipfile.ZipFile(p,'w') as z:
            for name in fixture.NAMES:
                data=(root/'DotnetLibrary'/name/(name+'.dll')).read_bytes()
                z.writestr('lib/netstandard2.0/'+name+'.dll',data+(b'changed' if changed else b''))
            if extra:z.writestr('lib/netstandard2.0/extra.dll',b'synthetic')
            z.writestr('OpenGeul.Diagnostic.Only.nuspec','<package><metadata><id>OpenGeul.Diagnostic.Only</id><version>0.0.0-diagnostic</version></metadata></package>')
        return p,root
    def test_nuget_requires_all_four_exact_output_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            p,r=self.package(td);self.assertEqual(controller.package_proof(p,r)['dllCount'],4)
    def test_nuget_extra_dll_or_changed_payload_is_rejected(self):
        for extra,changed in ((True,False),(False,True)):
            with tempfile.TemporaryDirectory() as td:
                p,r=self.package(td,extra=extra,changed=changed)
                with self.assertRaises(bounded.ProbeFailure):controller.package_proof(p,r)
    def test_verifier_requires_real_public_api_and_copy_evidence(self):
        v=dict(schemaVersion=1,expectedBase=2,known=1,success=1,errorCode=0,values=[2,4,8,12],publicApi=[1]*4,referenceClosure=[1]*4,copiedReferences=[1]*4)
        self.assertEqual(controller.verifier_record(v,2)['known'],1)
        for key in ('copiedReferences','referenceClosure','publicApi'):
            bad=dict(v);bad[key]=[1,1,1,0]
            with self.assertRaises(bounded.ProbeFailure):controller.verifier_record(bad,2)
        bad=dict(v);bad['known']=True
        with self.assertRaises(bounded.ProbeFailure):controller.verifier_record(bad,2)
    def test_unknown_cli_arguments_do_not_print_their_values(self):
        import contextlib,io
        out=io.StringIO();err=io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):code=controller.main(['--diagnostic-only','--output','unused','--unknown','SYNTHETIC-MUST-NOT-PRINT'])
        self.assertEqual(code,2);self.assertEqual(out.getvalue(),'');self.assertEqual(err.getvalue(),'')
    def test_qualified_engine_flags_are_always_false(self):
        self.assertTrue(controller.receipt_flags())
        self.assertTrue(all(value is False for value in controller.receipt_flags().values()))

    def test_implementation_change_may_reuse_reference_assemblies_but_not_child_compilers(self):
        log={'rootProjectCode':2,'cscStarted':[0,0,0,0,0,0,0],'cscFinished':[0]*7,'cscSucceeded':[0]*7}
        self.assertEqual(controller.compilation_ownership(log),0)
        bad={**log,'cscStarted':[0,1,0,0,0,0,0],'cscFinished':[0,1,0,0,0,0,0],'cscSucceeded':[0,1,0,0,0,0,0]}
        with self.assertRaises(bounded.ProbeFailure):controller.compilation_ownership(bad)

    def test_explicit_admission_uses_only_a_synthetic_environment_mapping(self):
        from unittest.mock import patch
        good={'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_REPOSITORY_ID':'1405493151','GITHUB_REPOSITORY_OWNER':'ATLKR','GITHUB_ACTOR':'ATLKR','GITHUB_EVENT_NAME':'push','GITHUB_REF':'refs/heads/work/opengeul-office-dotnet-graph-diagnostic','GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40,'GITHUB_JOB':'dotnet-graph-diagnostic','OPENGEUL_DOTNET_GRAPH_DIAGNOSTIC_ONLY':'1','GITHUB_ACTIONS':'true'}
        admitted=True
        with patch.object(controller.os,'environ',good):
            try:result=controller.context()
            except bounded.ProbeFailure:admitted=False
        self.assertTrue(admitted,'explicit isolated push profile is required')
        self.assertEqual(result['runId'],123)
        for key,value in [('GITHUB_REPOSITORY','other/repo'),('GITHUB_REPOSITORY_ID','1'),('GITHUB_ACTOR','other'),('GITHUB_REPOSITORY_OWNER',''),('GITHUB_EVENT_NAME','workflow_dispatch'),('GITHUB_REF','refs/heads/main'),('GITHUB_RUN_ATTEMPT','2'),('GITHUB_SHA','bad'),('GITHUB_JOB','native-firebird-and-office'),('GITHUB_ACTIONS','false')]:
            bad={**good,key:value}
            with patch.object(controller.os,'environ',bad),self.assertRaises(bounded.ProbeFailure):controller.context()
        bad={k:v for k,v in good.items() if k not in ('GITHUB_ACTOR','GITHUB_REPOSITORY_OWNER')}
        with patch.object(controller.os,'environ',bad),self.assertRaises(bounded.ProbeFailure):controller.context()

    def test_unexecuted_baseline_is_unknown_and_not_a_zero_event_proof(self):
        self.assertTrue(hasattr(controller,'reproduction_status'),'observation completeness guard is required')
        self.assertIsNone(controller.reproduction_status([])['baselineNoReproduction'])
        logs=[{'known':1,'buildStarted':1,'buildFinished':1,'cs2012Count':0}]*2
        self.assertTrue(controller.reproduction_status(logs)['baselineNoReproduction'])
        logs=[{'known':1,'buildStarted':1,'buildFinished':1,'cs2012Count':1},{'known':1,'buildStarted':1,'buildFinished':1,'cs2012Count':0}]
        self.assertFalse(controller.reproduction_status(logs)['baselineNoReproduction'])
        logs[0]['known']=0
        self.assertIsNone(controller.reproduction_status(logs)['baselineNoReproduction'])

    def test_sdk_first_run_environment_explicitly_disables_certificates_and_path_changes(self):
        with tempfile.TemporaryDirectory() as td:
            environment=bounded.child_environment(Path(td),r'C:\Windows',r'C:\Program Files\dotnet')
            for key in ('DOTNET_GENERATE_ASPNET_CERTIFICATE','DOTNET_ADD_GLOBAL_TOOLS_TO_PATH'):
                with self.subTest(field=key):self.assertEqual(environment.get(key),'false')

    def test_sdk_side_effect_guards_reject_missing_true_and_unknown_environment_before_launch(self):
        from runtime import sdk_win32
        keys=('DOTNET_GENERATE_ASPNET_CERTIFICATE','DOTNET_ADD_GLOBAL_TOOLS_TO_PATH')
        good=fake.explicit_environment(bounded);good.update({k:'false' for k in keys})
        bads=[]
        for key in keys:
            missing=dict(good);missing.pop(key);bads.append(missing)
            enabled=dict(good);enabled[key]='true';bads.append(enabled)
        bads.append({**good,'UNREVIEWED_SDK_SETTING':'false'})
        for ordinal,environment in enumerate(bads):
            with self.subTest(case=ordinal):
                clock=fake.Clock();api=fake.FakeApi(clock,True,False)
                state=bounded.Runner(api,clock=clock,pause=clock.pause).run([(['owned.exe'],'owned',environment)],3.)
                self.assertFalse(state['completed']);self.assertEqual(api.count,0)
                with self.assertRaises(sdk_win32.NativeCallError):sdk_win32._environment_block(environment)

    def test_held_descendant_preflight_requires_actual_root_exit_and_live_nonroot_member(self):
        self.assertTrue(hasattr(controller,'require_held_descendant_proof'))
        clock=fake.Clock();api=fake.FakeApi(clock,True,True)
        state=bounded.Runner(api,clock=clock,pause=clock.pause).run([(['owned.exe'],'owned',fake.explicit_environment(bounded))],3.)
        self.assertIs(state.get('rootExitedWithLiveDescendantObserved'),True)
        controller.require_held_descendant_proof(state)

    def test_root_hang_spawn_failure_empty_late_and_unknown_cannot_prove_descendants(self):
        for kind in ('root-only-hang','spawn-failure','root-exit-error','empty','late','unknown'):
            with self.subTest(kind=kind):
                clock=fake.Clock()
                class Case(fake.FakeApi):
                    def state(self,handle):
                        if self.terminations:return (0,0)
                        if kind=='root-only-hang':return (258,259)
                        if kind in ('spawn-failure','root-exit-error'):return (0,1)
                        if kind=='late':clock.now=2.1
                        return (0,0)
                    def census(self,job):
                        if self.terminations:return ()
                        if kind=='unknown':raise bounded.ProbeFailure(14)
                        if kind=='root-only-hang':return (201,)
                        return () if kind in ('empty','spawn-failure') else (500,)
                api=Case(clock,True,True)
                state=bounded.Runner(api,clock=clock,pause=clock.pause).run([(['owned.exe'],'owned',fake.explicit_environment(bounded))],3.)
                self.assertIsNot(state.get('rootExitedWithLiveDescendantObserved'),True)
                self.assertTrue(hasattr(controller,'require_held_descendant_proof'))
                with self.assertRaises(bounded.ProbeFailure):controller.require_held_descendant_proof(state)

    def test_descendant_proof_rejects_unknown_incomplete_or_untyped_receipts(self):
        good={'completed':False,'cleanupProved':True,'forcedCleanup':True,'rootExitedWithLiveDescendantObserved':True}
        controller.require_held_descendant_proof(good)
        for key,value in [('cleanupProved',False),('forcedCleanup',False),('rootExitedWithLiveDescendantObserved',False),('rootExitedWithLiveDescendantObserved',1),('rootExitedWithLiveDescendantObserved',None)]:
            with self.subTest(field=key,valueType=type(value).__name__):
                with self.assertRaises(bounded.ProbeFailure):controller.require_held_descendant_proof({**good,key:value})
        missing=dict(good);missing.pop('rootExitedWithLiveDescendantObserved')
        with self.assertRaises(bounded.ProbeFailure):controller.require_held_descendant_proof(missing)
