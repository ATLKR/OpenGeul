"""Static workflow preservation and synthetic admission/report regressions."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import ast

BASE=Path(__file__).resolve().parents[2]
CANDIDATE=BASE/'.github/workflows/office-suite.yml'
BRANCH='work/opengeul-office-native-writer-observer'
FIXTURE=BASE/'suite/tests/fixtures/writer-server-observer-normal-workflow.json'
FIXTURE_SHA256='191eb38642ecdc5d885815cea9567c70cdd49c7950d325403e143db113b62e2c'


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
        self.assertEqual(hashlib.sha256(candidate.split('  workflow_dispatch:',1)[0].encode()).hexdigest(),fixture['pushPrefixSha256'])

    def test_manual_job_is_exact_owner_branch_attempt_and_runner(self):
        job=self.candidate().split('\n  writer-server-observer:',1)[1]
        for fragment in ("github.event_name == 'workflow_dispatch'", "github.ref == 'refs/heads/"+BRANCH+"'",
            "github.repository == 'ATLKR/OpenGeul'", "github.actor == 'ATLKR'", "github.actor_id == '65988341'",
            "github.run_attempt == 1",'inputs.writer_server_observer == true','runs-on: windows-11-arm'):
            self.assertIn(fragment,job)
        self.assertNotIn('permissions:',job)
        self.assertNotIn('workflow_dispatch:',job)

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
