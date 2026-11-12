"""Portable synthetic controls; deliberately performs no native compilation."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
def load():
    spec=importlib.util.spec_from_file_location('fixed_collector_candidate',HERE/'observe-ime-finalization-compile.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class CollectorTests(unittest.TestCase):
    def setUp(self):self.c=load()
    def test_fixed_head_nine_file_roles_and_original_policy_positive(self):
        self.assertEqual(self.c.SOURCE_HEAD,'3a5b101ba9b66b6c17544f89c9f39cdd6e63d933')
        self.assertEqual(len(self.c.SOURCE_PINS),9)
        self.assertEqual(tuple(item[1] for item in self.c.CASES),('native_policy.cpp','native_adapter.cpp','native_negotiation.cpp'))
    def test_source_literal_is_read_by_ast_without_importing_ui(self):
        literal='OBSERVER_SOURCE = '+repr('fixed public native source')+'\nraise RuntimeError("must not execute")\n'
        self.assertEqual(self.c.observer_literal(literal.encode()),'fixed public native source')
        for data in (b'OBSERVER_SOURCE = function()',b'OBSERVER_SOURCE = "a"\nOBSERVER_SOURCE = "b"'):
            with self.assertRaises(ValueError):self.c.observer_literal(data)
    def test_closed_projection_keeps_severity_code_and_known_location(self):
        root=HERE/'synthetic-owned'
        result=self.c.project_diagnostics(str(root/'native_adapter.cpp')+'(20): warning C4312: SYNTHETIC_PRIVATE_SENTINEL\n',
            'LINK : fatal error LNK1104: SYNTHETIC_PRIVATE_SENTINEL\n',root)
        self.assertEqual(result['diagnostics'],[
            dict(streamCode=1,severity=1,kind=1,number=4312,fileCode=2,line=20),
            dict(streamCode=2,severity=3,kind=3,number=1104,fileCode=0,line=0)])
        self.assertNotIn('SYNTHETIC_PRIVATE_SENTINEL',json.dumps(result));self.assertNotIn(str(root),json.dumps(result))
    def test_projection_unknown_path_localized_label_and_caps(self):
        v=self.c.project_diagnostics('C:\\other\\native_adapter.cpp(20): warning C4312: unused\n'+'native_adapter.cpp(21): 경고 C4312: unused\n','',HERE)
        self.assertEqual([(r['fileCode'],r['line'],r['severity']) for r in v['diagnostics']],[(0,0,1),(2,21,0)])
        v=self.c.project_diagnostics('native_adapter.cpp(20): error C2220: unused\n'*40,'',HERE)
        self.assertEqual((len(v['diagnostics']),v['droppedCount']),(32,8))
        self.assertEqual(self.c.project_diagnostics('x'*65537,'',HERE)['scanComplete'],0)
    def test_compiler_wrapper_returns_original_result_object_and_original_failure(self):
        result=subprocess.CompletedProcess([],2,'native_adapter.cpp(20): warning C4312: unused','')
        calls=[];case=dict(compileCalls=0,compile=[])
        def original(*args,**kwargs):calls.append((args,kwargs));return result
        wrapper=self.c.compiler_observer(original,case)
        self.assertIs(wrapper('opaque synthetic command',cwd=HERE,env={},timeout=60,observe_phase=lambda:{}),result)
        self.assertEqual(case['compileCalls'],1);self.assertEqual(calls[0][1]['timeout'],60)
        self.assertEqual(case['compile'][0]['exitCode'],2)
        original_error=AssertionError('fixed synthetic error')
        def failure(*args,**kwargs):raise original_error
        with self.assertRaises(AssertionError) as caught:self.c.compiler_observer(failure,case)('opaque',cwd=HERE)
        self.assertIs(caught.exception,original_error)
    def test_unknown_exception_diagnostic_never_uses_repr(self):
        class NoConversionError(Exception):
            def __str__(self):raise AssertionError('Forbidden conversion')
            __repr__=__str__
        result=self.c.ClosedResult()
        case=unittest.FunctionTestCase(lambda:(_ for _ in ()).throw(NoConversionError()))
        case.run(result)
        self.assertEqual((result.testsRun,result.outcome,result.exceptionCode),(1,2,255))
        self.assertEqual(result.errors[0][1],'')
    def test_failed_cases_produce_exit_one_and_acceptance_zero(self):
        value=self.c.new_receipt()
        value['cases']=[dict(caseCode=1,outcome=0),dict(caseCode=2,outcome=1),dict(caseCode=3,outcome=1)]
        self.assertEqual(self.c.final_exit(value),1)
        value['cases']=[dict(caseCode=n,outcome=0) for n in (1,2,3)]
        self.assertEqual(self.c.final_exit(value),0)
        self.assertEqual((value['acceptanceEligible'],value['qualificationEligible']),(0,0))
    def test_alias_and_mutated_source_rejected_before_import(self):
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            root=Path(folder);target=root/'fixed.py';target.write_bytes(b'fixed')
            import hashlib
            pin=('fixed.py',5,hashlib.sha256(b'fixed').hexdigest())
            self.assertEqual(self.c.read_pinned(root,pin),b'fixed')
            target.write_bytes(b'wrong')
            with self.assertRaises(ValueError):self.c.read_pinned(root,pin)
            target.unlink();(root/'other.py').write_bytes(b'fixed');target.symlink_to(root/'other.py')
            with self.assertRaises(ValueError):self.c.read_pinned(root,pin)
    def test_admission_rejects_wrong_head_without_reading_source(self):
        with mock.patch.object(self.c,'read_head',return_value='0'*40),mock.patch.object(self.c,'read_pinned') as read:
            with self.assertRaises(ValueError):self.c.admit_source(HERE)
        self.assertEqual(read.call_count,0)
    def test_wrapper_projection_failure_cannot_replace_compiler_result(self):
        result=subprocess.CompletedProcess([],2,'','');case=dict(compileCalls=0,compile=[])
        with mock.patch.object(self.c,'project_diagnostics',side_effect=ValueError('synthetic')):
            self.assertIs(self.c.compiler_observer(lambda *a,**k:result,case)('opaque',cwd=HERE),result)
        self.assertEqual(case['compile'][0]['projectionFailed'],1)
    def test_source_failure_writes_only_closed_report_and_exits_one(self):
        with tempfile.TemporaryDirectory(dir=HERE)as folder:
            source=Path(folder)/'source';source.mkdir();output=Path(folder)/'output'
            with mock.patch.object(self.c,'admit_source',side_effect=ValueError('SYNTHETIC_PRIVATE_SENTINEL')),mock.patch.object(self.c,'run_cases')as run:
                code=self.c.main(['--source-root',str(source),'--architecture','x64','--output',str(output)])
            self.assertEqual((code,run.call_count),(1,0))
            text=(output/'report.numeric.json').read_text();value=json.loads(text)
            self.assertEqual((value['sourceVerified'],value['actualWindowsExecuted'],value['exitCode']),(0,0,1))
            self.assertNotIn('SYNTHETIC_PRIVATE_SENTINEL',text);self.assertNotIn(str(source),text)
            self.assertEqual([p.name for p in output.iterdir()],['report.numeric.json'])
    def test_invalid_cli_arguments_never_echo_values(self):
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=self.c.main(['--unapproved','SYNTHETIC_PRIVATE_SENTINEL'])
        self.assertEqual((code,out.getvalue(),err.getvalue()),(1,'',''))
    def test_output_freshness_alias_and_source_containment(self):
        with tempfile.TemporaryDirectory(dir=HERE)as folder:
            source=Path(folder)/'source';source.mkdir()
            with self.assertRaises(ValueError):self.c.prepare_output(source/'output',source)
            existing=Path(folder)/'existing';existing.mkdir()
            with self.assertRaises(ValueError):self.c.prepare_output(existing,source)
            alias=Path(folder)/'alias';alias.symlink_to(source,target_is_directory=True)
            with self.assertRaises(ValueError):self.c.prepare_output(alias/'outside',source)
    def test_pinned_original_cases_with_synthetic_windows_adapters_keep_two_failures(self):
        import builtins
        approved={name:(HERE/'pinned-source'/name).read_bytes()for name,_,_ in self.c.SOURCE_PINS}
        for name,size,digest in self.c.SOURCE_PINS:
            import hashlib
            self.assertEqual((len(approved[name]),hashlib.sha256(approved[name]).hexdigest()),(size,digest))
        original_exec=builtins.exec;original_os=os;installed=[]
        class SyntheticWindows(types.ModuleType):
            name='nt'
            def __getattr__(self,name):return getattr(original_os,name)
        with tempfile.TemporaryDirectory(dir=HERE)as folder:
            tools=Path(folder)
            def fixed_exec(code,globals=None,locals=None,**options):
                result=original_exec(code,globals,locals,**options)
                if globals is not None and globals.get('__name__')=='test_native_crt_probe':
                    fixture=globals['NativeSerializerFixtureTests']();instance,_=fixture.installation(tools,0x8664)
                    plan=globals['_serializer_tools'](instance,0x8664)
                    plan['commandProcessor']=globals['_serializer_pe'](fixture.pe(tools/'cmd.exe',0x8664),0x8664)
                    globals['_serializer_windows_plan']=lambda:plan
                    def compile_process(command,*,cwd,env,timeout,observe_phase):
                        self.assertEqual(timeout,60)
                        source=next(Path(cwd).glob('*.cpp'));installed.append(source.name)
                        if source.name=='native_policy.cpp':fixture.pe(Path(cwd)/'serializer.exe',0x8664);return subprocess.CompletedProcess([],0,'','')
                        code=4312 if source.name=='native_adapter.cpp'else 4267
                        return subprocess.CompletedProcess([],2,str(source)+'(20): warning C'+str(code)+': SYNTHETIC_PRIVATE_SENTINEL','')
                    globals['_serializer_compile_process']=compile_process
                return result
            def run(command,**options):return subprocess.CompletedProcess(command,0,'','')
            receipt=self.c.new_receipt()
            with mock.patch.object(builtins,'exec',side_effect=fixed_exec),mock.patch.dict(sys.modules,{'os':SyntheticWindows('os')}),mock.patch.object(subprocess,'run',side_effect=run):
                self.c.run_cases(approved,receipt)
            self.assertEqual(installed,['native_policy.cpp','native_adapter.cpp','native_negotiation.cpp'])
            self.assertEqual([r['outcome']for r in receipt['cases']],[0,1,1])
            self.assertEqual(self.c.final_exit(receipt),1)
            self.assertEqual([r['compile'][0]['exitCode']for r in receipt['cases']],[0,2,2])
            self.assertEqual([r['compile'][0]['diagnostics'][0]['number']for r in receipt['cases'][1:]],[4312,4267])
            self.assertNotIn('SYNTHETIC_PRIVATE_SENTINEL',json.dumps(receipt))
            self.assertFalse(any(n in sys.modules for n in('test_native_crt_probe','native_executable_cleanup','fixed_finalization_cases')))

class NumericResult(unittest.TestResult):
    def __init__(self):super().__init__();self.closed=[]
    def addError(self,test,err):self.errors.append((test,''));self.closed.append(dict(test=test._testMethodName,kind=1,errorType=err[0].__name__))
    def addFailure(self,test,err):self.failures.append((test,''));self.closed.append(dict(test=test._testMethodName,kind=2,errorType=err[0].__name__))

if __name__=='__main__':
    os.environ={'SYNTHETIC_ENVIRONMENT_ONLY':'1'}
    result=NumericResult();unittest.defaultTestLoader.loadTestsFromTestCase(CollectorTests).run(result)
    print(json.dumps(dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),descriptors=result.closed),separators=(',',':')))
    raise SystemExit(0 if result.wasSuccessful() else 1)
