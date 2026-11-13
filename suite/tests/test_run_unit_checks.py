"""The real unittest result stays primary; one opted-in summary is numeric only."""
from contextlib import redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from suite.tests.test_numeric_notice import environment

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = 'SYNTHETIC-PRIVATE-INPUT C:/private/document ::error::caption'


def implementation():
    return importlib.import_module('suite.scripts.run_unit_checks')


def unit_environment():
    env=environment()
    env.pop('OPENGEUL_SUITE_NUMERIC_NOTICE')
    env.pop('OPENGEUL_SUITE_NOTICE_SCOPE')
    env['OPENGEUL_SUITE_UNIT_NOTICE']='1'
    return env


def failing_suite(count=1):
    class Synthetic(unittest.TestCase):
        def test_failure(self):
            raise AssertionError(PRIVATE)
    return unittest.TestSuite(Synthetic('test_failure') for _ in range(count))


class UnitNoticeTests(unittest.TestCase):
    def setUp(self):
        self.m=implementation()
        self.files=self.m.source_file_map()

    def result(self, count=1):
        return self.m.UnitRunner(stream=io.StringIO(),verbosity=0,source_files=self.files).run(failing_suite(count))

    def decode(self, message):
        return self.m.decode_unit_notice(message,'a'*40,123,expected_architecture=0xaa64,
                                        expected_file_count=len(self.files))

    def notice(self, result):
        stream=io.StringIO()
        context=self.m.public_context(unit_environment())
        self.assertTrue(self.m.emit_unit_notice(result,context,self.files,stream=stream))
        line=stream.getvalue().strip()
        self.assertTrue(line.startswith('::notice title='+self.m.UNIT_TITLE+'::'))
        return line.split('::',2)[2]

    def test_missing_wrapper_is_a_real_missing_route(self):
        self.assertTrue((ROOT/'suite/scripts/run_unit_checks.py').is_file())

    def test_source_map_is_sorted_public_top_level_files_with_no_content_hashes(self):
        names=list(self.files.values())
        self.assertEqual(names,sorted(names))
        self.assertEqual(list(self.files),list(range(1,len(names)+1)))
        for name in names:
            path=Path(name)
            self.assertIn(path.parent.as_posix(),self.m.SOURCE_ROOTS)
            self.assertEqual(path.suffix,'.py')
        self.assertIn('suite/tests/test_run_unit_checks.py',names)

    def test_source_map_suffix_and_depth_policy_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for directory in self.m.SOURCE_ROOTS:
                target=root/directory;target.mkdir(parents=True,exist_ok=True)
                (target/'z.py').write_text('',encoding='utf-8')
                (target/'a.py').write_text('',encoding='utf-8')
                (target/'other.PY').write_text('',encoding='utf-8')
                (target/'nested').mkdir();(target/'nested/ignored.py').write_text('',encoding='utf-8')
            real_glob=Path.glob
            def case_insensitive(directory,pattern):
                return iter(set(real_glob(directory,pattern))|set(real_glob(directory,'*.PY')))
            with patch.object(Path,'glob',autospec=True,side_effect=case_insensitive):
                names=list(self.m.source_file_map(root).values())
        self.assertEqual(names,sorted(directory+'/'+name for directory in self.m.SOURCE_ROOTS for name in ('a.py','z.py')))

    def test_result_and_runner_stay_silent_even_with_valid_unit_opt_in(self):
        stream=io.StringIO()
        with patch.dict(os.environ,unit_environment(),clear=True),redirect_stdout(stream):
            result=self.result(2)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual((result.testsRun,len(result.failures),len(result.errors)),(2,2,0))
        self.assertEqual(stream.getvalue(),'')

    def test_summary_has_actual_counts_owned_locations_and_no_private_content(self):
        value=self.decode(self.notice(self.result(2)))
        self.assertEqual((value['testsRun'],value['failureCount'],value['errorCount']),(2,2,0))
        self.assertEqual((value['descriptorCount'],value['droppedFailureCount']),(2,0))
        code=next(code for code,path in self.files.items() if path=='suite/tests/test_run_unit_checks.py')
        for descriptor in value['failures']:
            self.assertEqual(descriptor['exceptionCode'],1)
            self.assertEqual(descriptor['fileCode'],code)
            self.assertEqual(descriptor['testFileCode'],code)
            self.assertGreater(descriptor['line'],descriptor['testLine'])
        message=json.dumps(value)
        self.assertNotIn(PRIVATE,message)
        self.assertNotIn('test_failure',message)
        self.assertNotIn('C:/',message)
        self.assertLessEqual(len(message.encode()),2048)

    def test_first_eight_failures_are_bounded_and_dropped_count_is_explicit(self):
        value=self.decode(self.notice(self.result(11)))
        self.assertEqual((value['testsRun'],value['failureCount']),(11,11))
        self.assertEqual((value['descriptorCount'],value['droppedFailureCount']),(8,3))
        self.assertEqual(len(value['failures']),8)

    def test_receiver_rejects_duplicates_private_extras_coercions_and_wrong_binding(self):
        message=self.notice(self.result())
        base=json.loads(message)
        invalid=['{"kind":3,'+message[1:],message+' '*2049]
        for change in ({'sourceCommit':'b'*40},{'runId':True},{'testsRun':'1'},
                       {'private':PRIVATE},{'descriptorCount':0},{'fileCount':len(self.files)+1}):
            invalid.append(json.dumps(base|change))
        for change in ({'line':0},{'exceptionCode':True},{'fileCode':len(self.files)+1},{'message':PRIVATE}):
            value=json.loads(message);value['failures'][0].update(change);invalid.append(json.dumps(value))
        for value in invalid:
            with self.subTest(value=value[:40]),self.assertRaises((ValueError,TypeError)):
                self.decode(value)

    def test_public_context_is_independent_of_both_notice_flags_and_scope(self):
        numeric=importlib.import_module('suite.e2e.numeric_notice')
        env=unit_environment()
        self.assertFalse(numeric.notices_enabled(env))
        expected=dict(sourceCommit='a'*40,runId=123,runAttempt=1,architecture=0xaa64)
        self.assertEqual(numeric.public_context(env),expected)
        for key,value in (('GITHUB_RUN_ATTEMPT','2'),('GITHUB_WORKFLOW_SHA','b'*40),('GITHUB_ACTOR_ID','1')):
            self.assertIsNone(numeric.public_context(env|{key:value}))

    def test_main_freezes_context_and_emits_once_after_tests_mutate_environment(self):
        result=self.result()
        def program(**kwargs):
            os.environ.clear()
            return SimpleNamespace(result=result)
        stream=io.StringIO()
        with patch.dict(os.environ,unit_environment(),clear=True),patch.object(self.m.unittest,'TestProgram',side_effect=program) as call,redirect_stdout(stream):
            self.assertEqual(self.m.main(['-s','suite/tests','-v']),1)
        self.assertEqual(call.call_args.kwargs['argv'],['python -m unittest','discover','-s','suite/tests','-v'])
        self.assertIsNone(call.call_args.kwargs['module'])
        self.assertIs(call.call_args.kwargs['exit'],False)
        lines=stream.getvalue().splitlines()
        self.assertEqual(len(lines),1)
        self.decode(lines[0].split('::',2)[2])

    def test_optional_emitter_failure_cannot_replace_the_actual_unit_result(self):
        result=self.result()
        with patch.dict(os.environ,unit_environment(),clear=True), \
             patch.object(self.m.unittest,'TestProgram',return_value=SimpleNamespace(result=result)), \
             patch.object(self.m,'emit_unit_notice',side_effect=OSError(PRIVATE)):
            self.assertEqual(self.m.main([]),1)

    def test_subtests_are_captured_before_formatting_without_reading_parameters(self):
        events=[]
        class ObservedError(ValueError):
            def __str__(self):events.append('formatted');return PRIVATE
        class Case(unittest.TestCase):
            def test_subtest(self):
                with self.subTest(private=PRIVATE):raise ObservedError()
        runner=self.m.UnitRunner(stream=io.StringIO(),verbosity=0,source_files=self.files)
        original=self.m.UnitResult._record
        def record(result,*args):
            events.append('captured');return original(result,*args)
        with patch.object(self.m.UnitResult,'_record',record):result=runner.run(unittest.TestSuite([Case('test_subtest')]))
        self.assertEqual(events[0],'captured')
        self.assertIn('formatted',events[1:])
        value=self.decode(self.notice(result))
        self.assertEqual(value['failures'][0]['resultCode'],3)
        self.assertNotIn(PRIVATE,json.dumps(value))

    def test_zero_run_class_skip_is_an_actual_valid_summary(self):
        class Case(unittest.TestCase):
            @classmethod
            def setUpClass(cls):raise unittest.SkipTest(PRIVATE)
            def test_unused(self):pass
        result=self.m.UnitRunner(stream=io.StringIO(),verbosity=0,source_files=self.files).run(unittest.TestSuite([Case('test_unused')]))
        value=self.decode(self.notice(result))
        self.assertEqual((value['testsRun'],value['skippedCount']),(0,1))
        self.assertEqual(value['failures'],[])

    def test_class_setup_error_has_zero_tests_run_and_no_invented_test_definition(self):
        class Case(unittest.TestCase):
            @classmethod
            def setUpClass(cls):raise ValueError(PRIVATE)
            def test_unused(self):pass
        result=self.m.UnitRunner(stream=io.StringIO(),verbosity=0,source_files=self.files).run(unittest.TestSuite([Case('test_unused')]))
        value=self.decode(self.notice(result))
        self.assertEqual((value['testsRun'],value['errorCount']),(0,1))
        self.assertEqual((value['failures'][0]['testFileCode'],value['failures'][0]['testLine']),(0,0))
        self.assertGreater(value['failures'][0]['fileCode'],0)

    def test_empty_discovery_preserves_the_standard_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            env=dict(os.environ);env.pop('OPENGEUL_SUITE_NUMERIC_NOTICE',None);env.pop('OPENGEUL_SUITE_UNIT_NOTICE',None)
            env.update(GH_TOKEN='synthetic-unit-fixture-token',GITHUB_TOKEN='synthetic-unit-fixture-token')
            original,wrapped=[subprocess.run([sys.executable,'-m',*module,'-s',folder],cwd=ROOT,
                env=env,capture_output=True,text=True,timeout=15,shell=False) for module in
                (['unittest','discover'],['suite.scripts.run_unit_checks'])]
        self.assertEqual(original.returncode,5)
        self.assertEqual(wrapped.returncode,original.returncode)
        self.assertEqual(wrapped.stdout,'')

    def test_unknown_trace_source_is_zero_without_copying_its_filename(self):
        result=self.m.UnitResult(io.StringIO(),False,0);result.source_paths=self.m._path_codes(self.files)
        class Case(unittest.TestCase):
            def test_unused(self):pass
        try:exec(compile('raise ValueError()\n','C:/'+PRIVATE,'exec'))
        except ValueError:
            # Remove the owned outer frame: only the unowned throwing frame remains.
            kind,error,trace=sys.exc_info();result._record(Case('test_unused'),(kind,error,trace.tb_next),1)
        self.assertEqual((result.numeric_failures[0]['fileCode'],result.numeric_failures[0]['line']),(0,0))
        self.assertNotIn(PRIVATE,json.dumps(result.numeric_failures))

    def test_maximum_legal_unit_notice_fits_two_kibibytes(self):
        value=self.decode(self.notice(self.result(8)))
        value.update(testsRun=0xffffffff,errorCount=0,failureCount=0xffffffff,
            skippedCount=0xffffffff,expectedFailureCount=0xffffffff,unexpectedSuccessCount=0,
            droppedFailureCount=0xffffffff-8,fileCount=self.m.MAX_FILE_CODE)
        for descriptor in value['failures']:
            descriptor.update(resultCode=4,exceptionCode=12,fileCode=self.m.MAX_FILE_CODE,
                line=self.m.MAX_LINE,testFileCode=self.m.MAX_FILE_CODE,testLine=self.m.MAX_LINE)
        message=json.dumps(value,separators=(',',':'))
        self.assertLessEqual(len(message.encode()),2048)
        self.m.decode_unit_notice(message,'a'*40,123,expected_architecture=0xaa64)

    def test_real_module_discovery_preserves_neighbor_imports_logs_counts_and_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            start=Path(folder)
            (start/'neighbor.py').write_text('VALUE=7\n',encoding='utf-8')
            (start/'test_synthetic.py').write_text(
                'import unittest\nfrom neighbor import VALUE\n'
                'class Cases(unittest.TestCase):\n'
                ' def test_pass(self): self.assertEqual(VALUE,7)\n'
                ' def test_fail(self): self.fail("SYNTHETIC-PRIVATE-INPUT")\n'
                ' def test_error(self): raise ValueError("SYNTHETIC-PRIVATE-INPUT")\n'
                ' @unittest.skip("SYNTHETIC-PRIVATE-INPUT")\n'
                ' def test_skip(self): pass\n'
                ' @unittest.expectedFailure\n'
                ' def test_expected(self): self.fail("SYNTHETIC-PRIVATE-INPUT")\n'
                ' @unittest.expectedFailure\n'
                ' def test_unexpected(self): pass\n'
                ' def test_sub(self):\n'
                '  with self.subTest(secret="SYNTHETIC-PRIVATE-INPUT"): self.fail("SYNTHETIC-PRIVATE-INPUT")\n',encoding='utf-8')
            env=dict(os.environ);env.update(unit_environment())
            env.update(GH_TOKEN='synthetic-unit-fixture-token',GITHUB_TOKEN='synthetic-unit-fixture-token')
            env.pop('OPENGEUL_SUITE_NUMERIC_NOTICE',None);env.pop('OPENGEUL_SUITE_NOTICE_SCOPE',None)
            commands=([sys.executable,'-m','unittest','discover','-s',str(start),'-v'],
                      [sys.executable,'-m','suite.scripts.run_unit_checks','-s',str(start),'-v'])
            original,wrapped=[subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,
                timeout=15,shell=False) for command in commands]
        self.assertEqual((original.returncode,wrapped.returncode),(1,1))
        normalize=lambda text:re.sub(r'Ran 7 tests in [0-9.]+s','Ran 7 tests in TIME',text)
        self.assertEqual(normalize(original.stderr),normalize(wrapped.stderr))
        self.assertEqual(original.stdout,'')
        lines=wrapped.stdout.splitlines();self.assertEqual(len(lines),1)
        value=self.decode(lines[0].split('::',2)[2])
        self.assertEqual((value['testsRun'],value['failureCount'],value['errorCount'],value['skippedCount'],
            value['expectedFailureCount'],value['unexpectedSuccessCount']),(7,2,1,1,1,1))
        self.assertNotIn('SYNTHETIC-PRIVATE-INPUT',wrapped.stdout)


if __name__=='__main__':
    unittest.main()
