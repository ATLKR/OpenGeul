"""Closed supplemental engine summaries never replace Suite acceptance."""
import ast
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'suite/scripts/publish-engine-failure-summary.py'
SPEC=importlib.util.spec_from_file_location('summary_publisher',SCRIPT)
publisher=None
if SCRIPT.is_file():
    publisher=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(publisher)
MODULES=('writer','calc','impress','draw','math','base')


def sample():
    cases=[]
    for module in MODULES:
        failed=module in ('writer','draw','math')
        cases.append({'module':module,'status':'failed' if failed else 'passed',
            'failure':{'stage':'engine-start','category':'RuntimeError'} if failed else None,
            'finalizationFailures':[],'cleanupErrorCount':0,
            'cleanup':{'gracefulQualified':None,'forcedTermination':False,'jobEmptyVerified':True,
                       'launcherExitCode':0,'errors':[],'errorsTruncated':False,
                       'desktopLifetime':None,'originalEngine':None}})
    return {'schemaVersion':1,'kind':'engine-failure-summary','acceptanceEligible':False,'passed':False,'cases':cases}


class EngineFailureSummaryArtifactTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(publisher,'Closed supplemental publisher is missing')
        self.row=sample()
        self.env={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows',
            'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_JOB':'windows-suite','GITHUB_SHA':'a'*40,
            'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}

    def encode(self,row=None):return json.dumps(self.row if row is None else row,allow_nan=False).encode()

    def test_valid_failed_summary_remains_non_acceptance(self):
        value=publisher.validate_bytes(self.encode())
        self.assertEqual(value,self.row)
        self.assertIs(value['acceptanceEligible'],False)
        self.assertIs(value['passed'],False)

    def test_utf8_size_and_duplicate_keys_are_strict(self):
        for raw in (b'\xff',b'\xef\xbb\xbf'+self.encode(),b' '*32769,
                    self.encode()[:-1]+b',"schemaVersion":1}',
                    self.encode().replace(b'"stage": "engine-start"',b'"stage":"engine-start","stage":"engine-start"',1)):
            with self.subTest(bytes=len(raw)),self.assertRaises(ValueError):publisher.validate_bytes(raw)

    def test_unknown_keys_at_every_level_are_rejected(self):
        for path in ((),('cases',0),('cases',0,'failure'),('cases',0,'cleanup')):
            row=copy.deepcopy(self.row);target=row
            for key in path:target=target[key]
            target['message']='SYNTHETIC-NEVER-COPY'
            with self.subTest(depth=len(path)),self.assertRaises(ValueError):publisher.validate_bytes(self.encode(row))

    def test_fixed_module_order_status_and_codebooks_are_required(self):
        rows=[]
        row=copy.deepcopy(self.row);row['cases'].reverse();rows.append(row)
        row=copy.deepcopy(self.row);row['cases'][0]['module']='calc';rows.append(row)
        row=copy.deepcopy(self.row);row['cases'][0]['status']='unknown';rows.append(row)
        for key in ('stage','category'):
            row=copy.deepcopy(self.row);row['cases'][0]['failure'][key]='free-form';rows.append(row)
        for row in rows:
            with self.assertRaises(ValueError):publisher.validate_bytes(self.encode(row))

    def test_nullable_flags_uint32_and_boolean_schema_are_exact(self):
        for key,value in [('launcherExitCode',True),('launcherExitCode',-1),('launcherExitCode',2**32),
                          ('gracefulQualified',1),('forcedTermination','false'),('jobEmptyVerified',0)]:
            row=copy.deepcopy(self.row);row['cases'][0]['cleanup'][key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):publisher.validate_bytes(self.encode(row))
        for key,value in [('schemaVersion',True),('acceptanceEligible',0),('acceptanceEligible',True),('passed',0)]:
            row=copy.deepcopy(self.row);row[key]=value
            with self.subTest(field=key),self.assertRaises(ValueError):publisher.validate_bytes(self.encode(row))

    def test_arrays_counts_and_overall_pass_are_bounded(self):
        error={'stage':'unknown','category':'unknown'}
        for mutate in (lambda r:r['cases'][0].update(finalizationFailures=[error]*3),
                       lambda r:r['cases'][0]['cleanup'].update(errors=[error]*17),
                       lambda r:r['cases'][0].update(cleanupErrorCount=True),
                       lambda r:r['cases'][0].update(cleanupErrorCount=-1),
                       lambda r:r.update(passed=True)):
            row=copy.deepcopy(self.row);mutate(row)
            with self.assertRaises(ValueError):publisher.validate_bytes(self.encode(row))

    def test_codebooks_match_the_unchanged_producer(self):
        tree=ast.parse((ROOT/'suite/e2e/engine_smoke.py').read_text())
        actual={}
        for node in tree.body:
            if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('_FAILURE_STAGES','_ERROR_CATEGORIES'):
                actual[node.targets[0].id]=frozenset(ast.literal_eval(node.value.args[0]))
        self.assertEqual(publisher.STAGES,actual['_FAILURE_STAGES']|{'unknown'})
        self.assertEqual(publisher.CATEGORIES,actual['_ERROR_CATEGORIES']|{'unknown'})

    def test_publish_reads_only_the_fixed_summary_and_copies_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'.work/suite-engine/engine-failure-summary.json'
            source.parent.mkdir(parents=True);source.write_bytes(self.encode())
            (source.parent/'engine-writer.json').write_text('SYNTHETIC-RAW-FORBIDDEN')
            original=Path.open;reads=[]
            def guarded(path,*args,**kwargs):
                mode=args[0] if args else kwargs.get('mode','r')
                if 'r' in mode:
                    if path!=source:raise AssertionError('Unexpected input read')
                    reads.append(1)
                return original(path,*args,**kwargs)
            with mock.patch.object(Path,'open',guarded):receipt=publisher.publish(root,1,'arm64',self.env)
            output=root/'.work/suite-engine-summary-first'
            self.assertEqual((output/'engine-failure-summary.json').read_bytes(),self.encode())
            binding=json.loads((output/'binding.numeric.json').read_bytes())
            self.assertEqual(binding,receipt)
            self.assertEqual(reads,[1])
            self.assertEqual(binding['sourceCommitWords'],[0xaaaaaaaa]*5)
            self.assertEqual((binding['runId'],binding['attempt'],binding['architectureCode'],binding['ordinal']),(123,1,2,1))
            self.assertEqual((binding['acceptanceEligible'],binding['sourceAuthorityQualified'],binding['checkoutVerified']),(0,0,0))

    def test_second_source_and_output_are_separate_and_stale_output_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'.work/suite-engine-2/engine-failure-summary.json'
            source.parent.mkdir(parents=True);source.write_bytes(self.encode())
            publisher.publish(root,2,'x64',self.env)
            self.assertTrue((root/'.work/suite-engine-summary-repeated/binding.numeric.json').is_file())
            with self.assertRaises((ValueError,OSError)):publisher.publish(root,2,'x64',self.env)

    def test_missing_malformed_summary_or_wrong_binding_cannot_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaises((ValueError,OSError)):publisher.publish(root,1,'arm64',self.env)
            source=root/'.work/suite-engine/engine-failure-summary.json';source.parent.mkdir(parents=True)
            source.write_bytes(self.encode()[:-1])
            with self.assertRaises(ValueError):publisher.publish(root,1,'arm64',self.env)
            source.write_bytes(self.encode())
            for key,value in [('GITHUB_REPOSITORY','other/repo'),('GITHUB_JOB','other'),('GITHUB_SHA','not-source'),('GITHUB_RUN_ID','0'),('GITHUB_RUN_ATTEMPT','0')]:
                with self.subTest(field=key),self.assertRaises(ValueError):publisher.publish(root,1,'arm64',{**self.env,key:value})
            self.assertFalse((root/'.work/suite-engine-summary-first').exists())

    def test_cli_never_formats_an_exception_or_outputs_payload(self):
        class Poison(Exception):
            def __str__(self):raise AssertionError('Forbidden formatting')
            def __repr__(self):raise AssertionError('Forbidden formatting')
        stream=io.StringIO()
        with mock.patch.object(publisher,'publish',side_effect=Poison()),mock.patch('sys.stdout',stream):
            code=publisher.main(['--ordinal','1','--architecture','arm64'])
        row=json.loads(stream.getvalue())
        self.assertEqual(code,1)
        self.assertEqual(set(row),{'schemaVersion','diagnosticOnly','acceptanceEligible','errorCode'})
        self.assertTrue(all(type(v) is int for v in row.values()))

    def probe_stream(self,stream,callback):
        class Probe:
            def __enter__(self):return self
            def __exit__(self,*_):stream.close()
            def fileno(self):return stream.fileno()
            def read(self,size=-1):
                raw=stream.read(size);callback();return raw
        return Probe()

    def test_check_to_open_replacement_is_rejected_before_any_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();source=root/'engine-failure-summary.json';other=root/'replacement.json'
            source.write_bytes(self.encode());other.write_bytes(self.encode())
            initial=source.stat();os.utime(other,ns=(initial.st_atime_ns,initial.st_mtime_ns))
            original=Path.open;reads=[]
            def replace_before_open(path,*args,**kwargs):
                if path==source:
                    other.replace(source)
                    return self.probe_stream(original(path,*args,**kwargs),lambda:reads.append(1))
                return original(path,*args,**kwargs)
            with mock.patch.object(Path,'open',replace_before_open),self.assertRaises(ValueError):
                publisher.read_summary(source)
            self.assertEqual(reads,[])

    def test_rename_swap_with_stable_fd_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();source=root/'engine-failure-summary.json';other=root/'replacement.json'
            source.write_bytes(self.encode());other.write_bytes(self.encode())
            initial=source.stat();os.utime(other,ns=(initial.st_atime_ns,initial.st_mtime_ns))
            replacement=other.lstat();original_open=Path.open;original_lstat=Path.lstat;read_started=[]
            def open_probe(path,*args,**kwargs):
                stream=original_open(path,*args,**kwargs)
                return self.probe_stream(stream,lambda:read_started.append(1)) if path==source else stream
            def swapped_lstat(path,*args,**kwargs):
                # Model the current name resolving to a replacement while the
                # originally opened handle remains stable, without Windows rename permissions.
                if path==source and read_started:return replacement
                return original_lstat(path,*args,**kwargs)
            with mock.patch.object(Path,'open',open_probe),mock.patch.object(Path,'lstat',swapped_lstat),self.assertRaises(ValueError):
                publisher.read_summary(source)
            self.assertTrue(read_started)

    def test_read_time_mutation_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();source=root/'engine-failure-summary.json';source.write_bytes(self.encode())
            initial=source.stat();original=Path.open;changed=[]
            def mutate():
                if not changed:
                    with original(source,'r+b') as writer:writer.write(b' ')
                    os.utime(source,ns=(initial.st_atime_ns,initial.st_mtime_ns+1000000000));changed.append(1)
            def open_probe(path,*args,**kwargs):
                stream=original(path,*args,**kwargs)
                return self.probe_stream(stream,mutate) if path==source else stream
            with mock.patch.object(Path,'open',open_probe),self.assertRaises(ValueError):publisher.read_summary(source)
            self.assertEqual(changed,[1])


class SummaryWorkflowTests(unittest.TestCase):
    def setUp(self):self.source=(ROOT/'.github/workflows/office-suite.yml').read_text()

    def test_four_supplemental_steps_keep_failures_visible_and_upload_after_validation(self):
        for suffix in ('first','repeated'):
            validation='engine-summary-'+suffix+'-validation';upload='engine-summary-'+suffix+'-evidence'
            steps=re.split(r'^    - name: ',self.source,flags=re.M)
            selected={name:next((s for s in steps if '\n      id: '+name+'\n' in s),'') for name in (validation,upload)}
            for step in selected.values():
                self.assertTrue(step)
                self.assertNotIn('      continue-on-error:',step)
            self.assertIn('always() && steps.build.outcome',selected[validation])
            self.assertIn("always() && steps."+validation+".outcome == 'success'",selected[upload])
            self.assertIn('path: .work/suite-engine-summary-'+suffix+'/',selected[upload])
            self.assertIn('opengeul-suite-engine-summary-'+suffix+'-${{ matrix.architecture }}-${{ github.run_id }}-${{ github.run_attempt }}',selected[upload])

    def actual_policy(self):
        spec=importlib.util.spec_from_file_location('actual_ci_policy',ROOT/'ci/policy.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_actual_policy_accepts_real_workflow(self):
        policy=self.actual_policy()
        self.policy_audit_error_code=0
        try:result=policy.audit(policy.load_workflow(ROOT/'.github/workflows/office-suite.yml'),workflow_path='.github/workflows/office-suite.yml')
        except ValueError:
            self.policy_audit_error_code=1
            raise
        self.assertIs(result,True)

    def test_actual_policy_rejects_synthetic_failure_suppression(self):
        policy=self.actual_policy()
        row={'on':['push'],'jobs':{'check':{'if':policy.PUBLIC,'runs-on':'windows-2022',
             'timeout-minutes':1,'steps':[{'run':'synthetic read-only check'}]}}}
        self.assertIs(policy.audit(row),True)
        for value in (True,'true','TRUE',1):
            changed=copy.deepcopy(row);changed['jobs']['check']['steps'][0]['continue-on-error']=value
            with self.subTest(value=value),self.assertRaises(ValueError):policy.audit(changed)

    def test_exact_inverse_retains_original_pinned_oracle(self):
        from suite.tests.workflow_scope import suite_workflow_sections
        from suite.tests.reviewed_normal_workflow import original_normal_oracle_text,_without_engine_summary_artifacts
        normal=suite_workflow_sections(self.source)[1]
        self.assertNotEqual(normal,_without_engine_summary_artifacts(normal))
        expected=json.loads((ROOT/'suite/tests/fixtures/writer-server-observer-normal-workflow.json').read_bytes())['normalJobTextSha256']
        self.assertEqual(hashlib.sha256(original_normal_oracle_text(normal).encode()).hexdigest(),expected)

    def test_inverse_rejects_duplicate_modified_or_relocated_new_steps(self):
        from suite.tests.workflow_scope import suite_workflow_sections
        from suite.tests.reviewed_normal_workflow import _without_engine_summary_artifacts,ENGINE_SUMMARY_FIRST_BLOCK
        normal=suite_workflow_sections(self.source)[1]
        for bad in (normal+ENGINE_SUMMARY_FIRST_BLOCK,normal.replace('--ordinal 1','--ordinal 2',1),
                    normal.replace('      id: engine-repeat\n','',1),
                    normal.replace(ENGINE_SUMMARY_FIRST_BLOCK,'',1)+ENGINE_SUMMARY_FIRST_BLOCK):
            with self.assertRaises(ValueError):_without_engine_summary_artifacts(bad)


if __name__=='__main__':unittest.main()
