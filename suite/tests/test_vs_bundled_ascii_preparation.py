"""Synthetic process boundaries and real source/PE readers; Windows execution is separate."""
import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_ascii_message_preparation as base
import test_native_clang_preparation as tools_fixture
import test_vs_bundled_clang_probe as qualification
import vs_bundled_clang_probe as bundled

m = base.m
MODE = 'vs-bundled-clang'


class Runtime(base.Runtime):
    def __init__(self, case):
        super().__init__(case)
        self.states = [[(0, 0, 0)] for _ in range(4)]
        self.version_queries = []
        self.versions = [(22, 1), (22, 1)]
        self.after_start = None
        self.library_bytes = qualification.qualification_pe(normal=('kernel32.dll','user32.dll'))

    def start(self, argv, folder):
        index = len(self.processes)
        process = SimpleNamespace(handle=40+index, job=60+index, pid=80+index,
            index=index, forced=False, closed=False, queries=0, argv=argv)
        def terminate(): process.forced = True
        def close():
            process.closed=True;process.handle=process.job=None
            if self.close_error: raise RuntimeError('synthetic close failure')
        process.terminate,process.close=terminate,close
        self.processes.append(process)
        if index == 0:
            (folder/'discovery.stdout').write_text(str(self.case.install),encoding='utf-8')
            (folder/'discovery.stderr').write_bytes(b'')
        elif folder == self.case.output:
            (folder/'ascii-message-observer.dll').write_bytes(self.library_bytes)
            (folder/'compiler.stdout').write_bytes(b'')
            (folder/'compiler.stderr').write_bytes(b'')
        else:
            request=json.loads(Path(argv[-2]).read_bytes())
            self.version_queries.append(copy.deepcopy(request))
            kind=request['kindCode'];major,minor=self.versions[kind-1]
            observed=dict(exitCode=0,timedOut=False,outputCapReached=False,pid=180+kind,
                creationTime=134395652231767531,imageMatched=True,naturalExit=True,
                handlesClosed=True,captureError=False,captureObservation=bundled.helper_module.capture_observation())
            raw=(('clang version ' if kind==1 else 'LLD ')+str(major)+'.'+str(minor)+'.0\n').encode('ascii')
            result=bundled.helper_module.query(request,capture_call=lambda *_:(observed,raw,b''))
            Path(argv[-1]).write_text(json.dumps(result),encoding='utf-8')
        if self.after_start:self.after_start(index)
        return process


class BundledAsciiPreparationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=base.PreparationTests('test_success_requires_two_naturally_empty_jobs_and_pins_every_output')
        self.addCleanup(self.fixture.doCleanups);self.fixture.setUp()
        for name in ('root','source','install','programs','output','clock'):
            setattr(self,name,getattr(self.fixture,name))
        for name in m.SOURCES:
            (self.source/name).write_bytes((Path(__file__).resolve().parents[1]/'e2e'/name).read_bytes())
        self.tool_root=self.install/'VC/Tools/Llvm/x64/bin';self.tool_root.mkdir(parents=True)
        for name in bundled.TOOLS:(self.tool_root/name).write_bytes(tools_fixture.executable())
        self.windows=self.root/'Windows';(self.windows/'System32').mkdir(parents=True)
        self.program_data=self.root/'ProgramData';self.program_data.mkdir()
        self.host=self.root/'python.exe';self.host.write_bytes(tools_fixture.executable())
        self.runtime=Runtime(self)
        self.environ={'ProgramFiles(x86)':str(self.programs),'SystemRoot':str(self.windows),
            'COMSPEC':str(self.windows/'System32/cmd.exe'),'ProgramData':str(self.program_data)}
        self.runtime_environments=[]
        def runtime(environment):
            self.runtime_environments.append(dict(environment));return self.runtime
        for p in (patch.object(bundled,'_Runtime',side_effect=runtime),
                  patch.object(bundled.sys,'executable',str(self.host)),
                  patch.object(os_module(),'environ',self.environ)):
            p.start();self.addCleanup(p.stop)

    def prepare(self,**kwargs):
        return m.prepare_observer(self.output,architecture='x64',compiler_mode=MODE,**kwargs)

    def proof(self):return json.loads((self.output/'preparation.json').read_bytes())

    def test_exact_selected_tools_recipe_and_before_input_replay(self):
        descriptor=self.prepare();proof=self.proof()
        self.assertEqual(m.require_prepared_library(descriptor,architecture='x64'),self.output/'ascii-message-observer.dll')
        compiler=proof['compiler'];self.assertEqual(compiler['mode'],MODE)
        self.assertEqual([Path(compiler['before'][n]['path'])for n in bundled.TOOLS],
            [self.tool_root/n for n in bundled.TOOLS])
        self.assertEqual(compiler['before'],compiler['after'])
        self.assertEqual((self.output/'compile.cmd').read_text(encoding='ascii'),bundled._qualification_recipe('14.50.35717'))
        self.assertEqual([r['stage']for r in proof['stages']],
            ['discovery','probe-clang-version','probe-lld-version','compile'])
        self.assertEqual([v['kindCode']for v in self.runtime.version_queries],[1,2])
        self.assertEqual(proof['deadline']-proof['startedAt'],30.)
        self.assertEqual(proof['workDeadline'],proof['deadline']-3.)
        self.assertTrue(all(p.closed and not p.forced for p in self.runtime.processes))
        self.assertEqual(len(self.runtime.processes),4)
        self.assertTrue(proof['binaryProof']['exportsMatch'])
        self.assertEqual(proof['binaryProof']['dynamicCrtImportCount'],0)
        self.assertEqual(set(self.runtime_environments[0]),
            {'COMSPEC','SystemRoot','WINDIR','PATH','TEMP','TMP','PYTHONUTF8','PYTHONDONTWRITEBYTECODE','ProgramData'})

    def test_native_recipe_line_endings_do_not_weaken_output_byte_pins(self):
        descriptor=self.prepare()
        recipe=bundled._qualification_recipe('14.50.35717')
        crlf=recipe.replace('\n','\r\n').encode('ascii')
        sample=self.root/'native-crlf-recipe.cmd';sample.write_bytes(crlf)
        self.assertEqual(sample.read_text(encoding='ascii'),recipe)
        script=self.output/'compile.cmd';original=script.read_bytes()
        changed=recipe.encode('ascii') if b'\r\n' in original else crlf
        self.assertNotEqual(changed,original)
        script.write_bytes(changed)
        with self.assertRaises(AssertionError):m.require_prepared_library(descriptor,architecture='x64')

    def test_x64_caller_selects_only_explicit_bundled_mode_and_arm_is_unchanged(self):
        editor=importlib.import_module('ascii_editor_input')
        native=importlib.import_module('ascii_message_preparation')
        with patch.object(native,'prepare_observer',return_value='synthetic')as selected:
            self.assertEqual(editor.prepare_observer(self.output,architecture='x64'),'synthetic')
            self.assertEqual(selected.call_args.kwargs,dict(architecture='x64',compiler_mode=MODE,budget=None))
            editor.prepare_observer(self.output,architecture='arm64')
            self.assertEqual(selected.call_args.kwargs,dict(architecture='arm64',budget=None))

    def test_unknown_mode_or_bundled_arm_never_starts_any_process(self):
        for mode,architecture in ((MODE,'arm64'),('unknown','x64')):
            with self.subTest(mode=mode),self.assertRaises(AssertionError):
                m.prepare_observer(self.output,architecture=architecture,compiler_mode=mode)
        self.assertEqual(self.runtime.processes,[])

    def test_supplied_budget_is_shared_without_renewal(self):
        budget=m._Budget();self.clock.value=124.
        with patch.object(m,'_Budget',side_effect=AssertionError('budget renewal forbidden')):
            self.prepare(budget=budget)
        proof=self.proof();self.assertEqual((proof['startedAt'],proof['deadline']),(100.,130.))
        self.assertEqual([x['deadline']for x in self.runtime.version_queries],[127.,127.])

    def test_expired_budget_has_no_runtime_or_process_start(self):
        budget=m._Budget();self.clock.value=127.
        with self.assertRaises(AssertionError):self.prepare(budget=budget)
        self.assertEqual(self.runtime.processes,[]);self.assertEqual(self.runtime_environments,[])

    def test_old_version_stops_before_other_version_and_compile_without_fallback(self):
        self.runtime.versions[0]=(21,1)
        with self.assertRaises(Exception):self.prepare()
        self.assertEqual([x['kindCode']for x in self.runtime.version_queries],[1])
        self.assertEqual(len(self.runtime.processes),2)
        self.assertFalse(self.proof()['success'])

    def test_version_job_root_zero_nonempty_still_fails_under_original_cutoff(self):
        self.runtime.states[1]=[(0,1,0)]
        with self.assertRaises(Exception):self.prepare()
        proof=self.proof();self.assertFalse(proof['success'])
        self.assertEqual(len(self.runtime.processes),2)
        self.assertTrue(self.runtime.processes[1].forced)
        self.assertTrue(all(p.closed for p in self.runtime.processes))
        self.assertEqual(proof['deadline'],130.)

    def test_compile_root_zero_nonempty_is_not_natural_or_retried(self):
        self.runtime.states[3]=[(0,1,0)]
        with self.assertRaises(AssertionError):self.prepare()
        stage=self.proof()['stages'][-1]
        self.assertEqual(stage['stage'],'compile');self.assertFalse(stage['natural'])
        self.assertTrue(stage['forcedOwnedJobCleanup']);self.assertTrue(stage['handlesClosed'])
        self.assertEqual(len(self.runtime.processes),4)

    def test_nonzero_compile_keeps_original_error_and_cleanup(self):
        self.runtime.states[3]=[(0,0,3)]
        with self.assertRaisesRegex(AssertionError,'compiler stage failed'):self.prepare()
        stage=self.proof()['stages'][-1];self.assertEqual(stage['error']['type'],'AssertionError')
        self.assertTrue(stage['handlesClosed']);self.assertFalse(self.proof()['success'])
        self.assertEqual(len(self.runtime.processes),4)

    def test_wrong_dll_exports_or_dynamic_crt_never_yield_descriptor(self):
        self.runtime.library_bytes=qualification.qualification_pe(normal=('msvcrt.dll',))
        with self.assertRaises(AssertionError):self.prepare()
        self.assertFalse(self.proof()['success'])
        self.assertTrue(all(p.closed for p in self.runtime.processes))

    def test_version_query_drift_stops_without_compiling(self):
        def drift(index):
            if index==1:
                tool=self.tool_root/'clang-cl.exe';tool.write_bytes(tool.read_bytes()+b'drift')
        self.runtime.after_start=drift
        with self.assertRaises(AssertionError):self.prepare()
        self.assertFalse(self.proof()['success']);self.assertEqual(len(self.runtime.processes),2)

    def test_prepared_version_recipe_and_tool_scope_tampering_is_rejected(self):
        descriptor=self.prepare()
        cases=(lambda p:p['compiler']['versions'][0].update(major=21),
            lambda p:p['compiler']['versions'][1].update(naturalExit=False),
            lambda p:p['compiler']['selection'].update(toolsetVersion='14.50.00000'))
        for change in cases:
            with self.subTest(case=cases.index(change)):
                proof=self.proof();original=copy.deepcopy(proof);change(proof)
                path=self.output/'preparation.json';path.write_text(json.dumps(proof))
                altered=copy.deepcopy(descriptor);altered['preparationReceipt'].update(m._pin(path));altered['compiler']=proof['compiler']
                with self.assertRaises(Exception):m.require_prepared_library(altered)
                path.write_text(json.dumps(original));descriptor['preparationReceipt'].update(m._pin(path))

    def test_replayed_success_cannot_claim_timeout_or_output_overflow(self):
        descriptor=self.prepare();original=self.proof()
        result_path=self.output/'version-1/query-1.result.private.json'
        original_result=result_path.read_bytes()
        for field in ('timedOut','outputCapReached'):
            with self.subTest(field=field):
                proof=copy.deepcopy(original)
                proof['compiler']['versions'][0][field]=True
                result_path.write_text(json.dumps(proof['compiler']['versions'][0]))
                proof['compiler']['versionArtifacts'][0]['result']=m._pin(result_path)
                path=self.output/'preparation.json';path.write_text(json.dumps(proof))
                altered=copy.deepcopy(descriptor);altered['preparationReceipt'].update(m._pin(path));altered['compiler']=proof['compiler']
                with self.assertRaises(AssertionError):m.require_prepared_library(altered)
                result_path.write_bytes(original_result)

    def test_unc_system_root_is_rejected_before_path_observation(self):
        self.environ['SystemRoot']='//synthetic-unread-root/Windows'
        seen=[];original=m._absolute
        def observe(path):
            if str(path).replace(chr(92),'/').startswith('//'):
                seen.append(True);raise AssertionError('synthetic path observation blocked')
            return original(path)
        with patch.object(m,'_absolute',side_effect=observe):
            with self.assertRaises(AssertionError):self.prepare()
        self.assertEqual(seen,[])
        self.assertEqual(self.runtime.processes,[])

    def test_named_environment_reads_never_copy_parent_mapping(self):
        class NoBulk(dict):
            bulk=0
            def forbidden(self,*_):self.bulk+=1;raise AssertionError('synthetic bulk environment forbidden')
            copy=keys=items=__iter__=forbidden
        environment=NoBulk(self.environ)
        with patch.object(os_module(),'environ',environment):
            descriptor=self.prepare()
        self.assertEqual(environment.bulk,0)
        self.assertEqual(m.require_prepared_library(descriptor),self.output/'ascii-message-observer.dll')

    def test_no_standalone_llvm_or_missing_selected_pair_fallback(self):
        (self.tool_root/'lld-link.exe').unlink()
        with self.assertRaises(AssertionError):self.prepare()
        self.assertFalse(self.proof()['success']);self.assertEqual(len(self.runtime.processes),2)
        self.assertNotIn('ProgramFiles',self.environ)


def os_module():
    import os
    return os


if __name__=='__main__':unittest.main()
