"""Synthetic public PR objects and owned local Git fixtures; never network/UI."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

BASE=Path(__file__).resolve().parents[1]
def module():
    spec=importlib.util.spec_from_file_location('fixed_runner_pr_binding',BASE/'e2e/runner-ready.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

class SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.m=module();self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.repo=self.root/'repo';self.repo.mkdir()
        self.git=shutil.which('git');self.assertIsNotNone(self.git)
        self.environment={'PATH':os.environ.get('PATH',os.defpath),'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,'GIT_TERMINAL_PROMPT':'0'}
        for key in('SystemRoot','WINDIR','SystemDrive','ComSpec','TEMP','TMP'):
            if key in os.environ:self.environment[key]=os.environ[key]
        self.command('init','-q')
        self.tree=self.command('hash-object','-t','tree','-w','--stdin',data=b'').decode().strip()
        self.base=self.commit([]);self.head=self.commit([self.base],message=b'synthetic head\n')
        self.raw=self.body([self.base,self.head]);self.merge=self.object(self.raw)
        self.command('update-ref','HEAD',self.merge)
    def command(self,*args,data=None):
        result=subprocess.run([self.git,'-C',str(self.repo),*args],input=data,env=self.environment,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5)
        self.assertEqual(result.returncode,0,'Synthetic Git fixture command failed');return result.stdout
    def body(self,parents,message=b'synthetic merge\n'):
        return(('tree '+self.tree+'\n'+''.join('parent '+p+'\n'for p in parents)+'author Synthetic <synthetic@example.invalid> 1 +0000\ncommitter Synthetic <synthetic@example.invalid> 1 +0000\n\n').encode()+message)
    def object(self,raw):return self.command('hash-object','-t','commit','-w','--stdin',data=raw).decode().strip()
    def commit(self,parents,message=b'synthetic base\n'):return self.object(self.body(parents,message))
    def prove(self,source=None,base=None,head=None,root=None):
        self.assertTrue(callable(getattr(self.m,'checkout_merge_context',None)),'Local source proof required')
        return self.m.checkout_merge_context(source or self.merge,base or self.base,head or self.head,root=root or self.repo)
    def event(self,metadata=None):
        repo={'full_name':'ATLKR/OpenGeul','private':False,'id':1};actor={'login':'public-contributor','id':91827364,'type':'User'}
        event={'repository':repo,'sender':actor,'number':17,'pull_request':{'number':17,'head':{'repo':repo,'ref':'work/change','sha':self.head},'base':{'repo':repo,'ref':'main','sha':self.base},'merge_commit_sha':metadata}}
        path=self.root/'event.json';path.write_text(json.dumps(event))
        env={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_EVENT_NAME':'pull_request','GITHUB_REF':'refs/pull/17/merge','GITHUB_ACTOR':actor['login'],'GITHUB_ACTOR_ID':str(actor['id']),'GITHUB_SHA':self.merge,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_JOB':'native-e2e-arm64','GITHUB_EVENT_PATH':str(path),'GITHUB_WORKFLOW_REF':'ATLKR/OpenGeul/.github/workflows/msix.yml@refs/pull/17/merge'}
        return event,env
    def test_valid_optional_metadata_difference_uses_actual_source_proof(self):
        _,env=self.event('d'*40)
        with mock.patch.object(self.m,'checkout_merge_context',return_value=None,create=True)as proof:
            value=self.m.binding(env)
        self.assertEqual(value['sourceCommit'],self.merge);proof.assert_called_once_with(self.merge,self.base,self.head)
    def test_null_optional_metadata_still_requires_actual_proof(self):
        _,env=self.event(None)
        with mock.patch.object(self.m,'checkout_merge_context',side_effect=ValueError('fixed source failure'),create=True)as proof:
            with self.assertRaises(ValueError):self.m.binding(env)
        self.assertEqual(proof.call_count,1)
    def test_matching_metadata_cannot_substitute_invalid_actual_proof(self):
        _,env=self.event(self.merge)
        with mock.patch.object(self.m,'checkout_merge_context',side_effect=ValueError('fixed source failure'),create=True):
            with self.assertRaises(ValueError):self.m.binding(env)
    def test_invalid_optional_metadata_stays_rejected(self):
        for bad in('',True,'A'*40,'0'*40,17,{},'bad'):
            _,env=self.event(bad)
            with self.assertRaises(ValueError):self.m.binding(env)
    def test_real_local_checkout_and_original_two_parents_pass(self):self.prove()
    def test_head_and_expected_parent_mismatches_rejected(self):
        for source,base,head in((self.head,self.base,self.head),(self.merge,'d'*40,self.head),(self.merge,self.base,'d'*40),(self.merge,self.head,self.base)):
            with self.assertRaises(ValueError):self.prove(source,base,head)
    def test_original_parent_count_duplicate_and_order_fail_closed(self):
        for parents in([], [self.base], [self.base,self.head,'d'*40], [self.base,self.base], [self.head,self.base]):
            merge=self.commit(parents);self.command('update-ref','HEAD',merge)
            with self.assertRaises(ValueError):self.prove(merge)
    def test_shallow_raw_headers_work_without_parent_objects(self):
        (self.repo/'.git/shallow').write_text(self.merge+'\n')
        for value in(self.base,self.head):(self.repo/'.git/objects'/value[:2]/value[2:]).unlink()
        traversal=self.command('rev-list','--parents','-n','1','HEAD').split()
        self.assertEqual(len(traversal),1)
        self.prove()
    def test_replacement_cannot_change_original_commit_identity(self):
        wrong=self.commit([self.head,self.base]);self.command('replace',self.merge,wrong)
        self.prove()
        self.command('replace','-d',self.merge);self.command('update-ref','HEAD',wrong);self.command('replace',wrong,self.merge)
        with self.assertRaises(ValueError):self.prove(wrong)
    def test_alias_and_wrong_root_rejected(self):
        other=self.repo/'subdir';other.mkdir()
        with self.assertRaises(ValueError):self.prove(root=other)
        if os.name!='nt':
            alias=self.root/'alias';alias.symlink_to(self.repo,target_is_directory=True)
            with self.assertRaises(ValueError):self.prove(root=alias)
        else:
            original=Path.lstat
            def lstat(path,*args,**options):
                value=original(path,*args,**options)
                if path==self.repo:
                    from types import SimpleNamespace
                    return SimpleNamespace(st_mode=value.st_mode,st_file_attributes=0x400)
                return value
            with mock.patch.object(Path,'lstat',lstat),self.assertRaises(ValueError):self.prove()
    def test_non_commit_and_missing_object_rejected(self):
        self.command('update-ref','HEAD',self.merge)
        with self.assertRaises(ValueError):self.prove('d'*40)
        # The parser independently requires the actual object type, not coercion.
        self.assertTrue(callable(getattr(self.m,'source_commit_parents',None)))
        for raw in(self.raw+b'x',b'tree '+self.tree.encode()+b'\n\nmessage'):
            with self.assertRaises(ValueError):self.m.source_commit_parents(raw,self.merge)
    def test_header_parser_ignores_message_and_signature_parent_like_text(self):
        self.assertTrue(callable(getattr(self.m,'source_commit_parents',None)))
        raw=self.raw.replace(b'\n\n',b'\ngpgsig synthetic\n parent '+b'e'*40+b'\n\n',1)+b'parent '+b'f'*40+b'\n'
        oid=hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        self.assertEqual(self.m.source_commit_parents(raw,oid),(self.base,self.head))
    def test_oversize_and_bad_headers_rejected(self):
        self.assertTrue(callable(getattr(self.m,'source_commit_parents',None)))
        for raw in(self.raw+b'x'*(256*1024),self.raw.replace(b'parent ',b'parent\t',1),self.raw.replace(b'\n\n',b'\r\n\r\n'),self.raw.replace(b'tree ',b'unknown ',1)):
            oid=hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
            with self.assertRaises(ValueError):self.m.source_commit_parents(raw,oid)
    def test_source_arguments_rejected_before_any_git_invocation(self):
        self.assertTrue(callable(getattr(self.m,'checkout_merge_context',None)))
        with mock.patch.object(self.m.subprocess,'Popen')as process:
            for value in('a'*39,'A'*40,'0'*40,'--bad','a'*40+'\n'):
                with self.assertRaises(ValueError):self.m.checkout_merge_context(value,self.base,self.head,root=self.repo)
        self.assertEqual(process.call_count,0)
    def test_git_failure_and_timeout_are_static_and_have_no_stream_output(self):
        self.assertTrue(callable(getattr(self.m,'source_git',None)))
        for error in(OSError('SYNTHETIC_PRIVATE_SENTINEL'),subprocess.TimeoutExpired('SYNTHETIC_PRIVATE_SENTINEL',1)):
            with mock.patch.object(self.m.subprocess,'Popen',side_effect=error):
                with self.assertRaises(ValueError)as caught:self.prove()
            self.assertNotIn('SYNTHETIC_PRIVATE_SENTINEL',str(caught.exception))
    def test_source_child_environment_has_only_approved_nonsecret_names(self):
        self.assertTrue(callable(getattr(self.m,'source_git_environment',None)))
        with mock.patch.object(os,'environ',{'PATH':'synthetic path','SystemRoot':'synthetic windows','SYNTHETIC_SERVICE_TOKEN':'SYNTHETIC_PRIVATE_SENTINEL','GIT_DIR':'unapproved'}):
            env=self.m.source_git_environment()
        self.assertNotIn('SYNTHETIC_SERVICE_TOKEN',env);self.assertNotIn('GIT_DIR',env)
        self.assertEqual(env['GIT_TERMINAL_PROMPT'],'0');self.assertEqual(env['GIT_NO_LAZY_FETCH'],'1')
    def test_fixed_git_argv_and_expired_budget_never_spawn(self):
        with mock.patch.object(self.m.subprocess,'Popen')as spawn:
            with self.assertRaises(ValueError):self.m.source_git(self.repo,'content','--invalid',time.monotonic()+1)
            with self.assertRaises(ValueError):self.m.source_git(self.repo,'foreign',self.merge,time.monotonic()+1)
            with self.assertRaises(ValueError):self.m.source_git(self.repo,'identity',self.merge,time.monotonic()-1)
        self.assertEqual(spawn.call_count,0)
        original=self.m.subprocess.Popen;calls=[]
        def create(command,**options):calls.append((command,options));return original(command,**options)
        with mock.patch.object(self.m.subprocess,'Popen',side_effect=create):self.prove()
        self.assertEqual(len(calls),5)
        allowed=(('rev-parse','--show-toplevel','--verify','HEAD'),('cat-file','-t',self.merge),('cat-file','-s',self.merge),('cat-file','commit',self.merge))
        for command,options in calls:
            self.assertEqual(command[1:6],['--no-pager','--no-replace-objects','--no-lazy-fetch','-C',str(self.repo)])
            self.assertIn(tuple(command[6:]),allowed)
            self.assertIs(options['stderr'],subprocess.DEVNULL);self.assertIs(options['stdin'],subprocess.DEVNULL)
            self.assertNotIn('shell',options)
    def test_real_owned_overflow_and_wait_budget_fail_without_output_or_live_child(self):
        original=subprocess.Popen;owned=[]
        for mode in('overflow','deadline'):
            def launch(command,**options):
                script="import sys,time;sys.stdout.write('x'*100);sys.stdout.flush();time.sleep(10)"if mode=='overflow'else'import time;time.sleep(10)'
                process=original([sys.executable,'-I','-B','-c',script],**options);owned.append(process);return process
            with mock.patch.object(self.m.subprocess,'Popen',side_effect=launch):
                with self.assertRaises(ValueError):self.m.source_git(self.repo,'type',self.merge,time.monotonic()+(2 if mode=='overflow'else .2))
        self.assertTrue(all(process.poll()is not None for process in owned))
    def test_mutating_checkout_head_before_final_identity_rejected(self):
        original=self.m.source_git;seen=[]
        def read(root,operation,source,deadline):
            raw=original(root,operation,source,deadline);seen.append(operation)
            if operation=='content':self.command('update-ref','HEAD',self.head)
            return raw
        with mock.patch.object(self.m,'source_git',side_effect=read),self.assertRaises(ValueError):self.prove()
        self.assertEqual(seen,['identity','type','size','content','identity'])
    def test_wrong_type_and_declared_oversize_stop_before_content(self):
        original=self.m.source_git
        for changed,value in(('type',b'blob\n'),('size',b'262145\n')):
            operations=[]
            def read(root,operation,source,deadline):
                operations.append(operation)
                return value if operation==changed else original(root,operation,source,deadline)
            with mock.patch.object(self.m,'source_git',side_effect=read),self.assertRaises(ValueError):self.prove()
            self.assertNotIn('content',operations)
    def test_invalid_source_proof_precedes_windows_probe_constructor(self):
        _,env=self.event(self.merge)
        with mock.patch.object(os,'environ',env),mock.patch.object(sys,'argv',['fixed-runner-ready','--prepare','--output','unused']),mock.patch.object(self.m,'checkout_merge_context',side_effect=ValueError('fixed proof failure'),create=True),mock.patch.object(self.m,'WindowsProbe')as probe:
            with self.assertRaises(ValueError):self.m.main()
        self.assertEqual(probe.call_count,0)

class NumericResult(unittest.TestResult):
    def __init__(self):super().__init__();self.closed=[]
    def addError(self,test,err):self.errors.append((test,''));self.closed.append(dict(test=test._testMethodName,kind=1,errorType=err[0].__name__))
    def addFailure(self,test,err):self.failures.append((test,''));self.closed.append(dict(test=test._testMethodName,kind=2,errorType=err[0].__name__))
    def addSubTest(self,test,subtest,err):
        if err is not None:self.addFailure(test,err)if issubclass(err[0],AssertionError)else self.addError(test,err)

if __name__=='__main__':
    allowed={k:v for k in('PATH','SystemRoot','WINDIR','SystemDrive','ComSpec','TEMP','TMP')if(v:=os.environ.get(k))is not None}
    os.environ=allowed
    result=NumericResult();unittest.defaultTestLoader.loadTestsFromTestCase(SourceBindingTests).run(result)
    print(json.dumps(dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),descriptors=result.closed),separators=(',',':')))
    raise SystemExit(0 if result.wasSuccessful()else 1)
