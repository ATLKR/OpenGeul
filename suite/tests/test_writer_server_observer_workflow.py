"""Static workflow preservation and synthetic admission/report regressions."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import ast
import contextlib
import copy
import io
import os
import shutil
import subprocess
from unittest import mock

BASE=Path(__file__).resolve().parents[2]
CANDIDATE=BASE/'.github/workflows/office-suite.yml'
BRANCH='work/opengeul-office-native-writer-observer-suite-9dea'
PRODUCER_BRANCH='work/opengeul-office-native-writer-observer-9dea'
FIXTURE=BASE/'suite/tests/fixtures/writer-server-observer-normal-workflow.json'
FIXTURE_SHA256='191eb38642ecdc5d885815cea9567c70cdd49c7950d325403e143db113b62e2c'
MARKER='[opengeul-writer-observer-9dea-run]'
REQUEST='suite/config/writer-server-observer-9dea/run-request.json'


def module():
    path=BASE/'suite/scripts/writer-server-observer-workflow.py'
    if not path.is_file():raise AssertionError('Writer workflow helper is absent')
    spec=importlib.util.spec_from_file_location('writer_workflow_candidate',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def context():
    head='1'*40
    return {'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_ACTOR':'ATLKR','GITHUB_ACTOR_ID':'65988341',
        'GITHUB_TRIGGERING_ACTOR':'ATLKR','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1',
        'GITHUB_REF':'refs/heads/'+BRANCH,'GITHUB_SHA':head,'GITHUB_WORKFLOW_SHA':head,
        'GITHUB_WORKFLOW_REF':'ATLKR/OpenGeul/.github/workflows/office-suite.yml@refs/heads/'+BRANCH,
        'WRITER_OBSERVER_ENABLED':'true','WRITER_OBSERVER_SUITE_HEAD':head}


def event():
    return {'repository':{'full_name':'ATLKR/OpenGeul','id':1405493151,'private':False},
        'sender':{'login':'ATLKR','id':65988341,'type':'User'}}


def original_push_prefix(source):
    prefix=source.split('  workflow_dispatch:',1)[0]
    addition='    - '+BRANCH+'\n'
    if prefix.count(addition)!=1:raise ValueError('Exact reviewed request branch required')
    return prefix.replace(addition,'',1)


class GitFixture:
    """Synthetic local objects only; never an actual observer input lock."""
    def __enter__(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.repo=self.root/'repo';self.repo.mkdir();profile=self.root/'profile';profile.mkdir()
        self.git_exe=shutil.which('git')
        if not self.git_exe:raise AssertionError('Existing Git is required')
        self.environment={'PATH':str(Path(self.git_exe).parent),'HOME':str(profile),'USERPROFILE':str(profile),
            'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,'GIT_TERMINAL_PROMPT':'0',
            'GIT_NO_LAZY_FETCH':'1','GIT_ALLOW_PROTOCOL':'','GIT_AUTHOR_NAME':'Synthetic fixture',
            'GIT_COMMITTER_NAME':'Synthetic fixture','GIT_AUTHOR_EMAIL':'fixture@example.invalid',
            'GIT_COMMITTER_EMAIL':'fixture@example.invalid','GIT_AUTHOR_DATE':'2000-01-01T00:00:00+0000',
            'GIT_COMMITTER_DATE':'2000-01-01T00:00:00+0000'}
        if os.name=='nt':
            for key in ('SystemRoot','WINDIR'):
                value=os.environ.get(key)
                if type(value)is str and 0<len(value)<=32767 and not any(ord(c)<32 for c in value):self.environment[key]=value
        self.real_run=subprocess.run
        self.git('init','-q','--object-format=sha1');self.git('config','core.autocrlf','false')
        self.git('config','core.ignorecase','false')
        (self.repo/'reviewed.py').write_bytes(b'SYNTHETIC REVIEWED CODE\n')
        (self.repo/'fixture-lock.json').write_bytes(b'SYNTHETIC SOURCE LOCK BYTES\n')
        self.git('add','.');self.git('commit','-qm','Synthetic reviewed parent')
        self.parent=self.git('rev-parse','HEAD').decode().strip()
        return self
    def __exit__(self,*args):self.temporary.cleanup()
    def git(self,*args,data=None):
        return self.real_run([self.git_exe,'-c','core.hooksPath='+os.devnull,'-c','commit.gpgSign=false',*args],
            cwd=self.repo,env=self.environment,input=data,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            check=True,timeout=10).stdout
    def request(self,*,raw=None,name=REQUEST,message=MARKER,executable=False,extra=None):
        value=dict(schemaVersion=1,kind='writer-server-observer-run-request',reviewedParentCommit=self.parent,phaseSeconds=900)
        target=self.repo/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(json.dumps(value).encode()if raw is None else raw)
        if extra is not None:(self.repo/extra).write_bytes(b'OTHER CHANGE\n')
        self.git('add','.')
        if executable:self.git('update-index','--chmod=+x',name)
        self.git('commit','-qm',message)
        self.head=self.git('rev-parse','HEAD').decode().strip()
        return self.head
    def push_event(self):
        return {**event(),'ref':'refs/heads/'+BRANCH,'before':self.parent,'after':self.head,
            'created':False,'deleted':False,'forced':False,
            'head_commit':dict(id=self.head,message=MARKER),'commits':[dict(id=self.head)]}
    def push_values(self):
        values=context();values.update(GITHUB_REPOSITORY_OWNER='ATLKR',GITHUB_EVENT_NAME='push',
            GITHUB_SHA=self.head,GITHUB_WORKFLOW_SHA=self.head,WRITER_OBSERVER_ENABLED='',WRITER_OBSERVER_SUITE_HEAD='')
        return values
    @contextlib.contextmanager
    def commands(self,m):
        calls=[]
        def run(*args,**kwargs):
            calls.append(args[0]);kwargs['env']=self.environment
            return self.real_run(*args,**kwargs)
        with mock.patch.object(m.subprocess,'run',run):yield calls


class RequestPush(unittest.TestCase):
    def api(self,name):
        m=module();self.assertTrue(callable(getattr(m,name,None)),'Missing request admission API');return m
    def test_valid_request_retains_actual_t_and_explicit_phase(self):
        m=self.api('verify_request_source')
        with GitFixture()as f:
            f.request();values=f.push_values();ev=f.push_event()
            self.assertTrue(m.require_push_context(values,ev))
            with f.commands(m)as calls:
                self.assertEqual(m.verify_request_source(f.repo,f.head,ev),(3,900))
                self.assertEqual(m.verify_source(f.repo,f.head),3)
            self.assertEqual(values['GITHUB_SHA'],f.head);self.assertNotEqual(f.head,f.parent)
            self.assertTrue(all('--no-replace-objects'in command for command in calls))
    def test_push_authority_metadata_and_marker_are_closed(self):
        m=self.api('require_push_context')
        with GitFixture()as f:
            f.request();values=f.push_values();ev=f.push_event();self.assertTrue(m.require_push_context(values,ev))
            for key in ('GITHUB_REPOSITORY','GITHUB_REPOSITORY_OWNER','GITHUB_ACTOR','GITHUB_ACTOR_ID',
                    'GITHUB_TRIGGERING_ACTOR','GITHUB_EVENT_NAME','GITHUB_RUN_ATTEMPT','GITHUB_REF','GITHUB_SHA','GITHUB_WORKFLOW_SHA','GITHUB_WORKFLOW_REF'):
                bad=dict(values);bad[key]='wrong'
                with self.subTest(key=key),self.assertRaises(m.Rejected):m.require_push_context(bad,ev)
            changes=[lambda e:e.update(before='0'*40),lambda e:e.update(after='e'*40),
                lambda e:e.update(created=True),lambda e:e.update(deleted=True),lambda e:e.update(forced=True),
                lambda e:e.update(created=0),lambda e:e.update(commits=[]),lambda e:e['commits'].append(dict(id='f'*40)),
                lambda e:e['head_commit'].update(id='f'*40),lambda e:e['head_commit'].update(message=MARKER+' body'),
                lambda e:e['head_commit'].update(message=MARKER+'\n\n'),lambda e:e.update(ref='refs/heads/main'),
                lambda e:e['repository'].update(private=True),lambda e:e['sender'].update(id=True)]
            for i,change in enumerate(changes):
                bad=copy.deepcopy(ev);change(bad)
                with self.subTest(change=i),self.assertRaises(m.Rejected):m.require_push_context(values,bad)
            ev['head_commit']['message']=MARKER+'\n';self.assertTrue(m.require_push_context(values,ev))
    def test_request_schema_and_blob_cap_reject_before_filesystem_verification(self):
        m=self.api('verify_request_source')
        for code in ('duplicate','extra','bool','string','float','low','high','parent','size','utf8'):
            with self.subTest(case=code),GitFixture()as f:
                d=dict(schemaVersion=1,kind='writer-server-observer-run-request',reviewedParentCommit=f.parent,phaseSeconds=900)
                if code=='extra':d['other']=False
                if code in('bool','string','float','low','high'):d['phaseSeconds']={'bool':True,'string':'900','float':900.0,'low':5,'high':1201}[code]
                if code=='parent':d['reviewedParentCommit']='f'*40
                raw=json.dumps(d).encode()
                if code=='duplicate':raw=raw[:-1]+b',"phaseSeconds":900}'
                if code=='size':raw+=b' '*1025
                if code=='utf8':raw=b'\xff'
                f.request(raw=raw)
                with f.commands(m)as calls,mock.patch.object(m,'verify_tracked_rows',side_effect=AssertionError('Filesystem reached'))as tracked:
                    with self.assertRaises(m.Rejected):m.verify_request_source(f.repo,f.head,f.push_event())
                tracked.assert_not_called()
                if code=='size':self.assertFalse(any('blob'in command for command in calls if 'cat-file'in command))
    def test_other_tree_changes_and_request_alias_or_mode_are_rejected(self):
        m=self.api('verify_request_source')
        for code in ('code','lock','foreign','alias','mode','raw-message'):
            with self.subTest(case=code),GitFixture()as f:
                name=REQUEST.upper()if code=='alias'else REQUEST
                extra={'code':'reviewed.py','lock':'fixture-lock.json','foreign':'foreign.txt'}.get(code)
                f.request(name=name,extra=extra,executable=code=='mode',message=MARKER+' body'if code=='raw-message'else MARKER)
                with f.commands(m),self.assertRaises(m.Rejected):m.verify_request_source(f.repo,f.head,f.push_event())
    def test_old_request_merge_missing_parent_and_replace_tricks_are_rejected(self):
        m=self.api('verify_request_source')
        for code in ('old','merge','missing','replace'):
            with self.subTest(case=code),GitFixture()as f:
                f.request();good=f.head
                if code=='old':
                    f.parent=f.head;(f.repo/REQUEST).write_bytes(b'CHANGED REQUEST');f.git('add','.');f.git('commit','-qm',MARKER);f.head=f.git('rev-parse','HEAD').decode().strip()
                else:
                    tree=f.git('rev-parse',good+'^{tree}').decode().strip()
                    parent=f.parent if code!='missing'else'f'*40
                    parents='parent '+parent+'\n'+('parent '+good+'\n'if code=='merge'else'')
                    raw=('tree '+tree+'\n'+parents+'author Synthetic <fixture@example.invalid> 1 +0000\ncommitter Synthetic <fixture@example.invalid> 1 +0000\n\n'+MARKER+'\n').encode()
                    if code=='replace':raw=raw.replace((MARKER+'\n').encode(),b'UNREVIEWED MESSAGE\n')
                    f.head=f.git('hash-object','-t','commit','-w','--stdin',data=raw).decode().strip();f.git('update-ref','HEAD',f.head)
                    if code=='missing':f.parent=parent
                    if code=='replace':f.git('replace',f.head,good)
                with f.commands(m),self.assertRaises(m.Rejected):m.verify_request_source(f.repo,f.head,f.push_event())
    def test_dirty_source_and_request_alias_are_rejected(self):
        m=self.api('verify_request_source')
        with GitFixture()as f:
            f.request();(f.repo/'reviewed.py').write_bytes(b'DIRTY')
            with f.commands(m),self.assertRaises(m.Rejected):m.verify_request_source(f.repo,f.head,f.push_event())
        with GitFixture()as f:
            f.request();p=f.repo/REQUEST;p.unlink();p.symlink_to(f.repo/'reviewed.py')
            with f.commands(m),self.assertRaises(m.Rejected):m.verify_request_source(f.repo,f.head,f.push_event())
    def test_graph_and_tracked_bytes_use_one_original_deadline(self):
        m=self.api('verify_request_source')
        with GitFixture()as f:
            f.request();now=[100.0];original=m.verify_tracked_rows
            def tracked(root,rows,*,check):now[0]=131.0;return original(root,rows,check=check)
            with f.commands(m),mock.patch.object(m.time,'monotonic',lambda:now[0]),mock.patch.object(m,'verify_tracked_rows',tracked):
                with self.assertRaises(m.Rejected):m.verify_request_source(f.repo,f.head,f.push_event())
    def test_manual_phase_and_clean_output_are_exact(self):
        m=self.api('phase_seconds')
        for value,expected in (('6',6),('900',900),('1200',1200)):self.assertEqual(m.phase_seconds(value),expected)
        for value in ('','05','0900','5','1201','+6','6.0','6\n',' 6','６',True):
            with self.subTest(valueType=type(value).__name__),self.assertRaises(m.Rejected):m.phase_seconds(value)
        with tempfile.TemporaryDirectory()as directory:
            p=Path(directory)/'output';p.touch();m.write_phase_output(p,900)
            self.assertEqual(p.read_bytes(),b'phase_seconds=900\n')
            with self.assertRaises(m.Rejected):m.write_phase_output(p,900)
            with self.assertRaises(m.Rejected):m.write_phase_output(p.with_name('missing'),900)
            p.write_bytes(b'');os.link(p,p.with_name('alias'))
            with self.assertRaises(m.Rejected):m.write_phase_output(p,900)
        with tempfile.TemporaryDirectory()as directory:
            p=Path(directory)/'output';p.touch()
            with mock.patch.object(m.os,'open',side_effect=PermissionError()),self.assertRaises(m.Rejected):m.write_phase_output(p,900)

    def test_output_alias_and_partial_write_fail_closed(self):
        m=module()
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);target=root/'target';target.touch();alias=root/'alias';alias.symlink_to(target)
            with self.assertRaises(m.Rejected):m.write_phase_output(alias,900)
            self.assertEqual(target.read_bytes(),b'')
            write=m.os.write
            with mock.patch.object(m.os,'write',lambda fd,raw:write(fd,raw[:2])),self.assertRaises(m.Rejected):m.write_phase_output(target,900)

    def test_phase_output_requests_native_binary_mode(self):
        m=module();native_binary=getattr(m.os,'O_BINARY',0);sentinel=1<<29
        self.assertEqual(native_binary&sentinel,0)
        real_open=m.os.open;opened=[]
        def open_binary(path,flags,*args,**kwargs):
            opened.append(flags)
            forwarded=flags&~sentinel
            if flags&sentinel:forwarded|=native_binary
            return real_open(path,forwarded,*args,**kwargs)
        with tempfile.TemporaryDirectory()as directory:
            path=Path(directory)/'output';path.touch();admitted=True
            with mock.patch.object(m.os,'O_BINARY',sentinel,create=True),mock.patch.object(m.os,'open',open_binary):
                try:m.write_phase_output(path,900)
                except m.Rejected:admitted=False
            # Assert outside the helper's rejection boundary. Restore the real
            # Windows binary bit when forwarding the synthetic portable flag.
            self.assertEqual(len(opened),1);self.assertTrue(opened[0]&sentinel)
            self.assertTrue(admitted);self.assertEqual(path.read_bytes(),b'phase_seconds=900\n')

    def test_admit_entry_both_routes_emit_only_fully_validated_phase(self):
        m=module()
        class Poison(dict):
            def forbidden(self,*args,**kwargs):raise AssertionError('Original environment traversal forbidden')
            copy=__iter__=keys=items=values=forbidden
        for route in ('manual','push','dirty','bad-context','bad-phase','missing-output'):
            with self.subTest(route=route),GitFixture()as f:
                if route=='push':f.request();values=f.push_values();ev=f.push_event()
                else:
                    f.head=f.parent;values=context();values.update(GITHUB_SHA=f.head,GITHUB_WORKFLOW_SHA=f.head,WRITER_OBSERVER_SUITE_HEAD=f.head)
                    ev=event()
                values['WRITER_OBSERVER_PHASE_SECONDS']='0900'if route=='bad-phase'else'900'
                if route=='bad-context':values['GITHUB_ACTOR']='wrong'
                if route=='dirty':(f.repo/'reviewed.py').write_bytes(b'DIRTY')
                event_path=f.root/'event.json';event_path.write_text(json.dumps(ev));output=f.root/'step-output';output.touch()
                values.update(GITHUB_EVENT_PATH=str(event_path),GITHUB_OUTPUT=str(output))
                if route=='missing-output':values.pop('GITHUB_OUTPUT')
                receipt_path=f.root/'context.numeric.json';capture=io.StringIO()
                with f.commands(m),contextlib.chdir(f.repo),mock.patch.object(m.os,'environ',Poison(values)),contextlib.redirect_stdout(capture):
                    result=m.main(['admit','--output',str(receipt_path)])
                receipt=json.loads(capture.getvalue());self.assertEqual(receipt,json.loads(receipt_path.read_bytes()))
                self.assertEqual(set(receipt),{'schemaVersion','stageCode','passed','sourceFileCount','errorCode',
                    'normalAcceptance','fullEngineQualified','acceptanceEligible','guiVerified'})
                self.assertTrue(all(receipt[k]is False for k in ('normalAcceptance','fullEngineQualified','acceptanceEligible','guiVerified')))
                admitted=route in('manual','push');self.assertEqual(result,0 if admitted else 1)
                self.assertEqual(output.read_bytes(),b'phase_seconds=900\n'if admitted else b'')
                if route=='dirty':self.assertEqual(receipt['stageCode'],1)

    def test_parent_request_case_alias_is_not_reviewed_code(self):
        m=module()
        with GitFixture()as f:
            alias=f.repo/REQUEST.upper();alias.parent.mkdir(parents=True);alias.write_bytes(b'SYNTHETIC OLD REQUEST')
            f.git('add','.');f.git('commit','-qm','Synthetic parent alias');f.parent=f.git('rev-parse','HEAD').decode().strip()
            f.request()
            with f.commands(m),self.assertRaises(m.Rejected):m.verify_request_source(f.repo,f.head,f.push_event())

    def test_nonfinite_and_regressed_clock_reject(self):
        m=module()
        for times in ((100.0,float('nan')),(100.0,float('inf')),(100.0,99.0)):
            with self.subTest(clockCase=len(times)),GitFixture()as f:
                f.request()
                with f.commands(m),mock.patch.object(m.time,'monotonic',side_effect=times),self.assertRaises(m.Rejected):
                    m.verify_request_source(f.repo,f.head,f.push_event())


class Workflow(unittest.TestCase):
    def test_regression_oracle_uses_no_machine_specific_source_checkout(self):
        tree=ast.parse(Path(__file__).read_text())
        absolute_calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and
            isinstance(node.func,ast.Name) and node.func.id=='Path' and node.args and
            isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str) and
            node.args[0].value.startswith('/workspace/')]
        self.assertEqual(absolute_calls,[])
    def candidate(self):
        self.assertTrue(CANDIDATE.is_file(),'Writer manual job candidate is absent')
        return CANDIDATE.read_text()

    def test_normal_job_and_existing_workflow_contract_are_preserved(self):
        raw=FIXTURE.read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),FIXTURE_SHA256)
        fixture=json.loads(raw);candidate=self.candidate()
        actual=candidate.split('jobs:\n',1)[1].split('\n  writer-server-observer:',1)[0]
        from suite.tests.reviewed_normal_workflow import original_normal_oracle_text
        actual=original_normal_oracle_text(actual)
        self.assertEqual(hashlib.sha256(actual.encode()).hexdigest(),fixture['normalJobTextSha256'])
        self.assertIn("permissions:\n  contents: read\n  actions: read\n",candidate)
        self.assertIn('OPENGEUL_SUITE_RUN_MODE: acceptance',candidate)
        self.assertEqual(hashlib.sha256(original_push_prefix(candidate).encode()).hexdigest(),fixture['pushPrefixSha256'])

    def test_push_prefix_oracle_reverses_only_one_reviewed_addition(self):
        source=self.candidate();addition='    - '+BRANCH+'\n'
        expected=json.loads(FIXTURE.read_bytes())['pushPrefixSha256']
        for changed in (source.replace(addition,'',1),source.replace(addition,addition*2,1),
                source.replace(addition,addition+'    - foreign\n',1),source.replace('name: OpenGeul','name: Changed',1)):
            self.assertNotEqual(changed,source)
            try:accepted=hashlib.sha256(original_push_prefix(changed).encode()).hexdigest()==expected
            except ValueError:accepted=False
            self.assertFalse(accepted)

    def test_actual_job_preselector_never_grants_request_authority(self):
        import yaml
        job=yaml.safe_load(self.candidate())['jobs']['writer-server-observer'];expression=job['if']
        # Interpret the actual closed expression with synthetic values, without
        # executing a GitHub runner or treating the prefix as source admission.
        fields={'github.event.repository.private':False,'github.ref':'refs/heads/'+BRANCH,
            'github.repository':'ATLKR/OpenGeul','github.repository_owner':'ATLKR','github.actor':'ATLKR',
            'github.actor_id':'65988341','github.triggering_actor':'ATLKR','github.run_attempt':1,
            'github.event_name':'push','inputs.writer_server_observer':False,'github.event.head_commit.message':MARKER}
        def selected(changes):
            values={**fields,**changes};text=expression
            for key in sorted(values,key=len,reverse=True):text=text.replace(key,repr(values[key]))
            text=text.replace('&&',' and ').replace('||',' or ').replace('false','False').replace('true','True')
            return eval(text,{'__builtins__':{},'startsWith':lambda value,prefix:value.startswith(prefix)})
        self.assertTrue(selected({}));self.assertFalse(selected({'github.event.head_commit.message':'Reviewed parent'}))
        self.assertTrue(selected({'github.event.head_commit.message':MARKER+' spoof'}))
        self.assertTrue(selected({'github.event_name':'workflow_dispatch','inputs.writer_server_observer':True}))
        self.assertFalse(selected({'github.event_name':'workflow_dispatch'}))
        for changes in ({'github.ref':'refs/heads/main'},{'github.run_attempt':2},{'github.actor':'foreign'},
                {'github.event.repository.private':True},{'github.event_name':'pull_request'}):self.assertFalse(selected(changes))
        steps=job['steps'];observe=next(s for s in steps if s.get('id')=='writer-observe')
        self.assertEqual(observe['env']['WRITER_OBSERVER_PHASE_SECONDS'],'${{ steps.writer-context.outputs.phase_seconds }}')
        checkout=next(s for s in steps if s.get('uses','').startswith('actions/checkout@'))
        self.assertEqual(checkout['with']['fetch-depth'],2);self.assertFalse(checkout['with']['persist-credentials'])

    def test_manual_job_is_exact_owner_branch_attempt_and_runner(self):
        job=self.candidate().split('\n  writer-server-observer:',1)[1]
        for fragment in ("github.event_name == 'workflow_dispatch'", "github.ref == 'refs/heads/"+BRANCH+"'",
            "github.repository == 'ATLKR/OpenGeul'", "github.actor == 'ATLKR'", "github.actor_id == '65988341'",
            "github.run_attempt == 1",'inputs.writer_server_observer == true','runs-on: windows-11-arm'):
            self.assertIn(fragment,job)
        self.assertNotIn('permissions:',job)
        self.assertNotIn('workflow_dispatch:',job)

    def test_request_push_keeps_manual_route_and_uses_admitted_phase(self):
        source=self.candidate();job=source.split('\n  writer-server-observer:',1)[1]
        prefix=source.split('  workflow_dispatch:',1)[0]
        self.assertEqual(prefix.count('    - '+BRANCH+'\n'),1)
        self.assertIn("github.event_name == 'push'",job)
        self.assertIn("startsWith(github.event.head_commit.message, '"+MARKER+"')",job)
        self.assertIn('fetch-depth: 2',job)
        self.assertIn('WRITER_OBSERVER_PHASE_SECONDS: ${{ steps.writer-context.outputs.phase_seconds }}',job)
        for forbidden in ('.added','.modified','.removed'):self.assertNotIn(forbidden,job)
        self.assertIn('inputs.writer_server_observer == true',job)
        self.assertIn("github.event_name == 'workflow_dispatch'",job)

    def test_producer_ref_cannot_be_the_suite_authority_or_normal_job_exclusion(self):
        self.assertNotEqual(BRANCH,PRODUCER_BRANCH)
        m=module();values=context()
        values.update(GITHUB_REF='refs/heads/'+PRODUCER_BRANCH,
            GITHUB_WORKFLOW_REF='ATLKR/OpenGeul/.github/workflows/office-suite.yml@refs/heads/'+PRODUCER_BRANCH)
        with self.assertRaises(m.Rejected):m.require_context(values,event())
        normal=self.candidate().split('jobs:\n',1)[1].split('\n  writer-server-observer:',1)[0]
        self.assertIn("github.ref != 'refs/heads/"+BRANCH+"'",normal)
        self.assertNotIn("github.ref != 'refs/heads/"+PRODUCER_BRANCH+"'",normal)

    def test_actual_order_and_original_entry_guards_are_preserved(self):
        job=self.candidate().split('\n  writer-server-observer:',1)[1]
        ordered=['id: writer-context','id: normal-engine','id: normal-build','id: normal-verify',
            'id: writer-fetch','id: writer-stage','id: atomic-prepare','id: writer-observe','id: writer-report','id: writer-upload','id: writer-terminal']
        self.assertEqual([job.index(x) for x in ordered],sorted(job.index(x) for x in ordered))
        for required in ('fetch-source-engine.ps1','runtime.arm64.lock.json','build-suite.ps1','verify-suite.py',
            'fetch-writer-server-observer.ps1','stage-writer-server-observer.py','writer_server_observer_phase.py',
            '--artifact','--diagnostic-lock','--source-lock','--prepared-library'):
            self.assertIn(required,job)
        for forbidden in ('windows_smoke.py','launch_suite','taskkill','Remove-Item','fullEngineQualified = $true','acceptanceEligible = $true'):
            self.assertNotIn(forbidden,job)
        self.assertEqual(job.count('--source-lock suite/config/writer-server-observer-9dea/source-lock.json'),1)
        self.assertEqual(job.count("--source-lock ([IO.Path]::GetFullPath('suite/config/writer-server-observer-9dea/source-lock.json'))"),1)
        self.assertNotIn('suite/engine-build/writer-server-observer-diagnostic/source-lock.json',job)
        phase=(BASE/'suite/e2e/writer_server_observer_phase.py').read_text()
        self.assertIn('from writer_server_observer_runner import main',phase)
        self.assertIn('return main(arguments[1:])',phase)

    def test_upload_has_explicit_numeric_paths_and_terminal_always_fails(self):
        job=self.candidate().split('\n  writer-server-observer:',1)[1]
        upload=job.split('id: writer-upload',1)[1].split('    - name:',1)[0]
        self.assertIn('.work/writer-observer-public/context.numeric.json',upload)
        self.assertIn('.work/writer-observer-public/report.numeric.json',upload)
        for forbidden in ('*','private/','stdout','stderr','.zip','screenshot','environment'):
            self.assertNotIn(forbidden,upload)
        terminal=job.split('id: writer-terminal',1)[1]
        self.assertIn('if: always()',terminal);self.assertIn("throw 'Writer observation is diagnostic only",terminal)

    def test_candidate_adds_no_production_pin_or_native_source_workflow(self):
        job=self.candidate().split('\n  writer-server-observer:',1)[1]
        self.assertIn('suite/config/writer-server-observer.arm64.lock.json',job)
        self.assertNotRegex(job,r'artifactId\s*[:=]\s*[0-9]')
        self.assertNotRegex(job,r'artifactSha256\s*[:=]')

    def test_workflow_contract_remains_valid_when_native_source_workflow_exists_in_repository(self):
        global BASE
        saved=BASE
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.github/workflows').mkdir(parents=True)
            (root/'.github/workflows/office-native-engine.yml').write_text('# synthetic existing native workflow')
            try:
                BASE=root
                self.test_candidate_adds_no_production_pin_or_native_source_workflow()
            finally:BASE=saved

    def test_exact_context_accepts_and_every_authority_field_rejects_mismatch(self):
        m=module();self.assertTrue(m.require_context(context(),event()))
        for key in context():
            with self.subTest(field=key):
                changed=context();changed[key]='wrong'
                with self.assertRaises(m.Rejected):m.require_context(changed,event())
        for changed in ({'repository':{'full_name':'ATLKR/OpenGeul','id':1405493151,'private':True},'sender':event()['sender']},
                        {'repository':event()['repository'],'sender':{'login':'ATLKR','id':1,'type':'User'}}):
            with self.assertRaises(m.Rejected):m.require_context(context(),changed)

    def test_source_blob_verifier_detects_changed_source_and_link_alias(self):
        m=module()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'tracked.py';path.write_bytes(b'fixed source\n')
            digest=hashlib.sha1(b'blob 13\0fixed source\n').hexdigest()
            rows=('100644 blob '+digest+'\ttracked.py\0').encode()
            self.assertEqual(m.verify_tracked_rows(root,rows,check=lambda:None),1)
            path.write_bytes(b'other source\n')
            with self.assertRaises(m.Rejected):m.verify_tracked_rows(root,rows,check=lambda:None)
            path.unlink();target=root/'other';target.write_bytes(b'fixed source\n');path.symlink_to(target)
            with self.assertRaises(m.Rejected):m.verify_tracked_rows(root,rows,check=lambda:None)

    def test_numeric_report_validator_never_accepts_private_field_or_acceptance(self):
        m=module();sys.path.insert(0,str(BASE/'suite/e2e'))
        self.assertTrue((BASE/'suite/e2e/writer_server_observer_runner.py').is_file())
        import writer_server_observer_runner as r
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.json';value=r.empty_report();path.write_text(json.dumps(value))
            self.assertTrue(m.require_report(path))
            for key,bad in (('privatePath','SYNTHETIC_SECRET'),('normalAcceptance',True)):
                wrong=dict(value);wrong[key]=bad;path.write_text(json.dumps(wrong))
                with self.assertRaises(m.Rejected):m.require_report(path)


if __name__=='__main__':unittest.main()
