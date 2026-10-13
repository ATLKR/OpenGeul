"""Dashboard reconciliation updates one journal without Store mutations."""
import copy, importlib, importlib.util, io, json, os, sys, tempfile, unittest, urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import store_submit as w

class Response(io.BytesIO):
    status=200

class Opener:
    def __init__(self,values):self.values=values;self.calls=[]
    def open(self,request,timeout):
        self.calls.append(request);value=self.values[len(self.calls)-1]
        if isinstance(value,Exception):raise value
        return Response(value if isinstance(value,bytes)else json.dumps(value).encode())

class Tests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('store_owner_delete_reconcile'),'The external-deletion reconciliation is missing')
        self.d=importlib.import_module('store_owner_delete_reconcile')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.directory=Path(self.temp.name)/'evidence'
        self.old=copy.deepcopy(self.d.EXPECTED)
        self.issue={'number':20,'id':5819766913,'title':w.TITLE,'state':'open','body':w._journal_body(self.old),
                    'user':{'login':'github-actions[bot]','type':'Bot','id':41898282}}
        self.app={'id':w.STORE_APP_ID,'packageIdentityName':w.STORE_IDENTITY['name'],
                  'pendingApplicationSubmission':None,'lastPublishedApplicationSubmission':{'id':self.d.PUBLISHED}}
        self.baseline={'id':self.d.PUBLISHED,'status':'Published','targetPublishMode':'Manual',
            'pricing':{'priceId':'Free','marketSpecificPricings':{'KR':'Base'}},'packageDeliveryOptions':{'isMandatoryUpdate':False},
            'fileUploadUrl':None,'applicationPackages':[{'version':'1.1.1.0','architecture':'X64','fileStatus':'Uploaded'}],
            'listings':{'private':'PRIVATE_LISTING'}}
        self.hashpatch=patch.object(self.d,'SEMANTIC_SHA',w.draft_semantic_sha256(self.baseline));self.hashpatch.start();self.addCleanup(self.hashpatch.stop)
        self.calls=[];self.patch_error=None
    def missing(self,status=404):return urllib.error.HTTPError('https://private/?sig=SECRET',status,'PRIVATE_REASON',{},io.BytesIO(b'PRIVATE_ERROR_BODY'))
    def values(self):return [value for _ in range(2)for value in(copy.deepcopy(self.app),self.missing(),copy.deepcopy(self.baseline))]
    def gh(self,method,path,data=None):
        self.calls.append((method,path))
        self.assertEqual(path,self.d.ISSUE)
        if method=='PATCH':
            self.assertTrue((self.directory/'external-delete-observation.json').is_file())
            if self.patch_error:raise self.patch_error
            self.issue.update(data)
        else:self.assertEqual(method,'GET')
        return copy.deepcopy(self.issue)
    def run_reconcile(self,values=None):
        o=Opener(self.values()if values is None else values)
        return o,self.d.reconcile(o,'OAUTH_SECRET',self.gh,self.directory)
    def test_exact_six_store_gets_and_one_journal_patch_preserve_full_claim(self):
        o,r=self.run_reconcile()
        self.assertEqual([q.get_method()for q in o.calls],['GET']*6)
        self.assertEqual([q.full_url for q in o.calls],[w.BASE,w.BASE+'/submissions/'+self.d.PENDING,w.BASE+'/submissions/'+self.d.PUBLISHED]*2)
        self.assertEqual(self.calls,[('GET',self.d.ISSUE),('GET',self.d.ISSUE),('PATCH',self.d.ISSUE),('GET',self.d.ISSUE)])
        self.assertTrue(r['journalUpdateAcknowledged']);new=w._journal_state(self.issue['body']);history=new['externally_deleted_clone']
        self.assertEqual(history['prior_journal'],self.old);self.assertIs(history['api_deletion_acknowledged'],False)
        self.assertTrue(history['owner_confirmed_dashboard_deletion']);self.assertEqual(new['phase'],'delete_confirmed');self.assertIsNone(new['submission_id'])
        self.assertFalse(any(k.startswith(('adopted_','adoption_'))for k in new));self.assertNotIn('recovered_clone',new)
        self.assertNotIn('PRIVATE_LISTING',json.dumps(r));self.assertNotIn('PRIVATE_ERROR_BODY',json.dumps(r))
    def test_any_pending_or_wrong_baseline_reference_prevents_patch(self):
        for field,value in [('pendingApplicationSubmission',{'id':self.d.PENDING}),('lastPublishedApplicationSubmission',{'id':'123'})]:
            self.directory=Path(self.temp.name)/field;values=self.values();values[0][field]=value
            _,r=self.run_reconcile(values);self.assertFalse(r['journalPatchAttempted']);self.assertFalse(any(m=='PATCH'for m,p in self.calls))
    def test_omitted_pending_property_reconciles_with_bounded_reference_schema(self):
        self.app.pop('pendingApplicationSubmission')
        o,r=self.run_reconcile()
        self.assertTrue(r['journalUpdateAcknowledged'])
        self.assertEqual([q.get_method()for q in o.calls],['GET']*6)
        self.assertEqual(len(r['applicationReferenceSchema']),2)
        for schema in r['applicationReferenceSchema']:
            self.assertEqual(schema['pending'],{'propertyPresent':False,'shape':'omitted','referenceId':None,'referenceValid':True})
            self.assertEqual(schema['published']['referenceId'],self.d.PUBLISHED)
        self.assertNotIn('PRIVATE_LISTING',json.dumps(r));self.assertNotIn('https://',json.dumps(r))
    def test_malformed_or_nonnull_pending_never_reaches_journal_patch(self):
        for index,value in enumerate(({},[],False,'PRIVATE_BAD_REFERENCE',{'id':'123'},{'id':None},{'id':True})):
            self.directory=Path(self.temp.name)/('malformed-'+str(index));values=self.values();values[0]['pendingApplicationSubmission']=value
            o,r=self.run_reconcile(values)
            self.assertEqual(len(o.calls),1);self.assertFalse(r['journalPatchAttempted'])
    def test_old_sid_still_readable_or_403_prevents_patch(self):
        for index,value in enumerate(({'id':self.d.PENDING},self.missing(403))):
            self.directory=Path(self.temp.name)/str(index);values=self.values();values[1]=value
            _,r=self.run_reconcile(values);self.assertFalse(r['journalPatchAttempted'])
    def test_changed_baseline_or_upload_url_prevents_patch(self):
        for field,value in [('listings',{'private':'CHANGED'}),('fileUploadUrl','https://private/?sig=SECRET'),('packageDeliveryOptions',{})]:
            self.directory=Path(self.temp.name)/field;values=self.values();values[2][field]=value
            _,r=self.run_reconcile(values);self.assertFalse(r['journalPatchAttempted'])
    def test_journal_phase_owner_or_claim_change_prevents_store_gets(self):
        for index in range(3):
            self.directory=Path(self.temp.name)/str(index);self.issue['body']=w._journal_body(self.old)
            if index==0:self.issue['body']=w._journal_body({**self.old,'phase':'draft_ready'})
            if index==1:self.issue['user']['login']='OTHER'
            if index==2:self.issue['body']=w._journal_body({**self.old,'source_sha':'0'*40});self.issue['user']['login']='github-actions[bot]'
            o,r=self.run_reconcile();self.assertEqual(o.calls,[]);self.assertFalse(r['journalPatchAttempted'])
    def test_duplicate_or_malformed_json_prevents_patch(self):
        for index,raw in enumerate((b'{"id":"a","id":"b"}',b'{',b'{"x":NaN}')):
            self.directory=Path(self.temp.name)/str(index);o,r=self.run_reconcile([raw]);self.assertEqual(len(o.calls),1);self.assertFalse(r['journalPatchAttempted'])
    def test_second_store_observation_change_prevents_patch(self):
        values=self.values();values[3]['pendingApplicationSubmission']={'id':'123'}
        _,r=self.run_reconcile(values);self.assertFalse(r['journalPatchAttempted'])
    def test_journal_cas_change_prevents_patch(self):
        original=self.gh
        def gh(method,path,data=None):
            if len(self.calls)==1:self.issue['body']=w._journal_body({**self.old,'deleted_id':'123'})
            return original(method,path,data)
        o=Opener(self.values());r=self.d.reconcile(o,'OAUTH_SECRET',gh,self.directory);self.assertFalse(r['journalPatchAttempted'])
    def test_unknown_patch_outcome_halts_without_retry(self):
        self.patch_error=TimeoutError('PRIVATE_ERROR');_,r=self.run_reconcile()
        self.assertTrue(r['journalPatchAttempted']);self.assertFalse(r['journalUpdateAcknowledged'])
        self.assertEqual(self.calls,[('GET',self.d.ISSUE),('GET',self.d.ISSUE),('PATCH',self.d.ISSUE)])
    def test_history_survives_normal_save_and_pair_replacement(self):
        self.run_reconcile();new=w._journal_state(self.issue['body']);history=copy.deepcopy(new['externally_deleted_clone'])
        journal={'number':'20','state':new};details={'formatVersion':2,'version':'1.1.3','sourceReleaseId':'88','sourceRunId':'99','sourceCommit':'2'*40,
            'sourceAssetFingerprintSha256':'3'*64,'architectures':{'x64':{'sourceMsixSha256':'4'*64,'sha256':'5'*64},'arm64':{'sourceMsixSha256':'6'*64,'sha256':'7'*64}}}
        def gh(method,path,data=None,**kwargs):
            if method=='PATCH':self.issue.update(data)
            return copy.deepcopy(self.issue)
        with patch.object(w,'_gh',gh):w._save(journal,'create_attempted',details,submission_id=None)
        self.assertEqual(journal['state']['externally_deleted_clone'],history);self.assertEqual(journal['state']['source_asset_fingerprint_sha256'],'3'*64)
    def test_same_head_second_dispatch_or_rerun_refuses_scope(self):
        run={'id':123,'head_sha':'1'*40,'head_branch':self.d.REF.removeprefix('refs/heads/'),'event':'workflow_dispatch',
             'path':'.github/workflows/store-package.yml','run_attempt':1,'actor':{'login':'ATLKR','type':'User','id':65988341},
             'triggering_actor':{'login':'ATLKR','type':'User','id':65988341}}
        env={'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_REF':self.d.REF,'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_ACTOR':'ATLKR',
             'GITHUB_TRIGGERING_ACTOR':'ATLKR','GITHUB_JOB':'reconcile','GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':'123','GITHUB_SHA':'1'*40,
             'GITHUB_WORKFLOW_REF':'ATLKR/OpenGeul/.github/workflows/store-package.yml@'+self.d.REF,'CONFIRM_OWNER_DELETED_PENDING_ID':self.d.PENDING}
        with patch.dict(os.environ,env,clear=True):
            self.d.scope({'total_count':1,'workflow_runs':[run]})
            with self.assertRaises(ValueError):self.d.scope({'total_count':2,'workflow_runs':[run,{**run,'id':124}]})
        with patch.dict(os.environ,{**env,'GITHUB_RUN_ATTEMPT':'2'},clear=True):
            with self.assertRaises(ValueError):self.d.scope({'total_count':1,'workflow_runs':[run]})

if __name__=='__main__':unittest.main()
