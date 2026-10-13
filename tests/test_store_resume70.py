import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import store_resume70 as resume
import store_submit as submitter
import test_store_submit as fixture


class ResumeAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.run = {'id':int(resume.RUN),'head_sha':resume.HEAD,'run_attempt':1,
            'event':'workflow_dispatch','head_branch':'main','path':'.github/workflows/store-package.yml',
            'repository':{'full_name':'ATLKR/OpenGeul','private':False},'status':'completed','conclusion':'failure',
            'actor':{'login':'ATLKR','type':'User'},'triggering_actor':{'login':'ATLKR','type':'User'}}
        self.jobs = {'total_count':7,'jobs':[{'id':job_id,'name':name,'run_id':int(resume.RUN),
            'run_attempt':1,'head_sha':resume.HEAD,'status':'completed',
            'conclusion':'failure' if name=='submit' else 'success'} for name,job_id in resume.GATES.items()]}
        self.artifact = {'id':resume.ARTIFACT,'name':'opengeul-store-qualified-'+resume.RUN,
            'size_in_bytes':resume.ZIP_SIZE,'digest':'sha256:'+resume.ZIP_SHA,'expired':False,
            'workflow_run':{'id':int(resume.RUN),'head_sha':resume.HEAD}}
        self.backend = type('Backend',(),{'get':lambda _,path:self.get(path)})()

    def get(self,path):
        if path=='actions/runs/'+resume.RUN:return copy.deepcopy(self.run)
        if '/attempts/1/jobs' in path:return copy.deepcopy(self.jobs)
        if path=='actions/artifacts/'+str(resume.ARTIFACT):return copy.deepcopy(self.artifact)
        return copy.deepcopy(self.caller_run)

    def test_actual_failed_producer_all_six_gates_and_artifact_are_bound(self):
        self.assertIs(resume.origin(self.backend),self.backend)
        for name in resume.GATES:
            for mutation in ('conclusion','run_attempt','head_sha','id'):
                with self.subTest(name=name,mutation=mutation):
                    original=copy.deepcopy(self.jobs)
                    row=next(j for j in self.jobs['jobs'] if j['name']==name)
                    row[mutation]={'conclusion':'canceled','run_attempt':2,'head_sha':'f'*40,'id':1}[mutation]
                    with self.assertRaises(submitter.SubmissionBlocked):resume.origin(self.backend)
                    self.jobs=original

    def test_expired_wrong_digest_wrong_source_and_duplicate_jobs_fail_closed(self):
        for key,value in [('expired',True),('digest','sha256:'+'a'*64),('size_in_bytes',True)]:
            original=copy.deepcopy(self.artifact);self.artifact[key]=value
            with self.assertRaises(submitter.SubmissionBlocked):resume.origin(self.backend)
            self.artifact=original
        self.jobs['jobs'].append(copy.deepcopy(self.jobs['jobs'][0]));self.jobs['total_count']+=1
        with self.assertRaises(submitter.SubmissionBlocked):resume.origin(self.backend)

    def test_caller_is_separate_fixed_branch_without_env_spoof(self):
        env={'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_REF':'refs/heads/'+resume.BRANCH,
            'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_JOB':'resume-store70','GITHUB_ACTIONS':'true',
            'RUNNER_ENVIRONMENT':'github-hosted','GITHUB_ACTOR':'ATLKR','GITHUB_TRIGGERING_ACTOR':'ATLKR',
            'GITHUB_RUN_ID':'38399999999','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'e'*40}
        self.caller_run=copy.deepcopy(self.run)
        self.caller_run.update(id=int(env['GITHUB_RUN_ID']),head_sha=env['GITHUB_SHA'],head_branch=resume.BRANCH,status='in_progress',conclusion=None)
        with patch.dict(os.environ,env,clear=True):
            before=dict(os.environ);resume.caller(self.backend);self.assertEqual(dict(os.environ),before)
            for key,value in [('GITHUB_REF','refs/heads/main'),('GITHUB_RUN_ID',resume.RUN),
                              ('GITHUB_RUN_ATTEMPT','2'),('GITHUB_TRIGGERING_ACTOR','outsider')]:
                with patch.dict(os.environ,{key:value}):
                    with self.assertRaises(submitter.SubmissionBlocked):resume.caller(self.backend)

    def test_only_owned_sid_routes_and_one_each_mutation_are_possible(self):
        seen=set()
        for method,path in [('DELETE','submissions/'+resume.SID),('POST','submissions'),
                            ('PUT','submissions/'+resume.BASELINE),('GET','submissions/1')]:
            with self.assertRaises(submitter.SubmissionBlocked):resume.api_guard(method,path,seen)
        for method,path in [('PUT','submissions/'+resume.SID),('POST','submissions/'+resume.SID+'/commit')]:
            resume.api_guard(method,path,seen)
            with self.assertRaises(submitter.SubmissionBlocked):resume.api_guard(method,path,seen)


class ResumeTransactionTests(unittest.TestCase):
    historical=False
    checksums=fixture.DualStoreSubmitTests.checksums
    write_details=fixture.DualStoreSubmitTests.write_details
    change_packages=fixture.DualStoreSubmitTests.change_packages
    github=fixture.DualStoreSubmitTests.github
    upload=fixture.DualStoreSubmitTests.upload
    setUp=fixture.DualStoreSubmitTests.setUp

    def start_resume(self):
        self.baseline['id']=resume.BASELINE
        self.app['lastPublishedApplicationSubmission']={'id':resume.BASELINE}
        self.app['pendingApplicationSubmission']={'id':resume.SID}
        self.new={**copy.deepcopy(self.baseline),'id':resume.SID,'status':'PendingCommit',
                  'fileUploadUrl':'https://storetest.blob.core.windows.net/ingestion/id?sig=FIXTURE'}
        journal=submitter._journal();submitter._save(journal,'draft_ready',self.details,submission_id=resume.SID)
        body=io.BytesIO()
        with zipfile.ZipFile(body,'w',zipfile.ZIP_STORED) as archive:
            for entry in self.details['architectures'].values():archive.writestr(entry['package'],(self.directory/entry['package']).read_bytes())
        self.verifier=patch.object(submitter,'_verify',return_value=(self.details,(1,1,3),body.getvalue()))
        self.verifier.start();self.addCleanup(self.verifier.stop)
        self.calls.clear();self.inject_after_upload=False

    def store(self,opener,token,method,path,data=None):
        self.calls.append(('operator',method,path))
        if self.inject_after_upload and method=='GET' and path=='' and any(c[:2]==('store','UPLOAD') for c in self.calls):
            raise submitter.StoreError('GET',None)
        return fixture.DualStoreSubmitTests.store(self,opener,token,method,
            path.replace(resume.SID,'30').replace(resume.BASELINE,'10'),data)

    def invoke(self):return submitter.submit(self.tag,self.directory,resume=True)

    def test_real_shared_verifier_resume_zip_is_time_independent_and_env_unchanged(self):
        context={'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_SHA':'b'*40,
                 'GITHUB_RUN_ID':'456','GITHUB_RUN_ATTEMPT':'2'}
        before=dict(os.environ)
        with patch.object(resume,'caller'), patch.object(resume,'producer',return_value=context):
            with patch.object(zipfile.time,'localtime',return_value=(2020,1,1,0,0,0,0,0,0)):
                first=submitter._verify(self.tag,self.directory,resume=True)[2]
            with patch.object(zipfile.time,'localtime',return_value=(2026,10,13,10,59,58,0,0,0)):
                second=submitter._verify(self.tag,self.directory,resume=True)[2]
        self.assertEqual(hashlib.sha256(first).digest(),hashlib.sha256(second).digest())
        self.assertEqual(dict(os.environ),before)
        self.assertEqual(self.inspect_mock.call_args.args[2],context)
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertTrue(all(e.date_time==(1980,1,1,0,0,0) and e.compress_type==zipfile.ZIP_STORED for e in archive.infolist()))
            for entry in self.details['architectures'].values():
                self.assertEqual(archive.read(entry['package']),(self.directory/entry['package']).read_bytes())

    def test_same_sid_pair_upload_and_commit_once_no_recreate(self):
        self.start_resume();self.assertEqual(self.invoke()['outcome'],'requested')
        self.assertEqual(sum(c==('store','UPLOAD','blob') for c in self.calls),1)
        self.assertEqual(sum(c==('operator','POST','submissions/'+resume.SID+'/commit') for c in self.calls),1)
        self.assertFalse(any(c[:2]==('operator','DELETE') or c==('operator','POST','submissions') for c in self.calls))

    def test_upload_uncertain_preserves_intent_and_never_repeats(self):
        self.start_resume();self.upload_mode='timeout'
        with self.assertRaises(submitter.SubmissionBlocked):self.invoke()
        self.assertEqual(submitter._journal()['state']['resume_upload_state'],'attempted')
        before=list(self.calls)
        with self.assertRaises(submitter.SubmissionBlocked):self.invoke()
        self.assertFalse(any(c[0]=='operator' for c in self.calls[len(before):]))
        self.assertEqual(sum(c==('store','UPLOAD','blob') for c in self.calls),1)

    def test_acknowledged_upload_resume_skips_put_and_upload_then_commits_once(self):
        self.start_resume();self.inject_after_upload=True
        with self.assertRaises(submitter.SubmissionBlocked):self.invoke()
        self.assertEqual(submitter._journal()['state']['resume_upload_state'],'acknowledged')
        self.inject_after_upload=False;self.assertEqual(self.invoke()['outcome'],'requested')
        self.assertEqual(sum(c==('operator','PUT','submissions/'+resume.SID) for c in self.calls),1)
        self.assertEqual(sum(c==('store','UPLOAD','blob') for c in self.calls),1)

    def test_unknown_commit_resumes_get_only_without_second_post(self):
        self.start_resume();self.commit_mode='unknown'
        with self.assertRaises(submitter.SubmissionBlocked):self.invoke()
        self.assertEqual(submitter._journal()['state']['phase'],'commit_attempted')
        self.new['status']='Certification';self.assertEqual(self.invoke()['outcome'],'already_requested')
        self.assertEqual(sum(c==('operator','POST','submissions/'+resume.SID+'/commit') for c in self.calls),1)

    def test_wrong_journal_sid_or_pair_never_reaches_store(self):
        for change in ('sid','pair'):
            with self.subTest(change=change):
                self.start_resume();journal=submitter._journal()
                if change=='sid':submitter._save(journal,'draft_ready',submission_id='1')
                else:submitter._save(journal,'draft_ready',store_msix_sha256_by_arch={'x64':'0'*64,'arm64':'1'*64})
                with self.assertRaises(submitter.SubmissionBlocked):self.invoke()
                self.assertFalse(any(c[0]=='operator' for c in self.calls))


if __name__=='__main__':unittest.main()
